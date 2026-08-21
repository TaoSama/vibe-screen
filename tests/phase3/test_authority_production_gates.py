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


def compact(text: str) -> str:
    return " ".join(text.split())


class AuthorityProductionGateTests(unittest.TestCase):
    def test_readme_keeps_phase3_release_gates_open(self) -> None:
        text = README.read_text(encoding="utf-8")
        normalized = compact(text)

        for phrase in (
            "Not proved: public Internet, real remote TURN",
            "network handoff, and soak",
            "public NAT/TURN deployment",
            "remain release gates rather than shipped features",
            "Relay credential admission is wired to Authority",
            "relay-initiated device revocation now propagates to Authority",
            "accepted coturn usage into the control-plane daily-byte ledger",
            "coturn exporter/reconcile/disconnect scripts are covered as local contracts",
            "real active TURN allocation/PeerConnection termination evidence remain open",
            "blocked readiness manifests with `--allow-blocked`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalized)

    def test_operations_keeps_authority_release_boundaries_open(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")

        self.assertIn("Relay credential\nadmission now delegates to the authority", text)
        self.assertIn("Authority owns coturn usage/reconciliation APIs", text)
        self.assertIn("exporter/reconcile/disconnect helper contract is locally tested", text)
        self.assertIn(
            "scheduled\n"
            "  reconciliation, multi-node collection, and active-allocation disconnect are not\n"
            "  production proven",
            text,
        )
        self.assertIn("does not remove the public-launch prohibition", text)
        self.assertIn("Do not expose it to the public Internet", text)

    def test_service_readmes_keep_phase3_release_boundaries_open(self) -> None:
        authority = compact(AUTHORITY_README.read_text(encoding="utf-8"))
        relay = compact(RELAY_README.read_text(encoding="utf-8"))
        signaling = compact(SIGNALING_README.read_text(encoding="utf-8"))
        deploy = compact(DEPLOY_README.read_text(encoding="utf-8"))

        self.assertIn("local coturn exporter and disconnect executor contract", authority)
        self.assertIn("do not create a durable collector cursor/WAL", authority)
        self.assertIn("production disconnect proof by themselves", authority)
        self.assertIn("scheduled production worker", authority)
        self.assertIn("active transport disconnect evidence remains open", authority)
        self.assertIn("scheduled active-allocation disconnect executor", authority)

        self.assertIn("not authoritative until a trusted coturn collector", relay)
        self.assertIn("contract helper only", relay)
        self.assertIn("production exporter, durable collector loop", relay)
        self.assertIn("concrete coturn allocation termination", relay)

        self.assertIn("coturn exporter, reconciliation loop", signaling)
        self.assertIn("active-allocation disconnect path are not production proven", signaling)
        self.assertIn("not actively disconnected", signaling)

        self.assertIn("does not prove production TLS", deploy)
        self.assertIn("public ingress, or multi-node behavior", deploy)

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
