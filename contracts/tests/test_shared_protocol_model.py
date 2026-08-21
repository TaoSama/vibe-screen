from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "contracts" / "shared-models" / "v1" / "manifest.json"
VERIFIER = REPO_ROOT / "scripts" / "verify_shared_protocol_model.py"


class SharedProtocolModelVerifierTest(unittest.TestCase):
    def run_with_manifest(self, document: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="vibescreen-shared-model-") as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return subprocess.run(
                ["python3", str(VERIFIER), "--manifest", str(manifest)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

    def test_manifest_verifies_current_android_ios_protocol_boundary(self) -> None:
        result = subprocess.run(
            ["python3", str(VERIFIER)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("shared protocol model verified", result.stdout)

    def test_manifest_fails_closed_when_required_capability_number_drifts(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["capabilities"]["CAPABILITY_USB_HID_MODIFIER_BYTE"]["value"] = 127
        result = self.run_with_manifest(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CAPABILITY_USB_HID_MODIFIER_BYTE", result.stderr)

    def test_manifest_fails_closed_when_shared_message_field_number_drifts(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["messages"]["DisplayDescriptor"]["fields"]["scale_factor"] = 99
        result = self.run_with_manifest(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DisplayDescriptor fields", result.stderr)

    def test_manifest_fails_closed_when_required_fixture_is_missing(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["requiredFixtureNames"].append("missing_cross_platform_fixture")
        result = self.run_with_manifest(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing_cross_platform_fixture", result.stderr)

    def test_manifest_fails_closed_when_envelope_payload_number_drifts(self) -> None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        document["envelopePayloads"]["managed_policy_status"] = 199
        result = self.run_with_manifest(document)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Envelope payload field numbers", result.stderr)


if __name__ == "__main__":
    unittest.main()
