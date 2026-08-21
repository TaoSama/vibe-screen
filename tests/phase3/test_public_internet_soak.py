from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.internet_soak_manifest import (
    FORBIDDEN_PASS_TEXT,
    REQUIRED_GATE_IDS,
    ManifestError,
    template_manifest,
    validate_manifest,
)


def _pass_manifest() -> dict:
    """Build a manifest that satisfies every required release gate."""
    placeholder_hash = "a" * 64
    placeholder_commit = "b" * 40
    return {
        "schema": "dev.vibescreen.phase3-public-internet-soak/v1",
        "result": "pass",
        "generated_at_utc": "2026-08-21T00:00:00Z",
        "repository": {
            "commit": placeholder_commit,
            "tree": placeholder_commit,
            "status": "clean",
        },
        "artifacts": {
            "apk_sha256": placeholder_hash,
            "host_build_sha256": placeholder_hash,
            "signaling_image_sha256": placeholder_hash,
            "relay_image_sha256": placeholder_hash,
            "coturn_image_sha256": placeholder_hash,
        },
        "device": {
            "platform": "Android",
            "acceptance_role": "android_substitute",
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "os_release": "16",
            "api_level": "35",
            "serial_hash": placeholder_hash,
        },
        "network": {
            "topology": "public_internet",
            "signaling_origin": "signaling.vibescreen.netops.prod",
            "turn_origin": "turn.vibescreen.netops.prod",
            "nat_observation": "symmetric_nat_fallback_to_turn",
        },
        "routes": {
            "direct": {
                "selected_candidate_pair": "direct",
                "evidence": ["evidence/direct-session.jsonl"],
            },
            "forced_turn": {
                "selected_candidate_pair": "relay",
                "evidence": ["evidence/relay-session.jsonl"],
            },
            "nat_fallback": {
                "direct_candidates_blocked": True,
                "selected_candidate_pair": "relay",
                "evidence": ["evidence/nat-fallback.jsonl"],
            },
        },
        "handoff": {
            "network_changes": 2,
            "initial_session_epoch": 1,
            "recovered_session_epoch": 2,
            "recovery_p95_seconds": 3.5,
            "evidence": ["evidence/network-handoff.jsonl"],
        },
        "revocation": {
            "authority_rejected_signaling": True,
            "authority_rejected_relay_credentials": True,
            "active_peerconnection_disconnected": True,
            "active_turn_allocation_disconnected": True,
            "post_revocation_reconnect_rejected": True,
            "evidence": ["evidence/replay-revocation.jsonl"],
        },
        "soak": {
            "duration_seconds": 7200,
            "mixed_direct_and_relay": True,
            "network_changes": 3,
            "memory_growth_mb": 0.0,
            "nonce_reuse_detected": False,
            "steadily_increasing_latency": False,
            "queue_bound_violations": False,
            "evidence": ["evidence/soak-summary.json"],
        },
        "latency": {
            "method": "external_camera",
            "direct_p95_ms": 120.0,
            "relay_p95_ms": 180.0,
            "evidence": ["evidence/latency-method.md"],
        },
        "privacy": {
            "secret_scan": {"status": "pass", "artifacts_scanned": 12},
            "packet_capture": {"application_payload_ciphertext_only": True},
            "evidence": ["evidence/privacy-scan.json"],
        },
        "gates": [
            {"id": gate_id, "status": "pass", "evidence": ["evidence/gates.md"]}
            for gate_id in REQUIRED_GATE_IDS
        ],
    }


class InternetSoakManifestTests(unittest.TestCase):
    def test_valid_pass_manifest_passes(self) -> None:
        validate_manifest(_pass_manifest())

    def test_blocked_manifest_fails_without_allow_blocked(self) -> None:
        manifest = template_manifest()
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_blocked_manifest_passes_with_allow_blocked(self) -> None:
        manifest = template_manifest()
        warnings = validate_manifest(manifest, allow_blocked=True)
        self.assertTrue(warnings)

    def test_local_only_marker_in_pass_manifest_fails_closed(self) -> None:
        for marker in FORBIDDEN_PASS_TEXT:
            with self.subTest(marker=marker):
                manifest = _pass_manifest()
                manifest["notes"] = [f"run used {marker}"]
                with self.assertRaises(ManifestError):
                    validate_manifest(manifest)

    def test_short_soak_duration_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["soak"]["duration_seconds"] = 7199
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_dirty_repository_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["repository"]["status"] = "dirty"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_local_signaling_origin_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["network"]["signaling_origin"] = "127.0.0.1:8090"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_placeholder_turn_origin_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["network"]["turn_origin"] = "turn.example.com"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_missing_required_gate_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["gates"] = manifest["gates"][1:]
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_blocked_gate_fails_closed_without_allow_blocked(self) -> None:
        manifest = _pass_manifest()
        manifest["gates"][0]["status"] = "blocked"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_wrong_schema_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["schema"] = "dev.vibescreen.phase3-public-e2e/v1"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_revocation_not_enforced_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["revocation"]["active_turn_allocation_disconnected"] = False
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_nonce_reuse_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["soak"]["nonce_reuse_detected"] = True
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_steadily_increasing_latency_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["soak"]["steadily_increasing_latency"] = True
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_packet_capture_plaintext_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["privacy"]["packet_capture"]["application_payload_ciphertext_only"] = False
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_handoff_epoch_not_advanced_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["handoff"]["recovered_session_epoch"] = manifest["handoff"]["initial_session_epoch"]
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_nat_fallback_without_blocked_direct_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["routes"]["nat_fallback"]["direct_candidates_blocked"] = False
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_placeholder_hash_fails_closed(self) -> None:
        manifest = _pass_manifest()
        manifest["artifacts"]["apk_sha256"] = "0" * 64
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_xiaomi_identity_cannot_be_labelled_substitute(self) -> None:
        manifest = _pass_manifest()
        manifest["device"]["model"] = "2211133C"
        manifest["device"]["device"] = "fuxi"
        with self.assertRaises(ManifestError):
            validate_manifest(manifest)

    def test_expected_nubia_identity_passes_for_android_substitute(self) -> None:
        validate_manifest(_pass_manifest(), expected_device="nubia-p0110")

    def test_expected_xiaomi_identity_rejects_nubia_substitute(self) -> None:
        with self.assertRaises(ManifestError):
            validate_manifest(_pass_manifest(), expected_device="xiaomi13")


class InternetSoakManifestCliTests(unittest.TestCase):
    def test_template_output_is_blocked(self) -> None:
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/phase3/internet_soak_manifest.py", "--template"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        document = json.loads(result.stdout)
        self.assertEqual(document["result"], "blocked")

    def test_blocked_manifest_exits_nonzero_without_allow_blocked(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "blocked.json"
            path.write_text(json.dumps(template_manifest()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/phase3/internet_soak_manifest.py", str(path)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_blocked_manifest_succeeds_with_allow_blocked(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "blocked.json"
            path.write_text(json.dumps(template_manifest()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/phase3/internet_soak_manifest.py",
                    "--allow-blocked",
                    str(path),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("does not close the gate", result.stdout)


if __name__ == "__main__":
    unittest.main()
