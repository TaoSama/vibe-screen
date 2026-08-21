from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/phase3"
RELAY_PRODUCTION_COMPOSE = DEPLOY / "docker-compose.production.yml"
AUTHORITY_PRODUCTION_COMPOSE = DEPLOY / "docker-compose.authority.production.yml"
RELAY_PRODUCTION_CONFIG = DEPLOY / "config/relay.production.example.json"
AUTHORITY_PRODUCTION_CONFIG = DEPLOY / "config/authority.production.example.json"
COTURN_PRODUCTION_CONFIG = DEPLOY / "coturn/production.conf"
COTURN_RECONCILER_DOCKERFILE = DEPLOY / "coturn-reconciler.Dockerfile"

PROHIBITED_RELAY_BUILD_MARKERS = (
    "build:",
    "context: ../../services/relay",
    "dockerfile: Dockerfile",
)
EXPECTED_RELAY_SECRET_FILES = (
    "VIBE_RELAY_TURN_SECRET_FILE: /run/secrets/turn_secret",
    "VIBE_RELAY_CLIENT_TOKEN_FILE: /run/secrets/client_token",
    "VIBE_RELAY_USAGE_TOKEN_FILE: /run/secrets/usage_token",
    "VIBE_RELAY_METRICS_TOKEN_FILE: /run/secrets/metrics_token",
    "VIBE_RELAY_ADMIN_TOKEN_FILE: /run/secrets/admin_token",
    "VIBE_RELAY_AUTHORITY_TOKEN_FILE: /run/secrets/authority_token",
)
EXPECTED_COTURN_DENIES = {
    "denied-peer-ip=0.0.0.0-0.255.255.255",
    "denied-peer-ip=10.0.0.0-10.255.255.255",
    "denied-peer-ip=100.64.0.0-100.127.255.255",
    "denied-peer-ip=127.0.0.0-127.255.255.255",
    "denied-peer-ip=169.254.0.0-169.254.255.255",
    "denied-peer-ip=172.16.0.0-172.31.255.255",
    "denied-peer-ip=192.0.0.0-192.0.0.255",
    "denied-peer-ip=192.168.0.0-192.168.255.255",
    "denied-peer-ip=198.18.0.0-198.19.255.255",
    "denied-peer-ip=::ffff:0:0-::ffff:ffff:ffff",
    "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fec0::-feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def non_comment_coturn_lines() -> set[str]:
    return {
        line.strip()
        for line in read(COTURN_PRODUCTION_CONFIG).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def service_section(text: str, name: str) -> str:
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break
    return "\n".join(lines[start:end])


class ProductionProfileStaticTests(unittest.TestCase):
    def test_relay_production_profile_requires_immutable_image(self) -> None:
        compose = read(RELAY_PRODUCTION_COMPOSE)

        expected_images = {
            "relay-migrate": r"\$\{VIBE_RELAY_IMAGE_REPOSITORY:\?[^}]+}"
            r"@sha256:\$\{VIBE_RELAY_IMAGE_SHA256:\?[^}]+}",
            "relay": r"\$\{VIBE_RELAY_IMAGE_REPOSITORY:\?[^}]+}"
            r"@sha256:\$\{VIBE_RELAY_IMAGE_SHA256:\?[^}]+}",
            "coturn": r"coturn/coturn:[^\s]+@sha256:[0-9a-f]{64}",
        }
        for service, image in expected_images.items():
            with self.subTest(service=service):
                self.assertRegex(compose, rf"(?ms)^  {service}:\n(?:    .+\n)*?    image: {image}$")
        for marker in PROHIBITED_RELAY_BUILD_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, compose)
        self.assertIn("network_mode: host", compose)
        for secret_file in EXPECTED_RELAY_SECRET_FILES:
            with self.subTest(secret_file=secret_file):
                self.assertIn(secret_file, compose)
        self.assertIn("./config/relay.production.json:/etc/vibe-relay/config.json:ro", compose)

    def test_authority_production_profile_requires_digest_tls_and_loopback_http(self) -> None:
        compose = read(AUTHORITY_PRODUCTION_COMPOSE)

        self.assertRegex(
            compose,
            r"image: \$\{VIBE_AUTHORITY_IMAGE_REPOSITORY:\?[^}]+}"
            r"@sha256:\$\{VIBE_AUTHORITY_IMAGE_SHA256:\?[^}]+}",
        )
        self.assertIn("VIBE_AUTHORITY_DATABASE_TLS_MODE: verify-full", compose)
        self.assertIn("VIBE_AUTHORITY_DATABASE_URL_FILE: /run/secrets/database_url", compose)
        self.assertIn("VIBE_AUTHORITY_SIGNALING_TOKEN_FILE: /run/secrets/signaling_token", compose)
        self.assertIn('"127.0.0.1:8091:8091/tcp"', compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertNotIn("build:", compose)

    def test_coturn_production_profile_keeps_fail_closed_network_policy(self) -> None:
        lines = non_comment_coturn_lines()

        self.assertTrue(EXPECTED_COTURN_DENIES.issubset(lines))
        allowed_peer_lines = sorted(line for line in lines if line.startswith("allowed-peer-ip="))
        self.assertEqual([], allowed_peer_lines)
        self.assertNotIn("no-auth", lines)
        self.assertIn("use-auth-secret", lines)
        self.assertIn("fingerprint", lines)
        self.assertIn("no-multicast-peers", lines)
        self.assertNotIn("no-cli", lines)
        self.assertIn("cli", lines)
        self.assertIn("cli-ip=127.0.0.1", lines)
        self.assertIn("cli-port=5766", lines)
        self.assertFalse(any(line.startswith("cli-password=") for line in lines))
        self.assertIn("no-tlsv1", lines)
        self.assertIn("no-tlsv1_1", lines)
        self.assertIn("tls-listening-port=5349", lines)
        self.assertIn("cert=/run/secrets/tls_certificate", lines)
        self.assertIn("pkey=/run/secrets/tls_private_key", lines)
        self.assertIn("min-port=49152", lines)
        self.assertIn("max-port=65535", lines)
        self.assertIn("user-quota=12", lines)
        self.assertIn("total-quota=1000", lines)
        self.assertIn("max-bps=20000000", lines)

    def test_relay_production_example_remains_public_and_bounded(self) -> None:
        config = json.loads(read(RELAY_PRODUCTION_CONFIG))

        self.assertEqual(config["listen_address"], "127.0.0.1:8090")
        self.assertEqual(config["turn_realm"], "relay.example.com")
        self.assertEqual(
            config["turn_uris"],
            [
                "turn:relay.example.com:3478?transport=udp",
                "turn:relay.example.com:3478?transport=tcp",
                "turns:relay.example.com:5349?transport=tcp",
            ],
        )
        self.assertLessEqual(config["credential_ttl_seconds"], 600)
        self.assertLessEqual(config["max_credential_ttl_seconds"], 1800)
        self.assertLessEqual(config["max_concurrent_sessions_per_device"], 2)
        self.assertLessEqual(config["daily_bytes_per_device"], 20 * 1024 * 1024 * 1024)
        self.assertEqual(config["state_file"], "/data/relay-state.json")
        self.assertEqual(config["allocation_registry_file"], "/var/lib/vibe-coturn/allocation-registry.json")

    def test_authority_production_example_keeps_short_session_and_reconciliation_bounds(self) -> None:
        config = json.loads(read(AUTHORITY_PRODUCTION_CONFIG))

        self.assertEqual(config["listen_address"], "0.0.0.0:8091")
        self.assertLessEqual(config["maximum_session_ttl_seconds"], 900)
        self.assertLessEqual(config["daily_bytes_per_device"], 20 * 1024 * 1024 * 1024)
        self.assertLessEqual(config["maximum_allocations_per_device"], 2)
        self.assertLessEqual(config["reconciliation_grace_seconds"], 120)

    def test_production_compose_does_not_embed_secret_values(self) -> None:
        combined = "\n".join(
            (
                read(RELAY_PRODUCTION_COMPOSE),
                read(AUTHORITY_PRODUCTION_COMPOSE),
            )
        )

        self.assertNotRegex(
            combined,
            re.compile(r"(?i)(bearer|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{32,}"),
        )
        self.assertIn("_FILE:", combined)
        self.assertIn("file: ./secrets/turn_secret.txt", combined)
        self.assertIn("file: ./secrets/coturn_cli_password.txt", combined)
        self.assertIn("file: ${VIBE_AUTHORITY_DATABASE_URL_FILE", combined)

    def test_coturn_reconciler_is_digest_pinned_and_fail_closed(self) -> None:
        compose = read(RELAY_PRODUCTION_COMPOSE)
        dockerfile = read(COTURN_RECONCILER_DOCKERFILE)

        self.assertRegex(
            compose,
            r"(?ms)^  coturn-reconciler:\n(?:    .+\n)*?    image: "
            r"\$\{VIBE_COTURN_RECONCILER_IMAGE_REPOSITORY:\?[^}]+\}"
            r"@sha256:\$\{VIBE_COTURN_RECONCILER_IMAGE_SHA256:\?[^}]+\}$",
        )
        self.assertIn("VIBE_COTURN_SOURCE_ID: ${VIBE_COTURN_SOURCE_ID:?set the Authority coturn source ID}", compose)
        self.assertIn("VIBE_COTURN_ALLOCATION_REGISTRY: /var/lib/vibe-coturn/allocation-registry.json", compose)
        self.assertIn("VIBE_COTURN_SEQUENCE_STATE: /var/lib/vibe-coturn/reconcile-sequence.json", compose)
        self.assertIn("VIBE_COTURN_CLI_PASSWORD_FILE: /run/secrets/coturn_cli_password", compose)
        self.assertIn("--exporter-command", compose)
        self.assertIn("coturn_cli_control.py", compose)
        self.assertIn("--disconnect-command", compose)
        self.assertIn("authority_coturn_token", compose)
        reconciler = service_section(compose, "coturn-reconciler")
        self.assertIn("no-new-privileges:true", reconciler)
        self.assertIn("read_only: true", reconciler)
        self.assertNotIn("../../scripts/phase3:/opt/vibe/scripts", reconciler)
        self.assertIn("ARG PYTHON_BASE_IMAGE", dockerfile)
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", dockerfile)
        self.assertIn("@sha256:[0-9a-f]{64}", dockerfile)
        self.assertNotRegex(dockerfile, re.compile(r"(?m)^FROM [^$].*:[^@\s]+$"))


if __name__ == "__main__":
    unittest.main()
