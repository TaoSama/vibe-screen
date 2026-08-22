import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.phase2_aggregate_owner import derive_report


MODULE = "vibescreen_evidence.phase2_aggregate_owner"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-aggregate-owner.schema.json"


def tablet_manifest(device_class="physical_8_9_inch_tablet"):
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_sustained_use_manifest",
        "device": {
            "identity": {
                "adb_serial": "EP0110PZ0B9110300B",
                "device_serial": "EP0110PZ0B9110300B",
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": "36",
                "build_fingerprint": "nubia/pacific/test",
                "abi": "arm64-v8a",
            },
            "device_class": device_class,
        },
    }


def close_signal(field):
    return {"schema_version": "vibescreen.evidence/v1", field: True}


class Phase2AggregateOwnerTest(unittest.TestCase):
    def test_missing_child_gates_are_blocked_and_keep_readme_open(self):
        report = derive_report()

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase2_gates"])
        gate_ids = {gate["gate_id"] for gate in report["owner_matrix"]}
        self.assertIn("physical_8_9_inch_tablet", gate_ids)
        self.assertTrue(
            any("no passing package-aware" in reason for reason in report["open_reasons"])
        )

    def test_android_substitute_manifest_cannot_close_tablet_gate(self):
        report = derive_report(
            tablet_manifest=tablet_manifest("android_substitute"),
            tablet_gate={
                "schema_version": "vibescreen.evidence/v1",
                "verdict": "pass",
                "evidence_package": {"passed": True},
            },
        )

        physical_gate = next(
            gate
            for gate in report["owner_matrix"]
            if gate["gate_id"] == "physical_8_9_inch_tablet"
        )
        self.assertEqual(physical_gate["status"], "insufficient")
        self.assertFalse(physical_gate["can_close"])
        self.assertTrue(report["substitute_readiness"]["notes"])
        self.assertFalse(report["can_close_readme_phase2_gates"])

    def test_all_child_signals_and_tablet_package_close_aggregate(self):
        report = derive_report(
            tablet_manifest=tablet_manifest(),
            tablet_gate={
                "schema_version": "vibescreen.evidence/v1",
                "verdict": "pass",
                "evidence_package": {"passed": True},
            },
            hardware_keyboard=close_signal("can_close_hardware_keyboard_gate"),
            device_memory=close_signal("can_close_device_memory_gate"),
            device_environment=close_signal("can_close_device_environment_gate"),
            soak_readiness=close_signal("can_close_eight_hour_soak_gate"),
            stand_charging=close_signal("can_close_stand_charging_gate"),
            tablet_ui=close_signal("can_close_tablet_ui_gate"),
            recovery=close_signal("can_close_recovery_gate"),
            login_headless=close_signal("can_close_login_headless_gate"),
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_readme_phase2_gates"])
        self.assertEqual(report["open_reasons"], [])
        self.assertTrue(all(gate["can_close"] for gate in report["owner_matrix"]))

    def test_merge_plan_has_unique_order_and_known_prs(self):
        report = derive_report()
        orders = [item["merge_order"] for item in report["merge_plan"]]
        pr_numbers = {item["pr_number"] for item in report["merge_plan"]}

        self.assertEqual(orders, sorted(orders))
        self.assertEqual(len(orders), len(set(orders)))
        self.assertTrue({174, 189, 234, 240, 252, 255}.issubset(pr_numbers))
        self.assertNotIn(213, pr_numbers)
        device_memory = next(
            gate for gate in report["owner_matrix"] if gate["gate_id"] == "device_memory"
        )
        self.assertEqual(device_memory["owner"]["pr_number"], 213)
        self.assertEqual(device_memory["owner"]["branch"], "origin/main")
        self.assertIn("#213 is already in current base", report["audit_summary"]["pairwise_overlap"][0])

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
