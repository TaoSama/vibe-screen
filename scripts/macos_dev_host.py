#!/usr/bin/env python3
"""Build, install, and preflight the local macOS development Host bundle."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import multiprocessing
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import package_macos


APP_NAME = package_macos.PRODUCT_NAME
EXECUTABLE_NAME = package_macos.EXECUTABLE_NAME
DEFAULT_INSTALL_PATH = Path("/Applications") / f"{APP_NAME}.app"
DEFAULT_OUTPUT_DIR = package_macos.REPOSITORY_ROOT / ".build" / "dev-macos-host"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "host-signing-and-permissions.txt"
DEFAULT_XCTEST_PREFLIGHT_JSON = DEFAULT_OUTPUT_DIR / "xctest-preflight.json"
DEFAULT_XCTEST_PREFLIGHT_REPORT = DEFAULT_OUTPUT_DIR / "xctest-toolchain.txt"
SYSTEM_TCC_DATABASE = Path("/Library/Application Support/com.apple.TCC/TCC.db")
USER_TCC_DATABASE_LABEL = "<user-tcc-db>"
SYSTEM_TCC_DATABASE_LABEL = "<system-tcc-db>"
EXPECTED_BUNDLE_ID = "dev.telemachus.display"
SCREEN_CAPTURE_SERVICES = ("kTCCServiceScreenCapture", "kTCCServiceScreenRecording")
ACCESSIBILITY_SERVICE = "kTCCServiceAccessibility"
ALLOWED_AUTH_VALUE = 2
DEFAULT_LISTENER_PORT = 54321
VIRTUAL_HID_ENTITLEMENT = "com.apple.developer.hid.virtual.device"
SYSTEM_SETTINGS_PATH = (
    "System Settings -> Privacy & Security -> Screen & System Audio Recording "
    "and Accessibility"
)
LOGIN_ITEM_DIAGNOSTIC_OPT_IN_DETAIL = (
    "Login item not probed by default; probe not run. Use an attended "
    "diagnostic session outside default readiness to inspect login-item state."
)

@dataclass(frozen=True)
class SigningMetadata:
    app_path: Path
    identifier: str
    source_commit: str | None
    source_tree: str | None
    source_dirty: bool | None
    binary_sha256: str
    authorities: tuple[str, ...]
    cdhash: str | None
    designated_requirement: str | None
    signature: str | None
    team_identifier: str | None
    leaf_certificate_hash: str | None

    @property
    def identity_name(self) -> str:
        return self.authorities[0] if self.authorities else "ad-hoc"

    @property
    def is_ad_hoc(self) -> bool:
        return not self.authorities or self.signature == "adhoc"


@dataclass(frozen=True)
class TCCRow:
    service: str
    client: str
    client_type: int
    auth_value: int | None
    auth_reason: int | None
    last_modified: int | None


@dataclass(frozen=True)
class PermissionStatus:
    database_path: str | Path
    rows: tuple[TCCRow, ...]
    readable: bool
    error: str | None = None

    def is_allowed(self, services: tuple[str, ...]) -> bool:
        return any(row.service in services and row.auth_value == ALLOWED_AUTH_VALUE for row in self.rows)


@dataclass(frozen=True)
class HostInspection:
    metadata: SigningMetadata | None
    source_identity: package_macos.SourceIdentity | None
    permissions: PermissionStatus
    errors: list[str]


@dataclass(frozen=True)
class XCTestPreflightStatus:
    developer_dir: str | None
    developer_dir_kind: str
    xcode_version: str | None
    xcode_build: str | None
    sdk_path: str | None
    has_xctest: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ListenerStatus:
    port: int
    observed: bool
    output: str
    error: str | None = None


@dataclass(frozen=True)
class EntitlementStatus:
    app_path: Path
    virtual_hid: bool
    keys: tuple[str, ...]
    raw_output: str
    error: str | None = None


def default_tcc_database() -> Path:
    return Path.home() / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db"


def tcc_database_paths(database_path: Path) -> tuple[Path, ...]:
    default_database = default_tcc_database().resolve()
    resolved = database_path.resolve()
    return (resolved, SYSTEM_TCC_DATABASE) if resolved == default_database else (resolved,)


def tcc_database_report_label(database_path: Path) -> str:
    resolved = database_path.resolve()
    if resolved == default_tcc_database().resolve():
        return USER_TCC_DATABASE_LABEL
    if resolved == SYSTEM_TCC_DATABASE.resolve():
        return SYSTEM_TCC_DATABASE_LABEL
    return str(database_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build/install the local Vibe Screen Host or fail-closed before Android device evidence. The tool never modifies TCC."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="build, sign, and install the stable local development Host bundle")
    add_common_options(install, include_sign_identity=True, include_output_dir=True)
    preflight = subparsers.add_parser("preflight", help="fail closed unless the installed Host is stable-signed and authorized")
    add_common_options(preflight, include_sign_identity=True)
    xctest_preflight = subparsers.add_parser(
        "xctest-preflight",
        help="fail closed unless the selected Apple developer directory can run SwiftPM XCTest",
    )
    xctest_preflight.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_XCTEST_PREFLIGHT_REPORT,
        help="path for the XCTest toolchain report (default: .build/dev-macos-host/xctest-toolchain.txt)",
    )
    xctest_preflight.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help=f"optional JSON report path; when omitted, the text report is written to --report (default JSON path: {DEFAULT_XCTEST_PREFLIGHT_JSON})",
    )
    readiness = subparsers.add_parser(
        "readiness",
        help="write read-only JSON readiness for shared Host signing, TCC, listener, and entitlement prerequisites",
    )
    add_common_options(readiness, include_sign_identity=True)
    readiness.add_argument(
        "--port",
        type=int,
        default=DEFAULT_LISTENER_PORT,
        help="Host TCP listener port to inspect (default: 54321)",
    )
    readiness.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "host-readiness.json",
        help="path for the structured readiness JSON report",
    )
    readiness.add_argument(
        "--probe-login-item",
        "--probe-login-items",
        "--include-login-item-diagnostic",
        "--inspect-login-items",
        dest="probe_login_item",
        action="store_true",
        help=(
            "opt in to the real macOS login-item diagnostic by calling "
            "/usr/bin/sfltool dumpbtm. This may trigger macOS administrator "
            "authorization prompts; default CI/test readiness skips it fail-closed."
        ),
    )
    return parser.parse_args()


def add_common_options(parser: argparse.ArgumentParser, *, include_sign_identity: bool = False, include_output_dir: bool = False) -> None:
    if include_sign_identity:
        sign_default = os.environ.get(package_macos.SIGN_IDENTITY_ENV, package_macos.DEFAULT_SIGN_IDENTITY)
        parser.add_argument(
            "--sign-identity",
            default=sign_default,
            help=(
                f"codesign identity; defaults to ${package_macos.SIGN_IDENTITY_ENV} "
                f"or '{package_macos.DEFAULT_SIGN_IDENTITY}'. '-' is refused for "
                "local device reruns because ad-hoc signatures drift across rebuilds."
            ),
        )
    if include_output_dir:
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=DEFAULT_OUTPUT_DIR,
            help="temporary packaging output directory (default: .build/dev-macos-host)",
        )
    parser.add_argument(
        "--install-path",
        type=Path,
        default=DEFAULT_INSTALL_PATH,
        help="installed Host path to verify (default: /Applications/Vibe Screen.app)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="path for the signing and permission report",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=package_macos.REPOSITORY_ROOT,
        help="repository root whose current clean HEAD the installed Host must match",
    )
    parser.add_argument(
        "--allow-source-mismatch",
        action="store_true",
        help="record source mismatch but do not fail the preflight; use only for historical fixed-binary reruns",
    )
    parser.add_argument("--tcc-db", type=Path, default=default_tcc_database(), help=argparse.SUPPRESS)


def run(*command: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return completed.stdout.strip()


def run_best_effort(*command: str, timeout_seconds: int | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        output = error.stdout if isinstance(error.stdout, str) else ""
        detail = output.strip()
        suffix = f": {detail}" if detail else ""
        return 124, f"command timed out after {timeout_seconds}s{suffix}"
    except FileNotFoundError as error:
        executable = str(error.filename or (command[0] if command else "command"))
        return 127, f"command unavailable: {Path(executable).name}"
    except OSError as error:
        command_name = Path(command[0]).name if command else "command"
        detail = error.strerror or error.__class__.__name__
        return 127, f"{command_name} unavailable: {detail}"
    return completed.returncode, completed.stdout.strip()


def parse_xcodebuild_version(output: str) -> tuple[str | None, str | None]:
    xcode_version: str | None = None
    xcode_build: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Xcode "):
            xcode_version = line.removeprefix("Xcode ").strip() or None
        elif line.startswith("Build version "):
            xcode_build = line.removeprefix("Build version ").strip() or None
    return xcode_version, xcode_build


def developer_dir_kind(developer_dir: Path | None) -> str:
    if developer_dir is None:
        return "unknown"
    text = str(developer_dir)
    if text.endswith(".app/Contents/Developer"):
        return "full_xcode"
    if developer_dir.name == "CommandLineTools" or "/CommandLineTools" in text:
        return "command_line_tools"
    return "unknown"


def has_xctest_framework(developer_dir: Path | None) -> bool:
    if developer_dir is None:
        return False
    candidates = (
        developer_dir / "Platforms" / "MacOSX.platform" / "Developer" / "Library" / "Frameworks" / "XCTest.framework",
        developer_dir / "Library" / "Frameworks" / "XCTest.framework",
    )
    return any(candidate.is_dir() for candidate in candidates)


def inspect_xctest_preflight() -> XCTestPreflightStatus:
    errors: list[str] = []
    developer_dir: Path | None = None
    developer_code, developer_output = run_best_effort("/usr/bin/xcode-select", "-p", timeout_seconds=10)
    if developer_code == 0 and developer_output.strip():
        developer_dir = Path(developer_output.strip())
    else:
        errors.append(f"xcode-select -p failed: {redact_local_report_text(developer_output or 'no developer directory')}")
    kind = developer_dir_kind(developer_dir)
    if kind != "full_xcode":
        errors.append("Full Xcode is required for SwiftPM XCTest; Command Line Tools are insufficient")

    xcode_version: str | None = None
    xcode_build: str | None = None
    xcode_code, xcode_output = run_best_effort("/usr/bin/xcodebuild", "-version", timeout_seconds=10)
    if xcode_code == 0:
        xcode_version, xcode_build = parse_xcodebuild_version(xcode_output)
    else:
        errors.append(f"xcodebuild -version failed: {redact_local_report_text(xcode_output or 'xcodebuild unavailable')}")

    sdk_path: str | None = None
    sdk_code, sdk_output = run_best_effort(
        "/usr/bin/xcrun",
        "--sdk",
        "macosx",
        "--show-sdk-path",
        timeout_seconds=10,
    )
    if sdk_code == 0 and sdk_output.strip():
        sdk_path = redact_local_report_text(sdk_output.strip())
    else:
        errors.append(f"xcrun macosx SDK lookup failed: {redact_local_report_text(sdk_output or 'macOS SDK unavailable')}")

    has_xctest = has_xctest_framework(developer_dir)
    if not has_xctest:
        errors.append("XCTest.framework was not found in the selected developer directory")

    return XCTestPreflightStatus(
        developer_dir=redact_local_report_text(str(developer_dir)) if developer_dir is not None else None,
        developer_dir_kind=kind,
        xcode_version=xcode_version,
        xcode_build=xcode_build,
        sdk_path=sdk_path,
        has_xctest=has_xctest,
        errors=tuple(errors),
    )


def build_xctest_preflight_document(status: XCTestPreflightStatus) -> dict[str, Any]:
    passed = status.developer_dir_kind == "full_xcode" and status.has_xctest and not status.errors
    return {
        "schema_version": "vibescreen.macos-xctest-preflight/v1",
        "kind": "macos_xctest_preflight",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "blocked",
        "can_run_swiftpm_xctest": passed,
        "developer_dir": status.developer_dir,
        "developer_dir_kind": status.developer_dir_kind,
        "is_full_xcode": status.developer_dir_kind == "full_xcode",
        "has_xctest": status.has_xctest,
        "xcode_version": status.xcode_version,
        "xcode_build": status.xcode_build,
        "sdk_path": status.sdk_path,
        "blockers": list(status.errors),
        "safety": {
            "read_only": True,
            "starts_host": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android": False,
        },
    }


TCC_QUERY_TIMEOUT_SECONDS = 5
DEFAULTS_PREFIX = "Telemachus_"
STARTUP_MODES = {"usb", "wireless", "lan"}
DEFAULT_HOST_LOG_PATH = Path.home() / "Library" / "Logs" / "Telemachus" / "telemachus.log"
IPV4_ENDPOINT_RE = re.compile(r"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?::[0-9]{1,5})?(?![0-9.])")


def redact_local_report_text(value: str) -> str:
    redacted = value.replace(str(default_tcc_database()), USER_TCC_DATABASE_LABEL)
    redacted = redacted.replace(str(SYSTEM_TCC_DATABASE), SYSTEM_TCC_DATABASE_LABEL)
    redacted = redacted.replace(str(DEFAULT_HOST_LOG_PATH), "<user-host-log>")
    home = str(Path.home())
    if home != "/":
        redacted = redacted.replace(home, "<user-home>")
    return redacted


def redact_network_endpoints(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            ipaddress.ip_address(match.group(1))
        except ValueError:
            return match.group(0)
        return "<redacted-ipv4>"

    return IPV4_ENDPOINT_RE.sub(replace, value)


def parse_defaults_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        values[key.strip()] = value.strip().rstrip(";")
    return values


def parse_defaults_export(output: str) -> dict[str, object]:
    try:
        value = plistlib.loads(output.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError):
        return parse_defaults_output(output)
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def defaults_bool(value: object | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if not isinstance(value, str):
        return default
    return value.strip().strip('"').lower() in {"1", "true", "yes"}


def defaults_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value.strip().strip('"'))
    except ValueError:
        return None


def defaults_string(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    return value.strip().strip('"')


def read_startup_settings(bundle_id: str = EXPECTED_BUNDLE_ID) -> HostStartupSettings:
    exit_code, output = run_best_effort("/usr/bin/defaults", "export", bundle_id, "-", timeout_seconds=10)
    if exit_code != 0:
        return HostStartupSettings(
            domain=bundle_id,
            readable=False,
            auto_start_streaming_on_launch=True,
            startup_mode="usb",
            has_completed_onboarding=False,
            display_source="currentMain",
            selected_display_uuid=None,
            selected_display_id=None,
            stored_keys=(),
            defaults_used=(
                "autoStartStreamingOnLaunch=True",
                "startupMode=usb",
                "hasCompletedOnboarding=False",
                "displaySource=currentMain",
            ),
            error=redact_local_report_text(output or "defaults domain not found"),
        )
    parsed = parse_defaults_export(output)
    startup_mode = defaults_string(parsed.get(DEFAULTS_PREFIX + "startupMode"))
    connection_mode = defaults_string(parsed.get(DEFAULTS_PREFIX + "connectionMode"))
    if startup_mode not in STARTUP_MODES:
        startup_mode = connection_mode if connection_mode in STARTUP_MODES else "usb"
    display_source = defaults_string(parsed.get(DEFAULTS_PREFIX + "displaySource")) or "currentMain"
    defaults_used = []
    for key, default_value in (
        ("autoStartStreamingOnLaunch", "True"),
        ("startupMode", "usb"),
        ("displaySource", "currentMain"),
    ):
        if DEFAULTS_PREFIX + key not in parsed:
            defaults_used.append(f"{key}={default_value}")
    if DEFAULTS_PREFIX + "hasCompletedOnboarding" not in parsed:
        defaults_used.append("hasCompletedOnboarding=False")
    return HostStartupSettings(
        domain=bundle_id,
        readable=True,
        auto_start_streaming_on_launch=defaults_bool(parsed.get(DEFAULTS_PREFIX + "autoStartStreamingOnLaunch"), True),
        startup_mode=startup_mode,
        has_completed_onboarding=defaults_bool(parsed.get(DEFAULTS_PREFIX + "hasCompletedOnboarding"), False),
        display_source=display_source,
        selected_display_uuid=defaults_string(parsed.get(DEFAULTS_PREFIX + "selectedDisplayUUID")),
        selected_display_id=defaults_int(parsed.get(DEFAULTS_PREFIX + "selectedDisplayID")),
        stored_keys=tuple(sorted(key for key in parsed if key.startswith(DEFAULTS_PREFIX))),
        defaults_used=tuple(defaults_used),
    )


def parse_login_item_state(output: str, bundle_id: str = EXPECTED_BUNDLE_ID) -> LoginItemReadiness:
    lines = output.splitlines()
    matches: list[str] = []
    for index, line in enumerate(lines):
        if bundle_id not in line and APP_NAME not in line:
            continue
        start = max(0, index - 8)
        end = min(len(lines), index + 12)
        matches.append(ascii_report_text("\n".join(lines[start:end])))
    if not matches:
        return LoginItemReadiness(
            state="not_found",
            matched=False,
            detail="No matching login item entry found in sfltool dumpbtm output.",
            evidence=(),
        )
    combined = "\n---\n".join(matches)
    lowered = combined.lower()
    if any(marker in lowered for marker in ("requires approval", "approval required", "not approved", "allowed = 0")):
        return LoginItemReadiness(
            state="requires_approval",
            matched=True,
            detail="Matching login item appears to need user approval; verify in System Settings.",
            evidence=tuple(matches),
        )
    if any(marker in lowered for marker in ("disabled", "not enabled", "state = 0")):
        return LoginItemReadiness(
            state="disabled",
            matched=True,
            detail="Matching login item appears present but disabled.",
            evidence=tuple(matches),
        )
    if any(marker in lowered for marker in ("enabled", "allowed = 1", "state = 1")):
        return LoginItemReadiness(
            state="enabled",
            matched=True,
            detail="Matching login item appears enabled in read-only sfltool output.",
            evidence=tuple(matches),
        )
    return LoginItemReadiness(
        state="present_unknown",
        matched=True,
        detail="Matching login item was found, but the enabled/approval state was not machine-parsable.",
        evidence=tuple(matches),
    )


def read_login_item_readiness() -> LoginItemReadiness:
    exit_code, output = run_best_effort("/usr/bin/sfltool", "dumpbtm", timeout_seconds=15)
    if exit_code != 0:
        return LoginItemReadiness(
            state="unverified",
            matched=False,
            detail=redact_local_report_text(output or "sfltool dumpbtm failed"),
            evidence=(),
        )
    return parse_login_item_state(output)


def skipped_login_item_readiness() -> LoginItemReadiness:
    return LoginItemReadiness(
        state="unverified",
        matched=False,
        detail=LOGIN_ITEM_DIAGNOSTIC_OPT_IN_DETAIL,
        evidence=(),
    )


def read_display_readiness() -> HostDisplayReadiness:
    script = r"""
