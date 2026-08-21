from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
OPERATIONS = ROOT / "docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md"
AUTHORITY_README = ROOT / "services/authority/README.md"
RELAY_README = ROOT / "services/relay/README.md"
SIGNALING_README = ROOT / "services/signaling/README.md"
DEPLOY_README = ROOT / "deploy/phase3/README.md"
AUTHORITY_PRODUCTION_COMPOSE = ROOT / "deploy/phase3/docker-compose.authority.production.yml"


class AuthorityProductionGateTests(unittest.TestCase):
    def test_readme_keeps_phase3_release_gates_open(self) -> None:
        text = README.read_text(encoding="utf-8")

        for phrase in (
            "Not proved:\npublic Internet, real remote TURN",
            "network handoff, and soak",
            "public NAT/TURN deployment",
            "remain release gates rather than shipped\nfeatures",
            "Relay credential admission is wired to Authority",
            "Authority can debit accepted\ncoturn usage into the control-plane daily-byte ledger",
            "relay now writes the\nallocation registry consumed by the coturn CLI exporter/disconnect worker",
            "bounded production Compose worker can fail closed",
            "durable\nmulti-node scheduling/WAL",
            "provider billing reconciliation",
            "production\nend-to-end enforcement remain release gates",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_operations_keeps_authority_release_boundaries_open(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")

        self.assertIn("Relay credential\nadmission now delegates to the authority", text)
        self.assertIn("Authority owns coturn usage/reconciliation APIs", text)
        self.assertIn(
            "`coturn_cli_control.py` is the\n"
            "minimal bundled coturn CLI exporter/disconnect command",
            text,
        )
        self.assertIn(
            "The production Compose profile runs those commands\n"
            "in a bounded worker",
            text,
        )
        self.assertIn("does not remove the public-launch prohibition", text)
        self.assertIn("not production-proven, has no durable scheduler/WAL", text)
        self.assertIn("Do not expose it to the public Internet", text)

    def test_service_readmes_keep_phase3_release_boundaries_open(self) -> None:
        authority = AUTHORITY_README.read_text(encoding="utf-8")
        relay = RELAY_README.read_text(encoding="utf-8")
        signaling = SIGNALING_README.read_text(encoding="utf-8")
        deploy = DEPLOY_README.read_text(encoding="utf-8")

        self.assertIn("minimal coturn CLI exporter and disconnect" + "\n" + "executor", authority)
        self.assertIn("Missing registry entries, duplicate or ambiguous username", authority)
        self.assertIn("production Compose profile wires" + "\n" + "that helper", authority)
        self.assertIn("no durable WAL or multi-node scheduler\nproof", authority)
        self.assertIn("end-to-end data-plane kill gate remains open", authority)

        self.assertIn("allocation_registry_file", relay)
        self.assertIn("Registry write or identity-conflict failure" + "\n" + "returns `503`", relay)
        self.assertIn("minimal single-node" + "\n" + "coturn CLI path", relay)
        self.assertIn("multi-node registry coordination", relay)

        self.assertIn("coturn CLI exporter", signaling)
        self.assertIn("bounded reconciliation/disconnect worker", signaling)
        self.assertIn("durable multi-node scheduling/WAL remains open", signaling)
        self.assertIn("end-to-end production revocation path remains unproved", signaling)

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


if __name__ == "__main__":
    unittest.main()
