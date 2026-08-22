#!/usr/bin/env python3
"""Build, install, and preflight the local macOS development Host bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import package_macos


APP_NAME = package_macos.PRODUCT_NAME
EXECUTABLE_NAME = package_macos.EXECUTABLE_NAME
DEFAULT_INSTALL_PATH = Path("/Applications") / f"{APP_NAME}.app"
DEFAULT_OUTPUT_DIR = package_macos.REPOSITORY_ROOT / ".build" / "dev-macos-host"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "host-signing-and-permissions.txt"
DEFAULT_READINESS_REPORT_PATH = DEFAULT_OUTPUT_DIR / "login-headless-readiness.txt"
DEFAULT_READINESS_JSON_PATH = DEFAULT_OUTPUT_DIR / "login-headless-readiness.json"
DEFAULT_HOST_LOG_PATH = Path.home() / "Library" / "Logs" / "Telemachus" / "telemachus.log"
SYSTEM_TCC_DATABASE = Path("/Library/Application Support/com.apple.TCC/TCC.db")
EXPECTED_BUNDLE_ID = "dev.telemachus.display"
SCREEN_CAPTURE_SERVICES = ("kTCCServiceScreenCapture", "kTCCServiceScreenRecording")
ACCESSIBILITY_SERVICE = "kTCCServiceAccessibility"
ALLOWED_AUTH_VALUE = 2
TCC_QUERY_TIMEOUT_SECONDS = 5
DEFAULTS_PREFIX = "Telemachus_"
STARTUP_MODES = {"usb", "wireless", "internet"}
SYSTEM_SETTINGS_PATH = (
    "System Settings -> Privacy & Security -> Screen & System Audio Recording "
    "and Accessibility"
)
TCC_QUERY_SCRIPT = textwrap.dedent(r'''
import json
import sqlite3
import sys
from pathlib import Path

database_path = Path(sys.argv[1])
bundle_id = sys.argv[2]
services = tuple(sys.argv[3:])
try:
    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(access)").fetchall()}
        required = {"service", "client", "client_type", "auth_value"}
        missing = required - columns
        if missing:
            raise sqlite3.OperationalError(
                f"TCC access table is missing required columns: {', '.join(sorted(missing))}"
            )
        auth_reason = "auth_reason" if "auth_reason" in columns else "NULL AS auth_reason"
        last_modified = "last_modified" if "last_modified" in columns else "NULL AS last_modified"
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
        print(json.dumps({"rows": cursor.fetchall()}))
    finally:
        connection.close()
except sqlite3.Error as error:
    print(json.dumps({"error": str(error)}))
''')


@dataclass(frozen=True)
class SigningMetadata:
    app_path: Path
    identifier: str
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


def default_tcc_database() -> Path:
    return Path.home() / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db"


def tcc_database_paths(database_path: Path) -> tuple[Path, ...]:
    default_database = default_tcc_database().resolve()
    resolved = database_path.resolve()
    return (resolved, SYSTEM_TCC_DATABASE) if resolved == default_database else (resolved,)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build/install the local Vibe Screen Host or collect read-only macOS "
            "readiness diagnostics. The tool never modifies TCC."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="build, sign, and install the stable local development Host bundle")
    add_common_options(install, include_sign_identity=True, include_output_dir=True)
    preflight = subparsers.add_parser("preflight", help="fail closed unless the installed Host is stable-signed and authorized")
    add_common_options(preflight, include_sign_identity=True)
    readiness = subparsers.add_parser(
        "readiness",
        help="collect read-only login/headless/unattended readiness diagnostics",
    )
    add_common_options(
        readiness,
        include_sign_identity=True,
        report_default=DEFAULT_READINESS_REPORT_PATH,
        report_help="path for the human-readable readiness report",
    )
    readiness.add_argument(
        "--json-report",
        type=Path,
        default=DEFAULT_READINESS_JSON_PATH,
        help="path for the machine-readable readiness report",
    )
    readiness.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_HOST_LOG_PATH,
        help="Host log path to summarize for startup/recovery markers",
    )
    return parser.parse_args()


def add_common_options(
    parser: argparse.ArgumentParser,
    *,
    include_sign_identity: bool = False,
    include_output_dir: bool = False,
    report_default: Path = DEFAULT_REPORT_PATH,
    report_help: str = "path for the signing and permission report",
) -> None:
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
        default=report_default,
        help=report_help,
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


def collect_signing_metadata(app_path: Path) -> SigningMetadata:
    require_expected_bundle(app_path, EXPECTED_BUNDLE_ID)
    try:
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path))
        details = run("/usr/bin/codesign", "-dvvv", str(app_path))
        requirement_output = run("/usr/bin/codesign", "-d", "-r-", str(app_path))
    except subprocess.CalledProcessError as error:
        output = (error.stdout or str(error)).strip()
        raise SystemExit(f"codesign inspection failed for {app_path}: {output}") from error
    fields = parse_codesign_details(details)
    requirement = parse_designated_requirement(requirement_output)
    plist = read_bundle_plist(app_path)
    executable_name = str(plist.get("CFBundleExecutable", EXECUTABLE_NAME))
    executable_path = app_path / "Contents" / "MacOS" / executable_name
    if not executable_path.is_file():
        raise SystemExit(f"signed bundle executable is missing: {executable_path}")
    return SigningMetadata(
        app_path=app_path,
        identifier=str(fields.get("Identifier", "")),
        binary_sha256=sha256(executable_path),
        authorities=tuple(fields.get("Authority", [])),
        cdhash=fields.get("CDHash") if isinstance(fields.get("CDHash"), str) else None,
        designated_requirement=requirement,
        signature=fields.get("Signature") if isinstance(fields.get("Signature"), str) else None,
        team_identifier=fields.get("TeamIdentifier") if isinstance(fields.get("TeamIdentifier"), str) else None,
        leaf_certificate_hash=parse_leaf_certificate_hash(requirement),
    )


def query_tcc_rows(bundle_id: str, database_paths: Path | tuple[Path, ...]) -> PermissionStatus:
    paths = (database_paths,) if isinstance(database_paths, Path) else database_paths
    rows: list[TCCRow] = []
    errors: list[str] = []
    for database_path in paths:
        status = query_tcc_database(bundle_id, database_path)
        rows.extend(status.rows)
        if status.error:
            errors.append(f"{database_path}: {status.error}")
    label = "; ".join(str(path) for path in paths)
    if rows or len(errors) < len(paths):
        return PermissionStatus(
            database_path=label,
            rows=tuple(rows),
            readable=True,
            error="; ".join(errors) or None,
        )
    return PermissionStatus(database_path=label, rows=(), readable=False, error="; ".join(errors))


def query_tcc_database(bundle_id: str, database_path: Path) -> PermissionStatus:
    if not database_path.exists():
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error="TCC database not found")
    exit_code, output = run_best_effort(
        sys.executable,
        "-c",
        TCC_QUERY_SCRIPT,
        str(database_path),
        bundle_id,
        *SCREEN_CAPTURE_SERVICES,
        ACCESSIBILITY_SERVICE,
        timeout_seconds=TCC_QUERY_TIMEOUT_SECONDS,
    )
    if exit_code != 0:
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error=output)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error=f"invalid TCC query output: {error}")
    if not isinstance(payload, dict):
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error="invalid TCC query output")
    if isinstance(payload.get("error"), str):
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error=str(payload["error"]))
    rows = tuple(
        TCCRow(
            service=str(row[0]),
            client=str(row[1]),
            client_type=int(row[2]),
            auth_value=None if row[3] is None else int(row[3]),
            auth_reason=None if row[4] is None else int(row[4]),
            last_modified=None if row[5] is None else int(row[5]),
        )
        for row in payload.get("rows", [])
    )
    return PermissionStatus(database_path=str(database_path), rows=rows, readable=True)


def validate_preflight(
    metadata: SigningMetadata, permissions: PermissionStatus, *, install_path: Path, expected_sign_identity: str | None = None
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


def format_report(metadata: SigningMetadata, permissions: PermissionStatus, errors: list[str]) -> str:
    authorities = "\n".join(f"Authority: {authority}" for authority in metadata.authorities)
    if not authorities:
        authorities = "Authority: ad-hoc"
    rows = "\n".join(format_permission_row(row) for row in permissions.rows)
    if not rows:
        rows = "(no matching rows)"
    result = "PASS" if not errors else "FAIL"
    error_lines = "\n".join(f"- {error}" for error in errors) or "(none)"
    return f"""Host bundle
