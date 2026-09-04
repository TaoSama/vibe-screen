#!/usr/bin/env python3
"""Record fail-closed readiness for README latency performance gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_PROFILES,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)
from .latency_evidence import LatencyEvidenceError, build_latency_evidence_report

STATUS_READY = "ready"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"
INPUT_SCHEMA_PATH = SCHEMA_DIRECTORY / "latency-preflight-input.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMA_DIRECTORY / "latency-preflight.schema.json"
DEFAULT_PROFILES = (
    GATE_USB_GLASS_TO_GLASS_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_INPUT_P95_SUB50,
)

PROFILE_REQUIREMENTS = {
    GATE_USB_GLASS_TO_GLASS_SUB50: (
        (
            "device_identity_recorded",
            "record Android manufacturer, model, codename, OS version, SDK, and build fingerprint",
        ),
        (
            "current_base_provenance_recorded",
            "record clean current-base repository commit and source tree used to build the measured artifacts",
        ),
        (
            "host_build_identity_recorded",
            "record the measured Mac host identity plus Host binary SHA-256 and provenance",
        ),
        (
            "client_build_identity_recorded",
            "record the measured Android client artifact SHA-256 and provenance",
        ),
        (
            "external_camera_timebase_ready",
            "capture Mac stimulus/result and Android display/input in one 120 FPS or higher external-camera timebase",
        ),
        (
            "raw_camera_recording_retained",
            "retain the raw high-frame-rate camera recording in the evidence directory",
        ),
        (
            "sample_annotations_retained",
            "retain latency samples derived from the same camera timebase",
        ),
        (
            "minimum_sample_count_ready",
            "annotate at least five valid samples for the selected profile",
        ),
        (
            "formal_manifest_retained",
            "write a formal latency manifest bound to the raw recording, samples, device, host, and build",
        ),
        (
            "usb_transport_ready",
            "record ADB reverse/USB connection setup and active USB stream proof for the run",
        ),
    ),
    GATE_LAN_GLASS_TO_GLASS_SUB80: (
        (
            "device_identity_recorded",
            "record Android manufacturer, model, codename, OS version, SDK, and build fingerprint",
        ),
        (
            "current_base_provenance_recorded",
            "record clean current-base repository commit and source tree used to build the measured artifacts",
        ),
        (
            "host_build_identity_recorded",
            "record the measured Mac host identity plus Host binary SHA-256 and provenance",
        ),
        (
            "client_build_identity_recorded",
            "record the measured Android client artifact SHA-256 and provenance",
        ),
        (
            "external_camera_timebase_ready",
            "capture Mac stimulus/result and Android display/input in one 120 FPS or higher external-camera timebase",
        ),
        (
            "raw_camera_recording_retained",
            "retain the raw high-frame-rate camera recording in the evidence directory",
        ),
        (
            "sample_annotations_retained",
            "retain latency samples derived from the same camera timebase",
        ),
        (
            "minimum_sample_count_ready",
            "annotate at least five valid samples for the selected profile",
        ),
        (
            "formal_manifest_retained",
            "write a formal latency manifest bound to the raw recording, samples, device, host, and build",
        ),
        (
            "lan_transport_ready",
            "record LAN network preflight plus active trusted-LAN stream proof for the run",
        ),
    ),
    GATE_INPUT_P95_SUB50: (
        (
            "device_identity_recorded",
            "record Android manufacturer, model, codename, OS version, SDK, and build fingerprint",
        ),
        (
            "current_base_provenance_recorded",
            "record clean current-base repository commit and source tree used to build the measured artifacts",
        ),
        (
            "host_build_identity_recorded",
            "record the measured Mac host identity plus Host binary SHA-256 and provenance",
        ),
        (
            "client_build_identity_recorded",
            "record the measured Android client artifact SHA-256 and provenance",
        ),
        (
            "measurement_timebase_ready",
            "retain external-camera evidence or synchronized-clock proof with total error budget below 5 ms",
        ),
        (
            "sample_annotations_retained",
            "retain direct latency samples or samples derived from the measurement timebase",
        ),
        (
            "minimum_sample_count_ready",
            "annotate at least five valid samples for the selected profile",
        ),
        (
            "formal_manifest_retained",
            "write a formal latency manifest bound to samples, device, host, build, and timing provenance",
        ),
        (
            "physical_input_actuation_ready",
            "use real physical Android input actuation visible to, or timestamped by, the measurement setup",
        ),
        (
            "visible_mac_input_result_ready",
            "record the first visible Mac-side result for each physical input sample",
        ),
    ),
}


class LatencyPreflightError(ValueError):
    """Raised when a latency preflight input cannot be evaluated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise LatencyPreflightError(f"cannot read {label} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise LatencyPreflightError(f"invalid JSON in {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise LatencyPreflightError(f"{label} must be a JSON object")
    return document


def _json_type_matches(value: Any, expected_type: str | list[Any]) -> bool:
    if isinstance(expected_type, list):
        return any(_json_type_matches(value, item) for item in expected_type)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "null":
        return value is None
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "string":
        return isinstance(value, str)
    return True


def _describe_json_type(expected_type: str | list[Any]) -> str:
    if isinstance(expected_type, list):
        return " or ".join(_describe_json_type(item) for item in expected_type)
    if expected_type == "array":
        return "an array"
    if expected_type == "boolean":
        return "a boolean"
    if expected_type == "integer":
        return "an integer"
    if expected_type == "null":
        return "null"
    if expected_type == "object":
        return "an object"
    if expected_type == "string":
        return "a string"
    return str(expected_type)


def _resolve_schema_ref(schema: dict[str, Any], ref: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise LatencyPreflightError(f"unsupported schema reference: {ref}")
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        raise LatencyPreflightError("schema is missing $defs")
    target = defs.get(ref[len(prefix) :])
    if not isinstance(target, dict):
        raise LatencyPreflightError(f"schema reference not found: {ref}")
    return target


def _validate_schema_node(
    value: Any, node: dict[str, Any], path: str, root_schema: dict[str, Any]
) -> list[str]:
    ref = node.get("$ref")
    if isinstance(ref, str):
        return _validate_schema_node(value, _resolve_schema_ref(root_schema, ref), path, root_schema)

    errors: list[str] = []
    for child in node.get("allOf", []):
        if isinstance(child, dict):
            errors.extend(_validate_schema_node(value, child, path, root_schema))

    condition = node.get("if")
    then_schema = node.get("then")
    if (
        isinstance(condition, dict)
        and isinstance(then_schema, dict)
        and not _validate_schema_node(value, condition, path, root_schema)
    ):
        errors.extend(_validate_schema_node(value, then_schema, path, root_schema))

    if "const" in node and value != node["const"]:
        errors.append(f"{path} must be {node['const']}")
    if "enum" in node and value not in node["enum"]:
        allowed = ", ".join(str(item) for item in node["enum"])
        errors.append(f"{path} must be one of: {allowed}")

    expected_type = node.get("type")
    if expected_type is not None and not _json_type_matches(value, expected_type):
        errors.append(f"{path} must be {_describe_json_type(expected_type)}")
        return errors

    if isinstance(value, dict):
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        required = node.get("required") if isinstance(node.get("required"), list) else []
        for field in required:
            if isinstance(field, str) and field not in value:
                errors.append(f"{path}.{field} is required")
        if node.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{path}.{field} is not allowed by schema")
        for field, child in properties.items():
            if field in value and isinstance(child, dict):
                errors.extend(_validate_schema_node(value[field], child, f"{path}.{field}", root_schema))
    elif isinstance(value, list):
        min_items = node.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path} must contain at least {min_items} item(s)")
        item_schema = node.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value, start=1):
                errors.extend(_validate_schema_node(item, item_schema, f"{path}[{index}]", root_schema))
    elif isinstance(value, str):
        min_length = node.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must not be empty")
    return errors


def _validate_document_schema(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path, f"{label} schema")
    errors = _validate_schema_node(document, schema, label, schema)
    if errors:
        raise LatencyPreflightError("; ".join(errors))


def _repository_revision(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LatencyPreflightError(f"cannot resolve repository revision: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise LatencyPreflightError(f"git rev-parse HEAD failed: {detail}")
    return result.stdout.strip()


def _device_from_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    document = _load_json(path, "device info")
    device = document.get("device")
    if not isinstance(device, dict):
        raise LatencyPreflightError("device info must contain a device object")
    return device


def _bool_checks(raw_checks: Any, profile: str) -> dict[str, bool]:
    if raw_checks is None:
        return {}
    if not isinstance(raw_checks, dict):
        raise LatencyPreflightError(f"gate profile {profile}: checks must be an object")
    checks: dict[str, bool] = {}
    allowed_fields = {field for field, _requirement in PROFILE_REQUIREMENTS[profile]}
    for key, value in raw_checks.items():
        if not isinstance(key, str):
            raise LatencyPreflightError(f"gate profile {profile}: check names must be strings")
        if key not in allowed_fields:
            raise LatencyPreflightError(f"gate profile {profile}: unsupported check {key}")
        if not isinstance(value, bool):
            raise LatencyPreflightError(f"gate profile {profile}: checks.{key} must be true or false")
        checks[key] = value
    return checks


def _input_profiles(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = document.get("gate_profiles")
    if raw_profiles is None:
        return [{"profile": profile} for profile in DEFAULT_PROFILES]
    if not isinstance(raw_profiles, list):
        raise LatencyPreflightError("gate_profiles must be a list")
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_profiles, start=1):
        if not isinstance(item, dict):
            raise LatencyPreflightError(f"gate_profiles[{index}] must be an object")
        profile = item.get("profile")
        if not isinstance(profile, str) or profile not in DEFAULT_PROFILES:
            raise LatencyPreflightError(f"gate_profiles[{index}].profile is unsupported")
        if profile in seen:
            raise LatencyPreflightError(f"gate profile {profile} appears more than once")
        seen.add(profile)
        profiles.append(item)
    return profiles


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _formal_failure_report(manifest_path: Path, gate_profile: str, reason: str) -> dict[str, Any]:
    profile = GATE_PROFILES[gate_profile]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": None,
        "kind": "latency_evidence_gate",
        "status": "failed",
        "derivation_status": "failed",
        "verdict": "insufficient",
        "latency_kind": profile["kind"],
        "transport": profile["transport"],
        "measurement_method": None,
        "gate": {
            "profile": gate_profile,
            "can_close_performance_gate": False,
            "summary_verdict": "insufficient",
            "threshold_ms": profile["threshold_ms"],
            "observed_ms": None,
            "observed_with_uncertainty_ms": None,
            "sample_count": None,
            "min_sample_count": None,
            "requires_external_hardware": True,
            "reasons": [reason],
        },
        "metrics": {},
        "source": {"manifest": str(manifest_path)},
    }


def _profile_result(
    item: dict[str, Any],
    *,
    base_dir: Path,
) -> tuple[dict[str, Any], str]:
    profile = str(item["profile"])
    gate_profile = GATE_PROFILES[profile]
    checks = _bool_checks(item.get("checks"), profile)
    requirements = PROFILE_REQUIREMENTS[profile]
    normalized_checks = {field: checks.get(field, False) for field, _ in requirements}
    missing_requirements = [
        {"field": field, "requirement": requirement}
        for field, requirement in requirements
        if not normalized_checks[field]
    ]
    artifact_paths: list[str] = []
    formal_report: dict[str, Any] | None = None

    manifest_value = item.get("manifest")
    if normalized_checks.get("formal_manifest_retained") and manifest_value is None:
        missing_requirements.append(
            {
                "field": "manifest",
                "requirement": (
                    "provide the formal latency manifest path so "
                    "the formal checker can validate retained artifacts"
                ),
            }
        )
    if manifest_value is not None:
        if not isinstance(manifest_value, str) or not manifest_value.strip():
            raise LatencyPreflightError(f"gate profile {profile}: manifest must be a non-empty string")
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = base_dir / manifest_path
        try:
            formal_report = build_latency_evidence_report(
                manifest_path=manifest_path,
                gate_profile=profile,
            )
        except LatencyEvidenceError as error:
            formal_report = _formal_failure_report(manifest_path, profile, str(error))
        artifact_paths.append(_relative_to_base(manifest_path, base_dir))

    if formal_report is not None:
        formal_verdict = str(formal_report.get("verdict"))
        if formal_verdict == "pass" and not missing_requirements:
            status = STATUS_READY
        elif formal_verdict == "fail":
            status = STATUS_FAILED
        else:
            status = STATUS_BLOCKED
        can_attempt_formal_gate = not missing_requirements
        can_close_performance_gate = formal_verdict == "pass" and not missing_requirements
    else:
        status = STATUS_READY if not missing_requirements else STATUS_BLOCKED
        can_attempt_formal_gate = not missing_requirements
        can_close_performance_gate = False

    result: dict[str, Any] = {
        "profile": profile,
        "status": status,
        "latency_kind": gate_profile["kind"],
        "transport": gate_profile["transport"],
        "checks": normalized_checks,
        "can_attempt_formal_gate": can_attempt_formal_gate,
        "can_close_performance_gate": can_close_performance_gate,
        "missing_requirements": missing_requirements,
        "artifact_paths": artifact_paths,
    }
    if formal_report is not None:
        result["formal_report"] = formal_report
        if formal_report.get("gate", {}).get("reasons"):
            result["formal_gate_reasons"] = formal_report["gate"]["reasons"]
    return result, status


def build_latency_preflight_report(
    *,
    input_document: dict[str, Any] | None = None,
    device_info: dict[str, Any] | None = None,
    repository_revision: str | None = None,
    checked_at: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    document = input_document or {}
    if input_document is not None:
        _validate_document_schema(document, INPUT_SCHEMA_PATH, "latency preflight input")
    base = base_dir or Path.cwd()
    profiles: list[dict[str, Any]] = []
    statuses: list[str] = []
    for item in _input_profiles(document):
        profile, status = _profile_result(item, base_dir=base)
        profiles.append(profile)
        statuses.append(status)

    if any(status == STATUS_FAILED for status in statuses):
        status = STATUS_FAILED
    elif any(status == STATUS_BLOCKED for status in statuses):
        status = STATUS_BLOCKED
    else:
        status = STATUS_READY

    notes = document.get("notes", [])
    if notes is None:
        notes = []
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise LatencyPreflightError("notes must be a list of strings")

    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "latency_gate_preflight",
        "run_id": str(document.get("run_id") or f"latency-preflight-{uuid.uuid4()}"),
        "checked_at": checked_at or str(document.get("checked_at") or _utc_now()),
        "repository_revision": repository_revision,
        "status": status,
        "claim_boundary": (
            "This preflight is readiness evidence only. It cannot close USB, LAN, "
            "or input latency gates; only a passing formal latency evidence report "
            "with retained real measurement artifacts can do that."
        ),
        "device": device_info,
        "gate_profiles": profiles,
        "notes": notes,
    }
    _validate_document_schema(report, OUTPUT_SCHEMA_PATH, "latency preflight report")
    return report


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="readiness input JSON; omitted checks default to false")
    parser.add_argument("--device-info", type=Path, help="device-info JSON to embed")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository used for git revision")
    parser.add_argument("--repository-revision", help="explicit repository revision")
    parser.add_argument("--checked-at", help="explicit timestamp or date for reproducible records")
    parser.add_argument("--output", type=Path, help="write preflight JSON to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        input_document = _load_json(args.input, "latency preflight input") if args.input else None
        device_info = _device_from_info(args.device_info)
        revision = args.repository_revision or _repository_revision(args.repo)
        report = build_latency_preflight_report(
            input_document=input_document,
            device_info=device_info,
            repository_revision=revision,
            checked_at=args.checked_at,
            base_dir=Path.cwd(),
        )
        if args.output:
            _write_json(args.output, report)
        else:
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    except (LatencyPreflightError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if report["status"] == STATUS_READY:
        return 0
    if report["status"] == STATUS_BLOCKED:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
