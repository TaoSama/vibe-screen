#!/usr/bin/env python3
"""Submit trusted coturn allocation snapshots to Authority.

This helper is the production-side contract between a coturn allocation exporter
and vibe-authority. It intentionally does not parse human-oriented coturn logs or
claim to be the exporter. A deployment supplies a structured snapshot, and this
process reconciles it with Authority. Unauthorized or conflicting active source
allocations are fail-closed: they require a configured external disconnect
executor and any executor failure makes the run fail.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, NoReturn, Sequence
from urllib import error, parse, request

IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
MAX_SIGNED_INT64 = (1 << 63) - 1
MAX_ALLOCATIONS = 10_000
MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TOKEN_ENV = "VIBE_AUTHORITY_COTURN_TOKEN"

SNAPSHOT_FIELDS = frozenset({"source_id", "observed_at", "allocations"})
ALLOCATION_FIELDS = frozenset(
    {
        "allocation_id",
        "device_id",
        "session_id",
        "sequence",
        "ingress_bytes",
        "egress_bytes",
        "closed",
    }
)
RESULT_FIELDS = frozenset(
    {
        "applied",
        "duplicate",
        "already_ahead",
        "missing_allocation_ids",
        "unauthorized_allocation_ids",
        "conflict_allocation_ids",
    }
)


class ReconcileError(RuntimeError):
    """Raised when reconciliation cannot produce a safe result."""


@dataclass(frozen=True)
class Settings:
    authority_url: str
    token: str
    snapshot: Path
    disconnect_command: tuple[str, ...]
    interval_seconds: float
    max_iterations: int
    request_timeout_seconds: float


class NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise error.HTTPError(newurl, code, "redirects are not permitted", headers, fp)


def _fail(message: str) -> NoReturn:
    raise ReconcileError(message)


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be 1-128 ASCII letters, digits, '.', '_' or '-'")
    return value


def _validate_uint(value: Any, field: str, *, minimum: int = 0) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > MAX_SIGNED_INT64
    ):
        _fail(f"{field} must be an integer from {minimum} through {MAX_SIGNED_INT64}")
    return value


def _validate_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be boolean")
    return value


def _normalize_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReconcileError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include an explicit timezone")
    # Keep the operator supplied precision and offset. Authority performs the
    # final clock-window check against its own clock.
    return value


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"cannot read snapshot: {exc}") from exc
    if not isinstance(raw, dict):
        _fail("snapshot must be a JSON object")
    extra = set(raw) - SNAPSHOT_FIELDS
    if extra:
        _fail(f"snapshot contains unknown fields: {', '.join(sorted(extra))}")
    source_id = _validate_identifier(raw.get("source_id"), "source_id")
    observed_at = _normalize_timestamp(raw.get("observed_at"), "observed_at")
    allocations = raw.get("allocations")
    if not isinstance(allocations, list) or len(allocations) > MAX_ALLOCATIONS:
        _fail(f"allocations must be a JSON array with at most {MAX_ALLOCATIONS} items")

    normalized_allocations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, allocation in enumerate(allocations):
        if not isinstance(allocation, dict):
            _fail(f"allocations[{index}] must be an object")
        extra = set(allocation) - ALLOCATION_FIELDS
        if extra:
            _fail(f"allocations[{index}] contains unknown fields: {', '.join(sorted(extra))}")
        allocation_id = _validate_identifier(
            allocation.get("allocation_id"), f"allocations[{index}].allocation_id"
        )
        if allocation_id in seen_ids:
            _fail(f"duplicate allocation_id in snapshot: {allocation_id}")
        seen_ids.add(allocation_id)
        normalized_allocations.append(
            {
                "allocation_id": allocation_id,
                "device_id": _validate_identifier(
                    allocation.get("device_id"), f"allocations[{index}].device_id"
                ),
                "session_id": _validate_identifier(
                    allocation.get("session_id"), f"allocations[{index}].session_id"
                ),
                "sequence": _validate_uint(
                    allocation.get("sequence"), f"allocations[{index}].sequence", minimum=1
                ),
                "ingress_bytes": _validate_uint(
                    allocation.get("ingress_bytes"), f"allocations[{index}].ingress_bytes"
                ),
                "egress_bytes": _validate_uint(
                    allocation.get("egress_bytes"), f"allocations[{index}].egress_bytes"
                ),
                "closed": _validate_bool(
                    allocation.get("closed", False), f"allocations[{index}].closed"
                ),
            }
        )
    return {"source_id": source_id, "observed_at": observed_at, "allocations": normalized_allocations}


def _load_token(env_name: str, token_file: Path | None) -> str:
    env_value = os.environ.get(env_name, "")
    if env_value and token_file is not None:
        _fail(f"{env_name} and --coturn-token-file cannot both be set")
    if token_file is not None:
        try:
            env_value = token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ReconcileError(f"cannot read coturn token file: {exc}") from exc
    if len(env_value) < 32:
        _fail(f"{env_name} or --coturn-token-file must contain at least 32 characters")
    return env_value


def _reconcile_endpoint(authority_url: str) -> str:
    parsed = parse.urlparse(authority_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _fail("authority URL must be https or loopback http")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        _fail("plaintext authority URL must use a loopback host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        _fail("authority URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        _fail("authority URL must not contain a path")
    base = authority_url.rstrip("/") + "/"
    return parse.urljoin(base, "v1/coturn/reconcile")


def submit_reconcile(settings: Settings, snapshot: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    req = request.Request(
        _reconcile_endpoint(settings.authority_url),
        data=body,
        headers={
            "Authorization": "Bearer " + settings.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = request.build_opener(NoRedirectHandler)
    try:
        with opener.open(req, timeout=settings.request_timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except error.HTTPError as exc:
        raise ReconcileError(f"authority reconcile failed with HTTP {exc.code}") from exc
    except OSError as exc:
        raise ReconcileError(f"authority reconcile request failed: {exc}") from exc
    if status != 200:
        _fail(f"authority reconcile failed with HTTP {status}")
    if len(raw) > MAX_RESPONSE_BYTES:
        _fail("authority reconcile response exceeded maximum size")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconcileError("authority reconcile returned invalid JSON") from exc
    return validate_result(decoded)


def validate_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("authority reconcile response must be an object")
    extra = set(value) - RESULT_FIELDS
    if extra:
        _fail(f"authority reconcile response contains unknown fields: {', '.join(sorted(extra))}")
    result: dict[str, Any] = {}
    for field in ("applied", "duplicate", "already_ahead"):
        result[field] = _validate_uint(value.get(field), field)
    for field in (
        "missing_allocation_ids",
        "unauthorized_allocation_ids",
        "conflict_allocation_ids",
    ):
        values = value.get(field)
        if not isinstance(values, list):
            _fail(f"{field} must be an array")
        normalized = [_validate_identifier(item, f"{field}[]") for item in values]
        seen_ids: set[str] = set()
        for allocation_id in normalized:
            if allocation_id in seen_ids:
                _fail(f"{field} contains duplicate allocation ids")
            seen_ids.add(allocation_id)
        result[field] = normalized
    all_result_ids = (
        result["missing_allocation_ids"]
        + result["unauthorized_allocation_ids"]
        + result["conflict_allocation_ids"]
    )
    if len(set(all_result_ids)) != len(all_result_ids):
        _fail("authority reconcile response contains allocation ids in multiple result categories")
    return result


def _minimal_executor_env(source_id: str, allocation_id: str, reason: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL"):
        if key in os.environ:
            env[key] = os.environ[key]
    env.update(
        {
            "VIBE_COTURN_DISCONNECT_SOURCE_ID": source_id,
            "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": allocation_id,
            "VIBE_COTURN_DISCONNECT_REASON": reason,
        }
    )
    return env


def disconnect_required_allocations(
    settings: Settings, source_id: str, result: dict[str, Any]
) -> list[dict[str, str]]:
    disconnects: list[dict[str, str]] = []
    required: list[tuple[str, str]] = []
    for reason, field in (
        ("unauthorized", "unauthorized_allocation_ids"),
        ("conflict", "conflict_allocation_ids"),
    ):
        required.extend((reason, allocation_id) for allocation_id in result[field])
    if required and not settings.disconnect_command:
        _fail("active source allocations require --disconnect-command")
    for reason, allocation_id in required:
        try:
            completed = subprocess.run(
                settings.disconnect_command,
                env=_minimal_executor_env(source_id, allocation_id, reason),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=settings.request_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReconcileError(
                f"disconnect executor timed out for {reason} allocation {allocation_id}"
            ) from exc
        except OSError as exc:
            raise ReconcileError(
                f"disconnect executor could not start for {reason} allocation {allocation_id}: {exc}"
            ) from exc
        if completed.returncode != 0:
            _fail(
                f"disconnect executor failed for {reason} allocation {allocation_id}: exit {completed.returncode}"
            )
        disconnects.append({"allocation_id": allocation_id, "reason": reason})
    return disconnects


def run_once(settings: Settings) -> dict[str, Any]:
    snapshot = load_snapshot(settings.snapshot)
    result = submit_reconcile(settings, snapshot)
    disconnects = disconnect_required_allocations(settings, snapshot["source_id"], result)
    status = "ok"
    if disconnects:
        status = "remediated"
    if result["missing_allocation_ids"]:
        status = "needs_ledger_close"
    return {
        "status": status,
        "source_id": snapshot["source_id"],
        "observed_at": snapshot["observed_at"],
        "reconcile": result,
        "disconnects": disconnects,
    }


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-url", required=True, help="Authority base URL; https unless loopback http")
    parser.add_argument("--snapshot", required=True, type=Path, help="trusted structured coturn snapshot JSON")
    parser.add_argument("--coturn-token-env", default=DEFAULT_TOKEN_ENV, help="environment variable containing the Authority coturn bearer token")
    parser.add_argument("--coturn-token-file", type=Path, help="file containing the Authority coturn bearer token")
    parser.add_argument("--request-timeout-seconds", type=_positive_float, default=10.0)
    parser.add_argument("--interval-seconds", type=_non_negative_float, default=0.0, help="sleep between repeated reconcile iterations")
    parser.add_argument("--max-iterations", type=_positive_int, default=1, help="bounded loop iteration count")
    parser.add_argument("--disconnect-command", nargs=argparse.REMAINDER, default=(), help="external idempotent active-allocation disconnect executor; use after all other flags")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    command = tuple(args.disconnect_command)
    if command and command[0] == "--":
        command = command[1:]
    return Settings(
        authority_url=args.authority_url,
        token=_load_token(args.coturn_token_env, args.coturn_token_file),
        snapshot=args.snapshot,
        disconnect_command=command,
        interval_seconds=args.interval_seconds,
        max_iterations=args.max_iterations,
        request_timeout_seconds=args.request_timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        settings = settings_from_args(build_parser().parse_args(argv))
        last_report: dict[str, Any] | None = None
        saw_missing_allocation = False
        for iteration in range(settings.max_iterations):
            last_report = run_once(settings)
            if last_report["status"] == "needs_ledger_close":
                saw_missing_allocation = True
            print(json.dumps(last_report, sort_keys=True), flush=True)
            if iteration + 1 < settings.max_iterations:
                time.sleep(settings.interval_seconds)
        if saw_missing_allocation:
            return 4
        return 0
    except ReconcileError as exc:
        print(f"coturn-reconcile: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
