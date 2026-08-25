from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.coturn_disconnect_executor import (  # noqa: E402
    AUDIT_SCHEMA,
    STATE_SCHEMA,
    DisconnectError,
    disconnect_allocation,
    validate_state,
)
from scripts.phase3.coturn_reconcile import Settings, disconnect_required_allocations  # noqa: E402


class CoturnDisconnectExecutorTests(unittest.TestCase):
    def state(self) -> dict[str, object]:
        return {
            "schema": STATE_SCHEMA,
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

    def write_state(self, root: Path) -> Path:
        path = root / "active-allocations.json"
        path.write_text(json.dumps(self.state()), encoding="utf-8")
        return path

    def test_disconnect_marks_active_allocation_inactive_and_audits_boundary(self) -> None:
        updated, audit = disconnect_allocation(self.state(), "turn-prod-1", "allocation-1", "revoked")

        self.assertEqual(updated["allocations"][0]["active"], False)  # type: ignore[index]
        self.assertEqual(updated["allocations"][0]["disconnect_reason"], "revoked")  # type: ignore[index]
        self.assertEqual(audit["schema"], AUDIT_SCHEMA)
        self.assertEqual(audit["active_allocation_removed"], True)
        self.assertEqual(
            audit["release_gate_boundary"],
            "local_state_disconnect_contract_not_public_internet_or_live_coturn_evidence",
        )

    def test_disconnect_is_idempotent_for_already_disconnected_allocation(self) -> None:
        state, _audit = disconnect_allocation(self.state(), "turn-prod-1", "allocation-1", "revoked")
        updated, audit = disconnect_allocation(state, "turn-prod-1", "allocation-1", "revoked")

        self.assertEqual(updated["allocations"][0]["active"], False)  # type: ignore[index]
        self.assertEqual(audit["already_disconnected"], True)

    def test_already_disconnected_allocation_requires_same_reason(self) -> None:
        state, _audit = disconnect_allocation(self.state(), "turn-prod-1", "allocation-1", "revoked")

        with self.assertRaisesRegex(DisconnectError, "different reason"):
            disconnect_allocation(state, "turn-prod-1", "allocation-1", "conflict")

    def test_unknown_or_wrong_source_allocation_fails_closed(self) -> None:
        with self.assertRaisesRegex(DisconnectError, "source_id"):
            disconnect_allocation(self.state(), "other-source", "allocation-1", "revoked")
        with self.assertRaisesRegex(DisconnectError, "not present"):
            disconnect_allocation(self.state(), "turn-prod-1", "missing-allocation", "revoked")

    def test_state_validation_rejects_ambiguous_inactive_allocation(self) -> None:
        state = self.state()
        state["allocations"][0]["active"] = False  # type: ignore[index]

        with self.assertRaisesRegex(DisconnectError, "disconnect metadata"):
            validate_state(state)

    def test_cli_consumes_reconcile_environment_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_path = self.write_state(root)
            audit_log = root / "audit.jsonl"
            env = os.environ.copy()
            env.update(
                {
                    "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
                    "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation-1",
                    "VIBE_COTURN_DISCONNECT_REASON": "revoked",
                }
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3/coturn_disconnect_executor.py"),
                    "--state",
                    str(state_path),
                    "--audit-log",
                    str(audit_log),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["allocations"][0]["active"], False)
            audit = json.loads(audit_log.read_text(encoding="utf-8").strip())
            self.assertEqual(audit["allocation_id"], "allocation-1")
            self.assertEqual(audit_log.stat().st_mode & 0o777, 0o600)

    def test_reconcile_disconnect_contract_drives_executor_for_revoked_and_quota_closed_allocations(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_path = self.write_state(root)
            audit_log = root / "audit.jsonl"
            settings = Settings(
                authority_url="http://127.0.0.1:1",
                token="x" * 32,
                disconnect_command=(
                    sys.executable,
                    str(ROOT / "scripts/phase3/coturn_disconnect_executor.py"),
                    "--state",
                    str(state_path),
                    "--audit-log",
                    str(audit_log),
                ),
                request_timeout_seconds=5,
            )

            disconnects = disconnect_required_allocations(
                settings,
                "turn-prod-1",
                {
                    "applied": 0,
                    "duplicate": 0,
                    "already_ahead": 0,
                    "missing_allocation_ids": [],
                    "unauthorized_allocation_ids": [],
                    "conflict_allocation_ids": [],
                    "revoked_allocation_ids": ["allocation-1"],
                },
            )

            self.assertEqual(disconnects, [{"allocation_id": "allocation-1", "reason": "revoked"}])
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["allocations"][0]["active"], False)
            self.assertEqual(updated["allocations"][0]["disconnect_reason"], "revoked")
            audit = json.loads(audit_log.read_text(encoding="utf-8").strip())
            self.assertEqual(audit["reason"], "revoked")


if __name__ == "__main__":
    unittest.main()
