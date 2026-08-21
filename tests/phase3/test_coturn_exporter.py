from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import scripts.phase3.coturn_disconnect_executor as disconnect_executor  # noqa: E402
import scripts.phase3.coturn_exporter as coturn_exporter  # noqa: E402
from scripts.phase3.coturn_exporter import (  # noqa: E402
    ExportError,
    Settings as ExporterSettings,
    export_snapshot,
    _parse_sessions,
    _parse_username,
)
from scripts.phase3.coturn_disconnect_executor import (  # noqa: E402
    DisconnectError,
    _find_session_ids,
)


SAMPLE_PS_OUTPUT = """
    1) id=013000000000000002, user <1787278635:device-1:session-1:allocation-1>:
      realm: test.local
      started 2 secs ago
      expiring in 1 secs
      client protocol UDP, relay protocol UDP
      client addr 127.0.0.1:52755, server addr 127.0.0.1:34789
      relay addr 127.0.0.1:49188
      usage: rp=9, rb=1172, sp=8, sb=552
       rate: r=0, s=0, total=0 (bytes per sec)
      peers:
          127.0.0.1:49162

    2) id=013000000000000001, user <1787278635:device-1:session-1:allocation-1>:
      realm: test.local
      started 2 secs ago
      expiring in 775 secs
      client protocol UDP, relay protocol UDP
      client addr 127.0.0.1:60392, server addr 127.0.0.1:34789
      relay addr 127.0.0.1:49196
      usage: rp=3, rb=348, sp=2, sb=184
       rate: r=0, s=0, total=0 (bytes per sec)

    3) id=013000000000000003, user <1787278635:device-2:session-2:allocation-2>:
      realm: test.local
      started 2 secs ago
      expiring in 598 secs
      client protocol UDP, relay protocol UDP
      client addr 127.0.0.1:50214, server addr 127.0.0.1:34789
      relay addr 127.0.0.1:49162
      usage: rp=7, rb=920, sp=6, sb=396
       rate: r=0, s=0, total=0 (bytes per sec)

  Total sessions: 3

> """


