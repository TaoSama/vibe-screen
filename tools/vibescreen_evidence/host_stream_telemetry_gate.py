"""Evaluate stream telemetry required by the formal Host RSS gate."""

from __future__ import annotations

import math
from typing import Any

from . import SCHEMA_VERSION
from .soak_public_report import EvidenceInputError
from .soak_report import _parse_timestamp


EXACT_WINDOW_REPORT_KIND = "soak_exact_window_report"
MAXIMUM_STREAM_TELEMETRY_GAP_SECONDS = 90.0
MAXIMUM_HEARTBEAT_GAP_SECONDS = 90.0
MAXIMUM_FRAME_QUEUE_DROP_TOTAL = 0.0
MINIMUM_ACCEPTED_HEARTBEAT_COUNT = 1


def thresholds() -> dict[str, float | int]:
    return {
        "maximum_stream_telemetry_gap_seconds": MAXIMUM_STREAM_TELEMETRY_GAP_SECONDS,
        "maximum_heartbeat_gap_seconds": MAXIMUM_HEARTBEAT_GAP_SECONDS,
        "maximum_frame_queue_drop_total": MAXIMUM_FRAME_QUEUE_DROP_TOTAL,
        "minimum_accepted_heartbeat_count": MINIMUM_ACCEPTED_HEARTBEAT_COUNT,
    }


def missing_exact_window_report_evaluation() -> dict[str, Any]:
    return {
        "verdict": "insufficient",
        "sufficiency": {
            "exact_window_report_present": _boolean_criterion(False),
        },
        "criteria": {},
        "metrics": {},
        "reasons": [
            "telemetry insufficient: exact_window_report_present",
        ],
    }


