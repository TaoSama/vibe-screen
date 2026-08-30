"""Evaluate the Phase 0 module-ownership extraction owner manifest.

This checker is intentionally source/evidence only. It records which baseline
Android ownership boundaries have a current-base owner and focused contract
coverage, and it fails closed while any required Phase 0 boundary is still open
or only partially enforced.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

KIND = "phase0_module_ownership_current_base_manifest"
SUMMARY_KIND = "phase0_module_ownership_current_base_summary"
PHASE = "phase0"
STATUS_CLOSED = "closed"
STATUS_PARTIAL = "partial"
STATUS_OPEN = "open"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAIL = "fail"
ALLOWED_STATUSES = {
    STATUS_CLOSED,
    STATUS_PARTIAL,
    STATUS_OPEN,
    STATUS_BLOCKED,
    STATUS_INSUFFICIENT,
    STATUS_FAIL,
}
VERDICT_PASS = "pass"
VERDICT_BLOCKED = "blocked"
VERDICT_INSUFFICIENT = "insufficient"
VERDICT_FAIL = "fail"
HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")

REQUIRED_BOUNDARY_IDS = (
    "transport_dependency_direction",
    "transport_resource_lifecycle",
    "stream_client_local_session_state",
    "stream_client_protocol_action_dispatch",
    "stream_client_input_envelope_routing",
    "stream_client_media_frame_routing",
    "protocol_side_effect_admission",
    "protocol_session_ownership",
    "file_transfer_product_ownership",
    "wake_host_product_ownership",
    "decoder_ownership",
    "renderer_ownership",
    "ui_product_session_boundaries",
)


class Phase0ModuleOwnershipError(ValueError):
    """Raised when the module-ownership manifest cannot be evaluated."""


def load_manifest(stream: TextIO) -> dict[str, Any]:
    try:
        manifest = json.load(stream)
    except json.JSONDecodeError as error:
        raise Phase0ModuleOwnershipError(f"invalid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise Phase0ModuleOwnershipError("manifest must be a JSON object")
    return manifest


def _string(record: dict[str, Any], field: str, *, required: bool = True) -> str:
    value = record.get(field)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise Phase0ModuleOwnershipError(f"{field} must be a non-empty string")
    return value


def _bool(record: dict[str, Any], field: str, *, default: bool = True) -> bool:
    value = record.get(field, default)
    if not isinstance(value, bool):
        raise Phase0ModuleOwnershipError(f"{field} must be true or false")
    return value


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Phase0ModuleOwnershipError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise Phase0ModuleOwnershipError(f"{field} must contain only non-empty strings")
    return value


def _source_summary(
    source: dict[str, Any], *, evaluation_date: _datetime.date | None = None
) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise Phase0ModuleOwnershipError("source must be an object")
    base_commit = _string(source, "base_commit")
    if not HASH_RE.fullmatch(base_commit):
        raise Phase0ModuleOwnershipError("source.base_commit must be a 40-character Git SHA")
    audit_date = _string(source, "audit_date")
    try:
        parsed_audit_date = _datetime.date.fromisoformat(audit_date)
    except ValueError as error:
        raise Phase0ModuleOwnershipError("source.audit_date must be an ISO date") from error
    if evaluation_date is None:
        evaluation_date = _datetime.date.today()
    if parsed_audit_date > evaluation_date:
        raise Phase0ModuleOwnershipError("source.audit_date must not be in the future")
    return {
        "base_commit": base_commit.lower(),
        "base_ref": _string(source, "base_ref"),
        "audit_date": audit_date,
        "owner": _string(source, "owner"),
    }


def _path_exists(repo_root: Path, value: str) -> bool:
    fragment_split = value.split("#", 1)
    if len(fragment_split) == 2 and not fragment_split[0].strip():
        return False
    if "://" in value or value.startswith("#"):
        return True
    candidate = Path(value)
    if candidate.is_absolute():
        return False
    if ".." in candidate.parts:
        return False
    resolved_root = repo_root.resolve()
    resolved_candidate = (resolved_root / candidate).resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        return False
    return resolved_candidate.exists()


def _boundary_summary(
    boundary: dict[str, Any], *, repo_root: Path | None
) -> dict[str, Any]:
    boundary_id = _string(boundary, "id")
    status = _string(boundary, "status")
    if status not in ALLOWED_STATUSES:
        raise Phase0ModuleOwnershipError(
            f"boundary {boundary_id}: unsupported status {status!r}"
        )
    evidence_paths = _string_list(boundary, "evidence_paths")
    focused_tests = _string_list(boundary, "focused_tests")
    blockers = _string_list(boundary, "blockers")
    fail_closed_checklist = _string_list(boundary, "fail_closed_checklist")
    required = _bool(boundary, "required_for_phase0_stable", default=True)

    issues: list[str] = []
    if status == STATUS_CLOSED:
        if blockers:
            issues.append("closed boundary must not list blockers")
        if fail_closed_checklist:
            issues.append("closed boundary must not list a fail-closed checklist")
        if not evidence_paths:
            issues.append("closed boundary must cite at least one evidence path")
        if not focused_tests:
            issues.append("closed boundary must cite at least one focused test or gate")
    else:
        if required and not blockers and not fail_closed_checklist:
            issues.append(
                "open required boundary must list blockers or a fail-closed checklist"
            )

    missing_evidence_paths: list[str] = []
    if repo_root is not None:
        missing_evidence_paths = [
            path for path in evidence_paths if not _path_exists(repo_root, path)
        ]
        if missing_evidence_paths:
            issues.append(
                "evidence path(s) do not exist: " + ", ".join(missing_evidence_paths)
            )

    can_close = required and status == STATUS_CLOSED and not issues
    return {
        "id": boundary_id,
        "title": _string(boundary, "title"),
        "required_for_phase0_stable": required,
        "status": status,
        "can_close": can_close,
        "owner_surface": _string(boundary, "owner_surface"),
        "evidence_paths": evidence_paths,
        "focused_tests": focused_tests,
        "blockers": blockers,
        "fail_closed_checklist": fail_closed_checklist,
        "missing_evidence_paths": missing_evidence_paths,
        "issues": issues,
    }


def evaluate_manifest(
    manifest: dict[str, Any],
    *,
    repo_root: Path | None = None,
    evaluation_date: _datetime.date | None = None,
) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise Phase0ModuleOwnershipError("schema_version must be vibescreen.evidence/v1")
    if manifest.get("kind") != KIND:
        raise Phase0ModuleOwnershipError(f"kind must be {KIND}")
    if manifest.get("phase") != PHASE:
        raise Phase0ModuleOwnershipError("phase must be phase0")

    source = _source_summary(manifest.get("source", {}), evaluation_date=evaluation_date)
    raw_boundaries = manifest.get("module_boundaries")
    if not isinstance(raw_boundaries, list):
        raise Phase0ModuleOwnershipError("module_boundaries must be a list")

    boundary_summaries = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    for raw_boundary in raw_boundaries:
        if not isinstance(raw_boundary, dict):
            raise Phase0ModuleOwnershipError("module_boundaries entries must be objects")
        summary = _boundary_summary(raw_boundary, repo_root=repo_root)
        if summary["id"] in seen_ids:
            duplicate_ids.append(summary["id"])
        seen_ids.add(summary["id"])
        boundary_summaries.append(summary)

    malformed_reasons = []
    missing_boundary_ids = [
        boundary_id for boundary_id in REQUIRED_BOUNDARY_IDS if boundary_id not in seen_ids
    ]
    unexpected_required_boundary_ids = [
        summary["id"]
        for summary in boundary_summaries
        if summary["required_for_phase0_stable"]
        and summary["id"] not in REQUIRED_BOUNDARY_IDS
    ]
    if missing_boundary_ids:
        malformed_reasons.append(
            "missing required module boundary id(s): " + ", ".join(missing_boundary_ids)
        )
    if duplicate_ids:
        malformed_reasons.append(
            "duplicate module boundary id(s): " + ", ".join(sorted(set(duplicate_ids)))
        )
    if unexpected_required_boundary_ids:
        malformed_reasons.append(
            "unexpected required module boundary id(s): "
            + ", ".join(unexpected_required_boundary_ids)
        )

    required_boundaries = [
        summary
        for summary in boundary_summaries
        if summary["id"] in REQUIRED_BOUNDARY_IDS
    ]
    open_required_boundaries = [
        summary
        for summary in required_boundaries
        if not summary["can_close"] or summary["issues"]
    ]

    if malformed_reasons or any(summary["issues"] for summary in boundary_summaries):
        verdict = VERDICT_INSUFFICIENT
    elif any(summary["status"] == STATUS_FAIL for summary in open_required_boundaries):
        verdict = VERDICT_FAIL
    elif open_required_boundaries:
        verdict = VERDICT_BLOCKED
    else:
        verdict = VERDICT_PASS

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SUMMARY_KIND,
        "phase": PHASE,
        "source": source,
        "verdict": verdict,
        "can_close_phase0_module_ownership_extraction": verdict == VERDICT_PASS,
        "required_boundary_count": len(REQUIRED_BOUNDARY_IDS),
        "closed_required_boundary_count": sum(
            1 for summary in required_boundaries if summary["can_close"]
        ),
        "missing_required_boundary_ids": missing_boundary_ids,
        "open_required_boundaries": open_required_boundaries,
        "boundary_summaries": boundary_summaries,
        "reasons": malformed_reasons,
    }


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
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, help="summary JSON path")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit nonzero unless every required module boundary is closed",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.manifest.open("r", encoding="utf-8") as stream:
            manifest = load_manifest(stream)
        summary = evaluate_manifest(manifest, repo_root=args.repo_root.resolve())
        if args.output:
            _write_summary(args.output, summary)
        else:
            json.dump(summary, sys.stdout, indent=2, sort_keys=True, allow_nan=False)
            sys.stdout.write("\n")
    except (OSError, Phase0ModuleOwnershipError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.require_pass and summary["verdict"] != VERDICT_PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
