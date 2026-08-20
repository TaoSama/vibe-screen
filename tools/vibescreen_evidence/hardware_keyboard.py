"""Summarize Phase 2 hardware-keyboard workflow acceptance evidence.

This gate closes only when a real Android-attached hardware keyboard drives the
production Protocol v1 keyboard path into a stable signed macOS Host with the
required permissions, and retained logs prove press, shortcut, release, and
modifier-cleanup behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "phase2-hardware-keyboard-workflow"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"

REQUIRED_FIELDS = (
    (
        "android_device_lock_acquired",
        "exclusively acquire /tmp/vibe-screen-device-android.lock before using the Android device",
    ),
    (
        "device_identity_recorded",
        "record Android serial, manufacturer, model, codename, OS/build, SDK, and ABI",
    ),
    (
        "device_identity_matches_claim",
        "label the evidence with the observed device identity, without relabeling P0110/pacific as Xiaomi/fuxi",
    ),
    ("apk_identity_recorded", "record APK version/signing identity and install timestamp"),
    ("physical_keyboard_attached", "attach and name a real external or hardware Android keyboard"),
    (
        "android_keyboard_source_observed",
        "observe a physical keyboard input source in Android input/log evidence",
    ),
    (
        "protocol_keyboard_capability_negotiated",
        "negotiate Protocol v1 keyboard capability on the active session",
    ),
    (
        "protocol_usb_hid_modifier_capability_negotiated",
        "negotiate the USB HID modifier-byte capability for standard modifier semantics",
    ),
    (
        "android_production_forwarding_observed",
        "observe MainActivity/StreamClient production keyboard forwarding, not only adb input dispatch",
    ),
    ("host_listener_observed", "record the macOS Host listener for the transport under test"),
    (
        "host_stable_signed_tcc_ready",
        "run a stable signed Host with Screen Recording and Accessibility permission ready",
    ),
    ("host_key_injection_observed", "retain Host 'Key injected:' CGEvent logs for the keyboard events"),
    ("key_press_release_observed", "prove key-down and key-up semantics for the same HID usage"),
    ("shortcut_combo_observed", "prove at least one shortcut/modifier combination reaches the Host"),
    (
        "modifier_release_no_leak_observed",
        "prove modifiers clear after shortcut release and do not leak into a later plain key",
    ),
    ("visible_mac_result_observed", "record the visible Mac-side result of the hardware keyboard workflow"),
    ("host_logs_retained", "retain Host logs covering the keyboard workflow"),
    ("android_logs_retained", "retain Android logs/input snapshots covering the keyboard workflow"),
)

BLOCKING_FIELDS = {
    "android_device_lock_acquired",
    "physical_keyboard_attached",
    "host_listener_observed",
    "host_stable_signed_tcc_ready",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)


class HardwareKeyboardEvidenceError(ValueError):
    """Raised when a hardware-keyboard evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise HardwareKeyboardEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise HardwareKeyboardEvidenceError(
            "hardware keyboard evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise HardwareKeyboardEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HardwareKeyboardEvidenceError(f"{field} must be a list of strings")
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise HardwareKeyboardEvidenceError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise HardwareKeyboardEvidenceError("run_id must be a non-empty string")


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    if not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": "phase2_hardware_keyboard_workflow",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_hardware_keyboard_gate": verdict == STATUS_PASS,
        "requires_physical_keyboard": True,
        "adb_input_is_not_physical_keyboard_evidence": True,
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16 "
            "evidence must not be relabeled as Xiaomi 13/fuxi."
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
        description=(
            "Summarize Vibe Screen Phase 2 hardware-keyboard workflow evidence."
        ),
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing "
            "booleans default to false so absent lock, physical keyboard, Host "
            "listener, or stable signed/TCC evidence cannot accidentally close the gate."
        ),
    )
    parser.add_argument(
        "input", help="hardware-keyboard evidence .json file, or - for stdin"
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
    except (HardwareKeyboardEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
