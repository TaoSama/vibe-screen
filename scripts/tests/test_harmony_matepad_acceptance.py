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


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "tools/schemas/harmony-matepad-acceptance.schema.json"
COMMIT = "a" * 40
TREE = "b" * 40
HASH = "1" * 64


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
        {"id": gate_id, "status": "pass", "evidence": [f"raw/{gate_id}.txt"]}
        for gate_id in harmony_device_gate.REQUIRED_GATE_IDS
    ]
    return manifest


def write_pass_artifacts(directory: Path, manifest: dict[str, object]) -> None:
    for gate in manifest["gates"]:
        for reference in gate["evidence"]:
            path = directory / reference
            path.parent.mkdir(parents=True, exist_ok=True)
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

    def test_write_blocked_creates_structural_manifest_and_blocked_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            readiness = passing_readiness()
            readiness["verdict"] = "blocked"
            readiness["blocking_reasons"] = ["hdc is unavailable"]
            readiness["device_gate_prefill"]["repository"]["status"] = "dirty"
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
        self.assertIn("repository.status: dirty", package["device_gate_manifest"]["warnings"])
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

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(package["verdict"], "pass")
        self.assertTrue(package["device_gate_manifest"]["strict_valid"])
        self.assertTrue(all(domain["status"] == "pass" for domain in package["acceptance_domains"]))
        self.assertTrue(all(reference["status"] == "present" for reference in package["artifact_references"]))

    def test_strict_manifest_with_missing_artifact_references_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(passing_device_manifest()), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        self.assertEqual(package["verdict"], "blocked")
        self.assertIn("missing or invalid local evidence references", "\n".join(package["blocking_reasons"]))
        self.assertTrue(any(reference["status"] == "missing" for reference in package["artifact_references"]))

    def test_external_artifact_references_can_support_strict_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest = passing_device_manifest()
            for gate in manifest["gates"]:
                gate["evidence"] = [f"artifact://release/harmony/{gate['id']}"]
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertTrue(all(reference["status"] == "external" for reference in package["artifact_references"]))

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

        validation = harmony_matepad_acceptance.validate_device_manifest(manifest)

        self.assertFalse(validation.strict_valid)
        self.assertFalse(validation.allow_blocked_valid)
        self.assertIn("Android evidence", validation.error or "")

    def test_absolute_or_escaping_artifact_references_are_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest = passing_device_manifest()
            manifest["gates"][0]["evidence"] = ["/tmp/private.log", "../outside.log"]
            (directory / "harmony-readiness.json").write_text(json.dumps(passing_readiness()), encoding="utf-8")
            (directory / "harmony-device-gates.json").write_text(json.dumps(manifest), encoding="utf-8")

            exit_code = run_main(["--evidence-dir", str(directory)])
            package = json.loads((directory / "harmony-matepad-acceptance.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_matepad_acceptance.BLOCKED_EXIT)
        invalid = [reference for reference in package["artifact_references"] if reference["status"] == "invalid"]
        self.assertEqual(len(invalid), 2)

    def test_blocked_device_manifest_keeps_acceptance_gates_blocked(self) -> None:
        manifest = harmony_matepad_acceptance.blocked_device_manifest(passing_readiness())

        warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)

        self.assertEqual(len(warnings), len(harmony_device_gate.REQUIRED_GATE_IDS))
        self.assertTrue(all(gate["evidence"] == ["harmony-readiness.json"] for gate in manifest["gates"]))


if __name__ == "__main__":
    unittest.main()
