from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/phase3"
RELAY_LOCAL_COMPOSE = DEPLOY / "docker-compose.yml"
RELAY_PRODUCTION_COMPOSE = DEPLOY / "docker-compose.production.yml"
AUTHORITY_LOCAL_COMPOSE = DEPLOY / "docker-compose.authority.yml"
AUTHORITY_PRODUCTION_COMPOSE = DEPLOY / "docker-compose.authority.production.yml"
RELAY_PRODUCTION_CONFIG = DEPLOY / "config/relay.production.example.json"
AUTHORITY_PRODUCTION_CONFIG = DEPLOY / "config/authority.production.example.json"
COTURN_PRODUCTION_CONFIG = DEPLOY / "coturn/production.conf"
START_COTURN = DEPLOY / "scripts/start-coturn.sh"
GENERATE_RELAY_SECRETS = DEPLOY / "scripts/generate-secrets.sh"
GENERATE_AUTHORITY_SECRETS = DEPLOY / "scripts/generate-authority-secrets.sh"
TEST_AUTHORITY_STACK = DEPLOY / "scripts/test-authority-stack.sh"

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
    "denied-peer-ip=192.0.2.0-192.0.2.255",
    "denied-peer-ip=192.168.0.0-192.168.255.255",
    "denied-peer-ip=198.18.0.0-198.19.255.255",
    "denied-peer-ip=198.51.100.0-198.51.100.255",
    "denied-peer-ip=203.0.113.0-203.0.113.255",
    "denied-peer-ip=224.0.0.0-239.255.255.255",
    "denied-peer-ip=240.0.0.0-255.255.255.255",
    "denied-peer-ip=0:0:0:0:0:0:0:0-ff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=::ffff:0:0-::ffff:ffff:ffff",
    "denied-peer-ip=64:ff9b::-64:ff9b::ffff:ffff",
    "denied-peer-ip=64:ff9b:1::-64:ff9b:1:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=100::-100::ffff:ffff:ffff:ffff",
    "denied-peer-ip=2001::-2001:1ff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=2001:db8::-2001:db8:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=2002::-2002:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fec0::-feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=ff00::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def non_comment_coturn_lines() -> set[str]:
    return {
        line.strip()
        for line in read(COTURN_PRODUCTION_CONFIG).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def service_section(compose: str, service: str) -> str:
    lines = compose.splitlines()
    try:
        start = lines.index(f"  {service}:")
    except ValueError as error:
        raise AssertionError(f"missing service section: {service}")
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
                self.assertRegex(service_section(compose, service), rf"(?m)^    image: {image}$")
        for marker in PROHIBITED_RELAY_BUILD_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, compose)
        self.assertIn("network_mode: host", compose)
        for secret_file in EXPECTED_RELAY_SECRET_FILES:
            with self.subTest(secret_file=secret_file):
                self.assertIn(secret_file, compose)
        self.assertIn("${VIBE_RELAY_CONFIG_FILE:-./config/relay.production.json}:/etc/vibe-relay/config.json:ro", compose)

    def test_production_app_containers_are_hardened(self) -> None:
        compose = read(RELAY_PRODUCTION_COMPOSE)
        anchor = compose.split("services:", 1)[0]
        self.assertIn("user: \"65532:65532\"", anchor)
        self.assertIn("read_only: true", anchor)
        self.assertIn("cap_drop:\n    - ALL", anchor)
        self.assertIn("no-new-privileges:true", anchor)
        self.assertIn("pids_limit: 128", anchor)
        self.assertIn("mem_limit: 256m", anchor)
        self.assertIn("cpus: 1.0", anchor)
        self.assertIn("tmpfs:\n    - /tmp:size=16m,mode=0700,uid=65532,gid=65532", anchor)
        for service in ("signaling-migrate", "signaling", "relay-migrate", "relay"):
            with self.subTest(service=service):
                self.assertRegex(compose, rf"(?m)^  {service}:\n    <<: \*vibe-service$")
        self.assertIn("start_period: 5s", service_section(compose, "signaling"))
        self.assertIn("start_period: 5s", service_section(compose, "relay"))

    def test_coturn_production_container_is_hardened_and_bounded(self) -> None:
        coturn = service_section(read(RELAY_PRODUCTION_COMPOSE), "coturn")

        self.assertIn("user: \"65532:65532\"", coturn)
        self.assertIn("read_only: true", coturn)
        self.assertIn("cap_drop:\n      - ALL", coturn)
        self.assertIn("no-new-privileges:true", coturn)
        self.assertIn("tmpfs:\n      - /tmp:size=16m,mode=0700,uid=65532,gid=65532", coturn)
        self.assertIn("pids_limit: 256", coturn)
        self.assertIn("mem_limit: 512m", coturn)
        self.assertIn("cpus: 2.0", coturn)

    def test_production_compose_projects_mount_secrets_for_non_root_containers(self) -> None:
        local_combined = "\n".join((read(RELAY_LOCAL_COMPOSE), read(AUTHORITY_LOCAL_COMPOSE)))
        relay_compose = read(RELAY_PRODUCTION_COMPOSE)
        authority_compose = read(AUTHORITY_PRODUCTION_COMPOSE)
        combined = "\n".join((local_combined, relay_compose, authority_compose))

        self.assertIn("phase3-secrets-init:", relay_compose)
        self.assertIn("authority-secrets-init:", authority_compose)
        self.assertIn('user: "0:0"', combined)
        self.assertIn("network_mode: none", combined)
        self.assertIn("cap_add:\n      - CHOWN\n      - DAC_READ_SEARCH", combined)
        self.assertEqual(4, combined.count("- DAC_READ_SEARCH"))
        self.assertNotIn("- DAC_READ_SEARCH", service_section(read(RELAY_LOCAL_COMPOSE), "relay-data-init"))
        for compose_text, service in (
            (read(RELAY_LOCAL_COMPOSE), "relay-secrets-init"),
            (relay_compose, "phase3-secrets-init"),
            (read(AUTHORITY_LOCAL_COMPOSE), "authority-secrets-init"),
            (authority_compose, "authority-secrets-init"),
        ):
            with self.subTest(service=service):
                self.assertIn("cap_add:\n      - CHOWN\n      - DAC_READ_SEARCH", service_section(compose_text, service))
        self.assertEqual(4, combined.count("umask 077"))
        self.assertIn("chmod \"$$mode\" \"$$temporary\"\n          chown \"$$owner\" \"$$temporary\"", relay_compose)
        self.assertIn("chmod 0400 \"$$temporary\"\n          chown 65532:65532 \"$$temporary\"", authority_compose)

        expected_secret_copies = (
            ("signaling_migration_database_url", "/out/signaling-migrate", "0400"),
            ("signaling_database_url", "/out/signaling", "0400"),
            ("signaling_issuer_token", "/out/signaling", "0400"),
            ("signaling_metrics_token", "/out/signaling", "0400"),
            ("signaling_authority_token", "/out/signaling", "0400"),
            ("relay_migration_database_url", "/out/relay-migrate", "0400"),
            ("relay_database_url", "/out/relay", "0400"),
            ("turn_secret", "/out/relay", "0400"),
            ("client_token", "/out/relay", "0400"),
            ("usage_token", "/out/relay", "0400"),
            ("metrics_token", "/out/relay", "0400"),
            ("admin_token", "/out/relay", "0400"),
            ("authority_token", "/out/relay", "0400"),
            ("turn_secret", "/out/coturn", "0400"),
            ("tls_certificate", "/out/coturn", "0444"),
            ("tls_private_key", "/out/coturn", "0400"),
            ("migration_database_url", "/out/migrate", None),
            ("database_url", "/out/authority", None),
            ("admin_token", "/out/authority", None),
            ("signaling_token", "/out/authority", None),
            ("relay_token", "/out/authority", None),
            ("coturn_token", "/out/authority", None),
            ("role_token_secret", "/out/authority", None),
        )
        for secret_name, target_dir, mode in expected_secret_copies:
            with self.subTest(secret_name=secret_name, target_dir=target_dir):
                if mode is None:
                    self.assertIn(f"copy_secret {secret_name} {target_dir} {secret_name}", combined)
                else:
                    self.assertIn(
                        f"copy_secret {secret_name} {target_dir} {secret_name} 65532:65532 {mode}",
                        combined,
                    )

        for volume_mount in (
            "signaling-migrate-runtime-secrets:/run/secrets:ro",
            "signaling-runtime-secrets:/run/secrets:ro",
            "relay-migrate-runtime-secrets:/run/secrets:ro",
            "relay-runtime-secrets:/run/secrets:ro",
            "coturn-runtime-secrets:/run/secrets:ro",
            "authority-migrate-runtime-secrets:/run/secrets:ro",
            "authority-runtime-secrets:/run/secrets:ro",
        ):
            with self.subTest(volume_mount=volume_mount):
                self.assertIn(volume_mount, combined)

    def test_authority_stack_failure_diagnostics_include_secret_initializer(self) -> None:
        script = read(TEST_AUTHORITY_STACK)

        self.assertIn(
            "compose logs --no-color authority-secrets-init authority-migrate authority postgres",
            script,
        )
        self.assertIn("compose logs --no-color authority-secrets-init authority postgres", script)
        self.assertIn("suppressed Authority container diagnostics containing a generated secret", script)

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
        self.assertIn("tmpfs:\n    - /tmp:size=16m,mode=0700,uid=65532,gid=65532", compose)
        self.assertNotIn("build:", compose)

    def test_coturn_production_profile_keeps_fail_closed_network_policy(self) -> None:
        lines = non_comment_coturn_lines()

        self.assertTrue(EXPECTED_COTURN_DENIES.issubset(lines))
        self.assertNotIn("denied-peer-ip=::", lines)
        allowed_peer_lines = sorted(line for line in lines if line.startswith("allowed-peer-ip="))
        self.assertEqual([], allowed_peer_lines)
        self.assertNotIn("no-auth", lines)
        self.assertIn("use-auth-secret", lines)
        self.assertIn("fingerprint", lines)
        self.assertIn("no-multicast-peers", lines)
        self.assertIn("no-cli", lines)
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

    def test_local_secret_generators_create_operator_only_source_files(self) -> None:
        cases = (
            (GENERATE_RELAY_SECRETS, "VIBE_RELAY_SECRETS_DIR", 6),
            (GENERATE_AUTHORITY_SECRETS, "VIBE_AUTHORITY_SECRETS_DIR", 8),
        )
        for script, env_name, expected_count in cases:
            with self.subTest(script=script.name), tempfile.TemporaryDirectory() as directory_name:
                secret_dir = Path(directory_name) / "secrets"
                result = subprocess.run(
                    ["sh", str(script)],
                    env={**os.environ, env_name: str(secret_dir)},
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(secret_dir.stat().st_mode & 0o777, 0o700)
                files = sorted(secret_dir.glob("*.txt"))
                self.assertEqual(len(files), expected_count)
                for secret_file in files:
                    with self.subTest(secret_file=secret_file.name):
                        self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("container-readable", result.stdout)

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
        self.assertEqual(config["authority_source_id"], "<turn-source-id>")
        self.assertNotIn("state_file", config)
        self.assertEqual(
            config["allocation_registry_file"],
            "/var/lib/vibe-coturn/allocation-registry.json",
        )

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
        self.assertIn("file: ${VIBE_AUTHORITY_DATABASE_URL_FILE", combined)

    def test_start_coturn_requires_public_runtime_inputs_for_production_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            secret = directory / "turn-secret.txt"
            secret.write_text("x" * 32, encoding="utf-8")
            secret.chmod(0o600)
            base_environment = {
                "PATH": "/usr/bin:/bin",
                "COTURN_CONFIG_FILE": str(COTURN_PRODUCTION_CONFIG),
                "VIBE_RELAY_TURN_SECRET_FILE": str(secret),
            }

            missing = subprocess.run(
                ["sh", str(START_COTURN)],
                env=base_environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("COTURN_EXTERNAL_IP is required", missing.stderr)

            private_ip = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "10.0.0.5",
                    "COTURN_REALM": "relay.production.example.net",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(private_ip.returncode, 0)
            self.assertIn("public side must be globally routable", private_ip.stderr)

            uppercase_private_ipv6 = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "FC00::1",
                    "COTURN_REALM": "relay.production.example.net",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(uppercase_private_ipv6.returncode, 0)
            self.assertIn("public side must be globally routable", uppercase_private_ipv6.stderr)

            test_realm = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "8.8.8.8",
                    "COTURN_REALM": "relay.test",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(test_realm.returncode, 0)
            self.assertIn("production public DNS hostname", test_realm.stderr)

            mapped_private_ip = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "::ffff:10.0.0.5",
                    "COTURN_REALM": "relay.production.example.net",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(mapped_private_ip.returncode, 0)
            self.assertIn("public side must be globally routable", mapped_private_ip.stderr)

            uppercase_mapped_private_ip = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "::FFFF:10.0.0.5",
                    "COTURN_REALM": "relay.production.example.net",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(uppercase_mapped_private_ip.returncode, 0)
            self.assertIn("public side must be globally routable", uppercase_mapped_private_ip.stderr)

            dotted_placeholder_realm = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "8.8.8.8",
                    "COTURN_REALM": "relay.example.com.",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(dotted_placeholder_realm.returncode, 0)
            self.assertIn("production public DNS hostname", dotted_placeholder_realm.stderr)

            uppercase_placeholder_realm = subprocess.run(
                ["sh", str(START_COTURN)],
                env={
                    **base_environment,
                    "COTURN_EXTERNAL_IP": "8.8.8.8",
                    "COTURN_REALM": "RELAY.EXAMPLE.COM",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(uppercase_placeholder_realm.returncode, 0)
            self.assertIn("production public DNS hostname", uppercase_placeholder_realm.stderr)

    def test_start_coturn_writes_runtime_config_only_after_valid_production_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            bin_directory = directory / "bin"
            bin_directory.mkdir()
            turnserver_log = directory / "turnserver.log"
            fake_turnserver = bin_directory / "turnserver"
            fake_turnserver.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$@\" > \"$TURN_SERVER_LOG\"\n",
                encoding="utf-8",
            )
            fake_turnserver.chmod(0o755)
            secret = directory / "turn-secret.txt"
            secret.write_text("x" * 32, encoding="utf-8")
            secret.chmod(0o600)
            runtime_config = directory / "runtime.conf"
            base_environment = {
                "PATH": f"{bin_directory}:/usr/bin:/bin",
                "COTURN_CONFIG_FILE": str(COTURN_PRODUCTION_CONFIG),
                "COTURN_RUNTIME_CONFIG": str(runtime_config),
                "TURN_SERVER_LOG": str(turnserver_log),
                "VIBE_RELAY_TURN_SECRET_FILE": str(secret),
            }

            def run_start(external_ip: str, realm: str) -> subprocess.CompletedProcess[str]:
                runtime_config.unlink(missing_ok=True)
                turnserver_log.unlink(missing_ok=True)
                return subprocess.run(
                    ["sh", str(START_COTURN)],
                    env={
                        **base_environment,
                        "COTURN_EXTERNAL_IP": external_ip,
                        "COTURN_REALM": realm,
                    },
                    text=True,
                    capture_output=True,
                    check=False,
                )

            rejected_inputs = (
                ("/10.0.0.5", "relay.production.example.net", "public side must be globally routable"),
                ("8.8.8.8/", "relay.production.example.net", "private side must be an IP address"),
                ("8.8.8.8//10.0.0.5", "relay.production.example.net", "single public or public/private IP mapping"),
                ("8.8.8.8/10.0.0.5/1", "relay.production.example.net", "single public or public/private IP mapping"),
                ("8.8.8.8/999.999.999.999", "relay.production.example.net", "private side must be an IP address"),
                ("::", "relay.production.example.net", "public side must be globally routable"),
                ("224.0.0.1", "relay.production.example.net", "public side must be globally routable"),
                ("240.0.0.1", "relay.production.example.net", "public side must be globally routable"),
                ("255.255.255.255", "relay.production.example.net", "public side must be globally routable"),
                ("ff02::1", "relay.production.example.net", "public side must be globally routable"),
                ("FEC0::1", "relay.production.example.net", "public side must be globally routable"),
                ("::ffff:0a00:0005", "relay.production.example.net", "IPv4-mapped public side must use dotted IPv4 notation"),
                ("::0:ffff:0a00:0005", "relay.production.example.net", "IPv4-mapped public side must use dotted IPv4 notation"),
                ("0:0:0:0:0:ffff:0a00:0005", "relay.production.example.net", "IPv4-mapped public side must use dotted IPv4 notation"),
                ("8.8.8.8/::ffff:0a00:0005", "relay.production.example.net", "IPv4-mapped private side must use dotted IPv4 notation"),
                ("192.0.0.1", "relay.production.example.net", "public side must be globally routable"),
                ("8.8.8.8", "relay.lan", "production public DNS hostname"),
                ("8.8.8.8", "relay.home.arpa", "production public DNS hostname"),
            )
            for external_ip, realm, expected_error in rejected_inputs:
                with self.subTest(external_ip=external_ip):
                    result = run_start(external_ip, realm)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertFalse(runtime_config.exists())
                    self.assertFalse(turnserver_log.exists())

            accepted_inputs = (
                "8.8.8.8/10.0.0.5",
                "::ffff:8.8.8.8",
                "2606:4700:ffff::1",
            )
            for external_ip in accepted_inputs:
                with self.subTest(external_ip=external_ip):
                    valid = run_start(external_ip, "RELAY.PRODUCTION.INVALIDNAME.NET.")
                    self.assertEqual(valid.returncode, 0, valid.stderr)
                    self.assertEqual(turnserver_log.read_text(encoding="utf-8"), f"-c\n{runtime_config}\n")
                    config_text = runtime_config.read_text(encoding="utf-8")
                    self.assertIn("static-auth-secret=" + "x" * 32, config_text)
                    self.assertIn(f"external-ip={external_ip.lower()}", config_text)
                    self.assertIn("realm=relay.production.invalidname.net", config_text)


if __name__ == "__main__":
    unittest.main()
