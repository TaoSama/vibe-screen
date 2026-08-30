from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from scripts.phase3.public_nat_turn_preflight import (
    BLOCKED_RESULT,
    CONNECTIVITY_SCHEMA,
    DEPLOYMENT_SCHEMA,
    PASS_RESULT,
    SCHEMA,
    PreflightError,
    build_report,
    main,
    parse_turn_uri,
    parse_arguments,
    require_public_host,
    read_json,
    validate_coturn_config,
    validate_deployment_evidence,
    validate_external_ip,
    validate_tls_identity,
)


_REAL_SUBPROCESS_RUN = subprocess.run


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
            "no-cli",
            "no-tlsv1",
            "no-tlsv1_1",
            "cert=/run/secrets/tls_certificate",
            "pkey=/run/secrets/tls_private_key",
            "min-port=49152",
            "max-port=65535",
            "total-quota=1000",
            "user-quota=12",
            "max-bps=20000000",
            "denied-peer-ip=0.0.0.0-0.255.255.255",
            "denied-peer-ip=10.0.0.0-10.255.255.255",
            "denied-peer-ip=100.64.0.0-100.127.255.255",
            "denied-peer-ip=127.0.0.0-127.255.255.255",
            "denied-peer-ip=169.254.0.0-169.254.255.255",
            "denied-peer-ip=172.16.0.0-172.31.255.255",
            "denied-peer-ip=192.0.0.0-192.0.0.255",
            "denied-peer-ip=192.0.2.0-192.0.2.255",
            "denied-peer-ip=192.168.0.0-192.168.255.255",
            "denied-peer-ip=198.18.0.0-198.19.255.255",
            "denied-peer-ip=198.51.100.0-198.51.100.255",
            "denied-peer-ip=203.0.113.0-203.0.113.255",
            "denied-peer-ip=240.0.0.0-255.255.255.255",
            "denied-peer-ip=::",
            "denied-peer-ip=::1",
            "denied-peer-ip=::ffff:0:0-::ffff:ffff:ffff",
            "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "denied-peer-ip=fec0::-feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            extra,
        ]
    )


def fake_private_key_fixture() -> str:
    return "-----BEGIN " + "PRIVATE KEY-----\nredacted\n-----END " + "PRIVATE KEY-----\n"


