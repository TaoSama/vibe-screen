import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import (
    KIND_GLASS_TO_GLASS,
    KIND_INPUT,
    METHOD_EXTERNAL_CAMERA,
    METHOD_SYNCHRONIZED_CLOCK,
    METHOD_UNSYNCHRONIZED_CLOCKS,
    TRANSPORT_LAN,
    TRANSPORT_USB,
    LatencyInputError,
    load_samples,
    summarize,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency"


class LatencySummaryTest(unittest.TestCase):
    def test_summarizes_direct_external_camera_samples(self) -> None:
        result = summarize(
            [
                {"latency_ms": 10},
                {"latency_ms": 20},
                {"latency_ms": 30},
                {"latency_ms": 40},
                {"latency_ms": 50},
            ],
            kind=KIND_GLASS_TO_GLASS,
            measurement_method=METHOD_EXTERNAL_CAMERA,
            transport=TRANSPORT_USB,
        )

        self.assertEqual(result["statistics"]["count"], 5)
        self.assertEqual(result["statistics"]["min"], 10)
        self.assertEqual(result["statistics"]["max"], 50)
        self.assertEqual(result["statistics"]["mean"], 30)
        self.assertEqual(result["statistics"]["median"], 30)
        self.assertAlmostEqual(result["statistics"]["p95"], 48)

    def test_converts_camera_frames_on_one_timebase(self) -> None:
        result = summarize(
            [{"start_frame": 100, "end_frame": 112, "camera_fps": 240}],
            kind=KIND_INPUT,
            measurement_method=METHOD_EXTERNAL_CAMERA,
            transport=TRANSPORT_LAN,
        )

        self.assertEqual(result["samples_ms"], [50.0])

    def test_rejects_unsynchronized_host_device_timestamps_for_any_claim(self) -> None:
        with self.assertRaisesRegex(LatencyInputError, "cannot establish end-to-end latency"):
            summarize(
                [{"latency_ms": 12}],
                kind=KIND_INPUT,
                measurement_method=METHOD_UNSYNCHRONIZED_CLOCKS,
                transport=TRANSPORT_USB,
            )

    def test_rejects_non_camera_glass_to_glass_claim(self) -> None:
        with self.assertRaisesRegex(LatencyInputError, "requires an external-camera"):
            summarize(
                [{"latency_ms": 12}],
                kind=KIND_GLASS_TO_GLASS,
                measurement_method=METHOD_SYNCHRONIZED_CLOCK,
                transport=TRANSPORT_USB,
            )

    def test_rejects_invalid_sample_values(self) -> None:
        invalid_samples = (
            {"latency_ms": -1},
            {"latency_ms": "nan"},
            {"start_frame": 2, "end_frame": 1, "camera_fps": 240},
            {"start_frame": 1, "end_frame": 2, "camera_fps": 0},
            {"latency_ms": 5, "start_frame": 1, "end_frame": 2, "camera_fps": 240},
        )
        for sample in invalid_samples:
            with self.subTest(sample=sample), self.assertRaises(LatencyInputError):
                summarize(
                    [sample],
                    kind=KIND_INPUT,
                    measurement_method=METHOD_EXTERNAL_CAMERA,
                    transport=TRANSPORT_USB,
                )

    def test_loads_csv_and_wrapped_json(self) -> None:
        csv_rows = load_samples(io.StringIO("latency_ms\n12.5\n"), "csv")
        json_rows = load_samples(io.StringIO('{"samples":[{"latency_ms":13}]}'), "json")

        self.assertEqual(csv_rows, [{"latency_ms": "12.5"}])
        self.assertEqual(json_rows, [{"latency_ms": 13}])

    def test_rejects_empty_input(self) -> None:
        with self.assertRaisesRegex(LatencyInputError, "no samples"):
            load_samples(io.StringIO("latency_ms\n"), "csv")


class LatencyCliTest(unittest.TestCase):
    def run_cli(
        self, *arguments: str, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_json_cli_output(self) -> None:
        result = self.run_cli(
            "-",
            "--input-format",
            "json",
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_USB,
            stdin='[{"start_frame":0,"end_frame":12,"camera_fps":240}]',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["latency_kind"], KIND_GLASS_TO_GLASS)
        self.assertEqual(output["transport"], TRANSPORT_USB)
        self.assertEqual(output["statistics"]["p95"], 50)

    def test_csv_cli_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory, "samples.csv")
            output_path = Path(directory, "summary.csv")
            input_path.write_text("latency_ms\n10\n20\n", encoding="utf-8")

            result = self.run_cli(
                str(input_path),
                "--kind",
                KIND_INPUT,
                "--measurement-method",
                METHOD_SYNCHRONIZED_CLOCK,
                "--transport",
                TRANSPORT_LAN,
                "--output-format",
                "csv",
                "--output",
                str(output_path),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = output_path.read_text(encoding="utf-8")
            self.assertIn("metric,value\n", output)
            self.assertIn("median,15.0\n", output)

    def test_cli_rejects_unsynchronized_clock_claim(self) -> None:
        result = self.run_cli(
            "-",
            "--input-format",
            "json",
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_UNSYNCHRONIZED_CLOCKS,
            "--transport",
            TRANSPORT_USB,
            stdin='[{"latency_ms":20}]',
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot establish end-to-end latency", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
