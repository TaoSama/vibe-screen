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
VALID_ROTATIONS = frozenset((0, 90, 180, 270))
REQUIRED_PROBES = (
    "visual_source_orientation",
    "input_mapping",
    "stable_stream",
    "no_session_teardown",
    "restored_original_host_rotation",
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


def _append_missing_string(
    errors: list[str], run_index: int, field: str, value: Any
) -> None:
    if not _is_non_empty_string(value):
        errors.append(f"runs[{run_index}].{field}: must be a non-empty string")


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


def _validate_probes(run: dict[str, Any], run_index: int, errors: list[str]) -> None:
    probes = run.get("probes")
    if not isinstance(probes, dict):
        errors.append(f"runs[{run_index}].probes: must be an object")
        return
    for name in REQUIRED_PROBES:
        if probes.get(name) is not True:
            errors.append(f"runs[{run_index}].probes.{name}: must be true")


def _validate_run(run: Any, run_index: int, errors: list[str]) -> str | None:
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
    _append_missing_string(errors, run_index, "transport", run.get("transport"))
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

    _validate_probes(run, run_index, errors)
    _validate_artifacts(run, run_index, errors)
    return display_kind if isinstance(display_kind, str) else None


def evaluate(document: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
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
            display_kind = _validate_run(run, index, errors)
            if display_kind is not None:
                seen_display_kinds.add(display_kind)

    missing_kinds = sorted(DISPLAY_KINDS - seen_display_kinds)
    for display_kind in missing_kinds:
        errors.append(f"runs: missing rotated {display_kind} host-display evidence")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "status": STATUS_COMPLETE if not errors else STATUS_FAILED,
        "covered_display_kinds": sorted(seen_display_kinds),
        "required_display_kinds": sorted(DISPLAY_KINDS),
        "required_probes": list(REQUIRED_PROBES),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = evaluate(_parse_json(args.input))
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
