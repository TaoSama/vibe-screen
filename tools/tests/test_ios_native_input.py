import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.ios_native_input import (
    BOOLEAN_FIELDS,
    IOSNativeInputEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.ios_native_input"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-native-input.schema.json"


class IOSNativeInputEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        record = {
            field: field
            not in {
                "android_evidence_used_for_ios_input",
                "simulator_evidence_used_for_ios_input",
                "offline_tests_used_as_device_evidence",
            }
            for field in BOOLEAN_FIELDS
        }
        record["artifact_paths"] = [
            "logs/ios-native-input.log",
            "logs/host-native-input.log",
        ]
        return record

    def test_blocks_without_real_ios_device_or_signed_install(self) -> None:
        record = self.complete_record()
        record["device_is_iphone_or_ipad"] = False
        record["signed_app_installed"] = False

        summary = summarize(record, run_id="run-1")

        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_ios_native_input_gate"])
        self.assertEqual(summary["gate_owner"], "phase5-ios-native-input-behavior")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {"device_is_iphone_or_ipad", "signed_app_installed"},
        )

    def test_blocks_without_required_physical_accessories(self) -> None:
        record = self.complete_record()
        record["hardware_keyboard_attached"] = False
        record["hover_pointer_accessory_attached"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {"hardware_keyboard_attached", "hover_pointer_accessory_attached"},
        )

    def test_insufficient_when_non_blocking_behavior_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["keyboard_modifier_release_no_leak_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_ios_native_input_gate"])

    def test_disallowed_android_simulator_or_offline_claim_fails(self) -> None:
        for field in (
            "android_evidence_used_for_ios_input",
            "simulator_evidence_used_for_ios_input",
            "offline_tests_used_as_device_evidence",
        ):
            with self.subTest(field=field):
                record = self.complete_record()
                record[field] = True

                summary = summarize(record)

                self.assertEqual(summary["verdict"], "fail")
                self.assertFalse(summary["can_close_ios_native_input_gate"])
                self.assertEqual(summary["disallowed_evidence"][0]["field"], field)

    def test_pass_requires_all_observations_and_no_disallowed_evidence(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_ios_native_input_gate"])
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["disallowed_evidence"], [])
        self.assertTrue(summary["requires_real_ios_device"])
        self.assertTrue(summary["offline_tests_are_readiness_only"])
        self.assertEqual(
            summary["artifact_paths"],
            ["logs/ios-native-input.log", "logs/host-native-input.log"],
        )

    def test_pass_requires_retained_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = []

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_ios_native_input_gate"])
        self.assertIn(
            "artifact_paths",
            {item["field"] for item in summary["missing_requirements"]},
        )

    def test_run_id_can_come_from_input_record(self) -> None:
        record = self.complete_record()
        record["run_id"] = "ios-input-run"

        summary = summarize(record)

        self.assertEqual(summary["run_id"], "ios-input-run")

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

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["signed_app_installed"] = "yes"

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "must be true or false"):
            summarize(record)

    def test_rejects_empty_artifact_paths_and_notes(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["ios-log.txt", ""]

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "artifact_paths"):
            summarize(record)

        record = self.complete_record()
        record["blocking_notes"] = ["needs keyboard", "   "]

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "blocking_notes"):
            summarize(record)

    def test_rejects_absolute_or_escaping_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["/tmp/ios.log"]

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "repository-relative"):
            summarize(record)

        record = self.complete_record()
        record["artifact_paths"] = ["../outside.log"]

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "evidence bundle"):
            summarize(record)

    def test_rejects_android_or_simulator_artifact_references(self) -> None:
        for artifact in (
            "logs/android-fuxi-adb.txt",
            "logs/nubia-p0110-pacific.txt",
            "logs/iphonesimulator-ui-smoke.log",
            "logs/unsigned-archive.log",
        ):
            with self.subTest(artifact=artifact):
                record = self.complete_record()
                record["artifact_paths"] = [artifact]

                summary = summarize(record)

                self.assertEqual(summary["verdict"], "fail")
                self.assertFalse(summary["can_close_ios_native_input_gate"])
                self.assertIn(
                    "public native-input evidence text must be sanitized and iOS-only",
                    summary["disallowed_evidence"][0]["reason"],
                )
                self.assertEqual(summary["artifact_paths"], [])

    def test_rejects_sensitive_run_id_notes_or_blocking_notes(self) -> None:
        cases = (
            ("run_id", "8a" + "023e3a"),
            (
                "notes",
                "/Users/example/Library/"
                + "Application Support/"
                + "com.apple."
                + "TCC/"
                + "TCC"
                + ".db",
            ),
            ("notes", "access" + "_token=redacted-value"),
            ("blocking_notes", ["private" + "_key=redacted-value"]),
        )
        for field, value in cases:
            with self.subTest(field=field):
                record = self.complete_record()
                record[field] = value

                summary = summarize(record)

                self.assertEqual(summary["verdict"], "fail")
                self.assertFalse(summary["can_close_ios_native_input_gate"])
                self.assertIn(field, {item["field"] for item in summary["disallowed_evidence"]})
                if field == "notes":
                    self.assertEqual(summary["notes"], "")
                if field == "blocking_notes":
                    self.assertEqual(summary["blocking_notes"], [])

    def test_rejects_empty_run_id(self) -> None:
        record = self.complete_record()
        record["run_id"] = ""

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "run_id"):
            summarize(record)

        with self.assertRaisesRegex(IOSNativeInputEvidenceError, "run_id"):
            summarize(self.complete_record(), run_id="")


class IOSNativeInputCliTest(unittest.TestCase):
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
        self.assertFalse(summary["can_close_ios_native_input_gate"])
        self.assertTrue(summary["simulator_is_not_ios_input_evidence"])

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

    def test_cli_file_input_requires_retained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            input_path = root / "ios-native-input-observations.json"
            record = IOSNativeInputEvidenceTest().complete_record()
            record["artifact_paths"] = ["logs/missing.log"]
            input_path.write_text(json.dumps(record), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "-m", MODULE, str(input_path)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist under the evidence bundle", result.stderr)


if __name__ == "__main__":
    unittest.main()
