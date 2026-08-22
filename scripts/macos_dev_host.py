#!/usr/bin/env python3
"""Build, install, and preflight the local macOS development Host bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import package_macos


APP_NAME = package_macos.PRODUCT_NAME
EXECUTABLE_NAME = package_macos.EXECUTABLE_NAME
DEFAULT_INSTALL_PATH = Path("/Applications") / f"{APP_NAME}.app"
DEFAULT_OUTPUT_DIR = package_macos.REPOSITORY_ROOT / ".build" / "dev-macos-host"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "host-signing-and-permissions.txt"
DEFAULT_XCTEST_REPORT_PATH = DEFAULT_OUTPUT_DIR / "xctest-toolchain.txt"
SYSTEM_TCC_DATABASE = Path("/Library/Application Support/com.apple.TCC/TCC.db")
PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS = package_macos.PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS
EXPECTED_BUNDLE_ID = "dev.telemachus.display"
SCREEN_CAPTURE_SERVICES = ("kTCCServiceScreenCapture", "kTCCServiceScreenRecording")
ACCESSIBILITY_SERVICE = "kTCCServiceAccessibility"
ALLOWED_AUTH_VALUE = 2
SYSTEM_SETTINGS_PATH = (
    "System Settings -> Privacy & Security -> Screen & System Audio Recording "
    "and Accessibility"
)
DEFAULT_IDENTITY_REMEDIATION = """Required remediation
--------------------
1. Confirm the configured signing identity is available:
   security find-identity -v -p codesigning | grep '"Vibe Screen Dev"'
2. If it is missing, create a self-signed Code Signing certificate named
   'Vibe Screen Dev' in Keychain Access, or set VIBE_SCREEN_SIGN_IDENTITY to an
   existing stable codesigning identity.
3. Rebuild and install the Host with make baseline-macos-dev-install, grant
   Screen Recording and Accessibility to /Applications/Vibe Screen.app, then
   rerun this preflight.
