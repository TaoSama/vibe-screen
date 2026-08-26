from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hardware_keyboard_readiness as readiness


SAMPLE_DUMPSYS_INPUT = """
Event Hub State:
  Devices:
    -1: Virtual
      Classes: KEYBOARD | ALPHAKEY | DPAD | VIRTUAL
      Descriptor: virtual-descriptor
    8: built-in keys
      Classes: KEYBOARD
      Descriptor: built-in-descriptor
Input Reader State (Nums of device: 3):
  Device -1: Virtual
    IsExternal: false
    Sources: KEYBOARD | DPAD
  Device 4: built-in keys
    IsExternal: false
    Sources: KEYBOARD
  Device 12: Folding Keyboard
    IsExternal: true
    Sources: KEYBOARD | DPAD
"""


class HardwareKeyboardReadinessTests(unittest.TestCase):
    def test_input_device_parser_finds_external_physical_keyboard(self) -> None:
        devices = readiness.parse_input_devices(SAMPLE_DUMPSYS_INPUT)

        keyboards = readiness.physical_keyboard_devices(devices)

        self.assertEqual([device.name for device in keyboards], ["Folding Keyboard"])
        self.assertEqual(keyboards[0].sources, "KEYBOARD | DPAD")

    def test_p0110_identity_must_match_recorded_device(self) -> None:
        matching = readiness.DeviceIdentity(
            serial="EP0110PZ0B9110300B",
            endpoint="EP0110PZ0B9110300B device product:pacific model:P0110 device:pacific",
            manufacturer="nubia",
            model="P0110",
            device="pacific",
            product="P0110",
            android_release="16",
            sdk="36",
            build_fingerprint="nubia/pacific/fingerprint",
            abi="arm64-v8a",
            device_serial="EP0110PZ0B9110300B",
        )
        mislabeled = readiness.DeviceIdentity(
            serial="EP0110PZ0B9110300B",
            endpoint="EP0110PZ0B9110300B device product:fuxi model:2211133C device:fuxi",
            manufacturer="Xiaomi",
            model="2211133C",
            device="fuxi",
            product="fuxi",
            android_release="16",
            sdk="36",
            build_fingerprint="xiaomi/fuxi/fingerprint",
            abi="arm64-v8a",
            device_serial="EP0110PZ0B9110300B",
        )

        self.assertTrue(readiness.device_identity_matches_claim(readiness.P0110_SERIAL, matching))
        self.assertFalse(readiness.device_identity_matches_claim(readiness.P0110_SERIAL, mislabeled))

    def test_non_p0110_identity_requires_recorded_public_fields(self) -> None:
        complete = readiness.DeviceIdentity(
            serial="other-adb-serial",
            endpoint="other-adb-serial device product:smalltab model:SmallTab device:smalltab",
            manufacturer="Example",
            model="SmallTab",
            device="smalltab",
            product="smalltab",
            android_release="14",
            sdk="34",
            build_fingerprint="example/smalltab/fingerprint",
            abi="arm64-v8a",
            device_serial="other-adb-serial",
        )
        incomplete = readiness.DeviceIdentity(
            serial="other-adb-serial",
            endpoint="other-adb-serial device product:smalltab model:SmallTab device:smalltab",
            manufacturer="Example",
            model="",
            device="smalltab",
            product="smalltab",
            android_release="14",
            sdk="34",
            build_fingerprint="example/smalltab/fingerprint",
            abi="arm64-v8a",
            device_serial="other-adb-serial",
        )

        self.assertTrue(readiness.device_identity_matches_claim("other-adb-serial", complete))
        self.assertFalse(readiness.device_identity_matches_claim("other-adb-serial", incomplete))

    def test_package_identity_accepts_zero_version_code(self) -> None:
        package = readiness.PackageIdentity(
            package_name="dev.telemachus.display",
            version_name="0.0.0",
            version_code=0,
            first_install_time="2026-08-23 10:00:00",
            last_update_time="",
        )

        self.assertTrue(readiness.package_identity_recorded(package))

    def test_device_info_document_matches_shared_schema_shape(self) -> None:
        device = readiness.DeviceIdentity(
            serial="EP0110PZ0B9110300B",
            endpoint="EP0110PZ0B9110300B device product:pacific model:P0110 device:pacific",
            manufacturer="nubia",
            model="P0110",
            device="pacific",
            product="pacific",
            android_release="16",
            sdk="36",
            build_fingerprint="nubia/pacific/fingerprint",
            abi="arm64-v8a",
            device_serial="EP0110PZ0B9110300B",
        )
        package = readiness.PackageIdentity(
            package_name="dev.telemachus.display",
            version_name="0.0.0",
            version_code=100000,
            first_install_time="2026-08-23 10:00:00",
            last_update_time="2026-08-23 10:00:00",
        )

        document = readiness.device_info_document(
            created_at="2026-08-23T00:00:00Z",
            connection="already connected to EP0110PZ0B9110300B",
            adb_version="Android Debug Bridge version 1.0.41",
            device=device,
            package=package,
        )

        self.assertEqual(document["device"]["adb_serial"], readiness.P0110_SERIAL)
        self.assertEqual(document["device"]["sdk"], 36)
        self.assertEqual(document["packages"][0]["package"], "dev.telemachus.display")

    def test_main_refuses_adb_when_device_lock_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = Path(temporary_directory) / "device.lock"
            lock.write_text("owner=other-task\n", encoding="utf-8")
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(readiness, "DEVICE_LOCKS", (lock,)),
                mock.patch.object(readiness, "adb", side_effect=AssertionError("adb must not run")),
            ):
                exit_code = readiness.main(
                    [
                        "--serial",
                        readiness.P0110_SERIAL,
                        "--evidence-dir",
                        str(evidence_dir),
                    ]
                )

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            self.assertFalse(evidence_dir.exists())

    def test_main_writes_lock_blocked_bundle_without_adb_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = Path(temporary_directory) / "device.lock"
            lock.write_text("owner=other-task\n", encoding="utf-8")
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(readiness, "DEVICE_LOCKS", (lock,)),
                mock.patch.object(readiness, "adb", side_effect=AssertionError("adb must not run")),
            ):
                exit_code = readiness.main(
                    [
                        "--serial",
                        readiness.P0110_SERIAL,
                        "--evidence-dir",
                        str(evidence_dir),
                        "--run-id",
                        "lock-run",
                        "--write-blocked-on-lock",
                    ]
                )

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            summary = json.loads((evidence_dir / "hardware-keyboard-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["run_id"], "lock-run")
            self.assertEqual(summary["verdict"], "blocked")
            self.assertFalse(summary["can_close_hardware_keyboard_gate"])
            readiness_record = json.loads((evidence_dir / "hardware-keyboard-readiness.json").read_text(encoding="utf-8"))
            self.assertFalse(readiness_record["device_lock"]["acquired"])
            self.assertEqual(readiness_record["device_lock"]["existing_locks"][0]["path"], readiness.REDACTED_DEVICE_LOCK_PATH)

    def test_main_collects_blocked_readiness_when_no_external_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lock = Path(temporary_directory) / "device.lock"
            evidence_dir = Path(temporary_directory) / "evidence"
            command_outputs = {
                ("adb", "-s", readiness.P0110_SERIAL, "devices", "-l"): "List of devices attached\nEP0110PZ0B9110300B device product:pacific model:P0110 device:pacific\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.product.manufacturer"): "nubia\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.product.model"): "P0110\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.product.device"): "pacific\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.product.name"): "P0110\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.build.version.release"): "16\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.build.version.sdk"): "36\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.build.fingerprint"): "nubia/pacific/fingerprint\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.product.cpu.abi"): "arm64-v8a\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "getprop", "ro.serialno"): "EP0110PZ0B9110300B\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "dumpsys", "input"): "Device -1: Virtual\n  IsExternal: false\n  Sources: KEYBOARD | DPAD\n",
                ("adb", "-s", readiness.P0110_SERIAL, "shell", "dumpsys", "package", "dev.telemachus.display"): "versionName=0.0.0\nversionCode=100000 minSdk=26 targetSdk=34\nfirstInstallTime=2026-08-21 10:00:00\n",
                ("adb", "version"): "Android Debug Bridge version 1.0.41\n",
                ("lsof", "-nP", "-iTCP:54321", "-sTCP:LISTEN"): "",
                ("security", "find-identity", "-v", "-p", "codesigning"): "     0 valid identities found\n",
            }

            def fake_run(command, **_kwargs):
                key = tuple(command)
                if len(command) >= 3 and command[0] == sys.executable and command[1].endswith("macos_dev_host.py"):
                    return subprocess_completed(command, returncode=1, stdout="codesign identity 'Vibe Screen Dev' not found\n")
                return subprocess_completed(command, stdout=command_outputs[key])

            with (
                mock.patch.object(readiness, "DEVICE_LOCKS", (lock,)),
                mock.patch.object(readiness.subprocess, "run", side_effect=fake_run),
            ):
                exit_code = readiness.main(
                    [
                        "--serial",
                        readiness.P0110_SERIAL,
                        "--evidence-dir",
                        str(evidence_dir),
                        "--run-id",
                        "p0110-run",
                    ]
                )

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            summary = json.loads((evidence_dir / "hardware-keyboard-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["verdict"], "blocked")
            self.assertTrue(summary["observations"]["android_device_lock_acquired"])
            self.assertTrue(summary["observations"]["device_identity_recorded"])
            self.assertTrue(summary["observations"]["device_identity_matches_claim"])
            self.assertTrue(summary["observations"]["apk_identity_recorded"])
            self.assertFalse(summary["observations"]["physical_keyboard_attached"])
            self.assertFalse(summary["observations"]["host_listener_observed"])
            self.assertFalse(summary["observations"]["host_stable_signed_tcc_ready"])
            self.assertFalse(lock.exists())

    def test_input_device_parser_rejects_builtin_non_virtual_keyboard(self) -> None:
        dumpsys_input = """
Event Hub State:
  Devices:
    3: gpio-keys
      Classes: KEYBOARD
      Descriptor: built-in-descriptor
Input Reader State (Nums of device: 1):
  Device 3: gpio-keys
    IsExternal: false
    Sources: KEYBOARD
"""

        keyboards = readiness.physical_keyboard_devices(readiness.parse_input_devices(dumpsys_input))

        self.assertEqual(keyboards, [])


def subprocess_completed(command, *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return readiness.subprocess.CompletedProcess(command, returncode, stdout, stderr)


if __name__ == "__main__":
    unittest.main()
