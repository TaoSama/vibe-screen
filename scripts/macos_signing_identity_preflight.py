#!/usr/bin/env python3
"""Collect read-only macOS codesigning identity readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import package_macos
import macos_dev_host


BLOCKED_EXIT = 2
DEFAULT_OUTPUT_DIR = package_macos.REPOSITORY_ROOT / ".build" / "dev-macos-host-signing-identity"


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    output_line_count: int
    stderr: str
    raw_output: str = ""


@dataclass(frozen=True)
class SigningIdentity:
    sha1: str
    name: str


@dataclass(frozen=True)
class SigningIdentityPreflight:
    created_at: str
    requested_identity: str
    sign_identity_env: str | None
    status: str
    valid_identity_count: int | None
    matching_identities: list[SigningIdentity]
    installed_host: dict[str, object]
    blockers: list[str]
    command: CommandResult | None
    next_steps: list[str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record whether the local keychain has exactly one stable codesign "
            "identity for evidence-grade Vibe Screen Host builds. This tool is "
            "read-only and never changes Keychain or TCC state."
        )
    )
    parser.add_argument(
        "--identity",
        default=os.environ.get(package_macos.SIGN_IDENTITY_ENV, package_macos.DEFAULT_SIGN_IDENTITY),
        help=(
            f"codesign identity to require; defaults to ${package_macos.SIGN_IDENTITY_ENV} "
            f"or '{package_macos.DEFAULT_SIGN_IDENTITY}'"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory for JSON and Markdown evidence",
    )
    parser.add_argument(
        "--host-app",
        type=Path,
        default=macos_dev_host.DEFAULT_INSTALL_PATH,
        help="installed Host .app to inspect without launching it",
    )
    parser.add_argument(
        "--tcc-db",
        type=Path,
        default=macos_dev_host.default_tcc_database(),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_security_find_identity() -> CommandResult:
    argv = ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"]
    try:
        completed = subprocess.run(argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return CommandResult(argv=argv, returncode=127, output_line_count=0, stderr="/usr/bin/security not found")
    combined_output = completed.stdout + completed.stderr
    return CommandResult(
        argv=argv,
        returncode=completed.returncode,
        output_line_count=len(combined_output.splitlines()),
        stderr=completed.stderr.strip(),
        raw_output=combined_output,
    )


def parse_identities(output: str) -> tuple[list[SigningIdentity], int | None]:
    identities: list[SigningIdentity] = []
    valid_identity_count: int | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        identity_match = re.match(r'^\d+\)\s+([0-9A-Fa-f]{40})\s+"(.+)"$', line)
        if identity_match:
            identities.append(SigningIdentity(sha1=identity_match.group(1).upper(), name=identity_match.group(2)))
            continue
        count_match = re.match(r"^(\d+) valid identities found$", line)
        if count_match:
            valid_identity_count = int(count_match.group(1))
    return identities, valid_identity_count


def build_next_steps(identity: str, blockers: Sequence[str]) -> list[str]:
    if not blockers:
        return [
            "Run make baseline-macos-dev-install to build and install /Applications/Vibe Screen.app with this identity.",
            "Grant Screen Recording and Accessibility to /Applications/Vibe Screen.app, relaunch it, then run make baseline-macos-touch-preflight.",
        ]
    steps = [
        f"Create a self-signed Code Signing certificate named {identity} in Keychain Access, or set VIBE_SCREEN_SIGN_IDENTITY to one existing stable codesign identity.",
        f"Confirm the selected identity with: security find-identity -v -p codesigning | grep '\"{identity}\"'.",
        "Run make baseline-macos-dev-install, grant Screen Recording and Accessibility to /Applications/Vibe Screen.app, relaunch it, then run make baseline-macos-touch-preflight.",
    ]
    if any("duplicate" in blocker for blocker in blockers):
        steps.insert(1, f"Remove or rename duplicate {identity} certificates so one leaf certificate hash is selected deterministically.")
    return steps


def tcc_rows_to_dicts(rows: Sequence[macos_dev_host.TCCRow]) -> list[dict[str, int | str | None]]:
    return [
        {
            "service": row.service,
            "client": row.client,
            "client_type": row.client_type,
            "auth_value": row.auth_value,
            "auth_reason": row.auth_reason,
            "last_modified": row.last_modified,
        }
        for row in rows
    ]


def sanitize_tcc_error(message: str | None) -> str | None:
    if message is None:
        return None
    sanitized = message.replace(str(macos_dev_host.default_tcc_database()), "current-user TCC database")
    sanitized = sanitized.replace(str(macos_dev_host.SYSTEM_TCC_DATABASE), "system TCC database")
    return sanitized


def tcc_interpretation(permissions: macos_dev_host.PermissionStatus) -> str:
    error = sanitize_tcc_error(permissions.error)
    if not permissions.readable:
        return f"unverified ({error})"
    screen = "allowed" if permissions.is_allowed(macos_dev_host.SCREEN_CAPTURE_SERVICES) else "not allowed"
    accessibility = "allowed" if permissions.is_allowed((macos_dev_host.ACCESSIBILITY_SERVICE,)) else "not allowed"
    if error:
        return f"Screen Recording {screen}; Accessibility {accessibility}; read warning: {error}."
    return f"Screen Recording {screen}; Accessibility {accessibility}."


def collect_installed_host(host_app: Path, tcc_db: Path) -> dict[str, object]:
    host: dict[str, object] = {
        "path": str(host_app),
        "inspected": False,
        "error": None,
        "tcc_database_scope": (
            "default current-user plus system databases"
            if tcc_db == macos_dev_host.default_tcc_database()
            else "custom TCC database"
        ),
    }
    try:
        metadata = macos_dev_host.collect_signing_metadata(host_app)
        host.update(
            {
                "inspected": True,
                "identifier": metadata.identifier,
                "identity": metadata.identity_name,
                "authorities": list(metadata.authorities),
                "team_identifier": metadata.team_identifier,
                "certificate_sha1": metadata.leaf_certificate_hash,
                "cdhash": metadata.cdhash,
                "binary_sha256": metadata.binary_sha256,
                "designated_requirement": metadata.designated_requirement,
                "is_ad_hoc": metadata.is_ad_hoc,
            }
        )
    except SystemExit as error:
        host["error"] = str(error)
    permissions = macos_dev_host.query_tcc_rows(macos_dev_host.EXPECTED_BUNDLE_ID, macos_dev_host.tcc_database_paths(tcc_db))
    host.update(
        {
            "tcc_readable": permissions.readable,
            "tcc_error": sanitize_tcc_error(permissions.error),
            "tcc_interpretation": tcc_interpretation(permissions),
            "tcc_rows": tcc_rows_to_dicts(permissions.rows),
        }
    )
    return host


def collect_preflight(
    identity: str,
    *,
    host_app: Path = macos_dev_host.DEFAULT_INSTALL_PATH,
    tcc_db: Path = macos_dev_host.default_tcc_database(),
    created_at: str | None = None,
) -> SigningIdentityPreflight:
    result = run_security_find_identity()
    combined_output = result.raw_output or result.stderr
    identities, valid_identity_count = parse_identities(combined_output)
    matches = [candidate for candidate in identities if candidate.name == identity]
    installed_host = collect_installed_host(host_app, tcc_db)
    blockers: list[str] = []
    if result.returncode != 0:
        blockers.append(f"security find-identity failed with exit code {result.returncode}")
    if not matches:
        blockers.append(f"codesign identity '{identity}' not found in the keychain")
    elif len(matches) > 1:
        blockers.append(f"duplicate codesign identities named '{identity}' found in the keychain")
    status = "pass" if not blockers else "blocked"
    return SigningIdentityPreflight(
        created_at=created_at or utc_now(),
        requested_identity=identity,
        sign_identity_env=os.environ.get(package_macos.SIGN_IDENTITY_ENV),
        status=status,
        valid_identity_count=valid_identity_count,
        matching_identities=matches,
        installed_host=installed_host,
        blockers=blockers,
        command=result,
        next_steps=build_next_steps(identity, blockers),
    )


def render_markdown(report: SigningIdentityPreflight) -> str:
    blockers = "\n".join(f"- {blocker}" for blocker in report.blockers) or "- none"
    if report.matching_identities:
        identities = "\n".join(f"- {item.name} sha1 {item.sha1}" for item in report.matching_identities)
    else:
        identities = "- none"
    next_steps = "\n".join(f"{index}. {step}" for index, step in enumerate(report.next_steps, start=1))
    command = " ".join(report.command.argv) if report.command else "not run"
    host = report.installed_host
    host_lines = [
        f"- Path: {host.get('path')}",
        f"- Inspected: {str(host.get('inspected')).lower()}",
    ]
    if host.get("error"):
        host_lines.append(f"- Error: {host.get('error')}")
    for key, label in (
        ("identifier", "Identifier"),
        ("identity", "Identity"),
        ("certificate_sha1", "Certificate SHA-1"),
        ("cdhash", "CDHash"),
        ("binary_sha256", "Binary SHA-256"),
        ("team_identifier", "TeamIdentifier"),
        ("tcc_interpretation", "TCC interpretation"),
    ):
        if host.get(key) is not None:
            host_lines.append(f"- {label}: {host.get(key)}")
    host_summary = "\n".join(host_lines)
    return f"""# macOS signing identity preflight

