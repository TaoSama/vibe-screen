import json
import subprocess
import sys
import unittest
from pathlib import Path

from vibescreen_evidence.phase2_device_environment import (
    BOOLEAN_FIELDS,
    DeviceEnvironmentEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.phase2_device_environment"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-device-environment.schema.json"


def complete_record() -> dict[str, object]:
    return {
        **{field: True for field in BOOLEAN_FIELDS},
        "thresholds": {
            "maximum_thermal_status": 2,
            "maximum_battery_temperature_celsius": 45.0,
            "maximum_net_battery_drain_percent": 5,
            "maximum_sample_gap_seconds": 90,
        },
        "measurements": {
            "environment_duration_seconds": 28800,
            "maximum_sample_gap_seconds": 30,
            "unplugged_sample_count": 0,
            "non_charging_sample_count": 0,
            "power_source_change_count": 0,
            "maximum_thermal_status": 1,
            "maximum_battery_temperature_celsius": 38.5,
            "net_battery_drain_percent": 0,
        },
        "artifact_paths": [
            "phase2-device-environment-observations.json",
            "adb-battery-before.txt",
            "adb-power-before.txt",
            "thermal-before.txt",
        ],
        "blocking_notes": [],
        "notes": "target tablet stand-mounted environment pass",
    }


class Phase2DeviceEnvironmentTests(unittest.TestCase):
    def test_blocks_when_target_tablet_or_stand_environment_is_missing(self) -> None:
        record = complete_record()
        record["physical_8_9_inch_tablet_observed"] = False
        record["controlled_thermal_load_observed"] = False
        record["blocking_notes"] = ["Nubia P0110 phone substitute only"]

        summary = summarize(record, run_id="environment-blocked")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_environment_gates"])
        self.assertTrue(summary["does_not_close_eight_hour_stream_gate"])
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {"physical_8_9_inch_tablet_observed", "controlled_thermal_load_observed"},
        )

    def test_insufficient_when_required_measurement_is_missing(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements.pop("maximum_battery_temperature_celsius")
        record["measurements"] = measurements

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("maximum_battery_temperature_celsius", summary["missing_criteria"])

    def test_fail_when_stand_power_or_thermal_thresholds_regress(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements.update(
            {
                "unplugged_sample_count": 1,
                "maximum_thermal_status": 3,
                "net_battery_drain_percent": 7,
            }
        )
        record["measurements"] = measurements

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "fail")
        self.assertEqual(
            set(summary["failed_criteria"]),
            {
                "unplugged_sample_count",
                "maximum_thermal_status",
                "net_battery_drain_percent",
            },
        )

    def test_pass_requires_all_observations_and_measurements(self) -> None:
        summary = summarize(complete_record(), run_id="environment-pass")

        self.assertEqual(summary["run_id"], "environment-pass")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_device_environment_gates"])
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["missing_criteria"], [])
        self.assertEqual(summary["failed_criteria"], [])

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = summarize(complete_record())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(
            set(summary["observations"]),
            set(observation_schema["properties"]),
        )
        for field in observation_schema["required"]:
            self.assertIn(field, summary["observations"])

    def test_rejects_non_boolean_observations(self) -> None:
        record = complete_record()
        record["stand_mounted_setup_observed"] = "yes"

        with self.assertRaisesRegex(DeviceEnvironmentEvidenceError, "must be true or false"):
            summarize(record)

    def test_rejects_non_numeric_measurement(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements["maximum_thermal_status"] = "cool"
        record["measurements"] = measurements

        with self.assertRaisesRegex(DeviceEnvironmentEvidenceError, "measurements.maximum_thermal_status"):
            summarize(record)

    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "environment-cli"],
            input=json.dumps(
                {
                    "device_identity_recorded": True,
                    "device_identity_matches_claim": True,
                    "artifact_paths": ["device-info.json"],
                    "blocking_notes": ["target tablet unavailable"],
                }
            ),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "environment-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_environment_gates"])

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


if __name__ == "__main__":
    unittest.main()
