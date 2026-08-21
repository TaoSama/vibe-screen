#!/usr/bin/env python3
"""Assemble and validate HarmonyOS MatePad Mini acceptance evidence.

This runner is a fail-closed aggregation layer around the narrower HarmonyOS
readiness and device-gate tools. It can write a blocked evidence package when
the local environment has no MatePad Mini, DevEco/HDC toolchain, signed HAP, or
Host build evidence, but it never turns blocked readiness into acceptance.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import harmony_device_gate


SCHEMA_VERSION = "vibescreen.evidence/v1"
KIND = "harmony_matepad_mini_acceptance_package"
BLOCKED_EXIT = 2
EXTERNAL_REFERENCE_PREFIXES = ("artifact://", "release://")

DOMAIN_GATES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "toolchain_and_source",
        "Clean source, DevEco SDK, API checker, HDC, and release artifacts",
        ("deveco_sdk_and_api_checker", "signed_release_hap"),
        ("harmony-readiness.json", "build-log.txt", "SHA256SUMS"),
    ),
    (
        "hap_install_signing",
        "Signed HAP install, launch, and permission denial/retry",
        ("signed_release_hap", "hap_install_launch", "permission_denial_retry"),
        ("hap-install.log", "hap-signature.txt", "permission-denial-retry.log", "screenshots/"),
    ),
    (
        "avcodec_decode",
        "H.264 and HEVC AVCodec hardware decode into the real device surface",
        ("h264_hardware_decode", "hevc_hardware_decode"),
        ("avcodec-h264.log", "avcodec-hevc.log", "decoder-telemetry.jsonl"),
    ),
    (
        "secure_pairing_huks",
        "HUKS-backed secure pairing, authenticated transport records, and revocation/replay rejection",
        (
            "huks_backed_secure_pairing",
            "authenticated_transport_records",
            "credential_revocation_replay",
        ),
        ("pairing-transcript-redacted.json", "huks-key-attestation.txt", "revocation-replay.log"),
    ),
    (
        "host_resume_interop",
        "Protocol v1 Host interoperability and bounded resume across app, network, and Host restart",
        (
            "host_protocol_v1_interop",
            "resume_background_foreground",
            "resume_network_roam",
            "resume_host_restart",
            "no_old_epoch_render",
        ),
        ("host.log", "harmony-hilog.txt", "resume-events.jsonl", "old-epoch-rejection.log"),
    ),
    (
        "ui_device_identity",
        "MatePad Mini identity plus touch, keyboard, pointer, stylus, and orientation UI evidence",
        ("ui_device_identity_record", "input_touch_keyboard_pointer_stylus"),
        ("device-identity.txt", "ui-tree.xml", "input-observations.json", "screenshots/"),
    ),
    (
        "sustained_operation",
        "Eight-hour soak and external-camera latency package",
        ("eight_hour_soak", "external_latency"),
        ("samples.jsonl", "soak-summary.json", "external-camera/", "latency-report.json"),
    ),
)


@dataclass(frozen=True)
class GateValidation:
    strict_valid: bool
    allow_blocked_valid: bool
    warnings: list[str]
    error: str | None


class AcceptanceError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"failed to read {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise AcceptanceError(f"{label} must be a JSON object: {path}")
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _merge_prefill(template: dict[str, Any], readiness: dict[str, Any] | None) -> dict[str, Any]:
    if readiness is None:
        return template
    prefill = readiness.get("device_gate_prefill")
    if not isinstance(prefill, dict):
        return template

    for section in ("repository", "toolchain", "artifact", "device", "host"):
        value = prefill.get(section)
        if isinstance(value, dict) and isinstance(template.get(section), dict):
            for key, child_value in value.items():
                if child_value not in (None, ""):
                    template[section][key] = child_value
    return template


def blocked_device_manifest(readiness: dict[str, Any] | None) -> dict[str, Any]:
    manifest = _merge_prefill(harmony_device_gate.template_manifest(), readiness)
    for gate in manifest["gates"]:
        gate["status"] = "blocked"
        gate["evidence"] = ["harmony-readiness.json"]
    manifest["notes"] = [
        "Blocked readiness record only; no real MatePad Mini acceptance is claimed.",
        "Android, simulator, or portable CI output cannot close this HarmonyOS gate.",
        "Replace each blocked gate with redacted raw MatePad Mini evidence before strict validation.",
    ]
    return manifest


def validate_device_manifest(manifest: dict[str, Any]) -> GateValidation:
    try:
        harmony_device_gate.validate_manifest(manifest)
        return GateValidation(strict_valid=True, allow_blocked_valid=True, warnings=[], error=None)
    except harmony_device_gate.ManifestError as strict_error:
        try:
            warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)
        except harmony_device_gate.ManifestError as blocked_error:
            return GateValidation(
                strict_valid=False,
                allow_blocked_valid=False,
                warnings=[],
                error=str(blocked_error),
            )
        return GateValidation(
            strict_valid=False,
            allow_blocked_valid=True,
            warnings=warnings,
            error=str(strict_error),
        )


def _gate_statuses(device_manifest: dict[str, Any]) -> dict[str, str]:
    gates = device_manifest.get("gates")
    if not isinstance(gates, list):
        return {}
    statuses: dict[str, str] = {}
    for gate in gates:
        if isinstance(gate, dict) and isinstance(gate.get("id"), str) and isinstance(gate.get("status"), str):
            statuses[gate["id"]] = gate["status"]
    return statuses


def _domain_status(gate_statuses: dict[str, str], gate_ids: Sequence[str]) -> str:
    statuses = [gate_statuses.get(gate_id) for gate_id in gate_ids]
    if statuses and all(status == "pass" for status in statuses):
        return "pass"
    if any(status == "fail" for status in statuses):
        return "fail"
    return "blocked"


def _artifact_references(evidence_dir: Path, device_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    gates = device_manifest.get("gates")
    if not isinstance(gates, list):
        return []
    references: list[dict[str, Any]] = []
    resolved_evidence_dir = evidence_dir.resolve()
    for gate in gates:
        if not isinstance(gate, dict) or not isinstance(gate.get("id"), str):
            continue
        for reference in gate.get("evidence", []):
            if not isinstance(reference, str) or not reference.strip():
                continue
            normalized = reference.strip()
            if normalized.startswith(EXTERNAL_REFERENCE_PREFIXES):
                references.append({"gate_id": gate["id"], "reference": normalized, "status": "external"})
                continue
            path = Path(normalized)
            if path.is_absolute():
                references.append({"gate_id": gate["id"], "reference": normalized, "status": "invalid", "detail": "absolute paths are not allowed"})
                continue
            resolved = (resolved_evidence_dir / path).resolve()
            try:
                resolved.relative_to(resolved_evidence_dir)
            except ValueError:
                references.append({"gate_id": gate["id"], "reference": normalized, "status": "invalid", "detail": "path escapes evidence directory"})
                continue
            exists = resolved.is_dir() if normalized.endswith("/") else resolved.is_file()
            references.append({
                "gate_id": gate["id"],
                "reference": normalized,
                "status": "present" if exists else "missing",
            })
    return references


def build_package(
    *,
    command: Sequence[str],
    evidence_dir: Path,
    readiness_path: Path,
    device_manifest_path: Path,
    readiness: dict[str, Any] | None,
    device_manifest: dict[str, Any],
    validation: GateValidation,
) -> dict[str, Any]:
    statuses = _gate_statuses(device_manifest)
    artifact_references = _artifact_references(evidence_dir, device_manifest)
    domains = []
    for domain_id, description, gate_ids, artifacts in DOMAIN_GATES:
        domains.append(
            {
                "id": domain_id,
                "status": _domain_status(statuses, gate_ids),
                "description": description,
                "device_gate_ids": list(gate_ids),
                "expected_raw_artifacts": list(artifacts),
            }
        )

    readiness_verdict = readiness.get("verdict") if isinstance(readiness, dict) else "missing"
    domain_blockers = [domain["id"] for domain in domains if domain["status"] != "pass"]
    blocking_reasons: list[str] = []
    if readiness_verdict != "pass":
        blocking_reasons.append("HarmonyOS readiness preflight is not pass")
    if validation.error is not None:
        blocking_reasons.append(validation.error)
    if domain_blockers:
        blocking_reasons.append("blocked acceptance domains: " + ", ".join(domain_blockers))
    missing_artifacts = [
        f"{item['gate_id']}:{item['reference']}"
        for item in artifact_references
        if item["status"] in {"missing", "invalid"}
    ]
    if validation.strict_valid and missing_artifacts:
        blocking_reasons.append("missing or invalid local evidence references: " + ", ".join(missing_artifacts))

    verdict = "pass" if validation.strict_valid and readiness_verdict == "pass" and not domain_blockers and not missing_artifacts else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "created_at": utc_timestamp(),
        "command": list(command),
        "verdict": verdict,
        "blocking_reasons": blocking_reasons,
        "evidence_dir": str(evidence_dir),
        "readiness": {
            "path": str(readiness_path),
            "present": readiness is not None,
            "verdict": readiness_verdict,
            "blocking_reasons": readiness.get("blocking_reasons", []) if isinstance(readiness, dict) else [],
        },
        "device_gate_manifest": {
            "path": str(device_manifest_path),
            **asdict(validation),
        },
        "acceptance_domains": domains,
        "artifact_references": artifact_references,
        "limitations": [
            "This package is acceptance evidence only when verdict is pass.",
            "Blocked packages are readiness evidence and must not close the HarmonyOS README gate.",
            "Android, simulator, and portable CI evidence are explicitly excluded from MatePad Mini acceptance.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True, help="Directory containing HarmonyOS acceptance evidence.")
    parser.add_argument("--readiness", type=Path, help="harmony-readiness.json path; defaults under --evidence-dir.")
    parser.add_argument("--device-gates", type=Path, help="harmony-device-gates.json path; defaults under --evidence-dir.")
    parser.add_argument("--output", type=Path, help="Acceptance package output path; defaults under --evidence-dir.")
    parser.add_argument("--write-blocked", action="store_true", help="Write a blocked device-gate manifest when one is missing.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence_dir = args.evidence_dir
    readiness_path = args.readiness or evidence_dir / "harmony-readiness.json"
    device_manifest_path = args.device_gates or evidence_dir / "harmony-device-gates.json"
    output_path = args.output or evidence_dir / "harmony-matepad-acceptance.json"
    command = ["scripts/harmony_matepad_acceptance.py", *(argv if argv is not None else sys.argv[1:])]

    try:
        readiness = _read_json(readiness_path, "readiness report") if readiness_path.exists() else None
        if args.write_blocked:
            _write_json(device_manifest_path, blocked_device_manifest(readiness))
        elif not device_manifest_path.exists():
            raise AcceptanceError(f"device gate manifest is missing: {device_manifest_path}")
        device_manifest = _read_json(device_manifest_path, "device gate manifest")
        validation = validate_device_manifest(device_manifest)
        if not validation.allow_blocked_valid:
            raise AcceptanceError(validation.error or "device gate manifest is invalid")
        package = build_package(
            command=command,
            evidence_dir=evidence_dir,
            readiness_path=readiness_path,
            device_manifest_path=device_manifest_path,
            readiness=readiness,
            device_manifest=device_manifest,
            validation=validation,
        )
        _write_json(output_path, package)
    except AcceptanceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"HarmonyOS MatePad Mini acceptance package: {package['verdict']}")
    print(f"package: {output_path}")
    for reason in package["blocking_reasons"]:
        print(f"- {reason}")
    return 0 if package["verdict"] == "pass" else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
