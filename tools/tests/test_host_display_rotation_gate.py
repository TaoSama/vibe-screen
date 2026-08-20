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
GATE_SCHEMA_PATH = (
    REPOSITORY_ROOT / "tools" / "schemas" / "host-display-rotation-gate.schema.json"
)
EVIDENCE_SCHEMA_PATH = (
    REPOSITORY_ROOT / "tools" / "schemas" / "host-display-rotation-evidence.schema.json"
)


def complete_run(display_kind: str, rotation: int = 90) -> dict:
    return {
        "display_kind": display_kind,
        "display_id": f"{display_kind}-display-1",
        "transport": "usb",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
            "adb_serial": "EP0110PZ0B9110300B",
        },
        "host_preflight": {
            "host_signing_identity": "Vibe Screen Dev",
            "host_bundle_id": "dev.telemachus.display",
            "screen_recording_granted": True,
            "accessibility_granted": True,
            "signing_tcc_match": True,
            "host_display_rotation_restoration_plan": True,
        },
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
    def assert_schema_node(self, value: object, node: dict, root: dict, path: str = "$") -> None:
        if "const" in node:
            self.assertEqual(value, node["const"], path)
        if "enum" in node:
            self.assertIn(value, node["enum"], path)
        if "$ref" in node:
            reference = node["$ref"]
            self.assertTrue(reference.startswith("#/$defs/"), path)
            self.assert_schema_node(value, root["$defs"][reference.removeprefix("#/$defs/")], root, path)
            return
        expected_type = node.get("type")
        if expected_type == "object":
            self.assertIsInstance(value, dict, path)
            keys = set(value)
            required = set(node.get("required", []))
            self.assertEqual(required - keys, set(), path)
            if node.get("additionalProperties") is False:
                self.assertEqual(keys - set(node.get("properties", {})), set(), path)
            for key, child in node.get("properties", {}).items():
                if key in value:
                    self.assert_schema_node(value[key], child, root, f"{path}.{key}")
        elif expected_type == "array":
            self.assertIsInstance(value, list, path)
            if "minItems" in node:
                self.assertGreaterEqual(len(value), node["minItems"], path)
            for index, item in enumerate(value):
                self.assert_schema_node(item, node["items"], root, f"{path}[{index}]")
        elif expected_type == "string":
            self.assertIsInstance(value, str, path)
            if "minLength" in node:
                self.assertGreaterEqual(len(value), node["minLength"], path)
        elif expected_type == "integer":
            self.assertIsInstance(value, int, path)
            self.assertNotIsInstance(value, bool, path)
            if "minimum" in node:
                self.assertGreaterEqual(value, node["minimum"], path)
        elif expected_type == "boolean":
            self.assertIsInstance(value, bool, path)

    def assert_matches_schema(self, value: dict, schema_path: Path) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assert_schema_node(value, schema, schema)

    def test_accepts_complete_physical_and_virtual_evidence(self) -> None:
        result = evaluate(complete_document())

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["covered_display_kinds"], ["physical", "virtual"])
        self.assertEqual(result["errors"], [])

    def test_complete_evidence_matches_published_input_schema(self) -> None:
        self.assert_matches_schema(complete_document(), EVIDENCE_SCHEMA_PATH)

    def test_gate_result_matches_published_output_schema(self) -> None:
        self.assert_matches_schema(evaluate(complete_document()), GATE_SCHEMA_PATH)

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

    def test_requires_device_identity_and_host_preflight(self) -> None:
        document = complete_document()
        document["runs"][0]["device"]["manufacturer"] = ""
        document["runs"][0]["device"]["sdk"] = True
        document["runs"][0]["host_preflight"]["screen_recording_granted"] = False
        document["runs"][0]["host_preflight"]["host_signing_identity"] = ""

        result = evaluate(document)

        self.assertIn(
            "runs[0].device.manufacturer: must be a non-empty string",
            result["errors"],
        )
        self.assertIn("runs[0].device.sdk: must be a positive integer", result["errors"])
        self.assertIn(
            "runs[0].host_preflight.screen_recording_granted: must be true",
            result["errors"],
        )
        self.assertIn(
            "runs[0].host_preflight.host_signing_identity: must be a non-empty string",
            result["errors"],
        )

    def test_rejects_non_usb_lan_transport(self) -> None:
        document = complete_document()
        document["runs"][0]["transport"] = "internet"

        result = evaluate(document)

        self.assertIn(
            "runs[0].transport: must be one of ['lan', 'usb']",
            result["errors"],
        )

    def test_requires_host_rotation_to_change_from_original(self) -> None:
        document = complete_document()
        document["runs"][0]["host_rotation_degrees"] = 90
        document["runs"][0]["original_host_rotation_degrees"] = 90

        result = evaluate(document)

        self.assertIn(
            "runs[0].host_rotation_degrees: must differ from original_host_rotation_degrees",
            result["errors"],
        )

    def test_optional_artifact_check_requires_retained_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory)
            document = complete_document()
            for run in document["runs"]:
                for artifact in run["artifacts"].values():
                    path = evidence_dir / artifact
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("retained evidence\n", encoding="utf-8")
            missing = evidence_dir / document["runs"][1]["artifacts"]["host_log"]
            missing.unlink()

            result = evaluate(document, evidence_dir=evidence_dir)

            self.assertEqual(result["artifact_file_check"], True)
            self.assertIn(
                f"runs[1].artifacts.host_log: retained artifact not found at {missing}",
                result["errors"],
            )

    def test_artifact_check_rejects_parent_directory_escape(self) -> None:
        document = complete_document()
        document["runs"][0]["artifacts"]["host_log"] = "../host.log"

        result = evaluate(document, evidence_dir=Path("/tmp/evidence"))

        self.assertIn(
            "runs[0].artifacts.host_log: must be a relative path inside the evidence directory",
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

    def test_cli_check_artifacts_reports_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory)
            input_path = evidence_dir / "host-display-rotation.json"
            input_path.write_text(json.dumps(complete_document()), encoding="utf-8")

            result = self.run_cli(str(input_path), "--check-artifacts")

            self.assertEqual(result.returncode, 1)
            self.assertIn("retained artifact not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
