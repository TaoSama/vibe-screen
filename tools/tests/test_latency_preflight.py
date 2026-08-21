from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import (
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)
from tools.vibescreen_evidence.latency_preflight import evaluate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_preflight"


def p0110_device() -> dict[str, object]:
    return {
        "manufacturer": "nubia",
        "model": "P0110",
        "codename": "pacific",
        "android_release": "16",
        "adb_serial": "EP0110PZ0B9110300B",
    }


def common_ready_checks() -> dict[str, bool]:
    return {
        "external_camera_timebase_ready": True,
        "raw_camera_recording_retained": True,
        "sample_annotations_retained": True,
        "minimum_sample_count_ready": True,
        "formal_manifest_retained": True,
        "device_identity_recorded": True,
        "host_build_identity_recorded": True,
    }


class LatencyPreflightTest(unittest.TestCase):
    def test_empty_input_blocks_all_profiles_with_actionable_requirements(self) -> None:
        result = evaluate({}, device=p0110_device(), run_id="blocked-run")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["run_id"], "blocked-run")
        self.assertEqual(result["device"]["model"], "P0110")
        self.assertEqual(len(result["gate_profiles"]), 3)
        for gate in result["gate_profiles"]:
            self.assertEqual(gate["status"], "blocked")
            self.assertFalse(gate["can_close_performance_gate"])
            self.assertFalse(gate["can_attempt_formal_gate"])
            missing_fields = {item["field"] for item in gate["missing_requirements"]}
            self.assertIn("external_camera_timebase_ready", missing_fields)
            self.assertIn("raw_camera_recording_retained", missing_fields)

    def test_ready_checks_allow_formal_attempt_without_closing_gate(self) -> None:
        checks = common_ready_checks()
        checks["usb_transport_ready"] = True
        result = evaluate(
            {
                "gate_profiles": [
                    {"profile": GATE_USB_GLASS_TO_GLASS_SUB50, "checks": checks}
                ]
            },
            profiles=(GATE_USB_GLASS_TO_GLASS_SUB50,),
            device=p0110_device(),
        )

        gate = result["gate_profiles"][0]
        self.assertEqual(result["status"], "ready")
        self.assertTrue(gate["can_attempt_formal_gate"])
        self.assertFalse(gate["can_close_performance_gate"])

    def test_device_identity_requires_serial(self) -> None:
        checks = common_ready_checks()
        checks["usb_transport_ready"] = True
        device = p0110_device()
        device.pop("adb_serial")

        result = evaluate(
            {
                "gate_profiles": [
                    {"profile": GATE_USB_GLASS_TO_GLASS_SUB50, "checks": checks}
                ]
            },
            profiles=(GATE_USB_GLASS_TO_GLASS_SUB50,),
            device=device,
        )

        gate = result["gate_profiles"][0]
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "device_identity_recorded",
            {item["field"] for item in gate["missing_requirements"]},
        )

    def test_lan_and_input_profile_specific_blockers_are_reported(self) -> None:
        checks = common_ready_checks()
        result = evaluate(
            {
                "gate_profiles": [
                    {"profile": GATE_LAN_GLASS_TO_GLASS_SUB80, "checks": checks},
                    {"profile": GATE_INPUT_P95_SUB50, "checks": checks},
                ]
            },
            profiles=(GATE_LAN_GLASS_TO_GLASS_SUB80, GATE_INPUT_P95_SUB50),
            device=p0110_device(),
        )

        missing_by_profile = {
            gate["profile"]: {item["field"] for item in gate["missing_requirements"]}
            for gate in result["gate_profiles"]
        }
        self.assertEqual(
            missing_by_profile[GATE_LAN_GLASS_TO_GLASS_SUB80],
            {"lan_transport_ready"},
        )
        self.assertEqual(
            missing_by_profile[GATE_INPUT_P95_SUB50],
            {"physical_input_actuation_ready", "visible_mac_input_result_ready"},
        )

    def test_notes_must_be_strings(self) -> None:
        with self.assertRaisesRegex(ValueError, "notes must be a list of strings"):
            evaluate({"notes": ["ok", 3]})


class LatencyPreflightCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_writes_blocked_report_for_missing_materials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "preflight-input.json"
            output_path = root / "preflight-report.json"
            input_path.write_text(
                json.dumps({"run_id": "missing-materials", "device": p0110_device()}),
                encoding="utf-8",
            )

            result = self.run_cli(
                "--input",
                str(input_path),
                "--checked-at",
                "2026-08-21",
                "--output",
                str(output_path),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["checked_at"], "2026-08-21")


if __name__ == "__main__":
    unittest.main()
