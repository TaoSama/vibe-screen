from __future__ import annotations

import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
OPERATIONS = ROOT / "docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md"
AUTHORITY_README = ROOT / "services/authority/README.md"
RELAY_README = ROOT / "services/relay/README.md"
SIGNALING_README = ROOT / "services/signaling/README.md"
DEPLOY_README = ROOT / "deploy/phase3/README.md"
AUTHORITY_PRODUCTION_COMPOSE = ROOT / "deploy/phase3/docker-compose.authority.production.yml"
SIGNALING_PRODUCTION_COMPOSE = ROOT / "deploy/phase3/docker-compose.production.yml"
SIGNALING_PRODUCTION_CONFIG = ROOT / "deploy/phase3/config/signaling.production.example.json"


def service_section(text: str, name: str) -> str:
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    "):
            end = index
            break
    return "\n".join(lines[start:end])


class AuthorityProductionGateTests(unittest.TestCase):
    def test_readme_keeps_phase3_release_gates_open(self) -> None:
        text = README.read_text(encoding="utf-8")

        for phrase in (
            "Not proved:\npublic Internet, real remote TURN",
            "network handoff, and soak",
            "public NAT/TURN deployment",
            "remain release gates rather than shipped\nfeatures",
            "Signaling now has a PostgreSQL-backed routing store",
            "local\ncross-instance contract coverage",
            "do not prove a production multi-replica rollout",
            "Relay credential\nadmission is wired to Authority",
            "accepted coturn usage\ninto the control-plane daily-byte ledger",
            "structured coturn reconcile helper\ncan fail closed",
            "production end-to-end enforcement remain release gates",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_operations_keeps_authority_release_boundaries_open(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")

        self.assertIn("Relay credential\nadmission now delegates to the authority", text)
        self.assertIn("Authority owns coturn usage/reconciliation APIs", text)
        self.assertIn("structured reconcile\n  helper is locally tested", text)
        self.assertIn(
            "coturn exporter, scheduled reconciliation loop,\n"
            "  and active-allocation disconnect are not production proven",
            text,
        )
        self.assertIn("does not remove the public-launch prohibition", text)
        self.assertIn("Do not expose it to the public Internet", text)

    def test_service_readmes_keep_phase3_release_boundaries_open(self) -> None:
        authority = AUTHORITY_README.read_text(encoding="utf-8")
        relay = RELAY_README.read_text(encoding="utf-8")
        signaling = SIGNALING_README.read_text(encoding="utf-8")
        deploy = DEPLOY_README.read_text(encoding="utf-8")

        self.assertIn("does **not** yet contain a production-proven coturn exporter", authority)
        self.assertIn("does not prove a" + "\n" + "production disconnect mechanism", authority)
        self.assertIn("coturn exporter, scheduled" + "\n" + "  reconciliation loop", authority)
        self.assertIn("active-allocation disconnect executor", authority)
        self.assertIn("production" + "\n" + "  coturn enforcement remain open", authority)

        self.assertIn("not authoritative until" + "\n" + "a trusted coturn collector", relay)
        self.assertIn("contract helper only", relay)
        self.assertIn("production exporter, durable" + "\n" + "collector loop", relay)
        self.assertIn("concrete coturn allocation" + "\n" + "termination", relay)

        self.assertIn("coturn exporter," + "\n" + "  reconciliation loop", signaling)
        self.assertIn("active-allocation disconnect path are not production" + "\n" + "  proven", signaling)
        self.assertIn("not actively disconnected", signaling)

        self.assertIn("does not prove production TLS", deploy)
        self.assertIn("public ingress, or multi-node" + "\n" + "behavior", deploy)

    def test_authority_production_compose_fails_closed_without_deployment_inputs(self) -> None:
        text = AUTHORITY_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
        expected_image = (
            "image: $" + "{VIBE_AUTHORITY_IMAGE_REPOSITORY:?set the vibe-authority image repository}"
            "@sha256:$"
            + "{VIBE_AUTHORITY_IMAGE_SHA256:?set the 64-character vibe-authority image digest}"
        )

        self.assertIn(expected_image, text)
        self.assertNotIn("postgres:", text)
        self.assertIn('"127.0.0.1:8091:8091/tcp"', text)
        self.assertEqual(text.count("VIBE_AUTHORITY_DATABASE_TLS_MODE: verify-full"), 2)

        required_secret_vars = (
            "VIBE_AUTHORITY_MIGRATION_DATABASE_URL_FILE",
            "VIBE_AUTHORITY_DATABASE_URL_FILE",
            "VIBE_AUTHORITY_ADMIN_TOKEN_FILE",
            "VIBE_AUTHORITY_SIGNALING_TOKEN_FILE",
            "VIBE_AUTHORITY_RELAY_TOKEN_FILE",
            "VIBE_AUTHORITY_COTURN_TOKEN_FILE",
            "VIBE_AUTHORITY_ROLE_TOKEN_SECRET_FILE",
        )
        for variable in required_secret_vars:
            with self.subTest(variable=variable):
                self.assertIn("$" + "{" + variable + ":?set ", text)

    def test_signaling_production_config_uses_postgres_authority_and_loopback(self) -> None:
        config = json.loads(SIGNALING_PRODUCTION_CONFIG.read_text(encoding="utf-8"))

        self.assertEqual(config["listen_address"], "127.0.0.1:8088")
        self.assertEqual(config["store_backend"], "postgres")
        self.assertEqual(config["authority_mode"], "production_authority")
        self.assertTrue(config["authority_url"].startswith("https://"))

    def test_signaling_production_compose_runs_migration_before_service(self) -> None:
        text = SIGNALING_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
        expected_image = (
            "image: $" + "{VIBE_SIGNALING_IMAGE_REPOSITORY:?set the vibe-signaling image repository}"
            "@sha256:$"
            + "{VIBE_SIGNALING_IMAGE_SHA256:?set the 64-character vibe-signaling image digest}"
        )

        self.assertIn("signaling-migrate:", text)
        self.assertIn(expected_image, text)
        self.assertIn("--migrate", text)
        self.assertIn("/usr/share/vibe-screen/migrations/001_signaling.sql", text)
        signaling = service_section(text, "signaling")
        self.assertIn("depends_on:", signaling)
        self.assertIn("signaling-migrate:", signaling)
        self.assertIn("http://127.0.0.1:8088/readyz", signaling)
        self.assertIn("./config/signaling.production.json", signaling)

    def test_signaling_production_credentials_are_file_backed(self) -> None:
        text = SIGNALING_PRODUCTION_COMPOSE.read_text(encoding="utf-8")
        self.assertIn("VIBE_SIGNALING_DATABASE_URL_FILE: /run/secrets/signaling_database_url", text)
        self.assertIn("VIBE_SIGNALING_ISSUER_TOKEN_FILE: /run/secrets/signaling_issuer_token", text)
        self.assertIn("VIBE_SIGNALING_METRICS_TOKEN_FILE: /run/secrets/signaling_metrics_token", text)
        self.assertIn("VIBE_SIGNALING_AUTHORITY_TOKEN_FILE: /run/secrets/signaling_authority_token", text)
        self.assertIn("VIBE_SIGNALING_MIGRATION_DATABASE_URL_FILE", text)
        self.assertIn("VIBE_SIGNALING_DATABASE_URL_FILE", text)
        self.assertIn("VIBE_SIGNALING_ISSUER_TOKEN_FILE", text)
        self.assertIn("VIBE_SIGNALING_METRICS_TOKEN_FILE", text)
        self.assertIn("VIBE_SIGNALING_AUTHORITY_TOKEN_FILE", text)
        self.assertNotRegex(text, re.compile(r"VIBE_SIGNALING_DATABASE_URL:\s*postgres", re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
