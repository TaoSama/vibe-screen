from __future__ import annotations

import errno
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase3"))

import android_real_qr_pairing_acceptance as runner


class RealQrPairingAcceptanceTests(unittest.TestCase):
    def test_argument_parsing_requires_serial(self) -> None:
        parser = runner.build_parser()
        with mock.patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--evidence", "/tmp/evidence.json"])

    def test_argument_parsing_defaults(self) -> None:
        parser = runner.build_parser()
        args = parser.parse_args(["--serial", "mock-serial-1", "--evidence", "/tmp/evidence.json"])
        self.assertEqual(args.serial, "mock-serial-1")
        self.assertEqual(args.package, "dev.telemachus.display")
        self.assertEqual(args.test_package, "dev.telemachus.display.test")
        self.assertEqual(args.test_runner, "dev.telemachus.display.test/androidx.test.runner.AndroidJUnitRunner")
        self.assertEqual(args.test_class, "dev.telemachus.display.RealQrInternetPairingInstrumentedTest")
        self.assertEqual(args.timeout, 120.0)
        self.assertEqual(args.poll_interval, 0.5)
        self.assertEqual(args.offer_file, "internet_pairing_offer.txt")
        self.assertEqual(args.marker_file, "qr_scan_marker.json")
        self.assertEqual(args.presenter_ready_file, "qr_scan_marker_request.txt")
        self.assertEqual(args.device_lock, runner.DEVICE_LOCK_PATH)
        self.assertFalse(args.skip_presenter)
        self.assertFalse(args.allow_blocked)

    def test_argument_parsing_custom_values(self) -> None:
        parser = runner.build_parser()
        args = parser.parse_args([
            "--serial", "test-serial-42",
            "--adb", "/usr/local/bin/adb",
            "--timeout", "45.5",
            "--poll-interval", "0.2",
            "--presenter-ready-file", "custom_ready.sentinel",
            "--device-lock", "/tmp/custom-device.lock",
            "--skip-presenter",
            "--allow-blocked",
            "--evidence", "/tmp/out.json",
        ])
        self.assertEqual(args.serial, "test-serial-42")
        self.assertEqual(args.adb, "/usr/local/bin/adb")
        self.assertEqual(args.timeout, 45.5)
        self.assertEqual(args.poll_interval, 0.2)
        self.assertEqual(args.presenter_ready_file, "custom_ready.sentinel")
        self.assertEqual(args.device_lock, Path("/tmp/custom-device.lock"))
        self.assertTrue(args.skip_presenter)
        self.assertTrue(args.allow_blocked)

    def test_redact_text_sanitizes_sensitive_data(self) -> None:
        sample_serial = "nubia-pacific-test-serial"
        raw = (
            f"Device serial {sample_serial} running at /Users/tester/vibe-screen/worktree\n"
            "Connecting to 192.168.1.100:54321\n"
            "Pairing offer: vibescreen://pair?v=1&secret=secrettoken123\n"
        )
        redacted = runner.redact_text(raw, sample_serial)
        self.assertNotIn(sample_serial, redacted)
        self.assertNotIn("/Users/tester", redacted)
        self.assertNotIn("192.168.1.100", redacted)
        self.assertNotIn("secrettoken123", redacted)
        self.assertIn("<ANDROID_SERIAL>", redacted)
        self.assertIn("<path>", redacted)
        self.assertIn("<ipv4>", redacted)
        self.assertIn("<URL>", redacted)

    def test_sanitize_and_summarize_log(self) -> None:
        sample_serial = "device-xyz"
        lines = [f"Line {i} with /Users/test/dir and {sample_serial}" for i in range(25)]
        raw_log = "\n".join(lines)
        log_sha, summary = runner.sanitize_and_summarize_log(raw_log, sample_serial, max_chars=200)
        self.assertEqual(log_sha, runner.sha256_hex(raw_log))
        self.assertNotIn(sample_serial, summary)
        self.assertNotIn("/Users/test", summary)
        self.assertIn("<path>", summary)
        self.assertIn("<ANDROID_SERIAL>", summary)
        self.assertLessEqual(len(summary), 200)

    def test_write_atomic_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "evidence.json"
            content = b'{"test": true}\n'
            runner.write_atomic_0600(target, content)
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), content)
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_device_lock_acquire_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "test.lock"
            lock = runner.DeviceLock(lock_path=lock_path, serial="test-dev")
            self.assertFalse(lock_path.exists())

            with lock:
                self.assertTrue(lock_path.is_file())
                mode = stat.S_IMODE(lock_path.stat().st_mode)
                self.assertEqual(mode, 0o600)
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                self.assertEqual(data["serial"], "test-dev")
                self.assertEqual(data["pid"], os.getpid())

            self.assertFalse(lock_path.exists())

    def test_device_lock_fails_when_already_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "test.lock"
            lock_path.write_text('{"pid": 9999}\n', encoding="utf-8")

            lock = runner.DeviceLock(lock_path=lock_path, serial="test-dev")
            with self.assertRaises(runner.AcceptanceError) as ctx:
                lock.acquire()
            self.assertIn("already exists", str(ctx.exception))

    def test_check_no_host_server_listener_ipv4(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_socket_cls.return_value.__enter__.return_value = mock_sock
            # IPv4 connect succeeds -> active listener found
            mock_sock.connect.return_value = None
            self.assertFalse(runner.check_no_host_server(54321))

    def test_check_no_host_server_listener_ipv6(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            ipv4_sock = mock.MagicMock()
            ipv6_sock = mock.MagicMock()

            def socket_factory(family, *args, **kwargs):
                if family == socket.AF_INET:
                    ipv4_sock.connect.side_effect = ConnectionRefusedError()
                    mock_ctx = mock.MagicMock()
                    mock_ctx.__enter__.return_value = ipv4_sock
                    return mock_ctx
                else:
                    ipv6_sock.connect.return_value = None  # IPv6 connects!
                    mock_ctx = mock.MagicMock()
                    mock_ctx.__enter__.return_value = ipv6_sock
                    return mock_ctx

            mock_socket_cls.side_effect = socket_factory
            self.assertFalse(runner.check_no_host_server(54321))

    def test_check_no_host_server_lsof_detected(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError()
            mock_socket_cls.return_value.__enter__.return_value = mock_sock

            def mock_runner(cmd, *args, **kwargs):
                if "lsof" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nMacHost 123 user 3u IPv4 ... LISTEN\n", "")
                return subprocess.CompletedProcess(cmd, 1, "", "")

            self.assertFalse(runner.check_no_host_server(54321, command_runner=mock_runner))

    def test_check_no_host_server_timeout_fails_closed(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            # Timeout is an OSError with errno != ECONNREFUSED
            mock_sock.connect.side_effect = socket.timeout("timed out")
            mock_socket_cls.return_value.__enter__.return_value = mock_sock

            self.assertFalse(runner.check_no_host_server(54321))

    def test_check_no_host_server_os_error_fails_closed(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = OSError(errno.EPERM, "Operation not permitted")
            mock_socket_cls.return_value.__enter__.return_value = mock_sock
            self.assertFalse(runner.check_no_host_server(54321))

    def test_check_no_host_server_success_both_refused(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError()
            mock_socket_cls.return_value.__enter__.return_value = mock_sock

            def mock_runner(cmd, *args, **kwargs):
                return subprocess.CompletedProcess(cmd, 1, "", "")

            self.assertTrue(runner.check_no_host_server(54321, command_runner=mock_runner))

    def test_check_device_state(self) -> None:
        def runner_device_ok(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "device\n", "")

        def runner_device_offline(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "offline\n", "")

        def runner_device_err(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "error: closed")

        runner.check_device_state("ser1", command_runner=runner_device_ok)

        with self.assertRaises(runner.AcceptanceError) as ctx:
            runner.check_device_state("ser1", command_runner=runner_device_offline)
        self.assertIn("not 'device'", str(ctx.exception))

        with self.assertRaises(runner.AcceptanceError) as ctx:
            runner.check_device_state("ser1", command_runner=runner_device_err)
        self.assertIn("get-state failed", str(ctx.exception))

    def test_check_no_adb_reverse(self) -> None:
        def runner_clean(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "(reverse) tcp:8088 tcp:8088\n", "")

        def runner_has_reverse(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "(reverse) tcp:54321 tcp:54321\n", "")

        def runner_fail(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "device not found")

        self.assertTrue(runner.check_no_adb_reverse("ser1", command_runner=runner_clean))
        self.assertFalse(runner.check_no_adb_reverse("ser1", command_runner=runner_has_reverse))
        with self.assertRaises(runner.AcceptanceError):
            runner.check_no_adb_reverse("ser1", command_runner=runner_fail)

        with self.assertRaises(runner.AcceptanceError):
            runner.check_no_adb_reverse("", command_runner=runner_clean)

    def test_get_device_identity_success_and_negative_cases(self) -> None:
        def runner_ok(cmd, *args, **kwargs):
            joined = " ".join(cmd)
            if "get-state" in joined:
                return subprocess.CompletedProcess(cmd, 0, "device\n", "")
            if "ro.product.manufacturer" in joined:
                return subprocess.CompletedProcess(cmd, 0, "nubia\n", "")
            if "ro.product.model" in joined:
                return subprocess.CompletedProcess(cmd, 0, "P0110\n", "")
            if "ro.product.device" in joined:
                return subprocess.CompletedProcess(cmd, 0, "pacific\n", "")
            if "ro.build.version.release" in joined:
                return subprocess.CompletedProcess(cmd, 0, "16\n", "")
            if "ro.build.version.sdk" in joined:
                return subprocess.CompletedProcess(cmd, 0, "36\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ident = runner.get_device_identity("ser1", command_runner=runner_ok)
        self.assertEqual(ident.manufacturer, "nubia")
        self.assertEqual(ident.model, "P0110")
        self.assertEqual(ident.device, "pacific")
        self.assertEqual(ident.android_release, "16")
        self.assertEqual(ident.sdk, 36)

        # Negative case: missing serial
        with self.assertRaises(runner.AcceptanceError):
            runner.get_device_identity("", command_runner=runner_ok)

        # Negative case: empty manufacturer
        def runner_empty_mfg(cmd, *args, **kwargs):
            if "ro.product.manufacturer" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 0, "\n", "")
            return runner_ok(cmd, *args, **kwargs)

        with self.assertRaises(runner.AcceptanceError) as ctx:
            runner.get_device_identity("ser1", command_runner=runner_empty_mfg)
        self.assertIn("manufacturer property", str(ctx.exception))

        # Negative case: invalid SDK <= 0
        def runner_invalid_sdk(cmd, *args, **kwargs):
            if "ro.build.version.sdk" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 0, "0\n", "")
            return runner_ok(cmd, *args, **kwargs)

        with self.assertRaises(runner.AcceptanceError) as ctx:
            runner.get_device_identity("ser1", command_runner=runner_invalid_sdk)
        self.assertIn("SDK version", str(ctx.exception))

    def test_run_as_write_and_read_and_delete(self) -> None:
        history: list[tuple[list[str], str | None]] = []

        def mock_runner(cmd, input=None, *args, **kwargs):
            history.append((cmd, input))
            joined = " ".join(cmd)
            if "if [ -f files/test.txt" in joined:
                return subprocess.CompletedProcess(cmd, 0, "file-content\n", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        # Write
        runner.run_as_write_file("dev.pkg", "test.txt", "file-content", "ser1", command_runner=mock_runner)
        self.assertEqual(history[0][1], "file-content")
        self.assertIn("tee files/test.txt", " ".join(history[0][0]))

        # Read
        content = runner.run_as_read_file("dev.pkg", "test.txt", "ser1", command_runner=mock_runner)
        self.assertEqual(content, "file-content")

        # Read absent file (device script exit code 3) returns None
        def mock_runner_absent(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 3, "", "")

        self.assertIsNone(runner.run_as_read_file("dev.pkg", "test.txt", "ser1", command_runner=mock_runner_absent))

        # Read error (exit code 1) raises AcceptanceError
        def mock_runner_error(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "permission denied")

        with self.assertRaises(runner.AcceptanceError):
            runner.run_as_read_file("dev.pkg", "test.txt", "ser1", command_runner=mock_runner_error)

        # Delete
        runner.run_as_delete_file("dev.pkg", "test.txt", "ser1", command_runner=mock_runner)
        self.assertIn("rm -f files/test.txt", " ".join(history[-1][0]))

    def test_run_as_write_file_failure_raises(self) -> None:
        def runner_fail(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "permission denied")

        with self.assertRaises(runner.AcceptanceError) as ctx:
            runner.run_as_write_file("pkg", "f.txt", "data", "ser1", command_runner=runner_fail)
        self.assertIn("Failed to write app-private file", str(ctx.exception))

    def test_presenter_controller_start_success(self) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.return_value = "QR_PRESENTER_READY\n"
        mock_proc.stdin = mock.MagicMock()

        controller = runner.PresenterController(
            script_path=Path("/fake/qr_presenter.swift"),
            popen_factory=lambda *a, **kw: mock_proc,
            startup_timeout=5.0,
        )
        controller.start("vibescreen://test-offer", timeout_seconds=45.0)

        mock_proc.stdin.write.assert_called_once()
        sent_config = json.loads(mock_proc.stdin.write.call_args[0][0])
        self.assertEqual(sent_config["payload"], "vibescreen://test-offer")
        self.assertEqual(sent_config["timeout_seconds"], 45.0)
        self.assertEqual(sent_config["scale"], 16.0)

        controller.stop()
        mock_proc.terminate.assert_called_once()

    def test_presenter_controller_early_crash(self) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = 2
        mock_proc.returncode = 2
        mock_proc.stdout.readline.return_value = ""
        mock_proc.stderr.read.return_value = "error: qr_presenter accepts no CLI args\n"

        controller = runner.PresenterController(
            script_path=Path("/fake/qr_presenter.swift"),
            popen_factory=lambda *a, **kw: mock_proc,
            startup_timeout=5.0,
        )
        with self.assertRaises(runner.AcceptanceError) as ctx:
            controller.start("vibescreen://test")
        self.assertIn("crashed or exited prematurely (code 2)", str(ctx.exception))
        self.assertIn("error: qr_presenter accepts no CLI args", str(ctx.exception))

    def test_presenter_controller_timeout(self) -> None:
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdout.readline.return_value = "diagnostic line\n"
        mock_proc.stderr.read.return_value = ""

        controller = runner.PresenterController(
            script_path=Path("/fake/qr_presenter.swift"),
            popen_factory=lambda *a, **kw: mock_proc,
            startup_timeout=0.05,
        )
        with self.assertRaises(runner.AcceptanceError) as ctx:
            controller.start("vibescreen://test")
        self.assertIn("failed to signal QR_PRESENTER_READY", str(ctx.exception))

    def test_presenter_controller_stop_behavior(self) -> None:
        controller = runner.PresenterController(script_path=Path("/fake/presenter.swift"))
        controller.stop()
        self.assertIsNone(controller.proc)

        mock_proc = mock.MagicMock()
        controller.proc = mock_proc
        controller.stop()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(controller.proc)

        mock_proc_hang = mock.MagicMock()
        mock_proc_hang.terminate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=3.0)
        controller.proc = mock_proc_hang
        controller.stop()
        mock_proc_hang.kill.assert_called_once()
        self.assertIsNone(controller.proc)

    def test_validate_qr_marker(self) -> None:
        sample_sha = runner.sha256_hex("vibescreen://test-offer")
        valid_marker = json.dumps({
            "schema": runner.MARKER_SCHEMA,
            "source": "CameraX ImageAnalysis",
            "decoder": "ZXing QRCodeReader",
            "payload_sha256": sample_sha,
            "payload_bytes": 22,
            "frame_width": 1920,
            "frame_height": 1080,
            "row_stride": 1920,
            "pixel_stride": 1,
            "rotation_degrees": 90,
            "luma_width": 1080,
            "luma_height": 1920,
            "decoded_at_uptime_ms": 12345,
        })

        parsed = runner.validate_qr_marker(valid_marker, sample_sha)
        self.assertEqual(parsed["schema"], runner.MARKER_SCHEMA)
        self.assertEqual(parsed["payload_sha256"], sample_sha)
        self.assertEqual(parsed["frame_width"], 1920)

        # Mismatched SHA
        with self.assertRaises(runner.AcceptanceError):
            runner.validate_qr_marker(valid_marker, "wrongsha")

        # Wrong schema
        bad_schema = json.dumps({
            "schema": "wrong-schema",
            "source": "CameraX ImageAnalysis",
            "decoder": "ZXing QRCodeReader",
            "payload_sha256": sample_sha,
        })
        with self.assertRaises(runner.AcceptanceError):
            runner.validate_qr_marker(bad_schema, sample_sha)

        # Invalid frame dimensions
        invalid_dim = json.dumps({
            "schema": runner.MARKER_SCHEMA,
            "source": "CameraX ImageAnalysis",
            "decoder": "ZXing QRCodeReader",
            "payload_sha256": sample_sha,
            "frame_width": 0,
            "frame_height": 1080,
            "luma_width": 1080,
            "luma_height": 1920,
        })
        with self.assertRaises(runner.AcceptanceError):
            runner.validate_qr_marker(invalid_dim, sample_sha)

    def test_run_acceptance_mock_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "vibe-screen-device-android.lock"
            sample_offer = "vibescreen://pair?v=1&token=sampletesttoken"
            sample_sha = runner.sha256_hex(sample_offer)
            sample_marker = json.dumps({
                "schema": runner.MARKER_SCHEMA,
                "source": "CameraX ImageAnalysis",
                "decoder": "ZXing QRCodeReader",
                "payload_sha256": sample_sha,
                "payload_bytes": len(sample_offer),
                "frame_width": 1920,
                "frame_height": 1080,
                "row_stride": 1920,
                "pixel_stride": 1,
                "rotation_degrees": 90,
                "luma_width": 1080,
                "luma_height": 1920,
                "decoded_at_uptime_ms": 1000,
            })

            command_history: list[list[str]] = []
            device_files: dict[str, str] = {}

            def mock_command_runner(cmd, input=None, *args, **kwargs):
                command_history.append(cmd)
                joined = " ".join(cmd)
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "getprop" in joined:
                    if "ro.product.manufacturer" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "nubia\n", "")
                    if "ro.product.model" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "P0110\n", "")
                    if "ro.product.device" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "pacific\n", "")
                    if "ro.build.version.release" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "16\n", "")
                    if "ro.build.version.sdk" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "sample\n", "")
                if "reverse --list" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "rm -f" in joined:
                    for f in list(device_files.keys()):
                        if f"files/{f}" in joined:
                            device_files.pop(f, None)
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "tee files/" in joined:
                    for f in [runner.OFFER_FILENAME, runner.MARKER_FILENAME, runner.DEFAULT_PRESENTER_READY_FILENAME]:
                        if f"files/{f}" in joined:
                            device_files[f] = input or ""
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "if [ -f files/" in joined:
                    for f, val in device_files.items():
                        if f"files/{f}" in joined:
                            return subprocess.CompletedProcess(cmd, 0, val + "\n", "")
                    return subprocess.CompletedProcess(cmd, 3, "", "")
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None
            mock_inst_proc.returncode = 0
            mock_inst_proc.communicate.return_value = (runner.EXPECTED_PASS_MARKER + "\n", "")

            def mock_popen(cmd, *args, **kwargs):
                joined = " ".join(cmd)
                if "am instrument" in joined:
                    device_files[runner.OFFER_FILENAME] = sample_offer
                    device_files[runner.MARKER_FILENAME] = sample_marker
                    stdout_arg = kwargs.get("stdout")
                    if stdout_arg and hasattr(stdout_arg, "write"):
                        stdout_arg.write(runner.EXPECTED_PASS_MARKER + "\n")
                        stdout_arg.flush()
                    return mock_inst_proc
                # Presenter proc
                p = mock.MagicMock()
                p.poll.return_value = None
                p.stdout.readline.return_value = "QR_PRESENTER_READY\n"
                p.stdin = mock.MagicMock()
                return p

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", str(evidence_file),
                "--timeout", "10.0",
                "--poll-interval", "0.01",
            ])

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                report = runner.run_acceptance(args, command_runner=mock_command_runner, popen_factory=mock_popen)

            self.assertEqual(report["schema"], runner.SCHEMA)
            self.assertEqual(report["result"], "pass")
            self.assertEqual(report["device"]["manufacturer"], "nubia")
            self.assertEqual(report["device"]["model"], "P0110")
            self.assertEqual(report["device"]["device"], "pacific")
            self.assertEqual(report["device"]["sdk"], 36)
            self.assertEqual(report["assertions"]["real_camerax_zxing"], "pass")
            self.assertEqual(report["assertions"]["no_host_server"], "pass")
            self.assertEqual(report["assertions"]["no_adb_reverse"], "pass")
            self.assertEqual(report["assertions"]["device_file_cleanup"], "pass")
            self.assertEqual(report["marker"]["payload_sha256"], sample_sha)

            self.assertFalse(lock_file.exists())

            force_stop_cmds = [cmd for cmd in command_history if "am force-stop" in " ".join(cmd)]
            self.assertGreaterEqual(len(force_stop_cmds), 2)

    def test_run_acceptance_fails_when_host_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_file = Path(temp_dir) / "test.lock"
            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", "/tmp/evidence.json",
            ])
            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.return_value = None
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args)
                self.assertIn("Host server is running on port 54321", str(ctx.exception))
            self.assertFalse(lock_file.exists())

    def test_run_acceptance_fails_when_adb_reverse_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_file = Path(temp_dir) / "test.lock"
            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", "/tmp/evidence.json",
            ])

            def runner_with_reverse(cmd, *args, **kwargs):
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "reverse" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "tcp:54321 tcp:54321\n", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args, command_runner=runner_with_reverse)
                self.assertIn("ADB reverse is configured for port 54321", str(ctx.exception))
            self.assertFalse(lock_file.exists())

    def test_run_acceptance_fails_when_lock_already_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_file = Path(temp_dir) / "test.lock"
            lock_file.write_text('{"pid": 1234}\n', encoding="utf-8")

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", "/tmp/evidence.json",
            ])
            with self.assertRaises(runner.AcceptanceError) as ctx:
                runner.run_acceptance(args)
            self.assertIn("Device coordination lock already exists", str(ctx.exception))

    def test_run_acceptance_fails_when_instrumentation_fails_with_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"
            sample_offer = "vibescreen://pair?v=1&token=sampletesttoken"
            sample_sha = runner.sha256_hex(sample_offer)
            sample_marker = json.dumps({
                "schema": runner.MARKER_SCHEMA,
                "source": "CameraX ImageAnalysis",
                "decoder": "ZXing QRCodeReader",
                "payload_sha256": sample_sha,
                "payload_bytes": len(sample_offer),
                "frame_width": 1920,
                "frame_height": 1080,
                "row_stride": 1920,
                "pixel_stride": 1,
                "rotation_degrees": 90,
                "luma_width": 1080,
                "luma_height": 1920,
                "decoded_at_uptime_ms": 1000,
            })

            def mock_command_runner(cmd, input=None, *args, **kwargs):
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "getprop" in joined:
                    if "ro.build.version.sdk" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "dummy\n", "")
                if "reverse --list" in joined or "rm -f" in joined or "chmod 600" in joined or "tee files/" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "if [ -f files/" in joined:
                    if f"files/{runner.OFFER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_offer + "\n", "")
                    if f"files/{runner.MARKER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_marker + "\n", "")
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None
            mock_inst_proc.returncode = 1

            def mock_popen(cmd, *args, **kwargs):
                if "am instrument" in " ".join(cmd):
                    stdout_arg = kwargs.get("stdout")
                    if stdout_arg and hasattr(stdout_arg, "write"):
                        stdout_arg.write("INSTRUMENTATION_FAILED: runtime exception in test\n")
                        stdout_arg.flush()
                    return mock_inst_proc
                p = mock.MagicMock()
                p.poll.return_value = None
                p.stdout.readline.return_value = "QR_PRESENTER_READY\n"
                p.stdin = mock.MagicMock()
                return p

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", str(evidence_file),
                "--timeout", "10.0",
                "--poll-interval", "0.01",
            ])

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args, command_runner=mock_command_runner, popen_factory=mock_popen)
                self.assertIn("Instrumentation failed with exit code 1", str(ctx.exception))
                self.assertIn("log_sha256=", str(ctx.exception))
                self.assertIn("INSTRUMENTATION_FAILED", str(ctx.exception))

    def test_run_acceptance_fails_when_pass_marker_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"
            sample_offer = "vibescreen://pair?v=1&token=sampletesttoken"
            sample_sha = runner.sha256_hex(sample_offer)
            sample_marker = json.dumps({
                "schema": runner.MARKER_SCHEMA,
                "source": "CameraX ImageAnalysis",
                "decoder": "ZXing QRCodeReader",
                "payload_sha256": sample_sha,
                "payload_bytes": len(sample_offer),
                "frame_width": 1920,
                "frame_height": 1080,
                "row_stride": 1920,
                "pixel_stride": 1,
                "rotation_degrees": 90,
                "luma_width": 1080,
                "luma_height": 1920,
                "decoded_at_uptime_ms": 1000,
            })

            def mock_command_runner(cmd, input=None, *args, **kwargs):
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "getprop" in joined:
                    if "ro.build.version.sdk" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "dummy\n", "")
                if "reverse --list" in joined or "rm -f" in joined or "chmod 600" in joined or "tee files/" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "if [ -f files/" in joined:
                    if f"files/{runner.OFFER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_offer + "\n", "")
                    if f"files/{runner.MARKER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_marker + "\n", "")
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None
            mock_inst_proc.returncode = 0

            def mock_popen(cmd, *args, **kwargs):
                if "am instrument" in " ".join(cmd):
                    stdout_arg = kwargs.get("stdout")
                    if stdout_arg and hasattr(stdout_arg, "write"):
                        stdout_arg.write("OK (1 test) but no pass marker printed\n")
                        stdout_arg.flush()
                    return mock_inst_proc
                p = mock.MagicMock()
                p.poll.return_value = None
                p.stdout.readline.return_value = "QR_PRESENTER_READY\n"
                p.stdin = mock.MagicMock()
                return p

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", str(evidence_file),
                "--timeout", "10.0",
                "--poll-interval", "0.01",
            ])

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args, command_runner=mock_command_runner, popen_factory=mock_popen)
                self.assertIn("missing required pass marker line", str(ctx.exception))
                self.assertIn("log_sha256=", str(ctx.exception))

    def test_run_acceptance_fails_when_postflight_checks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"
            sample_offer = "vibescreen://pair?v=1&token=sampletesttoken"
            sample_sha = runner.sha256_hex(sample_offer)
            sample_marker = json.dumps({
                "schema": runner.MARKER_SCHEMA,
                "source": "CameraX ImageAnalysis",
                "decoder": "ZXing QRCodeReader",
                "payload_sha256": sample_sha,
                "payload_bytes": len(sample_offer),
                "frame_width": 1920,
                "frame_height": 1080,
                "row_stride": 1920,
                "pixel_stride": 1,
                "rotation_degrees": 90,
                "luma_width": 1080,
                "luma_height": 1920,
                "decoded_at_uptime_ms": 1000,
            })

            preflight_done = False

            def mock_command_runner(cmd, input=None, *args, **kwargs):
                nonlocal preflight_done
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "getprop" in joined:
                    if "ro.build.version.sdk" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "dummy\n", "")
                if "reverse --list" in joined:
                    if preflight_done:
                        return subprocess.CompletedProcess(cmd, 0, "(reverse) tcp:54321 tcp:54321\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "rm -f" in joined or "chmod 600" in joined or "tee files/" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "if [ -f files/" in joined:
                    if f"files/{runner.OFFER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_offer + "\n", "")
                    if f"files/{runner.MARKER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_marker + "\n", "")
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None
            mock_inst_proc.returncode = 0

            def mock_popen(cmd, *args, **kwargs):
                nonlocal preflight_done
                if "am instrument" in " ".join(cmd):
                    preflight_done = True
                    stdout_arg = kwargs.get("stdout")
                    if stdout_arg and hasattr(stdout_arg, "write"):
                        stdout_arg.write(runner.EXPECTED_PASS_MARKER + "\n")
                        stdout_arg.flush()
                    return mock_inst_proc
                p = mock.MagicMock()
                p.poll.return_value = None
                p.stdout.readline.return_value = "QR_PRESENTER_READY\n"
                p.stdin = mock.MagicMock()
                return p

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", str(evidence_file),
                "--timeout", "10.0",
                "--poll-interval", "0.01",
            ])

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args, command_runner=mock_command_runner, popen_factory=mock_popen)
                self.assertIn("Postflight detected ADB reverse on port 54321", str(ctx.exception))

    def test_run_acceptance_fails_when_device_files_cleanup_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"
            sample_offer = "vibescreen://pair?v=1&token=sampletesttoken"
            sample_sha = runner.sha256_hex(sample_offer)
            sample_marker = json.dumps({
                "schema": runner.MARKER_SCHEMA,
                "source": "CameraX ImageAnalysis",
                "decoder": "ZXing QRCodeReader",
                "payload_sha256": sample_sha,
                "payload_bytes": len(sample_offer),
                "frame_width": 1920,
                "frame_height": 1080,
                "row_stride": 1920,
                "pixel_stride": 1,
                "rotation_degrees": 90,
                "luma_width": 1080,
                "luma_height": 1920,
                "decoded_at_uptime_ms": 1000,
            })

            def mock_command_runner(cmd, input=None, *args, **kwargs):
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "getprop" in joined:
                    if "ro.build.version.sdk" in joined:
                        return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "dummy\n", "")
                if "reverse --list" in joined or "rm -f" in joined or "chmod 600" in joined or "tee files/" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                if "if [ -f files/" in joined:
                    # Always returns file content, simulating failed rm
                    if f"files/{runner.OFFER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_offer + "\n", "")
                    if f"files/{runner.MARKER_FILENAME}" in joined:
                        return subprocess.CompletedProcess(cmd, 0, sample_marker + "\n", "")
                    return subprocess.CompletedProcess(cmd, 0, "still-present\n", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None
            mock_inst_proc.returncode = 0

            def mock_popen(cmd, *args, **kwargs):
                if "am instrument" in " ".join(cmd):
                    stdout_arg = kwargs.get("stdout")
                    if stdout_arg and hasattr(stdout_arg, "write"):
                        stdout_arg.write(runner.EXPECTED_PASS_MARKER + "\n")
                        stdout_arg.flush()
                    return mock_inst_proc
                p = mock.MagicMock()
                p.poll.return_value = None
                p.stdout.readline.return_value = "QR_PRESENTER_READY\n"
                p.stdin = mock.MagicMock()
                return p

            parser = runner.build_parser()
            args = parser.parse_args([
                "--serial", "mock-serial-1",
                "--device-lock", str(lock_file),
                "--evidence", str(evidence_file),
                "--timeout", "10.0",
                "--poll-interval", "0.01",
            ])

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with self.assertRaises(runner.AcceptanceError) as ctx:
                    runner.run_acceptance(args, command_runner=mock_command_runner, popen_factory=mock_popen)
                self.assertIn("Device files were not cleanly removed after acceptance run", str(ctx.exception))

    def test_main_failure_without_allow_blocked_returns_1(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.return_value = None
                with mock.patch("sys.stderr"):
                    code = runner.main([
                        "--serial", "mock-serial-1",
                        "--device-lock", str(lock_file),
                        "--evidence", str(evidence_file),
                    ])
            self.assertEqual(code, 1)
            data = json.loads(evidence_file.read_text(encoding="utf-8"))
            self.assertEqual(data["result"], "fail")
            self.assertNotIn("device", data)

    def test_main_failure_preserves_started_at_and_device(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            evidence_file = temp_path / "evidence.json"
            lock_file = temp_path / "test.lock"

            def mock_command_runner(cmd, *args, **kwargs):
                joined = " ".join(cmd)
                if "lsof" in joined:
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                if "get-state" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "device\n", "")
                if "ro.product.manufacturer" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "nubia\n", "")
                if "ro.product.model" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "P0110\n", "")
                if "ro.product.device" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "pacific\n", "")
                if "ro.build.version.release" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "16\n", "")
                if "ro.build.version.sdk" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "36\n", "")
                if "reverse" in joined:
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            mock_inst_proc = mock.MagicMock()
            mock_inst_proc.poll.return_value = None

            with mock.patch("socket.socket") as mock_socket_cls:
                mock_socket_cls.return_value.__enter__.return_value.connect.side_effect = ConnectionRefusedError()
                with mock.patch("sys.stderr"):
                    code = runner.main(
                        [
                            "--serial", "mock-serial-1",
                            "--device-lock", str(lock_file),
                            "--evidence", str(evidence_file),
                            "--timeout", "0.05",
                            "--poll-interval", "0.01",
                            "--allow-blocked",
                        ],
                        command_runner=mock_command_runner,
                        popen_factory=lambda *a, **kw: mock_inst_proc,
                    )

            self.assertEqual(code, 0)
            self.assertTrue(evidence_file.is_file())
            data = json.loads(evidence_file.read_text(encoding="utf-8"))
            self.assertEqual(data["result"], "fail")
            self.assertIn("device", data)
            self.assertEqual(data["device"]["manufacturer"], "nubia")
            self.assertEqual(data["device"]["model"], "P0110")
            self.assertIn("started_at_utc", data)
            self.assertIn("finished_at_utc", data)

    def test_qr_presenter_swift_rejects_cli_args(self) -> None:
        presenter_path = Path(__file__).resolve().parents[1] / "phase3" / "qr_presenter.swift"
        self.assertTrue(presenter_path.is_file())
        res = subprocess.run(
            ["swift", str(presenter_path), "--payload", "test"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15.0,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("qr_presenter.swift accepts no command-line arguments", res.stderr)

    def test_qr_presenter_swift_check_mode(self) -> None:
        presenter_path = Path(__file__).resolve().parents[1] / "phase3" / "qr_presenter.swift"
        self.assertTrue(presenter_path.is_file())
        res = subprocess.run(
            ["swift", str(presenter_path)],
            input='{"check": true}\n',
            capture_output=True,
            text=True,
            check=False,
            timeout=15.0,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("CHECK_PASS", res.stdout)

    def test_qr_presenter_swift_empty_stdin_fails(self) -> None:
        presenter_path = Path(__file__).resolve().parents[1] / "phase3" / "qr_presenter.swift"
        self.assertTrue(presenter_path.is_file())
        res = subprocess.run(
            ["swift", str(presenter_path)],
            input="\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=15.0,
        )
        self.assertEqual(res.returncode, 1)


    def test_validate_app_private_filename(self) -> None:
        for valid_name in ["offer.txt", "qr_scan_marker_request.txt", "test_123.json", "A"]:
            runner.validate_app_private_filename(valid_name)

        for invalid_name in ["../test.txt", "/tmp/file", "", "-flag", ".hidden", "a b", "a/b"]:
            with self.assertRaises(runner.AcceptanceError):
                runner.validate_app_private_filename(invalid_name)

    def test_check_no_host_server_lsof_error_exit_code_fails_closed(self) -> None:
        with mock.patch("socket.socket") as mock_socket_cls:
            mock_sock = mock.MagicMock()
            mock_sock.connect.side_effect = ConnectionRefusedError()
            mock_socket_cls.return_value.__enter__.return_value = mock_sock

            def mock_runner_err(cmd, *args, **kwargs):
                return subprocess.CompletedProcess(cmd, 255, "", "lsof error")

            self.assertFalse(runner.check_no_host_server(54321, command_runner=mock_runner_err))

    def test_presenter_ready_sentinel_schema_constant(self) -> None:
        self.assertEqual(runner.PRESENTER_READY_SCHEMA, "dev.vibescreen.phase3-real-qr-presenter-ready/v1")
        self.assertEqual(runner.DEFAULT_PRESENTER_READY_FILENAME, "qr_scan_marker_request.txt")

if __name__ == "__main__":
    unittest.main()