Ad-hoc signing is intentionally rejected for local device reruns because it
changes the code-signing identity that macOS TCC grants are bound to.
"""


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
class XCTestToolchainStatus:
    developer_dir: str | None
    swift_path: str | None
    swift_version: str | None
    xcodebuild_path: str | None
    xcodebuild_version: str | None
    xctest_path: str | None
    xctest_framework_path: str | None
    path_xcrun_warning: str | None
    errors: tuple[str, ...]


def default_tcc_database() -> Path:
    return Path.home() / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db"


def tcc_database_paths(database_path: Path) -> tuple[Path, ...]:
    default_database = default_tcc_database().resolve()
    resolved = database_path.resolve()
    return (resolved, SYSTEM_TCC_DATABASE) if resolved == default_database else (resolved,)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build/install the local Vibe Screen Host or fail-closed before an Android touch rerun. The tool never modifies TCC."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="build, sign, and install the stable local development Host bundle")
    add_common_options(install, include_sign_identity=True, include_output_dir=True)
    preflight = subparsers.add_parser("preflight", help="fail closed unless the installed Host is stable-signed and authorized")
    add_common_options(preflight, include_sign_identity=True)
    xctest = subparsers.add_parser(
        "xctest-preflight",
        help="fail closed with actionable diagnostics unless full Xcode is selected for SwiftPM XCTest",
    )
    xctest.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_XCTEST_REPORT_PATH,
        help="path for the XCTest toolchain report",
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
        help="repository root whose current HEAD the installed Host must match",
    )
    parser.add_argument(
        "--allow-source-mismatch",
        action="store_true",
        help="record source mismatch but do not fail the preflight; use only for historical fixed-binary reruns",
    )
    parser.add_argument("--tcc-db", type=Path, default=default_tcc_database(), help=argparse.SUPPRESS)


def run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return completed.stdout.strip()


def command_text(command: tuple[str, ...] | list[str] | str) -> str:
    return package_macos.command_text(command)


def timeout_message(command: tuple[str, ...] | list[str] | str, timeout: float) -> str:
    return f"timed out after {timeout:g}s while running {command_text(command)}"


def command_status(
    *command: str,
    timeout: float = PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, timeout_message(command, timeout)
    return completed.returncode, completed.stdout.strip()


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
        run(
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            str(app_path),
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
        details = run(
            "/usr/bin/codesign",
            "-dvvv",
            str(app_path),
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
        requirement_output = run(
            "/usr/bin/codesign",
            "-d",
            "-r-",
            str(app_path),
            timeout=PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as error:
        output = (error.stdout or str(error)).strip()
        raise SystemExit(f"codesign inspection failed for {app_path}: {output}") from error
    except subprocess.TimeoutExpired as error:
        raise SystemExit(
            f"codesign inspection timed out after "
            f"{PREFLIGHT_EXTERNAL_COMMAND_TIMEOUT_SECONDS:g}s while running "
            f"{command_text(error.cmd)}; refusing to treat the installed Host as verified."
        ) from error
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
        source_commit=string_plist_value(plist, package_macos.SOURCE_COMMIT_PLIST_KEY),
        source_tree=string_plist_value(plist, package_macos.SOURCE_TREE_PLIST_KEY),
        source_dirty=bool_plist_value(plist, package_macos.SOURCE_DIRTY_PLIST_KEY),
        binary_sha256=sha256(executable_path),
        authorities=tuple(fields.get("Authority", [])),
        cdhash=fields.get("CDHash") if isinstance(fields.get("CDHash"), str) else None,
        designated_requirement=requirement,
        signature=fields.get("Signature") if isinstance(fields.get("Signature"), str) else None,
        team_identifier=fields.get("TeamIdentifier") if isinstance(fields.get("TeamIdentifier"), str) else None,
        leaf_certificate_hash=parse_leaf_certificate_hash(requirement),
    )


def string_plist_value(plist: dict[str, object], key: str) -> str | None:
    value = plist.get(key)
    return value if isinstance(value, str) and value else None


def bool_plist_value(plist: dict[str, object], key: str) -> bool | None:
    value = plist.get(key)
    return value if isinstance(value, bool) else None


def current_source_identity(source_root: Path) -> package_macos.SourceIdentity:
    return package_macos.collect_source_identity(source_root.resolve())


def collect_xctest_toolchain_status() -> XCTestToolchainStatus:
    developer_dir_status, developer_dir_output = command_status("/usr/bin/xcode-select", "-p")
    developer_dir = developer_dir_output if developer_dir_status == 0 and developer_dir_output else None

    swift_status, swift_path_output = command_status("/usr/bin/xcrun", "--find", "swift")
    swift_path = swift_path_output if swift_status == 0 and swift_path_output else None
    swift_version_status, swift_version_output = command_status("/usr/bin/swift", "--version")
    swift_version = swift_version_output.splitlines()[0] if swift_version_status == 0 and swift_version_output else None

    xcodebuild_status, xcodebuild_path_output = command_status("/usr/bin/xcrun", "--find", "xcodebuild")
    xcodebuild_path = xcodebuild_path_output if xcodebuild_status == 0 and xcodebuild_path_output else None
    xcodebuild_version_status, xcodebuild_version_output = command_status("/usr/bin/xcodebuild", "-version")
    xcodebuild_version = (
        xcodebuild_version_output.replace("\n", "; ")
        if xcodebuild_version_status == 0 and xcodebuild_version_output
        else None
    )
    xctest_status, xctest_path_output = command_status("/usr/bin/xcrun", "--find", "xctest")
    xctest_path = xctest_path_output if xctest_status == 0 and xctest_path_output else None
    xctest_framework_path = find_xctest_framework_path(developer_dir)
    path_xcrun_warning = detect_path_xcrun_wrapper()

    errors: list[str] = []
    if developer_dir is None:
        errors.append(f"xcode-select -p failed: {developer_dir_output or 'no output'}")
    elif developer_dir.endswith("/CommandLineTools"):
        errors.append(
            "active developer directory is Command Line Tools; SwiftPM XCTest for MacHost requires full Xcode"
        )
    elif not developer_dir.endswith("/Contents/Developer"):
        errors.append(f"active developer directory is not a full Xcode Contents/Developer path: {developer_dir}")
    if swift_path is None:
        errors.append(f"xcrun --find swift failed: {swift_path_output or 'no output'}")
    if swift_version is None:
        errors.append(f"swift --version failed: {swift_version_output or 'no output'}")
    if xcodebuild_path is None:
        errors.append(f"xcrun --find xcodebuild failed: {xcodebuild_path_output or 'no output'}")
    if xcodebuild_version is None:
        errors.append(f"xcodebuild -version failed: {xcodebuild_version_output or 'no output'}")
    if xctest_path is None:
        errors.append(f"xcrun --find xctest failed: {xctest_path_output or 'no output'}")
    if developer_dir is not None and xctest_framework_path is None:
        errors.append(f"XCTest.framework not found under active developer directory: {developer_dir}")
    return XCTestToolchainStatus(
        developer_dir=developer_dir,
        swift_path=swift_path,
        swift_version=swift_version,
        xcodebuild_path=xcodebuild_path,
        xcodebuild_version=xcodebuild_version,
        xctest_path=xctest_path,
        xctest_framework_path=xctest_framework_path,
        path_xcrun_warning=path_xcrun_warning,
        errors=tuple(errors),
    )


def find_xctest_framework_path(developer_dir: str | None) -> str | None:
    if developer_dir is None:
        return None
    candidates = (
        Path(developer_dir)
        / "Platforms"
        / "MacOSX.platform"
        / "Developer"
        / "Library"
        / "Frameworks"
        / "XCTest.framework",
        Path(developer_dir) / "Library" / "Developer" / "Frameworks" / "XCTest.framework",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    return None


def detect_path_xcrun_wrapper() -> str | None:
    path_value = os.environ.get("PATH", "")
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "xcrun"
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if resolved != Path("/usr/bin/xcrun"):
            return f"PATH resolves xcrun to {candidate}; preflight uses /usr/bin/xcrun for deterministic diagnostics"
        return None
    return None


def format_xctest_toolchain_report(status: XCTestToolchainStatus) -> str:
    result = "PASS" if not status.errors else "FAIL"
    error_lines = "\n".join(f"- {error}" for error in status.errors) or "(none)"
    return f"""MacHost XCTest toolchain