import CoreGraphics
let maxDisplays: UInt32 = 32
let active = UnsafeMutablePointer<CGDirectDisplayID>.allocate(capacity: Int(maxDisplays))
defer { active.deallocate() }
var count: UInt32 = 0
let error = CGGetActiveDisplayList(maxDisplays, active, &count)
if error != .success {
    print("ERROR:\(error.rawValue)")
    exit(2)
}
for index in 0..<Int(count) {
    let id = active[index]
    let bounds = CGDisplayBounds(id)
    let mode = CGDisplayCopyDisplayMode(id)
    let main = CGDisplayIsMain(id) != 0 ? 1 : 0
    print("id=\(id)|main=\(main)|logical=\(Int(bounds.width))x\(Int(bounds.height))|physical=\(mode?.pixelWidth ?? 0)x\(mode?.pixelHeight ?? 0)")
}
"""
    exit_code, output = run_best_effort("/usr/bin/swift", "-e", script, timeout_seconds=20)
    displays: list[dict[str, object]] = []
    if exit_code == 0:
        for line in output.splitlines():
            fields = dict(part.split("=", 1) for part in line.split("|") if "=" in part)
            if fields:
                fields["source"] = "CoreGraphics"
                displays.append(fields)
        if displays:
            return HostDisplayReadiness(True, len(displays), tuple(displays), active_display_count=len(displays))
    profiler_displays = read_system_profiler_displays()
    if profiler_displays:
        return HostDisplayReadiness(
            True,
            len(profiler_displays),
            tuple(profiler_displays),
            error=None if exit_code == 0 else redact_local_report_text(output),
            active_display_count=len(profiler_displays),
        )
    if exit_code != 0:
        return HostDisplayReadiness(False, 0, (), redact_local_report_text(output or "display inventory command failed"))
    return HostDisplayReadiness(True, 0, (), active_display_count=0)


def read_system_profiler_displays() -> list[dict[str, object]]:
    exit_code, output = run_best_effort(
        "/usr/sbin/system_profiler",
        "SPDisplaysDataType",
        "-json",
        timeout_seconds=20,
    )
    if exit_code != 0:
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []
    displays: list[dict[str, object]] = []
    for gpu in payload.get("SPDisplaysDataType", []):
        if not isinstance(gpu, dict):
            continue
        for display in gpu.get("spdisplays_ndrvs", []):
            if not isinstance(display, dict):
                continue
            if display.get("spdisplays_online") not in (None, "spdisplays_yes"):
                continue
            displays.append(
                {
                    "id": str(display.get("_spdisplays_displayID", "unknown")),
                    "name": str(display.get("_name", "unknown")),
                    "main": "1" if display.get("spdisplays_main") == "spdisplays_yes" else "0",
                    "logical": str(display.get("_spdisplays_resolution", "unknown")),
                    "physical": str(display.get("_spdisplays_pixels", "unknown")),
                    "source": "system_profiler",
                }
            )
    return displays


def host_log_path_label(log_path: Path) -> str:
    if log_path.resolve() == DEFAULT_HOST_LOG_PATH.resolve():
        return "<user-host-log>"
    return redact_local_report_text(str(log_path))


def summarize_host_log(log_path: Path, marker_limit: int = 40) -> LogReadiness:
    if not log_path.exists():
        return LogReadiness(host_log_path_label(log_path), False, (), "Host log not found")
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
    except OSError as error:
        return LogReadiness(host_log_path_label(log_path), False, (), str(error))
    markers = [
        ascii_report_text(line)
        for line in lines
        if any(
            token in line
            for token in (
                "Launch at Login",
                "Auto-start",
                "automatic",
                "Unattended",
                "recovery",
                "retry",
                "Screen Recording",
                "CGPreflight",
                "Server started",
                "Streaming listener stopped",
            )
        )
    ]
    return LogReadiness(host_log_path_label(log_path), True, tuple(markers[-marker_limit:]))


def ascii_report_text(value: str) -> str:
    return redact_local_report_text(value).encode("ascii", errors="backslashreplace").decode("ascii")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bundle_plist(app_path: Path) -> dict[str, object]:
    with (app_path / "Contents" / "Info.plist").open("rb") as plist_file:
        return plistlib.load(plist_file)


def require_expected_bundle(app_path: Path, expected_bundle_id: str) -> None:
    if not app_path.is_dir():
        raise SystemExit(f"Host bundle not found: {app_path}")
    bundle_id = str(read_bundle_plist(app_path).get("CFBundleIdentifier", ""))
    if bundle_id != expected_bundle_id:
        raise SystemExit(
            f"refusing unexpected bundle at {app_path}: "
            f"CFBundleIdentifier is '{bundle_id}', expected '{expected_bundle_id}'"
        )


def parse_codesign_details(output: str) -> dict[str, object]:
    fields: dict[str, object] = {"Authority": []}
    authorities: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Authority="):
            authorities.append(line.split("=", 1)[1])
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"Identifier", "CDHash", "Signature", "TeamIdentifier"}:
            fields[key] = value
    fields["Authority"] = authorities
    return fields


def parse_designated_requirement(output: str) -> str | None:
    for line in output.splitlines():
        if "designated =>" in line:
            return line.split("designated =>", 1)[1].strip()
    stripped = output.strip()
    return stripped or None


def parse_leaf_certificate_hash(requirement: str | None) -> str | None:
    if requirement is None:
        return None
    match = re.search(r"certificate leaf = H\"([0-9a-fA-F]+)\"", requirement)
    return match.group(1).upper() if match else None


def parse_entitlement_keys(output: str) -> tuple[str, ...]:
    plist_start = output.find("<plist")
    plist_end = output.find("</plist>")
    if plist_start == -1 or plist_end == -1:
        return ()
    plist_xml = output[plist_start : plist_end + len("</plist>")]
    try:
        entitlements = plistlib.loads(plist_xml.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError, TypeError):
        return ()
    if not isinstance(entitlements, dict):
        return ()
    return tuple(sorted(str(key) for key in entitlements.keys() if entitlements.get(key) is True))


def redact_lsof_user_columns(output: str) -> str:
    if "COMMAND" not in output or "USER" not in output or "NODE NAME" not in output:
        return output
    redacted_lines = []
    for line in output.splitlines():
        if line.startswith("COMMAND"):
            redacted_lines.append(line)
            continue
        redacted_lines.append(re.sub(r"^(\S+\s+\d+\s+)(\S+)(\s+)", r"\1<redacted-user>\3", line))
    return redact_network_endpoints("\n".join(redacted_lines))


def inspect_entitlements(app_path: Path) -> EntitlementStatus:
    try:
        output = run("/usr/bin/codesign", "-d", "--entitlements", ":-", str(app_path))
    except subprocess.CalledProcessError as error:
        detail = (error.stdout or str(error)).strip()
        return EntitlementStatus(app_path, False, (), detail, detail)
    keys = parse_entitlement_keys(output)
    return EntitlementStatus(
        app_path=app_path,
        virtual_hid=VIRTUAL_HID_ENTITLEMENT in keys,
        keys=keys,
        raw_output=output,
    )


@dataclass(frozen=True)
class HostStartupSettings:
    domain: str
    readable: bool
    auto_start_streaming_on_launch: bool
    startup_mode: str
    has_completed_onboarding: bool
    display_source: str
    selected_display_uuid: str | None
    selected_display_id: int | None
    stored_keys: tuple[str, ...]
    defaults_used: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class LoginItemReadiness:
    state: str
    matched: bool
    detail: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class HostDisplayReadiness:
    readable: bool
    display_count: int
    displays: tuple[dict[str, object], ...]
    error: str | None = None
    active_display_count: int | None = None


@dataclass(frozen=True)
class LogReadiness:
    path: str
    readable: bool
    markers: tuple[str, ...]
    error: str | None = None


def collect_signing_metadata(app_path: Path) -> SigningMetadata:
    require_expected_bundle(app_path, EXPECTED_BUNDLE_ID)
    plist = read_bundle_plist(app_path)
    try:
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path))
        details = run("/usr/bin/codesign", "-dvvv", str(app_path))
        requirement_output = run("/usr/bin/codesign", "-d", "-r-", str(app_path))
    except subprocess.CalledProcessError as error:
        output = (error.stdout or str(error)).strip()
        raise SystemExit(f"codesign inspection failed for {app_path}: {output}") from error
    fields = parse_codesign_details(details)
    requirement = parse_designated_requirement(requirement_output)
    executable_name = str(plist.get("CFBundleExecutable", EXECUTABLE_NAME))
    executable_path = app_path / "Contents" / "MacOS" / executable_name
    if not executable_path.is_file():
        raise SystemExit(f"signed bundle executable is missing: {executable_path}")
    return SigningMetadata(
        app_path=app_path,
        identifier=str(fields.get("Identifier", "")),
        source_commit=string_or_none(plist.get(package_macos.SOURCE_COMMIT_PLIST_KEY)),
        source_tree=string_or_none(plist.get(package_macos.SOURCE_TREE_PLIST_KEY)),
        source_dirty=bool_or_none(plist.get(package_macos.SOURCE_DIRTY_PLIST_KEY)),
        binary_sha256=sha256(executable_path),
        authorities=tuple(fields.get("Authority", [])),
        cdhash=fields.get("CDHash") if isinstance(fields.get("CDHash"), str) else None,
        designated_requirement=requirement,
        signature=fields.get("Signature") if isinstance(fields.get("Signature"), str) else None,
        team_identifier=fields.get("TeamIdentifier") if isinstance(fields.get("TeamIdentifier"), str) else None,
        leaf_certificate_hash=parse_leaf_certificate_hash(requirement),
    )


def string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def current_source_identity(source_root: Path) -> package_macos.SourceIdentity:
    return package_macos.collect_source_identity(source_root.resolve())


def query_tcc_rows(bundle_id: str, database_paths: Path | tuple[Path, ...]) -> PermissionStatus:
    paths = (database_paths,) if isinstance(database_paths, Path) else database_paths
    rows: list[TCCRow] = []
    errors: list[str] = []
    for database_path in paths:
        status = query_tcc_database(bundle_id, database_path)
        rows.extend(status.rows)
        if status.error:
            errors.append(f"{tcc_database_report_label(database_path)}: {status.error}")
    label = "; ".join(tcc_database_report_label(path) for path in paths)
    if rows or len(errors) < len(paths):
        return PermissionStatus(
            database_path=label,
            rows=tuple(rows),
            readable=True,
            error="; ".join(errors) or None,
        )
    return PermissionStatus(database_path=label, rows=(), readable=False, error="; ".join(errors))


def query_tcc_database(bundle_id: str, database_path: Path, *, timeout_seconds: float = 5.0) -> PermissionStatus:
    import queue

    report_label = tcc_database_report_label(database_path)
    if not database_path.exists():
        return PermissionStatus(database_path=report_label, rows=(), readable=False, error="TCC database not found")
    context = _tcc_query_context()
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_query_tcc_database_worker, args=(result_queue, bundle_id, database_path))
    try:
        process.start()
        process.join(timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            if process.is_alive():
                process.kill()
                process.join()
            return PermissionStatus(
                database_path=report_label,
                rows=(),
                readable=False,
                error=f"TCC database query timed out after {timeout_seconds:g}s",
            )
        try:
            status, payload = result_queue.get(timeout=1.0)
        except queue.Empty:
            exitcode = process.exitcode if process.exitcode is not None else "unknown"
            return PermissionStatus(
                database_path=report_label,
                rows=(),
                readable=False,
                error=f"TCC database query exited without a result (exit {exitcode})",
            )
        if status == "ok":
            return payload
        return PermissionStatus(
            database_path=report_label,
            rows=(),
            readable=False,
            error=redact_local_report_text(str(payload)),
        )
    finally:
        result_queue.close()
        result_queue.join_thread()


def _tcc_query_context() -> multiprocessing.context.BaseContext:
    try:
        return multiprocessing.get_context("fork")
    except ValueError:
        return multiprocessing.get_context()


def _query_tcc_database_worker(result_queue: Any, bundle_id: str, database_path: Path) -> None:
    try:
        result_queue.put(("ok", _query_tcc_database_direct(bundle_id, database_path)))
    except Exception as error:
        result_queue.put(("error", redact_local_report_text(repr(error))))


def _query_tcc_database_direct(bundle_id: str, database_path: Path) -> PermissionStatus:
    report_label = tcc_database_report_label(database_path)
    try:
        connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(access)").fetchall()
            }
            required = {"service", "client", "client_type", "auth_value"}
            missing = required - columns
            if missing:
                raise sqlite3.OperationalError(
                    f"TCC access table is missing required columns: {', '.join(sorted(missing))}"
                )
            auth_reason = "auth_reason" if "auth_reason" in columns else "NULL AS auth_reason"
            last_modified = "last_modified" if "last_modified" in columns else "NULL AS last_modified"
            services = (*SCREEN_CAPTURE_SERVICES, ACCESSIBILITY_SERVICE)
            placeholders = ",".join("?" for _ in services)
            cursor = connection.execute(
                f"""
                SELECT service, client, client_type, auth_value, {auth_reason}, {last_modified}
                FROM access
                WHERE client = ? AND client_type = 0 AND service IN ({placeholders})
                ORDER BY service, last_modified
                """,
                (bundle_id, *services),
            )
            rows = tuple(
                TCCRow(
                    service=str(row[0]),
                    client=str(row[1]),
                    client_type=int(row[2]),
                    auth_value=None if row[3] is None else int(row[3]),
                    auth_reason=None if row[4] is None else int(row[4]),
                    last_modified=None if row[5] is None else int(row[5]),
                )
                for row in cursor.fetchall()
            )
            return PermissionStatus(database_path=report_label, rows=rows, readable=True)
        finally:
            connection.close()
    except sqlite3.Error as error:
        return PermissionStatus(database_path=report_label, rows=(), readable=False, error=redact_local_report_text(str(error)))


def inspect_listener(port: int) -> ListenerStatus:
    try:
        output = run("/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN")
    except subprocess.CalledProcessError as error:
        detail = (error.stdout or "").strip()
        return ListenerStatus(port=port, observed=False, output=detail, error="listener not observed")
    lines = [line for line in output.splitlines() if line.strip()]
    observed = any(f":{port}" in line and "LISTEN" in line for line in lines)
    output = redact_lsof_user_columns(output)
    return ListenerStatus(port=port, observed=observed, output=output, error=None if observed else "listener not observed")


def validate_preflight(
    metadata: SigningMetadata,
    permissions: PermissionStatus,
    *,
    install_path: Path,
    expected_sign_identity: str | None = None,
    source_identity: package_macos.SourceIdentity | None = None,
    allow_source_mismatch: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not is_default_install_path(install_path):
        errors.append(f"Host must be installed at the stable path: {DEFAULT_INSTALL_PATH}")
    if metadata.identifier != EXPECTED_BUNDLE_ID:
        errors.append(f"codesign identifier is '{metadata.identifier}', expected '{EXPECTED_BUNDLE_ID}'")
    if metadata.is_ad_hoc:
        errors.append(
            "Host is ad-hoc signed; use the configured local signing identity so TCC grants survive rebuilds"
        )
    elif expected_sign_identity and metadata.identity_name != expected_sign_identity:
        errors.append(f"Host is signed by '{metadata.identity_name}', expected configured identity '{expected_sign_identity}'")
    if not metadata.cdhash:
        errors.append("codesign CDHash is missing")
    if not metadata.designated_requirement:
        errors.append("codesign designated requirement is missing")
    if source_identity is not None:
        if source_identity.dirty and not allow_source_mismatch:
            errors.append("source repository is dirty; rerun from a clean current-base checkout")
        if not metadata.source_commit or not metadata.source_tree or metadata.source_dirty is None:
            if not allow_source_mismatch:
                errors.append("installed Host lacks source commit/tree provenance; rebuild with scripts/package_macos.py")
        else:
            if metadata.source_dirty and not allow_source_mismatch:
                errors.append("installed Host was packaged from a dirty source tree")
            if (
                metadata.source_commit != source_identity.commit
                or metadata.source_tree != source_identity.tree
            ) and not allow_source_mismatch:
                errors.append("installed Host source provenance does not match the current source checkout")
    if not permissions.readable:
        errors.append(f"cannot verify TCC permissions read-only: {permissions.error}")
    elif permissions.error:
        errors.append(f"cannot fully verify TCC permissions read-only: {permissions.error}")
    else:
        if not permissions.is_allowed(SCREEN_CAPTURE_SERVICES):
            errors.append("Screen Recording is not authorized for the installed Host")
        if not permissions.is_allowed((ACCESSIBILITY_SERVICE,)):
            errors.append("Accessibility is not authorized for the installed Host")
    return errors


def value_or_missing(value: int | None) -> str:
    return "missing" if value is None else str(value)


def format_permission_row(row: TCCRow) -> str:
    return f"{row.service}|{row.client}|{row.client_type}|{value_or_missing(row.auth_value)}|{value_or_missing(row.auth_reason)}|{value_or_missing(row.last_modified)}"


def permission_interpretation(permissions: PermissionStatus) -> str:
    if not permissions.readable:
        return f"unverified ({permissions.error})"
    screen = "allowed" if permissions.is_allowed(SCREEN_CAPTURE_SERVICES) else "not allowed"
    accessibility = "allowed" if permissions.is_allowed((ACCESSIBILITY_SERVICE,)) else "not allowed"
    if permissions.error:
        return f"Screen Recording {screen}; Accessibility {accessibility}; read warning: {permissions.error}."
    return f"Screen Recording {screen}; Accessibility {accessibility}."


def format_report(
    metadata: SigningMetadata | None,
    permissions: PermissionStatus,
    errors: list[str],
    *,
    source_identity: package_macos.SourceIdentity | None = None,
    allow_source_mismatch: bool = False,
    install_path: Path | None = None,
) -> str:
    if metadata is None:
        app_path: Path | str = install_path if install_path is not None else "not inspected"
        identifier = "not inspected"
        identity_name = "not inspected"
        authorities = "Authority: not inspected"
        team_identifier = "not inspected"
        certificate_sha1 = "not inspected"
        cdhash = "not inspected"
        binary_sha256 = "not inspected"
        designated_requirement = "not inspected"
        source_commit = "not inspected"
        source_tree = "not inspected"
        source_dirty: bool | str = "not inspected"
        verification = "not inspected"
    else:
        app_path = metadata.app_path
        identifier = metadata.identifier
        identity_name = metadata.identity_name
        authorities = "\n".join(f"Authority: {authority}" for authority in metadata.authorities)
        if not authorities:
            authorities = "Authority: ad-hoc"
        team_identifier = metadata.team_identifier or "not set"
        certificate_sha1 = metadata.leaf_certificate_hash or "not available"
        cdhash = metadata.cdhash or "missing"
        binary_sha256 = metadata.binary_sha256
        designated_requirement = metadata.designated_requirement or "missing"
        source_commit = metadata.source_commit or "missing"
        source_tree = metadata.source_tree or "missing"
        source_dirty = metadata.source_dirty if metadata.source_dirty is not None else "missing"
        verification = "valid on disk (codesign --verify --deep --strict)"
    rows = "\n".join(format_permission_row(row) for row in permissions.rows)
    if not rows:
        rows = "(no matching rows)"
    result = "PASS" if not errors else "FAIL"
    error_lines = "\n".join(f"- {error}" for error in errors) or "(none)"
    return f"""Host bundle