def evaluate_exact_window_report(
    exact_window_report: dict[str, Any],
    *,
    run_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    metrics = _section(exact_window_report.get("metrics"), "exact_window_report.metrics")
    stream = _section(metrics.get("stream"), "exact_window_report.metrics.stream")
    telemetry = _section(metrics.get("telemetry"), "exact_window_report.metrics.telemetry")
    window = _section(exact_window_report.get("window"), "exact_window_report.window")
    source_summary = _section(
        exact_window_report.get("source_summary"),
        "exact_window_report.source_summary",
    )

    event_counts = _section(
        telemetry.get("event_counts"),
        "exact_window_report.metrics.telemetry.event_counts",
    )
    stream_stats_count = _non_negative_integer(
        event_counts.get("stream_stats", 0),
        "exact_window_report.metrics.telemetry.event_counts.stream_stats",
    )
    heartbeat_count = _non_negative_integer(
        event_counts.get("heartbeat_received", 0),
        "exact_window_report.metrics.telemetry.event_counts.heartbeat_received",
    )
    accepted_heartbeat_count = _non_negative_integer(
        telemetry.get("accepted_heartbeat_count"),
        "exact_window_report.metrics.telemetry.accepted_heartbeat_count",
    )
    stream_stats_gaps = _gap_statistics(
        telemetry.get("stream_stats_gaps"),
        "exact_window_report.metrics.telemetry.stream_stats_gaps",
    )
    heartbeat_gaps = _gap_statistics(
        telemetry.get("heartbeat_gaps"),
        "exact_window_report.metrics.telemetry.heartbeat_gaps",
    )
    fps = _statistics(stream.get("fps"), "exact_window_report.metrics.stream.fps")
    queue_depth = _statistics(
        stream.get("queue_depth"),
        "exact_window_report.metrics.stream.queue_depth",
    )
    queue_capacity = _statistics(
        stream.get("queue_capacity"),
        "exact_window_report.metrics.stream.queue_capacity",
    )
    encoder_in_flight, encoder_capacity, encoder_pair_complete = _stat_pair_present(
        stream,
        "encoder_in_flight",
        "encoder_in_flight_capacity",
    )
    frame_registry_count = _statistics(
        stream.get("frame_registry_count"),
        "exact_window_report.metrics.stream.frame_registry_count",
    )
    latest_pixel_buffer_retained, latest_pixel_buffer_capacity, latest_pair_complete = (
        _stat_pair_present(
            stream,
            "latest_pixel_buffer_retained",
            "latest_pixel_buffer_capacity",
        )
    )
    frame_queue_drop_total = _finite_number(
        stream.get("frame_queue_drop_total"),
        "exact_window_report.metrics.stream.frame_queue_drop_total",
        minimum=0,
    )
    fallback_values = _boolean_list(
        telemetry.get("fallback_capture_active_values", []),
        "exact_window_report.metrics.telemetry.fallback_capture_active_values",
    )
    encoder_present_values = _boolean_list(
        telemetry.get("encoder_present_values", []),
        "exact_window_report.metrics.telemetry.encoder_present_values",
    )

    sufficiency = {
        "schema_version": _boolean_criterion(
            exact_window_report.get("schema_version") == SCHEMA_VERSION
        ),
        "kind": _boolean_criterion(
            exact_window_report.get("kind") == EXACT_WINDOW_REPORT_KIND
        ),
        "run_id": _boolean_criterion(exact_window_report.get("run_id") == run_id),
        "derivation_complete": _boolean_criterion(
            exact_window_report.get("derivation_status") == "complete"
            and exact_window_report.get("errors") == []
        ),
        "source_summary_complete": _boolean_criterion(
            source_summary.get("status") == "complete"
            and source_summary.get("errors") == []
        ),
        "window_matches_summary": _boolean_criterion(
            _matching_timestamp(
                window.get("started_at"),
                summary.get("started_at"),
                "exact_window_report.window.started_at",
            )
            and _matching_timestamp(
                window.get("finished_at"),
                summary.get("finished_at"),
                "exact_window_report.window.finished_at",
            )
        ),
        "stream_stats_present": _minimum_criterion(stream_stats_count, 1),
        "heartbeat_present": _minimum_criterion(heartbeat_count, 1),
        "accepted_heartbeat_present": _minimum_criterion(
            accepted_heartbeat_count,
            MINIMUM_ACCEPTED_HEARTBEAT_COUNT,
        ),
        "queue_metrics_present": _boolean_criterion(
            queue_depth is not None and queue_capacity is not None
        ),
        "encoder_metrics_present": _boolean_criterion(
            encoder_pair_complete
            and encoder_in_flight is not None
            and encoder_capacity is not None
            and frame_registry_count is not None
        ),
        "latest_pixel_buffer_metrics_present": _boolean_criterion(
            latest_pair_complete
            and latest_pixel_buffer_retained is not None
            and latest_pixel_buffer_capacity is not None
        ),
        "capture_state_booleans_present": _boolean_criterion(
            bool(fallback_values) and bool(encoder_present_values)
        ),
    }
    criteria = {
        "stream_stats_window_gap_seconds": _criterion(
            stream_stats_gaps["maximum_window_gap_seconds"],
            MAXIMUM_STREAM_TELEMETRY_GAP_SECONDS,
        ),
        "heartbeat_window_gap_seconds": _criterion(
            heartbeat_gaps["maximum_window_gap_seconds"],
            MAXIMUM_HEARTBEAT_GAP_SECONDS,
        ),
        "all_heartbeats_accepted": _boolean_criterion(
            heartbeat_count > 0 and accepted_heartbeat_count == heartbeat_count
        ),
        "minimum_fps_positive": _minimum_criterion(
            fps["min"] if fps else None,
            0.000001,
        ),
        "frame_queue_drop_total": _criterion(
            frame_queue_drop_total,
            MAXIMUM_FRAME_QUEUE_DROP_TOTAL,
        ),
        "queue_depth_within_capacity": _boolean_criterion(
            queue_depth is not None
            and queue_capacity is not None
            and queue_capacity["min"] > 0
            and queue_capacity["min"] == queue_capacity["max"]
            and queue_depth["max"] <= queue_capacity["min"]
        ),
        "encoder_in_flight_within_capacity": _boolean_criterion(
            encoder_in_flight is not None
            and encoder_capacity is not None
            and encoder_capacity["min"] > 0
            and encoder_capacity["min"] == encoder_capacity["max"]
            and encoder_in_flight["max"] <= encoder_capacity["min"]
        ),
        "frame_registry_within_encoder_capacity": _boolean_criterion(
            frame_registry_count is not None
            and encoder_capacity is not None
            and frame_registry_count["max"] <= encoder_capacity["min"]
        ),
        "latest_pixel_buffer_within_capacity": _boolean_criterion(
            latest_pixel_buffer_retained is not None
            and latest_pixel_buffer_capacity is not None
            and latest_pixel_buffer_capacity["min"] > 0
            and latest_pixel_buffer_capacity["min"] == latest_pixel_buffer_capacity["max"]
            and latest_pixel_buffer_retained["max"] <= latest_pixel_buffer_capacity["min"]
        ),
        "encoder_present_through_window": _boolean_criterion(encoder_present_values == [True]),
    }
    insufficiencies = [
        name for name, item in sufficiency.items() if not item["passed"]
    ]
    failures = [name for name, item in criteria.items() if not item["passed"]]
    verdict = "pass"
    reasons: list[str] = []
    if insufficiencies:
        verdict = "insufficient"
        reasons.extend(f"telemetry insufficient: {name}" for name in insufficiencies)
    elif failures:
        verdict = "fail"
        reasons.extend(f"telemetry criterion failed: {name}" for name in failures)
    return {
        "verdict": verdict,
        "sufficiency": sufficiency,
        "criteria": criteria,
        "metrics": {
            "stream_stats_count": stream_stats_count,
            "heartbeat_count": heartbeat_count,
            "accepted_heartbeat_count": accepted_heartbeat_count,
            "stream_stats_gaps": stream_stats_gaps,
            "heartbeat_gaps": heartbeat_gaps,
            "fps": fps,
            "queue_depth": queue_depth,
            "queue_capacity": queue_capacity,
            "encoder_in_flight": encoder_in_flight,
            "encoder_in_flight_capacity": encoder_capacity,
            "frame_registry_count": frame_registry_count,
            "latest_pixel_buffer_retained": latest_pixel_buffer_retained,
            "latest_pixel_buffer_capacity": latest_pixel_buffer_capacity,
            "frame_queue_drop_total": frame_queue_drop_total,
            "fallback_capture_active_values": fallback_values,
            "encoder_present_values": encoder_present_values,
        },
        "reasons": reasons,
    }


def _criterion(
    measured: float | int | None,
    maximum: float,
) -> dict[str, float | bool | None]:
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured is not None and float(measured) <= maximum,
    }


