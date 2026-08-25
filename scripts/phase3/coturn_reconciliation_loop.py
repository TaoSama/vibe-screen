#!/usr/bin/env python3
"""Run bounded coturn reconciliation with durable missing-allocation tracking.

This is the current-base operator loop around coturn_reconcile.py. It repeatedly
exports a strict allocation snapshot, submits it to Authority, lets the configured
disconnect executor remove unauthorized/conflicting/revoked active allocations,
and persists consecutive missing-allocation observations. A missing allocation is
reported as a ledger-close candidate only after it survives the configured
threshold. The script does not fabricate coturn closed-usage events and is not
public Internet release evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, NoReturn, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3 import coturn_reconcile  # noqa: E402

STATE_SCHEMA = "dev.vibescreen.phase3-coturn-reconciliation-loop-state/v1"
RUN_SCHEMA = "dev.vibescreen.phase3-coturn-reconciliation-loop-run/v1"
BOUNDARY = "local_bounded_reconciliation_loop_not_public_internet_release_evidence"
MAX_STATE_BYTES = 512 * 1024
STATE_FIELDS = frozenset({"schema", "source_id", "updated_at", "missing_allocations"})
MISSING_FIELDS = frozenset({"first_seen_at", "last_seen_at", "consecutive_count"})
IDENTIFIER = coturn_reconcile.IDENTIFIER


class LoopError(RuntimeError):
    """Raised when the reconciliation loop cannot produce trustworthy output."""


def _fail(message: str) -> NoReturn:
    raise LoopError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise LoopError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include an explicit timezone")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail(f"{field} must be a positive integer")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def load_loop_state(path: Path | None, source_id: str | None = None) -> dict[str, Any]:
    if path is None or not path.exists():
        if source_id is None:
            source_id = "unknown"
        return {"schema": STATE_SCHEMA, "source_id": source_id, "updated_at": _now(), "missing_allocations": {}}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LoopError(f"cannot read loop state: {exc}") from exc
    if len(raw) > MAX_STATE_BYTES:
        _fail("loop state exceeded maximum size")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LoopError("loop state must be UTF-8 JSON") from exc
    return validate_loop_state(decoded, source_id=source_id)


def validate_loop_state(value: Any, *, source_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("loop state must be a JSON object")
    extra = set(value) - STATE_FIELDS
    if extra:
        _fail(f"loop state contains unknown fields: {', '.join(sorted(extra))}")
    if value.get("schema") != STATE_SCHEMA:
        _fail(f"schema must be {STATE_SCHEMA}")
    state_source = _identifier(value.get("source_id"), "source_id")
    if source_id is not None and state_source not in {"unknown", source_id}:
        _fail("loop state source_id does not match reconcile source_id")
    updated_at = _timestamp(value.get("updated_at"), "updated_at")
    missing = value.get("missing_allocations")
    if not isinstance(missing, dict):
        _fail("missing_allocations must be an object")
    normalized_missing: dict[str, dict[str, Any]] = {}
    for allocation_id, record in missing.items():
        normalized_id = _identifier(allocation_id, "missing_allocations key")
        if not isinstance(record, dict):
            _fail(f"missing_allocations.{allocation_id} must be an object")
        extra = set(record) - MISSING_FIELDS
        if extra:
            _fail(f"missing_allocations.{allocation_id} contains unknown fields: {', '.join(sorted(extra))}")
        normalized_missing[normalized_id] = {
            "first_seen_at": _timestamp(record.get("first_seen_at"), f"missing_allocations.{allocation_id}.first_seen_at"),
            "last_seen_at": _timestamp(record.get("last_seen_at"), f"missing_allocations.{allocation_id}.last_seen_at"),
            "consecutive_count": _positive_int(
                record.get("consecutive_count"), f"missing_allocations.{allocation_id}.consecutive_count"
            ),
        }
    return {
        "schema": STATE_SCHEMA,
        "source_id": source_id if state_source == "unknown" and source_id is not None else state_source,
        "updated_at": updated_at,
        "missing_allocations": normalized_missing,
    }


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


def update_missing_state(
    state: dict[str, Any], report: dict[str, Any], *, missing_threshold: int
) -> tuple[dict[str, Any], list[str]]:
    source_id = _identifier(report["source_id"], "source_id")
    state = validate_loop_state(state, source_id=source_id)
    observed_at = _timestamp(report["observed_at"], "observed_at")
    current_missing = set(report["reconcile"]["missing_allocation_ids"])
    existing = state["missing_allocations"]
    next_missing: dict[str, dict[str, Any]] = {}
    for allocation_id in sorted(current_missing):
        _identifier(allocation_id, "missing_allocation_ids[]")
        record = existing.get(allocation_id)
        if record is None:
            next_missing[allocation_id] = {
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "consecutive_count": 1,
            }
        else:
            next_missing[allocation_id] = {
                "first_seen_at": record["first_seen_at"],
                "last_seen_at": observed_at,
                "consecutive_count": record["consecutive_count"] + 1,
            }
    state["source_id"] = source_id
    state["updated_at"] = _now()
    state["missing_allocations"] = next_missing
    candidates = [
        allocation_id
        for allocation_id, record in next_missing.items()
        if record["consecutive_count"] >= missing_threshold
    ]
    return state, candidates


def build_iteration_record(
    iteration: int,
    report: dict[str, Any],
    ledger_close_candidates: list[str],
) -> dict[str, Any]:
    status = report["status"]
    if ledger_close_candidates:
        status = "needs_ledger_close"
    elif report["reconcile"]["missing_allocation_ids"]:
        status = "watching_missing"
    return {
        "schema": RUN_SCHEMA,
        "iteration": iteration,
        "status": status,
        "source_id": report["source_id"],
        "observed_at": report["observed_at"],
        "reconcile": report["reconcile"],
        "disconnects": report["disconnects"],
        "ledger_close_candidates": ledger_close_candidates,
        "release_gate_boundary": BOUNDARY,
    }


def run_loop(
    settings: coturn_reconcile.Settings,
    *,
    state_path: Path,
    output_jsonl: Path | None,
    missing_threshold: int,
) -> dict[str, Any]:
    if missing_threshold <= 0:
        _fail("missing_threshold must be positive")
    state = load_loop_state(state_path if state_path.exists() else None)
    records: list[dict[str, Any]] = []
    saw_close_candidate = False
    for iteration in range(1, settings.max_iterations + 1):
        report = coturn_reconcile.run_once_with_retries(settings)
        state, close_candidates = update_missing_state(state, report, missing_threshold=missing_threshold)
        record = build_iteration_record(iteration, report, close_candidates)
        records.append(record)
        if close_candidates:
            saw_close_candidate = True
        if output_jsonl is not None:
            append_jsonl(output_jsonl, record)
        write_json(state_path, state)
        if iteration < settings.max_iterations:
            time.sleep(settings.interval_seconds)
    final_status = "needs_ledger_close" if saw_close_candidate else records[-1]["status"]
    return {
        "schema": RUN_SCHEMA,
        "status": final_status,
        "iterations": len(records),
        "last_record": records[-1],
        "state_path": str(state_path),
        "release_gate_boundary": BOUNDARY,
    }


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _positive_int_arg(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-url", required=True, help="Authority base URL; https unless loopback http")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path, help="trusted structured coturn snapshot JSON")
    source.add_argument(
        "--exporter-command",
        nargs="+",
        default=(),
        help="external coturn exporter that writes one structured snapshot JSON object to stdout",
    )
    parser.add_argument("--state", required=True, type=Path, help="durable reconciliation loop state JSON")
    parser.add_argument("--output-jsonl", type=Path, help="append iteration records to this JSONL path")
    parser.add_argument("--missing-threshold", type=_positive_int_arg, default=2)
    parser.add_argument("--coturn-token-env", default=coturn_reconcile.DEFAULT_TOKEN_ENV)
    parser.add_argument("--coturn-token-file", type=Path)
    parser.add_argument("--request-timeout-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--interval-seconds", type=_non_negative_float, default=0.0)
    parser.add_argument("--max-iterations", type=_positive_int_arg, default=1)
    parser.add_argument("--retry-attempts", type=int, default=0)
    parser.add_argument("--retry-backoff-seconds", type=_non_negative_float, default=1.0)
    parser.add_argument(
        "--disconnect-command",
        nargs=argparse.REMAINDER,
        default=(),
        help="external idempotent active-allocation disconnect executor; use after all other flags",
    )
    return parser


def settings_from_args(args: argparse.Namespace) -> coturn_reconcile.Settings:
    return coturn_reconcile.settings_from_args(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.retry_attempts < 0:
            _fail("--retry-attempts must be non-negative")
        settings = settings_from_args(args)
        summary = run_loop(
            settings,
            state_path=args.state,
            output_jsonl=args.output_jsonl,
            missing_threshold=args.missing_threshold,
        )
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 4 if summary["status"] == "needs_ledger_close" else 0
    except (LoopError, coturn_reconcile.ReconcileError) as exc:
        print(f"coturn-reconciliation-loop: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
