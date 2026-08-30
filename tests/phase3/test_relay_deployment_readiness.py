from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.phase3.relay_deployment_readiness import (
    BLOCKED_RESULT,
    PASS_RESULT,
    SCHEMA,
    PreflightError,
    build_report,
    check_disk_headroom,
    check_existing_containers,
    check_listening_ports,
    check_public_readyz,
    dns_check,
    main,
    parse_container_services,
    parse_deployment_df,
    parse_listening_ports,
    ssh_alias_available,
)


class RelayDeploymentReadinessTests(unittest.TestCase):
    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    def test_dns_check_hashes_resolved_addresses(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("198.51.100.10", 0))]

        result = dns_check("relay.example.net", family=2, timeout_seconds=1)

        self.assertEqual(result["record_count"], 1)
        self.assertEqual(len(result["resolved_address_hashes"]), 1)
        self.assertNotIn("198.51.100.10", json.dumps(result))

    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.getitimer")
    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.setitimer")
    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.signal")
    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    def test_dns_check_arms_and_restores_lookup_timeout(
        self, getaddrinfo, install_signal, setitimer, getitimer
    ) -> None:
        getitimer.return_value = (0.25, 0.0)
        getaddrinfo.return_value = [(None, None, None, None, ("198.51.100.10", 0))]

        result = dns_check("relay.example.net", family=2, timeout_seconds=1.5)

        self.assertEqual(result["record_count"], 1)
        self.assertEqual(setitimer.call_args_list[0].args, (signal.ITIMER_REAL, 1.5))
        self.assertEqual(setitimer.call_args_list[1].args, (signal.ITIMER_REAL, 0.25, 0.0))
        self.assertGreaterEqual(install_signal.call_count, 2)

    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.getitimer")
    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.setitimer")
    @mock.patch("scripts.phase3.relay_deployment_readiness.signal.signal")
    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    def test_dns_check_blocks_on_lookup_timeout_and_restores_timer(
        self, getaddrinfo, _install_signal, setitimer, getitimer
    ) -> None:
        getitimer.return_value = (0.0, 0.0)
        getaddrinfo.side_effect = TimeoutError

        with self.assertRaisesRegex(PreflightError, "timed out"):
            dns_check("relay.example.net", family=2, timeout_seconds=1.5)

        self.assertEqual(setitimer.call_args_list[1].args, (signal.ITIMER_REAL, 0.0, 0.0))

    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_build_report_blocks_without_ssh_alias_and_public_readyz(self, run, urlopen, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"non-zero")

        report = build_report(
            relay_host="relay.taoai.site",
            ready_url="https://relay.taoai.site/readyz",
            ssh_alias=None,
            timeout_seconds=1,
        )

        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertIn("ssh_alias_available", failed)
        self.assertNotIn("relay.taoai.site", json.dumps(report))
        self.assertNotIn("<operator-alias>", json.dumps(report))
        self.assertEqual(getaddrinfo.call_count, 2)
        run.assert_not_called()

    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    def test_build_report_does_not_leak_raw_dns_addresses(self, urlopen, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("198.51.100.11", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'

        report = build_report(
            relay_host="relay.example.net",
            ready_url="https://ready.example.net/readyz",
            ssh_alias=None,
            timeout_seconds=1,
        )

        rendered = json.dumps(report)
        self.assertNotIn("198.51.100.11", rendered)
        self.assertIn("resolved_address_hashes", rendered)

    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_build_report_passes_without_recording_remote_output(self, run, urlopen, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("203.0.113.22", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'

        def run_side_effect(args, **_kwargs):
            command = list(args)
            if command[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(command, 0, b"hostname host.example\nuser private-user\n", b"")
            if command[-3:] == ["df", "-Pk", "/"]:
                output = b"Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk1 50000000 10000000 40000000 20% /\n"
                return subprocess.CompletedProcess(command, 0, output, b"")
            if command[-2:] == ["docker", "--version"]:
                return subprocess.CompletedProcess(command, 0, b"Docker private-user internal-service\n", b"")
            if command[-3:] == ["docker", "compose", "version"]:
                return subprocess.CompletedProcess(command, 0, b"Compose private-user internal-service\n", b"")
            if command[-3:] == ["ss", "-H", "-ltnup"]:
                output = (
                    b"udp UNCONN 0 0 0.0.0.0:3478 0.0.0.0:* users:((turnserver,pid=1,fd=1))\n"
                    b"tcp LISTEN 0 4096 0.0.0.0:3478 0.0.0.0:* users:((turnserver,pid=1,fd=2))\n"
                    b"tcp LISTEN 0 4096 0.0.0.0:5349 0.0.0.0:* users:((turnserver,pid=1,fd=3))\n"
                    b"tcp LISTEN 0 4096 127.0.0.1:8088 0.0.0.0:* users:((signaling,pid=2,fd=4))\n"
                    b"tcp LISTEN 0 4096 127.0.0.1:8090 0.0.0.0:* users:((relay,pid=3,fd=5))\n"
                )
                return subprocess.CompletedProcess(command, 0, output, b"")
            if command[2:] == [
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.project=vibe-screen-phase3-production",
                "--filter",
                "status=running",
                "--format",
                "{{.Names}}",
            ]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    b"vibe-screen-phase3-production-signaling-1\n"
                    b"vibe-screen-phase3-production-relay-1\n"
                    b"vibe-screen-phase3-production-coturn-1\n",
                    b"",
                )
            private_output = b"private-user internal-service <local-place> relay <secret-marker>\n"
            return subprocess.CompletedProcess(command, 0, private_output, b"")

        run.side_effect = run_side_effect

        report = build_report(
            relay_host="relay.example.net",
            ready_url="https://ready.example.net/readyz",
            ssh_alias="relay-local",
            timeout_seconds=1,
        )

        rendered = json.dumps(report)
        self.assertEqual(report["result"], PASS_RESULT)
        self.assertNotIn("relay-local", rendered)
        self.assertNotIn("private-user", rendered)
        self.assertNotIn("internal-service", rendered)
        self.assertNotIn("<local-place>", rendered)
        self.assertNotIn("<secret-marker>", rendered)

    def test_ssh_alias_available_requires_ssh_binary_invocation(self) -> None:
        with mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            result, detail = ssh_alias_available("relay")

        self.assertEqual(result, PASS_RESULT)
        self.assertEqual(detail, "SSH alias config lookup passed")
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["ssh", "-G"])
        self.assertEqual(args[2], "relay")

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_ssh_alias_available_blocks_stderr_without_recording_remote_output(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            b"hostname relay.example.internal\nuser private-operator\n",
            b"Warning: remote host identification has changed!\nprivate-operator@relay.example.internal\n",
        )

        result, detail = ssh_alias_available("relay")

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertEqual(detail, "SSH alias config lookup reported stderr")
        self.assertNotIn("relay.example.internal", detail)
        self.assertNotIn("private-operator", detail)

    def test_ssh_alias_available_blocks_missing_alias(self) -> None:
        result, detail = ssh_alias_available(None)

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertIn("SSH alias", detail)

    def test_ssh_alias_available_rejects_shell_metacharacters(self) -> None:
        result, detail = ssh_alias_available("relay;uname")

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertIn("invalid", detail)

    def test_parse_deployment_df_reports_headroom(self) -> None:
        output = b"Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk1 50000000 10000000 40000000 20% /\n"

        self.assertEqual(parse_deployment_df(output), (40000000, 20))

    def test_parse_listening_ports_extracts_required_tcp_and_udp_ports(self) -> None:
        output = (
            b"Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            b"udp UNCONN 0 0 0.0.0.0:3478 0.0.0.0:* users:((\"turnserver\",pid=1,fd=1))\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8088 0.0.0.0:* users:((\"signaling\",pid=2,fd=3))\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8090 0.0.0.0:* users:((\"relay\",pid=3,fd=4))\n"
            b"tcp LISTEN 0 4096 [::]:3478 [::]:* users:((\"turnserver\",pid=4,fd=5))\n"
            b"tcp LISTEN 0 4096 [::]:5349 [::]:* users:((\"turnserver\",pid=4,fd=6))\n"
        )

        self.assertEqual(
            parse_listening_ports(output),
            {("udp", 3478), ("tcp", 3478), ("tcp", 5349), ("tcp", 8088), ("tcp", 8090)},
        )

    def test_parse_listening_ports_blocks_empty_snapshot(self) -> None:
        output = b"Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"

        with self.assertRaises(PreflightError):
            parse_listening_ports(output)

    def test_parse_container_services_blocks_empty_snapshot(self) -> None:
        with self.assertRaises(PreflightError):
            parse_container_services(b"\n")

    def test_parse_container_services_accepts_compose_container_names(self) -> None:
        output = (
            b"vibe-screen-phase3-production-signaling-1\n"
            b"vibe-screen-phase3-production-relay-1\n"
            b"vibe-screen-phase3-production-coturn-1\n"
        )

        self.assertEqual(parse_container_services(output), {"signaling", "relay", "coturn"})

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_disk_headroom_blocks_low_free_space(self, run) -> None:
        output = b"Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk1 50000000 49000000 1000000 98% /\n"
        run.return_value = subprocess.CompletedProcess([], 0, output, b"")

        result, detail = check_disk_headroom("relay", timeout_seconds=1)

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertIn("headroom", detail)

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_listening_ports_require_all_static_production_listeners(self, run) -> None:
        output = (
            b"Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8088 0.0.0.0:* users:((\"signaling\",pid=2,fd=3))\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8090 0.0.0.0:* users:((\"relay\",pid=3,fd=4))\n"
        )
        run.return_value = subprocess.CompletedProcess([], 0, output, b"")

        result, detail = check_listening_ports("relay", timeout_seconds=1)

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertIn("tcp/3478", detail)
        self.assertIn("udp/3478", detail)
        self.assertNotIn("127.0.0.1", detail)

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_listening_ports_pass_with_sanitized_count(self, run) -> None:
        output = (
            b"Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\n"
            b"udp UNCONN 0 0 0.0.0.0:3478 0.0.0.0:* users:((\"turnserver\",pid=1,fd=1))\n"
            b"tcp LISTEN 0 4096 0.0.0.0:3478 0.0.0.0:* users:((\"turnserver\",pid=1,fd=2))\n"
            b"tcp LISTEN 0 4096 0.0.0.0:5349 0.0.0.0:* users:((\"turnserver\",pid=1,fd=3))\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8088 0.0.0.0:* users:((\"signaling\",pid=2,fd=4))\n"
            b"tcp LISTEN 0 4096 127.0.0.1:8090 0.0.0.0:* users:((\"relay\",pid=3,fd=5))\n"
        )
        run.return_value = subprocess.CompletedProcess([], 0, output, b"")

        result, detail = check_listening_ports("relay", timeout_seconds=1)

        self.assertEqual(result, PASS_RESULT)
        self.assertEqual(detail, "required deployment listeners observed: 5")

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_existing_containers_require_compose_services(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"signaling\nrelay\n", b"")

        result, detail = check_existing_containers("relay", timeout_seconds=1)

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertIn("coturn", detail)

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_existing_containers_pass_with_sanitized_count(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"signaling\nrelay\ncoturn\n", b"")

        result, detail = check_existing_containers("relay", timeout_seconds=1)

        self.assertEqual(result, PASS_RESULT)
        self.assertEqual(detail, "required deployment containers observed: 3")

    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    def test_existing_containers_block_unexpected_services_without_leaking_names(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, b"signaling\nrelay\ncoturn\ninternal-admin\n", b"")

        result, detail = check_existing_containers("relay", timeout_seconds=1)

        self.assertEqual(result, BLOCKED_RESULT)
        self.assertEqual(detail, "deployment containers include unexpected services")
        self.assertNotIn("internal-admin", detail)

    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    def test_public_readyz_requires_status_ok(self, urlopen) -> None:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        check_public_readyz("https://relay.example.net/readyz", timeout_seconds=1)
        urlopen.assert_called_once()

    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    def test_public_readyz_rejects_non_ok_body(self, urlopen) -> None:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"degraded"}'
        with self.assertRaises(PreflightError):
            check_public_readyz("https://relay.example.net/readyz", timeout_seconds=1)

    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    def test_main_writes_blocked_report_with_allow_blocked(self, urlopen, run, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        run.return_value = subprocess.CompletedProcess([], 1, b"", b"non-zero")
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "relay-readiness.json"
            code = main(
                [
                    "--relay-host",
                    "relay.example.net",
                    "--ready-url",
                    "https://ready.example.net/readyz",
                    "--output",
                    str(output),
                    "--allow-blocked",
                    "--timeout-seconds",
                    "1",
                ]
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(report["result"], BLOCKED_RESULT)
        self.assertNotIn("relay.example.net", json.dumps(report))

    @mock.patch("scripts.phase3.relay_deployment_readiness.socket.getaddrinfo")
    @mock.patch("scripts.phase3.relay_deployment_readiness.subprocess.run")
    @mock.patch("scripts.phase3.relay_deployment_readiness.request.urlopen")
    def test_main_returns_nonzero_when_blocked_without_allow_blocked(self, urlopen, run, getaddrinfo) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "relay-readiness.json"
            code = main(
                [
                    "--relay-host",
                    "relay.example.net",
                    "--ready-url",
                    "https://ready.example.net/readyz",
                    "--output",
                    str(output),
                    "--timeout-seconds",
                    "1",
                ]
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 2)
        self.assertEqual(report["result"], BLOCKED_RESULT)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
