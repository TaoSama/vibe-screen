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


def write_referenced_evidence(root: Path, manifest: dict[str, object]) -> None:
    gates = manifest["gates"]
    assert isinstance(gates, list)
    for gate in gates:
        assert isinstance(gate, dict)
        evidence = gate["evidence"]
        assert isinstance(evidence, list)
        for reference in evidence:
            assert isinstance(reference, str)
            artifact = root / reference
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(f"{gate['id']} evidence\n", encoding="utf-8")


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
        "deveco_sdk_and_api_checker": "harmony-readiness.json",
        "h264_hardware_decode": "harmony-avcodec-preflight.json",
        "hevc_hardware_decode": "harmony-avcodec-preflight.json",
        "signed_release_hap": "harmony-hap-readiness.json",
        "hap_install_launch": "harmony-hap-readiness.json",
        "hap_in_place_upgrade": "harmony-hap-readiness.json",
        "hap_rollback_behavior": "harmony-hap-readiness.json",
        "hap_uninstall_cleanup": "harmony-hap-readiness.json",
        "huks_backed_secure_pairing": "harmony-secure-pairing.json",
        "credential_revocation_replay": "harmony-secure-pairing.json",
        "authenticated_transport_records": "harmony-authenticated-records.json",
        "host_protocol_v1_interop": "harmony-host-interop-preflight.json",
        "resume_background_foreground": "harmony-host-interop-preflight.json",
        "resume_network_roam": "harmony-host-interop-preflight.json",
        "resume_host_restart": "harmony-host-interop-preflight.json",
        "no_old_epoch_render": "harmony-host-interop-preflight.json",
        "resume_capable_host_interop": "harmony-host-interop-preflight.json",
        "permission_denial_retry": "permission-denial-retry.log",
        "ui_device_identity_record": "ui-tree.xml",
        "input_touch_keyboard_pointer_stylus": "input-observations.json",
        "eight_hour_soak": "soak-summary.json",
        "external_latency": "latency-report.json",
    }
    gates = []
    for gate_id in gate_ids:
        gate: dict[str, object] = {
            "id": gate_id,
            "status": "pass",
            "evidence": [f"evidence/{marker_by_gate[gate_id]}"],
        }
        if gate_id == "huks_backed_secure_pairing":
            gate["secure_pairing_manifest"] = {
                "schema": "dev.vibescreen.harmony-secure-pairing-gate/v1",
                "path": "harmony-secure-pairing.json",
                "status": "pass",
            }
        gates.append(gate)

    return {
        "schema": "dev.vibescreen.harmony-device-gates/v1",
        "repository": {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "status": "clean",
        },
        "toolchain": {
            "deveco_studio_version": "DevEco Studio 6",
            "harmony_sdk_api": "API 12",
            "harmony_sdk_version": "HarmonyOS NEXT 5.0.0",
            "hvigor_version": "hvigor 5",
            "ohpm_version": "ohpm 5",
            "hdc_version": "hdc 5",
        },
        "artifact": {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": "1" * 64,
            "signature_certificate_sha256": "2" * 64,
            "sha256sums_sha256": "3" * 64,
        },
        "device": {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "HarmonyOS NEXT build 1",
            "hdc_target": "redacted-hdc-target",
            "serial_hash": "6" * 64,
        },
        "host": {
            "commit": "a" * 40,
            "build_sha256": "4" * 64,
            "protocol": "Protocol v1",
        },
        "gates": gates,
    }


