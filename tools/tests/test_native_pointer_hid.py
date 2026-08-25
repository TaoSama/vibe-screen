import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.native_pointer_hid import (
    BOOLEAN_FIELDS,
    NativePointerHIDEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.native_pointer_hid"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "native-pointer-hid.schema.json"


class NativePointerHIDEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        return {
            "status": "passed",
            "reason": "All required native pointer evidence was observed.",
            "device": {
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": "36",
            },
            "external_mouse_devices": [{"name": "USB Mouse", "sources": "MOUSE", "is_external": "true"}],
            "required_pointer_events": ["move", "press", "release"],
            "observed_android_pointer_events": ["move", "press", "release"],
            "observed_host_pointer_events": ["move", "press", "release"],
            "host_stable_signed_tcc_ready": True,
            "visible_mac_result": "Mac cursor moved and primary click focused TextEdit.",
            "android_logcat_bytes": 200,
            "host_log_appended_bytes": 180,
        }

    def test_pass_requires_every_observation(self) -> None:
        summary = summarize(self.complete_record(), run_id="run-1")

        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_native_pointer_hid_gate"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_blocked_when_physical_mouse_is_absent(self) -> None:
        record = self.complete_record()
        record["status"] = "blocked"
        record["reason"] = "No external Android input device with MOUSE source is currently attached."
        record["external_mouse_devices"] = []
        record["observed_android_pointer_events"] = []
        record["observed_host_pointer_events"] = []
        record["visible_mac_result"] = ""
        record["android_logcat_bytes"] = 0
        record["host_log_appended_bytes"] = 0

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])
        self.assertIn("physical_mouse_attached", [item["field"] for item in summary["blocking_reasons"]])
        self.assertIn(record["reason"], summary["blocking_notes"])

    def test_physical_mouse_requires_external_mouse_like_source(self) -> None:
        record = self.complete_record()
        record["external_mouse_devices"] = [
            {"name": "Built-in keyboard", "sources": "KEYBOARD", "is_external": "true"},
            {"name": "Virtual mouse", "sources": "MOUSE", "is_external": "false"},
        ]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["physical_mouse_attached"])
        self.assertIn("physical_mouse_attached", [item["field"] for item in summary["blocking_reasons"]])

    def test_p0110_identity_cannot_be_relabeled_as_xiaomi(self) -> None:
        record = self.complete_record()
        record["device"] = {
            "manufacturer": "Xiaomi",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
            "sdk": "36",
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["observations"]["device_identity_matches_claim"])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_non_p0110_identity_cannot_close_current_p0110_gate(self) -> None:
        record = self.complete_record()
        record["device"] = {
            "manufacturer": "Google",
            "model": "Pixel 9",
            "device": "tokay",
            "android_release": "16",
            "sdk": "36",
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["observations"]["device_identity_matches_claim"])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_host_signing_tcc_is_a_blocking_prerequisite(self) -> None:
        record = self.complete_record()
        record["host_stable_signed_tcc_ready"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn("host_stable_signed_tcc_ready", [item["field"] for item in summary["blocking_reasons"]])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_blocked_when_device_identity_was_not_collected(self) -> None:
        record = self.complete_record()
        record["status"] = "blocked_device_coordination_lock"
        record["adb_was_run"] = False
        record["device"] = {"manufacturer": "not collected"}
        record["existing_locks"] = [{"path": "/tmp/vibe-screen-device-android.lock", "detail": "present"}]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["adb_was_run"])
        self.assertIn("/tmp/vibe-screen-device-android.lock: present", summary["blocking_notes"])

    def test_insufficient_when_logs_match_but_visible_result_is_missing(self) -> None:
        record = self.complete_record()
        record["status"] = "failed"
        record["visible_mac_result"] = ""

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_default_required_events_cannot_be_relaxed_for_gate_closure(self) -> None:
        record = self.complete_record()
        record["required_pointer_events"] = ["move"]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["observations"]["default_gate_events_required"])

    def test_inconsistent_host_result_without_android_forwarding_is_insufficient(self) -> None:
        record = self.complete_record()
        record["observed_android_pointer_events"] = []

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "host_pointer_changed_injected",
            [item["field"] for item in summary["inconsistent_observations"]],
        )

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = summarize(self.complete_record())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(set(summary["observations"]), set(observation_schema["properties"]))
        for field in observation_schema["required"]:
            self.assertIn(field, summary["observations"])

    def test_rejects_malformed_lists_and_counts(self) -> None:
        record = self.complete_record()
        record["observed_android_pointer_events"] = "move"
        with self.assertRaisesRegex(NativePointerHIDEvidenceError, "observed_android_pointer_events"):
            summarize(record)

        record = self.complete_record()
        record["android_logcat_bytes"] = "200"
        with self.assertRaisesRegex(NativePointerHIDEvidenceError, "android_logcat_bytes"):
            summarize(record)

    def test_rejects_empty_run_id(self) -> None:
        with self.assertRaisesRegex(NativePointerHIDEvidenceError, "run_id"):
            summarize(self.complete_record(), run_id="")


class NativePointerHIDCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"status": "blocked", "reason": "No physical mouse."}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])
        self.assertTrue(summary["synthetic_adb_pointer_is_not_physical_hid_evidence"])

    def test_require_pass_returns_nonzero_for_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--require-pass"],
            input=json.dumps({"status": "blocked", "reason": "No physical mouse."}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])


if __name__ == "__main__":
    unittest.main()
