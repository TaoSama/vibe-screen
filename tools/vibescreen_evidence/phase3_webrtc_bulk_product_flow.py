"""Evaluate Phase 3 public Internet WebRTC bulk product-flow evidence.

This checker is intentionally fail-closed. Local loopback, USB/LAN file-transfer
evidence, forced local coturn, relay deployment preflights, and raw bulk-channel
hook tests are useful readiness signals, but they cannot close the public
Internet WebRTC bulk product-flow gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


KIND = "phase3_webrtc_bulk_product_flow_gate"
MANIFEST_KIND = "phase3_webrtc_bulk_product_flow_manifest"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
OWNER_ROLE = "phase3_webrtc_bulk_product_flow_owner"
OWNER_BRANCH = "codex/phase3-public-internet-bulk-gate"

CORE_REQUIREMENTS = {
    "source_current_base": "manifest source commit matches a clean current checkout",
    "public_relay_webrtc_route": "real macOS and Android peers select a deployed public TURN relay WebRTC route",
    "coturn_lease_validation": "TURN credential and allocation leases are bound to Authority session ownership and expiry",
    "bulk_file_transfer_product_flow": "approved bidirectional file transfer uses vibescreen.bulk.v1 with chunks, progress, completion, and SHA-256 verification",
    "bulk_backpressure_and_cleanup": "bulk send/receive queues are bounded and cancel/disconnect cleanup is observed",
    "secure_record_layer": "bulk traffic uses the Phase 3 AES-256-GCM record layer with channel/session/key separation",
}

RELEASE_CHECKLIST = {
    "relay_production_prerequisites": "production relay DNS, /readyz, disk, TLS, quota, and secret-source checks pass",
    "real_capture_to_mediacodec": "real ScreenCaptureKit or CGDisplayStream frames reach Android MediaCodec",
    "network_handoff": "public route handoff recovers with a fresh session and old-record rejection",
    "cross_service_revocation": "Authority, signaling, TURN credential issuance, and active allocation all fail closed after revoke",
    "external_camera_latency": "direct and relay Internet paths have external-camera glass-to-glass latency evidence",
    "two_hour_mixed_route_soak": "two-hour mixed direct/relay/network-change soak has bounded queues, memory, nonce, latency, and media behavior",
    "packet_capture_confidentiality": "direct and relay packet captures show no plaintext content, credentials, or pairing secrets",
}

REQUIRED_CONTEXT_TRUE = {
    "real_macos_host": "real macOS Host participated",
    "real_android_device": "real Android device participated",
    "public_internet_path": "route crossed a genuine public Internet path",
    "deployed_remote_turn": "selected relay used a deployed remote TURN service",
    "webrtc_transport": "bulk bytes crossed WebRTC rather than TCP fallback",
    "identity_signed_host": "Host build was identity-signed",
    "screen_recording_granted": "Host Screen Recording was granted for the signed binary",
    "real_capture_to_mediacodec": "same run included real capture-to-MediaCodec continuity",
    "no_plaintext_fallback": "no plaintext fallback was used",
    "no_synthetic_peer": "no synthetic peer was used as product evidence",
}

DISALLOWED_EVIDENCE_FLAGS = (
    "usb_lan_tcp",
    "trusted_lan",
    "local_loopback",
    "forced_local_coturn",
    "relay_deployment_preflight_only",
    "synthetic_peer",
    "synthetic_media",
    "raw_bulk_hook_test",
)

SUBSTITUTION_FLAGS = {
    "pr404_relay_owner_used_as_product_e2e": "relay deployment preflight hardening cannot close public Internet product E2E",
    "usb_lan_file_transfer_used_for_internet": "USB/LAN file-transfer evidence cannot close Internet WebRTC bulk flow",
    "local_loopback_or_forced_local_coturn_used_as_public_internet": "local loopback or forced local coturn cannot close public Internet relay scope",
    "raw_bulk_hook_tests_used_as_product_flow": "raw bulk-channel hook tests cannot close product-flow evidence",
}

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SENSITIVE_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/Users/[^\r\n<>\"']+"), "<redacted-local-path>"),
    (re.compile(r"/home/[^\r\n<>\"']+"), "<redacted-local-path>"),
    (re.compile(r"EP[0-9A-Z]{14,}", re.IGNORECASE), "REDACTED_ANDROID_SERIAL"),
    (re.compile(r"(token|password|secret|private[_-]?key)=[^\s,;}]+", re.IGNORECASE), r"\1=<redacted>"),
)


class BulkProductFlowInputError(ValueError):
    """Raised when the evidence manifest cannot be evaluated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_text(value: Any) -> str:
    text = str(value)
    for pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_text(key): sanitize_value(item) for key, item in value.items()}
    return value


