"""Create an iOS current-base acceptance readiness manifest.

The manifest is preparation metadata for the Phase 5 iOS aggregate gate. It is
deliberately conservative: generated manifests start with every device gate open
and carry explicit limitations so a simulator build, unsigned archive, loopback,
or Android record cannot be promoted into iOS device acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

KIND = "ios_current_base_readiness_manifest"
AGGREGATE_OWNER = "current-base-ios-acceptance"
AGGREGATE_OWNER_PR = "#290"
DEVICE_ACCEPTANCE_OWNER_PR = "#290"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"

SCOPE_PRS = [
    "#182",
    "#196",
    "#207",
    "#208",
    "#209",
    "#238",
    "#251",
    "#253",
    "#257",
    "#279",
    "#282",
]
SOURCE_DOCS = [
    "docs/changes/2026-08-04-phase-5-ios-advanced/PRD.md",
    "docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md",
    "docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md",
    "docs/runbook/ios-device-acceptance.md",
]

FORMAL_DEVICE_GATES = {
    "signing": "signed archive, unique bundle ID, team, certificate, and provisioning profile",
    "device_install": "signed app installed and launched on both iPhone and iPad-class hardware",
    "protocol_session": "real iOS app/device trusted-LAN session envelopes against the host",
    "videotoolbox_h264": "hardware H.264 VideoToolbox decode on iOS hardware",
    "videotoolbox_hevc": "hardware HEVC VideoToolbox decode on iOS hardware",
    "input": "touch, drag, keyboard modifiers, and pointer/hover behavior with host acknowledgement",
    "reconnect": "network interruption and heartbeat reconnect with stale-epoch rejection",
    "audio_playback": "PCM S16LE AVAudioEngine playback with audible confirmation",
}

BROADER_GATES = {
    "hdr_output": "HDR/EDR output on iOS hardware, not SDR fallback only",
    "advanced_adapters": "host/product adapters for multi-client/display, audio, clipboard, files, actions, wake, and managed policy",
    "trusted_lan_secure_records": "secure-record trusted-LAN evidence; explicit plaintext legacy fallback is not enough",
}

DEFAULT_LIMITATIONS = [
    "This manifest does not claim an iOS device acceptance pass.",
    "Simulator builds, unsigned archives, MacHost loopback, and Android evidence do not close iOS device gates.",
    "The current iOS trusted-LAN baseline uses explicit plaintext legacy fallback and does not prove secure records.",
]

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_probe(command: Sequence[str], cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "command": list(command),
            "status": "blocked",
            "detail": str(error),
        }
    output = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return {
        "command": list(command),
        "status": "pass" if result.returncode == 0 else "blocked",
        "exit_code": result.returncode,
        "summary": output[:8],
    }


def _normalize_pr(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith("#"):
        digits = candidate[1:]
    else:
        digits = candidate
    if not digits.isdigit():
        raise ManifestError("--device-acceptance-owner-pr must be a PR number such as #290")
    owner_pr = f"#{int(digits)}"
    if owner_pr != DEVICE_ACCEPTANCE_OWNER_PR:
        raise ManifestError(
            f"device acceptance owner PR must remain {DEVICE_ACCEPTANCE_OWNER_PR}"
        )
    return owner_pr


def _ensure_source_docs(repo: Path, source_docs: Sequence[str]) -> list[str]:
    missing = [path for path in source_docs if not (repo / path).is_file()]
    if missing:
        raise ManifestError("missing source document(s): " + ", ".join(missing))
    return list(source_docs)


def _signing_probe() -> dict[str, Any]:
    result = _run_probe(["security", "find-identity", "-p", "codesigning", "-v"])
    summaries = result.get("summary", [])
    identity_count = 0
    if isinstance(summaries, list):
        for line in summaries:
            if isinstance(line, str) and re.search(r"\) [0-9A-Fa-f]{40} \".+\"", line):
                identity_count += 1
    result["valid_identity_count"] = identity_count
    result["status"] = "pass" if identity_count > 0 else "blocked"
    return result


def collect_environment(repo: Path) -> dict[str, Any]:
    return {
        "xcode_select": _run_probe(["xcode-select", "-p"]),
        "xcodebuild_version": _run_probe(["xcodebuild", "-version"]),
        "xcode_sdks": _run_probe(["xcodebuild", "-showsdks"]),
        "swift_version": _run_probe(["swift", "--version"], cwd=repo),
        "signing_identities": _signing_probe(),
    }


def _gate_record(name: str, requirement: str, *, category: str, blocking: bool) -> dict[str, Any]:
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
    for name, requirement in FORMAL_DEVICE_GATES.items():
        gates[name] = _gate_record(name, requirement, category="device_acceptance", blocking=True)
    for name, requirement in BROADER_GATES.items():
        gates[name] = _gate_record(name, requirement, category="broader_phase5", blocking=False)
    return gates


def default_devices() -> list[dict[str, Any]]:
    return [
        {
            "role": "iphone",
            "runtime_class": "missing",
            "install_status": "open",
            "evidence": [],
        },
        {
            "role": "ipad",
            "runtime_class": "missing",
            "install_status": "open",
            "evidence": [],
        },
    ]


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    device_acceptance_owner_pr: str = DEVICE_ACCEPTANCE_OWNER_PR,
    notes: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    owner_pr = _normalize_pr(device_acceptance_owner_pr)
    source_docs = _ensure_source_docs(repo, SOURCE_DOCS)
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
            "aggregate_pr": owner_pr,
            "device_acceptance_pr": owner_pr,
            "repository": REPOSITORY_FULL_NAME,
        },
        "scope_prs": list(SCOPE_PRS),
        "source_docs": source_docs,
        "local_environment": collect_environment(repo),
        "build_evidence": {
            "swift_build": {"status": "open", "evidence": []},
            "ios_selftest": {"status": "open", "evidence": []},
            "machost_loopback": {"status": "open", "evidence": []},
            "simulator_smoke": {"status": "open", "evidence": []},
            "unsigned_archive": {"status": "open", "evidence": []},
        },
        "signing": {
            "status": "blocked",
            "bundle_id": None,
            "unique_bundle_id": False,
            "team_id_redacted": True,
            "certificate_identity_recorded": False,
            "provisioning_profile_recorded": False,
            "signed_archive_sha256": None,
        },
        "devices": default_devices(),
        "gates": default_gates(),
        "android_evidence_used_for_ios_gates": False,
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
        "--device-acceptance-owner-pr",
        default=DEVICE_ACCEPTANCE_OWNER_PR,
        help="PR owning sanitized iOS current-base acceptance evidence validation, default #290",
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
        manifest = build_manifest(
            command=command,
            repo=args.repo,
            device_acceptance_owner_pr=args.device_acceptance_owner_pr,
            notes=args.notes,
        )
        write_json(args.output, manifest)
    except (ManifestError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if command:
        print(f"recorded command: {shlex.join(command)}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
