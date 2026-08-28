from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.host_display_rotation_current_base_gate import derive_gate
from vibescreen_evidence.host_display_rotation_current_base_manifest import (
    FORMAL_GATES,
    HOST_PREFLIGHT_CHECKS,
    REDACTED_ADB_SERIAL,
    SOURCE_DOCS,
    build_manifest,
)


MODULE = "vibescreen_evidence.host_display_rotation_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "host-display-rotation-current-base-gate.schema.json"
TEST_ADB_SERIAL = "TEST_ADB_SERIAL_001"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture" + chr(10), encoding="utf-8")


def make_device() -> dict[str, object]:
    return {
        "status": "pass",
        "runtime_class": "physical_android_device",
        "manufacturer": "nubia",
        "model": "P0110",
        "codename": "pacific",
        "android_release": "16",
        "sdk": 36,
        "adb_serial": REDACTED_ADB_SERIAL,
        "package_status": "installed",
        "evidence": ["device-identity.txt"],
        "probes": {},
    }


def make_manifest(root: Path) -> dict[str, object]:
    make_docs(root)
    with patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state") as state, patch(
        "vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment"
    ) as environment, patch(
        "vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device"
    ) as device:
        state.return_value = {"revision": "a" * 40, "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = make_device()
        return build_manifest(command=[], repo=root, adb_serial=TEST_ADB_SERIAL)


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "host-display-rotation-current-base-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def complete_manifest(root: Path) -> dict[str, object]:
    manifest = make_manifest(root)
    host_preflight = manifest["host_preflight"]
    assert isinstance(host_preflight, dict)
    for name in HOST_PREFLIGHT_CHECKS:
        record = host_preflight[name]
        assert isinstance(record, dict)
        record["status"] = "pass"
        record["evidence"] = [f"{name}.txt"]
    gates = manifest["gates"]
    assert isinstance(gates, dict)
    for name in FORMAL_GATES:
        gate = gates[name]
        assert isinstance(gate, dict)
        gate["status"] = "pass"
        gate["covered_host_rotations"] = [90, 180, 270]
        gate["evidence"] = [f"{name}.json"]
    return manifest


class HostDisplayRotationCurrentBaseGateTests(unittest.TestCase):
    def test_default_manifest_is_blocked_even_with_client_local_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_host_display_rotation_acceptance"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("blocked: signing_identity", report["reasons"])
        self.assertIn("blocked: physical_host_display_rotation", report["reasons"])
        self.assertIn("blocked: virtual_host_display_rotation", report["reasons"])

    def test_complete_synthetic_manifest_passes(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_host_display_rotation_acceptance"])
        self.assertTrue(report["can_close_current_base_aggregate"])
        self.assertTrue(report["can_claim_real_device_pass"])

    def test_missing_one_required_rotation_blocks_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            physical = gates["physical_host_display_rotation"]
            assert isinstance(physical, dict)
            physical["covered_host_rotations"] = [90, 270]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("blocked: physical_host_display_rotation", report["reasons"])

    def test_dirty_repository_blocks_current_base_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            repository = manifest["repository"]
            assert isinstance(repository, dict)
            repository["revision"] = "a" * 40
            repository["dirty"] = True
            repository["status_porcelain"] = ["?? evidence/partial.txt"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("metadata: repository_current_base", report["reasons"])

    def test_short_repository_revision_blocks_current_base_gate(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            repository = manifest["repository"]
            assert isinstance(repository, dict)
            repository["revision"] = "abc"
            repository["dirty"] = False
            repository["status_porcelain"] = []
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("metadata: repository_current_base", report["reasons"])

    def test_client_local_substitution_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest["client_local_matrix_used_for_host_rotation"] = True
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("fail: client_local_matrix_not_used_for_host_rotation", report["reasons"])

    def test_manifest_contract_violation_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            del manifest["source_root"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_real_device_pass"])
        self.assertIn("manifest schema violation", report["reasons"][0])

    def test_device_contract_requires_package_status_and_probes(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            device = manifest["device"]
            assert isinstance(device, dict)
            del device["package_status"]
            del device["probes"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("package_status", report["reasons"][0])
        self.assertIn("probes", report["reasons"][0])

    def test_source_docs_resolve_from_manifest_source_root(self):
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "repo"
            output_dir = Path(directory_name) / "out"
            output_dir.mkdir()
            manifest = complete_manifest(root)
            manifest_path = output_dir / "host-display-rotation-current-base-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                report = derive_gate(manifest_path)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(report["verdict"], "pass")

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
            output_path = root / "host-display-rotation-current-base-gate.json"

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
