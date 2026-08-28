import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibescreen_evidence.phase2_aggregate_owner import CURRENT_BASE
from vibescreen_evidence.phase2_aggregate_owner import current_base_label
from vibescreen_evidence.phase2_aggregate_owner import derive_report


MODULE = "vibescreen_evidence.phase2_aggregate_owner"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-aggregate-owner.schema.json"


def tablet_manifest(device_class="physical_8_9_inch_tablet"):
    identity = {
        "adb_serial": "TABLET123",
        "device_serial": "TABLET123",
        "manufacturer": "test-vendor",
        "model": "Tablet 8",
        "codename": "tablet8",
        "android_release": "16",
        "sdk": "36",
        "build_fingerprint": "test/tablet8/release",
        "abi": "arm64-v8a",
    }
    if device_class == "android_substitute":
        identity = {
            "adb_serial": "EP0110PZ0B9110300B",
            "device_serial": "EP0110PZ0B9110300B",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": "36",
            "build_fingerprint": "nubia/pacific/test",
            "abi": "arm64-v8a",
        }
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_sustained_use_manifest",
        "device": {
            "identity": identity,
            "device_class": device_class,
        },
    }


def close_signal(field):
    return {"schema_version": "vibescreen.evidence/v1", field: True}


class Phase2AggregateOwnerTest(unittest.TestCase):
    def test_source_baseline_reads_current_origin_main(self):
        with mock.patch(
            "vibescreen_evidence.phase2_aggregate_owner.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["git", "rev-parse", "origin/main"],
                0,
                stdout="f" * 40 + "\n",
                stderr="",
            ),
        ):
            report = derive_report()

        self.assertEqual(
            report["source_baseline"],
            "origin/main ffffffffffffffffffffffffffffffffffffffff",
        )

    def test_source_baseline_falls_back_when_git_is_unavailable(self):
        with mock.patch(
            "vibescreen_evidence.phase2_aggregate_owner.subprocess.run",
            side_effect=FileNotFoundError("git"),
        ):
            self.assertEqual(current_base_label(), CURRENT_BASE)

    def test_missing_child_gates_are_blocked_and_keep_readme_open(self):
        report = derive_report()

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase2_gates"])
        self.assertTrue(
            any(
                reason.startswith("physical_8_9_inch_tablet: missing gate output")
                for reason in report["open_reasons"]
            )
        )

    def test_p0110_substitute_cannot_close_physical_tablet_gate(self):
        report = derive_report(
            tablet_manifest=tablet_manifest("android_substitute"),
            tablet_gate={"schema_version": "vibescreen.evidence/v1", "verdict": "pass", "evidence_package": {"passed": True}},
        )

        physical = next(
            gate for gate in report["owner_matrix"] if gate["gate_id"] == "physical_8_9_inch_tablet"
        )
        self.assertFalse(physical["can_close"])
        self.assertIn(
            "known phone substitute cannot close the physical 8-9 inch tablet gate",
            physical["reasons"],
        )
        self.assertIn("android_substitute", report["substitute_readiness"]["notes"][0])

    def test_device_environment_owner_is_current_branch_and_stale_prs_are_classified(self):
        report = derive_report()
        environment = next(
            gate for gate in report["owner_matrix"] if gate["gate_id"] == "thermal_power_sampling"
        )
        stale_prs = {entry["pr_number"]: entry for entry in report["stale_prs"]}

        self.assertEqual(environment["owner"]["pr_number"], 338)
        self.assertEqual(environment["owner"]["state"], "merged_baseline")
        self.assertEqual(stale_prs[240]["status"], "closed_superseded")
        self.assertEqual(stale_prs[285]["replacement"], "#338")
        self.assertEqual(stale_prs[252]["replacement"], "#338")
        self.assertIn("#338", stale_prs[255]["replacement"])
        self.assertEqual(stale_prs[274]["status"], "stale_source_superseded")
        self.assertIn("#274", report["audit_summary"]["single_prs_against_origin_main"])

    def test_hardware_keyboard_owner_is_this_current_base_branch(self):
        report = derive_report()
        keyboard = next(
            gate for gate in report["owner_matrix"] if gate["gate_id"] == "hardware_keyboard"
        )

        self.assertIsNone(keyboard["owner"]["pr_number"])
        self.assertEqual(
            keyboard["owner"]["branch"],
            "codex/phase2-hardware-keyboard-current-base-owner",
        )
        self.assertEqual(keyboard["owner"]["state"], "this_current_base_pr")

    def test_all_child_pass_signals_close_aggregate(self):
        report = derive_report(
            tablet_manifest=tablet_manifest(),
            tablet_gate={"schema_version": "vibescreen.evidence/v1", "verdict": "pass", "evidence_package": {"passed": True}},
            hardware_keyboard=close_signal("can_close_hardware_keyboard_gate"),
            device_memory=close_signal("can_close_device_memory_gate"),
            device_environment={
                "schema_version": "vibescreen.evidence/v1",
                "can_close_device_environment_gate": True,
                "can_close_stand_charging_gate": True,
            },
            soak_readiness=close_signal("can_close_eight_hour_soak_gate"),
            tablet_ui=close_signal("can_close_tablet_ui_gate"),
            recovery=close_signal("can_close_recovery_gate"),
            login_headless=close_signal("can_close_login_headless_gate"),
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_readme_phase2_gates"])
        self.assertEqual(report["open_reasons"], [])
        self.assertTrue(all(gate["can_close"] for gate in report["owner_matrix"]))

    def test_blocked_login_headless_input_keeps_phase2_open(self):
        report = derive_report(login_headless={"schema_version": "vibescreen.evidence/v1", "verdict": "blocked", "can_close_login_headless_gate": False})

        login_headless = next(
            gate for gate in report["owner_matrix"] if gate["gate_id"] == "login_startup_headless"
        )

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase2_gates"])
        self.assertFalse(login_headless["can_close"])
        self.assertEqual(login_headless["status"], "blocked")
        self.assertIn(
            "login_startup_headless: can_close_login_headless_gate is false",
            report["open_reasons"],
        )

    def test_merge_plan_has_unique_order_and_current_child_owners(self):
        report = derive_report()
        orders = [item["merge_order"] for item in report["merge_plan"]]
        pr_numbers = {item["pr_number"] for item in report["merge_plan"]}

        self.assertEqual(orders, sorted(orders))
        self.assertEqual(len(orders), len(set(orders)))
        self.assertTrue({174, 234, 338}.issubset(pr_numbers))
        self.assertIn(None, pr_numbers)
        self.assertNotIn(240, pr_numbers)
        self.assertNotIn(285, pr_numbers)
        self.assertNotIn(252, pr_numbers)
        self.assertNotIn(255, pr_numbers)
        self.assertTrue(any(item["state"] == "this_current_base_pr" for item in report["merge_plan"]))

    def test_summary_matches_schema_required_fields(self):
        report = derive_report()
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_cli_writes_blocked_report_from_substitute_inputs(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest = directory / "manifest.json"
            output = directory / "aggregate.json"
            manifest.write_text(json.dumps(tablet_manifest("android_substitute")), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--tablet-manifest",
                    str(manifest),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase2_gates"])
        self.assertEqual(report["substitute_readiness"]["device_class"], "android_substitute")


if __name__ == "__main__":
    unittest.main()
