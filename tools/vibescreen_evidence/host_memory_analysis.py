"""Pure analysis for short macOS Host memory diagnostics."""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
import math
from statistics import median
from typing import Any

from .soak_public_report import EvidenceInputError


ATTRIBUTIONS = {"retained_growth", "allocator_high_water", "inconclusive"}
VERDICTS = {"pass", "fail", "insufficient"}
MINIMUM_DURATION_SECONDS = 10 * 60.0
MINIMUM_LIGHTWEIGHT_SAMPLE_COUNT = 20
MINIMUM_HEAP_SAMPLE_COUNT = 3
MAXIMUM_BOUNDARY_GAP_SECONDS = 60.0
MAXIMUM_MEMORY_INTERNAL_GAP_SECONDS = 90.0
MAXIMUM_TELEMETRY_BOUNDARY_GAP_SECONDS = 30.0
MAXIMUM_TELEMETRY_INTERNAL_GAP_SECONDS = 10.0
ENDPOINT_FRACTION = 0.20
PRESSURE_MINIMUM_DRIFT_BYTES = 1024 * 1024
PRESSURE_MINIMUM_SLOPE_BYTES_PER_MINUTE = 32 * 1024
LIVE_MINIMUM_DRIFT_BYTES = 512 * 1024
LIVE_MINIMUM_SLOPE_BYTES_PER_MINUTE = 16 * 1024
HEAP_MINIMUM_NODE_DRIFT = 500
STABLE_MAXIMUM_DRIFT_BYTES = 256 * 1024
STABLE_MAXIMUM_SLOPE_BYTES_PER_MINUTE = 16 * 1024
STABLE_MAXIMUM_NODE_DRIFT = 100
FRAGMENTATION_MINIMUM_DRIFT_BYTES = 512 * 1024

INTERPRETATION = (
    "This verdict applies only to the complete 10-17 minute diagnostic "
    "window. A pass means the required memory signals remained within the "
    "short-window stability thresholds while stream telemetry and bounded "
    "queues remained healthy. It is not the formal two-hour Host RSS "
    "no-growth gate and cannot close it; only host_rss_gate can evaluate "
    "the two-hour requirement."
)
MEMORY_COMPLETENESS_FIELDS = (
    "rss_bytes",
    "physical_footprint_bytes",
    "malloc_small_dirty_bytes",
    "malloc_zone_dirty_bytes",
    "malloc_zone_allocated_bytes",
    "malloc_zone_fragmentation_bytes",
)
HEAP_COMPLETENESS_FIELDS = ("node_count", "allocated_bytes")
SUFFICIENCY_FIELDS = (
    "collection_complete",
    "duration",
    "memory_samples",
    "memory_window_coverage",
    "heap_samples",
    "heap_window_coverage",
    "error_free",
    *(f"{field}_complete" for field in MEMORY_COMPLETENESS_FIELDS),
    *(f"heap_{field}_complete" for field in HEAP_COMPLETENESS_FIELDS),
    "stream_telemetry",
)


