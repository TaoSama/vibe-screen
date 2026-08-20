"""Summarize fixed-binary touch-gesture rerun evidence fail-closed.

The summary consumes retained artifacts. It never starts the Host, runs ADB, or
posts input events. A pass means the artifact set is complete enough to support
the fixed-binary touch rerun claim for the recorded device scope.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


HOST_MARKERS = {
    "protocol_v1_selected": "Protocol v1 selected",
    "touch_input_enabled": "Starting input receive loop... (touch=on)",
    "right_click_observed": "Touch gesture: right click injected",
    "drag_began_observed": "Touch gesture: drag began",
    "drag_ended_observed": "Touch gesture: drag ended",
    "two_finger_scroll_observed": "Touch gesture: two-finger scroll began",
    "pinch_observed": "Touch gesture: pinch began",
}


class TouchRerunSummaryError(RuntimeError):
    """Raised when evidence inputs cannot be read or interpreted."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise TouchRerunSummaryError(f"could not read {path}: {error}") from error


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as error:
        raise TouchRerunSummaryError(f"could not parse JSON {path}: {error}") from error
    if not isinstance(data, dict):
        raise TouchRerunSummaryError(f"expected JSON object in {path}")
    return data


def _event_lines(event_tap_log: str, *, name: str, command: bool) -> list[str]:
    expected = "true" if command else "false"
    return [
        line
        for line in event_tap_log.splitlines()
        if f"name={name}" in line and f"command={expected}" in line
    ]


def _first_mouse_event_command_clear(event_tap_log: str) -> bool:
    for line in event_tap_log.splitlines():
        if "name=leftMouseDown" in line or "name=rightMouseDown" in line:
            return "command=false" in line
    return False


def _event_tap_checks(event_tap_log: str) -> dict[str, bool]:
    return {
        "event_tap_ready": "EVENT_TAP_READY" in event_tap_log,
        "event_tap_done": "EVENT_TAP_DONE" in event_tap_log,
        "tap_left_down_up_observed": bool(_event_lines(event_tap_log, name="leftMouseDown", command=False))
        and bool(_event_lines(event_tap_log, name="leftMouseUp", command=False)),
        "right_click_event_observed": bool(_event_lines(event_tap_log, name="rightMouseDown", command=False))
        and bool(_event_lines(event_tap_log, name="rightMouseUp", command=False)),
        "drag_event_observed": bool(_event_lines(event_tap_log, name="leftMouseDragged", command=False)),
        "plain_scroll_event_observed": bool(_event_lines(event_tap_log, name="scrollWheel", command=False)),
        "pinch_zoom_event_observed": bool(_event_lines(event_tap_log, name="scrollWheel", command=True)),
        "first_plain_pointer_command_clear": _first_mouse_event_command_clear(event_tap_log),
    }


def _preflight_checks(
    preflight: dict[str, Any],
    *,
    expected_android_manufacturer: str | None,
    expected_android_model: str | None,
    expected_android_device: str | None,
    expected_android_release: str | None,
    expected_android_sdk: int | None,
) -> dict[str, bool]:
    android = preflight.get("android_device")
    expected = {
        "manufacturer": expected_android_manufacturer,
        "model": expected_android_model,
        "device": expected_android_device,
        "android_release": expected_android_release,
        "sdk": expected_android_sdk,
    }
    identity_matches = isinstance(android, dict) and all(
        expected_value is None or android.get(field) == expected_value
        for field, expected_value in expected.items()
    )
    return {
        "preflight_ready": preflight.get("result") == "ready" and not preflight.get("blockers"),
        "expected_android_identity_observed": identity_matches,
    }


def _host_checks(host_log: str) -> dict[str, bool]:
    return {name: marker in host_log for name, marker in HOST_MARKERS.items()}


def build_summary(
    *,
    preflight_path: Path,
    instrumentation_path: Path,
    host_log_path: Path,
    event_tap_path: Path,
    expected_android_manufacturer: str | None = None,
    expected_android_model: str | None = None,
    expected_android_device: str | None = None,
    expected_android_release: str | None = None,
    expected_android_sdk: int | None = None,
) -> dict[str, Any]:
    preflight = _read_json(preflight_path)
    instrumentation = _read_text(instrumentation_path)
    host_log = _read_text(host_log_path)
    event_tap_log = _read_text(event_tap_path)
    checks = {
        **_preflight_checks(
            preflight,
            expected_android_manufacturer=expected_android_manufacturer,
            expected_android_model=expected_android_model,
            expected_android_device=expected_android_device,
            expected_android_release=expected_android_release,
            expected_android_sdk=expected_android_sdk,
        ),
        "instrumentation_ok": "OK (1 test)" in instrumentation
        and "INSTRUMENTATION_CODE: -1" in instrumentation,
        **_host_checks(host_log),
        **_event_tap_checks(event_tap_log),
    }
    missing = [name for name, passed in checks.items() if not passed]
    android = preflight.get("android_device") if isinstance(preflight, dict) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "touch_fixed_binary_rerun_summary",
        "summarized_at": datetime.now(timezone.utc).isoformat(),
        "result": "pass" if not missing else "blocked",
        "can_close_touch_rerun_gate": not missing,
        "device_scope": "general_android_substitute" if not missing else "not_closed",
        "blockers": missing,
        "checks": checks,
        "android_device": android,
        "inputs": {
            "preflight": str(preflight_path),
            "instrumentation": str(instrumentation_path),
            "host_log": str(host_log_path),
            "event_tap": str(event_tap_path),
        },
        "limitations": [
            "A pass closes only the fixed stable-signed binary touch-gesture rerun for the recorded general Android substitute device.",
            "A Nubia P0110/pacific result must not be relabeled as Xiaomi 13/fuxi evidence.",
            "Physical-finger/manual UX and native HID mouse confirmations remain separate gates.",
        ],
    }


def write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def _blocked_error_document(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "touch_fixed_binary_rerun_summary",
        "summarized_at": datetime.now(timezone.utc).isoformat(),
        "result": "blocked",
        "can_close_touch_rerun_gate": False,
        "device_scope": "not_closed",
        "blockers": [f"summary collection failed: {error}"],
        "checks": {},
        "android_device": None,
        "inputs": {},
        "limitations": [
            "No touch rerun gate is closed when the summary inputs cannot be read or interpreted."
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--instrumentation", type=Path, required=True)
    parser.add_argument("--host-log", type=Path, required=True)
    parser.add_argument("--event-tap", type=Path, required=True)
    parser.add_argument("--expected-android-manufacturer")
    parser.add_argument("--expected-android-model")
    parser.add_argument("--expected-android-device")
    parser.add_argument("--expected-android-release")
    parser.add_argument("--expected-android-sdk", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        summary = build_summary(
            preflight_path=arguments.preflight,
            instrumentation_path=arguments.instrumentation,
            host_log_path=arguments.host_log,
            event_tap_path=arguments.event_tap,
            expected_android_manufacturer=arguments.expected_android_manufacturer,
            expected_android_model=arguments.expected_android_model,
            expected_android_device=arguments.expected_android_device,
            expected_android_release=arguments.expected_android_release,
            expected_android_sdk=arguments.expected_android_sdk,
        )
    except (OSError, TouchRerunSummaryError, ValueError) as error:
        write_json(arguments.output, _blocked_error_document(error))
        print(f"error: {error}", file=sys.stderr)
        return 1
    write_json(arguments.output, summary)
    if summary["result"] != "pass":
        print("blocked: " + ", ".join(summary["blockers"]), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

