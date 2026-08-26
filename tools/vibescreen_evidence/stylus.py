"""Summarize physical stylus drawing-app acceptance evidence.

The physical stylus gate closes only when a real Android stylus drives the
production Protocol v1 path into the macOS Host and the retained evidence proves
both same-session forwarding/injection logs plus a visible drawing-app result.
Capability snapshots from ``dumpsys input`` are readiness evidence only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "physical-stylus-drawing-app"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
EXIT_STATUS_BY_VERDICT = {
    STATUS_PASS: 0,
    STATUS_BLOCKED: 2,
    STATUS_INSUFFICIENT: 1,
}

REQUIRED_FIELDS = (
    (
        "adb_was_run",
        "run the collector against the named Android device unless blocked by a shared device lock",
    ),
    (
        "device_identity_recorded",
        "record Android manufacturer, model, codename, release, and SDK for the exact device under test",
    ),
    (
        "device_identity_matches_claim",
        "label the evidence with the observed device identity, without relabeling P0110/pacific as Xiaomi/fuxi",
    ),
    (
        "pass_eligible_stylus_capability",
        "record an Android input device with STYLUS source plus pressure and tilt axes",
    ),
    (
        "physical_drawing_observed",
        "observe a real physical stylus contacting the Android device during the active Protocol v1 session",
    ),
    (
        "android_stylus_forwarding_observed",
        "retain same-session Android diagnostic logs with Stylus forwarded samples from a stylus or eraser tool",
    ),
    (
        "host_stylus_injection_observed",
        "retain newly appended Host Stylus injected logs with contact, pressure, and signed two-axis tilt",
    ),
    (
        "host_stable_signed_tcc_ready",
        "run a stable signed Host with Screen Recording and Accessibility permission ready",
    ),
    (
        "visible_drawing_result_observed",
        "record the visible macOS drawing-app result of the physical stylus stroke",
    ),
    (
        "android_diag_log_retained",
        "retain the bounded Android diagnostic log window for the drawing attempt",
    ),
    (
        "host_log_window_retained",
        "retain the newly appended Host log observation window for the drawing attempt",
    ),
    (
        "collector_reported_passed",
        "use a collector result whose own status is pass, not blocked or failed",
    ),
)

BLOCKING_FIELDS = {
    "adb_was_run",
    "device_identity_recorded",
    "pass_eligible_stylus_capability",
    "physical_drawing_observed",
    "host_stable_signed_tcc_ready",
}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)

CONSISTENCY_RULES = (
    (
        "android_stylus_forwarding_observed",
        ("pass_eligible_stylus_capability", "physical_drawing_observed"),
        "Android stylus forwarding evidence requires a pass-eligible stylus source and physical drawing observation",
    ),
    (
        "host_stylus_injection_observed",
        ("android_stylus_forwarding_observed", "host_stable_signed_tcc_ready"),
        "Host stylus injection evidence must be paired with same-session Android stylus forwarding and stable signed/TCC-ready Host evidence",
    ),
    (
        "visible_drawing_result_observed",
        ("host_stylus_injection_observed", "physical_drawing_observed"),
        "Visible macOS drawing-app evidence requires Host stylus injection and physical drawing observation",
    ),
    (
        "collector_reported_passed",
        (
            "physical_drawing_observed",
            "android_stylus_forwarding_observed",
            "host_stylus_injection_observed",
            "visible_drawing_result_observed",
        ),
        "Collector pass requires physical drawing, Android forwarding, Host injection, and visible drawing output",
    ),
)


class StylusEvidenceError(ValueError):
    """Raised when a physical stylus evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise StylusEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise StylusEvidenceError("stylus evidence must be a JSON object")
    return record


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise StylusEvidenceError(f"{field} must be a string")


def _optional_string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise StylusEvidenceError(f"{field} must be a string or null")


