from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_webrtc_relay_e2e_current_base import (
    CORE_REQUIREMENTS,
    MANIFEST_KIND,
    RELEASE_CHECKLIST,
    default_manifest,
    derive_gate,
)


MODULE = "vibescreen_evidence.phase3_webrtc_relay_e2e_current_base"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def relay_artifact() -> dict[str, object]:
    return {
        "evidence_kind": "webrtc_turn_relay_product_e2e",
        "scope": "public_internet",
        "route_kind": "relay",
        "transport": "webrtc",
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
        "route": {
            "selected_route": "relay",
            "local_candidate_type": "relay",
            "remote_candidate_type": "srflx",
            "turn_realm": "relay.example.net",
            "allocation_id": "redacted-allocation-id",
            "local_coturn_loopback": False,
        },
        "media_continuity": {
            "capture_source_started": True,
            "videotoolbox_encoded_frames": True,
            "webrtc_media_epochs": True,
            "android_mediacodec_first_output": True,
            "rendered_visible_client_ui": True,
            "session_epoch_verified": True,
            "dropped_frames": 0,
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
    artifact = relay_artifact()
    write_json(path, artifact)
    record = dict(artifact)
    record["path"] = path.name
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record


def prerequisite_evidence_record(root: Path, name: str) -> dict[str, object]:
    path = root / "release-prerequisites" / f"{name}.json"
    write_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "kind": f"phase3_{name}_evidence",
            "status": "pass",
        },
    )
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


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
        manifest["release_prerequisites"][name]["evidence"] = [prerequisite_evidence_record(root, name)]
    manifest["claims"]["internet_webrtc_turn_relay_product_e2e"] = True
    return manifest


class Phase3WebrtcRelayE2ECurrentBaseTests(unittest.TestCase):
    def test_default_manifest_blocks_without_product_evidence(self) -> None:
        result = derive_gate(default_manifest(source_commit="a" * 40))

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["kind"], "phase3_webrtc_relay_e2e_current_base_gate")
        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_closed"])
        self.assertFalse(result["can_close_public_internet_webrtc_turn_relay_e2e_gate"])
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertIn("blocked: public_internet_webrtc_relay_route", result["blockers"])
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
        self.assertTrue(result["can_close_public_internet_webrtc_turn_relay_e2e_gate"])
        self.assertFalse(result["gate_can_close_phase3_release"])

    def test_local_coturn_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["substitutions"]["local_loopback_or_forced_local_coturn_used_as_public_internet"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: local_loopback_or_forced_local_coturn_used_as_public_internet", result["blockers"])

    def test_local_coturn_artifact_cannot_pass_public_internet_relay(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["core_gates"]["public_internet_webrtc_relay_route"]["evidence"][0]["route"]["local_coturn_loopback"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: public_internet_webrtc_relay_route", result["blockers"])
        gate = result["checks"]["public_internet_webrtc_relay_route"]
        self.assertTrue(any("local_coturn_loopback evidence is disallowed" in item for item in gate["evidence"]))

    def test_synthetic_peer_flag_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["evidence_context"]["no_synthetic_peer"] = False

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: no_synthetic_peer", result["blockers"])

    def test_missing_media_continuity_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            record = manifest["core_gates"]["real_media_continuity"]["evidence"][0]
            record["media_continuity"]["android_mediacodec_first_output"] = False

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        gate = result["checks"]["real_media_continuity"]
        self.assertTrue(any("android_mediacodec_first_output" in item for item in gate["evidence"]))

    def test_cli_writes_default_blocked_manifest_and_sanitized_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = root / "relay-e2e-manifest.json"
            output = root / "relay-e2e-gate.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest.resolve()),
                    "--output",
                    str(output.resolve()),
                    "--source-commit",
                    "a" * 40,
                    "--tree-status",
                    "dirty",
                    "--write-default-manifest",
                ],
                check=False,
                capture_output=True,
                cwd=REPOSITORY_ROOT,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            saved_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            saved_gate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["kind"], MANIFEST_KIND)
            self.assertEqual(saved_manifest["owner"]["role"], "phase3_webrtc_relay_e2e_current_base_owner")
            self.assertEqual(saved_gate["verdict"], "blocked")
            self.assertIn("blocked: source_current_base", saved_gate["blockers"])
            self.assertNotIn("a" * 40, completed.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
