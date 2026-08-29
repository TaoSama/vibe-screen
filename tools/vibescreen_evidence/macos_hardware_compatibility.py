"""Summarize macOS Host hardware compatibility matrix-row evidence.

The gate validates an already-collected evidence summary. It does not launch the
Host, change macOS display settings, touch TCC, or infer support for hardware
or OS rows that were not explicitly recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "macos-host-compatibility-row"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAILED = "failed"
CPU_ARCHITECTURES = frozenset(("apple_silicon", "intel"))
DISPLAY_TOPOLOGIES = frozenset((
    "built_in",
    "single_external",
    "multi_display",
    "dummy_or_headless",
    "screen_sharing",
))
TRANSPORTS = frozenset(("usb", "lan"))
CAPTURE_BACKENDS = frozenset((
    "screencapturekit",
    "cgdisplaystream_fallback",
    "current_main_fallback",
    "unavailable",
))
SCREEN_CAPTUREKIT_RESULTS = frozenset((
    "selected_display_first_frame",
    "unavailable_fallback_used",
    "unavailable_terminal",
))
CGDISPLAYSTREAM_RESULTS = frozenset((
    "fallback_first_frame",
    "not_used",
    "unavailable_terminal",
))
VIRTUAL_DISPLAY_RESULTS = frozenset((
    "created_online_captured",
    "fallback_current_main",
    "unavailable",
    "not_applicable",
))
MIRROR_RESULTS = frozenset((
    "hardware_mirror",
    "current_main_fallback",
    "unavailable",
    "not_applicable",
))
VIDEOTOOLBOX_RESULTS = frozenset((
    "h264_hevc_available",
    "h264_only",
    "hevc_only",
    "unavailable",
))
REPOSITORY_DIRTY_STATES = frozenset(("clean", "dirty"))
TCC_STATES = frozenset(("authorized", "not_authorized", "unverified"))
EXPECTED_HOST_BUNDLE_ID = "dev.telemachus.display"
COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

REQUIRED_FIELDS = (
    ("owner_recorded", "record the macOS Host compatibility gate owner for this row"),
    ("implementation_path_recorded", "record the implementation path or follow-up path for this matrix row"),
    ("repository_commit_recorded", "record the repository commit and dirty state used for the run"),
    ("host_model_recorded", "record the exact Mac model identifier and marketing family when available"),
    ("cpu_architecture_recorded", "record whether the Host is Apple silicon or Intel"),
    ("macos_version_build_recorded", "record macOS product version and build number"),
    ("xcode_swift_recorded", "record Xcode and Swift versions used for local build/test evidence"),
    ("host_build_identity_recorded", "record Host app commit, binary SHA-256, bundle id, and signing identity"),
    ("signing_and_tcc_state_recorded", "record signing stability plus Screen Recording and Accessibility state"),
    ("source_bound_host_recorded", "record installed Host source commit/tree provenance and require it to match this current-base row"),
    ("host_self_test_provenance_recorded", "record Host self-test provenance from the same current-base source revision"),
    ("display_topology_recorded", "record built-in, external, multi-display, dummy/headless, or Screen Sharing topology"),
    ("capture_backend_recorded", "record ScreenCaptureKit, CGDisplayStream fallback, or explicit unavailable result"),
    ("video_encoder_path_recorded", "record VideoToolbox H.264/HEVC capability or explicit unavailable result"),
    ("automated_macos_checks_passed", "run baseline macOS build, XCTest, and self-test commands for this source"),
    ("packaged_host_launch_observed", "launch the packaged Host on the recorded Mac row"),
    ("protocol_v1_stream_observed", "observe a Protocol v1 USB or trusted-LAN stream on this Host row"),
    ("display_selection_observed", "exercise display list and selected-display start on this Host row"),
    ("physical_display_capture_observed", "observe physical or current-main display capture on this Host row"),
    ("virtual_display_or_fallback_recorded", "record private virtual-display create/capture success or explicit fallback/unavailable behavior"),
    ("mirror_or_fallback_recorded", "record mirror success or explicit current-main fallback/unavailable behavior"),
    ("input_smoke_observed", "observe at least touch plus keyboard or scroll input through the Host path"),
    ("reconnect_observed", "observe a client/process reconnect while the Host PID survives"),
    ("artifacts_retained", "retain logs, screenshots, display snapshots, command output, and the gate summary"),
    ("claim_scoped_to_exact_row", "scope the support claim to this exact architecture, Mac model, OS build, topology, transport, and Android counterpart"),
)

BLOCKING_FIELDS = frozenset((
    "owner_recorded",
    "implementation_path_recorded",
    "repository_commit_recorded",
    "host_model_recorded",
    "cpu_architecture_recorded",
    "macos_version_build_recorded",
    "host_build_identity_recorded",
    "signing_and_tcc_state_recorded",
    "display_topology_recorded",
    "automated_macos_checks_passed",
    "packaged_host_launch_observed",
    "protocol_v1_stream_observed",
    "source_bound_host_recorded",
    "host_self_test_provenance_recorded",
    "artifacts_retained",
    "claim_scoped_to_exact_row",
))

INVALID_CLAIM_FIELDS = (
    ("ci_runner_only", "CI runner build/test output cannot close a real Host hardware compatibility row"),
    ("claims_intel_from_apple_silicon", "Intel compatibility cannot be inferred from Apple silicon evidence"),
    ("claims_os_range_from_single_build", "a single macOS build cannot prove the whole macOS 13+ range"),
    ("claims_display_topology_from_different_setup", "display topology claims cannot be inferred from another monitor/dummy/headless setup"),
    ("claims_screencapturekit_from_cgdisplaystream", "ScreenCaptureKit compatibility cannot be inferred from a CGDisplayStream fallback run"),
    ("claims_virtual_display_without_result", "private virtual-display support needs a success result or explicit fallback/unavailable result"),
    ("claims_virtual_display_from_symbol_probe", "runtime symbol presence is diagnostic only and cannot prove CGVirtualDisplay create/apply/online/capture behavior"),
    ("claims_virtual_display_from_current_main_fallback", "current-main fallback evidence cannot be reported as private virtual-display support"),
    ("claims_dummy_headless_from_attached_monitor", "dummy/headless compatibility cannot be inferred from an attached-monitor run"),
)

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
INVALID_BOOLEAN_FIELDS = tuple(field for field, _ in INVALID_CLAIM_FIELDS)
REQUIRED_METADATA_FIELDS = (
    ("owner", "owner_recorded", "record a non-empty macOS Host compatibility gate owner"),
    ("implementation_path", "implementation_path_recorded", "record a non-empty implementation path or follow-up path"),
    ("repository_commit", "repository_commit_recorded", "record the exact repository commit used for the row"),
    ("repository_dirty_state", "repository_commit_recorded", "record whether the repository was clean or dirty"),
    ("host_model_identifier", "host_model_recorded", "record a non-empty Mac model identifier"),
    ("cpu_architecture", "cpu_architecture_recorded", "record apple_silicon or intel CPU architecture"),
    ("macos_version", "macos_version_build_recorded", "record a non-empty macOS product version"),
    ("macos_build", "macos_version_build_recorded", "record a non-empty macOS build number"),
    ("xcode_version", "xcode_swift_recorded", "record a non-empty Xcode version"),
    ("swift_version", "xcode_swift_recorded", "record a non-empty Swift version"),
    ("host_build_identity", "host_build_identity_recorded", "record a non-empty Host build identity"),
    ("host_bundle_id", "host_build_identity_recorded", "record the packaged Host bundle identifier"),
    ("host_signing_identity", "host_build_identity_recorded", "record the concrete non-ad-hoc Host signing identity"),
    ("screen_recording_tcc", "signing_and_tcc_state_recorded", "record Screen Recording TCC authorization state for the packaged Host"),
    ("accessibility_tcc", "signing_and_tcc_state_recorded", "record Accessibility TCC authorization state for the packaged Host"),
    ("host_source_commit", "source_bound_host_recorded", "record the source commit embedded in the installed Host bundle"),
    ("host_source_tree", "source_bound_host_recorded", "record the source tree embedded in the installed Host bundle"),
    ("host_source_dirty_state", "source_bound_host_recorded", "record whether the installed Host was packaged from a clean source tree"),
    ("host_self_test_commit", "host_self_test_provenance_recorded", "record the commit used for Host self-test output"),
    ("current_base_commit", "host_self_test_provenance_recorded", "record the origin/main commit used as the current-base comparison point"),
    ("display_topology", "display_topology_recorded", "record a concrete display topology"),
    ("capture_backend", "capture_backend_recorded", "record a non-empty capture backend or unavailable result"),
    ("screen_capturekit_result", "capture_backend_recorded", "record ScreenCaptureKit first-frame, fallback, or terminal-unavailable result"),
    ("cgdisplaystream_result", "capture_backend_recorded", "record CGDisplayStream fallback first-frame, not-used, or terminal-unavailable result"),
    ("videotoolbox_result", "video_encoder_path_recorded", "record VideoToolbox H.264/HEVC availability or unavailable result"),
    ("virtual_display_result", "virtual_display_or_fallback_recorded", "record CGVirtualDisplay create/apply/online/capture success or explicit fallback/unavailable result"),
    ("mirror_result", "mirror_or_fallback_recorded", "record hardware mirror success or explicit current-main fallback/unavailable result"),
    ("stream_transport", "protocol_v1_stream_observed", "record a non-empty stream transport"),
    ("android_counterpart", "protocol_v1_stream_observed", "record the Android counterpart used for the stream"),
    ("compatibility_scope", "claim_scoped_to_exact_row", "record a non-empty exact-row compatibility scope"),
)

CLOSURE_CHECKLIST_GROUPS = (
    (
        "source_and_host_identity",
        "Source and Host identity",
        (
            "owner_recorded",
            "implementation_path_recorded",
            "repository_commit_recorded",
            "host_model_recorded",
            "cpu_architecture_recorded",
            "macos_version_build_recorded",
            "xcode_swift_recorded",
            "host_build_identity_recorded",
            "signing_and_tcc_state_recorded",
            "source_bound_host_recorded",
            "host_self_test_provenance_recorded",
        ),
    ),
    (
        "display_and_encoder_capability",
        "Display and encoder capability",
        (
            "display_topology_recorded",
            "capture_backend_recorded",
            "video_encoder_path_recorded",
            "virtual_display_or_fallback_recorded",
            "mirror_or_fallback_recorded",
        ),
    ),
    (
        "runtime_acceptance",
        "Runtime acceptance",
        (
            "automated_macos_checks_passed",
            "packaged_host_launch_observed",
            "protocol_v1_stream_observed",
            "display_selection_observed",
            "physical_display_capture_observed",
            "input_smoke_observed",
            "reconnect_observed",
        ),
    ),
    (
        "scope_and_artifacts",
        "Scope and retained artifacts",
        (
            "artifacts_retained",
            "claim_scoped_to_exact_row",
        ),
    ),
)


class MacOSHardwareCompatibilityError(ValueError):
    """Raised when a compatibility evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise MacOSHardwareCompatibilityError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise MacOSHardwareCompatibilityError(
            "macOS hardware compatibility evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise MacOSHardwareCompatibilityError(f"{field} must be true or false")


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise MacOSHardwareCompatibilityError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise MacOSHardwareCompatibilityError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip():
        return value
    raise MacOSHardwareCompatibilityError("run_id must be a non-empty string")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MacOSHardwareCompatibilityError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise MacOSHardwareCompatibilityError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _cpu_architecture(record: dict[str, Any]) -> str:
    value = _string_value(record, "cpu_architecture")
    if value and value not in CPU_ARCHITECTURES:
        raise MacOSHardwareCompatibilityError(
            f"cpu_architecture must be one of {sorted(CPU_ARCHITECTURES)}"
        )
    return value


def _display_topology(record: dict[str, Any]) -> str:
    value = _string_value(record, "display_topology")
    if value and value not in DISPLAY_TOPOLOGIES:
        raise MacOSHardwareCompatibilityError(
            f"display_topology must be one of {sorted(DISPLAY_TOPOLOGIES)}"
        )
    return value


def _enum_value(record: dict[str, Any], field: str, allowed: frozenset[str]) -> str:
    value = _string_value(record, field)
    if value and value not in allowed:
        raise MacOSHardwareCompatibilityError(
            f"{field} must be one of {sorted(allowed)}"
        )
    return value


def _full_sha_or_missing(
    missing: list[dict[str, str]], field: str, observation_field: str, value: str
) -> None:
    if value and COMMIT_SHA_RE.fullmatch(value) is None:
        _append_missing_once(
            missing,
            observation_field,
            f"record {field} as a 40-character hexadecimal git commit",
        )


def _artifact_path_report(
    artifact_paths: Sequence[str], evidence_dir: Path | None
) -> dict[str, Any]:
    if evidence_dir is None:
        return {
            "enabled": False,
            "evidence_dir": "",
            "missing_paths": [],
            "invalid_paths": [],
            "empty_paths": [],
        }

    reported_evidence_dir = str(evidence_dir)
    resolved_evidence_dir = evidence_dir.resolve()
    missing_paths: list[str] = []
    invalid_paths: list[str] = []
    empty_paths: list[str] = []
    for artifact_path in artifact_paths:
        path = Path(artifact_path)
        if path.is_absolute():
            invalid_paths.append(artifact_path)
            continue
        resolved_path = (resolved_evidence_dir / path).resolve()
        try:
            resolved_path.relative_to(resolved_evidence_dir)
        except ValueError:
            invalid_paths.append(artifact_path)
            continue
        if not resolved_path.exists():
            missing_paths.append(artifact_path)
        elif resolved_path.is_file() and resolved_path.stat().st_size == 0:
            empty_paths.append(artifact_path)
        elif resolved_path.is_dir() and not any(resolved_path.iterdir()):
            empty_paths.append(artifact_path)
    return {
        "enabled": True,
        "evidence_dir": reported_evidence_dir,
        "missing_paths": missing_paths,
        "invalid_paths": invalid_paths,
        "empty_paths": empty_paths,
    }


def _capture_backend_failures(record: dict[str, Any]) -> list[dict[str, str]]:
    capture_backend = _enum_value(record, "capture_backend", CAPTURE_BACKENDS)
    screen_capturekit_result = _enum_value(
        record, "screen_capturekit_result", SCREEN_CAPTUREKIT_RESULTS
    )
    cgdisplaystream_result = _enum_value(
        record, "cgdisplaystream_result", CGDISPLAYSTREAM_RESULTS
    )
    virtual_display_result = _enum_value(
        record, "virtual_display_result", VIRTUAL_DISPLAY_RESULTS
    )
    mirror_result = _enum_value(record, "mirror_result", MIRROR_RESULTS)
    failures: list[dict[str, str]] = []

    def add(reason: str) -> None:
        failures.append({"field": "capture_backend_consistency", "reason": reason})

    if capture_backend == "screencapturekit":
        if screen_capturekit_result != "selected_display_first_frame":
            add("ScreenCaptureKit backend requires selected-display first-frame evidence")
        if cgdisplaystream_result != "not_used":
            add("ScreenCaptureKit backend cannot also report CGDisplayStream fallback use")
    elif capture_backend == "cgdisplaystream_fallback":
        if screen_capturekit_result != "unavailable_fallback_used":
            add("CGDisplayStream fallback requires ScreenCaptureKit fallback evidence")
        if cgdisplaystream_result != "fallback_first_frame":
            add("CGDisplayStream fallback requires fallback first-frame evidence")
    elif capture_backend == "current_main_fallback":
        if screen_capturekit_result != "selected_display_first_frame":
            add("current-main fallback requires first-frame capture of the fallback display")
        if cgdisplaystream_result == "fallback_first_frame":
            add("current-main fallback cannot also report CGDisplayStream fallback use")
        if (
            virtual_display_result != "fallback_current_main"
            and mirror_result != "current_main_fallback"
        ):
            add("current-main fallback must be tied to virtual-display or mirror fallback evidence")
    elif capture_backend == "unavailable":
        if screen_capturekit_result == "selected_display_first_frame":
            add("unavailable capture backend cannot report a ScreenCaptureKit first frame")
        if cgdisplaystream_result == "fallback_first_frame":
            add("unavailable capture backend cannot report a CGDisplayStream first frame")
    return failures


def _append_missing_once(
    missing: list[dict[str, str]], field: str, requirement: str
) -> None:
    if not any(
        item["field"] == field and item["requirement"] == requirement
        for item in missing
    ):
        missing.append({"field": field, "requirement": requirement})


def _closure_checklist(
    *,
    missing: Sequence[dict[str, str]],
    invalid_claims: Sequence[dict[str, str]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for checklist_id, title, fields in CLOSURE_CHECKLIST_GROUPS:
        missing_for_group = [item for item in missing if item["field"] in fields]
        if any(item["field"] in BLOCKING_FIELDS for item in missing_for_group):
            status = STATUS_BLOCKED
        elif missing_for_group:
            status = STATUS_INSUFFICIENT
        else:
            status = STATUS_PASS
        items.append({
            "id": checklist_id,
            "title": title,
            "status": status,
            "missing_fields": sorted({item["field"] for item in missing_for_group}),
            "next_steps": [item["requirement"] for item in missing_for_group],
        })

    items.append({
        "id": "extrapolation_guard",
        "title": "No extrapolated support claims",
        "status": STATUS_FAILED if invalid_claims else STATUS_PASS,
        "missing_fields": [item["field"] for item in invalid_claims],
        "next_steps": [item["reason"] for item in invalid_claims],
    })
    return items


def summarize(
    record: dict[str, Any], *, run_id: str | None = None, evidence_dir: Path | None = None
) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    invalid_claim_values = {
        field: _bool_value(record, field) for field in INVALID_BOOLEAN_FIELDS
    }
    artifact_paths = _string_list(record, "artifact_paths")
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    for metadata_field, observation_field, requirement in REQUIRED_METADATA_FIELDS:
        if not _string_value(record, metadata_field).strip():
            _append_missing_once(missing, observation_field, requirement)
    repository_commit = _string_value(record, "repository_commit")
    host_source_commit = _string_value(record, "host_source_commit")
    host_source_tree = _string_value(record, "host_source_tree")
    host_self_test_commit = _string_value(record, "host_self_test_commit")
    current_base_commit = _string_value(record, "current_base_commit")
    repository_dirty_state = _enum_value(
        record, "repository_dirty_state", REPOSITORY_DIRTY_STATES
    )
    host_source_dirty_state = _enum_value(
        record, "host_source_dirty_state", REPOSITORY_DIRTY_STATES
    )
    if repository_commit and COMMIT_SHA_RE.fullmatch(repository_commit) is None:
        _append_missing_once(
            missing,
            "repository_commit_recorded",
            "record repository_commit as a 40-character hexadecimal git commit",
        )
    _full_sha_or_missing(missing, "host_source_commit", "source_bound_host_recorded", host_source_commit)
    _full_sha_or_missing(missing, "host_source_tree", "source_bound_host_recorded", host_source_tree)
    _full_sha_or_missing(missing, "host_self_test_commit", "host_self_test_provenance_recorded", host_self_test_commit)
    _full_sha_or_missing(missing, "current_base_commit", "host_self_test_provenance_recorded", current_base_commit)
    if repository_dirty_state == "dirty":
        _append_missing_once(
            missing,
            "repository_commit_recorded",
            "rerun the compatibility row from a clean repository state before closing it",
        )
    if host_source_dirty_state == "dirty":
        _append_missing_once(
            missing,
            "source_bound_host_recorded",
            "rebuild and install the Host from a clean source tree before closing the row",
        )
    if host_source_commit and repository_commit and host_source_commit != repository_commit:
        _append_missing_once(
            missing,
            "source_bound_host_recorded",
            "installed Host source commit must match repository_commit for this row",
        )
    if host_self_test_commit and repository_commit and host_self_test_commit != repository_commit:
        _append_missing_once(
            missing,
            "host_self_test_provenance_recorded",
            "Host self-test commit must match repository_commit for this row",
        )
    if current_base_commit and repository_commit and current_base_commit != repository_commit:
        _append_missing_once(
            missing,
            "host_self_test_provenance_recorded",
            "current_base_commit must match repository_commit for this current-base row",
        )
    host_bundle_id = _string_value(record, "host_bundle_id")
    if host_bundle_id and host_bundle_id != EXPECTED_HOST_BUNDLE_ID:
        _append_missing_once(
            missing,
            "host_build_identity_recorded",
            f"Host bundle id must be {EXPECTED_HOST_BUNDLE_ID}",
        )
    host_signing_identity = _string_value(record, "host_signing_identity").strip().lower()
    if host_signing_identity in {"-", "ad-hoc", "adhoc"}:
        _append_missing_once(
            missing,
            "host_build_identity_recorded",
            "Host signing identity must be a stable non-ad-hoc identity",
        )
    screen_recording_tcc = _enum_value(record, "screen_recording_tcc", TCC_STATES)
    accessibility_tcc = _enum_value(record, "accessibility_tcc", TCC_STATES)
    if screen_recording_tcc and screen_recording_tcc != "authorized":
        _append_missing_once(
            missing,
            "signing_and_tcc_state_recorded",
            "Screen Recording TCC must be authorized for the packaged Host",
        )
    if accessibility_tcc and accessibility_tcc != "authorized":
        _append_missing_once(
            missing,
            "signing_and_tcc_state_recorded",
            "Accessibility TCC must be authorized for the packaged Host",
        )
    if field_values["artifacts_retained"] and not artifact_paths:
        _append_missing_once(
            missing,
            "artifacts_retained",
            "record at least one retained artifact path for this compatibility row",
        )
    artifact_file_check = _artifact_path_report(artifact_paths, evidence_dir)
    if field_values["artifacts_retained"] and not artifact_file_check["enabled"]:
        _append_missing_once(
            missing,
            "artifacts_retained",
            "provide --evidence-dir or a file input so retained artifacts can be verified",
        )
    if (
        field_values["artifacts_retained"]
        and artifact_file_check["enabled"]
        and (
            artifact_file_check["missing_paths"]
            or artifact_file_check["invalid_paths"]
            or artifact_file_check["empty_paths"]
        )
    ):
        _append_missing_once(
            missing,
            "artifacts_retained",
            "retain artifact paths as existing relative files inside the evidence directory",
        )
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    invalid_claims = [
        {"field": field, "reason": reason}
        for field, reason in INVALID_CLAIM_FIELDS
        if invalid_claim_values[field]
    ]
    invalid_claims.extend(_capture_backend_failures(record))

    if invalid_claims:
        verdict = STATUS_FAILED
    elif not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "macos_host_compatibility_matrix_row",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_macos_host_compatibility_row": verdict == STATUS_PASS,
        "row_scope": {
            "owner": _string_value(record, "owner"),
            "implementation_path": _string_value(record, "implementation_path"),
            "repository_commit": repository_commit,
            "repository_dirty_state": repository_dirty_state,
            "cpu_architecture": _cpu_architecture(record),
            "host_model_identifier": _string_value(record, "host_model_identifier"),
            "host_cpu_name": _string_value(record, "host_cpu_name"),
            "macos_version": _string_value(record, "macos_version"),
            "macos_build": _string_value(record, "macos_build"),
            "xcode_version": _string_value(record, "xcode_version"),
            "swift_version": _string_value(record, "swift_version"),
            "host_build_identity": _string_value(record, "host_build_identity"),
            "host_bundle_id": host_bundle_id,
            "host_signing_identity": _string_value(record, "host_signing_identity"),
            "screen_recording_tcc": screen_recording_tcc,
            "accessibility_tcc": accessibility_tcc,
            "host_source_commit": host_source_commit,
            "host_source_tree": host_source_tree,
            "host_source_dirty_state": host_source_dirty_state,
            "host_self_test_commit": host_self_test_commit,
            "current_base_commit": current_base_commit,
            "display_topology": _display_topology(record),
            "capture_backend": _enum_value(record, "capture_backend", CAPTURE_BACKENDS),
            "screen_capturekit_result": _enum_value(
                record, "screen_capturekit_result", SCREEN_CAPTUREKIT_RESULTS
            ),
            "cgdisplaystream_result": _enum_value(
                record, "cgdisplaystream_result", CGDISPLAYSTREAM_RESULTS
            ),
            "videotoolbox_result": _enum_value(
                record, "videotoolbox_result", VIDEOTOOLBOX_RESULTS
            ),
            "virtual_display_result": _enum_value(
                record, "virtual_display_result", VIRTUAL_DISPLAY_RESULTS
            ),
            "mirror_result": _enum_value(record, "mirror_result", MIRROR_RESULTS),
            "stream_transport": _enum_value(record, "stream_transport", TRANSPORTS),
            "android_counterpart": _string_value(record, "android_counterpart"),
            "compatibility_scope": _string_value(record, "compatibility_scope"),
        },
        "observations": field_values,
        "invalid_claims": invalid_claims,
        "invalid_claim_observations": invalid_claim_values,
        "closure_checklist": _closure_checklist(
            missing=missing,
            invalid_claims=invalid_claims,
        ),
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": artifact_paths,
        "artifact_file_check": artifact_file_check,
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }
    return summary


def _exit_code_for_verdict(verdict: str) -> int:
    if verdict == STATUS_PASS:
        return 0
    if verdict == STATUS_FAILED:
        return 2
    return 1


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize one Vibe Screen macOS Host compatibility matrix row.",
        epilog=(
            "Missing booleans default to false. A passing row is scoped only to "
            "the exact Mac architecture, model, macOS build, display topology, "
            "transport, and Android counterpart recorded in the input."
        ),
    )
    parser.add_argument("input", help="macOS compatibility evidence .json file, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--evidence-dir",
        help=(
            "directory used to verify artifact_paths. Defaults to the input file's "
            "parent for file input; disabled for stdin unless set explicitly"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
            evidence_dir = Path(args.evidence_dir) if args.evidence_dir else None
        else:
            input_path = Path(args.input)
            with input_path.open("r", encoding="utf-8") as stream:
                record = load_record(stream)
            evidence_dir = Path(args.evidence_dir) if args.evidence_dir else input_path.parent
        summary = summarize(record, run_id=args.run_id, evidence_dir=evidence_dir)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (MacOSHardwareCompatibilityError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return _exit_code_for_verdict(summary["verdict"])


if __name__ == "__main__":
    raise SystemExit(main())
