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
EXIT_STATUS_BY_VERDICT = {
    STATUS_PASS: 0,
    STATUS_BLOCKED: 2,
    STATUS_INSUFFICIENT: 1,
}

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
        "device_identity_matches_claim",
        "label the evidence with the observed device identity, without relabeling P0110/pacific as Xiaomi/fuxi",
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
        "android_forwarding_device_ids_match_external_mouse",
        "match every Android forwarded pointer event to a positive deviceId from the external mouse-like input device inventory",
    ),
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
        "host_stable_signed_tcc_ready",
        "run a stable signed Host with Screen Recording and Accessibility permission ready",
    ),
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

BLOCKING_FIELDS = {
    "adb_was_run",
    "device_identity_recorded",
    "physical_mouse_attached",
    "host_stable_signed_tcc_ready",
}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
MOUSE_LIKE_SOURCES = {"MOUSE", "MOUSE_RELATIVE", "TOUCHPAD", "TRACKBALL"}

CONSISTENCY_RULES = (
    (
        "android_move_forwarded",
        ("physical_mouse_attached", "android_forwarding_device_ids_match_external_mouse", "default_gate_events_required"),
        "Android native pointer MOVE evidence requires a physical mouse-like source, matching physical deviceId, and the full gate event set",
    ),
    (
        "android_button_press_forwarded",
        ("physical_mouse_attached", "android_forwarding_device_ids_match_external_mouse", "default_gate_events_required"),
        "Android native pointer BUTTON_PRESS evidence requires a physical mouse-like source, matching physical deviceId, and the full gate event set",
    ),
    (
        "android_button_release_forwarded",
        ("physical_mouse_attached", "android_forwarding_device_ids_match_external_mouse", "default_gate_events_required"),
        "Android native pointer BUTTON_RELEASE evidence requires a physical mouse-like source, matching physical deviceId, and the full gate event set",
    ),
    (
        "host_pointer_changed_injected",
        ("android_move_forwarded", "host_stable_signed_tcc_ready"),
        "Host pointer changed injection must be paired with Android native pointer MOVE forwarding and stable signed/TCC-ready Host evidence",
    ),
    (
        "host_pointer_began_injected",
        ("android_button_press_forwarded", "host_stable_signed_tcc_ready"),
        "Host pointer began injection must be paired with Android native pointer BUTTON_PRESS forwarding and stable signed/TCC-ready Host evidence",
    ),
    (
        "host_pointer_ended_injected",
        ("android_button_release_forwarded", "host_stable_signed_tcc_ready"),
        "Host pointer ended injection must be paired with Android native pointer BUTTON_RELEASE forwarding and stable signed/TCC-ready Host evidence",
    ),
    (
        "visible_mac_result_observed",
        ("host_pointer_changed_injected", "host_pointer_began_injected", "host_pointer_ended_injected"),
        "Visible Mac pointer/click evidence requires Host move, press, and release injection logs",
    ),
)


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


def _device_identity_matches_claim(record: dict[str, Any]) -> bool:
    device = record.get("device")
    if not isinstance(device, dict):
        return False
    manufacturer = str(device.get("manufacturer", "")).strip().lower()
    model = str(device.get("model", "")).strip().lower()
    codename = str(device.get("device", "")).strip().lower()
    android_release = str(device.get("android_release", "")).strip()
    sdk = str(device.get("sdk", "")).strip()
    if not all((manufacturer, model, codename, android_release, sdk)):
        return False
    return (manufacturer, model, codename, android_release, sdk) == (
        "nubia",
        "p0110",
        "pacific",
        "16",
        "36",
    )


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


def _positive_device_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _external_mouse_device_ids(record: dict[str, Any]) -> set[int]:
    device_ids: set[int] = set()
    for device in _dict_list(record, "external_mouse_devices"):
        if not _truthy_external_marker(device.get("is_external")):
            continue
        if not MOUSE_LIKE_SOURCES.intersection(_source_tokens(device.get("sources"))):
            continue
        device_id = _positive_device_id(device.get("device_id"))
        if device_id is not None:
            device_ids.add(device_id)
    return device_ids


