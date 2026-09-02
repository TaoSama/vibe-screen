"""Evaluate Phase 1 actionable-error current-base device evidence.

This gate is read-only. It validates retained artifacts and ownership status for
the current-base actionable-error matrix owner. It does not run ADB, launch the
Host, modify macOS TCC, or mutate network/USB state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .actionable_error_states import REQUIRED_ACTIONABLE_STATE_ID_SEQUENCE


MANIFEST_KIND = "phase1_actionable_error_current_base"
REPORT_KIND = "phase1_actionable_error_current_base_gate"
EXPECTED_DEVICE = {
    "adb_serial": "<redacted-adb-serial>",
    "manufacturer": "nubia",
    "model": "P0110",
    "codename": "pacific",
    "android_release": "16",
    "sdk": "36",
}
REDACTED_ADB_SERIAL = EXPECTED_DEVICE["adb_serial"]
SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"EP[0-9A-Z]{12,24}"), "raw ADB serial"),
    (re.compile(r"/Users/[^\s'\"]+"), "local user home path"),
    (re.compile(r"Application Support/com\.apple\.TCC"), "macOS privacy database path"),
    (re.compile(r"\bTCC\.db\b"), "macOS privacy database filename"),
    (re.compile("token" + r"s/", re.IGNORECASE), "token directory"),
    (re.compile("credential" + r"s/", re.IGNORECASE), "credential directory"),
    (re.compile("private" + r"[ -]key", re.IGNORECASE), "sensitive key material"),
)
MANDATORY_MANIFEST_STATE_IDS = (
    "host_screen_recording_denied",
    "accessibility_denied_or_limited",
    "tcp_54321_unavailable",
    "adb_reverse_missing",
    "usb_disconnected",
    "lan_route_unavailable",
    "stale_epoch_or_session_errors",
)
REQUIRED_BLOCKED_UI_STATE_IDS = REQUIRED_ACTIONABLE_STATE_ID_SEQUENCE
REQUIRED_STATE_IDS = MANDATORY_MANIFEST_STATE_IDS + REQUIRED_BLOCKED_UI_STATE_IDS
VALID_STATUSES = frozenset(("pass", "blocked", "insufficient", "not_run"))
VALID_ARTIFACT_KINDS = frozenset(
    (
        "device_identity",
        "repository_snapshot",
        "adb_reverse",
        "host_listener",
        "android_ui_dump",
        "android_logcat",
        "android_private_diag",
        "lan_route_preflight",
        "operator_note",
    )
)
PASS_STATUSES = frozenset(("pass",))
NON_PASS_STATUSES = VALID_STATUSES.difference(PASS_STATUSES)

INTERPRETATION = (
    "A pass means every required Phase 1 actionable-error state has retained "
    "current-base real-device evidence from the exact Nubia P0110/pacific "
    "Android 16 device, with the ADB serial redacted from public reports, and "
    "can close the README actionable-errors gate. "
    "Blocked, insufficient, not-run, offline-only, or relabeled evidence cannot "
    "close that gate."
)


class ActionableErrorCurrentBaseError(ValueError):
    """Raised when current-base evidence cannot be evaluated."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ActionableErrorCurrentBaseError(
            f"could not read current-base manifest {path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise ActionableErrorCurrentBaseError(
            "current-base manifest must be a JSON object"
        )
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _artifact_path(repository_root: Path, raw_path: Any) -> Path | None:
    if not _non_empty_string(raw_path):
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    return (repository_root / path).resolve()


