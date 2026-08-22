from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.phase2_tablet_soak import (
    DeviceLock,
    append_preflight_blockers,
    build_readiness,
    run_or_preflight,
    write_log_derivatives,
)

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-soak-readiness.schema.json"


def make_args(directory: Path, **overrides):
    values = {
        "output_dir": directory,
        "mode": "preflight",
        "allow_existing_device_lock": False,
        "device_class": "android_substitute",
        "serial": "EP0110PZ0B9110300B",
        "adb": "adb",
        "adb_timeout": 1.0,
        "host_pid": None,
        "host_telemetry_jsonl": None,
        "host_log": None,
        "apk": None,
        "apk_sha256": "test-sha",
        "repo": directory,
        "tablet_size_inches": None,
        "stand_setup": "bench substitute phone, no tablet stand",
        "charger": "unknown charger",
        "cable_or_dock": "USB-C data cable",
        "ambient_temperature_celsius": None,
        "transport": "usb",
        "video_preferences": "preflight only",
        "duration": 28800.0,
        "preflight_duration": 0.1,
        "interval": 1.0,
        "thermal_limit_status": 2,
        "battery_temperature_limit_celsius": None,
        "maximum_net_battery_drain_percent": None,
        "recovery_scenarios": "",
        "host_identity": "test host",
        "host_build": "test host build",
        "notes": None,
        "package": "dev.telemachus.display",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class Phase2TabletSoakTests(unittest.TestCase):
    def test_readiness_matches_schema_required_fields(self):
        readiness = build_readiness(
            mode="preflight",
            command=["phase2-tablet-soak"],
            output_dir=Path("evidence/run"),
            device_class="android_substitute",
            blockers=["not a tablet"],
            artifacts=[{"path": "device-info.json", "kind": "device_info", "returncode": 0}],
            soak_summary={"status": "complete"},
            gate=None,
            android_log_metrics={"telemetry_events": 1, "reconnect_log_lines": 0, "frame_drop_log_lines": 0},
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(readiness), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, readiness)

    def test_existing_device_lock_writes_blocked_readiness_without_adb(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            lock = directory / "android.lock"
            lock.write_text("owned by another run\n", encoding="utf-8")

            with (
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", directory / "soak.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", lock),
                patch("vibescreen_evidence.phase2_tablet_soak.subprocess.run") as run,
                patch("vibescreen_evidence.phase2_tablet_soak.subprocess.Popen") as popen,
            ):
                readiness = run_or_preflight(make_args(directory), ["phase2-tablet-soak"])

            persisted = json.loads((directory / "phase2-soak-readiness.json").read_text())

        self.assertEqual(readiness["result"], "blocked")
        self.assertFalse(readiness["can_close_phase2_gate"])
        self.assertIn("device coordination lock exists", " ".join(readiness["blockers"]))
        self.assertEqual(persisted["result"], "blocked")
        run.assert_not_called()
        popen.assert_not_called()

    def test_formal_run_with_precondition_blocker_does_not_start_soak(self):
        device_info = {
            "device": {
                "adb_serial": "EP0110PZ0B9110300B",
                "device_serial": "EP0110PZ0B9110300B",
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": 36,
                "build_fingerprint": "nubia/pacific/test",
                "abi": "arm64-v8a",
            }
        }
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            with (
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", directory / "soak.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", directory / "android.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.collect_static_artifacts") as collect,
                patch("vibescreen_evidence.phase2_tablet_soak.SoakRunner") as runner,
            ):
                collect.return_value = (device_info, [], [{"path": "device-info.json", "kind": "device_info"}], "sha")
                readiness = run_or_preflight(make_args(directory, mode="run"), ["phase2-tablet-soak"])

        self.assertEqual(readiness["result"], "blocked")
        self.assertIn("not physical_8_9_inch_tablet", " ".join(readiness["blockers"]))
        runner.assert_not_called()

    def test_append_preflight_blockers_reports_gate_preconditions(self):
        blockers: list[str] = []

        append_preflight_blockers(
            blockers,
            device_class="android_substitute",
            device_info=None,
            host_pid=None,
            telemetry_jsonl=Path("missing-host-telemetry.jsonl"),
        )

        joined = "\n".join(blockers)
        self.assertIn("device identity", joined)
        self.assertIn("not physical_8_9_inch_tablet", joined)
        self.assertIn("Host RSS", joined)
        self.assertIn("host telemetry JSONL does not exist", joined)

    def test_write_log_derivatives_extracts_telemetry_reconnects_and_drops(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            raw = directory / "raw-logcat.txt"
            raw.write_text(
                "08-21 VibeScreenTelemetry: {\"event\":\"stream_stats\",\"fps\":60}\n"
                "08-21 Telemachus: reconnect_scheduled in 250ms\n"
                "08-21 VibeScreenTelemetry: {\"event\":\"frame_dropped\",\"reason\":\"stale\"}\n",
                encoding="utf-8",
            )

            metrics = write_log_derivatives(raw, directory)

            telemetry = (directory / "decoder-telemetry.jsonl").read_text()
            reconnects = (directory / "reconnects.log").read_text()
            drops = (directory / "frame-drops.log").read_text()

        self.assertIn("stream_stats", telemetry)
        self.assertIn("frame_dropped", telemetry)
        self.assertIn("reconnect_scheduled", reconnects)
        self.assertIn("frame_dropped", drops)
        self.assertEqual(
            metrics,
            {
                "telemetry_events": 2,
                "reconnect_log_lines": 1,
                "frame_drop_log_lines": 1,
            },
        )

    def test_device_lock_is_exclusive_and_releases_owned_file(self):
        with tempfile.TemporaryDirectory() as directory_name:
            path = Path(directory_name) / "device.lock"
            owner = {"pid": 123, "serial": "EP0110PZ0B9110300B"}

            with DeviceLock(path, owner=owner):
                self.assertTrue(path.exists())
                with self.assertRaises(FileExistsError):
                    with DeviceLock(path, owner={"pid": 456}):
                        pass
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
