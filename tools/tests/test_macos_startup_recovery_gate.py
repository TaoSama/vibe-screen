import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.macos_startup_recovery_gate import (
    BOOLEAN_FIELDS,
    MacOSStartupRecoveryGateError,
    summarize,
)


MODULE = "vibescreen_evidence.macos_startup_recovery_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "macos-startup-recovery-gate.schema.json"


class MacOSStartupRecoveryGateTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
        record["android_device"] = {
            "serial": "EP0110PZ0B9110300B",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": "36",
            "abi": "arm64-v8a",
        }
        record["artifact_paths"] = ["host.log", "android-logcat.txt"]
        return record

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record(), run_id="run-1")

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_login_item_gate"])
        self.assertTrue(summary["can_close_automatic_startup_gate"])
        self.assertTrue(summary["can_close_headless_startup_gate"])
        self.assertTrue(summary["can_close_unattended_listener_recovery_gate"])
        self.assertTrue(summary["can_close_android_reconnect_gate"])
        self.assertTrue(summary["can_close_phase1_phase2_startup_recovery_gate"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_readiness_record_cannot_close_integration_gates(self) -> None:
        record = {
            "stable_signed_host_identity_recorded": True,
            "screen_recording_permission_recorded": True,
            "accessibility_permission_recorded": True,
            "artifact_paths": ["login-headless-readiness.json"],
            "blocking_notes": ["read-only readiness only"],
        }

        summary = summarize(record, run_id="readiness")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_login_item_gate"])
        self.assertFalse(summary["can_close_headless_startup_gate"])
        self.assertFalse(summary["can_close_unattended_listener_recovery_gate"])
        self.assertTrue(summary["readiness_preflight_is_not_acceptance"])
        self.assertIn(
            "macos_reboot_or_logout_login_performed",
            {item["field"] for item in summary["blocking_reasons"]},
        )

    def test_p0110_scope_is_android_reconnect_only(self) -> None:
        record = self.complete_record()
        for field in (
            "macos_reboot_or_logout_login_performed",
            "login_launch_timestamp_recorded",
            "headless_capture_first_frame_observed",
        ):
            record[field] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertTrue(summary["can_close_android_reconnect_gate"])
        self.assertFalse(summary["can_close_login_item_gate"])
        self.assertFalse(summary["can_close_headless_startup_gate"])
        self.assertIn("P0110/pacific/Android 16/SDK 36", summary["android_device_scope"])
        self.assertIn("does not prove macOS", summary["android_device_scope"])

    def test_android_reconnect_requires_device_identity_metadata(self) -> None:
        record = self.complete_record()
        record["android_device"] = {}

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_android_reconnect_gate"])
        self.assertFalse(summary["can_close_phase1_phase2_startup_recovery_gate"])
        self.assertIn(
            "android_device.serial",
            {item["field"] for item in summary["missing_requirements"]},
        )

    def test_pass_requires_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = []

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_login_item_gate"])
        self.assertFalse(summary["can_close_automatic_startup_gate"])
        self.assertFalse(summary["can_close_headless_startup_gate"])
        self.assertFalse(summary["can_close_unattended_listener_recovery_gate"])
        self.assertFalse(summary["can_close_android_reconnect_gate"])
        self.assertFalse(summary["can_close_phase1_phase2_startup_recovery_gate"])
        self.assertIn(
            "artifact_paths",
            {item["field"] for item in summary["missing_requirements"]},
        )

    def test_insufficient_when_only_non_blocking_artifact_is_missing(self) -> None:
        record = self.complete_record()
        record["raw_artifacts_retained"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_phase1_phase2_startup_recovery_gate"])

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
        record["macos_reboot_or_logout_login_performed"] = "yes"

        with self.assertRaisesRegex(MacOSStartupRecoveryGateError, "must be true or false"):
            summarize(record)

    def test_rejects_empty_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["host.log", ""]

        with self.assertRaisesRegex(MacOSStartupRecoveryGateError, "artifact_paths"):
            summarize(record)


class MacOSStartupRecoveryGateCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"stable_signed_host_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_phase1_phase2_startup_recovery_gate"])

    def test_cli_rejects_empty_run_id(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", ""],
            input=json.dumps({"stable_signed_host_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run_id must be a non-empty string", result.stderr)


if __name__ == "__main__":
    unittest.main()
