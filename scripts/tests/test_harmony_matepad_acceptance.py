from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harmony_device_gate
import harmony_matepad_acceptance
from vibescreen_evidence.harmony_current_base_gate import derive_gate


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "tools/schemas/harmony-matepad-acceptance.schema.json"
COMMIT = "a" * 40
TREE = "b" * 40
HASH = "1" * 64
MARKER_BY_GATE = {
    "deveco_sdk_and_api_checker": "harmony-readiness.json",
    "signed_release_hap": "harmony-hap-readiness.json",
    "hap_install_launch": "harmony-hap-readiness.json",
    "hap_in_place_upgrade": "harmony-hap-readiness.json",
    "hap_rollback_behavior": "harmony-hap-readiness.json",
    "hap_uninstall_cleanup": "harmony-hap-readiness.json",
    "permission_denial_retry": "permission-denial-retry.log",
    "huks_backed_secure_pairing": "harmony-secure-pairing.json",
    "authenticated_transport_records": "harmony-authenticated-records.json",
    "credential_revocation_replay": "harmony-secure-pairing.json",
    "h264_hardware_decode": "harmony-avcodec-preflight.json",
    "hevc_hardware_decode": "harmony-avcodec-preflight.json",
    "host_protocol_v1_interop": "harmony-host-interop-preflight.json",
    "resume_background_foreground": "harmony-host-interop-preflight.json",
    "resume_network_roam": "harmony-host-interop-preflight.json",
    "resume_host_restart": "harmony-host-interop-preflight.json",
    "resume_capable_host_interop": "harmony-host-interop-preflight.json",
    "no_old_epoch_render": "harmony-host-interop-preflight.json",
    "ui_device_identity_record": "ui-tree.xml",
    "input_touch_keyboard_pointer_stylus": "input-observations.json",
    "eight_hour_soak": "soak-summary.json",
    "external_latency": "latency-report.json",
}


def run_main(arguments: list[str]) -> int:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return harmony_matepad_acceptance.main(arguments)


def passing_readiness() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "harmony_readiness_preflight",
        "verdict": "pass",
        "blocking_reasons": [],
        "toolchain": {
            "deveco_studio": {"status": "pass", "version": "DevEco Studio 6"},
            "hvigor": {"status": "pass", "version": "hvigor 5"},
            "ohpm": {"status": "pass", "version": "ohpm 5"},
            "hdc": {"status": "pass", "version": "hdc 5"},
        },
        "artifact": {
            "hap_path": "dist/release/vibescreen.hap",
            "hap_sha256": HASH,
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
        "host": {"commit": "c" * 40, "build_sha256": "5" * 64, "protocol": "Protocol v1"},
        "device_gate_prefill": {
            "repository": {"commit": COMMIT, "tree": TREE, "status": "clean"},
            "toolchain": {
                "deveco_studio_version": "DevEco Studio 6",
                "harmony_sdk_api": "API 12",
                "harmony_sdk_version": "HarmonyOS NEXT 5",
                "hvigor_version": "hvigor 5",
                "ohpm_version": "ohpm 5",
                "hdc_version": "hdc 5",
            },
            "artifact": {
                "bundle_name": "dev.vibescreen.harmony",
                "version_name": "0.1.0",
                "hap_sha256": HASH,
                "signature_certificate_sha256": "2" * 64,
                "sha256sums_sha256": "3" * 64,
            },
            "device": {
                "platform": "HarmonyOS NEXT",
                "manufacturer": "Huawei",
                "model": "MatePad Mini",
                "product": "MatePad Mini",
                "os_build": "HarmonyOS NEXT build 1",
                "hdc_target": "sha256:redacted",
                "serial_hash": "4" * 64,
            },
            "host": {"commit": "c" * 40, "build_sha256": "5" * 64, "protocol": "Protocol v1"},
        },
    }


