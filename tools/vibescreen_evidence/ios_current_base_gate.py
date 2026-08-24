"""Evaluate the iOS current-base aggregate acceptance readiness gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .ios_current_base_manifest import (
    AGGREGATE_OWNER_PR,
    AGGREGATE_OWNER,
    BROADER_GATES,
    DEVICE_ACCEPTANCE_OWNER_PR,
    FORMAL_DEVICE_GATES,
    KIND as MANIFEST_KIND,
    SCOPE_PRS,
    SOURCE_DOCS,
)

GATE_KIND = "ios_current_base_readiness_gate"
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PASS_STATUSES = {"pass", "passed", "passed-offline"}
OPEN_STATUSES = {"open", "blocked", "blocked-readiness", "not-evidence"}
DEVICE_ROLES = {"iphone", "ipad"}
HDR_OWNER_EVIDENCE_MARKERS = ("ios-hdr-edr-gate", "can_close_ios_hdr_output_gate=true")
REQUIRED_SIGNING_FIELDS = {
    "status",
    "bundle_id",
    "unique_bundle_id",
    "team_id_redacted",
    "certificate_identity_recorded",
    "provisioning_profile_recorded",
    "signed_archive_sha256",
}
REQUIRED_DEVICE_FIELDS = {"role", "runtime_class", "install_status", "evidence"}
REQUIRED_GATE_FIELDS = {
    "status",
    "category",
    "requirement",
    "blocking",
    "evidence",
    "notes",
}

INTERPRETATION = (
    "A pass means the current-base iOS aggregate has signed iPhone and iPad "
    "device evidence for the formal acceptance gates plus reviewed broader "
    "Phase 5 gates. Simulator, unsigned archive, MacHost loopback, Android, "
    "and plaintext legacy-fallback evidence remain readiness only."
)


class IOSCurrentBaseGateError(ValueError):
    """Raised when an aggregate manifest cannot be evaluated."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IOSCurrentBaseGateError(f"cannot read iOS current-base manifest: {error}") from error
    if not isinstance(document, dict):
        raise IOSCurrentBaseGateError("iOS current-base manifest must be a JSON object")
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _status_pass(value: Any) -> bool:
    return isinstance(value, str) and value in PASS_STATUSES


def _status_open(value: Any) -> bool:
    return not isinstance(value, str) or value in OPEN_STATUSES


def _evidence_present(record: dict[str, Any]) -> bool:
    evidence = record.get("evidence", [])
    return isinstance(evidence, list) and any(_non_empty_string(item) for item in evidence)


def _hdr_owner_evidence_present(record: dict[str, Any]) -> bool:
    evidence = _string_list(record.get("evidence"))
    joined = "\n".join(evidence)
    return all(marker in joined for marker in HDR_OWNER_EVIDENCE_MARKERS)


def _check(passed: bool, expected: str, *, evidence: list[str] | None = None, blocking: bool = False) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": evidence or [],
        "blocking": blocking,
    }


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IOSCurrentBaseGateError(
            f"manifest schema violation: {name} must be an object"
        )
    return value


def _require_fields(record: dict[str, Any], fields: set[str], name: str) -> None:
    missing = sorted(field for field in fields if field not in record)
    if missing:
        raise IOSCurrentBaseGateError(
            f"manifest schema violation: {name} missing required field(s): {', '.join(missing)}"
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
            "build_evidence",
            "signing",
            "devices",
            "gates",
            "android_evidence_used_for_ios_gates",
            "limitations",
            "notes",
        },
        "manifest",
    )
    _require_object(manifest.get("repository"), "repository")
    _require_object(manifest.get("owner"), "owner")

    source_root = manifest.get("source_root")
    if not _non_empty_string(source_root):
        raise IOSCurrentBaseGateError(
            "manifest schema violation: source_root must be a non-empty string"
        )

    signing = _require_object(manifest.get("signing"), "signing")
    _require_fields(signing, REQUIRED_SIGNING_FIELDS, "signing")

    devices = manifest.get("devices")
    if not isinstance(devices, list):
        raise IOSCurrentBaseGateError("manifest schema violation: devices must be an array")
    for index, device in enumerate(devices):
        device_record = _require_object(device, f"devices[{index}]")
        _require_fields(device_record, REQUIRED_DEVICE_FIELDS, f"devices[{index}]")
        if not isinstance(device_record.get("evidence"), list):
            raise IOSCurrentBaseGateError(
                f"manifest schema violation: devices[{index}].evidence must be an array"
            )

    gates = _require_object(manifest.get("gates"), "gates")
    expected_gates = {*FORMAL_DEVICE_GATES, *BROADER_GATES}
    _require_fields(gates, expected_gates, "gates")
    for name in sorted(expected_gates):
        gate_record = _require_object(gates.get(name), f"gates.{name}")
        _require_fields(gate_record, REQUIRED_GATE_FIELDS, f"gates.{name}")
        if not isinstance(gate_record.get("evidence"), list):
            raise IOSCurrentBaseGateError(
                f"manifest schema violation: gates.{name}.evidence must be an array"
            )
        if not isinstance(gate_record.get("notes"), list):
            raise IOSCurrentBaseGateError(
                f"manifest schema violation: gates.{name}.notes must be an array"
            )


