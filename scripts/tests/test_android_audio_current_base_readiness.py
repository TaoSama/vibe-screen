from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import android_audio_current_base_readiness as readiness
import android_audio_readiness_support as support


SAMPLE_SERIAL = "sample-p0110-adb-serial"


class AndroidAudioCurrentBaseReadinessTests(unittest.TestCase):
    def test_redact_text_removes_public_sensitive_values(self) -> None:
        sample_team_id = "ABCDE" + "12345"
        sample_ip = ".".join(["192", "168", "1", "44"])
        sample_mac = ":".join(["aa", "bb", "cc", "dd", "ee", "ff"])
        raw = (
            f"adb -s {SAMPLE_SERIAL} shell ip addr show wlan0\n"
            f"{support.REPO_ROOT}/scripts/android_audio_current_base_readiness.py\n"
            f"{Path.home()}/Library/Application Support/com.apple.TCC/TCC" + ".db\n"
            f"TeamIdentifier={sample_team_id}\n"
            f"OU={sample_team_id}\n"
            f"inet {sample_ip}/24\n"
            f"ether {sample_mac}\n"
        )

        redacted = support.redact_text(raw, SAMPLE_SERIAL)

        self.assertIn("adb -s <ANDROID_SERIAL> shell ip addr show wlan0", redacted)
        self.assertIn("<repo-root>/scripts/android_audio_current_base_readiness.py", redacted)
        self.assertIn("<home>/Library/<tcc-store>/<tcc-db>", redacted)
        self.assertIn("TeamIdentifier=<TEAM_ID>", redacted)
        self.assertIn("OU=<TEAM_ID>", redacted)
        self.assertIn("inet <ipv4>/24", redacted)
        self.assertIn("ether <mac-address>", redacted)
        self.assertNotIn(SAMPLE_SERIAL, redacted)
        self.assertNotIn(str(support.REPO_ROOT), redacted)
        self.assertNotIn(str(Path.home()), redacted)
        self.assertNotIn(sample_ip, redacted)
        self.assertNotIn(sample_mac, redacted)

    def test_redact_json_replaces_serial_fields(self) -> None:
        document = {
            "device": {
                "adb_serial": SAMPLE_SERIAL,
                "device_serial": SAMPLE_SERIAL,
                "build_fingerprint": "nubia/pacific/private-build",
                "nested": [f"connected to {SAMPLE_SERIAL}"],
            },
            "team_identifier": "ABCDE12345",
            "observed_at": "2026-08-29 10:00:50",
        }

        redacted = support.redact_json(document, SAMPLE_SERIAL)
        serialized = json.dumps(redacted, sort_keys=True)

        self.assertEqual(redacted["device"]["adb_serial"], "<ANDROID_SERIAL>")
        self.assertEqual(redacted["device"]["device_serial"], "<ANDROID_DEVICE_SERIAL>")
        self.assertEqual(redacted["device"]["build_fingerprint"], "redacted-build-fingerprint")
        self.assertEqual(redacted["team_identifier"], "<TEAM_ID>")
        self.assertEqual(redacted["observed_at"], "2026-08-29 10:00:50")
        self.assertNotIn(SAMPLE_SERIAL, serialized)
        self.assertNotIn("private-build", serialized)

    def test_loopback_usb_transport_log_is_not_synthetic_audio_marker(self) -> None:
        self.assertFalse(readiness.has_non_product_audio_marker("Client connected via loopback (USB)"))
        self.assertTrue(readiness.has_non_product_audio_marker("synthetic audio harness accepted"))

    def test_build_observations_stays_blocked_without_real_audio_markers(self) -> None:
        observations = readiness.build_observations(
            run_id="run-1",
            device={
                "adb_serial": "<ANDROID_SERIAL>",
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": 36,
                "build_fingerprint": "nubia/pacific/pacific:16/example:userdebug/test-keys",
            },
            package={"package": "dev.telemachus.display"},
            host_readiness={"signing_tcc_status": "blocked", "listener": {"observed": False}},
            android_text="Protocol v1 session accepted with video only",
            host_text="Host audio log was not found at the expected development log path.",
            adb_state="device",
            network_text="wlan0: <NO-CARRIER> state DOWN",
        )

        self.assertTrue(observations["android_device_lock_acquired"])
        self.assertTrue(observations["device_identity_matches_claim"])
        self.assertFalse(observations["host_stable_signed_tcc_ready"])
        self.assertFalse(observations["host_listener_observed"])
        self.assertFalse(observations["audio_capability_negotiated"])
        self.assertFalse(observations["android_audio_track_started"])
        self.assertFalse(observations["android_audio_packets_written"])
        self.assertFalse(observations["playback_output_confirmed"])
        self.assertTrue(observations["no_synthetic_or_loopback_markers"])

    def test_write_readme_keeps_blocked_claim_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            readiness.write_readme(
                evidence_dir,
                commit="3508f229a5fb1218388e9e9ee5fec919d6b5bebf",
                summary={
                    "verdict": "blocked",
                    "can_close_android_audio_playback_gate": False,
                    "missing_requirements": [{"field": "audio_capability_negotiated"}],
                    "blocking_reasons": [{"field": "host_stable_signed_tcc_ready"}],
                },
            )

            content = (evidence_dir / "README.md").read_text(encoding="utf-8")

        self.assertIn("blocked before real USB/LAN audio playback acceptance", content)
        self.assertIn("verdict=blocked", content)
        self.assertIn("can_close_android_audio_playback_gate=false", content)
        self.assertIn("must not be cited as Android", content)
        self.assertIn("<ANDROID_SERIAL>", content)

    def test_write_readme_uses_evidence_dir_date_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "2026-08-30-p0110-audio-current-base-refresh"
            evidence_dir.mkdir()
            readiness.write_readme(
                evidence_dir,
                commit="3508f229a5fb1218388e9e9ee5fec919d6b5bebf",
                summary={
                    "verdict": "blocked",
                    "can_close_android_audio_playback_gate": False,
                    "missing_requirements": [],
                    "blocking_reasons": [],
                },
            )

            content = (evidence_dir / "README.md").read_text(encoding="utf-8")

        self.assertIn("# P0110 Android audio current-base refresh - 2026-08-30", content)

    def test_source_does_not_call_forbidden_sfltool_dump(self) -> None:
        source = Path(readiness.__file__).read_text(encoding="utf-8")
        executable_lines = [line for line in source.splitlines() if "run_command([" in line]

        self.assertIn('"pgrep", "-x", "sfltool"', source)
        self.assertNotIn("dump" + "btm", "\n".join(executable_lines))
        self.assertNotIn("probe-login" + "-item", "\n".join(executable_lines))

    def test_device_lock_blocks_without_running_adb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "device.lock"
            lock_path.write_text("busy\n", encoding="utf-8")

            lock = support.acquire_device_lock(lock_path)

        self.assertFalse(lock.acquired)
        self.assertIn("blocked collection", lock.detail)

    def test_command_result_redacts_serial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "command.txt"
            result = subprocess.CompletedProcess(
                ["adb", "-s", SAMPLE_SERIAL, "devices", "-l"],
                0,
                f"{SAMPLE_SERIAL} device product:pacific model:P0110\n",
                "",
            )
            support.write_command_result(path, result, SAMPLE_SERIAL)
            content = path.read_text(encoding="utf-8")

        self.assertIn("adb -s <ANDROID_SERIAL> devices -l", content)
        self.assertNotIn(SAMPLE_SERIAL, content)


if __name__ == "__main__":
    unittest.main()
