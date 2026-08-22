"""Summarize Phase 2 device-environment acceptance evidence.

This focused gate covers the physical setup and Android platform-environment
conditions for stand-mounted charging stability, controlled thermal-load
behavior, and power-source stability. It consumes explicit observations and
derived measurements; it does not collect ADB data or run the eight-hour soak.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "phase2-device-environment"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_FAIL = "fail"
STATUS_INSUFFICIENT = "insufficient"

MINIMUM_ENVIRONMENT_DURATION_SECONDS = 8 * 60 * 60
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_UNPLUGGED_SAMPLE_COUNT = 0.0
MAXIMUM_NON_CHARGING_SAMPLE_COUNT = 0.0
MAXIMUM_POWER_SOURCE_CHANGE_COUNT = 0.0
DEFAULT_MAXIMUM_THERMAL_STATUS = 2.0
DEFAULT_MAXIMUM_BATTERY_TEMPERATURE_CELSIUS = 45.0
DEFAULT_MAXIMUM_NET_BATTERY_DRAIN_PERCENT = 0.0

ENVIRONMENT_GATES = (
    "stand_mounted_charging_stability",
    "thermal_load",
    "power_source_stability",
)

REQUIRED_FIELDS = (
    (
        "android_device_lock_checked",
        "check /tmp/vibe-screen-device-android.lock before using the Android device and record the result",
    ),
    (
        "device_identity_recorded",
        "record Android serial, manufacturer, model, codename, OS/build, SDK, and ABI",
    ),
    (
        "device_identity_matches_claim",
        "label the evidence with the observed device identity without relabeling substitutes",
    ),
    (
        "physical_8_9_inch_tablet_observed",
        "run on the named physical 8-9 inch tablet, not a phone, emulator, or synthetic layout",
    ),
    (
        "stand_mounted_setup_observed",
        "observe and record the stand orientation, mount, charger, and cable or dock",
    ),
    (
        "eight_hour_environment_window_observed",
        "retain the full eight-hour environment sampling window for this setup",
    ),
    (
        "battery_power_samples_retained",
        "retain raw battery and power-source samples for the full environment window",
    ),
    (
        "thermal_samples_retained",
        "retain raw thermal status and battery-temperature samples for the full environment window",
    ),
    (
        "raw_platform_dumps_retained",
        "retain before/after dumpsys battery, power, and thermalservice artifacts",
    ),
    (
        "controlled_thermal_load_observed",
        "apply and document a safe controlled thermal load on the recorded tablet",
    ),
    (
        "thermal_load_recovery_observed",
        "show the tablet remains usable and returns within the declared thermal limit after load",
    ),
    (
        "settings_status_matches_platform",
        "verify the sustained-use UI agrees with dumpsys battery, power, and thermal state",
    ),
    (
        "run_readme_retained",
        "retain a run README with result, thresholds, commands, and first-failure details",
    ),
)

BLOCKING_FIELDS = {
    "android_device_lock_checked",
    "physical_8_9_inch_tablet_observed",
    "stand_mounted_setup_observed",
    "eight_hour_environment_window_observed",
    "controlled_thermal_load_observed",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)


class DeviceEnvironmentEvidenceError(ValueError):
    """Raised when a device-environment evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise DeviceEnvironmentEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise DeviceEnvironmentEvidenceError(
            "device environment evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise DeviceEnvironmentEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DeviceEnvironmentEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise DeviceEnvironmentEvidenceError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise DeviceEnvironmentEvidenceError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise DeviceEnvironmentEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise DeviceEnvironmentEvidenceError("run_id must be a non-empty string")


def _mapping(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field, {})
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise DeviceEnvironmentEvidenceError(f"{field} must be an object")


def _finite_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeviceEnvironmentEvidenceError(f"{field} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise DeviceEnvironmentEvidenceError(f"{field} must be a finite number")
    return converted


def _threshold(
    thresholds: dict[str, Any],
    key: str,
    default: float,
) -> float:
    value = _finite_number(thresholds.get(key), f"thresholds.{key}")
    if value is None:
        return default
    if value < 0:
        raise DeviceEnvironmentEvidenceError(f"thresholds.{key} must be non-negative")
    return value


def _maximum_criterion(
    *,
    measurements: dict[str, Any],
    field: str,
    maximum: float,
) -> dict[str, Any]:
    measured = _finite_number(measurements.get(field), f"measurements.{field}")
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured is not None and measured <= maximum,
    }


def _minimum_criterion(
    *,
    measurements: dict[str, Any],
    field: str,
    minimum: float,
) -> dict[str, Any]:
    measured = _finite_number(measurements.get(field), f"measurements.{field}")
    return {
        "measured": measured,
        "minimum": minimum,
        "passed": measured is not None and measured >= minimum,
    }


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [item for item in missing if item["field"] in BLOCKING_FIELDS]

    thresholds = _mapping(record, "thresholds")
    measurements = _mapping(record, "measurements")
    resolved_thresholds = {
        "minimum_environment_duration_seconds": MINIMUM_ENVIRONMENT_DURATION_SECONDS,
        "maximum_sample_gap_seconds": _threshold(
            thresholds, "maximum_sample_gap_seconds", MAXIMUM_SAMPLE_GAP_SECONDS
        ),
        "maximum_unplugged_sample_count": MAXIMUM_UNPLUGGED_SAMPLE_COUNT,
        "maximum_non_charging_sample_count": MAXIMUM_NON_CHARGING_SAMPLE_COUNT,
        "maximum_power_source_change_count": MAXIMUM_POWER_SOURCE_CHANGE_COUNT,
        "maximum_thermal_status": _threshold(
            thresholds, "maximum_thermal_status", DEFAULT_MAXIMUM_THERMAL_STATUS
        ),
        "maximum_battery_temperature_celsius": _threshold(
            thresholds,
            "maximum_battery_temperature_celsius",
            DEFAULT_MAXIMUM_BATTERY_TEMPERATURE_CELSIUS,
        ),
        "maximum_net_battery_drain_percent": _threshold(
            thresholds,
            "maximum_net_battery_drain_percent",
            DEFAULT_MAXIMUM_NET_BATTERY_DRAIN_PERCENT,
        ),
    }
    criteria = {
        "environment_duration_seconds": _minimum_criterion(
            measurements=measurements,
            field="environment_duration_seconds",
            minimum=resolved_thresholds["minimum_environment_duration_seconds"],
        ),
        "maximum_sample_gap_seconds": _maximum_criterion(
            measurements=measurements,
            field="maximum_sample_gap_seconds",
            maximum=resolved_thresholds["maximum_sample_gap_seconds"],
        ),
        "unplugged_sample_count": _maximum_criterion(
            measurements=measurements,
            field="unplugged_sample_count",
            maximum=resolved_thresholds["maximum_unplugged_sample_count"],
        ),
        "non_charging_sample_count": _maximum_criterion(
            measurements=measurements,
            field="non_charging_sample_count",
            maximum=resolved_thresholds["maximum_non_charging_sample_count"],
        ),
        "power_source_change_count": _maximum_criterion(
            measurements=measurements,
            field="power_source_change_count",
            maximum=resolved_thresholds["maximum_power_source_change_count"],
        ),
        "maximum_thermal_status": _maximum_criterion(
            measurements=measurements,
            field="maximum_thermal_status",
            maximum=resolved_thresholds["maximum_thermal_status"],
        ),
        "maximum_battery_temperature_celsius": _maximum_criterion(
            measurements=measurements,
            field="maximum_battery_temperature_celsius",
            maximum=resolved_thresholds["maximum_battery_temperature_celsius"],
        ),
        "net_battery_drain_percent": _maximum_criterion(
            measurements=measurements,
            field="net_battery_drain_percent",
            maximum=resolved_thresholds["maximum_net_battery_drain_percent"],
        ),
    }

    missing_criteria = [
        name for name, item in criteria.items() if item["measured"] is None
    ]
    failed_criteria = [
        name
        for name, item in criteria.items()
        if item["measured"] is not None and not item["passed"]
    ]

    if blocking_reasons:
        verdict = STATUS_BLOCKED
    elif missing or missing_criteria:
        verdict = STATUS_INSUFFICIENT
    elif failed_criteria:
        verdict = STATUS_FAIL
    else:
        verdict = STATUS_PASS

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "phase2_device_environment_acceptance",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_device_environment_gates": verdict == STATUS_PASS,
        "does_not_close_eight_hour_stream_gate": True,
        "environment_gates": list(ENVIRONMENT_GATES),
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16 "
            "evidence must not be relabeled as Xiaomi 13/fuxi or as physical tablet evidence."
        ),
        "observations": field_values,
        "thresholds": resolved_thresholds,
        "criteria": criteria,
        "missing_requirements": missing,
        "missing_criteria": missing_criteria,
        "failed_criteria": failed_criteria,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _string_list(record, "artifact_paths"),
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen Phase 2 device-environment evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations, optional "
            "thresholds, and derived measurements. Missing booleans default to false "
            "so absent tablet, stand, thermal-load, or eight-hour environment evidence "
            "cannot accidentally close the gate."
        ),
    )
    parser.add_argument(
        "input", help="phase2 device-environment observations .json file, or - for stdin"
    )
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(args.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        summary = summarize(record, run_id=args.run_id)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (DeviceEnvironmentEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
