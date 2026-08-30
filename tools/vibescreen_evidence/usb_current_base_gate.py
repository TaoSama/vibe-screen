"""Evaluate Android USB current-base real-device evidence.

This gate is deliberately read-only. It consumes retained artifacts already
collected by the existing USB smoke preflight / live smoke helpers and Host
readiness reports, then decides whether the current base has real-device USB
Protocol v1 evidence that can close the general Android USB/Protocol v1 gate.
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

MANIFEST_KIND = "android_usb_current_base"
REPORT_KIND = "android_usb_current_base_gate"
OWNER_PR = 457  # USB current-base owner PR
EXPECTED_DEVICE = {
    "adb_serial": "<redacted-adb-serial>",
    "manufacturer": "nubia",
    "model": "P0110",
    "device": "pacific",
    "android_release": "16",
    "sdk": "36",
}
VALID_ARTIFACT_KINDS = frozenset(
    (
        "repository_snapshot",
        "usb_smoke_preflight",
        "usb_live_smoke",
        "host_readiness",
        "device_identity",
        "privacy_scan",
    )
)
REQUIRED_ARTIFACT_KINDS = frozenset(
    (
        "repository_snapshot",
        "usb_smoke_preflight",
        "usb_live_smoke",
        "host_readiness",
        "device_identity",
    )
)
STATUSES = frozenset(("pass", "blocked", "insufficient", "fail"))
SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"\bEP[0-9A-Z]{12,24}\b", re.IGNORECASE), "raw ADB serial"),
    (re.compile(r"/Users/[^\s'\"]+"), "local user home path"),
    (re.compile(r"Application Support/com\.apple\.TCC", re.IGNORECASE), "macOS privacy database path"),
    (re.compile(r"\bTCC\.db\b", re.IGNORECASE), "macOS privacy database filename"),
    (re.compile("token" + r"s/", re.IGNORECASE), "token directory"),
    (re.compile("credential" + r"s/", re.IGNORECASE), "credential directory"),
    (re.compile("private" + r"[ -]key", re.IGNORECASE), "sensitive key material"),
)

INTERPRETATION = (
    "A pass means the current base has retained real-device USB evidence from "
    "the exact Nubia P0110/pacific Android 16 device: strict USB smoke preflight "
    "ready, read-only USB live smoke pass, current-source Host readiness, and "
    "retained structured device identity with public serial redaction. "
    "Blocked, insufficient, historical, offline, or relabeled evidence cannot "
    "close the README Android USB current-base / Protocol v1 general Android gate."
)


class UsbCurrentBaseError(ValueError):
    """Raised when current-base evidence cannot be evaluated."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsbCurrentBaseError(f"cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise UsbCurrentBaseError(f"{path} must be a JSON object")
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


def _artifact_path(root: Path, raw_path: Any) -> Path | None:
    if not _non_empty_string(raw_path):
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def _validate_public_artifact(path: Path, display_path: Any, prefix: str, errors: list[str]) -> None:
    try:
        data = path.read_bytes()
    except OSError as error:
        errors.append(f"{prefix}: could not read {display_path}: {error}")
        return
    if b"\x00" in data:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    for pattern, label in SENSITIVE_TEXT_PATTERNS:
        if pattern.search(text):
            errors.append(f"{prefix}: public artifact contains {label}")


def _required_artifact_paths(artifacts: Sequence[dict[str, Any]]) -> dict[str, Path | None]:
    by_kind: dict[str, Path | None] = {}
    for artifact in artifacts:
        kind = str(artifact.get("kind"))
        path = artifact.get("path")
        by_kind[kind] = Path(path).resolve() if _non_empty_string(path) else None
    return by_kind


