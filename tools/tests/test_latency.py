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
    KIND_TELEMETRY_STAGE,
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_USB_GLASS_TO_GLASS_SUB50,
    METHOD_CLIENT_TELEMETRY,
    METHOD_EXTERNAL_CAMERA,
    METHOD_HOST_TELEMETRY,
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
FIXTURE_DIR = REPOSITORY_ROOT / "tools" / "fixtures" / "latency"


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

    def test_usb_glass_to_glass_gate_passes_on_p95_threshold(self) -> None:
        result = summarize(
            [
                {"latency_ms": 20},
                {"latency_ms": 24},
                {"latency_ms": 28},
                {"latency_ms": 32},
                {"latency_ms": 36},
            ],
            kind=KIND_GLASS_TO_GLASS,
            measurement_method=METHOD_EXTERNAL_CAMERA,
            transport=TRANSPORT_USB,
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["gate"]["threshold_ms"], 50.0)
        self.assertEqual(result["gate"]["sample_count"], 5)
        self.assertEqual(result["gate"]["reasons"], [])

    def test_latency_gate_fails_when_p95_exceeds_threshold(self) -> None:
        result = summarize(
            [
                {"latency_ms": 70},
                {"latency_ms": 72},
                {"latency_ms": 74},
                {"latency_ms": 76},
                {"latency_ms": 100},
            ],
            kind=KIND_GLASS_TO_GLASS,
            measurement_method=METHOD_EXTERNAL_CAMERA,
            transport=TRANSPORT_LAN,
            gate_profile=GATE_LAN_GLASS_TO_GLASS_SUB80,
        )

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("exceeds threshold", result["gate"]["reasons"][0])

    def test_latency_gate_is_insufficient_with_too_few_samples(self) -> None:
        result = summarize(
            [{"latency_ms": 10}, {"latency_ms": 12}],
            kind=KIND_INPUT,
            measurement_method=METHOD_SYNCHRONIZED_CLOCK,
            transport=TRANSPORT_USB,
            gate_profile=GATE_INPUT_P95_SUB50,
        )

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("at least 5", result["gate"]["reasons"][0])

    def test_gate_profile_rejects_wrong_kind_or_transport(self) -> None:
        with self.assertRaisesRegex(LatencyInputError, "requires --kind glass-to-glass"):
            summarize(
                [{"latency_ms": 10}] * 5,
                kind=KIND_INPUT,
                measurement_method=METHOD_EXTERNAL_CAMERA,
                transport=TRANSPORT_USB,
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )
        with self.assertRaisesRegex(LatencyInputError, "requires --transport usb"):
            summarize(
                [{"latency_ms": 10}] * 5,
                kind=KIND_GLASS_TO_GLASS,
                measurement_method=METHOD_EXTERNAL_CAMERA,
                transport=TRANSPORT_LAN,
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

    def test_converts_camera_frames_on_one_timebase(self) -> None:
        result = summarize(
            [{"start_frame": 100, "end_frame": 112, "camera_fps": 240}],
            kind=KIND_INPUT,
            measurement_method=METHOD_EXTERNAL_CAMERA,
            transport=TRANSPORT_LAN,
        )

        self.assertEqual(result["samples_ms"], [50.0])

    def test_summarizes_telemetry_stage_without_closing_latency_gate(self) -> None:
        result = summarize(
            [
                {"stage": "host_capture_to_encode", "latency_ms": 6},
                {"stage": "host_capture_to_encode", "latency_ms": 10},
                {"stage": "client_decode", "latency_ms": 8},
            ],
            kind=KIND_TELEMETRY_STAGE,
            measurement_method=METHOD_HOST_TELEMETRY,
            transport=TRANSPORT_USB,
        )

        self.assertEqual(result["kind"], "telemetry_stage_latency")
        self.assertEqual(result["status"], "informational")
        self.assertFalse(result["gate"]["can_close_performance_gate"])
        self.assertIn("client_decode", result["stages"])
        self.assertEqual(result["stages"]["host_capture_to_encode"]["count"], 2)
        self.assertEqual(result["stages"]["host_capture_to_encode"]["median"], 8.0)

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

    def test_rejects_telemetry_method_for_end_to_end_claims(self) -> None:
        for kind in (KIND_GLASS_TO_GLASS, KIND_INPUT):
            with self.subTest(kind=kind), self.assertRaisesRegex(
                LatencyInputError, "can only be summarized with --kind telemetry-stage"
            ):
                summarize(
                    [{"stage": "client_decode", "latency_ms": 12}],
                    kind=kind,
                    measurement_method=METHOD_CLIENT_TELEMETRY,
                    transport=TRANSPORT_USB,
                )

    def test_rejects_telemetry_stage_without_stage_name(self) -> None:
        with self.assertRaisesRegex(LatencyInputError, "non-empty stage"):
            summarize(
                [{"latency_ms": 12}],
                kind=KIND_TELEMETRY_STAGE,
                measurement_method=METHOD_CLIENT_TELEMETRY,
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
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
            stdin='[{"start_frame":0,"end_frame":12,"camera_fps":240}]',
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["latency_kind"], KIND_GLASS_TO_GLASS)
        self.assertEqual(output["transport"], TRANSPORT_USB)
        self.assertEqual(output["statistics"]["p95"], 50)
        self.assertEqual(output["verdict"], "insufficient")

    def test_telemetry_stage_cli_output(self) -> None:
        result = self.run_cli(
            "-",
            "--input-format",
            "json",
            "--kind",
            KIND_TELEMETRY_STAGE,
            "--measurement-method",
            METHOD_CLIENT_TELEMETRY,
            "--transport",
            TRANSPORT_USB,
            stdin=(
                '[{"stage":"client_decode","latency_ms":6},'
                '{"stage":"client_decode","latency_ms":10}]'
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "informational")
        self.assertFalse(output["gate"]["can_close_performance_gate"])
        self.assertEqual(output["stages"]["client_decode"]["p95"], 9.8)

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
                "--gate-profile",
                GATE_INPUT_P95_SUB50,
                "--output-format",
                "csv",
                "--output",
                str(output_path),
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            output = output_path.read_text(encoding="utf-8")
            self.assertIn("metric,value\n", output)
            self.assertIn("median,15.0\n", output)
            self.assertIn("gate.verdict,insufficient\n", output)

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

    def test_fixture_usb_glass_to_glass_profile_passes(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "usb-glass-to-glass-pass.csv"),
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_USB,
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
            "--run-id",
            "fixture-usb-glass-pass",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["run_id"], "fixture-usb-glass-pass")
        self.assertEqual(output["verdict"], "pass")
        self.assertEqual(output["gate"]["profile"], GATE_USB_GLASS_TO_GLASS_SUB50)
        self.assertAlmostEqual(output["statistics"]["p95"], 45.0)

    def test_fixture_lan_glass_to_glass_profile_fails(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "lan-glass-to-glass-fail.csv"),
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_LAN,
            "--gate-profile",
            GATE_LAN_GLASS_TO_GLASS_SUB80,
            "--run-id",
            "fixture-lan-glass-fail",
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "fail")
        self.assertGreater(output["gate"]["observed_ms"], output["gate"]["threshold_ms"])
        self.assertIn("exceeds threshold", output["gate"]["reasons"][0])

    def test_fixture_usb_glass_to_glass_profile_is_insufficient(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "usb-glass-to-glass-insufficient.csv"),
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_USB,
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
            "--run-id",
            "fixture-usb-glass-insufficient",
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertLess(output["gate"]["sample_count"], output["gate"]["min_sample_count"])
        self.assertIn("at least 5", output["gate"]["reasons"][0])

    def test_fixture_input_latency_profile_passes_from_json(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "input-latency-pass.json"),
            "--kind",
            KIND_INPUT,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_USB,
            "--gate-profile",
            GATE_INPUT_P95_SUB50,
            "--run-id",
            "fixture-input-pass",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "pass")
        self.assertTrue(output["gate"]["can_close_performance_gate"])
        self.assertLessEqual(output["gate"]["observed_ms"], 50.0)

    def test_fixture_usb_glass_to_glass_insufficient_exits_nonzero(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "usb-glass-to-glass-insufficient.csv"),
            "--kind",
            KIND_GLASS_TO_GLASS,
            "--measurement-method",
            METHOD_EXTERNAL_CAMERA,
            "--transport",
            TRANSPORT_USB,
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
            "--run-id",
            "fixture-usb-insufficient",
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertLess(output["gate"]["sample_count"], output["gate"]["min_sample_count"])
        self.assertIn("at least 5", output["gate"]["reasons"][0])

    def test_fixture_telemetry_stage_stays_informational(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "telemetry-stage-informational.csv"),
            "--kind",
            KIND_TELEMETRY_STAGE,
            "--measurement-method",
            METHOD_HOST_TELEMETRY,
            "--transport",
            TRANSPORT_USB,
            "--run-id",
            "fixture-stage-info",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "informational")
        self.assertFalse(output["gate"]["can_close_performance_gate"])
        self.assertEqual(output["stages"]["host_capture_to_encode"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
