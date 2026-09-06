"""Evaluate the aggregate Phase 0 stable-release closure manifest.

This checker owns only the aggregate release decision. It does not reinterpret
readiness, synthetic, historical, or blocked sub-gate evidence as a pass.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import math
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

KIND = "phase0_stable_release_closure"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_FAIL = "fail"
STATUS_INSUFFICIENT = "insufficient"
STATUS_OPEN = "open"
EXPECTED_OPEN_PR_REPOSITORY = "TaoSama/vibe-screen"
TELEMETRY_AND_LATENCY_ARCHIVE_GATE_ID = "telemetry_and_latency_archive"
LATENCY_EVIDENCE_GATE_KIND = "latency_evidence_gate"
ANDROID_USB_LIVE_SMOKE_KIND = "android_usb_live_smoke"
LATENCY_ARCHIVE_MEASUREMENT_METHODS = {"external-camera", "synchronized-clock"}
ALLOWED_VERDICTS = {
    STATUS_PASS,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_INSUFFICIENT,
    STATUS_OPEN,
}
CLOSING_EVIDENCE_STRENGTHS = {
    "current-ci",
    "current-real-device",
    "current-source",
    "real-device",
}
REQUIRED_GATE_CLOSING_EVIDENCE_STRENGTHS = {
    "upstream_provenance_and_license": {"current-source"},
    "protocol_contract_ci": {"current-ci"},
    "android_clean_build": {"current-ci"},
    "macos_release_build_xcode_tests": {"current-ci"},
    "macos_host_hardware_compatibility_matrix": {"current-real-device"},
    "android_device_usb_stream_reconnect_codec": {
        "current-real-device",
        "real-device",
    },
    "telemetry_and_latency_archive": {"current-real-device"},
    "host_rss_2h_no_growth": {"current-real-device"},
    "native_pointer_hid_mouse": {"current-real-device"},
    "controller_runtime_acceptance": {"current-real-device"},
    "clipboard_android_macos_product_e2e": {"current-real-device"},
    "file_transfer_android_product_e2e": {"current-real-device"},
    "module_ownership_extraction": {"current-ci", "current-source"},
}
DEFAULT_README_GUARD_PHRASES = (
    "Phase 0 remains in progress",
    "rather than a stable release",
    "Do not treat roadmap items below as shipped features",
)
DEFAULT_FORBIDDEN_README_PATTERNS = (
    r"\bPhase\s*0\s+(?:is(?:\s+now)?|now|has(?:\s+been|\s+reached)?|was|marked|declared|treated as|reached)\s+(?:complete|closed|shipped|released|stable|done|production[- ]ready|generally available|GA)\b",
    r"\bPhase\s*0\s+(?:stable[- ]release|release)\s+(?:is|now|has been|was)\s+(?:available|ready|complete|shipped|released|stable|done|production[- ]ready|generally available|GA)\b",
    r"\bPhase\s*0\s+(?:GA|generally available|production[- ]ready)\b",
)

REQUIRED_GATE_IDS = (
    "upstream_provenance_and_license",
    "protocol_contract_ci",
    "android_clean_build",
    "macos_release_build_xcode_tests",
    "macos_host_hardware_compatibility_matrix",
    "android_device_usb_stream_reconnect_codec",
    "telemetry_and_latency_archive",
    "host_rss_2h_no_growth",
    "native_pointer_hid_mouse",
    "controller_runtime_acceptance",
    "clipboard_android_macos_product_e2e",
    "file_transfer_android_product_e2e",
    "module_ownership_extraction",
)
HASH_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
AGGREGATE_REFRESH_PATHS = (
    "README.md",
    "tools/README.md",
    "docs/changes/2026-08-22-phase0-stable-release-aggregate/",
)
RELEASE_CLAIM_GUARD_PATHS = (
    "Makefile",
    "tools/vibescreen_evidence/phase0_stable_release.py",
    "tools/schemas/phase0-stable-release.schema.json",
    "tools/schemas/phase0-stable-release-manifest.schema.json",
)


class Phase0StableReleaseError(ValueError):
    """Raised when the aggregate manifest cannot be evaluated."""


def load_json(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise Phase0StableReleaseError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise Phase0StableReleaseError("manifest must be a JSON object")
    return record


def _string(record: dict[str, Any], field: str, *, required: bool = True) -> str:
    value = record.get(field)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise Phase0StableReleaseError(f"{field} must be a non-empty string")
    return value


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Phase0StableReleaseError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise Phase0StableReleaseError(f"{field} must contain only non-empty strings")
    return value


def _owner_prs(gate: dict[str, Any]) -> list[int]:
    value = gate.get("owner_prs", [])
    if not isinstance(value, list) or not all(type(item) is int for item in value):
        raise Phase0StableReleaseError("owner_prs must be a list of integers")
    return value


def _int_list(record: dict[str, Any], field: str) -> list[int]:
    value = record.get(field, [])
    if not isinstance(value, list) or not all(type(item) is int for item in value):
        raise Phase0StableReleaseError(f"{field} must be a list of integers")
    if len(value) != len(set(value)):
        raise Phase0StableReleaseError(f"{field} must not contain duplicates")
    return value


def _required_bool(gate: dict[str, Any]) -> bool:
    value = gate.get("required_for_stable_release", True)
    if not isinstance(value, bool):
        raise Phase0StableReleaseError(
            "required_for_stable_release must be true or false"
        )
    return value


def _guard_string_list(
    guard: dict[str, Any], field: str, defaults: Sequence[str]
) -> tuple[str, ...]:
    value = guard.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Phase0StableReleaseError(f"readme_guard.{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise Phase0StableReleaseError(
            f"readme_guard.{field} must contain only non-empty strings"
        )

    combined: list[str] = []
    for item in [*defaults, *value]:
        if item not in combined:
            combined.append(item)
    return tuple(combined)


def _compile_guard_pattern(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise Phase0StableReleaseError(
            f"readme_guard.forbidden_regexes contains invalid regex {pattern!r}: {error}"
        ) from error


def _gate_summary(
    gate: dict[str, Any], *, repo_root: Path | None = None
) -> dict[str, Any]:
    gate_id = _string(gate, "id")
    title = _string(gate, "title")
    verdict = _string(gate, "verdict")
    if verdict not in ALLOWED_VERDICTS:
        raise Phase0StableReleaseError(
            f"gate {gate_id}: unsupported verdict {verdict!r}"
        )
    evidence_strength = (
        _string(gate, "evidence_strength", required=False) or "unknown"
    )
    evidence_paths = _string_list(gate, "evidence_paths")
    blockers = _string_list(gate, "blockers")
    required = _required_bool(gate)

    issues: list[str] = []
    if verdict == STATUS_PASS:
        if not evidence_paths:
            issues.append("pass gate must cite at least one evidence path or URL")
        if blockers:
            issues.append("pass gate must not list unresolved blockers")
        closing_evidence_strengths = REQUIRED_GATE_CLOSING_EVIDENCE_STRENGTHS.get(
            gate_id, CLOSING_EVIDENCE_STRENGTHS
        )
        if evidence_strength not in closing_evidence_strengths:
            issues.append(
                "pass gate must use a closing evidence strength for this gate, "
                f"got {evidence_strength!r}"
            )
        if gate_id == TELEMETRY_AND_LATENCY_ARCHIVE_GATE_ID:
            issues.extend(
                _telemetry_and_latency_archive_issues(
                    evidence_paths=evidence_paths, repo_root=repo_root
                )
            )
    elif required and not blockers:
        issues.append("non-pass required gate must list at least one blocker")
    can_close = required and verdict == STATUS_PASS and not issues
    return {
        "id": gate_id,
        "title": title,
        "required_for_stable_release": required,
        "verdict": verdict,
        "evidence_strength": evidence_strength,
        "can_close": can_close,
        "owner_prs": _owner_prs(gate),
        "evidence_paths": evidence_paths,
        "blockers": blockers,
        "issues": issues,
    }


def _telemetry_and_latency_archive_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "telemetry_and_latency_archive pass requires repo_root to verify "
            "structured evidence paths"
        ]

    valid_latency_report = False
    valid_android_stream_report = False
    issues: list[str] = []
    latency_candidate_issues: list[str] = []
    android_candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(repository, raw_path)
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"telemetry_and_latency_archive evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(evidence_path, raw_path)
        if load_issue is not None:
            issues.append(load_issue)
            continue
        kind = record.get("kind")
        if kind == LATENCY_EVIDENCE_GATE_KIND:
            report_issues = _formal_latency_report_issues(record, raw_path)
            if report_issues:
                latency_candidate_issues.extend(report_issues)
            else:
                valid_latency_report = True
        elif kind == ANDROID_USB_LIVE_SMOKE_KIND:
            report_issues = _android_usb_live_smoke_report_issues(record, raw_path)
            if report_issues:
                android_candidate_issues.extend(report_issues)
            else:
                valid_android_stream_report = True

    if not valid_latency_report:
        issues.append(
            "telemetry_and_latency_archive pass requires at least one passing "
            "formal latency_evidence_gate report in evidence_paths"
        )
        issues.extend(latency_candidate_issues)
    if not valid_android_stream_report:
        issues.append(
            "telemetry_and_latency_archive pass requires at least one passing "
            "android_usb_live_smoke report with stream telemetry and decoder "
            "counters in evidence_paths"
        )
        issues.extend(android_candidate_issues)
    return issues


def _repo_relative_evidence_path(
    repo_root: Path, raw_path: str
) -> tuple[Path | None, str | None]:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_path):
        return None, None
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        return (
            None,
            f"telemetry_and_latency_archive evidence path {raw_path!r} must be "
            "repo-relative",
        )
    candidate = repo_root / path
    try:
        candidate.resolve().relative_to(repo_root)
    except ValueError:
        return (
            None,
            f"telemetry_and_latency_archive evidence path {raw_path!r} must stay "
            "inside repo_root",
        )
    return candidate, None


def _load_evidence_json(
    evidence_path: Path, raw_path: str
) -> tuple[dict[str, Any], str | None]:
    try:
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
    except OSError as error:
        return {}, (
            f"could not read telemetry_and_latency_archive evidence {raw_path}: "
            f"{error}"
        )
    except json.JSONDecodeError as error:
        return {}, (
            f"telemetry_and_latency_archive evidence {raw_path} has invalid "
            f"JSON: {error}"
        )
    if not isinstance(record, dict):
        return (
            {},
            f"telemetry_and_latency_archive evidence {raw_path} must be a JSON object",
        )
    return record, None


def _formal_latency_report_issues(record: dict[str, Any], path: str) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{path}: formal latency report schema_version must be {SCHEMA_VERSION}")
    if record.get("status") != "complete":
        issues.append(f"{path}: formal latency report status must be complete")
    if record.get("derivation_status") != "complete":
        issues.append(
            f"{path}: formal latency report derivation_status must be complete"
        )
    if record.get("verdict") != STATUS_PASS:
        issues.append(f"{path}: formal latency report verdict must be pass")
    measurement_method = record.get("measurement_method")
    if measurement_method not in LATENCY_ARCHIVE_MEASUREMENT_METHODS:
        issues.append(
            f"{path}: formal latency report measurement_method must be "
            "external-camera or synchronized-clock"
        )
    if (
        measurement_method == "synchronized-clock"
        and record.get("latency_kind") != "input"
    ):
        issues.append(
            f"{path}: synchronized-clock latency report must use latency_kind input"
        )
    gate = record.get("gate")
    if not isinstance(gate, dict):
        issues.append(f"{path}: formal latency report gate must be an object")
        return issues
    if gate.get("can_close_performance_gate") is not True:
        issues.append(
            f"{path}: formal latency report gate.can_close_performance_gate "
            "must be true"
        )
    if gate.get("summary_verdict") != STATUS_PASS:
        issues.append(f"{path}: formal latency report gate.summary_verdict must be pass")
    sample_count = gate.get("sample_count")
    min_sample_count = gate.get("min_sample_count")
    if (
        not _is_number(sample_count)
        or not _is_number(min_sample_count)
        or sample_count < min_sample_count
    ):
        issues.append(
            f"{path}: formal latency report sample_count must be greater than "
            "or equal to min_sample_count"
        )
    source = record.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("manifest"), str):
        issues.append(f"{path}: formal latency report source.manifest must be present")
    return issues


def _android_usb_live_smoke_report_issues(record: dict[str, Any], path: str) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{path}: Android USB live smoke schema_version must be {SCHEMA_VERSION}")
    if record.get("verdict") != STATUS_PASS:
        issues.append(f"{path}: Android USB live smoke verdict must be pass")
    claims = record.get("claims")
    if not isinstance(claims, dict) or claims.get("live_usb_stream_observed") is not True:
        issues.append(
            f"{path}: Android USB live smoke must claim live_usb_stream_observed=true"
        )
    logs = record.get("logs")
    if not isinstance(logs, dict):
        issues.append(f"{path}: Android USB live smoke logs must be an object")
        return issues
    telemetry = logs.get("telemetry")
    if not isinstance(telemetry, dict):
        issues.append(f"{path}: Android USB live smoke logs.telemetry must be an object")
    else:
        _extend_android_telemetry_issues(issues, telemetry, path)
    decoder = logs.get("decoder")
    if not isinstance(decoder, dict):
        issues.append(f"{path}: Android USB live smoke logs.decoder must be an object")
    else:
        _extend_android_decoder_issues(issues, decoder, path)
    return issues


def _extend_android_telemetry_issues(
    issues: list[str], telemetry: dict[str, Any], path: str
) -> None:
    session_epochs = telemetry.get("session_epochs")
    if not isinstance(session_epochs, list) or not session_epochs:
        issues.append(
            f"{path}: Android USB live smoke telemetry must include session_epochs"
        )
    stream_stats = telemetry.get("stream_stats")
    if not isinstance(stream_stats, dict):
        issues.append(
            f"{path}: Android USB live smoke telemetry.stream_stats must be an object"
        )
        return
    if not _is_positive_number(stream_stats.get("count")):
        issues.append(
            f"{path}: Android USB live smoke telemetry.stream_stats.count must be positive"
        )
    if not _is_positive_number(stream_stats.get("positive_fps_count")):
        issues.append(
            f"{path}: Android USB live smoke telemetry must include positive FPS stream_stats"
        )
    frame_drops = telemetry.get("frame_drops")
    latest = stream_stats.get("latest")
    has_frame_drop_summary = isinstance(frame_drops, dict) and _is_number(
        frame_drops.get("max_dropped_total")
    )
    has_latest_dropped_frames = isinstance(latest, dict) and _is_number(
        latest.get("dropped_frames")
    )
    if not has_frame_drop_summary and not has_latest_dropped_frames:
        issues.append(
            f"{path}: Android USB live smoke telemetry must include frame-drop counters"
        )


def _extend_android_decoder_issues(
    issues: list[str], decoder: dict[str, Any], path: str
) -> None:
    has_output_counter = decoder.get("latest_output_counter") is not None
    has_decode_stats = isinstance(decoder.get("latest_decode_stats"), dict)
    if not has_output_counter and not has_decode_stats:
        issues.append(
            f"{path}: Android USB live smoke decoder counters must be present"
        )
    latency = decoder.get("latest_output_latency")
    if (
        not isinstance(latency, dict)
        or not _is_number(latency.get("avg_ms"))
        or not _is_number(latency.get("max_ms"))
    ):
        issues.append(
            f"{path}: Android USB live smoke decoder latency metrics must be present"
        )


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _is_positive_number(value: Any) -> bool:
    return _is_number(value) and value > 0


def _open_pr_snapshot_guard(
    manifest: dict[str, Any],
    gate_summaries: Sequence[dict[str, Any]],
    *,
    evaluation_date: _datetime.date | None = None,
) -> dict[str, Any]:
    owner_prs = sorted({
        owner_pr
        for summary in gate_summaries
        for owner_pr in summary["owner_prs"]
    })
    snapshot = manifest.get("open_pr_snapshot")
    if snapshot is None:
        reasons = []
        if owner_prs:
            reasons.append(
                "owner_prs require open_pr_snapshot from `gh pr list --state open`"
            )
        return {
            "verdict": STATUS_INSUFFICIENT if reasons else STATUS_PASS,
            "command": None,
            "repository": None,
            "queried_at": None,
            "state": None,
            "open_pr_numbers": [],
            "owner_prs": owner_prs,
            "stale_owner_prs": owner_prs,
            "reasons": reasons,
        }
    if not isinstance(snapshot, dict):
        raise Phase0StableReleaseError("open_pr_snapshot must be an object")

    command = _string(snapshot, "command")
    repository = _string(snapshot, "repository")
    queried_at = _string(snapshot, "queried_at")
    state = _string(snapshot, "state")
    if repository != EXPECTED_OPEN_PR_REPOSITORY:
        raise Phase0StableReleaseError(
            "open_pr_snapshot.repository must be TaoSama/vibe-screen"
        )
    if state != "open":
        raise Phase0StableReleaseError("open_pr_snapshot.state must be open")
    parsed_queried_at = _parse_manifest_date(
        queried_at, "open_pr_snapshot.queried_at"
    )
    if evaluation_date is None:
        evaluation_date = _datetime.date.today()
    if parsed_queried_at > evaluation_date:
        raise Phase0StableReleaseError(
            "open_pr_snapshot.queried_at must not be in the future"
        )
    source = manifest.get("source", {})
    if isinstance(source, dict):
        audit_date = source.get("audit_date")
        if isinstance(audit_date, str) and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", audit_date
        ):
            parsed_audit_date = _parse_manifest_date(
                audit_date, "manifest source.audit_date"
            )
            if parsed_queried_at != parsed_audit_date:
                raise Phase0StableReleaseError(
                    "open_pr_snapshot.queried_at must match "
                    "manifest source.audit_date"
                )
    if not _is_expected_open_pr_command(command, repository):
        raise Phase0StableReleaseError(
            "open_pr_snapshot.command must list open PRs for TaoSama/vibe-screen"
        )

    open_pr_numbers = sorted(_int_list(snapshot, "open_pr_numbers"))
    stale_owner_prs = [
        owner_pr for owner_pr in owner_prs if owner_pr not in open_pr_numbers
    ]
    reasons = []
    if stale_owner_prs:
        reasons.append(
            "owner_prs are not present in open_pr_snapshot.open_pr_numbers: "
            + ", ".join(f"#{owner_pr}" for owner_pr in stale_owner_prs)
        )
    return {
        "verdict": STATUS_INSUFFICIENT if reasons else STATUS_PASS,
        "command": command,
        "repository": repository,
        "queried_at": queried_at,
        "state": state,
        "open_pr_numbers": open_pr_numbers,
        "owner_prs": owner_prs,
        "stale_owner_prs": stale_owner_prs,
        "reasons": reasons,
    }


def _merged_pr_snapshot_guard(
    manifest: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    snapshot = manifest.get("merged_pr_snapshot")
    if snapshot is None:
        return {
            "verdict": STATUS_INSUFFICIENT,
            "command": None,
            "repository": None,
            "state": None,
            "base": None,
            "range": None,
            "path": None,
            "audited_source_commit": None,
            "merged_pr_numbers": [],
            "excluded_pr_numbers": [],
            "non_ancestor_prs": [],
            "reasons": [
                "merged_pr_snapshot is required to verify audited mainline inputs"
            ],
        }
    if not isinstance(snapshot, dict):
        raise Phase0StableReleaseError("merged_pr_snapshot must be an object")

    command = _string(snapshot, "command")
    repository = _string(snapshot, "repository")
    state = _string(snapshot, "state")
    base = _string(snapshot, "base")
    path = _string(snapshot, "path")
    audited_source_commit = _string(snapshot, "audited_source_commit")
    if "excluded_pr_numbers" not in snapshot:
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.excluded_pr_numbers is required"
        )
    excluded_pr_numbers = sorted(_int_list(snapshot, "excluded_pr_numbers"))
    pr_range = snapshot.get("range")
    if not isinstance(pr_range, dict):
        raise Phase0StableReleaseError("merged_pr_snapshot.range must be an object")
    minimum = pr_range.get("min")
    maximum = pr_range.get("max")
    if type(minimum) is not int or type(maximum) is not int or minimum > maximum:
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.range must contain integer min <= max"
        )
    if repository != EXPECTED_OPEN_PR_REPOSITORY:
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.repository must be TaoSama/vibe-screen"
        )
    if state != "merged":
        raise Phase0StableReleaseError("merged_pr_snapshot.state must be merged")
    if base != "main":
        raise Phase0StableReleaseError("merged_pr_snapshot.base must be main")
    if not HASH_RE.fullmatch(audited_source_commit):
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.audited_source_commit must be a git object id"
        )
    source = manifest.get("source", {})
    if isinstance(source, dict):
        manifest_base_commit = source.get("base_commit")
        if (
            isinstance(manifest_base_commit, str)
            and manifest_base_commit.strip()
            and audited_source_commit != manifest_base_commit
        ):
            raise Phase0StableReleaseError(
                "merged_pr_snapshot.audited_source_commit must match "
                "manifest source.base_commit"
            )
    if not _is_expected_merged_pr_command(command, repository):
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.command must list merged PRs for "
            "TaoSama/vibe-screen with --base main and mergeCommit"
        )

    entries, load_reasons = _load_merged_pr_entries(path, repo_root=repo_root)
    reasons = list(load_reasons)
    merged_pr_numbers: list[int] = []
    non_ancestor_prs: list[int] = []
    for entry in entries:
        number = entry.get("number")
        if type(number) is not int:
            reasons.append("merged PR entry is missing integer number")
            continue
        merged_pr_numbers.append(number)
        if number < minimum or number > maximum:
            reasons.append(
                f"merged PR #{number} is outside the declared audited range "
                f"#{minimum}-#{maximum}"
            )
        base_ref_name = entry.get("baseRefName")
        if base_ref_name != base:
            reasons.append(
                f"merged PR #{number} targets baseRefName={base_ref_name!r}, "
                f"expected {base!r}"
            )
        merge_commit = entry.get("mergeCommit")
        if not isinstance(merge_commit, dict):
            reasons.append(f"merged PR #{number} is missing mergeCommit object")
            continue
        merge_commit_oid = merge_commit.get("oid")
        if not isinstance(merge_commit_oid, str) or not HASH_RE.fullmatch(
            merge_commit_oid
        ):
            reasons.append(f"merged PR #{number} is missing mergeCommit.oid")
            continue
        if repo_root is None:
            reasons.append(
                f"merged PR #{number} ancestry requires repo_root to verify "
                "mergeCommit.oid"
            )
            continue
        if not _git_check_call(
            repo_root.resolve(),
            "merge-base",
            "--is-ancestor",
            merge_commit_oid,
            audited_source_commit,
        ):
            non_ancestor_prs.append(number)
            reasons.append(
                f"merged PR #{number} mergeCommit {merge_commit_oid} is not an "
                f"ancestor of audited source commit {audited_source_commit}"
            )
    if not merged_pr_numbers:
        reasons.append("merged_pr_snapshot.path must contain merged PR entries")
    duplicate_numbers = sorted({
        number for number in merged_pr_numbers if merged_pr_numbers.count(number) > 1
    })
    if duplicate_numbers:
        reasons.append(
            "merged_pr_snapshot.path must not contain duplicate PR numbers: "
            + ", ".join(f"#{number}" for number in duplicate_numbers)
        )
    expected_numbers = set(range(minimum, maximum + 1))
    recorded_numbers = set(merged_pr_numbers)
    excluded_numbers = set(excluded_pr_numbers)
    overlap = sorted(recorded_numbers & excluded_numbers)
    if overlap:
        reasons.append(
            "merged_pr_snapshot.excluded_pr_numbers must not contain recorded "
            "merged PRs: " + ", ".join(f"#{number}" for number in overlap)
        )
    outside_excluded = sorted(
        number for number in excluded_numbers if number < minimum or number > maximum
    )
    if outside_excluded:
        reasons.append(
            "merged_pr_snapshot.excluded_pr_numbers contains PRs outside the "
            f"declared range #{minimum}-#{maximum}: "
            + ", ".join(f"#{number}" for number in outside_excluded)
        )
    missing_numbers = sorted(expected_numbers - recorded_numbers - excluded_numbers)
    if missing_numbers:
        reasons.append(
            "merged_pr_snapshot.path is missing PR numbers from the declared "
            f"range #{minimum}-#{maximum}: "
            + ", ".join(f"#{number}" for number in missing_numbers)
        )

    return {
        "verdict": STATUS_INSUFFICIENT if reasons else STATUS_PASS,
        "command": command,
        "repository": repository,
        "state": state,
        "base": base,
        "range": {"min": minimum, "max": maximum},
        "path": path,
        "audited_source_commit": audited_source_commit,
        "merged_pr_numbers": sorted(merged_pr_numbers),
        "excluded_pr_numbers": excluded_pr_numbers,
        "non_ancestor_prs": non_ancestor_prs,
        "reasons": reasons,
    }


def _is_expected_open_pr_command(command: str, repository: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if tokens[:3] != ["gh", "pr", "list"]:
        return False
    repo = _option_value(tokens, "--repo") or _option_value(tokens, "-R")
    state = _option_value(tokens, "--state") or _option_value(tokens, "-s")
    return (
        repo == repository
        and state == "open"
    )


def _is_expected_merged_pr_command(command: str, repository: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if tokens[:3] != ["gh", "pr", "list"]:
        return False
    repo = _option_value(tokens, "--repo") or _option_value(tokens, "-R")
    state = _option_value(tokens, "--state") or _option_value(tokens, "-s")
    base = _option_value(tokens, "--base") or _option_value(tokens, "-B")
    json_fields = _option_value(tokens, "--json") or ""
    requested_fields = {field.strip() for field in json_fields.split(",")}
    return (
        repo == repository
        and state == "merged"
        and base == "main"
        and {"number", "baseRefName", "mergeCommit"}.issubset(requested_fields)
    )


def _load_merged_pr_entries(
    path: str, *, repo_root: Path | None
) -> tuple[list[dict[str, Any]], list[str]]:
    reasons: list[str] = []
    if path.startswith("/") or ".." in Path(path).parts:
        raise Phase0StableReleaseError(
            "merged_pr_snapshot.path must be repo-relative"
        )
    if repo_root is None:
        return [], ["merged_pr_snapshot.path requires repo_root to load entries"]
    snapshot_path = repo_root.resolve() / path
    try:
        raw_lines = snapshot_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return [], [f"could not read merged_pr_snapshot.path {path}: {error}"]

    entries: list[dict[str, Any]] = []
    for index, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            reasons.append(
                f"merged_pr_snapshot.path {path} line {index} has invalid JSON: {error}"
            )
            continue
        if not isinstance(entry, dict):
            reasons.append(
                f"merged_pr_snapshot.path {path} line {index} must be a JSON object"
            )
            continue
        entries.append(entry)
    return entries, reasons


def _parse_manifest_date(value: str, field: str) -> _datetime.date:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise Phase0StableReleaseError(f"{field} must use YYYY-MM-DD format")
    try:
        return _datetime.date.fromisoformat(value)
    except ValueError as error:
        raise Phase0StableReleaseError(
            f"{field} must use a valid calendar date"
        ) from error


def _option_value(tokens: Sequence[str], name: str) -> str | None:
    prefix = f"{name}="
    for index, token in enumerate(tokens):
        if token.startswith(prefix):
            return token[len(prefix) :]
        if token == name and index + 1 < len(tokens):
            return tokens[index + 1]
    return None


def _readme_guard(
    *,
    manifest: dict[str, Any],
    readme_text: str | None,
    aggregate_passed: bool,
) -> dict[str, Any]:
    if readme_text is None:
        return {
            "verdict": STATUS_INSUFFICIENT,
            "missing_required_phrases": [],
            "forbidden_matches": [],
            "reasons": ["README guard was not evaluated"],
        }

    guard = manifest.get("readme_guard", {})
    if guard is None:
        guard = {}
    if not isinstance(guard, dict):
        raise Phase0StableReleaseError("readme_guard must be an object")
    required_phrases = _guard_string_list(
        guard, "required_phrases", DEFAULT_README_GUARD_PHRASES
    )
    forbidden_patterns = _guard_string_list(
        guard, "forbidden_regexes", DEFAULT_FORBIDDEN_README_PATTERNS
    )

    normalized_readme_text = re.sub(
        r"\s+", " ", re.sub(r"(?m)^\s*>\s?", "", readme_text)
    )
    missing_required_phrases = [] if aggregate_passed else [
        phrase
        for phrase in required_phrases
        if re.sub(r"\s+", " ", phrase) not in normalized_readme_text
    ]
    forbidden_matches = []
    if not aggregate_passed:
        for pattern in forbidden_patterns:
            compiled = _compile_guard_pattern(pattern)
            for match in compiled.finditer(normalized_readme_text):
                start = max(0, match.start() - 40)
                end = min(len(normalized_readme_text), match.end() + 40)
                forbidden_matches.append({
                    "pattern": pattern,
                    "snippet": normalized_readme_text[start:end].strip(),
                })

    reasons = []
    if missing_required_phrases:
        reasons.append(
            "README is missing the required in-progress release guard phrase(s)"
        )
    if forbidden_matches:
        reasons.append(
            "README appears to claim Phase 0 is complete or shipped while "
            "aggregate gates are open"
        )
    return {
        "verdict": STATUS_FAIL if reasons else STATUS_PASS,
        "missing_required_phrases": missing_required_phrases,
        "forbidden_matches": forbidden_matches,
        "reasons": reasons,
    }


def evaluate_manifest(
    manifest: dict[str, Any],
    *,
    readme_text: str | None = None,
    expected_source_commit: str | None = None,
    evaluation_date: _datetime.date | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise Phase0StableReleaseError("schema_version must be vibescreen.evidence/v1")
    if manifest.get("kind") != KIND:
        raise Phase0StableReleaseError(f"kind must be {KIND}")
    if manifest.get("phase") != "phase0":
        raise Phase0StableReleaseError("phase must be phase0")
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        raise Phase0StableReleaseError("source must be an object")

    source_guard = _source_guard(
        source,
        expected_source_commit,
        evaluation_date=evaluation_date,
        repo_root=repo_root,
    )

    gates_value = manifest.get("required_gates")
    if not isinstance(gates_value, list):
        raise Phase0StableReleaseError("required_gates must be a list")

    gate_summaries = []
    seen_gate_ids: set[str] = set()
    duplicate_gate_ids: list[str] = []
    for raw_gate in gates_value:
        if not isinstance(raw_gate, dict):
            raise Phase0StableReleaseError("required_gates entries must be objects")
        summary = _gate_summary(raw_gate, repo_root=repo_root)
        if summary["id"] in seen_gate_ids:
            duplicate_gate_ids.append(summary["id"])
        seen_gate_ids.add(summary["id"])
        gate_summaries.append(summary)

    owner_pr_guard = _open_pr_snapshot_guard(
        manifest, gate_summaries, evaluation_date=evaluation_date
    )
    merged_pr_guard = _merged_pr_snapshot_guard(manifest, repo_root=repo_root)

    missing_gate_ids = [gate_id for gate_id in REQUIRED_GATE_IDS if gate_id not in seen_gate_ids]
    unexpected_required_gate_ids = [
        summary["id"]
        for summary in gate_summaries
        if summary["required_for_stable_release"] and summary["id"] not in REQUIRED_GATE_IDS
    ]
    malformed_reasons = []
    if missing_gate_ids:
        malformed_reasons.append(
            "missing required Phase 0 gate id(s): " + ", ".join(missing_gate_ids)
        )
    if duplicate_gate_ids:
        malformed_reasons.append(
            "duplicate gate id(s): " + ", ".join(sorted(set(duplicate_gate_ids)))
        )
    if unexpected_required_gate_ids:
        malformed_reasons.append(
            "unexpected required gate id(s): "
            + ", ".join(unexpected_required_gate_ids)
        )
    for summary in gate_summaries:
        if summary["id"] in REQUIRED_GATE_IDS and not summary["required_for_stable_release"]:
            summary["issues"].append(
                "required Phase 0 gate cannot set required_for_stable_release=false"
            )

    required_gate_summaries = [
        summary for summary in gate_summaries if summary["id"] in REQUIRED_GATE_IDS
    ]
    blocking_gates = [
        summary
        for summary in required_gate_summaries
        if not summary["can_close"] or summary["issues"]
    ]
    all_required_gates_closed = (
        not malformed_reasons
        and owner_pr_guard["verdict"] == STATUS_PASS
        and merged_pr_guard["verdict"] == STATUS_PASS
        and not blocking_gates
        and not any(summary["issues"] for summary in gate_summaries)
    )
    if (
        source_guard["accepted_aggregate_only_successor"]
        and all_required_gates_closed
    ):
        source_guard = {
            **source_guard,
            "verdict": STATUS_INSUFFICIENT,
            "reasons": [
                *source_guard["reasons"],
                "aggregate-only successor commits cannot support a Phase 0 "
                "stable-release claim; refresh source.base_commit to the exact "
                "evaluated commit before marking every required gate closed",
            ],
        }
    aggregate_passed = (
        not malformed_reasons
        and source_guard["verdict"] == STATUS_PASS
        and owner_pr_guard["verdict"] == STATUS_PASS
        and merged_pr_guard["verdict"] == STATUS_PASS
        and not blocking_gates
        and not any(summary["issues"] for summary in gate_summaries)
    )
    readme_guard = _readme_guard(
        manifest=manifest,
        readme_text=readme_text,
        aggregate_passed=aggregate_passed,
    )

    if readme_guard["verdict"] == STATUS_FAIL:
        aggregate_verdict = STATUS_FAIL
    elif readme_guard["verdict"] == STATUS_INSUFFICIENT:
        aggregate_verdict = STATUS_INSUFFICIENT
    elif (
        malformed_reasons
        or source_guard["verdict"] == STATUS_INSUFFICIENT
        or owner_pr_guard["verdict"] == STATUS_INSUFFICIENT
        or merged_pr_guard["verdict"] == STATUS_INSUFFICIENT
        or any(summary["issues"] for summary in gate_summaries)
    ):
        aggregate_verdict = STATUS_INSUFFICIENT
    elif blocking_gates:
        aggregate_verdict = STATUS_BLOCKED
    else:
        aggregate_verdict = STATUS_PASS
    gate_reasons = _gate_reasons(gate_summaries)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "phase0_stable_release_closure_summary",
        "phase": "phase0",
        "aggregate_verdict": aggregate_verdict,
        "can_mark_phase0_stable_release": aggregate_verdict == STATUS_PASS,
        "required_gate_count": len(REQUIRED_GATE_IDS),
        "closed_required_gate_count": sum(
            1 for summary in required_gate_summaries if summary["can_close"]
        ),
        "missing_required_gate_ids": missing_gate_ids,
        "blocking_required_gates": blocking_gates,
        "gate_summaries": gate_summaries,
        "readme_guard": readme_guard,
        "source_guard": source_guard,
        "owner_pr_guard": owner_pr_guard,
        "merged_pr_guard": merged_pr_guard,
        "manifest_source": source,
        "reasons": [
            *malformed_reasons,
            *source_guard["reasons"],
            *owner_pr_guard["reasons"],
            *merged_pr_guard["reasons"],
            *gate_reasons,
            *readme_guard["reasons"],
        ],
    }


def _source_guard(
    source: dict[str, Any],
    expected_source_commit: str | None,
    *,
    evaluation_date: _datetime.date | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    base_commit = source.get("base_commit")
    reasons: list[str] = []
    accepted_aggregate_only_successor = False
    if not isinstance(base_commit, str) or not base_commit.strip():
        reasons.append("manifest source.base_commit must be a non-empty string")
    elif expected_source_commit and base_commit != expected_source_commit:
        accepted_aggregate_only_successor, successor_reasons = (
            _aggregate_only_successor_guard(
                base_commit=base_commit,
                expected_source_commit=expected_source_commit,
                repo_root=repo_root,
            )
        )
        if not accepted_aggregate_only_successor:
            reasons.extend(successor_reasons)
    for field in ("base_ref", "owner", "audit_source"):
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"manifest source.{field} must be a non-empty string")
    audit_date = source.get("audit_date")
    if not isinstance(audit_date, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", audit_date
    ):
        reasons.append("manifest source.audit_date must use YYYY-MM-DD format")
    else:
        if evaluation_date is None:
            evaluation_date = _datetime.date.today()
        try:
            parsed_audit_date = _parse_manifest_date(
                audit_date, "manifest source.audit_date"
            )
        except Phase0StableReleaseError as error:
            reasons.append(str(error))
        else:
            if parsed_audit_date > evaluation_date:
                reasons.append(
                    "manifest source.audit_date must not be in the future"
                )

    return {
        "verdict": STATUS_INSUFFICIENT if reasons else STATUS_PASS,
        "accepted_aggregate_only_successor": accepted_aggregate_only_successor,
        "expected_source_commit": expected_source_commit or None,
        "manifest_base_commit": base_commit if isinstance(base_commit, str) else None,
        "reasons": reasons,
    }


def _aggregate_only_successor_guard(
    *,
    base_commit: str,
    expected_source_commit: str,
    repo_root: Path | None,
) -> tuple[bool, list[str]]:
    mismatch = (
        "manifest source.base_commit does not match the evaluated source "
        f"commit: {base_commit} != {expected_source_commit}"
    )
    if repo_root is None:
        return False, [mismatch]
    if not HASH_RE.fullmatch(base_commit) or not HASH_RE.fullmatch(
        expected_source_commit
    ):
        return False, [mismatch]

    repository = repo_root.resolve()
    if not _git_check_call(
        repository, "merge-base", "--is-ancestor", base_commit, expected_source_commit
    ):
        return False, [
            mismatch,
            "expected source commit is not a descendant of manifest source.base_commit",
        ]

    changed_files, diff_error = _git_changed_files(
        repository, base_commit, expected_source_commit
    )
    if diff_error:
        return False, [mismatch, diff_error]
    disallowed_paths = [
        path for path in changed_files if not _is_aggregate_refresh_path(path)
    ]
    if disallowed_paths:
        return False, [
            mismatch,
            "expected source commit contains non-aggregate changes after "
            "manifest source.base_commit: " + ", ".join(disallowed_paths),
        ]
    return True, []


def _git_check_call(repo_root: Path, *args: str) -> bool:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _git_changed_files(
    repo_root: Path, base_commit: str, expected_source_commit: str
) -> tuple[list[str], str | None]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base_commit, expected_source_commit],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        return [], f"could not inspect changed files between source commits: {message}"
    return [line for line in result.stdout.splitlines() if line.strip()], None


def _is_aggregate_refresh_path(path: str) -> bool:
    if path.startswith("/") or ".." in Path(path).parts:
        return False
    return any(
        path == allowed_path.rstrip("/")
        or (allowed_path.endswith("/") and path.startswith(allowed_path))
        for allowed_path in AGGREGATE_REFRESH_PATHS
    )


def _release_claim_checkout_reasons(
    *,
    repo_root: Path,
    expected_source_commit: str,
    manifest_path: Path,
    readme_path: Path,
) -> list[str]:
    repository = repo_root.resolve()
    reasons: list[str] = []

    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if head_result.returncode != 0:
        message = head_result.stderr.strip() or head_result.stdout.strip()
        return [f"could not inspect current git HEAD: {message}"]
    current_head = head_result.stdout.strip()
    if current_head != expected_source_commit:
        reasons.append(
            "current git HEAD does not match --expected-source-commit: "
            f"{current_head} != {expected_source_commit}"
        )

    candidate_paths = [
        _repo_relative_path(repository, manifest_path),
        _repo_relative_path(repository, readme_path),
        *RELEASE_CLAIM_GUARD_PATHS,
    ]
    guard_paths = sorted({path for path in candidate_paths if path})
    diff_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--", *guard_paths],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if diff_result.returncode != 0:
        message = diff_result.stderr.strip() or diff_result.stdout.strip()
        reasons.append(f"could not inspect release-claim guard paths: {message}")
        return reasons
    dirty_paths = []
    for line in diff_result.stdout.splitlines():
        if not line:
            continue
        dirty_paths.append(line[3:].strip() if len(line) > 3 else line.strip())
    if dirty_paths:
        reasons.append(
            "release-claim guard paths contain uncommitted changes: "
            + ", ".join(dirty_paths)
        )
    return reasons


def _repo_relative_path(repo_root: Path, path: Path) -> str | None:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(repo_root).as_posix()
    except ValueError:
        return None


def _gate_reasons(gate_summaries: Sequence[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for summary in gate_summaries:
        reasons.extend(
            f"{summary['id']}: {issue}" for issue in summary["issues"]
        )
        if summary["id"] not in REQUIRED_GATE_IDS:
            continue
        if summary["can_close"] or summary["issues"]:
            continue
        if summary["blockers"]:
            reasons.extend(
                f"{summary['id']}: {blocker}" for blocker in summary["blockers"]
            )
        else:
            reasons.append(f"{summary['id']}: verdict={summary['verdict']}")
    return reasons


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        temporary_path.replace(path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                print(
                    f"warning: failed to remove temporary summary file "
                    f"{temporary_path}: {cleanup_error}",
                    file=sys.stderr,
                )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--output", type=Path, help="summary JSON path")
    parser.add_argument(
        "--expected-source-commit",
        help=(
            "Fail closed unless manifest source.base_commit matches this commit, "
            "or the expected commit is a blocked aggregate-only refresh "
            "successor"
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help=(
            "Repository root used to verify that an expected-source-commit "
            "mismatch contains only aggregate refresh files"
        ),
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit nonzero unless every aggregate Phase 0 stable-release gate passes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.require_pass and not args.expected_source_commit:
        print(
            "error: --require-pass requires --expected-source-commit so stale "
            "Phase 0 release claims fail closed",
            file=sys.stderr,
        )
        return 1
    try:
        with args.manifest.open("r", encoding="utf-8") as stream:
            manifest = load_json(stream)
        readme_text = args.readme.read_text(encoding="utf-8")
        summary = evaluate_manifest(
            manifest,
            readme_text=readme_text,
            expected_source_commit=args.expected_source_commit,
            repo_root=args.repo_root,
        )
        if args.output:
            _write_summary(args.output, summary)
        else:
            json.dump(summary, sys.stdout, indent=2, sort_keys=True, allow_nan=False)
            sys.stdout.write("\n")
    except (OSError, Phase0StableReleaseError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if summary["readme_guard"]["verdict"] != STATUS_PASS:
        return 1
    if args.require_pass and summary["aggregate_verdict"] == STATUS_PASS:
        checkout_reasons = _release_claim_checkout_reasons(
            repo_root=args.repo_root,
            expected_source_commit=args.expected_source_commit,
            manifest_path=args.manifest,
            readme_path=args.readme,
        )
        if checkout_reasons:
            for reason in checkout_reasons:
                print(f"error: {reason}", file=sys.stderr)
            return 1
    if args.require_pass and summary["aggregate_verdict"] != STATUS_PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
