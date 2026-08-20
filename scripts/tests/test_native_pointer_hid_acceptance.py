from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_pointer_hid_acceptance as acceptance


SAMPLE_DUMPSYS_INPUT = """
Input Reader State (Nums of device: 3):
  Device 3: gdix_input_agent
    IsExternal: false
    Sources: KEYBOARD | TOUCHSCREEN
  Device 11: USB Optical Mouse
    IsExternal: true
    Sources: MOUSE | TOUCHPAD
  Device 12: Bluetooth Trackpad
    IsExternal: true
    Sources: MOUSE_RELATIVE
  Device -1: Virtual
    IsExternal: false
    Sources: KEYBOARD | DPAD
"""


class NativePointerHIDAcceptanceTests(unittest.TestCase):
    def test_input_device_parser_finds_external_mouse_sources(self) -> None:
        devices = acceptance.parse_input_devices(SAMPLE_DUMPSYS_INPUT)

        self.assertEqual(
            [device.name for device in devices],
            ["gdix_input_agent", "USB Optical Mouse", "Bluetooth Trackpad", "Virtual"],
        )
        self.assertEqual(
            acceptance.external_mouse_devices(devices),
            [
                acceptance.InputDeviceSummary("USB Optical Mouse", "MOUSE | TOUCHPAD", "true"),
                acceptance.InputDeviceSummary("Bluetooth Trackpad", "MOUSE_RELATIVE", "true"),
            ],
        )

    def test_observed_events_accept_swift_enum_and_plain_phase_spelling(self) -> None:
        log = """
        Pointer injected: phase=INPUT_PHASE_changed buttons=0
        Pointer injected: phase=began buttons=1
        Pointer injected: phase=ended buttons=0
        """

        self.assertEqual(acceptance.observed_events(log), ["move", "press", "release"])

    def test_observed_android_events_require_mouse_like_forwarding_logs(self) -> None:
        log = """
        08-21 12:00:00.000 D MA      : native pointer forwarded action=MOVE source=MOUSE buttonState=0 actionButton=0 wireButtons=0 x=0.5 y=0.5
        08-21 12:00:01.000 D MA      : native pointer forwarded action=BUTTON_PRESS source=MOUSE_RELATIVE buttonState=1 actionButton=1 wireButtons=1 x=0.5 y=0.5
        08-21 12:00:02.000 D MA      : native pointer forwarded action=BUTTON_RELEASE source=MOUSE buttonState=0 actionButton=1 wireButtons=0 x=0.5 y=0.5
        08-21 12:00:03.000 D MA      : native pointer forwarded action=MOVE source=OTHER buttonState=0 actionButton=0 wireButtons=0 x=0.1 y=0.1
        """

        self.assertEqual(acceptance.observed_android_events(log), ["move", "press", "release"])

    def test_utc_timestamp_uses_z_suffix(self) -> None:
        created_at = acceptance.utc_timestamp()

        self.assertRegex(created_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_evidence_text_strips_line_trailing_whitespace_and_ends_with_newline(self) -> None:
        self.assertEqual(
            acceptance.evidence_text("UniqueId:   \nConfigurationFile: \nLast line"),
            "UniqueId:\nConfigurationFile:\nLast line\n",
        )

    def test_read_new_host_log_rejects_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "host.log"
            log.write_text("short", encoding="utf-8")
            cursor = acceptance.HostLogCursor(device=log.stat().st_dev, inode=log.stat().st_ino, offset=10)

            with self.assertRaisesRegex(acceptance.AcceptanceError, "truncated"):
                acceptance.read_new_host_log(log, cursor, 100)

    def test_read_new_host_log_rejects_replacement_with_larger_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "host.log"
            log.write_text("before\n", encoding="utf-8")
            cursor = acceptance.host_log_cursor(log)
            replacement_log = Path(temporary_directory) / "replacement.log"
            replacement = "historical replacement content\n"
            replacement += "Pointer injected: phase=changed buttons=0\n"
            replacement += "Pointer injected: phase=began buttons=1\n"
            replacement += "Pointer injected: phase=ended buttons=0\n"
            replacement_log.write_text(replacement, encoding="utf-8")
            self.assertNotEqual(replacement_log.stat().st_ino, cursor.inode)
            replacement_log.replace(log)

            self.assertGreater(log.stat().st_size, cursor.offset)
            with self.assertRaisesRegex(acceptance.AcceptanceError, "identity changed"):
                acceptance.read_new_host_log(log, cursor, 1000)

    def test_main_writes_blocked_evidence_when_mouse_is_absent(self) -> None:
        identity = acceptance.DeviceIdentity(
            serial="EP0110PZ0B9110300B",
            endpoint="EP0110PZ0B9110300B device product:pacific model:P0110 device:pacific",
            manufacturer="nubia",
            model="P0110",
            device="pacific",
            android_release="16",
            sdk="36",
            fingerprint_sha256="0" * 64,
            display_size="Physical size: 1264x2800",
            display_density="Physical density: 480",
            battery_summary="level: 88",
            boot_completed="1",
        )
        no_mouse_dumpsys = """
        Device 3: gdix_input_agent
          IsExternal: false
          Sources: KEYBOARD | TOUCHSCREEN
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(acceptance, "read_device_identity", return_value=identity),
                mock.patch.object(
                    acceptance,
                    "adb",
                    return_value=acceptance.CommandResult(["adb"], 0, no_mouse_dumpsys, ""),
                ),
            ):
                exit_code = acceptance.main(
                    [
                        "--serial",
                        "EP0110PZ0B9110300B",
                        "--host-log",
                        str(Path(temporary_directory) / "host.log"),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--no-wait",
                    ]
                )

            self.assertEqual(exit_code, acceptance.BLOCKED_EXIT)
            result = json.loads((evidence_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["device"]["manufacturer"], "nubia")
            self.assertEqual(result["device"]["model"], "P0110")
            self.assertEqual(result["device"]["device"], "pacific")
            self.assertEqual(result["external_mouse_devices"], [])
            self.assertIn("No external Android input device", result["reason"])
            self.assertTrue((evidence_dir / "dumpsys-input.txt").exists())
            self.assertTrue((evidence_dir / "README.md").exists())

    def test_main_passes_when_required_android_host_and_visible_evidence_are_observed(self) -> None:
        identity = acceptance.DeviceIdentity(
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
            cursor = acceptance.host_log_cursor(host_log)
            host_log.write_text(
                "before\n"
                "Pointer injected: phase=changed buttons=0\n"
                "Pointer injected: phase=began buttons=1\n"
                "Pointer injected: phase=ended buttons=0\n",
                encoding="utf-8",
            )
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(acceptance, "read_device_identity", return_value=identity),
                mock.patch.object(
                    acceptance,
                    "adb",
                    return_value=acceptance.CommandResult(["adb"], 0, SAMPLE_DUMPSYS_INPUT, ""),
                ),
                mock.patch.object(acceptance, "host_log_cursor", return_value=cursor),
                mock.patch.object(
                    acceptance,
                    "LogcatCapture",
                    return_value=FakeLogcatCapture(
                        "native pointer forwarded action=MOVE source=MOUSE buttonState=0 actionButton=0 wireButtons=0 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_PRESS source=MOUSE buttonState=1 actionButton=1 wireButtons=1 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_RELEASE source=MOUSE buttonState=0 actionButton=1 wireButtons=0 x=0.5 y=0.5\n",
                    ),
                ),
            ):
                exit_code = acceptance.main(
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

            self.assertEqual(exit_code, 0)
            result = json.loads((evidence_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["observed_host_pointer_events"], ["move", "press", "release"])
            self.assertEqual(result["observed_android_pointer_events"], ["move", "press", "release"])
            self.assertEqual(result["external_mouse_devices"][0]["name"], "USB Optical Mouse")
            self.assertEqual(result["visible_mac_result"], "Mac cursor moved and the primary click focused TextEdit.")
            self.assertTrue((evidence_dir / "host-log-appended.txt").exists())
            self.assertTrue((evidence_dir / "android-logcat-native-pointer.txt").exists())

    def test_main_fails_without_visible_result_note_even_when_logs_match(self) -> None:
        identity = acceptance.DeviceIdentity(
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
            cursor = acceptance.host_log_cursor(host_log)
            host_log.write_text(
                "before\n"
                "Pointer injected: phase=changed buttons=0\n"
                "Pointer injected: phase=began buttons=1\n"
                "Pointer injected: phase=ended buttons=0\n",
                encoding="utf-8",
            )
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(acceptance, "read_device_identity", return_value=identity),
                mock.patch.object(
                    acceptance,
                    "adb",
                    return_value=acceptance.CommandResult(["adb"], 0, SAMPLE_DUMPSYS_INPUT, ""),
                ),
                mock.patch.object(acceptance, "host_log_cursor", return_value=cursor),
                mock.patch.object(
                    acceptance,
                    "LogcatCapture",
                    return_value=FakeLogcatCapture(
                        "native pointer forwarded action=MOVE source=MOUSE buttonState=0 actionButton=0 wireButtons=0 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_PRESS source=MOUSE buttonState=1 actionButton=1 wireButtons=1 x=0.5 y=0.5\n"
                        "native pointer forwarded action=BUTTON_RELEASE source=MOUSE buttonState=0 actionButton=1 wireButtons=0 x=0.5 y=0.5\n",
                    ),
                ),
            ):
                exit_code = acceptance.main(
                    [
                        "--serial",
                        "SERIAL",
                        "--host-log",
                        str(host_log),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--observe-seconds",
                        "0",
                    ]
                )

            self.assertEqual(exit_code, 1)
            result = json.loads((evidence_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertIn("visible Mac pointer/click result", result["reason"])


class FakeLogcatCapture:
    def __init__(self, output: str) -> None:
        self.output = output

    def __enter__(self) -> "FakeLogcatCapture":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.stop()

    def stop(self) -> bytes:
        return self.output.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