def thresholds() -> dict[str, float | int]:
    return {
        "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
        "minimum_memory_sample_count": MINIMUM_LIGHTWEIGHT_SAMPLE_COUNT,
        "minimum_heap_sample_count": MINIMUM_HEAP_SAMPLE_COUNT,
        "maximum_boundary_gap_seconds": MAXIMUM_BOUNDARY_GAP_SECONDS,
        "maximum_memory_internal_gap_seconds": (
            MAXIMUM_MEMORY_INTERNAL_GAP_SECONDS
        ),
        "maximum_telemetry_boundary_gap_seconds": (
            MAXIMUM_TELEMETRY_BOUNDARY_GAP_SECONDS
        ),
        "maximum_telemetry_internal_gap_seconds": (
            MAXIMUM_TELEMETRY_INTERNAL_GAP_SECONDS
        ),
        "pressure_minimum_drift_bytes": PRESSURE_MINIMUM_DRIFT_BYTES,
        "pressure_minimum_slope_bytes_per_minute": (
            PRESSURE_MINIMUM_SLOPE_BYTES_PER_MINUTE
        ),
        "live_minimum_drift_bytes": LIVE_MINIMUM_DRIFT_BYTES,
        "live_minimum_slope_bytes_per_minute": (
            LIVE_MINIMUM_SLOPE_BYTES_PER_MINUTE
        ),
        "heap_minimum_node_drift": HEAP_MINIMUM_NODE_DRIFT,
        "stable_maximum_drift_bytes": STABLE_MAXIMUM_DRIFT_BYTES,
        "stable_maximum_slope_bytes_per_minute": (
            STABLE_MAXIMUM_SLOPE_BYTES_PER_MINUTE
        ),
        "stable_maximum_node_drift": STABLE_MAXIMUM_NODE_DRIFT,
        "fragmentation_minimum_drift_bytes": FRAGMENTATION_MINIMUM_DRIFT_BYTES,
    }


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _trend(points: list[tuple[float, float]]) -> dict[str, float | int]:
    if len(points) < 2:
        raise ValueError("trend requires at least two points")
    points = sorted(points)
    origin = points[0][0]
    x_values = [(elapsed - origin) / 60.0 for elapsed, _ in points]
    y_values = [value for _, value in points]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator <= 0:
        raise ValueError("trend timestamps have no span")
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    ) / denominator
    endpoint_count = max(1, math.ceil(len(y_values) * ENDPOINT_FRACTION))
    drift = median(y_values[-endpoint_count:]) - median(y_values[:endpoint_count])
    return {
        "sample_count": len(points),
        "slope_per_minute": slope,
        "endpoint_median_drift": drift,
    }


def _series(
    records: list[dict[str, Any]], field: str, *, section: str
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for record in records:
        elapsed = _number(record.get("elapsed_seconds"))
        values = record.get(section)
        value = _number(values.get(field)) if isinstance(values, dict) else None
        if elapsed is not None and value is not None:
            points.append((elapsed, value))
    return points


def _is_growth(trend: dict[str, float | int], *, live: bool) -> bool:
    minimum_drift = LIVE_MINIMUM_DRIFT_BYTES if live else PRESSURE_MINIMUM_DRIFT_BYTES
    minimum_slope = (
        LIVE_MINIMUM_SLOPE_BYTES_PER_MINUTE
        if live
        else PRESSURE_MINIMUM_SLOPE_BYTES_PER_MINUTE
    )
    return (
        trend["endpoint_median_drift"] >= minimum_drift
        and trend["slope_per_minute"] >= minimum_slope
    )


def _is_stable(trend: dict[str, float | int]) -> bool:
    return (
        abs(trend["endpoint_median_drift"]) <= STABLE_MAXIMUM_DRIFT_BYTES
        and abs(trend["slope_per_minute"]) <= STABLE_MAXIMUM_SLOPE_BYTES_PER_MINUTE
    )


def _is_not_growing(trend: dict[str, float | int]) -> bool:
    return (
        trend["endpoint_median_drift"] <= STABLE_MAXIMUM_DRIFT_BYTES
        and trend["slope_per_minute"] <= STABLE_MAXIMUM_SLOPE_BYTES_PER_MINUTE
    )


def _heap_class_growth(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, dict[str, Any]]] = []
    for record in records:
        heap = record.get("heap")
        if not isinstance(heap, dict):
            continue
        classes = heap.get("classes")
        if not isinstance(classes, list):
            continue
        snapshot: dict[str, dict[str, Any]] = {}
        for item in classes:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                snapshot[item["name"]] = item
        snapshots.append(snapshot)
    if len(snapshots) < 2:
        return []

    growth: list[dict[str, Any]] = []
    for name in set(snapshots[0]).intersection(snapshots[-1]):
        first = snapshots[0][name]
        last = snapshots[-1][name]
        first_count = _number(first.get("count"))
        last_count = _number(last.get("count"))
        first_bytes = _number(first.get("allocated_bytes"))
        last_bytes = _number(last.get("allocated_bytes"))
        if None in (first_count, last_count, first_bytes, last_bytes):
            continue
        growth.append(
            {
                "name": name,
                "count_drift": last_count - first_count,
                "allocated_bytes_drift": last_bytes - first_bytes,
            }
        )
    return sorted(
        growth,
        key=lambda item: (item["allocated_bytes_drift"], item["count_drift"]),
        reverse=True,
    )[:20]


