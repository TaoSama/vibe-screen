import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.macos_hardware_compatibility import (
    BOOLEAN_FIELDS,
    INVALID_BOOLEAN_FIELDS,
    MacOSHardwareCompatibilityError,
    summarize,
)


MODULE = "vibescreen_evidence.macos_hardware_compatibility"
SCHEMA_PATH = (
    Path(__file__).parents[1]
    / "schemas"
    / "macos-hardware-compatibility.schema.json"
)


class MacOSHardwareCompatibilityTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
        record.update({field: False for field in INVALID_BOOLEAN_FIELDS})
        record.update({
            "run_id": "compat-apple-silicon-built-in",
            "owner": "Vibe Screen macOS Host compatibility owner",
            "implementation_path": "docs/runbook/macos-host-compatibility.md",
            "cpu_architecture": "apple_silicon",
            "host_model_identifier": "Mac14,10",
            "host_cpu_name": "Apple M2 Pro",
            "macos_version": "26.4.1",
            "macos_build": "25E253",
            "xcode_version": "Xcode 16.4",
            "swift_version": "Swift 6.1",
            "host_build_identity": "Vibe Screen Dev, sha256 example",
            "display_topology": "built_in",
            "capture_backend": "ScreenCaptureKit",
            "stream_transport": "usb",
            "android_counterpart": "Xiaomi 13 / fuxi / Android 16",
            "compatibility_scope": "Apple silicon Mac14,10 on macOS 26.4.1 built-in display over USB only",
            "artifact_paths": ["README.md", "host.log"],
            "blocking_notes": [],
            "notes": "one exact matrix row",
        })
        return record

    def test_pass_requires_every_observation_and_scopes_to_exact_row(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(summary["row_scope"]["cpu_architecture"], "apple_silicon")
        self.assertEqual(summary["row_scope"]["display_topology"], "built_in")
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["invalid_claims"], [])

    def test_blocks_when_intel_or_other_required_row_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["cpu_architecture_recorded"] = False
        record["host_model_recorded"] = False
        record["packaged_host_launch_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "cpu_architecture_recorded",
                "host_model_recorded",
                "packaged_host_launch_observed",
            },
        )

    def test_insufficient_when_non_blocking_runtime_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["video_encoder_path_recorded"] = False
        record["input_smoke_observed"] = False

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])

    def test_required_metadata_must_be_non_empty_even_when_boolean_is_true(self) -> None:
        record = self.complete_record()
        record["macos_build"] = ""
        record["host_model_identifier"] = ""

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {"macos_version_build_recorded", "host_model_recorded"},
        )

    def test_artifact_paths_are_required_to_close_row(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = []

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(summary["artifact_paths"], [])
        self.assertIn(
            {
                "field": "artifacts_retained",
                "requirement": "record at least one retained artifact path for this compatibility row",
            },
            summary["blocking_reasons"],
        )

    def test_fails_invalid_claims_from_ci_or_other_rows(self) -> None:
        record = self.complete_record()
        record["ci_runner_only"] = True
        record["claims_intel_from_apple_silicon"] = True
        record["claims_os_range_from_single_build"] = True

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "failed")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(
            {item["field"] for item in summary["invalid_claims"]},
            {
                "ci_runner_only",
                "claims_intel_from_apple_silicon",
                "claims_os_range_from_single_build",
            },
        )

    def test_rejects_unknown_cpu_architecture_or_display_topology(self) -> None:
        record = self.complete_record()
        record["cpu_architecture"] = "powerpc"

        with self.assertRaisesRegex(MacOSHardwareCompatibilityError, "cpu_architecture"):
            summarize(record)

        record = self.complete_record()
        record["display_topology"] = "projector"

        with self.assertRaisesRegex(MacOSHardwareCompatibilityError, "display_topology"):
            summarize(record)

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = summarize(self.complete_record())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(
            set(summary["observations"]),
            set(schema["properties"]["observations"]["properties"]),
        )
        self.assertEqual(
            set(summary["invalid_claim_observations"]),
            set(schema["properties"]["invalid_claim_observations"]["properties"]),
        )

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["owner_recorded"] = "yes"

        with self.assertRaisesRegex(MacOSHardwareCompatibilityError, "must be true or false"):
            summarize(record)


class MacOSHardwareCompatibilityCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"owner_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])

    def test_cli_rejects_empty_run_id(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", ""],
            input=json.dumps({"owner_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run_id must be a non-empty string", result.stderr)


if __name__ == "__main__":
    unittest.main()
