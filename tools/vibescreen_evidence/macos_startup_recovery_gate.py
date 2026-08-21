"""Summarize macOS login, headless startup, and recovery gate evidence.

This verifier is intentionally evidence-only. It does not register a login
item, reboot the Mac, start the Host, or run ADB. A passing summary requires
raw integration artifacts proving that macOS launched the installed app after
login/reboot, that the configured startup path rendered from the intended
headless display setup, that unattended listener recovery was bounded, and
that the Android client reconnected within the Phase 1 target.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "phase1-macos-login-headless-recovery"
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
P0110_ANDROID_SCOPE = (
    "Nubia P0110/pacific/Android 16/SDK 36 evidence may support only the "
    "Android reconnect endpoint of this gate; it does not prove macOS "
    "Launch at Login, reboot launch, or headless display behavior."
)

REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    (
        "stable_signed_host_identity_recorded",
        "record the installed /Applications/Vibe Screen.app bundle identity, signing identity, CDHash, and binary SHA-256",
    ),
    (
        "screen_recording_permission_recorded",
        "record Screen Recording authorization for the installed Host identity",
    ),
    (
        "accessibility_permission_recorded",
        "record Accessibility authorization when validating window return or input recovery",
    ),
    (
        "launch_at_login_enabled_not_approval_required",
        "record that Launch at Login is enabled and not waiting for System Settings approval",
    ),
    (
        "macos_reboot_or_logout_login_performed",
        "perform a real macOS logout/login or reboot after enabling Launch at Login",
    ),
    (
        "login_launch_timestamp_recorded",
        "retain a timestamped Host launch log from after the login/reboot boundary",
    ),
    (
        "manual_launch_excluded",
        "show the run was not started by manually opening the app from Finder, Dock, or CLI",
    ),
    (
        "startup_mode_recorded",
        "record the configured startup transport/display mode used by automatic startup",
    ),
    (
        "host_listener_started_without_user_action",
        "observe the Host listener starting after login without a post-login user click",
    ),
    (
        "automatic_stream_start_observed",
        "observe the configured automatic stream start path after login",
    ),
    (
        "headless_configuration_recorded",
        "record the intended headless display setup: physical monitor, dummy plug, or Screen Sharing virtual display",
    ),
    (
        "headless_display_identity_recorded",
        "record the post-login display UUID and logical/physical dimensions for the headless setup",
    ),
    (
        "headless_capture_first_frame_observed",
        "observe a first captured frame from the selected headless display setup",
    ),
    (
        "unattended_failure_trigger_recorded",
        "state the forced unattended failure trigger: listener startup failure, capture stop, client disconnect, or display disappearance",
    ),
    (
        "recovery_retry_schedule_observed",
        "retain logs showing the scheduled recovery retry delays",
    ),
    (
        "recovery_bounded_exhaustion_or_success_observed",
        "retain logs showing either successful recovery or bounded exhaustion after the maximum attempts",
    ),
    (
        "no_full_speed_retry_loop_observed",
        "prove recovery did not loop at full speed",
    ),
    (
        "android_device_lock_acquired",
        "exclusively acquire /tmp/vibe-screen-device-android.lock before using the Android device",
    ),
    (
        "android_device_identity_recorded",
        "record Android serial, manufacturer, model, codename, Android version, SDK, and ABI",
    ),
    (
        "android_device_identity_matches_claim",
        "label Android evidence with the observed identity, without relabeling P0110/pacific as Xiaomi/fuxi",
    ),
    (
        "android_reconnect_within_3s_observed",
        "measure reconnect completion within three seconds after the forced interruption",
    ),
    (
        "android_post_reconnect_render_observed",
        "observe rendered Android client frames after reconnect, not only process liveness",
    ),
    (
        "host_logs_retained",
        "retain Host logs covering login startup, listener start, display capture, recovery, and reconnect",
    ),
    (
        "android_logs_retained",
        "retain Android logcat/diagnostics covering reconnect timing and post-reconnect rendering",
    ),
    (
        "raw_artifacts_retained",
        "retain raw evidence artifacts rather than only a prose summary",
    ),
)
REQUIRED_ANDROID_DEVICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("serial", "record the Android device serial used for adb -s"),
    ("manufacturer", "record the Android device manufacturer"),
    ("model", "record the Android device model"),
    ("codename", "record the Android device codename"),
    ("android_version", "record the Android OS version"),
    ("sdk", "record the Android SDK version"),
    ("abi", "record the Android device ABI"),
)

LOGIN_ITEM_FIELDS = (
    "stable_signed_host_identity_recorded",
    "screen_recording_permission_recorded",
    "launch_at_login_enabled_not_approval_required",
    "macos_reboot_or_logout_login_performed",
    "login_launch_timestamp_recorded",
    "manual_launch_excluded",
)
AUTOMATIC_STARTUP_FIELDS = (
    *LOGIN_ITEM_FIELDS,
    "startup_mode_recorded",
    "host_listener_started_without_user_action",
    "automatic_stream_start_observed",
)
HEADLESS_FIELDS = (
    *AUTOMATIC_STARTUP_FIELDS,
    "headless_configuration_recorded",
    "headless_display_identity_recorded",
    "headless_capture_first_frame_observed",
)
UNATTENDED_RECOVERY_FIELDS = (
    "stable_signed_host_identity_recorded",
    "screen_recording_permission_recorded",
    "startup_mode_recorded",
    "host_listener_started_without_user_action",
    "unattended_failure_trigger_recorded",
    "recovery_retry_schedule_observed",
    "recovery_bounded_exhaustion_or_success_observed",
    "no_full_speed_retry_loop_observed",
    "host_logs_retained",
)
ANDROID_RECONNECT_FIELDS = (
    "android_device_lock_acquired",
    "android_device_identity_recorded",
    "android_device_identity_matches_claim",
    "android_reconnect_within_3s_observed",
    "android_post_reconnect_render_observed",
    "android_logs_retained",
)
BLOCKING_FIELDS = {
    "stable_signed_host_identity_recorded",
    "screen_recording_permission_recorded",
    "launch_at_login_enabled_not_approval_required",
    "macos_reboot_or_logout_login_performed",
    "headless_configuration_recorded",
    "host_listener_started_without_user_action",
    "android_device_lock_acquired",
    "android_device_identity_recorded",
}
BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)


class MacOSStartupRecoveryGateError(ValueError):
    """Raised when a startup/recovery evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise MacOSStartupRecoveryGateError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise MacOSStartupRecoveryGateError(
            "macOS startup recovery evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise MacOSStartupRecoveryGateError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MacOSStartupRecoveryGateError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise MacOSStartupRecoveryGateError(
            f"{field} must contain only non-empty strings"
        )
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise MacOSStartupRecoveryGateError(f"{field} must be a string")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise MacOSStartupRecoveryGateError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise MacOSStartupRecoveryGateError("run_id must be a non-empty string")