def _analyze_telemetry(
    records: list[dict[str, Any]],
    *,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    stream_records: list[dict[str, Any]] = []
    stream_timestamps: list[datetime] = []
    session_epochs: set[int] = set()
    total_stream_stats = 0
    out_of_window_records = 0
    invalid_records = 0
    required = ("queue_depth", "queue_capacity", "fps")
    optional = ("encoder_in_flight", "encoder_in_flight_capacity")
    missing_required_fields: set[str] = set()
    missing_optional_fields: set[str] = set()
    values: dict[str, list[float]] = {
        key: [] for key in (*required, *optional)
    }
    for record in records:
        if record.get("event") != "stream_stats":
            continue
        total_stream_stats += 1
        try:
            timestamp = _parse_time(record.get("wall_time"))
        except (TypeError, ValueError):
            invalid_records += 1
            continue
        schema_version = record.get("schema_version")
        monotonic_ns = record.get("monotonic_ns")
        session_epoch = record.get("session_epoch")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != 1
            or isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
            or monotonic_ns < 0
            or isinstance(session_epoch, bool)
            or not isinstance(session_epoch, int)
            or session_epoch < 1
        ):
            invalid_records += 1
            continue
        attributes = record.get("attributes")
        if not isinstance(attributes, dict):
            missing_required_fields.update(required)
            missing_optional_fields.update(optional)
            invalid_records += 1
            continue
        normalized: dict[str, float] = {}
        invalid_fields = False
        for key in required:
            value = _number(attributes.get(key))
            if value is None:
                missing_required_fields.add(key)
                invalid_fields = True
            else:
                normalized[key] = value
        for key in optional:
            if key not in attributes:
                missing_optional_fields.add(key)
                continue
            value = _number(attributes.get(key))
            if value is None:
                missing_optional_fields.add(key)
                invalid_fields = True
            else:
                normalized[key] = value
        if invalid_fields:
            invalid_records += 1
            continue
        if not started_at <= timestamp <= finished_at:
            out_of_window_records += 1
            continue
        stream_records.append(record)
        stream_timestamps.append(timestamp)
        session_epochs.add(session_epoch)
        for key, value in normalized.items():
            values[key].append(value)
    stream_timestamps.sort()

    anomalies: list[str] = []
    if (
        values["queue_depth"]
        and values["queue_capacity"]
        and max(values["queue_depth"]) > min(values["queue_capacity"])
    ):
        anomalies.append("network frame queue depth exceeded its advertised capacity")
    if values["queue_capacity"] and (
        min(values["queue_capacity"]) <= 0
        or len(set(values["queue_capacity"])) != 1
    ):
        anomalies.append("network frame queue capacity was invalid or changed")
    if (
        values["encoder_in_flight"]
        and values["encoder_in_flight_capacity"]
        and max(values["encoder_in_flight"])
        > min(values["encoder_in_flight_capacity"])
    ):
        anomalies.append("VideoToolbox in-flight count exceeded its advertised capacity")
    if values["fps"] and min(values["fps"]) <= 0:
        anomalies.append("stream_stats reported non-positive FPS")
    start_gap = (stream_timestamps[0] - started_at).total_seconds() if stream_timestamps else None
    finish_gap = (finished_at - stream_timestamps[-1]).total_seconds() if stream_timestamps else None
    internal_gaps = [
        (right - left).total_seconds()
        for left, right in pairwise(stream_timestamps)
    ]
    maximum_internal_gap = max(internal_gaps) if internal_gaps else None
    coverage_complete = (
        start_gap is not None
        and finish_gap is not None
        and maximum_internal_gap is not None
        and 0 <= start_gap <= MAXIMUM_TELEMETRY_BOUNDARY_GAP_SECONDS
        and 0 <= finish_gap <= MAXIMUM_TELEMETRY_BOUNDARY_GAP_SECONDS
        and maximum_internal_gap <= MAXIMUM_TELEMETRY_INTERNAL_GAP_SECONDS
    )
    admitted_record_count = len(stream_records)
    if total_stream_stats != (
        admitted_record_count + out_of_window_records + invalid_records
    ):
        raise EvidenceInputError("host memory diagnostic: telemetry counts disagree")
    return {
        "total_stream_stats_count": total_stream_stats,
        "stream_stats_count": admitted_record_count,
        "out_of_window_record_count": out_of_window_records,
        "invalid_record_count": invalid_records,
        "missing_required_fields": sorted(missing_required_fields),
        "missing_optional_fields": sorted(missing_optional_fields),
        "session_epochs": sorted(session_epochs),
        "single_session": len(session_epochs) == 1,
        "start_boundary_gap_seconds": start_gap,
        "finish_boundary_gap_seconds": finish_gap,
        "maximum_internal_gap_seconds": maximum_internal_gap,
        "coverage_complete": coverage_complete,
        "minimum_fps": min(values["fps"]) if values["fps"] else None,
        "maximum_queue_depth": (
            max(values["queue_depth"]) if values["queue_depth"] else None
        ),
        "queue_capacity": (
            min(values["queue_capacity"]) if values["queue_capacity"] else None
        ),
        "maximum_encoder_in_flight": (
            max(values["encoder_in_flight"]) if values["encoder_in_flight"] else None
        ),
        "encoder_in_flight_capacity": (
            min(values["encoder_in_flight_capacity"])
            if values["encoder_in_flight_capacity"]
            else None
        ),
        "anomalies": anomalies,
    }