def write_tls_pair(directory: Path, common_name: str = "relay.production.invalidname.net", *, add_san: bool = True) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / "privkey.pem"
    certificate = directory / "fullchain.pem"
    command = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        f"/CN={common_name}",
    ]
    if add_san:
        command.extend(["-addext", f"subjectAltName=DNS:{common_name}"])
    command.extend(["-keyout", str(key), "-out", str(certificate)])
    completed = _REAL_SUBPROCESS_RUN(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    key.chmod(0o600)
    certificate.chmod(0o644)
    return certificate, key


def fake_canary_run(_command, **_kwargs):
    return subprocess.CompletedProcess(
        ["external-canary"],
        0,
        stdout=json.dumps(valid_connectivity_evidence()),
        stderr="",
    )


def fake_bearer_header_fixture() -> str:
    return "Authorization: " + "Bearer fixture-not-a-real-token"


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


def valid_deployment_evidence() -> dict[str, object]:
    return {
        "schema": DEPLOYMENT_SCHEMA,
        "result": PASS_RESULT,
        "public_stun_endpoint_observed": True,
        "public_turn_udp_tcp_observed": True,
        "public_turn_tls_observed": True,
        "tls_certificate_hostname_valid": True,
        "tls_minimum_version_observed": True,
        "credential_rotation_observed": True,
        "old_credential_rejected_after_ttl": True,
        "quota_enforcement_observed": True,
        "monitoring_dashboards_observed": True,
        "alert_rules_observed": True,
        "remote_observer_outside_host_network": True,
        "real_remote_peer_path": True,
        "local_coturn_loopback": False,
        "synthetic_peer": False,
        "public_endpoints": {
            "stun": {"host": "stun.production.invalidname.net", "port": 3478},
            "turn": {"host": "relay.production.invalidname.net", "ports": [3478]},
            "turns": {"host": "relay.production.invalidname.net", "port": 5349},
        },
        "tls": {"minimum_version": "TLS1.3", "certificate_expires_in_days": 30},
        "quotas": {
            "credential_requests_per_minute": 12,
            "max_concurrent_sessions_per_device": 2,
            "daily_bytes_per_device": 20 * 1024 * 1024 * 1024,
        },
        "credential_rotation": {
            "new_credential_ttl_seconds": 600,
            "old_credential_rejected_after_ttl": True,
        },
        "monitoring": {
            "allocation_metrics": True,
            "auth_failure_metrics": True,
            "relay_byte_metrics": True,
            "quota_decision_metrics": True,
            "canary_history_count": 3,
        },
        "remote_observers": [
            {"outside_host_network": True, "observed_relay_candidate": True},
            {"outside_host_network": True, "observed_relay_candidate": True},
        ],
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
            "operator_paths_recorded": False,
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
        for host in (
            "127.0.0.1",
            "10.0.0.1",
            "relay.example.com",
            "relay.local",
            "::",
            "fec0::1",
            "224.0.0.1",
            "240.0.0.1",
            "255.255.255.255",
            "ff02::1",
            "::ffff:0a00:0005",
        ):
            with self.subTest(host=host):
                with self.assertRaises(PreflightError):
                    require_public_host(host, resolve=False)

    def test_public_host_allows_global_ipv4_mapped_dotted_literal(self) -> None:
        self.assertEqual(("::ffff:8.8.8.8",), require_public_host("::ffff:8.8.8.8", resolve=False))

    def test_external_ip_rejects_non_public_and_non_dotted_ipv4_mapped_values(self) -> None:
        for external_ip in (
            "/10.0.0.5",
            "::",
            "fec0::1",
            "224.0.0.1",
            "240.0.0.1",
            "255.255.255.255",
            "ff02::1",
            "::ffff:0a00:0005",
            "::FFFF:0A00:0005",
            "::0:ffff:0a00:0005",
            "0:0:0:0:0:ffff:0a00:0005",
            "8.8.8.8/",
            "8.8.8.8//10.0.0.5",
            "8.8.8.8/10.0.0.5/1",
            "8.8.8.8/999.999.999.999",
        ):
            with self.subTest(external_ip=external_ip):
                with self.assertRaises(PreflightError):
                    validate_external_ip(external_ip)

    def test_external_ip_allows_global_ipv6_with_ffff_group_and_dotted_mapping(self) -> None:
        for external_ip in ("2606:4700:ffff::1", "2001:4860:4860:ffff::1", "::ffff:8.8.8.8", "8.8.8.8/10.0.0.5"):
            with self.subTest(external_ip=external_ip):
                self.assertRegex(validate_external_ip(external_ip), r"^[0-9a-f]{64}$")

    def test_coturn_config_requires_production_hardening_controls(self) -> None:
        for required_line in ("no-cli", "no-tlsv1", "no-tlsv1_1"):
            with self.subTest(required_line=required_line):
                config = valid_coturn_config().replace(f"{required_line}\n", "")
                with tempfile.TemporaryDirectory() as directory_name:
                    path = write(Path(directory_name) / "production.conf", config)
                    with self.assertRaisesRegex(PreflightError, "required TLS/auth lines"):
                        validate_coturn_config(path)

    def test_coturn_config_requires_complete_private_peer_deny_list(self) -> None:
        config = valid_coturn_config().replace("denied-peer-ip=203.0.113.0-203.0.113.255\n", "")
        with tempfile.TemporaryDirectory() as directory_name:
            path = write(Path(directory_name) / "production.conf", config)
            with self.assertRaisesRegex(PreflightError, "private peer denies"):
                validate_coturn_config(path)

    def test_tls_identity_requires_turn_realm_hostname_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            certificate, private_key = write_tls_pair(Path(directory_name), "other.production.invalidname.net")
            with self.assertRaisesRegex(PreflightError, "SAN/CN does not match"):
                validate_tls_identity(certificate, private_key, "relay.production.invalidname.net")

    def test_tls_identity_accepts_matching_common_name_when_san_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            certificate, private_key = write_tls_pair(
                Path(directory_name),
                "relay.production.invalidname.net",
                add_san=False,
            )

            result = validate_tls_identity(certificate, private_key, "relay.production.invalidname.net")

        self.assertTrue(result["tls_certificate_hostname_matched"])
        self.assertTrue(result["tls_key_pair_matched"])

    def test_tls_identity_requires_certificate_private_key_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            certificate, _private_key = write_tls_pair(directory / "first")
            _other_certificate, other_private_key = write_tls_pair(directory / "second")
            with self.assertRaisesRegex(PreflightError, "private key do not match"):
                validate_tls_identity(certificate, other_private_key, "relay.production.invalidname.net")

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

    def test_read_json_unicode_error_detail_omits_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            broken = Path(directory_name) / "sensitive-path-connectivity.json"
            broken.write_bytes(b"{\xff")

            with self.assertRaises(PreflightError) as context:
                read_json(broken, "public NAT/TURN connectivity evidence")

        detail = str(context.exception)
        self.assertIn("UnicodeDecodeError", detail)
        self.assertNotIn(directory_name, detail)
        self.assertNotIn("sensitive-path-connectivity.json", detail)

    def test_coturn_unicode_error_detail_omits_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            broken = Path(directory_name) / "sensitive-production.conf"
            broken.write_bytes(b"\xff")

            with self.assertRaises(PreflightError) as context:
                validate_coturn_config(broken)

        detail = str(context.exception)
        self.assertIn("coturn production configuration is not readable", detail)
        self.assertNotIn(directory_name, detail)
        self.assertNotIn("sensitive-production.conf", detail)

    def test_connectivity_command_help_warns_about_remainder_ordering(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as context, redirect_stdout(stdout):
            parse_arguments(["--help"])

        self.assertEqual(context.exception.code, 0)
        self.assertIn("consumes all following arguments", stdout.getvalue())
        self.assertIn("--output and other preflight flags before", stdout.getvalue())
        self.assertIn("--connectivity-command", stdout.getvalue())
        self.assertEqual(
            parse_arguments(["--output", "out.json", "--connectivity-command", "canary", "--flag"]).connectivity_command,
            ["canary", "--flag"],
        )
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            parse_arguments(["--connectivity-command", "canary", "--output", "out.json"])

    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_missing_runtime_deployment_inputs_block_preflight(self, getaddrinfo, urlopen) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            tls_certificate, tls_private_key = write_tls_pair(directory)
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8/10.0.0.5",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], PASS_RESULT)
        self.assertEqual(report["limitations"], [])
        self.assertEqual(report["connectivity"]["reviewed_evidence"]["packets_received"], 5)
        self.assertEqual(report["connectivity"]["canary_evidence"]["packets_received"], 5)
        self.assertEqual(report["deployment"]["remote_observer_count"], 2)
        self.assertEqual(report["deployment"]["tls"]["minimum_version"], "TLS1.3")
        self.assertFalse(report["privacy"]["raw_endpoints_recorded"])
        self.assertNotIn("relay.production.invalidname.net", json.dumps(report))

    @mock.patch("scripts.phase3.public_nat_turn_preflight.subprocess.run")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_missing_deployment_evidence_blocks_preflight(self, getaddrinfo, urlopen, run) -> None:
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8/10.0.0.5",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertEqual(failed, {"deployment_evidence"})

    @mock.patch("scripts.phase3.public_nat_turn_preflight.subprocess.run")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.request.urlopen")
    @mock.patch("scripts.phase3.public_nat_turn_preflight.socket.getaddrinfo")
    def test_deployment_rotation_monitoring_and_remote_observers_are_required(self, getaddrinfo, urlopen, run) -> None:
        getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 0))]
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        run.return_value = subprocess.CompletedProcess(
            ["external-canary"],
            0,
            stdout=json.dumps(valid_connectivity_evidence()),
            stderr="",
        )
        deployment = valid_deployment_evidence()
        deployment["credential_rotation_observed"] = False
        deployment["monitoring"]["relay_byte_metrics"] = False  # type: ignore[index]
        deployment["remote_observers"] = [deployment["remote_observers"][0]]  # type: ignore[index]
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8/10.0.0.5",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                deployment_evidence=write(directory / "deployment.json", json.dumps(deployment)),
                resolve_dns=True,
                timeout_seconds=1,
            )

        self.assertEqual(report["result"], BLOCKED_RESULT)
        failed = {check["name"] for check in report["checks"] if check["result"] == BLOCKED_RESULT}
        self.assertEqual(failed, {"deployment_evidence"})

    def test_deployment_evidence_rejects_secret_like_fields_before_evaluation(self) -> None:
        deployment = valid_deployment_evidence()
        deployment["turn_password"] = "<redacted>"
        with tempfile.TemporaryDirectory() as directory_name:
            path = write(Path(directory_name) / "deployment.json", json.dumps(deployment))
            with self.assertRaisesRegex(PreflightError, "secret-like"):
                validate_deployment_evidence(path, resolve_dns=False)

        deployment = valid_deployment_evidence()
        deployment["notes"] = fake_bearer_header_fixture()
        with tempfile.TemporaryDirectory() as directory_name:
            path = write(Path(directory_name) / "deployment.json", json.dumps(deployment))
            with self.assertRaisesRegex(PreflightError, "secret material"):
                validate_deployment_evidence(path, resolve_dns=False)

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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(connectivity)),
                connectivity_command=None,
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=["external-canary"],
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(valid_relay_config())),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(config)),
                coturn_config=write(directory / "production.conf", valid_coturn_config("user-quota=1")),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://authority.production.invalidname.net/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
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
            tls_certificate, tls_private_key = write_tls_pair(directory)
            report = build_report(
                relay_config=write(directory / "relay.json", json.dumps(config)),
                coturn_config=write(directory / "production.conf", valid_coturn_config()),
                turn_secret_file=write(directory / "turn-secret", "x" * 32),
                tls_certificate=tls_certificate,
                tls_private_key=tls_private_key,
                coturn_external_ip="8.8.8.8",
                authority_ready_url="https://10.0.0.6/readyz",
                relay_ready_url="https://relay.production.invalidname.net/readyz",
                connectivity_evidence=write(directory / "connectivity.json", json.dumps(valid_connectivity_evidence())),
                connectivity_command=None,
                deployment_evidence=write(directory / "deployment.json", json.dumps(valid_deployment_evidence())),
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