-----------
Path: {app_path}
Identifier: {identifier}
Identity: {identity_name}
{authorities}
TeamIdentifier: {team_identifier}
Certificate SHA-1: {certificate_sha1}
CDHash: {cdhash}
Binary SHA-256: {binary_sha256}
Designated requirement: {designated_requirement}
Source commit: {source_commit}
Source tree: {source_tree}
Source dirty: {source_dirty}
Current source commit: {source_identity.commit if source_identity else 'not checked'}
Current source tree: {source_identity.tree if source_identity else 'not checked'}
Current source dirty: {source_identity.dirty if source_identity else 'not checked'}
Source mismatch allowed: {allow_source_mismatch}
Verification: {verification}

Read-only TCC capture
---------------------
Database: {permissions.database_path}
Field order: service|client|client_type|auth_value|auth_reason|last_modified
{rows}

Interpretation: {permission_interpretation(permissions)}

Preflight result
----------------
Status: {result}
Blocking issues:
{error_lines}
System permission path: {SYSTEM_SETTINGS_PATH}

Keychain and TCC handling
-------------------------
This tool does not reset Keychain, import certificates, request passwords, update
partition lists, modify macOS privacy databases, or request/override macOS privacy authorization.
It only uses the configured codesign identity and reads privacy databases in read-only mode.
"""


def format_signing_prerequisite_report(*, install_path: Path, sign_identity: str, error: str) -> str:
    return f"""Host signing prerequisite
