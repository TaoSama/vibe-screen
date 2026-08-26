from __future__ import annotations

import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_machost_loopback as runner


TEST_LOG_ENVIRONMENT = "VIBE_SCREEN_IOS_LOOPBACK_TEST_LOG"
FAKE_HOST = """
#!/usr/bin/env python3
import json
import os
import socket
from pathlib import Path

scenario = os.environ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"]
requested_port = int(os.environ["VIBE_SCREEN_IOS_LOOPBACK_PORT"])
log_path = Path(os.environ["VIBE_SCREEN_IOS_LOOPBACK_TEST_LOG"])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1", requested_port))
    listener.listen(1)
    listening_port = listener.getsockname()[1]
    with log_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({
            "role": "host",
            "scenario": scenario,
            "requested_port": requested_port,
            "listening_port": listening_port,
        }) + "\\n")
    print(f"IOS_LOOPBACK_HOST_READY port={listening_port}", flush=True)
    connection, _ = listener.accept()
    with connection:
        if connection.recv(1) != b"x":
            raise SystemExit(3)
"""
FAKE_CLIENT = """
#!/usr/bin/env python3
import json
import os
import socket
from pathlib import Path

scenario = os.environ["VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"]
port = int(os.environ["VIBE_SCREEN_IOS_LOOPBACK_PORT"])
log_path = Path(os.environ["VIBE_SCREEN_IOS_LOOPBACK_TEST_LOG"])
with log_path.open("a", encoding="utf-8") as output:
    output.write(json.dumps({
        "role": "client",
        "scenario": scenario,
        "port": port,
    }) + "\\n")
with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
    connection.sendall(b"x")
"""
STUBBORN_HOST = FAKE_HOST.replace(
    "import socket\n",
    "import signal\n"
    "import socket\n"
    "import time\n\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n",
    1,
).replace(
    "            raise SystemExit(3)\n",
    "            raise SystemExit(3)\n        time.sleep(60)\n",
)


class MacHostLoopbackRunnerTests(unittest.TestCase):
    def test_both_scenarios_use_ready_ports_while_default_port_is_occupied(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            host = self.write_executable(root, "fake-host", FAKE_HOST)
            client = self.write_executable(root, "fake-client", FAKE_CLIENT)
            log_path = root / "ports.jsonl"
            default_listener = self.occupy_default_port()
            try:
                if default_listener is not None:
                    with socket.create_connection(
                        ("127.0.0.1", 54_321),
                        timeout=0.5,
                    ):
                        pass
                with mock.patch.dict(
                    os.environ,
                    {TEST_LOG_ENVIRONMENT: str(log_path)},
                    clear=False,
                ):
                    lifecycle_port = runner.run_case(
                        host,
                        client,
                        startup_timeout=5,
                        test_timeout=5,
                        invalid_target=False,
                        legacy_plaintext=False,
                    )
                    invalid_target_port = runner.run_case(
                        host,
                        client,
                        startup_timeout=5,
                        test_timeout=5,
                        invalid_target=True,
                        legacy_plaintext=False,
                    )
            finally:
                if default_listener is not None:
                    default_listener.close()

            records = [json.loads(line) for line in log_path.read_text().splitlines()]
            indexed = {
                (record["role"], record["scenario"]): record
                for record in records
            }
            for scenario, returned_port in (
                ("lifecycle", lifecycle_port),
                ("invalid-target", invalid_target_port),
            ):
                host_record = indexed[("host", scenario)]
                client_record = indexed[("client", scenario)]
                self.assertEqual(host_record["requested_port"], 0)
                self.assertEqual(host_record["listening_port"], returned_port)
                self.assertEqual(client_record["port"], returned_port)
                self.assertNotEqual(returned_port, 54_321)
                self.assert_port_not_listening(returned_port)

    def test_invalid_client_ports_fail_closed(self) -> None:
        for port in (-1, 0, 65_536, True, "54321"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    runner.loopback_environment(
                        "lifecycle",
                        port,
                        allow_ephemeral=False,
                    )
        environment = runner.loopback_environment(
            "lifecycle",
            0,
            allow_ephemeral=True,
        )
        self.assertEqual(environment[runner.LOOPBACK_PORT_ENVIRONMENT], "0")
        self.assertNotIn(runner.LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT, environment)

    def test_legacy_plaintext_flag_is_explicit(self) -> None:
        secure_environment = runner.loopback_environment(
            "lifecycle",
            54_321,
            allow_ephemeral=False,
            legacy_plaintext=False,
        )
        legacy_environment = runner.loopback_environment(
            "lifecycle",
            54_321,
            allow_ephemeral=False,
            legacy_plaintext=True,
        )

        self.assertNotIn(runner.LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT, secure_environment)
        self.assertEqual(legacy_environment[runner.LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT], "1")

    def test_loopback_process_environment_does_not_inherit_ci_secrets(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                TEST_LOG_ENVIRONMENT: "/tmp/vibescreen-loopback.jsonl",
                "GITHUB_TOKEN": "redacted",
                "ACCESS_TOKEN": "redacted",
                "PRIVATE_KEY": "redacted",
            },
            clear=True,
        ):
            environment = runner.loopback_environment(
                "lifecycle",
                54_321,
                allow_ephemeral=False,
            )

        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertEqual(
            environment[runner.LOOPBACK_SCENARIO_ENVIRONMENT],
            "lifecycle",
        )
        self.assertEqual(environment[runner.LOOPBACK_PORT_ENVIRONMENT], "54321")
        self.assertEqual(
            environment[TEST_LOG_ENVIRONMENT],
            "/tmp/vibescreen-loopback.jsonl",
        )
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertNotIn("ACCESS_TOKEN", environment)
        self.assertNotIn("PRIVATE_KEY", environment)

    def test_timeout_cleanup_releases_listener(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            host = self.write_executable(root, "stubborn-host", STUBBORN_HOST)
            client = self.write_executable(root, "fake-client", FAKE_CLIENT)
            log_path = root / "ports.jsonl"
            with mock.patch.dict(
                os.environ,
                {TEST_LOG_ENVIRONMENT: str(log_path)},
                clear=False,
            ):
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner.run_case(
                        host,
                        client,
                        startup_timeout=5,
                        test_timeout=0.1,
                        invalid_target=False,
                        legacy_plaintext=False,
                    )
            host_record = next(
                json.loads(line)
                for line in log_path.read_text().splitlines()
                if json.loads(line)["role"] == "host"
            )
            self.assert_port_not_listening(host_record["listening_port"])

    def test_listener_shutdown_check_ignores_closed_tcp_connection_state(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                connection, _ = listener.accept()
                connection.close()
                self.assertEqual(client.recv(1), b"")
        runner.wait_for_listener_shutdown(port, timeout=0.5)

    def write_executable(self, root: Path, name: str, source: str) -> Path:
        path = root / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)
        return path

    def occupy_default_port(self) -> Optional[socket.socket]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 54_321))
            listener.listen(1)
            return listener
        except OSError as error:
            listener.close()
            if error.errno == errno.EADDRINUSE:
                return None
            raise

    def assert_port_not_listening(self, port: int) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            self.assertEqual(
                probe.connect_ex(("127.0.0.1", port)),
                errno.ECONNREFUSED,
            )


if __name__ == "__main__":
    unittest.main()