def _validate_top_level(manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if manifest.get("kind") != MANIFEST_KIND:
        errors.append(f"kind: must be {MANIFEST_KIND}")
    if not _non_empty_string(manifest.get("run_id")):
        errors.append("run_id: must be a non-empty string")
    if not _non_empty_string(manifest.get("created_at")):
        errors.append("created_at: must be a non-empty string")
    if not _non_empty_string(manifest.get("evidence_boundary")):
        errors.append("evidence_boundary: must be a non-empty string")
    if not _string_list(manifest.get("notes")):
        errors.append("notes: must contain at least one note")
    close_value = manifest.get("can_close_readme_phase1_actionable_errors_gate")
    if not isinstance(close_value, bool):
        errors.append("can_close_readme_phase1_actionable_errors_gate: must be boolean")

    repository = manifest.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository: must be an object")
    else:
        for field in (
            "name",
            "branch",
            "collected_at_commit",
            "evaluated_at_commit",
            "baseline",
        ):
            if not _non_empty_string(repository.get(field)):
                errors.append(f"repository.{field}: must be a non-empty string")
        if not _string_list(repository.get("notes")):
            errors.append("repository.notes: must contain at least one note")

    device = manifest.get("device")
    if not isinstance(device, dict):
        errors.append("device: must be an object")
    else:
        for field, expected in EXPECTED_DEVICE.items():
            value = device.get(field)
            if not _non_empty_string(value):
                errors.append(f"device.{field}: must be a non-empty string")
            elif field == "adb_serial" and value != REDACTED_ADB_SERIAL:
                errors.append(
                    "device.adb_serial: public current-base evidence must redact the "
                    "ADB serial as <redacted-adb-serial>"
                )
            elif str(value).lower() != expected.lower():
                errors.append(f"device.{field}: expected {expected}, got {value}")


def _validate_public_artifact_text(
    artifact_path: Path,
    display_path: Any,
    prefix: str,
    errors: list[str],
) -> None:
    try:
        data = artifact_path.read_bytes()
    except OSError as error:
        errors.append(f"{prefix}.path: could not read {display_path}: {error}")
        return
    if b"\x00" in data:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    for pattern, label in SENSITIVE_TEXT_PATTERNS:
        if pattern.search(text):
            errors.append(f"{prefix}.path: public artifact contains {label}")


def _validate_artifacts(
    state: dict[str, Any],
    state_index: int,
    repository_root: Path,
    errors: list[str],
) -> list[dict[str, Any]]:
    artifacts_value = state.get("artifacts", [])
    if not isinstance(artifacts_value, list):
        errors.append(f"states[{state_index}].artifacts: must be an array")
        return []

    artifacts: list[dict[str, Any]] = []
    root = repository_root.resolve()
    for artifact_index, artifact_value in enumerate(artifacts_value):
        prefix = f"states[{state_index}].artifacts[{artifact_index}]"
        if not isinstance(artifact_value, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        artifact = artifact_value
        kind = artifact.get("kind")
        if kind not in VALID_ARTIFACT_KINDS:
            errors.append(
                f"{prefix}.kind: must be one of {', '.join(sorted(VALID_ARTIFACT_KINDS))}"
            )
        artifact_path = _artifact_path(root, artifact.get("path"))
        if artifact_path is None:
            errors.append(f"{prefix}.path: must be a non-empty path")
            continue
        if not _path_inside(artifact_path, root):
            errors.append(f"{prefix}.path: must stay inside repository root")
            continue
        if not artifact_path.is_file():
            errors.append(f"{prefix}.path: missing file {artifact.get('path')}")
            continue
        _validate_public_artifact_text(artifact_path, artifact.get("path"), prefix, errors)
        expected_sha = artifact.get("sha256")
        if not _non_empty_string(expected_sha) or len(str(expected_sha)) != 64:
            errors.append(f"{prefix}.sha256: must be a 64-character hex digest")
        else:
            actual_sha = _sha256(artifact_path)
            if actual_sha.lower() != str(expected_sha).lower():
                errors.append(
                    f"{prefix}.sha256: mismatch for {artifact.get('path')} "
                    f"expected {expected_sha} got {actual_sha}"
                )
        if not _non_empty_string(artifact.get("description")):
            errors.append(f"{prefix}.description: must be a non-empty string")
        artifacts.append(artifact)
    return artifacts


def _validate_state(
    state: dict[str, Any],
    index: int,
    ids: set[str],
    repository_root: Path,
    errors: list[str],
) -> dict[str, Any]:
    prefix = f"states[{index}]"
    state_id = state.get("id")
    if not _non_empty_string(state_id):
        errors.append(f"{prefix}.id: must be a non-empty string")
        state_id = f"<invalid-{index}>"
    elif state_id in ids:
        errors.append(f"{prefix}.id: duplicate state id {state_id}")
    else:
        ids.add(str(state_id))

    status = state.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"{prefix}.status: must be one of {', '.join(sorted(VALID_STATUSES))}")
    if not isinstance(state.get("can_close_state"), bool):
        errors.append(f"{prefix}.can_close_state: must be boolean")
    if status in NON_PASS_STATUSES and state.get("can_close_state") is True:
        errors.append(f"{prefix}.can_close_state: non-pass state cannot close")
    if status == "pass" and state.get("can_close_state") is not True:
        errors.append(f"{prefix}.can_close_state: pass state must close")
    if not isinstance(state.get("observed_on_device"), bool):
        errors.append(f"{prefix}.observed_on_device: must be boolean")
    if status == "pass" and state.get("observed_on_device") is not True:
        errors.append(f"{prefix}.observed_on_device: pass state requires device observation")

    for field in ("classification", "owner", "notes"):
        value = state.get(field)
        if field == "notes":
            if not _string_list(value):
                errors.append(f"{prefix}.notes: must contain at least one note")
        elif not _non_empty_string(value):
            errors.append(f"{prefix}.{field}: must be a non-empty string")

    blockers = state.get("blockers", [])
    if blockers is None:
        blockers = []
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        errors.append(f"{prefix}.blockers: must be a list of strings")
        blockers = []
    if status == "blocked" and not _string_list(blockers):
        errors.append(f"{prefix}.blockers: blocked state must list a blocker")
    if status == "pass" and _string_list(blockers):
        errors.append(f"{prefix}.blockers: pass state must not list blockers")

    closure_requirements = state.get("closure_requirements")
    if not _string_list(closure_requirements):
        errors.append(f"{prefix}.closure_requirements: must contain at least one requirement")

    artifacts = _validate_artifacts(state, index, repository_root, errors)
    if status == "pass" and not artifacts:
        errors.append(f"{prefix}.artifacts: pass state requires retained artifacts")

    return {
        "id": str(state_id),
        "status": status if isinstance(status, str) else "invalid",
        "can_close_state": state.get("can_close_state") is True,
        "observed_on_device": state.get("observed_on_device") is True,
        "artifact_count": len(artifacts),
        "blockers": _string_list(blockers),
    }


def evaluate(manifest: dict[str, Any], *, repository_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    _validate_top_level(manifest, errors)
    states_value = manifest.get("states")
    states: list[dict[str, Any]] = []
    if not isinstance(states_value, list):
        errors.append("states: must be an array")
    else:
        for index, state_value in enumerate(states_value):
            if isinstance(state_value, dict):
                states.append(state_value)
            else:
                errors.append(f"states[{index}]: must be an object")

    ids: set[str] = set()
    state_results = [
        _validate_state(state, index, ids, repository_root, errors)
        for index, state in enumerate(states)
    ]
    missing_mandatory_state_ids = sorted(set(MANDATORY_MANIFEST_STATE_IDS).difference(ids))
    missing_blocked_ui_state_ids = sorted(set(REQUIRED_BLOCKED_UI_STATE_IDS).difference(ids))
    unexpected_state_ids = sorted(ids.difference(REQUIRED_STATE_IDS))
    for state_id in missing_mandatory_state_ids:
        errors.append(f"states: missing required state {state_id}")
    for state_id in unexpected_state_ids:
        errors.append(f"states: unexpected state {state_id}")

    required_results = [item for item in state_results if item["id"] in REQUIRED_STATE_IDS]
    all_required_passed = (
        len(required_results) == len(REQUIRED_STATE_IDS)
        and all(item["status"] == "pass" and item["can_close_state"] for item in required_results)
    )
    manifest_claims_close = manifest.get("can_close_readme_phase1_actionable_errors_gate") is True
    if manifest_claims_close and not all_required_passed:
        errors.append(
            "can_close_readme_phase1_actionable_errors_gate: cannot be true "
            "until all required states pass"
        )

    blocked_state_ids = sorted(
        item["id"] for item in required_results if item["status"] == "blocked"
    )
    blocked_state_ids.extend(missing_blocked_ui_state_ids)
    blocked_state_ids = sorted(set(blocked_state_ids))
    insufficient_state_ids = sorted(
        item["id"]
        for item in required_results
        if item["status"] in {"insufficient", "not_run"}
    )

    missing_close_claim = all_required_passed and not manifest_claims_close
    if missing_close_claim:
        insufficient_state_ids.append("readme_gate_closure_claim")
        insufficient_state_ids.sort()

    if errors:
        verdict = "fail"
    elif blocked_state_ids:
        verdict = "blocked"
    elif insufficient_state_ids or not all_required_passed:
        verdict = "insufficient"
    else:
        verdict = "pass"

    reasons: list[str] = []
    reasons.extend(f"blocked: {state_id}" for state_id in blocked_state_ids)
    reasons.extend(f"insufficient: {state_id}" for state_id in insufficient_state_ids)
    reasons.extend(f"fail: {error}" for error in errors)

    device = manifest.get("device") if isinstance(manifest.get("device"), dict) else {}
    repository = manifest.get("repository") if isinstance(manifest.get("repository"), dict) else {}
    can_close = not errors and all_required_passed and manifest_claims_close
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "run_id": manifest.get("run_id") if isinstance(manifest.get("run_id"), str) else None,
        "source": {
            "manifest": str(manifest.get("source_manifest", "")),
            "repository_name": repository.get("name", ""),
            "collected_at_commit": repository.get("collected_at_commit", ""),
            "evaluated_at_commit": repository.get("evaluated_at_commit", ""),
        },
        "device_identity": {
            field: device.get(field, "") for field in EXPECTED_DEVICE
        },
        "required_state_ids": list(REQUIRED_STATE_IDS),
        "state_results": state_results,
        "blocked_state_ids": blocked_state_ids,
        "insufficient_state_ids": insufficient_state_ids,
        "errors": errors,
        "reasons": reasons,
        "can_close_readme_phase1_actionable_errors_gate": can_close,
        "interpretation": INTERPRETATION,
    }


def _failure_report(manifest_path: Path, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "derivation_status": "failed",
        "verdict": "fail",
        "run_id": None,
        "source": {
            "manifest": str(manifest_path),
            "repository_name": "",
            "collected_at_commit": "",
            "evaluated_at_commit": "",
        },
        "device_identity": {field: "" for field in EXPECTED_DEVICE},
        "required_state_ids": list(REQUIRED_STATE_IDS),
        "state_results": [],
        "blocked_state_ids": [],
        "insufficient_state_ids": [],
        "errors": [reason],
        "reasons": [f"fail: {reason}"],
        "can_close_readme_phase1_actionable_errors_gate": False,
        "interpretation": INTERPRETATION,
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
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="return 0 for blocked or insufficient reports while still failing malformed evidence",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        manifest["source_manifest"] = str(args.manifest)
        report = evaluate(manifest, repository_root=args.repository_root)
    except (ActionableErrorCurrentBaseError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.manifest, str(error))
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: actionable-error current-base gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    verdict = report.get("verdict")
    if verdict == "pass" or (args.allow_blocked and verdict in {"blocked", "insufficient"}):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