def passing_device_manifest() -> dict[str, object]:
    manifest = harmony_device_gate.template_manifest()
    prefill = passing_readiness()["device_gate_prefill"]
    for key, value in prefill.items():
        manifest[key] = value
    manifest["gates"] = [
        {"id": gate_id, "status": "pass", "evidence": [f"evidence/{MARKER_BY_GATE[gate_id]}"]}
        for gate_id in harmony_device_gate.REQUIRED_GATE_IDS
    ]
    for gate in manifest["gates"]:
        if gate["id"] == "huks_backed_secure_pairing":
            gate["secure_pairing_manifest"] = {
                "schema": "dev.vibescreen.harmony-secure-pairing-gate/v1",
                "path": "harmony-secure-pairing.json",
                "status": "pass",
            }
    return manifest


def write_pass_artifacts(directory: Path, manifest: dict[str, object]) -> None:
    for gate in manifest["gates"]:
        for reference in gate["evidence"]:
            path = directory / reference
            path.parent.mkdir(parents=True, exist_ok=True)
            if reference.endswith("/"):
                path.mkdir(exist_ok=True)
            else:
                path.write_text(f"{gate['id']}\n", encoding="utf-8")


class HarmonyMatePadAcceptanceTests(unittest.TestCase):
    def test_acceptance_package_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            package = harmony_matepad_acceptance.build_package(
                command=["make", "harmony-matepad-acceptance"],
                evidence_dir=directory,
                readiness_path=directory / "harmony-readiness.json",
                device_manifest_path=directory / "harmony-device-gates.json",
                readiness=passing_readiness(),
                device_manifest=passing_device_manifest(),
                validation=harmony_matepad_acceptance.GateValidation(
                    strict_valid=True,
                    allow_blocked_valid=True,
                    warnings=[],
                    error=None,
                ),
                current_base_path=directory / "harmony-current-base-gate.json",
                current_base=harmony_matepad_acceptance.CurrentBaseValidation(
                    present=True,
                    verdict="pass",
                    can_close_readme_phase4_owner_gates=True,
                    can_claim_harmony_device_pass=True,
                    reasons=[],
                    error=None,
                ),
            )

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(package), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, package)
        self.assertEqual(
            set(package["readiness"]),
            set(schema["properties"]["readiness"]["properties"]),
        )
        self.assertEqual(
            set(package["device_gate_manifest"]),
            set(schema["properties"]["device_gate_manifest"]["properties"]),
        )
        self.assertEqual(
            set(package["current_base_gate"]),
            set(schema["properties"]["current_base_gate"]["properties"]),
        )

    def test_write_blocked_creates_structural_manifest_and_blocked_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            readiness = passing_readiness()
            readiness["verdict"] = "blocked"
            readiness["blocking_reasons"] = ["hdc is unavailable"]
            (directory / "harmony-readiness.json").write_text(json.dumps(readiness), encoding="utf-8")

            exit_code = run_main([
                "--evidence-dir",
                str(directory),
                "--write-blocked",
            ])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))
            device_gates = json.loads((directory / "harmony-device-gates.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["kind"], "harmony_matepad_mini_acceptance_package")
        self.assertEqual(package["verdict"], "blocked")
        self.assertEqual(package["current_base_gate"]["verdict"], "blocked")
        self.assertTrue(all(gate["status"] == "blocked" for gate in device_gates["gates"]))
        self.assertIn("hap_install_signing", {domain["id"] for domain in package["acceptance_domains"]})

    def test_missing_device_gate_manifest_without_write_blocked_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            exit_code = run_main(["--evidence-dir", str(directory)])

        self.assertEqual(exit_code, 1)

    def test_strict_pass_requires_readiness_pass_and_all_domain_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            manifest = passing_device_manifest()
            write_pass_artifacts(directory, manifest)
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")
            (directory / "harmony-current-base-gate.json").write_text(
                json.dumps(derive_gate(directory / "harmony-readiness.json", directory / "harmony-device-gates.json")),
                encoding="utf-8",
            )

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(package["verdict"], "pass")
        self.assertTrue(package["device_gate_manifest"]["strict_valid"])
        self.assertEqual(package["current_base_gate"]["verdict"], "pass")
        self.assertTrue(all(domain["status"] == "pass" for domain in package["acceptance_domains"]))
        self.assertTrue(all(reference["status"] == "present" for reference in package["artifact_references"]))

    def test_directory_artifact_references_can_pass_when_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            manifest = passing_device_manifest()
            for gate in manifest["gates"]:
                if gate["id"] == "ui_device_identity_record":
                    gate["evidence"] = ["screenshots/"]
            write_pass_artifacts(directory, manifest)
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(package["verdict"], "pass")

    def test_strict_manifest_with_missing_artifact_references_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(passing_device_manifest()), encoding="utf-8")
            (directory / "harmony-current-base-gate.json").write_text(
                json.dumps(derive_gate(directory / "harmony-readiness.json", directory / "harmony-device-gates.json")),
                encoding="utf-8",
            )

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["verdict"], "blocked")
        self.assertIn("missing or invalid local evidence references", "\n".join(package["blocking_reasons"]))
        self.assertTrue(any(reference["status"] == "missing" for reference in package["artifact_references"]))

    def test_stale_current_base_gate_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            readiness = passing_readiness()
            readiness["verdict"] = "blocked"
            readiness["blocking_reasons"] = ["hdc is unavailable"]
            (directory / "harmony-readiness.json").write_text(json.dumps(readiness), encoding="utf-8")
            manifest = passing_device_manifest()
            write_pass_artifacts(directory, manifest)
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")
            (directory / "harmony-current-base-gate.json").write_text(
                json.dumps(
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "harmony_current_base_owner_gate",
                        "verdict": "pass",
                        "can_close_readme_phase4_owner_gates": True,
                        "can_claim_harmony_device_pass": True,
                        "reasons": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["verdict"], "blocked")
        self.assertEqual(package["current_base_gate"]["verdict"], "blocked")
        self.assertIn("HarmonyOS current-base owner gate is not pass", package["blocking_reasons"])

    def test_external_artifact_references_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest = passing_device_manifest()
            for gate in manifest["gates"]:
                gate["evidence"] = [f"artifact://release/harmony/{gate['id']}"]
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["verdict"], "blocked")
        self.assertTrue(all(reference["status"] == "invalid" for reference in package["artifact_references"]))
        self.assertIn("expected repository-local evidence path", package["device_gate_manifest"]["error"] or "")

    def test_failed_device_gate_writes_structured_fail_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            manifest = passing_device_manifest()
            write_pass_artifacts(directory, manifest)
            for gate in manifest["gates"]:
                if gate["id"] == "external_latency":
                    gate["status"] = "fail"
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["verdict"], "fail")
        self.assertEqual(package["current_base_gate"]["verdict"], "fail")
        self.assertIn("sustained_operation", {domain["id"] for domain in package["acceptance_domains"] if domain["status"] == "fail"})

    def test_write_blocked_does_not_overwrite_existing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            manifest = passing_device_manifest()
            write_pass_artifacts(directory, manifest)
            manifest_path = directory / "harmony-device-gates.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory), "--write-blocked"])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))
            preserved = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(package["verdict"], "pass")
        self.assertTrue(all(gate["status"] == "pass" for gate in preserved["gates"]))

    def test_android_device_manifest_fails_closed(self) -> None:
        manifest = passing_device_manifest()
        manifest["device"] = {
            "platform": "Android",
            "manufacturer": "nubia",
            "model": "P0110",
            "product": "pacific",
            "os_build": "Android 16",
            "hdc_target": "not-applicable",
            "serial_hash": "4" * 64,
        }

        validation = harmony_matepad_acceptance.validate_device_manifest(manifest, evidence_root=Path("."))

        self.assertFalse(validation.strict_valid)
        self.assertFalse(validation.allow_blocked_valid)
        self.assertIn("Android evidence", validation.error or "")

    def test_absolute_or_escaping_artifact_references_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest = passing_device_manifest()
            manifest["gates"][0]["evidence"] = ["/tmp/private.log", "../outside.log", "./"]
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        invalid = [reference for reference in package["artifact_references"] if reference["status"] == "invalid"]
        self.assertEqual(len(invalid), 3)

    def test_blocked_device_manifest_keeps_acceptance_gates_blocked(self) -> None:
        manifest = harmony_matepad_acceptance.blocked_device_manifest(passing_readiness())

        warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)

        self.assertEqual(len(warnings), len(harmony_device_gate.REQUIRED_GATE_IDS))
        self.assertTrue(all(gate["evidence"] == ["harmony-readiness.json"] for gate in manifest["gates"]))


if __name__ == "__main__":
    unittest.main()
