from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.host_rss_gate import derive_gate as _derive_gate, main


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
    stream_gap_count: int | None = None,
    heartbeat_gap_count: int | None = None,
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
    lifecycle_metric_count: int | None = None,
    stream_boolean_count: int | None = None,
    fallback_capture_active_values: list[bool] | None = None,
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
    lifecycle_count = (
        stream_stats_count if lifecycle_metric_count is None else lifecycle_metric_count
    )
    boolean_count = stream_stats_count if stream_boolean_count is None else stream_boolean_count
    stream_gap_count = stream_stats_count if stream_gap_count is None else stream_gap_count
    heartbeat_gap_count = heartbeat_count if heartbeat_gap_count is None else heartbeat_gap_count
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
                            count=lifecycle_count,
                            maximum=queue_depth_max,
                        ),
                        "queue_capacity": stats(
                            count=lifecycle_count,
                            first=queue_capacity_min,
                            final=queue_capacity_min,
                            minimum=queue_capacity_min,
                            mean=queue_capacity_min,
                            maximum=queue_capacity_max,
                        ),
                        "encoder_in_flight": stats(
                            count=lifecycle_count,
                            maximum=encoder_in_flight_max,
                        ),
                        "encoder_in_flight_capacity": stats(
                            count=lifecycle_count,
                            first=encoder_capacity_min,
                            final=encoder_capacity_min,
                            minimum=encoder_capacity_min,
                            mean=encoder_capacity_min,
                            maximum=encoder_capacity_max,
                        ),
                        "frame_registry_count": stats(
                            count=lifecycle_count,
                            maximum=frame_registry_max,
                        ),
                        "latest_pixel_buffer_retained": stats(
                            count=lifecycle_count,
                            maximum=latest_pixel_buffer_retained_max,
                        ),
                        "latest_pixel_buffer_capacity": stats(
                            count=lifecycle_count,
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
                            "count": stream_gap_count,
                            "maximum_interval_seconds": stream_gap_seconds,
                            "maximum_window_gap_seconds": stream_gap_seconds,
                        },
                        "heartbeat_gaps": {
                            "count": heartbeat_gap_count,
                            "maximum_interval_seconds": heartbeat_gap_seconds,
                            "maximum_window_gap_seconds": heartbeat_gap_seconds,
                        },
                        "accepted_heartbeat_count": accepted_heartbeat_count,
                        "stream_boolean_counts": {
                            "fallback_capture_active": boolean_count,
                            "encoder_present": boolean_count,
                        },
                        "fallback_capture_active_values": fallback_capture_active_values
                        if fallback_capture_active_values is not None
                        else [False],
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


