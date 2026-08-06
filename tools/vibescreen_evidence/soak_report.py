"""Derive exact-window soak metrics from raw evidence without judging leaks."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

from . import SCHEMA_VERSION
from .soak_public_report import (
    EvidenceInputError,
    INTERPRETATION,
    PUBLICATION_PROFILE,
    PUBLIC_DERIVATION_ERROR_MESSAGE,
    PUBLIC_ERROR_DERIVATION_FAILED,
    PUBLIC_EVENT_NAMES,
    PUBLIC_OUTPUT_ERROR_MESSAGE,
    SOAK_REPORT_KIND,
    derive_public_report,
    finite_product as _finite_product,
    finite_sum as _finite_sum,
    is_integer as _is_integer,
    number_or_none as _number,
    parse_timestamp as _parse_timestamp,
    public_failure_report as _public_failure,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
    require_finite_number as _require_finite_number,
    require_non_empty_string as _require_non_empty_string,
    require_non_negative_integer as _require_non_negative_integer,
    write_public_report,
)


SOAK_SUMMARY_KIND = "soak"
HOST_TELEMETRY_SCHEMA_VERSION = 1
SUMMARY_STATUSES = ("complete", "partial", "failed")


def _statistics(values: Iterable[float], context: str = "statistics") -> dict[str, Any] | None:
    collected = list(values)
    if not collected:
        return None
    total = _finite_sum(collected, f"{context}.mean")
    mean = total / len(collected)
    if not math.isfinite(mean):
        raise EvidenceInputError(f"{context}.mean: numeric overflow")
    return {
        "count": len(collected),
        "first": collected[0],
        "final": collected[-1],
        "min": min(collected),
        "mean": mean,
        "max": max(collected),
    }


def _slope(points: list[tuple[datetime, float]]) -> float | None:
    if len(points) < 2:
        return None
    origin = points[0][0]
    x_values = [(timestamp - origin).total_seconds() / 60.0 for timestamp, _ in points]
    y_values = [value for _, value in points]
    x_mean = _finite_sum(x_values, "rss slope x mean") / len(x_values)
    y_mean = _finite_sum(y_values, "rss slope y mean") / len(y_values)
    denominator_terms = [
        _finite_product(value - x_mean, value - x_mean, "rss slope denominator")
        for value in x_values
    ]
    denominator = _finite_sum(denominator_terms, "rss slope denominator")
    if denominator == 0:
        return None
    numerator_terms: list[float] = []
    for x_value, y_value in zip(x_values, y_values, strict=True):
        y_delta = y_value - y_mean
        if not math.isfinite(y_delta):
            raise EvidenceInputError("rss slope numerator: numeric overflow")
        numerator_terms.append(
            _finite_product(x_value - x_mean, y_delta, "rss slope numerator")
        )
    slope = _finite_sum(numerator_terms, "rss slope numerator") / denominator
    if not math.isfinite(slope):
        raise EvidenceInputError("rss slope result: numeric overflow")
    return slope


def _rss_statistics(points: list[tuple[datetime, float]], midpoint: datetime) -> dict[str, Any] | None:
    if not points:
        return None
    result = _statistics((value for _, value in points), "rss")
    assert result is not None
    second_half = [point for point in points if point[0] >= midpoint]
    result["slope_kib_per_minute"] = {
        "full_window": _slope(points),
        "second_half": _slope(second_half),
        "second_half_sample_count": len(second_half),
    }
    return result


def _maximum_gaps(timestamps: list[datetime], started: datetime, finished: datetime) -> dict[str, Any]:
    ordered = sorted(timestamps)
    adjacent = [
        (right - left).total_seconds() for left, right in zip(ordered, ordered[1:])
    ]
    window_gaps: list[float] = []
    if ordered:
        window_gaps = [(ordered[0] - started).total_seconds(), *adjacent]
        window_gaps.append((finished - ordered[-1]).total_seconds())
    return {
        "count": len(ordered),
        "maximum_interval_seconds": max(adjacent) if adjacent else None,
        "maximum_window_gap_seconds": max(window_gaps) if window_gaps else None,
    }


def _get(record: dict[str, Any], *path: str) -> Any:
    value: Any = record
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


def _validate_summary(summary: dict[str, Any]) -> str:
    if summary.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceInputError(f"summary.schema_version: must be {SCHEMA_VERSION}")
    if summary.get("kind") != SOAK_SUMMARY_KIND:
        raise EvidenceInputError(f"summary.kind: must be {SOAK_SUMMARY_KIND}")
    run_id = _require_non_empty_string(summary.get("run_id"), "summary.run_id")
    if summary.get("status") not in SUMMARY_STATUSES:
        raise EvidenceInputError("summary.status: must be complete, partial, or failed")
    return run_id


def _validate_sample_record(
    record: dict[str, Any],
    line: int,
    run_id: str,
    previous_index: int | None,
    previous_elapsed: float | None,
) -> tuple[int, float, datetime]:
    context = f"samples line {line}"
    if record.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceInputError(f"{context}.schema_version: must be {SCHEMA_VERSION}")
    if record.get("run_id") != run_id:
        raise EvidenceInputError(f"{context}.run_id: does not match summary")
    sample_index = _require_non_negative_integer(
        record.get("sample_index"), f"{context}.sample_index"
    )
    if previous_index is not None and sample_index <= previous_index:
        raise EvidenceInputError(f"{context}.sample_index: must be strictly increasing")
    elapsed_value = _require_finite_number(
        record.get("elapsed_seconds"),
        f"{context}.elapsed_seconds",
        minimum=0,
    )
    elapsed_seconds = float(elapsed_value)
    if previous_elapsed is not None and elapsed_seconds < previous_elapsed:
        raise EvidenceInputError(
            f"{context}.elapsed_seconds: must be monotonically non-decreasing"
        )
    captured_at = _parse_timestamp(
        record.get("captured_at"), f"{context}.captured_at"
    )
    if not isinstance(record.get("device"), dict):
        raise EvidenceInputError(f"{context}.device: must be an object")
    if "host" in record and not isinstance(record.get("host"), dict):
        raise EvidenceInputError(f"{context}.host: must be an object")
    record_errors = record.get("errors", [])
    if not isinstance(record_errors, list) or not all(
        isinstance(error, str) for error in record_errors
    ):
        raise EvidenceInputError(f"{context}.errors: must be an array of strings")
    return sample_index, elapsed_seconds, captured_at


def _validate_telemetry_record(record: dict[str, Any], line: int) -> datetime:
    context = f"host telemetry line {line}"
    schema_version = record.get("schema_version")
    if not _is_integer(schema_version) or schema_version != HOST_TELEMETRY_SCHEMA_VERSION:
        raise EvidenceInputError(
            f"{context}.schema_version: must be {HOST_TELEMETRY_SCHEMA_VERSION}"
        )
    _require_non_empty_string(record.get("event"), f"{context}.event")
    timestamp = _parse_timestamp(record.get("wall_time"), f"{context}.wall_time")
    _require_non_negative_integer(
        record.get("monotonic_ns"), f"{context}.monotonic_ns"
    )
    if not isinstance(record.get("attributes"), dict):
        raise EvidenceInputError(f"{context}.attributes: must be an object")
    session_epoch = record.get("session_epoch")
    if session_epoch is not None:
        _require_non_negative_integer(session_epoch, f"{context}.session_epoch")
    for name, value in record["attributes"].items():
        if not isinstance(name, str):
            raise EvidenceInputError(f"{context}.attributes: keys must be strings")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _require_finite_number(value, f"{context}.attributes.{name}")
        elif not isinstance(value, (str, bool)):
            raise EvidenceInputError(
                f"{context}.attributes.{name}: must be a primitive value"
            )
    return timestamp


def derive_report(summary_path: Path, samples_path: Path, telemetry_path: Path) -> dict[str, Any]:
    summary = _read_json(summary_path, "summary")
    run_id = _validate_summary(summary)
    started = _parse_timestamp(summary.get("started_at"), "summary.started_at")
    finished = _parse_timestamp(summary.get("finished_at"), "summary.finished_at")
    if finished <= started:
        raise EvidenceInputError("summary: finished_at must be later than started_at")

    source_errors = summary.get("errors", [])
    if not isinstance(source_errors, list) or not all(
        isinstance(error, str) for error in source_errors
    ):
        raise EvidenceInputError("summary.errors must be an array of strings")

    errors: list[str] = []
    samples, sample_errors = _read_jsonl(samples_path, "samples")
    telemetry, telemetry_errors = _read_jsonl(telemetry_path, "host telemetry")
    errors.extend(sample_errors)
    errors.extend(telemetry_errors)

    exact_samples: list[tuple[datetime, dict[str, Any]]] = []
    previous_sample_index: int | None = None
    previous_elapsed_seconds: float | None = None
    for record in samples:
        line = record.pop("_source_line")
        try:
            sample_index, elapsed_seconds, timestamp = _validate_sample_record(
                record,
                line,
                run_id,
                previous_sample_index,
                previous_elapsed_seconds,
            )
        except EvidenceInputError as error:
            errors.append(str(error))
            continue
        previous_sample_index = sample_index
        previous_elapsed_seconds = elapsed_seconds
        if started <= timestamp <= finished:
            exact_samples.append((timestamp, record))
    exact_samples.sort(key=lambda item: item[0])
    if not exact_samples:
        errors.append("samples: no records in the summary exact window")

    exact_telemetry: list[tuple[datetime, dict[str, Any]]] = []
    excluded_telemetry_count = 0
    for record in telemetry:
        line = record.pop("_source_line")
        try:
            timestamp = _validate_telemetry_record(record, line)
        except EvidenceInputError as error:
            errors.append(str(error))
            continue
        if started <= timestamp <= finished:
            exact_telemetry.append((timestamp, record))
        else:
            excluded_telemetry_count += 1
    exact_telemetry.sort(key=lambda item: item[0])
    if not exact_telemetry:
        errors.append("host telemetry: no records in the summary exact window")

    midpoint = started + (finished - started) / 2
    host_rss: list[tuple[datetime, float]] = []
    client_rss: list[tuple[datetime, float]] = []
    thermal_status: list[float] = []
    thermal_by_sensor: dict[str, list[float]] = defaultdict(list)
    battery_values: dict[str, list[float]] = defaultdict(list)
    power_values: dict[str, list[float]] = defaultdict(list)
    for timestamp, sample in exact_samples:
        host_value = _number(_get(sample, "host", "rss_kb"))
        client_value = _number(_get(sample, "device", "memory", "app_total_pss_kb"))
        if host_value is not None:
            host_rss.append((timestamp, host_value))
        if client_value is not None:
            client_rss.append((timestamp, client_value))
        status = _number(_get(sample, "device", "thermal", "status"))
        if status is not None:
            thermal_status.append(status)
        temperatures = _get(sample, "device", "thermal", "temperatures")
        if isinstance(temperatures, list):
            for temperature in temperatures:
                if not isinstance(temperature, dict):
                    continue
                celsius = _number(temperature.get("celsius"))
                if celsius is not None:
                    name = str(temperature.get("name") or "unnamed")
                    thermal_by_sensor[name].append(celsius)
        battery = _get(sample, "device", "battery")
        if isinstance(battery, dict):
            for name in ("level", "temperature", "voltage", "charge_counter"):
                value = _number(battery.get(name))
                if value is not None:
                    battery_values[name].append(value / 10.0 if name == "temperature" else value)
        power = _get(sample, "device", "power")
        if isinstance(power, dict):
            for name, raw_value in power.items():
                value = _number(raw_value)
                if value is not None:
                    power_values[name].append(value)

    event_counts = Counter()
    event_timestamps: dict[str, list[datetime]] = defaultdict(list)
    stream_values: dict[str, list[float]] = defaultdict(list)
    accepted_heartbeat_count = 0
    queue_drop_values: list[float] = []
    for timestamp, record in exact_telemetry:
        event = record.get("event")
        if not isinstance(event, str) or not event:
            errors.append("host telemetry: record in exact window has no event name")
            continue
        event_counts[event] += 1
        event_timestamps[event].append(timestamp)
        attributes = record.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        if event == "heartbeat_received" and attributes.get("accepted") is True:
            accepted_heartbeat_count += 1
        if event == "frame_queue_drop":
            dropped_value = _number(attributes.get("dropped"))
            if dropped_value is not None:
                queue_drop_values.append(dropped_value)
        if event == "stream_stats":
            for name in ("fps", "average_frame_age_ms", "dropped_frames"):
                value = _number(attributes.get(name))
                if value is not None:
                    stream_values[name].append(value)

    if not stream_values.get("fps"):
        errors.append("host telemetry: no numeric stream_stats fps in exact window")
    if not event_timestamps.get("heartbeat_received"):
        errors.append("host telemetry: no heartbeat_received events in exact window")

    battery_names = {
        "level": "level_percent",
        "temperature": "temperature_celsius",
        "voltage": "voltage_mv",
        "charge_counter": "charge_counter",
    }
    reported_dropped_frames = stream_values.get("dropped_frames", [])
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SOAK_REPORT_KIND,
        "run_id": run_id,
        "derivation_status": "complete" if not errors else "partial",
        "window": {
            "started_at": summary["started_at"],
            "finished_at": summary["finished_at"],
            "duration_seconds": (finished - started).total_seconds(),
            "sample_records_in_window": len(exact_samples),
            "telemetry_records_in_window": len(exact_telemetry),
            "telemetry_records_excluded": excluded_telemetry_count,
        },
        "source_summary": {
            "status": summary.get("status"),
            "errors": source_errors,
        },
        "metrics": {
            "stream": {
                "fps": _statistics(stream_values.get("fps", []), "stream.fps"),
                "average_frame_age_ms": _statistics(
                    stream_values.get("average_frame_age_ms", []),
                    "stream.average_frame_age_ms",
                ),
                "reported_dropped_frames": {
                    "statistics": _statistics(
                        reported_dropped_frames, "stream.reported_dropped_frames"
                    ),
                    "sum": _finite_sum(
                        reported_dropped_frames, "stream.reported_dropped_frames.sum"
                    ),
                },
                "frame_queue_drop_total": _finite_sum(
                    queue_drop_values, "stream.frame_queue_drop_total"
                ),
            },
            "telemetry": {
                "event_counts": dict(sorted(event_counts.items())),
                "stream_stats_gaps": _maximum_gaps(
                    event_timestamps.get("stream_stats", []), started, finished
                ),
                "heartbeat_gaps": _maximum_gaps(
                    event_timestamps.get("heartbeat_received", []), started, finished
                ),
                "accepted_heartbeat_count": accepted_heartbeat_count,
            },
            "memory_kib": {
                "host_rss": _rss_statistics(host_rss, midpoint),
                "client_total_pss": _rss_statistics(client_rss, midpoint),
            },
            "thermal": {
                "status": _statistics(thermal_status, "thermal.status"),
                "sensors_celsius": {
                    name: _statistics(values, f"thermal.sensors_celsius.{name}")
                    for name, values in sorted(thermal_by_sensor.items())
                },
            },
            "battery": {
                battery_names[name]: _statistics(values, f"battery.{name}")
                for name, values in sorted(battery_values.items())
            },
            "power": {
                name: _statistics(values, f"power.{name}")
                for name, values in sorted(power_values.items())
            },
        },
        "errors": errors,
        "interpretation": INTERPRETATION,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="soak summary.json")
    parser.add_argument("--samples", type=Path, required=True, help="soak samples.jsonl")
    parser.add_argument(
        "--host-telemetry", type=Path, required=True, help="host telemetry JSONL"
    )
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--output", type=Path, help="internal derived report JSON")
    outputs.add_argument(
        "--public-output", type=Path, help="public allowlisted derived report JSON"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    public_mode = arguments.public_output is not None
    if public_mode:
        try:
            report = derive_report(
                arguments.summary, arguments.samples, arguments.host_telemetry
            )
        except Exception:  # noqa: BLE001 - fail closed; emit public failure only
            report = _public_failure()
        assert arguments.public_output is not None
        return write_public_report(arguments.public_output, report)

    try:
        report = derive_report(
            arguments.summary, arguments.samples, arguments.host_telemetry
        )
    except EvidenceInputError as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": SOAK_REPORT_KIND,
            "derivation_status": "failed",
            "errors": [str(error)],
        }
    try:
        encoded = json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n"
    except (OverflowError, TypeError, ValueError):
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": SOAK_REPORT_KIND,
            "derivation_status": "failed",
            "errors": ["derived report contains a non-finite value"],
        }
        encoded = json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n"
    output = arguments.output
    assert output is not None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(output)
    except OSError as error:
        print(
            json.dumps(
                {"derivation_status": "failed", "errors": [str(error)]},
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, allow_nan=False, sort_keys=True))
    return 0 if report["derivation_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
