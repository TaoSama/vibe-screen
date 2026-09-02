"""Evaluate the host display rotation current-base readiness gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .host_display_rotation_current_base_manifest import (
    AGGREGATE_OWNER,
    AGGREGATE_OWNER_PR,
    DEVICE_FIELDS,
    FORMAL_GATES,
    HOST_PREFLIGHT_CHECKS,
    KIND as MANIFEST_KIND,
    REQUIRED_HOST_ROTATIONS,
    REDACTED_SOURCE_ROOT,
    SCOPE_PRS,
    SOURCE_DOCS,
    SUPPORTING_GATES,
)
from .host_display_rotation_gate import (
    EXPECTED_EVIDENCE_SOURCE,
    KIND as EVIDENCE_GATE_KIND,
    REQUIRED_ARTIFACTS,
    REQUIRED_DEVICE_FIELDS,
    REQUIRED_HOST_PREFLIGHT_FIELDS,
    REQUIRED_INPUT_MAPPING_POINTS,
    REQUIRED_PROBES,
    VALID_TRANSPORTS,
    evaluate as evaluate_evidence_gate,
)

GATE_KIND = "host_display_rotation_current_base_gate"
PASS_STATUSES = {"pass", "passed", "complete"}
REQUIRED_RECORD_FIELDS = {"status", "category", "requirement", "blocking", "evidence", "notes"}
EVIDENCE_FILENAME = "host-display-rotation.json"
EVIDENCE_GATE_FILENAME = "host-display-rotation-gate.json"

INTERPRETATION = (
    "A pass means the current base has retained real-device evidence for both "
    "physical and virtual macOS host displays at 90, 180, and 270 degrees. "
    "The existing client-local Fit/Fill/rotation matrix with hostRotation=0 "
    "remains supporting evidence only and cannot close this gate."
)


class HostDisplayRotationCurrentBaseGateError(ValueError):
    """Raised when a current-base manifest cannot be evaluated."""


def _load_json(path: Path, label: str = "host display rotation current-base manifest") -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HostDisplayRotationCurrentBaseGateError(
            f"cannot read {label}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise HostDisplayRotationCurrentBaseGateError(
            f"{label} must be a JSON object"
        )
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _status_pass(value: Any) -> bool:
    return isinstance(value, str) and value in PASS_STATUSES


def _coverage_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {rotation for rotation in value if isinstance(rotation, int) and not isinstance(rotation, bool)}


def _evidence_present(record: dict[str, Any]) -> bool:
    evidence = record.get("evidence", [])
    return isinstance(evidence, list) and any(_non_empty_string(item) for item in evidence)


def _check(
    passed: bool,
    expected: str,
    *,
    evidence: list[str] | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": evidence or [],
        "blocking": blocking,
    }


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HostDisplayRotationCurrentBaseGateError(
            f"manifest schema violation: {name} must be an object"
        )
    return value


def _require_fields(record: dict[str, Any], fields: set[str], name: str) -> None:
    missing = sorted(field for field in fields if field not in record)
    if missing:
        raise HostDisplayRotationCurrentBaseGateError(
            f"manifest schema violation: {name} missing required field(s): {', '.join(missing)}"
        )


def _validate_record(record: dict[str, Any], name: str) -> None:
    _require_fields(record, REQUIRED_RECORD_FIELDS, name)
    if not isinstance(record.get("evidence"), list):
        raise HostDisplayRotationCurrentBaseGateError(
            f"manifest schema violation: {name}.evidence must be an array"
        )
    if not isinstance(record.get("notes"), list):
        raise HostDisplayRotationCurrentBaseGateError(
            f"manifest schema violation: {name}.notes must be an array"
        )


def _validate_manifest_contract(manifest: dict[str, Any]) -> None:
    _require_fields(
        manifest,
        {
            "schema_version",
            "kind",
            "run_id",
            "created_at",
            "command",
            "repository",
            "source_root",
            "owner",
            "scope_prs",
            "source_docs",
            "local_environment",
            "device",
            "host_preflight",
            "gates",
            "client_local_matrix_used_for_host_rotation",
            "limitations",
            "notes",
        },
        "manifest",
    )
    _require_object(manifest.get("repository"), "repository")
    _require_object(manifest.get("owner"), "owner")
    if not _non_empty_string(manifest.get("source_root")):
        raise HostDisplayRotationCurrentBaseGateError(
            "manifest schema violation: source_root must be a non-empty string"
        )

    device = _require_object(manifest.get("device"), "device")
    _require_fields(
        device,
        {"status", "runtime_class", "package_status", "evidence", "probes", *DEVICE_FIELDS},
        "device",
    )
    if not isinstance(device.get("evidence"), list):
        raise HostDisplayRotationCurrentBaseGateError(
            "manifest schema violation: device.evidence must be an array"
        )
    if not isinstance(device.get("probes"), dict):
        raise HostDisplayRotationCurrentBaseGateError(
            "manifest schema violation: device.probes must be an object"
        )

    host_preflight = _require_object(manifest.get("host_preflight"), "host_preflight")
    _require_fields(host_preflight, set(HOST_PREFLIGHT_CHECKS), "host_preflight")
    for name in HOST_PREFLIGHT_CHECKS:
        record = _require_object(host_preflight.get(name), f"host_preflight.{name}")
        _validate_record(record, f"host_preflight.{name}")

    gates = _require_object(manifest.get("gates"), "gates")
    expected_gates = {*SUPPORTING_GATES, *FORMAL_GATES}
    _require_fields(gates, expected_gates, "gates")
    for name in expected_gates:
        gate = _require_object(gates.get(name), f"gates.{name}")
        _validate_record(gate, f"gates.{name}")
        if name in FORMAL_GATES:
            _require_fields(gate, {"required_host_rotations", "covered_host_rotations"}, f"gates.{name}")
            if not isinstance(gate.get("required_host_rotations"), list):
                raise HostDisplayRotationCurrentBaseGateError(
                    f"manifest schema violation: gates.{name}.required_host_rotations must be an array"
                )
            if not isinstance(gate.get("covered_host_rotations"), list):
                raise HostDisplayRotationCurrentBaseGateError(
                    f"manifest schema violation: gates.{name}.covered_host_rotations must be an array"
                )


def _metadata_checks(manifest: dict[str, Any], manifest_path: Path) -> dict[str, dict[str, Any]]:
    repository = manifest.get("repository") if isinstance(manifest.get("repository"), dict) else {}
    owner = manifest.get("owner") if isinstance(manifest.get("owner"), dict) else {}
    scope_prs = set(_string_list(manifest.get("scope_prs")))
    source_docs = set(_string_list(manifest.get("source_docs")))
    repository_revision = str(repository.get("revision")) if repository.get("revision") else ""
    retained_origin_main_passed, retained_origin_main_evidence = _retained_origin_main_check(manifest_path)
    source_root_value = str(manifest.get("source_root"))
    if source_root_value == REDACTED_SOURCE_ROOT:
        source_root = Path.cwd()
    else:
        source_root = Path(source_root_value).expanduser()
    if not source_root.is_absolute():
        source_root = manifest_path.parent / source_root

    source_doc_exists = []
    for source_doc in SOURCE_DOCS:
        candidate = Path(source_doc)
        if candidate.is_absolute():
            source_doc_exists.append(candidate.is_file())
        else:
            source_doc_exists.append((source_root / candidate).is_file())

    return {
        "repository_current_base": _check(
            _non_empty_string(repository_revision)
            and len(repository_revision) == 40
            and all(character in "0123456789abcdefABCDEF" for character in repository_revision)
            and repository.get("dirty") is False
            and repository.get("status_porcelain") == []
            and retained_origin_main_passed,
            "current-base evidence records a clean repository source revision containing retained origin/main when present",
            evidence=[
                repository_revision or "<missing-revision>",
                f"dirty={repository.get('dirty')}",
                *retained_origin_main_evidence,
            ],
        ),
        "schema_version": _check(manifest.get("schema_version") == SCHEMA_VERSION, SCHEMA_VERSION),
        "kind": _check(manifest.get("kind") == MANIFEST_KIND, MANIFEST_KIND),
        "aggregate_owner": _check(
            owner.get("aggregate") == AGGREGATE_OWNER,
            AGGREGATE_OWNER,
            evidence=[str(owner.get("aggregate"))] if owner.get("aggregate") else [],
        ),
        "aggregate_owner_pr": _check(
            owner.get("aggregate_pr") == AGGREGATE_OWNER_PR,
            f"current-base aggregate owner {AGGREGATE_OWNER_PR}",
            evidence=[str(owner.get("aggregate_pr"))] if owner.get("aggregate_pr") else [],
        ),
        "scope_prs": _check(
            set(SCOPE_PRS).issubset(scope_prs),
            "related PRs #162/#243/#262/#272 are recorded in scope",
            evidence=sorted(scope_prs),
        ),
        "source_docs": _check(
            set(SOURCE_DOCS).issubset(source_docs) and all(source_doc_exists),
            "README, testing guide, runbook, and Phase 1 TEST are referenced and present",
            evidence=sorted(source_docs),
        ),
    }


def _device_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    device = manifest.get("device") if isinstance(manifest.get("device"), dict) else {}
    identity_complete = True
    for field in DEVICE_FIELDS:
        value = device.get(field)
        if field == "sdk":
            identity_complete = identity_complete and isinstance(value, int) and not isinstance(value, bool) and value > 0
        else:
            identity_complete = identity_complete and _non_empty_string(value)
    return {
        "physical_android_device": _check(
            device.get("runtime_class") == "physical_android_device",
            "device is a physical Android device, not simulator or synthetic evidence",
            evidence=[str(device.get("runtime_class"))] if device.get("runtime_class") else [],
            blocking=True,
        ),
        "device_identity": _check(
            device.get("status") == "pass" and identity_complete and _evidence_present(device),
            "manufacturer/model/codename/release/sdk/serial are retained for the device that produced evidence",
            evidence=_string_list(device.get("evidence")),
            blocking=True,
        ),
    }


def _host_preflight_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    host_preflight = manifest.get("host_preflight") if isinstance(manifest.get("host_preflight"), dict) else {}
    checks: dict[str, dict[str, Any]] = {}
    for name, requirement in HOST_PREFLIGHT_CHECKS.items():
        record = host_preflight.get(name) if isinstance(host_preflight.get(name), dict) else {}
        checks[name] = _check(
            _status_pass(record.get("status")) and _evidence_present(record),
            requirement,
            evidence=_string_list(record.get("evidence")),
            blocking=True,
        )
    return checks


def _evidence_gate_check(manifest_path: Path) -> dict[str, Any]:
    evidence_path = manifest_path.parent / EVIDENCE_FILENAME
    evidence_gate_path = manifest_path.parent / EVIDENCE_GATE_FILENAME
    try:
        evidence_document = _load_json(evidence_path, "host display rotation evidence")
        expected_document = evaluate_evidence_gate(
            evidence_document, evidence_dir=manifest_path.parent
        )
        document = _load_json(evidence_gate_path, "host display rotation evidence gate output")
    except HostDisplayRotationCurrentBaseGateError as error:
        return _check(
            False,
            "formal host-display rotation evidence gate output is retained, reproducible, and complete",
            evidence=[str(evidence_path), str(evidence_gate_path)],
            blocking=True,
        ) | {"detail": str(error)}

    covered_by_kind = document.get("covered_host_rotations_by_display_kind")
    if isinstance(covered_by_kind, dict):
        physical = _coverage_set(covered_by_kind.get("physical"))
        virtual = _coverage_set(covered_by_kind.get("virtual"))
    else:
        physical = set()
        virtual = set()
    required = set(REQUIRED_HOST_ROTATIONS)
    expected_required_artifacts = list(REQUIRED_ARTIFACTS)
    expected_required_device_fields = list(REQUIRED_DEVICE_FIELDS)
    expected_required_host_preflight_fields = list(REQUIRED_HOST_PREFLIGHT_FIELDS)
    expected_required_input_mapping_points = list(REQUIRED_INPUT_MAPPING_POINTS)
    expected_required_probes = list(REQUIRED_PROBES)
    expected_required_transports = sorted(VALID_TRANSPORTS)
    errors = document.get("errors")
    recomputed_errors = expected_document.get("errors")
    retained_matches_recomputed = document == expected_document
    passed = (
        retained_matches_recomputed
        and expected_document.get("schema_version") == SCHEMA_VERSION
        and expected_document.get("kind") == EVIDENCE_GATE_KIND
        and expected_document.get("status") == "complete"
        and isinstance(recomputed_errors, list)
        and len(recomputed_errors) == 0
        and document.get("schema_version") == SCHEMA_VERSION
        and document.get("kind") == EVIDENCE_GATE_KIND
        and document.get("status") == "complete"
        and required.issubset(physical)
        and required.issubset(virtual)
        and document.get("required_display_kinds") == ["physical", "virtual"]
        and document.get("required_host_rotations") == REQUIRED_HOST_ROTATIONS
        and document.get("required_input_mapping_points")
        == expected_required_input_mapping_points
        and document.get("required_transports") == expected_required_transports
        and document.get("required_device_fields") == expected_required_device_fields
        and document.get("required_host_preflight_fields")
        == expected_required_host_preflight_fields
        and document.get("required_evidence_source") == EXPECTED_EVIDENCE_SOURCE
        and document.get("required_probes") == expected_required_probes
        and document.get("required_artifacts") == expected_required_artifacts
        and document.get("artifact_file_check") is True
        and isinstance(errors, list)
        and len(errors) == 0
    )
    return _check(
        passed,
        "formal host-display rotation evidence gate output is retained, reproducible, and complete",
        evidence=[str(evidence_path), str(evidence_gate_path)],
        blocking=True,
    ) | {
        "status": document.get("status"),
        "recomputed_status": expected_document.get("status"),
        "retained_matches_recomputed": retained_matches_recomputed,
        "covered_host_rotations_by_display_kind": document.get(
            "covered_host_rotations_by_display_kind"
        ),
    }


def _gate_checks(
    manifest: dict[str, Any], evidence_gate: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    supporting: dict[str, dict[str, Any]] = {}
    formal: dict[str, dict[str, Any]] = {}
    for name, requirement in SUPPORTING_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        supporting[name] = _check(
            _status_pass(record.get("status")) and _evidence_present(record),
            requirement,
            evidence=_string_list(record.get("evidence")),
            blocking=False,
        )
    for name, requirement in FORMAL_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        covered = record.get("covered_host_rotations", [])
        required = record.get("required_host_rotations", REQUIRED_HOST_ROTATIONS)
        covered_set = _coverage_set(covered)
        required_set = (
            _coverage_set(required)
            if isinstance(required, list)
            else set(REQUIRED_HOST_ROTATIONS)
        )
        rotations_passed = (
            set(REQUIRED_HOST_ROTATIONS).issubset(covered_set)
            and required_set == set(REQUIRED_HOST_ROTATIONS)
        )
        formal[name] = _check(
            _status_pass(record.get("status"))
            and rotations_passed
            and _evidence_present(record)
            and evidence_gate.get("passed") is True,
            requirement,
            evidence=_string_list(record.get("evidence")),
            blocking=True,
        )
    return supporting, formal


def _substitution_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "client_local_matrix_not_used_for_host_rotation": _check(
            manifest.get("client_local_matrix_used_for_host_rotation") is False,
            "client-local Fit/Fill/rotation matrix is not used as host display rotation evidence",
            blocking=True,
        )
    }


def _retained_origin_main_check(manifest_path: Path) -> tuple[bool, list[str]]:
    origin_main_path = manifest_path.parent / "git-origin-main.txt"
    if not origin_main_path.exists():
        return True, ["origin_main=<not-retained>"]
    try:
        origin_main = origin_main_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, UnicodeDecodeError, IndexError):
        return False, ["origin_main=<unreadable>"]
    origin_main_valid = (
        len(origin_main) == 40
        and all(character in "0123456789abcdefABCDEF" for character in origin_main)
    )
    ancestor_path = manifest_path.parent / "git-origin-main-ancestor.exit-code"
    try:
        ancestor_exit = ancestor_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, UnicodeDecodeError, IndexError):
        ancestor_exit = "<unreadable>"
    return origin_main_valid and ancestor_exit == "0", [
        f"origin_main={origin_main or '<empty>'}",
        f"origin_main_ancestor_exit={ancestor_exit or '<empty>'}",
    ]


def derive_gate(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = _load_json(manifest_path)
        _validate_manifest_contract(manifest)
    except HostDisplayRotationCurrentBaseGateError as error:
        return _failure_report(manifest_path, str(error))

    metadata = _metadata_checks(manifest, manifest_path)
    device = _device_checks(manifest)
    host_preflight = _host_preflight_checks(manifest)
    evidence_gate = _evidence_gate_check(manifest_path)
    supporting, formal = _gate_checks(manifest, evidence_gate)
    substitutions = _substitution_checks(manifest)

    invalid_substitution = any(not item["passed"] for item in substitutions.values())
    blocking_groups = {
        **device,
        **host_preflight,
        "host_display_rotation_evidence_gate": evidence_gate,
        **formal,
    }
    metadata_missing = [name for name, item in metadata.items() if not item["passed"]]
    blocking_missing = [name for name, item in blocking_groups.items() if not item["passed"]]
    supporting_missing = [name for name, item in supporting.items() if not item["passed"]]

    if invalid_substitution:
        verdict = "fail"
    elif metadata_missing or blocking_missing:
        verdict = "blocked"
    elif supporting_missing:
        verdict = "insufficient"
    else:
        verdict = "pass"

    reasons: list[str] = []
    reasons.extend(f"metadata: {name}" for name in metadata_missing)
    reasons.extend(f"blocked: {name}" for name in blocking_missing)
    reasons.extend(f"fail: {name}" for name, item in substitutions.items() if not item["passed"])
    reasons.extend(f"insufficient: {name}" for name in supporting_missing)

    formal_passed = not metadata_missing and not blocking_missing and not invalid_substitution
    aggregate_passed = formal_passed and not supporting_missing

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "run_id": manifest.get("run_id"),
        "owner": manifest.get("owner"),
        "source": {"manifest": str(manifest_path)},
        "can_close_host_display_rotation_acceptance": formal_passed,
        "can_close_current_base_aggregate": aggregate_passed and verdict == "pass",
        "can_claim_real_device_pass": formal_passed,
        "checks": {
            "metadata": metadata,
            "device": device,
            "host_preflight": host_preflight,
            "supporting_client_local_gate": supporting,
            "host_display_rotation_evidence_gate": evidence_gate,
            "formal_host_display_rotation_gates": formal,
            "evidence_substitution": substitutions,
        },
        "reasons": reasons,
        "interpretation": INTERPRETATION,
    }


def _failure_report(manifest_path: Path, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "failed",
        "verdict": "blocked",
        "run_id": None,
        "owner": None,
        "source": {"manifest": str(manifest_path)},
        "can_close_host_display_rotation_acceptance": False,
        "can_close_current_base_aggregate": False,
        "can_claim_real_device_pass": False,
        "checks": {},
        "reasons": [reason],
        "interpretation": INTERPRETATION,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
    temporary.write_text(payload + chr(10), encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = derive_gate(args.manifest)
    except (HostDisplayRotationCurrentBaseGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.manifest, str(error))
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: host display rotation current-base gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
