"""Summarize iOS hardware VideoToolbox readiness evidence.

The Phase 5 README gate is intentionally hardware-scoped: simulator runs and
unsigned archives can prove buildability, but they cannot prove iPhone/iPad
VideoToolbox behavior. This helper owns the fail-closed evidence shape for that
gate without running or claiming a device acceptance pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "ios-hardware-videotoolbox-readiness"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"

RUNTIME_SIMULATOR = "simulator"
RUNTIME_UNSIGNED_ARCHIVE = "unsigned_archive"
RUNTIME_PHYSICAL_IPHONE = "physical_iphone"
RUNTIME_PHYSICAL_IPAD = "physical_ipad"
RUNTIME_CLASSES = {
    RUNTIME_SIMULATOR,
    RUNTIME_UNSIGNED_ARCHIVE,
    RUNTIME_PHYSICAL_IPHONE,
    RUNTIME_PHYSICAL_IPAD,
}
PHYSICAL_RUNTIME_CLASSES = {RUNTIME_PHYSICAL_IPHONE, RUNTIME_PHYSICAL_IPAD}

REQUIRED_FIELDS = (
    ("signed_app_installed", "install an Apple-signed build on the recorded iOS device"),
    (
        "physical_ios_device_identity_recorded",
        "record real iPhone/iPad hardware model, OS version, build number, and power state",
    ),
    (
        "device_family_matches_runtime_class",
        "label the run as physical_iphone or physical_ipad to match the actual device family",
    ),
    ("h264_parameter_sets_recorded", "retain H.264 SPS/PPS evidence for the decoded stream"),
    ("hevc_parameter_sets_recorded", "retain HEVC VPS/SPS/PPS evidence for the decoded stream"),
    ("videotoolbox_h264_session_created", "create a VideoToolbox H.264 decompression session on device"),
    ("videotoolbox_hevc_session_created", "create a VideoToolbox HEVC decompression session on device"),
    ("h264_output_frames_observed", "observe H.264 output CVPixelBuffers on the physical device"),
    ("hevc_output_frames_observed", "observe HEVC output CVPixelBuffers on the physical device"),
    (
        "hardware_decode_path_recorded",
        "retain platform evidence that the physical device used the hardware-capable VideoToolbox path",
    ),
    ("stream_epoch_telemetry_recorded", "record stream/config epochs, frame IDs, drops, and decoder errors"),
    ("thermal_and_power_recorded", "record thermal state, battery level, and low-power mode"),
    ("artifacts_retained", "retain sanitized logs or structured artifacts referenced by this summary"),
)

BLOCKING_FIELDS = {
    "signed_app_installed",
    "physical_ios_device_identity_recorded",
    "device_family_matches_runtime_class",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)


class IOSVideoToolboxReadinessError(ValueError):
    """Raised when an iOS VideoToolbox readiness record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise IOSVideoToolboxReadinessError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise IOSVideoToolboxReadinessError(
            "iOS VideoToolbox readiness evidence must be a JSON object"
        )
    return record


def _runtime_class(record: dict[str, Any]) -> str:
    value = record.get("runtime_class", "")
    if not isinstance(value, str) or value not in RUNTIME_CLASSES:
        raise IOSVideoToolboxReadinessError(
            "runtime_class must be simulator, unsigned_archive, physical_iphone, or physical_ipad"
        )
    return value


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise IOSVideoToolboxReadinessError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IOSVideoToolboxReadinessError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise IOSVideoToolboxReadinessError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise IOSVideoToolboxReadinessError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSVideoToolboxReadinessError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSVideoToolboxReadinessError("run_id must be a non-empty string")


def _runtime_blocking_reason(runtime_class: str) -> list[dict[str, str]]:
    if runtime_class in PHYSICAL_RUNTIME_CLASSES:
        return []
    if runtime_class == RUNTIME_SIMULATOR:
        requirement = "run on real iPhone or iPad hardware; Simulator VideoToolbox behavior is not device evidence"
    else:
        requirement = "install and launch a signed app on real iPhone or iPad hardware; an unsigned archive is build evidence only"
    return [{"field": "runtime_class", "requirement": requirement}]


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    runtime_class = _runtime_class(record)
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = _runtime_blocking_reason(runtime_class) + [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]

    if runtime_class in PHYSICAL_RUNTIME_CLASSES and not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": "ios_hardware_videotoolbox_readiness",
        "profile": GATE_PROFILE,
        "runtime_class": runtime_class,
        "verdict": verdict,
        "can_close_device_family_videotoolbox_gate": verdict == STATUS_PASS,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "requires_physical_ios_device": True,
        "simulator_is_not_device_evidence": True,
        "unsigned_archive_is_not_device_evidence": True,
        "android_evidence_is_not_ios_evidence": True,
        "phase5_gate_closure_rule": (
            "Collect passing summaries for both physical_iphone and physical_ipad, then review "
            "them with the broader iOS device-acceptance evidence before closing README Phase 5."
        ),
        "observations": field_values,
        "missing_requirements": missing,
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
        description="Summarize Vibe Screen iOS hardware VideoToolbox readiness evidence.",
        epilog=(
            "Input is a JSON object with runtime_class plus explicit boolean observations. "
            "Simulator and unsigned archive records are blocked by construction so build "
            "evidence cannot accidentally close the hardware gate."
        ),
    )
    parser.add_argument(
        "input", help="iOS VideoToolbox readiness observations .json file, or - for stdin"
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
    except (IOSVideoToolboxReadinessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
