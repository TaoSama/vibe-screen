from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure
from scripts.phase3_webrtc.privacy import assert_secret_free
from scripts.phase3_webrtc.processes import http_json, run_checked
from scripts.phase3_webrtc.run_local_e2e import main
from scripts.phase3_webrtc.session import metric_value, signaling_config
from scripts.phase3_webrtc.source_artifacts import locate_binaries


def traceback_locals(exception: BaseException) -> list[dict[str, object]]:
    frames = []
    traceback = exception.__traceback__
    while traceback is not None:
        frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


def assert_locals_exclude_private_material(
    test: unittest.TestCase,
    frames: list[dict[str, object]],
    private_values: tuple[str, ...],
) -> None:
    test.assertTrue(frames)
    for frame in frames:
        for value in frame.values():
            rendered = repr(value)
            if isinstance(value, Request):
                rendered += repr(value.headers) + repr(value.data) + value.full_url
            for private_value in private_values:
                test.assertNotIn(private_value, rendered)


class RunnerTests(unittest.TestCase):
    def test_standalone_cli_removes_stale_output_on_build_validation_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_path = repo_root / ".build/evidence.json"
            output_path.parent.mkdir()
            output_path.write_text('{"result":"pass"}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3_webrtc/run_local_e2e.py"),
                    "--repo-root",
                    str(repo_root),
                    "--skip-build",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_path.exists())
            self.assertNotIn('{"result":"pass"}', result.stdout + result.stderr)

    def test_signaling_config_is_loopback_and_bounded(self) -> None:
        config = signaling_config(39001)
        self.assertEqual(config["listen_address"], "127.0.0.1:39001")
        self.assertEqual(config["store_backend"], "memory")
        self.assertLessEqual(config["max_active_sessions"], 8)
        self.assertEqual(
            config["session_ttl_seconds"], config["max_session_ttl_seconds"]
        )

    def test_secret_scan_rejects_exact_value(self) -> None:
        with self.assertRaises(E2EFailure):
            assert_secret_free(
                "prefix generated-secret suffix",
                ["generated-secret"],
                "test",
            )

    def test_secret_scan_accepts_redacted_log(self) -> None:
        assert_secret_free(
            "server started; session accepted",
            ["generated-secret"],
            "test",
        )

    def test_command_failure_redacts_arguments_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            try:
                run_checked(
                    ["/bin/sh", "-c", "printf \"$RUNTIME_TOKEN\"; exit 9"],
                    cwd=Path(directory),
                    timeout=2,
                    environment={"RUNTIME_TOKEN": "generated-secret"},
                    redact_values=("generated-secret",),
                )
            except E2EFailure as exception:
                failure = exception
            else:
                self.fail("run_checked unexpectedly accepted a nonzero command")
        self.assertNotIn("generated-secret", str(failure))
        self.assertIn("<redacted>", str(failure))
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        assert_locals_exclude_private_material(
            self,
            traceback_locals(failure),
            ("generated-secret",),
        )

    @mock.patch("scripts.phase3_webrtc.processes.project_and_validate_public_diagnostic")
    def test_command_projection_failure_reports_only_safe_summary(
        self,
        project: mock.Mock,
    ) -> None:
        project.side_effect = E2EFailure("private path /Users/alice leaked")
        with tempfile.TemporaryDirectory() as directory:
            try:
                run_checked(
                    ["/bin/sh", "-c", "printf unsafe-secret"],
                    cwd=Path(directory),
                    timeout=2,
                    redact_values=("unsafe-secret",),
                )
            except E2EFailure as exception:
                failure = exception
            else:
                self.fail("run_checked unexpectedly accepted a projection failure")

        message = str(failure)
        self.assertIn("stage=stdout_projection", message)
        self.assertIn("exception=E2EFailure", message)
        self.assertIn("output_bytes=13", message)
        self.assertIn(hashlib.sha256(b"unsafe-secret").hexdigest(), message)
        self.assertNotIn("unsafe-secret", message)
        self.assertNotIn("/Users/alice", message)
        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)

    @mock.patch("scripts.phase3_webrtc.processes.subprocess.run")
    def test_timeout_clears_raw_exception_and_traceback_locals(
        self,
        run: mock.Mock,
    ) -> None:
        timeout_error = subprocess.TimeoutExpired(
            ["peer"],
            timeout=5,
            output="partial timeout-secret",
            stderr="stderr timeout-secret",
        )
        run.side_effect = timeout_error

        try:
            run_checked(
                ["peer"],
                cwd=ROOT,
                timeout=5,
                environment={"TOKEN": "environment-secret"},
                redact_values=("timeout-secret", "environment-secret"),
            )
        except E2EFailure as exception:
            failure = exception
        else:
            self.fail("run_checked unexpectedly accepted a timeout")

        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertIsNone(timeout_error.output)
        self.assertIsNone(timeout_error.stdout)
        self.assertIsNone(timeout_error.stderr)
        self.assertIsNone(timeout_error.__traceback__)
        run.reset_mock()
        run.side_effect = None
        assert_locals_exclude_private_material(
            self,
            traceback_locals(failure),
            ("timeout-secret", "environment-secret"),
        )

    def test_metric_parser_requires_exact_metric(self) -> None:
        metrics = "# HELP value\nmetric_total 7\nmetric_other 9\n"
        self.assertEqual(metric_value(metrics, "metric_total"), 7)
        with self.assertRaises(E2EFailure):
            metric_value(metrics, "missing_total")

    def test_locate_binaries_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(E2EFailure):
                locate_binaries(Path(directory))

    def test_http_error_body_is_reduced_to_status_length_and_hash(self) -> None:
        response_error = HTTPError(
            "http://127.0.0.1:39001/v1/sessions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                b'{"token":"runtime-secret","path":"/Users/alice/private",'
                b'"endpoint":"http://10.0.0.8/internal"}'
            ),
        )
        with mock.patch(
            "scripts.phase3_webrtc.processes.request.urlopen",
            side_effect=response_error,
        ):
            try:
                http_json(
                    "POST",
                    "http://127.0.0.1:39001/v1/sessions",
                    token="request-token",
                    body={"request_id": "request-secret"},
                )
            except E2EFailure as exception:
                failure = exception
            else:
                self.fail("http_json unexpectedly accepted an HTTP error")

        message = str(failure)
        self.assertIn("status=401", message)
        self.assertIn("response_bytes=94", message)
        self.assertIn(
            hashlib.sha256(
                b'{"token":"runtime-secret","path":"/Users/alice/private",'
                b'"endpoint":"http://10.0.0.8/internal"}'
            ).hexdigest(),
            message,
        )
        for private_value in (
            "runtime-secret",
            "/Users/alice",
            "10.0.0.8",
            "request-token",
            "request-secret",
        ):
            self.assertNotIn(private_value, message)
        del private_value

        self.assertIsNone(failure.__cause__)
        self.assertIsNone(failure.__context__)
        self.assertIsNone(response_error.fp)
        self.assertIsNone(response_error.__traceback__)
        frames = traceback_locals(failure)
        assert_locals_exclude_private_material(
            self,
            frames,
            (
                "runtime-secret",
                "/Users/alice",
                "10.0.0.8",
                "request-token",
                "request-secret",
            ),
        )
        self.assertFalse(
            any(
                isinstance(value, Request)
                for frame in frames
                for value in frame.values()
            )
        )

    def test_main_projects_unexpected_failure_before_writing_stderr(self) -> None:
        private_path = "/Users/alice/private/build"
        private_endpoint = "http://10.0.0.8/internal"
        private_serial = "device-ABC123"
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_path = repo_root / ".build/evidence.json"
            output_path.parent.mkdir()
            output_path.write_text('{"result":"pass"}\n', encoding="utf-8")
            arguments = SimpleNamespace(
                repo_root=repo_root,
                diagnostics_dir=None,
                output=output_path,
                mode="direct",
                slice="product",
                skip_build=False,
                timeout_seconds=45,
                turnserver=Path("/usr/local/bin/turnserver"),
            )

            def fail_build(*_: object, **__: object) -> None:
                self.assertFalse(output_path.exists())
                raise ValueError(
                    f"path={private_path} endpoint={private_endpoint} "
                    f"serial={private_serial}"
                )

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.parse_arguments",
                    return_value=arguments,
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.build_binaries",
                    side_effect=fail_build,
                ),
                redirect_stderr(stderr),
            ):
                result = main()

            self.assertFalse(output_path.exists())

        output = stderr.getvalue()
        self.assertEqual(result, 1)
        self.assertIn("Phase 3 local WebRTC E2E: FAIL", output)
        for private_value in (
            private_path,
            "10.0.0.8",
            private_serial,
        ):
            self.assertNotIn(private_value, output)

    def test_main_removes_output_created_before_run_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_path = repo_root / ".build/evidence.json"
            output_path.parent.mkdir()
            arguments = SimpleNamespace(
                repo_root=repo_root,
                diagnostics_dir=None,
                output=output_path,
                mode="direct",
                slice="product",
                skip_build=False,
                timeout_seconds=45,
                turnserver=Path("/usr/local/bin/turnserver"),
            )

            def fail_run(*_: object, **__: object) -> None:
                output_path.write_text('{"result":"pass"}\n', encoding="utf-8")
                raise E2EFailure("peer run failed")

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.parse_arguments",
                    return_value=arguments,
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.build_binaries",
                    return_value=(Path("signaling"), Path("mac"), []),
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.run_direct",
                    side_effect=fail_run,
                ),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(), 1)

            self.assertFalse(output_path.exists())

    def test_main_removes_output_created_before_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_path = repo_root / ".build/evidence.json"
            output_path.parent.mkdir()
            arguments = SimpleNamespace(
                repo_root=repo_root,
                diagnostics_dir=None,
                output=output_path,
                mode="direct",
                slice="product",
                skip_build=False,
                timeout_seconds=45,
                turnserver=Path("/usr/local/bin/turnserver"),
            )

            def fail_validation(*_: object, **__: object) -> None:
                output_path.write_text('{"result":"pass"}\n', encoding="utf-8")
                raise E2EFailure("evidence validation failed")

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.parse_arguments",
                    return_value=arguments,
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.build_binaries",
                    return_value=(Path("signaling"), Path("mac"), []),
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.run_direct",
                    return_value={"result": "pass"},
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.write_verified_evidence",
                    side_effect=fail_validation,
                ),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(), 1)

            self.assertFalse(output_path.exists())

    def test_missing_relay_hook_fails_without_writing_blocked_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output_path = repo_root / ".build/relay.json"
            output_path.parent.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.build_binaries",
                    return_value=(Path("signaling"), Path("mac"), []),
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.production_relay_hook_available",
                    return_value=False,
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = main([
                    "--repo-root", str(repo_root),
                    "--mode", "relay",
                    "--slice", "product",
                    "--output", str(output_path),
                ])

            self.assertEqual(result, 1)
            self.assertFalse(output_path.exists())
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                stderr.getvalue(),
                "Phase 3 local WebRTC E2E: FAIL "
                "(production forced-relay ICE is unavailable)\n",
            )

    def test_invalid_timeout_removes_declared_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output = repo_root / ".build/stale.json"
            output.parent.mkdir()
            output.write_text('{"result":"pass"}\n', encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output", str(output),
                    "--timeout-seconds", "0",
                ])

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())

    def test_unknown_argument_removes_declared_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            output = repo_root / ".build/stale.json"
            output.parent.mkdir()
            output.write_text('{"result":"pass"}\n', encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output", str(output),
                    "--unknown-option",
                ])

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())

    def test_invalid_arguments_do_not_delete_output_outside_build_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            sentinel = repo_root / "sensitive.json"
            sentinel.write_text('{"result":"pass"}\n', encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output", str(sentinel),
                    "--timeout-seconds", "0",
                ])

            self.assertEqual(result, 2)
            self.assertEqual(
                sentinel.read_text(encoding="utf-8"),
                '{"result":"pass"}\n',
            )

    def test_invalid_arguments_unlink_output_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            build_root = repo_root / ".build"
            build_root.mkdir()
            target = repo_root / "sensitive.json"
            target.write_text('{"result":"pass"}\n', encoding="utf-8")
            output = build_root / "stale.json"
            output.symlink_to(target)

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output", str(output),
                    "--unknown-option",
                ])

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                '{"result":"pass"}\n',
            )

    def test_malformed_output_argument_does_not_delete_unrelated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            sentinel = repo_root / "sensitive.json"
            sentinel.write_text('{"result":"pass"}\n', encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output",
                ])

            self.assertEqual(result, 2)
            self.assertEqual(
                sentinel.read_text(encoding="utf-8"),
                '{"result":"pass"}\n',
            )

    def test_duplicate_output_arguments_remove_each_legal_stale_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            build_root = repo_root / ".build"
            build_root.mkdir()
            first = build_root / "first.json"
            second = build_root / "second.json"
            sentinel = repo_root / "keep.json"
            for path in (first, second, sentinel):
                path.write_text('{"result":"pass"}\n', encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--output", str(first),
                    "--output", str(second),
                ])

            self.assertEqual(result, 2)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(sentinel.exists())

    def test_argument_failure_removes_only_owned_diagnostic_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_root = Path(temporary)
            diagnostics = repo_root / ".build/direct-logs"
            diagnostics.mkdir(parents=True)
            for name in ("peer.json", "signaling.json", "turnserver.json"):
                (diagnostics / name).write_text('{"result":"pass"}\n', encoding="utf-8")
            unrelated = diagnostics / "keep.txt"
            unrelated.write_text("keep\n", encoding="utf-8")

            with redirect_stderr(io.StringIO()):
                result = main([
                    "--repo-root", str(repo_root),
                    "--diagnostics-dir", str(diagnostics),
                    "--timeout-seconds", "0",
                ])

            self.assertEqual(result, 2)
            for name in ("peer.json", "signaling.json", "turnserver.json"):
                self.assertFalse((diagnostics / name).exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
