"""Evaluate Phase 1 reconnect timing evidence.

This checker is deliberately narrower than a general reconnect smoke record. A
timing pass requires an explicit disruption start, a fresh Protocol v1 recovery,
first received frame, first decoder output frame, and a stable Host PID. Plain
retry loops or post-hoc "connected" logs are not enough to close the three
second reconnect gate.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence, TextIO

from . import SCHEMA_VERSION


DISRUPTION_CLIENT_KILL = "client-kill"
DISRUPTION_ADB_REVERSE = "adb-reverse-disconnect"
DISRUPTION_LAN_NETWORK = "lan-network-interrupt"
DISRUPTIONS = (
    DISRUPTION_CLIENT_KILL,
    DISRUPTION_ADB_REVERSE,
    DISRUPTION_LAN_NETWORK,
)
TRANSPORT_USB = "usb"
TRANSPORT_LAN = "lan"
TRANSPORTS = (TRANSPORT_USB, TRANSPORT_LAN)
DEFAULT_THRESHOLD_MS = 3_000.0
BLOCKED_EXIT = 3
FAIL_EXIT = 2
INSUFFICIENT_EXIT = 1

_DIAG_LINE = re.compile(r"^\[(?P<timestamp>\d+(?:\.\d+)?)\]\s+(?P<body>.*)$")
_HOST_EPOCH = re.compile(r"Protocol v1 selected for connection epoch\s+(?P<epoch>\d+)")
_ANDROID_SESSION_EPOCH_JSON = re.compile(r'"event"\s*:\s*"connection_opened".*?"session_epoch"\s*:\s*(?P<epoch>\d+)')
_CONFIG_EPOCH = re.compile(r"\bepoch=(?P<epoch>\d+)\b")
_SESSION_EPOCH_FIELD = re.compile(r"\bsession_epoch=(?P<epoch>\d+)\b")
_CONFIG_EPOCH_FIELD = re.compile(r"\bconfig_epoch=(?P<epoch>\d+)\b")
_JSON_OBJECT = re.compile(r"\{.*\}")


def _positive_epoch_from_match(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    epoch = int(match.group("epoch"))
    return epoch if epoch > 0 else None


def _positive_epoch_from_value(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ReconnectTimingEvidenceError(f"{field} must be a positive integer")
    try:
        epoch = int(value)
    except (TypeError, ValueError) as error:
        raise ReconnectTimingEvidenceError(f"{field} must be a positive integer") from error
    return epoch if epoch > 0 else None


class ReconnectTimingEvidenceError(ValueError):
    """Raised when reconnect evidence is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise ReconnectTimingEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise ReconnectTimingEvidenceError("reconnect timing evidence must be a JSON object")
    return record


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ReconnectTimingEvidenceError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ReconnectTimingEvidenceError(f"{field} must be a finite number") from error
    if not math.isfinite(number):
        raise ReconnectTimingEvidenceError(f"{field} must be a finite number")
    return number


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ReconnectTimingEvidenceError(f"{field} must be a positive integer")
    try:
        integer = int(value)
    except (TypeError, ValueError) as error:
        raise ReconnectTimingEvidenceError(f"{field} must be a positive integer") from error
    if integer <= 0:
        raise ReconnectTimingEvidenceError(f"{field} must be a positive integer")
    return integer


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ReconnectTimingEvidenceError(f"{field} must be true or false")


def _read_optional_text(record: dict[str, Any], key: str, base_dir: Path | None) -> str:
    inline = record.get(key)
    if isinstance(inline, str) and inline:
        return inline
    path_value = record.get(f"{key}_path")
    if path_value in (None, ""):
        return ""
    if not isinstance(path_value, str):
        raise ReconnectTimingEvidenceError(f"{key}_path must be a string")
    path = Path(path_value)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ReconnectTimingEvidenceError(f"cannot read {path}: {error}") from error


