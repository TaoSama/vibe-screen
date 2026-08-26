from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.real_device_gate import (
    build_document,
    collect_locks,
    collect_stream_telemetry,
    main,
    sanitize_document,
    summarize_requested_gates,
    write_json,
)


class RealDeviceGateTests(unittest.TestCase):
    def test_ready_document_requires_host_device_transport_app_and_stream(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["adb", "-s", "sample-p0110-device-serial"]:
                return self._adb_success(command)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nVibe 123 user 9u IPv4 TCP 127.0.0.1:54321 (LISTEN)\n",
                    "",
                )
            if command[-3:-1] == ["preflight", "--report"]:
                Path(command[-1]).write_text("Status: PASS\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "macOS Host touch-rerun preflight passed\n", "")
            return subprocess.CompletedProcess(command, 1, "", f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.repository_state",
            return_value={"revision": "abc", "dirty": False, "status_porcelain": []},
        ):
            root = Path(directory)
            telemetry = root / "host-telemetry.jsonl"
            telemetry.write_text(
                json.dumps(
                    {
                        "event": "stream_stats",
                        "wall_time": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "attributes": {"fps": 60.0, "dropped_frames": 0},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            document = build_document(
                serial="sample-p0110-device-serial",
                repository_root=root,
                evidence_dir=root / "evidence",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                    "sdk": 36,
                },
                host_telemetry_jsonl=telemetry,
                host_log=None,
                require_fresh_stream=True,
                lock_globs=[],
                command_runner=run,
            )

        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["result"], "ready")
        self.assertEqual(document["blockers"], [])
        self.assertEqual(document["insufficiencies"], [])
        self.assertEqual(document["android_device"]["model"], "P0110")
        self.assertTrue(document["transport"]["adb_reverse"]["configured"])
        self.assertTrue(document["android_app"]["foreground"])
        self.assertTrue(document["host_listener"]["listening"])
        self.assertTrue(document["host_preflight"]["passed"])
        self.assertTrue(document["stream"]["ready"])
        self.assertTrue(document["safety"]["read_only"])
        self.assertTrue(commands)

    def test_blocked_document_records_known_operational_blockers(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["adb", "-s", "sample-p0110-device-serial"]:
                tail = command[3:]
                if tail == ["reverse", "--list"]:
                    return subprocess.CompletedProcess(command, 0, "", "")
                if tail == ["shell", "pidof", "dev.telemachus.display"]:
                    return subprocess.CompletedProcess(command, 0, "19904\n", "")
                if tail in (["shell", "dumpsys", "window"], ["shell", "dumpsys", "activity", "activities"]):
                    return subprocess.CompletedProcess(command, 0, "mCurrentFocus=Window{ other/.Activity }\n", "")
                return self._adb_success(command)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            if command[-3:-1] == ["preflight", "--report"]:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    "codesign identity 'Vibe Screen Dev' not found in the keychain.\n",
                )
            return subprocess.CompletedProcess(command, 1, "", f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.repository_state",
            return_value={"revision": "abc", "dirty": False, "status_porcelain": []},
        ):
            root = Path(directory)
            document = build_document(
                serial="sample-p0110-device-serial",
                repository_root=root,
                evidence_dir=root / "evidence",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                host_log=root / "missing.log",
                lock_globs=[],
                command_runner=run,
            )

        self.assertEqual(document["result"], "blocked")
        joined = "\n".join(document["blockers"])
        self.assertIn("Vibe Screen Dev", joined)
        self.assertIn("Mac Host is not listening on TCP 54321", joined)
        self.assertIn("ADB reverse tcp:54321 -> tcp:54321 is not configured", joined)
        self.assertIn("Android app is not foreground", joined)
        self.assertIn("no host stream_stats telemetry", joined)

    def test_device_lock_skips_adb_and_actionable_android_steps(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            if command[-3:-1] == ["preflight", "--report"]:
                return subprocess.CompletedProcess(command, 0, "macOS Host touch-rerun preflight passed\n", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected command")

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.repository_state",
            return_value={"revision": "abc", "dirty": False, "status_porcelain": []},
        ):
            root = Path(directory)
            lock = root / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            document = build_document(
                serial="sample-p0110-device-serial",
                repository_root=root,
                evidence_dir=root / "evidence",
                lock_globs=[str(root / "vibe-screen-*.lock")],
                configure_adb_reverse=True,
                launch_android_app=True,
                command_runner=run,
            )

        self.assertEqual(document["locks"], [str(lock)])
        self.assertIsNone(document["android_device"])
        self.assertFalse(any(command[:1] == ["adb"] for command in commands))
        self.assertIn("device lease lock is present", "\n".join(document["blockers"]))

    def test_short_soak_sampling_does_not_mark_report_as_mutating_state(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            if command[-3:-1] == ["preflight", "--report"]:
                return subprocess.CompletedProcess(command, 0, "macOS Host touch-rerun preflight passed\n", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected command")

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.repository_state",
            return_value={"revision": "abc", "dirty": False, "status_porcelain": []},
        ):
            root = Path(directory)
            lock = root / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            document = build_document(
                serial="sample-p0110-device-serial",
                repository_root=root,
                evidence_dir=root / "evidence",
                lock_globs=[str(lock)],
                collect_short_soak=True,
                command_runner=run,
            )

        self.assertTrue(document["safety"]["read_only"])
        self.assertTrue(document["safety"]["samples_device"])
        self.assertFalse(document["safety"]["creates_adb_reverse"])
        self.assertFalse(document["safety"]["launches_android_app"])

    def test_stream_jsonl_freshness_is_enforced_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            path.write_text(
                json.dumps({"event": "stream_stats", "wall_time": "2026-08-21T00:00:00Z"}) + "\n",
                encoding="utf-8",
            )
            telemetry, blockers = collect_stream_telemetry(
                telemetry_jsonl=path,
                host_log=None,
                freshness_seconds=10.0,
                require_fresh=True,
                now=datetime(2026, 8, 21, 0, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(telemetry["ready"])
        self.assertIn("not fresh", "\n".join(blockers))

    def test_host_log_pipeline_can_be_informational_when_freshness_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.log"
            path.write_text("Pipeline: 59.9fps, 8.0Mbps, avg frame age: 6.0ms, dropped: 0\n", encoding="utf-8")
            telemetry, blockers = collect_stream_telemetry(
                telemetry_jsonl=None,
                host_log=path,
                freshness_seconds=10.0,
                require_fresh=False,
            )

        self.assertTrue(telemetry["ready"])
        self.assertEqual(blockers, [])
        self.assertEqual(telemetry["source"], "host_log")

    def test_gate_summaries_are_insufficient_without_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.repository_state",
            return_value={"revision": "abc", "dirty": False, "status_porcelain": []},
        ):
            root = Path(directory)
            document = build_document(
                serial="sample-p0110-device-serial",
                repository_root=root,
                evidence_dir=root / "evidence",
                require_host_rss_gate=True,
                lock_globs=[],
                host_log=root / "missing.log",
                command_runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "blocked"),
            )

        self.assertEqual(document["result"], "blocked")
        self.assertIn(
            "Host RSS gate requires --soak-summary and --soak-samples",
            "\n".join(document["insufficiencies"]),
        )

    def test_requested_gate_report_with_false_closure_flag_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "latency.json"
            report.write_text(
                json.dumps(
                    {
                        "verdict": "pass",
                        "gate": {
                            "summary_verdict": "pass",
                            "can_close_performance_gate": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[report],
                input_summaries=[],
            )

        self.assertEqual(blockers, [])
        self.assertIn("latency gate report does not contain a passing gate closure verdict", insufficiencies)
        self.assertFalse(requested["latency"][0]["can_close"])
        self.assertEqual(requested["latency"][0]["closure_flags"], [False])

    def test_requested_gate_report_without_closure_flag_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "latency.json"
            report.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[report],
                input_summaries=[],
            )

        self.assertEqual(blockers, [])
        self.assertIn("latency gate report does not contain a passing gate closure verdict", insufficiencies)
        self.assertFalse(requested["latency"][0]["can_close"])
        self.assertEqual(requested["latency"][0]["closure_flags"], [])

    def test_requested_gate_report_accepts_explicit_closure_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "native-pointer.json"
            report.write_text(
                json.dumps(
                    {
                        "verdict": "pass",
                        "can_close_native_pointer_hid_gate": True,
                    }
                ),
                encoding="utf-8",
            )

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[],
                input_summaries=[report],
            )

        self.assertEqual(blockers, [])
        self.assertEqual(insufficiencies, [])
        self.assertTrue(requested["input"][0]["can_close"])
        self.assertEqual(requested["input"][0]["closure_flags"], [True])
        self.assertTrue(requested["input"][0]["has_passing_verdict"])

    def test_requested_gate_report_requires_pass_verdict_with_closure_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "native-pointer.json"
            report.write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "can_close_native_pointer_hid_gate": True,
                    }
                ),
                encoding="utf-8",
            )

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[],
                input_summaries=[report],
            )

        self.assertEqual(blockers, [])
        self.assertIn("input gate summary does not contain a passing gate closure verdict", insufficiencies)
        self.assertFalse(requested["input"][0]["can_close"])
        self.assertEqual(requested["input"][0]["closure_flags"], [True])
        self.assertFalse(requested["input"][0]["has_passing_verdict"])

    def test_requested_gate_report_ignores_requested_scope_close_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "reconnect.json"
            report.write_text(
                json.dumps(
                    {
                        "verdict": "pass",
                        "can_close_requested_scope": True,
                        "can_close_timing_gate": False,
                    }
                ),
                encoding="utf-8",
            )

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[report],
                input_summaries=[],
            )

        self.assertEqual(blockers, [])
        self.assertIn("latency gate report does not contain a passing gate closure verdict", insufficiencies)
        self.assertFalse(requested["latency"][0]["can_close"])
        self.assertEqual(requested["latency"][0]["closure_flags"], [False])
        self.assertTrue(requested["latency"][0]["has_passing_verdict"])

    def test_requested_gate_report_accepts_non_gate_named_closure_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "macos-compatibility.json"
            report.write_text(
                json.dumps(
                    {
                        "verdict": "pass",
                        "can_close_macos_host_compatibility_row": True,
                    }
                ),
                encoding="utf-8",
            )

            requested, blockers, insufficiencies = summarize_requested_gates(
                require_soak_summary=False,
                require_host_rss_gate=False,
                soak_summary=None,
                soak_samples=None,
                host_rss_gate_output=None,
                latency_reports=[],
                input_summaries=[report],
            )

        self.assertEqual(blockers, [])
        self.assertEqual(insufficiencies, [])
        self.assertTrue(requested["input"][0]["can_close"])
        self.assertEqual(requested["input"][0]["closure_flags"], [True])
        self.assertTrue(requested["input"][0]["has_passing_verdict"])

    def test_cli_exits_two_for_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.build_document",
            return_value={
                "schema_version": SCHEMA_VERSION,
                "kind": "android_real_device_gate_readiness",
                "result": "blocked",
                "blockers": ["missing listener"],
                "insufficiencies": [],
            },
        ):
            output = Path(directory) / "report.json"
            exit_code = main(["--serial", "sample-p0110-device-serial", "--output", str(output)])
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(written["result"], "blocked")

    def test_cli_exits_one_for_insufficient_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "vibescreen_evidence.real_device_gate.build_document",
            return_value={
                "schema_version": SCHEMA_VERSION,
                "kind": "android_real_device_gate_readiness",
                "result": "insufficient",
                "blockers": [],
                "insufficiencies": ["missing latency report"],
            },
        ):
            output = Path(directory) / "report.json"
            exit_code = main(["--serial", "sample-p0110-device-serial", "--output", str(output)])
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(written["result"], "insufficient")

    def test_collect_locks_sorts_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "vibe-screen-a.lock"
            second = Path(directory) / "vibe-screen-b.lock"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")

            locks = collect_locks([str(Path(directory) / "vibe-screen-*.lock"), str(first)])

        self.assertEqual(locks, [str(first), str(second)])

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate" / "readiness.json"
            write_json(path, {"result": "blocked"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"result": "blocked"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_public_report_redacts_serial_and_local_paths(self) -> None:
        sample_serial = "sample-p0110-device-serial"
        document = {
            "android_device": {
                "adb_serial": sample_serial,
                "device_serial": sample_serial,
                "model": "P0110",
            },
            "blockers": [
                f"ADB reverse tcp:54321 -> tcp:54321 is not configured for {sample_serial}",
                "could not read "
                + "/"
                + "Users"
                + "/localuser/Library/Application Support/com.apple."
                + "TCC"
                + "/TCC"
                + ".db",
            ],
            "transport": {
                "adb_reverse": {
                    "list_probe": {
                        "command": ["adb", "-s", sample_serial, "reverse", "--list"],
                        "stdout": f"{sample_serial} tcp:54321 tcp:54321",
                        "stderr": "",
                    }
                }
            },
        }

        sanitized = sanitize_document(document, adb_serial=sample_serial)
        encoded = json.dumps(sanitized)

        self.assertNotIn(sample_serial, encoded)
        self.assertNotIn("/" + "Users" + "/localuser", encoded)
        self.assertIn("<redacted-adb-serial>", encoded)
        self.assertIn("/" + "Users" + "/<redacted-user>", encoded)
        self.assertEqual(sanitized["android_device"]["model"], "P0110")

    @staticmethod
    def _adb_success(command):
        tail = command[3:]
        values = {
            ("get-state",): "device\n",
            ("shell", "getprop", "ro.product.manufacturer"): "nubia\n",
            ("shell", "getprop", "ro.product.model"): "P0110\n",
            ("shell", "getprop", "ro.product.device"): "pacific\n",
            ("shell", "getprop", "ro.product.name"): "pacific\n",
            ("shell", "getprop", "ro.build.version.release"): "16\n",
            ("shell", "getprop", "ro.build.version.sdk"): "36\n",
            ("shell", "getprop", "ro.build.fingerprint"): "nubia/pacific/test\n",
            ("shell", "getprop", "ro.product.cpu.abi"): "arm64-v8a\n",
            ("shell", "getprop", "ro.serialno"): "sample-p0110-device-serial\n",
            ("reverse", "--list"): "sample-p0110-device-serial tcp:54321 tcp:54321\n",
            ("shell", "pidof", "dev.telemachus.display"): "19904\n",
            ("shell", "dumpsys", "window"): "mCurrentFocus=Window{ dev.telemachus.display/.MainActivity }\n",
            ("shell", "dumpsys", "activity", "activities"): "mResumedActivity: dev.telemachus.display/.MainActivity\n",
        }
        return subprocess.CompletedProcess(command, 0, values.get(tuple(tail), ""), "")


if __name__ == "__main__":
    unittest.main()