--------------------------
Status: {result}
Developer directory: {status.developer_dir or 'missing'}
Swift path: {status.swift_path or 'missing'}
Swift version: {status.swift_version or 'missing'}
Xcodebuild path: {status.xcodebuild_path or 'missing'}
Xcodebuild version: {status.xcodebuild_version or 'missing'}
XCTest path: {status.xctest_path or 'missing'}
XCTest.framework: {status.xctest_framework_path or 'missing'}
PATH xcrun warning: {status.path_xcrun_warning or 'none'}

Blocking issues:
{error_lines}

Required remediation
--------------------
Install full Xcode if /Applications/Xcode.app is absent, then select it before
running MacHost XCTest:

sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
xcodebuild -version
make baseline-macos-test

Command Line Tools may build the Host executable, but this repository records
MacHost XCTest as blocked unless full Xcode is selected and xcodebuild resolves.
"""


def xctest_preflight_command(args: argparse.Namespace) -> int:
    status = collect_xctest_toolchain_status()
    report = format_xctest_toolchain_report(status)
    write_report(args.report, report)
    print(f"Wrote {args.report}")
    if status.errors:
        print(report, file=sys.stderr)
        return 2
    print("MacHost XCTest toolchain preflight passed")
    return 0


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
            return PermissionStatus(database_path=str(database_path), rows=rows, readable=True)
        finally:
            connection.close()
    except sqlite3.Error as error:
        return PermissionStatus(database_path=str(database_path), rows=(), readable=False, error=str(error))


def validate_preflight(
    metadata: SigningMetadata,
    permissions: PermissionStatus,
    *,
    install_path: Path,
    expected_sign_identity: str | None = None,
    signing_identity_errors: list[str] | None = None,
    expected_source: package_macos.SourceIdentity | None = None,
    allow_source_mismatch: bool = False,
) -> list[str]:
    errors: list[str] = list(signing_identity_errors or [])
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
    if expected_source is not None and not allow_source_mismatch:
        errors.extend(validate_source_identity(metadata, expected_source))
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


def validate_source_identity(metadata: SigningMetadata, expected_source: package_macos.SourceIdentity) -> list[str]:
    errors: list[str] = []
    if expected_source.dirty:
        errors.append("repository source root is dirty; refusing to treat an installed Host as current-source evidence")
    if metadata.source_commit is None or metadata.source_tree is None or metadata.source_dirty is None:
        errors.append("installed Host does not record its source commit/tree identity")
        return errors
    if metadata.source_dirty:
        errors.append("installed Host was packaged from a dirty source tree")
    if metadata.source_commit != expected_source.commit:
        errors.append(
            f"installed Host source commit {metadata.source_commit} does not match current HEAD {expected_source.commit}"
        )
    if metadata.source_tree != expected_source.tree:
        errors.append(
            f"installed Host source tree {metadata.source_tree} does not match current tree {expected_source.tree}"
        )
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
    metadata: SigningMetadata,
    permissions: PermissionStatus,
    errors: list[str],
    *,
    expected_source: package_macos.SourceIdentity | None = None,
    allow_source_mismatch: bool = False,
) -> str:
    authorities = "\n".join(f"Authority: {authority}" for authority in metadata.authorities)
    if not authorities:
        authorities = "Authority: ad-hoc"
    rows = "\n".join(format_permission_row(row) for row in permissions.rows)
    if not rows:
        rows = "(no matching rows)"
    result = "PASS" if not errors else "FAIL"
    error_lines = "\n".join(f"- {error}" for error in errors) or "(none)"
    expected_commit = expected_source.commit if expected_source else "not checked"
    expected_tree = expected_source.tree if expected_source else "not checked"
    expected_dirty = str(expected_source.dirty).lower() if expected_source else "not checked"
    source_policy = "warning-only" if allow_source_mismatch else "fail-closed"
    return f"""Host bundle
