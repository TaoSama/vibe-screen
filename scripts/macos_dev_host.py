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
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import package_macos


APP_NAME = package_macos.PRODUCT_NAME
EXECUTABLE_NAME = package_macos.EXECUTABLE_NAME
DEFAULT_INSTALL_PATH = Path("/Applications") / f"{APP_NAME}.app"
DEFAULT_OUTPUT_DIR = package_macos.REPOSITORY_ROOT / ".build" / "dev-macos-host"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "host-signing-and-permissions.txt"
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
        description="Build/install the local Vibe Screen Host or fail-closed before an Android touch rerun. The tool never modifies TCC."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="build, sign, and install the stable local development Host bundle")
    add_common_options(install, include_sign_identity=True, include_output_dir=True)
    preflight = subparsers.add_parser("preflight", help="fail closed unless the installed Host is stable-signed and authorized")
    add_common_options(preflight, include_sign_identity=True)
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
    return "\n".join(redacted_lines)


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


def query_tcc_database(bundle_id: str, database_path: Path) -> PermissionStatus:
    report_label = tcc_database_report_label(database_path)
    if not database_path.exists():
        return PermissionStatus(database_path=report_label, rows=(), readable=False, error="TCC database not found")
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
        return PermissionStatus(database_path=report_label, rows=(), readable=False, error=str(error))


def inspect_listener(port: int) -> ListenerStatus:
    try:
        output = run("/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN")
    except subprocess.CalledProcessError as error:
        detail = (error.stdout or "").strip()
        return ListenerStatus(port=port, observed=False, output=detail, error="listener not observed")
    output = redact_lsof_user_columns(output)
    lines = [line for line in output.splitlines() if line.strip()]
    observed = any(f":{port}" in line and "LISTEN" in line for line in lines)
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
    metadata: SigningMetadata,
    permissions: PermissionStatus,
    errors: list[str],
    *,
    source_identity: package_macos.SourceIdentity | None = None,
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
Source commit: {metadata.source_commit or 'missing'}
Source tree: {metadata.source_tree or 'missing'}
Source dirty: {metadata.source_dirty if metadata.source_dirty is not None else 'missing'}
Current source commit: {source_identity.commit if source_identity else 'not checked'}
Current source tree: {source_identity.tree if source_identity else 'not checked'}
Current source dirty: {source_identity.dirty if source_identity else 'not checked'}
Source mismatch allowed: {allow_source_mismatch}
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


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def missing_permission_status(error: str) -> PermissionStatus:
    return PermissionStatus(database_path="not inspected", rows=(), readable=False, error=error)


def inspect_host_without_throwing(
    install_path: Path,
    tcc_db: Path,
    *,
    expected_sign_identity: str | None = None,
    source_root: Path = package_macos.REPOSITORY_ROOT,
    allow_source_mismatch: bool = False,
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
    else:
        try:
            package_macos.resolve_sign_identity(expected_sign_identity or package_macos.DEFAULT_SIGN_IDENTITY)
        except SystemExit as error:
            errors.append(str(error))
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


def build_readiness_document(
    inspection: HostInspection,
    listener: ListenerStatus,
    entitlements: EntitlementStatus,
) -> dict[str, Any]:
    shared_ready = readiness_prerequisites_ready(inspection.errors, listener)
    controller_ready = shared_ready and entitlements.virtual_hid
    blockers = list(inspection.errors)
    if not listener.observed:
        blockers.append(f"Host listener is not observed on TCP port {listener.port}")
    if not entitlements.virtual_hid:
        blockers.append(f"Host is missing {VIRTUAL_HID_ENTITLEMENT} entitlement")
    return {
        "schema_version": "vibescreen.host-readiness/v1",
        "kind": "macos_host_shared_prerequisite_readiness",
        "status": "ready" if not blockers else "blocked",
        "signing_tcc_status": "ready" if not inspection.errors else "blocked",
        "listener_status": "ready" if listener.observed else "blocked",
        "virtual_hid_status": "ready" if entitlements.virtual_hid else "blocked",
        "can_start_host_rss_gate": shared_ready,
        "can_start_trusted_lan_gate": shared_ready,
        "can_start_native_hid_gate": shared_ready,
        "can_start_stylus_gate": shared_ready,
        "can_start_hardware_keyboard_gate": shared_ready,
        "can_start_controller_runtime_gate": controller_ready,
        "can_start_headless_login_gate": shared_ready,
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
) -> tuple[SigningMetadata, package_macos.SourceIdentity, PermissionStatus, list[str]]:
    metadata = collect_signing_metadata(install_path)
    source_identity = current_source_identity(source_root)
    permissions = query_tcc_rows(EXPECTED_BUNDLE_ID, tcc_database_paths(tcc_db))
    errors = validate_preflight(
        metadata,
        permissions,
        install_path=install_path,
        expected_sign_identity=expected_sign_identity,
        source_identity=source_identity,
        allow_source_mismatch=allow_source_mismatch,
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
    packaged_app = package_dev_app(args.output_dir, args.sign_identity)
    safe_replace_app(packaged_app, install_path, EXPECTED_BUNDLE_ID)
    metadata, source_identity, permissions, errors = metadata_and_permissions(
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
        source_identity=source_identity,
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
    refuse_ad_hoc_identity(args.sign_identity)
    package_macos.resolve_sign_identity(args.sign_identity)
    metadata, source_identity, permissions, errors = metadata_and_permissions(
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
        source_identity=source_identity,
        allow_source_mismatch=args.allow_source_mismatch,
    )
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
    inspection = inspect_host_without_throwing(
        install_path,
        args.tcc_db,
        expected_sign_identity=args.sign_identity,
        source_root=args.source_root,
        allow_source_mismatch=args.allow_source_mismatch,
    )
    listener = inspect_listener(args.port)
    entitlements = inspect_entitlements(install_path)
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
partition lists, modify TCC.db, or request/override macOS privacy authorization.
It only uses the configured codesign identity and reads TCC.db in read-only mode.
"""
    write_report(args.report, report)
    document = build_readiness_document(inspection, listener, entitlements)
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
    if args.command == "install":
        return install_command(args)
    if args.command == "preflight":
        return preflight_command(args)
    if args.command == "readiness":
        return readiness_command(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
