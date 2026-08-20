from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.ios_device_acceptance_gate import (
    ACCEPTANCE_KIND,
    REQUIRED_GATES,
    evaluate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.ios_device_acceptance_gate"
SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "ios-device-acceptance-gate.schema.json"


def write_artifacts(directory: Path, names: list[str]) -> None:
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact: {name}\n", encoding="utf-8")


def complete_document() -> dict:
    gates = {
        name: {"status": "complete", "evidence": [f"artifacts/{name}.txt"]}
        for name in REQUIRED_GATES
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": ACCEPTANCE_KIND,
        "platform": "ios",
        "status": "complete",
        "repository": {"commit": "abc123", "branch": "codex/ios-device-acceptance-gate", "dirty": False},
        "host": {
            "commit": "def456",
            "macos_version": "26.4.1",
            "permissions_changed_by_run": False,
        },
        "xcode": {
            "version": "16.4",
            "selected_developer_dir": "/Applications/Xcode.app",
            "ios_sdk": "18.5",
        },
        "trusted_lan": {
            "mode": "explicit_plaintext_legacy_fallback",
            "encrypted_lan_claimed": False,
        },
        "signing": {
            "status": "complete",
            "bundle_id": "dev.example.vibescreen.acceptance",
            "team_id_redacted": True,
            "certificate_common_name_redacted": True,
            "provisioning_profile_uuid_redacted": True,
            "archive_sha256": "sha256:" + "a" * 64,
        },
        "devices": [
            {
                "role": "iphone",
                "product_name": "iPhone 15",
                "hardware_model": "iPhone15,4",
                "os_version": "18.5",
                "build_number": "22F76",
                "install_status": "complete",
            },
            {
                "role": "ipad",
                "product_name": "iPad Pro",
                "hardware_model": "iPad14,5",
                "os_version": "18.5",
                "build_number": "22F76",
                "install_status": "complete",
            },
        ],
        "gates": gates,
        "android_evidence_used_for_ios_gates": False,
        "notes": [],
    }


class IOSDeviceAcceptanceGateTest(unittest.TestCase):
    def test_accepts_complete_iphone_and_ipad_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )

            result = evaluate(complete_document(), evidence_root)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["covered_devices"], ["ipad", "iphone"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["failures"], [])

    def test_result_shape_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            result = evaluate(complete_document(), evidence_root)

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(result), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, result)

    def test_missing_ipad_and_open_gate_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["devices"] = [document["devices"][0]]
            document["gates"]["reconnect"]["status"] = "open"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn("devices: missing ipad hardware evidence", result["missing"])
        self.assertIn("gates.reconnect.status: must be complete", result["missing"])

    def test_android_identity_or_android_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["android_evidence_used_for_ios_gates"] = True
            document["devices"][0]["product_name"] = "Nubia P0110 Android 16"
            document["gates"]["input"]["evidence"] = ["artifacts/android-input.txt"]
            write_artifacts(evidence_root, ["artifacts/android-input.txt"])

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("android_evidence_used_for_ios_gates: must be false", result["failures"])
        self.assertIn("devices[0].product_name: looks like Android evidence", result["failures"])
        self.assertIn(
            "gates.input.evidence[0]: must not reference Android evidence for an iOS gate",
            result["failures"],
        )

    def test_simulator_identity_or_encrypted_lan_claim_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["trusted_lan"]["encrypted_lan_claimed"] = True
            document["devices"][0]["product_name"] = "iPhone 17 Pro Simulator"
            document["signing"]["archive_sha256"] = "unsigned-simulator.zip"
            document["gates"]["protocol_session"]["evidence"] = ["artifacts/simulator-session.txt"]
            write_artifacts(evidence_root, ["artifacts/simulator-session.txt"])

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("trusted_lan.encrypted_lan_claimed: must be false", result["failures"])
        self.assertIn(
            "devices[0].product_name: must be physical iOS hardware, not Simulator",
            result["failures"],
        )
        self.assertIn(
            "signing.archive_sha256: must not reference unsigned or Simulator artifacts",
            result["failures"],
        )
        self.assertIn(
            "gates.protocol_session.evidence[0]: must not reference Simulator evidence for an iOS gate",
            result["failures"],
        )
        self.assertIn(
            "signing.archive_sha256: must be a SHA-256 digest",
            result["missing"],
        )

    def test_placeholder_archive_hash_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["signing"]["archive_sha256"] = "sha256:1234"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "signing.archive_sha256: must be a SHA-256 digest",
            result["missing"],
        )

    def test_missing_or_escaping_artifact_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["gates"]["audio_playback"]["evidence"] = ["missing-audio.log"]
            document["gates"]["reconnect"]["evidence"] = ["../outside.log"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "gates.audio_playback.evidence[0]: missing retained artifact missing-audio.log",
            result["missing"],
        )
        self.assertIn(
            "gates.reconnect.evidence[0]: must stay within the evidence root",
            result["missing"],
        )

    def test_failed_status_or_unredacted_signing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["status"] = "failed"
            document["signing"]["team_id_redacted"] = False
            document["host"]["permissions_changed_by_run"] = True

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("status: is failed", result["failures"])
        self.assertIn("signing.team_id_redacted: must be true in committed sanitized evidence", result["failures"])
        self.assertIn("host.permissions_changed_by_run: must be false for this acceptance runbook", result["failures"])


class IOSDeviceAcceptanceGateCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_writes_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            input_path = evidence_root / "acceptance.json"
            output_path = evidence_root / "ios-device-acceptance-gate.json"
            input_path.write_text(json.dumps(complete_document()), encoding="utf-8")

            result = self.run_cli(
                "--acceptance", str(input_path), "--output", str(output_path)
            )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(persisted["verdict"], "pass")

    def test_cli_returns_insufficient_for_open_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(
                evidence_root, [f"artifacts/{name}.txt" for name in REQUIRED_GATES]
            )
            document = complete_document()
            document["status"] = "open"
            input_path = evidence_root / "acceptance.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("--acceptance", str(input_path))

        self.assertEqual(result.returncode, 1)
        self.assertIn("status: must be complete", result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "insufficient")

    def test_cli_returns_error_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            input_path = Path(raw_directory) / "acceptance.json"
            input_path.write_text("not-json", encoding="utf-8")

            result = self.run_cli("--acceptance", str(input_path))

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
