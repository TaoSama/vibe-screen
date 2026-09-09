"""Evaluate the aggregate Phase 0 stable-release closure manifest.

This checker owns only the aggregate release decision. It does not reinterpret
readiness, synthetic, historical, or blocked sub-gate evidence as a pass.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
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
from .latency import GATE_PROFILES, MIN_GATE_SAMPLE_COUNT
from .latency_evidence import LatencyEvidenceError, build_latency_evidence_report
from .host_rss_gate import (
    GATE_KIND as HOST_RSS_GATE_KIND,
    MINIMUM_DURATION_SECONDS as HOST_RSS_MINIMUM_DURATION_SECONDS,
    MINIMUM_SAMPLE_COUNT as HOST_RSS_MINIMUM_SAMPLE_COUNT,
    derive_gate as derive_host_rss_gate,
)
from .macos_hardware_compatibility import (
    summarize as summarize_macos_hardware_compatibility,
)
from .controller_runtime import (
    BOOLEAN_FIELDS as CONTROLLER_RUNTIME_BOOLEAN_FIELDS,
)
from .native_pointer_hid import (
    ARTIFACT_FIELD_REQUIREMENTS as NATIVE_POINTER_HID_ARTIFACT_FIELD_REQUIREMENTS,
    BOOLEAN_FIELDS as NATIVE_POINTER_HID_BOOLEAN_FIELDS,
    GATE_KIND as NATIVE_POINTER_HID_GATE_KIND,
)
from .file_transfer_android_smoke import (
    EXPECTED_DIRECTION_ENDPOINTS as FILE_TRANSFER_EXPECTED_DIRECTION_ENDPOINTS,
    REQUIRED_CANCEL_ARTIFACT_ROLES as FILE_TRANSFER_REQUIRED_CANCEL_ARTIFACT_ROLES,
    REQUIRED_DIRECTION_ARTIFACT_ROLES as FILE_TRANSFER_REQUIRED_DIRECTION_ARTIFACT_ROLES,
    REQUIRED_PRODUCT_CONTEXT_FALSE as FILE_TRANSFER_REQUIRED_PRODUCT_CONTEXT_FALSE,
    REQUIRED_PRODUCT_CONTEXT_TRUE as FILE_TRANSFER_REQUIRED_PRODUCT_CONTEXT_TRUE,
)
from .clipboard_e2e_gate import (
    EXPECTED_DIRECTION_ENDPOINTS as CLIPBOARD_EXPECTED_DIRECTION_ENDPOINTS,
    LOCAL_MAXIMUM_CLIPBOARD_BYTES,
    REQUIRED_DIRECTION_ARTIFACT_ROLES as CLIPBOARD_REQUIRED_DIRECTION_ARTIFACT_ROLES,
)
from .soak_public_report import EvidenceInputError

KIND = "phase0_stable_release_closure"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_FAIL = "fail"
STATUS_INSUFFICIENT = "insufficient"
STATUS_OPEN = "open"
EXPECTED_OPEN_PR_REPOSITORY = "TaoSama/vibe-screen"
TELEMETRY_AND_LATENCY_ARCHIVE_GATE_ID = "telemetry_and_latency_archive"
HOST_RSS_2H_NO_GROWTH_GATE_ID = "host_rss_2h_no_growth"
NATIVE_POINTER_HID_MOUSE_GATE_ID = "native_pointer_hid_mouse"
CONTROLLER_RUNTIME_ACCEPTANCE_GATE_ID = "controller_runtime_acceptance"
MACOS_HOST_HARDWARE_COMPATIBILITY_MATRIX_GATE_ID = (
    "macos_host_hardware_compatibility_matrix"
)
CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID = "clipboard_android_macos_product_e2e"
FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID = "file_transfer_android_product_e2e"
LATENCY_EVIDENCE_GATE_KIND = "latency_evidence_gate"
ANDROID_USB_LIVE_SMOKE_KIND = "android_usb_live_smoke"
MACOS_HOST_COMPATIBILITY_MATRIX_ROW_KIND = "macos_host_compatibility_matrix_row"
CONTROLLER_RUNTIME_ACCEPTANCE_KIND = "controller_runtime_acceptance"
CLIPBOARD_E2E_GATE_KIND = "android_macos_clipboard_e2e_gate"
FILE_TRANSFER_ANDROID_SMOKE_GATE_KIND = "android_macos_file_transfer_smoke"
CLIPBOARD_E2E_REQUIRED_CHECKS = (
    "device_identity",
    "host_readiness",
    "real_transport_ready",
    "android_clipboardmanager_smoke",
    "bidirectional_product_e2e",
)
CLIPBOARD_PRODUCT_E2E_KIND = "android_macos_clipboard_product_e2e"
CLIPBOARD_SESSION_ID_RE = re.compile(r"[0-9a-fA-F]{32}")
CLIPBOARD_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
CLIPBOARD_REQUIRED_DIRECTION_TRUE = (
    "protocol_v1_session",
    "system_source_clipboard_read",
    "explicit_user_action",
    "receiver_user_approval",
    "remote_system_clipboard_write",
    "final_marker_match",
    "session_id_verified",
    "session_epoch_verified",
    "final_sha256_match",
    "origin_device_id_verified",
    "send_failure_absent",
    "write_failure_absent",
    "cleanup_completed",
    "utf8_valid",
    "overwrite_confirmed",
    "cancel_does_not_write",
    "failure_does_not_write",
    "deny_wins_observed",
)
CLIPBOARD_MARKER_FIELDS = (
    "marker",
    "overwrite_marker",
    "cancelled_marker",
    "failed_marker",
    "deny_marker",
)
LATENCY_ARCHIVE_MEASUREMENT_METHODS = {"external-camera", "synchronized-clock"}
LATENCY_SUMMARY_ONLY_KINDS = {"glass_to_glass", "input_latency"}
LATENCY_DIAGNOSTIC_ONLY_KINDS = {"telemetry_stage_latency"}
LATENCY_DIAGNOSTIC_ONLY_METHODS = {"host-telemetry", "client-telemetry"}
LATENCY_PREFLIGHT_ONLY_KINDS = {"latency_gate_preflight", "latency_preflight"}
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
FILE_TRANSFER_ANDROID_REQUIRED_CHECKS = (
    "device_identity",
    "host_readiness",
    "real_transport_ready",
    "android_file_transfer_smoke",
    "bidirectional_product_e2e",
    "cancel_cleanup",
)
FILE_TRANSFER_ANDROID_REQUIRED_SAFETY_TRUE = (
    "offline_tests_do_not_close_gate",
    "synthetic_evidence_do_not_close_gate",
    "no_host_ui_evidence_do_not_close_gate",
    "summary_only_evidence_do_not_close_gate",
    "retained_remote_file_bytes_required",
)
FILE_TRANSFER_ANDROID_REQUIRED_CLOSURE_TRUE = (
    "host_backed_product_session_required",
    "same_session_bidirectional_transfer_required",
    "same_session_id_required",
    "ordered_chunk_offsets_required",
    "final_chunk_marker_required",
    "retained_remote_file_bytes_required",
    "disconnect_cleanup_required",
    "summary_only_evidence_rejected",
    "no_host_ui_evidence_rejected",
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
    "tools/tests/test_phase0_stable_release.py",
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
    gate: dict[str, Any], *, repo_root: Path | None = None, manifest_source_commit: str | None = None
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
        elif gate_id == HOST_RSS_2H_NO_GROWTH_GATE_ID:
            issues.extend(
                _host_rss_2h_no_growth_issues(
                    evidence_paths=evidence_paths, repo_root=repo_root
                )
            )
        elif gate_id == MACOS_HOST_HARDWARE_COMPATIBILITY_MATRIX_GATE_ID:
            issues.extend(
                _macos_host_hardware_compatibility_matrix_issues(
                    evidence_paths=evidence_paths,
                    repo_root=repo_root,
                    manifest_source_commit=manifest_source_commit,
                )
            )
        elif gate_id == NATIVE_POINTER_HID_MOUSE_GATE_ID:
            issues.extend(
                _native_pointer_hid_mouse_issues(
                    evidence_paths=evidence_paths, repo_root=repo_root
                )
            )
        elif gate_id == CONTROLLER_RUNTIME_ACCEPTANCE_GATE_ID:
            issues.extend(
                _controller_runtime_acceptance_issues(
                    evidence_paths=evidence_paths, repo_root=repo_root
                )
            )
        elif gate_id == CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID:
            issues.extend(
                _clipboard_android_macos_product_e2e_issues(
                    evidence_paths=evidence_paths, repo_root=repo_root
                )
            )
        elif gate_id == FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID:
            issues.extend(
                _file_transfer_android_product_e2e_issues(
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
            report_issues = _formal_latency_report_issues(
                record, raw_path, repo_root=repository
            )
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
        else:
            latency_candidate_issues.extend(
                _non_formal_latency_artifact_issues(record, raw_path)
            )

    if not valid_latency_report:
        issues.append(
            "telemetry_and_latency_archive pass requires at least one passing "
            "formal latency_evidence_gate report whose source.manifest "
            "revalidates retained raw external-camera media or synchronized-clock "
            "physical-input proof"
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


def _macos_host_hardware_compatibility_matrix_issues(
    *,
    evidence_paths: Sequence[str],
    repo_root: Path | None,
    manifest_source_commit: str | None,
) -> list[str]:
    if repo_root is None:
        return [
            "macos_host_hardware_compatibility_matrix pass requires repo_root "
            "to verify formal compatibility row evidence paths"
        ]

    valid_compatibility_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=MACOS_HOST_HARDWARE_COMPATIBILITY_MATRIX_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                "macos_host_hardware_compatibility_matrix evidence path "
                f"{raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=MACOS_HOST_HARDWARE_COMPATIBILITY_MATRIX_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != MACOS_HOST_COMPATIBILITY_MATRIX_ROW_KIND:
            candidate_issues.append(
                f"{raw_path}: formal macOS Host compatibility report kind must be "
                f"{MACOS_HOST_COMPATIBILITY_MATRIX_ROW_KIND}"
            )
            continue
        report_issues = _formal_macos_host_compatibility_report_issues(
            record,
            raw_path,
            evidence_path=evidence_path,
            manifest_source_commit=manifest_source_commit,
        )
        if report_issues:
            candidate_issues.extend(report_issues)
        else:
            valid_compatibility_report = True

    if not valid_compatibility_report:
        issues.append(
            "macos_host_hardware_compatibility_matrix pass requires at least one "
            "passing formal macos_host_compatibility_matrix_row report that "
            "revalidates a retained gate_input artifact from the same evidence bundle"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_macos_host_compatibility_report_issues(
    record: dict[str, Any],
    path: str,
    *,
    evidence_path: Path,
    manifest_source_commit: str | None,
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            f"{path}: formal macOS Host compatibility report schema_version must be {SCHEMA_VERSION}"
        )
    if record.get("kind") != MACOS_HOST_COMPATIBILITY_MATRIX_ROW_KIND:
        issues.append(
            f"{path}: formal macOS Host compatibility report kind must be {MACOS_HOST_COMPATIBILITY_MATRIX_ROW_KIND}"
        )
    if record.get("profile") != "macos-host-compatibility-row":
        issues.append(
            f"{path}: formal macOS Host compatibility report profile must be macos-host-compatibility-row"
        )
    if record.get("verdict") != STATUS_PASS:
        issues.append(
            f"{path}: formal macOS Host compatibility report verdict must be pass"
        )
    if record.get("can_close_macos_host_compatibility_row") is not True:
        issues.append(
            f"{path}: formal macOS Host compatibility report can_close_macos_host_compatibility_row must be true"
        )

    for field in ("invalid_claims", "missing_requirements", "blocking_reasons"):
        value = record.get(field, [])
        if not isinstance(value, list):
            issues.append(
                f"{path}: formal macOS Host compatibility report {field} must be a list"
            )
        elif value:
            issues.append(
                f"{path}: formal macOS Host compatibility report pass must not include {field}"
            )

    checklist = record.get("closure_checklist")
    if not isinstance(checklist, list) or not checklist:
        issues.append(
            f"{path}: formal macOS Host compatibility report closure_checklist must be a non-empty list"
        )
    else:
        failing_items = [
            str(item.get("id", index))
            for index, item in enumerate(checklist)
            if not isinstance(item, dict) or item.get("status") != STATUS_PASS
        ]
        if failing_items:
            issues.append(
                f"{path}: formal macOS Host compatibility report closure_checklist must have all items pass: "
                + ", ".join(failing_items)
            )

    row_scope = record.get("row_scope")
    if not isinstance(row_scope, dict):
        issues.append(
            f"{path}: formal macOS Host compatibility report row_scope must be an object"
        )
    else:
        for field in (
            "repository_commit",
            "repository_tree",
            "cpu_architecture",
            "host_model_identifier",
            "macos_version",
            "macos_build",
            "display_topology",
            "capture_backend",
            "stream_transport",
            "android_counterpart",
            "compatibility_scope",
        ):
            if not isinstance(row_scope.get(field), str) or not row_scope.get(field, "").strip():
                issues.append(
                    f"{path}: formal macOS Host compatibility report row_scope.{field} must be present"
                )
        row_commit = row_scope.get("repository_commit")
        if (
            isinstance(manifest_source_commit, str)
            and HASH_RE.fullmatch(manifest_source_commit)
            and row_commit != manifest_source_commit
        ):
            issues.append(
                f"{path}: formal macOS Host compatibility report row_scope.repository_commit must match manifest source.base_commit"
            )

    artifact_file_check = record.get("artifact_file_check")
    if not isinstance(artifact_file_check, dict):
        issues.append(
            f"{path}: formal macOS Host compatibility report artifact_file_check must be an object"
        )
    else:
        if artifact_file_check.get("enabled") is not True:
            issues.append(
                f"{path}: formal macOS Host compatibility report artifact_file_check.enabled must be true"
            )
        for field in ("missing_paths", "invalid_paths", "empty_paths"):
            value = artifact_file_check.get(field, [])
            if not isinstance(value, list):
                issues.append(
                    f"{path}: formal macOS Host compatibility report artifact_file_check.{field} must be a list"
                )
            elif value:
                issues.append(
                    f"{path}: formal macOS Host compatibility report artifact_file_check.{field} must be empty"
                )

    artifact_role_check = record.get("artifact_role_check")
    gate_input_path = None
    if not isinstance(artifact_role_check, dict):
        issues.append(
            f"{path}: formal macOS Host compatibility report artifact_role_check must be an object"
        )
    else:
        for field in (
            "missing_roles",
            "invalid_paths",
            "unknown_roles",
            "duplicate_roles",
            "multi_role_paths",
        ):
            value = artifact_role_check.get(field, [])
            if not isinstance(value, list):
                issues.append(
                    f"{path}: formal macOS Host compatibility report artifact_role_check.{field} must be a list"
                )
            elif value:
                issues.append(
                    f"{path}: formal macOS Host compatibility report artifact_role_check.{field} must be empty"
                )
        gate_input_path = _single_macos_gate_input_path(artifact_role_check)
        if gate_input_path is None:
            issues.append(
                f"{path}: formal macOS Host compatibility report artifact_role_check must identify exactly one gate_input artifact"
            )

    if gate_input_path is not None:
        issues.extend(
            _macos_host_compatibility_gate_input_issues(
                record,
                path,
                evidence_path=evidence_path,
                gate_input_path=gate_input_path,
            )
        )
    return issues


def _single_macos_gate_input_path(artifact_role_check: dict[str, Any]) -> str | None:
    roles_by_path = artifact_role_check.get("roles_by_path")
    if not isinstance(roles_by_path, dict):
        return None
    gate_input_paths = [
        str(artifact_path)
        for artifact_path, roles in roles_by_path.items()
        if isinstance(artifact_path, str)
        and isinstance(roles, list)
        and roles == ["gate_input"]
    ]
    if len(gate_input_paths) != 1:
        return None
    return gate_input_paths[0]


def _macos_host_compatibility_gate_input_issues(
    record: dict[str, Any], path: str, *, evidence_path: Path, gate_input_path: str
) -> list[str]:
    input_path = Path(gate_input_path)
    if input_path.is_absolute() or ".." in input_path.parts:
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact must be evidence-relative"
        ]
    try:
        evidence_dir = evidence_path.parent.resolve()
        resolved_input = (evidence_dir / input_path).resolve(strict=True)
        resolved_input.relative_to(evidence_dir)
    except FileNotFoundError:
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact {gate_input_path} must exist"
        ]
    except (OSError, RuntimeError, ValueError) as error:
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact {gate_input_path} cannot be accessed: {error}"
        ]
    if not resolved_input.is_file():
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact {gate_input_path} must be a file"
        ]
    gate_input_record, load_issue = _load_evidence_json(
        resolved_input,
        gate_input_path,
        gate_id=MACOS_HOST_HARDWARE_COMPATIBILITY_MATRIX_GATE_ID,
    )
    if load_issue is not None:
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact could not be read: {load_issue}"
        ]
    try:
        rebuilt_report = summarize_macos_hardware_compatibility(
            gate_input_record, run_id=record.get("run_id"), evidence_dir=evidence_dir
        )
    except (OSError, TypeError, ValueError) as error:
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact could not be revalidated: {error}"
        ]
    if (
        rebuilt_report.get("verdict") != STATUS_PASS
        or rebuilt_report.get("can_close_macos_host_compatibility_row") is not True
    ):
        detail_parts = _macos_host_compatibility_failure_details(rebuilt_report)
        detail = "; ".join(part for part in detail_parts if part.strip())
        suffix = f": {detail}" if detail else ""
        return [
            f"{path}: formal macOS Host compatibility report gate_input artifact must rederive as a passing macos_host_compatibility_matrix_row report{suffix}"
        ]
    mismatch_fields = [
        field
        for field in (
            "run_id",
            "row_scope",
            "observations",
            "invalid_claims",
            "invalid_claim_observations",
            "closure_checklist",
            "missing_requirements",
            "blocking_reasons",
            "artifact_paths",
            "artifact_role_check",
        )
        if record.get(field) != rebuilt_report.get(field)
    ]
    if mismatch_fields:
        return [
            f"{path}: formal macOS Host compatibility report must match its rederived gate_input artifact for "
            + ", ".join(mismatch_fields)
        ]
    return []


def _macos_host_compatibility_failure_details(record: dict[str, Any]) -> list[str]:
    details: list[str] = []
    for field in ("blocking_reasons", "missing_requirements", "invalid_claims"):
        value = record.get(field, [])
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            detail = item.get("requirement") or item.get("reason")
            if isinstance(detail, str) and detail.strip():
                details.append(detail)
    return details


def _native_pointer_hid_mouse_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "native_pointer_hid_mouse pass requires repo_root to verify "
            "formal native pointer evidence paths"
        ]

    valid_native_pointer_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=NATIVE_POINTER_HID_MOUSE_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"native_pointer_hid_mouse evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=NATIVE_POINTER_HID_MOUSE_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != NATIVE_POINTER_HID_GATE_KIND:
            candidate_issues.append(
                f"{raw_path}: formal native pointer HID report kind must be "
                f"{NATIVE_POINTER_HID_GATE_KIND}"
            )
            continue
        report_issues = _formal_native_pointer_hid_report_issues(
            record, raw_path, evidence_path=evidence_path
        )
        if report_issues:
            candidate_issues.extend(report_issues)
        else:
            valid_native_pointer_report = True

    if not valid_native_pointer_report:
        issues.append(
            "native_pointer_hid_mouse pass requires at least one passing formal "
            "native_pointer_hid_acceptance report in evidence_paths"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_native_pointer_hid_report_issues(
    record: dict[str, Any], path: str, *, evidence_path: Path
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            f"{path}: formal native pointer HID report schema_version must be {SCHEMA_VERSION}"
        )
    if record.get("kind") != NATIVE_POINTER_HID_GATE_KIND:
        issues.append(
            f"{path}: formal native pointer HID report kind must be {NATIVE_POINTER_HID_GATE_KIND}"
        )
    if record.get("profile") != "native-pointer-hid-mouse":
        issues.append(
            f"{path}: formal native pointer HID report profile must be native-pointer-hid-mouse"
        )
    if record.get("verdict") != STATUS_PASS:
        issues.append(f"{path}: formal native pointer HID report verdict must be pass")
    if record.get("can_close_native_pointer_hid_gate") is not True:
        issues.append(
            f"{path}: formal native pointer HID report can_close_native_pointer_hid_gate must be true"
        )
    if record.get("requires_physical_mouse") is not True:
        issues.append(
            f"{path}: formal native pointer HID report requires_physical_mouse must be true"
        )
    if record.get("synthetic_adb_pointer_is_not_physical_hid_evidence") is not True:
        issues.append(
            f"{path}: formal native pointer HID report synthetic_adb_pointer_is_not_physical_hid_evidence must be true"
        )
    issues.extend(
        _required_observations_issues(
            record.get("observations"),
            NATIVE_POINTER_HID_BOOLEAN_FIELDS,
            f"{path}: formal native pointer HID report observations",
        )
    )
    for field in ("missing_requirements", "inconsistent_observations", "blocking_reasons"):
        value = record.get(field, [])
        if not isinstance(value, list):
            issues.append(f"{path}: formal native pointer HID report {field} must be a list")
        elif value:
            issues.append(
                f"{path}: formal native pointer HID report pass must not include {field}"
            )
    artifact_paths = record.get("artifact_paths", [])
    if not isinstance(artifact_paths, list) or not all(isinstance(item, str) for item in artifact_paths):
        issues.append(f"{path}: formal native pointer HID report artifact_paths must be a list of strings")
    else:
        issues.extend(
            _evidence_relative_artifact_path_issues(
                artifact_paths,
                f"{path}: formal native pointer HID report artifact_paths",
                evidence_dir=evidence_path.parent,
            )
        )
        required_artifact_names = {
            "dumpsys-input.txt",
            "android-logcat-native-pointer.txt",
            "host-log-appended.txt",
            "host-readiness.json",
        }
        missing_artifacts = [
            name for name in required_artifact_names if name not in artifact_paths
        ]
        if missing_artifacts:
            issues.append(
                f"{path}: formal native pointer HID report artifact_paths missing "
                + ", ".join(sorted(missing_artifacts))
            )
    observation_artifacts = record.get("observation_artifacts")
    if not isinstance(observation_artifacts, dict) or not observation_artifacts:
        issues.append(
            f"{path}: formal native pointer HID report observation_artifacts must be a non-empty object"
        )
    elif isinstance(artifact_paths, list):
        retained = {item for item in artifact_paths if isinstance(item, str)}
        mapped_native_pointer_observations = (
            set(NATIVE_POINTER_HID_ARTIFACT_FIELD_REQUIREMENTS)
            & set(NATIVE_POINTER_HID_BOOLEAN_FIELDS)
        )
        true_observations = [
            field
            for field in NATIVE_POINTER_HID_BOOLEAN_FIELDS
            if field in mapped_native_pointer_observations
            if isinstance(record.get("observations"), dict)
            and record["observations"].get(field) is True
        ]
        for field in true_observations:
            paths = observation_artifacts.get(field)
            if not isinstance(paths, list) or not paths or not all(isinstance(item, str) for item in paths):
                issues.append(
                    f"{path}: formal native pointer HID report observation_artifacts.{field} must be a non-empty list of strings"
                )
                continue
            missing_paths = sorted(item for item in paths if item not in retained)
            if missing_paths:
                issues.append(
                    f"{path}: formal native pointer HID report observation_artifacts.{field} must reference retained artifact_paths: "
                    + ", ".join(missing_paths)
                )
    return issues


def _controller_runtime_acceptance_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "controller_runtime_acceptance pass requires repo_root to verify "
            "formal controller runtime evidence paths"
        ]

    valid_controller_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=CONTROLLER_RUNTIME_ACCEPTANCE_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"controller_runtime_acceptance evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=CONTROLLER_RUNTIME_ACCEPTANCE_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != CONTROLLER_RUNTIME_ACCEPTANCE_KIND:
            candidate_issues.append(
                f"{raw_path}: formal controller runtime report kind must be "
                f"{CONTROLLER_RUNTIME_ACCEPTANCE_KIND}"
            )
            continue
        report_issues = _formal_controller_runtime_report_issues(
            record, raw_path, evidence_path=evidence_path
        )
        if report_issues:
            candidate_issues.extend(report_issues)
        else:
            valid_controller_report = True

    if not valid_controller_report:
        issues.append(
            "controller_runtime_acceptance pass requires at least one passing "
            "formal controller_runtime_acceptance report in evidence_paths"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_controller_runtime_report_issues(
    record: dict[str, Any], path: str, *, evidence_path: Path
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            f"{path}: formal controller runtime report schema_version must be {SCHEMA_VERSION}"
        )
    if record.get("kind") != CONTROLLER_RUNTIME_ACCEPTANCE_KIND:
        issues.append(
            f"{path}: formal controller runtime report kind must be {CONTROLLER_RUNTIME_ACCEPTANCE_KIND}"
        )
    if record.get("profile") != "controller-runtime-acceptance":
        issues.append(
            f"{path}: formal controller runtime report profile must be controller-runtime-acceptance"
        )
    if record.get("verdict") != STATUS_PASS:
        issues.append(f"{path}: formal controller runtime report verdict must be pass")
    if record.get("can_close_runtime_gate") is not True:
        issues.append(
            f"{path}: formal controller runtime report can_close_runtime_gate must be true"
        )
    if record.get("requires_external_hardware") is not True:
        issues.append(
            f"{path}: formal controller runtime report requires_external_hardware must be true"
        )
    if record.get("requires_entitled_host") is not True:
        issues.append(
            f"{path}: formal controller runtime report requires_entitled_host must be true"
        )
    issues.extend(
        _required_observations_issues(
            record.get("observations"),
            CONTROLLER_RUNTIME_BOOLEAN_FIELDS,
            f"{path}: formal controller runtime report observations",
        )
    )
    for field in ("missing_requirements", "inconsistent_observations", "blocking_reasons"):
        value = record.get(field, [])
        if not isinstance(value, list):
            issues.append(f"{path}: formal controller runtime report {field} must be a list")
        elif value:
            issues.append(
                f"{path}: formal controller runtime report pass must not include {field}"
            )
    artifact_paths = record.get("artifact_paths", [])
    if not isinstance(artifact_paths, list) or not all(isinstance(item, str) for item in artifact_paths):
        issues.append(f"{path}: formal controller runtime report artifact_paths must be a list of strings")
    elif not artifact_paths:
        issues.append(f"{path}: formal controller runtime report artifact_paths must be non-empty")
    else:
        issues.extend(
            _evidence_relative_artifact_path_issues(
                artifact_paths,
                f"{path}: formal controller runtime report artifact_paths",
                evidence_dir=evidence_path.parent,
            )
        )
    observation_artifacts = record.get("observation_artifacts")
    if not isinstance(observation_artifacts, dict) or not observation_artifacts:
        issues.append(
            f"{path}: formal controller runtime report observation_artifacts must be a non-empty object"
        )
    elif isinstance(artifact_paths, list):
        retained = {item for item in artifact_paths if isinstance(item, str)}
        for field, paths in observation_artifacts.items():
            if not isinstance(field, str):
                issues.append(
                    f"{path}: formal controller runtime report observation_artifacts keys must be strings"
                )
                continue
            if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
                issues.append(
                    f"{path}: formal controller runtime report observation_artifacts.{field} must be a list of strings"
                )
                continue
            missing = sorted(set(paths) - retained)
            if missing:
                issues.append(
                    f"{path}: formal controller runtime report observation_artifacts.{field} must reference retained artifact_paths: "
                    + ", ".join(missing)
                )
    return issues


def _required_observations_issues(
    observations: Any, required_fields: Sequence[str], label: str
) -> list[str]:
    if not isinstance(observations, dict):
        return [f"{label} must be an object"]
    missing = [field for field in required_fields if field not in observations]
    failing = [
        field
        for field in required_fields
        if field in observations and observations.get(field) is not True
    ]
    issues: list[str] = []
    if missing:
        issues.append(f"{label} missing required field(s): " + ", ".join(missing))
    if failing:
        issues.append(f"{label} must all be true: " + ", ".join(failing))
    return issues


def _evidence_relative_artifact_path_issues(
    artifact_paths: Sequence[str], label: str, *, evidence_dir: Path
) -> list[str]:
    issues: list[str] = []
    seen_paths: set[str] = set()
    try:
        resolved_evidence_dir = evidence_dir.resolve()
    except OSError as error:
        return [f"{label} evidence directory cannot be read: {error}"]
    for index, artifact in enumerate(artifact_paths):
        artifact_label = f"{label}[{index}]"
        if not artifact.strip():
            issues.append(f"{artifact_label} must be non-empty")
            continue
        artifact_path = Path(artifact)
        if artifact_path.is_absolute():
            issues.append(f"{artifact_label} must be evidence-relative")
            continue
        if ".." in artifact_path.parts:
            issues.append(f"{artifact_label} must stay inside the evidence bundle")
            continue
        normalized = artifact_path.as_posix()
        if normalized in seen_paths:
            issues.append(f"{artifact_label} must be distinct")
        seen_paths.add(normalized)
        try:
            resolved_artifact = (resolved_evidence_dir / artifact_path).resolve(strict=True)
            resolved_artifact.relative_to(resolved_evidence_dir)
        except FileNotFoundError:
            issues.append(f"{artifact_label} missing retained artifact {artifact}")
            continue
        except (OSError, RuntimeError, ValueError) as error:
            issues.append(f"{artifact_label} cannot access retained artifact {artifact}: {error}")
            continue
        if not resolved_artifact.is_file():
            issues.append(f"{artifact_label} missing retained artifact {artifact}")
            continue
        try:
            if resolved_artifact.stat().st_size <= 0:
                issues.append(f"{artifact_label} retained artifact {artifact} must be non-empty")
        except OSError as error:
            issues.append(f"{artifact_label} cannot stat retained artifact {artifact}: {error}")
    return issues


def _clipboard_android_macos_product_e2e_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "clipboard_android_macos_product_e2e pass requires repo_root to verify "
            "formal clipboard gate evidence paths"
        ]

    valid_clipboard_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"clipboard_android_macos_product_e2e evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != CLIPBOARD_E2E_GATE_KIND:
            candidate_issues.append(
                f"{raw_path}: formal clipboard report kind must be {CLIPBOARD_E2E_GATE_KIND}"
            )
            continue
        report_issues = _formal_clipboard_e2e_report_issues(
            record, raw_path, repo_root=repository
        )
        if report_issues:
            candidate_issues.extend(report_issues)
        else:
            valid_clipboard_report = True

    if not valid_clipboard_report:
        issues.append(
            "clipboard_android_macos_product_e2e pass requires at least one passing "
            "formal android_macos_clipboard_e2e_gate report in evidence_paths"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_clipboard_e2e_report_issues(
    record: dict[str, Any], path: str, *, repo_root: Path
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{path}: formal clipboard report schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") != CLIPBOARD_E2E_GATE_KIND:
        issues.append(f"{path}: formal clipboard report kind must be {CLIPBOARD_E2E_GATE_KIND}")
    if record.get("verdict") != STATUS_PASS or record.get("result") != STATUS_PASS:
        issues.append(f"{path}: formal clipboard report verdict and result must be pass")
    if record.get("gate_closed") is not True:
        issues.append(f"{path}: formal clipboard report gate_closed must be true")
    if record.get("can_close_android_macos_clipboard_e2e_gate") is not True:
        issues.append(
            f"{path}: formal clipboard report can_close_android_macos_clipboard_e2e_gate must be true"
        )
    blockers = record.get("blockers", [])
    if not isinstance(blockers, list) or any(not isinstance(blocker, str) for blocker in blockers):
        issues.append(f"{path}: formal clipboard report blockers must be a list of strings")
    elif any(blocker.strip() for blocker in blockers):
        issues.append(f"{path}: formal clipboard report pass must not include unresolved blockers")
    not_proven = record.get("not_proven", [])
    if not isinstance(not_proven, list) or any(not isinstance(item, str) for item in not_proven):
        issues.append(f"{path}: formal clipboard report not_proven must be a list of strings")
    elif any(item.strip() for item in not_proven):
        issues.append(f"{path}: formal clipboard report pass must not list unproven product paths")
    safety = record.get("safety")
    if not isinstance(safety, dict):
        issues.append(f"{path}: formal clipboard report safety must be an object")
    else:
        for field in (
            "offline_tests_do_not_close_gate",
            "synthetic_evidence_do_not_close_gate",
            "public_output_sanitized",
            "raw_serial_redacted",
        ):
            if safety.get(field) is not True:
                issues.append(f"{path}: formal clipboard report safety.{field} must be true")
    checks = record.get("checks")
    if not isinstance(checks, list):
        issues.append(f"{path}: formal clipboard report checks must be a list")
    else:
        check_by_name = {
            item.get("name"): item
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        for check_name in CLIPBOARD_E2E_REQUIRED_CHECKS:
            check = check_by_name.get(check_name)
            if check is None:
                issues.append(f"{path}: formal clipboard report checks missing {check_name}")
            elif check.get("status") != STATUS_PASS:
                issues.append(f"{path}: formal clipboard report check {check_name} must be pass")
    source = record.get("source")
    if not isinstance(source, dict):
        issues.append(f"{path}: formal clipboard report source must be an object")
        return issues
    product_e2e_ref = source.get("product_e2e")
    if not isinstance(product_e2e_ref, str) or not product_e2e_ref.strip():
        issues.append(f"{path}: formal clipboard report source.product_e2e must be present")
        return issues
    product_path, path_issue = _repo_relative_evidence_path(
        repo_root,
        product_e2e_ref.strip(),
        gate_id=CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID,
    )
    if path_issue is not None or product_path is None:
        issues.append(
            f"{path}: formal clipboard report source.product_e2e must be a repo-relative path inside repo_root"
        )
        return issues
    if not product_path.exists():
        issues.append(
            f"{path}: formal clipboard report source.product_e2e {product_e2e_ref.strip()} must exist"
        )
        return issues
    product_record, load_issue = _load_evidence_json(
        product_path,
        product_e2e_ref.strip(),
        gate_id=CLIPBOARD_ANDROID_MACOS_PRODUCT_E2E_GATE_ID,
    )
    if load_issue is not None:
        issues.append(f"{path}: formal clipboard report source.product_e2e could not be read: {load_issue}")
        return issues
    issues.extend(
        _clipboard_product_e2e_source_issues(
            product_record,
            f"{path}: source.product_e2e {product_e2e_ref.strip()}",
            evidence_dir=product_path.parent,
        )
    )
    return issues


def _clipboard_product_e2e_source_issues(
    record: dict[str, Any],
    label: str,
    *,
    evidence_dir: Path | None,
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{label} schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") != CLIPBOARD_PRODUCT_E2E_KIND:
        issues.append(f"{label} kind must be {CLIPBOARD_PRODUCT_E2E_KIND}")
    if record.get("synthetic") is True or record.get("offline_only") is True:
        issues.append(f"{label} synthetic or offline-only evidence cannot close this gate")

    directions = record.get("directions")
    if not isinstance(directions, dict):
        issues.append(f"{label} directions must be an object")
        return issues

    markers: dict[str, str] = {}
    change_ids: dict[str, str] = {}
    digests: dict[str, str] = {}
    session_ids: dict[str, str] = {}
    transports: dict[str, str] = {}
    session_epochs: dict[str, int] = {}
    artifact_paths: dict[Path | str, tuple[str, str]] = {}
    for direction_name, endpoints in CLIPBOARD_EXPECTED_DIRECTION_ENDPOINTS.items():
        direction = directions.get(direction_name)
        if not isinstance(direction, dict):
            issues.append(f"{label} missing {direction_name} direction evidence")
            continue
        issues.extend(
            _clipboard_direction_source_issues(
                direction,
                f"{label} {direction_name}",
                endpoints,
                evidence_dir,
                artifact_paths,
            )
        )
        marker = direction.get("marker")
        if isinstance(marker, str) and marker.strip():
            markers[direction_name] = marker.strip()
        change_id = direction.get("change_id_hex")
        if isinstance(change_id, str) and CLIPBOARD_SESSION_ID_RE.fullmatch(change_id):
            change_ids[direction_name] = change_id.lower()
        digest = direction.get("sha256")
        if isinstance(digest, str) and CLIPBOARD_SHA256_RE.fullmatch(digest):
            digests[direction_name] = digest.lower()
        session_id = direction.get("session_id_hex")
        if isinstance(session_id, str) and CLIPBOARD_SESSION_ID_RE.fullmatch(session_id):
            session_ids[direction_name] = session_id.lower()
        transport = direction.get("transport")
        if transport in {"usb", "trusted_lan"}:
            transports[direction_name] = transport
        session_epoch = direction.get("session_epoch")
        if _is_positive_integer(session_epoch):
            session_epochs[direction_name] = session_epoch

    android_to_macos = "android_clipboardmanager_to_macos_nspasteboard"
    macos_to_android = "macos_nspasteboard_to_android_clipboardmanager"
    if markers.get(android_to_macos) and markers.get(android_to_macos) == markers.get(macos_to_android):
        issues.append(f"{label} direction markers must be distinct")
    if change_ids.get(android_to_macos) and change_ids.get(android_to_macos) == change_ids.get(macos_to_android):
        issues.append(f"{label} direction change IDs must be distinct")
    if digests.get(android_to_macos) and digests.get(android_to_macos) == digests.get(macos_to_android):
        issues.append(f"{label} direction SHA-256 digests must be distinct")
    if session_ids.get(android_to_macos) and session_ids.get(macos_to_android) and session_ids[android_to_macos] != session_ids[macos_to_android]:
        issues.append(f"{label} direction session IDs must match for same-session bidirectional product evidence")
    if transports.get(android_to_macos) and transports.get(macos_to_android) and transports[android_to_macos] != transports[macos_to_android]:
        issues.append(f"{label} direction transports must match for same-session bidirectional product evidence")
    if session_epochs.get(android_to_macos) and session_epochs.get(macos_to_android) and session_epochs[android_to_macos] != session_epochs[macos_to_android]:
        issues.append(f"{label} direction session_epoch values must match for same-session bidirectional product evidence")
    return issues


def _clipboard_direction_source_issues(
    direction: dict[str, Any],
    label: str,
    endpoints: tuple[str, str],
    evidence_dir: Path | None,
    cross_direction_artifact_paths: dict[Path | str, tuple[str, str]],
) -> list[str]:
    issues: list[str] = []
    direction_name = label.rsplit(" ", 1)[-1]
    issues.extend(
        _retained_artifact_issues(
            direction,
            label,
            CLIPBOARD_REQUIRED_DIRECTION_ARTIFACT_ROLES,
            evidence_dir,
            expected_direction=direction_name,
            cross_direction_artifact_paths=cross_direction_artifact_paths,
        )
    )
    source_endpoint, destination_endpoint = endpoints
    if direction.get("source_system_clipboard") != source_endpoint:
        issues.append(f"{label}.source_system_clipboard must be {source_endpoint}")
    if direction.get("destination_system_clipboard") != destination_endpoint:
        issues.append(f"{label}.destination_system_clipboard must be {destination_endpoint}")
    for field in CLIPBOARD_REQUIRED_DIRECTION_TRUE:
        if direction.get(field) is not True:
            issues.append(f"{label}.{field} must be true")
    if direction.get("mime_type") != "text/plain":
        issues.append(f"{label}.mime_type must be text/plain")
    byte_length = direction.get("byte_length")
    if not _is_positive_integer(byte_length):
        issues.append(f"{label}.byte_length must be a positive integer")
    elif byte_length > LOCAL_MAXIMUM_CLIPBOARD_BYTES:
        issues.append(f"{label}.byte_length must not exceed 1048576 bytes")
    session_epoch = direction.get("session_epoch")
    if not _is_positive_integer(session_epoch):
        issues.append(f"{label}.session_epoch must be a positive integer")
    transport = direction.get("transport")
    if transport not in {"usb", "trusted_lan"}:
        issues.append(f"{label}.transport must be usb or trusted_lan")
    for field, description in (
        ("change_id_hex", "change ID"),
        ("session_id_hex", "session ID"),
    ):
        value = direction.get(field)
        if not isinstance(value, str) or not CLIPBOARD_SESSION_ID_RE.fullmatch(value):
            issues.append(f"{label}.{field} must be a 32-character hex {description}")
    sha256 = direction.get("sha256")
    if not isinstance(sha256, str) or not CLIPBOARD_SHA256_RE.fullmatch(sha256):
        issues.append(f"{label}.sha256 must be a 64-character hex SHA-256 digest")
    marker = direction.get("marker")
    if not isinstance(marker, str) or len(marker.strip()) < 8:
        issues.append(f"{label}.marker must identify the transferred text marker")
    final_marker = direction.get("final_marker")
    if final_marker != marker:
        issues.append(f"{label}.final_marker must equal marker after the destination system clipboard write")
    seen_markers: dict[str, str] = {}
    for field in CLIPBOARD_MARKER_FIELDS:
        value = direction.get(field)
        if not isinstance(value, str) or len(value.strip()) < 8:
            issues.append(f"{label}.{field} must identify the clipboard boundary marker")
            continue
        normalized = value.strip()
        previous = seen_markers.get(normalized)
        if previous is not None:
            issues.append(f"{label}.{field} must be distinct from {previous}")
        else:
            seen_markers[normalized] = field
    origin_device_id = direction.get("origin_device_id")
    if not isinstance(origin_device_id, str) or not origin_device_id.strip():
        issues.append(f"{label}.origin_device_id must record the verified Protocol v1 origin device ID")
    issues.extend(
        _clipboard_payload_artifact_issues(
            direction,
            label,
            "source_clipboard_read",
            evidence_dir,
        )
    )
    issues.extend(
        _clipboard_payload_artifact_issues(
            direction,
            label,
            "destination_clipboard_write",
            evidence_dir,
        )
    )
    issues.extend(_clipboard_protocol_packets_artifact_issues(direction, label, evidence_dir))
    return issues


def _clipboard_payload_artifact_issues(
    direction: dict[str, Any],
    label: str,
    role: str,
    evidence_dir: Path | None,
) -> list[str]:
    artifact_path = _retained_artifact_path(direction, role)
    if artifact_path is None or evidence_dir is None:
        return []
    resolved_artifact = _resolve_retained_artifact_path(artifact_path, evidence_dir)
    if resolved_artifact is None:
        return []
    issues: list[str] = []
    try:
        data = resolved_artifact.read_bytes()
    except OSError as error:
        return [f"{label}.{role} artifact cannot be read: {error}"]
    expected_byte_length = direction.get("byte_length")
    if _is_positive_integer(expected_byte_length) and len(data) != expected_byte_length:
        issues.append(
            f"{label}.{role} artifact size {len(data)} must equal direction.byte_length {expected_byte_length}"
        )
    expected_sha256 = direction.get("sha256")
    if isinstance(expected_sha256, str) and CLIPBOARD_SHA256_RE.fullmatch(expected_sha256):
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256.lower():
            issues.append(f"{label}.{role} artifact SHA-256 must equal direction.sha256")
    return issues


def _retained_artifact_path(record: dict[str, Any], role: str) -> Path | None:
    artifacts = record.get("retained_artifacts")
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("role") != role:
            continue
        path_value = artifact.get("path")
        if isinstance(path_value, str) and path_value.strip():
            return Path(path_value)
    return None


def _resolve_retained_artifact_path(path: Path, evidence_dir: Path) -> Path | None:
    if path.is_absolute() or ".." in path.parts:
        return None
    try:
        resolved_evidence_dir = evidence_dir.resolve()
        resolved_artifact = (evidence_dir / path).resolve(strict=True)
        resolved_artifact.relative_to(resolved_evidence_dir)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    if not resolved_artifact.is_file():
        return None
    return resolved_artifact


def _clipboard_protocol_packets_artifact_issues(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
) -> list[str]:
    artifact_path = _retained_artifact_path(direction, "protocol_packets")
    if artifact_path is None or evidence_dir is None:
        return []
    resolved_artifact = _resolve_retained_artifact_path(artifact_path, evidence_dir)
    if resolved_artifact is None:
        return []
    required_events = {"clipboard_offer", "clipboard_request", "clipboard_content"}
    observed_events: set[str] = set()
    observed_change_id = False
    observed_epoch = False
    observed_origin = False
    event_records_missing_metadata: list[str] = []
    malformed_lines: list[int] = []
    change_id = direction.get("change_id_hex")
    session_epoch = direction.get("session_epoch")
    origin_device_id = direction.get("origin_device_id")
    try:
        lines = resolved_artifact.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return [f"{label}.protocol_packets artifact cannot be read: {error}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line_number)
            continue
        if not isinstance(record, dict):
            malformed_lines.append(line_number)
            continue
        event_names = {
            str(record.get(key, "")).strip().lower()
            for key in ("type", "event", "name", "message_type", "packet_type")
            if str(record.get(key, "")).strip()
        }
        matching_events = required_events & event_names
        observed_events.update(matching_events)
        serialized_record = json.dumps(record, sort_keys=True).lower()
        event_has_change_id = (
            isinstance(change_id, str)
            and CLIPBOARD_SESSION_ID_RE.fullmatch(change_id) is not None
            and change_id.lower() in serialized_record
        )
        record_session_epoch = record.get("session_epoch")
        event_has_epoch = (
            isinstance(session_epoch, int)
            and not isinstance(session_epoch, bool)
            and isinstance(record_session_epoch, int)
            and not isinstance(record_session_epoch, bool)
            and record_session_epoch == session_epoch
        )
        event_has_origin = (
            isinstance(origin_device_id, str)
            and bool(origin_device_id.strip())
            and origin_device_id.strip().lower() in serialized_record
        )
        observed_change_id = observed_change_id or event_has_change_id
        observed_epoch = observed_epoch or event_has_epoch
        observed_origin = observed_origin or event_has_origin
        if matching_events and not (event_has_change_id and event_has_epoch and event_has_origin):
            event_records_missing_metadata.extend(sorted(matching_events))

    issues: list[str] = []
    if malformed_lines:
        issues.append(f"{label}.protocol_packets artifact must be JSONL; malformed line(s): {malformed_lines[:5]}")
    missing_events = sorted(required_events - observed_events)
    if missing_events:
        issues.append(f"{label}.protocol_packets artifact missing event(s): {', '.join(missing_events)}")
    if event_records_missing_metadata:
        missing_metadata_events = sorted(set(event_records_missing_metadata))
        issues.append(
            f"{label}.protocol_packets event record(s) must include matching change_id_hex, "
            f"session_epoch, and origin_device_id: {', '.join(missing_metadata_events)}"
        )
    if not observed_change_id:
        issues.append(f"{label}.protocol_packets artifact must include change_id_hex {direction.get('change_id_hex')}")
    if not observed_epoch:
        issues.append(f"{label}.protocol_packets artifact must include session_epoch {direction.get('session_epoch')}")
    if not observed_origin:
        issues.append(f"{label}.protocol_packets artifact must include origin_device_id {direction.get('origin_device_id')}")
    return issues


def _non_formal_latency_artifact_issues(record: dict[str, Any], path: str) -> list[str]:
    kind = record.get("kind")
    measurement_method = record.get("measurement_method")
    latency_kind = record.get("latency_kind")
    if (
        kind in LATENCY_DIAGNOSTIC_ONLY_KINDS
        or measurement_method in LATENCY_DIAGNOSTIC_ONLY_METHODS
        or latency_kind == "telemetry-stage"
    ):
        return [
            f"{path}: telemetry diagnostic artifacts are informational only; "
            "they may accompany but cannot replace a formal latency_evidence_gate "
            "report with external measurement proof"
        ]
    if kind in LATENCY_SUMMARY_ONLY_KINDS:
        return [
            f"{path}: latency summary artifacts are summary-only; "
            "telemetry_and_latency_archive pass requires the formal "
            "latency_evidence_gate output that revalidates the source manifest, "
            "raw external-camera media, sample annotations, and any synchronized-clock "
            "physical-input proof"
        ]
    if kind in LATENCY_PREFLIGHT_ONLY_KINDS:
        return [
            f"{path}: latency preflight artifacts record readiness only; they do "
            "not contain the formal raw-media or synchronized-clock physical-input "
            "evidence needed to close telemetry_and_latency_archive"
        ]
    return []


def _repo_relative_evidence_path(
    repo_root: Path, raw_path: str, *, gate_id: str = TELEMETRY_AND_LATENCY_ARCHIVE_GATE_ID
) -> tuple[Path | None, str | None]:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_path):
        return None, None
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        return (
            None,
            f"{gate_id} evidence path {raw_path!r} must be "
            "repo-relative",
        )
    candidate = repo_root / path
    try:
        candidate.resolve().relative_to(repo_root)
    except ValueError:
        return (
            None,
            f"{gate_id} evidence path {raw_path!r} must stay "
            "inside repo_root",
        )
    return candidate, None


def _load_evidence_json(
    evidence_path: Path, raw_path: str, *, gate_id: str = TELEMETRY_AND_LATENCY_ARCHIVE_GATE_ID
) -> tuple[dict[str, Any], str | None]:
    try:
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return {}, (
            f"could not read {gate_id} evidence {raw_path}: "
            f"{error}"
        )
    except json.JSONDecodeError as error:
        return {}, (
            f"{gate_id} evidence {raw_path} has invalid "
            f"JSON: {error}"
        )
    if not isinstance(record, dict):
        return (
            {},
            f"{gate_id} evidence {raw_path} must be a JSON object",
        )
    return record, None


def _file_transfer_android_product_e2e_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "file_transfer_android_product_e2e pass requires repo_root to verify "
            "structured evidence paths"
        ]

    valid_file_transfer_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"file_transfer_android_product_e2e evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != FILE_TRANSFER_ANDROID_SMOKE_GATE_KIND:
            candidate_issues.append(
                f"{raw_path}: formal file-transfer report kind must be "
                f"{FILE_TRANSFER_ANDROID_SMOKE_GATE_KIND}"
            )
            continue
        report_issues = _formal_file_transfer_android_product_e2e_report_issues(
            record, raw_path, repo_root=repository
        )
        if report_issues:
            candidate_issues.extend(report_issues)
        else:
            valid_file_transfer_report = True

    if not valid_file_transfer_report:
        issues.append(
            "file_transfer_android_product_e2e pass requires at least one passing "
            "formal android_macos_file_transfer_smoke gate report with Host-backed, "
            "same-session bidirectional product evidence and retained source/destination bytes"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_file_transfer_android_product_e2e_report_issues(
    record: dict[str, Any], path: str, *, repo_root: Path
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{path}: formal file-transfer report schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") != FILE_TRANSFER_ANDROID_SMOKE_GATE_KIND:
        issues.append(
            f"{path}: formal file-transfer report kind must be {FILE_TRANSFER_ANDROID_SMOKE_GATE_KIND}"
        )
    for field in ("verdict", "result"):
        if record.get(field) != STATUS_PASS:
            issues.append(f"{path}: formal file-transfer report {field} must be pass")
    if record.get("gate_closed") is not True:
        issues.append(f"{path}: formal file-transfer report gate_closed must be true")
    if record.get("can_close_file_transfer_android_smoke_gate") is not True:
        issues.append(
            f"{path}: formal file-transfer report can_close_file_transfer_android_smoke_gate must be true"
        )

    for field in ("blockers", "not_proven"):
        value = record.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            issues.append(f"{path}: formal file-transfer report {field} must be a list of strings")
        elif any(item.strip() for item in value):
            issues.append(f"{path}: formal file-transfer report pass must not include unresolved {field}")

    safety = record.get("safety")
    if not isinstance(safety, dict):
        issues.append(f"{path}: formal file-transfer report safety must be an object")
    else:
        for field in FILE_TRANSFER_ANDROID_REQUIRED_SAFETY_TRUE:
            if safety.get(field) is not True:
                issues.append(f"{path}: formal file-transfer report safety.{field} must be true")

    closure = record.get("product_e2e_closure")
    if not isinstance(closure, dict):
        issues.append(f"{path}: formal file-transfer report product_e2e_closure must be an object")
    else:
        for field in FILE_TRANSFER_ANDROID_REQUIRED_CLOSURE_TRUE:
            if closure.get(field) is not True:
                issues.append(
                    f"{path}: formal file-transfer report product_e2e_closure.{field} must be true"
                )

    checks = record.get("checks")
    if not isinstance(checks, list):
        issues.append(f"{path}: formal file-transfer report checks must be a list")
        return issues
    checks_by_name = {
        check.get("name"): check
        for check in checks
        if isinstance(check, dict) and isinstance(check.get("name"), str)
    }
    for check_name in FILE_TRANSFER_ANDROID_REQUIRED_CHECKS:
        check = checks_by_name.get(check_name)
        if not isinstance(check, dict):
            issues.append(f"{path}: formal file-transfer report missing {check_name} check")
            continue
        if check.get("status") != STATUS_PASS:
            issues.append(f"{path}: formal file-transfer report {check_name}.status must be pass")
        reasons = check.get("reasons", [])
        if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
            issues.append(f"{path}: formal file-transfer report {check_name}.reasons must be a list of strings")
        elif any(reason.strip() for reason in reasons):
            issues.append(f"{path}: formal file-transfer report {check_name}.reasons must be empty")

    source = record.get("source")
    if not isinstance(source, dict):
        issues.append(f"{path}: formal file-transfer report source must be an object")
        return issues
    product_e2e_ref = source.get("product_e2e")
    if not isinstance(product_e2e_ref, str) or not product_e2e_ref.strip():
        issues.append(f"{path}: formal file-transfer report source.product_e2e must be present")
        return issues
    product_path, path_issue = _repo_relative_evidence_path(
        repo_root,
        product_e2e_ref.strip(),
        gate_id=FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID,
    )
    if path_issue is not None or product_path is None:
        issues.append(
            f"{path}: formal file-transfer report source.product_e2e must be a repo-relative path inside repo_root"
        )
        return issues
    if not product_path.exists():
        issues.append(
            f"{path}: formal file-transfer report source.product_e2e {product_e2e_ref.strip()} must exist"
        )
        return issues
    product_record, load_issue = _load_evidence_json(
        product_path,
        product_e2e_ref.strip(),
        gate_id=FILE_TRANSFER_ANDROID_PRODUCT_E2E_GATE_ID,
    )
    if load_issue is not None:
        issues.append(f"{path}: formal file-transfer report source.product_e2e could not be read: {load_issue}")
        return issues
    issues.extend(
        _file_transfer_product_e2e_source_issues(
            product_record,
            f"{path}: source.product_e2e {product_e2e_ref.strip()}",
            evidence_dir=product_path.parent,
        )
    )
    return issues


def _file_transfer_product_e2e_source_issues(
    record: dict[str, Any],
    label: str,
    *,
    evidence_dir: Path | None,
) -> list[str]:
    issues: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{label} schema_version must be {SCHEMA_VERSION}")
    if record.get("kind") != "android_macos_file_transfer_product_e2e":
        issues.append(f"{label} kind must be android_macos_file_transfer_product_e2e")
    if record.get("synthetic") is True or record.get("offline_only") is True:
        issues.append(f"{label} synthetic or offline-only evidence cannot close this gate")
    for field in FILE_TRANSFER_REQUIRED_PRODUCT_CONTEXT_TRUE:
        if record.get(field) is not True:
            issues.append(f"{label} {field} must be true")
    for field in FILE_TRANSFER_REQUIRED_PRODUCT_CONTEXT_FALSE:
        if record.get(field) is not False:
            issues.append(f"{label} {field} must be false")

    directions = record.get("directions")
    if not isinstance(directions, dict):
        issues.append(f"{label} directions must be an object")
        return issues

    transfer_ids: dict[str, str] = {}
    digests: dict[str, str] = {}
    file_names: dict[str, str] = {}
    transports: dict[str, str] = {}
    session_ids: dict[str, str] = {}
    session_epochs: dict[str, int] = {}
    for direction_name, endpoints in FILE_TRANSFER_EXPECTED_DIRECTION_ENDPOINTS.items():
        direction = directions.get(direction_name)
        if not isinstance(direction, dict):
            issues.append(f"{label} missing {direction_name} direction evidence")
            continue
        issues.extend(
            _file_transfer_retained_artifact_issues(
                direction,
                f"{label} {direction_name}",
                FILE_TRANSFER_REQUIRED_DIRECTION_ARTIFACT_ROLES,
                evidence_dir,
            )
        )
        source_endpoint, destination_endpoint = endpoints
        if direction.get("source_endpoint") != source_endpoint:
            issues.append(f"{label} {direction_name}.source_endpoint must be {source_endpoint}")
        if direction.get("destination_endpoint") != destination_endpoint:
            issues.append(f"{label} {direction_name}.destination_endpoint must be {destination_endpoint}")
        transfer_id = direction.get("transfer_id_hex")
        if not isinstance(transfer_id, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", transfer_id):
            issues.append(f"{label} {direction_name}.transfer_id_hex must be a 32-character hex transfer ID")
        else:
            transfer_ids[direction_name] = transfer_id.lower()
        digest = direction.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            issues.append(f"{label} {direction_name}.sha256 must be a 64-character hex SHA-256 digest")
        else:
            digests[direction_name] = digest.lower()
        byte_length = direction.get("byte_length")
        if not _is_positive_integer(byte_length):
            issues.append(f"{label} {direction_name}.byte_length must be a positive integer")
        session_id = direction.get("session_id_hex")
        if not isinstance(session_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{32}", session_id
        ):
            issues.append(
                f"{label} {direction_name}.session_id_hex must be a "
                "32-character hex session ID"
            )
        else:
            session_ids[direction_name] = session_id.lower()
        session_epoch = direction.get("session_epoch")
        if not _is_positive_integer(session_epoch):
            issues.append(f"{label} {direction_name}.session_epoch must be a positive integer")
        else:
            session_epochs[direction_name] = session_epoch
        transport = direction.get("transport")
        if transport not in {"usb", "trusted_lan"}:
            issues.append(f"{label} {direction_name}.transport must be usb or trusted_lan")
        else:
            transports[direction_name] = transport
        file_name = direction.get("file_name")
        if not isinstance(file_name, str) or not file_name.strip():
            issues.append(f"{label} {direction_name}.file_name must be present")
        else:
            file_names[direction_name] = file_name.strip()

    android_to_macos = "android_to_macos_file_transfer"
    macos_to_android = "macos_to_android_file_transfer"
    if transfer_ids.get(android_to_macos) and transfer_ids.get(android_to_macos) == transfer_ids.get(macos_to_android):
        issues.append(f"{label} direction transfer IDs must be distinct")
    if digests.get(android_to_macos) and digests.get(android_to_macos) == digests.get(macos_to_android):
        issues.append(f"{label} direction SHA-256 digests must be distinct")
    if file_names.get(android_to_macos) and file_names.get(android_to_macos) == file_names.get(macos_to_android):
        issues.append(f"{label} direction file names must be distinct")
    if transports.get(android_to_macos) and transports.get(macos_to_android) and transports[android_to_macos] != transports[macos_to_android]:
        issues.append(f"{label} direction transports must match for same-session bidirectional product evidence")
    if (
        session_ids.get(android_to_macos)
        and session_ids.get(macos_to_android)
        and session_ids[android_to_macos] != session_ids[macos_to_android]
    ):
        issues.append(
            f"{label} direction session_id_hex values must match for "
            "same-session bidirectional product evidence"
        )
    if (
        session_epochs.get(android_to_macos)
        and session_epochs.get(macos_to_android)
        and session_epochs[android_to_macos] != session_epochs[macos_to_android]
    ):
        issues.append(f"{label} direction session_epoch values must match for same-session bidirectional product evidence")

    cancel_cleanup = record.get("cancel_cleanup")
    if not isinstance(cancel_cleanup, dict):
        issues.append(f"{label} missing cancel_cleanup evidence")
    else:
        issues.extend(
            _file_transfer_retained_artifact_issues(
                cancel_cleanup,
                f"{label} cancel_cleanup",
                FILE_TRANSFER_REQUIRED_CANCEL_ARTIFACT_ROLES,
                evidence_dir,
            )
        )
        for field in (
            "cancel_requested",
            "cancel_acknowledged",
            "partial_file_removed_or_quarantined",
            "sender_state_cleared",
            "receiver_state_cleared",
        ):
            if cancel_cleanup.get(field) is not True:
                issues.append(f"{label} cancel_cleanup.{field} must be true")
    return issues


def _file_transfer_retained_artifact_issues(
    record: dict[str, Any],
    label: str,
    required_roles: Sequence[str],
    evidence_dir: Path | None,
) -> list[str]:
    return _retained_artifact_issues(record, label, required_roles, evidence_dir)


def _retained_artifact_issues(
    record: dict[str, Any],
    label: str,
    required_roles: Sequence[str],
    evidence_dir: Path | None,
    *,
    expected_direction: str | None = None,
    cross_direction_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> list[str]:
    artifacts = record.get("retained_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return [f"{label}.retained_artifacts must retain product evidence artifacts"]

    issues: list[str] = []
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    required_role_names = set(required_roles)
    resolved_evidence_dir: Path | None = None
    if evidence_dir is not None:
        try:
            resolved_evidence_dir = evidence_dir.resolve()
        except OSError as error:
            return [f"{label}.retained_artifacts evidence directory cannot be read: {error}"]

    for index, artifact in enumerate(artifacts):
        artifact_label = f"{label}.retained_artifacts[{index}]"
        if not isinstance(artifact, dict):
            issues.append(f"{artifact_label} must be an object")
            continue
        role = artifact.get("role")
        role_name: str | None = None
        if not isinstance(role, str) or not role.strip():
            issues.append(f"{artifact_label}.role must be present")
        else:
            role_name = role.strip()
            if role_name not in required_role_names:
                issues.append(f"{artifact_label}.role must be one of {', '.join(required_roles)}")
            elif role_name in seen_roles:
                issues.append(f"{artifact_label}.role duplicates {role_name} artifact")
            seen_roles.add(role_name)

        if expected_direction is not None:
            artifact_direction = artifact.get("direction")
            if artifact_direction != expected_direction:
                issues.append(f"{artifact_label}.direction must be {expected_direction}")

        path_value = artifact.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            issues.append(f"{artifact_label}.path must be present")
            continue
        artifact_path = Path(path_value)
        if artifact_path.is_absolute():
            issues.append(f"{artifact_label}.path must be evidence-relative")
            continue
        if ".." in artifact_path.parts:
            issues.append(f"{artifact_label}.path must stay inside the evidence bundle")
            continue
        normalized_path = artifact_path.as_posix()
        if normalized_path in seen_paths:
            issues.append(f"{artifact_label}.path must be distinct")
        seen_paths.add(normalized_path)
        artifact_key: Path | str | None = normalized_path
        if resolved_evidence_dir is None:
            if cross_direction_artifact_paths is not None and role_name is not None:
                previous_artifact = cross_direction_artifact_paths.get(artifact_key)
                if previous_artifact is not None and previous_artifact[0] != label:
                    previous_label, previous_role = previous_artifact
                    issues.append(
                        f"{artifact_label}.path for {role_name} must be distinct from "
                        f"{previous_label} {previous_role} artifact path"
                    )
                elif previous_artifact is None:
                    cross_direction_artifact_paths[artifact_key] = (label, role_name)
            continue
        try:
            resolved_artifact = (resolved_evidence_dir / artifact_path).resolve(strict=True)
            resolved_artifact.relative_to(resolved_evidence_dir)
        except FileNotFoundError:
            role_suffix = f" for {role_name}" if role_name is not None else ""
            issues.append(f"{artifact_label}.path missing retained artifact{role_suffix} {path_value}")
            continue
        except (OSError, RuntimeError, ValueError) as error:
            issues.append(f"{artifact_label}.path cannot access retained artifact {path_value}: {error}")
            continue
        if not resolved_artifact.is_file():
            issues.append(f"{artifact_label}.path missing retained artifact {path_value}")
            continue
        artifact_key = resolved_artifact
        if cross_direction_artifact_paths is not None and role_name is not None:
            previous_artifact = cross_direction_artifact_paths.get(artifact_key)
            if previous_artifact is not None and previous_artifact[0] != label:
                previous_label, previous_role = previous_artifact
                issues.append(
                    f"{artifact_label}.path for {role_name} must be distinct from "
                    f"{previous_label} {previous_role} artifact path"
                )
            elif previous_artifact is None:
                cross_direction_artifact_paths[artifact_key] = (label, role_name)
        try:
            if resolved_artifact.stat().st_size <= 0:
                issues.append(f"{artifact_label}.path retained artifact {path_value} must be non-empty")
        except OSError as error:
            issues.append(f"{artifact_label}.path cannot stat retained artifact {path_value}: {error}")

    missing_roles = [role for role in required_roles if role not in seen_roles]
    issues.extend(f"{label}.retained_artifacts missing {role} artifact" for role in missing_roles)
    return issues


def _host_rss_2h_no_growth_issues(
    *, evidence_paths: Sequence[str], repo_root: Path | None
) -> list[str]:
    if repo_root is None:
        return [
            "host_rss_2h_no_growth pass requires repo_root to verify "
            "structured evidence paths"
        ]

    valid_host_rss_report = False
    issues: list[str] = []
    candidate_issues: list[str] = []
    repository = repo_root.resolve()
    for raw_path in evidence_paths:
        evidence_path, path_issue = _repo_relative_evidence_path(
            repository,
            raw_path,
            gate_id=HOST_RSS_2H_NO_GROWTH_GATE_ID,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue
        if evidence_path is not None and not evidence_path.exists():
            issues.append(
                f"host_rss_2h_no_growth evidence path {raw_path} must exist"
            )
            continue
        if evidence_path is None or evidence_path.suffix.lower() != ".json":
            continue
        record, load_issue = _load_evidence_json(
            evidence_path,
            raw_path,
            gate_id=HOST_RSS_2H_NO_GROWTH_GATE_ID,
        )
        if load_issue is not None:
            issues.append(load_issue)
            continue
        if record.get("kind") != HOST_RSS_GATE_KIND:
            candidate_issues.append(
                f"{raw_path}: formal Host RSS report kind must be {HOST_RSS_GATE_KIND}"
            )
        else:
            report_issues = _formal_host_rss_report_issues(
                record, raw_path, repo_root=repository
            )
            if report_issues:
                candidate_issues.extend(report_issues)
            else:
                valid_host_rss_report = True

    if not valid_host_rss_report:
        issues.append(
            "host_rss_2h_no_growth pass requires at least one passing formal "
            "host_rss_no_growth_gate report in evidence_paths"
        )
        issues.extend(candidate_issues)
    return issues


def _formal_host_rss_report_issues(
    record: dict[str, Any], path: str, *, repo_root: Path
) -> list[str]:
    issues: list[str] = []
    if record.get("kind") != HOST_RSS_GATE_KIND:
        issues.append(f"{path}: formal Host RSS report kind must be {HOST_RSS_GATE_KIND}")
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"{path}: formal Host RSS report schema_version must be {SCHEMA_VERSION}")
    if record.get("derivation_status") != "complete":
        issues.append(f"{path}: formal Host RSS report derivation_status must be complete")
    if record.get("verdict") != STATUS_PASS:
        issues.append(f"{path}: formal Host RSS report verdict must be pass")

    window = record.get("window")
    if not isinstance(window, dict):
        issues.append(f"{path}: formal Host RSS report window must be an object")
    else:
        duration_seconds = window.get("duration_seconds")
        elapsed_span_seconds = window.get("elapsed_span_seconds")
        sample_count = window.get("host_rss_sample_count")
        if (
            not _is_non_negative_number(duration_seconds)
            or duration_seconds < HOST_RSS_MINIMUM_DURATION_SECONDS
        ):
            issues.append(
                f"{path}: formal Host RSS report window.duration_seconds must be at least {HOST_RSS_MINIMUM_DURATION_SECONDS:g}"
            )
        if (
            not _is_non_negative_number(elapsed_span_seconds)
            or elapsed_span_seconds < HOST_RSS_MINIMUM_DURATION_SECONDS
        ):
            issues.append(
                f"{path}: formal Host RSS report window.elapsed_span_seconds must be at least {HOST_RSS_MINIMUM_DURATION_SECONDS:g}"
            )
        if (
            not _is_positive_integer(sample_count)
            or sample_count < HOST_RSS_MINIMUM_SAMPLE_COUNT
        ):
            issues.append(
                f"{path}: formal Host RSS report window.host_rss_sample_count must be at least {HOST_RSS_MINIMUM_SAMPLE_COUNT}"
            )

    source_summary = record.get("source_summary")
    if not isinstance(source_summary, dict):
        issues.append(f"{path}: formal Host RSS report source_summary must be an object")
    else:
        if source_summary.get("status") != "complete":
            issues.append(f"{path}: formal Host RSS report source_summary.status must be complete")
        error_count = source_summary.get("error_count")
        if not _is_non_negative_integer(error_count) or error_count != 0:
            issues.append(f"{path}: formal Host RSS report source_summary.error_count must be 0")
        source_errors = source_summary.get("errors", [])
        if not isinstance(source_errors, list) or any(
            not isinstance(error, str) for error in source_errors
        ):
            issues.append(
                f"{path}: formal Host RSS report source_summary.errors must be a list of strings"
            )
        elif any(error.strip() for error in source_errors):
            issues.append(f"{path}: formal Host RSS report source_summary.errors must be empty")

    for section_name in (
        "sufficiency",
        "criteria",
        "telemetry_sufficiency",
        "telemetry_criteria",
        "host_readiness_sufficiency",
        "host_readiness_criteria",
    ):
        issues.extend(_all_gate_section_checks_pass(record, path, section_name))

    reasons = record.get("reasons", [])
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        issues.append(f"{path}: formal Host RSS report reasons must be a list of strings")
    elif any(reason.strip() for reason in reasons):
        issues.append(f"{path}: formal Host RSS report pass must not include unresolved reasons")

    source = record.get("source")
    if not isinstance(source, dict):
        issues.append(f"{path}: formal Host RSS report source must be an object")
        return issues

    source_paths: dict[str, Path] = {}
    for field in ("summary", "samples", "exact_window_report", "host_readiness"):
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"{path}: formal Host RSS report source.{field} must be present")
            continue
        source_path, path_issue = _repo_relative_evidence_path(
            repo_root,
            value.strip(),
            gate_id=HOST_RSS_2H_NO_GROWTH_GATE_ID,
        )
        if path_issue is not None or source_path is None:
            issues.append(
                f"{path}: formal Host RSS report source.{field} must be a repo-relative path inside repo_root"
            )
            continue
        if not source_path.exists():
            issues.append(
                f"{path}: formal Host RSS report source.{field} {value.strip()} must exist"
            )
            continue
        source_paths[field] = source_path

    if set(source_paths) == {"summary", "samples", "exact_window_report", "host_readiness"}:
        try:
            rebuilt_report = derive_host_rss_gate(
                source_paths["summary"],
                source_paths["samples"],
                source_paths["exact_window_report"],
                source_paths["host_readiness"],
            )
        except (EvidenceInputError, OSError, TypeError, ValueError) as error:
            issues.append(
                f"{path}: formal Host RSS report source inputs could not be revalidated: {error}"
            )
        else:
            if rebuilt_report.get("verdict") != STATUS_PASS:
                rebuilt_reasons = rebuilt_report.get("reasons", [])
                detail = "; ".join(
                    str(reason)
                    for reason in rebuilt_reasons
                    if str(reason).strip()
                )
                suffix = f": {detail}" if detail else ""
                issues.append(
                    f"{path}: formal Host RSS report source inputs must rederive as a passing host_rss_gate report{suffix}"
                )
    return issues


def _all_gate_section_checks_pass(
    record: dict[str, Any], path: str, section_name: str
) -> list[str]:
    section = record.get(section_name)
    if not isinstance(section, dict) or not section:
        return [f"{path}: formal Host RSS report {section_name} must be a non-empty object"]
    failing = [
        name
        for name, item in section.items()
        if not isinstance(item, dict) or item.get("passed") is not True
    ]
    if failing:
        return [
            f"{path}: formal Host RSS report {section_name} must have all checks passed: "
            + ", ".join(failing)
        ]
    return []


def _formal_latency_report_issues(
    record: dict[str, Any], path: str, *, repo_root: Path
) -> list[str]:
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
    gate_profile = gate.get("profile")
    if not isinstance(gate_profile, str) or gate_profile not in GATE_PROFILES:
        issues.append(f"{path}: formal latency report gate.profile must be a known latency profile")
    else:
        expected_kind = GATE_PROFILES[gate_profile]["kind"]
        if record.get("latency_kind") != expected_kind:
            issues.append(
                f"{path}: formal latency report latency_kind must match "
                f"gate.profile kind {expected_kind}"
            )
        if measurement_method == "synchronized-clock" and expected_kind != "input":
            issues.append(
                f"{path}: synchronized-clock latency report must use an input "
                "latency gate profile"
            )
    if gate.get("can_close_performance_gate") is not True:
        issues.append(
            f"{path}: formal latency report gate.can_close_performance_gate "
            "must be true"
        )
    if gate.get("requires_external_hardware") is not True:
        issues.append(
            f"{path}: formal latency report gate.requires_external_hardware "
            "must be true"
        )
    if gate.get("summary_verdict") != STATUS_PASS:
        issues.append(f"{path}: formal latency report gate.summary_verdict must be pass")
    threshold_ms = gate.get("threshold_ms")
    observed_with_uncertainty_ms = gate.get("observed_with_uncertainty_ms")
    if not _is_non_negative_number(threshold_ms):
        issues.append(
            f"{path}: formal latency report gate.threshold_ms must be a finite non-negative number"
        )
    if not _is_non_negative_number(observed_with_uncertainty_ms):
        issues.append(
            f"{path}: formal latency report gate.observed_with_uncertainty_ms must be a finite non-negative number"
        )
    elif _is_non_negative_number(threshold_ms) and observed_with_uncertainty_ms > threshold_ms:
        issues.append(
            f"{path}: formal latency report gate.observed_with_uncertainty_ms must not exceed gate.threshold_ms"
        )
    sample_count = gate.get("sample_count")
    min_sample_count = gate.get("min_sample_count")
    if (
        not _is_positive_integer(sample_count)
        or not _is_positive_integer(min_sample_count)
        or min_sample_count != MIN_GATE_SAMPLE_COUNT
        or sample_count < MIN_GATE_SAMPLE_COUNT
        or sample_count < min_sample_count
    ):
        issues.append(
            f"{path}: formal latency report min_sample_count must equal "
            f"{MIN_GATE_SAMPLE_COUNT} and sample_count must be at least "
            f"{MIN_GATE_SAMPLE_COUNT}"
        )
    source = record.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("manifest"), str)
        or not source.get("manifest", "").strip()
    ):
        issues.append(f"{path}: formal latency report source.manifest must be present")
    elif isinstance(gate_profile, str) and gate_profile in GATE_PROFILES:
        manifest_ref = source["manifest"].strip()
        manifest_path, path_issue = _repo_relative_evidence_path(repo_root, manifest_ref)
        if path_issue is not None or manifest_path is None:
            issues.append(
                f"{path}: formal latency report source.manifest must be a repo-relative path inside repo_root"
            )
        elif not manifest_path.exists():
            issues.append(
                f"{path}: formal latency report source.manifest {manifest_ref} must exist"
            )
        else:
            try:
                rebuilt_report = build_latency_evidence_report(
                    manifest_path=manifest_path,
                    gate_profile=gate_profile,
                )
            except LatencyEvidenceError as error:
                issues.append(
                    f"{path}: formal latency report source.manifest could not be revalidated: {error}"
                )
            else:
                rebuilt_gate = rebuilt_report.get("gate")
                if (
                    rebuilt_report.get("verdict") != STATUS_PASS
                    or not isinstance(rebuilt_gate, dict)
                    or rebuilt_gate.get("can_close_performance_gate") is not True
                ):
                    rebuilt_reasons = (
                        rebuilt_gate.get("reasons", [])
                        if isinstance(rebuilt_gate, dict)
                        else []
                    )
                    detail = "; ".join(
                        str(reason) for reason in rebuilt_reasons if str(reason).strip()
                    )
                    suffix = f": {detail}" if detail else ""
                    issues.append(
                        f"{path}: formal latency report source.manifest must revalidate "
                        "as a passing latency evidence package with retained raw "
                        "external-camera media or synchronized-clock physical-input "
                        f"proof{suffix}"
                    )
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
    issues.extend(_android_usb_live_smoke_device_issues(record, path))
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


def _android_usb_live_smoke_device_issues(
    record: dict[str, Any], path: str
) -> list[str]:
    device = record.get("device")
    if not isinstance(device, dict):
        return [f"{path}: Android USB live smoke device must be an object"]
    identity = device.get("identity")
    if not isinstance(identity, dict):
        return [f"{path}: Android USB live smoke device.identity must be an object"]
    missing_fields = [
        field
        for field in ("manufacturer", "model", "device")
        if not isinstance(identity.get(field), str) or not identity.get(field, "").strip()
    ]
    if missing_fields:
        return [
            f"{path}: Android USB live smoke device.identity must include non-empty "
            + ", ".join(missing_fields)
        ]
    return []


def _extend_android_telemetry_issues(
    issues: list[str], telemetry: dict[str, Any], path: str
) -> None:
    session_epochs = telemetry.get("session_epochs")
    if (
        not isinstance(session_epochs, list)
        or not session_epochs
        or not all(_is_non_negative_integer(item) for item in session_epochs)
    ):
        issues.append(
            f"{path}: Android USB live smoke telemetry must include integer session_epochs"
        )
    stream_stats = telemetry.get("stream_stats")
    if not isinstance(stream_stats, dict):
        issues.append(
            f"{path}: Android USB live smoke telemetry.stream_stats must be an object"
        )
        return
    stream_stats_count = stream_stats.get("count")
    positive_fps_count = stream_stats.get("positive_fps_count")
    if not _is_positive_integer(stream_stats_count):
        issues.append(
            f"{path}: Android USB live smoke telemetry.stream_stats.count must be a positive integer"
        )
    if not _is_positive_integer(positive_fps_count):
        issues.append(
            f"{path}: Android USB live smoke telemetry must include positive integer FPS stream_stats"
        )
    elif _is_positive_integer(stream_stats_count) and positive_fps_count > stream_stats_count:
        issues.append(
            f"{path}: Android USB live smoke telemetry.stream_stats.positive_fps_count must not exceed stream_stats.count"
        )
    frame_drops = telemetry.get("frame_drops")
    latest = stream_stats.get("latest")
    has_frame_drop_summary = False
    if isinstance(frame_drops, dict) and "max_dropped_total" in frame_drops:
        has_frame_drop_summary = _is_non_negative_integer(
            frame_drops.get("max_dropped_total")
        )
        if not has_frame_drop_summary:
            issues.append(
                f"{path}: Android USB live smoke telemetry.frame_drops.max_dropped_total must be a non-negative integer"
            )
    has_latest_dropped_frames = False
    if isinstance(latest, dict) and "dropped_frames" in latest:
        has_latest_dropped_frames = _is_non_negative_integer(
            latest.get("dropped_frames")
        )
        if not has_latest_dropped_frames:
            issues.append(
                f"{path}: Android USB live smoke telemetry.stream_stats.latest.dropped_frames must be a non-negative integer"
            )
    if not has_frame_drop_summary and not has_latest_dropped_frames:
        issues.append(
            f"{path}: Android USB live smoke telemetry must include frame-drop counters"
        )


def _extend_android_decoder_issues(
    issues: list[str], decoder: dict[str, Any], path: str
) -> None:
    decode_stats = decoder.get("latest_decode_stats")
    has_output_counter = False
    if "latest_output_counter" in decoder:
        has_output_counter = _is_positive_integer(decoder.get("latest_output_counter"))
        if not has_output_counter:
            issues.append(
                f"{path}: Android USB live smoke decoder.latest_output_counter must be a positive integer"
            )
    has_decode_stats = False
    if "latest_decode_stats" in decoder:
        has_decode_stats = (
            isinstance(decode_stats, dict)
            and any(_is_positive_integer(value) for value in decode_stats.values())
        )
        if not has_decode_stats:
            issues.append(
                f"{path}: Android USB live smoke decoder.latest_decode_stats must include a positive integer counter"
            )
    if not has_output_counter and not has_decode_stats:
        issues.append(
            f"{path}: Android USB live smoke decoder counters must be present"
        )
    latency = decoder.get("latest_output_latency")
    if (
        not isinstance(latency, dict)
        or not _is_non_negative_number(latency.get("avg_ms"))
        or not _is_non_negative_number(latency.get("max_ms"))
    ):
        issues.append(
            f"{path}: Android USB live smoke decoder latency metrics must be present"
        )
    elif latency["avg_ms"] > latency["max_ms"]:
        issues.append(
            f"{path}: Android USB live smoke decoder latest_output_latency.avg_ms must not exceed max_ms"
        )


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _is_non_negative_number(value: Any) -> bool:
    return _is_number(value) and value >= 0


def _is_non_negative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


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
    except (OSError, UnicodeDecodeError) as error:
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
        summary = _gate_summary(
            raw_gate,
            repo_root=repo_root,
            manifest_source_commit=(
                source.get("base_commit") if isinstance(source.get("base_commit"), str) else None
            ),
        )
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