def parse_android_diag_events(text: str, *, after_ms: float | None = None) -> dict[str, Any]:
    """Extract recovery markers from Android private diag lines.

    The private diag log uses device monotonic-ish millisecond stamps in square
    brackets. Logcat wall-clock prefixes are intentionally not used for timing
    math here because they do not share this monotonic timebase.
    """
    events: dict[str, Any] = {}
    for line in text.splitlines():
        match = _DIAG_LINE.match(line.strip())
        if not match:
            continue
        timestamp_ms = _finite_number(match.group("timestamp"), "diag timestamp")
        if after_ms is not None and timestamp_ms < after_ms:
            continue
        body = match.group("body")
        if "Protocol v1 upgrade accepted" in body and "protocol_v1_accepted_ms" not in events:
            events["protocol_v1_accepted_ms"] = timestamp_ms
        if "First frame:" in body and "first_frame_ms" not in events:
            config_epoch = _positive_epoch_from_match(_CONFIG_EPOCH_FIELD.search(body))
            frame_epoch = _positive_epoch_from_match(_SESSION_EPOCH_FIELD.search(body))
            if config_epoch is not None and frame_epoch is not None:
                events["first_frame_ms"] = timestamp_ms
                events["first_frame_session_epoch"] = frame_epoch
                events.setdefault("config_epoch", config_epoch)
        if "First output frame!" in body and "first_output_frame_ms" not in events:
            frame_epoch = _positive_epoch_from_match(_SESSION_EPOCH_FIELD.search(body))
            if frame_epoch is not None:
                events["first_output_frame_ms"] = timestamp_ms
                events["first_output_frame_session_epoch"] = frame_epoch
        if "session ended" in body and "session_ended_ms" not in events:
            events["session_ended_ms"] = timestamp_ms
        if "connection_opened" in body and "android_session_epoch" not in events:
            epoch = _ANDROID_SESSION_EPOCH_JSON.search(body)
            session_epoch = _positive_epoch_from_match(epoch)
            if session_epoch is not None:
                events["android_session_epoch"] = session_epoch
        if "onVideoConfiguration" in body and "config_epoch" not in events:
            epoch = _positive_epoch_from_match(_CONFIG_EPOCH.search(body))
            if epoch is not None:
                events["config_epoch"] = epoch
    return events


def parse_android_logcat_events(text: str, *, after_ms: float | None = None) -> dict[str, Any]:
    """Extract telemetry markers from VibeScreenTelemetry logcat lines.

    These timestamps come from the app's JSON payload (`timestamp_ms`), not from
    the logcat wall-clock prefix. The caller must provide a disruption start in
    the same Android wall-clock timebase when using these markers for timing.
    """
    events: dict[str, Any] = {}
    for line in text.splitlines():
        if "VibeScreenTelemetry" not in line:
            continue
        json_match = _JSON_OBJECT.search(line)
        if not json_match:
            continue
        try:
            payload = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        timestamp_value = payload.get("timestamp_ms")
        if timestamp_value in (None, ""):
            continue
        timestamp_ms = _finite_number(timestamp_value, "timestamp_ms")
        if after_ms is not None and timestamp_ms < after_ms:
            continue
        event = payload.get("event")
        if event == "protocol_v1_accepted" and "protocol_v1_accepted_ms" not in events:
            epoch = _positive_epoch_from_value(payload.get("session_epoch"), "session_epoch")
            if epoch is not None:
                events["protocol_v1_accepted_ms"] = timestamp_ms
                events["android_session_epoch"] = epoch
        elif event == "connection_opened" and "android_session_epoch" not in events:
            epoch = _positive_epoch_from_value(payload.get("session_epoch"), "session_epoch")
            if epoch is not None:
                events["android_session_epoch"] = epoch
        elif event == "first_frame_received" and "first_frame_ms" not in events:
            config_epoch = _positive_epoch_from_value(payload.get("config_epoch"), "config_epoch")
            epoch = _positive_epoch_from_value(payload.get("session_epoch"), "session_epoch")
            if config_epoch is not None and epoch is not None:
                events["first_frame_ms"] = timestamp_ms
                events["first_frame_session_epoch"] = epoch
                events.setdefault("config_epoch", config_epoch)
        elif event == "first_output_frame" and "first_output_frame_ms" not in events:
            epoch = _positive_epoch_from_value(payload.get("session_epoch"), "session_epoch")
            if epoch is not None:
                events["first_output_frame_ms"] = timestamp_ms
                events["first_output_frame_session_epoch"] = epoch
    return events


