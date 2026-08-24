#!/usr/bin/env python3
"""Validate iOS app-signing readiness evidence.

This gate is intentionally passive. It evaluates a sanitized JSON summary from
an operator-controlled Xcode signing/archive check and fails closed when any
critical signing material is absent. It does not invoke Xcode, install an app,
or operate an iPhone/iPad.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


READINESS_KIND = "ios_app_signing_readiness"
GATE_KIND = "ios_app_signing_readiness_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
COMPLETE = "complete"
FAILED = "failed"
DEFAULT_BUNDLE_ID = "dev.vibescreen.ios"
OWNER_ROLE = "ios_app_signing_readiness_current_base_owner"
OWNER_BRANCH = "codex/phase5-ios-signing-readiness"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
UDID_HASH_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
TEAM_ID_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
PROFILE_UUID_PATTERN = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
PLACEHOLDERS = {"", "unknown", "todo", "tbd", "none", "null", "redacted", "not set"}
BAD_MARKERS = ("simulator", "iphonesimulator", "unsigned", "ad-hoc", "adhoc")
ANDROID_MARKERS = ("android", "adb", "apk", "nubia", "p0110", "pacific", "xiaomi", "fuxi")
REQUIRED_FALSE_FLAGS = (
    "simulator_build",
    "unsigned_build",
    "android_evidence_used_for_ios_signing",
)

REQUIRED_REPOSITORY_FIELDS = ("commit", "branch", "dirty")
REQUIRED_XCODE_FIELDS = ("version", "selected_developer_dir", "ios_sdk")
REQUIRED_SIGNING_FIELDS = (
    "team_id",
    "provisioning_profile_uuid",
    "bundle_id",
    "codesign_identity",
    "device_udids",
    "entitlements",
    "signed_artifact_sha256",
)
REQUIRED_ENTITLEMENTS_FIELDS = (
    "application_identifier",
    "team_identifier",
    "bundle_identifier",
    "keychain_access_groups",
    "raw_entitlements_sha256",
)

INTERPRETATION = (
    "A pass means retained signing-readiness evidence records Team ID, "
    "provisioning profile UUID, unique bundle ID, non-ad-hoc codesign "
    "identity, registered physical-device UDID hashes, and signed-app "
    "entitlements for an iPhoneOS artifact. It is not an install, launch, "
    "VideoToolbox, input, reconnect, audio, or full iOS device-acceptance pass."
)
REQUIRED_ARTIFACT_MARKERS = {
    "archive_command": ("archive", "xcodebuild"),
    "codesign_entitlements": ("codesign", "entitlement"),
    "provisioning_profile": ("profile", "provision"),
}


class IOSAppSigningReadinessError(ValueError):
    """Raised when the readiness input cannot be parsed."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_json(input_path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            input_path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise IOSAppSigningReadinessError(f"could not read {input_path}: {error}") from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise IOSAppSigningReadinessError(f"invalid JSON in {input_path}: {error}") from error
    if not isinstance(document, dict):
        raise IOSAppSigningReadinessError("top-level readiness evidence must be an object")
    return document


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_placeholder_string(value: Any) -> bool:
    return _is_non_empty_string(value) and str(value).strip().lower() not in PLACEHOLDERS


def _contains_marker(value: Any, markers: Sequence[str]) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in markers)


def _append_missing_string(
    messages: list[str], record: dict[str, Any], path: str, field: str
) -> None:
    if not _is_non_placeholder_string(record.get(field)):
        messages.append(f"{path}.{field}: must be a non-empty recorded value")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value.strip()) is not None


def _normalized_sha256(value: Any) -> str | None:
    if not _is_sha256(value):
        return None
    text = str(value).strip()
    if text.lower().startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text.lower()


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
    if _contains_marker(reference, BAD_MARKERS):
        failures.append(f"{path}: must not reference Simulator, unsigned, or ad-hoc evidence")
    if _contains_marker(reference, ANDROID_MARKERS):
        failures.append(f"{path}: must not reference Android evidence for iOS signing")

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
        if field == "dirty":
            if not isinstance(repository.get(field), bool):
                missing.append("repository.dirty: must be boolean")
        else:
            _append_missing_string(missing, repository, "repository", field)

    commit = repository.get("commit")
    if _is_non_placeholder_string(commit) and COMMIT_PATTERN.fullmatch(str(commit).strip()) is None:
        missing.append("repository.commit: must be a 40-character current-base commit SHA")
    if repository.get("dirty") is True:
        missing.append("repository.dirty: must be false for current-base signing readiness")