def _metadata_checks(manifest: dict[str, Any], manifest_path: Path) -> dict[str, dict[str, Any]]:
    owner = manifest.get("owner") if isinstance(manifest.get("owner"), dict) else {}
    scope_prs = set(_string_list(manifest.get("scope_prs")))
    source_docs = set(_string_list(manifest.get("source_docs")))
    source_root = Path(str(manifest.get("source_root"))).expanduser()
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
        "schema_version": _check(
            manifest.get("schema_version") == SCHEMA_VERSION,
            SCHEMA_VERSION,
        ),
        "kind": _check(
            manifest.get("kind") == MANIFEST_KIND,
            MANIFEST_KIND,
        ),
        "aggregate_owner": _check(
            owner.get("aggregate") == AGGREGATE_OWNER,
            AGGREGATE_OWNER,
            evidence=[str(owner.get("aggregate"))] if owner.get("aggregate") else [],
        ),
        "aggregate_owner_pr": _check(
            owner.get("aggregate_pr") == AGGREGATE_OWNER_PR,
            f"current-base aggregate owner {AGGREGATE_OWNER_PR}",
            evidence=[str(owner.get("aggregate_pr"))]
            if owner.get("aggregate_pr")
            else [],
        ),
        "device_acceptance_owner": _check(
            owner.get("device_acceptance_pr") == DEVICE_ACCEPTANCE_OWNER_PR,
            f"device acceptance evidence owner {DEVICE_ACCEPTANCE_OWNER_PR}",
            evidence=[str(owner.get("device_acceptance_pr"))]
            if owner.get("device_acceptance_pr")
            else [],
        ),
        "scope_prs": _check(
            set(SCOPE_PRS).issubset(scope_prs),
            "all current-base iOS PRs are in scope",
            evidence=sorted(scope_prs),
        ),
        "source_docs": _check(
            set(SOURCE_DOCS).issubset(source_docs) and all(source_doc_exists),
            "Phase 5 PRD/TECH/TEST and iOS device runbook are referenced and present",
            evidence=sorted(source_docs),
        ),
    }


def _signing_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    signing = manifest.get("signing") if isinstance(manifest.get("signing"), dict) else {}
    archive_sha = signing.get("signed_archive_sha256")
    archive_ok = isinstance(archive_sha, str) and HASH_RE.fullmatch(archive_sha) is not None
    return {
        "signing_status": _check(
            signing.get("status") == "pass",
            "signing.status is pass",
            evidence=[str(signing.get("status"))] if signing.get("status") else [],
            blocking=True,
        ),
        "unique_bundle_id": _check(
            signing.get("unique_bundle_id") is True,
            "unique development bundle ID recorded",
            blocking=True,
        ),
        "certificate_identity_recorded": _check(
            signing.get("certificate_identity_recorded") is True,
            "redacted signing certificate identity recorded",
            blocking=True,
        ),
        "provisioning_profile_recorded": _check(
            signing.get("provisioning_profile_recorded") is True,
            "redacted provisioning profile UUID recorded",
            blocking=True,
        ),
        "signed_archive_sha256": _check(
            archive_ok,
            "signed archive SHA-256 is a 64-character hex digest",
            evidence=[archive_sha] if isinstance(archive_sha, str) else [],
            blocking=True,
        ),
    }


def _environment_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    environment = (
        manifest.get("local_environment")
        if isinstance(manifest.get("local_environment"), dict)
        else {}
    )
    xcodebuild = (
        environment.get("xcodebuild_version")
        if isinstance(environment.get("xcodebuild_version"), dict)
        else {}
    )
    sdks = (
        environment.get("xcode_sdks")
        if isinstance(environment.get("xcode_sdks"), dict)
        else {}
    )
    sdk_summary = _string_list(sdks.get("summary"))
    has_ios_sdk = any("iphoneos" in line.lower() for line in sdk_summary)
    return {
        "xcodebuild_available": _check(
            xcodebuild.get("status") == "pass",
            "full Xcode xcodebuild is available",
            evidence=_string_list(xcodebuild.get("summary")),
            blocking=True,
        ),
        "ios_sdk_available": _check(
            sdks.get("status") == "pass" and has_ios_sdk,
            "xcodebuild -showsdks lists an iPhoneOS SDK",
            evidence=sdk_summary,
            blocking=True,
        ),
    }


