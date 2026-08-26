"""Summarize iOS hardware VideoToolbox readiness evidence.

The Phase 5 README gate is intentionally hardware-scoped: simulator runs and
unsigned archives can prove buildability, but they cannot prove iPhone/iPad
VideoToolbox behavior. This helper owns the fail-closed evidence shape for that
gate without running or claiming a device acceptance pass.
"""

from __future__ import annotations

import argparse
import json
import re
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
INVALID_ARTIFACT_MARKERS = (
    "android",
    "mediacodec",
    "simulator",
    "iphonesimulator",
    "unsigned",
    "ad-hoc",
    "adhoc",
    "synthetic",
)
REQUIRED_ARTIFACT_CATEGORIES = {
    "videotoolbox": ("videotoolbox", "vt"),
    "h264": ("h264", "h.264"),
    "hevc": ("hevc", "h265", "h.265"),
    "frames": ("frame", "cvpixelbuffer", "pixelbuffer"),
    "telemetry": ("telemetry", "epoch", "thermal", "power"),
}
SENSITIVE_PATH_PATTERNS = (
    re.compile(r"(?:^|/)Users/[^/\s]+", re.IGNORECASE),
    re.compile(r"(?:^|/)home/[^/\s]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    re.compile(r"^(?:~|\$HOME)(?:/|\\)", re.IGNORECASE),
    re.compile(r"Application Support/com\.apple\.TCC", re.IGNORECASE),
)
SENSITIVE_TEXT_PATTERNS = (
    *SENSITIVE_PATH_PATTERNS,
    re.compile(r"\b" + "TCC" + r"\.db\b", re.IGNORECASE),
    re.compile(r"\b(?:credential|credentials|password|passwd|token|tokens|secret|secrets)\b", re.IGNORECASE),
    re.compile(r"\b(?:private|secret)[_-]?key(?:\b|[_\-.])", re.IGNORECASE),
    re.compile(r"\b(?:api|access|refresh|session)[_-]?(?:key|token|secret|id)(?:\b|[_\-.])", re.IGNORECASE),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_]{8,}", re.IGNORECASE),
)

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


def _reject_sensitive_text(value: str, field: str) -> None:
    if any(pattern.search(value) for pattern in SENSITIVE_TEXT_PATTERNS):
        raise IOSVideoToolboxReadinessError(
            f"{field} must contain sanitized public evidence text"
        )


def _public_string_list(record: dict[str, Any], field: str) -> list[str]:
    values = _string_list(record, field)
    for value in values:
        if field == "artifact_paths" and Path(value).is_absolute():
            raise IOSVideoToolboxReadinessError(
                "artifact_paths must contain relative sanitized paths"
            )
        _reject_sensitive_text(value, field)
    return values


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _artifact_checks(
    artifact_paths: Sequence[str], evidence_dir: Path | None
) -> tuple[list[dict[str, Any]], bool]:
    if not artifact_paths:
        return [], False

    if evidence_dir is None:
        return [
            {
                "path": artifact,
                "exists": False,
                "non_empty": False,
                "under_evidence_dir": False,
                "valid_ios_videotoolbox_source": False,
            }
            for artifact in artifact_paths
        ], False

    root = evidence_dir.resolve()
    checks: list[dict[str, Any]] = []
    categories = {category: False for category in REQUIRED_ARTIFACT_CATEGORIES}
    for artifact in artifact_paths:
        raw_path = Path(artifact)
        artifact_path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = artifact_path.resolve(strict=False)
        exists = resolved.is_file()
        under_evidence_dir = _is_relative_to(resolved, root)
        non_empty = exists and resolved.stat().st_size > 0
        normalized = artifact.lower()
        valid_source = not any(marker in normalized for marker in INVALID_ARTIFACT_MARKERS)
        for category, markers in REQUIRED_ARTIFACT_CATEGORIES.items():
            if non_empty and under_evidence_dir and valid_source and any(
                marker in normalized for marker in markers
            ):
                categories[category] = True
        checks.append(
            {
                "path": artifact,
                "exists": exists,
                "non_empty": non_empty,
                "under_evidence_dir": under_evidence_dir,
                "valid_ios_videotoolbox_source": valid_source,
            }
        )
    return checks, all(categories.values())


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        _reject_sensitive_text(value, field)
        return value
    raise IOSVideoToolboxReadinessError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        _reject_sensitive_text(value, "run_id")
        return value
    raise IOSVideoToolboxReadinessError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        _reject_sensitive_text(value, "run_id")
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


def summarize(
    record: dict[str, Any], *, run_id: str | None = None, evidence_dir: Path | None = None
) -> dict[str, Any]:
    runtime_class = _runtime_class(record)
    artifact_paths = _public_string_list(record, "artifact_paths")
    artifact_checks, retained_artifacts_available = _artifact_checks(
        artifact_paths, evidence_dir
    )
    blocking_notes = _public_string_list(record, "blocking_notes")
    notes = _string_value(record, "notes")
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    if field_values["artifacts_retained"] and not artifact_paths:
        missing.append(
            {
                "field": "artifact_paths",
                "requirement": "retain at least one sanitized relative artifact path for reviewer inspection",
            }
        )
    if field_values["artifacts_retained"] and artifact_paths and not retained_artifacts_available:
        missing.append(
            {
                "field": "artifact_paths",
                "requirement": (
                    "retain existing non-empty iOS VideoToolbox artifacts under the evidence directory "
                    "covering H.264, HEVC, output frames, and stream/thermal telemetry"
                ),
            }
        )
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
        "artifact_paths": artifact_paths,
        "artifact_checks": artifact_checks,
        "blocking_notes": blocking_notes,
        "notes": notes,
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
    parser.add_argument(
        "--evidence-dir",
        help="directory that must contain retained artifact_paths before the gate can pass",
    )
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="return nonzero unless the summary can close the device-family VideoToolbox gate",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(args.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        evidence_dir = Path(args.evidence_dir) if args.evidence_dir else None
        summary = summarize(record, run_id=args.run_id, evidence_dir=evidence_dir)
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
    if args.require_pass and not summary["can_close_device_family_videotoolbox_gate"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
