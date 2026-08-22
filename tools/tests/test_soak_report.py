from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.soak_report import (
    EvidenceInputError,
    PUBLIC_EVENT_NAMES,
    derive_report,
    main,
)


def write_inputs(directory: Path):
    summary = directory / "summary.json"
    samples = directory / "samples.jsonl"
    telemetry = directory / "host-telemetry.jsonl"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "vibescreen.evidence/v1",
                "run_id": "run-1",
                "kind": "soak",
                "status": "complete",
                "started_at": "2026-08-05T00:00:00Z",
                "finished_at": "2026-08-05T00:04:00Z",
                "errors": ["preserved source warning"],
            }
        ),
        encoding="utf-8",
    )
    sample_records = []
    for minute, host_rss, client_rss in (
        (0, 100.0, 200.0),
        (1, 110.0, 220.0),
        (2, 120.0, 240.0),
        (3, 130.0, 260.0),
        (4, 140.0, 280.0),
    ):
        sample_records.append(
            {
                "schema_version": "vibescreen.evidence/v1",
                "run_id": "run-1",
                "sample_index": minute,
                "captured_at": f"2026-08-05T00:{minute:02d}:00Z",
                "elapsed_seconds": minute * 60,
                "host": {"rss_kb": host_rss},
                "device": {
                    "memory": {"app_total_pss_kb": client_rss},
                    "thermal": {
                        "status": 0,
                        "temperatures": [
                            {"name": "battery", "celsius": 36.0 + minute}
                        ],
                    },
                    "battery": {
                        "level": 80 - minute,
                        "plugged": 1,
                        "status": 2,
                        "temperature": 370 + minute,
                        "voltage": 4200 - minute,
                    },
                    "power": {"current_now_ua": -500000 + minute},
                },
                "errors": [],
            }
        )
    samples.write_text(
        "\n".join(json.dumps(record) for record in sample_records) + "\n",
        encoding="utf-8",
    )
    telemetry_records = [
        {
            "schema_version": 1,
            "wall_time": "2026-08-04T23:59:59Z",
            "monotonic_ns": 1,
            "event": "stream_stats",
            "attributes": {"fps": 1},
        },
        {
            "schema_version": 1,
            "wall_time": "2026-08-05T00:00:30Z",
            "monotonic_ns": 2,
            "event": "stream_stats",
            "attributes": {
                "fps": 59.0,
                # Historical host-log telemetry used these short aliases.
                "avg_frame_age_ms": 5.0,
                "dropped": 0,
            },
        },
        {
            "schema_version": 1,
            "wall_time": "2026-08-05T00:01:30Z",
            "monotonic_ns": 3,
            "event": "heartbeat_received",
            "attributes": {"accepted": True},
        },
        {
            "schema_version": 1,
            "wall_time": "2026-08-05T00:02:30Z",
            "monotonic_ns": 4,
            "event": "stream_stats",
            "attributes": {
                "fps": 61.0,
                "average_frame_age_ms": 7.0,
                "dropped_frames": 2,
            },
        },
        {
            "schema_version": 1,
            "wall_time": "2026-08-05T00:03:30Z",
            "monotonic_ns": 5,
            "event": "heartbeat_received",
            "attributes": {"accepted": True},
        },
        {
            "schema_version": 1,
            "wall_time": "2026-08-05T00:04:01Z",
            "monotonic_ns": 6,
            "event": "frame_queue_drop",
            "attributes": {"dropped": 99},
        },
    ]
    telemetry.write_text(
        "\n".join(json.dumps(record) for record in telemetry_records) + "\n",
        encoding="utf-8",
    )
    return summary, samples, telemetry


