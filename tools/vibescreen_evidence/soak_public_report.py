"""Build and persist privacy-minimized public soak reports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable

from . import SCHEMA_VERSION


PUBLICATION_PROFILE = "privacy-minimized-v1"
PUBLIC_ERROR_DERIVATION_FAILED = "evidence_derivation_failed"
PUBLIC_DERIVATION_ERROR_MESSAGE = "public evidence derivation failed"
PUBLIC_OUTPUT_ERROR_MESSAGE = "public evidence output write failed"
SOAK_REPORT_KIND = "soak_exact_window_report"
INTERPRETATION = (
    "Trend metrics are descriptive evidence, not a no-leak determination."
)
PUBLIC_EVENT_NAMES = (
    "session_admission_failed",
    "session_admitted",
    "session_disconnected",
    "heartbeat_received",
    "frame_queue_drop",
    "stream_stats",
)


class EvidenceInputError(ValueError):
    """Raised when input cannot define trustworthy derived evidence."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value}")
    return parsed


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def require_non_empty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceInputError(f"{context}: must be a non-empty string")
    return value


def require_non_negative_integer(value: Any, context: str) -> int:
    if not is_integer(value) or value < 0:
        raise EvidenceInputError(f"{context}: must be a non-negative integer")
    return value


def _require_positive_integer(value: Any, context: str) -> int:
    if not is_integer(value) or value < 1:
        raise EvidenceInputError(f"{context}: must be a positive integer")
    return value


def require_finite_number(
    value: Any, context: str, *, minimum: float | None = None
) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EvidenceInputError(f"{context}: must be a finite number")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as error:
        raise EvidenceInputError(f"{context}: must be a finite number") from error
    if not math.isfinite(converted):
        raise EvidenceInputError(f"{context}: must be a finite number")
    if minimum is not None and converted < minimum:
        raise EvidenceInputError(f"{context}: must be at least {minimum:g}")
    return value


