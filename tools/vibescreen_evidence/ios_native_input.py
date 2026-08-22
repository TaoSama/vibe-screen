"""Summarize iOS native-input behavior evidence without overstating it.

This gate is owned by the Phase 5 iOS native-input behavior track. It can only
close when a signed iPhone or iPad app drives the production touch, keyboard,
and hover/pointer paths against a Host session and retained logs prove the
targeted input reached the selected display stream.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_OWNER = "phase5-ios-native-input-behavior"
GATE_PROFILE = "ios-native-input-behavior"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAIL = "fail"

REQUIRED_FIELDS = (
    ("ios_device_lock_acquired", "exclusively reserve the iPhone or iPad used for this run"),
    ("device_identity_recorded", "record iPhone or iPad model, OS/build, and device family"),
    ("device_is_iphone_or_ipad", "run on real iPhone or iPad hardware, not Simulator"),
    ("app_revision_recorded", "record the iOS app source revision and dirty-tree state"),
    ("signed_app_installed", "install a signed app build on the recorded iOS device"),
    ("local_network_permission_recorded", "record the Local Network permission result"),
    ("baseline_machost_listener_observed", "record the baseline MacHost listener and build identity"),
    ("protocol_session_negotiated", "capture SSWA/SSWR, upgrade, Hello, SessionAccepted, and display start"),
    ("input_capabilities_negotiated", "negotiate touch, keyboard, pointer, and USB HID modifier-byte capabilities as applicable"),
    ("display_stream_binding_recorded", "record the selected display ID and stream ID used by input events"),
    ("touch_tap_observed", "observe a real touch tap forwarded from the iOS app"),
    ("touch_drag_observed", "observe a real touch drag forwarded from the iOS app"),
    ("hardware_keyboard_attached", "attach and identify a physical iOS hardware keyboard"),
    ("keyboard_press_release_observed", "prove key-down and key-up forwarding for the same USB HID usage"),
    ("keyboard_modifier_observed", "prove a modifier or shortcut uses the negotiated USB HID modifier byte"),
    ("keyboard_modifier_release_no_leak_observed", "prove modifiers clear after release and do not leak into a later plain key"),
    ("hover_pointer_accessory_attached", "attach and identify a real iOS hover/pointer accessory"),
    ("hover_pointer_move_observed", "observe hover or pointer movement over the selected stream"),
    ("host_input_acknowledgements_retained", "retain Host-side acknowledgements or logs for every input family"),
    ("ios_logs_retained", "retain sanitized iOS app/device logs for the input workflow"),
    ("host_logs_retained", "retain sanitized Host logs for the input workflow"),
)

BLOCKING_FIELDS = {
    "ios_device_lock_acquired",
    "device_identity_recorded",
    "device_is_iphone_or_ipad",
    "signed_app_installed",
    "baseline_machost_listener_observed",
    "hardware_keyboard_attached",
    "hover_pointer_accessory_attached",
}

DISALLOWED_EVIDENCE_FIELDS = {
    "android_evidence_used_for_ios_input": "Android evidence cannot close iOS native-input behavior",
    "simulator_evidence_used_for_ios_input": "Simulator evidence cannot close real iOS native-input behavior",
    "offline_tests_used_as_device_evidence": "offline tests are readiness evidence only, not device behavior",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS) + tuple(
    DISALLOWED_EVIDENCE_FIELDS
)


class IOSNativeInputEvidenceError(ValueError):
    """Raised when an iOS native-input evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise IOSNativeInputEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise IOSNativeInputEvidenceError(
            "iOS native-input evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise IOSNativeInputEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IOSNativeInputEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise IOSNativeInputEvidenceError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise IOSNativeInputEvidenceError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSNativeInputEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSNativeInputEvidenceError("run_id must be a non-empty string")


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    observations = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not observations[field]
    ]
    disallowed_evidence = [
        {"field": field, "reason": reason}
        for field, reason in DISALLOWED_EVIDENCE_FIELDS.items()
        if observations[field]
    ]
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]

    if disallowed_evidence:
        verdict = STATUS_FAIL
    elif not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "ios_native_input_behavior",
        "profile": GATE_PROFILE,
        "gate_owner": GATE_OWNER,
        "verdict": verdict,
        "can_close_ios_native_input_gate": verdict == STATUS_PASS,
        "requires_real_ios_device": True,
        "requires_signed_app": True,
        "requires_physical_keyboard": True,
        "requires_hover_or_pointer_accessory": True,
        "android_evidence_is_not_ios_input_evidence": True,
        "simulator_is_not_ios_input_evidence": True,
        "offline_tests_are_readiness_only": True,
        "observations": observations,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "disallowed_evidence": disallowed_evidence,
        "artifact_paths": _string_list(record, "artifact_paths"),
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen iOS native-input behavior evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing "
            "booleans default to false so absent iOS hardware, signed install, "
            "physical accessory, or Host acknowledgement evidence cannot close "
            "the gate."
        ),
    )
    parser.add_argument(
        "input", help="iOS native-input observations .json file, or - for stdin"
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
    except (IOSNativeInputEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
