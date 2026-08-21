#!/usr/bin/env python3
"""Validate recorded evidence for rotated host-display acceptance.

This gate intentionally validates an already-captured evidence summary. It does
not rotate macOS displays, start the Host, touch ADB, or claim real-device
coverage from offline data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


KIND = "host_display_rotation_acceptance"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
DISPLAY_KINDS = frozenset(("physical", "virtual"))
VALID_TRANSPORTS = frozenset(("lan", "usb"))
VALID_ROTATIONS = frozenset((0, 90, 180, 270))
REQUIRED_DEVICE_FIELDS = (
    "manufacturer",
    "model",
    "codename",
    "android_release",
    "sdk",
    "adb_serial",
)
REQUIRED_HOST_PREFLIGHT_FIELDS = (
    "host_signing_identity",
    "host_bundle_id",
    "screen_recording_granted",
    "accessibility_granted",
    "signing_tcc_match",
    "host_display_rotation_restoration_plan",
)
REQUIRED_PROBES = (
    "visual_source_orientation",
    "input_mapping",
    "stable_stream",
    "no_session_teardown",
    "restored_original_host_rotation",
)
EVIDENCE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "host-display-rotation-evidence.schema.json"
)
REQUIRED_ARTIFACTS = (
    "device_identity",
    "host_display_snapshot_before",
    "host_display_snapshot_rotated",
    "android_screenshot",
    "touch_matrix",
    "host_log",
    "android_logcat",
)
ARTIFACT_BOUNDARY_ERROR = "must be a relative path inside the evidence directory"


class HostDisplayRotationGateError(ValueError):
    """Raised when evidence input is invalid or incomplete."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_json(input_path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            input_path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise HostDisplayRotationGateError(
            f"could not read {input_path}: {error}"
        ) from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise HostDisplayRotationGateError(f"invalid JSON in {input_path}: {error}") from error
    if not isinstance(document, dict):
        raise HostDisplayRotationGateError("top-level evidence must be an object")
    return document


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_rotation(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in VALID_ROTATIONS
    )


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _describe_json_type(expected_type: str) -> str:
    if expected_type == "object":
        return "an object"
    if expected_type == "array":
        return "an array"
    if expected_type == "string":
        return "a string"
    if expected_type == "integer":
        return "an integer"
    if expected_type == "boolean":
        return "a boolean"
    return expected_type


def _validate_schema_node(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str
) -> list[str]:
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
            return [f"{path}: unsupported schema reference"]
        definition = root.get("$defs", {}).get(reference.removeprefix("#/$defs/"))
        if not isinstance(definition, dict):
            return [f"{path}: unresolved schema reference {reference}"]
        return _validate_schema_node(value, definition, root, path)

    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(item) for item in schema["enum"])
        errors.append(f"{path}: must be one of {allowed}")

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        errors.append(f"{path}: must be {_describe_json_type(expected_type)}")
        return errors

    if expected_type == "object":
        assert isinstance(value, dict)
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required")
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in value:
                    errors.append(f"{path}.{field}: is required")
        if schema.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{path}.{field}: is not allowed by schema")
        for field, child_schema in properties.items():
            if field in value and isinstance(child_schema, dict):
                errors.extend(
                    _validate_schema_node(value[field], child_schema, root, f"{path}.{field}")
                )
    elif expected_type == "array":
        assert isinstance(value, list)
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: must contain at least {min_items} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_schema_node(item, item_schema, root, f"{path}[{index}]"))
    elif expected_type == "string":
        assert isinstance(value, str)
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path}: must be a non-empty string")
    elif expected_type == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            errors.append(f"{path}: must be at least {minimum}")

    return errors


