#!/usr/bin/env python3
"""Validate recorded evidence for iOS device acceptance.

This gate intentionally evaluates a sanitized ``acceptance.json`` that was
captured from a separately scheduled iPhone/iPad run. It does not invoke Xcode,
start the Host, connect to a network, or touch any Android device.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


ACCEPTANCE_KIND = "ios_device_acceptance"
GATE_KIND = "ios_device_acceptance_gate"
PASS = "pass"
FAIL = "fail"
INSUFFICIENT = "insufficient"
COMPLETE = "complete"
FAILED = "failed"
REQUIRED_DEVICE_ROLES = ("iphone", "ipad")
REQUIRED_GATES = (
    "signing",
    "device_install",
    "protocol_session",
    "videotoolbox_h264",
    "videotoolbox_hevc",
    "input",
    "reconnect",
    "audio_playback",
)
REQUIRED_REPOSITORY_FIELDS = ("commit", "branch", "dirty")
REQUIRED_HOST_FIELDS = ("commit", "macos_version", "permissions_changed_by_run")
REQUIRED_XCODE_FIELDS = ("version", "selected_developer_dir", "ios_sdk")
REQUIRED_TRUSTED_LAN_FIELDS = ("mode", "encrypted_lan_claimed")
REQUIRED_SIGNING_FIELDS = (
    "status",
    "bundle_id",
    "team_id_redacted",
    "certificate_common_name_redacted",
    "provisioning_profile_uuid_redacted",
    "archive_sha256",
)
REQUIRED_DEVICE_FIELDS = (
    "role",
    "product_name",
    "hardware_model",
    "os_version",
    "build_number",
    "install_status",
)
ANDROID_MARKERS = (
    "android",
    "nubia",
    "p0110",
    "pacific",
    "xiaomi",
    "fuxi",
)
ANDROID_TOKEN_MARKERS = ("adb", "apk")
ANDROID_TOKEN_PATTERN = re.compile(
    r"(?<![0-9a-z])(?:" + "|".join(ANDROID_TOKEN_MARKERS) + r")(?![0-9a-z])"
)
SIMULATOR_MARKERS = ("simulator", "iphonesimulator")
UNSIGNED_MARKERS = ("unsigned", "simulator", "ad-hoc", "adhoc")
DEFAULT_BUNDLE_ID = "dev.vibescreen.ios"
TRUSTED_LAN_MODE = "explicit_plaintext_legacy_fallback"
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SIGNING_READINESS_GATE_KIND = "ios_app_signing_readiness_gate"
SIGNING_READINESS_OWNER_ROLE = "ios_app_signing_readiness_current_base_owner"
SIGNING_READINESS_OWNER_BRANCH = "codex/phase5-ios-signing-readiness"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
REQUIRED_SIGNING_READINESS_FIELDS = (
    "schema_version",
    "kind",
    "owner",
    "source",
    "current_base",
    "verdict",
    "signing_status",
    "signing_summary",
    "can_close_ios_app_signing_readiness",
    "can_close_ios_device_acceptance",
    "recorded_fields",
    "missing",
    "failures",
    "evidence",
    "interpretation",
)
REQUIRED_SIGNING_SUMMARY_FIELDS = (
    "status",
    "bundle_id",
    "unique_bundle_id",
    "team_id_recorded",
    "codesign_identity_recorded",
    "provisioning_profile_recorded",
    "device_udid_hashes_recorded",
    "entitlements_recorded",
    "signed_artifact_sha256",
)
REQUIRED_SIGNING_RECORDED_FIELDS = (
    "team_id",
    "provisioning_profile",
    "bundle_id",
    "codesign_identity",
    "device_udid",
    "entitlements",
    "signed_artifact",
    "artifacts",
)
INTERPRETATION = (
    "A pass means the supplied sanitized acceptance.json records complete "
    "iPhone and iPad device evidence for the listed gates and embeds a passing "
    "dedicated iOS app-signing readiness gate. It does not prove HDR output, "
    "advanced host adapters, Internet audio/bulk transport, or any behavior not "
    "represented by retained evidence artifacts."
)


class IOSDeviceAcceptanceGateError(ValueError):
    """Raised when the acceptance input cannot be parsed."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_json(input_path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            input_path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise IOSDeviceAcceptanceGateError(
            f"could not read {input_path}: {error}"
        ) from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise IOSDeviceAcceptanceGateError(f"invalid JSON in {input_path}: {error}") from error
    if not isinstance(document, dict):
        raise IOSDeviceAcceptanceGateError("top-level acceptance evidence must be an object")
    return document


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _append_missing_string(
    messages: list[str], record: dict[str, Any], path: str, field: str
) -> None:
    value = record.get(field)
    if not _is_non_empty_string(value):
        messages.append(f"{path}.{field}: must be a non-empty string")


