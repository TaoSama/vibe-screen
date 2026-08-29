from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.host_display_rotation_current_base_manifest import (
    FORMAL_GATES,
    HOST_PREFLIGHT_CHECKS,
    REDACTED_ADB_SERIAL,
    REDACTED_SOURCE_ROOT,
    SCOPE_PRS,
    SOURCE_DOCS,
    SUPPORTING_GATES,
    build_manifest,
    collect_environment,
    main,
)
from vibescreen_evidence.manifest import ManifestError


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "host-display-rotation-current-base-manifest.schema.json"
TEST_ADB_SERIAL = "TEST_ADB_SERIAL_001"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture" + chr(10), encoding="utf-8")


def blocked_device() -> dict[str, object]:
    return {
        "status": "blocked",
        "runtime_class": "missing",
        "manufacturer": None,
        "model": None,
        "codename": None,
        "android_release": None,
        "sdk": None,
        "adb_serial": None,
        "package_status": "not_checked",
        "evidence": [],
        "probes": {},
    }


class HostDisplayRotationCurrentBaseManifestTests(unittest.TestCase):
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_builds_manifest_with_fail_closed_defaults(self, state, environment, device):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = {
            "status": "pass",
            "runtime_class": "physical_android_device",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
            "adb_serial": TEST_ADB_SERIAL,
            "package_status": "not_installed",
            "evidence": ["device-identity.txt"],
            "probes": {},
        }
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)

            manifest = build_manifest(
                command=["make", "host-display-rotation-current-base-gate"],
                repo=root,
                adb_serial=TEST_ADB_SERIAL,
            )

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], "host_display_rotation_current_base_manifest")
        self.assertEqual(manifest["owner"]["aggregate_pr"], "#262")
        self.assertEqual(manifest["scope_prs"], SCOPE_PRS)
        self.assertEqual(set(manifest["source_docs"]), set(SOURCE_DOCS))
        self.assertEqual(set(manifest["host_preflight"]), set(HOST_PREFLIGHT_CHECKS))
        self.assertEqual(set(manifest["gates"]), set(SUPPORTING_GATES) | set(FORMAL_GATES))
        self.assertFalse(manifest["client_local_matrix_used_for_host_rotation"])
        self.assertEqual(manifest["gates"]["physical_host_display_rotation"]["status"], "blocked")
        self.assertEqual(manifest["source_root"], REDACTED_SOURCE_ROOT)
        self.assertEqual(manifest["device"]["adb_serial"], REDACTED_ADB_SERIAL)
        self.assertNotIn(TEST_ADB_SERIAL, json.dumps(manifest))
        self.assertNotIn(str(root), json.dumps(manifest))

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_manifest_matches_schema_required_top_level_fields(self, state, environment, device):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = blocked_device()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            manifest = build_manifest(command=[], repo=root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(manifest), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, manifest)

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_rejects_missing_source_docs(self, state, environment):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        with tempfile.TemporaryDirectory() as directory_name:
            with self.assertRaisesRegex(ManifestError, "missing source document"):
                build_manifest(command=[], repo=Path(directory_name))

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_rejects_non_owner_pr(self, state, environment, device):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {}
        device.return_value = blocked_device()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            with self.assertRaisesRegex(ManifestError, "must remain #262"):
                build_manifest(command=[], repo=root, aggregate_owner_pr="#999")

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_cli_writes_manifest(self, state, environment, device):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = blocked_device()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            output = root / "host-display-rotation-current-base-manifest.json"

            exit_code = main([
                "--repo",
                str(root),
                "--output",
                str(output),
                "--",
                "make",
                "host-display-rotation-current-base-gate",
            ])
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["command"], ["make", "host-display-rotation-current-base-gate"])

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_cli_resolves_relative_output_for_host_preflight_report(
        self, state, environment, device
    ):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = blocked_device()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "repo"
            root.mkdir()
            make_docs(root)
            caller = Path(directory_name) / "caller"
            caller.mkdir()
            previous_cwd = Path.cwd()
            try:
                os.chdir(caller)
                exit_code = main([
                    "--repo",
                    str(root),
                    "--output",
                    "evidence/manifest.json",
                    "--",
                    "make",
                    "host-display-rotation-current-base-gate",
                ])
            finally:
                os.chdir(previous_cwd)

            expected_output = (caller / "evidence" / "manifest.json").resolve()
            manifest = json.loads(expected_output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        environment.assert_called_once_with(root.resolve(), expected_output.parent / "host-preflight.txt")
        self.assertEqual(manifest["command"], ["make", "host-display-rotation-current-base-gate"])
        state.assert_called_once_with(root.resolve(), ignore_paths=[expected_output.parent])

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_cli_ignores_only_current_evidence_output_for_repository_state(
        self, state, environment, device
    ):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {"codesigning_identities": {"target_identity_available": False}}
        device.return_value = blocked_device()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "repo"
            root.mkdir()
            make_docs(root)
            output = root / "docs" / "changes" / "run" / "host-display-rotation-current-base-manifest.json"

            exit_code = main([
                "--repo",
                str(root),
                "--output",
                str(output),
            ])

        self.assertEqual(exit_code, 0)
        state.assert_called_once_with(root.resolve(), ignore_paths=[output.resolve().parent])

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest._host_preflight_probe")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest._run_probe")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest._installed_host_codesign_probe")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest._signing_probe")
    def test_collect_environment_writes_host_preflight_report_inside_evidence(
        self, signing, installed_codesign, run_probe, host_preflight
    ):
        signing.return_value = {"status": "blocked"}
        installed_codesign.return_value = {"status": "blocked"}
        run_probe.return_value = {"status": "blocked"}
        host_preflight.return_value = {"status": "blocked"}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            report = root / "evidence" / "host-preflight.txt"

            collect_environment(root, report)

        host_preflight.assert_called_once_with(root, report)

    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_device")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.collect_environment")
    @patch("vibescreen_evidence.host_display_rotation_current_base_manifest.repository_state")
    def test_redacts_public_manifest_values(self, state, environment, device):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        environment.return_value = {
            "host_preflight": {
                "command": ["[redacted-path]/python3", "scripts/macos_dev_host.py"],
                "summary": [
                    "Error: unable to open database \"/home/alice/private-permissions.db\"",
                ],
            },
        }
        device.return_value = {
            "status": "pass",
            "runtime_class": "physical_android_device",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
            "adb_serial": TEST_ADB_SERIAL,
            "package_status": "installed",
            "evidence": ["device-identity.txt"],
            "probes": {
                "adb_get_state": {
                    "command": ["adb", "-s", TEST_ADB_SERIAL, "get-state"],
                    "summary": [TEST_ADB_SERIAL],
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            manifest = build_manifest(
                command=["make", f"EVIDENCE_SERIAL={TEST_ADB_SERIAL}"],
                repo=root,
                adb_serial=TEST_ADB_SERIAL,
            )

        serialized = json.dumps(manifest)
        self.assertNotIn(TEST_ADB_SERIAL, serialized)
        self.assertNotIn("/home/alice", serialized)
        self.assertNotIn("private-permissions.db", serialized)
        self.assertIn(REDACTED_ADB_SERIAL, serialized)
        self.assertIn("unable to open redacted database", serialized)


if __name__ == "__main__":
    unittest.main()
