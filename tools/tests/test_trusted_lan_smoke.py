import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.trusted_lan_smoke import evaluate_evidence_dir


class TrustedLANSmokeEvidenceTest(unittest.TestCase):
    def test_blocked_preflight_is_a_valid_blocked_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "wlan0 reported NO-CARRIER state DOWN and Wifi is not connected.\n"
                "Host preflight failed because the Vibe Screen Dev codesign identity is missing.\n"
                "No real trusted-LAN stream was observed.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "blocked")
        self.assertEqual(report["errors"], [])

    def test_pass_requires_non_legacy_encrypted_lan_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "Protocol v1 over TRANSPORT_KIND_LAN and reconnect were observed.\n"
                "Decoder: HEVC.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("telemetry_encrypted" in error for error in report["errors"]))

    def test_nubia_record_must_not_be_labeled_as_xiaomi_or_fuxi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke - BLOCKED\n\n"
                "Device: nubia P0110 / pacific / Android 16, also fuxi.\n"
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

    def test_open_reconnect_gate_does_not_count_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Nubia P0110 trusted-LAN smoke\n\n"
                "Device: nubia P0110 / pacific / Android 16.\n"
                "Trusted LAN secure records negotiated.\n"
                "Wireless connected (trusted LAN encrypted records).\n"
                "trusted_lan_encrypted=true trusted_lan_legacy_plaintext=false.\n"
                "Protocol v1 over TRANSPORT_KIND_LAN. Decoder: HEVC.\n"
                "Reconnect remains open.\n",
                encoding="utf-8",
            )

            report = evaluate_evidence_dir(root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("reconnect_success" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
