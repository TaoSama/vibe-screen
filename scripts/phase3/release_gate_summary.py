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


class GateSummaryError(RuntimeError):
    """Raised when the summary cannot safely inspect its inputs."""


def git_revision(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
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
    boundaries = _historical_android_boundaries(value.get("evidence_boundaries", {}))
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
        "source_assertions": _historical_source_assertions(value),
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
    return {
        "kind": "current_main_real_media_attempt",
        "status": value.get("result", "unknown"),
        "path": path_label,
        "current_base": source_commit == current_commit and source_clean_before_run,
        "source_commit": source_commit,
        "source_clean_before_run": source_clean_before_run,
        "source_matched_origin_main": value.get("source_matched_origin_main"),
        "device": value.get("device", {}),
        "blocker": value.get("blocker", {}),
        "claims": claims,
        "release_gate_impact": "blocked_readiness_only",
    }


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
    current_commit: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    commit = current_commit or git_revision(repo)
    local_public_path = _resolve(repo, local_public_dir)
    android_interop_path = _resolve(repo, android_interop_acceptance)
    blocked_real_media_path = _resolve(repo, blocked_real_media_acceptance)
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
        summary = build_summary(
            args.repo,
            local_public_dir=args.local_public_dir,
            android_interop_acceptance=args.android_interop_acceptance,
            blocked_real_media_acceptance=args.blocked_real_media_acceptance,
            current_commit=args.current_commit,
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
