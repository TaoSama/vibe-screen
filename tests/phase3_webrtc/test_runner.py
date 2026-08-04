from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/phase3_webrtc/run_local_e2e.py"
SPEC = importlib.util.spec_from_file_location("phase3_webrtc_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunnerTests(unittest.TestCase):
    def test_signaling_config_is_loopback_and_bounded(self) -> None:
        config = RUNNER.signaling_config(39001)
        self.assertEqual(config["listen_address"], "127.0.0.1:39001")
        self.assertLessEqual(config["max_active_sessions"], 8)
        self.assertEqual(
            config["session_ttl_seconds"], config["max_session_ttl_seconds"]
        )

    def test_secret_scan_rejects_exact_value(self) -> None:
        with self.assertRaises(RUNNER.E2EFailure):
            RUNNER.assert_secret_free("prefix generated-secret suffix", ["generated-secret"], "test")

    def test_secret_scan_accepts_redacted_log(self) -> None:
        RUNNER.assert_secret_free("server started; session accepted", ["generated-secret"], "test")

    def test_command_failure_redacts_arguments_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RUNNER.E2EFailure) as failure:
                RUNNER.run_checked(
                    ["/bin/sh", "-c", "printf generated-secret; exit 9"],
                    cwd=Path(directory),
                    timeout=2,
                    redact_values=("generated-secret",),
                )
        self.assertNotIn("generated-secret", str(failure.exception))
        self.assertIn("<redacted>", str(failure.exception))

    def test_metric_parser_requires_exact_metric(self) -> None:
        metrics = "# HELP value\nmetric_total 7\nmetric_other 9\n"
        self.assertEqual(RUNNER.metric_value(metrics, "metric_total"), 7)
        with self.assertRaises(RUNNER.E2EFailure):
            RUNNER.metric_value(metrics, "missing_total")

    def test_locate_binaries_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RUNNER.E2EFailure):
                RUNNER.locate_binaries(Path(directory))


if __name__ == "__main__":
    unittest.main()
