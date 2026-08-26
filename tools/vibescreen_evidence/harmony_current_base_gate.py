"""Evaluate the HarmonyOS Phase 4 current-base owner gate.

This gate is intentionally an aggregate/readiness check, not a device runner. It
ties the README Phase 4 owner surface to the existing Harmony readiness preflight
and final device-gate manifest, then fails closed until real DevEco, signed HAP,
MatePad Mini, hardware decode, HUKS/authenticated transport, and Host resume
interoperability evidence exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import harmony_device_gate  # noqa: E402

GATE_KIND = "harmony_current_base_owner_gate"
READINESS_KIND = "harmony_readiness_preflight"
DEVICE_GATE_SCHEMA = "dev.vibescreen.harmony-device-gates/v1"
AGGREGATE_OWNER = "current-base-harmony-phase4-owner-gates"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"

SOURCE_DOCS = [
    "README.md",
    "apps/harmony/README.md",
    "docs/changes/2026-08-04-phase-4-harmony/CURRENT_BASE_AUDIT.md",
    "docs/changes/2026-08-04-phase-4-harmony/TEST.md",
    "docs/runbook/harmony-matepad-mini.md",
]

OWNER_GATES = {
    "deveco_build": {
        "owner": "HarmonyOS DevEco build and API-checker evidence",
        "required_device_gates": ("deveco_sdk_and_api_checker",),
        "required_evidence_markers": ("harmony-readiness.json", "deveco", "hvigor", "api-checker"),
        "requirement": "DevEco/Harmony SDK API checker evidence for the current HarmonyOS source tree",
    },
    "hap_sign_install": {
        "owner": "HarmonyOS signed HAP lifecycle evidence",
        "required_device_gates": ("signed_release_hap", "hap_install_launch"),
        "required_evidence_markers": ("harmony-hap-readiness.json", "SHA256SUMS", "hap-install"),
        "requirement": "DevEco-built signed HAP installed and launched on the target HarmonyOS MatePad Mini",
    },
    "hardware_decode_capability": {
        "owner": "HarmonyOS AVCodec hardware decode evidence",
        "required_device_gates": ("h264_hardware_decode", "hevc_hardware_decode"),
        "required_evidence_markers": ("harmony-avcodec-preflight.json",),
        "requirement": "H.264 and HEVC hardware decoder identity plus rendered-frame evidence on a HarmonyOS MatePad Mini",
    },
    "huks_secure_pairing": {
        "owner": "HarmonyOS HUKS secure-pairing evidence",
        "required_device_gates": ("huks_backed_secure_pairing", "credential_revocation_replay"),
        "required_evidence_markers": ("harmony-secure-pairing.json", "huks"),
        "requirement": "HUKS-backed pairing, credential issue/revoke, replay, and expiry evidence on HarmonyOS",
    },
    "authenticated_transport": {
        "owner": "HarmonyOS authenticated transport evidence",
        "required_device_gates": ("authenticated_transport_records",),
        "required_evidence_markers": ("harmony-authenticated-records.json", "harmony-lan-secure-record", "authenticated-transport"),
        "requirement": "Authenticated record-layer transport evidence for HarmonyOS and the Protocol v1 Host",
    },
    "host_resume_interop": {
        "owner": "Joint Mac Host and HarmonyOS resume interoperability evidence",
        "required_device_gates": (
            "host_protocol_v1_interop",
            "resume_background_foreground",
            "resume_network_roam",
            "resume_host_restart",
            "no_old_epoch_render",
            "resume_capable_host_interop",
        ),
        "required_evidence_markers": ("harmony-host-interop-preflight.json",),
        "requirement": "Protocol v1 Host interoperability with accepted resume results and stale-epoch rejection",
    },
    "matepad_acceptance": {
        "owner": "HarmonyOS MatePad Mini aggregate acceptance evidence",
        "required_device_gates": (
            "permission_denial_retry",
            "ui_device_identity_record",
            "input_touch_keyboard_pointer_stylus",
            "eight_hour_soak",
            "external_latency",
        ),
        "required_evidence_markers": ("harmony-matepad-acceptance.json", "harmony-device-gates.json"),
        "requirement": "Complete MatePad Mini UI/input/lifecycle/soak/latency acceptance evidence",
    },
}

INTERPRETATION = (
    "A pass means the README Phase 4 owner gates for HarmonyOS DevEco build, "
    "signed HAP install, hardware decode, HUKS secure pairing, authenticated "
    "transport, resume-capable Host interoperability, and MatePad Mini "
    "acceptance are backed by a passing readiness preflight and passing device "
    "manifest. Missing DevEco, signed HAP, MatePad Mini, Host identity, or gate "
    "evidence remains blocked/open and is not acceptance evidence."
)


def _load_json(path: Path, label: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"{label} missing: {path}"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"{label} unreadable: {error}"
    if not isinstance(document, dict):
        return None, f"{label} must be a JSON object"
    return document, None


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _non_placeholder_string(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    return set(str(value).lower()) != {"0"}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if _non_empty_string(item)]


def _strings_from_values(values: Sequence[Any]) -> list[str]:
    return [str(value) for value in values if _non_empty_string(value)]


def _check(passed: bool, expected: str, *, evidence: list[str] | None = None, blocking: bool = True) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": evidence or [],
        "blocking": blocking,
    }


def _gate_owners() -> dict[str, str]:
    return {gate_id: str(config["owner"]) for gate_id, config in OWNER_GATES.items()}


def _readiness_checks(readiness: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if readiness is None:
        return {
            "readiness_manifest": _check(False, "harmony-readiness.json is present"),
            "deveco": _check(False, "DevEco Studio, hvigor, ohpm, and hdc are available"),
            "hap": _check(False, "signed HAP, signature certificate hash, and checksum manifest are recorded"),
            "matepad": _check(False, "one HarmonyOS MatePad Mini-class HDC target is recorded"),
            "host": _check(False, "Protocol v1 Host commit and build SHA-256 are recorded"),
        }

    toolchain = readiness.get("toolchain") if isinstance(readiness.get("toolchain"), dict) else {}
    artifact = readiness.get("artifact") if isinstance(readiness.get("artifact"), dict) else {}
    device = readiness.get("device") if isinstance(readiness.get("device"), dict) else None
    host = readiness.get("host") if isinstance(readiness.get("host"), dict) else {}

    probes = [
        toolchain.get("deveco_studio"),
        toolchain.get("hvigor"),
        toolchain.get("ohpm"),
        toolchain.get("hdc"),
    ]
    probe_evidence: list[str] = []
    all_tools_pass = True
    for probe in probes:
        if not isinstance(probe, dict) or probe.get("status") != "pass":
            all_tools_pass = False
        elif _non_empty_string(probe.get("version")):
            probe_evidence.append(str(probe["version"]))

    artifact_evidence = _strings_from_values(
        [
            artifact.get("hap_path"),
            artifact.get("hap_sha256"),
            artifact.get("signature_certificate_sha256"),
            artifact.get("sha256sums_sha256"),
        ]
    )
    hap_ready = (
        artifact.get("hap_zip_readable") is True
        and artifact.get("sha256sums_contains_hap") is True
        and all(
            _non_placeholder_string(artifact.get(key))
            for key in ("hap_sha256", "signature_certificate_sha256", "sha256sums_sha256")
        )
    )

    matepad_ready = False
    device_evidence: list[str] = []
    if device is not None:
        platform = str(device.get("platform", ""))
        identity = " ".join(str(device.get(key, "")) for key in ("manufacturer", "model", "product")).strip()
        matepad_ready = platform in {"HarmonyOS", "HarmonyOS NEXT"} and device.get("is_matepad_mini") is True
        device_evidence = [item for item in (platform, identity) if item]

    host_commit = host.get("commit")
    host_build = host.get("build_sha256")
    host_ready = _non_placeholder_string(host_commit) and _non_placeholder_string(host_build) and host.get("protocol") == "Protocol v1"

    return {
        "readiness_manifest": _check(
            readiness.get("schema_version") == SCHEMA_VERSION
            and readiness.get("kind") == READINESS_KIND
            and readiness.get("verdict") == "pass",
            "harmony-readiness.json reports verdict pass",
            evidence=[str(readiness.get("verdict"))] if readiness.get("verdict") else [],
        ),
        "deveco": _check(
            all_tools_pass,
            "DevEco Studio, hvigor, ohpm, and hdc are available",
            evidence=probe_evidence,
        ),
        "hap": _check(
            hap_ready,
            "signed HAP, signature certificate hash, and checksum manifest are recorded",
            evidence=artifact_evidence,
        ),
        "matepad": _check(
            matepad_ready,
            "one HarmonyOS MatePad Mini-class HDC target is recorded",
            evidence=device_evidence,
        ),
        "host": _check(
            host_ready,
            "Protocol v1 Host commit and build SHA-256 are recorded",
            evidence=_strings_from_values([host_commit, host_build]),
        ),
    }


def _device_gate_checks(
    device_gates: dict[str, Any] | None,
    evidence_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    metadata: dict[str, dict[str, Any]] = {}
    owner: dict[str, dict[str, Any]] = {}
    if device_gates is None:
        metadata["device_gate_manifest"] = _check(False, "harmony-device-gates.json is present")
        metadata["strict_device_gate"] = _check(False, "harmony-device-gates.json passes strict validation")
        for gate_id, config in OWNER_GATES.items():
            owner[gate_id] = _check(False, str(config["requirement"]))
        return metadata, owner

    strict_error: str | None = None
    try:
        harmony_device_gate.validate_manifest(device_gates, evidence_root=evidence_root)
    except harmony_device_gate.ManifestError as error:
        strict_error = str(error)

    metadata["device_gate_manifest"] = _check(
        device_gates.get("schema") == DEVICE_GATE_SCHEMA,
        f"device manifest schema is {DEVICE_GATE_SCHEMA}",
        evidence=[str(device_gates.get("schema"))] if device_gates.get("schema") else [],
    )
    metadata["strict_device_gate"] = _check(
        strict_error is None,
        "harmony-device-gates.json passes strict validation with local evidence artifacts",
        evidence=[strict_error] if strict_error is not None else [],
    )

    device = device_gates.get("device") if isinstance(device_gates.get("device"), dict) else {}
    identity = " ".join(str(device.get(key, "")) for key in ("manufacturer", "model", "product")).lower()
    metadata["harmony_matepad_identity"] = _check(
        device.get("platform") in {"HarmonyOS", "HarmonyOS NEXT"}
        and "matepad" in identity
        and "mini" in identity,
        "device manifest records HarmonyOS MatePad Mini identity",
        evidence=_strings_from_values([device.get("platform"), identity.strip()]),
    )

    host = device_gates.get("host") if isinstance(device_gates.get("host"), dict) else {}
    metadata["protocol_v1_host"] = _check(
        host.get("protocol") == "Protocol v1"
        and _non_placeholder_string(host.get("commit"))
        and _non_placeholder_string(host.get("build_sha256")),
        "device manifest binds a Protocol v1 Host build",
        evidence=_strings_from_values([host.get("commit"), host.get("build_sha256")]),
    )

    artifact = device_gates.get("artifact") if isinstance(device_gates.get("artifact"), dict) else {}
    metadata["signed_hap_artifact"] = _check(
        artifact.get("bundle_name") == "dev.vibescreen.harmony"
        and all(
            _non_placeholder_string(artifact.get(key))
            for key in ("hap_sha256", "signature_certificate_sha256", "sha256sums_sha256")
        ),
        "device manifest binds the signed Harmony HAP and signing hashes",
        evidence=_strings_from_values(
            [
                artifact.get("hap_sha256"),
                artifact.get("signature_certificate_sha256"),
                artifact.get("sha256sums_sha256"),
            ]
        ),
    )

    gates_value = device_gates.get("gates")
    gate_records = gates_value if isinstance(gates_value, list) else []
    by_id = {gate.get("id"): gate for gate in gate_records if isinstance(gate, dict)}
    for gate_id, config in OWNER_GATES.items():
        missing: list[str] = []
        evidence: list[str] = []
        for required_id in config["required_device_gates"]:
            gate = by_id.get(required_id)
            if not isinstance(gate, dict):
                missing.append(f"{required_id}:missing")
                continue
            if gate.get("status") != "pass":
                missing.append(f"{required_id}:{gate.get('status', 'missing')}")
            gate_evidence = _string_list(gate.get("evidence"))
            if not gate_evidence:
                missing.append(f"{required_id}:no-evidence")
            elif not any(
                marker in item
                for marker in config["required_evidence_markers"]
                for item in gate_evidence
            ):
                markers = ",".join(config["required_evidence_markers"])
                missing.append(f"{required_id}:missing-evidence-marker:{markers}")
            evidence.extend(gate_evidence)
        owner[gate_id] = _check(
            not missing,
            str(config["requirement"]),
            evidence=[*evidence, *missing] if missing else evidence,
        )
    return metadata, owner


def _substitution_checks(readiness: dict[str, Any] | None, device_gates: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    evidence: list[str] = []
    invalid = False
    for label, document in (("readiness", readiness), ("device_gates", device_gates)):
        if not isinstance(document, dict):
            continue
        device = document.get("device") if isinstance(document.get("device"), dict) else None
        if device is None:
            continue
        platform = str(device.get("platform", ""))
        if platform == "Android":
            invalid = True
            evidence.append(f"{label}:Android")
    return {
        "no_android_evidence_for_harmony": _check(
            not invalid,
            "Android evidence is not used for HarmonyOS owner gates",
            evidence=evidence,
        )
    }


def derive_gate(readiness_path: Path, device_gates_path: Path, evidence_root: Path | None = None) -> dict[str, Any]:
    readiness, readiness_error = _load_json(readiness_path, "readiness manifest")
    device_gates, device_error = _load_json(device_gates_path, "device-gate manifest")
    resolved_evidence_root = evidence_root if evidence_root is not None else device_gates_path.parent

    readiness_checks = _readiness_checks(readiness)
    device_metadata, owner_gate_checks = _device_gate_checks(device_gates, resolved_evidence_root)
    substitutions = _substitution_checks(readiness, device_gates)

    reasons: list[str] = []
    if readiness_error is not None:
        reasons.append(f"blocked: {readiness_error}")
    if device_error is not None:
        reasons.append(f"blocked: {device_error}")

    invalid_substitution = any(not check["passed"] for check in substitutions.values())
    if invalid_substitution:
        reasons.extend(f"fail: {name}" for name, check in substitutions.items() if not check["passed"])

    readiness_missing = [name for name, check in readiness_checks.items() if not check["passed"]]
    metadata_missing = [name for name, check in device_metadata.items() if not check["passed"]]
    owner_missing = [name for name, check in owner_gate_checks.items() if not check["passed"]]
    reasons.extend(f"blocked: readiness.{name}" for name in readiness_missing)
    reasons.extend(f"blocked: device_manifest.{name}" for name in metadata_missing)
    reasons.extend(f"blocked: owner_gate.{name}" for name in owner_missing)

    if invalid_substitution:
        verdict = "fail"
    elif readiness_error or device_error or readiness_missing or metadata_missing or owner_missing:
        verdict = "blocked"
    else:
        verdict = "pass"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "owner": {
            "aggregate": AGGREGATE_OWNER,
            "repository": REPOSITORY_FULL_NAME,
            "scope": sorted(OWNER_GATES),
            "gate_owners": _gate_owners(),
        },
        "source": {
            "readiness": str(readiness_path),
            "device_gates": str(device_gates_path),
            "evidence_root": str(resolved_evidence_root),
        },
        "source_docs": SOURCE_DOCS,
        "can_close_readme_phase4_owner_gates": verdict == "pass",
        "can_claim_harmony_device_pass": verdict == "pass",
        "checks": {
            "readiness": readiness_checks,
            "device_manifest": device_metadata,
            "owner_gates": owner_gate_checks,
            "evidence_substitution": substitutions,
        },
        "reasons": reasons,
        "interpretation": INTERPRETATION,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, required=True, help="Path to harmony-readiness.json")
    parser.add_argument("--device-gates", type=Path, required=True, help="Path to harmony-device-gates.json")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="Directory that strict device-gate evidence references must resolve under.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Path for harmony-current-base-gate.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = derive_gate(args.readiness, args.device_gates, evidence_root=args.evidence_root)
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: HarmonyOS current-base gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