def _validate_evidence_schema(document: dict[str, Any]) -> list[str]:
    try:
        schema = json.loads(EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as error:
        raise HostDisplayRotationGateError(
            f"could not read host display rotation evidence schema: {error}"
        ) from error
    return _validate_schema_node(document, schema, schema, "evidence")


def _append_missing_string(
    errors: list[str], run_index: int, field: str, value: Any
) -> None:
    if not _is_non_empty_string(value):
        errors.append(f"runs[{run_index}].{field}: must be a non-empty string")


def _validate_device_identity(
    run: dict[str, Any], run_index: int, errors: list[str]
) -> None:
    device = run.get("device")
    if not isinstance(device, dict):
        errors.append(f"runs[{run_index}].device: must be an object")
        return
    for field in REQUIRED_DEVICE_FIELDS:
        value = device.get(field)
        if field == "sdk":
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(
                    f"runs[{run_index}].device.sdk: must be a positive integer"
                )
        elif not _is_non_empty_string(value):
            errors.append(
                f"runs[{run_index}].device.{field}: must be a non-empty string"
            )


def _validate_host_preflight(
    run: dict[str, Any], run_index: int, errors: list[str]
) -> None:
    preflight = run.get("host_preflight")
    if not isinstance(preflight, dict):
        errors.append(f"runs[{run_index}].host_preflight: must be an object")
        return
    for field in REQUIRED_HOST_PREFLIGHT_FIELDS:
        value = preflight.get(field)
        if field in (
            "screen_recording_granted",
            "accessibility_granted",
            "signing_tcc_match",
            "host_display_rotation_restoration_plan",
        ):
            if value is not True:
                errors.append(
                    f"runs[{run_index}].host_preflight.{field}: must be true"
                )
        elif not _is_non_empty_string(value):
            errors.append(
                f"runs[{run_index}].host_preflight.{field}: must be a non-empty string"
            )


def _validate_artifacts(run: dict[str, Any], run_index: int, errors: list[str]) -> None:
    artifacts = run.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append(f"runs[{run_index}].artifacts: must be an object")
        return
    for name in REQUIRED_ARTIFACTS:
        value = artifacts.get(name)
        if not _is_non_empty_string(value):
            errors.append(
                f"runs[{run_index}].artifacts.{name}: must reference a retained artifact"
            )


def _validate_artifact_files(
    run: dict[str, Any], run_index: int, evidence_dir: Path | None, errors: list[str]
) -> None:
    if evidence_dir is None:
        return
    artifacts = run.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    resolved_evidence_dir = evidence_dir.resolve()
    for name in REQUIRED_ARTIFACTS:
        value = artifacts.get(name)
        if not _is_non_empty_string(value):
            continue
        artifact_path = Path(value)
        if artifact_path.is_absolute() or ".." in artifact_path.parts:
            errors.append(
                f"runs[{run_index}].artifacts.{name}: {ARTIFACT_BOUNDARY_ERROR}"
            )
            continue
        resolved = (resolved_evidence_dir / artifact_path).resolve()
        try:
            resolved.relative_to(resolved_evidence_dir)
        except ValueError:
            errors.append(
                f"runs[{run_index}].artifacts.{name}: {ARTIFACT_BOUNDARY_ERROR}"
            )
            continue
        if not resolved.is_file():
            errors.append(
                f"runs[{run_index}].artifacts.{name}: retained artifact not found at {resolved}"
            )


def _validate_artifact_contents(
    run: dict[str, Any], run_index: int, evidence_dir: Path | None, errors: list[str]
) -> None:
    if evidence_dir is None:
        return
    artifacts = run.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    resolved_evidence_dir = evidence_dir.resolve()
    for name in ("host_log", "android_logcat", "touch_matrix"):
        value = artifacts.get(name)
        if not _is_non_empty_string(value):
            continue
        artifact_path = Path(value)
        if artifact_path.is_absolute() or ".." in artifact_path.parts:
            continue
        path = (resolved_evidence_dir / artifact_path).resolve()
        try:
            path.relative_to(resolved_evidence_dir)
        except ValueError:
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            errors.append(
                f"runs[{run_index}].artifacts.{name}: could not read retained artifact: {error}"
            )
            continue
        if not text.strip():
            errors.append(
                f"runs[{run_index}].artifacts.{name}: retained artifact is empty"
            )


def _validate_distinct_display_evidence(
    runs: list[Any], errors: list[str]
) -> None:
    evidence_by_kind: dict[str, list[tuple[int, str, str, str]]] = {
        "physical": [],
        "virtual": [],
    }
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            continue
        display_kind = run.get("display_kind")
        if display_kind not in DISPLAY_KINDS:
            continue
        artifacts = run.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        display_id = run.get("display_id")
        before_snapshot = artifacts.get("host_display_snapshot_before")
        rotated_snapshot = artifacts.get("host_display_snapshot_rotated")
        if not (
            _is_non_empty_string(display_id)
            and _is_non_empty_string(before_snapshot)
            and _is_non_empty_string(rotated_snapshot)
        ):
            continue
        evidence_by_kind[display_kind].append((
            index,
            display_id,
            before_snapshot,
            rotated_snapshot,
        ))

    for physical in evidence_by_kind["physical"]:
        physical_index, physical_display_id, physical_before, physical_rotated = physical
        for virtual in evidence_by_kind["virtual"]:
            virtual_index, virtual_display_id, virtual_before, virtual_rotated = virtual
            if physical_display_id == virtual_display_id:
                errors.append(
                    f"runs[{virtual_index}].display_id: must differ from "
                    f"runs[{physical_index}].display_id for distinct physical and virtual evidence"
                )
            if physical_before == virtual_before:
                errors.append(
                    f"runs[{virtual_index}].artifacts.host_display_snapshot_before: "
                    f"must differ from runs[{physical_index}].artifacts.host_display_snapshot_before"
                )
            if physical_rotated == virtual_rotated:
                errors.append(
                    f"runs[{virtual_index}].artifacts.host_display_snapshot_rotated: "
                    f"must differ from runs[{physical_index}].artifacts.host_display_snapshot_rotated"
                )


def _validate_probes(run: dict[str, Any], run_index: int, errors: list[str]) -> None:
    probes = run.get("probes")
    if not isinstance(probes, dict):
        errors.append(f"runs[{run_index}].probes: must be an object")
        return
    for name in REQUIRED_PROBES:
        if probes.get(name) is not True:
            errors.append(f"runs[{run_index}].probes.{name}: must be true")


def _validate_run(
    run: Any, run_index: int, errors: list[str], evidence_dir: Path | None
) -> str | None:
    if not isinstance(run, dict):
        errors.append(f"runs[{run_index}]: must be an object")
        return None

    display_kind = run.get("display_kind")
    if display_kind not in DISPLAY_KINDS:
        errors.append(
            f"runs[{run_index}].display_kind: must be one of {sorted(DISPLAY_KINDS)}"
        )
        display_kind = None

    _append_missing_string(errors, run_index, "display_id", run.get("display_id"))
    transport = run.get("transport")
    if transport not in VALID_TRANSPORTS:
        errors.append(
            f"runs[{run_index}].transport: must be one of {sorted(VALID_TRANSPORTS)}"
        )
    _append_missing_string(
        errors, run_index, "host_rotation_source", run.get("host_rotation_source")
    )

    host_rotation = run.get("host_rotation_degrees")
    if not _is_valid_rotation(host_rotation) or host_rotation == 0:
        errors.append(
            f"runs[{run_index}].host_rotation_degrees: must be 90, 180, or 270"
        )

    original_rotation = run.get("original_host_rotation_degrees")
    if not _is_valid_rotation(original_rotation):
        errors.append(
            f"runs[{run_index}].original_host_rotation_degrees: must be 0, 90, 180, or 270"
        )
    elif _is_valid_rotation(host_rotation) and host_rotation == original_rotation:
        errors.append(
            f"runs[{run_index}].host_rotation_degrees: must differ from "
            "original_host_rotation_degrees"
        )

    client_rotation = run.get("client_rotation_degrees")
    if not _is_valid_rotation(client_rotation):
        errors.append(
            f"runs[{run_index}].client_rotation_degrees: must be 0, 90, 180, or 270"
        )

    if run.get("client_transform_scope") != "client-local-only":
        errors.append(
            f"runs[{run_index}].client_transform_scope: must be client-local-only"
        )

    if run.get("host_rotation_combined_with_client_transform") is not False:
        errors.append(
            f"runs[{run_index}].host_rotation_combined_with_client_transform: must be false"
        )

    _validate_device_identity(run, run_index, errors)
    _validate_host_preflight(run, run_index, errors)
    _validate_probes(run, run_index, errors)
    _validate_artifacts(run, run_index, errors)
    _validate_artifact_files(run, run_index, evidence_dir, errors)
    _validate_artifact_contents(run, run_index, evidence_dir, errors)
    return display_kind if isinstance(display_kind, str) else None


def evaluate(
    document: dict[str, Any], evidence_dir: Path | None = None
) -> dict[str, Any]:
    errors: list[str] = _validate_evidence_schema(document)
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if document.get("kind") != KIND:
        errors.append(f"kind: must be {KIND}")

    runs = document.get("runs")
    seen_display_kinds: set[str] = set()
    if not isinstance(runs, list) or not runs:
        errors.append("runs: must be a non-empty array")
    else:
        for index, run in enumerate(runs):
            display_kind = _validate_run(run, index, errors, evidence_dir)
            if display_kind is not None:
                seen_display_kinds.add(display_kind)
        _validate_distinct_display_evidence(runs, errors)

    missing_kinds = sorted(DISPLAY_KINDS - seen_display_kinds)
    for display_kind in missing_kinds:
        errors.append(f"runs: missing rotated {display_kind} host-display evidence")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "status": STATUS_COMPLETE if not errors else STATUS_FAILED,
        "covered_display_kinds": sorted(seen_display_kinds),
        "required_display_kinds": sorted(DISPLAY_KINDS),
        "required_transports": sorted(VALID_TRANSPORTS),
        "required_device_fields": list(REQUIRED_DEVICE_FIELDS),
        "required_host_preflight_fields": list(REQUIRED_HOST_PREFLIGHT_FIELDS),
        "required_probes": list(REQUIRED_PROBES),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "artifact_file_check": evidence_dir is not None,
        "errors": errors,
    }


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a manually recorded rotated host-display acceptance "
            "evidence summary without performing device or display actions."
        )
    )
    parser.add_argument("input", type=Path, help="host-display rotation evidence JSON")
    parser.add_argument("--output", type=Path, help="write gate result JSON")
    parser.add_argument(
        "--check-artifacts",
        action="store_true",
        help="require retained artifact paths to exist relative to the input directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        evidence_dir = args.input.parent if args.check_artifacts else None
        result = evaluate(_parse_json(args.input), evidence_dir=evidence_dir)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (HostDisplayRotationGateError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if result["status"] != STATUS_COMPLETE:
        for error in result["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
