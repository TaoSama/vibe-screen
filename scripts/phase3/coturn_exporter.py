#!/usr/bin/env python3
"""Export active coturn allocations as a structured reconciliation snapshot.

This script connects to the coturn admin CLI, lists active sessions, and
produces the JSON snapshot that ``coturn_reconcile.py`` submits to Authority.
The TURN username is ``expiry:device_id:session_id:allocation_id``; the exporter
parses that principal to populate the Authority ledger fields. Byte counters come from
coturn's per-session usage line.

The exporter is read-only: it never modifies coturn state. Active-allocation
disconnection is the responsibility of the separate disconnect executor that
``coturn_reconcile.py`` invokes for unauthorized or conflicting allocations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any

DEFAULT_CLI_HOST = "127.0.0.1"
DEFAULT_CLI_PORT = 5766
DEFAULT_CLI_PASSWORD_ENV = "VIBE_COTURN_CLI_PASSWORD"
DEFAULT_CLI_PASSWORD_FILE = "/run/secrets/coturn_cli_password"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ALLOCATIONS = 10_000

SESSION_HEADER = re.compile(r"^\s*\d+\)\s+id=(\S+),\s+user\s+<([^>]+)>:")
USAGE_LINE = re.compile(r"usage:\s*rp=(\d+),\s*rb=(\d+),\s*sp=(\d+),\s*sb=(\d+)")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ExportError(RuntimeError):
    """Raised when the exporter cannot produce a safe snapshot."""


@dataclass(frozen=True)
class Settings:
    cli_host: str
    cli_port: int
    cli_password: str
    source_id: str
    timeout_seconds: float


def _fail(message: str) -> None:
    raise ExportError(message)


def _load_cli_password(env_name: str, password_file: Path | None) -> str:
    env_value = os.environ.get(env_name, "")
    if env_value and password_file is not None:
        _fail(f"{env_name} and --cli-password-file cannot both be set")
    if not env_value and password_file is None:
        default_password_file = Path(DEFAULT_CLI_PASSWORD_FILE)
        if default_password_file.exists():
            password_file = default_password_file
    if password_file is not None:
        try:
            env_value = password_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ExportError(f"cannot read coturn CLI password file: {exc}") from exc
    if len(env_value) < 16:
        _fail(f"{env_name} or --cli-password-file must contain at least 16 characters")
    return env_value


def _validate_loopback_host(value: str) -> str:
    if value == "localhost":
        return value
    try:
        address = ip_address(value)
    except ValueError as exc:
        raise ExportError("coturn CLI host must be a loopback IP address or localhost") from exc
    if not address.is_loopback:
        _fail("coturn CLI host must be loopback-only")
    return value


def _validate_identifier(value: str, field: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _parse_username(username: str) -> tuple[str, str, str]:
    """Return (device_id, session_id, allocation_id) from a TURN username."""
    parts = username.split(":")
    if len(parts) != 4:
        _fail(
            f"TURN username {username!r} must have the form "
            "expiry:device_id:session_id:allocation_id"
        )
    expiry, device_id, session_id, allocation_id = parts
    if not expiry.isdigit():
        _fail(f"TURN username expiry {expiry!r} is not numeric")
    return (
        _validate_identifier(device_id, "device_id"),
        _validate_identifier(session_id, "session_id"),
        _validate_identifier(allocation_id, "allocation_id"),
    )


def _cli_command(password: str, command: str, host: str, port: int, timeout: float) -> str:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise ExportError(f"coturn CLI connection failed: {exc}") from exc
    try:
        sock.settimeout(timeout)
        # Read the password prompt.
        _read_until(sock, b"Enter password:")
        sock.sendall(password.encode("utf-8") + b"\n")
        # Read until the command prompt.
        _read_until(sock, b"> ")
        sock.sendall(command.encode("utf-8") + b"\n")
        response = _read_until(sock, b"> ")
        return response.decode("utf-8", errors="replace")
    except OSError as exc:
        raise ExportError(f"coturn CLI command failed: {exc}") from exc
    finally:
        sock.close()


def _read_until(sock: socket.socket, marker: bytes) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            _fail("coturn CLI response exceeded maximum size")
        if marker in b"".join(chunks):
            break
    data = b"".join(chunks)
    # Strip the trailing prompt marker.
    if data.endswith(marker):
        data = data[: -len(marker)]
    return data


def _parse_sessions(ps_output: str) -> list[dict[str, Any]]:
    # A single Vibe Screen allocation may open several coturn sessions (for
    # example one ICE transport per media stream). Aggregate them by
    # allocation_id so Authority receives one ledger entry per allocation.
    by_allocation: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in ps_output.splitlines():
        header = SESSION_HEADER.match(line)
        if header:
            if current is not None:
                _merge_allocation(by_allocation, current)
            coturn_session_id, username = header.group(1), header.group(2)
            device_id, session_id, allocation_id = _parse_username(username)
            current = {
                "allocation_id": allocation_id,
                "device_id": device_id,
                "session_id": session_id,
                "ingress_bytes": 0,
                "egress_bytes": 0,
                "sequence": 0,
                "closed": False,
            }
            continue
        if current is None:
            continue
        usage = USAGE_LINE.search(line)
        if usage:
            received_bytes = int(usage.group(2))
            sent_bytes = int(usage.group(4))
            current["ingress_bytes"] = received_bytes
            current["egress_bytes"] = sent_bytes
            # Monotonic per-allocation sequence derived from total transferred
            # bytes so Authority can reject stale or out-of-order snapshots.
            current["sequence"] = received_bytes + sent_bytes
    if current is not None:
        _merge_allocation(by_allocation, current)
    return list(by_allocation.values())


def _merge_allocation(by_allocation: dict[str, dict[str, Any]], entry: dict[str, Any]) -> None:
    allocation_id = entry["allocation_id"]
    existing = by_allocation.get(allocation_id)
    if existing is None:
        entry["sequence"] = max(1, entry["ingress_bytes"] + entry["egress_bytes"])
        by_allocation[allocation_id] = entry
        return
    if existing["device_id"] != entry["device_id"] or existing["session_id"] != entry["session_id"]:
        _fail(f"allocation_id {allocation_id!r} maps to multiple device/session principals")
    existing["ingress_bytes"] += entry["ingress_bytes"]
    existing["egress_bytes"] += entry["egress_bytes"]
    existing["sequence"] = max(1, existing["ingress_bytes"] + existing["egress_bytes"])


def export_snapshot(settings: Settings) -> dict[str, Any]:
    ps_output = _cli_command(settings.cli_password, "ps", settings.cli_host, settings.cli_port, settings.timeout_seconds)
    allocations = _parse_sessions(ps_output)
    if len(allocations) > MAX_ALLOCATIONS:
        _fail(f"coturn reported more than {MAX_ALLOCATIONS} active allocations")
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "source_id": _validate_identifier(settings.source_id, "source_id"),
        "observed_at": observed_at,
        "allocations": allocations,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True, help="coturn node identifier registered with Authority")
    parser.add_argument("--cli-host", default=DEFAULT_CLI_HOST, help="coturn admin CLI host")
    parser.add_argument("--cli-port", type=int, default=DEFAULT_CLI_PORT, help="coturn admin CLI port")
    parser.add_argument("--cli-password-env", default=DEFAULT_CLI_PASSWORD_ENV, help="environment variable holding the coturn admin CLI password")
    parser.add_argument("--cli-password-file", type=Path, help="file holding the coturn admin CLI password")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="socket and CLI command timeout")
    parser.add_argument("--output", type=Path, help="write the snapshot JSON to this path instead of stdout")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(
        cli_host=_validate_loopback_host(args.cli_host),
        cli_port=args.cli_port,
        cli_password=_load_cli_password(args.cli_password_env, args.cli_password_file),
        source_id=args.source_id,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        settings = settings_from_args(args)
        snapshot = export_snapshot(settings)
        encoded = json.dumps(snapshot, sort_keys=True)
        if args.output is not None:
            args.output.write_text(encoded + "\n", encoding="utf-8")
        else:
            print(encoded, flush=True)
        return 0
    except ExportError as exc:
        print(f"coturn-exporter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
