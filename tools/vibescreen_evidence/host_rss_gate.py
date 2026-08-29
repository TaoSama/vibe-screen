"""Evaluate the evidence-grade two-hour host RSS no-growth gate."""

from __future__ import annotations

import argparse
from datetime import datetime
from itertools import pairwise
import json
import math
from pathlib import Path
from statistics import mean, median
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .soak_public_report import (
    EvidenceInputError,
    read_json as _read_json,
    read_jsonl as _read_jsonl,
)
from .host_stream_telemetry_gate import (
    evaluate_exact_window_report,
    missing_exact_window_report_evaluation,
    thresholds as _stream_telemetry_thresholds,
)
from .soak_report import (
    _parse_timestamp,
    _validate_sample_record,
    _validate_summary,
)


GATE_KIND = "host_rss_no_growth_gate"
MINIMUM_DURATION_SECONDS = 2 * 60 * 60 * 0.98
MINIMUM_SAMPLE_COUNT = 230
MINIMUM_SECOND_HALF_SAMPLE_COUNT = 115
MAXIMUM_BOUNDARY_GAP_SECONDS = 90.0
MAXIMUM_SLOPE_CI_UPPER_KIB_PER_MINUTE = 40.0
MAXIMUM_THEIL_SEN_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_SECOND_HALF_DRIFT_KIB = 4 * 1024.0
MAXIMUM_FULL_WINDOW_DRIFT_KIB = 8 * 1024.0
MAXIMUM_FINAL_QUARTER_STEP_KIB = 2 * 1024.0
NORMAL_95_PERCENT_TWO_SIDED_CRITICAL_VALUE = 1.959963984540054
ENDPOINT_FRACTION = 0.10

INTERPRETATION = (
    "A pass means this two-hour evidence window did not show practically "
    "significant host RSS growth under the recorded workload. It is not proof "
    "that the process cannot leak under other workloads or longer runs."
)


def _thresholds() -> dict[str, float | int]:
    return {
        "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
        "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
        "minimum_second_half_sample_count": MINIMUM_SECOND_HALF_SAMPLE_COUNT,
        "maximum_boundary_gap_seconds": MAXIMUM_BOUNDARY_GAP_SECONDS,
        "maximum_slope_ci_upper_kib_per_minute": (
            MAXIMUM_SLOPE_CI_UPPER_KIB_PER_MINUTE
        ),
        "maximum_theil_sen_slope_kib_per_minute": (
            MAXIMUM_THEIL_SEN_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_second_half_drift_kib": MAXIMUM_SECOND_HALF_DRIFT_KIB,
        "maximum_full_window_drift_kib": MAXIMUM_FULL_WINDOW_DRIFT_KIB,
        "maximum_final_quarter_step_kib": MAXIMUM_FINAL_QUARTER_STEP_KIB,
        **_stream_telemetry_thresholds(),
    }


def _endpoint_median(values: list[float], *, at_end: bool) -> float:
    count = max(1, math.ceil(len(values) * ENDPOINT_FRACTION))
    endpoint = values[-count:] if at_end else values[:count]
    return float(median(endpoint))


def _ols_slope_with_upper_bound(
    points: list[tuple[datetime, float]],
) -> tuple[float, float]:
    if len(points) < 3:
        raise EvidenceInputError("host RSS gate: at least three points are required")
    origin = points[0][0]
    x_values = [(timestamp - origin).total_seconds() / 60.0 for timestamp, _ in points]
    y_values = [value for _, value in points]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    sxx = sum((value - x_mean) ** 2 for value in x_values)
    if sxx <= 0:
        raise EvidenceInputError("host RSS gate: sample timestamps have no span")
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    ) / sxx
    intercept = y_mean - slope * x_mean
    residual_sum_squares = sum(
        (y_value - (intercept + slope * x_value)) ** 2
        for x_value, y_value in zip(x_values, y_values, strict=True)
    )
    slope_standard_error = math.sqrt(
        residual_sum_squares / (len(points) - 2) / sxx
    )
    # The gate requires at least 115 steady-state samples, where the normal
    # critical value is a close large-sample approximation to Student's t.
    upper_bound = (
        slope
        + NORMAL_95_PERCENT_TWO_SIDED_CRITICAL_VALUE * slope_standard_error
    )
    return slope, upper_bound


def _theil_sen_slope(points: list[tuple[datetime, float]]) -> float:
    slopes: list[float] = []
    for left_index, (left_time, left_value) in enumerate(points):
        for right_time, right_value in points[left_index + 1 :]:
            elapsed_minutes = (right_time - left_time).total_seconds() / 60.0
            if elapsed_minutes > 0:
                slopes.append((right_value - left_value) / elapsed_minutes)
    if not slopes:
        raise EvidenceInputError("host RSS gate: no increasing sample timestamps")
    return float(median(slopes))


def _criterion(measured: float, maximum: float) -> dict[str, float | bool]:
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured <= maximum,
    }


