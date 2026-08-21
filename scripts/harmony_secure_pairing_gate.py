#!/usr/bin/env python3
"""Validate HarmonyOS HUKS-backed secure-pairing evidence.

This is a source/evidence contract, not a device runner. A passing manifest must
show that the HarmonyOS pairing path used non-exportable HUKS identity keys,
accepted only Protocol v1 PairingOffer/Request/Result, delegated Internet
admission to Authority/Signaling, and rejected expiry, replay, revocation,
legacy-peer, and no-HUKS cases fail-closed. Blocked manifests can be checked for
shape without closing the Phase 4 device gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "dev.vibescreen.harmony-secure-pairing-gate/v1"
REQUIRED_CHECK_IDS = (
    "huks_non_exportable_identity",
    "huks_credential_storage",
    "pairing_offer_request_result",
    "host_signature_verification",
    "credential_issue_and_install",
    "credential_revoke_tombstone",
    "expiry_rejection",
    "replay_rejection",
    "legacy_peer_rejection",
    "no_huks_rejection",
    "authority_signaling_admission",
)
REQUIRED_REPOSITORY_KEYS = ("commit", "tree", "status")
REQUIRED_TOOLCHAIN_KEYS = ("deveco_studio_version", "harmony_sdk_api", "hvigor_version", "ohpm_version", "hdc_version")
REQUIRED_ARTIFACT_KEYS = ("hap_sha256", "signature_certificate_sha256")
REQUIRED_DEVICE_KEYS = ("platform", "manufacturer", "model", "product", "serial_hash")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HARMONY_PLATFORMS = {"HarmonyOS", "HarmonyOS NEXT"}


class ManifestError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path}: expected object")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}: expected non-empty string")
    return value


def _hex(value: Any, path: str, pattern: re.Pattern[str], *, allow_placeholder: bool) -> str:
    text = _string(value, path).lower()
    if pattern.fullmatch(text) is None:
        raise ManifestError(f"{path}: expected {pattern.pattern}")
    if not allow_placeholder and set(text) == {"0"}:
        raise ManifestError(f"{path}: placeholder zero value is not evidence")
    return text


def _require_keys(document: dict[str, Any], keys: Iterable[str], path: str) -> None:
    for key in keys:
        if key not in document:
            raise ManifestError(f"{path}.{key}: missing")
        _string(document[key], f"{path}.{key}")


def validate_manifest(document: dict[str, Any], *, allow_blocked: bool = False) -> list[str]:
    warnings: list[str] = []
    if document.get("schema") != SCHEMA:
        raise ManifestError(f"schema: expected {SCHEMA}")

    repository = _mapping(document.get("repository"), "repository")
    _require_keys(repository, REQUIRED_REPOSITORY_KEYS, "repository")
    _hex(repository["commit"], "repository.commit", HEX_40, allow_placeholder=allow_blocked)
    _hex(repository["tree"], "repository.tree", HEX_40, allow_placeholder=allow_blocked)
    if repository["status"] != "clean":
        raise ManifestError("repository.status: expected clean")

    toolchain = _mapping(document.get("toolchain"), "toolchain")
    _require_keys(toolchain, REQUIRED_TOOLCHAIN_KEYS, "toolchain")
    if not re.search(r"(?:^|\D)(?:12|1[3-9]|[2-9][0-9])(?:\D|$)", toolchain["harmony_sdk_api"]):
        raise ManifestError("toolchain.harmony_sdk_api: expected API 12 or newer")

    artifact = _mapping(document.get("artifact"), "artifact")
    for key in REQUIRED_ARTIFACT_KEYS:
        _hex(artifact.get(key), f"artifact.{key}", HEX_64, allow_placeholder=allow_blocked)

    device = _mapping(document.get("device"), "device")
    _require_keys(device, REQUIRED_DEVICE_KEYS, "device")
    if device["platform"] not in HARMONY_PLATFORMS:
        raise ManifestError("device.platform: Android evidence cannot close HarmonyOS secure-pairing gates")
    _hex(device["serial_hash"], "device.serial_hash", HEX_64, allow_placeholder=allow_blocked)

    crypto = _mapping(document.get("crypto"), "crypto")
    if crypto.get("provider") != "HUKS":
        raise ManifestError("crypto.provider: expected HUKS")
    if crypto.get("signing_key_exportable") is not False:
        raise ManifestError("crypto.signing_key_exportable: expected false")
    if crypto.get("credential_record_backend") != "Asset Store + HUKS-bound secret":
        raise ManifestError("crypto.credential_record_backend: expected Asset Store + HUKS-bound secret")
    if crypto.get("private_key_export_attempt") not in {"rejected", "not_supported"}:
        raise ManifestError("crypto.private_key_export_attempt: expected rejected or not_supported")

    services = _mapping(document.get("services"), "services")
    for service_name in ("authority", "signaling"):
        service = _mapping(services.get(service_name), f"services.{service_name}")
        _hex(service.get("commit"), f"services.{service_name}.commit", HEX_40, allow_placeholder=allow_blocked)
        if service.get("mode") not in {"production_authority", "local_blocked"}:
            raise ManifestError(f"services.{service_name}.mode: expected production_authority or local_blocked")
        if service.get("mode") == "local_blocked" and not allow_blocked:
            raise ManifestError(f"services.{service_name}.mode: local_blocked cannot close secure-pairing gates")

    checks = document.get("checks")
    if not isinstance(checks, list):
        raise ManifestError("checks: expected array")
    by_id: dict[str, dict[str, Any]] = {}
    for index, check_value in enumerate(checks):
        check = _mapping(check_value, f"checks[{index}]")
        check_id = _string(check.get("id"), f"checks[{index}].id")
        if check_id in by_id:
            raise ManifestError(f"checks[{index}].id: duplicate {check_id}")
        by_id[check_id] = check
        status = check.get("status")
        if status not in {"pass", "blocked", "fail"}:
            raise ManifestError(f"checks[{index}].status: expected pass, blocked, or fail")
        evidence = check.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
            raise ManifestError(f"checks[{index}].evidence: expected non-empty string array")
        if check_id in REQUIRED_CHECK_IDS and status != "pass":
            message = f"{check_id}: {status}"
            if allow_blocked and status == "blocked":
                warnings.append(message)
            else:
                raise ManifestError(message)

    missing = [check_id for check_id in REQUIRED_CHECK_IDS if check_id not in by_id]
    if missing:
        raise ManifestError("missing required checks: " + ", ".join(missing))

    notes = document.get("notes", [])
    if notes is not None and (not isinstance(notes, list) or not all(isinstance(item, str) for item in notes)):
        raise ManifestError("notes: expected string array")
    return warnings


def template_manifest() -> dict[str, Any]:
    placeholder_hash = "0" * 64
    placeholder_commit = "0" * 40
    return {
        "schema": SCHEMA,
        "repository": {"commit": placeholder_commit, "tree": placeholder_commit, "status": "clean"},
        "toolchain": {
            "deveco_studio_version": "recorded DevEco Studio version",
            "harmony_sdk_api": "API 12",
            "hvigor_version": "recorded hvigor --version",
            "ohpm_version": "recorded ohpm --version",
            "hdc_version": "recorded hdc -v",
        },
        "artifact": {"hap_sha256": placeholder_hash, "signature_certificate_sha256": placeholder_hash},
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "serial_hash": placeholder_hash,
        },
        "crypto": {
            "provider": "HUKS",
            "signing_key_exportable": False,
            "credential_record_backend": "Asset Store + HUKS-bound secret",
            "private_key_export_attempt": "rejected",
        },
        "services": {
            "authority": {"commit": placeholder_commit, "mode": "production_authority"},
            "signaling": {"commit": placeholder_commit, "mode": "production_authority"},
        },
        "checks": [
            {"id": check_id, "status": "blocked", "evidence": ["replace with redacted evidence path or artifact id"]}
            for check_id in REQUIRED_CHECK_IDS
        ],
        "notes": ["Do not commit raw serials, credentials, IP addresses, pairing URLs, tokens, or screen content."],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate HarmonyOS HUKS-backed secure-pairing evidence.")
    parser.add_argument("manifest", nargs="?", type=Path, help="Path to harmony-secure-pairing.json.")
    parser.add_argument("--allow-blocked", action="store_true", help="Validate a blocked readiness record without closing the gate.")
    parser.add_argument("--template", action="store_true", help="Print a redaction-safe manifest template and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.template:
        print(json.dumps(template_manifest(), indent=2, sort_keys=True))
        return 0
    if args.manifest is None:
        raise SystemExit("manifest is required unless --template is used")
    document = json.loads(args.manifest.read_text(encoding="utf-8"))
    warnings = validate_manifest(_mapping(document, "manifest"), allow_blocked=args.allow_blocked)
    if args.allow_blocked:
        print("HarmonyOS secure-pairing manifest is structurally valid but not acceptance evidence:")
        for warning in warnings or ["allow-blocked mode does not close secure-pairing gates"]:
            print(f"- {warning}")
    else:
        print("HarmonyOS HUKS-backed secure-pairing evidence passes all required gates.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, ManifestError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