def _contains_android_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in ANDROID_MARKERS):
        return True
    return ANDROID_TOKEN_PATTERN.search(lowered) is not None


def _contains_marker(value: Any, markers: Sequence[str]) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in markers)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value.strip()) is not None


def _normalized_sha256(value: Any) -> str | None:
    if not _is_sha256(value):
        return None
    digest = str(value).strip()
    if digest.lower().startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    return digest.lower()


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _artifact_path(reference: str, evidence_root: Path) -> Path:
    artifact = reference.split("#", 1)[0].strip()
    if not artifact:
        return evidence_root / ""
    path = Path(artifact)
    return path if path.is_absolute() else evidence_root / path


def _validate_artifact_reference(
    *,
    reference: Any,
    evidence_root: Path,
    path: str,
    missing: list[str],
    failures: list[str],
) -> None:
    if not _is_non_empty_string(reference):
        missing.append(f"{path}: must reference a retained artifact path")
        return

    if _contains_android_marker(reference):
        failures.append(f"{path}: must not reference Android evidence for an iOS gate")
    if _contains_marker(reference, SIMULATOR_MARKERS):
        failures.append(f"{path}: must not reference Simulator evidence for an iOS gate")

    artifact_path = _artifact_path(reference, evidence_root)
    if not _is_path_within(artifact_path, evidence_root):
        missing.append(f"{path}: must stay within the evidence root")
        return
    if not artifact_path.is_file():
        missing.append(f"{path}: missing retained artifact {reference}")


def _require_object(
    document: dict[str, Any], field: str, missing: list[str]
) -> dict[str, Any] | None:
    value = document.get(field)
    if not isinstance(value, dict):
        missing.append(f"{field}: must be an object")
        return None
    return value


def _validate_repository(document: dict[str, Any], missing: list[str]) -> None:
    repository = _require_object(document, "repository", missing)
    if repository is None:
        return
    for field in REQUIRED_REPOSITORY_FIELDS:
        if field != "dirty":
            _append_missing_string(missing, repository, "repository", field)
    if not isinstance(repository.get("dirty"), bool):
        missing.append("repository.dirty: must be boolean")


def _validate_host(document: dict[str, Any], missing: list[str], failures: list[str]) -> None:
    host = _require_object(document, "host", missing)
    if host is None:
        return
    for field in REQUIRED_HOST_FIELDS:
        if field != "permissions_changed_by_run":
            _append_missing_string(missing, host, "host", field)
    if not isinstance(host.get("permissions_changed_by_run"), bool):
        missing.append("host.permissions_changed_by_run: must be boolean")
    elif host["permissions_changed_by_run"] is True:
        failures.append("host.permissions_changed_by_run: must be false for this acceptance runbook")


def _validate_xcode(document: dict[str, Any], missing: list[str]) -> None:
    xcode = _require_object(document, "xcode", missing)
    if xcode is None:
        return
    for field in REQUIRED_XCODE_FIELDS:
        _append_missing_string(missing, xcode, "xcode", field)


def _validate_trusted_lan(
    document: dict[str, Any], missing: list[str], failures: list[str]
) -> None:
    trusted_lan = _require_object(document, "trusted_lan", missing)
    if trusted_lan is None:
        return
    for field in REQUIRED_TRUSTED_LAN_FIELDS:
        if field != "encrypted_lan_claimed":
            _append_missing_string(missing, trusted_lan, "trusted_lan", field)
    if trusted_lan.get("mode") != TRUSTED_LAN_MODE:
        failures.append(f"trusted_lan.mode: must be {TRUSTED_LAN_MODE}")
    if trusted_lan.get("encrypted_lan_claimed") is not False:
        failures.append("trusted_lan.encrypted_lan_claimed: must be false")


