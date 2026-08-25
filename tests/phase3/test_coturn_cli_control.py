from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3 import coturn_cli_control as control  # noqa: E402


PS_OUTPUT = """
1) id=013000000000000002, user <1700000000:device-1>:
  realm: relay.example.com
  usage: rp=3, rb=140, sp=2, sb=96
2) id=013000000000000003, user <1700000000:device-2>:
  usage: rp=8, rb=900, sp=5, sb=700
"""


class CoturnCLIControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_registry(self, payload: dict[str, object]) -> Path:
        path = self.root / "registry.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def registry_payload(self) -> dict[str, object]:
        return {
            "source_id": "turn-prod-1",
            "allocations": [
                {
                    "allocation_id": "allocation-1",
                    "device_id": "device-1",
                    "session_id": "session-1",
                    "username": "1700000000:device-1",
                    "coturn_session_id": "013000000000000002",
                }
            ],
        }

    def write_text(self, name: str, contents: str) -> Path:
        path = self.root / name
        path.write_text(contents, encoding="utf-8")
        return path

    def test_parse_coturn_ps_extracts_session_id_username_and_counters(self) -> None:
        sessions = control.parse_coturn_ps(PS_OUTPUT)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].coturn_session_id, "013000000000000002")
        self.assertEqual(sessions[0].username, "1700000000:device-1")
        self.assertEqual(sessions[0].received_bytes, 140)
        self.assertEqual(sessions[0].sent_bytes, 96)

    def test_parse_coturn_ps_rejects_incomplete_or_malformed_sessions(self) -> None:
        with self.assertRaisesRegex(control.CoturnControlError, "missing usage counters"):
            control.parse_coturn_ps("1) id=013000000000000002, user <1700000000:device-1>:\n")

        with self.assertRaisesRegex(control.CoturnControlError, "TURN REST username"):
            control.parse_coturn_ps(
                "1) id=013000000000000002, user <device-1>:\n"
                "  usage: rp=3, rb=140, sp=2, sb=96\n"
            )

    def test_registry_rejects_human_log_fields_and_bad_username(self) -> None:
        payload = self.registry_payload()
        allocation = payload["allocations"][0]  # type: ignore[index]
        allocation["log_line"] = "coturn text"  # type: ignore[index]
        with self.assertRaisesRegex(control.CoturnControlError, "unknown fields"):
            control.load_registry(self.write_registry(payload))

        payload = self.registry_payload()
        allocation = payload["allocations"][0]  # type: ignore[index]
        allocation["username"] = "device-1"  # type: ignore[index]
        with self.assertRaisesRegex(control.CoturnControlError, "TURN REST username"):
            control.load_registry(self.write_registry(payload))

        payload = self.registry_payload()
        allocation = payload["allocations"][0]  # type: ignore[index]
        allocation["username"] = "1700000000:device-2"  # type: ignore[index]
        with self.assertRaisesRegex(control.CoturnControlError, "does not match allocation device_id"):
            control.load_registry(self.write_registry(payload))

    def test_export_snapshot_joins_registry_to_active_coturn_sessions(self) -> None:
        registry = control.load_registry(self.write_registry(self.registry_payload()))
        sessions = control.parse_coturn_ps(PS_OUTPUT)
        snapshot = control.export_snapshot(
            registry,
            sessions,
            datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc),
            42,
        )
        self.assertEqual(
            snapshot,
            {
                "source_id": "turn-prod-1",
                "observed_at": "2026-08-21T01:02:03Z",
                "allocations": [
                    {
                        "allocation_id": "allocation-1",
                        "device_id": "device-1",
                        "session_id": "session-1",
                        "sequence": 42,
                        "ingress_bytes": 140,
                        "egress_bytes": 96,
                        "closed": False,
                    }
                ],
            },
        )

    def test_export_fails_closed_when_registry_username_mapping_is_ambiguous(self) -> None:
        payload = {
            "source_id": "turn-prod-1",
            "allocations": [
                {
                    "allocation_id": "allocation-1",
                    "device_id": "device-1",
                    "session_id": "session-1",
                    "username": "1700000000:device-1",
                },
                {
                    "allocation_id": "allocation-2",
                    "device_id": "device-1",
                    "session_id": "session-2",
                    "username": "1700000000:device-1",
                },
            ],
        }
        registry = control.load_registry(self.write_registry(payload))
        sessions = control.parse_coturn_ps(PS_OUTPUT)
        with self.assertRaisesRegex(control.CoturnControlError, "ambiguous username"):
            control.export_snapshot(
                registry,
                sessions,
                datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc),
                42,
            )

    def test_export_fails_closed_when_bound_and_unbound_allocations_share_username(self) -> None:
        payload = {
            "source_id": "turn-prod-1",
            "allocations": [
                {
                    "allocation_id": "allocation-bound",
                    "device_id": "device-1",
                    "session_id": "session-bound",
                    "username": "1700000000:device-1",
                    "coturn_session_id": "013000000000000002",
                },
                {
                    "allocation_id": "allocation-unbound",
                    "device_id": "device-1",
                    "session_id": "session-unbound",
                    "username": "1700000000:device-1",
                },
            ],
        }
        registry = control.load_registry(self.write_registry(payload))
        sessions = control.parse_coturn_ps(PS_OUTPUT)
        with self.assertRaisesRegex(control.CoturnControlError, "ambiguous username"):
            control.export_snapshot(
                registry,
                sessions,
                datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc),
                42,
            )

    def test_unbound_resolution_excludes_already_bound_coturn_session_ids(self) -> None:
        payload = {
            "source_id": "turn-prod-1",
            "allocations": [
                {
                    "allocation_id": "allocation-bound",
                    "device_id": "device-1",
                    "session_id": "session-bound",
                    "username": "1700000000:device-1",
                    "coturn_session_id": "013000000000000002",
                },
                {
                    "allocation_id": "allocation-unbound",
                    "device_id": "device-3",
                    "session_id": "session-unbound",
                    "username": "1700000000:device-3",
                },
            ],
        }
        registry = control.load_registry(self.write_registry(payload))
        allocation = registry.allocations[1]
        sessions = [
            control.CoturnSession("013000000000000002", "1700000000:device-3", 10, 20),
        ]
        resolved = control.resolve_session(
            allocation,
            sessions,
            control._registry_username_counts(registry),
            control._bound_session_ids(registry),
        )
        self.assertIsNone(resolved)

    def test_export_command_requires_password_from_secret_source(self) -> None:
        registry = self.write_registry(self.registry_payload())
        with mock.patch.dict(os.environ, {}, clear=True):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3/coturn_cli_control.py"),
                    "export",
                    "--registry",
                    str(registry),
                    "--source-id",
                    "turn-prod-1",
                    "--observed-at",
                    "2026-08-21T01:02:03Z",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("coturn CLI password must contain at least 32 characters", result.stderr)

    def test_export_command_accepts_registry_and_state_from_environment(self) -> None:
        registry = self.write_registry(self.registry_payload())
        state = self.root / "state.json"
        password = self.write_text("cli-password.txt", "p" * 32)

        def fake_runner(_settings: control.CLISettings, command: str) -> str:
            self.assertEqual(command, "ps")
            return PS_OUTPUT

        with mock.patch("scripts.phase3.coturn_cli_control.run_cli_command", side_effect=fake_runner):
            with mock.patch.dict(
                os.environ,
                {
                    "VIBE_COTURN_CLI_PASSWORD_FILE": str(password),
                    "VIBE_COTURN_ALLOCATION_REGISTRY": str(registry),
                    "VIBE_COTURN_SEQUENCE_STATE": str(state),
                    "VIBE_COTURN_SOURCE_ID": "turn-prod-1",
                },
                clear=True,
            ):
                with mock.patch("sys.stdout") as stdout:
                    self.assertEqual(
                        control.main(["export", "--observed-at", "2026-08-21T01:02:03Z"]), 0
                    )
        rendered = "".join(call.args[0] for call in stdout.write.call_args_list if call.args)
        snapshot = json.loads(rendered)
        self.assertEqual(snapshot["source_id"], "turn-prod-1")
        self.assertEqual(snapshot["allocations"][0]["allocation_id"], "allocation-1")

    def test_sequence_state_is_monotonic_across_same_timestamp(self) -> None:
        state = self.root / "state" / "sequence.json"
        first = control._next_sequence(state, datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc))
        second = control._next_sequence(state, datetime(2026, 8, 21, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(second, first + 1)

    def test_disconnect_uses_environment_contract_and_coturn_cs(self) -> None:
        registry = self.write_registry(self.registry_payload())
        commands: list[str] = []

        def fake_runner(_settings: control.CLISettings, command: str) -> str:
            commands.append(command)
            if command == "ps" and commands.count("ps") == 1:
                return PS_OUTPUT
            if command == "ps":
                return ""
            if command == "cs 013000000000000002":
                return "closed\n> "
            raise AssertionError(command)

        with mock.patch("scripts.phase3.coturn_cli_control.run_cli_command", side_effect=fake_runner):
            with mock.patch.dict(
                os.environ,
                {
                    "VIBE_COTURN_CLI_PASSWORD": "p" * 32,
                    "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
                    "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation-1",
                    "VIBE_COTURN_DISCONNECT_REASON": "revoked",
                },
                clear=True,
            ):
                with mock.patch("sys.stdout"):
                    self.assertEqual(control.main(["disconnect", "--registry", str(registry)]), 0)
        self.assertEqual(commands, ["ps", "cs 013000000000000002", "ps"])

    def test_disconnect_fails_closed_when_coturn_session_remains_active(self) -> None:
        registry = self.write_registry(self.registry_payload())
        commands: list[str] = []

        def fake_runner(_settings: control.CLISettings, command: str) -> str:
            commands.append(command)
            if command == "ps":
                return PS_OUTPUT
            if command == "cs 013000000000000002":
                return "closed\n> "
            raise AssertionError(command)

        with mock.patch("scripts.phase3.coturn_cli_control.run_cli_command", side_effect=fake_runner):
            with mock.patch.dict(
                os.environ,
                {
                    "VIBE_COTURN_CLI_PASSWORD": "p" * 32,
                    "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
                    "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation-1",
                    "VIBE_COTURN_DISCONNECT_REASON": "revoked",
                },
                clear=True,
            ):
                with mock.patch("sys.stdout"):
                    self.assertEqual(control.main(["disconnect", "--registry", str(registry)]), 2)
        self.assertEqual(commands, ["ps", "cs 013000000000000002", "ps"])

    def test_disconnect_fails_closed_for_missing_registry_binding(self) -> None:
        registry = self.write_registry(self.registry_payload())
        with mock.patch.dict(
            os.environ,
            {
                "VIBE_COTURN_CLI_PASSWORD": "p" * 32,
                "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
                "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation-missing",
                "VIBE_COTURN_DISCONNECT_REASON": "revoked",
            },
            clear=True,
        ):
            self.assertEqual(control.main(["disconnect", "--registry", str(registry)]), 2)


if __name__ == "__main__":
    unittest.main()
