from __future__ import annotations

import io
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.production_e2e_enforcement import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_FAIL,
    SCHEMA,
    EnforcementError,
    evaluate_manifest,
    main,
)


COMMIT = "b" * 40
ARTIFACT_TYPES = (
    "deployed_config",
    "public_network_observation",
    "data_plane_observation",
    "coturn_disconnect_observation",
    "mixed_route_soak",
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def valid_policy() -> dict[str, object]:
    return {
        "authority_source_id": "turn-prod-1",
        "turn_realm": "relay.example.com",
        "maximum_session_ttl_seconds": 900,
        "turn_credential_ttl_seconds": 600,
        "maximum_allocations_per_device": 2,
        "daily_bytes_per_device": 21474836480,
        "maximum_database_clock_skew_seconds": 5,
    }


def valid_manifest() -> dict[str, object]:
    policy = valid_policy()
    return {
        "schema": SCHEMA,
        "run_id": "phase3-production-e2e-20260822T010203Z",
        "recorded_at_utc": "2026-08-22T01:02:03Z",
        "owners": {
            "release_decision": {"team": "vibe-screen-release", "contact": "release-oncall"},
            "authority": {"team": "vibe-screen-authority", "contact": "authority-oncall"},
            "signaling": {"team": "vibe-screen-signaling", "contact": "signaling-oncall"},
            "coturn_data_plane": {"team": "vibe-screen-relay", "contact": "relay-oncall"},
            "evidence_review": {"team": "vibe-screen-qa", "contact": "qa-oncall"},
        },
        "source": {"commit": COMMIT, "dirty": False},
        "production_config": {
            "authority": {
                "present": True,
                "source": "deployed-secret-manager",
                "tls_verify_full": True,
                "http_public_ingress": False,
            },
            "signaling": {
                "present": True,
                "source": "deployed-secret-manager",
                "tls_verify_full": True,
                "mode": "production_authority",
                "storage_backend": "postgres",
            },
            "coturn": {
                "present": True,
                "source": "deployed-secret-manager",
                "tls_verify_full": True,
                "exporter": "deployed",
                "disconnect_executor": "deployed",
            },
        },
        "policy": {
            "authority": dict(policy),
            "signaling": dict(policy),
            "coturn": dict(policy),
        },
        "topology": {
            "classification": "public_internet",
            "local_loopback": False,
            "synthetic_peer": False,
            "public_route_observed": True,
            "remote_turn_observed": True,
            "public_endpoint_hosts": ["cloudflare.com", "one.one.one.one"],
        },
        "data_plane": {
            "real_screencapturekit_capture": True,
            "android_mediacodec_decode": True,
            "application_aead_verified": True,
            "coturn_allocation_observed": True,
            "coturn_disconnect_observed": True,
            "authority_admission_observed": True,
            "signaling_authorization_observed": True,
            "mixed_route_soak_minutes": 120,
        },
        "evidence": {
            "rerun_commands": [
                "make phase3-production-e2e-enforcement EVIDENCE_DIR=/protected/evidence"
            ],
            "artifacts": [
                {"type": artifact_type, "path": f"{artifact_type}.json", "sha256": "a" * 64}
                for artifact_type in ARTIFACT_TYPES
            ],
        },
    }


def write_valid_artifacts(root: Path, manifest: dict[str, object]) -> None:
    artifacts = manifest["evidence"]["artifacts"]
    for artifact in artifacts:
        artifact_type = artifact["type"]
        payload = json.dumps(valid_artifact_payload(artifact_type, manifest), sort_keys=True).encode("utf-8")
        path = root / artifact["path"]
        path.write_bytes(payload)
        artifact["sha256"] = sha256(payload)


def valid_artifact_payload(artifact_type: str, manifest: dict[str, object]) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": f"dev.vibescreen.phase3-production-{artifact_type.replace('_', '-')}"
        + ("/v1" if artifact_type != "mixed_route_soak" else "-observation/v1"),
        "run_id": manifest["run_id"],
        "source": {"commit": manifest["source"]["commit"]},
        "result": "pass",
    }
    if artifact_type == "deployed_config":
        return {
            **base,
            "schema": "dev.vibescreen.phase3-production-deployed-config-observation/v1",
            "production_config": manifest["production_config"],
            "policy": manifest["policy"],
        }
    if artifact_type == "public_network_observation":
        return {
            **base,
            "schema": "dev.vibescreen.phase3-production-public-network-observation/v1",
            "classification": "public_internet",
            "local_loopback": False,
            "synthetic_peer": False,
            "public_route_observed": True,
            "remote_turn_observed": True,
            "public_endpoint_hosts": manifest["topology"]["public_endpoint_hosts"],
        }
    if artifact_type == "data_plane_observation":
        return {
            **base,
            "schema": "dev.vibescreen.phase3-production-data-plane-observation/v1",
            "real_screencapturekit_capture": True,
            "android_mediacodec_decode": True,
            "application_aead_verified": True,
            "coturn_allocation_observed": True,
            "authority_admission_observed": True,
            "signaling_authorization_observed": True,
            "local_loopback": False,
            "synthetic_peer": False,
        }
    if artifact_type == "coturn_disconnect_observation":
        return {
            **base,
            "schema": "dev.vibescreen.phase3-production-coturn-disconnect-observation/v1",
            "coturn_disconnect_observed": True,
            "active_allocation_removed": True,
            "remote_turn_observed": True,
            "local_coturn": False,
        }
    if artifact_type == "mixed_route_soak":
        return {
            **base,
            "schema": "dev.vibescreen.phase3-production-mixed-route-soak-observation/v1",
            "real_android_device": True,
            "real_screencapturekit_capture": True,
            "android_mediacodec_decode": True,
            "synthetic_peer": False,
            "duration_minutes": 120,
            "public_route_minutes": 60,
            "turn_route_minutes": 60,
        }
    raise AssertionError(f"unknown artifact type: {artifact_type}")


