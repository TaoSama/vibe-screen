from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.ios_current_base_manifest import (
    BROADER_GATES,
    FORMAL_DEVICE_GATES,
    SCOPE_PRS,
    SOURCE_DOCS,
    build_manifest,
    main,
)
from vibescreen_evidence.manifest import ManifestError


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-current-base-manifest.schema.json"
CURRENT_BASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


class IOSCurrentBaseManifestTests(unittest.TestCase):
    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_builds_current_base_manifest_with_fail_closed_defaults(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"xcode_select": {"status": "blocked"}}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)

            manifest = build_manifest(command=["make", "ios-current-base-gate"], repo=root)

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], "ios_current_base_readiness_manifest")
        self.assertEqual(manifest["source_root"], str(root.resolve()))
        self.assertEqual(manifest["owner"]["aggregate_pr"], "#290")
        self.assertEqual(manifest["owner"]["device_acceptance_pr"], "#290")
        self.assertEqual(manifest["scope_prs"], SCOPE_PRS)
        self.assertEqual(set(manifest["source_docs"]), set(SOURCE_DOCS))
        self.assertEqual(set(manifest["gates"]), set(FORMAL_DEVICE_GATES) | set(BROADER_GATES))
        self.assertFalse(manifest["signing_readiness_gate"]["provided"])
        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertEqual(manifest["signing"]["status"], "blocked")
        self.assertFalse(manifest["android_evidence_used_for_ios_gates"])
        self.assertTrue(any("does not claim" in item for item in manifest["limitations"]))
        self.assertTrue(any("Team ID" in item for item in manifest["limitations"]))

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_binds_ios_app_signing_readiness_gate_summary(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            signing_gate = root / "ios-app-signing-readiness-gate.json"
            signing_gate.write_text(
                json.dumps(
                    {
                        "owner": {
                            "role": "ios_app_signing_readiness_current_base_owner",
                            "head_ref": "codex/phase5-ios-signing-readiness",
                            "repository": "TaoSama/vibe-screen",
                            "scope": "Phase 5 iOS app-signing readiness prerequisite only",
                        },
                        "current_base": {
                            "commit": CURRENT_BASE_COMMIT,
                            "branch": "codex/phase5-ios-signing-readiness",
                            "dirty": False,
                        },
                        "kind": "ios_app_signing_readiness_gate",
                        "verdict": "pass",
                        "can_close_ios_app_signing_readiness": True,
                        "signing_summary": {
                            "status": "pass",
                            "bundle_id": "dev.example.vibescreen.acceptance",
                            "unique_bundle_id": True,
                            "team_id_recorded": True,
                            "codesign_identity_recorded": True,
                            "provisioning_profile_recorded": True,
                            "device_udid_hashes_recorded": True,
                            "entitlements_recorded": True,
                            "signed_artifact_sha256": "a" * 64,
                        },
                        "missing": [],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_manifest(command=[], repo=root, signing_readiness_gate=signing_gate)

        self.assertTrue(manifest["signing_readiness_gate"]["provided"])
        self.assertEqual(manifest["signing_readiness_gate"]["kind"], "ios_app_signing_readiness_gate")
        self.assertEqual(manifest["signing_readiness_gate"]["verdict"], "pass")
        self.assertTrue(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertEqual(
            manifest["signing_readiness_gate"]["owner"]["role"],
            "ios_app_signing_readiness_current_base_owner",
        )
        self.assertEqual(
            manifest["signing"],
            {
                "status": "pass",
                "bundle_id": "dev.example.vibescreen.acceptance",
                "unique_bundle_id": True,
                "team_id_redacted": True,
                "certificate_identity_recorded": True,
                "provisioning_profile_recorded": True,
                "device_udid_hashes_recorded": True,
                "entitlements_recorded": True,
                "signed_archive_sha256": "a" * 64,
            },
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_missing_signing_readiness_gate_path_fails_closed(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            signing_gate = root / "missing-ios-app-signing-readiness-gate.json"

            manifest = build_manifest(command=[], repo=root, signing_readiness_gate=signing_gate)

        self.assertTrue(manifest["signing_readiness_gate"]["provided"])
        self.assertEqual(manifest["signing_readiness_gate"]["verdict"], "blocked")
        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertIn("unreadable", manifest["signing_readiness_gate"]["missing"][0])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_incomplete_signing_readiness_summary_fails_closed(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            signing_gate = root / "ios-app-signing-readiness-gate.json"
            signing_gate.write_text(
                json.dumps(
                    {
                        "owner": {
                            "role": "ios_app_signing_readiness_current_base_owner",
                            "head_ref": "codex/phase5-ios-signing-readiness",
                            "repository": "TaoSama/vibe-screen",
                            "scope": "Phase 5 iOS app-signing readiness prerequisite only",
                        },
                        "current_base": {
                            "commit": CURRENT_BASE_COMMIT,
                            "branch": "codex/phase5-ios-signing-readiness",
                            "dirty": False,
                        },
                        "kind": "ios_app_signing_readiness_gate",
                        "verdict": "pass",
                        "can_close_ios_app_signing_readiness": True,
                        "signing_summary": {
                            "status": "pass",
                            "bundle_id": "",
                            "unique_bundle_id": True,
                            "team_id_recorded": True,
                            "codesign_identity_recorded": True,
                            "provisioning_profile_recorded": True,
                            "device_udid_hashes_recorded": True,
                            "entitlements_recorded": True,
                            "signed_artifact_sha256": "a" * 64,
                        },
                        "missing": [],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_manifest(command=[], repo=root, signing_readiness_gate=signing_gate)

        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertIn(
            "ios app-signing readiness gate signing_summary is incomplete",
            manifest["signing_readiness_gate"]["missing"],
        )
        self.assertEqual(manifest["signing"]["status"], "blocked")
        self.assertIsNone(manifest["signing"]["bundle_id"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_signing_readiness_commit_must_match_repository_head(self, state, environment):
        state.return_value = {"revision": "f" * 40, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            signing_gate = root / "ios-app-signing-readiness-gate.json"
            signing_gate.write_text(
                json.dumps(
                    {
                        "owner": {
                            "role": "ios_app_signing_readiness_current_base_owner",
                            "head_ref": "codex/phase5-ios-signing-readiness",
                            "repository": "TaoSama/vibe-screen",
                            "scope": "Phase 5 iOS app-signing readiness prerequisite only",
                        },
                        "current_base": {
                            "commit": CURRENT_BASE_COMMIT,
                            "branch": "codex/phase5-ios-signing-readiness",
                            "dirty": False,
                        },
                        "kind": "ios_app_signing_readiness_gate",
                        "verdict": "pass",
                        "can_close_ios_app_signing_readiness": True,
                        "signing_summary": {
                            "status": "pass",
                            "bundle_id": "dev.example.vibescreen.acceptance",
                            "unique_bundle_id": True,
                            "team_id_recorded": True,
                            "codesign_identity_recorded": True,
                            "provisioning_profile_recorded": True,
                            "device_udid_hashes_recorded": True,
                            "entitlements_recorded": True,
                            "signed_artifact_sha256": "a" * 64,
                        },
                        "missing": [],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_manifest(command=[], repo=root, signing_readiness_gate=signing_gate)

        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertIn(
            "ios app-signing readiness gate current-base commit does not match repository HEAD",
            manifest["signing_readiness_gate"]["missing"],
        )
        self.assertEqual(manifest["signing"]["status"], "blocked")

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_non_dedicated_signing_readiness_gate_fails_closed(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            signing_gate = root / "ios-app-signing-readiness-gate.json"
            signing_gate.write_text(
                json.dumps(
                    {
                        "kind": "ios_app_signing_readiness_gate",
                        "verdict": "pass",
                        "can_close_ios_app_signing_readiness": True,
                        "missing": [],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_manifest(command=[], repo=root, signing_readiness_gate=signing_gate)

        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertIn(
            "ios app-signing readiness gate owner role is not the dedicated current-base owner",
            manifest["signing_readiness_gate"]["missing"],
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_current_base_scope_includes_related_ios_owner_prs(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)

            manifest = build_manifest(command=[], repo=root)

        self.assertGreaterEqual(
            set(manifest["scope_prs"]),
            {
                "#182",
                "#196",
                "#207",
                "#208",
                "#209",
                "#238",
                "#251",
                "#253",
                "#257",
                "#279",
                "#282",
            },
        )
        self.assertIn("docs/runbook/hdr-color-acceptance.md", manifest["source_docs"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_manifest_matches_schema_required_top_level_fields(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            manifest = build_manifest(command=[], repo=root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(manifest), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, manifest)

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_rejects_missing_source_docs(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            with self.assertRaisesRegex(ManifestError, "missing source document"):
                build_manifest(command=[], repo=Path(directory_name))

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_rejects_non_owner_device_acceptance_pr(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            with self.assertRaisesRegex(ManifestError, "must remain #290"):
                build_manifest(
                    command=[],
                    repo=root,
                    device_acceptance_owner_pr="#999",
                )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_cli_writes_manifest(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            output = root / "ios-current-base-manifest.json"

            exit_code = main(["--repo", str(root), "--output", str(output), "--", "make", "ios-current-base-gate"])
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["command"], ["make", "ios-current-base-gate"])


if __name__ == "__main__":
    unittest.main()
