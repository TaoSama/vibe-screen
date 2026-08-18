from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
OPERATIONS = ROOT / "docs/changes/2026-08-04-phase-3-secure-internet/OPERATIONS.md"
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
            "accepted coturn usage into the control-plane daily-byte ledger",
            "production end-to-end enforcement remain release gates",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_operations_keeps_authority_release_boundaries_open(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")

        self.assertIn("Relay credential\nadmission now delegates to the authority", text)
        self.assertIn("Authority owns coturn usage/reconciliation APIs", text)
        self.assertIn(
            "Relay credential admission is wired to the authority; coturn exporter\n"
            "  reconciliation and active-allocation disconnect are not production proven",
            text,
        )
        self.assertIn("Do not expose it to the public Internet", text)

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