-----------
Path: {metadata.app_path}
Identifier: {metadata.identifier}
Source commit: {metadata.source_commit or 'missing'}
Source tree: {metadata.source_tree or 'missing'}
Source dirty: {'missing' if metadata.source_dirty is None else str(metadata.source_dirty).lower()}
Expected source commit: {expected_commit}
Expected source tree: {expected_tree}
Expected source dirty: {expected_dirty}
Source match policy: {source_policy}
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

{DEFAULT_IDENTITY_REMEDIATION}

Keychain and TCC handling
-------------------------
This tool does not reset Keychain, import certificates, request passwords, update
partition lists, modify TCC.db, or request/override macOS privacy authorization.
It only uses the configured codesign identity and reads TCC.db in read-only mode.
"""


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def metadata_and_permissions(
    install_path: Path,
    tcc_db: Path,
    *,
    expected_sign_identity: str | None = None,
    signing_identity_errors: list[str] | None = None,
    source_root: Path = package_macos.REPOSITORY_ROOT,
    allow_source_mismatch: bool = False,
) -> tuple[SigningMetadata, PermissionStatus, package_macos.SourceIdentity | None, list[str]]:
    metadata = collect_signing_metadata(install_path)
    permissions = query_tcc_rows(EXPECTED_BUNDLE_ID, tcc_database_paths(tcc_db))
    source_identity_errors: list[str] = []
    try:
        expected_source = current_source_identity(source_root)
    except SystemExit as error:
        expected_source = None
        source_identity_errors.append(str(error))
    errors = validate_preflight(
        metadata,
        permissions,
        install_path=install_path,
        expected_sign_identity=expected_sign_identity,
        signing_identity_errors=[*(signing_identity_errors or []), *source_identity_errors],
        expected_source=expected_source,
        allow_source_mismatch=allow_source_mismatch,
    )
    return metadata, permissions, expected_source, errors


def refuse_ad_hoc_identity(sign_identity: str) -> None:
    if sign_identity == "-":
        raise SystemExit(
            "local device reruns require a stable signing identity; refusing --sign-identity -. "
            "Set VIBE_SCREEN_SIGN_IDENTITY to an existing codesigning identity or create "
            "the documented 'Vibe Screen Dev' self-signed identity, then grant permissions "
            "in System Settings."
        )


def collect_signing_identity_errors(sign_identity: str) -> list[str]:
    if sign_identity == "-":
        return [
            "local device reruns require a stable signing identity; refusing --sign-identity - because ad-hoc signatures invalidate macOS privacy grants"
        ]
    try:
        package_macos.resolve_sign_identity(sign_identity)
    except SystemExit as error:
        message = str(error).replace(
            ", or pass '--sign-identity -' for an ad-hoc build. Ad-hoc signing changes the code-signing hash on every rebuild and invalidates macOS Screen Recording/Accessibility grants.",
            ". Ad-hoc signing is not allowed for local device reruns because it changes the code-signing identity that macOS privacy grants are bound to.",
        )
        return [message]
    return []


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
    metadata, permissions, expected_source, errors = metadata_and_permissions(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    report = format_report(
        metadata,
        permissions,
        errors,
        expected_source=expected_source,
        allow_source_mismatch=args.allow_source_mismatch,
    )
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
    identity_errors = collect_signing_identity_errors(args.sign_identity)
    metadata, permissions, expected_source, errors = metadata_and_permissions(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        signing_identity_errors=identity_errors,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    report = format_report(
        metadata,
        permissions,
        errors,
        expected_source=expected_source,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    write_report(args.report, report)
    print(f"Wrote {args.report}")
    if errors:
        print(report, file=sys.stderr)
        return 2
    print("macOS Host touch-rerun preflight passed")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install_command(args)
    if args.command == "preflight":
        return preflight_command(args)
    if args.command == "xctest-preflight":
        return xctest_preflight_command(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
