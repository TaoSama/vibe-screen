from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import error

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.coturn_reconcile import (  # noqa: E402
    ReconcileError,
    MAX_RESPONSE_BYTES,
    NoRedirectHandler,
    Settings,
    disconnect_required_allocations,
    load_snapshot,
    main,
    run_once,
    run_once_with_retries,
    run_exporter,
    settings_from_args,
    submit_reconcile,
    validate_result,
)


class CoturnReconcileTests(unittest.TestCase):
    def write_snapshot(self, payload: dict[str, object]) -> Path:
        path = Path(self.tempdir.name) / "snapshot.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_snapshot_validation_rejects_log_like_or_ambiguous_input(self) -> None:
        path = self.write_snapshot(
            {
                "source_id": "turn-prod-1",
                "observed_at": "2026-08-20T01:02:03Z",
                "allocations": [
                    {
                        "allocation_id": "allocation-1",
                        "device_id": "device-1",
                        "session_id": "session-1",
                        "sequence": 1,
                        "ingress_bytes": 10,
                        "egress_bytes": 20,
                        "closed": False,
                        "log_line": "human coturn log text is not accepted",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ReconcileError, "unknown fields"):
            load_snapshot(path)

    def test_snapshot_validation_normalizes_expected_authority_payload(self) -> None:
        path = self.write_snapshot(
            {
                "source_id": "turn-prod-1",
                "observed_at": "2026-08-20T01:02:03Z",
                "allocations": [
                    {
                        "allocation_id": "allocation-1",
                        "device_id": "device-1",
                        "session_id": "session-1",
                        "sequence": 3,
                        "ingress_bytes": 10,
                        "egress_bytes": 20,
                    }
                ],
            }
        )
        snapshot = load_snapshot(path)
        self.assertEqual(snapshot["allocations"][0]["closed"], False)

    def test_validate_result_rejects_unknown_fields_and_duplicate_ids(self) -> None:
        good = {
            "applied": 1,
            "duplicate": 0,
            "already_ahead": 0,
            "missing_allocation_ids": [],
            "unauthorized_allocation_ids": ["allocation-2"],
            "conflict_allocation_ids": [],
            "revoked_allocation_ids": [],
        }
        self.assertEqual(validate_result(good)["unauthorized_allocation_ids"], ["allocation-2"])
        ordered = good | {"unauthorized_allocation_ids": ["allocation-2", "allocation-1"]}
        self.assertEqual(
            validate_result(ordered)["unauthorized_allocation_ids"],
            ["allocation-2", "allocation-1"],
        )
        with self.assertRaisesRegex(ReconcileError, "unknown fields"):
            validate_result(good | {"unexpected": True})
        with self.assertRaisesRegex(ReconcileError, "duplicate"):
            validate_result(good | {"unauthorized_allocation_ids": ["a", "a"]})
        with self.assertRaisesRegex(ReconcileError, "multiple result categories"):
            validate_result(
                good
                | {
                    "missing_allocation_ids": ["allocation-2"],
                    "unauthorized_allocation_ids": ["allocation-2"],
                }
            )

    @mock.patch("scripts.phase3.coturn_reconcile.subprocess.run")
    def test_exporter_stdout_is_validated_as_snapshot(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "source_id": "turn-prod-1",
                    "observed_at": "2026-08-20T01:02:03Z",
                    "allocations": [
                        {
                            "allocation_id": "allocation-1",
                            "device_id": "device-1",
                            "session_id": "session-1",
                            "sequence": 1,
                            "ingress_bytes": 10,
                            "egress_bytes": 20,
                        }
                    ],
                }
            ),
            stderr="",
        )
        os.environ["SECRET_SHOULD_NOT_LEAK"] = "private"
        self.addCleanup(lambda: os.environ.pop("SECRET_SHOULD_NOT_LEAK", None))
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            exporter_command=(sys.executable, "exporter.py"),
            request_timeout_seconds=1,
        )
        snapshot = run_exporter(settings)
        self.assertEqual(snapshot["source_id"], "turn-prod-1")
        self.assertEqual(snapshot["allocations"][0]["closed"], False)
        self.assertEqual(run.call_args.kwargs["env"].keys() & {"SECRET_SHOULD_NOT_LEAK"}, set())

    @mock.patch("scripts.phase3.coturn_reconcile.subprocess.run")
    def test_exporter_failure_fails_closed(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(returncode=7, stdout="{}", stderr="secret details")
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            exporter_command=(sys.executable, "exporter.py"),
            request_timeout_seconds=1,
        )
        with self.assertRaisesRegex(ReconcileError, "exporter failed"):
            run_exporter(settings)

    def test_active_source_allocations_require_disconnect_executor(self) -> None:
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=(),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        with self.assertRaisesRegex(ReconcileError, "disconnect-command"):
            disconnect_required_allocations(
                settings,
                "turn-prod-1",
                {
                    "applied": 0,
                    "duplicate": 0,
                    "already_ahead": 0,
                    "missing_allocation_ids": [],
                    "unauthorized_allocation_ids": ["allocation-1"],
                    "conflict_allocation_ids": [],
                    "revoked_allocation_ids": [],
                },
            )

    @mock.patch("scripts.phase3.coturn_reconcile.subprocess.run")
    def test_disconnect_executor_receives_minimal_environment(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(returncode=0)
        os.environ["SECRET_SHOULD_NOT_LEAK"] = "private"
        self.addCleanup(lambda: os.environ.pop("SECRET_SHOULD_NOT_LEAK", None))
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=(sys.executable, "executor.py"),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        report = disconnect_required_allocations(
            settings,
            "turn-prod-1",
            {
                "applied": 0,
                "duplicate": 0,
                "already_ahead": 0,
                "missing_allocation_ids": [],
                "unauthorized_allocation_ids": ["unauthorized-1"],
                "conflict_allocation_ids": ["conflict-1"],
                "revoked_allocation_ids": ["revoked-1"],
            },
        )
        self.assertEqual(
            report,
            [
                {"allocation_id": "unauthorized-1", "reason": "unauthorized"},
                {"allocation_id": "conflict-1", "reason": "conflict"},
                {"allocation_id": "revoked-1", "reason": "revoked"},
            ],
        )
        environments = [call.kwargs["env"] for call in run.mock_calls]
        self.assertEqual(environments[0]["VIBE_COTURN_DISCONNECT_ALLOCATION_ID"], "unauthorized-1")
        self.assertEqual(environments[1]["VIBE_COTURN_DISCONNECT_REASON"], "conflict")
        self.assertEqual(environments[2]["VIBE_COTURN_DISCONNECT_REASON"], "revoked")
        self.assertNotIn("SECRET_SHOULD_NOT_LEAK", environments[0])

    @mock.patch("scripts.phase3.coturn_reconcile.subprocess.run")
    def test_disconnect_executor_failure_fails_closed(self, run: mock.Mock) -> None:
        run.return_value = mock.Mock(returncode=17)
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=(sys.executable, "executor.py"),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        with self.assertRaisesRegex(ReconcileError, "executor failed"):
            disconnect_required_allocations(
                settings,
                "turn-prod-1",
                {
                    "applied": 0,
                    "duplicate": 0,
                    "already_ahead": 0,
                    "missing_allocation_ids": [],
                    "unauthorized_allocation_ids": ["allocation-1"],
                    "conflict_allocation_ids": [],
                    "revoked_allocation_ids": [],
                },
            )

    @mock.patch("scripts.phase3.coturn_reconcile.subprocess.run")
    def test_disconnect_executor_start_failure_fails_closed(self, run: mock.Mock) -> None:
        run.side_effect = OSError("not found")
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=("missing-executor",),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        with self.assertRaisesRegex(ReconcileError, "could not start"):
            disconnect_required_allocations(
                settings,
                "turn-prod-1",
                {
                    "applied": 0,
                    "duplicate": 0,
                    "already_ahead": 0,
                    "missing_allocation_ids": [],
                    "unauthorized_allocation_ids": ["allocation-1"],
                    "conflict_allocation_ids": [],
                    "revoked_allocation_ids": [],
                },
            )

    def test_plaintext_authority_url_must_be_loopback(self) -> None:
        path = self.write_snapshot({"source_id": "turn-prod-1", "observed_at": "2026-08-20T01:02:03Z", "allocations": []})
        with mock.patch.dict(os.environ, {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
            with mock.patch("sys.stderr"):
                exit_code = main(["--authority-url", "http://authority.internal.example.com", "--snapshot", str(path)])
        self.assertEqual(exit_code, 2)

    def test_authority_http_failures_are_rejected(self) -> None:
        settings = Settings(
            authority_url="https://authority.example.com",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=(),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        snapshot = {"source_id": "turn-prod-1", "observed_at": "2026-08-20T01:02:03Z", "allocations": []}

        opener = mock.Mock()
        opener.open.side_effect = error.HTTPError(
            "https://authority.example.com/v1/coturn/reconcile",
            503,
            "service unavailable",
            {},
            None,
        )
        with mock.patch("scripts.phase3.coturn_reconcile.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(ReconcileError, "HTTP 503"):
                submit_reconcile(settings, snapshot)

    def test_authority_malformed_responses_are_rejected(self) -> None:
        settings = Settings(
            authority_url="https://authority.example.com",
            token="x" * 32,
            snapshot=Path("unused"),
            disconnect_command=(),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        snapshot = {"source_id": "turn-prod-1", "observed_at": "2026-08-20T01:02:03Z", "allocations": []}

        cases = [
            (mock.MagicMock(status=202, read=mock.Mock(return_value=b"{}")), "HTTP 202"),
            (mock.MagicMock(status=200, read=mock.Mock(return_value=b"{")), "invalid JSON"),
            (mock.MagicMock(status=200, read=mock.Mock(return_value=b"{}" + b"x" * MAX_RESPONSE_BYTES)), "maximum size"),
        ]
        for response, message in cases:
            response.__enter__ = mock.Mock(return_value=response)
            response.__exit__ = mock.Mock(return_value=None)
            opener = mock.Mock()
            opener.open.return_value = response
            with self.subTest(message=message):
                with mock.patch("scripts.phase3.coturn_reconcile.request.build_opener", return_value=opener):
                    with self.assertRaisesRegex(ReconcileError, message):
                        submit_reconcile(settings, snapshot)

    def test_redirect_handler_rejects_redirects(self) -> None:
        handler = NoRedirectHandler()
        with self.assertRaises(error.HTTPError):
            handler.redirect_request(mock.Mock(), None, 302, "found", {}, "https://other.example.com")

    @mock.patch("scripts.phase3.coturn_reconcile.submit_reconcile")
    def test_missing_ledger_allocations_return_distinct_nonzero_status(self, submit: mock.Mock) -> None:
        path = self.write_snapshot({"source_id": "turn-prod-1", "observed_at": "2026-08-20T01:02:03Z", "allocations": []})
        submit.return_value = {
            "applied": 0,
            "duplicate": 0,
            "already_ahead": 0,
            "missing_allocation_ids": ["allocation-1"],
            "unauthorized_allocation_ids": [],
            "conflict_allocation_ids": [],
            "revoked_allocation_ids": [],
        }
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=path,
            disconnect_command=(),
            interval_seconds=0,
            max_iterations=1,
            request_timeout_seconds=1,
        )
        self.assertEqual(run_once(settings)["status"], "needs_ledger_close")
        with mock.patch.dict(os.environ, {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
            with mock.patch("scripts.phase3.coturn_reconcile.submit_reconcile", submit):
                with mock.patch("sys.stdout"):
                    self.assertEqual(
                        main(["--authority-url", "http://127.0.0.1:1", "--snapshot", str(path)]),
                        4,
                    )

    @mock.patch("scripts.phase3.coturn_reconcile.time.sleep")
    def test_repeated_runs_preserve_missing_allocation_exit(self, sleep: mock.Mock) -> None:
        path = self.write_snapshot({"source_id": "turn-prod-1", "observed_at": "2026-08-20T01:02:03Z", "allocations": []})
        first_result = {
            "applied": 0,
            "duplicate": 0,
            "already_ahead": 0,
            "missing_allocation_ids": ["allocation-1"],
            "unauthorized_allocation_ids": [],
            "conflict_allocation_ids": [],
            "revoked_allocation_ids": [],
        }
        clean_result = first_result | {"missing_allocation_ids": []}
        with mock.patch.dict(os.environ, {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
            with mock.patch(
                "scripts.phase3.coturn_reconcile.submit_reconcile",
                side_effect=[first_result, clean_result],
            ):
                with mock.patch("sys.stdout"):
                    self.assertEqual(
                        main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(path),
                                "--max-iterations",
                                "2",
                                "--interval-seconds",
                                "0",
                            ]
                        ),
                        4,
                    )
        sleep.assert_called_once_with(0.0)

    @mock.patch("scripts.phase3.coturn_reconcile.time.sleep")
    @mock.patch("scripts.phase3.coturn_reconcile.run_once")
    def test_retry_attempts_cover_transient_failures(self, run_once_mock: mock.Mock, sleep: mock.Mock) -> None:
        clean_report = {
            "status": "ok",
            "source_id": "turn-prod-1",
            "observed_at": "2026-08-20T01:02:03Z",
            "reconcile": {
                "applied": 0,
                "duplicate": 0,
                "already_ahead": 0,
                "missing_allocation_ids": [],
                "unauthorized_allocation_ids": [],
                "conflict_allocation_ids": [],
                "revoked_allocation_ids": [],
            },
            "disconnects": [],
        }
        run_once_mock.side_effect = [ReconcileError("temporary authority outage"), clean_report]
        settings = Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            retry_attempts=1,
            retry_backoff_seconds=0.25,
        )
        report = run_once_with_retries(settings)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["retry_attempts"], 1)
        sleep.assert_called_once_with(0.25)

    def test_settings_rejects_ambiguous_token_sources(self) -> None:
        token_file = Path(self.tempdir.name) / "token.txt"
        token_file.write_text("y" * 32, encoding="utf-8")
        parser = mock.Mock(
            authority_url="http://127.0.0.1:1",
            snapshot=Path("unused"),
            exporter_command=(),
            coturn_token_env="VIBE_AUTHORITY_COTURN_TOKEN",
            coturn_token_file=token_file,
            disconnect_command=(),
            interval_seconds=0,
            max_iterations=1,
            retry_attempts=0,
            retry_backoff_seconds=1,
            request_timeout_seconds=1,
        )
        with mock.patch.dict(os.environ, {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
            with self.assertRaisesRegex(ReconcileError, "cannot both be set"):
                settings_from_args(parser)


if __name__ == "__main__":
    unittest.main()
