import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.trusted_lan_smoke import evaluate_evidence_dir


MODULE = "vibescreen_evidence.trusted_lan_smoke"


class TrustedLANSmokeEvidenceTest(unittest.TestCase):
    def test_blocked_preflight_is_a_valid_blocked_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "wlan0 reported NO-CARRIER state DOWN and Wifi is not connected.\n"
                "Host preflight failed because the Vibe Screen Dev codesign identity is missing.\n"
                "No real trusted-LAN stream was observed.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_trusted_lan_stream_gate"])
        self.assertFalse(report["can_close_trusted_lan_reconnect_gate"])
        self.assertEqual(report["errors"], [])

    def test_pass_requires_non_legacy_encrypted_lan_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "Protocol v1 over TRANSPORT_KIND_LAN and reconnect succeeded.\n"
                "Decoder: HEVC. First output frame and continuing frame counters observed.\n"
                "Host PID preserved.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("telemetry_encrypted" in error for error in report["errors"]))

    def test_complete_lan_evidence_can_close_stream_and_reconnect_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "Trusted LAN secure records negotiated.\n"
                "Wireless connected (trusted LAN encrypted records).\n"
                "trusted_lan_encrypted=true trusted_lan_legacy_plaintext=false.\n"
                "Protocol v1 over TRANSPORT_KIND_LAN. Decoder: HEVC.\n"
                "First output frame and continuing frame counters observed.\n"
                "Reconnect succeeded with Host PID preserved.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_trusted_lan_stream_gate"])
        self.assertTrue(report["can_close_trusted_lan_reconnect_gate"])

    def test_nubia_record_must_not_be_labeled_as_xiaomi_or_fuxi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16, also fuxi.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "Wifi is not connected. Vibe Screen Dev signing identity missing.\n"
                "No real trusted-LAN stream was observed.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "README.md must not label Nubia P0110/pacific evidence as Xiaomi 13/fuxi",
            report["errors"],
        )

    def test_requires_device_lock_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "Wifi is not connected. Vibe Screen Dev signing identity missing.\n"
                "No real trusted-LAN stream was observed.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "evidence must record /tmp/vibe-screen-device-android.lock acquisition or equivalent lock observation",
            report["errors"],
        )

    def test_open_reconnect_gate_does_not_count_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "Trusted LAN secure records negotiated.\n"
                "Wireless connected (trusted LAN encrypted records).\n"
                "trusted_lan_encrypted=true trusted_lan_legacy_plaintext=false.\n"
                "Protocol v1 over TRANSPORT_KIND_LAN. Decoder: HEVC.\n"
                "First output frame and continuing frame counters observed.\n"
                "Reconnect remains open. Host PID recorded.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("reconnect_success" in error for error in report["errors"]))


class TrustedLANSmokeCliTest(unittest.TestCase):
    def test_cli_writes_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "verdict.json"
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "/tmp/vibe-screen-device-android.lock was acquired.\n"
                "Wifi is not connected. Vibe Screen Dev signing identity missing.\n"
                "No real trusted-LAN stream was observed.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "-m", MODULE, "--evidence-dir", str(root), "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
