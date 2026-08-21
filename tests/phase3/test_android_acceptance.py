from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.android_internet_acceptance import (
    INTERNET_LEASE_LOCK,
    MANDATORY_DEVICE_LOCKS,
    MAX_HOST_INPUT_EVIDENCE_BYTES,
    AcceptanceError,
    Adb,
    _capture_host_evidence_cursor,
    _coordination_locks,
    _device_identity,
    _extract_session_epoch,
    _read_new_host_evidence,
    _require_device_lease_authorized,
    _require_pattern,
    _require_session_epoch_advance,
    _write_json,
    build_parser,
    coordinate_pair,
    main,
    run,
    swipe,
)


class AndroidAcceptanceTests(unittest.TestCase):
    def test_serial_is_required_instead_of_using_repository_default(self) -> None:
        serial_action = next(
            action for action in build_parser()._actions if action.dest == "serial"
        )
        self.assertTrue(serial_action.required)
        self.assertIsNone(serial_action.default)
        expected_model_action = next(
            action for action in build_parser()._actions if action.dest == "expected_model"
        )
        self.assertIsNone(expected_model_action.default)

    def test_mandatory_locks_cannot_be_replaced_by_additional_lock(self) -> None:
        args = build_parser().parse_args(
            [
                "--apk",
                "/tmp/app.apk",
                "--serial",
                "device.example:5555",
                "--device-lock",
                "/tmp/extra.lock",
                "--lease-token",
                "owner-token",
                "--streaming-pattern",
                "frame",
                "--host-input-evidence",
                "/tmp/host.log",
                "--host-input-pattern",
                "ack",
                "--reconnect-pattern",
                "reconnect",
                "--session-epoch-pattern",
                r"session_epoch=(?P<epoch>\d+)",
                "--evidence",
                "/tmp/evidence.json",
            ]
        )
        self.assertEqual(
            _coordination_locks(args.device_lock),
            (*MANDATORY_DEVICE_LOCKS, Path("/tmp/extra.lock")),
        )
        self.assertEqual(MANDATORY_DEVICE_LOCKS[0], Path("/tmp/vibe-screen-device-soak.lock"))
        self.assertEqual(MANDATORY_DEVICE_LOCKS[1], Path("/tmp/vibe-screen-device-android.lock"))
        self.assertEqual(INTERNET_LEASE_LOCK, Path("/tmp/vibe-screen-device-internet.lock"))

    def test_existing_device_lock_blocks_before_any_adb_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            device_lock = root / "device.lock"
            device_lock.write_text("owned", encoding="utf-8")
            host_evidence = root / "host.log"
            host_evidence.write_text("", encoding="utf-8")
            args = build_parser().parse_args(
                [
                    "--apk",
                    str(apk),
                    "--serial",
                    "device.example:5555",
                    "--device-lock",
                    str(device_lock),
                    "--lease-token",
                    "owner-token",
                    "--streaming-pattern",
                    "frame",
                    "--host-input-evidence",
                    str(host_evidence),
                    "--host-input-pattern",
                    "ack",
                    "--reconnect-pattern",
                    "reconnect",
                    "--session-epoch-pattern",
                    r"session_epoch=(?P<epoch>\d+)",
                    "--evidence",
                    str(root / "evidence.json"),
                ]
            )
            with (
                mock.patch("scripts.phase3.android_internet_acceptance.MANDATORY_DEVICE_LOCKS", ()),
                mock.patch("scripts.phase3.android_internet_acceptance.subprocess.run") as subprocess_run,
            ):
                with self.assertRaisesRegex(AcceptanceError, "device lease lock exists"):
                    run(args)
            subprocess_run.assert_not_called()

    def test_adb_rechecks_lock_before_each_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            device_lock = Path(directory) / "device.lock"
            internet_lock = Path(directory) / "internet.lock"
            internet_lock.write_text("owner-token", encoding="utf-8")
            adb = Adb("adb", "serial", [], [device_lock], internet_lock, "owner-token")
            device_lock.write_text("owned", encoding="utf-8")
            with mock.patch("scripts.phase3.android_internet_acceptance.subprocess.run") as subprocess_run:
                with self.assertRaisesRegex(AcceptanceError, "no ADB command was run"):
                    adb.device(["get-state"])
            subprocess_run.assert_not_called()

    def test_adb_stops_when_internet_lease_owner_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            internet_lock = Path(directory) / "internet.lock"
            internet_lock.write_text("owner-token", encoding="utf-8")
            adb = Adb("adb", "serial", [], [], internet_lock, "owner-token")
            completed = subprocess.CompletedProcess(["adb", "get-state"], 0, stdout="device", stderr="")
            with mock.patch(
                "scripts.phase3.android_internet_acceptance.subprocess.run",
                return_value=completed,
            ) as subprocess_run:
                self.assertEqual(adb.device(["get-state"]), "device")
                internet_lock.write_text("new-owner", encoding="utf-8")
                with self.assertRaisesRegex(AcceptanceError, "owner does not match"):
                    adb.device(["get-state"])
            subprocess_run.assert_called_once()

    def test_cli_reports_locked_device_with_zero_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            device_lock = root / "device.lock"
            device_lock.write_text("owned", encoding="utf-8")
            evidence = root / "failure.json"
            stderr = io.StringIO()
            with (
                mock.patch("scripts.phase3.android_internet_acceptance.MANDATORY_DEVICE_LOCKS", ()),
                mock.patch("scripts.phase3.android_internet_acceptance.subprocess.run") as subprocess_run,
                mock.patch("sys.stderr", stderr),
            ):
                result = main(
                    [
                        "--adb",
                        str(root / "must-not-run-adb"),
                        "--apk",
                        str(apk),
                        "--serial",
                        "device.example:5555",
                        "--device-lock",
                        str(device_lock),
                        "--lease-token",
                        "owner-token",
                        "--streaming-pattern",
                        "frame",
                        "--host-input-evidence",
                        str(root / "host.log"),
                        "--host-input-pattern",
                        "ack",
                        "--reconnect-pattern",
                        "reconnect",
                        "--session-epoch-pattern",
                        r"session_epoch=(?P<epoch>\d+)",
                        "--evidence",
                        str(evidence),
                    ]
                )
            report = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertIn("Wait for the lease owner", stderr.getvalue())
            self.assertEqual(report["commands"], [])
            self.assertIn("<local-path>", report["error"])
            self.assertNotIn(str(device_lock), report["error"])
            self.assertNotIn("owner-token", evidence.read_text(encoding="utf-8"))
            subprocess_run.assert_not_called()

    def test_unreadable_lock_state_fails_closed(self) -> None:
        with mock.patch.object(Path, "lstat", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(AcceptanceError, "cannot verify"):
                _require_device_lease_authorized(
                    [Path("/tmp/device.lock")],
                    Path("/tmp/internet.lock"),
                    "owner-token",
                )

    def test_internet_lease_must_exist_and_match_without_echoing_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "internet.lock"
            with self.assertRaisesRegex(AcceptanceError, "lease is missing"):
                _require_device_lease_authorized([], lock, "private-owner-token")
            lock.write_text("other-owner", encoding="utf-8")
            with self.assertRaises(AcceptanceError) as mismatch:
                _require_device_lease_authorized([], lock, "private-owner-token")
            self.assertNotIn("private-owner-token", str(mismatch.exception))
            self.assertNotIn("other-owner", str(mismatch.exception))
            lock.write_text("private-owner-token\n", encoding="utf-8")
            with self.assertRaisesRegex(AcceptanceError, "owner does not match"):
                _require_device_lease_authorized([], lock, "private-owner-token")
            lock.write_text("private-owner-token", encoding="utf-8")
            _require_device_lease_authorized([], lock, "private-owner-token")

    def test_command_record_hashes_output_and_error_does_not_echo_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            internet_lock = Path(directory) / "internet.lock"
            internet_lock.write_text("owner-token", encoding="utf-8")
            records = []
            endpoint = "device.example:5555"
            adb = Adb(
                "/Users/private-account/platform-tools/adb",
                endpoint,
                records,
                [],
                internet_lock,
                "owner-token",
            )
            completed = subprocess.CompletedProcess(
                ["adb", "connect"],
                1,
                stdout="SSID=private-network BSSID=aa:bb:cc:dd:ee:ff account=private-account",
                stderr="token=owner-token endpoint=device.example:5555",
            )
            with mock.patch("scripts.phase3.android_internet_acceptance.subprocess.run", return_value=completed):
                with self.assertRaises(AcceptanceError) as failure:
                    adb.host(["connect", endpoint, "/Users/private-account/app.apk", "owner-token"])
            self.assertNotIn("owner-token", str(failure.exception))
            self.assertNotIn(endpoint, str(failure.exception))
            evidence_path = Path(directory) / "failure.json"
            _write_json(
                evidence_path,
                {
                    "device": {"manufacturer": "Xiaomi", "model": "2201123C", "device": "zeus"},
                    "error": str(failure.exception),
                    "commands": [record.__dict__ for record in records],
                },
            )
            serialized = evidence_path.read_text(encoding="utf-8")
            for sensitive in (
                endpoint,
                "owner-token",
                "private-network",
                "aa:bb:cc:dd:ee:ff",
                "private-account",
            ):
                self.assertNotIn(sensitive, serialized)
            self.assertIn("<device-endpoint>", records[0].argv)
            self.assertIn("<local-path>", records[0].argv)
            self.assertIn("<redacted>", records[0].argv)
            self.assertFalse(hasattr(records[0], "stdout"))
            self.assertGreater(records[0].stdout_bytes, 0)

    def test_device_identity_excludes_unique_hardware_identifiers(self) -> None:
        values = {
            "ro.product.manufacturer": "Xiaomi",
            "ro.product.model": "2201123C",
            "ro.product.device": "zeus",
            "ro.build.version.release": "14",
            "ro.build.version.sdk": "34",
        }
        with mock.patch(
            "scripts.phase3.android_internet_acceptance._property",
            side_effect=lambda _adb, name: values[name],
        ) as property_reader:
            identity = _device_identity(mock.Mock())
        self.assertEqual(
            identity,
            {
                "manufacturer": "Xiaomi",
                "model": "2201123C",
                "device": "zeus",
                "os_release": "14",
                "api_level": "34",
            },
        )
        requested_properties = {call.args[1] for call in property_reader.call_args_list}
        self.assertNotIn("ro.serialno", requested_properties)
        self.assertNotIn("ro.build.fingerprint", requested_properties)

    def test_host_input_evidence_only_reads_bytes_appended_after_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "host.log"
            evidence.write_text("stale ack\n", encoding="utf-8")
            cursor = _capture_host_evidence_cursor(evidence)
            with evidence.open("a", encoding="utf-8") as destination:
                destination.write("input ack sequence=42\n")
            appended = _read_new_host_evidence(evidence, cursor)
            self.assertEqual(appended, b"input ack sequence=42\n")
            _require_pattern("host input", r"sequence=42", appended.decode())

    def test_host_input_evidence_rejects_unbounded_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "host.log"
            evidence.write_bytes(b"")
            cursor = _capture_host_evidence_cursor(evidence)
            evidence.write_bytes(b"x" * (MAX_HOST_INPUT_EVIDENCE_BYTES + 1))
            with self.assertRaisesRegex(AcceptanceError, "exceeds"):
                _read_new_host_evidence(evidence, cursor)

    def test_session_epoch_requires_named_group_and_strict_advance(self) -> None:
        with self.assertRaisesRegex(AcceptanceError, "named group"):
            _extract_session_epoch("initial", r"session_epoch=\d+", "session_epoch=1")
        first = _extract_session_epoch(
            "initial",
            r"session_epoch=(?P<epoch>\d+)",
            "session_epoch=7",
        )
        reconnect = _extract_session_epoch(
            "reconnect",
            r"session_epoch=(?P<epoch>\d+)",
            "session_epoch=8",
        )
        self.assertEqual((first, reconnect), (7, 8))
        _require_session_epoch_advance(first, reconnect)
        with self.assertRaisesRegex(AcceptanceError, "did not advance"):
            _require_session_epoch_advance(reconnect, reconnect)

    def test_json_evidence_is_private_and_does_not_leave_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.json"
            temporary_modes = []
            real_replace = os.replace

            def record_mode_and_replace(source: Path, destination: Path) -> None:
                temporary_modes.append(Path(source).stat().st_mode & 0o777)
                real_replace(source, destination)

            with mock.patch(
                "scripts.phase3.android_internet_acceptance.os.replace",
                side_effect=record_mode_and_replace,
            ):
                _write_json(evidence, {"result": "passed"})
            self.assertEqual(temporary_modes, [0o600])
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(evidence.parent.glob(f".{evidence.name}.*.tmp")), [])

    def test_coordinates_parse_without_shell_interpolation(self) -> None:
        self.assertEqual(coordinate_pair("540,1600"), (540, 1600))
        self.assertEqual(swipe("1,2,3,4,250"), (1, 2, 3, 4, 250))

    def test_invalid_coordinates_are_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            coordinate_pair("-1,2")
        with self.assertRaises(argparse.ArgumentTypeError):
            swipe("1,2,3")

    def test_required_observation_fails_closed(self) -> None:
        with self.assertRaises(AcceptanceError):
            _require_pattern("stream", r"decoded frame", "application merely launched")
        _require_pattern("stream", r"decoded frame", "decoded frame 42")

    def test_main_writes_private_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "failure.json"
            with (
                mock.patch(
                    "scripts.phase3.android_internet_acceptance.run",
                    side_effect=AcceptanceError(
                        "APK does not exist: /Users/private-account/missing.apk; "
                        "owner-token device.example:5555"
                    ),
                ),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                result = main(
                    [
                        "--apk",
                        "/Users/private-account/missing.apk",
                        "--serial",
                        "device.example:5555",
                        "--lease-token",
                        "owner-token",
                        "--streaming-pattern",
                        "frame",
                        "--host-input-evidence",
                        str(Path(directory) / "host.log"),
                        "--host-input-pattern",
                        "ack",
                        "--reconnect-pattern",
                        "reconnect",
                        "--session-epoch-pattern",
                        r"session_epoch=(?P<epoch>\d+)",
                        "--evidence",
                        str(evidence),
                    ]
                )
            self.assertEqual(result, 1)
            report = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(report["result"], "failed")
            rendered = evidence.read_text(encoding="utf-8")
            self.assertNotIn("owner-token", rendered)
            self.assertNotIn("device.example:5555", rendered)
            self.assertNotIn("private-account", rendered)


if __name__ == "__main__":
    unittest.main()