def parse_host_epoch(text: str) -> int | None:
    epochs = [int(match.group("epoch")) for match in _HOST_EPOCH.finditer(text)]
    return epochs[-1] if epochs else None


def _merged_events(attempt: dict[str, Any], base_dir: Path | None) -> dict[str, Any]:
    events = dict(attempt.get("events") or {})
    start_value = attempt.get("disruption_started_at_ms", events.get("disruption_started_ms"))
    start_ms = _finite_number(start_value, "disruption_started_at_ms") if start_value not in (None, "") else None
    android_diag = _read_optional_text(attempt, "android_diag", base_dir)
    android_logcat = _read_optional_text(attempt, "android_logcat", base_dir)
    if android_diag and android_logcat:
        raise ReconnectTimingEvidenceError(
            "provide android_diag or android_logcat, not both: their timestamps use different timebases"
        )
    if android_diag:
        parsed = parse_android_diag_events(android_diag, after_ms=start_ms)
        for key, value in parsed.items():
            events.setdefault(key, value)
    if android_logcat:
        parsed = parse_android_logcat_events(android_logcat, after_ms=start_ms)
        for key, value in parsed.items():
            events.setdefault(key, value)
    host_log = _read_optional_text(attempt, "host_log", base_dir)
    if host_log and attempt.get("host_connection_epoch") in (None, ""):
        epoch = parse_host_epoch(host_log)
        if epoch is not None:
            events.setdefault("host_connection_epoch", epoch)
    if start_ms is not None:
        events["disruption_started_ms"] = start_ms
    return events


