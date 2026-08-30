import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "phase3" / "docker-compose.production.yml"
CONFIG = ROOT / "deploy" / "phase3" / "config" / "relay.production.example.json"


def service_section(text, name):
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break
    return " ".join(lines[start:end])


class RelayProductionProfileStaticTests(unittest.TestCase):
    def test_relay_production_config_uses_postgres_fail_closed_storage(self):
        config = json.loads(CONFIG.read_text())
        self.assertEqual(config["storage_backend"], "postgres")
        self.assertEqual(config["maximum_database_clock_skew_seconds"], 5)
        self.assertNotIn("state_file", config)
        self.assertEqual(
            config["allocation_registry_file"],
            "/var/lib/vibe-coturn/allocation-registry.json",
        )

    def test_relay_production_compose_runs_migration_before_service(self):
        compose = COMPOSE.read_text()
        self.assertIn("relay-migrate:", compose)
        self.assertIn("--migrate", compose)
        self.assertIn("/usr/share/vibe-screen/migrations/001_relay.sql", compose)
        relay = service_section(compose, "relay")
        self.assertIn("depends_on:", relay)
        self.assertIn("relay-migrate:", relay)

    def test_relay_production_database_credentials_are_file_backed_and_tls_verified(self):
        compose = COMPOSE.read_text()
        self.assertIn("VIBE_RELAY_DATABASE_URL_FILE: /run/secrets/relay_database_url", compose)
        self.assertIn("VIBE_RELAY_DATABASE_TLS_MODE: verify-full", compose)
        self.assertIn("VIBE_RELAY_MIGRATION_DATABASE_URL_FILE", compose)
        self.assertIn("VIBE_RELAY_DATABASE_URL_FILE", compose)
        self.assertNotRegex(compose, re.compile(r"VIBE_RELAY_DATABASE_URL:\s*postgres", re.MULTILINE))

    def test_relay_production_profile_does_not_use_local_state_volume(self):
        compose = COMPOSE.read_text()
        self.assertNotIn("relay-data", compose)
        self.assertNotIn(":/data", compose)
        self.assertIn("source: ${VIBE_COTURN_ALLOCATION_REGISTRY_DIR:-./coturn-state}", compose)
        self.assertIn("target: /var/lib/vibe-coturn", compose)
        self.assertIn("create_host_path: false", compose)
        self.assertIn("--healthcheck", compose)
        self.assertIn("http://127.0.0.1:8090/readyz", compose)
        self.assertIn("${VIBE_RELAY_CONFIG_FILE:-./config/relay.production.json}:/etc/vibe-relay/config.json:ro", compose)

    def test_relay_production_registry_state_is_ignored_and_precreated(self):
        gitignore = (ROOT / "deploy" / "phase3" / ".gitignore").read_text()
        readme = (ROOT / "deploy" / "phase3" / "README.md").read_text()
        self.assertIn("/coturn-state/", gitignore)
        self.assertIn("create_host_path: false", readme)
        self.assertIn("writable by relay UID/GID `65532`", readme)

    def test_relay_production_profile_does_not_claim_coturn_reconcile_worker(self):
        compose = COMPOSE.read_text()
        self.assertNotIn("coturn-reconcile", compose)
        self.assertNotIn("coturn_reconcile.py", compose)
        self.assertNotIn("coturn-exporter", compose)
        self.assertNotIn("coturn-disconnect", compose)
        self.assertNotRegex(
            compose,
            re.compile(r"(?m)^  (collector|exporter|reconciler|disconnect-executor):$"),
        )


if __name__ == "__main__":
    unittest.main()
