from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.ios_videotoolbox_readiness import (
    BOOLEAN_FIELDS,
    IOSVideoToolboxReadinessError,
    summarize,
)


MODULE = "vibescreen_evidence.ios_videotoolbox_readiness"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-videotoolbox-readiness.schema.json"


class IOSVideoToolboxReadinessTest(unittest.TestCase):
    def complete_record(self, runtime_class: str = "physical_iphone") -> dict[str, object]:
        record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
        record["runtime_class"] = runtime_class
        return record

    def test_simulator_is_blocked_even_with_decode_observations(self) -> None:
        summary = summarize(self.complete_record("simulator"), run_id="sim-run")

        self.assertEqual(summary["run_id"], "sim-run")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_family_videotoolbox_gate"])
        self.assertFalse(summary["can_close_phase5_hardware_videotoolbox_gate"])
        self.assertEqual(summary["blocking_reasons"][0]["field"], "runtime_class")
        self.assertTrue(summary["simulator_is_not_device_evidence"])

    def test_unsigned_archive_is_blocked(self) -> None:
        summary = summarize(self.complete_record("unsigned_archive"))

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            "unsigned archive",
            summary["blocking_reasons"][0]["requirement"],
        )
        self.assertTrue(summary["unsigned_archive_is_not_device_evidence"])

    def test_physical_device_blocks_without_signing_and_identity(self) -> None:
        record = self.complete_record("physical_ipad")
        record["signed_app_installed"] = False
        record["physical_ios_device_identity_recorded"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {"signed_app_installed", "physical_ios_device_identity_recorded"},
        )

    def test_physical_device_is_insufficient_when_decode_artifacts_are_missing(self) -> None:
        record = self.complete_record("physical_iphone")
        record["hevc_output_frames_observed"] = False
        record["hardware_decode_path_recorded"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_device_family_videotoolbox_gate"])

    def test_physical_device_family_pass_does_not_close_whole_phase5_gate(self) -> None:
        summary = summarize(self.complete_record("physical_ipad"), run_id="ipad-run")

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_device_family_videotoolbox_gate"])
        self.assertFalse(summary["can_close_phase5_hardware_videotoolbox_gate"])
        self.assertIn("both physical_iphone and physical_ipad", summary["phase5_gate_closure_rule"])

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = summarize(self.complete_record())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(
            set(summary["observations"]),
            set(observation_schema["properties"]),
        )
        for field in observation_schema["required"]:
            self.assertIn(field, summary["observations"])

    def test_rejects_invalid_runtime_class(self) -> None:
        record = self.complete_record()
        record["runtime_class"] = "android"

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "runtime_class"):
            summarize(record)

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["videotoolbox_hevc_session_created"] = "yes"

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "must be true or false"):
            summarize(record)

    def test_rejects_empty_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["device.log", ""]

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "artifact_paths"):
            summarize(record)


class IOSVideoToolboxReadinessCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_simulator_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"runtime_class": "simulator", "artifacts_retained": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_phase5_hardware_videotoolbox_gate"])

    def test_cli_rejects_empty_run_id(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", ""],
            input=json.dumps({"runtime_class": "physical_iphone"}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run_id must be a non-empty string", result.stderr)


if __name__ == "__main__":
    unittest.main()
