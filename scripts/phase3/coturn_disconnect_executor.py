#!/usr/bin/env python3
"""Disconnect one active coturn allocation through a strict executor contract.

The production deployment still needs a reviewed coturn/provider integration. This
executor is the current-base product-slice contract used by the reconciliation
helper: it consumes the exact environment exported by coturn_reconcile.py, mutates
a machine-readable active-allocation state file, and writes a non-secret audit
record. It intentionally cannot be used as public Internet release evidence by
itself.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, NoReturn, Sequence

STATE_SCHEMA = "dev.vibescreen.phase3-coturn-active-allocation-state/v1"
AUDIT_SCHEMA = "dev.vibescreen.phase3-coturn-disconnect-executor-audit/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
REASONS = frozenset({"unauthorized", "conflict", "revoked"})
MAX_STATE_BYTES = 512 * 1024
ROOT_FIELDS = frozenset({"schema", "source_id", "updated_at", "allocations"})
ALLOCATION_FIELDS = frozenset(
    {
        "allocation_id",
        "device_id",
        "session_id",
        "active",
        "disconnected_at",
        "disconnect_reason",
    }
)
ENV_SOURCE_ID = "VIBE_COTURN_DISCONNECT_SOURCE_ID"
ENV_ALLOCATION_ID = "VIBE_COTURN_DISCONNECT_ALLOCATION_ID"
ENV_REASON = "VIBE_COTURN_DISCONNECT_REASON"
BOUNDARY = "local_state_disconnect_contract_not_public_internet_or_live_coturn_evidence"


class DisconnectError(RuntimeError):
    """Raised when a requested allocation disconnect cannot be proved safe."""


def _fail(message: str) -> NoReturn:
    raise DisconnectError(message)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _timestamp(value: Any, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DisconnectError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include an explicit timezone")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be boolean")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DisconnectError(f"cannot read allocation state: {exc}") from exc
    if len(raw) > MAX_STATE_BYTES:
        _fail("allocation state exceeded maximum size")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DisconnectError("allocation state must be UTF-8 JSON") from exc
    return validate_state(decoded)


def validate_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("allocation state must be a JSON object")
    extra = set(value) - ROOT_FIELDS
    if extra:
        _fail(f"allocation state contains unknown fields: {', '.join(sorted(extra))}")
    if value.get("schema") != STATE_SCHEMA:
        _fail(f"schema must be {STATE_SCHEMA}")
    source_id = _identifier(value.get("source_id"), "source_id")
    updated_at = _timestamp(value.get("updated_at"), "updated_at")
    allocations = value.get("allocations")
    if not isinstance(allocations, list):
        _fail("allocations must be an array")

    normalized_allocations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, allocation in enumerate(allocations):
        if not isinstance(allocation, dict):
            _fail(f"allocations[{index}] must be an object")
        extra = set(allocation) - ALLOCATION_FIELDS
        if extra:
            _fail(f"allocations[{index}] contains unknown fields: {', '.join(sorted(extra))}")
        allocation_id = _identifier(allocation.get("allocation_id"), f"allocations[{index}].allocation_id")
        if allocation_id in seen:
            _fail(f"duplicate allocation_id in allocation state: {allocation_id}")
        seen.add(allocation_id)
        active = _bool(allocation.get("active"), f"allocations[{index}].active")
        disconnected_at = _timestamp(
            allocation.get("disconnected_at"),
            f"allocations[{index}].disconnected_at",
            allow_none=not allocation.get("disconnected_at"),
        )
        disconnect_reason = allocation.get("disconnect_reason")
        if disconnect_reason is not None:
            disconnect_reason = _validate_reason(disconnect_reason, f"allocations[{index}].disconnect_reason")
        if active and (disconnected_at is not None or disconnect_reason is not None):
            _fail(f"allocations[{index}] cannot be active and disconnected")
        if not active and (disconnected_at is None or disconnect_reason is None):
            _fail(f"allocations[{index}] inactive entries require disconnect metadata")
        normalized_allocations.append(
            {
                "allocation_id": allocation_id,
                "device_id": _identifier(allocation.get("device_id"), f"allocations[{index}].device_id"),
                "session_id": _identifier(allocation.get("session_id"), f"allocations[{index}].session_id"),
                "active": active,
                "disconnected_at": disconnected_at,
                "disconnect_reason": disconnect_reason,
            }
        )
    return {
        "schema": STATE_SCHEMA,
        "source_id": source_id,
        "updated_at": updated_at,
        "allocations": normalized_allocations,
    }


def _validate_reason(value: Any, field: str) -> str:
    if not isinstance(value, str) or value not in REASONS:
        _fail(f"{field} must be one of: {', '.join(sorted(REASONS))}")
    return value


def _env_or_arg(value: str | None, env_name: str, field: str) -> str:
    selected = value if value is not None else os.environ.get(env_name)
    return _identifier(selected, field)


def _reason_env_or_arg(value: str | None) -> str:
    selected = value if value is not None else os.environ.get(ENV_REASON)
    return _validate_reason(selected, "reason")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o600)


def disconnect_allocation(
    state: dict[str, Any], source_id: str, allocation_id: str, reason: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if state["source_id"] != source_id:
        _fail("disconnect source_id does not match allocation state")
    disconnected_at = _now()
    matched: dict[str, Any] | None = None
    already_disconnected = False
    for allocation in state["allocations"]:
        if allocation["allocation_id"] != allocation_id:
            continue
        matched = allocation
        if allocation["active"]:
            allocation["active"] = False
            allocation["disconnected_at"] = disconnected_at
            allocation["disconnect_reason"] = reason
        else:
            if allocation["disconnect_reason"] != reason:
                _fail("allocation was already disconnected for a different reason")
            already_disconnected = True
            disconnected_at = allocation["disconnected_at"]
        break
    if matched is None:
        _fail("allocation_id was not present in active-allocation state")
    state["updated_at"] = _now()
    audit = {
        "schema": AUDIT_SCHEMA,
        "source_id": source_id,
        "allocation_id": allocation_id,
        "device_id": matched["device_id"],
        "session_id": matched["session_id"],
        "reason": reason,
        "active_allocation_removed": True,
        "already_disconnected": already_disconnected,
        "disconnected_at": disconnected_at,
        "release_gate_boundary": BOUNDARY,
    }
    return state, audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path, help="machine-readable active-allocation state JSON")
    parser.add_argument("--audit-log", type=Path, help="append-only JSONL audit path")
    parser.add_argument("--audit-output", type=Path, help="single JSON audit output path")
    parser.add_argument("--source-id", help="defaults to VIBE_COTURN_DISCONNECT_SOURCE_ID")
    parser.add_argument("--allocation-id", help="defaults to VIBE_COTURN_DISCONNECT_ALLOCATION_ID")
    parser.add_argument("--reason", choices=sorted(REASONS), help="defaults to VIBE_COTURN_DISCONNECT_REASON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source_id = _env_or_arg(args.source_id, ENV_SOURCE_ID, "source_id")
        allocation_id = _env_or_arg(args.allocation_id, ENV_ALLOCATION_ID, "allocation_id")
        reason = _reason_env_or_arg(args.reason)
        state = load_state(args.state)
        updated_state, audit = disconnect_allocation(state, source_id, allocation_id, reason)
        write_json(args.state, updated_state)
        if args.audit_log is not None:
            append_jsonl(args.audit_log, audit)
        if args.audit_output is not None:
            write_json(args.audit_output, audit)
        if args.audit_log is None and args.audit_output is None:
            print(json.dumps(audit, sort_keys=True))
        return 0
    except DisconnectError as exc:
        print(f"coturn-disconnect-executor: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
