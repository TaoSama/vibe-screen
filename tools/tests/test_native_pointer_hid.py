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
            "external_mouse_devices": [{"device_id": 11, "name": "USB Mouse", "sources": "MOUSE", "is_external": "true"}],
            "required_pointer_events": ["move", "press", "release"],
            "observed_android_pointer_events": ["move", "press", "release"],
            "observed_android_pointer_device_ids_by_event": {"move": [11], "press": [11], "release": [11]},
            "observed_host_pointer_events": ["move", "press", "release"],
            "host_stable_signed_tcc_ready": True,
            "visible_mac_result": "Mac cursor moved and primary click focused TextEdit.",
            "android_logcat_bytes": 200,
            "host_log_appended_bytes": 180,
            "host_log": "host-log-appended.txt",
            "artifact_paths": [
                "result.json",
                "dumpsys-input.txt",
                "android-logcat-native-pointer.txt",
                "host-log-appended.txt",
                "host-readiness.json",
            ],
            "observation_artifacts": {
                "device_identity_recorded": ["result.json"],
                "device_identity_matches_claim": ["result.json"],
                "physical_mouse_attached": ["dumpsys-input.txt"],
                "android_move_forwarded": ["android-logcat-native-pointer.txt"],
                "android_forwarding_device_ids_match_external_mouse": [
                    "dumpsys-input.txt",
                    "android-logcat-native-pointer.txt",
                ],
                "android_required_events_share_external_mouse_device": [
                    "android-logcat-native-pointer.txt"
                ],
                "android_button_press_forwarded": ["android-logcat-native-pointer.txt"],
                "android_button_release_forwarded": ["android-logcat-native-pointer.txt"],
                "host_pointer_changed_injected": ["host-log-appended.txt"],
                "host_pointer_began_injected": ["host-log-appended.txt"],
                "host_pointer_ended_injected": ["host-log-appended.txt"],
                "host_stable_signed_tcc_ready": ["host-readiness.json"],
                "visible_mac_result_observed": ["result.json"],
                "android_logcat_window_retained": ["android-logcat-native-pointer.txt"],
                "host_log_window_retained": ["host-log-appended.txt"],
            },
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

    def test_zero_length_runtime_logs_are_not_listed_as_retained_artifacts(self) -> None:
        record = self.complete_record()
        record["status"] = "blocked"
        record["reason"] = "No external Android input device with MOUSE source is currently attached."
        record["external_mouse_devices"] = []
        record["observed_android_pointer_events"] = []
        record["observed_host_pointer_events"] = []
        record["visible_mac_result"] = ""
        record["android_logcat_bytes"] = 0
        record["host_log_appended_bytes"] = 0
        record["host_log"] = "host-log-appended.txt"
        record.pop("artifact_paths")
        record.pop("observation_artifacts")

        summary = summarize(record, source_path=Path("result.json"))

        self.assertEqual(summary["artifact_paths"], ["dumpsys-input.txt", "result.json"])

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

    def test_physical_mouse_rejects_devices_with_mixed_non_mouse_sources(self) -> None:
        record = self.complete_record()
        record["external_mouse_devices"] = [
            {"device_id": 11, "name": "USB Combo Receiver", "sources": "MOUSE|KEYBOARD", "is_external": "true"},
            {"device_id": 12, "name": "USB Touch Combo", "sources": "MOUSE+TOUCHSCREEN", "is_external": "true"},
        ]
        record["observed_android_pointer_device_ids_by_event"] = {"move": [11], "press": [11], "release": [11]}

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["physical_mouse_attached"])
        self.assertFalse(summary["observations"]["android_forwarding_device_ids_match_external_mouse"])
        self.assertFalse(summary["observations"]["android_required_events_share_external_mouse_device"])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_android_forwarding_device_ids_must_match_external_mouse(self) -> None:
        record = self.complete_record()
        record["observed_android_pointer_device_ids_by_event"] = {"move": [99], "press": [99], "release": [99]}

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["observations"]["android_forwarding_device_ids_match_external_mouse"])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_android_required_events_must_share_one_external_mouse_device(self) -> None:
        record = self.complete_record()
        record["external_mouse_devices"] = [
            {"device_id": 11, "name": "USB Mouse", "sources": "MOUSE", "is_external": "true"},
            {"device_id": 12, "name": "Bluetooth Trackpad", "sources": "TOUCHPAD", "is_external": "true"},
            {"device_id": 13, "name": "USB Trackball", "sources": "TRACKBALL", "is_external": "true"},
        ]
        record["observed_android_pointer_device_ids_by_event"] = {
            "move": [11],
            "press": [12],
            "release": [13],
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertTrue(summary["observations"]["android_forwarding_device_ids_match_external_mouse"])
        self.assertFalse(summary["observations"]["android_required_events_share_external_mouse_device"])
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])

    def test_synthetic_negative_device_id_cannot_close_gate(self) -> None:
        record = self.complete_record()
        record["external_mouse_devices"] = [{"device_id": -1, "name": "Virtual mouse", "sources": "MOUSE", "is_external": "true"}]
        record["observed_android_pointer_device_ids_by_event"] = {"move": [-1], "press": [-1], "release": [-1]}

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["physical_mouse_attached"])
        self.assertFalse(summary["observations"]["android_forwarding_device_ids_match_external_mouse"])
        self.assertFalse(summary["observations"]["android_required_events_share_external_mouse_device"])

    def test_virtual_named_mouse_cannot_close_gate_even_when_external(self) -> None:
        record = self.complete_record()
        record["external_mouse_devices"] = [
            {"device_id": 11, "name": "uinput synthetic mouse", "sources": "MOUSE", "is_external": "true"},
            {"device_id": 12, "name": "Virtual Bluetooth Trackpad", "sources": "TOUCHPAD", "is_external": "true"},
        ]
        record["observed_android_pointer_device_ids_by_event"] = {"move": [11], "press": [11], "release": [11]}

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["physical_mouse_attached"])
        self.assertFalse(summary["observations"]["android_forwarding_device_ids_match_external_mouse"])

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

    def test_xiaomi_13_identity_can_close_current_gate(self) -> None:
        record = self.complete_record()
        record["device"] = {
            "manufacturer": "Xiaomi",
            "model": "2211133C",
            "device": "fuxi",
            "android_release": "16",
            "sdk": "36",
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["observations"]["device_identity_matches_claim"])
        self.assertTrue(summary["can_close_native_pointer_hid_gate"])

    def test_unknown_identity_cannot_close_current_gate(self) -> None:
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

    def test_insufficient_when_true_observations_lack_artifact_mapping(self) -> None:
        record = self.complete_record()
        record.pop("observation_artifacts")

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_native_pointer_hid_gate"])
        missing_fields = {item["field"] for item in summary["missing_requirements"]}
        self.assertIn("observation_artifacts.android_move_forwarded", missing_fields)
        self.assertIn("observation_artifacts.host_pointer_changed_injected", missing_fields)

    def test_insufficient_when_observation_artifact_is_not_retained(self) -> None:
        record = self.complete_record()
        record["observation_artifacts"]["visible_mac_result_observed"] = ["missing-mac-result.txt"]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            {
                "field": "observation_artifacts.visible_mac_result_observed",
                "requirement": "list only paths also present in artifact_paths",
            },
            summary["missing_requirements"],
        )

    def test_insufficient_when_generic_artifact_is_reused_for_host_injection(self) -> None:
        record = self.complete_record()
        record["observation_artifacts"]["host_pointer_changed_injected"] = ["result.json"]

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            {
                "field": "observation_artifacts.host_pointer_changed_injected",
                "requirement": "retain Host Pointer injected changed logs for the same run",
            },
            summary["missing_requirements"],
        )

    def test_rejects_unknown_observation_artifact_key(self) -> None:
        record = self.complete_record()
        record["observation_artifacts"]["offline_pointer_mapper_passed"] = ["result.json"]

        with self.assertRaisesRegex(NativePointerHIDEvidenceError, "unknown observation_artifacts field"):
            summarize(record)

    def test_rejects_out_of_bundle_artifact_references(self) -> None:
        for artifact in ("", "/tmp/native-pointer.log", "../native-pointer.log", "logs/../native-pointer.log"):
            with self.subTest(artifact=artifact):
                record = self.complete_record()
                record["artifact_paths"] = [artifact]

                with self.assertRaisesRegex(NativePointerHIDEvidenceError, "artifact_paths"):
                    summarize(record)

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

    def test_cli_reuses_existing_output_run_id_when_rerun_without_explicit_id(self) -> None:
        with self.subTest("existing output run_id is stable"):
            import tempfile

            with tempfile.TemporaryDirectory() as temporary_directory:
                input_path = Path(temporary_directory) / "result.json"
                output_path = Path(temporary_directory) / "native-pointer-hid-summary.json"
                input_path.write_text(json.dumps({"status": "blocked", "reason": "No physical mouse."}), encoding="utf-8")
                output_path.write_text(json.dumps({"run_id": "stable-run"}), encoding="utf-8")

                result = subprocess.run(
                    [sys.executable, "-m", MODULE, str(input_path), "--output", str(output_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2, result.stderr)
                summary = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(summary["run_id"], "stable-run")

        with self.subTest("malformed existing run_id is ignored"):
            import tempfile

            with tempfile.TemporaryDirectory() as temporary_directory:
                input_path = Path(temporary_directory) / "result.json"
                output_path = Path(temporary_directory) / "native-pointer-hid-summary.json"
                input_path.write_text(json.dumps({"status": "blocked", "reason": "No physical mouse."}), encoding="utf-8")
                output_path.write_text(json.dumps({"run_id": ""}), encoding="utf-8")

                result = subprocess.run(
                    [sys.executable, "-m", MODULE, str(input_path), "--output", str(output_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2, result.stderr)
                summary = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertRegex(summary["run_id"], r"^[0-9a-f-]{36}$")


if __name__ == "__main__":
    unittest.main()
