"""Summarize controller runtime acceptance evidence without overstating it.

This gate is intentionally stricter than controller mapper or protocol tests:
it closes only when a physical Android controller drives the production
forwarding path and an identity-signed, entitled macOS Host exposes the
virtual gamepad to a Mac-side observer.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "controller-runtime-acceptance"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"

REQUIRED_FIELDS = (
    ("device_identity_recorded", "record Android hardware identity and OS/build details"),
    ("apk_identity_recorded", "record APK version/signing identity and install timestamp"),
    ("physical_controller_attached", "attach and name a physical Android controller"),
    ("android_controller_source_observed", "observe SOURCE_GAMEPAD or SOURCE_JOYSTICK in Android logs"),
    ("protocol_controller_capability_negotiated", "negotiate Protocol v1 controller capability"),
    ("android_production_forwarding_observed", "observe MainActivity/StreamClient production controller forwarding"),
    ("controller_connected_state_disconnected_observed", "record connected, state, and disconnected samples"),
    ("host_identity_signed", "run an Apple identity-signed Host build, not ad-hoc"),
    ("host_virtual_hid_entitlement_present", "include the approved virtual HID entitlement"),
    ("host_virtual_gamepad_available", "record Host virtual-gamepad runtime availability"),
    ("mac_side_controller_response_observed", "observe the virtual controller in a Mac-side target"),
    ("neutral_release_on_disconnect_observed", "record neutral release on disconnect"),
)

BLOCKING_FIELDS = {
    "physical_controller_attached",
    "host_identity_signed",
    "host_virtual_hid_entitlement_present",
    "host_virtual_gamepad_available",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)


class ControllerRuntimeEvidenceError(ValueError):
    """Raised when a controller evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise ControllerRuntimeEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise ControllerRuntimeEvidenceError("controller evidence must be a JSON object")
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise ControllerRuntimeEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ControllerRuntimeEvidenceError(f"{field} must be a list of strings")
    return value


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
        "run_id": run_id or str(uuid.uuid4()),
        "kind": "controller_runtime_acceptance",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_runtime_gate": verdict == STATUS_PASS,
        "requires_external_hardware": True,
        "requires_entitled_host": True,
        "observations": field_values,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _string_list(record, "artifact_paths"),
        "notes": record.get("notes", "") if isinstance(record.get("notes", ""), str) else "",
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen controller runtime acceptance evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing booleans "
            "default to false so absent physical controller or entitled Host evidence "
            "cannot accidentally close the gate."
        ),
    )
    parser.add_argument("input", help="controller evidence .json file, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence manifest")
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
    except (ControllerRuntimeEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
