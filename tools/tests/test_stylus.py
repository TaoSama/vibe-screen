import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.stylus import StylusEvidenceError, summarize


MODULE = "vibescreen_evidence.stylus"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "stylus.schema.json"


class StylusEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        return {
            "status": "pass",
            "device_identity": {
                "serialno": "redacted-pacific-serial",
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "os_release": "16",
                "api_level": "36",
            },
            "pass_eligible_stylus_candidates": [
                {
                    "name": "goodix_stylus_input",
                    "sources": ["STYLUS", "TOUCHSCREEN"],
                    "axes": ["PRESSURE", "TILT"],
                }
            ],
            "diag_log_read_error": None,
            "host_log_appended_bytes": 256,
            "host_stable_signed_tcc_ready": True,
            "observed_physical_drawing": True,
            "drawing_observation": "physical stylus produced visible pressure-aware ink",
        }

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record(), run_id="run-1")

        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_physical_stylus_gate"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_capability_only_record_stays_blocked(self) -> None:
        record = self.complete_record()
        record["status"] = "blocked_physical_stylus_not_observed"
        record["host_log_appended_bytes"] = 0
        record["observed_physical_drawing"] = False
        record["drawing_observation"] = ""

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_physical_stylus_gate"])
        self.assertIn("physical_drawing_observed", [item["field"] for item in summary["blocking_reasons"]])
        self.assertTrue(summary["synthetic_adb_stylus_is_not_physical_stylus_evidence"])

    def test_xiaomi_claim_in_p0110_gate_is_blocked(self) -> None:
        record = self.complete_record()
        record["device_identity"] = {
            "serialno": "redacted-pacific-serial",
            "manufacturer": "Xiaomi",
            "model": "2211133C",
            "device": "fuxi",
            "os_release": "16",
            "api_level": "36",
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["observations"]["device_identity_matches_claim"])
        self.assertFalse(summary["can_close_physical_stylus_gate"])

    def test_host_signing_tcc_is_a_blocking_prerequisite(self) -> None:
        record = self.complete_record()
        record["host_stable_signed_tcc_ready"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn("host_stable_signed_tcc_ready", [item["field"] for item in summary["blocking_reasons"]])
        self.assertFalse(summary["can_close_physical_stylus_gate"])

    def test_inconsistent_visible_result_without_host_log_is_insufficient(self) -> None:
        record = self.complete_record()
        record["host_log_appended_bytes"] = 0

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "visible_drawing_result_observed",
            [item["field"] for item in summary["inconsistent_observations"]],
        )

    def test_lock_blocked_record_does_not_run_gate_closed(self) -> None:
        summary = summarize(
            {
                "status": "blocked_device_coordination_lock",
                "existing_locks": [
                    {"path": "/tmp/vibe-screen-device-android.lock", "detail": "present"}
                ],
            }
        )

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["adb_was_run"])
        self.assertIn("/tmp/vibe-screen-device-android.lock: present", summary["blocking_notes"])
        self.assertNotIn("dumpsys-input.txt", summary["artifact_paths"])

    def test_schema_required_fields_match_summary(self) -> None:
        summary = summarize(self.complete_record())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(set(summary["observations"]), set(observation_schema["properties"]))
        for field in observation_schema["required"]:
            self.assertIn(field, summary["observations"])

    def test_rejects_malformed_fields(self) -> None:
        record = self.complete_record()
        record["host_log_appended_bytes"] = "256"

        with self.assertRaisesRegex(StylusEvidenceError, "host_log_appended_bytes"):
            summarize(record)

    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"status": "blocked_physical_stylus_not_observed"}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_physical_stylus_gate"])

    def test_require_pass_returns_nonzero_for_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--require-pass"],
            input=json.dumps({"status": "blocked_physical_stylus_not_observed"}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["can_close_physical_stylus_gate"])


if __name__ == "__main__":
    unittest.main()
