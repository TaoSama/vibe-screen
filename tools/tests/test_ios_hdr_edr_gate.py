from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.ios_hdr_edr_gate import REQUIRED_CHECKS, evaluate


MODULE = "vibescreen_evidence.ios_hdr_edr_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-hdr-edr-gate.schema.json"
CURRENT_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def complete_observations() -> dict[str, object]:
    evidence = {name: True for name, _ in REQUIRED_CHECKS}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "ios_hdr_edr_readiness_observations",
        "repository": {"commit": CURRENT_COMMIT, "dirty": False},
        "runtime": {
            "runtime_class": "physical_iphone",
            "device_role": "iphone",
            "product_name": "iPhone 15 Pro",
            "hardware_model": "iPhone16,1",
            "os_version": "iOS 18.5",
            "build_number": "22F76",
        },
        "evidence": evidence,
        "evidence_refs": {
            name: [f"artifacts/{name}.log"] for name, _ in REQUIRED_CHECKS
        },
        "invalid_evidence": {
            "simulator_evidence_used": False,
            "unsigned_archive_evidence_used": False,
            "android_evidence_used": False,
            "sdr_fallback_claimed_as_hdr": False,
            "protocol_fields_only_claimed": False,
            "macos_fallback_claimed_as_ios_hdr": False,
        },
        "artifact_paths": [
            "artifacts/ios-device.log",
            "artifacts/edr-diagnostics.json",
            "artifacts/visible-output.mov",
        ],
    }


def write_artifacts(root: Path, observations: dict[str, object]) -> None:
    for item in observations["artifact_paths"]:
        path = root / str(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact {item}\n", encoding="utf-8")


class IOSHDREDRGateTests(unittest.TestCase):
    def test_complete_synthetic_observations_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            write_artifacts(root, observations)

            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                result = evaluate(observations, evidence_root=root, repo=root)

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["can_close_ios_hdr_output_gate"])
        self.assertEqual(result["missing_requirements"], [])
        self.assertEqual(result["invalid_claims"], [])

    def test_missing_hdr_edr_observations_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            observations["evidence"]["client_advertised_hdr_video"] = False
            observations["evidence"]["edr_rendering_enabled"] = False
            write_artifacts(root, observations)

            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                result = evaluate(observations, evidence_root=root, repo=root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_close_ios_hdr_output_gate"])
        self.assertIn("blocked: client_advertised_hdr_video", result["reasons"])
        self.assertIn("blocked: edr_rendering_enabled", result["reasons"])

    def test_simulator_android_or_sdr_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            observations["runtime"]["runtime_class"] = "simulator"
            observations["runtime"]["product_name"] = "iPhone 17 Pro Simulator"
            observations["invalid_evidence"]["android_evidence_used"] = True
            observations["invalid_evidence"]["sdr_fallback_claimed_as_hdr"] = True
            observations["artifact_paths"] = ["artifacts/nubia-p0110-sdr-fallback.log"]
            write_artifacts(root, observations)

            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                result = evaluate(observations, evidence_root=root, repo=root)

        self.assertEqual(result["verdict"], "fail")
        self.assertFalse(result["can_close_ios_hdr_output_gate"])
        self.assertIn("fail: runtime.runtime_class", result["reasons"])
        self.assertIn("fail: android_evidence_used", result["reasons"])
        self.assertIn("fail: sdr_fallback_claimed_as_hdr", result["reasons"])
        self.assertIn("fail: artifact_paths", result["reasons"])

    def test_short_android_markers_require_token_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            observations["artifact_paths"] = ["artifacts/ipadbuild-hdr.log"]
            write_artifacts(root, observations)

            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                valid_result = evaluate(observations, evidence_root=root, repo=root)

            observations["artifact_paths"] = ["artifacts/adb-hdr-log.txt"]
            write_artifacts(root, observations)
            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                invalid_result = evaluate(observations, evidence_root=root, repo=root)

        self.assertEqual(valid_result["verdict"], "pass")
        self.assertEqual(invalid_result["verdict"], "fail")
        self.assertIn("fail: artifact_paths", invalid_result["reasons"])

    def test_repository_commit_must_match_clean_current_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            observations["repository"]["dirty"] = True
            write_artifacts(root, observations)

            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                dirty_result = evaluate(observations, evidence_root=root, repo=root)

            observations["repository"] = {
                "commit": "abcdefabcdefabcdefabcdefabcdefabcdefabcd",
                "dirty": False,
            }
            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                mismatch_result = evaluate(observations, evidence_root=root, repo=root)

        self.assertEqual(dirty_result["verdict"], "blocked")
        self.assertEqual(mismatch_result["verdict"], "blocked")
        self.assertIn("blocked: repository_current_base_recorded", dirty_result["reasons"])
        self.assertIn("blocked: repository_current_base_recorded", mismatch_result["reasons"])

    def test_report_shape_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            observations = complete_observations()
            write_artifacts(root, observations)
            with patch(
                "vibescreen_evidence.ios_hdr_edr_gate.repository_state",
                return_value={"commit": CURRENT_COMMIT, "dirty": False},
            ):
                result = evaluate(observations, evidence_root=root, repo=root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(result), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, result)

    def test_cli_writes_blocked_report_when_observations_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            output = root / "ios-hdr-edr-gate.json"
            missing = root / "ios-hdr-edr-observations.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--observations",
                    str(missing),
                    "--output",
                    str(output),
                    "--evidence-root",
                    str(root),
                    "--repo",
                    str(root),
                ],
                capture_output=True,
                text=True,
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_ios_hdr_output_gate"])
        self.assertIn("blocked: observations", report["reasons"])


if __name__ == "__main__":
    unittest.main()
