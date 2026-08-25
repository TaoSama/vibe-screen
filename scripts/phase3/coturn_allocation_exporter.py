#!/usr/bin/env python3
"""Export a strict coturn allocation snapshot for Authority reconciliation.

This is a production-shaped adapter for a trusted machine collector. It does not
parse human-oriented coturn logs. Operators feed it a structured allocation
state captured from a reviewed coturn/provider collector, and it emits exactly
the snapshot shape accepted by coturn_reconcile.py.
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

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3.coturn_reconcile import validate_snapshot  # noqa: E402

INPUT_SCHEMA = "dev.vibescreen.phase3-coturn-allocation-exporter-input/v1"
METADATA_SCHEMA = "dev.vibescreen.phase3-coturn-allocation-export/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
MAX_INPUT_BYTES = 512 * 1024
SECRET_KEY_PATTERN = re.compile(r"(password|credential|secret|token|private[_-]?key)", re.IGNORECASE)
ROOT_FIELDS = frozenset({"schema", "source_id", "boot_id", "observed_at", "allocations"})
ALLOCATION_FIELDS = frozenset(
    {
        "allocation_id",
        "turn_username",
        "device_id",
        "session_id",
        "sequence",
        "ingress_bytes",
        "egress_bytes",
        "closed",
    }
)


class ExporterError(RuntimeError):
    """Raised when the collector snapshot cannot be trusted."""


def _fail(message: str) -> NoReturn:
    raise ExporterError(message)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _uint(value: Any, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > (1 << 63) - 1:
        _fail(f"{field} must be an integer from {minimum} through {(1 << 63) - 1}")
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ExporterError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include an explicit timezone")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be boolean")
    return value


def _reject_secret_like_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(f"{path} contains a non-string key")
            if SECRET_KEY_PATTERN.search(key):
                _fail(f"{path}.{key} is secret-like and must not enter exporter input")
            _reject_secret_like_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_like_fields(child, f"{path}[{index}]")


def read_collector_input(path: Path) -> dict[str, Any]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ExporterError(f"cannot read collector input: {exc}") from exc
    if len(raw_bytes) > MAX_INPUT_BYTES:
        _fail("collector input exceeded maximum size")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExporterError("collector input must be UTF-8 JSON") from exc
    return normalize_collector_input(value)


def normalize_collector_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("collector input must be a JSON object")
    _reject_secret_like_fields(value)
    extra = set(value) - ROOT_FIELDS
    if extra:
        _fail(f"collector input contains unknown fields: {', '.join(sorted(extra))}")
    if value.get("schema") != INPUT_SCHEMA:
        _fail(f"schema must be {INPUT_SCHEMA}")
    source_id = _identifier(value.get("source_id"), "source_id")
    boot_id = _identifier(value.get("boot_id"), "boot_id")
    observed_at = _timestamp(value.get("observed_at"), "observed_at")
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
            _fail(f"duplicate allocation_id in collector input: {allocation_id}")
        seen.add(allocation_id)
        device_id = _identifier(allocation.get("device_id"), f"allocations[{index}].device_id")
        _turn_username(allocation.get("turn_username"), device_id, index)
        normalized_allocations.append(
            {
                "allocation_id": allocation_id,
                "device_id": device_id,
                "session_id": _identifier(allocation.get("session_id"), f"allocations[{index}].session_id"),
                "sequence": _uint(allocation.get("sequence"), f"allocations[{index}].sequence", minimum=1),
                "ingress_bytes": _uint(allocation.get("ingress_bytes"), f"allocations[{index}].ingress_bytes"),
                "egress_bytes": _uint(allocation.get("egress_bytes"), f"allocations[{index}].egress_bytes"),
                "closed": _bool(allocation.get("closed", False), f"allocations[{index}].closed"),
            }
        )
    snapshot = {"source_id": source_id, "observed_at": observed_at, "allocations": normalized_allocations}
    validate_snapshot(snapshot)
    return {"source_id": source_id, "boot_id": boot_id, "snapshot": snapshot}


def _turn_username(value: Any, device_id: str, index: int) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"allocations[{index}].turn_username must be a TURN REST username")
    expiry, separator, principal = value.partition(":")
    if separator != ":" or not expiry.isdigit() or int(expiry) <= 0:
        _fail(f"allocations[{index}].turn_username must use <expiry>:<device_id>")
    if principal != device_id:
        _fail(f"allocations[{index}].turn_username must map to device_id")
    return value


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


def build_metadata(export: dict[str, Any]) -> dict[str, Any]:
    snapshot = export["snapshot"]
    return {
        "schema": METADATA_SCHEMA,
        "source_id": export["source_id"],
        "boot_id": export["boot_id"],
        "observed_at": snapshot["observed_at"],
        "allocation_count": len(snapshot["allocations"]),
        "closed_allocation_count": sum(1 for item in snapshot["allocations"] if item["closed"]),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release_gate_boundary": "structured_export_only_not_public_internet_or_live_disconnect_evidence",
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="trusted structured collector JSON")
    parser.add_argument("--output", type=Path, help="snapshot output path; defaults to stdout")
    parser.add_argument("--metadata-output", type=Path, help="optional non-secret exporter metadata path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        export = read_collector_input(args.input)
        if args.output is not None:
            write_json(args.output, export["snapshot"])
        else:
            print(json.dumps(export["snapshot"], sort_keys=True))
        if args.metadata_output is not None:
            write_json(args.metadata_output, build_metadata(export))
        return 0
    except ExporterError as exc:
        print(f"coturn-allocation-exporter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
