"""Create an iOS current-base acceptance readiness manifest.

The manifest is preparation metadata for the Phase 5 iOS aggregate gate. It is
deliberately conservative: generated manifests start with every device gate open
and carry explicit limitations so a simulator build, unsigned archive, loopback,
or Android record cannot be promoted into iOS device acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from . import ios_native_input
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
GATE_OWNERS = {
    "signing": "#290",
    "device_install": "#290",
    "protocol_session": "#290",
    "videotoolbox_h264": "#251",
    "videotoolbox_hevc": "#251",
    "input": "#257",
    "reconnect": "#238",
    "audio_playback": "#209",
    "hdr_output": "#196",
    "advanced_adapters": "#253",
    "host_advanced_adapters": "#253",
    "trusted_lan_secure_records": "#208",
}
SOURCE_DOCS = [
    "docs/changes/2026-08-04-phase-5-ios-advanced/PRD.md",
    "docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md",
    "docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md",
    "docs/runbook/ios-device-acceptance.md",
    "docs/runbook/hdr-color-acceptance.md",
]
SIGNING_READINESS_GATE_KIND = "ios_app_signing_readiness_gate"
SIGNING_READINESS_OWNER_ROLE = "ios_app_signing_readiness_current_base_owner"
SIGNING_READINESS_OWNER_BRANCH = "codex/ios-app-signing-readiness-current-base-20260829"
SIGNING_REQUIREMENT_FIELDS = (
    "team_id",
    "provisioning_profile",
    "bundle_id",
    "codesign_identity",
    "device_udids",
    "entitlements",
)
NATIVE_INPUT_KIND = "ios_native_input_behavior"
NATIVE_INPUT_PROFILE = "ios-native-input-behavior"
NATIVE_INPUT_GATE_OWNER = "phase5-ios-native-input-behavior"
NATIVE_INPUT_OWNER_ROLE = "ios_native_input_behavior_current_base_owner"
NATIVE_INPUT_OWNER_BRANCH = "codex/ios-native-input-readiness-gate"
NATIVE_INPUT_OWNER_PR = "#257"
VIDEOTOOLBOX_READINESS_KIND = "ios_hardware_videotoolbox_readiness"
VIDEOTOOLBOX_READINESS_PROFILE = "ios-hardware-videotoolbox-readiness"
VIDEOTOOLBOX_RUNTIME_CLASSES = ("physical_iphone", "physical_ipad")

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
    "hdr_output": "dedicated ios-hdr-edr-gate pass for HDR/EDR output on iOS hardware, not SDR fallback only",
    "advanced_adapters": "iOS app/product adapters for multi-client/display, audio, clipboard, files, HDR/color, actions, wake, and managed policy",
    "host_advanced_adapters": "MacHost advanced adapters for multi-client/display streams, audio capture, clipboard/file handlers, HDR/color retry, host actions, wake helper, and managed policy",
    "trusted_lan_secure_records": "secure-record trusted-LAN evidence; explicit plaintext legacy fallback is not enough",
}

DEFAULT_LIMITATIONS = [
    "This manifest does not claim an iOS device acceptance pass.",
    "Simulator builds, unsigned archives, MacHost loopback, and Android evidence do not close iOS device gates.",
    "The signing gate requires sanitized Team ID, provisioning profile, codesign identity, physical-device UDID hashes, unique bundle ID, and entitlements evidence before it can pass.",
    "The VideoToolbox gate requires physical iPhone and iPad readiness summaries with retained hardware decode artifacts.",
    "The current iOS trusted-LAN Core loopback has secure-record readiness evidence, while signed app/device and real-network LAN evidence remain open.",
]

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NATIVE_INPUT_REDACTED_PATH = "ios-native-input-gate.json"
NATIVE_INPUT_REDACTED_METADATA = {
    "field": "native_input_gate",
    "reason": "public native-input gate metadata contained unsafe text and was redacted",
}
NATIVE_INPUT_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\b" + "8a" + "023e3a" + r"\b", re.IGNORECASE),
    re.compile(r"\bEP[0-9A-Z]{16}\b"),
    re.compile(r"(?:^|/)Users/[^/\s]+", re.IGNORECASE),
    re.compile(r"(?:^|/)home/[^/\s]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\Users\\[^\s]+", re.IGNORECASE),
    re.compile(r"^(?:~|\$HOME)(?:/|\\)", re.IGNORECASE),
    re.compile(r"Application Support/com\.apple\.TCC", re.IGNORECASE),
    re.compile(r"\bTCC\.db\b", re.IGNORECASE),
    re.compile(r"\b(?:private|secret)[_-]?key(?:\b|[_.-])", re.IGNORECASE),
    re.compile(r"\b(?:api|access|refresh|session)[_-]?(?:key|token|secret|id)(?:\b|[_.-])", re.IGNORECASE),
    re.compile(r"\b(?:token|secret|password|passwd|credential|credentials)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_]{8,}", re.IGNORECASE),
)
PROBE_SENSITIVE_TEXT_REPLACEMENTS = (
    (re.compile(r"/Applications/[^\s\"']+/Contents/Developer"), "[redacted-developer-dir]"),
    (re.compile(r"/Library/Developer/CommandLineTools"), "[redacted-developer-dir]"),
    (re.compile(r"/Users/[^/\s]+"), "[redacted-user-home]"),
    (re.compile(r"/home/[^/\s]+"), "[redacted-user-home]"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\s]+", re.IGNORECASE), "[redacted-user-home]"),
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _redact_probe_text(value: str) -> str:
    redacted = value
    for pattern, replacement in PROBE_SENSITIVE_TEXT_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


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
            "detail": _redact_probe_text(str(error)),
        }
    output = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return {
        "command": list(command),
        "status": "pass" if result.returncode == 0 else "blocked",
        "exit_code": result.returncode,
        "summary": [_redact_probe_text(line) for line in output[:8]],
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


def _contains_disallowed_native_input_text(value: Any) -> bool:
    if isinstance(value, str):
        return any(
            pattern.search(value)
            for pattern in NATIVE_INPUT_SENSITIVE_TEXT_PATTERNS
        )
    if isinstance(value, dict):
        return any(_contains_disallowed_native_input_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_disallowed_native_input_text(item) for item in value)
    return False


def _native_input_path_reference(path: Path | None, repo: Path | None) -> str | None:
    if path is None:
        return None
    if _native_input_path_is_unsafe(path, repo):
        return NATIVE_INPUT_REDACTED_PATH
    candidate = path
    if candidate.is_absolute() and repo is not None:
        try:
            candidate = candidate.resolve().relative_to(repo.resolve())
        except ValueError:
            return NATIVE_INPUT_REDACTED_PATH
    text = candidate.as_posix()
    if _contains_disallowed_native_input_text(text):
        return NATIVE_INPUT_REDACTED_PATH
    return text


def _native_input_path_is_unsafe(path: Path | None, repo: Path | None) -> bool:
    if path is None:
        return False
    candidate = path
    if ".." in candidate.parts:
        return True
    if candidate.is_absolute():
        if repo is None:
            return True
        try:
            candidate = candidate.resolve().relative_to(repo.resolve())
        except ValueError:
            return True
    return _contains_disallowed_native_input_text(candidate.as_posix())


def _sanitize_native_input_list(value: Any, field: str) -> tuple[list[Any], list[dict[str, str]]]:
    if not isinstance(value, list):
        return [], []
    sanitized: list[Any] = []
    redactions: list[dict[str, str]] = []
    for item in value:
        if _contains_disallowed_native_input_text(item):
            redactions.append({**NATIVE_INPUT_REDACTED_METADATA, "source_field": field})
        elif isinstance(item, str):
            if field in {"missing_requirements", "blocking_reasons"}:
                sanitized.append({"field": "native_input_gate", "requirement": item})
            elif field == "disallowed_evidence":
                sanitized.append({"field": "native_input_gate", "reason": item})
            else:
                sanitized.append(item)
        else:
            sanitized.append(item)
    return sanitized, redactions


def _sanitize_native_input_artifact_paths(value: Any) -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(value, list):
        return [], []
    sanitized: list[str] = []
    redactions: list[dict[str, str]] = []
    for artifact in value:
        if not isinstance(artifact, str) or not artifact.strip():
            continue
        artifact_path = Path(artifact)
        if (
            artifact_path.is_absolute()
            or ".." in artifact_path.parts
            or _contains_disallowed_native_input_text(artifact)
        ):
            redactions.append({**NATIVE_INPUT_REDACTED_METADATA, "source_field": "artifact_paths"})
            continue
        sanitized.append(artifact)
    return sanitized, redactions


def _native_input_observation_failures(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["ios native-input gate observations must be an object"]
    failures: list[str] = []
    for field, requirement in ios_native_input.REQUIRED_FIELDS:
        if value.get(field) is not True:
            failures.append(
                f"ios native-input gate observation {field} must be true: {requirement}"
            )
    for field, reason in ios_native_input.DISALLOWED_EVIDENCE_FIELDS.items():
        if value.get(field) is not False:
            failures.append(
                f"ios native-input gate observation {field} must be false: {reason}"
            )
    return failures


def _canonical_native_input_observations(value: Any) -> dict[str, bool]:
    observations = value if isinstance(value, dict) else {}
    return {
        field: observations.get(field) is True
        for field in ios_native_input.BOOLEAN_FIELDS
    }


def _signing_probe() -> dict[str, Any]:
    result = _run_probe(["security", "find-identity", "-p", "codesigning", "-v"])
    summaries = result.get("summary", [])
    identity_count = 0
    if isinstance(summaries, list):
        for line in summaries:
            if isinstance(line, str) and re.search(r"\) [0-9A-Fa-f]{40} \".+\"", line):
                identity_count += 1
    command = result.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        command = ["security", "find-identity", "-p", "codesigning", "-v"]
    probe_passed = result.get("status") == "pass"
    sanitized = {
        "command": command,
        "status": "pass" if probe_passed and identity_count > 0 else "blocked",
        "valid_identity_count": identity_count,
        "summary": ["codesigning identity output redacted; count retained only"],
    }
    if "exit_code" in result:
        sanitized["exit_code"] = result["exit_code"]
    if result.get("status") == "blocked" and identity_count == 0 and "detail" in result:
        sanitized["detail"] = "codesigning identity probe unavailable"
    return sanitized


def _blocked_signing_requirements() -> dict[str, Any]:
    return {
        "status": "blocked",
        "requirements": {field: False for field in SIGNING_REQUIREMENT_FIELDS},
        "all_requirements_recorded": False,
        "simulator_build_used": False,
        "unsigned_build_used": False,
        "android_evidence_used": False,
    }


def _normalize_signing_requirements(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("requirements"), dict):
        return _blocked_signing_requirements()

    raw_requirements = value["requirements"]
    requirements = {
        field: raw_requirements.get(field) is True
        for field in SIGNING_REQUIREMENT_FIELDS
    }
    status = value.get("status") if isinstance(value.get("status"), str) else None
    return {
        "status": status if status in {"pass", "blocked", "fail"} else "blocked",
        "requirements": requirements,
        "all_requirements_recorded": value.get("all_requirements_recorded") is True
        and all(requirements.values()),
        "simulator_build_used": value.get("simulator_build_used") is True,
        "unsigned_build_used": value.get("unsigned_build_used") is True,
        "android_evidence_used": value.get("android_evidence_used") is True,
    }


def _load_signing_readiness_gate(path: Path | None, repository: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "path": None,
            "owner": None,
            "current_base": None,
            "signing_summary": None,
            "readiness_requirements": _blocked_signing_requirements(),
            "kind": None,
            "verdict": "blocked",
            "can_close_ios_app_signing_readiness": False,
            "can_close_ios_device_acceptance": False,
            "missing": ["ios-app-signing-readiness-gate.json not provided"],
            "failures": [],
        }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "provided": True,
            "path": str(path),
            "owner": None,
            "current_base": None,
            "signing_summary": None,
            "readiness_requirements": _blocked_signing_requirements(),
            "kind": None,
            "verdict": "blocked",
            "can_close_ios_app_signing_readiness": False,
            "can_close_ios_device_acceptance": False,
            "missing": [f"ios app-signing readiness gate unreadable: {error}"],
            "failures": [],
        }
    if not isinstance(document, dict):
        return {
            "provided": True,
            "path": str(path),
            "owner": None,
            "current_base": None,
            "signing_summary": None,
            "readiness_requirements": _blocked_signing_requirements(),
            "kind": None,
            "verdict": "blocked",
            "can_close_ios_app_signing_readiness": False,
            "can_close_ios_device_acceptance": False,
            "missing": ["ios app-signing readiness gate must be a JSON object"],
            "failures": [],
        }
    owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
    owner_role = owner.get("role") if isinstance(owner, dict) else None
    owner_head_ref = owner.get("head_ref") if isinstance(owner, dict) else None
    owner_repository = owner.get("repository") if isinstance(owner, dict) else None
    current_base = document.get("current_base") if isinstance(document.get("current_base"), dict) else {}
    current_base_commit = current_base.get("commit") if isinstance(current_base, dict) else None
    current_base_dirty = current_base.get("dirty") if isinstance(current_base, dict) else None
    repository_revision = repository.get("revision") if isinstance(repository, dict) else None
    repository_dirty = repository.get("dirty") if isinstance(repository, dict) else None
    signing_summary = (
        document.get("signing_summary")
        if isinstance(document.get("signing_summary"), dict)
        else {}
    )
    readiness_requirements = _normalize_signing_requirements(
        document.get("readiness_requirements")
    )
    requirements_complete = (
        readiness_requirements.get("status") == "pass"
        and readiness_requirements.get("all_requirements_recorded") is True
        and readiness_requirements.get("simulator_build_used") is False
        and readiness_requirements.get("unsigned_build_used") is False
        and readiness_requirements.get("android_evidence_used") is False
        and all(
            readiness_requirements.get("requirements", {}).get(field) is True
            for field in SIGNING_REQUIREMENT_FIELDS
        )
    )
    summary_complete = (
        signing_summary.get("status") == "pass"
        and isinstance(signing_summary.get("bundle_id"), str)
        and bool(signing_summary["bundle_id"].strip())
        and signing_summary.get("unique_bundle_id") is True
        and signing_summary.get("team_id_recorded") is True
        and signing_summary.get("codesign_identity_recorded") is True
        and signing_summary.get("provisioning_profile_recorded") is True
        and signing_summary.get("device_udid_hashes_recorded") is True
        and signing_summary.get("entitlements_recorded") is True
        and isinstance(signing_summary.get("signed_artifact_sha256"), str)
        and HASH_RE.fullmatch(signing_summary["signed_artifact_sha256"]) is not None
    )
    can_close = (
        document.get("kind") == SIGNING_READINESS_GATE_KIND
        and document.get("verdict") == "pass"
        and document.get("can_close_ios_app_signing_readiness") is True
        and document.get("can_close_ios_device_acceptance") is False
        and owner_role == SIGNING_READINESS_OWNER_ROLE
        and owner_head_ref == SIGNING_READINESS_OWNER_BRANCH
        and owner_repository == REPOSITORY_FULL_NAME
        and isinstance(current_base_commit, str)
        and COMMIT_RE.fullmatch(current_base_commit) is not None
        and isinstance(repository_revision, str)
        and current_base_commit.lower() == repository_revision.lower()
        and current_base_dirty is False
        and repository_dirty is False
        and summary_complete
        and requirements_complete
    )
    missing = document.get("missing", []) if isinstance(document.get("missing"), list) else []
    failures = document.get("failures", []) if isinstance(document.get("failures"), list) else []
    if document.get("kind") == SIGNING_READINESS_GATE_KIND and not can_close:
        if owner_role != SIGNING_READINESS_OWNER_ROLE:
            missing = [*missing, "ios app-signing readiness gate owner role is not the dedicated current-base owner"]
        if owner_head_ref != SIGNING_READINESS_OWNER_BRANCH:
            missing = [*missing, "ios app-signing readiness gate owner branch is not the current-base signing owner"]
        if owner_repository != REPOSITORY_FULL_NAME:
            missing = [*missing, "ios app-signing readiness gate repository is not TaoSama/vibe-screen"]
        if not isinstance(current_base_commit, str) or COMMIT_RE.fullmatch(current_base_commit) is None:
            missing = [*missing, "ios app-signing readiness gate current-base commit is not recorded"]
        elif not isinstance(repository_revision, str) or current_base_commit.lower() != repository_revision.lower():
            missing = [*missing, "ios app-signing readiness gate current-base commit does not match repository HEAD"]
        if current_base_dirty is not False:
            missing = [*missing, "ios app-signing readiness gate current-base dirty state is not clean"]
        if repository_dirty is not False:
            missing = [*missing, "repository dirty state is not clean for iOS signing readiness"]
        if not summary_complete:
            missing = [*missing, "ios app-signing readiness gate signing_summary is incomplete"]
        if not requirements_complete:
            missing = [*missing, "ios app-signing readiness gate readiness_requirements are incomplete"]
        if document.get("can_close_ios_device_acceptance") is not False:
            missing = [
                *missing,
                "ios app-signing readiness gate must not claim iOS device acceptance closure",
            ]

    return {
        "provided": True,
        "path": str(path),
        "owner": document.get("owner") if isinstance(document.get("owner"), dict) else None,
        "current_base": document.get("current_base")
        if isinstance(document.get("current_base"), dict)
        else None,
        "signing_summary": document.get("signing_summary")
        if isinstance(document.get("signing_summary"), dict)
        else None,
        "readiness_requirements": readiness_requirements,
        "kind": document.get("kind"),
        "verdict": "pass" if can_close else "blocked",
        "can_close_ios_app_signing_readiness": can_close,
        "can_close_ios_device_acceptance": False,
        "missing": missing,
        "failures": failures,
    }


def _signing_from_readiness_gate(gate: dict[str, Any]) -> dict[str, Any]:
    summary = gate.get("signing_summary") if isinstance(gate.get("signing_summary"), dict) else {}
    if gate.get("can_close_ios_app_signing_readiness") is not True:
        summary = {}
    return {
        "status": "pass" if gate.get("can_close_ios_app_signing_readiness") is True else "blocked",
        "bundle_id": summary.get("bundle_id") if isinstance(summary.get("bundle_id"), str) else None,
        "unique_bundle_id": summary.get("unique_bundle_id") is True,
        "team_id_redacted": summary.get("team_id_recorded") is True,
        "certificate_identity_recorded": summary.get("codesign_identity_recorded") is True,
        "provisioning_profile_recorded": summary.get("provisioning_profile_recorded") is True,
        "device_udid_hashes_recorded": summary.get("device_udid_hashes_recorded") is True,
        "entitlements_recorded": summary.get("entitlements_recorded") is True,
        "signed_archive_sha256": summary.get("signed_artifact_sha256")
        if isinstance(summary.get("signed_artifact_sha256"), str)
        else None,
    }


def _default_native_input_gate(
    *,
    provided: bool = False,
    path: Path | None = None,
    repo: Path | None = None,
    reasons: Sequence[str] | None = None,
    failures: Sequence[Any] | None = None,
) -> dict[str, Any]:
    observations = {field: False for field in ios_native_input.BOOLEAN_FIELDS}
    field_missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in ios_native_input.REQUIRED_FIELDS
    ]
    reason_missing = list(reasons or ["ios-native-input-gate.json not provided"])
    field_blocking = [
        {"field": field, "requirement": requirement}
        for field, requirement in ios_native_input.REQUIRED_FIELDS
        if field in ios_native_input.BLOCKING_FIELDS
    ]
    return {
        "provided": provided,
        "path": _native_input_path_reference(path, repo),
        "owner": None,
        "current_base": None,
        "kind": NATIVE_INPUT_KIND,
        "profile": NATIVE_INPUT_PROFILE,
        "gate_owner": NATIVE_INPUT_GATE_OWNER,
        "verdict": "blocked",
        "can_close_ios_native_input_gate": False,
        "requires_real_ios_device": True,
        "requires_signed_app": True,
        "requires_physical_keyboard": True,
        "requires_hover_or_pointer_accessory": True,
        "android_evidence_is_not_ios_input_evidence": True,
        "simulator_is_not_ios_input_evidence": True,
        "offline_tests_are_readiness_only": True,
        "observations": observations,
        "missing_requirements": [
            *field_missing,
            *({"field": "native_input_gate", "requirement": reason} for reason in reason_missing),
        ],
        "blocking_reasons": [
            *field_blocking,
            *(
                {"field": "native_input_gate", "requirement": reason}
                for reason in reason_missing
            ),
        ],
        "disallowed_evidence": list(failures or []),
        "artifact_paths": [],
    }


def _current_base_for_native_input(document: dict[str, Any]) -> dict[str, Any]:
    current_base = document.get("current_base") if isinstance(document.get("current_base"), dict) else {}
    commit = current_base.get("commit")
    if commit is None and isinstance(current_base.get("revision"), str):
        commit = current_base["revision"]
    return {
        "commit": commit if isinstance(commit, str) else None,
        "dirty": current_base.get("dirty") if isinstance(current_base.get("dirty"), bool) else None,
    }


def _load_native_input_gate(
    path: Path | None, repository: dict[str, Any], repo: Path | None = None
) -> dict[str, Any]:
    if path is None:
        return _default_native_input_gate()
    path_reference = _native_input_path_reference(path, repo)
    path_redactions = (
        [{**NATIVE_INPUT_REDACTED_METADATA, "source_field": "path"}]
        if _native_input_path_is_unsafe(path, repo)
        else []
    )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_native_input_gate(
            provided=True,
            path=path,
            repo=repo,
            reasons=["ios native-input gate is unreadable"],
            failures=path_redactions,
        )
    if not isinstance(document, dict):
        return _default_native_input_gate(
            provided=True,
            path=path,
            repo=repo,
            reasons=["ios native-input gate must be a JSON object"],
            failures=path_redactions,
        )

    owner = document.get("owner") if isinstance(document.get("owner"), dict) else {}
    current_base = _current_base_for_native_input(document)
    safe_artifact_paths, artifact_redactions = _sanitize_native_input_artifact_paths(
        document.get("artifact_paths")
    )
    missing, missing_redactions = _sanitize_native_input_list(
        document.get("missing_requirements"), "missing_requirements"
    )
    blocking_reasons, blocking_redactions = _sanitize_native_input_list(
        document.get("blocking_reasons"), "blocking_reasons"
    )
    disallowed_evidence, disallowed_redactions = _sanitize_native_input_list(
        document.get("disallowed_evidence"), "disallowed_evidence"
    )
    metadata_redactions = [
        *path_redactions,
        *artifact_redactions,
        *missing_redactions,
        *blocking_redactions,
        *disallowed_redactions,
    ]
    observations = _canonical_native_input_observations(document.get("observations"))
    observation_failures = _native_input_observation_failures(document.get("observations"))

    gate_commit = current_base.get("commit") if isinstance(current_base, dict) else None
    repository_revision = repository.get("revision") if isinstance(repository, dict) else None
    current_base_matches = (
        isinstance(gate_commit, str)
        and COMMIT_RE.fullmatch(gate_commit) is not None
        and isinstance(repository_revision, str)
        and gate_commit.lower() == repository_revision.lower()
        and current_base.get("dirty") is False
        and repository.get("dirty") is False
    )
    can_close = (
        document.get("kind") == NATIVE_INPUT_KIND
        and document.get("profile") == NATIVE_INPUT_PROFILE
        and document.get("gate_owner") == NATIVE_INPUT_GATE_OWNER
        and document.get("verdict") == "pass"
        and document.get("can_close_ios_native_input_gate") is True
        and owner.get("role") == NATIVE_INPUT_OWNER_ROLE
        and owner.get("head_ref") == NATIVE_INPUT_OWNER_BRANCH
        and owner.get("pull_request") == NATIVE_INPUT_OWNER_PR
        and owner.get("repository") == REPOSITORY_FULL_NAME
        and current_base_matches
        and bool(safe_artifact_paths)
        and not metadata_redactions
        and not observation_failures
        and document.get("requires_real_ios_device") is True
        and document.get("requires_signed_app") is True
        and document.get("requires_physical_keyboard") is True
        and document.get("requires_hover_or_pointer_accessory") is True
        and document.get("android_evidence_is_not_ios_input_evidence") is True
        and document.get("simulator_is_not_ios_input_evidence") is True
        and document.get("offline_tests_are_readiness_only") is True
        and document.get("missing_requirements") == []
        and document.get("blocking_reasons") == []
        and document.get("disallowed_evidence") == []
    )
    can_close = bool(can_close)
    if not can_close:
        if metadata_redactions:
            missing = [*missing, "ios native-input gate metadata contained unsafe text and was redacted"]
        if observation_failures:
            missing = [*missing, *observation_failures]
        if document.get("kind") != NATIVE_INPUT_KIND:
            missing = [*missing, "ios native-input gate kind is not ios_native_input_behavior"]
        if document.get("profile") != NATIVE_INPUT_PROFILE:
            missing = [*missing, "ios native-input gate profile is not ios-native-input-behavior"]
        if document.get("gate_owner") != NATIVE_INPUT_GATE_OWNER:
            missing = [*missing, "ios native-input gate gate_owner is not the dedicated native-input owner"]
        if document.get("verdict") != "pass" or document.get("can_close_ios_native_input_gate") is not True:
            missing = [*missing, "ios native-input gate verdict does not close the native-input gate"]
        if owner.get("role") != NATIVE_INPUT_OWNER_ROLE:
            missing = [*missing, "ios native-input gate owner role is not the dedicated current-base owner"]
        if owner.get("head_ref") != NATIVE_INPUT_OWNER_BRANCH:
            missing = [*missing, "ios native-input gate owner branch is not the current-base native-input owner"]
        if owner.get("pull_request") != NATIVE_INPUT_OWNER_PR:
            missing = [*missing, "ios native-input gate owner PR must remain #257"]
        if owner.get("repository") != REPOSITORY_FULL_NAME:
            missing = [*missing, "ios native-input gate repository is not TaoSama/vibe-screen"]
        if not isinstance(gate_commit, str) or COMMIT_RE.fullmatch(gate_commit) is None:
            missing = [*missing, "ios native-input gate current-base commit is not recorded"]
        elif not isinstance(repository_revision, str) or gate_commit.lower() != repository_revision.lower():
            missing = [*missing, "ios native-input gate current-base commit does not match repository HEAD"]
        if current_base.get("dirty") is not False:
            missing = [*missing, "ios native-input gate current-base dirty state is not clean"]
        if repository.get("dirty") is not False:
            missing = [*missing, "repository dirty state is not clean for iOS native input"]
        if document.get("requires_real_ios_device") is not True:
            missing = [*missing, "ios native-input gate requires_real_ios_device must be true"]
        if document.get("requires_signed_app") is not True:
            missing = [*missing, "ios native-input gate requires_signed_app must be true"]
        if document.get("requires_physical_keyboard") is not True:
            missing = [*missing, "ios native-input gate requires_physical_keyboard must be true"]
        if document.get("requires_hover_or_pointer_accessory") is not True:
            missing = [*missing, "ios native-input gate requires_hover_or_pointer_accessory must be true"]
        if document.get("android_evidence_is_not_ios_input_evidence") is not True:
            missing = [*missing, "ios native-input gate android_evidence_is_not_ios_input_evidence must be true"]
        if document.get("simulator_is_not_ios_input_evidence") is not True:
            missing = [*missing, "ios native-input gate simulator_is_not_ios_input_evidence must be true"]
        if document.get("offline_tests_are_readiness_only") is not True:
            missing = [*missing, "ios native-input gate offline_tests_are_readiness_only must be true"]
        if document.get("verdict") != "pass" or document.get("can_close_ios_native_input_gate") is not True:
            missing = [*missing, "ios native-input gate verdict is not pass"]
        if document.get("missing_requirements") != []:
            missing = [*missing, "ios native-input gate missing_requirements must be an explicit empty list"]
        if document.get("blocking_reasons") != []:
            missing = [*missing, "ios native-input gate blocking_reasons must be an explicit empty list"]
        if document.get("disallowed_evidence") != []:
            missing = [*missing, "ios native-input gate disallowed_evidence must be an explicit empty list"]
        if blocking_reasons:
            missing = [*missing, "ios native-input gate still has blocking reasons"]
        if disallowed_evidence:
            missing = [*missing, "ios native-input gate contains disallowed evidence"]
        if not safe_artifact_paths:
            missing = [*missing, "ios native-input gate must retain sanitized iOS/Host artifacts"]

    missing_requirements = [
        item if isinstance(item, dict) else {"field": "native_input_gate", "requirement": str(item)}
        for item in missing
    ]
    blocking_reasons = _sanitize_native_input_list(
        blocking_reasons if blocking_reasons else missing_requirements, "blocking_reasons"
    )[0]
    disallowed_evidence = [
        item
        if isinstance(item, dict) and {"field", "reason"}.issubset(item)
        else {"field": "native_input_gate", "reason": str(item)}
        for item in [*disallowed_evidence, *metadata_redactions]
    ]
    normalized = _default_native_input_gate(
        provided=True,
        path=path,
        repo=repo,
        reasons=missing_requirements,
        failures=disallowed_evidence,
    )
    normalized.update(
        {
            "owner": document.get("owner") if isinstance(document.get("owner"), dict) else None,
            "current_base": current_base,
            "kind": document.get("kind"),
            "profile": document.get("profile"),
            "gate_owner": document.get("gate_owner"),
            "verdict": "pass" if can_close else "blocked",
            "can_close_ios_native_input_gate": can_close,
            "requires_real_ios_device": document.get("requires_real_ios_device") is True,
            "requires_signed_app": document.get("requires_signed_app") is True,
            "requires_physical_keyboard": document.get("requires_physical_keyboard") is True,
            "requires_hover_or_pointer_accessory": document.get("requires_hover_or_pointer_accessory") is True,
            "android_evidence_is_not_ios_input_evidence": document.get("android_evidence_is_not_ios_input_evidence") is True,
            "simulator_is_not_ios_input_evidence": document.get("simulator_is_not_ios_input_evidence") is True,
            "offline_tests_are_readiness_only": document.get("offline_tests_are_readiness_only") is True,
            "observations": observations,
            "missing_requirements": missing_requirements,
            "blocking_reasons": blocking_reasons,
            "disallowed_evidence": disallowed_evidence,
            "artifact_paths": safe_artifact_paths,
        }
    )
    return normalized


def default_videotoolbox_readiness_gates() -> list[dict[str, Any]]:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": VIDEOTOOLBOX_READINESS_KIND,
        "profile": VIDEOTOOLBOX_READINESS_PROFILE,
        "verdict": "blocked",
        "can_close_device_family_videotoolbox_gate": False,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "artifact_paths": [],
        "artifact_checks": [],
    }
    return [
        {
            **common,
            "runtime_class": "physical_iphone",
            "blocking_reasons": [
                {
                    "field": "artifact_paths",
                    "requirement": "retain physical iPhone VideoToolbox hardware decode artifacts",
                }
            ],
        },
        {
            **common,
            "runtime_class": "physical_ipad",
            "blocking_reasons": [
                {
                    "field": "artifact_paths",
                    "requirement": "retain physical iPad VideoToolbox hardware decode artifacts",
                }
            ],
        },
    ]


def _blocked_videotoolbox_readiness_gate(
    *,
    path: Path | None,
    runtime_class: str | None,
    artifact_paths: Any = None,
    artifact_checks: Any = None,
    reasons: Sequence[str],
) -> dict[str, Any]:
    safe_artifact_paths = (
        artifact_paths
        if isinstance(artifact_paths, list)
        and all(isinstance(artifact, str) and artifact.strip() for artifact in artifact_paths)
        else []
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": VIDEOTOOLBOX_READINESS_KIND,
        "profile": VIDEOTOOLBOX_READINESS_PROFILE,
        "runtime_class": runtime_class if runtime_class in VIDEOTOOLBOX_RUNTIME_CLASSES else "physical_iphone",
        "verdict": "blocked",
        "can_close_device_family_videotoolbox_gate": False,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "artifact_paths": safe_artifact_paths,
        "artifact_checks": artifact_checks if isinstance(artifact_checks, list) else [],
        "blocking_reasons": [
            {"field": "videotoolbox_readiness_gate", "requirement": reason}
            for reason in reasons
        ],
    }


def _load_videotoolbox_readiness_gate(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return _blocked_videotoolbox_readiness_gate(
            path=path,
            runtime_class=None,
            reasons=["ios videotoolbox readiness gate is unreadable"],
        )
    except UnicodeDecodeError:
        return _blocked_videotoolbox_readiness_gate(
            path=path,
            runtime_class=None,
            reasons=["ios videotoolbox readiness gate must be UTF-8 JSON"],
        )
    except json.JSONDecodeError:
        return _blocked_videotoolbox_readiness_gate(
            path=path,
            runtime_class=None,
            reasons=["ios videotoolbox readiness gate must be valid JSON"],
        )
    if not isinstance(document, dict):
        return _blocked_videotoolbox_readiness_gate(
            path=path,
            runtime_class=None,
            reasons=["ios videotoolbox readiness gate must be a JSON object"],
        )

    runtime_class = document.get("runtime_class")
    missing: list[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        missing.append(f"schema_version must be {SCHEMA_VERSION}")
    if document.get("kind") != VIDEOTOOLBOX_READINESS_KIND:
        missing.append("kind must be ios_hardware_videotoolbox_readiness")
    if document.get("profile") != VIDEOTOOLBOX_READINESS_PROFILE:
        missing.append("profile must be ios-hardware-videotoolbox-readiness")
    if runtime_class not in VIDEOTOOLBOX_RUNTIME_CLASSES:
        missing.append("runtime_class must be physical_iphone or physical_ipad")
    if document.get("verdict") != "pass":
        missing.append("verdict must be pass")
    if document.get("can_close_device_family_videotoolbox_gate") is not True:
        missing.append("can_close_device_family_videotoolbox_gate must be true")
    if document.get("can_close_phase5_hardware_videotoolbox_gate") is not False:
        missing.append("can_close_phase5_hardware_videotoolbox_gate must remain false")
    artifact_paths = document.get("artifact_paths")
    if (
        not isinstance(artifact_paths, list)
        or not artifact_paths
        or not all(isinstance(artifact, str) and artifact.strip() for artifact in artifact_paths)
    ):
        missing.append("artifact_paths must retain sanitized VideoToolbox artifacts")
    artifact_checks = document.get("artifact_checks")
    if not isinstance(artifact_checks, list) or not artifact_checks:
        missing.append("artifact_checks must retain artifact validation results")
    else:
        required_flags = ("exists", "non_empty", "under_evidence_dir", "valid_ios_videotoolbox_source")
        for check in artifact_checks:
            if not isinstance(check, dict) or not all(check.get(flag) is True for flag in required_flags):
                missing.append("artifact_checks must all pass")
                break

    if missing:
        return _blocked_videotoolbox_readiness_gate(
            path=path,
            runtime_class=runtime_class if isinstance(runtime_class, str) else None,
            artifact_paths=document.get("artifact_paths"),
            artifact_checks=document.get("artifact_checks"),
            reasons=missing,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": VIDEOTOOLBOX_READINESS_KIND,
        "profile": VIDEOTOOLBOX_READINESS_PROFILE,
        "runtime_class": runtime_class,
        "verdict": "pass",
        "can_close_device_family_videotoolbox_gate": True,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "artifact_paths": artifact_paths,
        "artifact_checks": artifact_checks,
        "blocking_reasons": [],
    }


def _merge_videotoolbox_readiness_gates(paths: Sequence[Path] | None) -> list[dict[str, Any]]:
    defaults = {gate["runtime_class"]: gate for gate in default_videotoolbox_readiness_gates()}
    if not paths:
        return [defaults[runtime] for runtime in VIDEOTOOLBOX_RUNTIME_CLASSES]

    merged = dict(defaults)
    for path in paths:
        gate = _load_videotoolbox_readiness_gate(path)
        runtime_class = gate.get("runtime_class")
        if runtime_class in VIDEOTOOLBOX_RUNTIME_CLASSES:
            merged[runtime_class] = gate
    return [merged[runtime] for runtime in VIDEOTOOLBOX_RUNTIME_CLASSES]


def default_native_input_gate() -> dict[str, Any]:
    return _default_native_input_gate()


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
        "owner_pr": GATE_OWNERS[name],
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
    signing_readiness_gate: Path | None = None,
    native_input_gate: Path | None = None,
    videotoolbox_readiness_gates: Sequence[Path] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    owner_pr = _normalize_pr(device_acceptance_owner_pr)
    source_docs = _ensure_source_docs(repo, SOURCE_DOCS)
    repository = repository_state(repo)
    signing_readiness = _load_signing_readiness_gate(signing_readiness_gate, repository)
    native_input = _load_native_input_gate(native_input_gate, repository, repo=repo)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_timestamp(),
        "command": list(command),
        "repository": repository,
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
        "signing_readiness_gate": signing_readiness,
        "native_input_gate": native_input,
        "signing": _signing_from_readiness_gate(signing_readiness),
        "videotoolbox_readiness_gates": _merge_videotoolbox_readiness_gates(videotoolbox_readiness_gates),
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
    parser.add_argument(
        "--signing-readiness-gate",
        type=Path,
        help="optional ios-app-signing-readiness-gate.json to bind into current-base readiness",
    )
    parser.add_argument(
        "--native-input-gate",
        type=Path,
        help="optional ios-native-input-gate.json to bind into current-base readiness",
    )
    parser.add_argument(
        "--videotoolbox-readiness-gate",
        type=Path,
        action="append",
        help="optional ios-videotoolbox-readiness.json to bind; pass once per device family",
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
            signing_readiness_gate=args.signing_readiness_gate,
            native_input_gate=args.native_input_gate,
            videotoolbox_readiness_gates=args.videotoolbox_readiness_gate,
            notes=args.notes,
        )
        manifest["source_root"] = os.path.relpath(
            args.repo.resolve(),
            args.output.resolve().parent,
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
