from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.ios_app_signing_readiness import READINESS_KIND, evaluate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.ios_app_signing_readiness"
SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "ios-app-signing-readiness-gate.schema.json"


def write_artifacts(directory: Path, names: list[str]) -> None:
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact: {name}\n", encoding="utf-8")


def complete_document() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": READINESS_KIND,
        "platform": "ios",
        "status": "complete",
        "repository": {
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "branch": "codex/ios-signing-readiness",
            "dirty": False,
        },
        "xcode": {
            "version": "Xcode 16.4",
            "selected_developer_dir": "/Applications/Xcode.app/Contents/Developer",
            "ios_sdk": "iphoneos18.5",
        },
        "signing": {
            "status": "complete",
            "team_id": "ABCDE12345",
            "provisioning_profile_uuid": "12345678-1234-1234-1234-1234567890AB",
            "bundle_id": "dev.example.vibescreen.acceptance",
            "codesign_identity": "Apple Development: Example Developer (ABCDE12345)",
            "device_udids": ["sha256:" + "1" * 64],
            "entitlements": {
                "application_identifier": "ABCDE12345.dev.example.vibescreen.acceptance",
                "team_identifier": "ABCDE12345",
                "bundle_identifier": "dev.example.vibescreen.acceptance",
                "keychain_access_groups": ["ABCDE12345.dev.example.vibescreen.acceptance"],
                "raw_entitlements_sha256": "2" * 64,
            },
            "signed_artifact_sha256": "3" * 64,
        },
        "artifacts": [
            "logs/xcodebuild-archive.txt",
            "logs/codesign-entitlements.txt",
            "logs/profile-summary.txt",
        ],
        "simulator_build": False,
        "unsigned_build": False,
        "android_evidence_used_for_ios_signing": False,
        "notes": [],
    }


