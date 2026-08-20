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
            "first": 100.0,
            "final": 100.0,
            "min": 99.0,
            "mean": 99.5,
            "max": 100.0,
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


class Phase2TabletGateTest(unittest.TestCase):
    def test_complete_eight_hour_stable_report_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            report_path = write_report(Path(raw_directory))
            gate = derive_gate(report_path)

        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["reasons"], [])
        self.assertTrue(all(item["passed"] for item in gate["sufficiency"].values()))
        self.assertTrue(all(item["passed"] for item in gate["criteria"].values()))

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
