import json
import subprocess
import sys
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import (
    GATE_INPUT_P95_SUB50,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)
from tools.vibescreen_evidence.latency_preflight import build_latency_preflight_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_preflight"
FIXTURE_DIR = REPOSITORY_ROOT / "tools" / "fixtures" / "latency"


class LatencyPreflightReportTest(unittest.TestCase):
    def test_default_preflight_blocks_all_profiles(self) -> None:
        report = build_latency_preflight_report(repository_revision="fixture-revision")

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["gate_profiles"]), 3)
        self.assertTrue(
            all(not profile["can_close_performance_gate"] for profile in report["gate_profiles"])
        )
        self.assertTrue(report["gate_profiles"][0]["missing_requirements"])

    def test_formal_manifest_check_requires_manifest_path(self) -> None:
        input_document = {
            "schema_version": "vibescreen.evidence/v1",
            "gate_profiles": [
                {
                    "profile": GATE_USB_GLASS_TO_GLASS_SUB50,
                    "checks": {
                        "device_identity_recorded": True,
                        "host_build_identity_recorded": True,
                        "external_camera_timebase_ready": True,
                        "raw_camera_recording_retained": True,
                        "sample_annotations_retained": True,
                        "minimum_sample_count_ready": True,
                        "formal_manifest_retained": True,
                        "usb_transport_ready": True,
                    },
                }
            ]
        }

        report = build_latency_preflight_report(
            input_document=input_document, repository_revision="fixture-revision"
        )

        profile = report["gate_profiles"][0]
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(profile["can_attempt_formal_gate"])
        self.assertFalse(profile["can_close_performance_gate"])
        self.assertIn(
            {
                "field": "manifest",
                "requirement": (
                    "provide the formal latency manifest path so "
                    "the formal checker can validate retained artifacts"
                ),
            },
            profile["missing_requirements"],
        )

    def test_passing_formal_report_can_close_selected_profile(self) -> None:
        input_document = {
            "schema_version": "vibescreen.evidence/v1",
            "gate_profiles": [
                {
                    "profile": GATE_USB_GLASS_TO_GLASS_SUB50,
                    "manifest": "tools/fixtures/latency/external-camera-valid/manifest.json",
                    "checks": {
                        "device_identity_recorded": True,
                        "host_build_identity_recorded": True,
                        "external_camera_timebase_ready": True,
                        "raw_camera_recording_retained": True,
                        "sample_annotations_retained": True,
                        "minimum_sample_count_ready": True,
                        "formal_manifest_retained": True,
                        "usb_transport_ready": True,
                    },
                }
            ]
        }

        report = build_latency_preflight_report(
            input_document=input_document,
            repository_revision="fixture-revision",
            base_dir=REPOSITORY_ROOT,
        )

        profile = report["gate_profiles"][0]
        self.assertEqual(report["status"], "ready")
        self.assertTrue(profile["can_close_performance_gate"])
        self.assertEqual(profile["formal_report"]["verdict"], "pass")

    def test_invalid_formal_manifest_keeps_profile_blocked(self) -> None:
        input_document = {
            "schema_version": "vibescreen.evidence/v1",
            "gate_profiles": [
                {
                    "profile": GATE_USB_GLASS_TO_GLASS_SUB50,
                    "manifest": "tools/fixtures/latency/lan-glass-to-glass-fail.csv",
                    "checks": {
                        "device_identity_recorded": True,
                        "host_build_identity_recorded": True,
                        "external_camera_timebase_ready": True,
                        "raw_camera_recording_retained": True,
                        "sample_annotations_retained": True,
                        "minimum_sample_count_ready": True,
                        "formal_manifest_retained": True,
                        "usb_transport_ready": True,
                    },
                }
            ]
        }

        report = build_latency_preflight_report(
            input_document=input_document,
            repository_revision="fixture-revision",
            base_dir=REPOSITORY_ROOT,
        )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gate_profiles"][0]["formal_report"]["verdict"], "insufficient")

    def test_unknown_check_name_is_rejected(self) -> None:
        input_document = {
            "schema_version": "vibescreen.evidence/v1",
            "gate_profiles": [
                {
                    "profile": GATE_USB_GLASS_TO_GLASS_SUB50,
                    "checks": {"not_a_real_readiness_check": True},
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "not_a_real_readiness_check"):
            build_latency_preflight_report(
                input_document=input_document,
                repository_revision="fixture-revision",
                base_dir=REPOSITORY_ROOT,
            )


class LatencyPreflightCliTest(unittest.TestCase):
    def test_cli_writes_blocked_report_and_exit_2(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                MODULE,
                "--repository-revision",
                "fixture-revision",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["repository_revision"], "fixture-revision")

    def test_cli_embeds_device_info(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                MODULE,
                "--repository-revision",
                "fixture-revision",
                "--device-info",
                "docs/changes/2026-08-04-phase-0-baseline/evidence/2026-08-21-nubia-p0110-latency-preflight-blocked/device-info.json",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["device"]["manufacturer"], "nubia")
        self.assertEqual(report["device"]["model"], "P0110")
        self.assertEqual(report["device"]["device"], "pacific")


if __name__ == "__main__":
    unittest.main()