def _evaluate(
    points: list[tuple[datetime, float]],
    started: datetime,
    finished: datetime,
    elapsed_span_seconds: float,
) -> dict[str, Any]:
    duration_seconds = (finished - started).total_seconds()
    midpoint = started + (finished - started) / 2
    second_half = [point for point in points if point[0] >= midpoint]
    start_gap_seconds = (points[0][0] - started).total_seconds()
    finish_gap_seconds = (finished - points[-1][0]).total_seconds()
    internal_gaps = [
        (right[0] - left[0]).total_seconds()
        for left, right in pairwise(points)
    ]
    maximum_internal_gap_seconds = max(internal_gaps) if internal_gaps else duration_seconds
    sufficiency = {
        "duration": {
            "measured_seconds": duration_seconds,
            "minimum_seconds": MINIMUM_DURATION_SECONDS,
            "passed": duration_seconds >= MINIMUM_DURATION_SECONDS,
        },
        "elapsed_span": {
            "measured_seconds": elapsed_span_seconds,
            "minimum_seconds": MINIMUM_DURATION_SECONDS,
            "passed": elapsed_span_seconds >= MINIMUM_DURATION_SECONDS,
        },
        "sample_count": {
            "measured": len(points),
            "minimum": MINIMUM_SAMPLE_COUNT,
            "passed": len(points) >= MINIMUM_SAMPLE_COUNT,
        },
        "second_half_sample_count": {
            "measured": len(second_half),
            "minimum": MINIMUM_SECOND_HALF_SAMPLE_COUNT,
            "passed": len(second_half) >= MINIMUM_SECOND_HALF_SAMPLE_COUNT,
        },
        "start_boundary_gap": {
            "measured_seconds": start_gap_seconds,
            "maximum_seconds": MAXIMUM_BOUNDARY_GAP_SECONDS,
            "passed": 0 <= start_gap_seconds <= MAXIMUM_BOUNDARY_GAP_SECONDS,
        },
        "finish_boundary_gap": {
            "measured_seconds": finish_gap_seconds,
            "maximum_seconds": MAXIMUM_BOUNDARY_GAP_SECONDS,
            "passed": 0 <= finish_gap_seconds <= MAXIMUM_BOUNDARY_GAP_SECONDS,
        },
        "maximum_internal_gap": {
            "measured_seconds": maximum_internal_gap_seconds,
            "maximum_seconds": MAXIMUM_BOUNDARY_GAP_SECONDS,
            "passed": maximum_internal_gap_seconds <= MAXIMUM_BOUNDARY_GAP_SECONDS,
        },
    }
    if not all(item["passed"] for item in sufficiency.values()):
        return {
            "verdict": "insufficient",
            "sufficiency": sufficiency,
            "criteria": {},
            "metrics": {},
            "reasons": ["the evidence window is shorter or sparser than the gate requires"],
        }

    slope, slope_upper = _ols_slope_with_upper_bound(second_half)
    robust_slope = _theil_sen_slope(second_half)
    full_values = [value for _, value in points]
    second_half_values = [value for _, value in second_half]
    full_drift = _endpoint_median(full_values, at_end=True) - _endpoint_median(
        full_values, at_end=False
    )
    second_half_drift = _endpoint_median(
        second_half_values, at_end=True
    ) - _endpoint_median(second_half_values, at_end=False)
    quarter_size = max(1, len(second_half_values) // 4)
    previous_quarter = second_half_values[-2 * quarter_size : -quarter_size]
    final_quarter = second_half_values[-quarter_size:]
    final_quarter_step = mean(final_quarter) - mean(previous_quarter)

    criteria = {
        "second_half_ols_slope_ci_upper_kib_per_minute": _criterion(
            slope_upper, MAXIMUM_SLOPE_CI_UPPER_KIB_PER_MINUTE
        ),
        "second_half_theil_sen_slope_kib_per_minute": _criterion(
            robust_slope, MAXIMUM_THEIL_SEN_SLOPE_KIB_PER_MINUTE
        ),
        "second_half_endpoint_median_drift_kib": _criterion(
            second_half_drift, MAXIMUM_SECOND_HALF_DRIFT_KIB
        ),
        "full_window_endpoint_median_drift_kib": _criterion(
            full_drift, MAXIMUM_FULL_WINDOW_DRIFT_KIB
        ),
        "final_quarter_mean_step_kib": _criterion(
            final_quarter_step, MAXIMUM_FINAL_QUARTER_STEP_KIB
        ),
    }
    failed = [name for name, item in criteria.items() if not item["passed"]]
    return {
        "verdict": "fail" if failed else "pass",
        "sufficiency": sufficiency,
        "criteria": criteria,
        "metrics": {
            "second_half_ols_slope_kib_per_minute": slope,
            "second_half_ols_slope_ci_upper_kib_per_minute": slope_upper,
            "second_half_theil_sen_slope_kib_per_minute": robust_slope,
            "second_half_endpoint_median_drift_kib": second_half_drift,
            "full_window_endpoint_median_drift_kib": full_drift,
            "final_quarter_mean_step_kib": final_quarter_step,
        },
        "reasons": [f"criterion failed: {name}" for name in failed],
    }


def _combine_verdicts(rss_verdict: str, telemetry_verdict: str) -> str:
    if "fail" in (rss_verdict, telemetry_verdict):
        return "fail"
    if "insufficient" in (rss_verdict, telemetry_verdict):
        return "insufficient"
    return "pass"


def derive_gate(
    summary_path: Path,
    samples_path: Path,
    exact_window_report_path: Path | None = None,
) -> dict[str, Any]:
    summary = _read_json(summary_path, "summary")
    run_id = _validate_summary(summary)
    started = _parse_timestamp(summary.get("started_at"), "summary.started_at")
    finished = _parse_timestamp(summary.get("finished_at"), "summary.finished_at")
    if finished <= started:
        raise EvidenceInputError("summary: finished_at must be later than started_at")

    records, read_errors = _read_jsonl(samples_path, "samples")
    if read_errors:
        raise EvidenceInputError("; ".join(read_errors))
    points: list[tuple[datetime, float]] = []
    elapsed_values: list[float] = []
    previous_index: int | None = None
    previous_elapsed: float | None = None
    previous_captured_at: datetime | None = None
    for record in records:
        source_line = record.pop("_source_line")
        sample_index, elapsed, captured_at = _validate_sample_record(
            record, source_line, run_id, previous_index, previous_elapsed
        )
        previous_index = sample_index
        previous_elapsed = elapsed
        if previous_captured_at is not None and captured_at < previous_captured_at:
            raise EvidenceInputError(
                f"samples line {source_line}.captured_at: must be monotonically non-decreasing"
            )
        previous_captured_at = captured_at
        if not (started <= captured_at <= finished):
            continue
        elapsed_values.append(elapsed)
        rss_value = record.get("host", {}).get("rss_kb")
        if not isinstance(rss_value, (int, float)) or isinstance(rss_value, bool):
            continue
        rss = float(rss_value)
        if not math.isfinite(rss) or rss < 0:
            raise EvidenceInputError(
                f"samples line {source_line}.host.rss_kb: must be finite and non-negative"
            )
        points.append((captured_at, rss))
    points.sort(key=lambda item: item[0])
    if not points:
        raise EvidenceInputError("samples: no host RSS records in the summary exact window")

    duration_seconds = (finished - started).total_seconds()
    elapsed_span_seconds = max(elapsed_values) - min(elapsed_values)
    evaluation = _evaluate(points, started, finished, elapsed_span_seconds)
    if summary.get("status") != "complete" or summary.get("errors"):
        evaluation["verdict"] = "insufficient"
        evaluation["reasons"] = [
            "the source soak summary is not complete and error-free",
            *evaluation["reasons"],
        ]
    if exact_window_report_path is None:
        telemetry_evaluation = missing_exact_window_report_evaluation()
    else:
        telemetry_evaluation = evaluate_exact_window_report(
            _read_json(exact_window_report_path, "exact_window_report"),
            run_id=run_id,
            summary=summary,
        )
    evaluation["verdict"] = _combine_verdicts(
        str(evaluation["verdict"]),
        str(telemetry_evaluation["verdict"]),
    )
    evaluation["reasons"] = [
        *evaluation["reasons"],
        *telemetry_evaluation["reasons"],
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "run_id": run_id,
        "window": {
            "started_at": summary["started_at"],
            "finished_at": summary["finished_at"],
            "duration_seconds": duration_seconds,
            "elapsed_span_seconds": elapsed_span_seconds,
            "host_rss_sample_count": len(points),
        },
        "source_summary": {
            "status": summary.get("status"),
            "error_count": len(summary.get("errors", [])),
        },
        "telemetry_sufficiency": telemetry_evaluation["sufficiency"],
        "telemetry_criteria": telemetry_evaluation["criteria"],
        "telemetry_metrics": telemetry_evaluation["metrics"],
        "thresholds": _thresholds(),
        **evaluation,
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
        "telemetry_sufficiency": {},
        "telemetry_criteria": {},
        "telemetry_metrics": {},
        "thresholds": _thresholds(),
        "sufficiency": {},
        "criteria": {},
        "metrics": {},
        "reasons": ["the gate inputs could not be validated"],
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
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument(
        "--exact-window-report",
        type=Path,
        required=True,
        help="soak_report output for the same exact two-hour window",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_gate(
            arguments.summary,
            arguments.samples,
            arguments.exact_window_report,
        )
        _write_json(arguments.output, report)
    except (EvidenceInputError, OSError, TypeError, ValueError):
        report = _failure_report()
        try:
            _write_json(arguments.output, report)
        except (OSError, TypeError, ValueError):
            print("error: host RSS gate output could not be written", file=sys.stderr)
            return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