def finite_sum(values: Iterable[float], context: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as error:
        raise EvidenceInputError(f"{context}: numeric overflow") from error
    if not math.isfinite(result):
        raise EvidenceInputError(f"{context}: numeric overflow")
    return result


def finite_product(left: float, right: float, context: str) -> float:
    result = left * right
    if not math.isfinite(result):
        raise EvidenceInputError(f"{context}: numeric overflow")
    return result


def parse_timestamp(value: Any, context: str) -> datetime:
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


def read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except OSError as error:
        raise EvidenceInputError(f"{context}: could not read {path}: {error}") from error
    except UnicodeError as error:
        raise EvidenceInputError(f"{context}: invalid UTF-8 in {path}: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise EvidenceInputError(f"{context}: invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{context}: top-level JSON must be an object")
    return value


def read_jsonl(path: Path, context: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceInputError(f"{context}: could not read {path}: {error}") from error
    except UnicodeError as error:
        raise EvidenceInputError(f"{context}: invalid UTF-8 in {path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(
                line,
                parse_constant=_reject_non_finite_json_constant,
                parse_float=_parse_finite_json_float,
            )
        except (json.JSONDecodeError, ValueError) as error:
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


def number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = float(value)
        except (OverflowError, ValueError):
            return None
        if math.isfinite(converted):
            return converted
    return None


def _optional_number(
    value: Any, context: str, *, minimum: float | None = None
) -> int | float | None:
    if value is None:
        return None
    return require_finite_number(value, context, minimum=minimum)


def _statistics(value: Any, context: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{context}: must be an object or null")
    return {
        "count": _require_positive_integer(value.get("count"), f"{context}.count"),
        "first": require_finite_number(value.get("first"), f"{context}.first"),
        "final": require_finite_number(value.get("final"), f"{context}.final"),
        "min": require_finite_number(value.get("min"), f"{context}.min"),
        "mean": require_finite_number(value.get("mean"), f"{context}.mean"),
        "max": require_finite_number(value.get("max"), f"{context}.max"),
    }


def _rss_statistics(value: Any, context: str) -> dict[str, Any] | None:
    projected = _statistics(value, context)
    if projected is None:
        return None
    slopes = value.get("slope_kib_per_minute")
    if not isinstance(slopes, dict):
        raise EvidenceInputError(f"{context}.slope_kib_per_minute: must be an object")
    projected["slope_kib_per_minute"] = {
        "full_window": _optional_number(
            slopes.get("full_window"), f"{context}.slope.full_window"
        ),
        "second_half": _optional_number(
            slopes.get("second_half"), f"{context}.slope.second_half"
        ),
        "second_half_sample_count": require_non_negative_integer(
            slopes.get("second_half_sample_count"),
            f"{context}.slope.second_half_sample_count",
        ),
    }
    return projected


def _gap_statistics(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceInputError(f"{context}: must be an object")
    return {
        "count": require_non_negative_integer(value.get("count"), f"{context}.count"),
        "maximum_interval_seconds": _optional_number(
            value.get("maximum_interval_seconds"),
            f"{context}.maximum_interval_seconds",
            minimum=0,
        ),
        "maximum_window_gap_seconds": _optional_number(
            value.get("maximum_window_gap_seconds"),
            f"{context}.maximum_window_gap_seconds",
            minimum=0,
        ),
    }


def _aggregate_sensor_statistics(sensors: Any) -> dict[str, Any]:
    if not isinstance(sensors, dict):
        raise EvidenceInputError("thermal.sensors_celsius: must be an object")
    minimum_values: list[float] = []
    maximum_values: list[float] = []
    for name, statistics in sensors.items():
        if not isinstance(statistics, dict):
            raise EvidenceInputError(
                f"thermal.sensors_celsius.{name}: must be an object"
            )
        minimum = require_finite_number(
            statistics.get("min"), f"thermal.sensors_celsius.{name}.min"
        )
        maximum = require_finite_number(
            statistics.get("max"), f"thermal.sensors_celsius.{name}.max"
        )
        minimum_values.append(float(minimum))
        maximum_values.append(float(maximum))
    return {
        "sensor_count": len(sensors),
        "min": min(minimum_values) if minimum_values else None,
        "max": max(maximum_values) if maximum_values else None,
    }


def public_failure_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SOAK_REPORT_KIND,
        "publication_profile": PUBLICATION_PROFILE,
        "derivation_status": "failed",
        "error_code": PUBLIC_ERROR_DERIVATION_FAILED,
    }


def _public_timestamp(value: Any, context: str) -> str:
    return parse_timestamp(value, context).isoformat().replace("+00:00", "Z")


def _project_public_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceInputError("report.schema_version: invalid")
    if report.get("kind") != SOAK_REPORT_KIND:
        raise EvidenceInputError("report.kind: invalid")
    require_non_empty_string(report.get("run_id"), "report.run_id")
    if report.get("derivation_status") != "complete" or report.get("errors") != []:
        raise EvidenceInputError("report: derivation is not complete")
    source = report.get("source_summary")
    if not isinstance(source, dict) or source.get("status") != "complete":
        raise EvidenceInputError("source_summary: source run is not complete")
    if source.get("errors") != []:
        raise EvidenceInputError("source_summary: source run has errors")

    window = report.get("window")
    metrics = report.get("metrics")
    if not isinstance(window, dict) or not isinstance(metrics, dict):
        raise EvidenceInputError("report: window and metrics must be objects")
    started_at = _public_timestamp(window.get("started_at"), "window.started_at")
    finished_at = _public_timestamp(window.get("finished_at"), "window.finished_at")
    if parse_timestamp(finished_at, "window.finished_at") <= parse_timestamp(
        started_at, "window.started_at"
    ):
        raise EvidenceInputError("window: finished_at must be later than started_at")
    duration_seconds = require_finite_number(
        window.get("duration_seconds"), "window.duration_seconds", minimum=0
    )
    if duration_seconds <= 0:
        raise EvidenceInputError("window.duration_seconds: must be positive")
    sample_count = require_non_negative_integer(
        window.get("sample_records_in_window"), "window.sample_records_in_window"
    )
    telemetry_count = require_non_negative_integer(
        window.get("telemetry_records_in_window"),
        "window.telemetry_records_in_window",
    )
    if sample_count == 0 or telemetry_count == 0:
        raise EvidenceInputError("window: complete report must contain source records")
    excluded_count = require_non_negative_integer(
        window.get("telemetry_records_excluded"), "window.telemetry_records_excluded"
    )

    stream = metrics.get("stream")
    telemetry = metrics.get("telemetry")
    memory = metrics.get("memory_kib")
    thermal = metrics.get("thermal")
    battery = metrics.get("battery")
    if not all(
        isinstance(section, dict)
        for section in (stream, telemetry, memory, thermal, battery)
    ):
        raise EvidenceInputError("metrics: required sections must be objects")
    source_event_counts = telemetry.get("event_counts")
    if not isinstance(source_event_counts, dict):
        raise EvidenceInputError("metrics.telemetry.event_counts: must be an object")
    event_counts = {
        event: require_non_negative_integer(
            source_event_counts.get(event, 0),
            f"metrics.telemetry.event_counts.{event}",
        )
        for event in PUBLIC_EVENT_NAMES
    }
    dropped = stream.get("reported_dropped_frames")
    if not isinstance(dropped, dict):
        raise EvidenceInputError(
            "metrics.stream.reported_dropped_frames: must be an object"
        )

    projected = {
        "schema_version": SCHEMA_VERSION,
        "kind": SOAK_REPORT_KIND,
        "publication_profile": PUBLICATION_PROFILE,
        "derivation_status": "complete",
        "window": {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "sample_records_in_window": sample_count,
            "telemetry_records_in_window": telemetry_count,
            "telemetry_records_excluded": excluded_count,
        },
        "source_summary": {"status": "complete"},
        "metrics": {
            "stream": {
                "fps": _statistics(stream.get("fps"), "metrics.stream.fps"),
                "average_frame_age_ms": _statistics(
                    stream.get("average_frame_age_ms"),
                    "metrics.stream.average_frame_age_ms",
                ),
                "reported_dropped_frames": {
                    "statistics": _statistics(
                        dropped.get("statistics"),
                        "metrics.stream.reported_dropped_frames.statistics",
                    ),
                    "sum": require_finite_number(
                        dropped.get("sum"),
                        "metrics.stream.reported_dropped_frames.sum",
                        minimum=0,
                    ),
                },
                "frame_queue_drop_total": require_finite_number(
                    stream.get("frame_queue_drop_total"),
                    "metrics.stream.frame_queue_drop_total",
                    minimum=0,
                ),
            },
            "telemetry": {
                "event_counts": event_counts,
                "stream_stats_gaps": _gap_statistics(
                    telemetry.get("stream_stats_gaps"),
                    "metrics.telemetry.stream_stats_gaps",
                ),
                "heartbeat_gaps": _gap_statistics(
                    telemetry.get("heartbeat_gaps"),
                    "metrics.telemetry.heartbeat_gaps",
                ),
                "accepted_heartbeat_count": require_non_negative_integer(
                    telemetry.get("accepted_heartbeat_count"),
                    "metrics.telemetry.accepted_heartbeat_count",
                ),
            },
            "memory_kib": {
                "host_rss": _rss_statistics(
                    memory.get("host_rss"), "metrics.memory_kib.host_rss"
                ),
                "client_total_pss": _rss_statistics(
                    memory.get("client_total_pss"),
                    "metrics.memory_kib.client_total_pss",
                ),
            },
            "thermal": {
                "status": _statistics(
                    thermal.get("status"), "metrics.thermal.status"
                ),
                "sensors_celsius_aggregate": _aggregate_sensor_statistics(
                    thermal.get("sensors_celsius")
                ),
            },
            "battery": {
                name: _statistics(battery.get(name), f"metrics.battery.{name}")
                for name in (
                    "level_percent",
                    "plugged",
                    "status",
                    "temperature_celsius",
                    "voltage_mv",
                    "charge_counter",
                )
            },
        },
        "interpretation": INTERPRETATION,
    }
    json.dumps(projected, allow_nan=False, sort_keys=True)
    return projected


def derive_public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Project a complete internal report onto a fixed public allowlist."""

    try:
        return _project_public_report(report)
    except Exception:  # noqa: BLE001 - fail closed; never surface private detail
        return public_failure_report()


def write_public_report(output: Path, report: dict[str, Any]) -> int:
    """Project and atomically persist an internal report on the public allowlist."""

    public_report = derive_public_report(report)
    encoded = json.dumps(
        public_report, allow_nan=False, indent=2, sort_keys=True
    ) + "\n"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(output)
    except Exception:  # noqa: BLE001 - fail closed; emit a fixed message only
        print(PUBLIC_OUTPUT_ERROR_MESSAGE, file=sys.stderr)
        return 1
    if public_report["derivation_status"] != "complete":
        print(PUBLIC_DERIVATION_ERROR_MESSAGE, file=sys.stderr)
        return 1
    return 0
