#!/usr/bin/env python3
"""Write blocked Phase 3 network recovery evidence.

This report is not a release-gate pass. It records why public Internet,
network handoff, and mixed-route soak validation could not start in the current
environment without touching the shared Android device or local network state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "dev.vibescreen.phase3-network-recovery-blocked/v1"
RELEASE_GATE_SCHEMA = "dev.vibescreen.phase3-release-gate-manifest/v1"
BLOCKED_GATES = (
    "public_internet_direct_path",
    "remote_turn_relay_path",
    "real_screencapturekit_to_android_media",
    "network_handoff_recovery",
    "cross_service_revocation",
    "packet_capture_confidentiality",
    "external_camera_latency",
    "two_hour_mixed_route_soak",
)
DEFAULT_BLOCKERS = (
    "missing_internet_device_lease",
    "no_controlled_network_impairment_harness",
    "no_public_internet_or_remote_turn_route",
    "no_real_handoff_or_two_hour_soak_window",
)


class BlockedEvidenceError(ValueError):
    """Raised when blocked evidence arguments are invalid."""


def git_output(root: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        command = " ".join(arguments)
        raise BlockedEvidenceError(f"git {command} failed")
    return completed.stdout.strip()


def source_state(root: Path) -> dict[str, Any]:
    status = git_output(root, ["status", "--porcelain=v1"])
    return {
        "commit": git_output(root, ["rev-parse", "HEAD"]),
        "tree_status": "dirty" if status else "clean",
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def blocked_release_manifest(args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    gate_defaults = {
        "status": "blocked",
        "synthetic_media": True,
        "local_loopback_only": True,
        "evidence_files": ["blocked-evidence.json", "README.md"],
        "blockers": list(args.blocker),
    }
    return {
        "schema": RELEASE_GATE_SCHEMA,
        "result": "blocked",
        "source": {"commit": source["commit"], "tree_status": source["tree_status"]},
        "device": {
            "manufacturer": args.device_manufacturer,
            "model": args.device_model,
            "codename": args.device_codename,
            "os_version": args.device_os_version,
            "evidence_role": "general_android_substitute",
        },
        "artifacts": {"mac_host_sha256": "blocked", "android_apk_sha256": "blocked"},
        "claims": [
            "Blocked readiness record only; no Phase 3 Internet release gate is closed.",
            f"Device target is {args.device_manufacturer} {args.device_model}/{args.device_codename}; primary-device evidence is not claimed.",
        ],
        "gates": {gate: dict(gate_defaults) for gate in BLOCKED_GATES},
    }


def build_evidence(args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    if not args.blocker:
        raise BlockedEvidenceError("at least one blocker is required")
    adb_command = f"adb -s {args.device_serial} ..." if args.device_serial else "adb -s <device-serial> ..."
    return {
        "schema": SCHEMA,
        "result": "blocked",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "device": {
            "manufacturer": args.device_manufacturer,
            "model": args.device_model,
            "codename": args.device_codename,
            "os_version": args.device_os_version,
            "api_level": args.device_api_level,
            "adb_serial_used": False,
        },
        "blocked_before_adb": True,
        "adb_command_required_for_future_run": adb_command,
        "blocked_gates": list(BLOCKED_GATES),
        "blockers": list(args.blocker),
        "readiness_improvements": [
            "release-gate manifest validator requires real controlled impairment metadata for handoff and mixed-route soak claims",
            "network-handoff release claims require fresh-session or ICE-restart timeline fields, old-session closure, epoch advance, stale-epoch rejection, and stream resume timing",
            "deterministic network-profile output is scoped as contract simulation and cannot close real Internet, ICE, TURN, latency, or soak gates",
        ],
        "claims": {
            "public_internet": False,
            "remote_turn": False,
            "real_network_handoff": False,
            "real_screencapturekit_to_android_media": False,
            "two_hour_soak": False,
            "phase3_release_gate_closed": False,
        },
    }


def build_readme(evidence: dict[str, Any]) -> str:
    source = evidence["source"]
    device = evidence["device"]
    blockers = "\n".join(f"- {item}" for item in evidence["blockers"])
    adb_command = evidence["adb_command_required_for_future_run"]
    return (
        "# Phase 3 network handoff and soak readiness - BLOCKED\n\n"
        "This is a blocked readiness record, not release evidence. No ADB command was run "
        "and no local network state was changed. The future Android command boundary must use "
        f"`{adb_command}`; that endpoint is recorded only as the intended shared "
        "device handle. The device identity for this run remains "
        f"`{device['manufacturer']} {device['model']} / {device['codename']} / {device['os_version']}`.\n\n"
        "## Result\n\n"
        "**BLOCKED.** The real Phase 3 public Internet, remote TURN, handoff, and two-hour "
        "mixed-route soak gates were not executed. The source snapshot was "
        f"`{source['commit']}` with tree status `{source['tree_status']}` at evidence creation.\n\n"
        "## Blockers\n\n"
        f"{blockers}\n\n"
        "## What This Proves\n\n"
        "- The run did not claim public Internet, remote TURN, real ScreenCaptureKit to Android "
        "media, real network handoff, latency, or soak acceptance.\n"
        "- The repository now has machine-checkable release-gate manifest requirements for "
        "controlled impairment metadata and fresh-session or ICE-restart recovery fields.\n"
        "- The deterministic network-profile simulator remains labelled as contract simulation "
        "only and cannot close real network gates.\n\n"
        "## Evidence Layout\n\n"
        "- `blocked-evidence.json`: machine-readable blocker and readiness-improvement record.\n"
        "- `release-gate-manifest.json`: intentionally blocked manifest; it must fail the pass verifier.\n"
        "- `README.md`: this summary.\n"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device-manufacturer", default="nubia")
    parser.add_argument("--device-model", default="P0110")
    parser.add_argument("--device-codename", default="pacific")
    parser.add_argument("--device-os-version", default="Android 16")
    parser.add_argument("--device-api-level", type=int, default=36)
    parser.add_argument("--device-serial", default="EP0110PZ0B9110300B")
    parser.add_argument("--blocker", action="append", default=list(DEFAULT_BLOCKERS))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = source_state(args.repo_root.resolve())
        evidence = build_evidence(args, source)
        output_dir = args.output_dir.resolve()
        write_json(output_dir / "blocked-evidence.json", evidence)
        write_json(output_dir / "release-gate-manifest.json", blocked_release_manifest(args, source))
        write_text(output_dir / "README.md", build_readme(evidence))
    except (BlockedEvidenceError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"BLOCKED: evidence written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
