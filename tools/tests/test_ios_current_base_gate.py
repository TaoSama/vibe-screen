from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.ios_current_base_gate import derive_gate
from vibescreen_evidence.ios_current_base_manifest import (
    BROADER_GATES,
    FORMAL_DEVICE_GATES,
    SOURCE_DOCS,
    build_manifest,
)


MODULE = "vibescreen_evidence.ios_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-current-base-gate.schema.json"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


def make_manifest(root: Path) -> dict[str, object]:
    make_docs(root)
    with patch("vibescreen_evidence.ios_current_base_manifest.repository_state") as state, patch(
        "vibescreen_evidence.ios_current_base_manifest.collect_environment"
    ) as environment:
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        return build_manifest(command=[], repo=root)


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "ios-current-base-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def complete_manifest(root: Path) -> dict[str, object]:
    manifest = make_manifest(root)
    manifest["local_environment"] = {
        "xcodebuild_version": {
            "status": "pass",
            "summary": ["Xcode 16.4", "Build version 16F6"],
        },
        "xcode_sdks": {
            "status": "pass",
            "summary": ["iOS 18.5                  -sdk iphoneos18.5"],
        },
    }
    signing = manifest["signing"]
    assert isinstance(signing, dict)
    manifest["signing_readiness_gate"] = {
        "provided": True,
        "path": str(root / "ios-app-signing-readiness-gate.json"),
        "kind": "ios_app_signing_readiness_gate",
        "verdict": "pass",
        "can_close_ios_app_signing_readiness": True,
        "missing": [],
        "failures": [],
    }
    signing.update(
        {
            "status": "pass",
            "bundle_id": "dev.vibescreen.ios.acceptance.fixture",
            "unique_bundle_id": True,
            "certificate_identity_recorded": True,
            "provisioning_profile_recorded": True,
            "signed_archive_sha256": "a" * 64,
        }
    )
    manifest["devices"] = [
        {
            "role": "iphone",
            "runtime_class": "physical_device",
            "install_status": "pass",
            "evidence": ["iphone-install.log"],
        },
        {
            "role": "ipad",
            "runtime_class": "physical_device",
            "install_status": "pass",
            "evidence": ["ipad-install.log"],
        },
    ]
    gates = manifest["gates"]
    assert isinstance(gates, dict)
    for name in [*FORMAL_DEVICE_GATES, *BROADER_GATES]:
        gate = gates[name]
        assert isinstance(gate, dict)
        gate["status"] = "pass"
        gate["evidence"] = [f"{name}.json"]
    hdr_gate = gates["hdr_output"]
    assert isinstance(hdr_gate, dict)
    hdr_gate["evidence"] = [
        "ios-hdr-edr-gate.json verdict=pass can_close_ios_hdr_output_gate=true"
    ]
    return manifest


class IOSCurrentBaseGateTests(unittest.TestCase):
    def test_default_manifest_is_blocked_and_cannot_claim_device_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_ios_device_acceptance"])
        self.assertFalse(report["can_claim_device_pass"])
        self.assertIn("blocked: xcodebuild_available", report["reasons"])
        self.assertIn("blocked: ios_sdk_available", report["reasons"])
        self.assertIn("blocked: dedicated_signing_readiness_gate", report["reasons"])
        self.assertIn("blocked: signing_status", report["reasons"])
        self.assertIn("blocked: iphone_physical_device", report["reasons"])
        self.assertIn("blocked: ipad_physical_device", report["reasons"])

    def test_android_or_simulator_substitution_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["android_evidence_used_for_ios_gates"] = True
            manifest["devices"] = [
                {
                    "role": "iphone",
                    "runtime_class": "simulator",
                    "install_status": "pass",
                    "evidence": ["simulator.log"],
                },
                {
                    "role": "ipad",
                    "runtime_class": "android",
                    "install_status": "pass",
                    "evidence": ["nubia.log"],
                },
            ]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("fail: no_android_evidence_for_ios", report["reasons"])
        self.assertIn("fail: no_simulator_or_android_device_substitution", report["reasons"])

    def test_formal_device_pass_without_broader_gates_is_insufficient_for_aggregate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            for name in BROADER_GATES:
                gate = gates[name]
                assert isinstance(gate, dict)
                gate["status"] = "open"
                gate["evidence"] = []
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(report["can_close_ios_device_acceptance"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("insufficient: hdr_output", report["reasons"])

    def test_hdr_output_requires_dedicated_owner_gate_evidence(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            hdr_gate = gates["hdr_output"]
            assert isinstance(hdr_gate, dict)
            hdr_gate["status"] = "pass"
            hdr_gate["evidence"] = ["hdr-output.json"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(report["can_close_ios_device_acceptance"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("insufficient: hdr_output", report["reasons"])

    def test_complete_synthetic_manifest_passes(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_ios_device_acceptance"])
        self.assertTrue(report["can_close_current_base_aggregate"])
        self.assertTrue(report["can_claim_device_pass"])

    def test_manifest_contract_violation_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            del manifest["source_root"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_ios_device_acceptance"])
        self.assertIn("manifest schema violation", report["reasons"][0])

    def test_dedicated_signing_readiness_gate_is_required_for_signing_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["signing_readiness_gate"] = {
                "provided": True,
                "path": "ios-app-signing-readiness-gate.json",
                "kind": "ios_app_signing_readiness_gate",
                "verdict": "blocked",
                "can_close_ios_app_signing_readiness": False,
                "missing": ["signing.device_udids missing"],
                "failures": [],
            }
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_ios_device_acceptance"])
        self.assertIn("blocked: dedicated_signing_readiness_gate", report["reasons"])

    def test_missing_nested_evidence_contract_cannot_pass(self):
        cases = {
            "signing": lambda manifest: manifest["signing"].pop("certificate_identity_recorded"),
            "device": lambda manifest: manifest["devices"][0].pop("runtime_class"),
            "gate": lambda manifest: manifest["gates"]["signing"].pop("status"),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory_name:
                root = Path(directory_name)
                manifest = complete_manifest(root)
                mutate(manifest)
                manifest_path = write_manifest(root, manifest)

                report = derive_gate(manifest_path)

                self.assertEqual(report["derivation_status"], "failed")
                self.assertEqual(report["verdict"], "blocked")
                self.assertFalse(report["can_close_ios_device_acceptance"])
                self.assertIn("manifest schema violation", report["reasons"][0])

    def test_source_docs_resolve_from_manifest_source_root(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "repo"
            output_dir = Path(directory_name) / "out"
            output_dir.mkdir()
            manifest = complete_manifest(root)
            manifest_path = output_dir / "ios-current-base-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")

    def test_source_docs_do_not_resolve_from_process_cwd(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            other_root = root / "other"
            other_root.mkdir()
            manifest["source_root"] = str(other_root)
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("metadata: source_docs", report["reasons"])

    def test_report_matches_schema_required_top_level_fields(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, complete_manifest(root))
            report = derive_gate(manifest_path)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_cli_writes_blocked_report_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))
            output_path = root / "ios-current-base-gate.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