def host_readiness_payload(
    *,
    source_commit: str = "c" * 40,
    source_tree: str = "d" * 40,
    source_dirty: bool = False,
    current_source_commit: str | None = None,
    current_source_tree: str | None = None,
    current_source_dirty: bool = False,
    can_start_host_rss_gate: bool = True,
    signing_tcc_status: str = "ready",
    listener_observed: bool = True,
    is_ad_hoc: bool = False,
    certificate_sha1: str = "9AAE572BF6D764E3436A6109197D345B5A87998C",
    expected_certificate_sha1: str = "9AAE572BF6D764E3436A6109197D345B5A87998C",
    permissions_readable: bool = True,
    permission_value: bool = True,
) -> dict:
    current_source_commit = current_source_commit or source_commit
    current_source_tree = current_source_tree or source_tree
    return {
        "schema_version": "vibescreen.host-readiness/v1",
        "kind": "macos_host_shared_prerequisite_readiness",
        "generated_at": "2026-08-10T00:00:00+00:00",
        "status": "pass" if can_start_host_rss_gate else "blocked",
        "signing_tcc_status": signing_tcc_status,
        "listener_status": "ready" if listener_observed else "blocked",
        "virtual_hid_status": "blocked",
        "login_headless_status": "blocked",
        "can_start_host_rss_gate": can_start_host_rss_gate,
        "can_start_trusted_lan_gate": can_start_host_rss_gate,
        "can_start_native_hid_gate": can_start_host_rss_gate,
        "can_start_stylus_gate": can_start_host_rss_gate,
        "can_start_hardware_keyboard_gate": can_start_host_rss_gate,
        "can_start_controller_runtime_gate": False,
        "can_start_headless_login_gate": False,
        "can_close_runtime_gates": False,
        "blockers": [] if can_start_host_rss_gate else ["Host listener is not observed"],
        "host": {
            "app_path": "/Applications/Vibe Screen.app",
            "identifier": "dev.telemachus.display",
            "identity": "Vibe Screen Dev",
            "is_ad_hoc": is_ad_hoc,
            "authorities": ["Vibe Screen Dev"],
            "team_identifier": None,
            "certificate_sha1": certificate_sha1,
            "expected_certificate_sha1": expected_certificate_sha1,
            "cdhash": "a" * 40,
            "binary_sha256": "b" * 64,
            "designated_requirement": "identifier \"dev.telemachus.display\" and certificate leaf = H\"9AAE572BF6D764E3436A6109197D345B5A87998C\"",
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_dirty": source_dirty,
            "current_source_commit": current_source_commit,
            "current_source_tree": current_source_tree,
            "current_source_dirty": current_source_dirty,
        },
        "permissions": {
            "database_path": "<user-tcc-db>; <system-tcc-db>",
            "readable": permissions_readable,
            "error": None,
            "screen_recording_granted": permission_value,
            "screen_recording_auth_reason": 2,
            "accessibility_granted": permission_value,
            "accessibility_auth_reason": 2,
            "microphone_granted": permission_value,
            "microphone_auth_reason": 2,
            "screen_recording_state": "authorized_current_host_identity",
            "accessibility_state": "authorized_current_host_identity",
            "microphone_state": "authorized_current_host_identity",
            "screen_recording_identity_bound": permission_value,
            "accessibility_identity_bound": permission_value,
            "microphone_identity_bound": permission_value,
            "rows": [],
        },
        "listener": {"port": 54321, "observed": listener_observed, "output": "Vibe Screen LISTEN", "error": None},
        "entitlements": {"app_path": "/Applications/Vibe Screen.app", "virtual_hid": False, "keys": [], "error": None},
        "login_headless": {"status": "blocked", "blockers": ["Launch at Login is not verified enabled: unverified"]},
        "safety": {
            "read_only": True,
            "starts_host": False,
            "opens_host_gui": False,
            "opens_system_settings": False,
            "requests_screen_recording": False,
            "requests_accessibility": False,
            "requests_microphone": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "installs_or_replaces_host": False,
            "modifies_android": False,
            "closes_runtime_gates": False,
        },
    }


def write_host_readiness(directory: Path, **overrides) -> Path:
    report = directory / "host-readiness.json"
    report.write_text(json.dumps(host_readiness_payload(**overrides)), encoding="utf-8")
    return report


