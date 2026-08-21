from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.phase2_tablet_gate import derive_gate, main


def write_report(
    directory: Path,
    *,
    duration_seconds: float = 8 * 60 * 60,
    sample_count: int = 961,
    telemetry_count: int = 961,
    sample_gap_seconds: float = 30.0,
    source_status: str = "complete",
    source_errors: list[str] | None = None,
    derivation_errors: list[str] | None = None,
    session_disconnects: int = 0,
    include_session_disconnect_count: bool = True,
    accepted_heartbeat_count: int | None = None,
    frame_queue_drops: float = 0.0,
    dropped_frames: float = 0.0,
    thermal_status_max: float = 1.0,
    battery_temperature_max: float = 38.0,
    include_battery_temperature: bool = True,
    battery_level_first: float = 100.0,
    battery_level_final: float = 100.0,
    battery_status_counts: dict[str, int] | None = None,
    plugged_counts: dict[str, int] | None = None,
    include_battery_status: bool = True,
    include_battery_plugged: bool = True,
    client_slope: float = 0.0,
    client_final: float = 210_000.0,
    host_slope: float = 0.0,
    host_final: float = 400_000.0,
    include_host_rss: bool = True,
) -> Path:
    event_counts = {
        "session_admission_failed": 0,
        "session_admitted": 1,
        "heartbeat_received": telemetry_count,
        "frame_queue_drop": 0,
        "stream_stats": telemetry_count,
    }
    if include_session_disconnect_count:
        event_counts["session_disconnected"] = session_disconnects

    battery_metrics = {
        "level_percent": {
            "count": sample_count,
            "first": battery_level_first,
            "final": battery_level_final,
            "min": min(99.0, battery_level_first, battery_level_final),
            "mean": 99.5,
            "max": max(100.0, battery_level_first, battery_level_final),
        },
        "voltage_mv": {
            "count": sample_count,
            "first": 4200.0,
            "final": 4200.0,
            "min": 4180.0,
            "mean": 4190.0,
            "max": 4210.0,
        },
        "charge_counter": {
            "count": sample_count,
            "first": 4_000_000.0,
            "final": 4_000_000.0,
            "min": 3_990_000.0,
            "mean": 3_995_000.0,
            "max": 4_000_000.0,
        },
    }
    if include_battery_temperature:
        battery_metrics["temperature_celsius"] = {
            "count": sample_count,
            "first": 34.0,
            "final": battery_temperature_max,
            "min": 34.0,
            "mean": 36.0,
            "max": battery_temperature_max,
        }
    if include_battery_status:
        battery_metrics["status"] = {
            "count": sample_count,
            "first": 2.0,
            "final": 5.0,
            "min": 2.0,
            "mean": 2.5,
            "max": 5.0,
        }
        battery_metrics["status_counts"] = battery_status_counts or {
            "2": sample_count // 2,
            "5": sample_count - (sample_count // 2),
        }
    if include_battery_plugged:
        battery_metrics["plugged"] = {
            "count": sample_count,
            "first": 1.0,
            "final": 1.0,
            "min": 1.0,
            "mean": 1.0,
            "max": 1.0,
        }
        battery_metrics["plugged_counts"] = plugged_counts or {"1": sample_count}

    memory_metrics = {
        "client_total_pss": {
            "count": sample_count,
            "first": 210_000.0,
            "final": client_final,
            "min": 209_000.0,
            "mean": 210_000.0,
            "max": max(210_000.0, client_final),
            "slope_kib_per_minute": {
                "full_window": client_slope,
                "second_half": client_slope,
                "second_half_sample_count": sample_count // 2,
            },
        },
    }
    if include_host_rss:
        memory_metrics["host_rss"] = {
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

    report = {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "soak_exact_window_report",
        "run_id": "phase2-run",
        "derivation_status": "complete",
        "window": {
            "started_at": "2026-08-14T00:00:00Z",
            "finished_at": "2026-08-14T08:00:00Z",
            "duration_seconds": duration_seconds,
            "sample_records_in_window": sample_count,
            "telemetry_records_in_window": telemetry_count,
            "telemetry_records_excluded": 0,
        },
        "source_summary": {
            "status": source_status,
            "errors": source_errors or [],
        },
        "metrics": {
            "samples": {
                "gaps": {
                    "count": sample_count,
                    "maximum_interval_seconds": sample_gap_seconds,
                    "maximum_window_gap_seconds": sample_gap_seconds,
                }
            },
            "stream": {
                "fps": {
                    "count": telemetry_count,
                    "first": 60.0,
                    "final": 60.0,
                    "min": 59.0,
                    "mean": 60.0,
                    "max": 61.0,
                },
                "average_frame_age_ms": {
                    "count": telemetry_count,
                    "first": 6.0,
                    "final": 6.0,
                    "min": 5.0,
                    "mean": 6.0,
                    "max": 7.0,
                },
                "reported_dropped_frames": {
                    "statistics": {
                        "count": telemetry_count,
                        "first": 0.0,
                        "final": dropped_frames,
                        "min": 0.0,
                        "mean": dropped_frames / max(1, telemetry_count),
                        "max": dropped_frames,
                    },
                    "sum": dropped_frames,
                },
                "frame_queue_drop_total": frame_queue_drops,
            },
            "telemetry": {
                "event_counts": event_counts,
                "stream_stats_gaps": {
                    "count": telemetry_count,
                    "maximum_interval_seconds": 30.0,
                    "maximum_window_gap_seconds": 30.0,
                },
                "heartbeat_gaps": {
                    "count": telemetry_count,
                    "maximum_interval_seconds": 30.0,
                    "maximum_window_gap_seconds": 30.0,
                },
                "accepted_heartbeat_count": telemetry_count
                if accepted_heartbeat_count is None
                else accepted_heartbeat_count,
            },
            "memory_kib": memory_metrics,
            "thermal": {
                "status": {
                    "count": sample_count,
                    "first": 0.0,
                    "final": thermal_status_max,
                    "min": 0.0,
                    "mean": 1.0,
                    "max": thermal_status_max,
                },
                "sensors_celsius": {
                    "battery": {
                        "count": sample_count,
                        "first": 34.0,
                        "final": battery_temperature_max,
                        "min": 34.0,
                        "mean": 36.0,
                        "max": battery_temperature_max,
                    }
                },
            },
            "battery": battery_metrics,
        },
        "errors": derivation_errors or [],
        "interpretation": "Trend metrics are descriptive evidence, not a no-leak determination.",
    }
    path = directory / "exact-window-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def write_manifest(
    directory: Path,
    *,
    device_class: str = "physical_8_9_inch_tablet",
    thermal_limit_status: int = 2,
    battery_temperature_limit_celsius: float = 45.0,
    maximum_net_battery_drain_percent: int = 5,
) -> Path:
    manifest = {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_sustained_use_manifest",
        "run_id": "phase2-run",
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
            "tablet_size_inches": "8.8" if device_class == "physical_8_9_inch_tablet" else None,
        },
        "physical_setup": {
            "stand_setup": "desktop stand, portrait",
            "charger": "vendor USB-C charger",
            "cable_or_dock": "USB-C data cable",
            "ambient_temperature_celsius": 24.0,
        },
        "session": {
            "duration_seconds": 28800,
            "sample_interval_seconds": 30,
        },
        "thresholds": {
            "thermal_limit_status": thermal_limit_status,
            "battery_temperature_limit_celsius": battery_temperature_limit_celsius,
            "maximum_net_battery_drain_percent": maximum_net_battery_drain_percent,
        },
    }
    path = directory / "phase2-tablet-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def write_evidence_artifacts(directory: Path) -> None:
    for relative_path in (
        "README.md",
        "device-info.json",
        "device.txt",
        "host.txt",
        "build.txt",
        "apk-sha256.txt",
        "samples.jsonl",
        "summary.json",
        "adb-battery-before.txt",
        "adb-battery-after.txt",
        "adb-power-before.txt",
        "adb-power-after.txt",
        "thermal-before.txt",
        "thermal-after.txt",
        "raw-logcat.txt",
        "host.log",
        "reconnects.log",
        "frame-drops.log",
        "decoder-telemetry.jsonl",
    ):
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative_path}\n", encoding="utf-8")
    for relative_path in ("thermal-before.err", "thermal-after.err"):
        path = directory / relative_path
        path.write_text("", encoding="utf-8")
    (directory / "screenshots").mkdir()


