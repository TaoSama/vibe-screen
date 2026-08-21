import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.hardware_keyboard import (
    BOOLEAN_FIELDS,
    HardwareKeyboardEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.hardware_keyboard"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "hardware-keyboard.schema.json"


class HardwareKeyboardEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, bool]:
        return {field: True for field in BOOLEAN_FIELDS}

    def test_blocks_when_device_lock_is_missing(self) -> None:
        record = self.complete_record()
        record["android_device_lock_acquired"] = False

        summary = summarize(record, run_id="run-1")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_hardware_keyboard_gate"])
        self.assertEqual(
            [item["field"] for item in summary["blocking_reasons"]],
            ["android_device_lock_acquired"],
        )

    def test_blocks_when_physical_keyboard_or_host_preconditions_are_missing(self) -> None:
        record = self.complete_record()
        record["physical_keyboard_attached"] = False
        record["host_listener_observed"] = False
        record["host_stable_signed_tcc_ready"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "physical_keyboard_attached",
                "host_listener_observed",
                "host_stable_signed_tcc_ready",
            },
        )

    def test_insufficient_when_non_blocking_workflow_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["modifier_release_no_leak_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_hardware_keyboard_gate"])

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_hardware_keyboard_gate"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_run_id_can_come_from_input_record(self) -> None:
        record = self.complete_record()
        record["run_id"] = "fixed-run"

        summary = summarize(record)

        self.assertEqual(summary["run_id"], "fixed-run")

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

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["physical_keyboard_attached"] = "yes"

        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "must be true or false"):
            summarize(record)

    def test_rejects_empty_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["device-lock.txt", ""]

        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "artifact_paths"):
            summarize(record)

    def test_rejects_blank_blocking_notes(self) -> None:
        record = self.complete_record()
        record["blocking_notes"] = ["lock held", "   "]

        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "blocking_notes"):
            summarize(record)

    def test_rejects_empty_input_run_id(self) -> None:
        record = self.complete_record()
        record["run_id"] = ""

        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "run_id"):
            summarize(record)

    def test_rejects_empty_explicit_run_id(self) -> None:
        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "run_id"):
            summarize(self.complete_record(), run_id="")

    def test_rejects_non_string_explicit_run_id(self) -> None:
        with self.assertRaisesRegex(HardwareKeyboardEvidenceError, "run_id"):
            summarize(self.complete_record(), run_id=123)  # type: ignore[arg-type]


class HardwareKeyboardCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"device_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_hardware_keyboard_gate"])
        self.assertTrue(summary["adb_input_is_not_physical_keyboard_evidence"])

    def test_cli_rejects_empty_run_id(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", ""],
            input=json.dumps({"device_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run_id must be a non-empty string", result.stderr)


if __name__ == "__main__":
    unittest.main()
