import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.wake_host_current_base import (
    BOOLEAN_FIELDS,
    WakeHostCurrentBaseEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.wake_host_current_base"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "wake-host-current-base.schema.json"
)
CURRENT_MAIN_SHA = "1abc03b0287feba7b932f175a9e8ff1280495606"


class WakeHostCurrentBaseTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        record = {field: True for field in BOOLEAN_FIELDS}
        record["current_main_sha"] = CURRENT_MAIN_SHA
        return record

    def test_default_record_is_blocked_and_cannot_close_gate(self) -> None:
        summary = summarize({}, run_id="run-1")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_wake_host_current_base_gate"])
        self.assertFalse(summary["can_claim_sleeping_mac_wake"])
        self.assertTrue(summary["offline_baseline_only_is_not_acceptance"])
        self.assertIn(
            "identity_signed_host_tcc_ready",
            {item["field"] for item in summary["blocking_reasons"]},
        )
        self.assertIn(
            "router_broadcast_or_directed_wol_verified",
            {item["field"] for item in summary["blocking_reasons"]},
        )

    def test_offline_baseline_without_sleeping_mac_remains_blocked(self) -> None:
        record = {
            "current_main_verified": True,
            "current_main_sha": CURRENT_MAIN_SHA,
            "magic_packet_path_baseline_merged": True,
            "paired_authorization_offline_passed": True,
            "device_identity_recorded": True,
            "host_logs_retained": True,
            "client_logs_retained": True,
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_wake_host_current_base_gate"])
        self.assertIn(
            "host_sleep_state_recorded",
            {item["field"] for item in summary["blocking_reasons"]},
        )
        self.assertIn(
            "mac_woke_from_sleep_observed",
            {item["field"] for item in summary["blocking_reasons"]},
        )

    def test_insufficient_when_only_non_blocking_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["negative_wrong_key_or_signature_rejected"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_claim_sleeping_mac_wake"])

    def test_insufficient_when_granular_offline_security_contract_is_missing(self) -> None:
        record = self.complete_record()
        record["key_rotation_offline_passed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertIn(
            "key_rotation_offline_passed",
            {item["field"] for item in summary["missing_requirements"]},
        )
        self.assertFalse(summary["can_close_wake_host_current_base_gate"])

    def test_failure_observation_overrides_complete_record(self) -> None:
        record = self.complete_record()
        record["wake_attempt_failed_observed"] = True

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "fail")
        self.assertFalse(summary["can_close_wake_host_current_base_gate"])
        self.assertTrue(summary["failure_reasons"])

    def test_complete_hardware_record_passes(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["host.log", "packet-capture.pcapng"]

        summary = summarize(record, run_id="run-pass")

        self.assertEqual(summary["run_id"], "run-pass")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_wake_host_current_base_gate"])
        self.assertTrue(summary["can_claim_sleeping_mac_wake"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_run_id_can_come_from_input_record(self) -> None:
        record = self.complete_record()
        record["run_id"] = "wake-run"

        summary = summarize(record)

        self.assertEqual(summary["run_id"], "wake-run")
        self.assertEqual(summary["current_main_sha"], CURRENT_MAIN_SHA)

    def test_current_main_sha_required_when_main_is_verified(self) -> None:
        with self.assertRaisesRegex(WakeHostCurrentBaseEvidenceError, "current_main_sha"):
            summarize({"current_main_verified": True})

    def test_rejects_malformed_current_main_sha(self) -> None:
        record = self.complete_record()
        record["current_main_sha"] = "not-a-sha"

        with self.assertRaisesRegex(WakeHostCurrentBaseEvidenceError, "40-character Git SHA"):
            summarize(record)

    def test_summary_matches_schema_contract(self) -> None:
        summary = summarize(self.complete_record(), run_id="schema-run")
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

    def test_rejects_non_boolean_observation(self) -> None:
        record = self.complete_record()
        record["mac_woke_from_sleep_observed"] = "yes"

        with self.assertRaisesRegex(WakeHostCurrentBaseEvidenceError, "must be true or false"):
            summarize(record)

    def test_rejects_empty_artifact_path(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["host.log", ""]

        with self.assertRaisesRegex(WakeHostCurrentBaseEvidenceError, "artifact_paths"):
            summarize(record)

    def test_cli_writes_blocked_summary_and_exits_nonzero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"current_main_verified": False}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_wake_host_current_base_gate"])

    def test_cli_rejects_empty_run_id(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", ""],
            input=json.dumps({}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 3)
        self.assertIn("run_id must be a non-empty string", result.stderr)


if __name__ == "__main__":
    unittest.main()