class SoakReportTest(unittest.TestCase):
    def test_public_event_names_remain_available_from_soak_report(self):
        self.assertEqual(
            PUBLIC_EVENT_NAMES,
            (
                "session_admission_failed",
                "session_admitted",
                "session_disconnected",
                "heartbeat_received",
                "frame_queue_drop",
                "stream_stats",
            ),
        )

    def test_derives_exact_window_metrics_and_slopes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            report = derive_report(summary, samples, telemetry)

        self.assertEqual(report["derivation_status"], "complete")
        self.assertEqual(report["source_summary"]["errors"], ["preserved source warning"])
        self.assertEqual(report["window"]["telemetry_records_excluded"], 2)
        self.assertEqual(report["metrics"]["stream"]["fps"]["mean"], 60.0)
        self.assertEqual(
            report["metrics"]["samples"]["gaps"]["maximum_interval_seconds"],
            60.0,
        )
        self.assertEqual(
            report["metrics"]["stream"]["average_frame_age_ms"]["mean"], 6.0
        )
        self.assertEqual(
            report["metrics"]["stream"]["reported_dropped_frames"]["sum"], 2.0
        )
        self.assertEqual(
            report["metrics"]["telemetry"]["accepted_heartbeat_count"], 2
        )
        self.assertEqual(
            report["metrics"]["telemetry"]["stream_stats_gaps"][
                "maximum_interval_seconds"
            ],
            120.0,
        )
        host_slopes = report["metrics"]["memory_kib"]["host_rss"][
            "slope_kib_per_minute"
        ]
        self.assertEqual(host_slopes["full_window"], 10.0)
        self.assertEqual(host_slopes["second_half"], 10.0)
        self.assertEqual(
            report["metrics"]["memory_kib"]["client_total_pss"]["final"], 280.0
        )
        self.assertEqual(
            report["metrics"]["thermal"]["sensors_celsius"]["battery"]["max"],
            40.0,
        )
        self.assertEqual(
            report["metrics"]["battery"]["temperature_celsius"]["min"], 37.0
        )
        self.assertEqual(report["metrics"]["battery"]["plugged"]["min"], 1.0)
        self.assertEqual(report["metrics"]["battery"]["plugged_counts"], {"1": 5})
        self.assertEqual(report["metrics"]["battery"]["status"]["max"], 2.0)
        self.assertEqual(report["metrics"]["battery"]["status_counts"], {"2": 5})
        self.assertIn("not a no-leak", report["interpretation"])

    def test_invalid_lines_and_missing_window_data_are_partial(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            samples.write_text("not-json\n", encoding="utf-8")
            telemetry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "wall_time": "not-a-time",
                        "monotonic_ns": 1,
                        "event": "stream_stats",
                        "attributes": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = derive_report(summary, samples, telemetry)

        self.assertEqual(report["derivation_status"], "partial")
        self.assertTrue(
            any(
                "no records in the summary exact window" in error
                for error in report["errors"]
            )
        )
        self.assertTrue(any("invalid timestamp" in error for error in report["errors"]))

    def test_rejects_invalid_summary_window(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            summary = directory / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "run_id": "run-1",
                        "kind": "soak",
                        "status": "complete",
                        "started_at": "2026-08-05T00:00:00",
                        "finished_at": "2026-08-05T01:00:00Z",
                        "errors": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceInputError, "UTC offset"):
                derive_report(summary, directory / "missing", directory / "missing")

    def test_summary_contract_failures_are_rejected(self):
        cases = (
            ("schema_version", "vibescreen.evidence/v999", "schema_version"),
            ("kind", "input_latency", "summary.kind"),
            ("run_id", "", "summary.run_id"),
            ("status", "unknown", "summary.status"),
        )
        for field, value, error_pattern in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw_dir:
                summary, samples, telemetry = write_inputs(Path(raw_dir))
                record = json.loads(summary.read_text(encoding="utf-8"))
                record["errors"] = []
                record[field] = value
                summary.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaisesRegex(EvidenceInputError, error_pattern):
                    derive_report(summary, samples, telemetry)

    def test_sample_contract_failures_are_partial(self):
        cases = (
            ("schema_version", lambda rows: rows[0].update(
                {"schema_version": "vibescreen.evidence/v999"}), "schema_version"),
            ("negative_index", lambda rows: rows[0].update(
                {"sample_index": -1}), "non-negative integer"),
            ("non_increasing_index", lambda rows: rows[1].update(
                {"sample_index": 0}), "strictly increasing"),
            ("negative_elapsed", lambda rows: rows[1].update(
                {"elapsed_seconds": -1}), "at least 0"),
            ("decreasing_elapsed", lambda rows: rows[2].update(
                {"elapsed_seconds": 30}), "monotonically non-decreasing"),
        )
        for name, mutate, error_pattern in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as raw_dir:
                summary, samples, telemetry = write_inputs(Path(raw_dir))
                rows = [json.loads(line) for line in samples.read_text(
                    encoding="utf-8").splitlines()]
                mutate(rows)
                samples.write_text(
                    "\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8",
                )
                report = derive_report(summary, samples, telemetry)
                self.assertEqual(report["derivation_status"], "partial")
                self.assertTrue(
                    any(error_pattern in error for error in report["errors"]),
                    report["errors"],
                )

    def test_finite_source_values_that_overflow_statistics_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            summary_record = json.loads(summary.read_text(encoding="utf-8"))
            summary_record["errors"] = []
            summary.write_text(json.dumps(summary_record), encoding="utf-8")
            records = [json.loads(line) for line in telemetry.read_text(
                encoding="utf-8").splitlines()]
            records[1]["attributes"]["fps"] = 1e308
            records[3]["attributes"]["fps"] = 1e308
            telemetry.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceInputError, "numeric overflow"):
                derive_report(summary, samples, telemetry)

    def test_telemetry_contract_failures_are_partial(self):
        cases = (
            (
                "integer_schema_version",
                "schema_version",
                lambda row: row.update({"schema_version": 2}),
            ),
            (
                "boolean_schema_version",
                "schema_version",
                lambda row: row.update({"schema_version": True}),
            ),
            ("event", "event", lambda row: row.update({"event": ""})),
            (
                "monotonic_ns",
                "monotonic_ns",
                lambda row: row.update({"monotonic_ns": -1}),
            ),
            ("attributes", "attributes", lambda row: row.update({"attributes": []})),
        )
        for name, error_pattern, mutate in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as raw_dir:
                summary, samples, telemetry = write_inputs(Path(raw_dir))
                records = [json.loads(line) for line in telemetry.read_text(
                    encoding="utf-8").splitlines()]
                mutate(records[1])
                telemetry.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                report = derive_report(summary, samples, telemetry)
                self.assertEqual(report["derivation_status"], "partial")
                self.assertTrue(
                    any(error_pattern in error for error in report["errors"]),
                    report["errors"],
                )

    def test_cli_writes_machine_readable_failure(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            invalid = directory / "summary.json"
            output = directory / "report.json"
            invalid.write_text("{}", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "--summary", str(invalid),
                        "--samples", str(directory / "samples.jsonl"),
                        "--host-telemetry", str(directory / "telemetry.jsonl"),
                        "--output", str(output),
                    ]
                )
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(persisted["derivation_status"], "failed")
        self.assertTrue(persisted["errors"])

    def test_internal_cli_output_and_stdout_behavior_is_preserved(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples, telemetry = write_inputs(Path(raw_directory))
            output = Path(raw_directory) / "internal.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--summary", str(summary),
                        "--samples", str(samples),
                        "--host-telemetry", str(telemetry),
                        "--output", str(output),
                    ]
                )
            persisted = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), persisted)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(persisted["kind"], "soak_exact_window_report")
        self.assertNotIn("publication_profile", persisted)
        self.assertEqual(
            persisted["source_summary"]["errors"], ["preserved source warning"]
        )

    def test_cli_output_modes_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(
                [
                    "--summary", "summary.json",
                    "--samples", "samples.jsonl",
                    "--host-telemetry", "telemetry.jsonl",
                    "--output", "internal.json",
                    "--public-output", "public.json",
                ]
            )
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