Status: {report.status}
Created: {report.created_at}

## Requested identity

- Name: {report.requested_identity}
- Environment override: {report.sign_identity_env or 'not set'}
- Valid codesigning identities reported by Keychain: {report.valid_identity_count if report.valid_identity_count is not None else 'unknown'}

## Matching identities

{identities}

## Blockers

{blockers}

## Installed Host snapshot

{host_summary}

## Next steps

{next_steps}

## Command

    {command}

This preflight is read-only. It does not import certificates, change Keychain
ACLs, install or sign the Host, modify TCC.db, call tccutil, or grant macOS
privacy permissions. Passing it only proves the requested stable codesigning
identity is selectable; Android/macOS device gates still require a matching
installed Host bundle, Screen Recording, Accessibility, and live device evidence.
"""


def write_reports(output_dir: Path, report: SigningIdentityPreflight) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    if payload.get("command"):
        payload["command"].pop("raw_output", None)
    (output_dir / "signing-identity-preflight.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = collect_preflight(args.identity, host_app=args.host_app, tcc_db=args.tcc_db)
    write_reports(args.output_dir, report)
    print(f"macOS signing identity preflight: {report.status}")
    print(f"wrote {args.output_dir / 'signing-identity-preflight.json'}")
    print(f"wrote {args.output_dir / 'README.md'}")
    if report.blockers:
        for blocker in report.blockers:
            print(f"blocked: {blocker}", file=sys.stderr)
        return BLOCKED_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