def _optional_object(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field, {})
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise MacOSStartupRecoveryGateError(f"{field} must be an object")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _gate_passes(field_values: dict[str, bool], fields: Sequence[str]) -> bool:
    return all(field_values[field] for field in fields)


def _metadata_requirements(
    record: dict[str, Any], android_device: dict[str, Any], artifact_paths: list[str]
) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if not artifact_paths:
        missing.append(
            {
                "field": "artifact_paths",
                "requirement": "retain at least one raw artifact path for the evidence package",
            }
        )

    if _bool_value(record, "android_device_identity_recorded"):
        for field, requirement in REQUIRED_ANDROID_DEVICE_FIELDS:
            if not _non_empty_string(android_device.get(field)):
                missing.append(
                    {
                        "field": f"android_device.{field}",
                        "requirement": requirement,
                    }
                )
    return missing


def _android_device_scope(android_device: dict[str, Any]) -> str:
    manufacturer = str(android_device.get("manufacturer", "")).strip().lower()
    model = str(android_device.get("model", "")).strip().lower()
    codename = str(android_device.get("codename", "")).strip().lower()
    android_version = str(android_device.get("android_version", "")).strip()
    sdk = str(android_device.get("sdk", "")).strip()
    if (
        manufacturer == "nubia"
        and model == "p0110"
        and codename == "pacific"
        and android_version == "16"
        and sdk == "36"
    ):
        return P0110_ANDROID_SCOPE
    if any(_non_empty_string(android_device.get(key)) for key in ("manufacturer", "model", "codename")):
        return "Android evidence scope is limited to the recorded device identity and cannot prove macOS login or headless behavior."
    return "No Android device identity was supplied; Android reconnect evidence cannot close."


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    android_device = _optional_object(record, "android_device")
    artifact_paths = _string_list(record, "artifact_paths")
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    missing.extend(_metadata_requirements(record, android_device, artifact_paths))
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]

    artifact_metadata_present = bool(artifact_paths)
    can_close_login_item_gate = _gate_passes(
        field_values, LOGIN_ITEM_FIELDS
    ) and artifact_metadata_present
    can_close_automatic_startup_gate = _gate_passes(
        field_values, AUTOMATIC_STARTUP_FIELDS
    ) and artifact_metadata_present
    can_close_headless_startup_gate = _gate_passes(
        field_values, HEADLESS_FIELDS
    ) and artifact_metadata_present
    can_close_unattended_listener_recovery_gate = _gate_passes(
        field_values, UNATTENDED_RECOVERY_FIELDS
    ) and artifact_metadata_present
    can_close_android_reconnect_gate = _gate_passes(
        field_values, ANDROID_RECONNECT_FIELDS
    ) and artifact_metadata_present and not any(
        item["field"].startswith("android_device.") for item in missing
    )
    can_close_phase1_phase2_startup_recovery_gate = not missing

    if can_close_phase1_phase2_startup_recovery_gate:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "macos_startup_recovery_gate",
        "profile": GATE_PROFILE,
        "verdict": verdict,
        "can_close_login_item_gate": can_close_login_item_gate,
        "can_close_automatic_startup_gate": can_close_automatic_startup_gate,
        "can_close_headless_startup_gate": can_close_headless_startup_gate,
        "can_close_unattended_listener_recovery_gate": can_close_unattended_listener_recovery_gate,
        "can_close_android_reconnect_gate": can_close_android_reconnect_gate,
        "can_close_phase1_phase2_startup_recovery_gate": (
            can_close_phase1_phase2_startup_recovery_gate
        ),
        "requires_real_macos_login_or_reboot": True,
        "readiness_preflight_is_not_acceptance": True,
        "android_device_scope": _android_device_scope(android_device),
        "observations": field_values,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "artifact_paths": artifact_paths,
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen macOS login/headless/recovery gate evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing "
            "booleans default to false, so readiness/preflight records cannot "
            "accidentally close login, headless, recovery, or reconnect gates."
        ),
    )
    parser.add_argument(
        "input", help="macOS startup/recovery evidence .json file, or - for stdin"
    )
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(args.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        summary = summarize(record, run_id=args.run_id)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (MacOSStartupRecoveryGateError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if summary["verdict"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
