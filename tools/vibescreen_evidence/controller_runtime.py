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
from pathlib import Path, PurePosixPath
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "controller-runtime-acceptance"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
EXIT_STATUS_BY_VERDICT = {
    STATUS_PASS: 0,
    STATUS_BLOCKED: 2,
    STATUS_INSUFFICIENT: 1,
}

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

ARTIFACT_FIELD_REQUIREMENTS = {
    "device_identity_recorded": "retain Android device identity, OS/build, and adb devices artifacts",
    "apk_identity_recorded": "retain APK version, signing, and install-time artifacts",
    "physical_controller_attached": "retain named physical controller hardware evidence",
    "android_controller_source_observed": "retain SOURCE_GAMEPAD or SOURCE_JOYSTICK Android input evidence",
    "protocol_controller_capability_negotiated": "retain Protocol v1 controller capability negotiation evidence",
    "android_production_forwarding_observed": "retain MainActivity/StreamClient production forwarding evidence",
    "controller_connected_state_disconnected_observed": "retain CONNECTED, STATE, and DISCONNECTED controller samples",
    "host_identity_signed": "retain identity-signed Host codesign evidence",
    "host_virtual_hid_entitlement_present": "retain approved virtual HID entitlement evidence",
    "host_virtual_gamepad_available": "retain Host virtual-gamepad runtime availability evidence",
    "mac_side_controller_response_observed": "retain Mac-side observer output showing visible controller response",
    "neutral_release_on_disconnect_observed": "retain disconnect neutral-release evidence",
}

ARTIFACT_PATH_MARKERS = {
    "device_identity_recorded": ("device-info", "adb-devices"),
    "apk_identity_recorded": ("dumpsys-package", "apk"),
    "physical_controller_attached": ("dumpsys-input", "controller-hardware"),
    "android_controller_source_observed": ("dumpsys-input", "android-controller"),
    "protocol_controller_capability_negotiated": ("protocol-controller", "capability"),
    "android_production_forwarding_observed": ("android-controller", "streamclient", "mainactivity"),
    "controller_connected_state_disconnected_observed": ("protocol-controller", "controller-lifecycle"),
    "host_identity_signed": ("host-codesign",),
    "host_virtual_hid_entitlement_present": ("host-codesign", "entitlement"),
    "host_virtual_gamepad_available": ("host-controller-availability", "host-controller-injection"),
    "mac_side_controller_response_observed": ("mac-controller-observer", "mac-side-controller"),
    "neutral_release_on_disconnect_observed": ("neutral-release",),
}

CONSISTENCY_RULES = (
    (
        "physical_controller_attached",
        ("android_controller_source_observed",),
        "physical controller evidence must include an Android SOURCE_GAMEPAD or SOURCE_JOYSTICK observation",
    ),
    (
        "android_production_forwarding_observed",
        ("protocol_controller_capability_negotiated",),
        "production forwarding evidence must come from a negotiated controller-capable Protocol v1 session",
    ),
    (
        "controller_connected_state_disconnected_observed",
        ("android_production_forwarding_observed",),
        "controller lifecycle samples must be observed on the production forwarding path",
    ),
    (
        "host_virtual_gamepad_available",
        ("host_identity_signed", "host_virtual_hid_entitlement_present"),
        "Host virtual-gamepad availability requires an identity-signed build with the virtual HID entitlement",
    ),
    (
        "mac_side_controller_response_observed",
        ("host_virtual_gamepad_available",),
        "Mac-side response evidence requires Host virtual-gamepad availability",
    ),
    (
        "neutral_release_on_disconnect_observed",
        ("controller_connected_state_disconnected_observed",),
        "neutral release evidence requires connected, state, and disconnected controller lifecycle samples",
    ),
)


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
    for item in value:
        _validate_artifact_reference(field, item)
    return value


def _validate_artifact_reference(field: str, reference: str) -> None:
    if not reference.strip():
        raise ControllerRuntimeEvidenceError(f"{field} must contain only non-empty strings")
    path = PurePosixPath(reference)
    if path.is_absolute():
        raise ControllerRuntimeEvidenceError(f"{field} must contain relative evidence-bundle paths")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ControllerRuntimeEvidenceError(f"{field} must not escape the evidence bundle")


def _observation_artifacts(record: dict[str, Any]) -> dict[str, list[str]]:
    value = record.get("observation_artifacts", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ControllerRuntimeEvidenceError("observation_artifacts must be an object")
    artifacts: dict[str, list[str]] = {}
    for field, paths in value.items():
        if not isinstance(field, str):
            raise ControllerRuntimeEvidenceError("observation_artifacts keys must be strings")
        if field not in BOOLEAN_FIELDS:
            raise ControllerRuntimeEvidenceError(f"unknown observation_artifacts field: {field}")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ControllerRuntimeEvidenceError(
                f"observation_artifacts.{field} must be a list of strings"
            )
        for path in paths:
            _validate_artifact_reference(f"observation_artifacts.{field}", path)
        artifacts[field] = paths
    return artifacts


def _has_expected_artifact_marker(field: str, paths: Sequence[str]) -> bool:
    markers = ARTIFACT_PATH_MARKERS[field]
    normalized_paths = [path.lower() for path in paths]
    return any(marker in path for marker in markers for path in normalized_paths)


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


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    artifact_paths = _string_list(record, "artifact_paths")
    observation_artifacts = _observation_artifacts(record)
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    inconsistencies = _inconsistent_observations(field_values)
    if not artifact_paths:
        missing.append(
            {
                "field": "artifact_paths",
                "requirement": (
                    "retain raw or focused artifacts proving every true controller "
                    "runtime observation"
                ),
            }
        )
    artifact_path_set = set(artifact_paths)
    for field in BOOLEAN_FIELDS:
        if not field_values[field]:
            continue
        paths = observation_artifacts.get(field, [])
        if not paths:
            missing.append(
                {
                    "field": f"observation_artifacts.{field}",
                    "requirement": ARTIFACT_FIELD_REQUIREMENTS[field],
                }
            )
            continue
        if artifact_path_set and any(path not in artifact_path_set for path in paths):
            missing.append(
                {
                    "field": f"observation_artifacts.{field}",
                    "requirement": "list only paths also present in artifact_paths",
                }
            )
            continue
        if not _has_expected_artifact_marker(field, paths):
            missing.append(
                {
                    "field": f"observation_artifacts.{field}",
                    "requirement": ARTIFACT_FIELD_REQUIREMENTS[field],
                }
            )
    if not missing and not inconsistencies:
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
        "inconsistent_observations": inconsistencies,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": artifact_paths,
        "observation_artifacts": observation_artifacts,
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
        return EXIT_STATUS_BY_VERDICT[summary["verdict"]]
    except (ControllerRuntimeEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
