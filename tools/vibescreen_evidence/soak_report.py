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


class EvidenceInputError(ValueError):
    """Raised when an input cannot define a trustworthy exact window."""


def _parse_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceInputError(f"{context}: missing timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise EvidenceInputError(f"{context}: invalid timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise EvidenceInputError(f"{context}: timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvidenceInputError(f"{context}: could not read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise EvidenceInputError(f"{context}: invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{context}: top-level JSON must be an object")
    return value


def _read_jsonl(path: Path, context: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceInputError(f"{context}: could not read {path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"{context} line {line_number}: invalid JSON: {error}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{context} line {line_number}: record must be an object")
            continue
        value["_source_line"] = line_number
        records.append(value)
    if not records:
        errors.append(f"{context}: no readable records")
    return records, errors


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted):
            return converted
    return None


def _statistics(values: Iterable[float]) -> dict[str, Any] | None:
    collected = list(values)
    if not collected:
        return None
    return {
        "count": len(collected),
        "first": collected[0],
        "final": collected[-1],
        "min": min(collected),
        "mean": sum(collected) / len(collected),
        "max": max(collected),
    }


def _slope(points: list[tuple[datetime, float]]) -> float | None:
    if len(points) < 2:
        return None
    origin = points[0][0]
    x_values = [(timestamp - origin).total_seconds() / 60.0 for timestamp, _ in points]
    y_values = [value for _, value in points]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return None
    return sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values)
    ) / denominator


def _rss_statistics(
    points: list[tuple[datetime, float]], midpoint: datetime
) -> dict[str, Any] | None:
    if not points:
        return None
    result = _statistics(value for _, value in points)
    assert result is not None
    second_half = [point for point in points if point[0] >= midpoint]
    result["slope_kib_per_minute"] = {
        "full_window": _slope(points),
        "second_half": _slope(second_half),
        "second_half_sample_count": len(second_half),
    }
    return result


def _maximum_gaps(
    timestamps: list[datetime], started: datetime, finished: datetime
) -> dict[str, Any]:
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


def derive_report(
    summary_path: Path, samples_path: Path, telemetry_path: Path
) -> dict[str, Any]:
    summary = _read_json(summary_path, "summary")
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

    run_id = summary.get("run_id")
    exact_samples: list[tuple[datetime, dict[str, Any]]] = []
    for record in samples:
        line = record.pop("_source_line")
        try:
            timestamp = _parse_timestamp(record.get("captured_at"), f"samples line {line}")
        except EvidenceInputError as error:
            errors.append(str(error))
            continue
        if run_id is not None and record.get("run_id") != run_id:
            errors.append(f"samples line {line}: run_id does not match summary")
            continue
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
            timestamp = _parse_timestamp(
                record.get("wall_time"), f"host telemetry line {line}"
            )
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
    queue_drop_total = 0.0
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
            queue_drop_total += _number(attributes.get("dropped")) or 0.0
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
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "soak_exact_window_report",
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
                "fps": _statistics(stream_values.get("fps", [])),
                "average_frame_age_ms": _statistics(
                    stream_values.get("average_frame_age_ms", [])
                ),
                "reported_dropped_frames": {
                    "statistics": _statistics(stream_values.get("dropped_frames", [])),
                    "sum": sum(stream_values.get("dropped_frames", [])),
                },
                "frame_queue_drop_total": queue_drop_total,
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
                "status": _statistics(thermal_status),
                "sensors_celsius": {
                    name: _statistics(values)
                    for name, values in sorted(thermal_by_sensor.items())
                },
            },
            "battery": {
                battery_names[name]: _statistics(values)
                for name, values in sorted(battery_values.items())
            },
            "power": {
                name: _statistics(values) for name, values in sorted(power_values.items())
            },
        },
        "errors": errors,
        "interpretation": "Trend metrics are descriptive evidence, not a no-leak determination.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="soak summary.json")
    parser.add_argument("--samples", type=Path, required=True, help="soak samples.jsonl")
    parser.add_argument(
        "--host-telemetry", type=Path, required=True, help="host telemetry JSONL"
    )
    parser.add_argument("--output", type=Path, required=True, help="derived report JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_report(
            arguments.summary, arguments.samples, arguments.host_telemetry
        )
    except EvidenceInputError as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": "soak_exact_window_report",
            "derivation_status": "failed",
            "errors": [str(error)],
        }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(arguments.output)
    except OSError as error:
        print(json.dumps({"derivation_status": "failed", "errors": [str(error)]}), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["derivation_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
