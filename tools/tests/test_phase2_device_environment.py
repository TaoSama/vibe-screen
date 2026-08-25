import json
import subprocess
import sys
import tempfile
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
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_device_environment_observations",
        "run_id": "phase2-environment-run",
        "device": {
            "identity": {
                "adb_serial": "TABLET123",
                "device_serial": "TABLET123",
                "manufacturer": "huawei",
                "model": "MatePad Mini",
                "codename": "matepad-mini",
                "android_release": "16",
                "sdk": "36",
                "build_fingerprint": "vendor/tablet/release",
                "abi": "arm64-v8a",
            },
            "device_class": "physical_8_9_inch_tablet",
            "tablet_size_inches": 8.8,
        },
        **{field: True for field in BOOLEAN_FIELDS},
        "thresholds": {
            "maximum_thermal_status": 2,
            "maximum_battery_temperature_celsius": 45.0,
            "maximum_net_battery_drain_percent": 5,
            "maximum_sample_gap_seconds": 90,
            "minimum_power_voltage_uv": 3_500_000,
        },
        "measurements": {
            "environment_duration_seconds": 28800,
            "maximum_sample_gap_seconds": 30,
            "unplugged_sample_count": 0,
            "non_charging_sample_count": 0,
            "power_source_change_count": 0,
            "maximum_thermal_status": 1,
            "thermal_recovery_status_max": 1,
            "maximum_battery_temperature_celsius": 38.5,
            "net_battery_drain_percent": 0,
            "power_voltage_now_uv_min": 3_900_000,
            "charge_counter_uah_negative_drift": 0,
        },
        "artifact_paths": [
            "README.md",
            "device-info.json",
            "adb-battery-before.txt",
            "adb-battery-after.txt",
            "adb-power-before.txt",
            "adb-power-after.txt",
            "thermal-before.txt",
            "thermal-before.err",
            "thermal-after.txt",
            "thermal-after.err",
            "soak-8h/samples.jsonl",
            "soak-8h/summary.json",
            "soak-8h/exact-window-report.json",
            "screenshots/sustained-use-portrait.png",
            "screenshots/sustained-use-landscape.png",
        ],
        "blocking_notes": [],
        "notes": "target tablet stand-mounted environment pass",
    }


