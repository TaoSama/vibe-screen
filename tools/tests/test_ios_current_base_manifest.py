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
    GATE_OWNERS,
    SCOPE_PRS,
    SOURCE_DOCS,
    build_manifest,
    main,
)
from vibescreen_evidence.manifest import ManifestError


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "ios-current-base-manifest.schema.json"
CURRENT_BASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def make_videotoolbox_readiness_summary(
    runtime_class: str,
    artifact_paths: list[str] | None = None,
    **overrides: object,
) -> dict[str, object]:
    artifacts = artifact_paths or [
        f"{runtime_class}-videotoolbox-h264-hevc-frames-telemetry.json"
    ]
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "ios_hardware_videotoolbox_readiness",
        "profile": "ios-hardware-videotoolbox-readiness",
        "runtime_class": runtime_class,
        "verdict": "pass",
        "can_close_device_family_videotoolbox_gate": True,
        "can_close_phase5_hardware_videotoolbox_gate": False,
        "artifact_paths": artifacts,
        "artifact_checks": [
            {
                "path": artifact,
                "exists": True,
                "non_empty": True,
                "under_evidence_dir": True,
                "valid_ios_videotoolbox_source": True,
            }
            for artifact in artifacts
        ],
        "blocking_reasons": [],
    }
    summary.update(overrides)
    return summary


def make_native_input_summary(**overrides: object) -> dict[str, object]:
    summary: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "ios-native-input-run",
        "kind": "ios_native_input_behavior",
        "profile": "ios-native-input-behavior",
        "gate_owner": "phase5-ios-native-input-behavior",
        "owner": {
            "role": "ios_native_input_behavior_current_base_owner",
            "head_ref": "codex/ios-native-input-readiness-gate",
            "pull_request": "#257",
            "repository": "TaoSama/vibe-screen",
            "scope": "README Phase 5 iOS native-input behavior gate",
        },
        "current_base": {"commit": CURRENT_BASE_COMMIT, "dirty": False},
        "verdict": "pass",
        "can_close_ios_native_input_gate": True,
        "requires_real_ios_device": True,
        "requires_signed_app": True,
        "requires_physical_keyboard": True,
        "requires_hover_or_pointer_accessory": True,
        "android_evidence_is_not_ios_input_evidence": True,
        "simulator_is_not_ios_input_evidence": True,
        "offline_tests_are_readiness_only": True,
        "observations": {"signed_app_installed": True},
        "missing_requirements": [],
        "blocking_reasons": [],
        "disallowed_evidence": [],
        "artifact_paths": ["ios-native-input/iphone-ipad-host-logs.json"],
    }
    summary.update(overrides)
    return summary


def write_videotoolbox_readiness_summary(
    root: Path, runtime_class: str, **overrides: object
) -> Path:
    path = root / f"{runtime_class}-ios-videotoolbox-readiness.json"
    path.write_text(
        json.dumps(make_videotoolbox_readiness_summary(runtime_class, **overrides)),
        encoding="utf-8",
    )
    return path


def make_native_input_gate(**overrides: object) -> dict[str, object]:
    gate = make_native_input_summary(
        run_id="native-input-fixture",
        current_base={"commit": CURRENT_BASE_COMMIT, "dirty": False},
        observations={},
        artifact_paths=["logs/ios-native-input.log", "logs/host-native-input.log"],
        blocking_notes=[],
        notes=None,
    )
    gate.update(overrides)
    return gate


