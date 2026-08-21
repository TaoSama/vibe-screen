from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]

from scripts.phase3.public_internet_evidence import (  # noqa: E402
    BLOCKED_RESULT,
    PASS_RESULT,
    PREFLIGHT_SCHEMA,
    PublicInternetEvidenceError,
    build_blocked_soak_report,
    build_preflight_report,
    build_soak_report,
    build_verifier_report,
    parse_turn_uri,
    require_public_remote_host,
)


def write(path: Path, content: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def valid_relay_config() -> dict[str, object]:
    return {
        "listen_address": "127.0.0.1:8090",
        "turn_realm": "relay.prod.test",
        "turn_uris": [
            "turn:relay.prod.test:3478?transport=udp",
            "turns:relay.prod.test:5349?transport=tcp",
        ],
        "credential_ttl_seconds": 600,
        "max_credential_ttl_seconds": 1800,
        "credential_requests_per_minute": 12,
        "max_concurrent_sessions_per_device": 2,
        "daily_bytes_per_device": 1,
        "max_usage_event_bytes": 1,
        "egress_microcents_per_gibibyte": 1,
        "storage_backend": "postgres",
        "authority_mode": "production_authority",
        "authority_url": "https://authority.prod.test",
        "authority_source_id": "turn-prod-a",
        "maximum_database_clock_skew_seconds": 5,
        "state_file": "/data/relay-state.json",
    }


def valid_coturn_conf(extra: str = "") -> str:
    return "\n".join(
        [
            "listening-port=3478",
            "tls-listening-port=5349",
            "use-auth-secret",
            "fingerprint",
            "no-multicast-peers",
            "cert=/run/secrets/tls_certificate",
            "pkey=/run/secrets/tls_private_key",
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


def valid_soak_summary() -> dict[str, object]:
    return {
        "duration_seconds": 7200,
        "route_counts": {"direct": 12, "relay": 12},
        "network_handoffs": 1,
        "nonce_reuse_detected": False,
        "metrics": {
            "rss": {},
            "queue": {},
            "loss": {},
            "rtt": {},
            "fps": {},
            "bitrate": {},
            "relay_bytes": {},
            "ice_restarts": {},
            "drops": {},
            "thermal": {},
            "battery": {},
        },
    }


class PublicInternetEvidenceTests(unittest.TestCase):
    def test_turn_uri_parser_defaults_and_rejects_unsupported_scheme(self) -> None:
        parsed = parse_turn_uri("turns:relay.prod.test?transport=tcp")
        self.assertEqual(parsed.port, 5349)
        self.assertEqual(parsed.transport, "tcp")
        with self.assertRaisesRegex(PublicInternetEvidenceError, "turn: or turns"):
            parse_turn_uri("stun:relay.prod.test:3478")

    def test_public_remote_host_rejects_loopback_private_and_placeholder(self) -> None:
        for host in ("127.0.0.1", "10.0.0.1", "relay.example.com", "phase3.local"):
            with self.subTest(host=host):
                with self.assertRaises(PublicInternetEvidenceError):
                    require_public_remote_host(host, resolve=False)

    @mock.patch("scripts.phase3.public_internet_evidence.urlopen")
    @mock.patch("scripts.phase3.public_internet_evidence.socket.getaddrinfo")
    def test_preflight_blocks_when_public_deployment_inputs_are_missing(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            relay_config = write(directory / "relay.json", json.dumps(valid_relay_config()))
            coturn_config = write(directory / "production.conf", valid_coturn_conf())

            report = build_preflight_report(
                relay_config_path=relay_config,
                coturn_config_path=coturn_config,
                turn_secret_file=None,
                tls_certificate=None,
                tls_private_key=None,
                coturn_external_ip=None,
                authority_ready_url=None,
                relay_ready_url=None,
            )

        self.assertEqual(report["schema"], PREFLIGHT_SCHEMA)
        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertTrue({"turn_secret_file", "tls_certificate", "tls_private_key", "coturn_external_ip"}.issubset(failed))
        self.assertIn("blocked_before_public_internet_or_remote_turn_evidence", report["limitations"])

    @mock.patch("scripts.phase3.public_internet_evidence.urlopen")
    @mock.patch("scripts.phase3.public_internet_evidence.socket.getaddrinfo")
    def test_preflight_pass_requires_public_tls_authority_and_secret_files(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            relay_config = write(directory / "relay.json", json.dumps(valid_relay_config()))
            coturn_config = write(directory / "production.conf", valid_coturn_conf())
            secret = write(directory / "turn-secret", "x" * 32)
            cert = write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n")
            key = write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n")

            report = build_preflight_report(
                relay_config_path=relay_config,
                coturn_config_path=coturn_config,
                turn_secret_file=secret,
                tls_certificate=cert,
                tls_private_key=key,
                coturn_external_ip="8.8.8.8/10.0.0.5",
                authority_ready_url="https://authority.prod.test/readyz",
                relay_ready_url="https://relay.prod.test/readyz",
            )

        self.assertEqual(report["result"], PASS_RESULT)
        self.assertEqual(report["limitations"], [])
        self.assertFalse(report["privacy"]["raw_endpoints_recorded"])
        self.assertGreater(report["relay"]["turns_uri_count"], 0)

    @mock.patch("scripts.phase3.public_internet_evidence.urlopen")
    @mock.patch("scripts.phase3.public_internet_evidence.socket.getaddrinfo")
    def test_preflight_blocks_local_development_and_non_tls_turn(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        config = valid_relay_config()
        config["authority_mode"] = "local_development"
        config["turn_uris"] = ["turn:relay.prod.test:3478?transport=udp"]
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report = build_preflight_report(
                relay_config_path=write(directory / "relay.json", json.dumps(config)),
                coturn_config_path=write(directory / "production.conf", valid_coturn_conf("allowed-peer-ip=0.0.0.0-255.255.255.255")),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=write(directory / "fullchain.pem", "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n"),
                tls_private_key=write(directory / "privkey.pem", "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----\n"),
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.prod.test/readyz",
                relay_ready_url="https://relay.prod.test/readyz",
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertIn("relay_production_config", failed)
        self.assertIn("coturn_production_config", failed)

    @mock.patch("scripts.phase3.public_internet_evidence.subprocess.run")
    @mock.patch("scripts.phase3.public_internet_evidence.urlopen")
    @mock.patch("scripts.phase3.public_internet_evidence.socket.getaddrinfo")
    def test_verifier_requires_passed_preflight_and_remote_peer(self, getaddrinfo, urlopen, run) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.4.4", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {
                "username": "1900000000:device-a",
                "password": "credential-value",
                "ttl_seconds": 600,
                "realm": "relay.prod.test",
                "uris": ["turn:relay.prod.test:3478?transport=udp", "turns:relay.prod.test:5349?transport=tcp"],
            }
        ).encode("utf-8")
        run.return_value = subprocess.CompletedProcess(
            ["turnutils_uclient"],
            0,
            stdout="success\ntot_send_msgs=5\ntot_recv_msgs=5\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            preflight = write(
                directory / "preflight.json",
                json.dumps(
                    {
                        "schema": PREFLIGHT_SCHEMA,
                        "result": PASS_RESULT,
                        "relay": {
                            "turn_host_hashes": [
                                "63cb14d3ee8e9ccc6d509100d9870d846415bef63c784d7b4270e28c11ee3bf9"
                            ]
                        },
                    }
                ),
            )
            token = write(directory / "client-token", "x" * 32)

            report = build_verifier_report(
                preflight_path=preflight,
                relay_url="https://relay.prod.test",
                client_token_file=token,
                device_id="device-a",
                session_id="session-a",
                allocation_id="allocation-a",
                peer_host="peer.prod.test",
                peer_port=3479,
                turnutils_uclient="turnutils_uclient",
            )

        self.assertEqual(report["result"], PASS_RESULT)
        self.assertEqual(report["turn"]["tot_recv_msgs"], 5)
        self.assertIn("turn_allocation", report)
        self.assertIn("-e", run.call_args.args[0])
        self.assertNotIn("device-a", json.dumps(report))
        self.assertNotIn("credential-value", json.dumps(report))

    @mock.patch("scripts.phase3.public_internet_evidence.urlopen")
    @mock.patch("scripts.phase3.public_internet_evidence.socket.getaddrinfo")
    def test_verifier_rejects_turn_hosts_outside_passed_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.4.4", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {
                "username": "1900000000:device-a",
                "password": "credential-value",
                "ttl_seconds": 600,
                "realm": "relay.prod.test",
                "uris": [
                    "turn:relay.prod.test:3478?transport=udp",
                    "turns:relay.prod.test:5349?transport=tcp",
                ],
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            preflight = write(
                directory / "preflight.json",
                json.dumps(
                    {
                        "schema": PREFLIGHT_SCHEMA,
                        "result": PASS_RESULT,
                        "relay": {"turn_host_hashes": ["0" * 64]},
                    }
                ),
            )
            token = write(directory / "client-token", "x" * 32)

            with self.assertRaisesRegex(PublicInternetEvidenceError, "do not match"):
                build_verifier_report(
                    preflight_path=preflight,
                    relay_url="https://relay.prod.test",
                    client_token_file=token,
                    device_id="device-a",
                    session_id="session-a",
                    allocation_id="allocation-a",
                    peer_host="peer.prod.test",
                    peer_port=3479,
                    turnutils_uclient="turnutils_uclient",
                )

    def test_blocked_soak_report_never_claims_public_pass(self) -> None:
        report = build_blocked_soak_report(
            preflight_path=None,
            verifier_path=None,
            preset="2h",
            reason="no deployment",
        )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        self.assertEqual(report["required_duration_seconds"], 7200)
        self.assertIn("blocked_before_two_hour_public_internet_soak", report["limitations"])

    def test_soak_pass_requires_two_hours_direct_relay_handoff_and_nonce_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            preflight = write(directory / "preflight.json", json.dumps({"schema": PREFLIGHT_SCHEMA, "result": PASS_RESULT}))
            verifier = write(
                directory / "verifier.json",
                json.dumps({"schema": "dev.vibescreen.phase3-remote-turn-verifier/v1", "result": PASS_RESULT}),
            )
            summary = write(directory / "private-summary.json", json.dumps(valid_soak_summary()))

            report = build_soak_report(
                preflight_path=preflight,
                verifier_path=verifier,
                private_summary_path=summary,
                preset="2h",
            )

        self.assertEqual(report["result"], PASS_RESULT)
        self.assertEqual(report["summary"]["network_handoffs"], 1)

    def test_soak_rejects_short_or_relay_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            preflight = write(directory / "preflight.json", json.dumps({"schema": PREFLIGHT_SCHEMA, "result": PASS_RESULT}))
            verifier = write(
                directory / "verifier.json",
                json.dumps({"schema": "dev.vibescreen.phase3-remote-turn-verifier/v1", "result": PASS_RESULT}),
            )
            invalid = valid_soak_summary()
            invalid["duration_seconds"] = 60
            invalid["route_counts"] = {"direct": 0, "relay": 1}
            summary = write(directory / "private-summary.json", json.dumps(invalid))

            with self.assertRaises(PublicInternetEvidenceError):
                build_soak_report(
                    preflight_path=preflight,
                    verifier_path=verifier,
                    private_summary_path=summary,
                    preset="2h",
                )


if __name__ == "__main__":
    unittest.main()