def _device_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    devices = manifest.get("devices") if isinstance(manifest.get("devices"), list) else []
    by_role = {device.get("role"): device for device in devices if isinstance(device, dict)}
    checks: dict[str, dict[str, Any]] = {}
    for role in sorted(DEVICE_ROLES):
        device = by_role.get(role) if isinstance(by_role.get(role), dict) else {}
        runtime_class = device.get("runtime_class")
        install_status = device.get("install_status")
        evidence = _string_list(device.get("evidence"))
        checks[f"{role}_physical_device"] = _check(
            runtime_class == "physical_device",
            f"{role} evidence comes from physical iOS hardware",
            evidence=[str(runtime_class)] if runtime_class else evidence,
            blocking=True,
        )
        checks[f"{role}_install"] = _check(
            install_status == "pass" and bool(evidence),
            f"{role} signed install/launch evidence retained",
            evidence=evidence,
            blocking=True,
        )
    return checks


def _gate_checks(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    formal: dict[str, dict[str, Any]] = {}
    broader: dict[str, dict[str, Any]] = {}
    for name, requirement in FORMAL_DEVICE_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        formal[name] = _check(
            _status_pass(record.get("status")) and _evidence_present(record),
            requirement,
            evidence=_string_list(record.get("evidence")),
            blocking=True,
        )
    for name, requirement in BROADER_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        has_required_evidence = _evidence_present(record)
        if name == "hdr_output":
            has_required_evidence = _hdr_owner_evidence_present(record)
        broader[name] = _check(
            _status_pass(record.get("status")) and has_required_evidence,
            requirement,
            evidence=_string_list(record.get("evidence")),
            blocking=False,
        )
    return formal, broader


def _substitution_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    devices = manifest.get("devices") if isinstance(manifest.get("devices"), list) else []
    invalid_runtime_roles: list[str] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        runtime_class = device.get("runtime_class")
        if runtime_class in {"android", "simulator"}:
            invalid_runtime_roles.append(str(device.get("role", "unknown")))
    return {
        "no_android_evidence_for_ios": _check(
            manifest.get("android_evidence_used_for_ios_gates") is not True,
            "Android evidence is not used for iOS gates",
            blocking=True,
        ),
        "no_simulator_or_android_device_substitution": _check(
            not invalid_runtime_roles,
            "device records are missing or physical iOS hardware only",
            evidence=invalid_runtime_roles,
            blocking=True,
        ),
    }


def derive_gate(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = _load_json(manifest_path)
        _validate_manifest_contract(manifest)
    except IOSCurrentBaseGateError as error:
        return _failure_report(manifest_path, str(error))
    metadata = _metadata_checks(manifest, manifest_path)
    environment = _environment_checks(manifest)
    signing = _signing_checks(manifest)
    devices = _device_checks(manifest)
    formal, broader = _gate_checks(manifest)
    substitutions = _substitution_checks(manifest)

    invalid_substitution = any(not item["passed"] for item in substitutions.values())
    blocking_groups = {**environment, **signing, **devices, **formal}
    blocking_missing = [name for name, item in blocking_groups.items() if not item["passed"]]
    metadata_missing = [name for name, item in metadata.items() if not item["passed"]]
    broader_missing = [name for name, item in broader.items() if not item["passed"]]

    if invalid_substitution:
        verdict = "fail"
    elif metadata_missing or blocking_missing:
        verdict = "blocked"
    elif broader_missing:
        verdict = "insufficient"
    else:
        verdict = "pass"

    reasons: list[str] = []
    reasons.extend(f"metadata: {name}" for name in metadata_missing)
    reasons.extend(f"blocked: {name}" for name in blocking_missing)
    reasons.extend(
        f"fail: {name}" for name, item in substitutions.items() if not item["passed"]
    )
    reasons.extend(f"insufficient: {name}" for name in broader_missing)

    formal_passed = not metadata_missing and not blocking_missing and not invalid_substitution
    aggregate_passed = formal_passed and not broader_missing

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "run_id": manifest.get("run_id"),
        "owner": manifest.get("owner"),
        "source": {"manifest": str(manifest_path)},
        "can_close_ios_device_acceptance": formal_passed,
        "can_close_current_base_aggregate": aggregate_passed and verdict == "pass",
        "can_claim_device_pass": formal_passed,
        "checks": {
            "metadata": metadata,
            "environment": environment,
            "signing": signing,
            "devices": devices,
            "formal_device_gates": formal,
            "broader_phase5_gates": broader,
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
        "can_close_ios_device_acceptance": False,
        "can_close_current_base_aggregate": False,
        "can_claim_device_pass": False,
        "checks": {},
        "reasons": [reason],
        "interpretation": INTERPRETATION,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = derive_gate(args.manifest)
    except (IOSCurrentBaseGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.manifest, str(error))
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: iOS current-base gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
