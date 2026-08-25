#!/usr/bin/env python3
"""Export and disconnect coturn allocations through the loopback CLI.

The TURN REST username is not the Authority allocation ID. Production use must
therefore provide the strict allocation registry written by vibe-relay so this
helper can bind Authority allocation IDs to coturn sessions. Missing or
ambiguous bindings fail closed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from typing import Any, Callable, NoReturn, Sequence


IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
REST_USERNAME = re.compile(r"^[0-9]{1,20}:[A-Za-z0-9_.-]{1,128}$")
CLI_PASSWORD = re.compile(r"^[A-Za-z0-9_.:@%+=,-]{32,}$")
SESSION_HEADER = re.compile(r"\bid=([A-Za-z0-9_.-]{1,128}),\s*user <([^>]*)>:")
USAGE_LINE = re.compile(r"\busage:\s*rp=([0-9]+),\s*rb=([0-9]+),\s*sp=([0-9]+),\s*sb=([0-9]+)")
MAX_SIGNED_INT64 = (1 << 63) - 1
MAX_CLI_OUTPUT_BYTES = 1024 * 1024
DEFAULT_CLI_PASSWORD_ENV = "VIBE_COTURN_CLI_PASSWORD"
DEFAULT_CLI_PASSWORD_FILE_ENV = "VIBE_COTURN_CLI_PASSWORD_FILE"
DEFAULT_REGISTRY_ENV = "VIBE_COTURN_ALLOCATION_REGISTRY"
DEFAULT_SEQUENCE_STATE_ENV = "VIBE_COTURN_SEQUENCE_STATE"
DEFAULT_SOURCE_ID_ENV = "VIBE_COTURN_SOURCE_ID"
REGISTRY_FIELDS = frozenset({"source_id", "allocations"})
REGISTRY_ALLOCATION_FIELDS = frozenset(
    {"allocation_id", "device_id", "session_id", "username", "coturn_session_id"}
)


class CoturnControlError(RuntimeError):
    """Raised when coturn control cannot produce a safe result."""


@dataclass(frozen=True)
class RegistryAllocation:
    allocation_id: str
    device_id: str
    session_id: str
    username: str
    coturn_session_id: str | None = None


@dataclass(frozen=True)
class Registry:
    source_id: str
    allocations: tuple[RegistryAllocation, ...]


@dataclass(frozen=True)
class CoturnSession:
    coturn_session_id: str
    username: str
    received_bytes: int
    sent_bytes: int


@dataclass(frozen=True)
class CLISettings:
    host: str
    port: int
    password: str
    timeout_seconds: float


def _fail(message: str) -> NoReturn:
    raise CoturnControlError(message)


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _validate_username(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REST_USERNAME.fullmatch(value):
        _fail(f"{field} must be a TURN REST username '<expiry>:<device-id>'")
    expiry_raw, device_id = value.split(":", 1)
    try:
        expiry = int(expiry_raw)
    except ValueError as exc:
        raise CoturnControlError(f"{field} has an invalid expiry") from exc
    if expiry <= 0 or expiry > MAX_SIGNED_INT64:
        _fail(f"{field} expiry is outside the supported range")
    _validate_identifier(device_id, f"{field} device id")
    return value


def _validate_uint(value: int, field: str) -> int:
    if value < 0 or value > MAX_SIGNED_INT64:
        _fail(f"{field} must be from 0 through {MAX_SIGNED_INT64}")
    return value


def _parse_timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CoturnControlError("--observed-at must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail("--observed-at must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _registry_path(path: Path | None) -> Path:
    if path is not None:
        return path
    env_value = os.environ.get(DEFAULT_REGISTRY_ENV, "")
    if not env_value:
        _fail(f"--registry or {DEFAULT_REGISTRY_ENV} is required")
    return Path(env_value)


def _sequence_state_path(path: Path | None) -> Path | None:
    if path is not None:
        return path
    env_value = os.environ.get(DEFAULT_SEQUENCE_STATE_ENV, "")
    if not env_value:
        return None
    return Path(env_value)


def _source_id(value: str | None) -> str:
    if value:
        return _validate_identifier(value, "source_id")
    env_value = os.environ.get(DEFAULT_SOURCE_ID_ENV, "")
    if not env_value:
        _fail(f"--source-id or {DEFAULT_SOURCE_ID_ENV} is required")
    return _validate_identifier(env_value, DEFAULT_SOURCE_ID_ENV)


def load_registry(path: Path, expected_source_id: str | None = None) -> Registry:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoturnControlError(f"cannot read allocation registry: {exc}") from exc
    if not isinstance(raw, dict):
        _fail("allocation registry must be a JSON object")
    extra = set(raw) - REGISTRY_FIELDS
    if extra:
        _fail(f"allocation registry contains unknown fields: {', '.join(sorted(extra))}")
    source_id = _validate_identifier(raw.get("source_id"), "source_id")
    if expected_source_id is not None and source_id != expected_source_id:
        _fail("allocation registry source_id does not match the requested source")
    raw_allocations = raw.get("allocations")
    if not isinstance(raw_allocations, list):
        _fail("allocations must be an array")

    allocations: list[RegistryAllocation] = []
    seen_allocations: set[str] = set()
    seen_coturn_sessions: set[str] = set()
    for index, allocation in enumerate(raw_allocations):
        if not isinstance(allocation, dict):
            _fail(f"allocations[{index}] must be an object")
        extra = set(allocation) - REGISTRY_ALLOCATION_FIELDS
        if extra:
            _fail(f"allocations[{index}] contains unknown fields: {', '.join(sorted(extra))}")
        allocation_id = _validate_identifier(
            allocation.get("allocation_id"), f"allocations[{index}].allocation_id"
        )
        if allocation_id in seen_allocations:
            _fail(f"duplicate allocation_id in registry: {allocation_id}")
        seen_allocations.add(allocation_id)
        coturn_session_id = allocation.get("coturn_session_id")
        if coturn_session_id is not None:
            coturn_session_id = _validate_identifier(
                coturn_session_id, f"allocations[{index}].coturn_session_id"
            )
            if coturn_session_id in seen_coturn_sessions:
                _fail(f"duplicate coturn_session_id in registry: {coturn_session_id}")
            seen_coturn_sessions.add(coturn_session_id)
        device_id = _validate_identifier(
            allocation.get("device_id"), f"allocations[{index}].device_id"
        )
        username = _validate_username(allocation.get("username"), f"allocations[{index}].username")
        if username.split(":", 1)[1] != device_id:
            _fail(f"allocations[{index}].username device id does not match allocation device_id")
        allocations.append(
            RegistryAllocation(
                allocation_id=allocation_id,
                device_id=device_id,
                session_id=_validate_identifier(
                    allocation.get("session_id"), f"allocations[{index}].session_id"
                ),
                username=username,
                coturn_session_id=coturn_session_id,
            )
        )
    return Registry(source_id=source_id, allocations=tuple(allocations))


def parse_coturn_ps(output: str) -> tuple[CoturnSession, ...]:
    sessions: list[CoturnSession] = []
    current_id: str | None = None
    current_username: str | None = None
    for line in output.splitlines():
        header = SESSION_HEADER.search(line)
        if header:
            if current_id is not None or current_username is not None:
                _fail("coturn CLI session entry is missing usage counters")
            current_id = _validate_identifier(header.group(1), "coturn session id")
            current_username = _validate_username(header.group(2), "coturn session username")
            continue
        if "id=" in line and "user <" in line:
            _fail("malformed coturn CLI session header")
        usage = USAGE_LINE.search(line)
        if usage and current_id is not None and current_username is not None:
            received_bytes = _validate_uint(int(usage.group(2)), "received bytes")
            sent_bytes = _validate_uint(int(usage.group(4)), "sent bytes")
            sessions.append(
                CoturnSession(
                    coturn_session_id=current_id,
                    username=current_username,
                    received_bytes=received_bytes,
                    sent_bytes=sent_bytes,
                )
            )
            current_id = None
            current_username = None
    if current_id is not None or current_username is not None:
        _fail("coturn CLI session entry is missing usage counters")
    return tuple(sessions)


def run_cli_command(settings: CLISettings, command: str) -> str:
    if "\n" in command or "\r" in command:
        _fail("coturn CLI command must be single-line")
    with socket.create_connection((settings.host, settings.port), timeout=settings.timeout_seconds) as sock:
        sock.settimeout(settings.timeout_seconds)
        sock.sendall((settings.password + "\n").encode("utf-8"))
        _read_until_prompt(sock, settings.timeout_seconds)
        sock.sendall((command + "\n").encode("utf-8"))
        output = _read_until_prompt(sock, settings.timeout_seconds)
        try:
            sock.sendall(b"quit\n")
        except OSError:
            pass
        return output


def _read_until_prompt(sock: socket.socket, timeout_seconds: float) -> str:
    deadline = time.monotonic() + timeout_seconds
    chunks = bytearray()
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > MAX_CLI_OUTPUT_BYTES:
            _fail("coturn CLI output exceeded maximum size")
        text = chunks.decode("utf-8", errors="replace")
        if text.endswith("> "):
            return text
    _fail("coturn CLI timed out before prompt")


def _load_password(env_name: str, password_file: Path | None) -> str:
    if password_file is None:
        path = os.environ.get(DEFAULT_CLI_PASSWORD_FILE_ENV, "")
        if path:
            password_file = Path(path)
    env_value = os.environ.get(env_name, "")
    if env_value and password_file is not None:
        _fail(f"{env_name} and --cli-password-file cannot both be set")
    if password_file is not None:
        try:
            env_value = password_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CoturnControlError(f"cannot read coturn CLI password file: {exc}") from exc
    if not CLI_PASSWORD.fullmatch(env_value):
        _fail(
            "coturn CLI password must contain at least 32 characters from "
            "A-Z, a-z, 0-9, '_', '.', ':', '@', '%', '+', '=' or '-'"
        )
    return env_value


def _next_sequence(state_file: Path | None, observed_at: datetime) -> int:
    candidate = int(observed_at.timestamp() * 1_000_000_000)
    if candidate <= 0:
        _fail("observed_at cannot produce a positive sequence")
    if state_file is None:
        return candidate
    previous = 0
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) - {"last_sequence"}:
            _fail("sequence state file must contain only last_sequence")
        value = raw.get("last_sequence", 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _fail("sequence state last_sequence must be a non-negative integer")
        previous = value
    except FileNotFoundError:
        previous = 0
    except json.JSONDecodeError as exc:
        raise CoturnControlError(f"cannot parse sequence state file: {exc}") from exc
    sequence = max(candidate, previous + 1)
    if sequence > MAX_SIGNED_INT64:
        _fail("sequence exceeds supported range")
    _write_state_atomic(state_file, {"last_sequence": sequence})
    return sequence


def _write_state_atomic(path: Path, payload: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _sessions_by_id(sessions: Sequence[CoturnSession]) -> dict[str, CoturnSession]:
    indexed: dict[str, CoturnSession] = {}
    for session in sessions:
        if session.coturn_session_id in indexed:
            _fail(f"duplicate coturn session id in CLI output: {session.coturn_session_id}")
        indexed[session.coturn_session_id] = session
    return indexed


def _sessions_by_username(sessions: Sequence[CoturnSession]) -> dict[str, list[CoturnSession]]:
    indexed: dict[str, list[CoturnSession]] = {}
    for session in sessions:
        indexed.setdefault(session.username, []).append(session)
    return indexed


def _registry_username_counts(registry: Registry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for allocation in registry.allocations:
        if allocation.coturn_session_id is None:
            counts[allocation.username] = counts.get(allocation.username, 0) + 1
    return counts


def resolve_session(
    allocation: RegistryAllocation,
    sessions: Sequence[CoturnSession],
    username_counts: dict[str, int],
) -> CoturnSession | None:
    if allocation.coturn_session_id is not None:
        session = _sessions_by_id(sessions).get(allocation.coturn_session_id)
        if session is None:
            return None
        if session.username != allocation.username:
            _fail(f"coturn session username mismatch for allocation {allocation.allocation_id}")
        return session
    if username_counts.get(allocation.username, 0) > 1:
        _fail(f"registry has ambiguous username mapping for {allocation.username}")
    candidates = _sessions_by_username(sessions).get(allocation.username, [])
    if len(candidates) > 1:
        _fail(f"coturn CLI returned multiple sessions for username {allocation.username}")
    if not candidates:
        return None
    return candidates[0]


def export_snapshot(
    registry: Registry,
    sessions: Sequence[CoturnSession],
    observed_at: datetime,
    sequence: int,
) -> dict[str, Any]:
    username_counts = _registry_username_counts(registry)
    allocations: list[dict[str, Any]] = []
    for allocation in registry.allocations:
        session = resolve_session(allocation, sessions, username_counts)
        if session is None:
            continue
        allocations.append(
            {
                "allocation_id": allocation.allocation_id,
                "device_id": allocation.device_id,
                "session_id": allocation.session_id,
                "sequence": sequence,
                "ingress_bytes": session.received_bytes,
                "egress_bytes": session.sent_bytes,
                "closed": False,
            }
        )
    return {
        "source_id": registry.source_id,
        "observed_at": _format_timestamp(observed_at),
        "allocations": allocations,
    }


def _read_active_sessions(
    settings: CLISettings, runner: Callable[[CLISettings, str], str]
) -> tuple[CoturnSession, ...]:
    return parse_coturn_ps(runner(settings, "ps"))


def command_export(args: argparse.Namespace) -> int:
    expected_source = _source_id(args.source_id)
    registry = load_registry(_registry_path(args.registry), expected_source)
    observed_at = _parse_timestamp(args.observed_at)
    sequence = _next_sequence(_sequence_state_path(args.state_file), observed_at)
    settings = CLISettings(
        host=args.cli_host,
        port=args.cli_port,
        password=_load_password(args.cli_password_env, args.cli_password_file),
        timeout_seconds=args.timeout_seconds,
    )
    sessions = _read_active_sessions(settings, run_cli_command)
    snapshot = export_snapshot(registry, sessions, observed_at, sequence)
    print(json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
    return 0


def _allocation_by_id(registry: Registry, allocation_id: str) -> RegistryAllocation:
    for allocation in registry.allocations:
        if allocation.allocation_id == allocation_id:
            return allocation
    _fail(f"allocation {allocation_id} is not present in the registry")


def command_disconnect(args: argparse.Namespace) -> int:
    source_id = _validate_identifier(
        os.environ.get("VIBE_COTURN_DISCONNECT_SOURCE_ID"), "VIBE_COTURN_DISCONNECT_SOURCE_ID"
    )
    allocation_id = _validate_identifier(
        os.environ.get("VIBE_COTURN_DISCONNECT_ALLOCATION_ID"),
        "VIBE_COTURN_DISCONNECT_ALLOCATION_ID",
    )
    reason = _validate_identifier(
        os.environ.get("VIBE_COTURN_DISCONNECT_REASON"), "VIBE_COTURN_DISCONNECT_REASON"
    )
    if reason not in {"unauthorized", "conflict", "revoked"}:
        _fail("VIBE_COTURN_DISCONNECT_REASON must be unauthorized, conflict, or revoked")
    registry = load_registry(_registry_path(args.registry), source_id)
    allocation = _allocation_by_id(registry, allocation_id)
    settings = CLISettings(
        host=args.cli_host,
        port=args.cli_port,
        password=_load_password(args.cli_password_env, args.cli_password_file),
        timeout_seconds=args.timeout_seconds,
    )
    sessions = _read_active_sessions(settings, run_cli_command)
    session = resolve_session(allocation, sessions, _registry_username_counts(registry))
    if session is None:
        print(
            json.dumps(
                {"status": "already_disconnected", "allocation_id": allocation_id, "reason": reason},
                sort_keys=True,
            )
        )
        return 0
    run_cli_command(settings, f"cs {session.coturn_session_id}")
    remaining_sessions = _read_active_sessions(settings, run_cli_command)
    if resolve_session(allocation, remaining_sessions, _registry_username_counts(registry)) is not None:
        _fail(f"coturn session remained active after disconnect for allocation {allocation_id}")
    print(
        json.dumps(
            {
                "status": "disconnected",
                "allocation_id": allocation_id,
                "coturn_session_id": session.coturn_session_id,
                "reason": reason,
            },
            sort_keys=True,
        )
    )
    return 0


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _port(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed > 65535:
        raise argparse.ArgumentTypeError("must be from 1 through 65535")
    return parsed


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registry",
        type=Path,
        help=f"strict allocation registry JSON; defaults to {DEFAULT_REGISTRY_ENV}",
    )
    parser.add_argument("--cli-host", default="127.0.0.1", help="coturn CLI host; keep loopback in production")
    parser.add_argument("--cli-port", type=_port, default=5766, help="coturn CLI TCP port")
    parser.add_argument(
        "--cli-password-env",
        default=DEFAULT_CLI_PASSWORD_ENV,
        help="environment variable containing the coturn CLI password",
    )
    parser.add_argument(
        "--cli-password-file",
        type=Path,
        help=f"file containing the coturn CLI password; defaults to {DEFAULT_CLI_PASSWORD_FILE_ENV}",
    )
    parser.add_argument("--timeout-seconds", type=_positive_float, default=5.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="print a strict Authority reconcile snapshot")
    add_cli_arguments(export)
    export.add_argument("--source-id", help=f"expected source_id; defaults to {DEFAULT_SOURCE_ID_ENV}")
    export.add_argument("--observed-at", help="RFC3339 timestamp override for tests and replay")
    export.add_argument(
        "--state-file",
        type=Path,
        help=f"persistent monotonic sequence state; defaults to {DEFAULT_SEQUENCE_STATE_ENV}",
    )
    export.set_defaults(func=command_export)

    disconnect = subparsers.add_parser("disconnect", help="disconnect one allocation from coturn")
    add_cli_arguments(disconnect)
    disconnect.set_defaults(func=command_disconnect)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except CoturnControlError as exc:
        print(f"coturn-cli-control: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
