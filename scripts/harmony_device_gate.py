#!/usr/bin/env python3
"""Validate HarmonyOS NEXT real-device gate evidence.

The validator is intentionally stricter than the portable Harmony checks. A
passing manifest must bind a signed HAP, DevEco/Harmony SDK toolchain, MatePad
Mini identity, HUKS-backed security, authenticated transport, hardware decode,
resume interoperability, and real-device behavior evidence. Android or
portable-only records are rejected so they cannot be used to close the
HarmonyOS gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "dev.vibescreen.harmony-device-gates/v1"
HARMONY_PLATFORMS = {"HarmonyOS", "HarmonyOS NEXT"}
REQUIRED_GATE_IDS = (
    "deveco_sdk_and_api_checker",
    "signed_release_hap",
    "hap_install_launch",
    "permission_denial_retry",
    "huks_backed_secure_pairing",
    "authenticated_transport_records",
    "credential_revocation_replay",
    "h264_hardware_decode",
    "hevc_hardware_decode",
    "host_protocol_v1_interop",
    "resume_background_foreground",
    "resume_network_roam",
    "resume_host_restart",
    "resume_capable_host_interop",
    "no_old_epoch_render",
    "input_touch_keyboard_pointer_stylus",
    "eight_hour_soak",
    "external_latency",
)
REQUIRED_ARTIFACT_KEYS = (
    "hap_sha256",
    "signature_certificate_sha256",
    "sha256sums_sha256",
)
REQUIRED_TOOLCHAIN_KEYS = (
    "deveco_studio_version",
    "harmony_sdk_api",
    "harmony_sdk_version",
    "hvigor_version",
    "ohpm_version",
    "hdc_version",
)
REQUIRED_DEVICE_KEYS = (
    "manufacturer",
    "model",
    "product",
    "os_build",
    "hdc_target",
    "serial_hash",
)
REQUIRED_HOST_KEYS = ("commit", "build_sha256", "protocol")
REQUIRED_REPOSITORY_KEYS = ("commit", "tree", "status")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


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


def _hex(value: Any, path: str, pattern: re.Pattern[str], *, allow_placeholder: bool = False) -> str:
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


def _validate_evidence_reference(reference: str, root: Path, path: str) -> None:
    if URL_RE.match(reference):
        raise ManifestError(f"{path}: expected repository-local evidence path, got URL")
    reference_path = Path(reference)
    if reference_path.is_absolute():
        raise ManifestError(f"{path}: expected path relative to evidence root")
    if any(part == ".." for part in reference_path.parts):
        raise ManifestError(f"{path}: must not escape evidence root")
    resolved_root = root.resolve()
    resolved_path = (resolved_root / reference_path).resolve()
    if resolved_path == resolved_root:
        raise ManifestError(f"{path}: expected an evidence artifact below evidence root")
    if resolved_root not in resolved_path.parents:
        raise ManifestError(f"{path}: must stay within evidence root")
    if not resolved_path.exists():
        raise ManifestError(f"{path}: missing evidence artifact {reference}")
    if not resolved_path.is_file():
        raise ManifestError(f"{path}: expected evidence artifact file {reference}")


def validate_manifest(
    document: dict[str, Any],
    *,
    allow_blocked: bool = False,
    evidence_root: Path | None = None,
) -> list[str]:
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
    api_value = _string(toolchain["harmony_sdk_api"], "toolchain.harmony_sdk_api")
    if not re.search(r"(?:^|\D)(?:12|1[3-9]|[2-9][0-9])(?:\D|$)", api_value):
        raise ManifestError("toolchain.harmony_sdk_api: expected API 12 or newer")

    artifact = _mapping(document.get("artifact"), "artifact")
    _require_keys(artifact, ("bundle_name", "version_name"), "artifact")
    for key in REQUIRED_ARTIFACT_KEYS:
        _hex(artifact.get(key), f"artifact.{key}", HEX_64, allow_placeholder=allow_blocked)
    if artifact["bundle_name"] != "dev.vibescreen.harmony":
        raise ManifestError("artifact.bundle_name: expected dev.vibescreen.harmony")

    device = _mapping(document.get("device"), "device")
    _require_keys(device, REQUIRED_DEVICE_KEYS, "device")
    platform = _string(device.get("platform"), "device.platform")
    if platform not in HARMONY_PLATFORMS:
        raise ManifestError("device.platform: Android evidence cannot close HarmonyOS gates")
    identity_text = " ".join(str(device.get(key, "")) for key in ("manufacturer", "model", "product"))
    if "matepad" not in identity_text.lower() or "mini" not in identity_text.lower():
        raise ManifestError("device: expected the primary MatePad Mini target identity")
    _hex(device["serial_hash"], "device.serial_hash", HEX_64, allow_placeholder=allow_blocked)

    host = _mapping(document.get("host"), "host")
    _require_keys(host, REQUIRED_HOST_KEYS, "host")
    _hex(host["commit"], "host.commit", HEX_40, allow_placeholder=allow_blocked)
    _hex(host["build_sha256"], "host.build_sha256", HEX_64, allow_placeholder=allow_blocked)
    if host["protocol"] != "Protocol v1":
        raise ManifestError("host.protocol: expected Protocol v1")

    gates = document.get("gates")
    if not isinstance(gates, list):
        raise ManifestError("gates: expected array")
    by_id: dict[str, dict[str, Any]] = {}
    for index, gate_value in enumerate(gates):
        gate = _mapping(gate_value, f"gates[{index}]")
        gate_id = _string(gate.get("id"), f"gates[{index}].id")
        if gate_id in by_id:
            raise ManifestError(f"gates[{index}].id: duplicate {gate_id}")
        by_id[gate_id] = gate
        status = gate.get("status")
        if status not in {"pass", "blocked", "fail"}:
            raise ManifestError(f"gates[{index}].status: expected pass, blocked, or fail")
        evidence = gate.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
            raise ManifestError(f"gates[{index}].evidence: expected non-empty string array")
        if gate_id in REQUIRED_GATE_IDS and status != "pass":
            message = f"{gate_id}: {status}"
            if allow_blocked and status == "blocked":
                warnings.append(message)
            else:
                raise ManifestError(message)
        if evidence_root is not None and not allow_blocked and status == "pass":
            for evidence_index, reference in enumerate(evidence):
                _validate_evidence_reference(
                    reference,
                    evidence_root,
                    f"gates[{index}].evidence[{evidence_index}]",
                )

    missing = [gate_id for gate_id in REQUIRED_GATE_IDS if gate_id not in by_id]
    if missing:
        raise ManifestError("missing required gates: " + ", ".join(missing))

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
            "deveco_studio_version": "recorded from DevEco Studio",
            "harmony_sdk_api": "API 12",
            "harmony_sdk_version": "recorded SDK version",
            "hvigor_version": "recorded hvigor --version",
            "ohpm_version": "recorded ohpm --version",
            "hdc_version": "recorded hdc -v",
        },
        "artifact": {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": placeholder_hash,
            "signature_certificate_sha256": placeholder_hash,
            "sha256sums_sha256": placeholder_hash,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "recorded Settings build",
            "hdc_target": "recorded hdc list targets -v target",
            "serial_hash": placeholder_hash,
        },
        "host": {"commit": placeholder_commit, "build_sha256": placeholder_hash, "protocol": "Protocol v1"},
        "gates": [
            {"id": gate_id, "status": "blocked", "evidence": ["replace with redacted raw evidence path or artifact id"]}
            for gate_id in REQUIRED_GATE_IDS
        ],
        "notes": ["Do not commit raw serials, credentials, IP addresses, or screen content."],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a HarmonyOS real-device gate manifest.")
    parser.add_argument("manifest", nargs="?", type=Path, help="Path to the evidence manifest JSON.")
    parser.add_argument("--allow-blocked", action="store_true", help="Validate structure for a blocked readiness record without closing the gate.")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="Directory that strict pass evidence references must resolve under.",
    )
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
    evidence_root = args.evidence_root if args.evidence_root is not None else args.manifest.parent
    warnings = validate_manifest(
        _mapping(document, "manifest"),
        allow_blocked=args.allow_blocked,
        evidence_root=evidence_root,
    )
    if args.allow_blocked:
        print("HarmonyOS device manifest is structurally valid but not acceptance evidence:")
        for warning in warnings or ["allow-blocked mode does not close real-device gates"]:
            print(f"- {warning}")
    else:
        print("HarmonyOS device manifest passes all required real-device gates.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, ManifestError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