def _has_physical_mouse_like_device(record: dict[str, Any]) -> bool:
    return bool(_external_mouse_device_ids(record))


def _event_device_ids(record: dict[str, Any]) -> dict[str, set[int]]:
    value = record.get("observed_android_pointer_device_ids_by_event", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise NativePointerHIDEvidenceError("observed_android_pointer_device_ids_by_event must be an object")
    parsed: dict[str, set[int]] = {}
    for event, device_ids in value.items():
        if not isinstance(event, str) or not event.strip():
            raise NativePointerHIDEvidenceError("observed_android_pointer_device_ids_by_event keys must be non-empty strings")
        if not isinstance(device_ids, list):
            raise NativePointerHIDEvidenceError("observed_android_pointer_device_ids_by_event values must be lists")
        parsed[event] = {
            parsed_id
            for raw_id in device_ids
            if (parsed_id := _positive_device_id(raw_id)) is not None
        }
    return parsed


def _android_forwarding_device_ids_match_external_mouse(record: dict[str, Any]) -> bool:
    external_device_ids = _external_mouse_device_ids(record)
    if not external_device_ids:
        return False
    event_device_ids = _event_device_ids(record)
    return all(
        bool(external_device_ids.intersection(event_device_ids.get(event, set())))
        for event in REQUIRED_POINTER_EVENTS
    )


def _observations(record: dict[str, Any]) -> dict[str, bool]:
    status = _string_value(record, "status")
    required_events = set(_string_list(record, "required_pointer_events"))
    android_events = set(_string_list(record, "observed_android_pointer_events"))
    host_events = set(_string_list(record, "observed_host_pointer_events"))
    adb_default = status != "blocked_device_coordination_lock"

    return {
        "adb_was_run": _boolean_value(record, "adb_was_run", adb_default),
        "device_identity_recorded": _device_identity_recorded(record),
        "device_identity_matches_claim": _device_identity_matches_claim(record),
        "physical_mouse_attached": _has_physical_mouse_like_device(record),
        "default_gate_events_required": set(REQUIRED_POINTER_EVENTS).issubset(required_events),
        "android_move_forwarded": "move" in android_events,
        "android_forwarding_device_ids_match_external_mouse": _android_forwarding_device_ids_match_external_mouse(record),
        "android_button_press_forwarded": "press" in android_events,
        "android_button_release_forwarded": "release" in android_events,
        "host_pointer_changed_injected": "move" in host_events,
        "host_pointer_began_injected": "press" in host_events,
        "host_pointer_ended_injected": "release" in host_events,
        "host_stable_signed_tcc_ready": _boolean_value(record, "host_stable_signed_tcc_ready", False),
        "visible_mac_result_observed": bool(_string_value(record, "visible_mac_result").strip()),
        "android_logcat_window_retained": _integer_value(record, "android_logcat_bytes") > 0,
        "host_log_window_retained": _integer_value(record, "host_log_appended_bytes") > 0,
        "collector_reported_passed": status == "passed",
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
        "inconsistent_observations": inconsistencies,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _artifact_paths(record, source_path),
        "blocking_notes": blocking_notes,
        "notes": reason,
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def _existing_output_run_id(output_path: Path | None) -> str | None:
    if output_path is None or not output_path.exists():
        return None
    try:
        with output_path.open("r", encoding="utf-8") as stream:
            existing = load_record(stream)
    except (NativePointerHIDEvidenceError, OSError):
        return None
    return _optional_run_id(existing)


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
        output_path = Path(args.output) if args.output else None
        run_id = args.run_id or _existing_output_run_id(output_path)
        summary = summarize(record, run_id=run_id, source_path=source_path)
        if output_path:
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
    return EXIT_STATUS_BY_VERDICT[summary["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