def write_artifacts(directory: Path) -> None:
    record = complete_record()
    for relative_path in record["artifact_paths"]:
        path = directory / str(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "" if path.name.endswith(".err") else f"{relative_path}\n"
        path.write_text(content, encoding="utf-8")


class Phase2DeviceEnvironmentTests(unittest.TestCase):
    def test_pass_requires_all_observations_measurements_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            write_artifacts(directory)
            summary = summarize(complete_record(), run_id="environment-pass", evidence_dir=directory)

        self.assertEqual(summary["run_id"], "environment-pass")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_device_environment_gate"])
        self.assertTrue(summary["can_close_device_environment_gates"])
        self.assertTrue(summary["can_close_stand_charging_gate"])
        self.assertEqual(summary["missing_requirements"], [])
        self.assertEqual(summary["missing_criteria"], [])
        self.assertEqual(summary["failed_criteria"], [])

    def test_complete_record_without_evidence_dir_cannot_pass(self) -> None:
        summary = summarize(complete_record(), run_id="environment-no-evidence-dir")

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_device_environment_gate"])
        self.assertFalse(summary["can_close_device_environment_gates"])
        self.assertFalse(summary["can_close_stand_charging_gate"])
        self.assertIn("README.md", summary["missing_artifacts"])
        self.assertEqual(
            summary["artifact_checks"]["README.md"]["expected"],
            "file exists; rerun with --evidence-dir for filesystem verification",
        )

    def test_blocks_phone_substitute_even_if_other_observations_exist(self) -> None:
        record = complete_record()
        record["device"] = {
            "identity": {
                "adb_serial": "<redacted-adb-serial>",
                "device_serial": "<redacted-adb-serial>",
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": "36",
                "build_fingerprint": "nubia/pacific/test",
                "abi": "arm64-v8a",
            },
            "device_class": "android_substitute",
            "tablet_size_inches": None,
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_environment_gate"])
        self.assertFalse(summary["can_close_stand_charging_gate"])
        self.assertFalse(summary["device_checks"]["known_phone_substitute_rejected"]["passed"])

    def test_blocks_when_device_identity_required_fields_are_missing(self) -> None:
        record = complete_record()
        record["device"] = {
            "identity": {},
            "device_class": "physical_8_9_inch_tablet",
            "tablet_size_inches": 8.8,
        }

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_environment_gate"])
        self.assertFalse(summary["can_close_stand_charging_gate"])
        self.assertFalse(summary["device_checks"]["identity_required_fields"]["passed"])
        self.assertIn(
            {
                "field": "device.identity",
                "requirement": "device identity must include non-empty adb_serial, manufacturer, model, codename, Android release, SDK, build fingerprint, and ABI fields",
            },
            summary["blocking_reasons"],
        )

    def test_insufficient_when_required_measurement_or_artifact_is_missing(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements.pop("thermal_recovery_status_max")
        record["measurements"] = measurements
        artifact_paths = list(record["artifact_paths"])
        artifact_paths.remove("adb-power-after.txt")
        record["artifact_paths"] = artifact_paths

        summary = summarize(record)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("thermal_recovery_status_max", summary["missing_criteria"])
        self.assertIn("adb-power-after.txt", summary["missing_artifacts"])

    def test_fails_when_stand_power_or_thermal_thresholds_regress(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            write_artifacts(directory)
            record = complete_record()
            measurements = dict(record["measurements"])
            measurements.update(
                {
                    "unplugged_sample_count": 1,
                    "non_charging_sample_count": 1,
                    "power_source_change_count": 1,
                    "maximum_thermal_status": 3,
                    "thermal_recovery_status_max": 3,
                    "net_battery_drain_percent": 7,
                    "power_voltage_now_uv_min": 3_400_000,
                    "charge_counter_uah_negative_drift": 1,
                }
            )
            record["measurements"] = measurements

            summary = summarize(record, evidence_dir=directory)

        self.assertEqual(summary["verdict"], "fail")
        self.assertIn("unplugged_sample_count", summary["failed_criteria"])
        self.assertIn("maximum_thermal_status", summary["failed_criteria"])
        self.assertIn("power_voltage_now_uv_min", summary["failed_criteria"])
        self.assertFalse(summary["can_close_device_environment_gate"])
        self.assertFalse(summary["can_close_stand_charging_gate"])

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = summarize(complete_record(), run_id="environment-schema")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(set(summary["observations"]), set(observation_schema["properties"]))
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

    def test_rejects_non_string_device_identity_values(self) -> None:
        record = complete_record()
        device = dict(record["device"])
        identity = dict(device["identity"])
        identity["sdk"] = 36
        device["identity"] = identity
        record["device"] = device

        with self.assertRaisesRegex(DeviceEnvironmentEvidenceError, "device.identity.sdk"):
            summarize(record)

    def test_rejects_negative_sample_counts(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements["unplugged_sample_count"] = -1
        record["measurements"] = measurements

        with self.assertRaisesRegex(
            DeviceEnvironmentEvidenceError,
            "measurements.unplugged_sample_count",
        ):
            summarize(record)

    def test_rejects_fractional_sample_counts(self) -> None:
        record = complete_record()
        measurements = dict(record["measurements"])
        measurements["power_source_change_count"] = 0.5
        record["measurements"] = measurements

        with self.assertRaisesRegex(
            DeviceEnvironmentEvidenceError,
            "measurements.power_source_change_count",
        ):
            summarize(record)

    def test_cli_outputs_blocked_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            output = directory / "environment.json"
            result = subprocess.run(
                [sys.executable, "-m", MODULE, "-", "--run-id", "environment-cli", "--output", str(output)],
                input=json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "android_device_lock_checked": True,
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
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(summary["run_id"], "environment-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_device_environment_gate"])

    def test_cli_complete_record_without_evidence_dir_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            observations = directory / "observations.json"
            output = directory / "environment.json"
            observations.write_text(json.dumps(complete_record()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    str(observations),
                    "--run-id",
                    "environment-cli-no-evidence-dir",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(summary["run_id"], "environment-cli-no-evidence-dir")
        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("README.md", summary["missing_artifacts"])
        self.assertFalse(summary["can_close_device_environment_gate"])

    def test_cli_rejects_empty_run_id_but_writes_fail_closed_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            output = Path(raw_directory) / "environment.json"
            result = subprocess.run(
                [sys.executable, "-m", MODULE, "-", "--run-id", "", "--output", str(output)],
                input=json.dumps({"device_identity_recorded": True}),
                capture_output=True,
                text=True,
                check=False,
            )
            output_exists = output.is_file()

        self.assertEqual(result.returncode, 1)
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
