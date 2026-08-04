import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from vibescreen_evidence.adb import ADBError
from vibescreen_evidence.soak import PRESET_SECONDS, SoakRunner, parse_duration


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeADBClient:
    serial = "device.example:5555"

    def __init__(self):
        self.state_checks = 0
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return "connected"

    def identity(self):
        return {"model": "Xiaomi 12", "adb_serial": self.serial}

    def adb_version(self):
        return "Android Debug Bridge version 1.0.41"

    def require_device(self):
        self.state_checks += 1
        if self.state_checks == 2:
            raise ADBError("device offline")

    def sample(self, package_name=None):
        return {
            "device": {
                "process": {"package": package_name, "running": True, "pids": [123]},
                "memory": {"app_total_pss_kb": 100 + self.state_checks},
                "thermal": {"status": 0, "temperatures": [{"celsius": 40.0}]},
                "battery": {"level": 80},
                "power": {"current_now_ua": -500000},
            },
            "errors": [],
        }


class DurationTest(unittest.TestCase):
    def test_presets_and_custom_units(self):
        self.assertEqual(PRESET_SECONDS, {"30m": 1800.0, "2h": 7200.0, "8h": 28800.0})
        self.assertEqual(parse_duration("250ms"), 0.25)
        self.assertEqual(parse_duration("1.5m"), 90.0)


class SoakRunnerTest(unittest.TestCase):
    def test_recovers_identity_after_transient_initial_failure(self):
        class TransientIdentityClient(FakeADBClient):
            def __init__(self):
                super().__init__()
                self.identity_calls = 0

            def identity(self):
                self.identity_calls += 1
                if self.identity_calls == 1:
                    raise ADBError("transient identity failure")
                return super().identity()

        client = TransientIdentityClient()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "samples.jsonl"
            runner = SoakRunner(
                client,
                duration_seconds=0.5,
                interval_seconds=1,
                output_jsonl=output,
                summary_json=Path(directory) / "summary.json",
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            summary = runner.run()
            sample = json.loads(output.read_text().splitlines()[0])

        self.assertEqual(sample["device"]["identity"]["model"], "Xiaomi 12")
        self.assertIn("transient identity failure", summary["errors"][0])
        self.assertIsNotNone(summary["environment"]["adb_version"])

    def test_writes_jsonl_summary_and_runs_transition_hooks(self):
        client = FakeADBClient()
        clock = FakeClock()
        hook_calls = []

        def run(command, **kwargs):
            hook_calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "samples.jsonl"
            summary_path = Path(directory) / "summary.json"
            runner = SoakRunner(
                client,
                duration_seconds=2,
                interval_seconds=1,
                output_jsonl=output,
                summary_json=summary_path,
                package_name="dev.vibescreen.client",
                disconnect_hook=("disconnect-command",),
                reconnect_hook=("reconnect-command",),
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                wall_clock=lambda: "2026-08-04T00:00:00Z",
                command_runner=run,
                run_id="run-1",
            )
            summary = runner.run()

            samples = [json.loads(line) for line in output.read_text().splitlines()]
            persisted_summary = json.loads(summary_path.read_text())

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0]["device"]["identity"]["model"], "Xiaomi 12")
        self.assertIn("device offline", samples[1]["errors"][0])
        self.assertTrue(samples[1]["device"]["connected"])
        self.assertEqual(summary["metrics"]["reconnect_count"], 1)
        self.assertEqual(persisted_summary["metrics"]["sample_count"], 2)
        self.assertFalse(summary_path.with_suffix(".json.tmp").exists())
        self.assertEqual(
            [call[0] for call in hook_calls],
            [["disconnect-command"], ["reconnect-command"]],
        )
        self.assertEqual(hook_calls[0][1]["env"]["VIBESCREEN_EVENT"], "disconnect")

    def test_host_rss_is_summarized(self):
        client = FakeADBClient()
        clock = FakeClock()

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "2048\n", "")

        with tempfile.TemporaryDirectory() as directory:
            runner = SoakRunner(
                client,
                duration_seconds=0.5,
                interval_seconds=1,
                output_jsonl=Path(directory) / "samples.jsonl",
                summary_json=Path(directory) / "summary.json",
                host_pid=42,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                command_runner=run,
            )
            summary = runner.run()

        host_stats = summary["metrics"]["statistics"]["host_rss_kb"]
        self.assertEqual(host_stats["max"], 2048.0)
        self.assertEqual(host_stats["samples"], 1)

    def test_formal_soak_requires_running_process_and_stream_telemetry(self):
        client = FakeADBClient()
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "host.jsonl"
            telemetry.write_text(
                json.dumps({"schema_version": 1, "event": "stream_stats"}) + "\n",
                encoding="utf-8",
            )
            runner = SoakRunner(
                client,
                duration_seconds=0.5,
                interval_seconds=1,
                output_jsonl=Path(directory) / "samples.jsonl",
                summary_json=Path(directory) / "summary.json",
                package_name="dev.vibescreen.client",
                telemetry_jsonl=telemetry,
                require_stream_telemetry=True,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            summary = runner.run()

        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["metrics"]["stream_telemetry"]["event_counts"]["stream_stats"], 1)

    def test_missing_process_or_stream_telemetry_is_partial(self):
        class StoppedClient(FakeADBClient):
            def sample(self, package_name=None):
                sample = super().sample(package_name)
                sample["device"]["process"]["running"] = False
                return sample

        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            runner = SoakRunner(
                StoppedClient(),
                duration_seconds=0.5,
                interval_seconds=1,
                output_jsonl=Path(directory) / "samples.jsonl",
                summary_json=Path(directory) / "summary.json",
                package_name="dev.vibescreen.client",
                telemetry_jsonl=Path(directory) / "missing.jsonl",
                require_stream_telemetry=True,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
            summary = runner.run()

        self.assertEqual(summary["status"], "partial")
        self.assertIn("application process was not running", " ".join(summary["errors"]))
        self.assertIn("required stream_stats telemetry", " ".join(summary["errors"]))


if __name__ == "__main__":
    unittest.main()
