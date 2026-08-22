from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.phase3_production_e2e_gate import derive_gate
from vibescreen_evidence.phase3_production_e2e_manifest import (
    READINESS_GATES,
    REQUIRED_PRODUCTION_GATES,
    SOURCE_DOCS,
    build_manifest,
)


MODULE = "vibescreen_evidence.phase3_production_e2e_gate"
MANIFEST_SCHEMA = Path(__file__).parents[1] / "schemas" / "phase3-production-e2e-manifest.schema.json"
GATE_SCHEMA = Path(__file__).parents[1] / "schemas" / "phase3-production-e2e-gate.schema.json"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


def make_manifest(root: Path) -> dict[str, object]:
    make_docs(root)
    with patch("vibescreen_evidence.phase3_production_e2e_manifest.repository_state") as state:
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        return build_manifest(command=["make", "phase3-production-e2e-gate"], repo=root)


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "phase3-production-e2e-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def write_artifacts(root: Path, paths: list[str]) -> None:
    for item in paths:
        target = root / item
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


def complete_manifest(root: Path) -> dict[str, object]:
    manifest = make_manifest(root)
    manifest["production_environment"] = {
        "public_internet_path": True,
        "remote_turn": True,
        "production_authority": True,
        "managed_postgresql": True,
        "tls_public_ingress": True,
        "ntp_monitoring": True,
    }
    manifest["device"] = {
        "runtime_class": "physical_android_device",
        "manufacturer": "nubia",
        "model": "P0110",
        "codename": "pacific",
        "android_release": "16",
        "sdk": "36",
        "identity_label": "Nubia P0110 / pacific / Android 16 / SDK 36",
        "evidence": ["device-properties.txt"],
    }
    manifest["host"] = {
        "capture_source": "real_display",
        "capture_api": "ScreenCaptureKit",
        "encoder": "VideoToolbox HEVC",
        "build_identity": "Vibe Screen release build abc123",
        "screen_recording_permission": "granted",
        "evidence": ["host-version.txt", "capture-decode-observation.json"],
    }
    manifest["android_artifact"] = {
        "apk_sha256": "a" * 64,
        "version_name": "0.1.0",
        "version_code": 1,
        "evidence": ["artifact-sha256.txt", "client-version.txt"],
    }
    gates = manifest["gates"]
    assert isinstance(gates, dict)
    for name in REQUIRED_PRODUCTION_GATES:
        gate = gates[name]
        assert isinstance(gate, dict)
        gate["status"] = "pass"
        gate["evidence"] = [f"{name}.json"]
    gates["mixed_route_soak"]["metrics"] = {"duration_seconds": 7200}
    for name in READINESS_GATES:
        gate = gates[name]
        assert isinstance(gate, dict)
        gate["status"] = "passed-readiness"
        gate["evidence"] = [f"{name}.json"]
    write_artifacts(
        root,
        [
            "device-properties.txt",
            "host-version.txt",
            "capture-decode-observation.json",
            "artifact-sha256.txt",
            "client-version.txt",
            *[f"{name}.json" for name in REQUIRED_PRODUCTION_GATES],
            *[f"{name}.json" for name in READINESS_GATES],
        ],
    )
    return manifest


class Phase3ProductionE2EGateTests(unittest.TestCase):
    def test_default_manifest_is_blocked_and_cannot_close_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_phase3_production_e2e"])
        self.assertFalse(report["can_claim_public_internet_release"])
        self.assertIn("blocked: public_internet_path", report["reasons"])
        self.assertIn("blocked: real_capture_to_mediacodec", report["reasons"])

    def test_complete_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, complete_manifest(root))

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_phase3_production_e2e"])
        self.assertTrue(report["can_claim_real_screen_capture_android_decode"])
        self.assertTrue(report["can_claim_revocation_soak_enforcement"])

    def test_local_synthetic_evidence_is_readiness_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            gates["local_synthetic_e2e"]["status"] = "passed-readiness"
            gates["local_synthetic_e2e"]["evidence"] = ["local-synthetic.json"]
            write_artifacts(root, ["local-synthetic.json"])
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["can_close_phase3_production_e2e"])
        self.assertIn("readiness-only: local_synthetic_e2e", report["reasons"])

    def test_synthetic_or_loopback_claim_for_production_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            claims = manifest["claims"]
            assert isinstance(claims, dict)
            claims["local_loopback_used_for_production"] = True
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_claim_public_internet_release"])
        self.assertIn("fail: local_loopback_used_for_production", report["reasons"])

    def test_local_readiness_artifact_used_for_production_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            evidence_path = root / "real_capture_to_mediacodec.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "limitations": [
                            "local_loopback_only",
                            "synthetic_protocol_v1_device",
                            "no_real_screen_capture",
                            "no_android_mediacodec_decode",
                            "no_public_internet_path",
                        ],
                        "product_session": {
                            "capture_or_stream_server_started": False,
                            "synthetic_device": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn(
            "fail: production_evidence_substitution:real_capture_to_mediacodec",
            report["reasons"],
        )

    def test_nubia_identity_guard_rejects_xiaomi_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            device = manifest["device"]
            assert isinstance(device, dict)
            device["identity_label"] = "Xiaomi 13 / fuxi"
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn("blocked: nubia_identity_guard", report["reasons"])

    def test_short_soak_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            gates = manifest["gates"]
            assert isinstance(gates, dict)
            gates["mixed_route_soak"]["metrics"] = {"duration_seconds": 7199}
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn("blocked: mixed_route_soak_duration", report["reasons"])

    def test_missing_evidence_artifact_blocks_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            (root / "real_capture_to_mediacodec.json").unlink()
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn("blocked: real_capture_to_mediacodec", report["reasons"])

    def test_manifest_contract_violation_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            del manifest["claims"]
            manifest_path = write_manifest(root, manifest)

            report = derive_gate(manifest_path)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("manifest schema violation", report["reasons"][0])

    def test_reports_match_schema_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = complete_manifest(root)
            manifest_path = write_manifest(root, manifest)
            report = derive_gate(manifest_path)
        gate_schema = json.loads(GATE_SCHEMA.read_text(encoding="utf-8"))
        manifest_schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(gate_schema["properties"]))
        for field in gate_schema["required"]:
            self.assertIn(field, report)
        self.assertTrue(set(manifest).issubset(set(manifest_schema["properties"])))

    def test_cli_writes_blocked_report_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))
            output_path = root / "phase3-production-e2e-gate.json"

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
