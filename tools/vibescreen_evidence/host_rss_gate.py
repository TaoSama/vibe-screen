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
    _parse_finite_json_float,
    _reject_non_finite_json_constant,
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
HOST_READINESS_KIND = "macos_host_shared_prerequisite_readiness"
HOST_READINESS_SCHEMA_VERSION = "vibescreen.host-readiness/v1"
HOST_READINESS_REQUIRED_PERMISSION_FIELDS = (
    "screen_recording_granted",
    "accessibility_granted",
    "microphone_granted",
    "screen_recording_identity_bound",
    "accessibility_identity_bound",
    "microphone_identity_bound",
)


def _host_readiness_thresholds() -> dict[str, bool]:
    return {
        "host_readiness_report_required": True,
        "host_readiness_shared_status_must_be_ready": True,
        "host_readiness_must_allow_host_rss_gate": True,
        "host_readiness_current_source_must_be_clean": True,
        "host_readiness_installed_host_must_match_current_source": True,
        "host_readiness_signing_must_use_stable_identity": True,
        "host_readiness_tcc_must_be_identity_bound": True,
    }


def _thresholds() -> dict[str, float | int | bool]:
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
        **_host_readiness_thresholds(),
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


def _combine_all_verdicts(*verdicts: str) -> str:
    if "fail" in verdicts:
        return "fail"
    if "insufficient" in verdicts:
        return "insufficient"
    return "pass"


def _readiness_check(passed: bool, detail: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"passed": passed}
    if detail:
        record["detail"] = detail
    return record


def missing_host_readiness_evaluation() -> dict[str, Any]:
    return {
        "verdict": "insufficient",
        "summary": {
            "present": False,
            "status": None,
            "can_start_host_rss_gate": None,
            "blockers": ["host readiness report was not provided"],
        },
        "sufficiency": {
            "host_readiness_report_present": _readiness_check(
                False,
                "provide scripts/macos_dev_host.py readiness JSON for the same current-source Host session",
            )
        },
        "criteria": {},
        "reasons": ["host_readiness_report_present"],
    }


def _readiness_reason(name: str, detail: str | None = None) -> str:
    return f"{name}: {detail}" if detail else name


