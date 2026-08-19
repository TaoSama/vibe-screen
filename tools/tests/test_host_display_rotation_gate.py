from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.host_display_rotation_gate import KIND, evaluate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.host_display_rotation_gate"


def complete_run(display_kind: str, rotation: int = 90) -> dict:
    return {
        "display_kind": display_kind,
        "display_id": f"{display_kind}-display-1",
        "transport": "usb",
        "host_rotation_degrees": rotation,
        "original_host_rotation_degrees": 0,
        "client_rotation_degrees": 0,
        "client_transform_scope": "client-local-only",
        "host_rotation_combined_with_client_transform": False,
        "host_rotation_source": "macOS Displays settings",
        "probes": {
            "visual_source_orientation": True,
            "input_mapping": True,
            "stable_stream": True,
            "no_session_teardown": True,
            "restored_original_host_rotation": True,
        },
        "artifacts": {
            "device_identity": "device-and-artifact-identity.txt",
            "host_display_snapshot_before": "host-display-before.txt",
            "host_display_snapshot_rotated": "host-display-rotated.txt",
            "android_screenshot": "android-rotated-host-display.png",
            "touch_matrix": "touch-matrix.txt",
            "host_log": "host.log",
            "android_logcat": "logcat.txt",
        },
    }


def complete_document() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "runs": [complete_run("physical"), complete_run("virtual", 270)],
    }


class HostDisplayRotationGateTest(unittest.TestCase):
    def test_accepts_complete_physical_and_virtual_evidence(self) -> None:
        result = evaluate(complete_document())

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["covered_display_kinds"], ["physical", "virtual"])
        self.assertEqual(result["errors"], [])

    def test_requires_both_display_kinds(self) -> None:
        document = complete_document()
        document["runs"] = [complete_run("physical")]

        result = evaluate(document)

        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "runs: missing rotated virtual host-display evidence", result["errors"]
        )

    def test_rejects_client_local_matrix_as_host_rotation_evidence(self) -> None:
        document = complete_document()
        document["runs"][0]["host_rotation_degrees"] = 0
        document["runs"][0]["host_rotation_combined_with_client_transform"] = True

        result = evaluate(document)

        self.assertIn(
            "runs[0].host_rotation_degrees: must be 90, 180, or 270",
            result["errors"],
        )
        self.assertIn(
            "runs[0].host_rotation_combined_with_client_transform: must be false",
            result["errors"],
        )

    def test_requires_probe_and_artifact_records(self) -> None:
        document = complete_document()
        del document["runs"][1]["probes"]["input_mapping"]
        document["runs"][1]["artifacts"]["touch_matrix"] = ""

        result = evaluate(document)

        self.assertIn("runs[1].probes.input_mapping: must be true", result["errors"])
        self.assertIn(
            "runs[1].artifacts.touch_matrix: must reference a retained artifact",
            result["errors"],
        )


class HostDisplayRotationGateCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_writes_complete_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "host-display-rotation.json"
            output_path = Path(directory) / "gate-result.json"
            input_path.write_text(json.dumps(complete_document()), encoding="utf-8")

            result = self.run_cli(str(input_path), "--output", str(output_path))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "complete")

    def test_cli_reports_missing_virtual_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "host-display-rotation.json"
            document = complete_document()
            document["runs"] = [complete_run("physical")]
            input_path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli(str(input_path))

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing rotated virtual host-display evidence", result.stderr
            )
            self.assertEqual(json.loads(result.stdout)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
