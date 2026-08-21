#!/usr/bin/env python3
"""Disconnect an active coturn allocation by its Authority allocation id.

``coturn_reconcile.py`` invokes this executor (or another idempotent command)
for unauthorized or conflicting active source allocations. It receives the
allocation identity through environment variables, looks up the matching coturn
session(s) through the admin CLI, and forcefully cancels them.

The executor is idempotent: if the allocation is already gone, it exits
successfully. Any failure to enumerate or cancel sessions fails closed with a
non-zero exit code so the reconcile run is not silently marked complete.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

DEFAULT_CLI_HOST = "127.0.0.1"
DEFAULT_CLI_PORT = 5766
DEFAULT_CLI_PASSWORD_ENV = "VIBE_COTURN_CLI_PASSWORD"
DEFAULT_CLI_PASSWORD_FILE = "/run/secrets/coturn_cli_password"
MAX_RESPONSE_BYTES = 1024 * 1024

SESSION_HEADER = re.compile(r"^\s*\d+\)\s+id=(\S+),\s+user\s+<([^>]+)>:")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class DisconnectError(RuntimeError):
    """Raised when the disconnect executor cannot safely terminate an allocation."""


@dataclass(frozen=True)
class Settings:
    cli_host: str
    cli_port: int
    cli_password: str
    allocation_id: str
    source_id: str
    reason: str
    timeout_seconds: float


def _fail(message: str) -> None:
    raise DisconnectError(message)


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
            raise DisconnectError(f"cannot read coturn CLI password file: {exc}") from exc
    if len(env_value) < 16:
        _fail(f"{env_name} or --cli-password-file must contain at least 16 characters")
    return env_value


def _validate_identifier(value: str, field: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _validate_loopback_host(value: str) -> str:
    if value == "localhost":
        return value
    try:
        address = ip_address(value)
    except ValueError as exc:
        raise DisconnectError("coturn CLI host must be a loopback IP address or localhost") from exc
    if not address.is_loopback:
        _fail("coturn CLI host must be loopback-only")
    return value


def _cli_command(password: str, command: str, host: str, port: int, timeout: float) -> str:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise DisconnectError(f"coturn CLI connection failed: {exc}") from exc
    try:
        sock.settimeout(timeout)
        _read_until(sock, b"Enter password:")
        sock.sendall(password.encode("utf-8") + b"\n")
        _read_until(sock, b"> ")
        sock.sendall(command.encode("utf-8") + b"\n")
        return _read_until(sock, b"> ").decode("utf-8", errors="replace")
    except OSError as exc:
        raise DisconnectError(f"coturn CLI command failed: {exc}") from exc
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
    if data.endswith(marker):
        data = data[: -len(marker)]
    return data


def _find_session_ids(ps_output: str, allocation_id: str) -> list[str]:
    session_ids: list[str] = []
    for line in ps_output.splitlines():
        header = SESSION_HEADER.match(line)
        if not header:
            continue
        session_id, username = header.group(1), header.group(2)
        parts = username.split(":")
        if len(parts) == 4 and parts[3] == allocation_id:
            session_ids.append(session_id)
    return session_ids


def disconnect(settings: Settings) -> list[str]:
    ps_output = _cli_command(
        settings.cli_password, "ps", settings.cli_host, settings.cli_port, settings.timeout_seconds
    )
    session_ids = _find_session_ids(ps_output, settings.allocation_id)
    cancelled: list[str] = []
    for session_id in session_ids:
        response = _cli_command(
            settings.cli_password,
            f"cs {session_id}",
            settings.cli_host,
            settings.cli_port,
            settings.timeout_seconds,
        )
        if "error" in response.lower() or "fail" in response.lower():
            _fail(f"coturn failed to cancel session {session_id}: {response.strip()}")
        cancelled.append(session_id)
    return cancelled


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-host", default=DEFAULT_CLI_HOST, help="coturn admin CLI host")
    parser.add_argument("--cli-port", type=int, default=DEFAULT_CLI_PORT, help="coturn admin CLI port")
    parser.add_argument("--cli-password-env", default=DEFAULT_CLI_PASSWORD_ENV, help="environment variable holding the coturn admin CLI password")
    parser.add_argument("--cli-password-file", type=Path, help="file holding the coturn admin CLI password")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="socket and CLI command timeout")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    allocation_id = os.environ.get("VIBE_COTURN_DISCONNECT_ALLOCATION_ID", "")
    source_id = os.environ.get("VIBE_COTURN_DISCONNECT_SOURCE_ID", "")
    reason = os.environ.get("VIBE_COTURN_DISCONNECT_REASON", "")
    return Settings(
        cli_host=_validate_loopback_host(args.cli_host),
        cli_port=args.cli_port,
        cli_password=_load_cli_password(args.cli_password_env, args.cli_password_file),
        allocation_id=_validate_identifier(allocation_id, "VIBE_COTURN_DISCONNECT_ALLOCATION_ID"),
        source_id=_validate_identifier(source_id, "VIBE_COTURN_DISCONNECT_SOURCE_ID"),
        reason=reason,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        settings = settings_from_args(build_parser().parse_args(argv))
        cancelled = disconnect(settings)
        print(
            f"disconnected allocation {settings.allocation_id} "
            f"(reason={settings.reason}, sessions={len(cancelled)})",
            flush=True,
        )
        return 0
    except DisconnectError as exc:
        print(f"coturn-disconnect: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
