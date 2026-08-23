"""Summarize native pointer HID mouse acceptance evidence.

The README gate closes only when a real Android-attached mouse-like HID drives
the production Protocol v1 pointer path into a macOS Host and the retained
evidence proves move, press, release, and a visible Mac-side result.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "native-pointer-hid-mouse"
GATE_KIND = "native_pointer_hid_acceptance"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"

REQUIRED_POINTER_EVENTS = ("move", "press", "release")

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
        "physical_mouse_attached",
        "attach a real USB/Bluetooth mouse, touchpad, trackball, or relative mouse source to Android",
    ),
    (
        "default_gate_events_required",
        "collect the full README gate event set: move, primary-button press, and primary-button release",
    ),
    ("android_move_forwarded", "retain Android native pointer MOVE forwarding logs from a mouse-like source"),
    (
        "android_button_press_forwarded",
        "retain Android native pointer BUTTON_PRESS forwarding logs from a mouse-like source",
    ),
    (
        "android_button_release_forwarded",
        "retain Android native pointer BUTTON_RELEASE forwarding logs from a mouse-like source",
    ),
    ("host_pointer_changed_injected", "retain Host Pointer injected changed logs"),
    ("host_pointer_began_injected", "retain Host Pointer injected began logs"),
    ("host_pointer_ended_injected", "retain Host Pointer injected ended logs"),
    (
        "visible_mac_result_observed",
        "record an operator note describing visible Mac cursor movement and click result",
    ),
    ("android_logcat_window_retained", "retain the bounded Android logcat observation window"),
    ("host_log_window_retained", "retain the newly appended Host log observation window"),
    (
        "collector_reported_passed",
        "use a collector result whose own status is passed, not blocked or failed",
    ),
)

BLOCKING_FIELDS = {"adb_was_run", "device_identity_recorded", "physical_mouse_attached"}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
MOUSE_LIKE_SOURCES = {"MOUSE", "MOUSE_RELATIVE", "TOUCHPAD", "TRACKBALL"}


class NativePointerHIDEvidenceError(ValueError):
    """Raised when a native pointer HID evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise NativePointerHIDEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise NativePointerHIDEvidenceError("native pointer HID evidence must be a JSON object")
    return record


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise NativePointerHIDEvidenceError(f"{field} must be a string")


def _integer_value(record: dict[str, Any], field: str) -> int:
    value = record.get(field, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise NativePointerHIDEvidenceError(f"{field} must be an integer")


def _boolean_value(record: dict[str, Any], field: str, default: bool) -> bool:
    value = record.get(field, default)
    if isinstance(value, bool):
        return value
    raise NativePointerHIDEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise NativePointerHIDEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise NativePointerHIDEvidenceError(f"{field} must contain only non-empty strings")
    return value


def _dict_list(record: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise NativePointerHIDEvidenceError(f"{field} must be a list of objects")
    return value


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise NativePointerHIDEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip():
        return value
    raise NativePointerHIDEvidenceError("run_id must be a non-empty string")


def _device_identity_recorded(record: dict[str, Any]) -> bool:
    device = record.get("device")
    if not isinstance(device, dict):
        return False
    required_fields = ("manufacturer", "model", "device", "android_release", "sdk")
    for field in required_fields:
        value = device.get(field)
        if not isinstance(value, str) or not value.strip() or value.startswith("not collected"):
            return False
    return True


def _artifact_paths(record: dict[str, Any], source_path: Path | None) -> list[str]:
    explicit = record.get("artifact_paths")
    if explicit is not None:
        return _string_list(record, "artifact_paths")
    paths: list[str] = []
    if source_path is not None and str(source_path) != "-":
        paths.append(source_path.name)
    paths.append("dumpsys-input.txt")
    paths.append("android-logcat-native-pointer.txt")
    host_log = _string_value(record, "host_log")
    if host_log:
        paths.append(host_log)
    return sorted(dict.fromkeys(paths))


def _lock_notes(record: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for lock in _dict_list(record, "existing_locks"):
        path = lock.get("path")
        detail = lock.get("detail") or lock.get("read_error") or "present"
        if isinstance(path, str) and path.strip():
            notes.append(f"{path}: {detail}")
    return notes


def _truthy_external_marker(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _source_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        source_text = value
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        source_text = "|".join(value)
    else:
        return set()
    return {token.strip().upper() for token in source_text.replace(",", "|").split("|") if token.strip()}


def _has_physical_mouse_like_device(record: dict[str, Any]) -> bool:
    for device in _dict_list(record, "external_mouse_devices"):
        if not _truthy_external_marker(device.get("is_external")):
            continue
        if MOUSE_LIKE_SOURCES.intersection(_source_tokens(device.get("sources"))):
            return True
    return False


def _observations(record: dict[str, Any]) -> dict[str, bool]:
    status = _string_value(record, "status")
    required_events = set(_string_list(record, "required_pointer_events"))
    android_events = set(_string_list(record, "observed_android_pointer_events"))
    host_events = set(_string_list(record, "observed_host_pointer_events"))
    adb_default = status != "blocked_device_coordination_lock"

    return {
        "adb_was_run": _boolean_value(record, "adb_was_run", adb_default),
        "device_identity_recorded": _device_identity_recorded(record),
        "physical_mouse_attached": _has_physical_mouse_like_device(record),
        "default_gate_events_required": set(REQUIRED_POINTER_EVENTS).issubset(required_events),
        "android_move_forwarded": "move" in android_events,
        "android_button_press_forwarded": "press" in android_events,
        "android_button_release_forwarded": "release" in android_events,
        "host_pointer_changed_injected": "move" in host_events,
        "host_pointer_began_injected": "press" in host_events,
        "host_pointer_ended_injected": "release" in host_events,
        "visible_mac_result_observed": bool(_string_value(record, "visible_mac_result").strip()),
        "android_logcat_window_retained": _integer_value(record, "android_logcat_bytes") > 0,
        "host_log_window_retained": _integer_value(record, "host_log_appended_bytes") > 0,
        "collector_reported_passed": status == "passed",
    }


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
    if not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    blocking_notes = _string_list(record, "blocking_notes") + _lock_notes(record)
    status = _string_value(record, "status")
    reason = _string_value(record, "reason")
    if verdict == STATUS_BLOCKED and reason:
        blocking_notes.append(reason)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": GATE_KIND,
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_native_pointer_hid_gate": verdict == STATUS_PASS,
        "collector_status": status,
        "requires_physical_mouse": True,
        "synthetic_adb_pointer_is_not_physical_hid_evidence": True,
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16 "
            "evidence must not be relabeled as Xiaomi 13/fuxi."
        ),
        "observations": field_values,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _artifact_paths(record, source_path),
        "blocking_notes": blocking_notes,
        "notes": reason,
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen native pointer HID mouse acceptance evidence.",
        epilog=(
            "Input is the result.json written by scripts/native_pointer_hid_acceptance.py. "
            "The summary keeps the gate open unless physical mouse, Android forwarding, "
            "Host injection, and visible Mac-result evidence are all present."
        ),
    )
    parser.add_argument("input", help="native pointer HID result.json file, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="return nonzero unless the summary can close the native pointer HID gate",
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
    except (NativePointerHIDEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.require_pass and not summary["can_close_native_pointer_hid_gate"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
