"""Evaluate the Phase 2 device memory evidence gate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .phase2_tablet_manifest import KIND as MANIFEST_KIND
from .soak_public_report import EvidenceInputError, read_json as _read_json
from .soak_report import SOAK_REPORT_KIND


GATE_KIND = "phase2_device_memory_gate"
MINIMUM_DURATION_SECONDS = 8 * 60 * 60
MAXIMUM_SAMPLE_INTERVAL_SECONDS = 60
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_ANDROID_PSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_ANDROID_PSS_FULL_WINDOW_DRIFT_KIB = 8 * 1024.0
MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_HOST_RSS_FULL_WINDOW_DRIFT_KIB = 8 * 1024.0
MINIMUM_CHARGING_OR_FULL = 1.0

NON_TABLET_ANDROID_SUBSTITUTES = (
    {"manufacturer": "nubia", "model": "p0110", "codename": "pacific"},
)

INTERPRETATION = (
    "A pass means one schema-backed Phase 2 physical 8-9 inch tablet run supplied "
    "an eight-hour exact window with continuous Android PSS, Host RSS, charging, "
    "and thermal samples inside the declared memory thresholds. It does not close "
    "other Phase 2 recovery, login, headless, stylus, or hardware-keyboard gates."
)


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


def _minimum(measured: float | None, minimum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "minimum": minimum,
        "passed": measured is not None and measured >= minimum,
    }


def _maximum(measured: float | None, maximum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured is not None and measured <= maximum,
    }


def _equals(measured: Any, expected: Any) -> dict[str, Any]:
    return {
        "measured": measured,
        "expected": expected,
        "passed": measured == expected,
    }


def _stats_count(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if isinstance(value, dict):
        return _finite_number(value.get("count"))
    return None


def _stats_min(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if isinstance(value, dict):
        return _finite_number(value.get("min"))
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


def _expected_sample_count(duration_seconds: float | None, interval_seconds: float | None) -> float | None:
    if duration_seconds is None or interval_seconds is None or interval_seconds <= 0:
        return None
    return math.floor(duration_seconds / interval_seconds)


def _tablet_size_inches(manifest: dict[str, Any]) -> float | None:
    value = _get(manifest, "device", "tablet_size_inches")
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return _finite_number(value)


def _is_known_non_tablet_substitute(identity: dict[str, Any]) -> bool:
    normalized = {
        "manufacturer": str(identity.get("manufacturer", "")).strip().lower(),
        "model": str(identity.get("model", "")).strip().lower(),
        "codename": str(identity.get("codename", "")).strip().lower(),
    }
    return any(
        all(normalized.get(key) == value for key, value in substitute.items())
        for substitute in NON_TABLET_ANDROID_SUBSTITUTES
    )


def _validate_manifest(manifest: dict[str, Any]) -> str | None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        return f"manifest.schema_version must be {SCHEMA_VERSION}"
    if manifest.get("kind") != MANIFEST_KIND:
        return f"manifest.kind must be {MANIFEST_KIND}"
    if not isinstance(manifest.get("device"), dict):
        return "manifest.device must be an object"
    if not isinstance(_get(manifest, "device", "identity"), dict):
        return "manifest.device.identity must be an object"
    if not isinstance(manifest.get("session"), dict):
        return "manifest.session must be an object"
    if not isinstance(manifest.get("memory_sampling"), dict):
        return "manifest.memory_sampling must be an object"
    return None


def _validate_report(report: dict[str, Any]) -> str | None:
    if report.get("schema_version") != SCHEMA_VERSION:
        return f"report.schema_version must be {SCHEMA_VERSION}"
    if report.get("kind") != SOAK_REPORT_KIND:
        return f"report.kind must be {SOAK_REPORT_KIND}"
    if report.get("derivation_status") != "complete":
        return "report derivation_status is not complete"
    if _get(report, "source_summary", "status") != "complete":
        return "source soak summary is not complete"
    if report.get("errors", []) != []:
        return "report carries derivation errors"
    source_errors = _get(report, "source_summary", "errors")
    if source_errors not in (None, []):
        return "source soak summary carries errors"
    return None


def _thresholds(manifest: dict[str, Any]) -> dict[str, float]:
    thermal_limit = _finite_number(_get(manifest, "thresholds", "thermal_limit_status"))
    return {
        "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
        "maximum_sample_interval_seconds": MAXIMUM_SAMPLE_INTERVAL_SECONDS,
        "maximum_sample_gap_seconds": MAXIMUM_SAMPLE_GAP_SECONDS,
        "maximum_android_pss_second_half_slope_kib_per_minute": (
            MAXIMUM_ANDROID_PSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_android_pss_full_window_drift_kib": (
            MAXIMUM_ANDROID_PSS_FULL_WINDOW_DRIFT_KIB
        ),
        "maximum_host_rss_second_half_slope_kib_per_minute": (
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_host_rss_full_window_drift_kib": (
            MAXIMUM_HOST_RSS_FULL_WINDOW_DRIFT_KIB
        ),
        "minimum_charging_or_full": MINIMUM_CHARGING_OR_FULL,
        "maximum_thermal_status": thermal_limit if thermal_limit is not None else 2.0,
    }


def derive_gate(manifest_path: Path, report_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path, "Phase 2 tablet manifest")
    report = _read_json(report_path, "exact-window report")
    manifest_validation_error = _validate_manifest(manifest)
    report_validation_error = _validate_report(report)

    identity = _get(manifest, "device", "identity")
    if not isinstance(identity, dict):
        identity = {}
    device_class = _get(manifest, "device", "device_class")
    tablet_size = _tablet_size_inches(manifest)
    duration = _finite_number(_get(report, "window", "duration_seconds"))
    manifest_duration = _finite_number(_get(manifest, "session", "duration_seconds"))
    sample_interval = _finite_number(_get(manifest, "session", "sample_interval_seconds"))
    host_pid = _finite_number(_get(manifest, "memory_sampling", "host_pid"))
    require_host_pid = _get(manifest, "memory_sampling", "require_host_pid")
    expected_samples = _expected_sample_count(manifest_duration, sample_interval)
    minimum_samples = expected_samples if expected_samples is not None else MINIMUM_DURATION_SECONDS / MAXIMUM_SAMPLE_INTERVAL_SECONDS + 1
    thermal_limit = _thresholds(manifest)["maximum_thermal_status"]

    is_known_substitute = _is_known_non_tablet_substitute(identity)
    sufficiency = {
        "manifest_device_class": _equals(device_class, "physical_8_9_inch_tablet"),
        "manifest_tablet_size_inches": {
            "measured": tablet_size,
            "minimum": 8.0,
            "maximum": 9.0,
            "passed": tablet_size is not None and 8.0 <= tablet_size <= 9.0,
        },
        "known_phone_substitute_rejected": {
            "measured": is_known_substitute,
            "expected": False,
            "passed": not is_known_substitute,
        },
        "manifest_duration": _minimum(
            manifest_duration,
            MINIMUM_DURATION_SECONDS,
        ),
        "report_duration": _minimum(duration, MINIMUM_DURATION_SECONDS),
        "manifest_sample_interval": _maximum(
            sample_interval, MAXIMUM_SAMPLE_INTERVAL_SECONDS
        ),
        "manifest_host_pid": {
            "measured": host_pid,
            "required": require_host_pid is not False,
            "passed": require_host_pid is False or (host_pid is not None and host_pid >= 1),
        },
        "report_sample_gap": _maximum(
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
        "report_sample_count": _minimum(
            _finite_number(_get(report, "window", "sample_records_in_window")),
            minimum_samples,
        ),
        "android_pss_samples": _minimum(
            _stats_count(report, "metrics", "memory_kib", "client_total_pss"),
            minimum_samples,
        ),
        "host_rss_samples": _minimum(
            _stats_count(report, "metrics", "memory_kib", "host_rss"),
            minimum_samples,
        ),
        "thermal_status_samples": _minimum(
            _stats_count(report, "metrics", "thermal", "status"),
            minimum_samples,
        ),
        "charging_state_samples": _minimum(
            _stats_count(report, "metrics", "battery", "charging_or_full"),
            minimum_samples,
        ),
    }

    criteria = {
        "android_pss_second_half_slope_kib_per_minute": _maximum(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "memory_kib",
                    "client_total_pss",
                    "slope_kib_per_minute",
                    "second_half",
                )
            ),
            MAXIMUM_ANDROID_PSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
        ),
        "android_pss_full_window_endpoint_drift_kib": _maximum(
            _stats_drift(report, "metrics", "memory_kib", "client_total_pss"),
            MAXIMUM_ANDROID_PSS_FULL_WINDOW_DRIFT_KIB,
        ),
        "host_rss_second_half_slope_kib_per_minute": _maximum(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "memory_kib",
                    "host_rss",
                    "slope_kib_per_minute",
                    "second_half",
                )
            ),
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
        ),
        "host_rss_full_window_endpoint_drift_kib": _maximum(
            _stats_drift(report, "metrics", "memory_kib", "host_rss"),
            MAXIMUM_HOST_RSS_FULL_WINDOW_DRIFT_KIB,
        ),
        "charging_or_full_min": _minimum(
            _stats_min(report, "metrics", "battery", "charging_or_full"),
            MINIMUM_CHARGING_OR_FULL,
        ),
        "thermal_status_max": _maximum(
            _stats_max(report, "metrics", "thermal", "status"),
            thermal_limit,
        ),
    }

    reasons: list[str] = []
    if manifest_validation_error is not None:
        reasons.append(manifest_validation_error)
    if report_validation_error is not None:
        reasons.append(report_validation_error)
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
        manifest_validation_error is not None
        or report_validation_error is not None
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
        "manifest": {
            "run_id": manifest.get("run_id"),
            "device_identity": identity,
            "device_class": device_class,
            "tablet_size_inches": _get(manifest, "device", "tablet_size_inches"),
            "memory_sampling": manifest.get("memory_sampling"),
        },
        "report": {
            "run_id": report.get("run_id"),
            "window": report.get("window") if isinstance(report.get("window"), dict) else {},
            "source_summary": report.get("source_summary")
            if isinstance(report.get("source_summary"), dict)
            else {},
        },
        "thresholds": _thresholds(manifest),
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
        "manifest": {},
        "report": {},
        "thresholds": _thresholds({}),
        "sufficiency": {},
        "criteria": {},
        "reasons": ["the Phase 2 device memory gate inputs could not be validated"],
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
    parser.add_argument("--manifest", type=Path, required=True, help="Phase 2 tablet manifest JSON")
    parser.add_argument("--report", type=Path, required=True, help="exact-window soak report JSON")
    parser.add_argument("--output", type=Path, required=True, help="Phase 2 device memory gate JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_gate(arguments.manifest, arguments.report)
        _write_json(arguments.output, report)
    except (EvidenceInputError, OSError, TypeError, ValueError):
        report = _failure_report()
        try:
            _write_json(arguments.output, report)
        except (OSError, TypeError, ValueError):
            print("error: Phase 2 device memory gate output could not be written", file=sys.stderr)
            return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
