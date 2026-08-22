"""Create a Phase 3 production end-to-end evidence manifest.

The manifest is deliberately conservative. A generated manifest is only a
current-base planning artifact: every production gate starts open and local or
synthetic evidence is labeled as readiness only until a real public-network run
fills in the retained artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

KIND = "phase3_production_e2e_manifest"
AGGREGATE_OWNER = "phase3-production-e2e-current-base"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"

SCOPE_PRS = [
    "#164",
    "#188",
    "#190",
    "#194",
    "#200",
    "#212",
    "#214",
    "#215",
    "#216",
    "#224",
    "#228",
    "#248",
    "#254",
    "#258",
    "#276",
]

SOURCE_DOCS = [
    "README.md",
    "docs/changes/2026-08-04-phase-3-secure-internet/PRD.md",
    "docs/changes/2026-08-04-phase-3-secure-internet/TECH.md",
    "docs/changes/2026-08-04-phase-3-secure-internet/TEST.md",
    "docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md",
]

REQUIRED_PRODUCTION_GATES = {
    "production_deployment": "production signaling, Authority, relay, and coturn endpoints are deployed with production configuration and retained sanitized config evidence",
    "public_internet_path": "the session crosses a genuine public Internet/NAT path instead of loopback, adb reverse, simulator, emulator, or same-host networking",
    "real_remote_turn": "a forced-relay leg uses a remote TURN allocation with relay candidate-pair evidence and no local coturn substitution",
    "real_capture_to_mediacodec": "real ScreenCaptureKit or CGDisplayStream output is encoded by the Host and decoded by Android MediaCodec with first-frame/device evidence",
    "android_device_ui": "a physical Android device runs the production UI/session rather than a synthetic Protocol v1 harness",
    "input_round_trip": "touch and keyboard input traverse the production Internet session and produce visible or logged Host effects",
    "network_handoff_recovery": "Wi-Fi/cellular or independently routed network handoff recovers with bounded duration, fresh session state, and rejected stale traffic",
    "revocation_propagation": "device/session revocation propagates across Authority, signaling, relay/TURN admission, and both peers, blocking direct and relay reconnect",
    "mixed_route_soak": "a two-hour mixed direct/relay/network-change soak proves bounded queues, memory, latency, loss, RTT, FPS, bitrate, relay bytes, battery, and thermal behavior",
    "latency": "external-camera or formally synchronized physical-input latency evidence covers direct and relay Internet paths",
    "privacy_scan": "all retained logs, manifests, packet-capture notes, and diagnostics pass the Phase 3 secret/privacy scan",
}

READINESS_GATES = {
    "local_synthetic_e2e": "local direct and forced-local-coturn product E2E readiness with synthetic Protocol v1 peer only",
    "service_contracts": "Phase 3 protocol, crypto, signaling, Authority, relay, static profile, and local container tests pass on current source",
    "pr_coordination": "open Phase 3 PR ownership and merge order are recorded so the aggregate does not duplicate sub-gate work",
}

DEFAULT_LIMITATIONS = [
    "Generated manifests do not claim a Phase 3 production release pass.",
    "Local loopback, adb reverse, emulator, simulator, forced local coturn, and synthetic Protocol v1 harness evidence are readiness only.",
    "A pass requires real public-network/TURN, real ScreenCaptureKit-to-Android MediaCodec continuity, revocation propagation, latency, privacy, and two-hour mixed-route soak evidence.",
]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_source_docs(repo: Path, source_docs: Sequence[str]) -> list[str]:
    missing = [path for path in source_docs if not (repo / path).is_file()]
    if missing:
        raise ManifestError("missing source document(s): " + ", ".join(missing))
    return list(source_docs)


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _gate_record(requirement: str, *, category: str, blocking: bool) -> dict[str, Any]:
    return {
        "status": "open",
        "category": category,
        "requirement": requirement,
        "blocking": blocking,
        "evidence": [],
        "notes": [],
    }


def default_gates() -> dict[str, dict[str, Any]]:
    gates: dict[str, dict[str, Any]] = {}
    for name, requirement in REQUIRED_PRODUCTION_GATES.items():
        gates[name] = _gate_record(requirement, category="production_e2e", blocking=True)
    for name, requirement in READINESS_GATES.items():
        gates[name] = _gate_record(requirement, category="readiness", blocking=False)
    return gates


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    aggregate_owner_pr: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_timestamp(),
        "command": list(command),
        "repository": repository_state(repo),
        "source_root": str(repo),
        "owner": {
            "aggregate": AGGREGATE_OWNER,
            "aggregate_pr": aggregate_owner_pr,
            "repository": REPOSITORY_FULL_NAME,
            "scope_prs": list(SCOPE_PRS),
        },
        "scope_prs": list(SCOPE_PRS),
        "source_docs": _ensure_source_docs(repo, SOURCE_DOCS),
        "production_environment": {
            "public_internet_path": False,
            "remote_turn": False,
            "production_authority": False,
            "managed_postgresql": False,
            "tls_public_ingress": False,
            "ntp_monitoring": False,
        },
        "device": {
            "runtime_class": "missing",
            "manufacturer": None,
            "model": None,
            "codename": None,
            "android_release": None,
            "sdk": None,
            "identity_label": None,
            "evidence": [],
        },
        "host": {
            "capture_source": "missing",
            "capture_api": None,
            "encoder": None,
            "build_identity": None,
            "screen_recording_permission": "unknown",
            "evidence": [],
        },
        "android_artifact": {
            "apk_sha256": None,
            "version_name": None,
            "version_code": None,
            "evidence": [],
        },
        "claims": {
            "local_loopback_used_for_production": False,
            "synthetic_protocol_v1_used_for_production": False,
            "simulator_or_emulator_used_for_production": False,
            "legacy_plaintext_fallback_used": False,
            "historical_or_stale_source_used_for_current_gate": False,
        },
        "gates": default_gates(),
        "required_artifacts": [
            "README.md",
            "phase3-production-e2e-manifest.json",
            "phase3-production-e2e-gate.json",
            "commands.txt",
            "host-version.txt",
            "client-version.txt",
            "artifact-sha256.txt",
            "device-properties.txt",
            "public-network-observation.json",
            "remote-turn-observation.json",
            "capture-decode-observation.json",
            "revocation-propagation.json",
            "network-handoff.jsonl",
            "soak-2h/summary.json",
            "latency/latency-evidence-report.json",
            "privacy-scan.json",
        ],
        "limitations": list(DEFAULT_LIMITATIONS),
        "notes": notes,
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--aggregate-owner-pr",
        help="PR number for the current-base aggregate owner, such as #277, once assigned",
    )
    parser.add_argument(
        "--scope-prs",
        help="comma-separated PR list for documentation only; defaults to the known Phase 3 PR set",
    )
    parser.add_argument("--notes")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Exact evidence command, placed after -- (optional)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        document = build_manifest(
            command=command,
            repo=args.repo,
            aggregate_owner_pr=args.aggregate_owner_pr,
            notes=args.notes,
        )
        if args.scope_prs:
            scope_prs = _split_csv(args.scope_prs)
            document["scope_prs"] = scope_prs
            document["owner"]["scope_prs"] = scope_prs
        write_json(args.output, document)
    except (ManifestError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
