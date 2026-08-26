#!/usr/bin/env python3
"""Evaluate retained evidence for the iOS HDR/EDR output gate.

This gate is intentionally passive. It reads a sanitized observation file from a
separately scheduled iPhone/iPad run and fails closed when the run does not prove
the full HDR path. It does not launch Xcode, use Simulator evidence, connect to
Android, start the Host, or infer visible HDR output from SDR fallback tests.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


OBSERVATIONS_KIND = "ios_hdr_edr_readiness_observations"
GATE_KIND = "ios_hdr_edr_readiness_gate"
OWNER_ROLE = "ios_hdr_edr_current_base_owner"
OWNER_BRANCH = "codex/ios-hdr-edr-current-base-owner"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
PHYSICAL_IOS_RUNTIME_CLASSES = frozenset(("physical_iphone", "physical_ipad"))
INVALID_RUNTIME_CLASSES = frozenset(("simulator", "iphonesimulator", "android", "unsigned_archive"))
HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")

REQUIRED_CHECKS: tuple[tuple[str, str], ...] = (
    ("repository_current_base_recorded", "record the exact current-base source commit and clean/dirty state"),
    ("physical_ios_device", "use physical iPhone or iPad hardware, not Simulator, Android, or an archive"),
    ("hdr_capable_display", "record that the attached iOS display is HDR-capable"),
    ("edr_headroom_recorded", "record platform EDR headroom or an equivalent HDR display diagnostic"),
    ("client_advertised_hdr_video", "record that the iOS client advertised CAPABILITY_HDR_VIDEO"),
    ("hdr_config_accepted", "record an accepted HDR video config rather than an SDR fallback"),
    ("ten_bit_decode_capability_recorded", "record 10-bit hardware decode capability for the selected codec"),
    ("pq_or_hlg_transfer_recorded", "record PQ or HLG transfer metadata on the decoded stream"),
    ("bt2020_or_p3_color_metadata_recorded", "record BT.2020 or Display P3 HDR color metadata"),
    ("videotoolbox_output_format_recorded", "record VideoToolbox output pixel format for the HDR stream"),
    ("videotoolbox_hdr_metadata_recorded", "record VideoToolbox/CoreVideo HDR attachments on output frames"),
    ("edr_rendering_enabled", "record that the iOS rendering layer enabled EDR/HDR output"),
    ("visible_hdr_output_recorded", "retain visible output evidence or platform diagnostics proving HDR/EDR output"),
    ("sdr_peer_fallback_recorded", "record same-revision SDR-only peer fallback behavior"),
    ("artifacts_retained", "retain the logs, screenshots/recordings, diagnostics, and this gate output"),
)

INVALID_CLAIMS: tuple[tuple[str, str], ...] = (
    ("simulator_evidence_used", "Simulator evidence cannot close iOS HDR/EDR output"),
    ("unsigned_archive_evidence_used", "an unsigned archive cannot close iOS HDR/EDR output"),
    ("android_evidence_used", "Android evidence cannot close iOS HDR/EDR output"),
    ("sdr_fallback_claimed_as_hdr", "SDR fallback evidence cannot be reported as HDR output"),
    ("protocol_fields_only_claimed", "Protocol field presence without rendered output cannot close HDR/EDR output"),
    ("macos_fallback_claimed_as_ios_hdr", "macOS HDR-to-SDR fallback cannot be reported as iOS HDR output"),
)

ANDROID_MARKERS = ("android", "nubia", "p0110", "pacific", "xiaomi", "fuxi")
ANDROID_TOKEN_MARKERS = ("adb", "apk")
ANDROID_TOKEN_PATTERN = re.compile(
    r"(?<![0-9a-z])(?:" + "|".join(ANDROID_TOKEN_MARKERS) + r")(?![0-9a-z])"
)
SIMULATOR_MARKERS = ("simulator", "iphonesimulator")
UNSIGNED_MARKERS = ("unsigned", "unsigned_archive")

INTERPRETATION = (
    "A pass means retained evidence proves physical iOS HDR/EDR output end to end: "
    "HDR-capable display, HDR capability negotiation, 10-bit PQ/HLG decode, "
    "VideoToolbox/CoreVideo HDR metadata, EDR rendering enablement, visible "
    "output diagnostics, same-revision SDR fallback, and retained artifacts. "
    "SDR fallback, Simulator, unsigned archives, Android evidence, macOS "
    "fallback, and protocol fields alone remain readiness only."
)


class IOSHDREDRGateError(ValueError):
    """Raised when the observations file cannot be evaluated."""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_git(repo: Path, args: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repository_state(repo: Path) -> dict[str, Any]:
    revision = _run_git(repo, ["rev-parse", "HEAD"])
    status = _run_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    return {
        "commit": revision.lower() if isinstance(revision, str) and HASH_RE.fullmatch(revision) else None,
        "dirty": bool(status) if status is not None else None,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IOSHDREDRGateError(f"cannot read iOS HDR/EDR observations: {error}") from error
    if not isinstance(document, dict):
        raise IOSHDREDRGateError("iOS HDR/EDR observations must be a JSON object")
    return document


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _bool_observation(observations: dict[str, Any], field: str) -> bool:
    evidence = _dict(observations.get("evidence"))
    if field in evidence:
        return evidence.get(field) is True
    return observations.get(field) is True


def _bool_invalid_claim(observations: dict[str, Any], field: str) -> bool:
    invalid = _dict(observations.get("invalid_evidence"))
    if field in invalid:
        return invalid.get(field) is True
    return observations.get(field) is True


def _evidence_for(observations: dict[str, Any], field: str) -> list[str]:
    evidence_refs = _dict(observations.get("evidence_refs"))
    value = evidence_refs.get(field)
    if isinstance(value, str) and value.strip():
        return [value]
    return _string_list(value)


def _contains_marker(value: str, markers: Sequence[str]) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in markers)


def _contains_android_marker(value: str) -> bool:
    lowered = value.lower()
    return _contains_marker(lowered, ANDROID_MARKERS) or ANDROID_TOKEN_PATTERN.search(lowered) is not None


def _artifact_paths(observations: dict[str, Any]) -> list[str]:
    return _string_list(observations.get("artifact_paths"))


def _artifact_checks(
    artifact_paths: Sequence[str], evidence_root: Path | None
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    artifacts: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    resolved_root = evidence_root.resolve() if evidence_root is not None else None
    for reference in artifact_paths:
        record: dict[str, Any] = {"path": reference, "exists": None, "bytes": None}
        if Path(reference).is_absolute():
            invalid.append({"field": "artifact_paths", "reason": f"artifact path must be relative: {reference}"})
            artifacts.append(record)
            continue
        if _contains_android_marker(reference):
            invalid.append({"field": "artifact_paths", "reason": f"artifact path looks like Android evidence: {reference}"})
        if _contains_marker(reference, SIMULATOR_MARKERS):
            invalid.append({"field": "artifact_paths", "reason": f"artifact path looks like Simulator evidence: {reference}"})
        if _contains_marker(reference, UNSIGNED_MARKERS):
            invalid.append({"field": "artifact_paths", "reason": f"artifact path looks like unsigned archive evidence: {reference}"})
        if resolved_root is None:
            artifacts.append(record)
            continue
        path = (resolved_root / reference).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError:
            invalid.append({"field": "artifact_paths", "reason": f"artifact path escapes evidence root: {reference}"})
            artifacts.append(record)
            continue
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        record.update({"exists": exists, "bytes": size})
        if not exists:
            missing.append({"field": "artifact_paths", "requirement": f"retain artifact file: {reference}"})
        elif size == 0:
            missing.append({"field": "artifact_paths", "requirement": f"retained artifact must be non-empty: {reference}"})
        artifacts.append(record)
    return artifacts, missing, invalid


def _repository_checks(observations: dict[str, Any], repo: Path | None) -> dict[str, Any]:
    repository = _dict(observations.get("repository"))
    commit = repository.get("commit")
    dirty = repository.get("dirty")
    current = repository_state(repo) if repo is not None else {"commit": None, "dirty": None}
    commit_ok = isinstance(commit, str) and HASH_RE.fullmatch(commit) is not None
    clean_ok = dirty is False
    current_match = current["commit"] is None or (commit_ok and str(commit).lower() == current["commit"])
    return {
        "passed": commit_ok and clean_ok and current_match,
        "expected": "observations repository commit is a clean full SHA matching the evaluated worktree when available",
        "evidence": [str(commit)] if commit else [],
    }


def _runtime_checks(observations: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    runtime = _dict(observations.get("runtime"))
    runtime_class = runtime.get("runtime_class")
    identity_fields = ("device_role", "product_name", "hardware_model", "os_version", "build_number")
    identity_ok = all(_is_non_empty_string(runtime.get(field)) for field in identity_fields)
    invalid: list[dict[str, str]] = []
    if isinstance(runtime_class, str) and runtime_class.lower() in INVALID_RUNTIME_CLASSES:
        invalid.append({"field": "runtime.runtime_class", "reason": f"{runtime_class} cannot close iOS HDR/EDR output"})
    for field in identity_fields:
        value = runtime.get(field)
        if isinstance(value, str):
            if _contains_android_marker(value):
                invalid.append({"field": f"runtime.{field}", "reason": "runtime identity looks like Android evidence"})
            if _contains_marker(value, SIMULATOR_MARKERS):
                invalid.append({"field": f"runtime.{field}", "reason": "runtime identity looks like Simulator evidence"})
    return {
        "runtime_class_physical_ios": {
            "passed": runtime_class in PHYSICAL_IOS_RUNTIME_CLASSES,
            "expected": "runtime.runtime_class is physical_iphone or physical_ipad",
            "evidence": [str(runtime_class)] if runtime_class else [],
        },
        "device_identity_recorded": {
            "passed": identity_ok,
            "expected": "record iOS device role, product name, hardware model, OS version, and build number",
            "evidence": [str(runtime.get(field)) for field in identity_fields if runtime.get(field)],
        },
    }, invalid


def evaluate(
    observations: dict[str, Any], *, evidence_root: Path | None = None, repo: Path | None = None, source: str | None = None
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    missing_requirements: list[dict[str, str]] = []
    invalid_claims: list[dict[str, str]] = []

    if observations.get("schema_version") != SCHEMA_VERSION:
        missing_requirements.append(
            {"field": "schema_version", "requirement": f"set schema_version to {SCHEMA_VERSION}"}
        )
    if observations.get("kind") != OBSERVATIONS_KIND:
        missing_requirements.append(
            {"field": "kind", "requirement": f"set kind to {OBSERVATIONS_KIND}"}
        )

    checks["repository_current_base_recorded"] = _repository_checks(observations, repo)
    runtime_checks, runtime_invalid = _runtime_checks(observations)
    checks.update(runtime_checks)
    invalid_claims.extend(runtime_invalid)

    for field, expected in REQUIRED_CHECKS:
        if field == "repository_current_base_recorded":
            continue
        passed = _bool_observation(observations, field)
        checks[field] = {
            "passed": passed,
            "expected": expected,
            "evidence": _evidence_for(observations, field),
        }

    for field, reason in INVALID_CLAIMS:
        if _bool_invalid_claim(observations, field):
            invalid_claims.append({"field": field, "reason": reason})

    artifact_paths = _artifact_paths(observations)
    artifacts, missing_artifacts, invalid_artifacts = _artifact_checks(artifact_paths, evidence_root)
    missing_requirements.extend(missing_artifacts)
    invalid_claims.extend(invalid_artifacts)
    if not artifact_paths:
        checks["artifacts_retained"]["passed"] = False

    for field, check in checks.items():
        if not check["passed"]:
            missing_requirements.append({"field": field, "requirement": str(check["expected"])})

    verdict = FAIL if invalid_claims else (BLOCKED if missing_requirements else PASS)
    reasons: list[str] = []
    reasons.extend(f"fail: {item['field']}" for item in invalid_claims)
    reasons.extend(f"blocked: {item['field']}" for item in missing_requirements)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "created_at": _utc_timestamp(),
        "verdict": verdict,
        "can_close_ios_hdr_output_gate": verdict == PASS,
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "pull_request": None,
            "repository": REPOSITORY_FULL_NAME,
            "scope": "README Phase 5 iOS HDR output / EDR rendering gate",
        },
        "source": {"observations": source},
        "current_base": repository_state(repo) if repo is not None else {"commit": None, "dirty": None},
        "checks": checks,
        "retained_artifacts": artifacts,
        "missing_requirements": missing_requirements,
        "invalid_claims": invalid_claims,
        "reasons": reasons,
        "interpretation": INTERPRETATION,
    }


def blocked_report(observations_path: Path, reason: str, *, repo: Path | None = None) -> dict[str, Any]:
    report = evaluate({}, repo=repo, source=str(observations_path))
    report["missing_requirements"].insert(0, {"field": "observations", "requirement": reason})
    report["reasons"].insert(0, "blocked: observations")
    return report


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
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve() if args.repo else None
    try:
        observations = _load_json(args.observations)
        report = evaluate(
            observations,
            evidence_root=args.evidence_root,
            repo=repo,
            source=str(args.observations),
        )
    except (IOSHDREDRGateError, OSError, TypeError, ValueError) as error:
        report = blocked_report(args.observations, str(error), repo=repo)
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: iOS HDR/EDR gate output could not be written: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
