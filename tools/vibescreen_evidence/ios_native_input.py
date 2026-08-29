"""Summarize iOS native-input behavior evidence without overstating it.

This gate is owned by the Phase 5 iOS native-input behavior track. It can only
close when signed iPhone and iPad app runs drive the production touch,
keyboard, and hover/pointer paths against a Host session and retained logs
prove the targeted input reached the selected display stream.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_OWNER = "phase5-ios-native-input-behavior"
GATE_PROFILE = "ios-native-input-behavior"
OWNER_ROLE = "ios_native_input_behavior_current_base_owner"
OWNER_BRANCH = "codex/ios-native-input-readiness-gate"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAIL = "fail"
EXIT_STATUS_BY_VERDICT = {
    STATUS_PASS: 0,
    STATUS_BLOCKED: 2,
    STATUS_INSUFFICIENT: 1,
    STATUS_FAIL: 3,
}
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
DISALLOWED_TEXT_PATTERNS = (
    re.compile(r"\b(?:android|adb|xiaomi|fuxi|nubia|p0110|pacific|mediacodec)\b", re.IGNORECASE),
    re.compile(r"\b(?:simulator|iphonesimulator|unsigned|ad-hoc|adhoc|synthetic)\b", re.IGNORECASE),
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

REQUIRED_FIELDS = (
    ("ios_device_lock_acquired", "exclusively reserve the iPhone and iPad used for this run"),
    ("device_identity_recorded", "record iPhone and iPad model, OS/build, and device family"),
    ("device_is_iphone_or_ipad", "run on real iPhone and iPad hardware, not Simulator"),
    ("iphone_native_input_observed", "record native-input behavior from a signed iPhone app run"),
    ("ipad_native_input_observed", "record native-input behavior from a signed iPad app run"),
    ("app_revision_recorded", "record the iOS app source revision and dirty-tree state"),
    ("signed_app_installed", "install a signed app build on the recorded iOS device"),
    ("local_network_permission_recorded", "record the Local Network permission result"),
    ("baseline_machost_listener_observed", "record the baseline MacHost listener and build identity"),
    ("protocol_session_negotiated", "capture SSWA/SSWR, upgrade, Hello, SessionAccepted, and display start"),
    ("input_capabilities_negotiated", "negotiate touch, keyboard, pointer, and USB HID modifier-byte capabilities as applicable"),
    ("display_stream_binding_recorded", "record the selected display ID and stream ID used by input events"),
    ("touch_tap_observed", "observe a real touch tap forwarded from the iOS app"),
    ("touch_drag_observed", "observe a real touch drag forwarded from the iOS app"),
    ("hardware_keyboard_attached", "attach and identify a physical iOS hardware keyboard"),
    ("keyboard_press_release_observed", "prove key-down and key-up forwarding for the same USB HID usage"),
    ("keyboard_modifier_observed", "prove a modifier or shortcut uses the negotiated USB HID modifier byte"),
    ("keyboard_modifier_release_no_leak_observed", "prove modifiers clear after release and do not leak into a later plain key"),
    ("hover_pointer_accessory_attached", "attach and identify a real iOS hover/pointer accessory"),
    ("hover_pointer_move_observed", "observe hover or pointer movement over the selected stream"),
    ("host_input_acknowledgements_retained", "retain Host-side acknowledgements or logs for every input family"),
    ("ios_logs_retained", "retain sanitized iOS app/device logs for the input workflow"),
    ("host_logs_retained", "retain sanitized Host logs for the input workflow"),
)

BLOCKING_FIELDS = {
    "ios_device_lock_acquired",
    "device_identity_recorded",
    "device_is_iphone_or_ipad",
    "iphone_native_input_observed",
    "ipad_native_input_observed",
    "signed_app_installed",
    "baseline_machost_listener_observed",
    "hardware_keyboard_attached",
    "hover_pointer_accessory_attached",
}

DISALLOWED_EVIDENCE_FIELDS = {
    "android_evidence_used_for_ios_input": "Android evidence cannot close iOS native-input behavior",
    "simulator_evidence_used_for_ios_input": "Simulator evidence cannot close real iOS native-input behavior",
    "offline_tests_used_as_device_evidence": "offline tests are readiness evidence only, not device behavior",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS) + tuple(
    DISALLOWED_EVIDENCE_FIELDS
)


class IOSNativeInputEvidenceError(ValueError):
    """Raised when an iOS native-input evidence record is malformed."""


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


def repository_state(repo: Path | None) -> dict[str, Any]:
    if repo is None:
        return {"commit": None, "dirty": None}
    revision = _run_git(repo, ["rev-parse", "HEAD"])
    status = _run_git(repo, ["status", "--porcelain=v1", "--untracked-files=all"])
    return {
        "commit": revision.lower() if isinstance(revision, str) and COMMIT_RE.fullmatch(revision) else None,
        "dirty": bool(status) if status is not None else None,
    }


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise IOSNativeInputEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise IOSNativeInputEvidenceError(
            "iOS native-input evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise IOSNativeInputEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IOSNativeInputEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise IOSNativeInputEvidenceError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _disallowed_text_finding(value: str, field: str) -> dict[str, str] | None:
    if any(pattern.search(value) for pattern in DISALLOWED_TEXT_PATTERNS):
        return {
            "field": field,
            "reason": "public native-input evidence text must be sanitized and iOS-only",
        }
    return None


def _artifact_paths(record: dict[str, Any], evidence_dir: Path | None = None) -> list[str]:
    paths = _string_list(record, "artifact_paths")
    for index, reference in enumerate(paths):
        path = Path(reference)
        if path.is_absolute():
            raise IOSNativeInputEvidenceError(
                f"artifact_paths[{index}] must be repository-relative"
            )
        if ".." in path.parts:
            raise IOSNativeInputEvidenceError(
                f"artifact_paths[{index}] must stay inside the evidence bundle"
            )
        if evidence_dir is not None and not (evidence_dir / path).is_file():
            raise IOSNativeInputEvidenceError(
                f"artifact_paths[{index}] does not exist under the evidence bundle"
            )
    return paths


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise IOSNativeInputEvidenceError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSNativeInputEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise IOSNativeInputEvidenceError("run_id must be a non-empty string")


def summarize(
    record: dict[str, Any],
    *,
    run_id: str | None = None,
    repo: Path | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_paths = _artifact_paths(record, evidence_dir=evidence_dir)
    blocking_notes = _string_list(record, "blocking_notes")
    notes = _string_value(record, "notes")
    input_run_id = _explicit_run_id(run_id) or _optional_run_id(record)
    observations = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not observations[field]
    ]
    if not artifact_paths:
        missing.append(
            {
                "field": "artifact_paths",
                "requirement": "retain sanitized iOS and Host native-input artifacts under the evidence bundle",
            }
        )
    disallowed_evidence = [
        {"field": field, "reason": reason}
        for field, reason in DISALLOWED_EVIDENCE_FIELDS.items()
        if observations[field]
    ]
    public_text_values = [
        ("artifact_paths", artifact) for artifact in artifact_paths
    ] + [("blocking_notes", note) for note in blocking_notes]
    if notes:
        public_text_values.append(("notes", notes))
    if input_run_id:
        public_text_values.append(("run_id", input_run_id))
    for field, value in public_text_values:
        finding = _disallowed_text_finding(value, field)
        if finding is not None:
            disallowed_evidence.append(finding)
    contaminated_fields = {item["field"] for item in disallowed_evidence}
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]

    if disallowed_evidence:
        verdict = STATUS_FAIL
    elif not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": input_run_id
        if input_run_id and not _disallowed_text_finding(input_run_id, "run_id")
        else str(uuid.uuid4()),
        "kind": "ios_native_input_behavior",
        "profile": GATE_PROFILE,
        "gate_owner": GATE_OWNER,
        "owner": {
            "role": OWNER_ROLE,
            "head_ref": OWNER_BRANCH,
            "pull_request": "#257",
            "repository": REPOSITORY_FULL_NAME,
            "scope": "README Phase 5 iOS native-input behavior gate",
        },
        "current_base": repository_state(repo),
        "verdict": verdict,
        "can_close_ios_native_input_gate": verdict == STATUS_PASS,
        "requires_real_ios_device": True,
        "requires_signed_app": True,
        "requires_physical_keyboard": True,
        "requires_hover_or_pointer_accessory": True,
        "android_evidence_is_not_ios_input_evidence": True,
        "simulator_is_not_ios_input_evidence": True,
        "offline_tests_are_readiness_only": True,
        "observations": observations,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "disallowed_evidence": disallowed_evidence,
        "artifact_paths": [] if "artifact_paths" in contaminated_fields else artifact_paths,
        "blocking_notes": []
        if "blocking_notes" in contaminated_fields
        else blocking_notes,
        "notes": "" if "notes" in contaminated_fields else notes,
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen iOS native-input behavior evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing "
            "booleans default to false so absent iOS hardware, signed install, "
            "physical accessory, or Host acknowledgement evidence cannot close "
            "the gate."
        ),
    )
    parser.add_argument(
        "input", help="iOS native-input observations .json file, or - for stdin"
    )
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="repository root used to bind current-base provenance",
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="return nonzero unless the evidence verdict is pass",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(args.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        evidence_dir = None if args.input == "-" else Path(args.input).resolve().parent
        summary = summarize(
            record,
            run_id=args.run_id,
            repo=args.repo.resolve(),
            evidence_dir=evidence_dir,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (IOSNativeInputEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.require_pass:
        return EXIT_STATUS_BY_VERDICT[summary["verdict"]]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
