"""Evaluate the Phase 2 eight-hour tablet productization evidence gate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .phase2_tablet_manifest import KIND as MANIFEST_KIND
from .phase2_tablet_manifest import MAXIMUM_TABLET_SIZE_INCHES
from .phase2_tablet_manifest import MINIMUM_DURATION_SECONDS as MANIFEST_MINIMUM_DURATION_SECONDS
from .phase2_tablet_manifest import MINIMUM_TABLET_SIZE_INCHES
from .phase2_tablet_manifest import NUBIA_P0110_CODENAME
from .phase2_tablet_manifest import NUBIA_P0110_MODEL
from .phase2_tablet_manifest import PHYSICAL_TABLET_DEVICE_CLASS
from .soak_public_report import EvidenceInputError, read_json as _read_json
from .soak_report import SOAK_REPORT_KIND


GATE_KIND = "phase2_tablet_productization_gate"
MINIMUM_DURATION_SECONDS = 8 * 60 * 60 * 0.98
MINIMUM_SAMPLE_COUNT = 8 * 60 * 2 * 0.98
MINIMUM_TELEMETRY_COUNT = 8 * 60 * 2 * 0.98
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_STREAM_STATS_GAP_SECONDS = 90.0
MAXIMUM_HEARTBEAT_GAP_SECONDS = 90.0
MAXIMUM_RECONNECT_COUNT = 0
MAXIMUM_QUEUE_DROP_TOTAL = 0.0
MAXIMUM_DROPPED_FRAMES = 0.0
MAXIMUM_THERMAL_STATUS = 2.0
MAXIMUM_BATTERY_TEMPERATURE_CELSIUS = 45.0
MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB = 8 * 1024.0
MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB = 8 * 1024.0
ANDROID_BATTERY_STATUS_CHARGING = 2
ANDROID_BATTERY_STATUS_FULL = 5
REQUIRED_GATE_OWNERS: tuple[tuple[str, str], ...] = (
    (
        "stand_mounted_charging",
        "owner for stand-mounted charging stability acceptance",
    ),
    (
        "thermal_power_sampling",
        "owner for thermal and power sampling acceptance",
    ),
    (
        "posture_and_mount",
        "owner for stand posture, mount, charger, cable, and ambient setup review",
    ),
    (
        "eight_hour_sustained_stream",
        "owner for the eight-hour sustained streaming verdict",
    ),
)

PHASE2_MANIFEST_NAME = "phase2-tablet-manifest.json"
REQUIRED_EVIDENCE_ARTIFACTS: tuple[tuple[str, tuple[str, ...], bool, str], ...] = (
    ("readme", ("README.md",), True, "file"),
    ("device_info", ("device-info.json",), True, "file"),
    ("device_properties", ("device.txt",), True, "file"),
    ("host_identity", ("host.txt",), True, "file"),
    ("build_log", ("build.txt",), True, "file"),
    ("apk_sha256", ("apk-sha256.txt",), True, "file"),
    ("samples_jsonl", ("samples.jsonl", "soak-8h/samples.jsonl"), True, "file"),
    ("summary_json", ("summary.json", "soak-8h/summary.json"), True, "file"),
    (
        "exact_window_report",
        ("exact-window-report.json", "soak-8h/exact-window-report.json"),
        True,
        "file",
    ),
    ("adb_battery_before", ("adb-battery-before.txt",), True, "file"),
    ("adb_battery_after", ("adb-battery-after.txt",), True, "file"),
    ("adb_power_before", ("adb-power-before.txt",), True, "file"),
    ("adb_power_after", ("adb-power-after.txt",), True, "file"),
    ("thermal_before", ("thermal-before.txt",), True, "file"),
    ("thermal_before_stderr", ("thermal-before.err",), False, "file"),
    ("thermal_after", ("thermal-after.txt",), True, "file"),
    ("thermal_after_stderr", ("thermal-after.err",), False, "file"),
    ("raw_logcat", ("raw-logcat.txt",), True, "file"),
    ("host_log", ("host.log",), True, "file"),
    ("reconnects_log", ("reconnects.log",), True, "file"),
    ("frame_drops_log", ("frame-drops.log",), True, "file"),
    ("decoder_telemetry", ("decoder-telemetry.jsonl",), True, "file"),
    ("screenshots", ("screenshots",), False, "directory"),
)

INTERPRETATION = (
    "A pass means the exact-window report, Phase 2 tablet manifest, and raw "
    "evidence package all satisfy the productization gate checks implemented by "
    "this tool. Unmeasured stand, thermal, power, recovery, login, or headless "
    "conditions remain open unless their raw artifacts are present and checked in "
    "the evidence bundle."
)


def _thresholds(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    thermal_limit = _finite_number(
        _manifest_get(manifest or {}, "thresholds", "thermal_limit_status")
    )
    battery_temperature_limit = _finite_number(
        _manifest_get(manifest or {}, "thresholds", "battery_temperature_limit_celsius")
    )
    maximum_net_battery_drain = _finite_number(
        _manifest_get(manifest or {}, "thresholds", "maximum_net_battery_drain_percent")
    )
    return {
        "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
        "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
        "minimum_telemetry_count": MINIMUM_TELEMETRY_COUNT,
        "maximum_sample_gap_seconds": MAXIMUM_SAMPLE_GAP_SECONDS,
        "maximum_stream_stats_gap_seconds": MAXIMUM_STREAM_STATS_GAP_SECONDS,
        "maximum_heartbeat_gap_seconds": MAXIMUM_HEARTBEAT_GAP_SECONDS,
        "maximum_reconnect_count": MAXIMUM_RECONNECT_COUNT,
        "maximum_queue_drop_total": MAXIMUM_QUEUE_DROP_TOTAL,
        "maximum_dropped_frames": MAXIMUM_DROPPED_FRAMES,
        "maximum_thermal_status": thermal_limit
        if thermal_limit is not None
        else MAXIMUM_THERMAL_STATUS,
        "maximum_battery_temperature_celsius": battery_temperature_limit
        if battery_temperature_limit is not None
        else MAXIMUM_BATTERY_TEMPERATURE_CELSIUS,
        "maximum_net_battery_drain_percent": maximum_net_battery_drain
        if maximum_net_battery_drain is not None
        else 0,
        "allowed_battery_statuses": [
            ANDROID_BATTERY_STATUS_CHARGING,
            ANDROID_BATTERY_STATUS_FULL,
        ],
        "minimum_plugged_value": 1,
        "maximum_client_rss_second_half_slope_kib_per_minute": (
            MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_client_rss_second_half_drift_kib": (
            MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB
        ),
        "maximum_host_rss_second_half_slope_kib_per_minute": (
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE
        ),
        "maximum_host_rss_second_half_drift_kib": (
            MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB
        ),
    }


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


def _criterion(measured: float | None, maximum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "maximum": maximum,
        "passed": measured is not None and measured <= maximum,
    }


def _minimum(measured: float | None, minimum: float) -> dict[str, Any]:
    return {
        "measured": measured,
        "minimum": minimum,
        "passed": measured is not None and measured >= minimum,
    }


def _stats_count(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if isinstance(value, dict):
        return _finite_number(value.get("count"))
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


def _stats_negative_drift(report: dict[str, Any], *path: str) -> float | None:
    drift = _stats_drift(report, *path)
    if drift is None:
        return None
    return max(0.0, -drift)


def _plugged_count(report: dict[str, Any], plugged_value: int) -> float | None:
    counts = _get(report, "metrics", "battery", "plugged_counts")
    if not isinstance(counts, dict):
        return None
    value = counts.get(str(plugged_value))
    return 0.0 if value is None else _finite_number(value)


def _non_charging_status_count(report: dict[str, Any]) -> float | None:
    counts = _get(report, "metrics", "battery", "status_counts")
    if not isinstance(counts, dict):
        return None
    total = 0.0
    for status, count in counts.items():
        parsed = _finite_number(count)
        if parsed is None:
            return None
        if str(status) not in {
            str(ANDROID_BATTERY_STATUS_CHARGING),
            str(ANDROID_BATTERY_STATUS_FULL),
        }:
            total += parsed
    return total


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _manifest_get(manifest: dict[str, Any], *path: str) -> Any:
    value: Any = manifest
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


def _boolean_check(passed: bool, expected: str) -> dict[str, Any]:
    return {"passed": passed, "expected": expected}


def _gate_owner_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    owners = _manifest_get(manifest, "gate_owners")
    if not isinstance(owners, dict):
        owners = {}
    checks: dict[str, dict[str, Any]] = {}
    for key, description in REQUIRED_GATE_OWNERS:
        value = owners.get(key)
        checks[key] = {
            "passed": _non_empty_string(value),
            "owner": value if isinstance(value, str) else None,
            "expected": f"gate_owners.{key} declares {description}",
        }
    return checks


def _tablet_size_inches(manifest: dict[str, Any]) -> float | None:
    value = _manifest_get(manifest, "device", "tablet_size_inches")
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return _finite_number(value)


def _is_nubia_p0110_manifest(manifest: dict[str, Any]) -> bool:
    model = str(_manifest_get(manifest, "device", "identity", "model") or "").strip().lower()
    codename = str(_manifest_get(manifest, "device", "identity", "codename") or "").strip().lower()
    return model == NUBIA_P0110_MODEL and codename == NUBIA_P0110_CODENAME


def _artifact_check(
    evidence_dir: Path,
    candidates: tuple[str, ...],
    require_non_empty: bool,
    artifact_type: str,
) -> dict[str, Any]:
    checked = [str(Path(candidate)) for candidate in candidates]
    for candidate in candidates:
        path = evidence_dir / candidate
        if artifact_type == "directory":
            if path.is_dir():
                return {
                    "passed": True,
                    "path": str(path),
                    "checked": checked,
                    "expected": "directory exists",
                }
            continue
        if not path.is_file():
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
        passed = not require_non_empty or (size_bytes is not None and size_bytes > 0)
        return {
            "passed": passed,
            "path": str(path),
            "checked": checked,
            "size_bytes": size_bytes,
            "expected": "non-empty file" if require_non_empty else "file exists",
        }
    return {
        "passed": False,
        "path": None,
        "checked": checked,
        "expected": "directory exists"
        if artifact_type == "directory"
        else ("non-empty file" if require_non_empty else "file exists"),
    }


def _evaluate_evidence_package(
    *,
    manifest_path: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path, "Phase 2 tablet manifest")
    manifest_checks = {
        "schema_version": _boolean_check(
            manifest.get("schema_version") == SCHEMA_VERSION,
            f"{SCHEMA_VERSION}",
        ),
        "kind": _boolean_check(
            manifest.get("kind") == MANIFEST_KIND,
            MANIFEST_KIND,
        ),
        "physical_8_9_inch_tablet": _boolean_check(
            _manifest_get(manifest, "device", "device_class") == PHYSICAL_TABLET_DEVICE_CLASS,
            "device.device_class is physical_8_9_inch_tablet",
        ),
        "tablet_size_inches": _boolean_check(
            (size_inches := _tablet_size_inches(manifest)) is not None
            and MINIMUM_TABLET_SIZE_INCHES <= size_inches <= MAXIMUM_TABLET_SIZE_INCHES,
            "device.tablet_size_inches is a numeric 8.0..9.0 value",
        ),
        "not_nubia_p0110_substitute": _boolean_check(
            not _is_nubia_p0110_manifest(manifest),
            "Nubia P0110/pacific cannot close the physical 8-9 inch tablet gate",
        ),
        "stand_setup_declared": _boolean_check(
            _non_empty_string(_manifest_get(manifest, "physical_setup", "stand_setup")),
            "physical_setup.stand_setup is non-empty",
        ),
        "charger_declared": _boolean_check(
            _non_empty_string(_manifest_get(manifest, "physical_setup", "charger")),
            "physical_setup.charger is non-empty",
        ),
        "cable_or_dock_declared": _boolean_check(
            _non_empty_string(_manifest_get(manifest, "physical_setup", "cable_or_dock")),
            "physical_setup.cable_or_dock is non-empty",
        ),
        "ambient_temperature_declared": _boolean_check(
            _finite_number(_manifest_get(manifest, "physical_setup", "ambient_temperature_celsius"))
            is not None,
            "physical_setup.ambient_temperature_celsius is finite",
        ),
        "duration_declared": _boolean_check(
            _finite_number(_manifest_get(manifest, "session", "duration_seconds"))
            is not None
            and float(_manifest_get(manifest, "session", "duration_seconds"))
            >= MANIFEST_MINIMUM_DURATION_SECONDS,
            "session.duration_seconds is at least 28800",
        ),
        "sample_interval_declared": _boolean_check(
            _finite_number(_manifest_get(manifest, "session", "sample_interval_seconds"))
            is not None
            and 0
            < float(_manifest_get(manifest, "session", "sample_interval_seconds"))
            <= 60,
            "session.sample_interval_seconds is in 1..60",
        ),
        "thermal_limit_declared": _boolean_check(
            _finite_number(_manifest_get(manifest, "thresholds", "thermal_limit_status"))
            is not None,
            "thresholds.thermal_limit_status is finite",
        ),
        "battery_drain_threshold_declared": _boolean_check(
            _finite_number(
                _manifest_get(manifest, "thresholds", "maximum_net_battery_drain_percent")
            )
            is not None,
            "thresholds.maximum_net_battery_drain_percent is finite",
        ),
        "battery_temperature_threshold_declared": _boolean_check(
            _finite_number(
                _manifest_get(manifest, "thresholds", "battery_temperature_limit_celsius")
            )
            is not None,
            "thresholds.battery_temperature_limit_celsius is finite",
        ),
    }
    artifacts = {
        name: _artifact_check(evidence_dir, candidates, require_non_empty, artifact_type)
        for name, candidates, require_non_empty, artifact_type in REQUIRED_EVIDENCE_ARTIFACTS
    }
    gate_owner_checks = _gate_owner_checks(manifest)
    reasons = [
        f"insufficient evidence package: manifest.{name}"
        for name, item in manifest_checks.items()
        if not item["passed"]
    ]
    reasons.extend(
        f"insufficient evidence package: gate_owner.{name}"
        for name, item in gate_owner_checks.items()
        if not item["passed"]
    )
    reasons.extend(
        f"insufficient evidence package: artifact.{name}"
        for name, item in artifacts.items()
        if not item["passed"]
    )
    passed = not reasons
    return {
        "passed": passed,
        "manifest_path": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "manifest_document": manifest,
        "manifest": manifest_checks,
        "gate_owners": gate_owner_checks,
        "artifacts": artifacts,
        "reasons": reasons,
    }


def _event_count(report: dict[str, Any], event: str) -> float | None:
    value = _get(report, "metrics", "telemetry", "event_counts", event)
    return 0.0 if value is None else _finite_number(value)


def _rss_criteria(
    report: dict[str, Any],
    section: str,
    maximum_slope: float,
    maximum_drift: float,
) -> dict[str, dict[str, Any]]:
    prefix = ("metrics", "memory_kib", section)
    slope = _finite_number(_get(report, *prefix, "slope_kib_per_minute", "second_half"))
    drift = _stats_drift(report, *prefix)
    return {
        f"{section}_second_half_slope_kib_per_minute": _criterion(
            slope, maximum_slope
        ),
        f"{section}_full_window_endpoint_drift_kib": _criterion(
            drift, maximum_drift
        ),
    }


def _validate_report(report: dict[str, Any]) -> str | None:
    if report.get("schema_version") != SCHEMA_VERSION:
        return f"report.schema_version must be {SCHEMA_VERSION}"
    if report.get("kind") != SOAK_REPORT_KIND:
        return f"report.kind must be {SOAK_REPORT_KIND}"
    if report.get("derivation_status") != "complete":
        return "report derivation_status is not complete"
    if _get(report, "source_summary", "status") != "complete":
        return "source soak summary is not complete"
    errors = report.get("errors", [])
    if errors != []:
        return "report carries derivation errors"
    source_errors = _get(report, "source_summary", "errors")
    if source_errors not in (None, []):
        return "source soak summary carries errors"
    return None


def derive_gate(
    report_path: Path,
    *,
    manifest_path: Path | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    report = _read_json(report_path, "exact-window report")
    validation_error = _validate_report(report)
    window = report.get("window") if isinstance(report.get("window"), dict) else {}
    source_summary = (
        report.get("source_summary")
        if isinstance(report.get("source_summary"), dict)
        else {}
    )
    run_id = report.get("run_id")
    evidence_package = None
    manifest_document = None
    if manifest_path is not None or evidence_dir is not None:
        resolved_evidence_dir = evidence_dir or (manifest_path.parent if manifest_path is not None else report_path.parent)
        resolved_manifest_path = manifest_path or (resolved_evidence_dir / PHASE2_MANIFEST_NAME)
        evidence_package = _evaluate_evidence_package(
            manifest_path=resolved_manifest_path,
            evidence_dir=resolved_evidence_dir,
        )
        manifest_document = evidence_package["manifest_document"]
    thresholds = _thresholds(manifest_document)

    sufficiency = {
        "duration": _minimum(
            _finite_number(window.get("duration_seconds")), MINIMUM_DURATION_SECONDS
        ),
        "sample_count": _minimum(
            _finite_number(window.get("sample_records_in_window")),
            MINIMUM_SAMPLE_COUNT,
        ),
        "telemetry_count": _minimum(
            _finite_number(window.get("telemetry_records_in_window")),
            MINIMUM_TELEMETRY_COUNT,
        ),
        "sample_gap": _criterion(
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
        "stream_stats_gap": _criterion(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "telemetry",
                    "stream_stats_gaps",
                    "maximum_window_gap_seconds",
                )
            ),
            MAXIMUM_STREAM_STATS_GAP_SECONDS,
        ),
        "heartbeat_gap": _criterion(
            _finite_number(
                _get(
                    report,
                    "metrics",
                    "telemetry",
                    "heartbeat_gaps",
                    "maximum_window_gap_seconds",
                )
            ),
            MAXIMUM_HEARTBEAT_GAP_SECONDS,
        ),
        "accepted_heartbeat_count": _minimum(
            _finite_number(
                _get(report, "metrics", "telemetry", "accepted_heartbeat_count")
            ),
            MINIMUM_TELEMETRY_COUNT,
        ),
        "client_memory_samples": _minimum(
            _stats_count(report, "metrics", "memory_kib", "client_total_pss"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "thermal_samples": _minimum(
            _stats_count(report, "metrics", "thermal", "status"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "battery_samples": _minimum(
            _stats_count(report, "metrics", "battery", "level_percent"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "battery_status_samples": _minimum(
            _stats_count(report, "metrics", "battery", "status"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "battery_plugged_samples": _minimum(
            _stats_count(report, "metrics", "battery", "plugged"),
            MINIMUM_SAMPLE_COUNT,
        ),
        "stream_fps_samples": _minimum(
            _stats_count(report, "metrics", "stream", "fps"),
            MINIMUM_TELEMETRY_COUNT,
        ),
    }

    criteria = {
        "session_disconnect_count": _criterion(
            _event_count(report, "session_disconnected"), MAXIMUM_RECONNECT_COUNT
        ),
        "stream_frame_queue_drop_total": _criterion(
            _finite_number(_get(report, "metrics", "stream", "frame_queue_drop_total")),
            MAXIMUM_QUEUE_DROP_TOTAL,
        ),
        "stream_reported_dropped_frames": _criterion(
            _finite_number(
                _get(report, "metrics", "stream", "reported_dropped_frames", "sum")
            ),
            MAXIMUM_DROPPED_FRAMES,
        ),
        "thermal_status_max": _criterion(
            _stats_max(report, "metrics", "thermal", "status"),
            float(thresholds["maximum_thermal_status"]),
        ),
        "battery_temperature_celsius_max": _criterion(
            _stats_max(report, "metrics", "battery", "temperature_celsius"),
            float(thresholds["maximum_battery_temperature_celsius"]),
        ),
        "stand_charging_non_charging_status_samples": _criterion(
            _non_charging_status_count(report),
            0.0,
        ),
        "stand_charging_unplugged_samples": _criterion(
            _plugged_count(report, 0),
            0.0,
        ),
        "net_battery_drain_percent": _criterion(
            _stats_negative_drift(report, "metrics", "battery", "level_percent"),
            float(thresholds["maximum_net_battery_drain_percent"]),
        ),
        **_rss_criteria(
            report,
            "client_total_pss",
            MAXIMUM_CLIENT_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
            MAXIMUM_CLIENT_RSS_SECOND_HALF_DRIFT_KIB,
        ),
        **_rss_criteria(
            report,
            "host_rss",
            MAXIMUM_HOST_RSS_SECOND_HALF_SLOPE_KIB_PER_MINUTE,
            MAXIMUM_HOST_RSS_SECOND_HALF_DRIFT_KIB,
        ),
    }

    reasons: list[str] = []
    if validation_error is not None:
        reasons.append(validation_error)
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

    if evidence_package is not None:
        reasons.extend(evidence_package["reasons"])
        evidence_package = dict(evidence_package)
        evidence_package.pop("manifest_document", None)

    if (
        validation_error is not None
        or any(not item["passed"] for item in sufficiency.values())
        or missing_criteria
        or (evidence_package is not None and not evidence_package["passed"])
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
        "run_id": run_id,
        "window": {
            "started_at": window.get("started_at"),
            "finished_at": window.get("finished_at"),
            "duration_seconds": window.get("duration_seconds"),
            "sample_records_in_window": window.get("sample_records_in_window"),
            "telemetry_records_in_window": window.get("telemetry_records_in_window"),
        },
        "source_summary": {
            "status": source_summary.get("status"),
            "error_count": len(source_summary.get("errors", []))
            if isinstance(source_summary.get("errors", []), list)
            else None,
        },
        "thresholds": thresholds,
        "sufficiency": sufficiency,
        "criteria": criteria,
        "evidence_package": evidence_package,
        "reasons": reasons,
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
        "thresholds": _thresholds(),
        "sufficiency": {},
        "criteria": {},
        "evidence_package": None,
        "reasons": ["the Phase 2 tablet gate inputs could not be validated"],
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
    parser.add_argument("--report", type=Path, required=True, help="exact-window soak report JSON")
    parser.add_argument("--manifest", type=Path, help="Phase 2 tablet manifest JSON")
    parser.add_argument("--evidence-dir", type=Path, help="Phase 2 evidence package root")
    parser.add_argument("--output", type=Path, required=True, help="Phase 2 gate JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_gate(
            arguments.report,
            manifest_path=arguments.manifest,
            evidence_dir=arguments.evidence_dir,
        )
        _write_json(arguments.output, report)
    except (EvidenceInputError, OSError, TypeError, ValueError):
        report = _failure_report()
        try:
            _write_json(arguments.output, report)
        except (OSError, TypeError, ValueError):
            print("error: Phase 2 tablet gate output could not be written", file=sys.stderr)
            return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
