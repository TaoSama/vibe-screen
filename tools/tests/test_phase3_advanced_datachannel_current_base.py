from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_advanced_datachannel_current_base import (
    GATE_EVIDENCE_REQUIREMENTS,
    REQUIRED_GATES,
    default_manifest,
    derive_gate,
)

MODULE = "vibescreen_evidence.phase3_advanced_datachannel_current_base"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def evidence_record(root: Path, gate_name: str) -> dict[str, object]:
    path = root / f"{gate_name}.json"
    requirement = GATE_EVIDENCE_REQUIREMENTS[gate_name]
    record: dict[str, object] = {
        "evidence_kind": requirement["evidence_kind"],
        "scope": "public_internet",
        "route_kind": "public_internet",
        "transport": "webrtc_datachannel",
        "peer_kind": "product",
        "real_macos_host": True,
        "real_android_device": True,
        "public_internet_path": True,
        "no_plaintext_fallback": True,
        "no_synthetic_peer": True,
    }
    if "channel" in requirement:
        record["channel"] = requirement["channel"]
    if "channels" in requirement:
        record["channels"] = sorted(requirement["channels"])
    if requirement.get("bounded_backpressure") is True:
        record["bounded_backpressure"] = True
    if requirement.get("separate_aes_domains") is True:
        record["separate_aes_domains"] = True
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    record["path"] = path.name
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return record


def complete_manifest(root: Path, *, commit: str = "a" * 40) -> dict[str, object]:
    manifest = default_manifest(source_commit=commit, tree_status="clean")
    manifest["evidence_context"].update(
        {
            "real_macos_host": True,
            "real_android_device": True,
            "public_internet_path": True,
            "identity_signed_host": True,
            "no_plaintext_fallback": True,
            "no_synthetic_peer": True,
        }
    )
    for name in REQUIRED_GATES:
        manifest["gates"][name]["status"] = "pass"
        manifest["gates"][name]["evidence"] = [evidence_record(root, name)]
    manifest["claims"].update(
        {
            "internet_audio_product_flow": True,
            "internet_clipboard_product_flow": True,
            "internet_file_transfer_product_flow": True,
        }
    )
    return manifest


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class Phase3AdvancedDataChannelCurrentBaseTests(unittest.TestCase):
    def test_default_manifest_blocks_product_flow_claims(self) -> None:
        result = derive_gate(default_manifest(source_commit="a" * 40))

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertFalse(result["can_claim_internet_datachannel_product_flows"])
        self.assertIn("blocked: clean_current_base", result["reasons"])
        self.assertIn("blocked: audio_product_flow", result["reasons"])
        self.assertIn("blocked: claim_audio", result["reasons"])

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
        self.assertTrue(result["can_claim_internet_datachannel_product_flows"])
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertEqual(result["release_gate_effect"], "child_gate_only")

    def test_substituting_usb_lan_or_loopback_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["substitutions"]["usb_lan_tcp_evidence_used_for_internet"] = True
            manifest["substitutions"]["local_loopback_or_forced_local_coturn_used_as_public_internet"] = True
            manifest["substitutions"]["raw_channel_hook_tests_used_as_product_flow"] = True

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: usb_lan_tcp_evidence_used_for_internet", result["reasons"])
        self.assertIn(
            "fail: local_loopback_or_forced_local_coturn_used_as_public_internet",
            result["reasons"],
        )
        self.assertIn("fail: raw_channel_hook_tests_used_as_product_flow", result["reasons"])

    def test_passing_gate_without_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["gates"]["file_transfer_product_flow"]["evidence"] = []

            result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: file_transfer_product_flow", result["reasons"])

    def test_string_placeholder_evidence_cannot_pass(self) -> None:
        manifest = default_manifest(source_commit="a" * 40, tree_status="clean")
        manifest["evidence_context"].update(
            {
                "real_macos_host": True,
                "real_android_device": True,
                "public_internet_path": True,
                "identity_signed_host": True,
                "no_plaintext_fallback": True,
                "no_synthetic_peer": True,
            }
        )
        for name in REQUIRED_GATES:
            manifest["gates"][name]["status"] = "pass"
            manifest["gates"][name]["evidence"] = [f"{name}.json"]
        manifest["claims"].update(
            {
                "internet_audio_product_flow": True,
                "internet_clipboard_product_flow": True,
                "internet_file_transfer_product_flow": True,
            }
        )

        result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: audio_product_flow", result["reasons"])

    def test_missing_or_mismatched_retained_artifact_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            missing_record = dict(manifest["gates"]["audio_product_flow"]["evidence"][0])
            missing_record["path"] = "missing-audio.json"
            manifest["gates"]["audio_product_flow"]["evidence"] = [missing_record]
            missing = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

            manifest = complete_manifest(root)
            manifest["gates"]["audio_product_flow"]["evidence"][0]["sha256"] = "0" * 64
            mismatch = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

        self.assertEqual(missing["verdict"], "blocked")
        self.assertIn("blocked: audio_product_flow", missing["reasons"])
        self.assertEqual(mismatch["verdict"], "blocked")
        self.assertIn("blocked: audio_product_flow", mismatch["reasons"])

    def test_old_commit_or_dirty_worktree_blocks_current_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root, commit="a" * 40)

            old_commit = derive_gate(manifest, current_commit="b" * 40, tree_clean=True, evidence_root=root)
            dirty_tree = derive_gate(manifest, current_commit="a" * 40, tree_clean=False, evidence_root=root)

        self.assertEqual(old_commit["verdict"], "blocked")
        self.assertIn("blocked: actual_current_base", old_commit["reasons"])
        self.assertEqual(dirty_tree["verdict"], "blocked")
        self.assertIn("blocked: actual_current_base", dirty_tree["reasons"])

    def test_disallowed_evidence_metadata_blocks(self) -> None:
        for flag in (
            "usb_lan_tcp",
            "trusted_lan",
            "local_loopback",
            "forced_local_coturn",
            "synthetic_peer",
            "raw_hook_test",
        ):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory_name:
                root = Path(directory_name)
                manifest = complete_manifest(root)
                manifest["gates"]["audio_product_flow"]["evidence"][0][flag] = True

                result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

                self.assertEqual(result["verdict"], "blocked")
                self.assertIn("blocked: audio_product_flow", result["reasons"])

    def test_disallowed_markers_must_be_an_empty_string_list(self) -> None:
        for value in ("local_loopback", {"marker": "local_loopback"}, [""], ["", 7]):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory_name:
                root = Path(directory_name)
                manifest = complete_manifest(root)
                manifest["gates"]["audio_product_flow"]["evidence"][0]["disallowed_markers"] = value

                result = derive_gate(manifest, current_commit="a" * 40, tree_clean=True, evidence_root=root)

                self.assertEqual(result["verdict"], "blocked")
                self.assertIn("blocked: audio_product_flow", result["reasons"])

    def test_cli_writes_default_manifest_and_blocked_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = root / "manifest.json"
            output = root / "gate.json"

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

        self.assertEqual(completed.returncode, 1)
        self.assertIn("blocked: clean_current_base", completed.stderr)
        self.assertNotIn("blocked: blocked:", completed.stderr)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
