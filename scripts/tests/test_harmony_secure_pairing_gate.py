import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "harmony_secure_pairing_gate.py"
DEVICE_GATE_SCRIPT = ROOT / "scripts" / "harmony_device_gate.py"

spec = importlib.util.spec_from_file_location("harmony_secure_pairing_gate", SCRIPT)
secure_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secure_gate)

device_spec = importlib.util.spec_from_file_location("harmony_device_gate", DEVICE_GATE_SCRIPT)
device_gate = importlib.util.module_from_spec(device_spec)
device_spec.loader.exec_module(device_gate)


class HarmonySecurePairingGateTest(unittest.TestCase):
    def complete_manifest(self):
        manifest = secure_gate.template_manifest()
        manifest["repository"] = {
            "commit": "1" * 40,
            "tree": "2" * 40,
            "status": "clean",
        }
        manifest["artifact"] = {
            "hap_sha256": "3" * 64,
            "signature_certificate_sha256": "4" * 64,
        }
        manifest["device"]["serial_hash"] = "5" * 64
        manifest["services"]["authority"]["commit"] = "6" * 40
        manifest["services"]["signaling"]["commit"] = "7" * 40
        for check in manifest["checks"]:
            check["status"] = "pass"
            check["evidence"] = [f"redacted/{check['id']}.txt"]
        return manifest

    def write_evidence_files(self, root, manifest):
        for check in manifest["checks"]:
            for reference in check["evidence"]:
                artifact = root / reference
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("redacted evidence\n", encoding="utf-8")

    def test_complete_huks_pairing_manifest_passes(self):
        self.assertEqual([], secure_gate.validate_manifest(self.complete_manifest()))

    def test_strict_pass_evidence_must_exist_under_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self.complete_manifest()
            self.write_evidence_files(root, manifest)

            self.assertEqual([], secure_gate.validate_manifest(manifest, evidence_root=root))

            missing = copy.deepcopy(manifest)
            missing["checks"][0]["evidence"] = ["redacted/missing.txt"]
            with self.assertRaisesRegex(secure_gate.ManifestError, "missing evidence artifact"):
                secure_gate.validate_manifest(missing, evidence_root=root)

            escaped = copy.deepcopy(manifest)
            escaped["checks"][0]["evidence"] = ["../outside.txt"]
            with self.assertRaisesRegex(secure_gate.ManifestError, "must not escape"):
                secure_gate.validate_manifest(escaped, evidence_root=root)

            absolute = copy.deepcopy(manifest)
            absolute["checks"][0]["evidence"] = [str(root / "redacted" / "huks_non_exportable_identity.txt")]
            with self.assertRaisesRegex(secure_gate.ManifestError, "relative to evidence root"):
                secure_gate.validate_manifest(absolute, evidence_root=root)

            url = copy.deepcopy(manifest)
            url["checks"][0]["evidence"] = ["https://example.invalid/evidence.txt"]
            with self.assertRaisesRegex(secure_gate.ManifestError, "got URL"):
                secure_gate.validate_manifest(url, evidence_root=root)

            directory = copy.deepcopy(manifest)
            directory["checks"][0]["evidence"] = ["redacted"]
            with self.assertRaisesRegex(secure_gate.ManifestError, "expected evidence artifact file"):
                secure_gate.validate_manifest(directory, evidence_root=root)

            blocked = secure_gate.template_manifest()
            self.assertTrue(secure_gate.validate_manifest(blocked, allow_blocked=True, evidence_root=root))

    def test_blocked_manifest_is_structure_only(self):
        manifest = secure_gate.template_manifest()
        warnings = secure_gate.validate_manifest(manifest, allow_blocked=True)
        self.assertIn("huks_non_exportable_identity: blocked", warnings)
        with self.assertRaises(secure_gate.ManifestError):
            secure_gate.validate_manifest(manifest)

    def test_android_or_exportable_key_cannot_close_gate(self):
        android = self.complete_manifest()
        android["device"]["platform"] = "Android"
        with self.assertRaisesRegex(secure_gate.ManifestError, "Android evidence"):
            secure_gate.validate_manifest(android)

        exportable = self.complete_manifest()
        exportable["crypto"]["signing_key_exportable"] = True
        with self.assertRaisesRegex(secure_gate.ManifestError, "signing_key_exportable"):
            secure_gate.validate_manifest(exportable)

    def test_local_blocked_service_mode_cannot_close_gate(self):
        manifest = self.complete_manifest()
        manifest["services"]["authority"]["mode"] = "local_blocked"
        with self.assertRaisesRegex(secure_gate.ManifestError, "local_blocked cannot close"):
            secure_gate.validate_manifest(manifest)
        self.assertEqual([], secure_gate.validate_manifest(manifest, allow_blocked=True))

    def test_cli_rejects_missing_legacy_and_no_huks_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest()
            manifest["checks"] = [check for check in manifest["checks"] if check["id"] != "legacy_peer_rejection"]
            self.write_evidence_files(root, manifest)
            path = root / "harmony-secure-pairing.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(["python3", str(SCRIPT), str(path)], check=False, text=True,
                                    capture_output=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("legacy_peer_rejection", result.stderr)

    def test_cli_strict_mode_defaults_evidence_root_to_manifest_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self.complete_manifest()
            self.write_evidence_files(root, manifest)
            path = root / "harmony-secure-pairing.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")

            result = subprocess.run(["python3", str(SCRIPT), str(path)], check=False, text=True,
                                    capture_output=True, timeout=30)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("passes all required gates", result.stdout)

    def test_device_manifest_requires_secure_pairing_manifest_reference(self):
        manifest = device_gate.template_manifest()
        manifest["repository"] = {"commit": "1" * 40, "tree": "2" * 40, "status": "clean"}
        manifest["artifact"].update({
            "hap_sha256": "3" * 64,
            "signature_certificate_sha256": "4" * 64,
            "sha256sums_sha256": "5" * 64,
        })
        manifest["device"]["serial_hash"] = "6" * 64
        manifest["host"] = {"commit": "7" * 40, "build_sha256": "8" * 64, "protocol": "Protocol v1"}
        for gate in manifest["gates"]:
            gate["status"] = "pass"
            gate["evidence"] = [
                "redacted/harmony-avcodec-preflight.json"
                if gate["id"] in device_gate.AVCODEC_GATE_IDS
                else f"redacted/{gate['id']}.txt"
            ]
            if gate["id"] == "huks_backed_secure_pairing":
                gate["secure_pairing_manifest"]["status"] = "pass"
        broken = copy.deepcopy(manifest)
        for gate in broken["gates"]:
            if gate["id"] == "huks_backed_secure_pairing":
                gate.pop("secure_pairing_manifest", None)
        with self.assertRaisesRegex(device_gate.ManifestError, "secure_pairing_manifest"):
            device_gate.validate_manifest(broken)
        self.assertEqual([], device_gate.validate_manifest(manifest))


if __name__ == "__main__":
    unittest.main()