def derive_gate(
    summary: Path,
    samples: Path,
    exact_window: Path | None = None,
    host_readiness: Path | None = None,
) -> dict:
    if host_readiness is None and exact_window is not None:
        host_readiness = write_host_readiness(summary.parent)
    return _derive_gate(summary, samples, exact_window, host_readiness)


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
        self.assertEqual(
            report["source"],
            {
                "summary": summary.as_posix(),
                "samples": samples.as_posix(),
                "exact_window_report": exact_window.as_posix(),
                "host_readiness": (Path(raw_directory) / "host-readiness.json").as_posix(),
            },
        )
        self.assertEqual(report["source_summary"]["errors"], [])
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
                        "--host-readiness", str(directory / "missing-readiness.json"),
                        "--output", str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["sufficiency"], {})

    def test_cli_records_repo_relative_source_paths_when_repo_root_is_set(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            evidence_dir = directory / "docs" / "evidence" / "host-rss"
            evidence_dir.mkdir(parents=True)
            summary, samples = write_inputs(evidence_dir)
            exact_window = write_exact_window_report(evidence_dir)
            host_readiness = write_host_readiness(evidence_dir)
            output = evidence_dir / "host-rss-gate.json"

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--host-readiness", str(host_readiness),
                        "--output", str(output),
                        "--repo-root", str(directory),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            report["source"],
            {
                "summary": "docs/evidence/host-rss/summary.json",
                "samples": "docs/evidence/host-rss/samples.jsonl",
                "exact_window_report": (
                    "docs/evidence/host-rss/exact-window-report.json"
                ),
                "host_readiness": "docs/evidence/host-rss/host-readiness.json",
            },
        )
        self.assertEqual(report["host_readiness"]["status"], "pass")
        self.assertTrue(
            report["host_readiness_criteria"]["can_start_host_rss_gate"]["passed"]
        )

    def test_cli_fails_closed_on_malformed_host_rss_values(self):
        for bad_rss in ("120000", True, {}, []):
            with self.subTest(bad_rss=bad_rss), tempfile.TemporaryDirectory() as raw_directory:
                directory = Path(raw_directory)
                summary, samples = write_inputs(directory)
                rows = [
                    json.loads(line)
                    for line in samples.read_text(encoding="utf-8").splitlines()
                ]
                rows[10]["host"]["rss_kb"] = bad_rss
                samples.write_text(
                    "\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8",
                )
                exact_window = write_exact_window_report(directory)
                host_readiness = write_host_readiness(directory)
                output = directory / "gate.json"

                with redirect_stdout(io.StringIO()):
                    exit_code = main(
                        [
                            "--summary", str(summary),
                            "--samples", str(samples),
                            "--exact-window-report", str(exact_window),
                            "--host-readiness", str(host_readiness),
                            "--output", str(output),
                        ]
                    )
                report = json.loads(output.read_text(encoding="utf-8"))

                self.assertEqual(exit_code, 1)
                self.assertEqual(report["derivation_status"], "failed")
                self.assertEqual(report["verdict"], "insufficient")

    def test_single_in_window_sample_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory, sample_count=1)
            exact_window = write_exact_window_report(directory)
            host_readiness = write_host_readiness(directory)
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--host-readiness", str(host_readiness),
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
            host_readiness = write_host_readiness(directory)
            output = directory / "existing-directory"
            output.mkdir()
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--host-readiness", str(host_readiness),
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
            host_readiness = write_host_readiness(directory)
            output = directory / "gate.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--exact-window-report", str(exact_window),
                        "--host-readiness", str(host_readiness),
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

    def test_missing_host_readiness_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            report = _derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["host_readiness_sufficiency"]["host_readiness_report_present"]["passed"]
        )
        self.assertIn("host_readiness_report_present", report["reasons"])

    def test_non_object_host_readiness_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            host_readiness = directory / "host-readiness.json"
            host_readiness.write_text("[]", encoding="utf-8")
            report = _derive_gate(summary, samples, exact_window, host_readiness)

        self.assertEqual(report["derivation_status"], "complete")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["host_readiness_sufficiency"]["host_readiness_report_object"]["passed"]
        )
        self.assertTrue(
            any("host_readiness_report_object" in reason for reason in report["reasons"])
        )

    def test_blocked_host_readiness_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            host_readiness = write_host_readiness(
                directory,
                can_start_host_rss_gate=False,
                signing_tcc_status="blocked",
                listener_observed=False,
            )
            report = _derive_gate(summary, samples, exact_window, host_readiness)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["host_readiness_criteria"]["can_start_host_rss_gate"]["passed"]
        )
        self.assertFalse(report["host_readiness_criteria"]["listener_observed"]["passed"])
        self.assertTrue(
            any("signing_tcc_status_ready" in reason for reason in report["reasons"])
        )

    def test_wrong_source_signing_or_tcc_readiness_is_insufficient(self):
        cases = (
            (
                "source_mismatch",
                {"current_source_commit": "e" * 40},
                "installed_host_matches_current_source",
            ),
            (
                "dirty_current_source",
                {"current_source_dirty": True},
                "current_source_clean",
            ),
            (
                "ad_hoc_signed",
                {"is_ad_hoc": True},
                "stable_signing_identity",
            ),
            (
                "permission_not_bound",
                {"permission_value": False},
                "screen_recording_granted",
            ),
            (
                "permission_unreadable",
                {"permissions_readable": False},
                "permissions_readable",
            ),
        )
        for _name, overrides, failing_key in cases:
            with self.subTest(_name), tempfile.TemporaryDirectory() as raw_directory:
                directory = Path(raw_directory)
                summary, samples = write_inputs(directory)
                exact_window = write_exact_window_report(directory)
                host_readiness = write_host_readiness(directory, **overrides)
                report = _derive_gate(summary, samples, exact_window, host_readiness)

                self.assertEqual(report["verdict"], "insufficient")
                self.assertFalse(report["host_readiness_criteria"][failing_key]["passed"])

    def test_host_readiness_safety_must_not_install_or_close_runtime_gates(self):
        cases = (
            "installs_or_replaces_host",
            "closes_runtime_gates",
        )
        for field in cases:
            with self.subTest(field), tempfile.TemporaryDirectory() as raw_directory:
                directory = Path(raw_directory)
                summary, samples = write_inputs(directory)
                exact_window = write_exact_window_report(directory)
                host_readiness = directory / "host-readiness.json"
                payload = host_readiness_payload()
                payload["safety"][field] = True
                host_readiness.write_text(json.dumps(payload), encoding="utf-8")

                report = _derive_gate(summary, samples, exact_window, host_readiness)

                self.assertEqual(report["verdict"], "insufficient")
                self.assertFalse(
                    report["host_readiness_criteria"][f"safety_{field}"]["passed"]
                )

    def test_host_readiness_safety_missing_runtime_closure_fields_is_insufficient(self):
        cases = (
            "installs_or_replaces_host",
            "closes_runtime_gates",
        )
        for field in cases:
            with self.subTest(field), tempfile.TemporaryDirectory() as raw_directory:
                directory = Path(raw_directory)
                summary, samples = write_inputs(directory)
                exact_window = write_exact_window_report(directory)
                host_readiness = directory / "host-readiness.json"
                payload = host_readiness_payload()
                payload["safety"].pop(field)
                host_readiness.write_text(json.dumps(payload), encoding="utf-8")

                report = _derive_gate(summary, samples, exact_window, host_readiness)

                self.assertEqual(report["verdict"], "insufficient")
                self.assertFalse(
                    report["host_readiness_criteria"][f"safety_{field}"]["passed"]
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

    def test_exact_window_gap_counts_must_match_event_counts(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                stream_stats_count=241,
                stream_gap_count=1,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["telemetry_gap_counts_match_events"]["passed"]
        )

    def test_exact_window_heartbeat_gap_count_must_match_event_count(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                heartbeat_count=241,
                heartbeat_gap_count=1,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["telemetry_gap_counts_match_events"]["passed"]
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

    def test_exact_window_fallback_capture_active_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                fallback_capture_active_values=[False, True],
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(
            report["telemetry_criteria"]["fallback_capture_inactive_through_window"]["passed"]
        )

    def test_exact_window_lifecycle_stat_counts_must_cover_all_stream_stats(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                stream_stats_count=241,
                lifecycle_metric_count=1,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["stream_lifecycle_counts_complete"]["passed"]
        )
        self.assertTrue(
            any(
                "stream_lifecycle_counts_complete" in reason
                for reason in report["reasons"]
            )
        )

    def test_exact_window_capture_state_counts_must_cover_all_stream_stats(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(
                directory,
                stream_stats_count=241,
                stream_boolean_count=1,
            )
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["stream_lifecycle_counts_complete"]["passed"]
        )
        self.assertEqual(
            report["telemetry_metrics"]["stream_boolean_counts"],
            {"fallback_capture_active": 1, "encoder_present": 1},
        )

    def test_exact_window_missing_capture_state_counts_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            payload = json.loads(exact_window.read_text(encoding="utf-8"))
            del payload["metrics"]["telemetry"]["stream_boolean_counts"]
            exact_window.write_text(json.dumps(payload), encoding="utf-8")
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["stream_lifecycle_counts_complete"]["passed"]
        )

    def test_exact_window_partial_capture_state_counts_are_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            payload = json.loads(exact_window.read_text(encoding="utf-8"))
            del payload["metrics"]["telemetry"]["stream_boolean_counts"][
                "fallback_capture_active"
            ]
            exact_window.write_text(json.dumps(payload), encoding="utf-8")
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["stream_lifecycle_counts_complete"]["passed"]
        )

    def test_exact_window_capture_state_counts_must_be_integers(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary, samples = write_inputs(directory)
            exact_window = write_exact_window_report(directory)
            payload = json.loads(exact_window.read_text(encoding="utf-8"))
            payload["metrics"]["telemetry"]["stream_boolean_counts"][
                "fallback_capture_active"
            ] = True
            exact_window.write_text(json.dumps(payload), encoding="utf-8")
            report = derive_gate(summary, samples, exact_window)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["telemetry_sufficiency"]["stream_lifecycle_counts_complete"]["passed"]
        )


if __name__ == "__main__":
    unittest.main()
