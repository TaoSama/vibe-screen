#!/usr/bin/env python3
"""Evaluate Phase 3 adaptive-media current-base evidence.

This is a narrow child gate for real network fluctuation adaptation. It consumes
retained evidence only; it does not start the Host, touch ADB, change network
state, or infer behavior from local loopback, deterministic fixtures, static
latency summaries, or synthetic media.

Exit codes are 0 for pass, 1 for blocked, 2 for runtime fail, and 3 for input
or invocation errors. Even a pass never closes the broader Phase 3 public
Internet release gate.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


KIND = "phase3_adaptive_media_current_base_gate"
REPORT_SCHEMA = "dev.vibescreen.phase3-adaptive-media-fluctuation/v1"
REPORT_KIND = "phase3_adaptive_media_fluctuation_report"
OWNER_ROLE = "phase3_adaptive_media_current_base_owner"
OWNER_BRANCH = "codex/phase3-adaptive-media-current-base"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
MAX_DOWNGRADE_OBSERVATIONS = 2
MIN_UPGRADE_OBSERVATIONS = 4
BANNED_IMPAIRMENT_MARKERS = (
    "fixture",
    "loopback",
    "network_profile.py",
    "deterministic",
    "simulation",
    "synthetic",
    "static latency",
)
SENSITIVE_PATTERNS = (
    (
        re.compile(r"\b(?:https?|turns?|stuns?)://[^\s<>\"']+", re.IGNORECASE),
        "[redacted-url]",
    ),
    (
        re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?![0-9.])"),
        "[redacted-ip]",
    ),
    (
        re.compile(
            r"(?:/Users/[^\s<>\"']+|/home/[^\s<>\"']+|/Volumes/[^\s<>\"']+|[A-Za-z]:\\Users\\[^\s<>\"']+)",
            re.IGNORECASE,
        ),
        "[redacted-path]",
    ),
    (re.compile(r"([\w.-]+)@([\w.-]+\.[A-Za-z]{2,})"), "[redacted-account]"),
)


class AdaptiveMediaInputError(ValueError):
    """Raised when the input report cannot be read or trusted."""


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
        raise AdaptiveMediaInputError("could not resolve repository HEAD")
    return str(revision).lower()


def _is_git_revision(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdaptiveMediaInputError(f"could not read adaptive-media report {path}: {error}") from error
    if not isinstance(document, dict):
        raise AdaptiveMediaInputError("adaptive-media report must be a JSON object")
    return document


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer() and math.isfinite(value):
        return int(value)
    return None


def _sanitize(value: Any) -> str:
    text = str(value)
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:240]


def _normalize_device_identity(value: Any) -> dict[str, Any]:
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
            or _string(device.get("os_version"))
        ),
        "sdk": sdk if isinstance(sdk, int) and not isinstance(sdk, bool) else None,
    }


def _device_identity_complete(value: Any) -> bool:
    device = _normalize_device_identity(value)
    return all(
        _string(device.get(field)) is not None
        for field in ("manufacturer", "model", "codename", "android_version")
    ) and isinstance(device.get("sdk"), int)


def _evidence_path(path: Path, repo: Path) -> str:
    resolved_repo = repo.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_repo).as_posix()
    except ValueError:
        return f"[external]/{path.name}"


def _check(passed: bool, expected: str, *, evidence: Sequence[Any] = ()) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": [_sanitize(item) for item in evidence if item is not None],
    }


def _record_blocking_check(
    checks: dict[str, dict[str, Any]],
    reasons: list[str],
    key: str,
    passed: bool,
    expected: str,
    *,
    evidence: Sequence[Any] = (),
) -> None:
    checks[key] = _check(passed, expected, evidence=evidence)
    if not passed:
        reasons.append(f"blocked: {key}")


def _event_number(event: dict[str, Any], key: str) -> float | None:
    return _finite_number(event.get(key))


def _event_epoch(event: dict[str, Any]) -> int | None:
    return _integer(event.get("config_epoch"))


def _event_direction(event: dict[str, Any]) -> str | None:
    value = _string(event.get("direction"))
    return value.lower() if value is not None else None


def _events(adaptive: dict[str, Any]) -> list[dict[str, Any]]:
    raw = adaptive.get("profile_events")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _strictly_increasing(values: Sequence[int]) -> bool:
    return len(values) >= 2 and all(left < right for left, right in zip(values, values[1:]))


def _profile_change_summary(adaptive: dict[str, Any]) -> tuple[bool, list[str]]:
    events = _events(adaptive)
    if len(events) < 3:
        return False, ["profile_events must include baseline, downgrade, and recovery records"]

    downgrade_index = next(
        (index for index, event in enumerate(events) if _event_direction(event) == "downgrade"),
        None,
    )
    upgrade_index = next(
        (
            index
            for index, event in enumerate(events)
            if index > (downgrade_index or -1) and _event_direction(event) == "upgrade"
        ),
        None,
    )
    if downgrade_index is None or downgrade_index == 0 or upgrade_index is None:
        return False, ["profile_events must show a downgrade followed by a later upgrade"]

    baseline = events[downgrade_index - 1]
    downgrade = events[downgrade_index]
    upgrade = events[upgrade_index]
    baseline_bitrate = _event_number(baseline, "bitrate_bps")
    baseline_fps = _event_number(baseline, "fps")
    downgrade_bitrate = _event_number(downgrade, "bitrate_bps")
    downgrade_fps = _event_number(downgrade, "fps")
    upgrade_bitrate = _event_number(upgrade, "bitrate_bps")
    upgrade_fps = _event_number(upgrade, "fps")
    reasons: list[str] = []
    if None in (baseline_bitrate, baseline_fps, downgrade_bitrate, downgrade_fps, upgrade_bitrate, upgrade_fps):
        reasons.append("profile_events must include numeric bitrate_bps and fps")
    else:
        if not (downgrade_bitrate < baseline_bitrate and downgrade_fps < baseline_fps):
            reasons.append("downgrade must reduce both bitrate_bps and fps")
        if not (downgrade_bitrate < upgrade_bitrate <= baseline_bitrate):
            reasons.append("upgrade bitrate must recover without exceeding the user baseline")
        if not (downgrade_fps < upgrade_fps <= baseline_fps):
            reasons.append("upgrade fps must recover without exceeding the user baseline")
    if any(event.get("acked") is not True for event in events[downgrade_index:upgrade_index + 1]):
        reasons.append("downgrade and upgrade config events must be acknowledged")
    return not reasons, reasons


def _config_epoch_summary(adaptive: dict[str, Any]) -> tuple[bool, list[int]]:
    configured = adaptive.get("config_epochs")
    if isinstance(configured, list):
        epochs = [_integer(item) for item in configured]
    else:
        epochs = [_event_epoch(event) for event in _events(adaptive)]
    numeric_epochs = [epoch for epoch in epochs if epoch is not None]
    return len(numeric_epochs) == len(epochs) and _strictly_increasing(numeric_epochs), numeric_epochs


def _impairment_tool_allowed(value: Any) -> bool:
    tool = _string(value)
    if tool is None:
        return False
    lowered = tool.lower()
    return not any(marker in lowered for marker in BANNED_IMPAIRMENT_MARKERS)


def _raw_sources(report: dict[str, Any]) -> list[str]:
    value = report.get("raw_sources")
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _raw_sources_complete(sources: Sequence[str]) -> bool:
    lowered = [source.lower() for source in sources]
    has_host = any("host" in source for source in lowered)
    has_android = any("android" in source or "logcat" in source for source in lowered)
    has_webrtc_stats = any("webrtc" in source and "stat" in source for source in lowered)
    has_fixture = any("fixture" in source for source in lowered)
    return has_host and has_android and has_webrtc_stats and not has_fixture


def _source_summary(report_path: Path, report: dict[str, Any], repo: Path) -> dict[str, Any]:
    repository = _dict(report.get("repository"))
    return {
        "report": {
            "path": _evidence_path(report_path, repo),
            "exists": report_path.is_file(),
        },
        "report_repository_revision": repository.get("revision"),
        "report_repository_branch": repository.get("branch"),
        "report_repository_dirty": repository.get("dirty"),
        "raw_sources": [_sanitize(item) for item in _raw_sources(report)],
    }


def _device_identity_allowed(device: dict[str, Any]) -> bool:
    manufacturer = (device.get("manufacturer") or "").lower()
    if device.get("model") == "P0110" and device.get("codename") != "pacific":
        return False
    if manufacturer == "xiaomi" and device.get("codename") != "fuxi":
        return False
    return True


def derive_gate(
    *,
    report_path: Path,
    repo: Path,
    current_commit: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    current = (current_commit or git_revision(repo)).lower()
    if not _is_git_revision(current):
        raise AdaptiveMediaInputError("current_commit must be a full Git revision")

    report = _load_json(report_path)
    repository = _dict(report.get("repository"))
    run_context = _dict(report.get("run_context"))
    adaptive = _dict(report.get("adaptive_media"))
    transport = _dict(report.get("transport_continuity"))
    device = report.get("device")

    checks: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    failures: list[str] = []

    schema_ok = report.get("schema") == REPORT_SCHEMA or (
        report.get("schema_version") == SCHEMA_VERSION and report.get("kind") == REPORT_KIND
    )
    _record_blocking_check(
        checks,
        blocked,
        "report_schema",
        schema_ok,
        "input uses dev.vibescreen.phase3-adaptive-media-fluctuation/v1 or equivalent kind",
        evidence=[report.get("schema"), report.get("kind")],
    )

    report_verdict = report.get("verdict") or report.get("status")
    checks["report_passed"] = _check(report_verdict == PASS, "input run verdict is pass", evidence=[report_verdict])
    if report_verdict == FAIL:
        failures.append("fail: report_passed")
    elif report_verdict != PASS:
        blocked.append("blocked: report_passed")

    revision = repository.get("revision")
    _record_blocking_check(
        checks,
        blocked,
        "current_base_commit",
        isinstance(revision, str) and revision.lower() == current,
        "adaptive-media evidence repository revision matches current HEAD",
        evidence=[revision, current],
    )
    _record_blocking_check(
        checks,
        blocked,
        "clean_source",
        repository.get("dirty") is False,
        "adaptive-media evidence was captured from a clean source tree",
        evidence=[repository.get("dirty")],
    )

    normalized_device = _normalize_device_identity(device)
    device_ok = _device_identity_complete(device) and _device_identity_allowed(normalized_device)
    _record_blocking_check(
        checks,
        blocked,
        "android_device_identity",
        device_ok,
        "device identity is exact and does not relabel Nubia P0110/pacific as Xiaomi/fuxi",
        evidence=[normalized_device],
    )

    _record_blocking_check(
        checks,
        blocked,
        "public_internet_scope",
        run_context.get("network_scope") == "public_internet"
        and run_context.get("public_internet_path") is True
        and run_context.get("local_loopback_only") is False,
        "run used a real public Internet path, not local loopback",
        evidence=[run_context.get("network_scope"), run_context.get("local_loopback_only")],
    )
    _record_blocking_check(
        checks,
        blocked,
        "controlled_real_impairment",
        run_context.get("controlled_impairment") is True
        and run_context.get("real_network_impairment") is True,
        "network fluctuation came from controlled real impairment, not a policy fixture",
        evidence=[run_context.get("controlled_impairment"), run_context.get("real_network_impairment")],
    )
    _record_blocking_check(
        checks,
        blocked,
        "impairment_tool",
        _impairment_tool_allowed(run_context.get("impairment_tool")),
        "impairment tool is named and is not deterministic fixture, loopback, or static latency tooling",
        evidence=[run_context.get("impairment_tool")],
    )
    no_fixture = (
        run_context.get("static_latency_fixture") is False
        and run_context.get("synthetic_media") is False
        and report.get("static_latency_fixture") is not True
    )
    _record_blocking_check(
        checks,
        blocked,
        "no_static_fixture_or_synthetic_media",
        no_fixture,
        "static latency fixtures and synthetic media are absent",
        evidence=[run_context.get("static_latency_fixture"), run_context.get("synthetic_media")],
    )
    _record_blocking_check(
        checks,
        blocked,
        "real_webrtc_statistics",
        run_context.get("real_webrtc_statistics") is True,
        "adaptive policy decisions are backed by retained real WebRTC transport statistics",
        evidence=[run_context.get("real_webrtc_statistics")],
    )
    raw_sources = _raw_sources(report)
    _record_blocking_check(
        checks,
        blocked,
        "raw_sources_retained",
        _raw_sources_complete(raw_sources),
        "raw Host, Android/logcat, and WebRTC statistics sources are listed and are not fixture-only files",
        evidence=raw_sources,
    )

    fast_drop = _dict(adaptive.get("fast_drop"))
    downgrade_within = _finite_number(fast_drop.get("downgrade_within_observations"))
    fast_drop_ok = (
        fast_drop.get("observed") is True
        and downgrade_within is not None
        and downgrade_within <= MAX_DOWNGRADE_OBSERVATIONS
    )
    _record_blocking_check(
        checks,
        blocked,
        "fast_drop",
        fast_drop_ok,
        f"weak network samples trigger downgrade within {MAX_DOWNGRADE_OBSERVATIONS} observations",
        evidence=[downgrade_within],
    )

    slow_rise = _dict(adaptive.get("slow_rise"))
    upgrade_after = _finite_number(slow_rise.get("upgrade_after_observations"))
    slow_rise_ok = (
        slow_rise.get("observed") is True
        and upgrade_after is not None
        and downgrade_within is not None
        and upgrade_after >= MIN_UPGRADE_OBSERVATIONS
        and upgrade_after > downgrade_within
    )
    _record_blocking_check(
        checks,
        blocked,
        "slow_rise",
        slow_rise_ok,
        f"recovery upgrade waits at least {MIN_UPGRADE_OBSERVATIONS} observations and longer than downgrade",
        evidence=[upgrade_after],
    )

    profile_ok, profile_reasons = _profile_change_summary(adaptive)
    _record_blocking_check(
        checks,
        blocked,
        "bitrate_fps_profile_changes",
        profile_ok,
        "downgrade lowers bitrate/FPS and recovery does not exceed the user baseline",
        evidence=profile_reasons,
    )
    config_ok, epochs = _config_epoch_summary(adaptive)
    _record_blocking_check(
        checks,
        blocked,
        "config_epoch_progression",
        config_ok,
        "video config epochs are present and strictly increasing across adaptation events",
        evidence=epochs,
    )
    _record_blocking_check(
        checks,
        blocked,
        "config_ack_keyframe_resume",
        adaptive.get("video_config_acknowledged") is True
        and adaptive.get("keyframe_after_config_ack") is True,
        "each applied VideoConfig is acknowledged before keyframe/resume evidence",
        evidence=[adaptive.get("video_config_acknowledged"), adaptive.get("keyframe_after_config_ack")],
    )
    _record_blocking_check(
        checks,
        blocked,
        "policy_safety_boundaries",
        adaptive.get("latest_proposal_wins") is True
        and adaptive.get("stale_owner_or_generation_rejected") is True
        and adaptive.get("rollback_fail_closed") is True,
        "latest-proposal wins, stale generation rejection, and rollback fail-closed behavior are retained",
        evidence=[
            adaptive.get("latest_proposal_wins"),
            adaptive.get("stale_owner_or_generation_rejected"),
            adaptive.get("rollback_fail_closed"),
        ],
    )
    if adaptive.get("oscillation_detected") is True:
        checks["no_unsafe_oscillation"] = _check(False, "adaptive policy does not oscillate under jitter", evidence=[True])
        failures.append("fail: no_unsafe_oscillation")
    else:
        checks["no_unsafe_oscillation"] = _check(True, "adaptive policy does not oscillate under jitter", evidence=[adaptive.get("oscillation_detected")])

    transport_restart_count = _integer(transport.get("transport_restart_count"))
    transport_ok = (
        transport.get("selected_transport") == "webrtc"
        and transport.get("no_transport_restart") is True
        and transport.get("session_epoch_unchanged") is True
        and transport.get("media_channel_continuous") is True
        and transport_restart_count == 0
    )
    checks["transport_continuity"] = _check(
        transport_ok,
        "WebRTC transport, session epoch, and media channel stay continuous while config epoch changes",
        evidence=[
            transport.get("selected_transport"),
            transport.get("no_transport_restart"),
            transport.get("session_epoch_unchanged"),
            transport.get("media_channel_continuous"),
            transport_restart_count,
        ],
    )
    if transport_restart_count is not None and transport_restart_count > 0:
        failures.append("fail: transport_continuity")
    elif not transport_ok:
        blocked.append("blocked: transport_continuity")

    verdict = PASS
    if failures:
        verdict = FAIL
    elif blocked:
        verdict = BLOCKED

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "can_claim_current_base_adaptive_media_fluctuation": verdict == PASS,
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "repository": REPOSITORY_FULL_NAME,
            "scope": "current-base Phase 3 adaptive media behavior under real WebRTC Internet network fluctuation",
        },
        "current_base": {
            "repository_commit": current,
            "report_repository_revision": revision,
            "report_repository_dirty": repository.get("dirty"),
        },
        "device": normalized_device if isinstance(device, dict) else None,
        "source": _source_summary(report_path, report, repo),
        "checks": checks,
        "adaptive_media_summary": {
            "downgrade_within_observations": downgrade_within,
            "upgrade_after_observations": upgrade_after,
            "config_epochs": epochs,
            "profile_event_count": len(_events(adaptive)),
        },
        "transport_summary": {
            "selected_transport": transport.get("selected_transport"),
            "selected_candidate_pair": (
                _sanitize(transport.get("selected_candidate_pair"))
                if transport.get("selected_candidate_pair") is not None
                else None
            ),
            "transport_restart_count": transport_restart_count,
            "session_epoch_unchanged": transport.get("session_epoch_unchanged"),
            "media_channel_continuous": transport.get("media_channel_continuous"),
        },
        "reasons": failures if failures else blocked,
        "release_gate_effect": "child_gate_only" if verdict == PASS else "none",
        "interpretation": (
            "A pass means retained current-base evidence proves fast-drop/slow-rise adaptive "
            "media behavior, bitrate/FPS/config-epoch changes, and transport continuity under "
            "real WebRTC public-Internet network fluctuation. It is a child gate only: it does "
            "not close Phase 3 public Internet release, latency, soak, revocation, or handoff gates."
        ),
    }


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Phase 3 adaptive-media current-base evidence.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
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
                raise AdaptiveMediaInputError("--current-commit does not match the checked-out repository HEAD")
            current_commit = requested_commit
        else:
            current_commit = None
        result = derive_gate(report_path=args.report, repo=args.repo, current_commit=current_commit)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (AdaptiveMediaInputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 3

    if result["verdict"] == PASS:
        return 0
    for reason in result["reasons"]:
        print(f"{result['verdict']}: {reason}", file=sys.stderr)
    return 2 if result["verdict"] == FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