class HarmonyCurrentBaseGateTests(unittest.TestCase):
    def test_missing_hardware_environment_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            readiness_path = write_json(root, "harmony-readiness.json", blocked_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase4_owner_gates"])
        self.assertFalse(report["can_claim_harmony_device_pass"])
        self.assertIn("blocked: readiness.readiness_manifest", report["reasons"])
        self.assertIn("blocked: readiness.deveco", report["reasons"])
        self.assertIn("blocked: readiness.hap", report["reasons"])
        self.assertIn("blocked: readiness.matepad", report["reasons"])
        self.assertIn("blocked: readiness.host", report["reasons"])

    def test_zero_hash_placeholders_are_not_metadata_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            device_gates["artifact"] = {
                "bundle_name": "dev.vibescreen.harmony",
                "version_name": "0.1.0",
                "hap_sha256": "0" * 64,
                "signature_certificate_sha256": "0" * 64,
                "sha256sums_sha256": "0" * 64,
            }
            device_gates["host"] = {
                "commit": "0" * 40,
                "build_sha256": "0" * 64,
                "protocol": "Protocol v1",
            }
            readiness_path = write_json(root, "harmony-readiness.json", blocked_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["checks"]["device_manifest"]["signed_hap_artifact"]["passed"])
        self.assertFalse(report["checks"]["device_manifest"]["protocol_v1_host"]["passed"])
        self.assertIn("blocked: device_manifest.signed_hap_artifact", report["reasons"])
        self.assertIn("blocked: device_manifest.protocol_v1_host", report["reasons"])

    def test_missing_owner_gate_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            write_referenced_evidence(root, manifest)
            gates = manifest["gates"]
            assert isinstance(gates, list)
            gates[:] = [gate for gate in gates if gate["id"] != "resume_host_restart"]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.host_resume_interop", report["reasons"])
        self.assertFalse(report["checks"]["owner_gates"]["host_resume_interop"]["passed"])

    def test_missing_deveco_owner_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            write_referenced_evidence(root, manifest)
            gates = manifest["gates"]
            assert isinstance(gates, list)
            gates[:] = [gate for gate in gates if gate["id"] != "deveco_sdk_and_api_checker"]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.deveco_build", report["reasons"])
        self.assertFalse(report["checks"]["owner_gates"]["deveco_build"]["passed"])

    def test_missing_hap_owner_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            write_referenced_evidence(root, manifest)
            gates = manifest["gates"]
            assert isinstance(gates, list)
            gates[:] = [
                gate
                for gate in gates
                if gate["id"]
                not in {
                    "signed_release_hap",
                    "hap_install_launch",
                    "hap_in_place_upgrade",
                    "hap_rollback_behavior",
                    "hap_uninstall_cleanup",
                }
            ]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.hap_sign_install", report["reasons"])
        self.assertFalse(report["checks"]["owner_gates"]["hap_sign_install"]["passed"])

    def test_missing_security_transport_or_matepad_evidence_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            write_referenced_evidence(root, manifest)
            gates = manifest["gates"]
            assert isinstance(gates, list)
            gates[:] = [
                gate
                for gate in gates
                if gate["id"]
                not in {
                    "huks_backed_secure_pairing",
                    "authenticated_transport_records",
                    "eight_hour_soak",
                }
            ]
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", manifest)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: owner_gate.huks_secure_pairing", report["reasons"])
        self.assertIn("blocked: owner_gate.authenticated_transport", report["reasons"])
        self.assertIn("blocked: owner_gate.matepad_acceptance", report["reasons"])

    def test_generic_evidence_reference_cannot_close_owner_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = passing_device_gates()
            write_referenced_evidence(root, manifest)
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

    def test_matepad_owner_accepts_raw_artifact_markers_without_self_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["checks"]["owner_gates"]["matepad_acceptance"]["passed"])

    def test_failed_device_gate_reports_fail_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            gates = device_gates["gates"]
            assert isinstance(gates, list)
            for gate in gates:
                if gate["id"] == "external_latency":
                    gate["status"] = "fail"
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("fail: device_gate.external_latency", report["reasons"])
        self.assertFalse(report["can_claim_harmony_device_pass"])

    def test_android_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
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
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)

            report = derive_gate(readiness_path, device_path)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_readme_phase4_owner_gates"])
        self.assertEqual(set(report["checks"]["owner_gates"]), set(OWNER_GATES))

    def test_report_matches_schema_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            device_gates = passing_device_gates()
            write_referenced_evidence(root, device_gates)
            readiness_path = write_json(root, "harmony-readiness.json", passing_readiness())
            device_path = write_json(root, "harmony-device-gates.json", device_gates)
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
                cwd=Path(__file__).parents[1],
                check=False,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
