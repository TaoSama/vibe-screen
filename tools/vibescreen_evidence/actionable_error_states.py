"""Validate the Phase 1 actionable-error state owner matrix.

This gate is intentionally offline. It validates that the documented Android
and macOS Host system states have stable ownership, user actions, retry policy,
and evidence boundaries. It does not start the Host, run ADB, inspect devices,
or close the README Phase 1 device acceptance gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


KIND = "phase1_actionable_error_state_matrix"
REPORT_KIND = "phase1_actionable_error_state_gate"
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
VALID_PLATFORMS = frozenset(("android", "macos_host"))
VALID_RETRY_BEHAVIORS = frozenset(
    ("bounded_auto_retry", "manual_retry", "terminal_no_retry", "not_applicable")
)
VALID_EVIDENCE_STATUSES = frozenset(
    ("device-covered", "offline-covered", "blocked", "open", "offline-only")
)
VALID_GATE_STATUSES = frozenset(("device-covered", "covered-offline", "blocked", "open"))
REQUIRED_OPEN_PRS = frozenset((242, 243, 272))
MIN_ANDROID_STATES = 8
MIN_HOST_STATES = 8
REMOTE_EVIDENCE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
SESSION_FAILURE_ENUM_RE = re.compile(r"\benum\s+class\s+SessionFailureKind\b")

REQUIRED_STATE_FIELDS = (
    "id",
    "platform",
    "system_state",
    "failed_layer",
    "source_classifier",
    "ui_surface",
    "user_visible_copy",
    "user_action",
    "retry_behavior",
    "offline_evidence",
    "device_evidence_status",
    "gate_status",
    "readme_gate_closure",
)


class ActionableErrorStateError(ValueError):
    """Raised when the actionable-error matrix is malformed."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def load_matrix(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise ActionableErrorStateError(f"could not read {path}: {error}") from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ActionableErrorStateError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict):
        raise ActionableErrorStateError("top-level matrix must be an object")
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _integer_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _state_id_set(states: list[dict[str, Any]], platform: str) -> set[str]:
    return {
        state["id"]
        for state in states
        if state.get("platform") == platform and isinstance(state.get("id"), str)
    }


def _skip_quoted(source: str, start: int) -> int:
    if source.startswith('\"\"\"', start):
        end = source.find('\"\"\"', start + 3)
        if end == -1:
            return len(source)
        return end + 3

    quote = source[start]
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character == quote:
            return index + 1
        index += 1
    return len(source)


def _skip_comment(source: str, start: int) -> int | None:
    if source.startswith("//", start):
        end = source.find("\n", start + 2)
        return len(source) if end == -1 else end + 1
    if source.startswith("/*", start):
        end = source.find("*/", start + 2)
        return len(source) if end == -1 else end + 2
    return None


def _extract_balanced_brace_body(source: str, open_brace_index: int) -> str:
    depth = 0
    body_start = open_brace_index + 1
    index = open_brace_index
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[body_start:index]
            if depth < 0:
                break
        index += 1
    raise ActionableErrorStateError("SessionFailureKind enum body is not balanced")


def _find_next_open_brace(source: str, start: int) -> int:
    index = start
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        if character == "{":
            return index
        index += 1
    return -1


def _find_session_failure_enum_open_brace(source: str) -> int:
    index = 0
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        match = SESSION_FAILURE_ENUM_RE.match(source, index)
        if match:
            return _find_next_open_brace(source, match.end())
        index += 1
    return -1


