from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_runtime_readiness as readiness


SAMPLE_DUMPSYS_INPUT = """
Event Hub State:
  Devices:
    3: Virtual
      Classes: KEYBOARD | ALPHAKEY | DPAD | VIRTUAL
      Descriptor: virtual-descriptor
Input Reader State (Nums of device: 2):
  Device 8: Built-in Touch
    IsExternal: false
    Sources: KEYBOARD | TOUCHSCREEN
  Device 12: 8BitDo Controller
    IsExternal: true
    Sources: KEYBOARD | GAMEPAD | JOYSTICK
"""


class ControllerRuntimeReadinessTests(unittest.TestCase):
    def sample_device(self) -> readiness.DeviceIdentity:
        return readiness.DeviceIdentity(
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

    def sample_package(self) -> readiness.PackageIdentity:
        return readiness.PackageIdentity(
            package_name="dev.telemachus.display",
            version_name="0.0.0",
            version_code="100000",
            first_install_time="2026-08-20 10:00:00",
            last_update_time="2026-08-20 10:00:00",
            raw_summary="versionName=0.0.0",
        )

    def test_input_device_parser_finds_physical_controller(self) -> None:
        devices = readiness.parse_input_devices(SAMPLE_DUMPSYS_INPUT)

        controllers = readiness.physical_controller_devices(devices)

        self.assertEqual([device.name for device in controllers], ["8BitDo Controller"])
        self.assertEqual(controllers[0].sources, "KEYBOARD | GAMEPAD | JOYSTICK")

    def test_input_device_parser_ignores_virtual_dpad(self) -> None:
        dumpsys = """
        Device -1: Virtual
          IsExternal: false
          Sources: KEYBOARD | DPAD
        """

        self.assertEqual(readiness.physical_controller_devices(readiness.parse_input_devices(dumpsys)), [])

    def test_host_availability_uses_latest_controller_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log = Path(temporary_directory) / "host.log"
            log.write_text(
                "2026-08-20T01:00:00Z Controller forwarding unavailable: missing entitlement\n"
                "2026-08-20T01:05:00Z Controller forwarding available\n",
                encoding="utf-8",
            )

            status = readiness.inspect_host_availability(log, 10_000)

            self.assertTrue(status.virtual_gamepad_available)
            self.assertEqual(status.unavailable_reason, "")
            self.assertIn("available", status.last_controller_line)

    def test_virtual_hid_entitlement_requires_exact_true_value(self) -> None:
        entitlement_text = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <plist version=\"1.0\"><dict>
        <key>com.apple.developer.hid.virtual.device</key><false/>
        <key>com.example.other</key><true/>
        </dict></plist>
        """

        self.assertFalse(readiness.virtual_hid_entitlement_present(entitlement_text))

        self.assertTrue(
            readiness.virtual_hid_entitlement_present(
                "Executable=/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen\n"
                "<?xml version=\"1.0\"?><plist version=\"1.0\"><dict>"
                "<key>com.apple.developer.hid.virtual.device</key><true/>"
                "</dict></plist>"
                "\nwarning: trailing codesign text"
            )
        )

    def test_build_result_blocks_on_missing_hardware_and_host(self) -> None:
        result = readiness.build_result(
            run_id="run-1",
            created_at="2026-08-20T00:00:00Z",
            device=self.sample_device(),
            package=self.sample_package(),
            controller_devices=[],
            host_signing=readiness.HostSigningStatus(None, False, False, "", "", ""),
            host_availability=readiness.HostAvailabilityStatus(
                "host.log",
                False,
                "Controller forwarding unavailable: missing entitlement",
                "missing entitlement",
            ),
        )

        self.assertEqual(result.summary["verdict"], "blocked")
        self.assertFalse(result.summary["can_close_runtime_gate"])
        self.assertIn("physical_controller_attached", {item["field"] for item in result.summary["blocking_reasons"]})
        self.assertTrue(result.observations["device_identity_recorded"])
        self.assertTrue(result.observations["apk_identity_recorded"])

    def test_main_writes_readiness_bundle(self) -> None:
        package_raw = """
        versionCode=100000 minSdk=26 targetSdk=34
        versionName=0.0.0
        firstInstallTime=2026-08-20 10:00:00
        lastUpdateTime=2026-08-20 10:00:00
        """
        host_line = "2026-08-20T10:00:28Z Controller forwarding unavailable: use an Apple identity-signed build\n"

        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            host_log = Path(temporary_directory) / "host.log"
            host_log.write_text(host_line, encoding="utf-8")
            with (
                mock.patch.object(
                    readiness,
                    "read_device_identity",
                    return_value=(self.sample_device(), "List of devices attached\n"),
                ),
                mock.patch.object(
                    readiness,
                    "read_package_identity",
                    return_value=(self.sample_package(), package_raw),
                ),
                mock.patch.object(
                    readiness,
                    "adb",
                    return_value=readiness.CommandResult(
                        ["adb"],
                        0,
                        "Device 1: touch\n  IsExternal: false\n  Sources: TOUCHSCREEN\n",
                        "",
                    ),
                ),
            ):
                exit_code = readiness.main(
                    [
                        "--serial",
                        "EP0110PZ0B9110300B",
                        "--host-log",
                        str(host_log),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--run-id",
                        "run-test",
                    ]
                )

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            summary = json.loads((evidence_dir / "controller-runtime-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["run_id"], "run-test")
            self.assertEqual(summary["verdict"], "blocked")
            self.assertTrue((evidence_dir / "device-info.json").exists())
            self.assertTrue((evidence_dir / "dumpsys-input.txt").exists())
            self.assertTrue((evidence_dir / "host-controller-availability.txt").exists())
            readme = (evidence_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("Controller runtime readiness: blocked", readme)


if __name__ == "__main__":
    unittest.main()