def _current_base(document: dict[str, Any]) -> dict[str, Any]:
    repository = document.get("repository") if isinstance(document.get("repository"), dict) else {}
    commit = repository.get("commit")
    normalized_commit = None
    if _is_non_placeholder_string(commit) and COMMIT_PATTERN.fullmatch(str(commit).strip()):
        normalized_commit = str(commit).strip().lower()
    branch = repository.get("branch")
    return {
        "commit": normalized_commit,
        "branch": str(branch).strip() if _is_non_placeholder_string(branch) else None,
        "dirty": repository.get("dirty") if isinstance(repository.get("dirty"), bool) else None,
    }


def _signing_summary(document: dict[str, Any], recorded_fields: dict[str, bool], verdict: str) -> dict[str, Any]:
    signing = document.get("signing") if isinstance(document.get("signing"), dict) else {}
    bundle_id = signing.get("bundle_id")
    normalized_bundle_id = str(bundle_id).strip() if _is_non_placeholder_string(bundle_id) else None
    unique_bundle_id = (
        normalized_bundle_id is not None
        and normalized_bundle_id != DEFAULT_BUNDLE_ID
        and not _contains_marker(normalized_bundle_id, BAD_MARKERS)
    )
    signed_artifact_sha256 = _normalized_sha256(signing.get("signed_artifact_sha256"))
    return {
        "status": PASS if verdict == PASS else verdict,
        "bundle_id": normalized_bundle_id,
        "unique_bundle_id": unique_bundle_id,
        "team_id_recorded": recorded_fields["team_id"],
        "codesign_identity_recorded": recorded_fields["codesign_identity"],
        "provisioning_profile_recorded": recorded_fields["provisioning_profile"],
        "device_udid_hashes_recorded": recorded_fields["device_udid"],
        "entitlements_recorded": recorded_fields["entitlements"],
        "signed_artifact_sha256": signed_artifact_sha256,
    }


def _validate_required_false_flags(document: dict[str, Any], missing: list[str], failures: list[str]) -> None:
    failure_messages = {
        "simulator_build": "simulator_build: Simulator output cannot close iOS app-signing readiness",
        "unsigned_build": "unsigned_build: unsigned output cannot close iOS app-signing readiness",
        "android_evidence_used_for_ios_signing": "android_evidence_used_for_ios_signing: must be false",
    }
    for field in REQUIRED_FALSE_FLAGS:
        value = document.get(field)
        if value is True:
            failures.append(failure_messages[field])
        elif value is not False:
            missing.append(f"{field}: must be explicitly false")


def _validate_xcode(document: dict[str, Any], missing: list[str]) -> None:
    xcode = _require_object(document, "xcode", missing)
    if xcode is None:
        return
    for field in REQUIRED_XCODE_FIELDS:
        _append_missing_string(missing, xcode, "xcode", field)
    ios_sdk = xcode.get("ios_sdk")
    if _is_non_empty_string(ios_sdk) and "iphoneos" not in str(ios_sdk).lower():
        missing.append("xcode.ios_sdk: must record an iPhoneOS SDK, not Simulator-only SDKs")