def write_native_input_gate(root: Path, **overrides: object) -> Path:
    path = root / "ios-native-input-gate.json"
    path.write_text(json.dumps(make_native_input_gate(**overrides)), encoding="utf-8")
    return path


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
        for name, gate in manifest["gates"].items():
            self.assertEqual(gate["owner_pr"], GATE_OWNERS[name])
        self.assertFalse(manifest["signing_readiness_gate"]["provided"])
        self.assertFalse(manifest["signing_readiness_gate"]["can_close_ios_app_signing_readiness"])
        self.assertFalse(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["verdict"], "blocked")
        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios-native-input-gate.json not provided",
            manifest["native_input_gate"]["missing_requirements"],
        )
        self.assertEqual(
            {gate["runtime_class"] for gate in manifest["videotoolbox_readiness_gates"]},
            {"physical_iphone", "physical_ipad"},
        )
        self.assertFalse(
            any(
                gate["can_close_device_family_videotoolbox_gate"]
                for gate in manifest["videotoolbox_readiness_gates"]
            )
        )
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

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_missing_ios_native_input_gate_path_fails_closed(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_gate = root / "missing-ios-native-input-gate.json"

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_gate)

        self.assertTrue(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["verdict"], "blocked")
        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertTrue(
            any(
                isinstance(reason, dict)
                and reason.get("field") == "native_input_gate"
                and "unreadable" in str(reason.get("requirement"))
                for reason in manifest["native_input_gate"]["blocking_reasons"]
            )
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_ios_native_input_gate_current_base_must_match_repository_head(self, state, environment):
        state.return_value = {"revision": "f" * 40, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_gate = write_native_input_gate(root)

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_gate)

        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios native-input gate current-base commit does not match repository HEAD",
            manifest["native_input_gate"]["missing_requirements"],
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_binds_ios_native_input_gate_file(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_input_gate = write_native_input_gate(root)

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        self.assertTrue(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["kind"], "ios_native_input_behavior")
        self.assertEqual(manifest["native_input_gate"]["verdict"], "pass")
        self.assertTrue(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertEqual(
            manifest["native_input_gate"]["owner"]["role"],
            "ios_native_input_behavior_current_base_owner",
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_incomplete_native_input_gate_fails_closed_and_stays_schema_compatible(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_input_gate = write_native_input_gate(root, owner=None, requires_signed_app=False)

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        self.assertTrue(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["verdict"], "blocked")
        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios native-input gate owner role is not the dedicated current-base owner",
            manifest["native_input_gate"]["missing_requirements"],
        )
        self.assertIn(
            "ios native-input gate requires_signed_app must be true",
            manifest["native_input_gate"]["missing_requirements"],
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_native_input_gate_missing_required_fields_fails_closed(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate = make_native_input_gate()
            for key in (
                "kind",
                "profile",
                "gate_owner",
                "requires_real_ios_device",
                "requires_signed_app",
                "requires_physical_keyboard",
                "requires_hover_or_pointer_accessory",
                "android_evidence_is_not_ios_input_evidence",
                "simulator_is_not_ios_input_evidence",
                "offline_tests_are_readiness_only",
            ):
                gate.pop(key)
            native_input_gate = root / "ios-native-input-gate.json"
            native_input_gate.write_text(json.dumps(gate), encoding="utf-8")

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        native_gate = manifest["native_input_gate"]
        self.assertTrue(native_gate["provided"])
        self.assertEqual(native_gate["verdict"], "blocked")
        self.assertFalse(native_gate["can_close_ios_native_input_gate"])
        self.assertIn("ios native-input gate kind is not ios_native_input_behavior", native_gate["missing_requirements"])
        self.assertIn("ios native-input gate profile is not ios-native-input-behavior", native_gate["missing_requirements"])
        self.assertIn("ios native-input gate requires_signed_app must be true", native_gate["missing_requirements"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_native_input_gate_blocking_reasons_prevent_close(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_input_gate = write_native_input_gate(root, blocking_reasons=["still missing physical-device trace"])

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        native_gate = manifest["native_input_gate"]
        self.assertEqual(native_gate["verdict"], "blocked")
        self.assertFalse(native_gate["can_close_ios_native_input_gate"])
        self.assertEqual(native_gate["blocking_reasons"], ["still missing physical-device trace"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_native_input_gate_requires_explicit_empty_lists(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate = make_native_input_gate()
            del gate["missing_requirements"]
            del gate["blocking_reasons"]
            del gate["disallowed_evidence"]
            native_input_gate = root / "ios-native-input-gate.json"
            native_input_gate.write_text(json.dumps(gate), encoding="utf-8")

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        native_gate = manifest["native_input_gate"]
        self.assertFalse(native_gate["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios native-input gate missing_requirements must be an explicit empty list",
            native_gate["blocking_reasons"],
        )
        self.assertIn(
            "ios native-input gate blocking_reasons must be an explicit empty list",
            native_gate["blocking_reasons"],
        )
        self.assertIn(
            "ios native-input gate disallowed_evidence must be an explicit empty list",
            native_gate["blocking_reasons"],
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
    def test_native_input_gate_preserves_profile_and_clear_blocking_reasons(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_input_gate = write_native_input_gate(root)

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        self.assertTrue(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["kind"], "ios_native_input_behavior")
        self.assertEqual(manifest["native_input_gate"]["profile"], "ios-native-input-behavior")
        self.assertEqual(
            manifest["native_input_gate"]["owner"]["role"],
            "ios_native_input_behavior_current_base_owner",
        )
        self.assertTrue(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertEqual(manifest["native_input_gate"]["blocking_reasons"], [])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_ios_native_input_gate_commit_must_match_repository_head(self, state, environment):
        state.return_value = {"revision": "f" * 40, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_input_gate = write_native_input_gate(root)

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_input_gate)

        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios native-input gate current-base commit does not match repository HEAD",
            manifest["native_input_gate"]["missing_requirements"],
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_binds_videotoolbox_readiness_gate_for_both_families(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            iphone_gate = write_videotoolbox_readiness_summary(root, "physical_iphone")
            ipad_gate = write_videotoolbox_readiness_summary(root, "physical_ipad")

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[iphone_gate, ipad_gate],
            )

        gates = manifest["videotoolbox_readiness_gates"]
        self.assertEqual({gate["runtime_class"] for gate in gates}, {"physical_iphone", "physical_ipad"})
        self.assertTrue(all(gate["can_close_device_family_videotoolbox_gate"] for gate in gates))
        self.assertTrue(all(gate["blocking_reasons"] == [] for gate in gates))

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_binds_ios_native_input_gate_summary(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_gate = root / "ios-native-input-gate.json"
            native_gate.write_text(json.dumps(make_native_input_summary()), encoding="utf-8")

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_gate)

        self.assertTrue(manifest["native_input_gate"]["provided"])
        self.assertEqual(manifest["native_input_gate"]["kind"], "ios_native_input_behavior")
        self.assertEqual(manifest["native_input_gate"]["verdict"], "pass")
        self.assertTrue(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertEqual(
            manifest["native_input_gate"]["owner"]["role"],
            "ios_native_input_behavior_current_base_owner",
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_incomplete_ios_native_input_gate_fails_closed(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            native_gate = root / "ios-native-input-gate.json"
            native_gate.write_text(
                json.dumps(make_native_input_summary(verdict="blocked", artifact_paths=[])),
                encoding="utf-8",
            )

            manifest = build_manifest(command=[], repo=root, native_input_gate=native_gate)

        self.assertFalse(manifest["native_input_gate"]["can_close_ios_native_input_gate"])
        self.assertIn(
            "ios native-input gate verdict does not close the native-input gate",
            manifest["native_input_gate"]["missing_requirements"],
        )
        self.assertIn(
            "ios native-input gate must retain sanitized iOS/Host artifacts",
            manifest["native_input_gate"]["missing_requirements"],
        )
        self.assertIsInstance(manifest["native_input_gate"]["can_close_ios_native_input_gate"], bool)

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_missing_videotoolbox_family_falls_back_to_blocked_default(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            iphone_gate = write_videotoolbox_readiness_summary(root, "physical_iphone")

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[iphone_gate],
            )

        by_runtime = {gate["runtime_class"]: gate for gate in manifest["videotoolbox_readiness_gates"]}
        self.assertTrue(by_runtime["physical_iphone"]["can_close_device_family_videotoolbox_gate"])
        self.assertFalse(by_runtime["physical_ipad"]["can_close_device_family_videotoolbox_gate"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_invalid_videotoolbox_readiness_gate_fails_closed(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate_path = write_videotoolbox_readiness_summary(root, "physical_iphone", verdict="blocked")

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[gate_path],
            )

        iphone_gate = next(
            gate for gate in manifest["videotoolbox_readiness_gates"] if gate["runtime_class"] == "physical_iphone"
        )
        self.assertFalse(iphone_gate["can_close_device_family_videotoolbox_gate"])
        self.assertTrue(iphone_gate["blocking_reasons"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_videotoolbox_readiness_rejects_schema_version_mismatch(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate_path = write_videotoolbox_readiness_summary(
                root,
                "physical_iphone",
                schema_version="vibescreen.evidence/v0",
            )

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[gate_path],
            )

        iphone_gate = next(
            gate for gate in manifest["videotoolbox_readiness_gates"] if gate["runtime_class"] == "physical_iphone"
        )
        self.assertFalse(iphone_gate["can_close_device_family_videotoolbox_gate"])
        self.assertIn(
            "schema_version must be vibescreen.evidence/v1",
            {reason["requirement"] for reason in iphone_gate["blocking_reasons"]},
        )

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_invalid_videotoolbox_artifact_paths_stay_schema_compatible(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate_path = write_videotoolbox_readiness_summary(
                root,
                "physical_iphone",
                artifact_paths=[123],
            )

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[gate_path],
            )

        iphone_gate = next(
            gate for gate in manifest["videotoolbox_readiness_gates"] if gate["runtime_class"] == "physical_iphone"
        )
        self.assertFalse(iphone_gate["can_close_device_family_videotoolbox_gate"])
        self.assertEqual(iphone_gate["artifact_paths"], [])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_videotoolbox_readiness_rejects_phase5_close_claim(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate_path = write_videotoolbox_readiness_summary(
                root,
                "physical_iphone",
                can_close_phase5_hardware_videotoolbox_gate=True,
            )

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[gate_path],
            )

        iphone_gate = next(
            gate for gate in manifest["videotoolbox_readiness_gates"] if gate["runtime_class"] == "physical_iphone"
        )
        self.assertFalse(iphone_gate["can_close_device_family_videotoolbox_gate"])
        self.assertIn("must remain false", iphone_gate["blocking_reasons"][0]["requirement"])

    @patch("vibescreen_evidence.ios_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.ios_current_base_manifest.repository_state")
    def test_videotoolbox_readiness_requires_physical_runtime_class(self, state, environment):
        state.return_value = {"revision": CURRENT_BASE_COMMIT, "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            gate_path = root / "simulator-ios-videotoolbox-readiness.json"
            gate_path.write_text(
                json.dumps(make_videotoolbox_readiness_summary("simulator")),
                encoding="utf-8",
            )

            manifest = build_manifest(
                command=[],
                repo=root,
                videotoolbox_readiness_gates=[gate_path],
            )

        self.assertFalse(
            any(
                gate["can_close_device_family_videotoolbox_gate"]
                for gate in manifest["videotoolbox_readiness_gates"]
            )
        )

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

            native_gate = write_native_input_gate(root)

            exit_code = main([
                "--repo",
                str(root),
                "--output",
                str(output),
                "--native-input-gate",
                str(native_gate),
                "--",
                "make",
                "ios-current-base-gate",
            ])
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["command"], ["make", "ios-current-base-gate"])
        self.assertEqual(manifest["source_root"], ".")
        self.assertEqual(manifest["native_input_gate"]["path"], str(native_gate))


if __name__ == "__main__":
    unittest.main()
