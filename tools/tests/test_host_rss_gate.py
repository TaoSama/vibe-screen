from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.host_rss_gate import derive_gate, main


def write_inputs(
    directory: Path,
    *,
    duration_seconds: int = 7200,
    sample_count: int = 241,
    rss_at_minute=lambda minute: 120_000.0,
    status: str = "complete",
    errors: list[str] | None = None,
) -> tuple[Path, Path]:
    started = datetime(2026, 8, 10, tzinfo=timezone.utc)
    finished = started + timedelta(seconds=duration_seconds)
    summary = directory / "summary.json"
    samples = directory / "samples.jsonl"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "run_id": "rss-run",
                "kind": "soak",
                "status": status,
                "started_at": started.isoformat().replace("+00:00", "Z"),
                "finished_at": finished.isoformat().replace("+00:00", "Z"),
                "errors": errors or [],
            }
        ),
        encoding="utf-8",
    )
    rows = []
    for index in range(sample_count):
        elapsed = duration_seconds * index / max(1, sample_count - 1)
        timestamp = started + timedelta(seconds=elapsed)
        rows.append(
            {
                "schema_version": "vibescreen.evidence/v1",
                "run_id": "rss-run",
                "sample_index": index,
                "captured_at": timestamp.isoformat().replace("+00:00", "Z"),
                "elapsed_seconds": elapsed,
                "host": {"rss_kb": rss_at_minute(elapsed / 60.0)},
                "device": {},
                "errors": [],
            }
        )
    samples.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return summary, samples


def write_exact_window_report(
    directory: Path,
    *,
    derivation_status: str = "complete",
    errors: list[str] | None = None,
    started_at: str = "2026-08-10T00:00:00Z",
    finished_at: str = "2026-08-10T02:00:00Z",
    stream_stats_count: int = 241,
    heartbeat_count: int = 241,
    accepted_heartbeat_count: int = 241,
    stream_gap_seconds: float | None = 30.0,
    heartbeat_gap_seconds: float | None = 30.0,
    fps_min: float = 60.0,
    frame_queue_drop_total: float = 0.0,
    queue_depth_max: float = 1.0,
    queue_capacity_min: float = 2.0,
    queue_capacity_max: float = 2.0,
    encoder_in_flight_max: float = 1.0,
    encoder_capacity_min: float = 2.0,
    encoder_capacity_max: float = 2.0,
    frame_registry_max: float = 1.0,
    latest_pixel_buffer_retained_max: float = 1.0,
    latest_pixel_buffer_capacity_min: float = 1.0,
    latest_pixel_buffer_capacity_max: float = 1.0,
    encoder_present_values: list[bool] | None = None,
) -> Path:
    def stats(
        *,
        count: int,
        first: float = 1.0,
        final: float = 1.0,
        minimum: float = 1.0,
        mean: float = 1.0,
        maximum: float = 1.0,
    ) -> dict:
        return {
            "count": count,
            "first": first,
            "final": final,
            "min": minimum,
            "mean": mean,
            "max": maximum,
        }

    report = directory / "exact-window-report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "kind": "soak_exact_window_report",
                "run_id": "rss-run",
                "derivation_status": derivation_status,
                "window": {
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_seconds": 7200,
                    "sample_records_in_window": 241,
                    "telemetry_records_in_window": stream_stats_count + heartbeat_count,
                    "telemetry_records_excluded": 0,
                },
                "source_summary": {"status": "complete", "errors": []},
                "metrics": {
                    "stream": {
                        "fps": stats(
                            count=stream_stats_count,
                            first=60.0,
                            final=60.0,
                            minimum=fps_min,
                            mean=60.0,
                            maximum=60.0,
                        ),
                        "average_frame_age_ms": stats(count=stream_stats_count),
                        "reported_dropped_frames": {
                            "statistics": stats(
                                count=stream_stats_count,
                                first=0.0,
                                final=0.0,
                                minimum=0.0,
                                mean=0.0,
                                maximum=0.0,
                            ),
                            "sum": 0.0,
                        },
                        "frame_queue_drop_total": frame_queue_drop_total,
                        "queue_depth": stats(
                            count=stream_stats_count,
                            maximum=queue_depth_max,
                        ),
                        "queue_capacity": stats(
                            count=stream_stats_count,
                            first=queue_capacity_min,
                            final=queue_capacity_min,
                            minimum=queue_capacity_min,
                            mean=queue_capacity_min,
                            maximum=queue_capacity_max,
                        ),
                        "encoder_in_flight": stats(
                            count=stream_stats_count,
                            maximum=encoder_in_flight_max,
                        ),
                        "encoder_in_flight_capacity": stats(
                            count=stream_stats_count,
                            first=encoder_capacity_min,
                            final=encoder_capacity_min,
                            minimum=encoder_capacity_min,
                            mean=encoder_capacity_min,
                            maximum=encoder_capacity_max,
                        ),
                        "frame_registry_count": stats(
                            count=stream_stats_count,
                            maximum=frame_registry_max,
                        ),
                        "latest_pixel_buffer_retained": stats(
                            count=stream_stats_count,
                            maximum=latest_pixel_buffer_retained_max,
                        ),
                        "latest_pixel_buffer_capacity": stats(
                            count=stream_stats_count,
                            first=latest_pixel_buffer_capacity_min,
                            final=latest_pixel_buffer_capacity_min,
                            minimum=latest_pixel_buffer_capacity_min,
                            mean=latest_pixel_buffer_capacity_min,
                            maximum=latest_pixel_buffer_capacity_max,
                        ),
                    },
                    "telemetry": {
                        "event_counts": {
                            "stream_stats": stream_stats_count,
                            "heartbeat_received": heartbeat_count,
                        },
                        "stream_stats_gaps": {
                            "count": stream_stats_count,
                            "maximum_interval_seconds": stream_gap_seconds,
                            "maximum_window_gap_seconds": stream_gap_seconds,
                        },
                        "heartbeat_gaps": {
                            "count": heartbeat_count,
                            "maximum_interval_seconds": heartbeat_gap_seconds,
                            "maximum_window_gap_seconds": heartbeat_gap_seconds,
                        },
                        "accepted_heartbeat_count": accepted_heartbeat_count,
                        "fallback_capture_active_values": [False],
                        "encoder_present_values": encoder_present_values
                        if encoder_present_values is not None
                        else [True],
                    },
                },
                "errors": errors or [],
            }
        ),
        encoding="utf-8",
    )
    return report


