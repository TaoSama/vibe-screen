from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_runtime_readiness as readiness

SAMPLE_DEVICE_SERIAL = "sample-p0110-device-serial"


class ControllerRuntimeReadinessRedactionTests(unittest.TestCase):
    def sample_device(self) -> readiness.DeviceIdentity:
        return readiness.DeviceIdentity(
            serial=SAMPLE_DEVICE_SERIAL,
            endpoint=f"{SAMPLE_DEVICE_SERIAL} device product:pacific model:P0110 device:pacific",
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

    def sample_host_signing(self) -> readiness.HostSigningStatus:
        return readiness.HostSigningStatus(
            host_app=str(Path.home() / "Applications/Vibe Screen.app"),
            identity_signed=False,
            virtual_hid_entitlement_present=False,
            team_identifier="not set",
            codesign_summary="Executable=/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen",
            entitlement_summary='<plist version="1.0"><dict></dict></plist>',
        )

    def sample_host_availability(self) -> readiness.HostAvailabilityStatus:
        return readiness.HostAvailabilityStatus(
            host_log=str(Path.home() / "Library/Logs/Telemachus/telemachus.log"),
            virtual_gamepad_available=False,
            last_controller_line=f"Controller forwarding unavailable for {SAMPLE_DEVICE_SERIAL}",
            unavailable_reason="missing entitlement",
        )

    def test_read_source_commit_reports_git_failure(self) -> None:
        with mock.patch.object(
            readiness,
            "run_command",
            return_value=readiness.CommandResult(["git"], 128, "", "not a git repository"),
        ):
            with self.assertRaisesRegex(readiness.ReadinessError, "failed to read source commit"):
                readiness.read_source_commit()

    def test_redacted_device_identity_preserves_public_model_fields(self) -> None:
        device = readiness.redacted_device_identity(self.sample_device(), SAMPLE_DEVICE_SERIAL)

        self.assertEqual(device.serial, "<device-serial>")
        self.assertIn("product:pacific model:P0110 device:pacific", device.endpoint)
        self.assertNotIn(SAMPLE_DEVICE_SERIAL, device.endpoint)
        self.assertEqual(device.manufacturer, "nubia")
        self.assertEqual(device.model, "P0110")
        self.assertEqual(device.device, "pacific")
        self.assertEqual(device.android_release, "16")
        self.assertEqual(device.sdk, "36")

    def test_redact_evidence_text_removes_serial_and_home_path(self) -> None:
        raw = str(Path.home() / "Library/Logs/Telemachus/telemachus.log") + f" {SAMPLE_DEVICE_SERIAL}"

        redacted = readiness.redact_evidence_text(raw, SAMPLE_DEVICE_SERIAL)

        self.assertIn("~/Library/Logs/Telemachus/telemachus.log", redacted)
        self.assertIn("<device-serial>", redacted)
        self.assertNotIn(str(Path.home()), redacted)
        self.assertNotIn(SAMPLE_DEVICE_SERIAL, redacted)

    def test_redacted_auxiliary_records_remove_raw_local_detail(self) -> None:
        package = readiness.redacted_package_identity(self.sample_package())
        controllers = readiness.redacted_controller_devices(
            [
                readiness.InputDeviceSummary(
                    name="External Controller",
                    classes="0x00000041",
                    sources="GAMEPAD JOYSTICK",
                    is_external="true",
                    descriptor="usb:vendor=1234,product=5678,serial=sample-device-descriptor",
                )
            ]
        )
        signing = readiness.redacted_host_signing(self.sample_host_signing())
        availability = readiness.redacted_host_availability(
            self.sample_host_availability(),
            SAMPLE_DEVICE_SERIAL,
        )

        self.assertEqual(package.raw_summary, "redacted package signature summary")
        self.assertEqual(controllers[0].descriptor, "redacted-device-descriptor")
        self.assertNotIn("sample-device-descriptor", json.dumps([controller.__dict__ for controller in controllers]))
        self.assertEqual(signing.host_app, "redacted-host-app")
        self.assertEqual(signing.team_identifier, "not set")
        self.assertEqual(signing.codesign_summary, "redacted codesign summary")
        self.assertEqual(signing.entitlement_summary, "redacted entitlement summary")
        self.assertEqual(availability.host_log, "redacted-host-log")
        self.assertIn("<device-serial>", availability.last_controller_line)
        self.assertNotIn(SAMPLE_DEVICE_SERIAL, availability.last_controller_line)

        signed = readiness.redacted_host_signing(
            readiness.HostSigningStatus(
                host_app="/Applications/Vibe Screen.app",
                identity_signed=True,
                virtual_hid_entitlement_present=True,
                team_identifier="TEAMID1234",
                codesign_summary="TeamIdentifier=TEAMID1234",
                entitlement_summary="virtual HID entitlement present",
            )
        )
        self.assertEqual(signed.team_identifier, "redacted-team-identifier")
        self.assertNotIn("TEAMID1234", signed.codesign_summary)

    def test_main_redacts_committed_evidence_when_requested(self) -> None:
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
                    return_value=(
                        self.sample_device(),
                        f"List of devices attached\n{SAMPLE_DEVICE_SERIAL} device product:pacific model:P0110 device:pacific\n",
                    ),
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
                        (
                            "Device 1: External Controller\n"
                            "  Classes: 0x00000041\n"
                            "  Descriptor: usb:vendor=1234,product=5678,serial=sample-device-descriptor\n"
                            "  IsExternal: true\n"
                            "  Sources: GAMEPAD JOYSTICK\n"
                        ),
                        "",
                    ),
                ),
                mock.patch.object(readiness, "DEVICE_LOCKS", ()),
                mock.patch.object(readiness, "read_source_commit", return_value="abc123"),
            ):
                exit_code = readiness.main(
                    [
                        "--serial",
                        SAMPLE_DEVICE_SERIAL,
                        "--host-log",
                        str(host_log),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--run-id",
                        "run-test",
                        "--redact-identifiers",
                    ]
                )

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            readme = (evidence_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("serial <device-serial>", readme)
            self.assertNotIn(SAMPLE_DEVICE_SERIAL, readme)
            device_info = json.loads((evidence_dir / "device-info.json").read_text(encoding="utf-8"))
            self.assertEqual(device_info["serial"], "<device-serial>")
            self.assertNotIn(SAMPLE_DEVICE_SERIAL, device_info["endpoint"])
            readiness_record = json.loads((evidence_dir / "controller-runtime-readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness_record["source_commit"], "abc123")
            self.assertEqual(
                readiness_record["device"]["endpoint"],
                "redacted adb endpoint product:pacific model:P0110 device:pacific",
            )
            self.assertEqual(
                readiness_record["device"]["fingerprint_sha256"],
                "redacted-build-fingerprint-sha256",
            )
            self.assertEqual(readiness_record["host_availability"]["host_log"], "redacted-host-log")
            self.assertEqual(
                readiness_record["host_signing"]["codesign_summary"],
                "redacted codesign summary",
            )
            self.assertEqual(
                readiness_record["package"]["raw_summary"],
                "redacted package signature summary",
            )
            self.assertEqual(
                readiness_record["controller_devices"][0]["descriptor"],
                "redacted-device-descriptor",
            )
            self.assertFalse((evidence_dir / "adb-devices.txt").exists())
            self.assertFalse((evidence_dir / "dumpsys-input.txt").exists())
            self.assertFalse((evidence_dir / "dumpsys-package.txt").exists())
            self.assertFalse((evidence_dir / "host-controller-availability.txt").exists())
            self.assertNotIn(SAMPLE_DEVICE_SERIAL, json.dumps(readiness_record))
            self.assertNotIn("sample-device-descriptor", json.dumps(readiness_record))

    def test_lock_blocked_evidence_redacts_requested_serial_and_lock_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            readiness.write_lock_blocked_evidence(
                evidence_dir,
                requested_serial=SAMPLE_DEVICE_SERIAL,
                created_at="2026-08-25T00:00:00Z",
                source_commit="abc123",
                run_id="lock-run",
                locks=[{"path": "/tmp/device.lock", "detail": f"owner={SAMPLE_DEVICE_SERIAL}"}],
                redact_identifiers=True,
            )

            readiness_record = json.loads((evidence_dir / "controller-runtime-readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness_record["requested_serial"], "<device-serial>")
            self.assertIn("<device-serial>", readiness_record["existing_locks"][0]["detail"])
            self.assertNotIn(SAMPLE_DEVICE_SERIAL, json.dumps(readiness_record))



    def test_redacted_host_readiness_removes_serial_and_home_path(self) -> None:
        state = {
            "present": True,
            "readable": True,
            "document": {
                "can_start_controller_runtime_gate": False,
                "blockers": [f"Host serial {SAMPLE_DEVICE_SERIAL} blocked", str(Path.home() / "tmp" / "host.log")],
                "entitlements": {"virtual_hid": False},
                "host": {"team_identifier": "TEAMID1234"},
            },
        }

        redacted = readiness.redact_host_readiness(state, SAMPLE_DEVICE_SERIAL)

        serialized = json.dumps(redacted)
        self.assertNotIn(SAMPLE_DEVICE_SERIAL, serialized)
        self.assertNotIn(str(Path.home()), serialized)
        self.assertIn("<device-serial>", serialized)
        self.assertIn("~/tmp/host.log", serialized)

if __name__ == "__main__":
    unittest.main()
