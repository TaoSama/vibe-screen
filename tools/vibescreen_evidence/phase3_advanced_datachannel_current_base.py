"""Evaluate Phase 3 advanced Internet DataChannel current-base evidence.

The checker is intentionally conservative: source-level raw audio/bulk hooks,
USB/LAN TCP evidence, local loopback, forced local coturn, and synthetic peers
are readiness signals only. A pass requires retained product-flow evidence for
audio, clipboard, and file transfer over the Internet WebRTC DataChannels.
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

KIND = "phase3_advanced_datachannel_current_base_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
OWNER_ROLE = "phase3_advanced_datachannel_current_base_owner"
OWNER_BRANCH = "codex/phase3-advanced-datachannel-owner"

REQUIRED_GATES = {
    "internet_transport_scope": "real macOS and Android peers over a genuine public Internet WebRTC path",
    "audio_product_flow": "PCM audio capture/playback over vibescreen.audio.v1 with Android playback evidence",
    "clipboard_product_flow": "explicit clipboard offer/request/content over the protected control DataChannel",
    "file_transfer_product_flow": "approved file transfer over vibescreen.bulk.v1 with chunk/backpressure/digest evidence",
    "advanced_channel_backpressure": "owner-scoped audio/bulk admission, bounded backlog, and stale-owner rejection",
    "aes_record_layer_boundary": "distinct AES-256-GCM key/nonce/replay domains for control, media, audio, and bulk",
}

GATE_EVIDENCE_REQUIREMENTS = {
    "internet_transport_scope": {
        "evidence_kind": "internet_transport_scope",
        "channels": {"vibescreen.control.v1", "vibescreen.audio.v1", "vibescreen.bulk.v1"},
    },
    "audio_product_flow": {
        "evidence_kind": "audio_product_flow",
        "channel": "vibescreen.audio.v1",
    },
    "clipboard_product_flow": {
        "evidence_kind": "clipboard_product_flow",
        "channel": "vibescreen.control.v1",
    },
    "file_transfer_product_flow": {
        "evidence_kind": "file_transfer_product_flow",
        "channel": "vibescreen.bulk.v1",
    },
    "advanced_channel_backpressure": {
        "evidence_kind": "advanced_channel_backpressure",
        "channels": {"vibescreen.audio.v1", "vibescreen.bulk.v1"},
        "bounded_backpressure": True,
    },
    "aes_record_layer_boundary": {
        "evidence_kind": "aes_record_layer_boundary",
        "channels": {
            "vibescreen.control.v1",
            "vibescreen.media.v1",
            "vibescreen.audio.v1",
            "vibescreen.bulk.v1",
        },
        "separate_aes_domains": True,
    },
}

DISALLOWED_EVIDENCE_FLAGS = (
    "usb_lan_tcp",
    "trusted_lan",
    "local_loopback",
    "forced_local_coturn",
    "synthetic_peer",
    "raw_hook_test",
)

REQUIRED_CONTEXT_TRUE = {
    "real_macos_host": "real macOS Host participated",
    "real_android_device": "real Android device participated",
    "public_internet_path": "route used public Internet rather than local loopback",
    "identity_signed_host": "Host build was identity-signed",
    "no_plaintext_fallback": "no plaintext legacy fallback was used",
    "no_synthetic_peer": "no synthetic peer was used as product evidence",
}

SUBSTITUTION_FLAGS = {
    "usb_lan_tcp_evidence_used_for_internet": "USB/LAN TCP evidence cannot close Internet DataChannel flows",
    "ios_trusted_lan_evidence_used_for_android_internet": "iOS trusted-LAN evidence cannot close Android Internet flows",
    "local_loopback_or_forced_local_coturn_used_as_public_internet": "local loopback or forced local coturn cannot close public Internet scope",
    "raw_channel_hook_tests_used_as_product_flow": "raw channel hook tests cannot close product-flow evidence",
}

HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class AdvancedDataChannelInputError(ValueError):
    """Raised when the evidence manifest cannot be evaluated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdvancedDataChannelInputError(f"could not read manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise AdvancedDataChannelInputError("manifest must be a JSON object")
    return document


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
        raise AdvancedDataChannelInputError(f"could not inspect repository: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AdvancedDataChannelInputError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def repository_state(repo: Path) -> tuple[str, bool]:
    commit = _run_git(repo, ["rev-parse", "HEAD"]).lower()
    if HASH_RE.fullmatch(commit) is None:
        raise AdvancedDataChannelInputError("git rev-parse HEAD did not return a 40-character commit")
    return commit, _run_git(repo, ["status", "--porcelain"]) == ""


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AdvancedDataChannelInputError(f"could not hash evidence artifact {path}: {error}") from error
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
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return False
    return not value


def _bool(value: Any) -> bool:
    return value is True


def _evidence_artifact_path(root: Path | None, value: Any) -> Path | None:
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


def _load_evidence_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, f"retained artifact is not readable JSON: {error}"
    if not isinstance(document, dict):
        return None, "retained artifact JSON must be an object"
    return document, None


def _validate_evidence_metadata(
    metadata: dict[str, Any],
    gate_name: str,
    *,
    source: str,
) -> list[str]:
    problems: list[str] = []
    requirement = GATE_EVIDENCE_REQUIREMENTS[gate_name]

    expected_kind = requirement["evidence_kind"]
    if metadata.get("evidence_kind") != expected_kind:
        problems.append(f"{source}.evidence_kind must be {expected_kind}")
    for field, expected in (
        ("scope", "public_internet"),
        ("route_kind", "public_internet"),
        ("transport", "webrtc_datachannel"),
        ("peer_kind", "product"),
    ):
        if metadata.get(field) != expected:
            problems.append(f"{source}.{field} must be {expected}")
    for field in (
        "real_macos_host",
        "real_android_device",
        "public_internet_path",
        "no_plaintext_fallback",
        "no_synthetic_peer",
    ):
        if not _bool(metadata.get(field)):
            problems.append(f"{source}.{field} must be true")
    for field in DISALLOWED_EVIDENCE_FLAGS:
        if metadata.get(field) is True:
            problems.append(f"{source}.{field} evidence is disallowed for this gate")
    if not _empty_marker_list(metadata.get("disallowed_markers")):
        problems.append(f"{source}.disallowed_markers must be empty")

    expected_channel = requirement.get("channel")
    if isinstance(expected_channel, str) and metadata.get("channel") != expected_channel:
        problems.append(f"{source}.channel must be {expected_channel}")
    expected_channels = requirement.get("channels")
    if isinstance(expected_channels, set):
        channels = set(_string_list(metadata.get("channels")))
        if not expected_channels.issubset(channels):
            expected = ", ".join(sorted(expected_channels))
            problems.append(f"{source}.channels must include {expected}")
    if requirement.get("bounded_backpressure") is True and metadata.get("bounded_backpressure") is not True:
        problems.append(f"{source}.bounded_backpressure must be true")
    if requirement.get("separate_aes_domains") is True and metadata.get("separate_aes_domains") is not True:
        problems.append(f"{source}.separate_aes_domains must be true")
    return problems


def _evidence_record_valid(
    record: Any,
    gate_name: str,
    *,
    evidence_root: Path | None,
) -> tuple[bool, list[str]]:
    if not isinstance(record, dict):
        return False, ["evidence record must be an object"]

    problems: list[str] = []
    path = _evidence_artifact_path(evidence_root, record.get("path"))
    if path is None or not path.is_file():
        problems.append("retained artifact path is missing or outside the evidence directory")
    expected_sha = record.get("sha256")
    if not isinstance(expected_sha, str) or SHA256_RE.fullmatch(expected_sha) is None:
        problems.append("retained artifact sha256 is missing or invalid")
    elif path is not None and path.is_file() and _sha256(path).lower() != expected_sha.lower():
        problems.append("retained artifact sha256 does not match")

    problems.extend(_validate_evidence_metadata(record, gate_name, source="manifest evidence"))
    if path is not None and path.is_file():
        artifact, error = _load_evidence_json(path)
        if error is not None:
            problems.append(error)
        elif artifact is not None:
            problems.extend(_validate_evidence_metadata(artifact, gate_name, source="retained artifact"))

    return not problems, problems


def _check(
    passed: bool,
    expected: str,
    *,
    evidence: Sequence[str] = (),
    blocking: bool = True,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": list(evidence),
        "blocking": blocking,
    }


def _gate_check(
    manifest: dict[str, Any],
    name: str,
    expected: str,
    *,
    evidence_root: Path | None,
) -> dict[str, Any]:
    gates = _dict(manifest.get("gates"))
    gate = _dict(gates.get(name))
    status = gate.get("status")
    evidence = gate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return _check(False, expected, evidence=["missing structured retained evidence"])

    artifacts: list[str] = []
    problems: list[str] = []
    for index, record in enumerate(evidence):
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            artifacts.append(record["path"])
        valid, record_problems = _evidence_record_valid(record, name, evidence_root=evidence_root)
        if not valid:
            problems.extend(f"evidence[{index}]: {problem}" for problem in record_problems)
    return _check(status == PASS and not problems, expected, evidence=artifacts + problems)


def default_manifest(
    *,
    source_commit: str | None = None,
    tree_status: str = "unknown",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "phase3_advanced_datachannel_current_base_manifest",
        "created_at": _utc_now(),
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "pull_request": "pending",
            "repository": REPOSITORY_FULL_NAME,
        },
        "source": {
            "commit": source_commit,
            "tree_status": tree_status,
        },
        "evidence_context": {
            "real_macos_host": False,
            "real_android_device": False,
            "public_internet_path": False,
            "identity_signed_host": False,
            "no_plaintext_fallback": True,
            "no_synthetic_peer": True,
        },
        "substitutions": {name: False for name in SUBSTITUTION_FLAGS},
        "gates": {
            name: {"status": "open", "evidence": [], "requirement": requirement}
            for name, requirement in REQUIRED_GATES.items()
        },
        "claims": {
            "internet_audio_product_flow": False,
            "internet_clipboard_product_flow": False,
            "internet_file_transfer_product_flow": False,
        },
        "limitations": [
            "No public Internet DataChannel audio product-flow pass is claimed.",
            "No public Internet DataChannel clipboard product-flow pass is claimed.",
            "No public Internet DataChannel file-transfer product-flow pass is claimed.",
        ],
    }


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
    checks: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    failures: list[str] = []

    owner = _dict(manifest.get("owner"))
    source = _dict(manifest.get("source"))
    context = _dict(manifest.get("evidence_context"))
    substitutions = _dict(manifest.get("substitutions"))
    claims = _dict(manifest.get("claims"))

    checks["schema"] = _check(
        manifest.get("schema_version") == SCHEMA_VERSION
        and manifest.get("kind") == "phase3_advanced_datachannel_current_base_manifest",
        "manifest is phase3_advanced_datachannel_current_base_manifest v1",
    )
    checks["owner"] = _check(
        owner.get("role") == OWNER_ROLE and owner.get("repository") == REPOSITORY_FULL_NAME,
        "dedicated current-base owner is recorded",
        evidence=[str(owner.get("role")), str(owner.get("repository"))],
    )
    checks["clean_current_base"] = _check(
        isinstance(source.get("commit"), str)
        and HASH_RE.fullmatch(source["commit"]) is not None
        and source.get("tree_status") == "clean",
        "manifest records a clean 40-character current-base commit",
        evidence=[str(source.get("commit")), str(source.get("tree_status"))],
    )
    checks["actual_current_base"] = _check(
        isinstance(source.get("commit"), str)
        and current_commit is not None
        and source.get("commit", "").lower() == current_commit.lower()
        and tree_clean is True,
        "manifest source commit matches actual HEAD and actual worktree is clean",
        evidence=[str(source.get("commit")), str(current_commit), str(tree_clean)],
    )
    for key, expected in REQUIRED_CONTEXT_TRUE.items():
        checks[key] = _check(context.get(key) is True, expected, evidence=[str(context.get(key))])
    for key, expected in SUBSTITUTION_FLAGS.items():
        substituted = substitutions.get(key) is True
        checks[key] = _check(not substituted, expected, evidence=[str(substitutions.get(key))], blocking=False)
        if substituted:
            failures.append(f"fail: {key}")
    for key, expected in REQUIRED_GATES.items():
        checks[key] = _gate_check(manifest, key, expected, evidence_root=evidence_root)
    claim_mapping = {
        "claim_audio": "internet_audio_product_flow",
        "claim_clipboard": "internet_clipboard_product_flow",
        "claim_file_transfer": "internet_file_transfer_product_flow",
    }
    for check_name, claim_name in claim_mapping.items():
        checks[check_name] = _check(
            claims.get(claim_name) is True,
            f"{claim_name} is true only when retained evidence supports it",
            evidence=[str(claims.get(claim_name))],
        )

    for name, check in checks.items():
        if check["passed"] or name in SUBSTITUTION_FLAGS:
            continue
        reasons.append(f"blocked: {name}")

    verdict = FAIL if failures else (BLOCKED if reasons else PASS)
    all_reasons = failures + reasons
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": _utc_now(),
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "can_claim_internet_datachannel_product_flows": verdict == PASS,
        "owner": {
            "role": owner.get("role"),
            "head_ref": owner.get("head_ref"),
            "pull_request": owner.get("pull_request"),
            "repository": owner.get("repository"),
        },
        "source": source,
        "checks": checks,
        "reasons": all_reasons,
        "release_gate_effect": "child_gate_only" if verdict == PASS else "none",
        "interpretation": (
            "A pass requires retained real macOS plus Android public-Internet product evidence for "
            "audio playback, explicit clipboard transfer, and bounded file transfer over protected "
            "WebRTC DataChannels. This child gate never closes Phase 3 public Internet release by itself."
        ),
    }


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
            _write_json(
                args.manifest,
                default_manifest(source_commit=source_commit, tree_status=tree_status),
            )
        result = derive_gate(
            args.manifest,
            current_commit=current_commit,
            tree_clean=tree_clean,
            evidence_root=args.manifest.parent,
        )
        _write_json(args.output, result)
    except (AdvancedDataChannelInputError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 3
    for reason in result["reasons"]:
        print(reason, file=sys.stderr)
    return 0 if result["verdict"] == PASS else (2 if result["verdict"] == FAIL else 1)


if __name__ == "__main__":
    raise SystemExit(main())