def _validate_signing(
    document: dict[str, Any], missing: list[str], failures: list[str]
) -> None:
    signing = _require_object(document, "signing", missing)
    if signing is None:
        return
    for field in REQUIRED_SIGNING_FIELDS:
        if not field.endswith("_redacted"):
            _append_missing_string(missing, signing, "signing", field)

    if signing.get("status") != COMPLETE:
        missing.append("signing.status: must be complete")
    bundle_id = signing.get("bundle_id")
    if bundle_id == DEFAULT_BUNDLE_ID:
        missing.append("signing.bundle_id: must be a unique non-default bundle identifier")
    if _contains_marker(signing.get("archive_sha256"), UNSIGNED_MARKERS):
        failures.append(
            "signing.archive_sha256: must not reference unsigned, Simulator, or ad-hoc artifacts"
        )
    if not _is_sha256(signing.get("archive_sha256")):
        missing.append("signing.archive_sha256: must be a SHA-256 digest")
    for field in (
        "team_id_redacted",
        "certificate_common_name_redacted",
        "provisioning_profile_uuid_redacted",
    ):
        if signing.get(field) is not True:
            failures.append(f"signing.{field}: must be true in committed sanitized evidence")


def _require_gate_object(
    record: dict[str, Any], field: str, path: str, missing: list[str]
) -> dict[str, Any] | None:
    value = record.get(field)
    if not isinstance(value, dict):
        missing.append(f"{path}.{field}: must be an object")
        return None
    return value