def _minimum_criterion(
    measured: float | int | None,
    minimum: float,
) -> dict[str, float | bool | None]:
    return {
        "measured": measured,
        "minimum": minimum,
        "passed": measured is not None and float(measured) >= minimum,
    }


def _boolean_criterion(passed: bool) -> dict[str, bool]:
    return {"passed": passed}


def _finite_number(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EvidenceInputError(f"{context}: must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise EvidenceInputError(f"{context}: must be finite")
    if minimum is not None and converted < minimum:
        raise EvidenceInputError(f"{context}: must be at least {minimum:g}")
    return converted


def _non_negative_integer(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvidenceInputError(f"{context}: must be a non-negative integer")
    return value


def _section(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{context}: must be an object")
    return value


def _statistics(value: Any, context: str) -> dict[str, float | int] | None:
    if value is None:
        return None
    section = _section(value, context)
    count = _non_negative_integer(section.get("count"), f"{context}.count")
    return {
        "count": count,
        "first": _finite_number(section.get("first"), f"{context}.first"),
        "final": _finite_number(section.get("final"), f"{context}.final"),
        "min": _finite_number(section.get("min"), f"{context}.min"),
        "mean": _finite_number(section.get("mean"), f"{context}.mean"),
        "max": _finite_number(section.get("max"), f"{context}.max"),
    }


def _gap_statistics(value: Any, context: str) -> dict[str, float | int | None]:
    section = _section(value, context)
    return {
        "count": _non_negative_integer(section.get("count"), f"{context}.count"),
        "maximum_interval_seconds": _optional_non_negative_number(
            section.get("maximum_interval_seconds"),
            f"{context}.maximum_interval_seconds",
        ),
        "maximum_window_gap_seconds": _optional_non_negative_number(
            section.get("maximum_window_gap_seconds"),
            f"{context}.maximum_window_gap_seconds",
        ),
    }


def _optional_non_negative_number(value: Any, context: str) -> float | None:
    if value is None:
        return None
    return _finite_number(value, context, minimum=0)


def _matching_timestamp(left: Any, right: Any, context: str) -> bool:
    return _parse_timestamp(left, f"{context}.left") == _parse_timestamp(
        right, f"{context}.right"
    )


def _stat_pair_present(
    stream: dict[str, Any], left_name: str, right_name: str
) -> tuple[dict[str, float | int] | None, dict[str, float | int] | None, bool]:
    left = _statistics(stream.get(left_name), f"metrics.stream.{left_name}")
    right = _statistics(stream.get(right_name), f"metrics.stream.{right_name}")
    return left, right, (left is None) == (right is None)


def _boolean_list(value: Any, context: str) -> list[bool]:
    if not isinstance(value, list) or not all(isinstance(item, bool) for item in value):
        raise EvidenceInputError(f"{context}: must be an array of booleans")
    return value
