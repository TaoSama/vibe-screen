from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.ios_videotoolbox_readiness import (
    BOOLEAN_FIELDS,
    IOSVideoToolboxReadinessError,
    summarize,
)


MODULE = "vibescreen_evidence.ios_videotoolbox_readiness"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-videotoolbox-readiness.schema.json"
PASS_ARTIFACTS = [
    "ios-videotoolbox/videotoolbox-h264-session.log",
    "ios-videotoolbox/videotoolbox-hevc-session.log",
    "ios-videotoolbox/videotoolbox-output-frames.log",
    "ios-videotoolbox/videotoolbox-telemetry-power.log",
]


def write_artifacts(directory: Path, names: list[str]) -> None:
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact: {name}\n", encoding="utf-8")


class IOSVideoToolboxReadinessTest(unittest.TestCase):
    def complete_record(self, runtime_class: str = "physical_iphone") -> dict[str, object]:
        record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
        record["runtime_class"] = runtime_class
        record["artifact_paths"] = list(PASS_ARTIFACTS)
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

    def test_artifacts_retained_requires_a_reviewable_artifact_path(self) -> None:
        record = self.complete_record("physical_iphone")
        record["artifact_paths"] = []

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "artifact_paths",
            {item["field"] for item in summary["missing_requirements"]},
        )
        self.assertFalse(summary["can_close_device_family_videotoolbox_gate"])

    def test_physical_device_family_pass_does_not_close_whole_phase5_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_dir = Path(raw_directory)
            write_artifacts(evidence_dir, PASS_ARTIFACTS)

            summary = summarize(
                self.complete_record("physical_ipad"),
                run_id="ipad-run",
                evidence_dir=evidence_dir,
            )

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_device_family_videotoolbox_gate"])
        self.assertFalse(summary["can_close_phase5_hardware_videotoolbox_gate"])
        self.assertIn("both physical_iphone and physical_ipad", summary["phase5_gate_closure_rule"])

    def test_summary_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_dir = Path(raw_directory)
            write_artifacts(evidence_dir, PASS_ARTIFACTS)

            summary = summarize(self.complete_record(), evidence_dir=evidence_dir)
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
        artifact_check_schema = schema["properties"]["artifact_checks"]
        for field in artifact_check_schema["items"]["required"]:
            self.assertIn(field, summary["artifact_checks"][0])

    def test_physical_pass_requires_existing_ios_videotoolbox_artifacts(self) -> None:
        record = self.complete_record()

        summary_without_root = summarize(record)

        self.assertEqual(summary_without_root["verdict"], "insufficient")
        self.assertIn(
            "artifact_paths",
            {item["field"] for item in summary_without_root["missing_requirements"]},
        )
        self.assertFalse(summary_without_root["can_close_device_family_videotoolbox_gate"])

        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_dir = Path(raw_directory)
            write_artifacts(evidence_dir, PASS_ARTIFACTS[:-1])

            missing_artifact = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(missing_artifact["verdict"], "insufficient")
        self.assertFalse(missing_artifact["artifact_checks"][-1]["exists"])
        self.assertFalse(missing_artifact["can_close_device_family_videotoolbox_gate"])

    def test_android_or_simulator_artifact_markers_cannot_pass(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["ios-videotoolbox/android-mediacodec-simulator.log"]
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_dir = Path(raw_directory)
            write_artifacts(evidence_dir, list(record["artifact_paths"]))

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["artifact_checks"][0]["valid_ios_videotoolbox_source"])
        self.assertFalse(summary["can_close_device_family_videotoolbox_gate"])

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

    def test_rejects_absolute_or_local_user_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["/tmp/ios-videotoolbox.log"]

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "relative sanitized paths"):
            summarize(record)

        record["artifact_paths"] = ["Users/example/Library/Logs/device.log"]
        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
            summarize(record)

        record["artifact_paths"] = ["~/Library/Logs/device.log"]
        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
            summarize(record)

    def test_rejects_sensitive_artifact_filenames(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["evidence/private_key_export.bin"]

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
            summarize(record)

    def test_rejects_sensitive_notes(self) -> None:
        examples = (
            "operator token was copied into the log",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "api_key=sk-abc12345",
            "access_token=abcdef12345",
            "session_id=abcdef12345",
            "secret_key=abcdef12345",
        )
        for example in examples:
            with self.subTest(example=example):
                record = self.complete_record()
                record["notes"] = example

                with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
                    summarize(record)

    def test_rejects_sensitive_run_id(self) -> None:
        record = self.complete_record()

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
            summarize(record, run_id="secret-api-key-sk_abc12345")

        record["run_id"] = "Bearer abcdefghijk"
        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
            summarize(record)

    def test_rejects_tcc_database_paths_in_blocking_notes(self) -> None:
        record = self.complete_record()
        record["blocking_notes"] = ["".join(("TCC", ".db", " was inspected"))]

        with self.assertRaisesRegex(IOSVideoToolboxReadinessError, "sanitized public"):
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

    def test_cli_require_pass_rejects_blocked_simulator_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli", "--require-pass"],
            input=json.dumps({"runtime_class": "simulator", "artifacts_retained": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "blocked")

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
