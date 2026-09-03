from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3 import coturn_reconciliation_loop  # noqa: E402
from scripts.phase3.coturn_disconnect_executor import STATE_SCHEMA as ACTIVE_ALLOCATION_STATE_SCHEMA  # noqa: E402
from scripts.phase3.coturn_reconcile import Settings  # noqa: E402
from scripts.phase3.coturn_reconciliation_loop import STATE_SCHEMA, LoopError, run_loop, update_missing_state  # noqa: E402


class CoturnReconciliationLoopTests(unittest.TestCase):
    def base_report(self, missing: list[str] | None = None, disconnects: list[dict[str, str]] | None = None) -> dict[str, object]:
        return {
            "status": "remediated" if disconnects else ("needs_ledger_close" if missing else "ok"),
            "source_id": "turn-prod-1",
            "observed_at": "2026-08-25T01:02:03Z",
            "reconcile": {
                "applied": 1,
                "duplicate": 0,
                "already_ahead": 0,
                "missing_allocation_ids": missing or [],
                "unauthorized_allocation_ids": [],
                "conflict_allocation_ids": [],
                "revoked_allocation_ids": [],
            },
            "disconnects": disconnects or [],
        }

    def settings(self, iterations: int = 1) -> Settings:
        return Settings(
            authority_url="http://127.0.0.1:1",
            token="x" * 32,
            snapshot=Path("unused.json"),
            interval_seconds=0,
            max_iterations=iterations,
            request_timeout_seconds=1,
        )

    def write_snapshot(self, root: Path) -> Path:
        path = root / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "source_id": "turn-prod-1",
                    "observed_at": "2026-08-25T01:02:03Z",
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
            encoding="utf-8",
        )
        return path

    def write_active_allocation_state(self, root: Path) -> Path:
        path = root / "active-allocations.json"
        path.write_text(
            json.dumps(
                {
                    "schema": ACTIVE_ALLOCATION_STATE_SCHEMA,
                    "source_id": "turn-prod-1",
                    "updated_at": "2026-08-25T01:02:03Z",
                    "allocations": [
                        {
                            "allocation_id": "allocation-1",
                            "device_id": "device-1",
                            "session_id": "session-1",
                            "active": True,
                            "disconnected_at": None,
                            "disconnect_reason": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_stale_allocation_requires_consecutive_observations_before_close_candidate(self) -> None:
        state = {
            "schema": STATE_SCHEMA,
            "source_id": "turn-prod-1",
            "updated_at": "2026-08-25T01:00:00Z",
            "missing_allocations": {},
        }

        state, candidates = update_missing_state(state, self.base_report(missing=["allocation-1"]), missing_threshold=2)
        self.assertEqual(candidates, [])
        self.assertEqual(state["missing_allocations"]["allocation-1"]["consecutive_count"], 1)

        state, candidates = update_missing_state(state, self.base_report(missing=["allocation-1"]), missing_threshold=2)
        self.assertEqual(candidates, ["allocation-1"])
        self.assertEqual(state["missing_allocations"]["allocation-1"]["consecutive_count"], 2)

    def test_missing_allocation_state_clears_when_snapshot_recovers(self) -> None:
        state = {
            "schema": STATE_SCHEMA,
            "source_id": "turn-prod-1",
            "updated_at": "2026-08-25T01:00:00Z",
            "missing_allocations": {
                "allocation-1": {
                    "first_seen_at": "2026-08-25T01:01:00Z",
                    "last_seen_at": "2026-08-25T01:01:00Z",
                    "consecutive_count": 1,
                }
            },
        }

        state, candidates = update_missing_state(state, self.base_report(), missing_threshold=2)

        self.assertEqual(candidates, [])
        self.assertEqual(state["missing_allocations"], {})

    def test_run_loop_persists_records_and_returns_needs_ledger_close_on_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_path = root / "loop-state.json"
            output_jsonl = root / "loop.jsonl"
            with mock.patch(
                "scripts.phase3.coturn_reconcile.run_once_with_retries",
                side_effect=[self.base_report(missing=["allocation-1"]), self.base_report(missing=["allocation-1"])],
            ):
                summary = run_loop(
                    self.settings(iterations=2),
                    state_path=state_path,
                    output_jsonl=output_jsonl,
                    missing_threshold=2,
                )

            self.assertEqual(summary["status"], "needs_ledger_close")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["missing_allocations"]["allocation-1"]["consecutive_count"], 2)
            records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["status"], "watching_missing")
            self.assertEqual(records[1]["ledger_close_candidates"], ["allocation-1"])
            self.assertEqual(records[1]["release_gate_boundary"], "local_bounded_reconciliation_loop_not_public_internet_release_evidence")

    def test_run_loop_records_revoked_or_quota_closed_disconnects_without_release_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_path = root / "loop-state.json"
            disconnects = [{"allocation_id": "allocation-1", "reason": "revoked"}]
            with mock.patch(
                "scripts.phase3.coturn_reconcile.run_once_with_retries",
                return_value=self.base_report(disconnects=disconnects),
            ):
                summary = run_loop(
                    self.settings(iterations=1),
                    state_path=state_path,
                    output_jsonl=None,
                    missing_threshold=2,
                )

            self.assertEqual(summary["status"], "remediated")
            self.assertEqual(summary["last_record"]["disconnects"], disconnects)
            self.assertEqual(
                summary["release_gate_boundary"],
                "local_bounded_reconciliation_loop_not_public_internet_release_evidence",
            )

    def test_loop_state_source_mismatch_fails_closed(self) -> None:
        state = {
            "schema": STATE_SCHEMA,
            "source_id": "turn-prod-2",
            "updated_at": "2026-08-25T01:00:00Z",
            "missing_allocations": {},
        }

        with self.assertRaisesRegex(LoopError, "source_id"):
            update_missing_state(state, self.base_report(missing=["allocation-1"]), missing_threshold=2)

    def test_cli_returns_distinct_status_for_ledger_close_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = root / "snapshot.json"
            state = root / "state.json"
            snapshot.write_text(
                json.dumps({"source_id": "turn-prod-1", "observed_at": "2026-08-25T01:02:03Z", "allocations": []}),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch(
                    "scripts.phase3.coturn_reconcile.submit_reconcile",
                    return_value={
                        "applied": 0,
                        "duplicate": 0,
                        "already_ahead": 0,
                        "missing_allocation_ids": ["allocation-1"],
                        "unauthorized_allocation_ids": [],
                        "conflict_allocation_ids": [],
                        "revoked_allocation_ids": [],
                    },
                ):
                    with mock.patch("sys.stdout"):
                        code = coturn_reconciliation_loop.main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(snapshot),
                                "--state",
                                str(state),
                                "--missing-threshold",
                                "1",
                            ]
                        )

        self.assertEqual(code, 4)

    def test_cli_honors_bounded_max_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = root / "snapshot.json"
            state = root / "state.json"
            snapshot.write_text(
                json.dumps({"source_id": "turn-prod-1", "observed_at": "2026-08-25T01:02:03Z", "allocations": []}),
                encoding="utf-8",
            )
            submit = mock.Mock(
                side_effect=[
                    {
                        "applied": 0,
                        "duplicate": 0,
                        "already_ahead": 0,
                        "missing_allocation_ids": ["allocation-1"],
                        "unauthorized_allocation_ids": [],
                        "conflict_allocation_ids": [],
                        "revoked_allocation_ids": [],
                    },
                    {
                        "applied": 0,
                        "duplicate": 0,
                        "already_ahead": 0,
                        "missing_allocation_ids": ["allocation-1"],
                        "unauthorized_allocation_ids": [],
                        "conflict_allocation_ids": [],
                        "revoked_allocation_ids": [],
                    },
                ]
            )
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch("scripts.phase3.coturn_reconcile.submit_reconcile", submit):
                    with mock.patch("sys.stdout"):
                        code = coturn_reconciliation_loop.main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(snapshot),
                                "--state",
                                str(state),
                                "--missing-threshold",
                                "2",
                                "--max-iterations",
                                "2",
                            ]
                        )

            self.assertEqual(code, 4)
            self.assertEqual(submit.call_count, 2)
            state_data = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(state_data["missing_allocations"]["allocation-1"]["consecutive_count"], 2)

    def test_cli_disconnect_state_runs_bundled_executor_for_revoked_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            state = root / "loop-state.json"
            active_state = self.write_active_allocation_state(root)
            audit_log = root / "disconnect-audit.jsonl"
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch(
                    "scripts.phase3.coturn_reconcile.submit_reconcile",
                    return_value={
                        "applied": 0,
                        "duplicate": 0,
                        "already_ahead": 0,
                        "missing_allocation_ids": [],
                        "unauthorized_allocation_ids": [],
                        "conflict_allocation_ids": [],
                        "revoked_allocation_ids": ["allocation-1"],
                    },
                ):
                    with mock.patch("sys.stdout"):
                        code = coturn_reconciliation_loop.main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(snapshot),
                                "--state",
                                str(state),
                                "--disconnect-state",
                                str(active_state),
                                "--disconnect-audit-log",
                                str(audit_log),
                            ]
                        )

            self.assertEqual(code, 0)
            updated = json.loads(active_state.read_text(encoding="utf-8"))
            self.assertEqual(updated["allocations"][0]["active"], False)
            self.assertEqual(updated["allocations"][0]["disconnect_reason"], "revoked")
            audit = json.loads(audit_log.read_text(encoding="utf-8").strip())
            self.assertEqual(audit["allocation_id"], "allocation-1")
            self.assertEqual(audit["reason"], "revoked")
            loop_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(loop_state["source_id"], "turn-prod-1")

    def test_cli_disconnect_state_requires_audit_log_before_loading_token(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                code = coturn_reconciliation_loop.main(
                    [
                        "--authority-url",
                        "http://127.0.0.1:1",
                        "--snapshot",
                        str(snapshot),
                        "--state",
                        str(root / "loop-state.json"),
                        "--disconnect-state",
                        str(root / "active-allocations.json"),
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("--disconnect-state requires --disconnect-audit-log", stderr.getvalue())
        self.assertNotIn("VIBE_AUTHORITY_COTURN_TOKEN", stderr.getvalue())

    def test_cli_disconnect_audit_log_requires_disconnect_state_before_loading_token(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                code = coturn_reconciliation_loop.main(
                    [
                        "--authority-url",
                        "http://127.0.0.1:1",
                        "--snapshot",
                        str(snapshot),
                        "--state",
                        str(root / "loop-state.json"),
                        "--disconnect-audit-log",
                        str(root / "disconnect-audit.jsonl"),
                    ]
                )

        self.assertEqual(code, 2)
        self.assertIn("--disconnect-audit-log requires --disconnect-state", stderr.getvalue())
        self.assertNotIn("VIBE_AUTHORITY_COTURN_TOKEN", stderr.getvalue())

    def test_cli_disconnect_state_fails_closed_when_bundled_executor_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch.object(coturn_reconciliation_loop, "LOCAL_DISCONNECT_EXECUTOR", root / "missing-executor.py"):
                    with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                        code = coturn_reconciliation_loop.main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(snapshot),
                                "--state",
                                str(root / "loop-state.json"),
                                "--disconnect-state",
                                str(root / "active-allocations.json"),
                                "--disconnect-audit-log",
                                str(root / "disconnect-audit.jsonl"),
                            ]
                        )

        self.assertEqual(code, 2)
        self.assertIn("local disconnect executor is missing", stderr.getvalue())

    def test_cli_disconnect_state_executor_failure_fails_closed_without_loop_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            state = root / "loop-state.json"
            audit_log = root / "disconnect-audit.jsonl"
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch(
                    "scripts.phase3.coturn_reconcile.submit_reconcile",
                    return_value={
                        "applied": 0,
                        "duplicate": 0,
                        "already_ahead": 0,
                        "missing_allocation_ids": [],
                        "unauthorized_allocation_ids": [],
                        "conflict_allocation_ids": [],
                        "revoked_allocation_ids": ["allocation-1"],
                    },
                ):
                    with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                        code = coturn_reconciliation_loop.main(
                            [
                                "--authority-url",
                                "http://127.0.0.1:1",
                                "--snapshot",
                                str(snapshot),
                                "--state",
                                str(state),
                                "--disconnect-state",
                                str(root / "missing-active-allocations.json"),
                                "--disconnect-audit-log",
                                str(audit_log),
                            ]
                        )

        self.assertEqual(code, 2)
        self.assertIn("disconnect executor failed for revoked allocation allocation-1", stderr.getvalue())
        self.assertFalse(state.exists())
        self.assertFalse(audit_log.exists())

    def test_cli_disconnect_state_rejects_custom_disconnect_command(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    code = coturn_reconciliation_loop.main(
                        [
                            "--authority-url",
                            "http://127.0.0.1:1",
                            "--snapshot",
                            str(snapshot),
                            "--state",
                            str(root / "loop-state.json"),
                            "--disconnect-state",
                            str(root / "active-allocations.json"),
                            "--disconnect-audit-log",
                            str(root / "disconnect-audit.jsonl"),
                            "--disconnect-command",
                            sys.executable,
                            "custom-executor.py",
                        ]
                    )

        self.assertEqual(code, 2)
        self.assertIn("cannot be combined", stderr.getvalue())

    def test_settings_preserve_custom_disconnect_command_without_disconnect_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            snapshot = self.write_snapshot(root)
            args = coturn_reconciliation_loop.build_parser().parse_args(
                [
                    "--authority-url",
                    "http://127.0.0.1:1",
                    "--snapshot",
                    str(snapshot),
                    "--state",
                    str(root / "loop-state.json"),
                    "--disconnect-command",
                    sys.executable,
                    "custom-executor.py",
                ]
            )
            with mock.patch.dict("os.environ", {"VIBE_AUTHORITY_COTURN_TOKEN": "x" * 32}, clear=True):
                settings = coturn_reconciliation_loop.settings_from_args(args)

        self.assertEqual(settings.disconnect_command, (sys.executable, "custom-executor.py"))


if __name__ == "__main__":
    unittest.main()