class IOSAppSigningReadinessTests(unittest.TestCase):
    def test_complete_signing_readiness_passes_without_claiming_device_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            write_artifacts(evidence_root, list(complete_document()["artifacts"]))

            result = evaluate(complete_document(), evidence_root)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(
            result["owner"]["role"],
            "ios_app_signing_readiness_current_base_owner",
        )
        self.assertEqual(result["owner"]["head_ref"], "codex/phase5-ios-signing-readiness")
        self.assertEqual(result["owner"]["repository"], "TaoSama/vibe-screen")
        self.assertEqual(
            result["current_base"],
            {
                "commit": "0123456789abcdef0123456789abcdef01234567",
                "branch": "codex/ios-signing-readiness",
                "dirty": False,
            },
        )
        self.assertEqual(
            result["signing_summary"],
            {
                "status": "pass",
                "bundle_id": "dev.example.vibescreen.acceptance",
                "unique_bundle_id": True,
                "team_id_recorded": True,
                "codesign_identity_recorded": True,
                "provisioning_profile_recorded": True,
                "device_udid_hashes_recorded": True,
                "entitlements_recorded": True,
                "signed_artifact_sha256": "3" * 64,
            },
        )
        self.assertTrue(result["can_close_ios_app_signing_readiness"])
        self.assertFalse(result["can_close_ios_device_acceptance"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["failures"], [])

    def test_result_shape_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            result = evaluate(document, evidence_root)

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(result), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, result)

    def test_blocked_readiness_fixture_matches_input_schema_shape(self) -> None:
        document = complete_document()
        document["status"] = "blocked"
        document["repository"] = {"commit": None, "branch": None, "dirty": None}
        document["xcode"] = {"version": "", "selected_developer_dir": "", "ios_sdk": ""}
        document["signing"] = {
            "status": "blocked",
            "team_id": "",
            "provisioning_profile_uuid": "",
            "bundle_id": "",
            "codesign_identity": "",
            "device_udids": [],
            "entitlements": {
                "application_identifier": "",
                "team_identifier": "",
                "bundle_identifier": "",
                "keychain_access_groups": [],
                "raw_entitlements_sha256": "",
            },
            "signed_artifact_sha256": "",
        }
        document["artifacts"] = []

        result = evaluate(document, Path.cwd())

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_close_ios_app_signing_readiness"])

    def test_prefixed_signed_artifact_digest_is_normalized_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            signing = document["signing"]
            assert isinstance(signing, dict)
            signing["signed_artifact_sha256"] = "sha256:" + "A" * 64

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["signing_summary"]["signed_artifact_sha256"], "a" * 64)

    def test_missing_critical_signing_fields_block(self) -> None:
        field_expectations = {
            "team_id": "signing.team_id: must be a non-empty recorded value",
            "provisioning_profile_uuid": "signing.provisioning_profile_uuid: must be a non-empty recorded value",
            "bundle_id": "signing.bundle_id: must be a non-empty recorded value",
            "codesign_identity": "signing.codesign_identity: must be a non-empty recorded value",
            "device_udids": "signing.device_udids: must include at least one registered physical-device UDID hash",
            "entitlements": "signing.entitlements: must be an object",
            "signed_artifact_sha256": "signing.signed_artifact_sha256: must be a non-empty recorded value",
        }
        for field, expected in field_expectations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw_directory:
                evidence_root = Path(raw_directory)
                document = complete_document()
                write_artifacts(evidence_root, list(document["artifacts"]))
                signing = document["signing"]
                assert isinstance(signing, dict)
                signing.pop(field)

                result = evaluate(document, evidence_root)

                self.assertEqual(result["verdict"], "blocked")
                self.assertFalse(result["can_close_ios_app_signing_readiness"])
                self.assertIn(expected, result["missing"])

    def test_invalid_shapes_and_default_bundle_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            signing = document["signing"]
            assert isinstance(signing, dict)
            signing["team_id"] = "bad-team"
            signing["provisioning_profile_uuid"] = "not-a-uuid"
            signing["bundle_id"] = "dev.vibescreen.ios"
            signing["device_udids"] = ["raw-device-udid"]
            signing["signed_artifact_sha256"] = "1234"
            entitlements = signing["entitlements"]
            assert isinstance(entitlements, dict)
            entitlements["team_identifier"] = "bad-team"
            entitlements["bundle_identifier"] = "dev.vibescreen.ios"
            entitlements["raw_entitlements_sha256"] = "abcd"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("signing.team_id: must be a 10-character Apple Team ID", result["missing"])
        self.assertIn("signing.provisioning_profile_uuid: must be a UUID", result["missing"])
        self.assertIn("signing.bundle_id: must be a unique non-default bundle identifier", result["missing"])
        self.assertIn("signing.device_udids[0]: must be a SHA-256 hash, not a raw UDID or placeholder", result["missing"])
        self.assertIn("signing.signed_artifact_sha256: must be a SHA-256 digest", result["missing"])
        self.assertIn("signing.entitlements.raw_entitlements_sha256: must be a SHA-256 digest", result["missing"])

    def test_current_base_repository_must_be_clean_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            repository = document["repository"]
            assert isinstance(repository, dict)
            repository["commit"] = "not-a-commit"
            repository["dirty"] = True

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_close_ios_app_signing_readiness"])
        self.assertIn("repository.commit: must be a 40-character current-base commit SHA", result["missing"])
        self.assertIn("repository.dirty: must be false for current-base signing readiness", result["missing"])
        self.assertIsNone(result["current_base"]["commit"])
        self.assertTrue(result["current_base"]["dirty"])

    def test_entitlement_identity_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            signing = document["signing"]
            assert isinstance(signing, dict)
            entitlements = signing["entitlements"]
            assert isinstance(entitlements, dict)
            entitlements["team_identifier"] = "ZZZZZ99999"
            entitlements["bundle_identifier"] = "dev.example.other"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("signing.entitlements.team_identifier: must match signing.team_id", result["failures"])
        self.assertIn("signing.entitlements.bundle_identifier: must match signing.bundle_id", result["failures"])

    def test_entitlements_must_belong_to_team_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            signing = document["signing"]
            assert isinstance(signing, dict)
            entitlements = signing["entitlements"]
            assert isinstance(entitlements, dict)
            entitlements["application_identifier"] = "WRONGTEAM.dev.example.other"
            entitlements["keychain_access_groups"] = ["WRONGTEAM.dev.example.other"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "signing.entitlements.application_identifier: must match Team ID and bundle ID",
            result["failures"],
        )
        self.assertIn(
            "signing.entitlements.keychain_access_groups: must include Team ID and bundle ID",
            result["failures"],
        )

    def test_simulator_unsigned_adhoc_or_android_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            document["simulator_build"] = True
            document["unsigned_build"] = True
            document["android_evidence_used_for_ios_signing"] = True
            document["artifacts"] = ["logs/simulator-unsigned.txt", "logs/nubia-adb.txt"]
            write_artifacts(evidence_root, list(document["artifacts"]))
            signing = document["signing"]
            assert isinstance(signing, dict)
            signing["codesign_identity"] = "ad-hoc"

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("simulator_build: Simulator output cannot close iOS app-signing readiness", result["failures"])
        self.assertIn("unsigned_build: unsigned output cannot close iOS app-signing readiness", result["failures"])
        self.assertIn("android_evidence_used_for_ios_signing: must be false", result["failures"])
        self.assertIn("signing.codesign_identity: must be a real Apple signing identity, not ad-hoc", result["failures"])
        self.assertIn("artifacts[0]: must not reference Simulator, unsigned, or ad-hoc evidence", result["failures"])
        self.assertIn("artifacts[1]: must not reference Android evidence for iOS signing", result["failures"])

    def test_simulator_unsigned_and_android_flags_must_be_explicitly_false(self) -> None:
        for field in (
            "simulator_build",
            "unsigned_build",
            "android_evidence_used_for_ios_signing",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw_directory:
                evidence_root = Path(raw_directory)
                document = complete_document()
                write_artifacts(evidence_root, list(document["artifacts"]))
                document.pop(field)

                result = evaluate(document, evidence_root)

                self.assertEqual(result["verdict"], "blocked")
                self.assertIn(f"{field}: must be explicitly false", result["missing"])

    def test_missing_or_escaping_artifact_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            document["artifacts"] = ["missing-profile.txt", "../outside.txt"]

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("artifacts[0]: missing retained artifact missing-profile.txt", result["missing"])
        self.assertIn("artifacts[1]: must stay within the evidence root", result["missing"])

    def test_missing_required_artifact_categories_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            document["artifacts"] = ["logs/signing-output.txt"]
            write_artifacts(evidence_root, list(document["artifacts"]))

            result = evaluate(document, evidence_root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "artifacts.archive_command: must retain signing-readiness evidence for archive_command",
            result["missing"],
        )
        self.assertIn(
            "artifacts.codesign_entitlements: must retain signing-readiness evidence for codesign_entitlements",
            result["missing"],
        )
        self.assertIn(
            "artifacts.provisioning_profile: must retain signing-readiness evidence for provisioning_profile",
            result["missing"],
        )


class IOSAppSigningReadinessCliTests(unittest.TestCase):
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
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            input_path = evidence_root / "ios-app-signing-readiness.json"
            output_path = evidence_root / "ios-app-signing-readiness-gate.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("--readiness", str(input_path), "--output", str(output_path))
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(persisted["verdict"], "pass")
        self.assertEqual(persisted["source"]["readiness"], str(input_path))

    def test_cli_preserves_relative_source_paths_for_committable_evidence(self) -> None:
        scratch_root = REPOSITORY_ROOT / ".build" / "ios-signing-readiness-test"
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch_root) as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            input_path = evidence_root / "ios-app-signing-readiness.json"
            output_path = evidence_root / "ios-app-signing-readiness-gate.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")
            relative_input = input_path.relative_to(REPOSITORY_ROOT)
            relative_output = output_path.relative_to(REPOSITORY_ROOT)

            result = self.run_cli(
                "--readiness",
                str(relative_input),
                "--output",
                str(relative_output),
            )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(persisted["source"]["readiness"], str(relative_input))
        self.assertEqual(persisted["source"]["evidence_root"], str(relative_input.parent))

    def test_cli_returns_blocked_for_open_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            evidence_root = Path(raw_directory)
            document = complete_document()
            write_artifacts(evidence_root, list(document["artifacts"]))
            document["status"] = "open"
            input_path = evidence_root / "ios-app-signing-readiness.json"
            input_path.write_text(json.dumps(document), encoding="utf-8")

            result = self.run_cli("--readiness", str(input_path))

        self.assertEqual(result.returncode, 1)
        self.assertIn("status: must be complete", result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "blocked")

    def test_cli_returns_error_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            input_path = Path(raw_directory) / "ios-app-signing-readiness.json"
            input_path.write_text("not-json", encoding="utf-8")

            result = self.run_cli("--readiness", str(input_path))

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
