import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import GATE_USB_GLASS_TO_GLASS_SUB50
from tools.vibescreen_evidence.latency_evidence import build_latency_evidence_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_evidence"
FIXTURE_DIR = REPOSITORY_ROOT / "tools" / "fixtures" / "latency"


class LatencyEvidenceReportTest(unittest.TestCase):
    def test_valid_external_camera_package_passes(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "external-camera-valid" / "manifest.json",
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["gate"]["can_close_performance_gate"])
        self.assertEqual(report["gate"]["sample_count"], 5)
        self.assertEqual(report["gate"]["reasons"], [])

    def test_missing_raw_camera_artifact_is_insufficient(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "external-camera-missing-video" / "manifest.json",
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertTrue(
            any("recording.raw_video does not exist" in reason for reason in report["gate"]["reasons"])
        )

    def test_numeric_camera_frame_rate_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            manifest["camera"]["frame_rate_fps"] = 240
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "samples.csv").write_text((source / "samples.csv").read_text(encoding="utf-8"), encoding="utf-8")
            (root / "raw-camera-placeholder.mov").write_text("placeholder", encoding="utf-8")

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")

    def test_manifest_mismatch_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            manifest["transport"] = "lan"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "samples.csv").write_text((source / "samples.csv").read_text(encoding="utf-8"), encoding="utf-8")
            (root / "raw-camera-placeholder.mov").write_text("placeholder", encoding="utf-8")

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("requires --transport usb" in reason for reason in report["gate"]["reasons"]))


class LatencyEvidenceCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_passes_valid_external_camera_package(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "external-camera-valid" / "manifest.json"),
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "pass")
        self.assertEqual(output["measurement_method"], "external-camera")

    def test_cli_outputs_insufficient_json_for_missing_manifest(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "external-camera-valid" / "missing-manifest.json"),
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertIn("cannot read latency evidence manifest", output["gate"]["reasons"][0])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
