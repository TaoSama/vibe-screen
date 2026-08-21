from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.phase2_device_memory_gate import derive_gate, main


def write_manifest(
    directory: Path,
    *,
    device_class: str = "physical_8_9_inch_tablet",
    manufacturer: str = "huawei",
    model: str = "MatePad Mini",
    codename: str = "matepad-mini",
    tablet_size_inches: str | None = "8.8",
    duration_seconds: int = 28800,
    sample_interval_seconds: int = 30,
) -> Path:
    manifest = {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_sustained_use_manifest",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "created_at": "2026-08-21T00:00:00Z",
        "command": ["make", "soak-8h"],
        "repository": {"revision": "abc", "dirty": False, "status_porcelain": []},
        "device": {
            "identity": {
                "adb_serial": "tablet-serial",
                "device_serial": "tablet-serial",
                "manufacturer": manufacturer,
                "model": model,
                "codename": codename,
                "android_release": "16",
                "sdk": "36",
                "build_fingerprint": "vendor/device/build",
                "abi": "arm64-v8a",
            },
            "device_class": device_class,
            "tablet_size_inches": tablet_size_inches,
        },
        "physical_setup": {
            "stand_setup": "desktop stand",
            "charger": "vendor charger",
            "cable_or_dock": "USB-C cable",
            "ambient_temperature_celsius": 24.0,
        },
        "host": {"identity": "Mac mini", "build": "release build"},
        "android_artifact": {"apk_sha256": "abc123"},
        "session": {
            "transport": "usb",
            "video_preferences": "Balanced 60 FPS",
            "duration_seconds": duration_seconds,
            "sample_interval_seconds": sample_interval_seconds,
        },
        "memory_sampling": {
            "android_pss_source": "ADB dumpsys meminfo app TOTAL PSS",
            "host_pid": 4242,
            "host_rss_source": "soak --host-pid sampling via ps -o rss=",
            "require_host_pid": True,
            "sample_interval_seconds": sample_interval_seconds,
            "minimum_duration_seconds": 28800,
            "required_fields": [
                "device.memory.app_total_pss_kb",
                "host.rss_kb",
                "device.battery.level",
                "device.battery.status",
                "device.thermal.status",
            ],
        },
        "thresholds": {
            "thermal_limit_status": 2,
            "battery_temperature_limit_celsius": 45.0,
            "maximum_net_battery_drain_percent": 5,
        },
        "recovery_scenarios": ["background_foreground"],
        "required_gates": ["device_memory_sampling", "eight_hour_sustained_stream"],
        "required_artifacts": [
            "phase2-tablet-manifest.json",
            "samples.jsonl",
            "summary.json",
            "exact-window-report.json",
            "phase2-device-memory-gate.json",
        ],
        "limitations": [],
        "notes": None,
    }
    path = directory / "phase2-tablet-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def write_report(
    directory: Path,
    *,
    duration_seconds: float = 28800.0,
    sample_count: int = 960,
    include_host_rss: bool = True,
    include_charging: bool = True,
    include_thermal: bool = True,
    android_slope: float = 0.0,
    android_final: float = 210_000.0,
    host_slope: float = 0.0,
    host_final: float = 400_000.0,
) -> Path:
    memory = {
        "client_total_pss": {
            "count": sample_count,
            "first": 210_000.0,
            "final": android_final,
            "min": 209_000.0,
            "mean": 210_000.0,
            "max": max(210_000.0, android_final),
            "slope_kib_per_minute": {
                "full_window": android_slope,
                "second_half": android_slope,
                "second_half_sample_count": sample_count // 2,
            },
        },
    }
    if include_host_rss:
        memory["host_rss"] = {
            "count": sample_count,
            "first": 400_000.0,
            "final": host_final,
            "min": 399_000.0,
            "mean": 400_000.0,
            "max": max(400_000.0, host_final),
            "slope_kib_per_minute": {
                "full_window": host_slope,
                "second_half": host_slope,
                "second_half_sample_count": sample_count // 2,
            },
        }
    battery = {
        "level_percent": {
            "count": sample_count,
            "first": 100.0,
            "final": 100.0,
            "min": 100.0,
            "mean": 100.0,
            "max": 100.0,
        },
        "temperature_celsius": {
            "count": sample_count,
            "first": 34.0,
            "final": 36.0,
            "min": 34.0,
            "mean": 35.0,
            "max": 36.0,
        },
    }
    if include_charging:
        battery["charging_or_full"] = {
            "count": sample_count,
            "first": 1.0,
            "final": 1.0,
            "min": 1.0,
            "mean": 1.0,
            "max": 1.0,
        }
    metrics = {
        "memory_kib": memory,
        "battery": battery,
        "samples": {
            "gaps": {
                "count": sample_count,
                "maximum_interval_seconds": 30.0,
                "maximum_window_gap_seconds": 30.0,
            }
        },
    }
    if include_thermal:
        metrics["thermal"] = {
            "status": {
                "count": sample_count,
                "first": 0.0,
                "final": 1.0,
                "min": 0.0,
                "mean": 0.5,
                "max": 1.0,
            }
        }
    report = {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "soak_exact_window_report",
        "run_id": "phase2-run",
        "derivation_status": "complete",
        "window": {
            "started_at": "2026-08-21T00:00:00Z",
            "finished_at": "2026-08-21T08:00:00Z",
            "duration_seconds": duration_seconds,
            "sample_records_in_window": sample_count,
            "telemetry_records_in_window": sample_count,
        },
        "source_summary": {"status": "complete", "errors": []},
        "metrics": metrics,
        "errors": [],
    }
    path = directory / "exact-window-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class Phase2DeviceMemoryGateTest(unittest.TestCase):
    def test_complete_physical_tablet_memory_report_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            gate = derive_gate(write_manifest(directory), write_report(directory))

        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["reasons"], [])
        self.assertTrue(all(item["passed"] for item in gate["sufficiency"].values()))
        self.assertTrue(all(item["passed"] for item in gate["criteria"].values()))

    def test_nubia_p0110_is_insufficient_even_if_manifest_claims_tablet(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            gate = derive_gate(
                write_manifest(
                    directory,
                    manufacturer="nubia",
                    model="P0110",
                    codename="pacific",
                ),
                write_report(directory),
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["known_phone_substitute_rejected"]["passed"])

    def test_android_substitute_class_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            gate = derive_gate(
                write_manifest(
                    directory,
                    device_class="android_substitute",
                    tablet_size_inches=None,
                    manufacturer="nubia",
                    model="P0110",
                    codename="pacific",
                ),
                write_report(directory),
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["manifest_device_class"]["passed"])

    def test_short_run_or_missing_samples_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            gate = derive_gate(
                write_manifest(directory),
                write_report(directory, duration_seconds=7200.0, sample_count=241),
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["report_duration"]["passed"])

    def test_missing_host_rss_charging_or_thermal_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            gate = derive_gate(
                write_manifest(directory),
                write_report(
                    directory,
                    include_host_rss=False,
                    include_charging=False,
                    include_thermal=False,
                ),
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertIn("insufficient evidence: host_rss_samples", gate["reasons"])
        self.assertIn("insufficient evidence: charging_state_samples", gate["reasons"])
        self.assertIn("insufficient evidence: thermal_status_samples", gate["reasons"])

    def test_memory_growth_or_unplugged_state_fails_complete_evidence(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(
                directory,
                android_slope=60.0,
                android_final=230_000.0,
                host_slope=60.0,
                host_final=420_000.0,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["metrics"]["battery"]["charging_or_full"]["min"] = 0.0
            report_path.write_text(json.dumps(report), encoding="utf-8")

            gate = derive_gate(write_manifest(directory), report_path)

        self.assertEqual(gate["verdict"], "fail")
        self.assertFalse(
            gate["criteria"]["android_pss_second_half_slope_kib_per_minute"]["passed"]
        )
        self.assertFalse(gate["criteria"]["charging_or_full_min"]["passed"])

    def test_cli_fails_closed_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--manifest",
                        str(directory / "missing-manifest.json"),
                        "--report",
                        str(directory / "missing-report.json"),
                        "--output",
                        str(output),
                    ]
                )
            gate = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(gate["derivation_status"], "failed")
        self.assertEqual(gate["verdict"], "insufficient")


if __name__ == "__main__":
    unittest.main()
