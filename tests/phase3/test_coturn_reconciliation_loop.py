from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3 import coturn_reconciliation_loop  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