class Phase2TabletGateTest(unittest.TestCase):
    def test_complete_eight_hour_stable_report_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(Path(raw_directory))
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["reasons"], [])
        self.assertTrue(all(item["passed"] for item in gate["sufficiency"].values()))
        self.assertTrue(all(item["passed"] for item in gate["criteria"].values()))

    def test_complete_report_with_full_evidence_package_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(directory)
            write_manifest(directory)
            write_evidence_artifacts(directory)
            gate = derive_gate(
                report_path,
                manifest_path=directory / "phase2-tablet-manifest.json",
                evidence_dir=directory,
            )

        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["reasons"], [])
        self.assertTrue(gate["evidence_package"]["passed"])

    def test_android_substitute_package_stays_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(directory)
            write_manifest(directory, device_class="android_substitute")
            write_evidence_artifacts(directory)
            gate = derive_gate(
                report_path,
                manifest_path=directory / "phase2-tablet-manifest.json",
                evidence_dir=directory,
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertIn(
            "insufficient evidence package: manifest.physical_8_9_inch_tablet",
            gate["reasons"],
        )

    def test_missing_raw_evidence_package_artifact_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(directory)
            write_manifest(directory)
            write_evidence_artifacts(directory)
            (directory / "adb-power-after.txt").unlink()
            gate = derive_gate(
                report_path,
                manifest_path=directory / "phase2-tablet-manifest.json",
                evidence_dir=directory,
            )

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertIn(
            "insufficient evidence package: artifact.adb_power_after",
            gate["reasons"],
        )

    def test_short_or_sparse_report_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory), duration_seconds=900, sample_count=31, telemetry_count=31
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["duration"]["passed"])
        self.assertTrue(
            any("duration" in reason for reason in gate["reasons"]), gate["reasons"]
        )

    def test_large_sample_gap_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(Path(raw_directory), sample_gap_seconds=120.0)
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["sample_gap"]["passed"])

    def test_missing_criterion_measurement_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory),
                include_battery_temperature=False,
                include_host_rss=False,
                include_battery_status=False,
                include_battery_plugged=False,
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["criteria"]["battery_temperature_celsius_max"]["passed"])
        self.assertIsNone(gate["criteria"]["battery_temperature_celsius_max"]["measured"])
        self.assertIn(
            "insufficient evidence: battery_temperature_celsius_max",
            gate["reasons"],
        )
        self.assertIn(
            "insufficient evidence: host_rss_second_half_slope_kib_per_minute",
            gate["reasons"],
        )
        self.assertIn("insufficient evidence: battery_status_samples", gate["reasons"])
        self.assertIn("insufficient evidence: battery_plugged_samples", gate["reasons"])

    def test_manifest_thresholds_drive_thermal_temperature_and_drain_criteria(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(
                directory,
                thermal_status_max=2.0,
                battery_temperature_max=42.0,
                battery_level_first=90.0,
                battery_level_final=84.0,
            )
            write_manifest(
                directory,
                thermal_limit_status=1,
                battery_temperature_limit_celsius=40.0,
                maximum_net_battery_drain_percent=5,
            )
            write_evidence_artifacts(directory)
            gate = derive_gate(
                report_path,
                manifest_path=directory / "phase2-tablet-manifest.json",
                evidence_dir=directory,
            )

        self.assertEqual(gate["verdict"], "fail")
        self.assertEqual(gate["thresholds"]["maximum_thermal_status"], 1.0)
        self.assertEqual(gate["thresholds"]["maximum_battery_temperature_celsius"], 40.0)
        self.assertFalse(gate["criteria"]["thermal_status_max"]["passed"])
        self.assertFalse(gate["criteria"]["battery_temperature_celsius_max"]["passed"])
        self.assertFalse(gate["criteria"]["net_battery_drain_percent"]["passed"])

    def test_unplugged_or_discharging_samples_fail_stand_charging_criteria(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(
                directory,
                battery_status_counts={"2": 960, "3": 1},
                plugged_counts={"0": 1, "1": 960},
            )
            write_manifest(directory)
            write_evidence_artifacts(directory)
            gate = derive_gate(
                report_path,
                manifest_path=directory / "phase2-tablet-manifest.json",
                evidence_dir=directory,
            )

        self.assertEqual(gate["verdict"], "fail")
        self.assertFalse(
            gate["criteria"]["stand_charging_non_charging_status_samples"]["passed"]
        )
        self.assertFalse(
            gate["criteria"]["stand_charging_unplugged_samples"]["passed"]
        )

    def test_rejected_heartbeats_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(Path(raw_directory), accepted_heartbeat_count=0)
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertFalse(gate["sufficiency"]["accepted_heartbeat_count"]["passed"])
        self.assertIn("insufficient evidence: accepted_heartbeat_count", gate["reasons"])

    def test_source_or_derivation_errors_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory),
                source_status="partial",
                source_errors=["device offline"],
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "insufficient")
        self.assertIn("source soak summary is not complete", gate["reasons"])

    def test_missing_session_disconnect_counter_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory), include_session_disconnect_count=False
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["criteria"]["session_disconnect_count"]["measured"], 0.0)

    def test_stream_reconnect_or_temperature_regression_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory),
                session_disconnects=1,
                frame_queue_drops=1,
                dropped_frames=2,
                thermal_status_max=3,
                battery_temperature_max=48.0,
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "fail")
        self.assertFalse(gate["criteria"]["session_disconnect_count"]["passed"])
        self.assertFalse(gate["criteria"]["thermal_status_max"]["passed"])
        self.assertFalse(gate["criteria"]["battery_temperature_celsius_max"]["passed"])

    def test_memory_growth_regression_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(
                Path(raw_directory),
                client_slope=60.0,
                client_final=230_000.0,
                host_slope=60.0,
                host_final=420_000.0,
            )
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "fail")
        self.assertFalse(
            gate["criteria"]["client_total_pss_second_half_slope_kib_per_minute"]["passed"]
        )
        self.assertFalse(
            gate["criteria"]["host_rss_full_window_endpoint_drift_kib"]["passed"]
        )

    def test_cli_fails_closed_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            output = directory / "gate.json"
            invalid = directory / "missing.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--report", str(invalid), "--output", str(output)])
            gate = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(gate["derivation_status"], "failed")
        self.assertEqual(gate["verdict"], "insufficient")

    def test_cli_with_manifest_and_evidence_dir_writes_package_result(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(directory)
            manifest_path = write_manifest(directory)
            write_evidence_artifacts(directory)
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--report",
                        str(report_path),
                        "--manifest",
                        str(manifest_path),
                        "--evidence-dir",
                        str(directory),
                        "--output",
                        str(output),
                    ]
                )
            gate = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertTrue(gate["evidence_package"]["passed"])

    def test_cli_returns_failure_when_output_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            report_path = write_report(directory)
            output = directory / "existing-directory"
            output.mkdir()
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                exit_code = main(["--report", str(report_path), "--output", str(output)])

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "error: Phase 2 tablet gate output could not be written\n",
        )


if __name__ == "__main__":
    unittest.main()
