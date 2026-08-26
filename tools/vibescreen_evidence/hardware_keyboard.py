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
EXIT_STATUS_BY_VERDICT = {
    STATUS_PASS: 0,
    STATUS_BLOCKED: 2,
    STATUS_INSUFFICIENT: 1,
}

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
        "label the evidence with the observed device identity, without relabeling P0110/pacific as another device",
    ),
    ("apk_identity_recorded", "record APK version/signing identity and install timestamp"),
    (
        "physical_keyboard_attached",
        "attach and name a real external, non-virtual Android hardware keyboard",
    ),
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
    (
        "android_focus_ime_boundary_observed",
        "prove the Android Activity foreground/focus path accepts the hardware keyboard while IME or system-key boundaries do not masquerade as forwarded keys",
    ),
    (
        "selected_display_stream_observed",
        "prove the Protocol v1 session was actively streaming the selected display while the keyboard workflow ran",
    ),
    ("host_listener_observed", "record the macOS Host listener for the transport under test"),
    (
        "host_stable_signed_tcc_ready",
        "run a stable signed Host with Screen Recording and Accessibility permission ready",
    ),
    ("host_key_injection_observed", "retain Host 'Key injected:' CGEvent logs for the keyboard events"),
    (
        "host_ack_cgevent_log_observed",
        "retain Host-side admission/acknowledgement logs and CGEvent injection logs for every claimed key and shortcut event",
    ),
    ("key_press_release_observed", "prove key-down and key-up semantics for the same HID usage"),
    (
        "modifier_press_release_observed",
        "prove modifier key press and release semantics, not only a shortcut side effect",
    ),
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
HOST_CONFIRMATION_FIELDS = (
    "host_key_injection_observed",
    "host_ack_cgevent_log_observed",
)
HOST_CONFIRMATION_REQUIREMENT = (
    "retain Host-side `Key injected:` CGEvent logs or Host acknowledgement/CGEvent logs "
    "for every claimed key and shortcut event"
)

CONSISTENCY_RULES = (
    (
        "android_keyboard_source_observed",
        ("physical_keyboard_attached",),
        "Android keyboard source evidence requires a named physical Android-attached keyboard",
    ),
    (
        "protocol_usb_hid_modifier_capability_negotiated",
        ("protocol_keyboard_capability_negotiated",),
        "USB HID modifier capability evidence requires Protocol v1 keyboard capability negotiation",
    ),
    (
        "android_production_forwarding_observed",
        ("physical_keyboard_attached", "protocol_keyboard_capability_negotiated"),
        "production keyboard forwarding requires a physical keyboard and negotiated Protocol v1 keyboard capability",
    ),
    (
        "android_focus_ime_boundary_observed",
        ("physical_keyboard_attached", "android_production_forwarding_observed"),
        "Android focus and IME-boundary evidence requires a physical keyboard and production forwarding logs",
    ),
    (
        "selected_display_stream_observed",
        ("protocol_keyboard_capability_negotiated",),
        "selected-display stream evidence requires Protocol v1 keyboard capability negotiation",
    ),
    (
        "host_key_injection_observed",
        ("android_production_forwarding_observed", "host_listener_observed", "host_stable_signed_tcc_ready"),
        "Host key-injection logs require production forwarding plus a stable signed/TCC-ready Host listener",
    ),
    (
        "host_ack_cgevent_log_observed",
        ("android_production_forwarding_observed", "host_listener_observed", "host_stable_signed_tcc_ready"),
        "Host acknowledgement/CGEvent logs require production forwarding plus a stable signed/TCC-ready Host listener",
    ),
    (
        "modifier_release_no_leak_observed",
        ("shortcut_combo_observed", "key_press_release_observed"),
        "modifier cleanup evidence requires shortcut and key release observations",
    ),
    (
        "android_logs_retained",
        ("android_production_forwarding_observed",),
        "retained Android keyboard logs must correspond to production forwarding",
    ),
)


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
    if any(not item.strip() for item in value):
        raise HardwareKeyboardEvidenceError(
            f"{field} must contain only non-empty strings"
        )
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


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise HardwareKeyboardEvidenceError("run_id must be a non-empty string")


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
    host_confirmed = any(field_values[field] for field in HOST_CONFIRMATION_FIELDS)
    for observed_field, requirement in (
        ("key_press_release_observed", "key press/release evidence requires Host key-injection or acknowledgement/CGEvent logs"),
        (
            "modifier_press_release_observed",
            "modifier press/release evidence requires Host key-injection or acknowledgement/CGEvent logs and negotiated USB HID modifier semantics",
        ),
        (
            "shortcut_combo_observed",
            "shortcut evidence requires Host key-injection or acknowledgement/CGEvent logs and negotiated USB HID modifier semantics",
        ),
        ("visible_mac_result_observed", "visible Mac keyboard result requires Host key-injection or acknowledgement/CGEvent logs"),
        ("host_logs_retained", "retained Host keyboard logs must correspond to Host key-injection or acknowledgement/CGEvent evidence"),
    ):
        if field_values[observed_field] and not host_confirmed:
            inconsistencies.append(
                {
                    "field": observed_field,
                    "requires": list(HOST_CONFIRMATION_FIELDS),
                    "requirement": requirement,
                }
            )
    for observed_field, requirement in (
        ("modifier_press_release_observed", "modifier press/release evidence requires negotiated USB HID modifier semantics"),
        ("shortcut_combo_observed", "shortcut evidence requires negotiated USB HID modifier semantics"),
    ):
        if (
            field_values[observed_field]
            and not field_values["protocol_usb_hid_modifier_capability_negotiated"]
        ):
            inconsistencies.append(
                {
                    "field": observed_field,
                    "requires": ["protocol_usb_hid_modifier_capability_negotiated"],
                    "requirement": requirement,
                }
            )
    return inconsistencies


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    host_confirmed = any(field_values[field] for field in HOST_CONFIRMATION_FIELDS)
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if field not in HOST_CONFIRMATION_FIELDS and not field_values[field]
    ]
    if not host_confirmed:
        missing.append(
            {
                "field": "|".join(HOST_CONFIRMATION_FIELDS),
                "requirement": HOST_CONFIRMATION_REQUIREMENT,
            }
        )
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    inconsistencies = _inconsistent_observations(field_values)
    if not missing and not inconsistencies:
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
        "kind": "phase2_hardware_keyboard_workflow",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_hardware_keyboard_gate": verdict == STATUS_PASS,
        "requires_physical_keyboard": True,
        "adb_input_is_not_physical_keyboard_evidence": True,
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16 "
            "evidence must not be relabeled as another device."
        ),
        "observations": field_values,
        "missing_requirements": missing,
        "inconsistent_observations": inconsistencies,
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
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="return exit status 1 unless the evidence verdict is pass",
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
    if args.require_pass and summary["verdict"] != STATUS_PASS:
        return 1
    return EXIT_STATUS_BY_VERDICT[summary["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
