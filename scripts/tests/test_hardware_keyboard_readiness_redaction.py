from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hardware_keyboard_readiness as readiness


SAMPLE_SERIAL = "test-p0110-adb-serial"


class HardwareKeyboardReadinessRedactionTests(unittest.TestCase):
    def test_redact_text_removes_serial_and_local_paths(self) -> None:
        raw = (
            f"adb -s {SAMPLE_SERIAL} shell input keyevent A\n"
            f"{readiness.REPO_ROOT}/scripts/macos_dev_host.py\n"
            f"{Path.home()}/Library/Android/sdk/platform-tools/adb\n"
            "/tmp/vibe-screen-p0110-runtime-gates-clean-evidence/hardware-keyboard/host-signing-and-permissions.txt\n"
        )

        redacted = readiness.redact_text(raw, SAMPLE_SERIAL)

        self.assertIn("adb -s <device-serial> shell input keyevent A", redacted)
        self.assertIn("<repo-root>/scripts/macos_dev_host.py", redacted)
        self.assertIn("<android-sdk>/platform-tools/adb", redacted)
        self.assertIn("<tmp-evidence>", redacted)
        self.assertNotIn(SAMPLE_SERIAL, redacted)
        self.assertNotIn(str(readiness.REPO_ROOT), redacted)
        self.assertNotIn(str(Path.home()), redacted)
        self.assertNotIn("/tmp/vibe-screen-p0110-runtime-gates-clean-evidence", redacted)

    def test_redact_text_replaces_longer_overlapping_serials_first(self) -> None:
        redacted = readiness.redact_text("device ABC123 also has prefix ABC", "ABC", "ABC123")

        self.assertEqual(redacted, "device <device-serial> also has prefix <device-serial>")
        self.assertNotIn("ABC", redacted)

    def test_redacts_adb_devices_non_target_endpoint_and_lsof_user(self) -> None:
        adb_devices = (
            "List of devices attached\n"
            f"{SAMPLE_SERIAL} device product:pacific model:P0110 device:pacific\n"
            "test-emulator-endpoint device product:sdk_phone64_arm64 model:Android_SDK_built_for_arm64 device:emu64a\n"
        )
        lsof_output = (
            "COMMAND     PID     USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n"
            "Vibe\\x20S 22385 localuser    7u  IPv4 0x123      0t0  TCP 127.0.0.1:54321 (LISTEN)\n"
        )

        redacted_devices = readiness.redact_adb_devices_text(adb_devices, SAMPLE_SERIAL)
        redacted_lsof = readiness.redact_text(lsof_output)

        self.assertIn("<device-serial> device product:pacific", redacted_devices)
        self.assertIn("<adb-endpoint> device product:sdk_phone64_arm64", redacted_devices)
        self.assertNotIn(SAMPLE_SERIAL, redacted_devices)
        self.assertNotIn("test-emulator-endpoint", redacted_devices)
        self.assertIn("Vibe\\x20S 22385 <user>", redacted_lsof)
        self.assertNotIn("localuser", redacted_lsof)

    def test_android_dumpsys_redaction_removes_window_tokens_and_serials(self) -> None:
        raw = (
            f"{SAMPLE_SERIAL} token=0xb400007b62b3a410 "
            "applicationInfo.token=<null>\n"
        )

        redacted = readiness.redact_android_dumpsys_text(raw, SAMPLE_SERIAL)

        self.assertEqual(redacted, "<device-serial> token=<redacted> applicationInfo.token=<redacted>")
        self.assertNotIn(SAMPLE_SERIAL, redacted)
        self.assertNotIn("0xb400007b62b3a410", redacted)

    def test_device_info_document_can_store_redacted_device_identity(self) -> None:
        raw_device = readiness.DeviceIdentity(
            serial=SAMPLE_SERIAL,
            endpoint=f"{SAMPLE_SERIAL} device product:pacific model:P0110 device:pacific",
            manufacturer="nubia",
            model="P0110",
            device="pacific",
            product="pacific",
            android_release="16",
            sdk="36",
            build_fingerprint="nubia/pacific/fingerprint",
            abi="arm64-v8a",
            device_serial=SAMPLE_SERIAL,
        )
        document = readiness.device_info_document(
            created_at="2026-08-24T00:00:00Z",
            connection=readiness.redact_text(f"already connected to {SAMPLE_SERIAL}", SAMPLE_SERIAL),
            adb_version="Android Debug Bridge version 1.0.41",
            device=readiness.redacted_device_identity(raw_device),
            package=None,
        )

        serialized = json.dumps(document, sort_keys=True)
        self.assertEqual(document["connection"], "already connected to <device-serial>")
        self.assertEqual(document["device"]["adb_serial"], "<device-serial>")
        self.assertEqual(document["device"]["device_serial"], "<device-serial>")
        self.assertIn("nubia", serialized)
        self.assertNotIn(SAMPLE_SERIAL, serialized)

    def test_format_command_result_redacts_serials_from_host_output(self) -> None:
        result = readiness.CommandResult(
            ["macos-preflight", SAMPLE_SERIAL],
            1,
            f"stdout mentions {SAMPLE_SERIAL}\n",
            f"stderr mentions {SAMPLE_SERIAL}\n",
        )

        redacted = readiness.format_command_result(result, SAMPLE_SERIAL)

        self.assertIn("<device-serial>", redacted)
        self.assertNotIn(SAMPLE_SERIAL, redacted)

    def test_lock_blocked_bundle_redacts_requested_serial_and_lock_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            readiness.write_lock_blocked_evidence(
                evidence_dir,
                serial=SAMPLE_SERIAL,
                created_at="2026-08-24T00:00:00Z",
                run_id="blocked-redaction-run",
                locks=[{"path": str(Path.home() / "lock"), "detail": f"owner={SAMPLE_SERIAL}"}],
            )

            readiness_record = json.loads((evidence_dir / "hardware-keyboard-readiness.json").read_text(encoding="utf-8"))
            lock_record = json.loads((evidence_dir / "device-locks.json").read_text(encoding="utf-8"))
            serialized = json.dumps({"readiness": readiness_record, "locks": lock_record}, sort_keys=True)

            self.assertFalse(readiness_record["device_lock"]["acquired"])
            self.assertIn("<device-serial>", serialized)
            self.assertIn("<home>/lock", serialized)
            self.assertNotIn(SAMPLE_SERIAL, serialized)
            self.assertNotIn(str(Path.home()), serialized)


if __name__ == "__main__":
    unittest.main()
