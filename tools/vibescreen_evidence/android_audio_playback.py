"""Summarize Android Protocol v1 audio playback acceptance evidence.

The USB/LAN audio gate closes only when a real macOS Host microphone PCM
capture path is negotiated over Protocol v1 and a named Android device writes
those packets to the production AudioTrack path with audible or
instrumentation-backed playback confirmation. Offline protocol tests, loopback
harnesses, and Android-only logs are diagnostics only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_KIND = "android_audio_playback_acceptance"
GATE_PROFILE = "protocol-v1-android-usb-lan-audio-playback"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
SUPPORTED_TRANSPORTS = frozenset(("usb", "trusted_lan"))
REQUIRED_DEVICE_FIELDS = (
    "adb_serial",
    "manufacturer",
    "model",
    "device",
    "android_release",
    "sdk",
    "build_fingerprint",
)
REQUIRED_ARTIFACT_CATEGORIES = {
    "device": ("device",),
    "host_audio": ("host-audio", "host_audio"),
    "android_audio": ("android-audio", "android_audio", "logcat"),
    "playback_confirmation": ("playback", "audible", "instrument"),
}

REQUIRED_FIELDS = (
    (
        "android_device_lock_acquired",
        "exclusively acquire /tmp/vibe-screen-device-android.lock before using the Android device",
    ),
    (
        "device_identity_recorded",
        "record Android serial, manufacturer, model, codename, Android release, SDK, and build fingerprint",
    ),
    (
        "device_identity_matches_claim",
        "label the evidence with the observed device identity; P0110/pacific evidence must not be relabeled as Xiaomi/fuxi",
    ),
    ("transport_supported", "run the gate over USB or trusted-LAN, not loopback or synthetic transport"),
    ("apk_identity_recorded", "record APK version/signing identity and install timestamp"),
    ("host_build_identity_recorded", "record Host commit, binary hash, and signing identity"),
    (
        "host_stable_signed_tcc_ready",
        "run a stable signed Host with Screen Recording, Accessibility, and Microphone permission ready",
    ),
    ("host_listener_observed", "record the macOS Host listener for the transport under test"),
    (
        "protocol_v1_session_observed",
        "retain logs proving a real production Protocol v1 session, not a loopback or synthetic harness",
    ),
    (
        "audio_capability_negotiated",
        "retain negotiated CAPABILITY_AUDIO and maximum_audio_streams from the active session",
    ),
    (
        "audio_config_accepted",
        "retain AudioConfig and AudioConfigResult.accepted=true for PCM S16LE on the active session",
    ),
    ("host_microphone_capture_started", "retain Host audio_capture_started telemetry/logs"),
    (
        "host_audio_packets_sent",
        "retain Host channel 3 audio packet/frame send evidence for the accepted stream",
    ),
    (
        "android_audio_track_started",
        "retain Android production AudioTrack playback-start evidence for the accepted stream",
    ),
    (
        "android_audio_packets_written",
        "retain Android AudioTrack write evidence for Protocol v1 audio packets",
    ),
    (
        "playback_output_confirmed",
        "record audible output or instrumentation-backed Android playback confirmation from the real device",
    ),
    ("disconnect_cleanup_observed", "retain Host and Android audio cleanup after disconnect or reconfiguration"),
    ("host_logs_retained", "retain Host logs covering negotiation, packet flow, and cleanup"),
    ("android_logs_retained", "retain Android logcat/private diagnostics covering playback writes"),
    (
        "no_synthetic_or_loopback_markers",
        "exclude synthetic harness, loopback-only, Android-only, and plaintext legacy fallback evidence from gate closure",
    ),
)
COMPUTED_REQUIRED_FIELDS = (
    (
        "device_identity_structured",
        "record structured Android serial, manufacturer, model, codename, release, SDK, and build fingerprint fields",
    ),
    (
        "retained_artifacts_available",
        "retain non-empty pass artifacts under the evidence directory for device, Host audio, Android audio, and playback confirmation",
    ),
)

BLOCKING_FIELDS = {
    "android_device_lock_acquired",
    "device_identity_recorded",
    "device_identity_structured",
    "transport_supported",
    "retained_artifacts_available",
    "host_stable_signed_tcc_ready",
    "host_listener_observed",
    "protocol_v1_session_observed",
    "playback_output_confirmed",
}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
ALL_REQUIRED_FIELDS = REQUIRED_FIELDS + COMPUTED_REQUIRED_FIELDS


class AndroidAudioPlaybackEvidenceError(ValueError):
    """Raised when Android audio playback evidence is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise AndroidAudioPlaybackEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise AndroidAudioPlaybackEvidenceError(
            "Android audio playback evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise AndroidAudioPlaybackEvidenceError(f"{field} must be true or false")


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise AndroidAudioPlaybackEvidenceError(f"{field} must be a string")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AndroidAudioPlaybackEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise AndroidAudioPlaybackEvidenceError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _device_record(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("device", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AndroidAudioPlaybackEvidenceError("device must be an object")
    return value


def _device_summary(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    device = _device_record(record)
    normalized: dict[str, Any] = {}
    complete = True
    for field in REQUIRED_DEVICE_FIELDS:
        value = device.get(field)
        if field == "sdk":
            if not isinstance(value, int):
                complete = False
                normalized[field] = None
            else:
                normalized[field] = value
            continue
        if not isinstance(value, str) or not value.strip():
            complete = False
            normalized[field] = ""
        else:
            normalized[field] = value.strip()

    labels = " ".join(str(item).lower() for item in normalized.values())
    has_p0110 = any(marker in labels for marker in ("nubia", "p0110", "pacific"))
    has_fuxi = any(marker in labels for marker in ("xiaomi", "2211133c", "fuxi"))
    if has_p0110 and has_fuxi:
        complete = False
    return normalized, complete


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _artifact_checks(
    record: dict[str, Any], evidence_dir: Path | None
) -> tuple[list[dict[str, Any]], bool]:
    artifacts = _string_list(record, "artifact_paths")
    if not artifacts or evidence_dir is None:
        return [
            {
                "path": artifact,
                "exists": False,
                "non_empty": False,
                "under_evidence_dir": False,
            }
            for artifact in artifacts
        ], False

    root = evidence_dir.resolve()
    checks = []
    categories = {category: False for category in REQUIRED_ARTIFACT_CATEGORIES}
    for artifact in artifacts:
        raw_path = Path(artifact)
        artifact_path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = artifact_path.resolve(strict=False)
        exists = resolved.is_file()
        under_evidence_dir = _is_relative_to(resolved, root)
        non_empty = exists and resolved.stat().st_size > 0
        name = raw_path.name.lower()
        for category, markers in REQUIRED_ARTIFACT_CATEGORIES.items():
            if any(marker in name for marker in markers) and non_empty and under_evidence_dir:
                categories[category] = True
        checks.append(
            {
                "path": artifact,
                "exists": exists,
                "non_empty": non_empty,
                "under_evidence_dir": under_evidence_dir,
            }
        )
    return checks, all(categories.values())


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise AndroidAudioPlaybackEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise AndroidAudioPlaybackEvidenceError("run_id must be a non-empty string")


def _transport_supported(record: dict[str, Any]) -> bool:
    transport = _string_value(record, "transport").strip().lower().replace("-", "_")
    return transport in SUPPORTED_TRANSPORTS


def _observations(
    record: dict[str, Any], *, device_identity_structured: bool, retained_artifacts_available: bool
) -> dict[str, bool]:
    values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    values["transport_supported"] = _transport_supported(record)
    values["device_identity_structured"] = device_identity_structured
    values["retained_artifacts_available"] = retained_artifacts_available
    return values


def summarize(
    record: dict[str, Any], *, run_id: str | None = None, evidence_dir: Path | None = None
) -> dict[str, Any]:
    device, device_identity_structured = _device_summary(record)
    artifact_checks, retained_artifacts_available = _artifact_checks(record, evidence_dir)
    field_values = _observations(
        record,
        device_identity_structured=device_identity_structured,
        retained_artifacts_available=retained_artifacts_available,
    )
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in ALL_REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [item for item in missing if item["field"] in BLOCKING_FIELDS]
    if not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    notes = _string_value(record, "notes")
    blocking_notes = _string_list(record, "blocking_notes")
    if verdict == STATUS_BLOCKED and notes:
        blocking_notes.append(notes)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4()),
        "kind": GATE_KIND,
        "profile": GATE_PROFILE,
        "transport": _string_value(record, "transport").strip().lower().replace("-", "_"),
        "verdict": verdict,
        "can_close_android_audio_playback_gate": verdict == STATUS_PASS,
        "requires_real_android_device": True,
        "requires_audible_or_instrumented_output": True,
        "loopback_or_synthetic_is_not_playback_evidence": True,
        "android_only_logs_are_not_playback_evidence": True,
        "required_device_identity": (
            "Record the actual Android device identity; Nubia P0110/pacific/Android 16/SDK 36 "
            "evidence must not be relabeled as Xiaomi 13/fuxi."
        ),
        "device": device,
        "observations": field_values,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": _string_list(record, "artifact_paths"),
        "artifact_checks": artifact_checks,
        "blocking_notes": blocking_notes,
        "notes": notes,
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen Android Protocol v1 audio playback evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing booleans "
            "default to false so readiness/tooling records cannot close the gate by omission."
        ),
    )
    parser.add_argument("input", help="Android audio playback evidence .json file, or - for stdin")
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument(
        "--evidence-dir",
        help="directory that must contain retained artifact_paths before the gate can pass",
    )
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="return nonzero unless the summary can close the Android audio playback gate",
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
        evidence_dir = Path(args.evidence_dir) if args.evidence_dir else None
        summary = summarize(record, run_id=args.run_id, evidence_dir=evidence_dir)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (AndroidAudioPlaybackEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.require_pass and not summary["can_close_android_audio_playback_gate"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
