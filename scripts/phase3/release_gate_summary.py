#!/usr/bin/env python3
"""Summarize Phase 3 current-base evidence without closing release gates.

The summary is intentionally conservative: local loopback, synthetic peers,
forced local coturn, and blocked attempts can only document readiness. They never
turn the public Internet release gate green.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.phase3_webrtc.model import E2EFailure  # noqa: E402
from scripts.phase3_webrtc.public_schema import (  # noqa: E402
    PUBLIC_LIMITATIONS,
    read_json_file,
    validate_public_artifact_tree,
)

SCHEMA = "dev.vibescreen.phase3-release-gate-summary/v1"
AGGREGATE_OWNER = {
    "pull_request": 258,
    "title": "Add Phase 3 current-base release gate summary",
    "head_ref": "codex/phase3-current-base-gates",
    "role": "current_base_aggregate_owner",
}
DEFAULT_LOCAL_PUBLIC_DIR = Path(".build/phase3-local-synthetic-product-e2e/public")
DEFAULT_ANDROID_INTEROP = Path(
    "docs/changes/2026-08-04-phase-3-secure-internet/evidence/"
    "2026-08-05-nubia-p0110-internet/acceptance.json"
)
DEFAULT_BLOCKED_REAL_MEDIA = Path(
    "docs/changes/2026-08-04-phase-3-secure-internet/evidence/"
    "2026-08-18-nubia-p0110-current-main-real-media-blocked/acceptance.json"
)
DEFAULT_CURRENT_BASE_REAL_MEDIA = Path(
    ".build/evidence/phase3-real-media-current-base/current-base-real-media.json"
)

RELEASE_GATES = (
    (
        "public_internet_path",
        "Real Android and macOS peers traverse a genuine public Internet path.",
        194,
        "blocked_pending_public_deployment",
    ),
    (
        "real_remote_turn",
        "A deployed remote TURN route is selected and distinguished from forced local coturn.",
        194,
        "blocked_pending_remote_turn_deployment",
    ),
    (
        "screencapturekit_to_android_mediacodec",
        "Real ScreenCaptureKit or CGDisplayStream output reaches Android MediaCodec.",
        173,
        "blocked_current_base_attempt_no_capture_or_decode",
    ),
    (
        "visible_input_effects",
        "Touch and keyboard produce visible, host-side Mac input effects.",
        173,
        "blocked_pending_real_capture_session",
    ),
    (
        "network_handoff",
        "Wi-Fi/cellular or independently routed handoff resumes with a larger session epoch.",
        224,
        "blocked_pending_real_handoff_run",
    ),
    (
        "cross_service_revocation",
        "Authority, signaling, relay credential issuance, and active transport allocation all fail closed after revoke.",
        190,
        "blocked_pending_cross_service_active_allocation_proof",
    ),
    (
        "packet_capture_confidentiality",
        "Direct and TURN packet captures prove no plaintext content or credentials.",
        194,
        "blocked_pending_public_path_packet_capture",
    ),
    (
        "two_hour_mixed_route_soak",
        "A two-hour mixed direct/relay/network-change soak has bounded memory, queues, latency, and nonce use.",
        214,
        "blocked_pending_two_hour_public_mixed_route_run",
    ),
    (
        "production_services",
        "Production Authority/signaling/relay/coturn deployment gates pass with TLS, HA, PITR, NTP, and multi-node coverage.",
        254,
        "blocked_pending_deployed_production_enforcement",
    ),
    (
        "independent_security_review",
        "Protocol transcript, KDF, nonce, replay, rotation, revocation, and key storage pass independent review.",
        188,
        "blocked_pending_independent_security_review",
    ),
)

CANDIDATE_PRS = tuple(
    {"pull_request": number, "role": role, "recommendation": recommendation, "reason": reason}
    for number, role, recommendation, reason in (
        (164, "legacy_manifest_candidate", "supersede_with_aggregate_owner", "overlaps release-gate manifest ownership and is older-base/dirty"),
        (171, "network_recovery_handoff_slice", "keep_as_child_gate_after_rebase", "owns network recovery evidence, not aggregate status"),
        (172, "coturn_reconciliation_slice", "keep_as_child_gate_serialized_late", "touches authority/signaling/relay/coturn service state"),
        (173, "real_media_continuity_slice", "keep_as_child_gate", "owns ScreenCaptureKit-to-decoder blocked evidence"),
        (188, "release_gate_contracts_candidate", "narrow_or_supersede_aggregate_parts", "broad gate contracts duplicate aggregate ownership"),
        (190, "revocation_propagation_slice", "keep_as_child_gate", "owns fail-closed cross-service revocation checks"),
        (194, "public_internet_remote_turn_slice", "keep_as_child_gate", "owns public deployment and remote TURN blocked/readiness evidence"),
        (200, "authority_profile_issuance_slice", "keep_as_service_child_gate", "authority issuance supports production services but is not aggregate status"),
        (212, "internet_latency_slice", "keep_as_child_gate", "owns external-camera latency manifest/readiness"),
        (214, "internet_soak_slice", "keep_as_child_gate", "owns two-hour mixed-route soak gate"),
        (215, "signaling_multinode_slice", "superseded_by_merged_223_for_aggregate_accounting", "open PR overlaps merged signaling multi-node work"),
        (216, "qr_pairing_flow_slice", "keep_as_child_gate", "owns pairing-flow evidence and remains bounded"),
        (223, "merged_signaling_multinode_slice", "record_as_merged_child_gate", "merged into current base and supports production service readiness only"),
        (224, "runtime_network_handoff_slice", "keep_as_child_gate_after_rebase", "owns bounded handoff runtime changes, not release closure"),
        (228, "production_coturn_enforcement_slice", "keep_as_child_gate_serialized_late", "broad authority/relay/coturn changes should not be duplicated here"),
        (241, "merged_open_gates_audit_baseline", "record_as_docs_only_audit", "merged coverage audit informs ownership but is not an executable aggregate verifier"),
        (254, "production_e2e_enforcement_slice", "keep_as_child_gate", "owns blocked production enforcement package"),
        (258, "current_base_aggregate_owner", "use_as_unique_aggregate_owner", "current-base summary is executable and keeps all public release gates open"),
    )
)
HISTORICAL_ANDROID_BOUNDARY_DEFAULTS = {
    "network_scope": "local_direct_and_forced_local_coturn_only",
    "public_internet": "not_claimed",
    "real_remote_turn": "not_claimed",
    "android_mediacodec_decode": "not_claimed",
    "visible_mac_input_effects": "not_claimed",
}
REQUIRED_HISTORICAL_BOUNDARIES = {
    "disconnect_reconnect": "not_claimed",
    "real_display_content": "not_claimed",
    "screen_capture_kit": "not_claimed",
    "soak": "not_claimed",
}
REQUIRED_HISTORICAL_ASSERTIONS = {
    "real_android_app_and_instrumentation": "pass",
    "real_local_signaling_process": "pass",
    "synthetic_video_config_keyframe_delta": "pass",
}
REQUIRED_FALSE_REAL_MEDIA_CLAIMS = (
    "real_capture",
    "real_media_delivery",
    "hardware_decode",
    "internet_or_turn",
)
REQUIRED_CURRENT_BASE_REAL_MEDIA_CHECKS = (
    "continuity_schema",
    "continuity_passed",
    "current_base_commit",
    "continuity_source_clean",
    "android_device_identity",
    "public_internet_path",
    "identity_signed_host",
    "screen_recording_granted",
    "real_capture_first_frame",
    "videotoolbox_output",
    "webrtc_media_channel",
    "protocol_v1_epoch",
    "android_mediacodec_decode",
    "no_synthetic_media",
    "visible_android_ui",
    "no_decoder_errors",
    "bounded_drops",
)


class GateSummaryError(RuntimeError):
    """Raised when the summary cannot safely inspect its inputs."""


def git_revision(repo: Path) -> str:
    git = shutil.which("git")
    if git is None:
        raise GateSummaryError("cannot locate git to resolve repository HEAD")
    try:
        result = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except OSError as exception:
        raise GateSummaryError("cannot execute git to resolve repository HEAD") from exception
    if result.returncode != 0:
        raise GateSummaryError("cannot resolve repository HEAD")
    revision = result.stdout.strip().lower()
    if len(revision) < 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise GateSummaryError("repository HEAD is not a Git revision")
    return revision


def _resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _path_label(path: Path, repo: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo.resolve()).as_posix()
    except ValueError:
        return "<external-path>"


def _missing_record(kind: str, path_label: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "missing",
        "path": path_label,
        "release_gate_impact": "none",
    }


def _invalid_record(kind: str, path_label: str, errors: list[str]) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "invalid",
        "path": path_label,
        "errors": errors,
        "current_base": False,
        "release_gate_impact": "none",
    }


def _is_git_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _validate_input_record(
    value: object,
    *,
    expected_category: str,
    require_existing: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{expected_category} input record must be an object"]
    if value.get("category") != expected_category:
        errors.append(f"{expected_category} input record category is required")
    if not _non_empty_string(value.get("path")):
        errors.append(f"{expected_category} input record path is required")
    if not isinstance(value.get("extension"), str):
        errors.append(f"{expected_category} input record extension is required")
    exists = value.get("exists")
    if not isinstance(exists, bool):
        errors.append(f"{expected_category} input record exists must be boolean")
    if exists is not True and require_existing:
        errors.append(f"{expected_category} input record must exist")
    if exists is True or require_existing:
        if not _valid_sha256(value.get("sha256")):
            errors.append(f"{expected_category} input record sha256 is required")
        if not isinstance(value.get("bytes"), int) or value.get("bytes") <= 0:
            errors.append(f"{expected_category} input record bytes must be positive")
    elif value.get("sha256") is not None:
        errors.append(f"{expected_category} missing input record sha256 must be null")
    elif value.get("bytes") is not None:
        errors.append(f"{expected_category} missing input record bytes must be null")
    return errors


def inspect_local_public_artifacts(
    path: Path,
    current_commit: str,
    path_label: str,
) -> dict[str, Any]:
    if not path.exists():
        return _missing_record("local_synthetic_product_e2e", path_label)
    try:
        files = validate_public_artifact_tree(path, require_complete=True)
        direct = read_json_file(path / "direct.json", "public direct evidence")
        relay = read_json_file(path / "relay.json", "public relay evidence")
    except (E2EFailure, OSError) as error:
        return {
            "kind": "local_synthetic_product_e2e",
            "status": "invalid",
            "path": path_label,
            "error": str(error),
            "release_gate_impact": "none",
        }
    direct_source = direct["source"]
    relay_source = relay["source"]
    source_commit = direct_source["repository_commit"]
    return {
        "kind": "local_synthetic_product_e2e",
        "status": "pass",
        "path": path_label,
        "files": files,
        "current_base": (
            source_commit == current_commit
            and relay_source["repository_commit"] == current_commit
            and not direct_source["dirty"]
            and not relay_source["dirty"]
        ),
        "source_commit": source_commit,
        "modes": [direct["mode"], relay["mode"]],
        "limitations": direct["limitations"],
        "release_gate_impact": "readiness_only",
    }


def inspect_historical_android_interop(
    path: Path,
    current_commit: str,
    path_label: str,
) -> dict[str, Any]:
    if not path.exists():
        return _missing_record("historical_android_local_interop", path_label)
    value = read_json_file(path, "historical Android interop acceptance")
    source_commit = _source_commit(value)
    run_commits = _run_commits(value)
    device = value.get("device", {})
    raw_boundaries = value.get("evidence_boundaries", {})
    boundaries = _historical_android_boundaries(raw_boundaries)
    assertions = _historical_source_assertions(value)
    errors = _validate_historical_android_interop(
        value,
        source_commit,
        run_commits,
        device,
        raw_boundaries,
        assertions,
    )
    if errors:
        invalid = _invalid_record("historical_android_local_interop", path_label, errors)
        invalid.update(
            {
                "source_commit": source_commit,
                "run_commits": run_commits,
                "run_commits_match_source": _run_commits_match_source(
                    source_commit, run_commits
                ),
                "device": device if isinstance(device, dict) else {},
                "routes": value.get("routes", []),
                "evidence_boundaries": boundaries,
                "source_assertions": assertions,
            }
        )
        return invalid
    return {
        "kind": "historical_android_local_interop",
        "status": value.get("result", "unknown"),
        "path": path_label,
        "current_base": (
            source_commit == current_commit
            and _run_commits_match_source(source_commit, run_commits)
        ),
        "source_commit": source_commit,
        "run_commits": run_commits,
        "run_commits_match_source": _run_commits_match_source(source_commit, run_commits),
        "device": device,
        "routes": value.get("routes", []),
        "relay_kind": "forced_local_coturn",
        "evidence_boundaries": boundaries,
        "source_assertions": assertions,
        "release_gate_impact": "readiness_only",
    }


def inspect_blocked_real_media(
    path: Path,
    current_commit: str,
    path_label: str,
) -> dict[str, Any]:
    if not path.exists():
        return _missing_record("current_main_real_media_attempt", path_label)
    value = read_json_file(path, "blocked real-media acceptance")
    claims = value.get("claims", {})
    source_commit = value.get("source_commit")
    source_clean_before_run = value.get("source_dirty_before_run") is False
    errors = _validate_blocked_real_media(value, source_commit, claims)
    if errors:
        invalid = _invalid_record("current_main_real_media_attempt", path_label, errors)
        invalid.update(
            {
                "source_commit": source_commit,
                "source_clean_before_run": source_clean_before_run,
                "source_matched_origin_main": value.get("source_matched_origin_main"),
                "device": value.get("device", {}),
                "blocker": value.get("blocker", {}),
                "claims": claims if isinstance(claims, dict) else {},
            }
        )
        return invalid
    return {
        "kind": "current_main_real_media_attempt",
        "status": value.get("result", "unknown"),
        "path": path_label,
        "current_base": (
            source_commit == current_commit
            and source_clean_before_run
            and value.get("source_matched_origin_main") is True
        ),
        "source_commit": source_commit,
        "source_clean_before_run": source_clean_before_run,
        "source_matched_origin_main": value.get("source_matched_origin_main"),
        "device": value.get("device", {}),
        "blocker": value.get("blocker", {}),
        "claims": claims,
        "release_gate_impact": "blocked_readiness_only",
    }


def _validate_current_base_real_media(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schema_version") != "vibescreen.evidence/v1":
        errors.append("schema_version must be vibescreen.evidence/v1")
    if value.get("kind") != "phase3_real_media_current_base_gate":
        errors.append("kind must be phase3_real_media_current_base_gate")
    if value.get("gate_can_close_phase3_release") is not False:
        errors.append("gate_can_close_phase3_release must be false")
    release_gate_effect = value.get("release_gate_effect")
    if release_gate_effect not in {"none", "child_gate_only"}:
        errors.append("release_gate_effect must be none or child_gate_only")
    verdict = value.get("verdict")
    if verdict not in {"pass", "blocked", "fail"}:
        errors.append("verdict must be pass, blocked, or fail")
    can_claim = value.get("can_claim_current_base_real_media_continuity")
    if not isinstance(can_claim, bool):
        errors.append("can_claim_current_base_real_media_continuity must be boolean")
    elif verdict == "pass" and can_claim is not True:
        errors.append("pass verdict must claim current-base real-media continuity")
    elif verdict in {"blocked", "fail"} and can_claim is not False:
        errors.append("blocked or fail verdict cannot claim current-base real-media continuity")
    if verdict == "pass" and release_gate_effect != "child_gate_only":
        errors.append("pass verdict must use release_gate_effect child_gate_only")
    if verdict in {"blocked", "fail"} and release_gate_effect != "none":
        errors.append("blocked or fail verdict must use release_gate_effect none")
    current_base = value.get("current_base")
    if not isinstance(current_base, dict):
        errors.append("current_base must be an object")
    else:
        if not _is_git_revision(current_base.get("repository_commit")):
            errors.append("current_base.repository_commit must be a full Git revision")
        if not _is_git_revision(current_base.get("continuity_repository_revision")):
            errors.append("current_base.continuity_repository_revision must be a full Git revision")
        if not isinstance(current_base.get("continuity_repository_dirty"), bool):
            errors.append("current_base.continuity_repository_dirty must be boolean")
        if verdict == "pass" and current_base.get("continuity_repository_revision") != current_base.get("repository_commit"):
            errors.append("pass verdict requires continuity repository revision to match repository_commit")
        if verdict == "pass" and current_base.get("continuity_repository_dirty") is not False:
            errors.append("pass verdict requires clean continuity repository source")
    owner = value.get("owner")
    if not isinstance(owner, dict):
        errors.append("owner must be an object")
    else:
        if owner.get("role") != "phase3_real_media_current_base_owner":
            errors.append("owner.role must be phase3_real_media_current_base_owner")
        for key in ("pull_request", "head_ref", "scope"):
            if not _non_empty_string(owner.get(key)):
                errors.append(f"owner.{key} must be present")
        if owner.get("repository") != "TaoSama/vibe-screen":
            errors.append("owner.repository must be TaoSama/vibe-screen")
    source = value.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        errors.extend(
            _validate_input_record(
                source.get("continuity_result"),
                expected_category="real_media_continuity",
                require_existing=True,
            )
        )
        if not _is_git_revision(source.get("continuity_repository_revision")):
            errors.append("source.continuity_repository_revision must be a full Git revision")
        if not isinstance(source.get("continuity_repository_dirty"), bool):
            errors.append("source.continuity_repository_dirty must be boolean")
        if (
            verdict == "pass"
            and isinstance(current_base, dict)
            and source.get("continuity_repository_revision")
            != current_base.get("continuity_repository_revision")
        ):
            errors.append("pass verdict requires source revision to match current_base continuity revision")
        if (
            verdict == "pass"
            and isinstance(current_base, dict)
            and source.get("continuity_repository_dirty")
            != current_base.get("continuity_repository_dirty")
        ):
            errors.append("pass verdict requires source dirty flag to match current_base dirty flag")
    device = value.get("device")
    if not isinstance(device, dict):
        errors.append("device must be an object")
    else:
        for key in ("manufacturer", "model", "codename", "android_version"):
            if not _non_empty_string(device.get(key)):
                errors.append(f"device.{key} must be present")
        if not isinstance(device.get("sdk"), int):
            errors.append("device.sdk must be an integer")
    android_visible_ui = value.get("android_visible_ui")
    if not isinstance(android_visible_ui, dict):
        errors.append("android_visible_ui must be an object")
    else:
        artifact_kind = android_visible_ui.get("artifact_kind")
        if artifact_kind not in {
            "device_screenshot",
            "device_screen_recording",
            "external_camera_recording",
        }:
            errors.append("android_visible_ui.artifact_kind is invalid")
        operator_note = android_visible_ui.get("operator_note")
        if verdict == "pass" and not _non_empty_string(operator_note):
            errors.append("android_visible_ui.operator_note must be present")
        elif operator_note is not None and not isinstance(operator_note, str):
            errors.append("android_visible_ui.operator_note must be a string or null")
        artifacts = android_visible_ui.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append("android_visible_ui.artifacts must be a list")
        elif verdict == "pass" and not artifacts:
            errors.append("android_visible_ui.artifacts must contain at least one artifact")
        else:
            valid_extensions = {
                "device_screenshot": {".png", ".jpg", ".jpeg", ".webp"},
                "device_screen_recording": {".mp4", ".mov", ".webm"},
                "external_camera_recording": {".mp4", ".mov", ".webm"},
            }.get(artifact_kind, set())
            valid_artifacts = 0
            for artifact in artifacts:
                artifact_errors = _validate_input_record(
                    artifact,
                    expected_category="android_visible_ui",
                    require_existing=verdict == "pass",
                )
                if artifact_errors:
                    errors.extend(artifact_errors)
                    continue
                if artifact.get("artifact_kind") != artifact_kind:
                    errors.append("android_visible_ui artifact kind must match parent")
                    continue
                if artifact.get("extension") not in valid_extensions:
                    errors.append("android_visible_ui artifact extension is not allowed")
                    continue
                if artifact.get("exists") is True:
                    valid_artifacts += 1
            if verdict == "pass" and valid_artifacts == 0:
                errors.append("android_visible_ui must include at least one valid artifact")
    checks = value.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    else:
        for key in REQUIRED_CURRENT_BASE_REAL_MEDIA_CHECKS:
            check = checks.get(key)
            if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
                errors.append(f"check {key} must record a boolean passed value")
                continue
            if not _non_empty_string(check.get("expected")):
                errors.append(f"check {key} must record expected evidence")
            if not isinstance(check.get("evidence"), list):
                errors.append(f"check {key} must record an evidence list")
            if verdict == "pass" and check.get("passed") is not True:
                errors.append(f"pass verdict requires check {key} to pass")
    return errors


def inspect_current_base_real_media_gate(
    path: Path,
    current_commit: str,
    path_label: str,
) -> dict[str, Any]:
    if not path.exists():
        return _missing_record("current_base_real_media_gate", path_label)
    value = read_json_file(path, "current-base real-media gate")
    errors = _validate_current_base_real_media(value)
    current_base = value.get("current_base") if isinstance(value.get("current_base"), dict) else {}
    source_commit = current_base.get("repository_commit")
    commit_matches = source_commit == current_commit
    if errors:
        invalid = _invalid_record("current_base_real_media_gate", path_label, errors)
        invalid.update(
            {
                "verdict": value.get("verdict"),
                "source_commit": source_commit,
                "current_base": False,
            }
        )
        return invalid
    return {
        "kind": "current_base_real_media_gate",
        "status": value.get("verdict"),
        "path": path_label,
        "current_base": commit_matches,
        "source_commit": source_commit,
        "can_claim_current_base_real_media_continuity": (
            value.get("can_claim_current_base_real_media_continuity") is True
            and value.get("verdict") == "pass"
            and commit_matches
        ),
        "required_checks": {
            key: value["checks"][key]["passed"]
            for key in REQUIRED_CURRENT_BASE_REAL_MEDIA_CHECKS
        },
        "release_gate_impact": value.get("release_gate_effect"),
    }


def _validate_historical_android_interop(
    value: dict[str, Any],
    source_commit: str | None,
    run_commits: list[str],
    device: object,
    raw_boundaries: object,
    assertions: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if value.get("result") != "pass":
        errors.append("result must be pass for historical Android readiness")
    if not _is_git_revision(source_commit):
        errors.append("source commit must be a full Git revision")
    if not _run_commits_match_source(source_commit, run_commits):
        errors.append("run commits must be present and match the source commit")
    if (
        not isinstance(device, dict)
        or not device.get("product")
        or not device.get("codename")
    ):
        errors.append("device product and codename are required")
    routes = value.get("routes")
    if not isinstance(routes, list) or set(routes) != {"direct", "relay"}:
        errors.append("historical Android readiness must cover direct and relay routes only")
    if not isinstance(raw_boundaries, dict):
        errors.append("evidence boundaries are required")
    else:
        for key, expected in REQUIRED_HISTORICAL_BOUNDARIES.items():
            if raw_boundaries.get(key) != expected:
                errors.append(f"evidence boundary {key} must be {expected}")
    for key, expected in REQUIRED_HISTORICAL_ASSERTIONS.items():
        if assertions.get(key) != expected:
            errors.append(f"source assertion {key} must be {expected}")
    return errors


def _validate_blocked_real_media(
    value: dict[str, Any],
    source_commit: object,
    claims: object,
) -> list[str]:
    errors: list[str] = []
    if value.get("result") != "blocked":
        errors.append("result must be blocked for blocked real-media readiness")
    if not _is_git_revision(source_commit):
        errors.append("source_commit must be a full Git revision")
    if not isinstance(value.get("source_dirty_before_run"), bool):
        errors.append("source_dirty_before_run must be boolean")
    if not isinstance(value.get("source_matched_origin_main"), bool):
        errors.append("source_matched_origin_main must be boolean")
    device = value.get("device")
    if (
        not isinstance(device, dict)
        or not device.get("product")
        or not device.get("codename")
    ):
        errors.append("device product and codename are required")
    blocker = value.get("blocker")
    if not isinstance(blocker, dict) or not blocker.get("component"):
        errors.append("blocker component is required")
    if not isinstance(claims, dict):
        errors.append("claims must be an object")
    else:
        for key in REQUIRED_FALSE_REAL_MEDIA_CLAIMS:
            if claims.get(key) is not False:
                errors.append(f"claim {key} must be false")
    return errors


def _first_run_commit(value: dict[str, Any]) -> str | None:
    runs = value.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    first = runs[0]
    if not isinstance(first, dict):
        return None
    gate = first.get("adb_gate")
    if not isinstance(gate, dict):
        return None
    commit = gate.get("commit")
    return commit if isinstance(commit, str) else None


def _source_commit(value: dict[str, Any]) -> str | None:
    source = value.get("source")
    if isinstance(source, dict):
        commit = source.get("commit")
        if isinstance(commit, str):
            return commit
    return _first_run_commit(value)


def _run_commits(value: dict[str, Any]) -> list[str]:
    runs = value.get("runs")
    if not isinstance(runs, list):
        return []
    commits: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        gate = run.get("adb_gate")
        if not isinstance(gate, dict):
            continue
        commit = gate.get("commit")
        if isinstance(commit, str):
            commits.append(commit)
    return commits


def _run_commits_match_source(source_commit: str | None, run_commits: list[str]) -> bool:
    if source_commit is None or not run_commits:
        return False
    return all(commit == source_commit for commit in run_commits)


def _historical_android_boundaries(value: object) -> dict[str, Any]:
    boundaries = dict(value) if isinstance(value, dict) else {}
    for key, marker in HISTORICAL_ANDROID_BOUNDARY_DEFAULTS.items():
        boundaries.setdefault(key, marker)
    return boundaries


def _historical_source_assertions(value: dict[str, Any]) -> dict[str, Any]:
    runs = value.get("runs")
    first = (
        runs[0]
        if isinstance(runs, list) and runs and isinstance(runs[0], dict)
        else value
    )
    assertions = first.get("assertions") if isinstance(first, dict) else None
    if not isinstance(assertions, dict):
        return {}
    return {
        key: assertions.get(key)
        for key in (
            "real_local_signaling_process",
            "synthetic_video_config_keyframe_delta",
            "real_android_app_and_instrumentation",
        )
        if key in assertions
    }


def release_gate_rows() -> list[dict[str, Any]]:
    return [
        {
            "gate": name,
            "status": "open",
            "required_evidence": required,
            "current_base_evidence": "not_present",
            "owner_pr": owner_pr,
            "evidence_state": evidence_state,
        }
        for name, required, owner_pr, evidence_state in RELEASE_GATES
    ]


def build_summary(
    repo: Path,
    *,
    local_public_dir: Path = DEFAULT_LOCAL_PUBLIC_DIR,
    android_interop_acceptance: Path = DEFAULT_ANDROID_INTEROP,
    blocked_real_media_acceptance: Path = DEFAULT_BLOCKED_REAL_MEDIA,
    current_base_real_media_gate: Path = DEFAULT_CURRENT_BASE_REAL_MEDIA,
    current_commit: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    commit = current_commit or git_revision(repo)
    local_public_path = _resolve(repo, local_public_dir)
    android_interop_path = _resolve(repo, android_interop_acceptance)
    blocked_real_media_path = _resolve(repo, blocked_real_media_acceptance)
    current_base_real_media_path = _resolve(repo, current_base_real_media_gate)
    observations = [
        inspect_local_public_artifacts(
            local_public_path,
            commit,
            _path_label(local_public_path, repo),
        ),
        inspect_historical_android_interop(
            android_interop_path,
            commit,
            _path_label(android_interop_path, repo),
        ),
        inspect_blocked_real_media(
            blocked_real_media_path,
            commit,
            _path_label(blocked_real_media_path, repo),
        ),
        inspect_current_base_real_media_gate(
            current_base_real_media_path,
            commit,
            _path_label(current_base_real_media_path, repo),
        ),
    ]
    return {
        "schema": SCHEMA,
        "result": "open",
        "aggregate_owner": dict(AGGREGATE_OWNER),
        "current_base": {"repository_commit": commit},
        "candidate_prs": list(CANDIDATE_PRS),
        "readiness_observations": observations,
        "release_gates": release_gate_rows(),
        "classification_rules": {
            "local_loopback_synthetic": "readiness only; cannot close public Internet or Android-device gates",
            "forced_local_coturn": "readiness only; distinct from deployed remote TURN",
            "historical_device_synthetic_media": "bound only to its recorded source and device",
            "blocked_attempt": "records blocker only; cannot be promoted to pass",
            "current_base_real_media_child_gate": "may prove only the ScreenCaptureKit/CGDisplayStream to Android MediaCodec plus visible Android UI child gate; it still cannot close the Phase 3 public release gate alone",
            "release_gate": "requires real public-path Android/macOS evidence with ScreenCaptureKit-to-MediaCodec, handoff, revocation, capture privacy, latency, and soak artifacts",
        },
        "fixed_public_limitations": list(PUBLIC_LIMITATIONS),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize Phase 3 current-base evidence and open release gates."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--local-public-dir", type=Path, default=DEFAULT_LOCAL_PUBLIC_DIR)
    parser.add_argument("--android-interop-acceptance", type=Path, default=DEFAULT_ANDROID_INTEROP)
    parser.add_argument("--blocked-real-media-acceptance", type=Path, default=DEFAULT_BLOCKED_REAL_MEDIA)
    parser.add_argument("--current-base-real-media-gate", type=Path, default=DEFAULT_CURRENT_BASE_REAL_MEDIA)
    parser.add_argument(
        "--current-commit",
        help="Git revision to record as the current base; defaults to git rev-parse HEAD.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-release-pass",
        action="store_true",
        help="Return nonzero while any Phase 3 public release gate remains open.",
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = parse_arguments(arguments)
    try:
        resolved_commit = git_revision(args.repo.resolve())
        current_commit = resolved_commit
        if args.current_commit is not None:
            current_commit = args.current_commit.lower()
            if current_commit != resolved_commit:
                raise GateSummaryError(
                    "--current-commit does not match the checked-out repository HEAD"
                )
        summary = build_summary(
            args.repo,
            local_public_dir=args.local_public_dir,
            android_interop_acceptance=args.android_interop_acceptance,
            blocked_real_media_acceptance=args.blocked_real_media_acceptance,
            current_base_real_media_gate=args.current_base_real_media_gate,
            current_commit=current_commit,
        )
    except (E2EFailure, GateSummaryError) as error:
        print(f"Phase 3 release gate summary: FAIL ({error})", file=sys.stderr)
        return 2
    if args.output is not None:
        write_json(args.output, summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    if args.require_release_pass and summary["result"] != "pass":
        print("Phase 3 public Internet release gate remains open", file=sys.stderr)
        return 1
    print("Phase 3 release gate summary: OPEN", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