def _validate_signing_readiness_gate(
    document: dict[str, Any], missing: list[str], failures: list[str]
) -> None:
    gate = _require_object(document, "signing_readiness_gate", missing)
    if gate is None:
        return

    for field in REQUIRED_SIGNING_READINESS_FIELDS:
        if field not in gate:
            missing.append(f"signing_readiness_gate.{field}: must be recorded")

    if gate.get("schema_version") != SCHEMA_VERSION:
        missing.append(f"signing_readiness_gate.schema_version: must be {SCHEMA_VERSION}")
    if gate.get("kind") != SIGNING_READINESS_GATE_KIND:
        failures.append(
            f"signing_readiness_gate.kind: must be {SIGNING_READINESS_GATE_KIND}"
        )
    if gate.get("verdict") == FAIL:
        failures.append("signing_readiness_gate.verdict: is fail")
    elif gate.get("verdict") != PASS:
        missing.append("signing_readiness_gate.verdict: must be pass")
    if gate.get("can_close_ios_app_signing_readiness") is not True:
        missing.append(
            "signing_readiness_gate.can_close_ios_app_signing_readiness: must be true"
        )
    if gate.get("can_close_ios_device_acceptance") is not False:
        failures.append("signing_readiness_gate.can_close_ios_device_acceptance: must be false")

    owner = _require_gate_object(gate, "owner", "signing_readiness_gate", missing)
    if owner is not None:
        expected_owner = {
            "role": SIGNING_READINESS_OWNER_ROLE,
            "head_ref": SIGNING_READINESS_OWNER_BRANCH,
            "repository": REPOSITORY_FULL_NAME,
        }
        for field, expected in expected_owner.items():
            if owner.get(field) != expected:
                failures.append(f"signing_readiness_gate.owner.{field}: must be {expected}")
        _append_missing_string(missing, owner, "signing_readiness_gate.owner", "scope")

    source = _require_gate_object(gate, "source", "signing_readiness_gate", missing)
    if source is not None:
        readiness = source.get("readiness")
        if readiness is not None and not _is_non_empty_string(readiness):
            missing.append(
                "signing_readiness_gate.source.readiness: must be null or a non-empty string"
            )
        _append_missing_string(
            missing, source, "signing_readiness_gate.source", "evidence_root"
        )

    repository = document.get("repository") if isinstance(document.get("repository"), dict) else {}
    current_base = _require_gate_object(
        gate, "current_base", "signing_readiness_gate", missing
    )
    if current_base is not None:
        commit = current_base.get("commit")
        repository_commit = repository.get("commit")
        if not _is_non_empty_string(commit) or COMMIT_PATTERN.fullmatch(str(commit).strip()) is None:
            missing.append(
                "signing_readiness_gate.current_base.commit: must be a 40-character commit SHA"
            )
        elif not _is_non_empty_string(repository_commit) or str(commit).strip().lower() != str(
            repository_commit
        ).strip().lower():
            missing.append(
                "signing_readiness_gate.current_base.commit: must match repository.commit"
            )
        _append_missing_string(missing, current_base, "signing_readiness_gate.current_base", "branch")
        if current_base.get("dirty") is not False:
            missing.append("signing_readiness_gate.current_base.dirty: must be false")
        if repository.get("dirty") is not False:
            missing.append("repository.dirty: must be false when binding signing readiness")

    signing_summary = _require_gate_object(
        gate, "signing_summary", "signing_readiness_gate", missing
    )
    if signing_summary is not None:
        for field in REQUIRED_SIGNING_SUMMARY_FIELDS:
            if field not in signing_summary:
                missing.append(f"signing_readiness_gate.signing_summary.{field}: must be recorded")
        if signing_summary.get("status") != PASS:
            missing.append("signing_readiness_gate.signing_summary.status: must be pass")
        _append_missing_string(
            missing, signing_summary, "signing_readiness_gate.signing_summary", "bundle_id"
        )
        if signing_summary.get("unique_bundle_id") is not True:
            missing.append("signing_readiness_gate.signing_summary.unique_bundle_id: must be true")
        for field in (
            "team_id_recorded",
            "codesign_identity_recorded",
            "provisioning_profile_recorded",
            "device_udid_hashes_recorded",
            "entitlements_recorded",
        ):
            if signing_summary.get(field) is not True:
                missing.append(f"signing_readiness_gate.signing_summary.{field}: must be true")
        if not _is_sha256(signing_summary.get("signed_artifact_sha256")):
            missing.append(
                "signing_readiness_gate.signing_summary.signed_artifact_sha256: must be a SHA-256 digest"
            )

    recorded_fields = _require_gate_object(
        gate, "recorded_fields", "signing_readiness_gate", missing
    )
    if recorded_fields is not None:
        for field in REQUIRED_SIGNING_RECORDED_FIELDS:
            if recorded_fields.get(field) is not True:
                missing.append(f"signing_readiness_gate.recorded_fields.{field}: must be true")

    gate_missing = gate.get("missing")
    if not isinstance(gate_missing, list) or gate_missing:
        missing.append("signing_readiness_gate.missing: must be an empty array")
    gate_failures = gate.get("failures")
    if not isinstance(gate_failures, list) or gate_failures:
        failures.append("signing_readiness_gate.failures: must be an empty array")

    gate_evidence = gate.get("evidence")
    if not isinstance(gate_evidence, list) or not gate_evidence:
        missing.append("signing_readiness_gate.evidence: must include retained signing artifacts")
    _append_missing_string(missing, gate, "signing_readiness_gate", "interpretation")

    signing = document.get("signing") if isinstance(document.get("signing"), dict) else {}
    if isinstance(signing_summary, dict) and isinstance(signing, dict):
        expected_matches = {
            "bundle_id": (signing.get("bundle_id"), signing_summary.get("bundle_id")),
            "team_id_redacted": (
                signing.get("team_id_redacted"),
                signing_summary.get("team_id_recorded"),
            ),
            "certificate_common_name_redacted": (
                signing.get("certificate_common_name_redacted"),
                signing_summary.get("codesign_identity_recorded"),
            ),
            "provisioning_profile_uuid_redacted": (
                signing.get("provisioning_profile_uuid_redacted"),
                signing_summary.get("provisioning_profile_recorded"),
            ),
        }
        for field, (actual, expected) in expected_matches.items():
            if actual != expected:
                missing.append(f"signing.{field}: must match signing_readiness_gate summary")
        if _normalized_sha256(signing.get("archive_sha256")) != _normalized_sha256(
            signing_summary.get("signed_artifact_sha256")
        ):
            missing.append(
                "signing.archive_sha256: must match signing_readiness_gate signed artifact digest"
            )


def _validate_devices(
    document: dict[str, Any], missing: list[str], failures: list[str]
) -> list[str]:
    devices = document.get("devices")
    covered_roles: set[str] = set()
    if not isinstance(devices, list) or not devices:
        missing.append("devices: must contain iPhone and iPad records")
        return []

    for index, device in enumerate(devices):
        path = f"devices[{index}]"
        if not isinstance(device, dict):
            missing.append(f"{path}: must be an object")
            continue
        for field in REQUIRED_DEVICE_FIELDS:
            _append_missing_string(missing, device, path, field)

        role = device.get("role")
        if role not in REQUIRED_DEVICE_ROLES:
            missing.append(f"{path}.role: must be iphone or ipad")
        else:
            covered_roles.add(role)

        if device.get("install_status") != COMPLETE:
            missing.append(f"{path}.install_status: must be complete")

        for field, value in device.items():
            if _contains_android_marker(value):
                failures.append(f"{path}.{field}: looks like Android evidence")
            if _contains_marker(value, SIMULATOR_MARKERS):
                failures.append(f"{path}.{field}: must be physical iOS hardware, not Simulator")

    for role in REQUIRED_DEVICE_ROLES:
        if role not in covered_roles:
            missing.append(f"devices: missing {role} hardware evidence")
    return sorted(covered_roles)