class ProductionE2EEnforcementTests(unittest.TestCase):
    def test_complete_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = valid_manifest()
            write_valid_artifacts(root, manifest)

            result = evaluate_manifest(manifest, root)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reasons"], [])
        self.assertIn("release_decision", result["owners"])

    def test_real_config_absence_blocks_release_gate_without_passing(self) -> None:
        manifest = valid_manifest()
        manifest["production_config"]["authority"]["present"] = False
        manifest["production_config"]["authority"]["source"] = "example-file"

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "blocked")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("production_config.authority.present", fields)
        self.assertIn("production_config.authority.source", fields)

    def test_policy_mismatch_fails_closed(self) -> None:
        manifest = valid_manifest()
        manifest["policy"]["coturn"]["daily_bytes_per_device"] = 42
        manifest["policy"]["signaling"]["turn_realm"] = "other.example.com"

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("policy.coturn.daily_bytes_per_device", fields)
        self.assertIn("policy.signaling.turn_realm", fields)

    def test_local_loopback_or_synthetic_peer_cannot_claim_public_production_e2e(self) -> None:
        manifest = valid_manifest()
        manifest["topology"]["local_loopback"] = True
        manifest["topology"]["synthetic_peer"] = True
        manifest["topology"]["public_endpoint_hosts"] = ["127.0.0.1", "localhost"]

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("topology.local_loopback", fields)
        self.assertIn("topology.synthetic_peer", fields)
        self.assertIn("topology.public_endpoint_hosts[0]", fields)

    def test_missing_data_plane_observations_block_release_gate(self) -> None:
        manifest = valid_manifest()
        manifest["data_plane"]["real_screencapturekit_capture"] = False
        manifest["data_plane"]["coturn_disconnect_observed"] = False
        manifest["data_plane"]["mixed_route_soak_minutes"] = 30

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "blocked")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("data_plane.real_screencapturekit_capture", fields)
        self.assertIn("data_plane.coturn_disconnect_observed", fields)
        self.assertIn("data_plane.mixed_route_soak_minutes", fields)

    def test_evidence_root_requires_files_hashes_and_artifact_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = valid_manifest()
            first_artifact = manifest["evidence"]["artifacts"][0]
            first_artifact["sha256"] = sha256(b"different")
            (root / first_artifact["path"]).write_bytes(b"actual")

            result = evaluate_manifest(manifest, root)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("evidence.artifacts[0].sha256", fields)

        manifest = valid_manifest()
        manifest["evidence"]["artifacts"] = manifest["evidence"]["artifacts"][:1]
        result = evaluate_manifest(manifest)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("evidence.artifacts.type", {reason["field"] for reason in result["reasons"]})

    def test_local_synthetic_artifacts_fail_even_when_manifest_claims_public(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = valid_manifest()
            write_valid_artifacts(root, manifest)
            local_artifact = root / manifest["evidence"]["artifacts"][0]["path"]
            payload = b'{"schema":"dev.vibescreen.phase3-webrtc-e2e/v1","result":"pass","limitation":"local_loopback_only"}'
            local_artifact.write_bytes(payload)
            manifest["evidence"]["artifacts"][0]["sha256"] = sha256(payload)

            result = evaluate_manifest(manifest, root)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("evidence.artifacts[deployed_config]", fields)
        self.assertIn("evidence.artifacts[deployed_config].schema", fields)

    def test_tiny_self_attesting_pass_artifacts_do_not_close_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = valid_manifest()
            artifacts = manifest["evidence"]["artifacts"]
            for artifact in artifacts:
                payload = json.dumps(
                    {
                        "schema": f"dev.vibescreen.{artifact['type']}/v1",
                        "result": "pass",
                        "observed": True,
                    },
                    sort_keys=True,
                ).encode("utf-8")
                (root / artifact["path"]).write_bytes(payload)
                artifact["sha256"] = sha256(payload)

            result = evaluate_manifest(manifest, root)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("evidence.artifacts[deployed_config].production_config", fields)
        self.assertIn("evidence.artifacts[data_plane_observation].real_screencapturekit_capture", fields)
        self.assertIn("evidence.artifacts[mixed_route_soak].duration_minutes", fields)

    def test_internal_dns_names_are_not_public_endpoint_evidence(self) -> None:
        manifest = valid_manifest()
        manifest["topology"]["public_endpoint_hosts"] = ["relay.internal", "turn.corp"]

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("topology.public_endpoint_hosts[0]", fields)
        self.assertIn("topology.public_endpoint_hosts[1]", fields)

    def test_deployed_unsafe_config_fails_but_missing_signaling_stays_blocked(self) -> None:
        manifest = valid_manifest()
        manifest["production_config"]["authority"]["http_public_ingress"] = True
        manifest["production_config"]["authority"]["tls_verify_full"] = False
        manifest["production_config"]["coturn"]["exporter"] = "not_deployed"

        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "fail")
        fields = {reason["field"]: reason["category"] for reason in result["reasons"]}
        self.assertEqual(fields["production_config.authority.http_public_ingress"], "fail")
        self.assertEqual(fields["production_config.authority.tls_verify_full"], "fail")
        self.assertEqual(fields["production_config.coturn.exporter"], "fail")

        manifest = valid_manifest()
        del manifest["production_config"]["signaling"]
        result = evaluate_manifest(manifest)

        self.assertEqual(result["status"], "blocked")
        fields = {reason["field"] for reason in result["reasons"]}
        self.assertIn("production_config", fields)
        self.assertNotIn("production_config.signaling.mode", fields)

    def test_schema_and_unknown_fields_are_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["extra"] = True
        with self.assertRaisesRegex(EnforcementError, "unknown fields"):
            evaluate_manifest(manifest)

        manifest = valid_manifest()
        manifest["schema"] = "other"
        with self.assertRaisesRegex(EnforcementError, "schema must be"):
            evaluate_manifest(manifest)

    def test_cli_writes_blocked_report_and_uses_nonzero_exit_code(self) -> None:
        manifest = valid_manifest()
        manifest["production_config"]["coturn"]["present"] = False
        manifest["production_config"]["coturn"]["source"] = "not_available"
        manifest["production_config"]["coturn"]["tls_verify_full"] = False
        manifest["production_config"]["coturn"]["disconnect_executor"] = "not_deployed"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            output_path = root / "result.json"
            write_valid_artifacts(root, manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                code = main(["--manifest", str(manifest_path), "--output", str(output_path)])

            self.assertEqual(code, EXIT_BLOCKED)
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "blocked")
            self.assertIn('"status": "blocked"', stdout.getvalue())

    def test_cli_rejects_malformed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text("[]", encoding="utf-8")
            stderr = io.StringIO()
            with mock.patch("sys.stderr", stderr):
                code = main(["--manifest", str(manifest_path)])

        self.assertEqual(code, EXIT_FAIL)
        self.assertIn("manifest must be a JSON object", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