def _validate_entitlements(
    signing: dict[str, Any], missing: list[str], failures: list[str]
) -> None:
    entitlements = signing.get("entitlements")
    if not isinstance(entitlements, dict):
        missing.append("signing.entitlements: must be an object")
        return
    for field in REQUIRED_ENTITLEMENTS_FIELDS:
        if field == "keychain_access_groups":
            groups = entitlements.get(field)
            if not isinstance(groups, list) or not any(_is_non_placeholder_string(item) for item in groups):
                missing.append("signing.entitlements.keychain_access_groups: must list at least one group")
        else:
            _append_missing_string(missing, entitlements, "signing.entitlements", field)

    if not _is_sha256(entitlements.get("raw_entitlements_sha256")):
        missing.append("signing.entitlements.raw_entitlements_sha256: must be a SHA-256 digest")

    bundle_id = signing.get("bundle_id")
    entitlement_bundle_id = entitlements.get("bundle_identifier")
    if _is_non_empty_string(bundle_id) and _is_non_empty_string(entitlement_bundle_id):
        if str(bundle_id).strip() != str(entitlement_bundle_id).strip():
            failures.append("signing.entitlements.bundle_identifier: must match signing.bundle_id")

    team_id = signing.get("team_id")
    entitlement_team_id = entitlements.get("team_identifier")
    if _is_non_empty_string(team_id) and _is_non_empty_string(entitlement_team_id):
        if str(team_id).strip() != str(entitlement_team_id).strip():
            failures.append("signing.entitlements.team_identifier: must match signing.team_id")

    team_id_is_valid = (
        _is_non_empty_string(team_id)
        and TEAM_ID_PATTERN.fullmatch(str(team_id).strip()) is not None
    )
    bundle_id_is_valid = (
        _is_non_empty_string(bundle_id)
        and str(bundle_id).strip() != DEFAULT_BUNDLE_ID
        and not _contains_marker(bundle_id, BAD_MARKERS)
    )
    if team_id_is_valid and bundle_id_is_valid:
        expected_application_identifier = f"{str(team_id).strip()}.{str(bundle_id).strip()}"
        application_identifier = entitlements.get("application_identifier")
        if _is_non_empty_string(application_identifier):
            if str(application_identifier).strip() != expected_application_identifier:
                failures.append(
                    "signing.entitlements.application_identifier: must match Team ID and bundle ID"
                )
        keychain_groups = entitlements.get("keychain_access_groups")
        if isinstance(keychain_groups, list):
            normalized_groups = {
                str(group).strip()
                for group in keychain_groups
                if _is_non_placeholder_string(group)
            }
            if expected_application_identifier not in normalized_groups:
                failures.append(
                    "signing.entitlements.keychain_access_groups: must include Team ID and bundle ID"
                )


def _validate_device_udids(signing: dict[str, Any], missing: list[str], failures: list[str]) -> list[str]:
    udids = signing.get("device_udids")
    if not isinstance(udids, list) or not udids:
        missing.append("signing.device_udids: must include at least one registered physical-device UDID hash")
        return []

    recorded: list[str] = []
    for index, value in enumerate(udids):
        path = f"signing.device_udids[{index}]"
        if not _is_non_placeholder_string(value):
            missing.append(f"{path}: must be a non-empty UDID hash")
            continue
        text = str(value).strip()
        recorded.append(text)
        if not UDID_HASH_PATTERN.fullmatch(text):
            missing.append(f"{path}: must be a SHA-256 hash, not a raw UDID or placeholder")
        if _contains_marker(text, BAD_MARKERS):
            failures.append(f"{path}: must not be Simulator-derived")
        if _contains_marker(text, ANDROID_MARKERS):
            failures.append(f"{path}: must not be Android-derived")
    return recorded


