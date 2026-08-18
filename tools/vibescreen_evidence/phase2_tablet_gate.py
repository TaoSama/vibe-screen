"""Evaluate the Phase 2 eight-hour tablet productization evidence gate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .soak_public_report import EvidenceInputError, read_json as _read_json
from .soak_report import SOAK_REPORT_KIND


GATE_KIND = "phase2_tablet_productization_gate"
MINIMUM_DURATION_SECONDS = 8 * 60 * 60 * 0.98
MINIMUM_SAMPLE_COUNT = 8 * 60 * 2 * 0.98
MINIMUM_TELEMETRY_COUNT = 8 * 60 * 2 * 0.98
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_STREAM_STATS_GAP_SECONDS = 90.0
MAXIMUM_HEARTBEAT_GAP_SECONDS = 90.0
MAXIMUM_RECONNECT_COUNT = 0
MAXIMUM_QUEUE_DROP_TOTAL = 0.0
MAXIMUM_DROPPED_FRAMES = 0.0
MAXIMUM_THERMAL_STATUS = 2.0
MAXIMUM_BATTERY_TEMPERATURE_CELSIUS = 45.0
MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB = 8 * 1024.0
MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB = 8 * 1024.0

INTERPRETATION = (
    "A pass means the supplied exact-window report meets the Phase 2 tablet "
    "soak evidence thresholds. It does not prove unmeasured physical-tablet, "
    "stand, login, or headless conditions unless those raw artifacts are present "
    "in the evidence bundle."
)


def _thresholds() -> dict[str, float | int]:
    return {
        "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
        "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
        "minimum_telemetry_count": MINIMUM_TELEMETRY_COUNT,
        "maximum_sample_gap_seconds": MAXIMUM_SAMPLE_GAP_SECONDS,
        "maximum_stream_stats_gap_seconds": MAXIMUM_STREAM_STATS_GAP_SECONDS,
        "maximum_heartbeat_gap_seconds": MAXIMUM_HEARTBEAT_GAP_SECONDS,
        "maximum_reconnect_count": MAXIMUM_RECONNECT_COUNT,
        "maximum_queue_drop_total": MAXIMUM_QUEUE_DROP_TOTAL,
        "maximum_dropped_frames": MAXIMUM_DROPPED_FRAMES,
        "maximum_thermal_status": MAXIMUM_THERMAL_STATUS,
        "maximum_battery_temperature_celsius": MAXIMUM_BATTERY_TEMPERATURE_CELSIUS,
        "maximum_client_rss_second_half_slope_kib_per_minute": (
            MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_client_rss_second_half_drift_kib": (
            MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB
        ),
        "maximum_host_rss_second_half_slope_kib_per_minute": (
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_host_rss_second_half_drift_kib": (
            MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB
        ),
    }


def _get(record: dict[str, Any], *path: str) -> Any:
    value: Any = record
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = float(value)
        except (OverflowError, ValueError):
            return None
        if math.isfinite(converted):
            return converted
    return None


def _criterion(measured: float | None, maximum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured is not None and measured <= maximum,
    }


def _minimum(measured: float | None, minimum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "minimum": minimum,
        "passed": measured is not None and measured >= minimum,
    }


def _stats_count(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if isinstance(value, dict):
        return _finite_number(value.get("count"))
    return None


def _stats_max(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if isinstance(value, dict):
        return _finite_number(value.get("max"))
    return None


def _stats_drift(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if not isinstance(value, dict):
        return None
    first = _finite_number(value.get("first"))
    final = _finite_number(value.get("final"))
    if first is None or final is None:
        return None
    return final - first


def _event_count(report: dict[str, Any], event: str) -> float | None:
    value = _get(report, "metrics", "telemetry", "event_counts", event)
    return 0.0 if value is None else _finite_number(value)


def _rss_criteria(
    report: dict[str, Any],
    section: str,
    maximum_slope: float,
    maximum_drift: float,
) -> dict[str, dict[str, Any]]:
    prefix = ("metrics", "memory_kib", section)
    slope = _finite_number(_get(report, *prefix, "slope_kib_per_minute", "second_half"))
    drift = _stats_drift(report, *prefix)
    return {
        f"{section}_second_half_slope_kib_per_minute": _criterion(
            slope, maximum_slope
        ),
        f"{section}_full_window_endpoint_drift_kib": _criterion(
            drift, maximum_drift
        ),
    }


def _validate_report(report: dict[str, Any]) -> str | None:
    if report.get("schema_version") != SCHEMA_VERSION:
        return f"report.schema_version must be {SCHEMA_VERSION}"
    if report.get("kind") != SOAK_REPORT_KIND:
        return f"report.kind must be {SOAK_REPORT_KIND}"
    if report.get("derivation_status") != "complete":
        return "report derivation_status is not complete"
    if _get(report, "source_summary", "status") != "complete":
        return "source soak summary is not complete"
    errors = report.get("errors", [])
    if errors != []:
        return "report carries derivation errors"
    source_errors = _get(report, "source_summary", "errors")
    if source_errors not in (None, []):
        return "source soak summary carries errors"
    return None


def derive_gate(report_path: Path) -> dict[str, Any]:
    report = _read_json(report_path, "exact-window report")
    validation_error = _validate_report(report)
    window = report.get("window") if isinstance(report.get("window"), dict) else {}
    source_summary = (
        report.get("source_summary")
        if isinstance(report.get("source_summary"), dict)
        else {}
    )
    run_id = report.get("run_id")

    sufficiency = {
        "duration": _minimum(
            _finite_number(window.get("duration_seconds")), MINIMUM_DURATION_SECONDS
        ),
        "sample_count": _minimum(
            _finite_number(window.get("sample_records_in_window")),
            MINIMUM_SAMPLE_COUNT,
        ),
        "telemetry_count": _minimum(
            _finite_number(window.get("telemetry_records_in_window")),
            MINIMUM_TELEMETRY_COUNT,
        ),
        "sample_gap": _criterion(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "samples",
                    "gaps",
                    "maximum_window_gap_seconds",
                )
            ),
            MAXIMUM_SAMPLE_GAP_SECONDS,
        ),
        "stream_stats_gap": _criterion(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "telemetry",
                    "stream_stats_gaps",
                    "maximum_window_gap_seconds",
                )
            ),
            MAXIMUM_STREAM_STATS_GAP_SECONDS,
        ),
        "heartbeat_gap": _criterion(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "telemetry",
                    "heartbeat_gaps",
                    "maximum_window_gap_seconds",
                )
            ),
            MAXIMUM_HEARTBEAT_GAP_SECONDS,
        ),
        "accepted_heartbeat_count": _minimum(
            _finite_number(
                _get(report, "metrics", "telemetry", "accepted_heartbeat_count")
            ),
            MINIMUM_TELEMETRY_COUNT,
        ),
        "client_memory_samples": _minimum(
            _stats_count(report, "metrics", "memory_kib", "client_total_pss"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "thermal_samples": _minimum(
            _stats_count(report, "metrics", "thermal", "status"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "battery_samples": _minimum(
            _stats_count(report, "metrics", "battery", "level_percent"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "stream_fps_samples": _minimum(
            _stats_count(report, "metrics", "stream", "fps"),
            MINIMUM_TELEMETRY_COUNT,
        ),
    }

    criteria = {
        "session_disconnect_count": _criterion(
            _event_count(report, "session_disconnected"), MAXIMUM_RECONNECT_COUNT
        ),
        "stream_frame_queue_drop_total": _criterion(
            _finite_number(_get(report, "metrics", "stream", "frame_queue_drop_total")),
            MAXIMUM_QUEUE_DROP_TOTAL,
        ),
        "stream_reported_dropped_frames": _criterion(
            _finite_number(
                _get(report, "metrics", "stream", "reported_dropped_frames", "sum")
            ),
            MAXIMUM_DROPPED_FRAMES,
        ),
        "thermal_status_max": _criterion(
            _stats_max(report, "metrics", "thermal", "status"),
            MAXIMUM_THERMAL_STATUS,
        ),
        "battery_temperature_celsius_max": _criterion(
            _stats_max(report, "metrics", "battery", "temperature_celsius"),
            MAXIMUM_BATTERY_TEMPERATURE_CELSIUS,
        ),
        **_rss_criteria(
            report,
            "client_total_pss",
            MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
            MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB,
        ),
        **_rss_criteria(
            report,
            "host_rss",
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
            MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB,
        ),
    }

    reasons: list[str] = []
    if validation_error is not None:
        reasons.append(validation_error)
    reasons.extend(
        f"insufficient evidence: {name}"
        for name, item in sufficiency.items()
        if not item["passed"]
    )
    missing_criteria = {
        name for name, item in criteria.items() if item["measured"] is None
    }
    reasons.extend(
        (
            f"{'insufficient evidence' if name in missing_criteria else 'criterion failed'}: "
            f"{name}"
        )
        for name, item in criteria.items()
        if not item["passed"]
    )
    if (
        validation_error is not None
        or any(not item["passed"] for item in sufficiency.values())
        or missing_criteria
    ):
        verdict = "insufficient"
    elif any(not item["passed"] for item in criteria.values()):
        verdict = "fail"
    else:
        verdict = "pass"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "run_id": run_id,
        "window": {
            "started_at": window.get("started_at"),
            "finished_at": window.get("finished_at"),
            "duration_seconds": window.get("duration_seconds"),
            "sample_records_in_window": window.get("sample_records_in_window"),
            "telemetry_records_in_window": window.get("telemetry_records_in_window"),
        },
        "source_summary": {
            "status": source_summary.get("status"),
            "error_count": len(source_summary.get("errors", []))
            if isinstance(source_summary.get("errors", []), list)
            else None,
        },
        "thresholds": _thresholds(),
        "sufficiency": sufficiency,
        "criteria": criteria,
        "reasons": reasons,
        "interpretation": INTERPRETATION,
    }


def _failure_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "failed",
        "verdict": "insufficient",
        "window": {},
        "source_summary": {},
        "thresholds": _thresholds(),
        "sufficiency": {},
        "criteria": {},
        "reasons": ["the Phase 2 tablet gate inputs could not be validated"],
        "interpretation": INTERPRETATION,
    }


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="exact-window soak report JSON")
    parser.add_argument("--output", type=Path, required=True, help="Phase 2 gate JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_gate(arguments.report)
        _write_json(arguments.output, report)
    except (EvidenceInputError, OSError, TypeError, ValueError):
        report = _failure_report()
        try:
            _write_json(arguments.output, report)
        except (OSError, TypeError, ValueError):
            print("error: Phase 2 tablet gate output could not be written", file=sys.stderr)
            return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