class HostRSSGateTest(unittest.TestCase):
    def test_flat_noisy_two_hour_window_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory),
                rss_at_minute=lambda minute: 120_000.0 + (128.0 if int(minute * 2) % 2 else -128.0),
            )
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(all(
            item["passed"] for item in report["criteria"].values()
        ))

    def test_historical_growth_rate_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory),
                rss_at_minute=lambda minute: 500_000.0 + 96.5 * minute,
            )
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["criteria"][
                "second_half_ols_slope_ci_upper_kib_per_minute"
            ]["passed"]
        )
        self.assertFalse(
            report["criteria"][
                "second_half_theil_sen_slope_kib_per_minute"
            ]["passed"]
        )

    def test_late_step_fails_platform_and_drift_criteria(self):
        def rss(minute: float) -> float:
            return 120_000.0 + (5 * 1024.0 if minute >= 105 else 0.0)

        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(Path(raw_directory), rss_at_minute=rss)
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["criteria"]["second_half_endpoint_median_drift_kib"]["passed"]
        )
        self.assertFalse(
            report["criteria"]["final_quarter_mean_step_kib"]["passed"]
        )

    def test_short_window_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory), duration_seconds=900, sample_count=31
            )
            exact_window = write_exact_window_report(
                Path(raw_directory),
                finished_at="2026-08-10T00:15:00Z",
                stream_stats_count=31,
                heartbeat_count=31,
                accepted_heartbeat_count=31,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["sufficiency"]["duration"]["passed"])
        self.assertFalse(report["sufficiency"]["elapsed_span"]["passed"])
        self.assertEqual(report["window"]["elapsed_span_seconds"], 900)

    def test_stretched_wall_clock_with_short_elapsed_span_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            for index, row in enumerate(rows):
                row["elapsed_seconds"] = 900 * index / max(1, len(rows) - 1)
            samples.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            exact_window = write_exact_window_report(directory)
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["sufficiency"]["elapsed_span"]["passed"])
        self.assertEqual(report["window"]["elapsed_span_seconds"], 900)

    def test_elapsed_span_uses_all_in_window_samples_not_only_rss_samples(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            del rows[0]["host"]
            del rows[-1]["host"]
            samples.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            exact_window = write_exact_window_report(directory)
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["window"]["elapsed_span_seconds"], 7200)
        self.assertEqual(report["window"]["host_rss_sample_count"], 239)

    def test_missing_end_of_window_coverage_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(Path(raw_directory))
            rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            for index, row in enumerate(rows):
                row["captured_at"] = (
                    datetime(2026, 8, 10, tzinfo=timezone.utc)
                    + timedelta(seconds=index * 10)
                ).isoformat().replace("+00:00", "Z")
            samples.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["sufficiency"]["finish_boundary_gap"]["passed"])

    def test_large_internal_sampling_gap_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(Path(raw_directory))
            rows = [
                json.loads(line)
                for line in samples.read_text(encoding="utf-8").splitlines()
            ]
            rows = rows[:100] + rows[105:]
            samples.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["sufficiency"]["maximum_internal_gap"]["passed"]
        )

    def test_partial_source_summary_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory), status="partial", errors=["sensor unavailable"]
            )
            exact_window = write_exact_window_report(Path(raw_directory))
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["source_summary"]["error_count"], 1)
        self.assertTrue(report["criteria"])

    def test_cli_fails_closed_on_invalid_input(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary = directory / "summary.json"
            output = directory / "gate.json"
            summary.write_text("{}", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(directory / "missing.jsonl"),
                        "--exact-window-report", str(directory / "missing-report.json"),
                        "--output", str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["sufficiency"], {})

    def test_single_in_window_sample_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory, sample_count=1)
            exact_window = write_exact_window_report(directory)
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--output", str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "complete")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["sufficiency"]["maximum_internal_gap"]["passed"]
        )

    def test_cli_returns_failure_when_output_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            output = directory / "existing-directory"
            output.mkdir()
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--output", str(output),
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "error: host RSS gate output could not be written\n",
        )

    def test_missing_exact_window_report_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(Path(raw_directory))
            report = derive_gate(summary, samples)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["exact_window_report_present"]["passed"]
        )

    def test_partial_exact_window_report_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                derivation_status="partial",
                errors=["host telemetry: no heartbeat_received events in exact window"],
                heartbeat_count=0,
                accepted_heartbeat_count=0,
                heartbeat_gap_seconds=None,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["derivation_complete"]["passed"]
        )
        self.assertTrue(
            any("heartbeat_present" in reason for reason in report["reasons"])
        )

    def test_cli_writes_structured_insufficient_for_missing_telemetry_gaps(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                derivation_status="partial",
                errors=["host telemetry: no heartbeat_received events in exact window"],
                heartbeat_count=0,
                accepted_heartbeat_count=0,
                heartbeat_gap_seconds=None,
            )
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--output", str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "complete")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertIsNone(
            report["telemetry_criteria"]["heartbeat_window_gap_seconds"]["measured"]
        )
        self.assertTrue(
            any("heartbeat_present" in reason for reason in report["reasons"])
        )

    def test_exact_window_queue_over_capacity_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                queue_depth_max=3.0,
                queue_capacity_min=2.0,
                queue_capacity_max=2.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["queue_depth_within_capacity"]["passed"]
        )

    def test_exact_window_latest_pixel_buffer_over_capacity_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                latest_pixel_buffer_retained_max=2.0,
                latest_pixel_buffer_capacity_min=1.0,
                latest_pixel_buffer_capacity_max=1.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["latest_pixel_buffer_within_capacity"]["passed"]
        )

    def test_exact_window_encoder_in_flight_over_capacity_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                encoder_in_flight_max=3.0,
                encoder_capacity_min=2.0,
                encoder_capacity_max=2.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["encoder_in_flight_within_capacity"]["passed"]
        )

    def test_exact_window_frame_registry_over_capacity_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                frame_registry_max=3.0,
                encoder_capacity_min=2.0,
                encoder_capacity_max=2.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["frame_registry_within_encoder_capacity"]["passed"]
        )

    def test_exact_window_frame_queue_drop_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                frame_queue_drop_total=1.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["frame_queue_drop_total"]["passed"]
        )

    def test_exact_window_heartbeat_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                heartbeat_count=241,
                accepted_heartbeat_count=240,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["all_heartbeats_accepted"]["passed"]
        )

    def test_exact_window_telemetry_gap_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                stream_gap_seconds=91.0,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["stream_stats_window_gap_seconds"]["passed"]
        )

    def test_exact_window_non_positive_fps_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory, fps_min=0.0)
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["minimum_fps_positive"]["passed"]
        )

    def test_exact_window_encoder_missing_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                encoder_present_values=[False, True],
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["encoder_present_through_window"]["passed"]
        )


if __name__ == "__main__":
    unittest.main()