def _parse_enum_constants(body: str) -> set[str]:
    kinds: set[str] = set()
    nesting = 0
    expecting_entry = True
    index = 0
    while index < len(body):
        comment_end = _skip_comment(body, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = body[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(body, index)
            continue
        if nesting == 0 and character == ";":
            break
        if character in "({[":
            nesting += 1
            index += 1
            continue
        if character in ")}]":
            nesting -= 1
            if nesting < 0:
                raise ActionableErrorStateError(
                    "SessionFailureKind enum constants are not balanced"
                )
            index += 1
            continue
        if nesting == 0 and character == ",":
            expecting_entry = True
            index += 1
            continue
        if nesting == 0 and expecting_entry:
            if character.isspace():
                index += 1
                continue
            match = re.match(r"[A-Z][A-Z0-9_]*\b", body[index:])
            if match:
                kinds.add(match.group(0))
                expecting_entry = False
                index += len(match.group(0))
                continue
        index += 1
    if nesting != 0:
        raise ActionableErrorStateError(
            "SessionFailureKind enum constants are not balanced"
        )
    return kinds


def parse_session_failure_kinds(source_path: Path) -> set[str]:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ActionableErrorStateError(
            f"could not read Android SessionFailure source: {error}"
        ) from error
    open_brace_index = _find_session_failure_enum_open_brace(source)
    if open_brace_index == -1:
        raise ActionableErrorStateError(
            "could not find enum class SessionFailureKind body in Android source"
        )
    kinds = _parse_enum_constants(
        _extract_balanced_brace_body(source, open_brace_index)
    )
    if not kinds:
        raise ActionableErrorStateError("SessionFailureKind enum contains no cases")
    return kinds


def _evidence_path(reference: str) -> str | None:
    stripped = reference.strip()
    if not stripped or REMOTE_EVIDENCE_RE.match(stripped):
        return None
    path = stripped.split("#", 1)[0]
    return path or None


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_top_level(matrix: dict[str, Any], errors: list[str]) -> None:
    if matrix.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if matrix.get("kind") != KIND:
        errors.append(f"kind: must be {KIND}")
    if matrix.get("readme_gate_closure") is not False:
        errors.append("readme_gate_closure: must be false for this offline owner slice")
    if not _non_empty_string(matrix.get("owner")):
        errors.append("owner: must be a non-empty string")
    if not _non_empty_string(matrix.get("evidence_boundary")):
        errors.append("evidence_boundary: must be a non-empty string")

    reviewed = matrix.get("reviewed_open_prs")
    if not isinstance(reviewed, list) or not all(isinstance(item, int) for item in reviewed):
        errors.append("reviewed_open_prs: must be an array of PR numbers")
        return
    missing = sorted(REQUIRED_OPEN_PRS.difference(reviewed))
    if missing:
        errors.append(
            "reviewed_open_prs: missing required PR review(s) "
            + ", ".join(f"#{pr}" for pr in missing)
        )


def _validate_state(
    state: dict[str, Any],
    index: int,
    ids: set[str],
    errors: list[str],
    *,
    repository_root: Path | None = None,
) -> None:
    prefix = f"states[{index}]"
    for field in REQUIRED_STATE_FIELDS:
        if field not in state:
            errors.append(f"{prefix}.{field}: is required")

    state_id = state.get("id")
    if not _non_empty_string(state_id):
        errors.append(f"{prefix}.id: must be a non-empty string")
    elif state_id in ids:
        errors.append(f"{prefix}.id: duplicate state id {state_id}")
    else:
        ids.add(state_id)

    if state.get("platform") not in VALID_PLATFORMS:
        errors.append(f"{prefix}.platform: must be android or macos_host")

    for field in (
        "system_state",
        "failed_layer",
        "source_classifier",
        "ui_surface",
        "user_visible_copy",
        "user_action",
    ):
        if not _non_empty_string(state.get(field)):
            errors.append(f"{prefix}.{field}: must be a non-empty string")

    if state.get("retry_behavior") not in VALID_RETRY_BEHAVIORS:
        errors.append(
            f"{prefix}.retry_behavior: must be one of "
            f"{', '.join(sorted(VALID_RETRY_BEHAVIORS))}"
        )
    if state.get("device_evidence_status") not in VALID_EVIDENCE_STATUSES:
        errors.append(
            f"{prefix}.device_evidence_status: must be one of "
            f"{', '.join(sorted(VALID_EVIDENCE_STATUSES))}"
        )
    if state.get("gate_status") not in VALID_GATE_STATUSES:
        errors.append(
            f"{prefix}.gate_status: must be one of "
            f"{', '.join(sorted(VALID_GATE_STATUSES))}"
        )
    if state.get("readme_gate_closure") is not False:
        errors.append(f"{prefix}.readme_gate_closure: must be false")

    offline_evidence = _string_list(state.get("offline_evidence"))
    if not offline_evidence:
        errors.append(f"{prefix}.offline_evidence: must contain at least one reference")
    elif repository_root is not None:
        root = repository_root.resolve()
        for reference in offline_evidence:
            relative_path = _evidence_path(reference)
            if relative_path is None:
                continue
            evidence_path = (root / relative_path).resolve()
            if not _path_is_inside(evidence_path, root) or not evidence_path.exists():
                errors.append(
                    f"{prefix}.offline_evidence: missing repository path {relative_path}"
                )
    if "localizedDescription" == str(state.get("user_visible_copy")).strip():
        errors.append(f"{prefix}.user_visible_copy: must not be a bare localizedDescription")

    android_failure_kinds = state.get("android_session_failure_kinds", [])
    if android_failure_kinds is None:
        android_failure_kinds = []
    if not isinstance(android_failure_kinds, list) or not all(
        isinstance(item, str) and item.strip() for item in android_failure_kinds
    ):
        errors.append(
            f"{prefix}.android_session_failure_kinds: must be a list of non-empty strings"
        )


def evaluate(
    matrix: dict[str, Any],
    *,
    android_session_failure_kinds: set[str] | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    _validate_top_level(matrix, errors)

    states_value = matrix.get("states")
    if not isinstance(states_value, list):
        errors.append("states: must be an array")
        states: list[dict[str, Any]] = []
    else:
        states = []
        for index, item in enumerate(states_value):
            if isinstance(item, dict):
                states.append(item)
            else:
                errors.append(f"states[{index}]: must be an object")

    ids: set[str] = set()
    for index, state in enumerate(states):
        _validate_state(state, index, ids, errors, repository_root=repository_root)

    android_state_ids = _state_id_set(states, "android")
    host_state_ids = _state_id_set(states, "macos_host")
    if len(android_state_ids) < MIN_ANDROID_STATES:
        errors.append(f"states: must contain at least {MIN_ANDROID_STATES} Android states")
    if len(host_state_ids) < MIN_HOST_STATES:
        errors.append(f"states: must contain at least {MIN_HOST_STATES} macOS Host states")

    covered_session_failure_kinds: set[str] = set()
    for state in states:
        for kind in state.get("android_session_failure_kinds", []) or []:
            if isinstance(kind, str) and kind.strip():
                covered_session_failure_kinds.add(kind.strip())
    missing_session_failure_kinds: list[str] = []
    if android_session_failure_kinds is not None:
        missing_session_failure_kinds = sorted(
            android_session_failure_kinds.difference(covered_session_failure_kinds)
        )
        for kind in missing_session_failure_kinds:
            errors.append(f"android_session_failure_kinds: missing {kind}")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "verdict": STATUS_PASS if not errors else STATUS_FAIL,
        "can_close_readme_phase1_actionable_errors_gate": False,
        "matrix_kind": matrix.get("kind") if isinstance(matrix.get("kind"), str) else "",
        "owner": matrix.get("owner") if isinstance(matrix.get("owner"), str) else "",
        "state_count": len(states),
        "android_state_count": len(android_state_ids),
        "macos_host_state_count": len(host_state_ids),
        "reviewed_open_prs": _integer_list(matrix.get("reviewed_open_prs")),
        "covered_android_session_failure_kinds": sorted(covered_session_failure_kinds),
        "missing_android_session_failure_kinds": missing_session_failure_kinds,
        "errors": errors,
        "interpretation": (
            "This offline gate validates matrix ownership and drift coverage only. "
            "It does not prove Android or macOS runtime acceptance and cannot close "
            "the README Phase 1 actionable-errors gate without retained device evidence."
        ),
    }


def _write_report(report: dict[str, Any], output: TextIO) -> None:
    json.dump(report, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the Vibe Screen Phase 1 actionable-error state matrix."
    )
    parser.add_argument("matrix", help="actionable error state matrix JSON file")
    parser.add_argument(
        "--android-session-failure-source",
        help="optional SessionFailure.kt path for enum drift coverage",
    )
    parser.add_argument(
        "--repository-root",
        default=".",
        help=(
            "repository root for validating repository-relative offline evidence "
            "paths (default: current directory)"
        ),
    )
    parser.add_argument("--output", help="output gate JSON file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        matrix = load_matrix(Path(args.matrix))
        session_failure_kinds = None
        if args.android_session_failure_source:
            session_failure_kinds = parse_session_failure_kinds(
                Path(args.android_session_failure_source)
            )
        report = evaluate(
            matrix,
            android_session_failure_kinds=session_failure_kinds,
            repository_root=Path(args.repository_root),
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_report(report, stream)
        else:
            _write_report(report, sys.stdout)
    except (ActionableErrorStateError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if report["verdict"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
