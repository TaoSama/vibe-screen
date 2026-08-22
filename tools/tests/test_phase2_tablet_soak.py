from __future__ import annotations

import argparse
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.phase2_tablet_soak import (
    DeviceLock,
    acquire_device_locks,
    append_preflight_blockers,
    build_readiness,
    is_sha256_digest,
    main,
    run_or_preflight,
    runner_required_artifacts,
    write_readme,
    write_log_derivatives,
)

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-soak-readiness.schema.json"
REPO_ROOT = Path(__file__).parents[2]


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
        "repo": REPO_ROOT,
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

    def test_preflight_manifest_artifacts_use_readiness_paths(self):
        artifacts = runner_required_artifacts("preflight")

        self.assertIn("phase2-soak-readiness.json", artifacts)
        self.assertIn("soak-preflight/samples.jsonl", artifacts)
        self.assertIn("soak-preflight/summary.json", artifacts)
        self.assertIn("host.txt", artifacts)
        self.assertNotIn("samples.jsonl", artifacts)
        self.assertNotIn("summary.json", artifacts)
        self.assertNotIn("host.log", artifacts)

    def test_sha256_digest_validation(self):
        self.assertTrue(is_sha256_digest("a" * 64))
        self.assertTrue(is_sha256_digest(" " + "A" * 64 + " "))
        self.assertFalse(is_sha256_digest("a" * 63))
        self.assertFalse(is_sha256_digest("g" * 64))
        self.assertFalse(is_sha256_digest("readiness-only-no-apk-hash"))
        self.assertFalse(is_sha256_digest(None))

    def test_generated_readme_names_readiness_close_contract(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            write_readme(
                directory,
                build_readiness(
                    mode="preflight",
                    command=["phase2-tablet-soak"],
                    output_dir=directory,
                    device_class="android_substitute",
                    blockers=["--apk-sha256 must be a 64-character hexadecimal digest"],
                    artifacts=[{"path": "apk-sha256.txt", "kind": "android_artifact"}],
                    soak_summary=None,
                    gate=None,
                ),
            )
            readme = (directory / "README.md").read_text(encoding="utf-8")

        self.assertIn("phase2-soak-readiness.json", readme)
        self.assertIn("can_close_phase2_gate=true", readme)
        self.assertIn("readiness-only blocker context", readme)

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
            output_files = sorted(
                path.name for path in directory.iterdir() if path.name != "android.lock"
            )

        self.assertEqual(readiness["result"], "blocked")
        self.assertFalse(readiness["can_close_phase2_gate"])
        self.assertIn("device coordination lock exists", " ".join(readiness["blockers"]))
        self.assertEqual(output_files, ["README.md", "phase2-soak-readiness.json"])
        self.assertEqual(persisted["result"], "blocked")
        run.assert_not_called()
        popen.assert_not_called()

    def test_second_lock_race_writes_blocked_readiness_without_adb(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            with (
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", directory / "soak.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", directory / "android.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.DeviceLock.__enter__") as enter_lock,
                patch("vibescreen_evidence.phase2_tablet_soak.subprocess.run") as run,
            ):
                enter_lock.side_effect = [None, FileExistsError("soak lock won by another run")]

                readiness = run_or_preflight(make_args(directory), ["phase2-tablet-soak"])

        self.assertEqual(readiness["result"], "blocked")
        self.assertIn("device coordination lock exists", " ".join(readiness["blockers"]))
        run.assert_not_called()

    def test_device_lock_releases_owned_file_after_inner_lock_failure(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            owner = {"pid": 123, "serial": "EP0110PZ0B9110300B"}
            android_lock = directory / "android.lock"
            soak_lock = directory / "soak.lock"

            with self.assertRaises(FileExistsError):
                with DeviceLock(android_lock, owner=owner):
                    with DeviceLock(soak_lock, owner=owner):
                        raise FileExistsError("simulated second lock failure")

            self.assertFalse(android_lock.exists())
            self.assertFalse(soak_lock.exists())

    def test_acquire_device_locks_releases_android_lock_when_soak_lock_exists(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            android_lock = directory / "android.lock"
            soak_lock = directory / "soak.lock"
            soak_lock.write_text("owned by another run\n", encoding="utf-8")

            with (
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", android_lock),
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", soak_lock),
            ):
                with self.assertRaises(FileExistsError):
                    acquire_device_locks({"pid": 123, "serial": "EP0110PZ0B9110300B"})

            self.assertFalse(android_lock.exists())
            self.assertEqual(soak_lock.read_text(encoding="utf-8"), "owned by another run\n")

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

    def test_preflight_placeholder_apk_sha256_blocks_but_still_runs_soak(self):
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
                patch("vibescreen_evidence.phase2_tablet_soak.start_logcat") as start_logcat,
                patch("vibescreen_evidence.phase2_tablet_soak.SoakRunner") as runner_class,
                patch("vibescreen_evidence.phase2_tablet_soak.collect_after_artifacts", return_value=[]),
                patch("vibescreen_evidence.phase2_tablet_soak.stop_process"),
            ):
                collect.return_value = (
                    device_info,
                    [],
                    [{"path": "device-info.json", "kind": "device_info"}],
                    "readiness-only-no-apk-hash",
                )
                start_logcat.return_value = (object(), object())
                runner_class.return_value.run.return_value = {"status": "complete"}

                readiness = run_or_preflight(make_args(directory), ["phase2-tablet-soak"])

        self.assertEqual(readiness["result"], "blocked")
        self.assertIn("--apk-sha256 must be a 64-character hexadecimal digest", readiness["blockers"])
        runner_class.assert_called_once()

    def test_formal_run_logcat_failure_blocks_and_skips_gate(self):
        device_info = {
            "device": {
                "adb_serial": "EP0110PZ0B9110300B",
                "device_serial": "EP0110PZ0B9110300B",
                "manufacturer": "test",
                "model": "Tablet",
                "codename": "tablet",
                "android_release": "16",
                "sdk": 36,
                "build_fingerprint": "test/tablet/build",
                "abi": "arm64-v8a",
            }
        }
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            telemetry = directory / "host-telemetry.jsonl"
            telemetry.write_text("{}\n", encoding="utf-8")
            with (
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", directory / "soak.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", directory / "android.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.collect_static_artifacts") as collect,
                patch("vibescreen_evidence.phase2_tablet_soak.start_logcat", return_value=(None, None)),
                patch("vibescreen_evidence.phase2_tablet_soak.SoakRunner") as runner,
                patch("vibescreen_evidence.phase2_tablet_soak.derive_gate") as derive_gate,
                patch("vibescreen_evidence.phase2_tablet_soak.collect_after_artifacts", return_value=[]),
            ):
                collect.return_value = (device_info, [], [{"path": "device-info.json", "kind": "device_info"}], "a" * 64)
                readiness = run_or_preflight(
                    make_args(
                        directory,
                        mode="run",
                        device_class="physical_8_9_inch_tablet",
                        host_pid=123,
                        host_telemetry_jsonl=telemetry,
                        apk_sha256="a" * 64,
                    ),
                    ["phase2-tablet-soak"],
                )

        self.assertEqual(readiness["result"], "blocked")
        self.assertFalse(readiness["can_close_phase2_gate"])
        self.assertIn("logcat capture failed", " ".join(readiness["blockers"]))
        runner.assert_not_called()
        derive_gate.assert_not_called()

    def test_formal_run_derives_gate_with_manifest_and_evidence_dir(self):
        device_info = {
            "device": {
                "adb_serial": "EP0110PZ0B9110300B",
                "device_serial": "EP0110PZ0B9110300B",
                "manufacturer": "test",
                "model": "Tablet",
                "codename": "tablet",
                "android_release": "16",
                "sdk": 36,
                "build_fingerprint": "test/tablet/build",
                "abi": "arm64-v8a",
            }
        }
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            telemetry = directory / "host-telemetry.jsonl"
            telemetry.write_text("{}\n", encoding="utf-8")
            with (
                patch("vibescreen_evidence.phase2_tablet_soak.SOAK_LOCK", directory / "soak.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.ANDROID_LOCK", directory / "android.lock"),
                patch("vibescreen_evidence.phase2_tablet_soak.collect_static_artifacts") as collect,
                patch("vibescreen_evidence.phase2_tablet_soak.start_logcat") as start_logcat,
                patch("vibescreen_evidence.phase2_tablet_soak.SoakRunner") as runner_class,
                patch("vibescreen_evidence.phase2_tablet_soak.derive_report", return_value={"kind": "report"}),
                patch("vibescreen_evidence.phase2_tablet_soak.derive_gate", return_value={"verdict": "pass"}) as derive_gate,
                patch("vibescreen_evidence.phase2_tablet_soak.collect_after_artifacts", return_value=[]),
                patch("vibescreen_evidence.phase2_tablet_soak.stop_process"),
            ):
                collect.return_value = (device_info, [], [{"path": "device-info.json", "kind": "device_info"}], "a" * 64)
                start_logcat.return_value = (object(), object())
                runner_class.return_value.run.return_value = {"status": "complete"}

                readiness = run_or_preflight(
                    make_args(
                        directory,
                        mode="run",
                        device_class="physical_8_9_inch_tablet",
                        host_pid=123,
                        host_telemetry_jsonl=telemetry,
                        apk_sha256="a" * 64,
                    ),
                    ["phase2-tablet-soak"],
                )

        self.assertTrue(readiness["can_close_phase2_gate"])
        derive_gate.assert_called_once_with(
            directory / "soak-8h" / "exact-window-report.json",
            manifest_path=directory / "phase2-tablet-manifest.json",
            evidence_dir=directory,
        )

    def test_formal_mode_rejects_placeholder_apk_sha256(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main([
                        "--serial",
                        "EP0110PZ0B9110300B",
                        "--output-dir",
                        str(directory),
                        "--mode",
                        "run",
                        "--apk-sha256",
                        "readiness-only-no-apk-hash",
                        "--device-class",
                        "physical_8_9_inch_tablet",
                        "--stand-setup",
                        "desktop stand",
                        "--charger",
                        "vendor charger",
                        "--cable-or-dock",
                        "USB-C cable",
                        "--video-preferences",
                        "Balanced",
                        "--host-identity",
                        "test host",
                        "--host-build",
                        "signed host",
                    ])

        self.assertEqual(raised.exception.code, 2)

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
