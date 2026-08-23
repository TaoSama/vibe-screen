from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from scripts.phase3.public_nat_turn_preflight import (
    BLOCKED_RESULT,
    CONNECTIVITY_SCHEMA,
    PASS_RESULT,
    SCHEMA,
    PreflightError,
    build_report,
    main,
    parse_turn_uri,
    require_public_host,
    read_json,
)


def write(path: Path, value: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)
    return path


def valid_relay_config() -> dict[str, object]:
    return {
        "listen_address": "127.0.0.1:8090",
        "turn_realm": "relay.production.invalidname.net",
        "turn_uris": [
            "turn:relay.production.invalidname.net:3478?transport=udp",
            "turn:relay.production.invalidname.net:3478?transport=tcp",
            "turns:relay.production.invalidname.net:5349?transport=tcp",
        ],
        "credential_ttl_seconds": 600,
        "max_credential_ttl_seconds": 1800,
        "credential_requests_per_minute": 12,
        "max_concurrent_sessions_per_device": 2,
        "daily_bytes_per_device": 20 * 1024 * 1024 * 1024,
        "max_usage_event_bytes": 1024 * 1024 * 1024,
        "storage_backend": "postgres",
        "authority_mode": "production_authority",
        "authority_url": "https://authority.production.invalidname.net",
        "authority_source_id": "turn-prod-a",
        "maximum_database_clock_skew_seconds": 5,
        "state_file": "/data/relay-state.json",
    }


def valid_coturn_config(extra: str = "") -> str:
    return "\n".join(
        [
            "listening-port=3478",
            "tls-listening-port=5349",
            "use-auth-secret",
            "fingerprint",
            "no-multicast-peers",
            "cert=/run/secrets/tls_certificate",
            "pkey=/run/secrets/tls_private_key",
            "min-port=49152",
            "max-port=65535",
            "total-quota=1000",
            "user-quota=12",
            "max-bps=20000000",
            "denied-peer-ip=10.0.0.0-10.255.255.255",
            "denied-peer-ip=100.64.0.0-100.127.255.255",
            "denied-peer-ip=127.0.0.0-127.255.255.255",
            "denied-peer-ip=169.254.0.0-169.254.255.255",
            "denied-peer-ip=172.16.0.0-172.31.255.255",
            "denied-peer-ip=192.168.0.0-192.168.255.255",
            "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            extra,
        ]
    )


def valid_connectivity_evidence() -> dict[str, object]:
    return {
        "schema": CONNECTIVITY_SCHEMA,
        "result": PASS_RESULT,
        "public_internet_path": True,
        "remote_turn": True,
        "forced_local_coturn": False,
        "loopback": False,
        "synthetic_peer": False,
        "selected_candidate_pair": {
            "selected_route": "relay",
            "local_candidate_type": "relay",
            "remote_candidate_type": "srflx",
            "protocol": "udp",
            "turn_host": "relay.production.invalidname.net",
        },
        "connectivity": {
            "result": PASS_RESULT,
            "packets_sent": 5,
            "packets_received": 5,
        },
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
        },
    }