def _run_git(repo: Path, args: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BulkProductFlowInputError(f"could not inspect repository: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise BulkProductFlowInputError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def repository_state(repo: Path) -> tuple[str, bool]:
    commit = _run_git(repo, ["rev-parse", "HEAD"]).lower()
    if COMMIT_RE.fullmatch(commit) is None:
        raise BulkProductFlowInputError("git rev-parse HEAD did not return a 40-character commit")
    return commit, _run_git(repo, ["status", "--porcelain"]) == ""


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BulkProductFlowInputError(f"could not read manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise BulkProductFlowInputError("manifest must be a JSON object")
    return document


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise BulkProductFlowInputError(f"could not hash evidence artifact {path}: {error}") from error
    return digest.hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _empty_marker_list(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, list) and all(isinstance(item, str) for item in value) and not value


def _artifact_path(root: Path | None, value: Any) -> Path | None:
    if root is None or not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    resolved_root = root.resolve(strict=False)
    resolved = (resolved_root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _retained_artifact_record(record: dict[str, Any], source: str, evidence_root: Path | None) -> tuple[Path | None, list[str], list[str]]:
    problems: list[str] = []
    artifacts: list[str] = []
    path = _artifact_path(evidence_root, record.get("path"))
    if path is None or not path.is_file():
        problems.append(f"{source} retained artifact path is missing or outside the evidence directory")
    else:
        artifacts.append(str(record.get("path")))
    expected_sha = record.get("sha256")
    if not isinstance(expected_sha, str) or SHA256_RE.fullmatch(expected_sha) is None:
        problems.append(f"{source} retained artifact sha256 is missing or invalid")
    elif path is not None and path.is_file() and _sha256(path).lower() != expected_sha.lower():
        problems.append(f"{source} retained artifact sha256 does not match")
    return path, problems, artifacts


def _retained_artifact_list(value: Any, source: str, evidence_root: Path | None) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or not value:
        return [], [f"{source} retained evidence is required"]
    problems: list[str] = []
    artifacts: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            problems.append(f"{source}.evidence[{index}] must be an object with path and sha256")
            continue
        _path, item_problems, item_artifacts = _retained_artifact_record(
            item,
            f"{source}.evidence[{index}]",
            evidence_root,
        )
        problems.extend(item_problems)
        artifacts.extend(item_artifacts)
    return artifacts, problems


def _check(passed: bool, expected: str, *, evidence: Sequence[str] = (), blocking: bool = True) -> dict[str, Any]:
    return {"passed": passed, "expected": expected, "evidence": list(evidence), "blocking": blocking}


def default_manifest(*, source_commit: str | None = None, tree_status: str = "unknown") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "created_at": _utc_now(),
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "pull_request": "pending",
            "repository": REPOSITORY_FULL_NAME,
        },
        "source": {"commit": source_commit, "tree_status": tree_status},
        "evidence_context": {key: False for key in REQUIRED_CONTEXT_TRUE},
        "substitutions": {key: False for key in SUBSTITUTION_FLAGS},
        "core_gates": {
            name: {"status": "open", "evidence": [], "requirement": requirement}
            for name, requirement in CORE_REQUIREMENTS.items()
        },
        "release_prerequisites": {
            name: {"status": BLOCKED, "evidence": [], "requirement": requirement}
            for name, requirement in RELEASE_CHECKLIST.items()
        },
        "claims": {
            "internet_webrtc_bulk_file_transfer_product_flow": False,
            "phase3_public_internet_product_e2e": False,
        },
        "limitations": [
            "No public Internet WebRTC bulk file-transfer product-flow pass is claimed.",
            "Relay deployment preflight hardening is not product E2E evidence.",
            "relay.taoai.site production DNS, /readyz, disk, TURN/WebRTC, real media, handoff, revocation, latency, and soak evidence remain blocked unless a retained evidence package proves otherwise.",
        ],
    }


def _validate_artifact_metadata(record: dict[str, Any], source: str) -> list[str]:
    problems: list[str] = []
    expected_values = {
        "evidence_kind": "webrtc_bulk_file_transfer_product_flow",
        "scope": "public_internet",
        "route_kind": "relay",
        "transport": "webrtc_datachannel",
        "channel": "vibescreen.bulk.v1",
        "peer_kind": "product",
    }
    for field, expected in expected_values.items():
        if record.get(field) != expected:
            problems.append(f"{source}.{field} must be {expected}")
    for field, expected in REQUIRED_CONTEXT_TRUE.items():
        if record.get(field) is not True:
            problems.append(f"{source}.{field} must be true ({expected})")
    for field in DISALLOWED_EVIDENCE_FLAGS:
        if field in record and record.get(field) is not False:
            problems.append(f"{source}.{field} evidence is disallowed for this gate")
    if not _empty_marker_list(record.get("disallowed_markers")):
        problems.append(f"{source}.disallowed_markers must be empty")
    return problems


def _direction_reasons(direction: Any, label: str) -> list[str]:
    if not isinstance(direction, dict):
        return [f"missing {label} direction evidence"]
    required_true = (
        "protocol_v1_session",
        "file_offer_observed",
        "receiver_request_observed",
        "bulk_chunks_observed",
        "progress_observed",
        "completion_ack_observed",
        "source_file_read",
        "explicit_user_action",
        "receiver_approved",
        "remote_file_written",
        "final_sha256_match",
        "session_epoch_verified",
        "chunk_offsets_ordered",
        "chunk_payload_sha256_verified",
        "progress_offsets_monotonic",
        "final_chunk_observed",
    )
    reasons = [f"{label}.{field} must be true" for field in required_true if direction.get(field) is not True]
    if direction.get("transport") != "webrtc_datachannel":
        reasons.append(f"{label}.transport must be webrtc_datachannel")
    if direction.get("channel") != "vibescreen.bulk.v1":
        reasons.append(f"{label}.channel must be vibescreen.bulk.v1")
    if direction.get("route") != "relay":
        reasons.append(f"{label}.route must be relay")
    session_epoch = direction.get("session_epoch")
    if not isinstance(session_epoch, int) or session_epoch <= 0:
        reasons.append(f"{label}.session_epoch must be a positive integer")
    byte_length = direction.get("byte_length")
    if not isinstance(byte_length, int) or byte_length <= 0:
        reasons.append(f"{label}.byte_length must be a positive integer")
    sha256 = direction.get("sha256")
    if not isinstance(sha256, str) or SHA256_RE.fullmatch(sha256) is None:
        reasons.append(f"{label}.sha256 must be a 64-character hex SHA-256 digest")
    return reasons


def _file_transfer_flow_reasons(record: dict[str, Any], source: str) -> list[str]:
    reasons: list[str] = []
    flow = _dict(record.get("file_transfer"))
    directions = _dict(flow.get("directions"))
    reasons.extend(_direction_reasons(directions.get("android_to_macos"), f"{source}.file_transfer.directions.android_to_macos"))
    reasons.extend(_direction_reasons(directions.get("macos_to_android"), f"{source}.file_transfer.directions.macos_to_android"))
    cleanup = _dict(flow.get("cleanup"))
    for field in (
        "bounded_send_queue_observed",
        "receiver_backpressure_observed",
        "oversized_payload_rejected",
        "stale_owner_rejected",
        "transfer_timeout_cancel_observed",
        "timeout_frees_transfer_slot_observed",
        "cancel_cleanup_observed",
        "disconnect_cleanup_observed",
    ):
        if cleanup.get(field) is not True:
            reasons.append(f"{source}.file_transfer.cleanup.{field} must be true")
    return reasons


def _coturn_lease_reasons(record: dict[str, Any], source: str) -> list[str]:
    lease = _dict(record.get("coturn_lease_validation"))
    reasons: list[str] = []
    for field in (
        "turn_credential_lease_observed",
        "allocation_lease_observed",
        "authority_session_binding_verified",
        "device_binding_verified",
        "lease_expiry_checked",
        "revoked_lease_rejected",
        "allocation_reconciliation_observed",
        "coturn_username_bound_to_device",
    ):
        if lease.get(field) is not True:
            reasons.append(f"{source}.coturn_lease_validation.{field} must be true")
    return reasons


def _secure_record_reasons(record: dict[str, Any], source: str) -> list[str]:
    secure = _dict(record.get("secure_record_layer"))
    expected = {
        "algorithm": "AES-256-GCM",
        "header_as_aad": True,
        "session_epoch_bound": True,
        "key_epoch_bound": True,
        "channel_key_separation": True,
        "directional_key_separation": True,
        "replay_protection": True,
        "packet_capture_no_plaintext": True,
        "nonce_reuse_detected": False,
        "plaintext_fallback": False,
    }
    reasons: list[str] = []
    for field, expected_value in expected.items():
        if secure.get(field) != expected_value:
            reasons.append(f"{source}.secure_record_layer.{field} must be {expected_value!r}")
    return reasons


def _validate_evidence_record(record: Any, *, evidence_root: Path | None) -> tuple[bool, list[str], list[str]]:
    if not isinstance(record, dict):
        return False, ["evidence record must be an object"], []
    problems: list[str] = []
    artifacts: list[str] = []
    problems.extend(_validate_artifact_metadata(record, "manifest evidence"))
    problems.extend(_coturn_lease_reasons(record, "manifest evidence"))
    problems.extend(_file_transfer_flow_reasons(record, "manifest evidence"))
    problems.extend(_secure_record_reasons(record, "manifest evidence"))

    path, artifact_problems, artifacts = _retained_artifact_record(record, "manifest evidence", evidence_root)
    problems.extend(artifact_problems)
    if path is not None and path.is_file():
        artifact = _load_json(path)
        problems.extend(_validate_artifact_metadata(artifact, "retained artifact"))
        problems.extend(_coturn_lease_reasons(artifact, "retained artifact"))
        problems.extend(_file_transfer_flow_reasons(artifact, "retained artifact"))
        problems.extend(_secure_record_reasons(artifact, "retained artifact"))
    return not problems, problems, artifacts


def _structured_gate(manifest: dict[str, Any], name: str, expected: str, *, evidence_root: Path | None) -> dict[str, Any]:
    gates = _dict(manifest.get("core_gates"))
    gate = _dict(gates.get(name))
    evidence = gate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return _check(False, expected, evidence=["missing structured retained evidence"])
    artifacts: list[str] = []
    problems: list[str] = []
    for index, record in enumerate(evidence):
        valid, record_problems, record_artifacts = _validate_evidence_record(record, evidence_root=evidence_root)
        artifacts.extend(record_artifacts)
        if not valid:
            problems.extend(f"evidence[{index}]: {problem}" for problem in record_problems)
    return _check(gate.get("status") == PASS and not problems, expected, evidence=artifacts + problems)


def derive_gate(
    manifest: dict[str, Any] | Path,
    *,
    current_commit: str | None = None,
    tree_clean: bool | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    if isinstance(manifest, Path):
        evidence_root = evidence_root or manifest.parent
        manifest = _load_json(manifest)

    owner = _dict(manifest.get("owner"))
    source = _dict(manifest.get("source"))
    context = _dict(manifest.get("evidence_context"))
    substitutions = _dict(manifest.get("substitutions"))
    claims = _dict(manifest.get("claims"))
    release_prerequisites = _dict(manifest.get("release_prerequisites"))

    checks: dict[str, dict[str, Any]] = {
        "schema": _check(
            manifest.get("schema_version") == SCHEMA_VERSION and manifest.get("kind") == MANIFEST_KIND,
            f"manifest is {MANIFEST_KIND} v1",
        ),
        "owner": _check(
            owner.get("role") == OWNER_ROLE and owner.get("repository") == REPOSITORY_FULL_NAME,
            "dedicated current-base bulk product-flow owner is recorded",
            evidence=[str(owner.get("role")), str(owner.get("repository"))],
        ),
        "source_current_base": _check(
            isinstance(source.get("commit"), str)
            and COMMIT_RE.fullmatch(source["commit"]) is not None
            and source.get("tree_status") == "clean"
            and current_commit is not None
            and source.get("commit", "").lower() == current_commit.lower()
            and tree_clean is True,
            CORE_REQUIREMENTS["source_current_base"],
            evidence=[str(source.get("commit")), str(current_commit), str(tree_clean)],
        ),
    }
    for key, expected in REQUIRED_CONTEXT_TRUE.items():
        checks[key] = _check(context.get(key) is True, expected, evidence=[str(context.get(key))])

    failures: list[str] = []
    for key, expected in SUBSTITUTION_FLAGS.items():
        substituted = substitutions.get(key) is True
        checks[key] = _check(not substituted, expected, evidence=[str(substitutions.get(key))], blocking=False)
        if substituted:
            failures.append(f"fail: {key}")

    for name, expected in CORE_REQUIREMENTS.items():
        if name == "source_current_base":
            continue
        checks[name] = _structured_gate(manifest, name, expected, evidence_root=evidence_root)

    closure_checklist: dict[str, dict[str, Any]] = {}
    for name, expected in RELEASE_CHECKLIST.items():
        item = _dict(release_prerequisites.get(name))
        evidence, evidence_problems = _retained_artifact_list(
            item.get("evidence"),
            f"release_prerequisite.{name}",
            evidence_root,
        )
        closure_checklist[name] = _check(
            item.get("status") == PASS and not evidence_problems,
            expected,
            evidence=evidence + evidence_problems,
        )

    checks["claim_bulk_file_transfer"] = _check(
        claims.get("internet_webrtc_bulk_file_transfer_product_flow") is True,
        "internet_webrtc_bulk_file_transfer_product_flow is true only when retained evidence supports it",
        evidence=[str(claims.get("internet_webrtc_bulk_file_transfer_product_flow"))],
    )
    checks["claim_phase3_product_e2e"] = _check(
        claims.get("phase3_public_internet_product_e2e") is False,
        "bulk child gate must not claim the broader Phase 3 public Internet product E2E gate",
        evidence=[str(claims.get("phase3_public_internet_product_e2e"))],
        blocking=False,
    )
    if claims.get("phase3_public_internet_product_e2e") is True:
        failures.append("fail: phase3_public_internet_product_e2e claimed by bulk child gate")

    reasons = [
        f"blocked: {name}"
        for name, check in checks.items()
        if not check["passed"] and name not in SUBSTITUTION_FLAGS and check.get("blocking") is not False
    ]
    reasons.extend(
        f"blocked: release_prerequisite.{name}"
        for name, check in closure_checklist.items()
        if not check["passed"]
    )
    verdict = FAIL if failures else (BLOCKED if reasons else PASS)
    all_reasons = failures + reasons
    return sanitize_value(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "generated_at": _utc_now(),
            "verdict": verdict,
            "gate_closed": verdict == PASS,
            "can_close_public_internet_bulk_product_flow_gate": verdict == PASS,
            "gate_can_close_phase3_release": False,
            "owner": {
                "role": owner.get("role"),
                "head_ref": owner.get("head_ref"),
                "pull_request": owner.get("pull_request"),
                "repository": owner.get("repository"),
            },
            "source": source,
            "checks": checks,
            "closure_checklist": closure_checklist,
            "blockers": all_reasons,
            "not_proven": [
                item
                for item in (
                    "public Internet WebRTC relay route to a real Android device" if verdict != PASS else "",
                    "Authority-bound TURN credential and coturn allocation lease validation" if checks.get("coturn_lease_validation", {}).get("passed") is not True else "",
                    "approved bidirectional file transfer over vibescreen.bulk.v1 with ordered chunks, per-chunk SHA-256, monotonic progress, and final file SHA-256" if verdict != PASS else "",
                    "bulk transfer timeout cancellation and transfer-slot recovery" if checks.get("bulk_backpressure_and_cleanup", {}).get("passed") is not True else "",
                    "relay.taoai.site production DNS, /readyz, disk, TURN, and secret-source readiness" if closure_checklist.get("relay_production_prerequisites", {}).get("passed") is not True else "",
                    "real ScreenCaptureKit/CGDisplayStream to Android MediaCodec continuity" if closure_checklist.get("real_capture_to_mediacodec", {}).get("passed") is not True else "",
                    "network handoff, revocation, external-camera latency, packet-capture, and two-hour soak release evidence" if any(not check["passed"] for check in closure_checklist.values()) else "",
                )
                if item
            ],
            "safety": {
                "relay_preflight_does_not_close_product_e2e": True,
                "offline_tests_do_not_close_gate": True,
                "usb_lan_evidence_do_not_close_internet_gate": True,
                "synthetic_evidence_do_not_close_gate": True,
                "public_output_sanitized": True,
            },
            "interpretation": (
                "A pass requires retained evidence for a real public Internet WebRTC relay session, "
                "Authority-bound TURN credential/allocation leases, approved bidirectional file "
                "transfer over vibescreen.bulk.v1, ordered chunks with per-chunk SHA-256 and final "
                "file SHA-256 verification, bounded bulk backpressure, timeout cancellation and "
                "cleanup, AES-256-GCM record-layer separation, and every listed Phase 3 release "
                "prerequisite. Relay deployment preflight work, including PR #404-style readyz/DNS/"
                "disk hardening, is not product E2E evidence by itself."
            ),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--write-default-manifest", action="store_true")
    parser.add_argument("--source-commit")
    parser.add_argument("--tree-status", choices=("clean", "dirty", "unknown"))
    parser.add_argument("--repo", type=Path, default=Path("."))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        current_commit, tree_clean = repository_state(args.repo)
        source_commit = args.source_commit or current_commit
        tree_status = args.tree_status or ("clean" if tree_clean else "dirty")
        if args.write_default_manifest:
            _write_json(args.manifest, default_manifest(source_commit=source_commit, tree_status=tree_status))
        report = derive_gate(
            args.manifest,
            current_commit=current_commit,
            tree_clean=tree_clean,
            evidence_root=args.manifest.parent,
        )
        _write_json(args.output, report)
    except (BulkProductFlowInputError, OSError, ValueError) as error:
        print(f"error: {sanitize_text(error)}", file=sys.stderr)
        return 2
    for reason in report["blockers"]:
        print(reason, file=sys.stderr)
    return 0 if report["verdict"] == PASS else (2 if report["verdict"] == FAIL else 1)


if __name__ == "__main__":
    raise SystemExit(main())