-------------------------
Configured identity: {sign_identity}
Install path: {install_path}

Result
------
Status: FAIL
Blocking issues:
- Host signing prerequisite is not met: {error}

Next action
-----------
Create or import the stable local codesigning identity, or set
${package_macos.SIGN_IDENTITY_ENV} to an existing stable identity, then rebuild
and reinstall the Host before rerunning device evidence. Do not use ad-hoc
signing for fixed-binary device reruns because it changes the code-signing hash
and invalidates macOS Screen Recording/Accessibility grants.

Safety
------
This blocked operation did not start the Host, run Android instrumentation,
modify Keychain, edit privacy databases, clear Android app data, or change ADB state. This
is a Host signing prerequisite, not an Android device-identity result.
System permission path: {SYSTEM_SETTINGS_PATH}
"""


def write_signing_prerequisite_report(args: argparse.Namespace, error: BaseException) -> int:
    report = format_signing_prerequisite_report(
        install_path=args.install_path.resolve(),
        sign_identity=args.sign_identity,
        error=str(error),
    )
    write_report(args.report, report)
    print(report, file=sys.stderr)
    return 2


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def command_report_line(label: str, exit_code: int, output: str) -> str:
    clean_output = ascii_report_text(output or "<empty>")
    return f"{label}: exit_code={exit_code}\n{clean_output}"

def xctest_preflight_command(args: argparse.Namespace) -> int:
    report_path = getattr(args, "report", None)
    json_output = getattr(args, "json_output", None)

    if isinstance(json_output, Path):
        status = inspect_xctest_preflight()
        document = build_xctest_preflight_document(status)
        write_json_report(json_output, document)
        print(f"Wrote {json_output}")
        if status.errors:
            return 2
        return 0

    if not isinstance(report_path, Path):
        exit_code, output = run_best_effort("/usr/bin/xcrun", "--find", "xctest", timeout_seconds=10)
        xctest_path = output.splitlines()[0].strip() if output.strip() else ""
        if exit_code != 0 or not xctest_path:
            detail = redact_local_report_text(output.strip()) if output.strip() else "xcrun did not return an XCTest path"
            print(
                "macOS XCTest preflight failed: select a full Xcode installation before running "
                f"baseline-macos-test ({detail}).",
                file=sys.stderr,
            )
            return 2
        print(f"macOS XCTest preflight passed: {redact_local_report_text(xctest_path)}")
        return 0

    developer_status, developer_dir = run_best_effort("/usr/bin/xcode-select", "-p", timeout_seconds=10)
    swift_path_status, swift_path = run_best_effort("/usr/bin/xcrun", "--find", "swift", timeout_seconds=10)
    swift_version_status, swift_version = run_best_effort("/usr/bin/swift", "--version", timeout_seconds=10)
    xcodebuild_path_status, xcodebuild_path = run_best_effort(
        "/usr/bin/xcrun", "--find", "xcodebuild", timeout_seconds=10
    )
    xcodebuild_version_status, xcodebuild_version = run_best_effort(
        "/usr/bin/xcodebuild", "-version", timeout_seconds=10
    )

    errors: list[str] = []
    if developer_status != 0:
        errors.append("xcode-select did not report a selected developer directory")
    elif "CommandLineTools" in developer_dir or ".app/Contents/Developer" not in developer_dir:
        errors.append("full Xcode is not selected; Command Line Tools cannot run this XCTest suite")
    if swift_path_status != 0 or swift_version_status != 0:
        errors.append("Swift toolchain is not available through xcrun and /usr/bin/swift")
    if xcodebuild_path_status != 0 or xcodebuild_version_status != 0:
        errors.append("xcodebuild is not available from the selected Apple developer directory")

    report = "\n".join(
        (
            "MacHost XCTest toolchain preflight",
            "---------------------------------",
            f"Status: {'PASS' if not errors else 'FAIL'}",
            command_report_line("xcode-select -p", developer_status, developer_dir),
            command_report_line("xcrun --find swift", swift_path_status, swift_path),
            command_report_line("swift --version", swift_version_status, swift_version),
            command_report_line("xcrun --find xcodebuild", xcodebuild_path_status, xcodebuild_path),
            command_report_line("xcodebuild -version", xcodebuild_version_status, xcodebuild_version),
            "Blocking issues:",
            "\n".join(f"- {error}" for error in errors) if errors else "- none",
            "Safety: read-only; does not build, install, sign, modify TCC, or touch devices.",
            "",
        )
    )
    write_report(report_path, report)
    print(f"Wrote {report_path}")
    json_errors: tuple[str, ...] = ()
    if isinstance(json_output, Path):
        status = inspect_xctest_preflight()
        json_errors = status.errors
        document = build_xctest_preflight_document(status)
        write_json_report(json_output, document)
        print(f"Wrote {json_output}")
    if errors or json_errors:
        print(report, file=sys.stderr)
        return 2
    print("macOS Host XCTest toolchain preflight passed")
    return 0

def missing_permission_status(error: str) -> PermissionStatus:
    return PermissionStatus(database_path="not inspected", rows=(), readable=False, error=error)


def inspect_host_without_throwing(
    install_path: Path,
    tcc_db: Path,
    *,
    expected_sign_identity: str | None = None,
    source_root: Path = package_macos.REPOSITORY_ROOT,
    allow_source_mismatch: bool = False,
    validate_configured_identity: bool = True,
) -> HostInspection:
    errors: list[str] = []
    source_identity: package_macos.SourceIdentity | None
    try:
        source_identity = current_source_identity(source_root)
    except SystemExit as error:
        source_identity = None
        errors.append(str(error))
    if expected_sign_identity == "-":
        errors.append(
            "Host readiness requires a stable signing identity; --sign-identity - is ad-hoc and cannot retain TCC grants"
        )
    elif validate_configured_identity:
        try:
            resolved_identity = package_macos.resolve_sign_identity(
                expected_sign_identity or package_macos.DEFAULT_SIGN_IDENTITY
            )
        except SystemExit as error:
            errors.append(str(error))
        else:
            if expected_sign_identity and resolved_identity != expected_sign_identity:
                errors.append(
                    "configured signing identity did not resolve exactly: "
                    f"requested '{expected_sign_identity}', resolved '{resolved_identity}'"
                )
    try:
        metadata = collect_signing_metadata(install_path)
    except SystemExit as error:
        return HostInspection(
            metadata=None,
            source_identity=source_identity,
            permissions=missing_permission_status("Host bundle signing was not inspected"),
            errors=[*errors, str(error)],
        )
    permissions = query_tcc_rows(EXPECTED_BUNDLE_ID, tcc_database_paths(tcc_db))
    errors.extend(
        validate_preflight(
            metadata,
            permissions,
            install_path=install_path,
            expected_sign_identity=expected_sign_identity,
            source_identity=source_identity,
            allow_source_mismatch=allow_source_mismatch,
        )
    )
    return HostInspection(metadata, source_identity, permissions, errors)


def permission_record(permissions: PermissionStatus) -> dict[str, Any]:
    return {
        "database_path": str(permissions.database_path),
        "readable": permissions.readable,
        "error": permissions.error,
        "screen_recording_granted": permissions.is_allowed(SCREEN_CAPTURE_SERVICES),
        "accessibility_granted": permissions.is_allowed((ACCESSIBILITY_SERVICE,)),
        "rows": [row.__dict__ for row in permissions.rows],
    }


def signing_record(
    metadata: SigningMetadata | None,
    install_path: Path,
    source_identity: package_macos.SourceIdentity | None,
) -> dict[str, Any]:
    if metadata is None:
        return {
            "app_path": str(install_path),
            "identifier": None,
            "identity": None,
            "is_ad_hoc": None,
            "authorities": [],
            "team_identifier": None,
            "certificate_sha1": None,
            "cdhash": None,
            "binary_sha256": None,
            "designated_requirement": None,
            "source_commit": None,
            "source_tree": None,
            "source_dirty": None,
            "current_source_commit": source_identity.commit if source_identity else None,
            "current_source_tree": source_identity.tree if source_identity else None,
            "current_source_dirty": source_identity.dirty if source_identity else None,
        }
    return {
        "app_path": str(metadata.app_path),
        "identifier": metadata.identifier,
        "identity": metadata.identity_name,
        "is_ad_hoc": metadata.is_ad_hoc,
        "authorities": list(metadata.authorities),
        "team_identifier": metadata.team_identifier,
        "certificate_sha1": metadata.leaf_certificate_hash,
        "cdhash": metadata.cdhash,
        "binary_sha256": metadata.binary_sha256,
        "designated_requirement": metadata.designated_requirement,
        "source_commit": metadata.source_commit,
        "source_tree": metadata.source_tree,
        "source_dirty": metadata.source_dirty,
        "current_source_commit": source_identity.commit if source_identity else None,
        "current_source_tree": source_identity.tree if source_identity else None,
        "current_source_dirty": source_identity.dirty if source_identity else None,
    }


def readiness_prerequisites_ready(errors: list[str], listener: ListenerStatus) -> bool:
    return not errors and listener.observed


def login_headless_blockers(
    settings: HostStartupSettings,
    login_item: LoginItemReadiness,
    displays: HostDisplayReadiness,
    logs: LogReadiness,
) -> list[str]:
    blockers: list[str] = []
    if not settings.readable:
        blockers.append(f"cannot read startup defaults: {settings.error}")
    if login_item.state != "enabled":
        blockers.append(f"Launch at Login is not verified enabled: {login_item.state}")
    if not settings.auto_start_streaming_on_launch:
        blockers.append("Start streaming automatically is disabled")
    if settings.startup_mode not in STARTUP_MODES:
        expected = ", ".join(sorted(STARTUP_MODES))
        blockers.append(f"startupMode is '{settings.startup_mode}', expected one of {expected} for local headless readiness")
    if not settings.has_completed_onboarding:
        blockers.append("onboarding has not completed; automatic startup waits for onboarding outside explicit benchmark mode")
    if not displays.readable:
        blockers.append(f"cannot read active display inventory: {displays.error}")
    elif (displays.active_display_count if displays.active_display_count is not None else displays.display_count) < 1:
        blockers.append("no active display is visible to the current WindowServer session")
    if not logs.readable:
        blockers.append(f"cannot summarize Host startup/recovery log: {logs.error}")
    return blockers


def login_headless_record(
    settings: HostStartupSettings,
    login_item: LoginItemReadiness,
    displays: HostDisplayReadiness,
    logs: LogReadiness,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "does_not_prove": [
            "macOS launched Vibe Screen after logout/login or reboot",
            "a headless Mac mini exposes a capturable display after reboot",
            "system_profiler display inventory proves ScreenCaptureKit can capture that display",
            "USB or LAN streaming rendered on an Android client",
            "unattended recovery succeeded or exhausted during a real listener/capture/display failure",
        ],
        "recommended_next_evidence": [
            "capture a reboot or logout/login launch log without manually launching Vibe Screen",
            "record the intended headless display setup and first successful capture after login",
            "force one listener, capture, or selected-display failure during unattended operation and preserve bounded retry logs",
        ],
        "startup_settings": {
            "domain": settings.domain,
            "readable": settings.readable,
            "error": settings.error,
            "auto_start_streaming_on_launch": settings.auto_start_streaming_on_launch,
            "startup_mode": settings.startup_mode,
            "has_completed_onboarding": settings.has_completed_onboarding,
            "display_source": settings.display_source,
            "selected_display_uuid": settings.selected_display_uuid,
            "selected_display_id": settings.selected_display_id,
            "stored_keys": list(settings.stored_keys),
            "defaults_used": list(settings.defaults_used),
        },
        "login_item": {
            "state": login_item.state,
            "matched": login_item.matched,
            "detail": login_item.detail,
            "evidence": list(login_item.evidence),
        },
        "display_inventory": {
            "readable": displays.readable,
            "display_count": displays.display_count,
            "active_display_count": displays.active_display_count if displays.active_display_count is not None else displays.display_count,
            "error": displays.error,
            "displays": list(displays.displays),
        },
        "host_log": {
            "path": logs.path,
            "readable": logs.readable,
            "error": logs.error,
            "startup_recovery_markers": list(logs.markers),
        },
    }


def build_readiness_document(
    inspection: HostInspection,
    listener: ListenerStatus,
    entitlements: EntitlementStatus,
    settings: HostStartupSettings | None = None,
    login_item: LoginItemReadiness | None = None,
    displays: HostDisplayReadiness | None = None,
    logs: LogReadiness | None = None,
) -> dict[str, Any]:
    if settings is None:
        settings = read_startup_settings()
    if login_item is None:
        login_item = skipped_login_item_readiness()
    if displays is None:
        displays = read_display_readiness()
    if logs is None:
        logs = summarize_host_log(DEFAULT_HOST_LOG_PATH)
    shared_ready = readiness_prerequisites_ready(inspection.errors, listener)
    controller_ready = shared_ready and entitlements.virtual_hid
    login_blockers = login_headless_blockers(settings, login_item, displays, logs)
    headless_login_ready = shared_ready and not login_blockers
    blockers = list(inspection.errors)
    if not listener.observed:
        blockers.append(f"Host listener is not observed on TCP port {listener.port}")
    if not entitlements.virtual_hid:
        blockers.append(f"Host is missing {VIRTUAL_HID_ENTITLEMENT} entitlement")
    blockers.extend(f"login/headless readiness: {blocker}" for blocker in login_blockers)
    return {
        "schema_version": "vibescreen.host-readiness/v1",
        "kind": "macos_host_shared_prerequisite_readiness",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not blockers else "blocked",
        "signing_tcc_status": "ready" if not inspection.errors else "blocked",
        "listener_status": "ready" if listener.observed else "blocked",
        "virtual_hid_status": "ready" if entitlements.virtual_hid else "blocked",
        "login_headless_status": "ready" if headless_login_ready else "blocked",
        "can_start_host_rss_gate": shared_ready,
        "can_start_trusted_lan_gate": shared_ready,
        "can_start_native_hid_gate": shared_ready,
        "can_start_stylus_gate": shared_ready,
        "can_start_hardware_keyboard_gate": shared_ready,
        "can_start_controller_runtime_gate": controller_ready,
        "can_start_headless_login_gate": headless_login_ready,
        "can_close_runtime_gates": False,
        "blockers": blockers,
        "host": signing_record(inspection.metadata, entitlements.app_path, inspection.source_identity),
        "permissions": permission_record(inspection.permissions),
        "listener": {
            "port": listener.port,
            "observed": listener.observed,
            "output": listener.output,
            "error": listener.error,
        },
        "entitlements": {
            "app_path": str(entitlements.app_path),
            "virtual_hid": entitlements.virtual_hid,
            "keys": list(entitlements.keys),
            "error": entitlements.error,
        },
        "login_headless": login_headless_record(settings, login_item, displays, logs, login_blockers),
        "safety": {
            "read_only": True,
            "starts_host": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android": False,
            "closes_runtime_gates": False,
        },
    }


def write_json_report(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def metadata_and_permissions(
    install_path: Path,
    tcc_db: Path,
    *,
    expected_sign_identity: str | None = None,
    source_root: Path = package_macos.REPOSITORY_ROOT,
    allow_source_mismatch: bool = False,
    validate_configured_identity: bool = True,
) -> tuple[SigningMetadata, package_macos.SourceIdentity, PermissionStatus, list[str]]:
    errors: list[str] = []
    if validate_configured_identity:
        if expected_sign_identity == "-":
            errors.append(
                "Host readiness requires a stable signing identity; --sign-identity - is ad-hoc and cannot retain TCC grants"
            )
        else:
            try:
                resolved_identity = package_macos.resolve_sign_identity(
                    expected_sign_identity or package_macos.DEFAULT_SIGN_IDENTITY
                )
            except SystemExit as error:
                errors.append(str(error))
            else:
                if expected_sign_identity and resolved_identity != expected_sign_identity:
                    errors.append(
                        "configured signing identity did not resolve exactly: "
                        f"requested '{expected_sign_identity}', resolved '{resolved_identity}'"
                    )
    metadata = collect_signing_metadata(install_path)
    source_identity = current_source_identity(source_root)
    permissions = query_tcc_rows(EXPECTED_BUNDLE_ID, tcc_database_paths(tcc_db))
    errors.extend(
        validate_preflight(
            metadata,
            permissions,
            install_path=install_path,
            expected_sign_identity=expected_sign_identity,
            source_identity=source_identity,
            allow_source_mismatch=allow_source_mismatch,
        )
    )
    return metadata, source_identity, permissions, errors


def refuse_ad_hoc_identity(sign_identity: str) -> None:
    if sign_identity == "-":
        raise SystemExit(
            "local device reruns require a stable signing identity; refusing --sign-identity -. "
            "Set VIBE_SCREEN_SIGN_IDENTITY to an existing codesigning identity or create "
            "the documented 'Vibe Screen Dev' self-signed identity, then grant permissions "
            "in System Settings."
        )


def package_dev_app(output_dir: Path, sign_identity: str) -> Path:
    refuse_ad_hoc_identity(sign_identity)
    package_macos.resolve_sign_identity(sign_identity)
    output_dir = output_dir.resolve()
    command = (
        sys.executable,
        str(package_macos.REPOSITORY_ROOT / "scripts" / "package_macos.py"),
        "--output-dir",
        str(output_dir),
        "--sign-identity",
        sign_identity,
    )
    run(*command, cwd=package_macos.REPOSITORY_ROOT)
    app_path = output_dir / f"{APP_NAME}.app"
    require_expected_bundle(app_path, EXPECTED_BUNDLE_ID)
    return app_path


def safe_replace_app(source_app: Path, install_path: Path, expected_bundle_id: str) -> None:
    require_expected_bundle(source_app, expected_bundle_id)
    if install_path.exists():
        require_expected_bundle(install_path, expected_bundle_id)
    install_path.parent.mkdir(parents=True, exist_ok=True)
    staging = install_path.parent / f".{install_path.name}.installing-{os.getpid()}"
    backup = install_path.parent / f".{install_path.name}.previous-{os.getpid()}"
    if staging.exists() or backup.exists():
        raise SystemExit(f"temporary install path already exists near {install_path}")
    try:
        shutil.copytree(source_app, staging, symlinks=True)
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(staging))
        if install_path.exists():
            install_path.rename(backup)
        staging.rename(install_path)
        if backup.exists():
            shutil.rmtree(backup)
    except PermissionError as error:
        restore_backup(install_path, backup)
        raise SystemExit(
            f"installing to {install_path} requires permission: {error}. Keep the Host at "
            "/Applications/Vibe Screen.app and approve it in System Settings."
        ) from error
    except Exception:
        restore_backup(install_path, backup)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def restore_backup(install_path: Path, backup: Path) -> None:
    if backup.exists():
        if install_path.exists():
            shutil.rmtree(install_path, ignore_errors=True)
        backup.rename(install_path)


def is_default_install_path(path: Path) -> bool:
    return path.resolve() == DEFAULT_INSTALL_PATH.resolve()


def install_command(args: argparse.Namespace) -> int:
    install_path = args.install_path.resolve()
    if not is_default_install_path(install_path):
        raise SystemExit(f"refusing nonstandard install path; use {DEFAULT_INSTALL_PATH}")
    try:
        packaged_app = package_dev_app(args.output_dir, args.sign_identity)
    except SystemExit as error:
        message = str(error)
        if "signing identity" in message or "codesign identity" in message:
            return write_signing_prerequisite_report(args, error)
        raise
    safe_replace_app(packaged_app, install_path, EXPECTED_BUNDLE_ID)
    inspection = inspect_host_without_throwing(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    report = format_report(
        inspection.metadata,
        inspection.permissions,
        inspection.errors,
        source_identity=inspection.source_identity,
        allow_source_mismatch=args.allow_source_mismatch,
        install_path=install_path,
    )
    write_report(args.report, report)
    print(f"Installed {install_path}")
    print(f"Wrote {args.report}")
    if inspection.errors:
        print(
            "Permissions are not ready for device evidence yet; grant the listed items in "
            f"{SYSTEM_SETTINGS_PATH}, relaunch Vibe Screen, then run preflight."
        )
        if inspection.metadata is None:
            print(report, file=sys.stderr)
            return 2
    return 0


def preflight_command(args: argparse.Namespace) -> int:
    install_path = args.install_path.resolve()
    if not is_default_install_path(install_path):
        raise SystemExit(f"refusing nonstandard install path; use {DEFAULT_INSTALL_PATH}")
    try:
        refuse_ad_hoc_identity(args.sign_identity)
    except SystemExit as error:
        return write_signing_prerequisite_report(args, error)
    try:
        package_macos.resolve_sign_identity(args.sign_identity)
    except SystemExit as error:
        return write_signing_prerequisite_report(args, error)
    inspection = inspect_host_without_throwing(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
        validate_configured_identity=False,
    )
    report = format_report(
        inspection.metadata,
        inspection.permissions,
        inspection.errors,
        source_identity=inspection.source_identity,
        allow_source_mismatch=args.allow_source_mismatch,
        install_path=install_path,
    )
    write_report(args.report, report)
    print(f"Wrote {args.report}")
    if inspection.errors:
        print(report, file=sys.stderr)
        print("macOS XCTest preflight failed", file=sys.stderr)
        return 2
    print("macOS Host touch-rerun preflight passed")
    return 0


def readiness_command(args: argparse.Namespace) -> int:
    install_path = args.install_path.resolve()
    if not is_default_install_path(install_path):
        raise SystemExit(f"refusing nonstandard install path; use {DEFAULT_INSTALL_PATH}")
    inspection = inspect_host_without_throwing(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    listener = inspect_listener(args.port)
    entitlements = inspect_entitlements(install_path)
    probe_login_item = bool(
        vars(args).get("probe_login_item", False)
        or vars(args).get("include_login_item_diagnostic", False)
    )
    login_item = read_login_item_readiness() if probe_login_item else skipped_login_item_readiness()
    if inspection.metadata is not None:
        report = format_report(
            inspection.metadata,
            inspection.permissions,
            inspection.errors,
            source_identity=inspection.source_identity,
            allow_source_mismatch=args.allow_source_mismatch,
        )
    else:
        error_lines = "\n".join(f"- {error}" for error in inspection.errors) or "(none)"
        report = f"""Host bundle
-----------
Path: {install_path}
Verification: not inspected

Preflight result
----------------
Status: FAIL
Blocking issues:
{error_lines}
System permission path: {SYSTEM_SETTINGS_PATH}

Keychain and TCC handling
-------------------------
This tool does not reset Keychain, import certificates, request passwords, update
partition lists, modify macOS privacy databases, or request/override macOS privacy authorization.
It only uses the configured codesign identity and reads privacy databases in read-only mode.
"""
    write_report(args.report, report)
    document = build_readiness_document(inspection, listener, entitlements, login_item=login_item)
    write_json_report(args.json_output, document)
    print(f"Wrote {args.report}")
    print(f"Wrote {args.json_output}")
    if document["status"] != "ready":
        print(json.dumps(document, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print("macOS Host shared prerequisite readiness passed")
    return 0

def main() -> int:
    args = parse_args()
    if args.command == "xctest-preflight":
        return xctest_preflight_command(args)
    if args.command == "install":
        return install_command(args)
    if args.command == "preflight":
        return preflight_command(args)
    if args.command == "readiness":
        return readiness_command(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
