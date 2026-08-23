#!/usr/bin/env python3
"""Evaluate current-base Phase 3 real-media evidence packaging.

This gate consumes the narrower phase3_real_media_continuity result plus
retained Android visible-UI artifacts. It is intentionally passive: it does not
start the Host, touch ADB, change macOS TCC state, or infer evidence from local
synthetic WebRTC runs.

Exit codes are 0 for pass, 1 for blocked, 2 for runtime fail, and 3 for input
or invocation errors. Even a pass is only the current-base real-media child gate
and never closes the broader Phase 3 public Internet release gate by itself.
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
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION
from .phase3_real_media_continuity import (
    BLOCKED,
    FAIL,
    KIND as CONTINUITY_KIND,
    PASS,
)

KIND = "phase3_real_media_current_base_gate"
OWNER_ROLE = "phase3_real_media_current_base_owner"
OWNER_BRANCH = "codex/phase3-real-media-evidence-gate"
OWNER_PR = "#303"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
ACCEPTED_UI_EVIDENCE_KINDS = frozenset(
    ("device_screenshot", "device_screen_recording", "external_camera_recording")
)
UI_EVIDENCE_EXTENSIONS = {
    "device_screenshot": frozenset((".png", ".jpg", ".jpeg", ".webp")),
    "device_screen_recording": frozenset((".mp4", ".mov", ".webm")),
    "external_camera_recording": frozenset((".mp4", ".mov", ".webm")),
}
SENSITIVE_PATTERNS = (
    (re.compile(r"\b(?:https?|turns?|stuns?)://[^\s<>\"']+", re.IGNORECASE), "[redacted-url]"),
    (re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?![0-9.])"), "[redacted-ip]"),
    (re.compile(r"(?:/Users/[^\s<>\"']+|/home/[^\s<>\"']+|/Volumes/[^\s<>\"']+|[A-Za-z]:\\Users\\[^\s<>\"']+)", re.IGNORECASE), "[redacted-path]"),
    (re.compile(r"([\w.-]+)@([\w.-]+\.[A-Za-z]{2,})"), "[redacted-account]"),
    (re.compile(r"\b((?:hardware|device) serial\s*:\s*)(?!\[?redacted\]?\b)[^\r\n]+", re.IGNORECASE), r"\1[redacted]"),
)


class CurrentBaseInputError(ValueError):
    """Raised when the gate input cannot be read or trusted."""


def _run_git(repo: Path, args: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_revision(repo: Path) -> str:
    revision = _run_git(repo, ["rev-parse", "HEAD"])
    if not _is_git_revision(revision):
        raise CurrentBaseInputError("could not resolve repository HEAD")
    return str(revision).lower()


def _is_git_revision(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CurrentBaseInputError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentBaseInputError(f"could not read continuity result {path}: {error}") from error
    if not isinstance(document, dict):
        raise CurrentBaseInputError("continuity result must be a JSON object")
    return document


def _evidence_path(path: Path, repo: Path) -> str:
    resolved_repo = repo.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_repo).as_posix()
    except ValueError:
        return f"[external]/{path.name}"


def _sanitize_fragment(value: str) -> str:
    sanitized = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized[:240]


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bool(value: Any) -> bool:
    return value is True


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _device_identity_complete(value: Any) -> bool:
    device = _normalized_device_identity(value)
    return all(
        _string(device.get(field)) is not None
        for field in ("manufacturer", "model", "codename", "android_version")
    ) and isinstance(device.get("sdk"), int)


def _normalized_device_identity(value: Any) -> dict[str, Any]:
    device = _dict(value)
    sdk = device.get("sdk")
    if isinstance(sdk, str) and sdk.isdigit():
        sdk = int(sdk)
    return {
        "manufacturer": _string(device.get("manufacturer")),
        "model": _string(device.get("model")),
        "codename": (
            _string(device.get("codename"))
            or _string(device.get("device"))
            or _string(device.get("product"))
        ),
        "android_version": (
            _string(device.get("android_version"))
            or _string(device.get("android_release"))
        ),
        "sdk": sdk if isinstance(sdk, int) and not isinstance(sdk, bool) else None,
    }


def _check(passed: bool, expected: str, *, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": evidence or [],
    }


def _append_blocking_check(
    checks: dict[str, dict[str, Any]],
    reasons: list[str],
    key: str,
    passed: bool,
    expected: str,
    *,
    evidence: list[str] | None = None,
) -> None:
    checks[key] = _check(passed, expected, evidence=evidence)
    if not passed:
        reasons.append(f"blocked: {key}")


def _input_record(path: Path, repo: Path, category: str) -> dict[str, Any]:
    if path.is_file():
        return {
            "category": category,
            "path": _evidence_path(path, repo),
            "extension": path.suffix.lower(),
            "exists": True,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    return {
        "category": category,
        "path": _evidence_path(path, repo),
        "extension": path.suffix.lower(),
        "exists": False,
        "sha256": None,
        "bytes": None,
    }


def _ui_inputs(paths: Sequence[Path], repo: Path, artifact_kind: str) -> list[dict[str, Any]]:
    return [
        _input_record(path, repo, "android_visible_ui") | {"artifact_kind": artifact_kind}
        for path in paths
    ]


def _valid_ui_records(records: Sequence[dict[str, Any]], artifact_kind: str) -> list[dict[str, Any]]:
    allowed_extensions = UI_EVIDENCE_EXTENSIONS[artifact_kind]
    return [
        record
        for record in records
        if record["exists"]
        and isinstance(record["bytes"], int)
        and record["bytes"] > 0
        and record["extension"] in allowed_extensions
    ]


def _source_summary(continuity_path: Path, continuity: dict[str, Any], repo: Path) -> dict[str, Any]:
    repository = _dict(continuity.get("repository"))
    return {
        "continuity_result": _input_record(continuity_path, repo, "real_media_continuity"),
        "continuity_repository_revision": repository.get("revision"),
        "continuity_repository_branch": repository.get("branch"),
        "continuity_repository_dirty": repository.get("dirty"),
    }


def derive_gate(
    *,
    continuity_result: Path,
    repo: Path,
    android_ui_evidence: Sequence[Path] = (),
    android_ui_evidence_kind: str = "device_screenshot",
    android_ui_note: str | None = None,
    current_commit: str | None = None,
) -> dict[str, Any]:
    if android_ui_evidence_kind not in ACCEPTED_UI_EVIDENCE_KINDS:
        raise CurrentBaseInputError(
            "android_ui_evidence_kind must be one of "
            + ", ".join(sorted(ACCEPTED_UI_EVIDENCE_KINDS))
        )
    repo = repo.resolve()
    current = (current_commit or git_revision(repo)).lower()
    if not _is_git_revision(current):
        raise CurrentBaseInputError("current_commit must be a full Git revision")

    continuity = _load_json(continuity_result)
    conditions = _dict(continuity.get("conditions"))
    repository = _dict(continuity.get("repository"))
    summary = _dict(continuity.get("continuity_summary"))
    host = _dict(continuity.get("host_observation"))
    android = _dict(continuity.get("android_observation"))
    device = continuity.get("device")

    checks: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    failures: list[str] = []

    _append_blocking_check(
        checks,
        blocked,
        "continuity_schema",
        continuity.get("schema_version") == SCHEMA_VERSION
        and continuity.get("kind") == CONTINUITY_KIND,
        "input is a phase3_real_media_continuity_preflight v1 result",
        evidence=[str(continuity.get("kind"))],
    )
    continuity_verdict = continuity.get("verdict")
    checks["continuity_passed"] = _check(
        continuity_verdict == PASS,
        "narrow continuity preflight verdict is pass",
        evidence=[str(continuity_verdict)],
    )
    if continuity_verdict == BLOCKED:
        blocked.append("blocked: continuity_passed")
    elif continuity_verdict == FAIL:
        failures.append("fail: continuity_preflight_failed")
    elif continuity_verdict != PASS:
        blocked.append("blocked: continuity_passed")

    continuity_revision = repository.get("revision")
    _append_blocking_check(
        checks,
        blocked,
        "current_base_commit",
        isinstance(continuity_revision, str) and continuity_revision.lower() == current,
        "continuity evidence repository revision matches current HEAD",
        evidence=[str(continuity_revision), current],
    )
    _append_blocking_check(
        checks,
        blocked,
        "continuity_source_clean",
        repository.get("dirty") is False,
        "continuity evidence was captured from a clean source tree",
        evidence=[str(repository.get("dirty"))],
    )
    _append_blocking_check(
        checks,
        blocked,
        "android_device_identity",
        _device_identity_complete(device),
        "real Android device identity records manufacturer, model, codename, Android version, and SDK",
    )
    _append_blocking_check(
        checks,
        blocked,
        "public_internet_path",
        conditions.get("network_path") == "public_internet"
        and _bool(summary.get("public_internet_path")),
        "real public Internet route evidence is present",
        evidence=[str(conditions.get("network_path"))],
    )
    _append_blocking_check(
        checks,
        blocked,
        "identity_signed_host",
        conditions.get("host_signing") == "identity_signed",
        "Host binary is identity-signed for the run",
        evidence=[str(conditions.get("host_signing"))],
    )
    _append_blocking_check(
        checks,
        blocked,
        "screen_recording_granted",
        conditions.get("screen_recording") == "granted"
        and not _bool(host.get("screen_recording_blocked")),
        "macOS Screen Recording permission was granted during capture",
        evidence=[str(conditions.get("screen_recording"))],
    )
    _append_blocking_check(
        checks,
        blocked,
        "real_capture_first_frame",
        summary.get("media_source") == "real_screencapturekit_or_cgdisplaystream"
        and int(summary.get("capture_frame_count") or 0) > 0,
        "ScreenCaptureKit/CGDisplayStream first frame is observed",
    )
    _append_blocking_check(
        checks,
        blocked,
        "videotoolbox_output",
        int(summary.get("videotoolbox_output_frames") or 0) > 0,
        "VideoToolbox encoded output is observed",
    )
    _append_blocking_check(
        checks,
        blocked,
        "webrtc_media_channel",
        _string(summary.get("selected_webrtc_route")) is not None,
        "Phase 3 WebRTC media path is active",
        evidence=[str(summary.get("selected_webrtc_route"))],
    )
    _append_blocking_check(
        checks,
        blocked,
        "protocol_v1_epoch",
        bool(summary.get("protocol_v1_media_epochs"))
        or summary.get("protocol_v1_session_epoch") is not None,
        "Protocol v1 media or session epoch is observed",
    )
    _append_blocking_check(
        checks,
        blocked,
        "android_mediacodec_decode",
        _bool(summary.get("mediacodec_first_input_frame"))
        and _bool(summary.get("mediacodec_first_output_frame"))
        and int(summary.get("continuous_output_frames") or 0)
        >= int(conditions.get("minimum_output_frames") or 1),
        "Android MediaCodec first input/output and continuous output count are observed",
        evidence=[str(summary.get("continuous_output_frames"))],
    )
    synthetic_markers = list(host.get("synthetic_markers") or []) + list(
        android.get("synthetic_markers") or []
    )
    _append_blocking_check(
        checks,
        blocked,
        "no_synthetic_media",
        not synthetic_markers,
        "synthetic media markers are absent",
        evidence=[str(item) for item in synthetic_markers],
    )

    ui_records = _ui_inputs(android_ui_evidence, repo, android_ui_evidence_kind)
    normalized_ui_note = _string(android_ui_note)
    ui_note = _sanitize_fragment(normalized_ui_note) if normalized_ui_note else None
    valid_ui_records = _valid_ui_records(ui_records, android_ui_evidence_kind)
    _append_blocking_check(
        checks,
        blocked,
        "visible_android_ui",
        bool(valid_ui_records) and bool(ui_note),
        "retained Android screenshot/video evidence and operator visible-UI note are present",
        evidence=[record["path"] for record in valid_ui_records],
    )

    decoder_errors = int(summary.get("decoder_error_count") or 0)
    dropped_frames = int(summary.get("dropped_frames") or 0)
    maximum_dropped = int(conditions.get("maximum_dropped_frames") or 0)
    checks["no_decoder_errors"] = _check(
        decoder_errors == 0,
        "Android decoder error count is zero",
        evidence=[str(decoder_errors)],
    )
    checks["bounded_drops"] = _check(
        dropped_frames <= maximum_dropped,
        "Android dropped-frame count stays within the configured threshold",
        evidence=[str(dropped_frames), str(maximum_dropped)],
    )
    if decoder_errors != 0:
        failures.append("fail: no_decoder_errors")
    if dropped_frames > maximum_dropped:
        failures.append("fail: bounded_drops")

    verdict = PASS
    if blocked:
        verdict = BLOCKED
    elif failures:
        verdict = FAIL

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "can_claim_current_base_real_media_continuity": verdict == PASS,
        "owner": {
            "role": OWNER_ROLE,
            "pull_request": OWNER_PR,
            "head_ref": OWNER_BRANCH,
            "repository": REPOSITORY_FULL_NAME,
            "scope": "current-base ScreenCaptureKit/CGDisplayStream -> VideoToolbox -> Phase 3 WebRTC -> Android MediaCodec plus visible UI evidence",
        },
        "current_base": {
            "repository_commit": current,
            "continuity_repository_revision": continuity_revision,
            "continuity_repository_dirty": repository.get("dirty"),
        },
        "device": _normalized_device_identity(device) if isinstance(device, dict) else None,
        "source": _source_summary(continuity_result, continuity, repo),
        "android_visible_ui": {
            "artifact_kind": android_ui_evidence_kind,
            "operator_note": ui_note,
            "artifacts": ui_records,
        },
        "checks": checks,
        "continuity_summary": {
            "media_source": summary.get("media_source"),
            "public_internet_path": summary.get("public_internet_path"),
            "selected_webrtc_route": summary.get("selected_webrtc_route"),
            "continuous_output_frames": summary.get("continuous_output_frames"),
            "dropped_frames": dropped_frames,
            "decoder_error_count": decoder_errors,
        },
        "reasons": blocked if blocked else failures,
        "release_gate_effect": "child_gate_only" if verdict == PASS else "none",
        "interpretation": (
            "A pass means retained current-base evidence proves the narrow real-media path "
            "from macOS ScreenCaptureKit/CGDisplayStream through VideoToolbox and Phase 3 "
            "WebRTC into Android MediaCodec with visible Android UI evidence. It does not "
            "close public Internet release gates such as remote TURN, handoff, revocation, "
            "latency, or soak."
        ),
    }


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate current-base Phase 3 real-media evidence packaging."
    )
    parser.add_argument("--continuity-result", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--android-ui-evidence", action="append", type=Path, default=[])
    parser.add_argument(
        "--android-ui-evidence-kind",
        choices=sorted(ACCEPTED_UI_EVIDENCE_KINDS),
        default="device_screenshot",
    )
    parser.add_argument("--android-ui-note")
    parser.add_argument("--current-commit")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.current_commit is not None:
            requested_commit = args.current_commit.lower()
            resolved_commit = git_revision(args.repo.resolve())
            if requested_commit != resolved_commit:
                raise CurrentBaseInputError(
                    "--current-commit does not match the checked-out repository HEAD"
                )
            current_commit = requested_commit
        else:
            current_commit = None
        result = derive_gate(
            continuity_result=args.continuity_result,
            repo=args.repo,
            android_ui_evidence=args.android_ui_evidence,
            android_ui_evidence_kind=args.android_ui_evidence_kind,
            android_ui_note=args.android_ui_note,
            current_commit=current_commit,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (CurrentBaseInputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 3

    if result["verdict"] == PASS:
        return 0
    for reason in result["reasons"]:
        print(f"{result['verdict']}: {reason}", file=sys.stderr)
    return 2 if result["verdict"] == FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