def _artifact_paths(record: dict[str, Any], attempt: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for source in (record, attempt):
        value = source.get("artifact_paths")
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ReconnectTimingEvidenceError("artifact_paths must be a list of strings")
        paths.extend(value)
    for key in ("android_diag_path", "android_logcat_path", "host_log_path"):
        value = attempt.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    return sorted(dict.fromkeys(paths))


def _attempt_or_event(attempt: dict[str, Any], events: dict[str, Any], key: str) -> Any:
    value = attempt.get(key)
    return events.get(key) if value in (None, "") else value


def _validate_attempt(
    record: dict[str, Any],
    attempt: dict[str, Any],
    *,
    threshold_ms: float,
    base_dir: Path | None,
) -> dict[str, Any]:
    if not isinstance(attempt, dict):
        raise ReconnectTimingEvidenceError("each attempt must be an object")
    disruption = attempt.get("disruption")
    if disruption not in DISRUPTIONS:
        raise ReconnectTimingEvidenceError(
            "attempt disruption must be one of: " + ", ".join(DISRUPTIONS)
        )
    transport = attempt.get("transport")
    if transport not in TRANSPORTS:
        raise ReconnectTimingEvidenceError("attempt transport must be usb or lan")
    if disruption == DISRUPTION_ADB_REVERSE and transport != TRANSPORT_USB:
        raise ReconnectTimingEvidenceError("adb-reverse-disconnect requires usb transport")
    if disruption == DISRUPTION_LAN_NETWORK and transport != TRANSPORT_LAN:
        raise ReconnectTimingEvidenceError("lan-network-interrupt requires lan transport")

    explicit_status = attempt.get("status")
    if explicit_status == "blocked":
        blockers = attempt.get("blocking_reasons") or attempt.get("blockers") or []
        if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
            raise ReconnectTimingEvidenceError("blocked attempt reasons must be a list of strings")
        return {
            "name": attempt.get("name") or disruption,
            "disruption": disruption,
            "transport": transport,
            "verdict": "blocked",
            "can_close_timing_gate": False,
            "blocking_reasons": blockers or ["attempt was marked blocked"],
            "reasons": blockers or ["attempt was marked blocked"],
            "artifact_paths": _artifact_paths(record, attempt),
        }

    events = _merged_events(attempt, base_dir)
    reasons: list[str] = []
    failures: list[str] = []
    blocking_reasons: list[str] = []

    start_ms = events.get("disruption_started_ms")
    protocol_ms = events.get("protocol_v1_accepted_ms")
    first_frame_ms = events.get("first_frame_ms")
    first_output_ms = events.get("first_output_frame_ms")
    for field, value in (
        ("disruption_started_ms", start_ms),
        ("protocol_v1_accepted_ms", protocol_ms),
        ("first_frame_ms", first_frame_ms),
        ("first_output_frame_ms", first_output_ms),
    ):
        if value in (None, ""):
            reasons.append(f"missing {field}")
        else:
            events[field] = _finite_number(value, field)

    host_pid_before = _optional_positive_int(attempt.get("host_pid_before"), "host_pid_before")
    host_pid_after = _optional_positive_int(attempt.get("host_pid_after"), "host_pid_after")
    if host_pid_before is None or host_pid_after is None:
        reasons.append("missing host_pid_before or host_pid_after")
    elif host_pid_before != host_pid_after:
        failures.append("Host PID changed during reconnect")

    host_epoch = _optional_positive_int(
        _attempt_or_event(attempt, events, "host_connection_epoch"),
        "host_connection_epoch",
    )
    if host_epoch is None:
        reasons.append("missing Host Protocol v1 connection epoch")

    android_epoch = _optional_positive_int(
        _attempt_or_event(attempt, events, "android_session_epoch"),
        "android_session_epoch",
    )
    config_epoch = _optional_positive_int(
        _attempt_or_event(attempt, events, "config_epoch"),
        "config_epoch",
    )
    if android_epoch is None:
        reasons.append("missing android_session_epoch")
    if config_epoch is None:
        reasons.append("missing config_epoch")
    for field in ("first_frame_session_epoch", "first_output_frame_session_epoch"):
        marker_epoch = _optional_positive_int(events.get(field), field)
        if marker_epoch is None:
            reasons.append(f"missing {field}")
        elif android_epoch is not None and marker_epoch != android_epoch:
            reasons.append(f"{field} does not match android_session_epoch")

    if disruption == DISRUPTION_ADB_REVERSE:
        restored = _optional_bool(attempt.get("adb_reverse_restored"), "adb_reverse_restored")
        if restored is not True:
            reasons.append("adb_reverse_restored must be true for adb-reverse-disconnect")
    if disruption == DISRUPTION_LAN_NETWORK:
        encrypted = _optional_bool(attempt.get("trusted_lan_encrypted"), "trusted_lan_encrypted")
        legacy_plaintext = _optional_bool(
            attempt.get("trusted_lan_legacy_plaintext"), "trusted_lan_legacy_plaintext"
        )
        if encrypted is not True:
            blocking_reasons.append("trusted LAN encrypted record negotiation was not observed")
        if legacy_plaintext is not False:
            blocking_reasons.append("trusted LAN legacy plaintext fallback was not ruled out")

    metrics: dict[str, float] = {}
    if not reasons:
        start = float(events["disruption_started_ms"])
        protocol = float(events["protocol_v1_accepted_ms"])
        first_frame = float(events["first_frame_ms"])
        first_output = float(events["first_output_frame_ms"])
        if protocol < start:
            reasons.append("Protocol v1 accepted before disruption start")
        if first_frame < protocol:
            reasons.append("first frame preceded Protocol v1 recovery")
        if first_output < first_frame:
            reasons.append("first output frame preceded first received frame")
        if not reasons:
            metrics = {
                "protocol_recovery_ms": protocol - start,
                "first_frame_ms": first_frame - start,
                "first_output_frame_ms": first_output - start,
            }
            if metrics["first_output_frame_ms"] > threshold_ms:
                failures.append(
                    f"first output frame {metrics['first_output_frame_ms']:.3f} ms exceeds threshold {threshold_ms:.3f} ms"
                )

    if blocking_reasons:
        verdict = "blocked"
    elif failures:
        verdict = "fail"
    elif reasons:
        verdict = "insufficient"
    else:
        verdict = "pass"

    return {
        "name": attempt.get("name") or disruption,
        "disruption": disruption,
        "transport": transport,
        "verdict": verdict,
        "can_close_timing_gate": verdict == "pass",
        "threshold_ms": threshold_ms,
        "metrics": metrics,
        "timestamps_ms": {
            key: events[key]
            for key in (
                "disruption_started_ms",
                "protocol_v1_accepted_ms",
                "first_frame_ms",
                "first_output_frame_ms",
            )
            if key in events
        },
        "host_pid_before": host_pid_before,
        "host_pid_after": host_pid_after,
        "same_host_pid": host_pid_before is not None and host_pid_before == host_pid_after,
        "host_connection_epoch": host_epoch,
        "android_session_epoch": android_epoch,
        "config_epoch": config_epoch,
        "reasons": reasons + failures + blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _artifact_paths(record, attempt),
    }


def _required_disruptions(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return DISRUPTIONS
    unknown = [value for value in values if value not in DISRUPTIONS]
    if unknown:
        raise ReconnectTimingEvidenceError(
            "unsupported required disruption: " + ", ".join(unknown)
        )
    return tuple(dict.fromkeys(values))


def summarize(
    record: dict[str, Any],
    *,
    threshold_ms: float = DEFAULT_THRESHOLD_MS,
    required_disruptions: Sequence[str] | None = None,
    run_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    threshold_ms = _finite_number(threshold_ms, "threshold_ms")
    if threshold_ms <= 0:
        raise ReconnectTimingEvidenceError("threshold_ms must be positive")
    required = _required_disruptions(required_disruptions)
    full_gate_required = DISRUPTIONS
    full_gate_mode = tuple(required) == full_gate_required
    blocked_reasons = record.get("blocked_reasons") or record.get("blockers") or []
    if blocked_reasons:
        if not isinstance(blocked_reasons, list) or not all(isinstance(item, str) for item in blocked_reasons):
            raise ReconnectTimingEvidenceError("blocked_reasons must be a list of strings")
        attempts: list[dict[str, Any]] = []
        verdict = "blocked"
    else:
        raw_attempts = record.get("attempts")
        if not isinstance(raw_attempts, list):
            raise ReconnectTimingEvidenceError("record must contain an attempts array")
        attempts = [
            _validate_attempt(record, attempt, threshold_ms=threshold_ms, base_dir=base_dir)
            for attempt in raw_attempts
        ]
        observed = {attempt["disruption"] for attempt in attempts}
        missing = [disruption for disruption in required if disruption not in observed]
        summary_reasons: list[str] = [f"missing required disruption: {item}" for item in missing]
        if any(attempt["verdict"] == "fail" for attempt in attempts):
            verdict = "fail"
        elif any(attempt["verdict"] == "blocked" for attempt in attempts):
            verdict = "blocked"
        elif summary_reasons or any(attempt["verdict"] == "insufficient" for attempt in attempts):
            verdict = "insufficient"
        else:
            verdict = "pass"
        blocked_reasons = [
            reason
            for attempt in attempts
            for reason in attempt.get("blocking_reasons", [])
        ]

    missing_required = [] if blocked_reasons and not attempts else [
        disruption for disruption in required if disruption not in {attempt["disruption"] for attempt in attempts}
    ]
    full_gate_missing = [
        disruption for disruption in full_gate_required if disruption not in {attempt["disruption"] for attempt in attempts}
    ]
    full_gate_passed_attempts = {
        attempt["disruption"]
        for attempt in attempts
        if attempt["disruption"] in full_gate_required and attempt["verdict"] == "pass"
    }
    full_gate_failed_or_incomplete = [
        attempt["disruption"]
        for attempt in attempts
        if attempt["disruption"] in full_gate_required and attempt["verdict"] != "pass"
    ]
    can_close_full_gate = (
        verdict == "pass"
        and full_gate_mode
        and not full_gate_missing
        and set(full_gate_required) == full_gate_passed_attempts
        and not full_gate_failed_or_incomplete
    )
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or record.get("run_id") or str(uuid.uuid4()),
        "kind": "reconnect_timing_gate",
        "profile": "phase1-reconnect-within-3s",
        "verdict": verdict,
        "can_close_timing_gate": can_close_full_gate,
        "can_close_requested_scope": verdict == "pass",
        "full_gate_required_disruptions": list(full_gate_required),
        "full_gate_missing_disruptions": full_gate_missing,
        "threshold_ms": threshold_ms,
        "required_disruptions": list(required),
        "missing_required_disruptions": missing_required,
        "attempts": attempts,
        "device": record.get("device", {}),
        "host": record.get("host", {}),
        "artifact_paths": _artifact_paths(record, {}),
        "blocked_reasons": blocked_reasons,
        "notes": record.get("notes", "") if isinstance(record.get("notes", ""), str) else "",
    }
    if verdict == "insufficient":
        summary["reasons"] = [
            f"missing required disruption: {item}" for item in missing_required
        ] + [
            reason
            for attempt in attempts
            if attempt["verdict"] == "insufficient"
            for reason in attempt.get("reasons", [])
        ]
    elif verdict == "blocked":
        summary["reasons"] = blocked_reasons or ["run was blocked before timing evidence could be collected"]
    elif verdict == "fail":
        summary["reasons"] = [
            reason for attempt in attempts for reason in attempt.get("reasons", []) if attempt["verdict"] == "fail"
        ]
    else:
        summary["reasons"] = []
    return summary


def blocked_record(
    *,
    blockers: Sequence[str],
    target_device: str | None = None,
    artifact_paths: Sequence[str] = (),
    notes: str | None = None,
) -> dict[str, Any]:
    if not blockers:
        raise ReconnectTimingEvidenceError("at least one --blocker is required with --blocked")
    device = {"target": target_device} if target_device else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "reconnect_timing_observations",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "device": device,
        "attempts": [],
        "blocked_reasons": list(blockers),
        "artifact_paths": list(artifact_paths),
        "notes": notes or "",
    }


def _write_summary(summary: dict[str, Any], stream: TextIO) -> None:
    json.dump(summary, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Vibe Screen Phase 1 reconnect timing evidence.",
        epilog=(
            "A pass requires explicit disruption start, Protocol v1 recovery, first received frame, "
            "first output frame, stable Host PID, and all required disruption scenarios."
        ),
    )
    parser.add_argument("input", nargs="?", help="reconnect timing observation JSON, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--threshold-ms", type=float, default=DEFAULT_THRESHOLD_MS)
    parser.add_argument(
        "--require-disruption",
        action="append",
        choices=DISRUPTIONS,
        help="required disruption scenario; repeatable. Defaults to all Phase 1 scenarios.",
    )
    parser.add_argument("--run-id", help="identifier shared with the evidence manifest")
    parser.add_argument(
        "--base-dir",
        type=Path,
        help="base directory for relative log paths in the observation JSON",
    )
    parser.add_argument("--blocked", action="store_true", help="write a blocked summary without an input record")
    parser.add_argument("--blocker", action="append", default=[], help="blocking reason; repeatable with --blocked")
    parser.add_argument("--target-device", help="declared target device for a blocked run")
    parser.add_argument("--artifact", action="append", default=[], help="artifact path to include in a blocked run")
    parser.add_argument("--notes", help="free-form note for a blocked run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.blocked:
            record = blocked_record(
                blockers=args.blocker,
                target_device=args.target_device,
                artifact_paths=args.artifact,
                notes=args.notes,
            )
        else:
            if not args.input:
                raise ReconnectTimingEvidenceError("input is required unless --blocked is used")
            if args.input == "-":
                record = load_record(sys.stdin)
            else:
                input_path = Path(args.input)
                with input_path.open("r", encoding="utf-8") as stream:
                    record = load_record(stream)
                if args.base_dir is None:
                    args.base_dir = input_path.parent
        summary = summarize(
            record,
            threshold_ms=args.threshold_ms,
            required_disruptions=args.require_disruption,
            run_id=args.run_id,
            base_dir=args.base_dir,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (ReconnectTimingEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return INSUFFICIENT_EXIT
    verdict = summary["verdict"]
    if verdict == "pass":
        return 0
    if verdict == "fail":
        return FAIL_EXIT
    if verdict == "blocked":
        return BLOCKED_EXIT
    return INSUFFICIENT_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
