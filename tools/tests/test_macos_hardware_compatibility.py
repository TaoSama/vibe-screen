import json
import subprocess
import sys
import tempfile
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


def complete_record() -> dict[str, object]:
    record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
    record.update({field: False for field in INVALID_BOOLEAN_FIELDS})
    record.update({
        "run_id": "compat-apple-silicon-built-in",
        "owner": "Vibe Screen macOS Host compatibility owner",
        "implementation_path": "docs/runbook/macos-host-compatibility.md",
        "repository_commit": "0123456789abcdef0123456789abcdef01234567",
        "repository_dirty_state": "clean",
        "cpu_architecture": "apple_silicon",
        "host_model_identifier": "Mac14,10",
        "host_cpu_name": "Apple M2 Pro",
        "macos_version": "26.4.1",
        "macos_build": "25E253",
        "xcode_version": "Xcode 16.4",
        "swift_version": "Swift 6.1",
        "host_build_identity": "Vibe Screen Dev, sha256 example",
        "host_bundle_id": "dev.telemachus.display",
        "host_signing_identity": "Vibe Screen Dev",
        "screen_recording_tcc": "authorized",
        "accessibility_tcc": "authorized",
        "host_source_commit": "0123456789abcdef0123456789abcdef01234567",
        "host_source_tree": "89abcdef0123456789abcdef0123456789abcdef",
        "host_source_dirty_state": "clean",
        "host_self_test_commit": "0123456789abcdef0123456789abcdef01234567",
        "current_base_commit": "0123456789abcdef0123456789abcdef01234567",
        "display_topology": "built_in",
        "capture_backend": "screencapturekit",
        "screen_capturekit_result": "selected_display_first_frame",
        "cgdisplaystream_result": "not_used",
        "videotoolbox_result": "h264_hevc_available",
        "virtual_display_result": "created_online_captured",
        "mirror_result": "current_main_fallback",
        "stream_transport": "usb",
        "android_counterpart": "nubia P0110 / pacific / Android 16 / SDK 36",
        "compatibility_scope": (
            "Apple silicon Mac14,10 on macOS 26.4.1 built-in display over USB only"
        ),
        "artifact_paths": ["README.md", "host.log"],
        "blocking_notes": [],
        "notes": "one exact matrix row",
    })
    return record


class MacOSHardwareCompatibilityTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        return complete_record()

    def summarize_with_artifacts(self, record: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "host.log").write_text("capture started\n", encoding="utf-8")
            (directory / "README.md").write_text("evidence note\n", encoding="utf-8")
            return summarize(record, evidence_dir=directory)

    def test_pass_requires_every_observation_and_scopes_to_exact_row(self) -> None:
        summary = self.summarize_with_artifacts(self.complete_record())

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(summary["row_scope"]["cpu_architecture"], "apple_silicon")
        self.assertEqual(summary["row_scope"]["display_topology"], "built_in")
        self.assertEqual(summary["row_scope"]["repository_dirty_state"], "clean")
        self.assertEqual(summary["row_scope"]["capture_backend"], "screencapturekit")
        self.assertEqual(summary["row_scope"]["virtual_display_result"], "created_online_captured")
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["invalid_claims"], [])
        self.assertEqual(
            {item["id"]: item["status"] for item in summary["closure_checklist"]},
            {
                "source_and_host_identity": "pass",
                "display_and_encoder_capability": "pass",
                "runtime_acceptance": "pass",
                "scope_and_artifacts": "pass",
                "extrapolation_guard": "pass",
            },
        )
        self.assertTrue(summary["artifact_file_check"]["enabled"])

    def test_blocks_when_intel_or_other_required_row_evidence_is_missing(self) -> None:
        record = self.complete_record()
        record["cpu_architecture_recorded"] = False
        record["host_model_recorded"] = False
        record["packaged_host_launch_observed"] = False

        summary = self.summarize_with_artifacts(record)

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

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        checklist = {item["id"]: item for item in summary["closure_checklist"]}
        self.assertEqual(checklist["display_and_encoder_capability"]["status"], "insufficient")
        self.assertEqual(checklist["runtime_acceptance"]["status"], "insufficient")
        self.assertIn(
            "video_encoder_path_recorded",
            checklist["display_and_encoder_capability"]["missing_fields"],
        )
        self.assertIn(
            "input_smoke_observed",
            checklist["runtime_acceptance"]["missing_fields"],
        )

    def test_required_metadata_must_be_non_empty_even_when_boolean_is_true(self) -> None:
        record = self.complete_record()
        record["macos_build"] = ""
        record["host_model_identifier"] = ""
        record["repository_commit"] = ""

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "macos_version_build_recorded",
                "host_model_recorded",
                "repository_commit_recorded",
            },
        )

    def test_repository_commit_must_be_clean_full_sha(self) -> None:
        record = self.complete_record()
        record["repository_commit"] = "deadbeef"

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            {
                "field": "repository_commit_recorded",
                "requirement": "record repository_commit as a 40-character hexadecimal git commit",
            },
            summary["blocking_reasons"],
        )

    def test_host_source_and_self_test_must_match_current_base_commit(self) -> None:
        record = self.complete_record()
        record["host_source_commit"] = "1" * 40
        record["host_self_test_commit"] = "2" * 40
        record["current_base_commit"] = "3" * 40

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            {
                "field": "source_bound_host_recorded",
                "requirement": "installed Host source commit must match repository_commit for this row",
            },
            summary["blocking_reasons"],
        )
        self.assertIn(
            {
                "field": "host_self_test_provenance_recorded",
                "requirement": "Host self-test commit must match repository_commit for this row",
            },
            summary["blocking_reasons"],
        )
        self.assertIn(
            {
                "field": "host_self_test_provenance_recorded",
                "requirement": "current_base_commit must match repository_commit for this current-base row",
            },
            summary["blocking_reasons"],
        )

    def test_signing_tcc_and_bundle_fields_fail_closed(self) -> None:
        record = self.complete_record()
        record["host_bundle_id"] = "dev.example.other"
        record["host_signing_identity"] = "ad-hoc"
        record["screen_recording_tcc"] = "not_authorized"
        record["accessibility_tcc"] = "unverified"

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            {
                "field": "host_build_identity_recorded",
                "requirement": "Host bundle id must be dev.telemachus.display",
            },
            summary["blocking_reasons"],
        )
        self.assertIn(
            {
                "field": "host_build_identity_recorded",
                "requirement": "Host signing identity must be a stable non-ad-hoc identity",
            },
            summary["blocking_reasons"],
        )
        self.assertIn(
            {
                "field": "signing_and_tcc_state_recorded",
                "requirement": "Screen Recording TCC must be authorized for the packaged Host",
            },
            summary["blocking_reasons"],
        )
        self.assertIn(
            {
                "field": "signing_and_tcc_state_recorded",
                "requirement": "Accessibility TCC must be authorized for the packaged Host",
            },
            summary["blocking_reasons"],
        )

        record = self.complete_record()
        record["repository_dirty_state"] = "dirty"

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            {
                "field": "repository_commit_recorded",
                "requirement": "rerun the compatibility row from a clean repository state before closing it",
            },
            summary["blocking_reasons"],
        )

    def test_artifact_paths_are_required_to_close_row(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = []

        summary = summarize(record, evidence_dir=Path("."))

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
        record["claims_virtual_display_from_symbol_probe"] = True

        summary = self.summarize_with_artifacts(record)

        self.assertEqual(summary["verdict"], "failed")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])
        checklist = {item["id"]: item for item in summary["closure_checklist"]}
        self.assertEqual(checklist["extrapolation_guard"]["status"], "failed")
        self.assertIn("ci_runner_only", checklist["extrapolation_guard"]["missing_fields"])
        self.assertEqual(
            {item["field"] for item in summary["invalid_claims"]},
            {
                "ci_runner_only",
                "claims_intel_from_apple_silicon",
                "claims_os_range_from_single_build",
                "claims_virtual_display_from_symbol_probe",
            },
        )

    def test_fails_inconsistent_capture_backend_results(self) -> None:
        record = self.complete_record()
        record["capture_backend"] = "screencapturekit"
        record["screen_capturekit_result"] = "unavailable_terminal"

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "failed")
        self.assertIn(
            {
                "field": "capture_backend_consistency",
                "reason": "ScreenCaptureKit backend requires selected-display first-frame evidence",
            },
            summary["invalid_claims"],
        )

        record = self.complete_record()
        record["capture_backend"] = "cgdisplaystream_fallback"
        record["screen_capturekit_result"] = "selected_display_first_frame"

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "failed")
        self.assertIn(
            {
                "field": "capture_backend_consistency",
                "reason": "CGDisplayStream fallback requires ScreenCaptureKit fallback evidence",
            },
            summary["invalid_claims"],
        )

        record = self.complete_record()
        record["capture_backend"] = "unavailable"
        record["screen_capturekit_result"] = "selected_display_first_frame"

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "failed")
        self.assertIn(
            {
                "field": "capture_backend_consistency",
                "reason": "unavailable capture backend cannot report a ScreenCaptureKit first frame",
            },
            summary["invalid_claims"],
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

        record = self.complete_record()
        record["capture_backend"] = "manual-screen-photo"

        with self.assertRaisesRegex(MacOSHardwareCompatibilityError, "capture_backend"):
            summarize(record)

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = self.summarize_with_artifacts(self.complete_record())
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

    def test_check_artifacts_requires_relative_existing_non_empty_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = [
            "host.log",
            "empty.txt",
            "missing.txt",
            "../escape.txt",
        ]
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "host.log").write_text("capture started\n", encoding="utf-8")
            (directory / "empty.txt").write_text("", encoding="utf-8")
            summary = summarize(record, evidence_dir=directory)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertEqual(summary["artifact_file_check"]["missing_paths"], ["missing.txt"])
        self.assertEqual(summary["artifact_file_check"]["invalid_paths"], ["../escape.txt"])
        self.assertEqual(summary["artifact_file_check"]["empty_paths"], ["empty.txt"])

    def test_artifact_report_preserves_relative_evidence_dir(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["README.md"]
        with tempfile.TemporaryDirectory() as directory_name:
            base = Path(directory_name)
            evidence_dir = base / "relative-evidence"
            evidence_dir.mkdir()
            (evidence_dir / "README.md").write_text("evidence note\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(base)
                summary = summarize(record, evidence_dir=Path("relative-evidence"))
            finally:
                os.chdir(old_cwd)

        self.assertEqual(summary["verdict"], "pass")
        self.assertEqual(summary["artifact_file_check"]["evidence_dir"], "relative-evidence")


class MacOSHardwareCompatibilityCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"owner_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_macos_host_compatibility_row"])

    def test_cli_stdin_without_evidence_dir_cannot_pass_with_artifacts(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-"],
            input=json.dumps(complete_record()),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn(
            {
                "field": "artifacts_retained",
                "requirement": "provide --evidence-dir or a file input so retained artifacts can be verified",
            },
            summary["blocking_reasons"],
        )

    def test_cli_pass_exits_zero_and_checks_input_relative_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "host.log").write_text("capture started\n", encoding="utf-8")
            (directory / "README.md").write_text("evidence note\n", encoding="utf-8")
            evidence = directory / "macos-hardware-compatibility.json"
            evidence.write_text(json.dumps(complete_record()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", MODULE, str(evidence)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["artifact_file_check"]["enabled"])
        self.assertEqual(summary["artifact_file_check"]["missing_paths"], [])

    def test_cli_failed_invalid_claim_exits_two(self) -> None:
        record = complete_record()
        record["claims_dummy_headless_from_attached_monitor"] = True
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-"],
            input=json.dumps(record),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["verdict"], "failed")

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
