from contextlib import redirect_stdout
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


class HostRSSGateTest(unittest.TestCase):
    def test_flat_noisy_two_hour_window_passes(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory),
                rss_at_minute=lambda minute: 120_000.0 + (128.0 if int(minute * 2) % 2 else -128.0),
            )
            report = derive_gate(summary, samples)

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
            report = derive_gate(summary, samples)

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
            report = derive_gate(summary, samples)

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
            report = derive_gate(summary, samples)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["sufficiency"]["duration"]["passed"])

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
            report = derive_gate(summary, samples)

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
            report = derive_gate(summary, samples)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(
            report["sufficiency"]["maximum_internal_gap"]["passed"]
        )

    def test_partial_source_summary_is_insufficient(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            summary, samples = write_inputs(
                Path(raw_directory), status="partial", errors=["sensor unavailable"]
            )
            report = derive_gate(summary, samples)

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
                        "--output", str(output),
                    ]
                )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["sufficiency"], {})


if __name__ == "__main__":
    unittest.main()