def _validate_required_artifact_semantics(
    artifacts: Sequence[dict[str, Any]],
    manifest_state: dict[str, Any],
    errors: list[str],
) -> None:
    paths = _required_artifact_paths(artifacts)
    live_path = paths.get("usb_live_smoke")
    if live_path is None:
        return
    try:
        live = json.loads(live_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        errors.append(f"usb_live_smoke: cannot read semantic evidence {live_path}: {error}")
        return
    if not isinstance(live, dict):
        errors.append("usb_live_smoke: must be a JSON object")
        return
    if live.get("kind") != "android_usb_live_smoke":
        errors.append("usb_live_smoke.kind: must be android_usb_live_smoke")
    if live.get("verdict") not in STATUSES:
        errors.append("usb_live_smoke.verdict: must be pass, blocked, insufficient, or fail")
    claims = live.get("claims")
    if not isinstance(claims, dict):
        errors.append("usb_live_smoke.claims: must be an object")
        return
    state_live = manifest_state.get("usb_live_smoke")
    attempting_pass = (
        isinstance(state_live, dict)
        and state_live.get("observed") is True
        and not _string_list(manifest_state.get("blockers"))
    )
    if attempting_pass:
        if live.get("verdict") != "pass":
            errors.append(
                "usb_live_smoke.verdict: retained usb_live_smoke must be pass when manifest state requests a pass"
            )
        if claims.get("live_usb_stream_observed") is not True:
            errors.append(
                "usb_live_smoke.claims.live_usb_stream_observed: retained usb_live_smoke must observe a live USB stream"
            )


def _validate_repository_snapshot_semantics(
    artifacts: Sequence[dict[str, Any]],
    repository_root: Path,
    expected_current_main_sha: str,
    errors: list[str],
) -> None:
    snapshot_path = _required_artifact_paths(artifacts).get("repository_snapshot")
    if snapshot_path is None:
        return
    candidates = {"git-origin-main.txt", "git-head.txt", "source-baseline.txt"}
    snapshot_dir = snapshot_path.parent
    current_main_shas: list[str] = []
    for candidate in candidates:
        candidate_path = snapshot_dir / candidate
        try:
            text = candidate_path.read_text(encoding="utf-8")
        except OSError:
            continue
        current_main_shas.extend(
            match.group(1)
            for line in text.splitlines()
            if (match := re.search(r"\b([0-9a-fA-F]{40})\b", line))
        )
    if not current_main_shas:
        errors.append("repository_snapshot: retained snapshot does not record the current main SHA")
        return
    normalized = {sha.lower() for sha in current_main_shas}
    if expected_current_main_sha.lower() not in normalized:
        errors.append(
            "repository.current_main_sha: retained repository snapshot does not match manifest current_main_sha"
        )


def _validate_pass_provenance_semantics(
    artifacts: Sequence[dict[str, Any]],
    expected_current_main_sha: str,
    manifest_state: dict[str, Any],
    errors: list[str],
) -> None:
    state_live = manifest_state.get("usb_live_smoke")
    attempting_pass = (
        isinstance(state_live, dict)
        and state_live.get("observed") is True
        and not _string_list(manifest_state.get("blockers"))
    )
    if not attempting_pass:
        return
    paths = _required_artifact_paths(artifacts)
    host_path = paths.get("host_readiness")
    if host_path is not None:
        try:
            host = json.loads(host_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"host_readiness: cannot read retained provenance {host_path}: {error}")
            host = None
        if isinstance(host, dict):
            host_provenance = host.get("host")
            if isinstance(host_provenance, dict):
                commit = host_provenance.get("current_source_commit")
                if commit != expected_current_main_sha:
                    errors.append(
                        "host_readiness.host.current_source_commit: retained host readiness must match manifest current_main_sha when claiming a pass"
                    )
                if host_provenance.get("current_source_dirty") is True:
                    errors.append(
                        "host_readiness.host.current_source_dirty: retained host readiness must not be dirty when claiming a pass"
                    )
            else:
                errors.append("host_readiness.host: retained host readiness must include source provenance when claiming a pass")
        else:
            errors.append("host_readiness: retained host readiness must be a JSON object when claiming a pass")
    preflight_path = paths.get("usb_smoke_preflight")
    if preflight_path is None:
        return
    command_ledger = preflight_path.with_name("usb-smoke-preflight.command.txt")
    try:
        text = command_ledger.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"usb_smoke_preflight.command: cannot read retained command ledger {command_ledger}: {error}")
        return
    if len(re.findall(r"\b([0-9a-fA-F]{40})\b", text)) != 1:
        errors.append("usb_smoke_preflight.command: retained command ledger must contain exactly one current-main SHA when claiming a pass")
        return
    match = re.search(r"\b([0-9a-fA-F]{40})\b", text)
    if match and match.group(1).lower() != expected_current_main_sha.lower():
        errors.append(
            "usb_smoke_preflight.command: retained command ledger Base must match manifest current_main_sha when claiming a pass"
        )