def _validate_final_state(attribution: str, verdict: str) -> None:
    if attribution not in ATTRIBUTIONS:
        raise EvidenceInputError(
            f"host memory diagnostic: invalid attribution {attribution!r}"
        )
    if verdict not in VERDICTS:
        raise EvidenceInputError(
            f"host memory diagnostic: invalid verdict {verdict!r}"
        )


def analyze_records(
    records: list[dict[str, Any]],
    telemetry_records: list[dict[str, Any]],
    *,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    started = _parse_time(started_at)
    finished = _parse_time(finished_at)
    if finished <= started:
        raise ValueError("finished_at must be later than started_at")
    errors = [
        error
        for record in records
        for error in record.get("errors", [])
        if isinstance(error, str)
    ]
    elapsed_values = [
        value
        for record in records
        if (value := _number(record.get("elapsed_seconds"))) is not None
    ]
    heap_elapsed = [
        value
        for record in records
        if isinstance(record.get("heap"), dict)
        and (value := _number(record.get("elapsed_seconds"))) is not None
    ]
    sampled_duration = max(elapsed_values) - min(elapsed_values) if elapsed_values else 0
    memory_internal_gaps = [
        right - left for left, right in pairwise(sorted(elapsed_values))
    ]
    sufficiency = {
        "collection_complete": bool(records),
        "duration": sampled_duration >= MINIMUM_DURATION_SECONDS,
        "memory_samples": len(records) >= MINIMUM_LIGHTWEIGHT_SAMPLE_COUNT,
        "memory_window_coverage": (
            bool(elapsed_values)
            and min(elapsed_values) <= MAXIMUM_BOUNDARY_GAP_SECONDS
            and (
                not memory_internal_gaps
                or max(memory_internal_gaps) <= MAXIMUM_MEMORY_INTERNAL_GAP_SECONDS
            )
        ),
        "heap_samples": len(heap_elapsed) >= MINIMUM_HEAP_SAMPLE_COUNT,
        "heap_window_coverage": (
            len(heap_elapsed) >= MINIMUM_HEAP_SAMPLE_COUNT
            and min(heap_elapsed) <= MAXIMUM_BOUNDARY_GAP_SECONDS
            and max(heap_elapsed) >= sampled_duration * 0.98
        ),
        "error_free": bool(records) and not errors,
    }

    metrics: dict[str, Any] = {}
    for field in MEMORY_COMPLETENESS_FIELDS:
        points = _series(records, field, section="memory")
        sufficiency[f"{field}_complete"] = (
            bool(records) and len(points) == len(records)
        )
        if len(points) >= 2:
            metrics[field] = _trend(points)
    for field in ("malloc_large_dirty_bytes", "iosurface_dirty_bytes"):
        points = _series(records, field, section="memory")
        if len(points) >= 2:
            metrics[field] = _trend(points)
    vmmap_footprint = _series(
        records, "vmmap_physical_footprint_bytes", section="memory"
    )
    if len(vmmap_footprint) >= 2:
        metrics["vmmap_physical_footprint_bytes"] = _trend(vmmap_footprint)
    for field in HEAP_COMPLETENESS_FIELDS:
        points = _series(records, field, section="heap")
        sufficiency[f"heap_{field}_complete"] = (
            bool(heap_elapsed) and len(points) == len(heap_elapsed)
        )
        if len(points) >= 2:
            metrics[f"heap_{field}"] = _trend(points)
    metrics["heap_class_growth"] = _heap_class_growth(records)

    telemetry = _analyze_telemetry(
        telemetry_records, started_at=started, finished_at=finished
    )
    sufficiency["stream_telemetry"] = (
        telemetry["stream_stats_count"] > 0
        and telemetry["invalid_record_count"] == 0
        and not telemetry["missing_required_fields"]
        and telemetry["single_session"]
        and telemetry["coverage_complete"]
    )
    reasons: list[str] = []
    if not all(sufficiency.values()):
        reasons.append("required short-run samples or telemetry are incomplete")
    reasons.extend(telemetry["anomalies"])

    attribution = "inconclusive"
    verdict = "insufficient"
    if all(sufficiency.values()) and not telemetry["anomalies"]:
        pressure_growth = (
            _is_growth(metrics["rss_bytes"], live=False)
            and _is_growth(metrics["physical_footprint_bytes"], live=False)
        )
        live_growth = _is_growth(metrics["malloc_zone_allocated_bytes"], live=True)
        heap_byte_growth = _is_growth(metrics["heap_allocated_bytes"], live=True)
        heap_node_drift = metrics["heap_node_count"]["endpoint_median_drift"]
        heap_node_growth = heap_node_drift >= HEAP_MINIMUM_NODE_DRIFT
        live_stable = _is_stable(metrics["malloc_zone_allocated_bytes"])
        heap_stable = (
            _is_stable(metrics["heap_allocated_bytes"])
            and abs(heap_node_drift) <= STABLE_MAXIMUM_NODE_DRIFT
        )
        allocator_growth = (
            _is_growth(metrics["malloc_zone_dirty_bytes"], live=True)
            and metrics["malloc_zone_fragmentation_bytes"]["endpoint_median_drift"]
            >= FRAGMENTATION_MINIMUM_DRIFT_BYTES
        )
        short_window_stable = all(
            _is_not_growing(metrics[field])
            for field in (
                "rss_bytes",
                "physical_footprint_bytes",
                "malloc_small_dirty_bytes",
                "malloc_zone_dirty_bytes",
                "malloc_zone_allocated_bytes",
                "malloc_zone_fragmentation_bytes",
                "heap_allocated_bytes",
            )
        ) and heap_node_drift <= STABLE_MAXIMUM_NODE_DRIFT

        if pressure_growth and live_growth and (heap_byte_growth or heap_node_growth):
            attribution = "retained_growth"
            verdict = "fail"
            reasons.append("footprint, live malloc allocations, and heap objects grew together")
        elif pressure_growth and allocator_growth and live_stable and heap_stable:
            attribution = "allocator_high_water"
            verdict = "fail"
            reasons.append("resident allocator pages grew while live allocations stayed flat")
        elif short_window_stable:
            verdict = "pass"
            reasons.append("required memory signals stayed within short-window stability thresholds")
        else:
            reasons.append("short-run signals are stable, weak, or contradictory")
    elif telemetry["anomalies"]:
        verdict = "fail"

    _validate_final_state(attribution, verdict)
    return {
        "verdict": verdict,
        "attribution": attribution,
        "sufficiency": sufficiency,
        "metrics": metrics,
        "telemetry": telemetry,
        "errors": errors,
        "reasons": reasons,
    }
