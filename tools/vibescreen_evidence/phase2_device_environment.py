"""Evaluate Phase 2 stand, thermal-load, and power environment evidence.

The input is an explicit observation record prepared beside a Phase 2 tablet
evidence package. This tool is intentionally passive: it does not run ADB,
start the Host, or infer missing physical setup from logs. Missing tablet,
stand, controlled-load, raw dump, or eight-hour observations fail closed so
short phone readiness checks cannot become Phase 2 tablet acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import uuid
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


INPUT_KIND = "phase2_device_environment_observations"
GATE_KIND = "phase2_device_environment_gate"
GATE_PROFILE = "phase2-device-environment"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_FAIL = "fail"
STATUS_INSUFFICIENT = "insufficient"

MINIMUM_ENVIRONMENT_DURATION_SECONDS = 8 * 60 * 60
DEFAULT_MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
DEFAULT_MAXIMUM_THERMAL_STATUS = 2.0
DEFAULT_MAXIMUM_BATTERY_TEMPERATURE_CELSIUS = 45.0
DEFAULT_MAXIMUM_NET_BATTERY_DRAIN_PERCENT = 0.0
DEFAULT_MINIMUM_POWER_VOLTAGE_UV = 3_500_000.0
DEFAULT_MAXIMUM_POWER_SOURCE_CHANGE_COUNT = 0.0
MAXIMUM_UNPLUGGED_SAMPLE_COUNT = 0.0
MAXIMUM_NON_CHARGING_SAMPLE_COUNT = 0.0
MAXIMUM_NEGATIVE_CHARGE_COUNTER_DRIFT_UAH = 0.0

ENVIRONMENT_GATES = (
    "stand_mounted_charging",
    "thermal_power_sampling",
    "power_source_stability",
)

NON_TABLET_ANDROID_SUBSTITUTES = (
    {"manufacturer": "nubia", "model": "p0110", "codename": "pacific"},
)
REQUIRED_IDENTITY_FIELDS = (
    "adb_serial",
    "manufacturer",
    "model",
    "codename",
    "android_release",
    "sdk",
    "build_fingerprint",
    "abi",
)

REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("android_device_lock_checked", "check /tmp/vibe-screen-device-android.lock before using the Android device and record the result"),
    ("device_identity_recorded", "record Android serial, manufacturer, model, codename, OS/build, SDK, and ABI"),
    ("device_identity_matches_claim", "label evidence with the observed device identity without relabeling substitutes"),
    ("physical_8_9_inch_tablet_observed", "run on the named physical 8-9 inch tablet, not a phone, emulator, or synthetic layout"),
    ("stand_mounted_setup_observed", "observe and record the stand orientation, mount, charger, and cable or dock"),
    ("eight_hour_environment_window_observed", "retain the full eight-hour environment sampling window for this setup"),
    ("battery_power_samples_retained", "retain raw battery and power-source samples for the full environment window"),
    ("thermal_samples_retained", "retain raw thermal status and battery-temperature samples for the full environment window"),
    ("raw_platform_dumps_retained", "retain before/after dumpsys battery, power, and thermalservice artifacts"),
    ("controlled_thermal_load_observed", "apply and document a safe controlled thermal load on the recorded tablet"),
    ("thermal_load_recovery_observed", "show the tablet remains usable and returns within the declared thermal limit after load"),
    ("settings_status_matches_platform", "verify the sustained-use UI agrees with dumpsys battery, power, and thermal state"),
    ("run_readme_retained", "retain a run README with result, thresholds, commands, and first-failure details"),
)

BLOCKING_FIELDS = {
    "android_device_lock_checked",
    "device_identity_recorded",
    "device_identity_matches_claim",
    "physical_8_9_inch_tablet_observed",
    "stand_mounted_setup_observed",
    "eight_hour_environment_window_observed",
    "controlled_thermal_load_observed",
}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
STAND_FIELDS = {
    "android_device_lock_checked",
    "device_identity_recorded",
    "device_identity_matches_claim",
    "physical_8_9_inch_tablet_observed",
    "stand_mounted_setup_observed",
    "eight_hour_environment_window_observed",
    "battery_power_samples_retained",
    "raw_platform_dumps_retained",
    "settings_status_matches_platform",
    "run_readme_retained",
}
THERMAL_POWER_FIELDS = {
    "android_device_lock_checked",
    "device_identity_recorded",
    "device_identity_matches_claim",
    "physical_8_9_inch_tablet_observed",
    "eight_hour_environment_window_observed",
    "battery_power_samples_retained",
    "thermal_samples_retained",
    "raw_platform_dumps_retained",
    "controlled_thermal_load_observed",
    "thermal_load_recovery_observed",
    "settings_status_matches_platform",
    "run_readme_retained",
}

REQUIRED_ARTIFACTS: tuple[tuple[str, bool], ...] = (
    ("README.md", True),
    ("device-info.json", True),
    ("adb-battery-before.txt", True),
    ("adb-battery-after.txt", True),
    ("adb-power-before.txt", True),
    ("adb-power-after.txt", True),
    ("thermal-before.txt", True),
    ("thermal-before.err", False),
    ("thermal-after.txt", True),
    ("thermal-after.err", False),
    ("soak-8h/samples.jsonl", True),
    ("soak-8h/summary.json", True),
    ("soak-8h/exact-window-report.json", True),
    ("screenshots/sustained-use-portrait.png", True),
    ("screenshots/sustained-use-landscape.png", True),
)

INTERPRETATION = (
    "A pass means a physical 8-9 inch tablet run supplied explicit stand-mounted "
    "setup observations, an eight-hour environment window, continuous battery, "
    "power-source, and thermal samples, and a controlled thermal-load recovery "
    "record within the declared thresholds. This summary does not close the "
    "separate eight-hour stream, device-memory, recovery, login, headless, "
    "stylus, or hardware-keyboard gates."
)


class DeviceEnvironmentEvidenceError(ValueError):
    """Raised when a Phase 2 device-environment record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise DeviceEnvironmentEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise DeviceEnvironmentEvidenceError("device environment evidence must be a JSON object")
    if record.get("schema_version") not in (None, SCHEMA_VERSION):
        raise DeviceEnvironmentEvidenceError(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") not in (None, INPUT_KIND):
        raise DeviceEnvironmentEvidenceError(f"kind must be {INPUT_KIND}")
    return record


def _get(record: dict[str, Any], *path: str) -> Any:
    value: Any = record
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


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
        raise DeviceEnvironmentEvidenceError(f"{field} must contain only non-empty strings")
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise DeviceEnvironmentEvidenceError(f"{field} must be a string")


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


def _safe_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _threshold(thresholds: dict[str, Any], key: str, default: float) -> float:
    value = _finite_number(thresholds.get(key), f"thresholds.{key}")
    if value is None:
        return default
    if value < 0:
        raise DeviceEnvironmentEvidenceError(f"thresholds.{key} must be non-negative")
    return value


def _measurement(
    measurements: dict[str, Any], field: str, *, non_negative: bool = False, integer: bool = False
) -> float | None:
    measured = _finite_number(measurements.get(field), f"measurements.{field}")
    if non_negative and measured is not None and measured < 0:
        raise DeviceEnvironmentEvidenceError(f"measurements.{field} must be non-negative")
    if integer and measured is not None and not measured.is_integer():
        raise DeviceEnvironmentEvidenceError(f"measurements.{field} must be an integer")
    return measured


def _maximum_criterion(
    measurements: dict[str, Any],
    field: str,
    maximum: float,
    *,
    non_negative: bool = False,
    integer: bool = False,
) -> dict[str, Any]:
    measured = _measurement(measurements, field, non_negative=non_negative, integer=integer)
    return {"measured": measured, "maximum": maximum, "passed": measured is not None and measured <= maximum}


def _minimum_criterion(
    measurements: dict[str, Any],
    field: str,
    minimum: float,
    *,
    non_negative: bool = False,
) -> dict[str, Any]:
    measured = _measurement(measurements, field, non_negative=non_negative)
    return {"measured": measured, "minimum": minimum, "passed": measured is not None and measured >= minimum}


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
    if value.strip():
        return value
    raise DeviceEnvironmentEvidenceError("run_id must be a non-empty string")


def _normalized_identity(record: dict[str, Any]) -> dict[str, str]:
    identity = _get(record, "device", "identity")
    if not isinstance(identity, dict):
        return {}
    normalized: dict[str, str] = {}
    for key in (
        "adb_serial",
        "device_serial",
        "manufacturer",
        "model",
        "codename",
        "android_release",
        "sdk",
        "build_fingerprint",
        "abi",
    ):
        value = identity.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise DeviceEnvironmentEvidenceError(f"device.identity.{key} must be a string")
        normalized[key] = value.strip()
    return normalized


def _is_known_non_tablet_substitute(identity: dict[str, str]) -> bool:
    normalized = {
        "manufacturer": identity.get("manufacturer", "").lower(),
        "model": identity.get("model", "").lower(),
        "codename": identity.get("codename", "").lower(),
    }
    return any(
        all(normalized.get(key) == value for key, value in substitute.items())
        for substitute in NON_TABLET_ANDROID_SUBSTITUTES
    )


def _missing_identity_fields(identity: dict[str, str]) -> list[str]:
    return [field for field in REQUIRED_IDENTITY_FIELDS if not identity.get(field)]


def _tablet_size_inches(record: dict[str, Any]) -> float | None:
    value = _get(record, "device", "tablet_size_inches")
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return _safe_finite_number(value)


def _artifact_paths(record: dict[str, Any]) -> list[str]:
    paths = _string_list(record, "artifact_paths")
    artifacts = record.get("artifacts")
    if artifacts is None:
        return paths
    if not isinstance(artifacts, dict):
        raise DeviceEnvironmentEvidenceError("artifacts must be an object")
    for value in artifacts.values():
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
        elif isinstance(value, list):
            if not all(isinstance(item, str) and item.strip() for item in value):
                raise DeviceEnvironmentEvidenceError("artifacts lists must contain non-empty strings")
            paths.extend(item.strip() for item in value)
        else:
            raise DeviceEnvironmentEvidenceError("artifacts values must be strings or string lists")
    return sorted(set(paths))


def _artifact_checks(paths: list[str], evidence_dir: Path | None) -> dict[str, Any]:
    supplied = set(paths)
    checks: dict[str, Any] = {}
    for relative_path, require_non_empty in REQUIRED_ARTIFACTS:
        path = evidence_dir / relative_path if evidence_dir is not None else None
        listed = relative_path in supplied
        exists = path.is_file() if path is not None else None
        size_bytes = None
        if path is not None and exists:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
        if evidence_dir is None:
            passed = False
            expected = "file exists; rerun with --evidence-dir for filesystem verification"
        else:
            passed = bool(exists and (not require_non_empty or (size_bytes is not None and size_bytes > 0)))
            expected = "non-empty file exists" if require_non_empty else "file exists"
        checks[relative_path] = {
            "listed": listed,
            "path": str(path) if path is not None else relative_path,
            "size_bytes": size_bytes,
            "expected": expected,
            "passed": passed,
        }
    return checks


def _build_criteria(measurements: dict[str, Any], thresholds: dict[str, float]) -> dict[str, dict[str, Any]]:
    return {
        "environment_duration_seconds": _minimum_criterion(measurements, "environment_duration_seconds", thresholds["minimum_environment_duration_seconds"], non_negative=True),
        "maximum_sample_gap_seconds": _maximum_criterion(measurements, "maximum_sample_gap_seconds", thresholds["maximum_sample_gap_seconds"], non_negative=True),
        "unplugged_sample_count": _maximum_criterion(measurements, "unplugged_sample_count", thresholds["maximum_unplugged_sample_count"], non_negative=True, integer=True),
        "non_charging_sample_count": _maximum_criterion(measurements, "non_charging_sample_count", thresholds["maximum_non_charging_sample_count"], non_negative=True, integer=True),
        "power_source_change_count": _maximum_criterion(measurements, "power_source_change_count", thresholds["maximum_power_source_change_count"], non_negative=True, integer=True),
        "maximum_thermal_status": _maximum_criterion(measurements, "maximum_thermal_status", thresholds["maximum_thermal_status"], non_negative=True),
        "thermal_recovery_status_max": _maximum_criterion(measurements, "thermal_recovery_status_max", thresholds["maximum_thermal_status"], non_negative=True),
        "maximum_battery_temperature_celsius": _maximum_criterion(measurements, "maximum_battery_temperature_celsius", thresholds["maximum_battery_temperature_celsius"]),
        "net_battery_drain_percent": _maximum_criterion(measurements, "net_battery_drain_percent", thresholds["maximum_net_battery_drain_percent"]),
        "power_voltage_now_uv_min": _minimum_criterion(measurements, "power_voltage_now_uv_min", thresholds["minimum_power_voltage_uv"], non_negative=True),
        "charge_counter_uah_negative_drift": _maximum_criterion(measurements, "charge_counter_uah_negative_drift", thresholds["maximum_negative_charge_counter_drift_uah"], non_negative=True),
    }


def _resolved_thresholds(record: dict[str, Any]) -> dict[str, float]:
    thresholds = _mapping(record, "thresholds")
    return {
        "minimum_environment_duration_seconds": MINIMUM_ENVIRONMENT_DURATION_SECONDS,
        "maximum_sample_gap_seconds": _threshold(thresholds, "maximum_sample_gap_seconds", DEFAULT_MAXIMUM_SAMPLE_GAP_SECONDS),
        "maximum_unplugged_sample_count": MAXIMUM_UNPLUGGED_SAMPLE_COUNT,
        "maximum_non_charging_sample_count": MAXIMUM_NON_CHARGING_SAMPLE_COUNT,
        "maximum_power_source_change_count": _threshold(thresholds, "maximum_power_source_change_count", DEFAULT_MAXIMUM_POWER_SOURCE_CHANGE_COUNT),
        "maximum_thermal_status": _threshold(thresholds, "maximum_thermal_status", DEFAULT_MAXIMUM_THERMAL_STATUS),
        "maximum_battery_temperature_celsius": _threshold(thresholds, "maximum_battery_temperature_celsius", DEFAULT_MAXIMUM_BATTERY_TEMPERATURE_CELSIUS),
        "maximum_net_battery_drain_percent": _threshold(thresholds, "maximum_net_battery_drain_percent", DEFAULT_MAXIMUM_NET_BATTERY_DRAIN_PERCENT),
        "minimum_power_voltage_uv": _threshold(thresholds, "minimum_power_voltage_uv", DEFAULT_MINIMUM_POWER_VOLTAGE_UV),
        "maximum_negative_charge_counter_drift_uah": MAXIMUM_NEGATIVE_CHARGE_COUNTER_DRIFT_UAH,
    }


def _device_checks(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    identity = _normalized_identity(record)
    device_class = _get(record, "device", "device_class")
    tablet_size = _tablet_size_inches(record)
    known_substitute = _is_known_non_tablet_substitute(identity)
    missing_identity_fields = _missing_identity_fields(identity)
    return {
        "identity": identity,
        "device_class": device_class,
        "tablet_size_inches": tablet_size,
    }, {
        "identity_required_fields": {
            "measured_missing": missing_identity_fields,
            "expected": list(REQUIRED_IDENTITY_FIELDS),
            "passed": not missing_identity_fields,
        },
        "device_class": {"measured": device_class, "expected": "physical_8_9_inch_tablet", "passed": device_class == "physical_8_9_inch_tablet"},
        "tablet_size_inches": {"measured": tablet_size, "minimum": 8.0, "maximum": 9.0, "passed": tablet_size is not None and 8.0 <= tablet_size <= 9.0},
        "known_phone_substitute_rejected": {"measured": known_substitute, "expected": False, "passed": not known_substitute},
    }


def _device_blocking_reasons(device_checks: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    reasons = []
    for name, item in device_checks.items():
        if item["passed"]:
            continue
        if name == "identity_required_fields":
            reasons.append(
                {
                    "field": "device.identity",
                    "requirement": "device identity must include non-empty adb_serial, manufacturer, model, codename, Android release, SDK, build fingerprint, and ABI fields",
                }
            )
        else:
            reasons.append(
                {
                    "field": f"device.{name}",
                    "requirement": "device environment evidence must come from the named physical 8-9 inch tablet, not a phone substitute",
                }
            )
    return reasons


def _close_signals(
    *,
    blocking_reasons: list[dict[str, str]],
    missing_requirements: list[dict[str, str]],
    missing_artifacts: list[str],
    criteria: dict[str, dict[str, Any]],
) -> tuple[bool, bool]:
    stand_criteria = {
        "environment_duration_seconds",
        "maximum_sample_gap_seconds",
        "unplugged_sample_count",
        "non_charging_sample_count",
        "power_source_change_count",
        "net_battery_drain_percent",
        "power_voltage_now_uv_min",
        "charge_counter_uah_negative_drift",
    }
    thermal_power_criteria = {
        "environment_duration_seconds",
        "maximum_sample_gap_seconds",
        "power_source_change_count",
        "maximum_thermal_status",
        "thermal_recovery_status_max",
        "maximum_battery_temperature_celsius",
        "power_voltage_now_uv_min",
        "charge_counter_uah_negative_drift",
    }
    stand_missing = {item["field"] for item in missing_requirements if item["field"] in STAND_FIELDS}
    thermal_power_missing = {item["field"] for item in missing_requirements if item["field"] in THERMAL_POWER_FIELDS}
    can_close_stand = not blocking_reasons and not stand_missing and not missing_artifacts and all(
        criteria[name]["passed"] for name in stand_criteria
    )
    can_close_environment = not blocking_reasons and not thermal_power_missing and not missing_artifacts and all(
        criteria[name]["passed"] for name in thermal_power_criteria
    )
    return can_close_stand, can_close_environment


def summarize(
    record: dict[str, Any], *, run_id: str | None = None, evidence_dir: Path | None = None
) -> dict[str, Any]:
    observations = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing_requirements = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not observations[field]
    ]
    blocking_reasons = [item for item in missing_requirements if item["field"] in BLOCKING_FIELDS]
    device, device_checks = _device_checks(record)
    blocking_reasons.extend(_device_blocking_reasons(device_checks))
    thresholds = _resolved_thresholds(record)
    measurements = _mapping(record, "measurements")
    criteria = _build_criteria(measurements, thresholds)
    missing_criteria = [name for name, item in criteria.items() if item["measured"] is None]
    failed_criteria = [name for name, item in criteria.items() if item["measured"] is not None and not item["passed"]]
    paths = _artifact_paths(record)
    artifact_checks = _artifact_checks(paths, evidence_dir)
    missing_artifacts = [name for name, item in artifact_checks.items() if not item["passed"]]
    missing_requirements.extend(
        {"field": f"artifact.{name}", "requirement": item["expected"]}
        for name, item in artifact_checks.items()
        if not item["passed"]
    )
    if blocking_reasons:
        verdict = STATUS_BLOCKED
    elif missing_requirements or missing_criteria:
        verdict = STATUS_INSUFFICIENT
    elif failed_criteria:
        verdict = STATUS_FAIL
    else:
        verdict = STATUS_PASS
    can_close_stand, can_close_environment = _close_signals(
        blocking_reasons=blocking_reasons,
        missing_requirements=missing_requirements,
        missing_artifacts=missing_artifacts,
        criteria=criteria,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": GATE_KIND,
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_device_environment_gate": can_close_environment,
        "can_close_device_environment_gates": can_close_environment and can_close_stand,
        "can_close_stand_charging_gate": can_close_stand,
        "does_not_close_eight_hour_stream_gate": True,
        "environment_gates": list(ENVIRONMENT_GATES),
        "device": device,
        "required_device_identity": "Record the actual Android device identity; Nubia P0110/pacific/Android 16 evidence must not be relabeled as Xiaomi 13/fuxi or as physical tablet evidence.",
        "observations": observations,
        "device_checks": device_checks,
        "thresholds": thresholds,
        "criteria": criteria,
        "artifact_checks": artifact_checks,
        "missing_artifacts": missing_artifacts,
        "missing_requirements": missing_requirements,
        "missing_criteria": missing_criteria,
        "failed_criteria": failed_criteria,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": paths,
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
        "interpretation": INTERPRETATION,
    }


def _failure_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "kind": GATE_KIND,
        "profile": GATE_PROFILE,
        "verdict": STATUS_INSUFFICIENT,
        "can_close_device_environment_gate": False,
        "can_close_device_environment_gates": False,
        "can_close_stand_charging_gate": False,
        "does_not_close_eight_hour_stream_gate": True,
        "environment_gates": list(ENVIRONMENT_GATES),
        "device": {"identity": {}, "device_class": None, "tablet_size_inches": None},
        "required_device_identity": "The Phase 2 device-environment gate inputs could not be validated.",
        "observations": {field: False for field in BOOLEAN_FIELDS},
        "device_checks": {},
        "thresholds": {},
        "criteria": {},
        "artifact_checks": {},
        "missing_artifacts": [],
        "missing_requirements": [],
        "missing_criteria": [],
        "failed_criteria": [],
        "blocking_reasons": [],
        "artifact_paths": [],
        "blocking_notes": [
            "the Phase 2 device-environment gate inputs could not be validated"
        ],
        "notes": "",
        "interpretation": INTERPRETATION,
    }


def _write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="phase2 device-environment observations .json file, or - for stdin",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="output summary JSON file",
    )
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="evidence package root for artifact existence checks",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(arguments.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        summary = summarize(
            record,
            run_id=arguments.run_id,
            evidence_dir=arguments.evidence_dir,
        )
        _write_summary(summary, arguments.output)
    except (DeviceEnvironmentEvidenceError, OSError, TypeError, ValueError):
        summary = _failure_report()
        try:
            _write_summary(summary, arguments.output)
        except (OSError, TypeError, ValueError):
            print(
                "error: Phase 2 device-environment gate output could not be written",
                file=sys.stderr,
            )
            return 1
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0 if summary.get("verdict") == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
