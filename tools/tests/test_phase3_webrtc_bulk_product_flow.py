from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_webrtc_bulk_product_flow import (
    CORE_REQUIREMENTS,
    MANIFEST_KIND,
    RELEASE_CHECKLIST,
    default_manifest,
    derive_gate,
)


MODULE = "vibescreen_evidence.phase3_webrtc_bulk_product_flow"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def bulk_artifact() -> dict[str, object]:
    direction = {
        "protocol_v1_session": True,
        "file_offer_observed": True,
        "receiver_request_observed": True,
        "bulk_chunks_observed": True,
        "progress_observed": True,
        "completion_ack_observed": True,
        "source_file_read": True,
        "explicit_user_action": True,
        "receiver_approved": True,
        "remote_file_written": True,
        "final_sha256_match": True,
        "session_epoch_verified": True,
        "transport": "webrtc_datachannel",
        "channel": "vibescreen.bulk.v1",
        "route": "relay",
        "session_epoch": 9,
        "byte_length": 4096,
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    }
    return {
        "evidence_kind": "webrtc_bulk_file_transfer_product_flow",
        "scope": "public_internet",
        "route_kind": "relay",
        "transport": "webrtc_datachannel",
        "channel": "vibescreen.bulk.v1",
        "peer_kind": "product",
        "real_macos_host": True,
        "real_android_device": True,
        "public_internet_path": True,
        "deployed_remote_turn": True,
        "webrtc_transport": True,
        "identity_signed_host": True,
        "screen_recording_granted": True,
        "real_capture_to_mediacodec": True,
        "no_plaintext_fallback": True,
        "no_synthetic_peer": True,
        "disallowed_markers": [],
        "file_transfer": {
            "directions": {
                "android_to_macos": dict(direction),
                "macos_to_android": dict(direction),
            },
            "cleanup": {
                "bounded_send_queue_observed": True,
                "receiver_backpressure_observed": True,
                "oversized_payload_rejected": True,
                "stale_owner_rejected": True,
                "cancel_cleanup_observed": True,
                "disconnect_cleanup_observed": True,
            },
        },
        "secure_record_layer": {
            "algorithm": "AES-256-GCM",
            "header_as_aad": True,
            "session_epoch_bound": True,
            "key_epoch_bound": True,
            "channel_key_separation": True,
            "directional_key_separation": True,
            "replay_protection": True,
            "packet_capture_no_plaintext": True,
            "nonce_reuse_detected": False,
            "plaintext_fallback": False,
        },
    }


def evidence_record(root: Path, name: str) -> dict[str, object]:
    path = root / f"{name}.json"
    artifact = bulk_artifact()
    write_json(path, artifact)
    record = dict(artifact)
    record["path"] = path.name
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record


def complete_manifest(root: Path, *, commit: str = "a" * 40) -> dict[str, object]:
    manifest = default_manifest(source_commit=commit, tree_status="clean")
    manifest["evidence_context"].update({key: True for key in manifest["evidence_context"]})
    for name in CORE_REQUIREMENTS:
        if name == "source_current_base":
            continue
        manifest["core_gates"][name]["status"] = "pass"
        manifest["core_gates"][name]["evidence"] = [evidence_record(root, name)]
    for name in RELEASE_CHECKLIST:
        manifest["release_prerequisites"][name]["status"] = "pass"
        manifest["release_prerequisites"][name]["evidence"] = [f"{name}.json"]
    manifest["claims"]["internet_webrtc_bulk_file_transfer_product_flow"] = True
    return manifest


class Phase3WebrtcBulkProductFlowTests(unittest.TestCase):
    def test_default_manifest_blocks_without_product_evidence(self) -> None:
        result = derive_gate(default_manifest(source_commit="a" * 40))

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["kind"], "phase3_webrtc_bulk_product_flow_gate")
        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_closed"])
        self.assertFalse(result["can_close_public_internet_bulk_product_flow_gate"])
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertIn("blocked: public_relay_webrtc_route", result["blockers"])
        self.assertIn("blocked: release_prerequisite.relay_production_prerequisites", result["blockers"])

    def test_complete_manifest_passes_child_gate_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            result = derive_gate(
                complete_manifest(root),
                current_commit="a" * 40,
                tree_clean=True,
                evidence_root=root,
            )

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["gate_closed"])
        self.assertTrue(result["can_close_public_internet_bulk_product_flow_gate"])
        self.assertFalse(result["gate_can_close_phase3_release"])

    def test_pr404_relay_preflight_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["substitutions"]["pr404_relay_owner_used_as_product_e2e"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: pr404_relay_owner_used_as_product_e2e", result["blockers"])

    def test_usb_lan_product_artifact_cannot_pass_internet_bulk(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["core_gates"]["bulk_file_transfer_product_flow"]["evidence"][0]["usb_lan_tcp"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: bulk_file_transfer_product_flow", result["blockers"])

    def test_incomplete_bulk_direction_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            record = manifest["core_gates"]["bulk_file_transfer_product_flow"]["evidence"][0]
            record["file_transfer"]["directions"]["macos_to_android"]["receiver_approved"] = False

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        gate = result["checks"]["bulk_file_transfer_product_flow"]
        self.assertTrue(any("receiver_approved" in item for item in gate["evidence"]))

    def test_child_gate_cannot_claim_phase3_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["claims"]["phase3_public_internet_product_e2e"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "fail")
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertIn("fail: phase3_public_internet_product_e2e claimed by bulk child gate", result["blockers"])

    def test_cli_writes_default_blocked_manifest_and_sanitized_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = root / "bulk-manifest.json"
            output = root / "bulk-gate.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(output),
                    "--source-commit",
                    "a" * 40,
                    "--tree-status",
                    "dirty",
                    "--write-default-manifest",
                ],
                check=False,
                capture_output=True,
                cwd=REPOSITORY_ROOT,
                env={**os.environ, "PYTHONPATH": "tools"},
                text=True,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            written_manifest = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")
        self.assertEqual(written_manifest["kind"], MANIFEST_KIND)
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn(directory_name, serialized)
        self.assertNotIn("/Users/", serialized)


if __name__ == "__main__":
    unittest.main()
