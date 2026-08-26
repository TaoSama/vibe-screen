from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import android_stylus_acceptance
import hardware_keyboard_readiness as keyboard_readiness
import native_pointer_hid_acceptance


def p0110_identity() -> dict[str, str]:
    return {
        "serialno": "redacted-pacific-serial",
        "manufacturer": "nubia",
        "model": "P0110",
        "device": "pacific",
        "os_release": "16",
        "api_level": "36",
    }


class PeripheralHostReadyFailClosedTests(unittest.TestCase):
    def test_stylus_drawing_without_host_ready_flag_stays_blocked(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text("ready\n", encoding="utf-8")
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=False,
            )

            status = android_stylus_acceptance.conclusion_status(
                args,
                [candidate],
                diag_log=(
                    "Stylus forwarded: samples=1 extended=true rawSource=0x5002 rawAction=2 "
                    "rawTools=[stylus] phase=INPUT_PHASE_CHANGED contact=contact tool=pen "
                    "buttons=0 pressure=0.5 tiltX=45.0 tiltY=-45.0"
                ),
                host_log_excerpt=(
                    "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                    "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
                ),
            )

        self.assertEqual(status, "blocked_host_stable_signed_tcc_not_ready")

    def test_native_pointer_without_host_ready_flag_stays_blocked(self) -> None:
        identity = native_pointer_hid_acceptance.DeviceIdentity(
            serial="SERIAL",
            endpoint="SERIAL device product:pacific model:P0110 device:pacific",
            manufacturer="nubia",
            model="P0110",
            device="pacific",
            android_release="16",
            sdk="36",
            fingerprint_sha256="1" * 64,
            display_size="Physical size: 1264x2800",
            display_density="Physical density: 480",
            battery_summary="level: 88",
            boot_completed="1",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host.log"
            host_log.write_text("before\n", encoding="utf-8")
            cursor = native_pointer_hid_acceptance.host_log_cursor(host_log)
            host_log.write_text(
                "before\n"
                "Pointer injected: phase=changed buttons=0\n"
                "Pointer injected: phase=began buttons=1\n"
                "Pointer injected: phase=ended buttons=0\n",
                encoding="utf-8",
            )
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(native_pointer_hid_acceptance, "describe_device_locks", return_value=[]),
                mock.patch.object(native_pointer_hid_acceptance, "read_device_identity", return_value=identity),
                mock.patch.object(
                    native_pointer_hid_acceptance,
                    "adb",
                    return_value=native_pointer_hid_acceptance.CommandResult(
                        ["adb"],
                        0,
                        "Device 12: USB Optical Mouse\n  IsExternal: true\n  Sources: MOUSE | TOUCHPAD\n",
                        "",
                    ),
                ),
                mock.patch.object(native_pointer_hid_acceptance, "host_log_cursor", return_value=cursor),
                mock.patch.object(
                    native_pointer_hid_acceptance,
                    "LogcatCapture",
                    return_value=FakeLogcatCapture(
                        "native pointer forwarded action=MOVE source=MOUSE buttonState=0 actionButton=0 wireButtons=0 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_PRESS source=MOUSE buttonState=1 actionButton=1 wireButtons=1 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_RELEASE source=MOUSE buttonState=0 actionButton=1 wireButtons=0 x=0.5 y=0.5\n",
                    ),
                ),
            ):
                exit_code = native_pointer_hid_acceptance.main(
                    [
                        "--serial",
                        "SERIAL",
                        "--host-log",
                        str(host_log),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--observe-seconds",
                        "0",
                        "--visible-result-note",
                        "Mac cursor moved and the primary click focused TextEdit.",
                    ]
                )

            self.assertEqual(exit_code, native_pointer_hid_acceptance.BLOCKED_EXIT)
            result = json.loads((evidence_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("stable signed/TCC-ready Host", result["reason"])

    def test_hardware_keyboard_redacts_local_paths_in_evidence_text(self) -> None:
        raw = (
            "$ /opt/homebrew/opt/python@3.11/bin/python3.11 "
            f"{keyboard_readiness.REPO_ROOT}/scripts/macos_dev_host.py preflight\n"
            "Installed as /" "Users" "/example/Library/Android/sdk/platform-tools/adb\n"
            "worktree=/" "Users" "/example/private/vibe-screen\n"
        )

        redacted = keyboard_readiness.redact_evidence_text(raw)

        self.assertIn("<python3.11> <repo-root>/scripts/macos_dev_host.py", redacted)
        self.assertIn("Installed as <android-sdk>/platform-tools/adb", redacted)
        self.assertIn("worktree=<user-home>", redacted)
        self.assertNotIn("/Users/example", redacted)


class FakeLogcatCapture:
    def __init__(self, output: str) -> None:
        self.output = output

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def stop(self) -> bytes:
        return self.output.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