-----------
Path: {metadata.app_path}
Identifier: {metadata.identifier}
Identity: {metadata.identity_name}
{authorities}
TeamIdentifier: {metadata.team_identifier or 'not set'}
Certificate SHA-1: {metadata.leaf_certificate_hash or 'not available'}
CDHash: {metadata.cdhash or 'missing'}
Binary SHA-256: {metadata.binary_sha256}
Designated requirement: {metadata.designated_requirement or 'missing'}
Verification: valid on disk (codesign --verify --deep --strict)

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
partition lists, modify TCC.db, or request/override macOS privacy authorization.
It only uses the configured codesign identity and reads TCC.db in read-only mode.
"""


def run_best_effort(*command: str, timeout_seconds: int = 15) -> tuple[int, str]:
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
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        detail = f"command timed out after {timeout_seconds}s"
        if output.strip():
            detail = f"{detail}: {output.strip()}"
        return 124, detail
    return completed.returncode, completed.stdout.strip()


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
    return value.strip().lower() in {"1", "true", "yes"}


def defaults_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def defaults_string(value: object | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        return stripped[1:-1]
    return stripped


def read_startup_settings(bundle_id: str = EXPECTED_BUNDLE_ID) -> HostStartupSettings:
    exit_code, output = run_best_effort("/usr/bin/defaults", "export", bundle_id, "-")
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
            error=output or "defaults domain not found",
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
        auto_start_streaming_on_launch=defaults_bool(
            parsed.get(DEFAULTS_PREFIX + "autoStartStreamingOnLaunch"),
            True,
        ),
        startup_mode=startup_mode,
        has_completed_onboarding=defaults_bool(
            parsed.get(DEFAULTS_PREFIX + "hasCompletedOnboarding"),
            False,
        ),
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
        matches.append("\n".join(lines[start:end]))
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
        state = "requires_approval"
        detail = "Matching login item appears to need user approval; verify in System Settings."
    elif any(marker in lowered for marker in ("disabled", "not enabled", "state = 0")):
        state = "disabled"
        detail = "Matching login item appears present but disabled."
    elif any(marker in lowered for marker in ("enabled", "allowed = 1", "state = 1")):
        state = "enabled"
        detail = "Matching login item appears enabled in read-only sfltool output."
    else:
        state = "present_unknown"
        detail = "Matching login item was found, but the enabled/approval state was not machine-parsable."
    return LoginItemReadiness(state=state, matched=True, detail=detail, evidence=tuple(matches))


def read_login_item_readiness() -> LoginItemReadiness:
    exit_code, output = run_best_effort("/usr/bin/sfltool", "dumpbtm")
    if exit_code != 0:
        return LoginItemReadiness(
            state="unverified",
            matched=False,
            detail=output or "sfltool dumpbtm failed",
            evidence=(),
        )
    return parse_login_item_state(output)


def read_display_readiness() -> HostDisplayReadiness:
    script = """
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
    exit_code, output = run_best_effort("/usr/bin/swift", "-e", script)
    if exit_code != 0:
        return HostDisplayReadiness(False, 0, (), output or "display inventory command failed")
    displays: list[dict[str, object]] = []
    for line in output.splitlines():
        fields = dict(part.split("=", 1) for part in line.split("|") if "=" in part)
        if fields:
            displays.append(fields)
    if displays:
        return HostDisplayReadiness(True, len(displays), tuple(displays), active_display_count=len(displays))
    profiler_displays = read_system_profiler_displays()
    if profiler_displays:
        return HostDisplayReadiness(True, len(profiler_displays), tuple(profiler_displays), active_display_count=0)
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