def _read_host_readiness_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except OSError as error:
        raise EvidenceInputError(f"host_readiness: could not read {path}: {error}") from error
    except UnicodeError as error:
        raise EvidenceInputError(f"host_readiness: invalid UTF-8 in {path}: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise EvidenceInputError(f"host_readiness: invalid JSON in {path}: {error}") from error


def evaluate_host_readiness_report(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {
            "verdict": "insufficient",
            "summary": {
                "present": True,
                "status": None,
                "can_start_host_rss_gate": None,
                "blockers": ["host readiness report must be a JSON object"],
            },
            "sufficiency": {
                "host_readiness_report_object": _readiness_check(
                    False, "host readiness report must be a JSON object"
                )
            },
            "criteria": {},
            "reasons": [
                "host_readiness_report_object: host readiness report must be a JSON object"
            ],
        }
    summary: dict[str, Any] = {
        "present": True,
        "status": record.get("status"),
        "can_start_host_rss_gate": record.get("can_start_host_rss_gate"),
        "blockers": record.get("blockers", []),
    }
    sufficiency: dict[str, dict[str, Any]] = {}
    criteria: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    def add_sufficiency(name: str, passed: bool, detail: str | None = None) -> None:
        sufficiency[name] = _readiness_check(passed, None if passed else detail)
        if not passed:
            reasons.append(_readiness_reason(name, detail))

    def add_criterion(name: str, passed: bool, detail: str | None = None) -> None:
        criteria[name] = _readiness_check(passed, None if passed else detail)
        if not passed:
            reasons.append(_readiness_reason(name, detail))

    add_sufficiency(
        "schema_version",
        record.get("schema_version") == HOST_READINESS_SCHEMA_VERSION,
        f"expected {HOST_READINESS_SCHEMA_VERSION!r}, got {record.get('schema_version')!r}",
    )
    add_sufficiency(
        "kind",
        record.get("kind") == HOST_READINESS_KIND,
        f"expected {HOST_READINESS_KIND!r}, got {record.get('kind')!r}",
    )
    try:
        _parse_timestamp(record.get("generated_at"), "host_readiness.generated_at")
    except EvidenceInputError as error:
        generated_at_valid = False
        generated_at_detail = str(error)
    else:
        generated_at_valid = True
        generated_at_detail = None
    add_sufficiency("generated_at", generated_at_valid, generated_at_detail)
    blockers = record.get("blockers", [])
    blockers_valid = isinstance(blockers, list) and all(
        isinstance(blocker, str) for blocker in blockers
    )
    add_sufficiency(
        "blockers_list",
        blockers_valid,
        "blockers must be a list of strings",
    )
    host = record.get("host")
    host_is_object = isinstance(host, dict)
    add_sufficiency(
        "host_record_present",
        host_is_object,
        "host readiness must include host source/signing provenance",
    )
    permissions = record.get("permissions")
    permissions_is_object = isinstance(permissions, dict)
    add_sufficiency(
        "permissions_record_present",
        permissions_is_object,
        "host readiness must include TCC permission state",
    )
    listener = record.get("listener")
    listener_is_object = isinstance(listener, dict)
    add_sufficiency(
        "listener_record_present",
        listener_is_object,
        "host readiness must include listener state",
    )
    safety = record.get("safety")
    safety_is_object = isinstance(safety, dict)
    add_sufficiency(
        "safety_record_present",
        safety_is_object,
        "host readiness must include read-only safety metadata",
    )

    if not all(item["passed"] for item in sufficiency.values()):
        return {
            "verdict": "insufficient",
            "summary": summary,
            "sufficiency": sufficiency,
            "criteria": criteria,
            "reasons": reasons,
        }

    assert isinstance(host, dict)
    assert isinstance(permissions, dict)
    assert isinstance(listener, dict)
    assert isinstance(safety, dict)
    blockers = record.get("blockers", [])
    assert isinstance(blockers, list)

    add_criterion(
        "signing_tcc_status_ready",
        record.get("signing_tcc_status") == "ready",
        f"signing_tcc_status={record.get('signing_tcc_status')!r}",
    )
    add_criterion(
        "can_start_host_rss_gate",
        record.get("can_start_host_rss_gate") is True,
        f"can_start_host_rss_gate={record.get('can_start_host_rss_gate')!r}",
    )
    add_criterion(
        "listener_observed",
        listener.get("observed") is True,
        f"listener.observed={listener.get('observed')!r}",
    )
    add_criterion(
        "current_source_clean",
        host.get("current_source_dirty") is False,
        f"host.current_source_dirty={host.get('current_source_dirty')!r}",
    )
    source_commit = host.get("source_commit")
    current_source_commit = host.get("current_source_commit")
    source_tree = host.get("source_tree")
    current_source_tree = host.get("current_source_tree")
    add_criterion(
        "installed_host_matches_current_source",
        isinstance(source_commit, str)
        and bool(source_commit.strip())
        and source_commit == current_source_commit
        and isinstance(source_tree, str)
        and bool(source_tree.strip())
        and source_tree == current_source_tree
        and host.get("source_dirty") is False,
        "installed Host source commit/tree must match clean current source",
    )
    add_criterion(
        "stable_signing_identity",
        host.get("is_ad_hoc") is False
        and isinstance(host.get("certificate_sha1"), str)
        and bool(host.get("certificate_sha1", "").strip())
        and isinstance(host.get("expected_certificate_sha1"), str)
        and bool(host.get("expected_certificate_sha1", "").strip())
        and host.get("certificate_sha1") == host.get("expected_certificate_sha1"),
        "Host must be stable-signed with the expected certificate leaf",
    )
    add_criterion(
        "permissions_readable",
        permissions.get("readable") is True,
        f"permissions.readable={permissions.get('readable')!r}",
    )
    for field in HOST_READINESS_REQUIRED_PERMISSION_FIELDS:
        add_criterion(
            field,
            permissions.get(field) is True,
            f"permissions.{field}={permissions.get(field)!r}",
        )
    for field in (
        "read_only",
        "starts_host",
        "opens_host_gui",
        "opens_system_settings",
        "requests_screen_recording",
        "requests_accessibility",
        "requests_microphone",
        "modifies_tcc",
        "modifies_keychain",
        "installs_or_replaces_host",
        "modifies_android",
        "closes_runtime_gates",
    ):
        expected = field == "read_only"
        add_criterion(
            f"safety_{field}",
            safety.get(field) is expected,
            f"safety.{field}={safety.get(field)!r}",
        )

    return {
        "verdict": "pass" if all(item["passed"] for item in criteria.values()) else "insufficient",
        "summary": summary,
        "sufficiency": sufficiency,
        "criteria": criteria,
        "reasons": reasons,
    }


def derive_gate(
    summary_path: Path,
    samples_path: Path,
    exact_window_report_path: Path | None = None,
    host_readiness_path: Path | None = None,
    *,
    repo_root: Path | None = None,
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
        host = record.get("host", {})
        if not isinstance(host, dict) or "rss_kb" not in host:
            continue
        rss_value = host.get("rss_kb")
        if not isinstance(rss_value, (int, float)) or isinstance(rss_value, bool):
            raise EvidenceInputError(
                f"samples line {source_line}.host.rss_kb: must be finite and non-negative"
            )
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
    if host_readiness_path is None:
        host_readiness_evaluation = missing_host_readiness_evaluation()
    else:
        host_readiness_evaluation = evaluate_host_readiness_report(
            _read_host_readiness_json(host_readiness_path)
        )
    evaluation["verdict"] = _combine_all_verdicts(
        str(evaluation["verdict"]),
        str(telemetry_evaluation["verdict"]),
        str(host_readiness_evaluation["verdict"]),
    )
    evaluation["reasons"] = [
        *evaluation["reasons"],
        *telemetry_evaluation["reasons"],
        *host_readiness_evaluation["reasons"],
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "run_id": run_id,
        "source": {
            "summary": _source_path(summary_path, repo_root=repo_root),
            "samples": _source_path(samples_path, repo_root=repo_root),
            "exact_window_report": _source_path(
                exact_window_report_path, repo_root=repo_root
            ),
            "host_readiness": _source_path(
                host_readiness_path, repo_root=repo_root
            ),
        },
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
            "errors": summary.get("errors", []),
        },
        "telemetry_sufficiency": telemetry_evaluation["sufficiency"],
        "telemetry_criteria": telemetry_evaluation["criteria"],
        "telemetry_metrics": telemetry_evaluation["metrics"],
        "host_readiness": host_readiness_evaluation["summary"],
        "host_readiness_sufficiency": host_readiness_evaluation["sufficiency"],
        "host_readiness_criteria": host_readiness_evaluation["criteria"],
        "thresholds": _thresholds(),
        **evaluation,
        "interpretation": INTERPRETATION,
    }


def _source_path(path: Path | None, *, repo_root: Path | None) -> str | None:
    if path is None:
        return None
    if repo_root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _failure_report(
    *,
    error: BaseException | None = None,
    summary_path: Path | None = None,
    samples_path: Path | None = None,
    exact_window_report_path: Path | None = None,
    host_readiness_path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    reason = "the gate inputs could not be validated"
    if error is not None:
        reason = f"{reason}: {error}"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "failed",
        "run_id": None,
        "source": {
            "summary": _source_path(summary_path, repo_root=repo_root),
            "samples": _source_path(samples_path, repo_root=repo_root),
            "exact_window_report": _source_path(
                exact_window_report_path, repo_root=repo_root
            ),
            "host_readiness": _source_path(host_readiness_path, repo_root=repo_root),
        },
        "verdict": "insufficient",
        "window": {},
        "source_summary": {},
        "telemetry_sufficiency": {},
        "telemetry_criteria": {},
        "telemetry_metrics": {},
        "host_readiness": {},
        "host_readiness_sufficiency": {},
        "host_readiness_criteria": {},
        "thresholds": _thresholds(),
        "sufficiency": {},
        "criteria": {},
        "metrics": {},
        "reasons": [reason],
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
    parser.add_argument(
        "--host-readiness",
        type=Path,
        required=True,
        help="scripts/macos_dev_host.py readiness JSON for the same current-source Host session",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="repository root used to record source paths as repo-relative",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_gate(
            arguments.summary,
            arguments.samples,
            arguments.exact_window_report,
            arguments.host_readiness,
            repo_root=arguments.repo_root,
        )
        _write_json(arguments.output, report)
    except (EvidenceInputError, OSError, TypeError, ValueError) as error:
        report = _failure_report(
            error=error,
            summary_path=arguments.summary,
            samples_path=arguments.samples,
            exact_window_report_path=arguments.exact_window_report,
            host_readiness_path=arguments.host_readiness,
            repo_root=arguments.repo_root,
        )
        try:
            _write_json(arguments.output, report)
        except (OSError, TypeError, ValueError):
            print("error: host RSS gate output could not be written", file=sys.stderr)
            return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