def _validate_signing(
    document: dict[str, Any], evidence_root: Path, missing: list[str], failures: list[str]
) -> dict[str, bool]:
    signing = _require_object(document, "signing", missing)
    recorded = {
        "team_id": False,
        "provisioning_profile": False,
        "bundle_id": False,
        "codesign_identity": False,
        "device_udid": False,
        "entitlements": False,
        "signed_artifact": False,
        "artifacts": False,
    }
    if signing is None:
        return recorded

    for field in REQUIRED_SIGNING_FIELDS:
        if field in {"device_udids", "entitlements"}:
            continue
        _append_missing_string(missing, signing, "signing", field)

    if signing.get("status") == FAILED:
        failures.append("signing.status: is failed")
    elif signing.get("status") != COMPLETE:
        missing.append("signing.status: must be complete")

    team_id = signing.get("team_id")
    if _is_non_placeholder_string(team_id):
        recorded["team_id"] = True
        if TEAM_ID_PATTERN.fullmatch(str(team_id).strip()) is None:
            missing.append("signing.team_id: must be a 10-character Apple Team ID")

    profile_uuid = signing.get("provisioning_profile_uuid")
    if _is_non_placeholder_string(profile_uuid):
        recorded["provisioning_profile"] = True
        if PROFILE_UUID_PATTERN.fullmatch(str(profile_uuid).strip()) is None:
            missing.append("signing.provisioning_profile_uuid: must be a UUID")

    bundle_id = signing.get("bundle_id")
    if _is_non_placeholder_string(bundle_id):
        recorded["bundle_id"] = True
        if str(bundle_id).strip() == DEFAULT_BUNDLE_ID:
            missing.append("signing.bundle_id: must be a unique non-default bundle identifier")
        if _contains_marker(bundle_id, BAD_MARKERS):
            failures.append("signing.bundle_id: must not be Simulator, unsigned, or ad-hoc scoped")

    codesign_identity = signing.get("codesign_identity")
    if _is_non_placeholder_string(codesign_identity):
        recorded["codesign_identity"] = True
        identity = str(codesign_identity).strip().lower()
        if identity in {"-", "adhoc", "ad-hoc"} or "ad hoc" in identity or "ad-hoc" in identity:
            failures.append("signing.codesign_identity: must be a real Apple signing identity, not ad-hoc")

    if _is_sha256(signing.get("signed_artifact_sha256")):
        recorded["signed_artifact"] = True
    else:
        missing.append("signing.signed_artifact_sha256: must be a SHA-256 digest")
    if _contains_marker(signing.get("signed_artifact_sha256"), BAD_MARKERS):
        failures.append("signing.signed_artifact_sha256: must not reference unsigned or Simulator artifacts")

    device_udids = _validate_device_udids(signing, missing, failures)
    recorded["device_udid"] = bool(device_udids)

    _validate_entitlements(signing, missing, failures)
    entitlements = signing.get("entitlements")
    recorded["entitlements"] = isinstance(entitlements, dict) and all(
        field in entitlements for field in REQUIRED_ENTITLEMENTS_FIELDS
    )

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        missing.append("artifacts: must include retained signing command/profile/entitlements output")
    else:
        recorded["artifacts"] = True
        for index, reference in enumerate(artifacts):
            _validate_artifact_reference(
                reference=reference,
                evidence_root=evidence_root,
                path=f"artifacts[{index}]",
                missing=missing,
                failures=failures,
            )
        joined_artifacts = "\n".join(
            str(reference).lower() for reference in artifacts if isinstance(reference, str)
        )
        for label, markers in REQUIRED_ARTIFACT_MARKERS.items():
            if not any(marker in joined_artifacts for marker in markers):
                missing.append(
                    f"artifacts.{label}: must retain signing-readiness evidence for {label}"
                )

    return recorded


def evaluate(
    document: dict[str, Any], evidence_root: Path, readiness_path: Path | None = None
) -> dict[str, Any]:
    missing: list[str] = []
    failures: list[str] = []

    if document.get("schema_version") != SCHEMA_VERSION:
        missing.append(f"schema_version: must be {SCHEMA_VERSION}")
    if document.get("kind") != READINESS_KIND:
        missing.append(f"kind: must be {READINESS_KIND}")
    if document.get("platform") != "ios":
        missing.append("platform: must be ios")
    if document.get("status") == FAILED:
        failures.append("status: is failed")
    elif document.get("status") != COMPLETE:
        missing.append("status: must be complete")
    _validate_required_false_flags(document, missing, failures)

    _validate_repository(document, missing)
    _validate_xcode(document, missing)
    recorded_fields = _validate_signing(document, evidence_root, missing, failures)

    verdict = PASS
    if failures:
        verdict = FAIL
    elif missing:
        verdict = BLOCKED

    signing_status = document.get("status") if isinstance(document.get("status"), str) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "repository": REPOSITORY_FULL_NAME,
            "scope": "Phase 5 iOS app-signing readiness prerequisite only",
        },
        "source": {
            "readiness": str(readiness_path) if readiness_path is not None else None,
            "evidence_root": str(evidence_root),
        },
        "current_base": _current_base(document),
        "verdict": verdict,
        "signing_status": signing_status,
        "signing_summary": _signing_summary(document, recorded_fields, verdict),
        "can_close_ios_app_signing_readiness": verdict == PASS,
        "can_close_ios_device_acceptance": False,
        "recorded_fields": recorded_fields,
        "missing": missing,
        "failures": failures,
        "evidence": document.get("artifacts") if isinstance(document.get("artifacts"), list) else [],
        "interpretation": INTERPRETATION,
    }


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readiness",
        type=Path,
        required=True,
        help="sanitized iOS app-signing readiness JSON",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="directory that contains artifact paths referenced by readiness JSON",
    )
    parser.add_argument("--output", type=Path, help="write gate result JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        readiness_path = args.readiness.resolve()
        evidence_root = (args.evidence_root or readiness_path.parent).resolve()
        result = evaluate(_parse_json(readiness_path), evidence_root, readiness_path)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (IOSAppSigningReadinessError, OSError) as error:
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
