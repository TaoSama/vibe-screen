from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.harmony_current_base_gate import OWNER_GATES, derive_gate


MODULE = "vibescreen_evidence.harmony_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "harmony-current-base-gate.schema.json"


def write_json(root: Path, name: str, document: dict[str, object]) -> Path:
    path = root / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def passing_readiness() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "harmony_readiness_preflight",
        "verdict": "pass",
        "toolchain": {
            "deveco_studio": {"status": "pass", "version": "DevEco Studio 6"},
            "hvigor": {"status": "pass", "version": "hvigor 5"},
            "ohpm": {"status": "pass", "version": "ohpm 5"},
            "hdc": {"status": "pass", "version": "hdc 5"},
        },
        "artifact": {
            "hap_path": "dist/release/vibescreen.hap",
            "hap_sha256": "1" * 64,
            "hap_zip_readable": True,
            "signature_certificate_sha256": "2" * 64,
            "sha256sums_sha256": "3" * 64,
            "sha256sums_contains_hap": True,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "is_matepad_mini": True,
        },
        "host": {
            "commit": "a" * 40,
            "build_sha256": "4" * 64,
            "protocol": "Protocol v1",
        },
    }


def blocked_readiness() -> dict[str, object]:
    manifest = passing_readiness()
    manifest["verdict"] = "blocked"
    manifest["toolchain"] = {
        "deveco_studio": {"status": "blocked", "detail": "DevEco Studio not found"},
        "hvigor": {"status": "blocked", "detail": "hvigor not found"},
        "ohpm": {"status": "blocked", "detail": "ohpm not found"},
        "hdc": {"status": "blocked", "detail": "hdc not found"},
    }
    manifest["artifact"] = {
        "hap_path": None,
        "hap_sha256": None,
        "hap_zip_readable": False,
        "signature_certificate_sha256": None,
        "sha256sums_sha256": None,
        "sha256sums_contains_hap": False,
    }
    manifest["device"] = None
    manifest["host"] = {"commit": None, "build_sha256": None, "protocol": "Protocol v1"}
    return manifest


def passing_device_gates() -> dict[str, object]:
    gate_ids = sorted({gate for config in OWNER_GATES.values() for gate in config["required_device_gates"]})
    marker_by_gate = {
        "h264_hardware_decode": "harmony-avcodec-preflight.json",
        "hevc_hardware_decode": "harmony-avcodec-preflight.json",
        "signed_release_hap": "harmony-hap-readiness.json",
        "hap_install_launch": "harmony-hap-readiness.json",
        "host_protocol_v1_interop": "harmony-host-interop-preflight.json",
        "resume_background_foreground": "harmony-host-interop-preflight.json",
        "resume_network_roam": "harmony-host-interop-preflight.json",
        "resume_host_restart": "harmony-host-interop-preflight.json",
        "no_old_epoch_render": "harmony-host-interop-preflight.json",
        "resume_capable_host_interop": "harmony-host-interop-preflight.json",
    }
    return {
        "schema": "dev.vibescreen.harmony-device-gates/v1",
        "artifact": {
            "bundle_name": "dev.vibescreen.harmony",
            "hap_sha256": "1" * 64,
            "signature_certificate_sha256": "2" * 64,
            "sha256sums_sha256": "3" * 64,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
        },
        "host": {
            "commit": "a" * 40,
            "build_sha256": "4" * 64,
            "protocol": "Protocol v1",
        },
        "gates": [
            {"id": gate_id, "status": "pass", "evidence": [f"evidence/{marker_by_gate[gate_id]}"]}
            for gate_id in gate_ids
        ],
    }


class HarmonyCurrentBaseGateTests(unittest.TestCase):
    def test_missing_hardware_environment_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            readiness_path = write_json(root, "harmony-readiness.json", blocked_readiness())
            device_path = write_json(root, "harmony-device-gates.json", passing_device_gates())

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase4_owner_gates"])
        self.assertFalse(report["can_claim_harmony_device_pass"])
        self.assertIn("blocked: readiness.readiness_manifest", report["reasons"])
        self.assertIn("blocked: readiness.deveco", report["reasons"])
        self.assertIn("blocked: readiness.hap", report["reasons"])
        self.assertIn("blocked: readiness.matepad", report["reasons"])
        self.assertIn("blocked: readiness.host", report["reasons"])

    def test_missing_owner_gate_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            gates = manifest["gates"]
            assert isinstance(gates, list)
            gates[:] = [gate for gate in gates if gate["id"] != "resume_host_restart"]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.host_resume_interop", report["reasons"])
        self.assertFalse(report["checks"]["owner_gates"]["host_resume_interop"]["passed"])

    def test_generic_evidence_reference_cannot_close_owner_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            gates = manifest["gates"]
            assert isinstance(gates, list)
            for gate in gates:
                if gate["id"] == "h264_hardware_decode":
                    gate["evidence"] = ["evidence/generic-video.log"]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.hardware_decode_capability", report["reasons"])
        evidence = report["checks"]["owner_gates"]["hardware_decode_capability"]["evidence"]
        self.assertIn("h264_hardware_decode:missing-evidence-marker:harmony-avcodec-preflight.json", evidence)

    def test_android_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            device_gates["device"] = {
                "platform": "Android",
                "manufacturer": "nubia",
                "model": "P0110",
                "product": "pacific",
            }
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("fail: no_android_evidence_for_harmony", report["reasons"])
        self.assertFalse(report["can_claim_harmony_device_pass"])

    def test_complete_synthetic_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", passing_device_gates())

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_readme_phase4_owner_gates"])
        self.assertEqual(set(report["checks"]["owner_gates"]), set(OWNER_GATES))

    def test_report_matches_schema_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", passing_device_gates())
            report = derive_gate(readiness_path, device_path)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_cli_writes_blocked_report_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            readiness_path = write_json(root, "harmony-readiness.json", blocked_readiness())
            device_path = write_json(root, "harmony-device-gates.json", passing_device_gates())
            output_path = root / "harmony-current-base-gate.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--readiness",
                    str(readiness_path),
                    "--device-gates",
                    str(device_path),
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
