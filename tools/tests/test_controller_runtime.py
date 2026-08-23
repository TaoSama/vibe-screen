import json
import subprocess
import sys
import unittest

from vibescreen_evidence.controller_runtime import (
    BOOLEAN_FIELDS,
    ControllerRuntimeEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.controller_runtime"


class ControllerRuntimeEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, bool]:
        return {field: True for field in BOOLEAN_FIELDS}

    def test_blocks_when_physical_controller_is_missing(self) -> None:
        record = self.complete_record()
        record["physical_controller_attached"] = False

        summary = summarize(record, run_id="run-1")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_runtime_gate"])
        self.assertEqual(
            [item["field"] for item in summary["blocking_reasons"]],
            ["physical_controller_attached"],
        )

    def test_blocks_when_entitled_host_runtime_is_missing(self) -> None:
        record = self.complete_record()
        record["host_identity_signed"] = False
        record["host_virtual_hid_entitlement_present"] = False
        record["host_virtual_gamepad_available"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "host_identity_signed",
                "host_virtual_hid_entitlement_present",
                "host_virtual_gamepad_available",
            },
        )

    def test_insufficient_when_non_blocking_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["mac_side_controller_response_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_runtime_gate"])

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_runtime_gate"])
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["inconsistent_observations"], [])

    def test_insufficient_when_observations_are_inconsistent(self) -> None:
        record = self.complete_record()
        record["controller_connected_state_disconnected_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_runtime_gate"])
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertEqual(
            summary["inconsistent_observations"],
            [
                {
                    "field": "neutral_release_on_disconnect_observed",
                    "requires": ["controller_connected_state_disconnected_observed"],
                    "requirement": (
                        "neutral release evidence requires connected, state, and disconnected "
                        "controller lifecycle samples"
                    ),
                }
            ],
        )

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["physical_controller_attached"] = "yes"

        with self.assertRaisesRegex(ControllerRuntimeEvidenceError, "must be true or false"):
            summarize(record)


class ControllerRuntimeCliTest(unittest.TestCase):
    def complete_record(self) -> dict[str, bool]:
        return {field: True for field in BOOLEAN_FIELDS}

    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"android_production_forwarding_observed": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_runtime_gate"])

    def test_cli_returns_one_for_insufficient_summary(self) -> None:
        record = self.complete_record()
        record["mac_side_controller_response_observed"] = False
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-insufficient"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "insufficient")


if __name__ == "__main__":
    unittest.main()