def summarize_host_log(log_path: Path, marker_limit: int = 40) -> LogReadiness:
    if not log_path.exists():
        return LogReadiness(str(log_path), False, (), "Host log not found")
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
    except OSError as error:
        return LogReadiness(str(log_path), False, (), str(error))
    markers = [
        line
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
    return LogReadiness(str(log_path), True, tuple(markers[-marker_limit:]))


def build_readiness_payload(
    metadata: SigningMetadata,
    permissions: PermissionStatus,
    signing_errors: list[str],
    settings: HostStartupSettings,
    login_item: LoginItemReadiness,
    displays: HostDisplayReadiness,
    logs: LogReadiness,
) -> dict[str, object]:
    blockers = list(signing_errors)
    warnings: list[str] = []
    if not settings.readable:
        blockers.append(f"cannot read startup defaults: {settings.error}")
    if login_item.state != "enabled":
        blockers.append(f"Launch at Login is not verified enabled: {login_item.state}")
    if not settings.auto_start_streaming_on_launch:
        blockers.append("Start streaming automatically is disabled")
    if settings.startup_mode not in {"usb", "wireless"}:
        blockers.append(f"startupMode is '{settings.startup_mode}', expected usb or wireless for local headless readiness")
    if not settings.has_completed_onboarding:
        blockers.append("onboarding has not completed; automatic startup waits for onboarding outside explicit benchmark mode")
    if not displays.readable:
        blockers.append(f"cannot read active display inventory: {displays.error}")
    elif (displays.active_display_count if displays.active_display_count is not None else displays.display_count) < 1:
        blockers.append("no active display is visible to the current WindowServer session")
    if not logs.readable:
        warnings.append(f"cannot summarize Host startup/recovery log: {logs.error}")
    return {
        "schema": "dev.vibescreen.macos-startup-readiness/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": "ready" if not blockers else "blocked",
        "scope": "read-only login startup, headless display, and unattended recovery readiness",
        "does_not_prove": [
            "macOS launched Vibe Screen after logout/login or reboot",
            "a headless Mac mini exposes a capturable display after reboot",
            "system_profiler display inventory proves ScreenCaptureKit can capture that display",
            "USB or LAN streaming rendered on an Android client",
            "unattended recovery succeeded or exhausted during a real listener/capture/display failure",
        ],
        "blockers": blockers,
        "warnings": warnings,
        "recommended_next_evidence": [
            "run this readiness command again after Launch at Login can be read and at least one display is visible",
            "capture a reboot or logout/login launch log without manually launching Vibe Screen",
            "record the intended headless display setup and first successful capture after login",
            "force one listener, capture, or selected-display failure during unattended operation and preserve bounded retry logs",
        ],
        "host_bundle": {
            "path": str(metadata.app_path),
            "identifier": metadata.identifier,
            "identity": metadata.identity_name,
            "authorities": list(metadata.authorities),
            "team_identifier": metadata.team_identifier,
            "certificate_sha1": metadata.leaf_certificate_hash,
            "cdhash": metadata.cdhash,
            "binary_sha256": metadata.binary_sha256,
            "designated_requirement": metadata.designated_requirement,
            "ad_hoc": metadata.is_ad_hoc,
        },
        "permissions": {
            "database": str(permissions.database_path),
            "readable": permissions.readable,
            "error": permissions.error,
            "screen_recording_allowed": permissions.is_allowed(SCREEN_CAPTURE_SERVICES),
            "accessibility_allowed": permissions.is_allowed((ACCESSIBILITY_SERVICE,)),
            "rows": [row.__dict__ for row in permissions.rows],
        },
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
            "active_display_count": displays.active_display_count
            if displays.active_display_count is not None
            else displays.display_count,
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


def format_readiness_report(payload: dict[str, object]) -> str:
    host = payload["host_bundle"]
    permissions = payload["permissions"]
    settings = payload["startup_settings"]
    login_item = payload["login_item"]
    display_inventory = payload["display_inventory"]
    host_log = payload["host_log"]
    blocker_lines = "\n".join(f"- {blocker}" for blocker in payload["blockers"]) or "(none)"
    warning_lines = "\n".join(f"- {warning}" for warning in payload["warnings"]) or "(none)"
    display_lines = "\n".join(f"- {display}" for display in display_inventory["displays"]) or "(none)"
    log_lines = "\n".join(
        f"- {ascii_report_text(str(marker))}"
        for marker in host_log["startup_recovery_markers"]
    ) or "(none)"
    does_not_prove = "\n".join(f"- {item}" for item in payload["does_not_prove"])
    next_evidence = "\n".join(f"- {item}" for item in payload["recommended_next_evidence"])
    defaults_used = settings["defaults_used"]
    defaults_used_text = ", ".join(defaults_used) if defaults_used else "none"
    selected_display_id = settings["selected_display_id"]
    selected_display_id_text = selected_display_id if selected_display_id is not None else "not set"
    return f"""macOS login/headless readiness
--------------------------------
Generated: {payload['generated_at']}
Result: {str(payload['result']).upper()}
Scope: {payload['scope']}

Blocking issues
---------------
{blocker_lines}

Warnings
--------
{warning_lines}

Installed Host
--------------
Path: {host['path']}
Identifier: {host['identifier']}
Identity: {host['identity']}
Certificate SHA-1: {host['certificate_sha1'] or 'not available'}
CDHash: {host['cdhash'] or 'missing'}
Binary SHA-256: {host['binary_sha256']}
Ad-hoc: {host['ad_hoc']}

Permissions
-----------
Database: {permissions['database']}
Screen Recording allowed: {permissions['screen_recording_allowed']}
Accessibility allowed: {permissions['accessibility_allowed']}
Read warning: {permissions['error'] or 'none'}

Startup settings
----------------
Defaults domain readable: {settings['readable']}
autoStartStreamingOnLaunch: {settings['auto_start_streaming_on_launch']}
startupMode: {settings['startup_mode']}
hasCompletedOnboarding: {settings['has_completed_onboarding']}
displaySource: {settings['display_source']}
selectedDisplayUUID: {settings['selected_display_uuid'] or 'not set'}
selectedDisplayID: {selected_display_id_text}
Defaults used: {defaults_used_text}

Launch at Login
---------------
State: {login_item['state']}
Detail: {login_item['detail']}

Display inventory
-----------------
Readable: {display_inventory['readable']}
Display count: {display_inventory['display_count']}
Active CoreGraphics display count: {display_inventory['active_display_count']}
{display_lines}

Recent Host startup/recovery markers
------------------------------------
Log path: {host_log['path']}
Readable: {host_log['readable']}
{log_lines}

This readiness report does not prove
------------------------------------
{does_not_prove}

Recommended next evidence
-------------------------
{next_evidence}

Safety
------
This command is read-only. It does not register login items, reboot, launch or
stop Vibe Screen, reset TCC, grant permissions, modify Keychain, or contact an
Android device.
"""


def ascii_report_text(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def metadata_and_permissions(
    install_path: Path, tcc_db: Path, *, expected_sign_identity: str | None = None
) -> tuple[SigningMetadata, PermissionStatus, list[str]]:
    metadata = collect_signing_metadata(install_path)
    permissions = query_tcc_rows(EXPECTED_BUNDLE_ID, tcc_database_paths(tcc_db))
    errors = validate_preflight(metadata, permissions, install_path=install_path, expected_sign_identity=expected_sign_identity)
    return metadata, permissions, errors


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
    packaged_app = package_dev_app(args.output_dir, args.sign_identity)
    safe_replace_app(packaged_app, install_path, EXPECTED_BUNDLE_ID)
    metadata, permissions, errors = metadata_and_permissions(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
    )
    report = format_report(metadata, permissions, errors)
    write_report(args.report, report)
    print(f"Installed {install_path}")
    print(f"Wrote {args.report}")
    if errors:
        print(
            "Permissions are not ready for touch rerun yet; grant the listed items in "
            f"{SYSTEM_SETTINGS_PATH}, relaunch Vibe Screen, then run preflight."
        )
    return 0


def preflight_command(args: argparse.Namespace) -> int:
    install_path = args.install_path.resolve()
    if not is_default_install_path(install_path):
        raise SystemExit(f"refusing nonstandard install path; use {DEFAULT_INSTALL_PATH}")
    refuse_ad_hoc_identity(args.sign_identity)
    package_macos.resolve_sign_identity(args.sign_identity)
    metadata, permissions, errors = metadata_and_permissions(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
    )
    report = format_report(metadata, permissions, errors)
    write_report(args.report, report)
    print(f"Wrote {args.report}")
    if errors:
        print(report, file=sys.stderr)
        return 2
    print("macOS Host touch-rerun preflight passed")
    return 0


def readiness_command(args: argparse.Namespace) -> int:
    install_path = args.install_path.resolve()
    if not is_default_install_path(install_path):
        raise SystemExit(f"refusing nonstandard install path; use {DEFAULT_INSTALL_PATH}")
    metadata, permissions, signing_errors = metadata_and_permissions(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
    )
    payload = build_readiness_payload(
        metadata=metadata,
        permissions=permissions,
        signing_errors=signing_errors,
        settings=read_startup_settings(),
        login_item=read_login_item_readiness(),
        displays=read_display_readiness(),
        logs=summarize_host_log(args.log_path),
    )
    report = format_readiness_report(payload)
    write_report(args.report, report)
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.report}")
    print(f"Wrote {args.json_report}")
    if payload["result"] != "ready":
        print(report, file=sys.stderr)
        return 2
    print("macOS Host login/headless readiness preflight passed")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install_command(args)
    if args.command == "preflight":
        return preflight_command(args)
    if args.command == "readiness":
        return readiness_command(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
