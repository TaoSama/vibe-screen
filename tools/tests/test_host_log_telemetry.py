from pathlib import Path
import json
import tempfile
import unittest

from vibescreen_evidence.host_log_telemetry import collect


class HostLogTelemetryCollectTests(unittest.TestCase):
    def _run(self, log_lines_over_time, *, ticks):
        # log_lines_over_time[i] is the full log file content visible at tick i.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            log_path = directory / "host.log"
            output = directory / "telemetry.jsonl"

            state = {"tick": 0}

            def fake_monotonic():
                # One unit per tick; started=0 so tick i is at time i.
                return float(state["tick"])

            def fake_sleep(_seconds):
                state["tick"] += 1
                index = min(state["tick"], len(log_lines_over_time) - 1)
                log_path.write_text(log_lines_over_time[index], encoding="utf-8")

            clock = {"n": 0}

            def fake_wall():
                clock["n"] += 1
                return f"2026-08-08T00:00:{clock['n']:02d}Z"

            log_path.write_text(log_lines_over_time[0], encoding="utf-8")
            written = collect(
                log_path,
                output,
                duration_seconds=float(ticks),
                interval_seconds=1.0,
                monotonic=fake_monotonic,
                sleep=fake_sleep,
                wall_clock=fake_wall,
            )
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return written, records

    @staticmethod
    def _pipeline(fps, dropped):
        return f"Pipeline: {fps}fps, 12.0Mbps, avg frame age: 6.0ms, dropped: {dropped}"

    def test_skips_repeated_identical_pipeline_line(self):
        stalled = self._pipeline(60.0, 0)
        # The host prints nothing new across every tick.
        written, records = self._run([stalled] * 5, ticks=5)
        self.assertEqual(written, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["attributes"]["fps"], 60.0)

    def test_records_each_fresh_pipeline_line(self):
        # Each tick appends a genuinely new sample as the last line.
        logs = []
        accumulated = ""
        for fps, dropped in ((60.0, 0), (59.9, 1), (60.1, 1)):
            accumulated += self._pipeline(fps, dropped) + "\n"
            logs.append(accumulated)
        written, records = self._run(logs, ticks=3)
        self.assertEqual(written, 3)
        self.assertEqual([r["attributes"]["dropped"] for r in records], [0, 1, 1])
        self.assertEqual([r["attributes"]["fps"] for r in records], [60.0, 59.9, 60.1])


if __name__ == "__main__":
    unittest.main()