def _integer_value(record: dict[str, Any], field: str) -> int:
    value = record.get(field, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise StylusEvidenceError(f"{field} must be an integer")


def _boolean_value(record: dict[str, Any], field: str, default: bool) -> bool:
    value = record.get(field, default)
    if isinstance(value, bool):
        return value
    raise StylusEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StylusEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise StylusEvidenceError(f"{field} must contain only non-empty strings")
    return value


def _dict_list(record: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise StylusEvidenceError(f"{field} must be a list of objects")
    return value


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise StylusEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise StylusEvidenceError("run_id must be a non-empty string")


def _device_identity_recorded(record: dict[str, Any]) -> bool:
    device = record.get("device_identity")
    if not isinstance(device, dict):
        return False
    for field in ("manufacturer", "model", "device", "os_release", "api_level"):
        value = device.get(field)
        if not isinstance(value, str) or not value.strip() or value.startswith("not collected"):
            return False
    return True


def _device_identity_matches_claim(record: dict[str, Any]) -> bool:
    device = record.get("device_identity")
    if not isinstance(device, dict):
        return False
    manufacturer = str(device.get("manufacturer", "")).strip().lower()
    model = str(device.get("model", "")).strip().lower()
    codename = str(device.get("device", "")).strip().lower()
    release = str(device.get("os_release", "")).strip()
    api_level = str(device.get("api_level", "")).strip()
    if not all((manufacturer, model, codename, release, api_level)):
        return False
    return (manufacturer, model, codename, release, api_level) == (
        "nubia",
        "p0110",
        "pacific",
        "16",
        "36",
    )


def _candidate_sources(candidate: dict[str, Any]) -> set[str]:
    value = candidate.get("sources")
    if isinstance(value, str):
        tokens = value.replace(",", "|").split("|")
    elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        tokens = value
    else:
        return set()
    return {token.strip().upper() for token in tokens if token.strip()}


def _candidate_axes(candidate: dict[str, Any]) -> set[str]:
    value = candidate.get("axes")
    if isinstance(value, str):
        tokens = value.replace(",", "|").split("|")
    elif isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        tokens = value
    else:
        return set()
    return {token.strip().upper() for token in tokens if token.strip()}


def _has_pass_eligible_stylus(record: dict[str, Any]) -> bool:
    for candidate in _dict_list(record, "pass_eligible_stylus_candidates"):
        if "STYLUS" in _candidate_sources(candidate) and {"PRESSURE", "TILT"}.issubset(
            _candidate_axes(candidate)
        ):
            return True
    for candidate in _dict_list(record, "stylus_candidates"):
        if "STYLUS" in _candidate_sources(candidate) and {"PRESSURE", "TILT"}.issubset(
            _candidate_axes(candidate)
        ):
            return True
    return False


def _artifact_paths(record: dict[str, Any], source_path: Path | None) -> list[str]:
    explicit = record.get("artifact_paths")
    if explicit is not None:
        return _string_list(record, "artifact_paths")
    paths: list[str] = []
    if source_path is not None and str(source_path) != "-":
        paths.append(source_path.name)
    paths.append("dumpsys-input.txt")
    if _optional_string_value(record, "diag_log_read_error") == "":
        paths.append("android-diag.log")
    if _integer_value(record, "host_log_appended_bytes") > 0:
        paths.append("host-stylus.log")
    return sorted(dict.fromkeys(paths))


def _lock_notes(record: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for lock in _dict_list(record, "existing_locks"):
        path = lock.get("path")
        detail = lock.get("detail") or lock.get("read_error") or "present"
        if isinstance(path, str) and path.strip():
            notes.append(f"{path}: {detail}")
    return notes


def _observations(record: dict[str, Any]) -> dict[str, bool]:
    status = _string_value(record, "status")
    observed = _boolean_value(record, "observed_physical_drawing", False)
    diag_error = _optional_string_value(record, "diag_log_read_error")
    diag_retained = diag_error == ""
    host_bytes = _integer_value(record, "host_log_appended_bytes")
    return {
        "adb_was_run": status != "blocked_device_coordination_lock",
        "device_identity_recorded": _device_identity_recorded(record),
        "device_identity_matches_claim": _device_identity_matches_claim(record),
        "pass_eligible_stylus_capability": _has_pass_eligible_stylus(record),
        "physical_drawing_observed": observed,
        "android_stylus_forwarding_observed": status == "pass" and diag_retained,
        "host_stylus_injection_observed": status == "pass" and host_bytes > 0,
        "host_stable_signed_tcc_ready": _boolean_value(record, "host_stable_signed_tcc_ready", False),
        "visible_drawing_result_observed": bool(_string_value(record, "drawing_observation").strip()),
        "android_diag_log_retained": diag_retained,
        "host_log_window_retained": host_bytes > 0,
        "collector_reported_passed": status == "pass",
    }


def _inconsistent_observations(field_values: dict[str, bool]) -> list[dict[str, Any]]:
    inconsistencies: list[dict[str, Any]] = []
    for observed_field, prerequisites, requirement in CONSISTENCY_RULES:
        if not field_values[observed_field]:
            continue
        missing_prerequisites = [field for field in prerequisites if not field_values[field]]
        if missing_prerequisites:
            inconsistencies.append(
                {
                    "field": observed_field,
                    "requires": missing_prerequisites,
                    "requirement": requirement,
                }
            )
    return inconsistencies


def summarize(
    record: dict[str, Any],
    *,
    run_id: str | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    field_values = _observations(record)
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [item for item in missing if item["field"] in BLOCKING_FIELDS]
    inconsistencies = _inconsistent_observations(field_values)
    if not missing and not inconsistencies:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    blocking_notes = _string_list(record, "blocking_notes") + _lock_notes(record)
    status = _string_value(record, "status")
    if verdict == STATUS_BLOCKED and status:
        blocking_notes.append(f"collector_status={status}")

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": "physical_stylus_drawing_app",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_physical_stylus_gate": verdict == STATUS_PASS,
        "requires_physical_stylus": True,
        "synthetic_adb_stylus_is_not_physical_stylus_evidence": True,
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16 "
            "evidence must not be relabeled as Xiaomi 13/fuxi."
        ),
        "collector_status": status or "unknown",
        "observations": field_values,
        "missing_requirements": missing,
        "inconsistent_observations": inconsistencies,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _artifact_paths(record, source_path),
        "blocking_notes": blocking_notes,
        "notes": _string_value(record, "notes"),
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen physical stylus drawing-app evidence.",
        epilog=(
            "Input is a stylus-evidence.json object from scripts/android_stylus_acceptance.py. "
            "Capability-only, synthetic, lock-blocked, or log-incomplete records cannot close the gate."
        ),
    )
    parser.add_argument("input", help="stylus evidence .json file, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit nonzero unless can_close_physical_stylus_gate is true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_path = None if args.input == "-" else Path(args.input)
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with source_path.open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        summary = summarize(record, run_id=args.run_id, source_path=source_path)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (StylusEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.require_pass and not summary["can_close_physical_stylus_gate"]:
        return 1
    return EXIT_STATUS_BY_VERDICT[summary["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