class CoturnExporterTests(unittest.TestCase):
    def test_parse_username_extracts_device_and_allocation(self) -> None:
        device_id, session_id, allocation_id = _parse_username("1787278635:device-1:session-1:allocation-1")
        self.assertEqual(device_id, "device-1")
        self.assertEqual(session_id, "session-1")
        self.assertEqual(allocation_id, "allocation-1")

    def test_parse_username_rejects_malformed_principals(self) -> None:
        for value in ("only-expiry", "expiry:device:session", "expiry:device:session:alloc:extra"):
            with self.assertRaises(ExportError):
                _parse_username(value)

    def test_parse_sessions_aggregates_same_allocation_id(self) -> None:
        allocations = _parse_sessions(SAMPLE_PS_OUTPUT)
        by_id = {a["allocation_id"]: a for a in allocations}
        self.assertEqual(set(by_id), {"allocation-1", "allocation-2"})
        # Two coturn sessions for allocation-1 are merged into one ledger entry.
        self.assertEqual(by_id["allocation-1"]["device_id"], "device-1")
        self.assertEqual(by_id["allocation-1"]["session_id"], "session-1")
        self.assertEqual(by_id["allocation-1"]["ingress_bytes"], 1172 + 348)
        self.assertEqual(by_id["allocation-1"]["egress_bytes"], 552 + 184)
        self.assertEqual(by_id["allocation-1"]["sequence"], 1172 + 348 + 552 + 184)
        self.assertFalse(by_id["allocation-1"]["closed"])

    def test_parse_sessions_preserves_distinct_allocations(self) -> None:
        allocations = _parse_sessions(SAMPLE_PS_OUTPUT)
        by_id = {a["allocation_id"]: a for a in allocations}
        self.assertEqual(by_id["allocation-2"]["device_id"], "device-2")
        self.assertEqual(by_id["allocation-2"]["session_id"], "session-2")
        self.assertEqual(by_id["allocation-2"]["ingress_bytes"], 920)
        self.assertEqual(by_id["allocation-2"]["egress_bytes"], 396)

    def test_parse_sessions_keeps_idle_allocation_sequence_positive(self) -> None:
        output = """
    1) id=013000000000000004, user <1787278635:device-3:session-3:allocation-3>:
      usage: rp=0, rb=0, sp=0, sb=0

> """
        allocations = _parse_sessions(output)
        self.assertEqual(allocations[0]["sequence"], 1)

    def test_parse_sessions_rejects_allocation_identity_conflict(self) -> None:
        output = SAMPLE_PS_OUTPUT.replace(
            "1787278635:device-1:session-1:allocation-1",
            "1787278635:device-9:session-9:allocation-1",
            1,
        )
        with self.assertRaises(ExportError):
            _parse_sessions(output)

    def test_find_session_ids_matches_allocation_id(self) -> None:
        session_ids = _find_session_ids(SAMPLE_PS_OUTPUT, "allocation-1")
        self.assertEqual(session_ids, ["013000000000000002", "013000000000000001"])

    def test_find_session_ids_returns_empty_for_unknown_allocation(self) -> None:
        self.assertEqual(_find_session_ids(SAMPLE_PS_OUTPUT, "missing"), [])

    def test_exporter_and_disconnect_reject_non_loopback_cli_hosts(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_COTURN_CLI_PASSWORD": "x" * 16}, clear=True):
            exporter_args = coturn_exporter.build_parser().parse_args(
                ["--source-id", "turn-prod-1", "--cli-host", "198.51.100.10"]
            )
            with self.assertRaisesRegex(ExportError, "loopback"):
                coturn_exporter.settings_from_args(exporter_args)

            disconnect_args = disconnect_executor.build_parser().parse_args(
                ["--cli-host", "198.51.100.10"]
            )
            env = {
                "VIBE_COTURN_CLI_PASSWORD": "x" * 16,
                "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
                "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation-1",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(DisconnectError, "loopback"):
                    disconnect_executor.settings_from_args(disconnect_args)

    def test_disconnect_rejects_invalid_environment_identity(self) -> None:
        disconnect_args = disconnect_executor.build_parser().parse_args([])
        env = {
            "VIBE_COTURN_CLI_PASSWORD": "x" * 16,
            "VIBE_COTURN_DISCONNECT_SOURCE_ID": "turn-prod-1",
            "VIBE_COTURN_DISCONNECT_ALLOCATION_ID": "allocation:bad",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(DisconnectError, "VIBE_COTURN_DISCONNECT_ALLOCATION_ID"):
                disconnect_executor.settings_from_args(disconnect_args)

    def test_exporter_reports_cli_connection_failure_without_traceback(self) -> None:
        settings = ExporterSettings(
            cli_host="127.0.0.1",
            cli_port=1,
            cli_password="x" * 16,
            source_id="turn-prod-1",
            timeout_seconds=0.001,
        )
        with self.assertRaisesRegex(ExportError, "coturn CLI connection failed"):
            export_snapshot(settings)

    def test_exporter_and_disconnect_use_default_container_secret_file(self) -> None:
        password = "x" * 16
        with tempfile.TemporaryDirectory() as temporary:
            exporter_password = Path(temporary) / "exporter-password"
            exporter_password.write_text(password, encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(coturn_exporter, "DEFAULT_CLI_PASSWORD_FILE", str(exporter_password)):
                    self.assertEqual(
                        coturn_exporter._load_cli_password("VIBE_COTURN_CLI_PASSWORD", None),
                        password,
                    )

            disconnect_password = Path(temporary) / "disconnect-password"
            disconnect_password.write_text(password, encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(disconnect_executor, "DEFAULT_CLI_PASSWORD_FILE", str(disconnect_password)):
                    self.assertEqual(
                        disconnect_executor._load_cli_password("VIBE_COTURN_CLI_PASSWORD", None),
                        password,
                    )


if __name__ == "__main__":
    unittest.main()
