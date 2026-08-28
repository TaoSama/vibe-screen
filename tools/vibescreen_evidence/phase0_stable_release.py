"""Evaluate the aggregate Phase 0 stable-release closure manifest.

This checker owns only the aggregate release decision. It does not reinterpret
readiness, synthetic, historical, or blocked sub-gate evidence as a pass.
"""

from __future__ import annotations

import argparse
import json
import re
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
    "module_ownership_extraction",
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
    if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
        raise Phase0StableReleaseError("owner_prs must be a list of integers")
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


def _gate_summary(gate: dict[str, Any]) -> dict[str, Any]:
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

    source_guard = _source_guard(source, expected_source_commit)

    gates_value = manifest.get("required_gates")
    if not isinstance(gates_value, list):
        raise Phase0StableReleaseError("required_gates must be a list")

    gate_summaries = []
    seen_gate_ids: set[str] = set()
    duplicate_gate_ids: list[str] = []
    for raw_gate in gates_value:
        if not isinstance(raw_gate, dict):
            raise Phase0StableReleaseError("required_gates entries must be objects")
        summary = _gate_summary(raw_gate)
        if summary["id"] in seen_gate_ids:
            duplicate_gate_ids.append(summary["id"])
        seen_gate_ids.add(summary["id"])
        gate_summaries.append(summary)

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
    aggregate_passed = (
        not malformed_reasons
        and source_guard["verdict"] == STATUS_PASS
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
        "manifest_source": source,
        "reasons": [
            *malformed_reasons,
            *source_guard["reasons"],
            *gate_reasons,
            *readme_guard["reasons"],
        ],
    }


def _source_guard(
    source: dict[str, Any], expected_source_commit: str | None
) -> dict[str, Any]:
    base_commit = source.get("base_commit")
    reasons: list[str] = []
    if not isinstance(base_commit, str) or not base_commit.strip():
        reasons.append("manifest source.base_commit must be a non-empty string")
    elif expected_source_commit and base_commit != expected_source_commit:
        reasons.append(
            "manifest source.base_commit does not match the evaluated source "
            f"commit: {base_commit} != {expected_source_commit}"
        )
    for field in ("base_ref", "owner", "audit_source"):
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"manifest source.{field} must be a non-empty string")
    audit_date = source.get("audit_date")
    if not isinstance(audit_date, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", audit_date
    ):
        reasons.append("manifest source.audit_date must use YYYY-MM-DD format")

    return {
        "verdict": STATUS_INSUFFICIENT if reasons else STATUS_PASS,
        "expected_source_commit": expected_source_commit or None,
        "manifest_base_commit": base_commit if isinstance(base_commit, str) else None,
        "reasons": reasons,
    }


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
        help="Fail closed unless manifest source.base_commit matches this commit",
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit nonzero unless every aggregate Phase 0 stable-release gate passes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.manifest.open("r", encoding="utf-8") as stream:
            manifest = load_json(stream)
        readme_text = args.readme.read_text(encoding="utf-8")
        summary = evaluate_manifest(
            manifest,
            readme_text=readme_text,
            expected_source_commit=args.expected_source_commit,
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
    if args.require_pass and summary["aggregate_verdict"] != STATUS_PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