def _validate_artifacts(manifest: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    artifacts_value = manifest.get("artifacts", [])
    errors: list[str] = []
    artifacts: list[dict[str, Any]] = []
    kinds = set()
    root = repository_root.resolve()
    if not isinstance(artifacts_value, list):
        errors.append("artifacts: must be an array")
    else:
        for index, artifact_value in enumerate(artifacts_value):
            prefix = f"artifacts[{index}]"
            if not isinstance(artifact_value, dict):
                errors.append(f"{prefix}: must be an object")
                continue
            kind = artifact_value.get("kind")
            if kind not in VALID_ARTIFACT_KINDS:
                errors.append(f"{prefix}.kind: must be one of {', '.join(sorted(VALID_ARTIFACT_KINDS))}")
            else:
                kinds.add(str(kind))
            path = _artifact_path(root, artifact_value.get("path"))
            if path is None:
                errors.append(f"{prefix}.path: must be a non-empty path")
                continue
            if not _path_inside(path, root):
                errors.append(f"{prefix}.path: must stay inside repository root")
                continue
            if not path.is_file():
                errors.append(f"{prefix}.path: missing file {artifact_value.get('path')}")
                continue
            _validate_public_artifact(path, artifact_value.get("path"), prefix, errors)
            expected_sha = artifact_value.get("sha256", "")
            if not _non_empty_string(expected_sha) or len(str(expected_sha)) != 64:
                errors.append(f"{prefix}.sha256: must be a 64-character hex digest")
            elif _sha256(path).lower() != str(expected_sha).lower():
                errors.append(f"{prefix}.sha256: mismatch for {artifact_value.get('path')}")
            if not _non_empty_string(artifact_value.get("description")):
                errors.append(f"{prefix}.description: must be a non-empty string")
            artifacts.append(
                {
                    "kind": str(kind),
                    "path": artifact_value.get("path"),
                    "resolved_path": str(path),
                }
            )
    missing = sorted(REQUIRED_ARTIFACT_KINDS.difference(kinds))
    for kind in missing:
        errors.append(f"artifacts: missing required kind {kind}")
    if not errors:
        _validate_required_artifact_semantics(
            artifacts,
            manifest.get("state", {}),
            errors,
        )
        _validate_repository_snapshot_semantics(
            artifacts,
            repository_root,
            str(manifest.get("repository", {}).get("current_main_sha", "")),
            errors,
        )
        _validate_pass_provenance_semantics(
            artifacts,
            str(manifest.get("repository", {}).get("current_main_sha", "")),
            manifest.get("state", {}),
            errors,
        )
    return {"errors": errors, "artifacts": artifacts}


def _validate_device(manifest: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    device = manifest.get("device")
    if not isinstance(device, dict):
        errors.append("device: must be an object")
        return {}
    for field, expected in EXPECTED_DEVICE.items():
        value = device.get(field)
        if not _non_empty_string(value):
            errors.append(f"device.{field}: must be a non-empty string")
        elif field == "adb_serial" and value != "<redacted-adb-serial>":
            errors.append("device.adb_serial: public current-base evidence must redact the ADB serial")
        elif str(value).lower() != expected.lower() and not (field == "sdk" and str(value).isdigit() and int(value) == int(expected)):
            errors.append(f"device.{field}: expected {expected}, got {value}")
    return device


def _validate_repository(manifest: dict[str, Any], errors: list[str]) -> None:
    repository = manifest.get("repository")
    if not isinstance(repository, dict):
        errors.append("repository: must be an object")
        return
    for field in ("branch", "current_main_sha"):
        if not _non_empty_string(repository.get(field)):
            errors.append(f"repository.{field}: must be a non-empty string")
    current_main = str(repository.get("current_main_sha", ""))
    if not re.fullmatch(r"[0-9a-fA-F]{40}", current_main):
        errors.append("repository.current_main_sha: must be a 40-character Git SHA")
    if repository.get("dirty") is not False:
        errors.append("repository.dirty: current-base evidence must be collected from a clean worktree")
    if not isinstance(repository.get("notes"), list) or not all(bool(x) for x in repository.get("notes", [])):
        errors.append("repository.notes: must contain at least one note")


def _validate_top_level(manifest: dict[str, Any], errors: list[str]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version: must be vibescreen.evidence/v1")
    if manifest.get("kind") != MANIFEST_KIND:
        errors.append(f"kind: must be {MANIFEST_KIND}")
    if not _non_empty_string(manifest.get("run_id")):
        errors.append("run_id: must be a non-empty string")
    if not _non_empty_string(manifest.get("created_at")):
        errors.append("created_at: must be a non-empty string")
    if not _string_list(manifest.get("notes")):
        errors.append("notes: must contain at least one note")
    close = manifest.get("can_close_readme_android_usb_current_base_gate")
    if not isinstance(close, bool):
        errors.append("can_close_readme_android_usb_current_base_gate: must be boolean")
    if close is True:
        errors.append("can_close_readme_android_usb_current_base_gate: cannot be true in a non-passing current-base record")


def _validate_gate_state(manifest: dict[str, Any], errors: list[str]) -> tuple[str, list[str], list[str]]:
    state = manifest.get("state")
    if not isinstance(state, dict):
        errors.append("state: must be an object")
        return "fail", list(errors), []
    usb_preflight = state.get("usb_preflight")
    usb_live = state.get("usb_live_smoke")
    host = state.get("host_readiness")
    blockers = _string_list(state.get("blockers"))
    observed_pass = all(
        isinstance(record, dict) and record.get("observed") is True
        for record in (usb_preflight, usb_live, host)
    )
    if observed_pass:
        if blockers:
            errors.append("state.blockers: pass record must not list blockers")
        verdict = "pass"
    elif blockers:
        verdict = "blocked"
    elif not errors:
        verdict = "insufficient"
    else:
        verdict = "fail"
    return verdict, list(errors), blockers


def evaluate(manifest: dict[str, Any], *, repository_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    _validate_top_level(manifest, errors)
    _validate_repository(manifest, errors)
    _validate_device(manifest, errors)
    artifact_result = _validate_artifacts(manifest, repository_root)
    errors.extend(artifact_result["errors"])
    if errors:
        verdict = "blocked" if any("missing required kind" in error for error in errors) else "fail"
        blockers = _string_list(manifest.get("state", {}).get("blockers")) if isinstance(manifest.get("state"), dict) else []
    else:
        computed_verdict, computed_errors, computed_blockers = _validate_gate_state(manifest, errors)
        verdict = computed_verdict
        blockers = computed_blockers

    requirements = {
        "repository_current_main_verified": bool(
            manifest.get("repository", {}).get("current_main_sha")
        )
        and manifest.get("repository", {}).get("dirty") is False,
        "device_identity_recorded": bool(manifest.get("device")),
        "required_artifacts_available": bool(
            artifact_result["artifacts"]
            and {artifact["kind"] for artifact in artifact_result["artifacts"]}
            >= REQUIRED_ARTIFACT_KINDS
        ),
        "public_evidence_sanitized": not errors,
        "state_observed": verdict == "pass",
    }
    missing = [field for field, value in requirements.items() if not value]
    can_close = not errors and verdict == "pass" and not missing
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "derivation_status": "complete" if not errors else "failed",
        "verdict": verdict,
        "run_id": manifest.get("run_id"),
        "owner_pr": OWNER_PR,
        "current_main_sha": manifest.get("repository", {}).get("current_main_sha"),
        "can_close_readme_android_usb_current_base_gate": can_close,
        "can_claim_current_base_usb_pass": can_close,
        "requirements": requirements,
        "missing_requirements": missing,
        "blockers": blockers,
        "errors": errors,
        "reasons": [
            *[f"blocked: {blocker}" for blocker in blockers],
            *[f"fail: {error}" for error in errors],
            *[f"insufficient: {item}" for item in missing],
        ],
        "interpretation": INTERPRETATION,
    }


def _failure_report(manifest_path: Path, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "derivation_status": "failed",
        "verdict": "fail",
        "run_id": None,
        "owner_pr": OWNER_PR,
        "current_main_sha": None,
        "can_close_readme_android_usb_current_base_gate": False,
        "can_claim_current_base_usb_pass": False,
        "requirements": {},
        "missing_requirements": ["manifest_invalid"],
        "blockers": [],
        "errors": [reason],
        "reasons": [f"fail: {reason}"],
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
        help="return 0 for blocked records while preserving fail-closed evidence",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _load_json(args.manifest)
        report = evaluate(manifest, repository_root=args.repository_root)
    except (UsbCurrentBaseError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.manifest, str(error))
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: USB current-base gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    verdict = report.get("verdict")
    if verdict == "pass" or (args.allow_blocked and verdict == "blocked"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