def _validate_gates(
    *,
    document: dict[str, Any],
    evidence_root: Path,
    missing: list[str],
    failures: list[str],
) -> list[str]:
    gates = document.get("gates")
    completed: list[str] = []
    if not isinstance(gates, dict):
        missing.append("gates: must be an object")
        return completed

    for name in REQUIRED_GATES:
        path = f"gates.{name}"
        gate = gates.get(name)
        if not isinstance(gate, dict):
            missing.append(f"{path}: must be an object")
            continue
        status = gate.get("status")
        if status == FAILED:
            failures.append(f"{path}.status: is failed")
        elif status != COMPLETE:
            missing.append(f"{path}.status: must be complete")
        else:
            completed.append(name)

        evidence = gate.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            missing.append(f"{path}.evidence: must be a non-empty artifact list")
            continue
        for index, reference in enumerate(evidence):
            _validate_artifact_reference(
                reference=reference,
                evidence_root=evidence_root,
                path=f"{path}.evidence[{index}]",
                missing=missing,
                failures=failures,
            )

    for name in sorted(set(gates) - set(REQUIRED_GATES)):
        if not isinstance(gates.get(name), dict):
            missing.append(f"gates.{name}: optional gates must be objects")
    return completed


def evaluate(document: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    missing: list[str] = []
    failures: list[str] = []

    if document.get("schema_version") != SCHEMA_VERSION:
        missing.append(f"schema_version: must be {SCHEMA_VERSION}")
    if document.get("kind") != ACCEPTANCE_KIND:
        missing.append(f"kind: must be {ACCEPTANCE_KIND}")
    if document.get("platform") != "ios":
        missing.append("platform: must be ios")
    if document.get("status") == FAILED:
        failures.append("status: is failed")
    elif document.get("status") != COMPLETE:
        missing.append("status: must be complete")
    if document.get("android_evidence_used_for_ios_gates") is not False:
        failures.append("android_evidence_used_for_ios_gates: must be false")

    _validate_repository(document, missing)
    _validate_host(document, missing, failures)
    _validate_xcode(document, missing)
    _validate_trusted_lan(document, missing, failures)
    _validate_signing(document, missing, failures)
    _validate_signing_readiness_gate(document, missing, failures)
    covered_devices = _validate_devices(document, missing, failures)
    completed_gates = _validate_gates(
        document=document,
        evidence_root=evidence_root,
        missing=missing,
        failures=failures,
    )

    verdict = PASS
    if failures:
        verdict = FAIL
    elif missing:
        verdict = INSUFFICIENT
    acceptance_status = document.get("status")
    if not isinstance(acceptance_status, str):
        acceptance_status = None

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "verdict": verdict,
        "acceptance_status": acceptance_status,
        "covered_devices": covered_devices,
        "required_devices": list(REQUIRED_DEVICE_ROLES),
        "completed_gates": completed_gates,
        "required_gates": list(REQUIRED_GATES),
        "missing": missing,
        "failures": failures,
        "interpretation": INTERPRETATION,
    }


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acceptance",
        type=Path,
        required=True,
        help="sanitized iOS acceptance.json captured from the device run",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="directory that contains artifact paths referenced by acceptance.json",
    )
    parser.add_argument("--output", type=Path, help="write gate result JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        acceptance_path = args.acceptance.resolve()
        evidence_root = (args.evidence_root or acceptance_path.parent).resolve()
        result = evaluate(_parse_json(acceptance_path), evidence_root)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (IOSDeviceAcceptanceGateError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    for item in result["failures"]:
        print(f"error: {item}", file=sys.stderr)
    for item in result["missing"]:
        print(f"error: {item}", file=sys.stderr)

    if result["verdict"] == PASS:
        return 0
    if result["verdict"] == FAIL:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