class PublicNatTurnPreflightTests(unittest.TestCase):
    def test_turn_uri_parser_defaults_turns_port(self) -> None:
        parsed = parse_turn_uri("turns:relay.prod.test?transport=tcp")
        self.assertEqual(parsed["scheme"], "turns")
        self.assertEqual(parsed["port"], 5349)
        self.assertEqual(parsed["transport"], "tcp")
        with self.assertRaisesRegex(PreflightError, "turn: or turns"):
            parse_turn_uri("stun:relay.prod.test:3478")

    def test_public_host_rejects_local_private_and_placeholder_hosts(self) -> None:
        for host in ("127.0.0.1", "10.0.0.1", "relay.example.com", "relay.local"):
            with self.subTest(host=host):
                with self.assertRaises(PreflightError):
                    require_public_host(host, resolve=False)

    def test_read_json_error_detail_omits_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            broken = Path(directory_name) / "sensitive-path-connectivity.json"
            broken.write_text("{", encoding="utf-8")

            with self.assertRaises(PreflightError) as context:
                read_json(broken, "public NAT/TURN connectivity evidence")

        detail = str(context.exception)
        self.assertIn("JSONDecodeError", detail)
        self.assertNotIn(directory_name, detail)
        self.assertNotIn("sensitive-path-connectivity.json", detail)

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_missing_runtime_deployment_inputs_block_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=None,
                tls_certificate=None,
                tls_private_key=None,
                coturn_external_ip=None,
                authority_ready_url=None,
                relay_ready_url=None,
                connectivity_evidence=None,
                connectivity_command=None,
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertTrue(set(report["required_runtime_inputs"]).issubset(failed))
        self.assertIn("blocked_before_public_nat_turn_deployment_gate", report["limitations"])

    @mock.patch("scripts.phase3.public_nat_turn_preflight.subprocess.run")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_pass_requires_public_config_secret_files_readiness_and_remote_connectivity(self, getaddrinfo, urlopen, run) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        run.return_value = subprocess.CompletedProcess(
            ["external-canary"],
            0,
            stdout=json.dumps(valid_connectivity_evidence()),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8/10.0.0.5",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], PASS_RESULT)
        self.assertEqual(report["limitations"], [])
        self.assertEqual(report["connectivity"]["reviewed_evidence"]["packets_received"], 5)
        self.assertEqual(report["connectivity"]["canary_evidence"]["packets_received"], 5)
        self.assertFalse(report["privacy"]["raw_endpoints_recorded"])
        self.assertNotIn("relay.production.invalidname.net", json.dumps(report))

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_local_coturn_or_synthetic_peer_connectivity_blocks_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        connectivity = valid_connectivity_evidence()
        connectivity["forced_local_coturn"] = True
        connectivity["synthetic_peer"] = True
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(connectivity)),
                connectivity_command=None,
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertEqual(failed, {"connectivity_evidence", "external_connectivity_canary"})

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_self_reported_connectivity_file_cannot_pass_without_external_canary(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertEqual(failed, {"external_connectivity_canary"})
        self.assertEqual(report["connectivity"]["reviewed_evidence"]["packets_received"], 5)

    @mock.patch("scripts.phase3.public_nat_turn_preflight.subprocess.run")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_reviewed_connectivity_must_match_external_canary_output(self, getaddrinfo, urlopen, run) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        canary = valid_connectivity_evidence()
        canary["connectivity"] = {"result": PASS_RESULT, "packets_sent": 7, "packets_received": 7}
        run.return_value = subprocess.CompletedProcess(
            ["external-canary"],
            0,
            stdout=json.dumps(canary),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertEqual(failed, {"connectivity_evidence_matches_canary"})
        self.assertIn("reviewed_evidence", report["connectivity"])
        self.assertIn("canary_evidence", report["connectivity"])

    @mock.patch("scripts.phase3.public_nat_turn_preflight.subprocess.run")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    def test_skip_dns_resolution_blocks_pass_even_with_complete_runtime_inputs(self, urlopen, run) -> None:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        run.return_value = subprocess.CompletedProcess(
            ["external-canary"],
            0,
            stdout=json.dumps(valid_connectivity_evidence()),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                resolve_dns=False,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertIn("dns_resolution", failed)

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_too_low_relay_or_coturn_quota_blocks_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        config = valid_relay_config()
        config["daily_bytes_per_device"] = 1
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(config)),
                coturn_config=write(directory / "production.conf", valid_coturn_config("user-quota=1")),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertIn("relay_production_config", failed)
        self.assertIn("coturn_production_config", failed)

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_private_authority_or_readiness_hosts_block_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        config = valid_relay_config()
        config["authority_url"] = "https://10.0.0.5"
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(config)),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n", mode=0o644),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://10.0.0.6/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertIn("relay_production_config", failed)
        self.assertIn("authority_readiness", failed)

    def test_checked_in_example_config_is_blocked_before_public_deployment(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "preflight.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--relay-config",
                        str(root / "deploy/phase3/config/relay.production.example.json"),
                        "--coturn-config",
                        str(root / "deploy/phase3/coturn/production.conf"),
                        "--skip-dns-resolution",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("BLOCKED", stderr.getvalue())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["result"], BLOCKED_RESULT)
            self.assertEqual(report["privacy"]["sensitive_values_recorded"], False)

    def test_allow_blocked_records_evidence_with_zero_exit(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "preflight.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--relay-config",
                        str(root / "deploy/phase3/config/relay.production.example.json"),
                        "--coturn-config",
                        str(root / "deploy/phase3/coturn/production.conf"),
                        "--skip-dns-resolution",
                        "--output",
                        str(output),
                        "--allow-blocked",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["result"], BLOCKED_RESULT)


if __name__ == "__main__":
    unittest.main()
