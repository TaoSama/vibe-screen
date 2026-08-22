"""Summarize macOS Host hardware compatibility matrix-row evidence.

The gate validates an already-collected evidence summary. It does not launch the
Host, change macOS display settings, touch TCC, or infer support for hardware
or OS rows that were not explicitly recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "macos-host-compatibility-row"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAILED = "failed"
CPU_ARCHITECTURES = frozenset(("apple_silicon", "intel"))
DISPLAY_TOPOLOGIES = frozenset((
    "built_in",
    "single_external",
    "multi_display",
    "dummy_or_headless",
    "screen_sharing",
))

REQUIRED_FIELDS = (
    ("owner_recorded", "record the macOS Host compatibility gate owner for this row"),
    ("implementation_path_recorded", "record the implementation path or follow-up path for this matrix row"),
    ("repository_commit_recorded", "record the repository commit and dirty state used for the run"),
    ("host_model_recorded", "record the exact Mac model identifier and marketing family when available"),
    ("cpu_architecture_recorded", "record whether the Host is Apple silicon or Intel"),
    ("macos_version_build_recorded", "record macOS product version and build number"),
    ("xcode_swift_recorded", "record Xcode and Swift versions used for local build/test evidence"),
    ("host_build_identity_recorded", "record Host app commit, binary SHA-256, bundle id, and signing identity"),
    ("signing_and_tcc_state_recorded", "record signing stability plus Screen Recording and Accessibility state"),
    ("display_topology_recorded", "record built-in, external, multi-display, dummy/headless, or Screen Sharing topology"),
    ("capture_backend_recorded", "record ScreenCaptureKit, CGDisplayStream fallback, or explicit unavailable result"),
    ("video_encoder_path_recorded", "record VideoToolbox H.264/HEVC capability or explicit unavailable result"),
    ("automated_macos_checks_passed", "run baseline macOS build, XCTest, and self-test commands for this source"),
    ("packaged_host_launch_observed", "launch the packaged Host on the recorded Mac row"),
    ("protocol_v1_stream_observed", "observe a Protocol v1 USB or trusted-LAN stream on this Host row"),
    ("display_selection_observed", "exercise display list and selected-display start on this Host row"),
    ("physical_display_capture_observed", "observe physical or current-main display capture on this Host row"),
    ("virtual_display_or_fallback_recorded", "record private virtual-display create/capture success or explicit fallback/unavailable behavior"),
    ("mirror_or_fallback_recorded", "record mirror success or explicit current-main fallback/unavailable behavior"),
    ("input_smoke_observed", "observe at least touch plus keyboard or scroll input through the Host path"),
    ("reconnect_observed", "observe a client/process reconnect while the Host PID survives"),
    ("artifacts_retained", "retain logs, screenshots, display snapshots, command output, and the gate summary"),
    ("claim_scoped_to_exact_row", "scope the support claim to this exact architecture, Mac model, OS build, topology, transport, and Android counterpart"),
)

BLOCKING_FIELDS = frozenset((
    "owner_recorded",
    "implementation_path_recorded",
    "host_model_recorded",
    "cpu_architecture_recorded",
    "macos_version_build_recorded",
    "display_topology_recorded",
    "automated_macos_checks_passed",
    "packaged_host_launch_observed",
    "protocol_v1_stream_observed",
    "artifacts_retained",
    "claim_scoped_to_exact_row",
))

INVALID_CLAIM_FIELDS = (
    ("ci_runner_only", "CI runner build/test output cannot close a real Host hardware compatibility row"),
    ("claims_intel_from_apple_silicon", "Intel compatibility cannot be inferred from Apple silicon evidence"),
    ("claims_os_range_from_single_build", "a single macOS build cannot prove the whole macOS 13+ range"),
    ("claims_display_topology_from_different_setup", "display topology claims cannot be inferred from another monitor/dummy/headless setup"),
    ("claims_virtual_display_without_result", "private virtual-display support needs a success result or explicit fallback/unavailable result"),
)

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
INVALID_BOOLEAN_FIELDS = tuple(field for field, _ in INVALID_CLAIM_FIELDS)
REQUIRED_METADATA_FIELDS = (
    ("owner", "owner_recorded", "record a non-empty macOS Host compatibility gate owner"),
    ("implementation_path", "implementation_path_recorded", "record a non-empty implementation path or follow-up path"),
    ("host_model_identifier", "host_model_recorded", "record a non-empty Mac model identifier"),
    ("cpu_architecture", "cpu_architecture_recorded", "record apple_silicon or intel CPU architecture"),
    ("macos_version", "macos_version_build_recorded", "record a non-empty macOS product version"),
    ("macos_build", "macos_version_build_recorded", "record a non-empty macOS build number"),
    ("xcode_version", "xcode_swift_recorded", "record a non-empty Xcode version"),
    ("swift_version", "xcode_swift_recorded", "record a non-empty Swift version"),
    ("host_build_identity", "host_build_identity_recorded", "record a non-empty Host build identity"),
    ("display_topology", "display_topology_recorded", "record a concrete display topology"),
    ("capture_backend", "capture_backend_recorded", "record a non-empty capture backend or unavailable result"),
    ("stream_transport", "protocol_v1_stream_observed", "record a non-empty stream transport"),
    ("android_counterpart", "protocol_v1_stream_observed", "record the Android counterpart used for the stream"),
    ("compatibility_scope", "claim_scoped_to_exact_row", "record a non-empty exact-row compatibility scope"),
)


class MacOSHardwareCompatibilityError(ValueError):
    """Raised when a compatibility evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise MacOSHardwareCompatibilityError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise MacOSHardwareCompatibilityError(
            "macOS hardware compatibility evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise MacOSHardwareCompatibilityError(f"{field} must be true or false")


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise MacOSHardwareCompatibilityError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise MacOSHardwareCompatibilityError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip():
        return value
    raise MacOSHardwareCompatibilityError("run_id must be a non-empty string")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MacOSHardwareCompatibilityError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise MacOSHardwareCompatibilityError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _cpu_architecture(record: dict[str, Any]) -> str:
    value = _string_value(record, "cpu_architecture")
    if value and value not in CPU_ARCHITECTURES:
        raise MacOSHardwareCompatibilityError(
            f"cpu_architecture must be one of {sorted(CPU_ARCHITECTURES)}"
        )
    return value


def _display_topology(record: dict[str, Any]) -> str:
    value = _string_value(record, "display_topology")
    if value and value not in DISPLAY_TOPOLOGIES:
        raise MacOSHardwareCompatibilityError(
            f"display_topology must be one of {sorted(DISPLAY_TOPOLOGIES)}"
        )
    return value


def _append_missing_once(
    missing: list[dict[str, str]], field: str, requirement: str
) -> None:
    if not any(item["field"] == field for item in missing):
        missing.append({"field": field, "requirement": requirement})


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    invalid_claim_values = {
        field: _bool_value(record, field) for field in INVALID_BOOLEAN_FIELDS
    }
    artifact_paths = _string_list(record, "artifact_paths")
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    for metadata_field, observation_field, requirement in REQUIRED_METADATA_FIELDS:
        if not _string_value(record, metadata_field).strip():
            _append_missing_once(missing, observation_field, requirement)
    if field_values["artifacts_retained"] and not artifact_paths:
        _append_missing_once(
            missing,
            "artifacts_retained",
            "record at least one retained artifact path for this compatibility row",
        )
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    invalid_claims = [
        {"field": field, "reason": reason}
        for field, reason in INVALID_CLAIM_FIELDS
        if invalid_claim_values[field]
    ]

    if invalid_claims:
        verdict = STATUS_FAILED
    elif not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "macos_host_compatibility_matrix_row",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_macos_host_compatibility_row": verdict == STATUS_PASS,
        "row_scope": {
            "owner": _string_value(record, "owner"),
            "implementation_path": _string_value(record, "implementation_path"),
            "cpu_architecture": _cpu_architecture(record),
            "host_model_identifier": _string_value(record, "host_model_identifier"),
            "host_cpu_name": _string_value(record, "host_cpu_name"),
            "macos_version": _string_value(record, "macos_version"),
            "macos_build": _string_value(record, "macos_build"),
            "xcode_version": _string_value(record, "xcode_version"),
            "swift_version": _string_value(record, "swift_version"),
            "host_build_identity": _string_value(record, "host_build_identity"),
            "display_topology": _display_topology(record),
            "capture_backend": _string_value(record, "capture_backend"),
            "stream_transport": _string_value(record, "stream_transport"),
            "android_counterpart": _string_value(record, "android_counterpart"),
            "compatibility_scope": _string_value(record, "compatibility_scope"),
        },
        "observations": field_values,
        "invalid_claims": invalid_claims,
        "invalid_claim_observations": invalid_claim_values,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": artifact_paths,
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }
    return summary


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize one Vibe Screen macOS Host compatibility matrix row.",
        epilog=(
            "Missing booleans default to false. A passing row is scoped only to "
            "the exact Mac architecture, model, macOS build, display topology, "
            "transport, and Android counterpart recorded in the input."
        ),
    )
    parser.add_argument("input", help="macOS compatibility evidence .json file, or - for stdin")
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
    except (MacOSHardwareCompatibilityError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
