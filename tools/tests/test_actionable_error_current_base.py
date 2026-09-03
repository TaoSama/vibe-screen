from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.actionable_error_current_base import (
    EXPECTED_DEVICE,
    MANIFEST_KIND,
    REQUIRED_STATE_IDS,
    evaluate,
    load_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "docs"
    / "changes"
    / "2026-08-23-actionable-error-states"
    / "evidence"
    / "2026-08-24-p0110-current-base-owner"
)
MANIFEST_PATH = EVIDENCE_DIR / "actionable-error-current-base.json"
MODULE = "vibescreen_evidence.actionable_error_current_base"
MANIFEST_SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "actionable-error-current-base.schema.json"
GATE_SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "actionable-error-current-base-gate.schema.json"


class ActionableErrorCurrentBaseGateTests(unittest.TestCase):
    def load_real_manifest(self) -> dict[str, object]:
        return load_manifest(MANIFEST_PATH)

    def assert_schema_node(self, value: object, node: dict, root: dict, path: str = "$") -> None:
        if "const" in node:
            self.assertEqual(value, node["const"], path)
        if "enum" in node:
            self.assertIn(value, node["enum"], path)
        if "$ref" in node:
            reference = node["$ref"]
            self.assertTrue(reference.startswith("#/$defs/"), path)
            self.assert_schema_node(value, root["$defs"][reference.removeprefix("#/$defs/")], root, path)
            return
        expected_type = node.get("type")
        if expected_type == "object":
            self.assertIsInstance(value, dict, path)
            keys = set(value)
            required = set(node.get("required", []))
            self.assertEqual(required - keys, set(), path)
            if node.get("additionalProperties") is False:
                self.assertEqual(keys - set(node.get("properties", {})), set(), path)
            for key, child in node.get("properties", {}).items():
                if key in value:
                    self.assert_schema_node(value[key], child, root, f"{path}.{key}")
        elif expected_type == "array":
            self.assertIsInstance(value, list, path)
            for index, item in enumerate(value):
                self.assert_schema_node(item, node["items"], root, f"{path}[{index}]")
        elif expected_type == "string":
            self.assertIsInstance(value, str, path)
        elif expected_type == "integer":
            self.assertIsInstance(value, int, path)
            self.assertNotIsInstance(value, bool, path)
        elif expected_type == "boolean":
            self.assertIsInstance(value, bool, path)
        elif expected_type == "null":
            self.assertIsNone(value, path)

    def test_real_current_base_record_is_blocked_and_cannot_close_gate(self) -> None:
        report = evaluate(self.load_real_manifest(), repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_phase1_actionable_errors_gate"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(set(report["required_state_ids"]), set(REQUIRED_STATE_IDS))
        self.assertIn("host_screen_recording_denied", report["blocked_state_ids"])
        self.assertIn("tcp_54321_unavailable", report["blocked_state_ids"])
        self.assertTrue(
            {
                "android-internet-webrtc-disconnected",
                "android-codec-negotiation-failed",
                "android-managed-policy-deny",
                "android-unsupported-peripheral-kind",
                "android-file-transfer-policy-deny",
                "android-clipboard-policy-deny",
            }.issubset(set(report["blocked_state_ids"])),
        )

    def test_real_current_base_report_matches_schema(self) -> None:
        report = evaluate(self.load_real_manifest(), repository_root=REPOSITORY_ROOT)
        schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assert_schema_node(report, schema, schema)

    def test_real_manifest_matches_published_schema(self) -> None:
        manifest = self.load_real_manifest()
        schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assert_schema_node(manifest, schema, schema)

    def test_real_manifest_excludes_raw_or_misleading_artifacts(self) -> None:
        manifest = self.load_real_manifest()
        states = manifest["states"]
        assert isinstance(states, list)
        paths = {
            artifact["path"]
            for state in states
            if isinstance(state, dict)
            for artifact in state.get("artifacts", [])
            if isinstance(artifact, dict)
        }

        self.assertNotIn(
            "docs/changes/2026-08-23-actionable-error-states/evidence/2026-08-24-p0110-current-base-owner/lan-route-blocked-readonly.txt",
            paths,
        )
        self.assertNotIn(
            "docs/changes/2026-08-23-actionable-error-states/evidence/2026-08-24-p0110-current-base-owner/usb-host-not-listening.png",
            paths,
        )

    def test_rejects_missing_required_state(self) -> None:
        manifest = self.load_real_manifest()
        states = manifest["states"]
        assert isinstance(states, list)
        manifest["states"] = [state for state in states if state["id"] != "usb_disconnected"]

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("states: missing required state usb_disconnected", report["errors"])

    def test_missing_new_current_base_ui_state_is_blocked_not_malformed(self) -> None:
        report = evaluate(self.load_real_manifest(), repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "blocked")
        self.assertEqual(report["errors"], [])
        self.assertIn("android-clipboard-policy-deny", report["blocked_state_ids"])

    def test_rejects_relabeling_p0110_as_xiaomi(self) -> None:
        manifest = self.load_real_manifest()
        device = manifest["device"]
        assert isinstance(device, dict)
        device["manufacturer"] = "OtherVendor"
        device["model"] = "2211133C"
        device["codename"] = "othercodename"

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("device.manufacturer: expected nubia, got OtherVendor", report["errors"])

    def test_real_current_base_report_redacts_adb_serial(self) -> None:
        report = evaluate(self.load_real_manifest(), repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["device_identity"]["adb_serial"], "<redacted-adb-serial>")
        self.assertNotIn("EPTESTSERIAL000000", json.dumps(report, sort_keys=True))

    def test_rejects_public_manifest_with_raw_adb_serial(self) -> None:
        manifest = self.load_real_manifest()
        device = manifest["device"]
        assert isinstance(device, dict)
        device["adb_serial"] = "EPTESTSERIAL000000"

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("device.adb_serial: public current-base evidence must redact", "\n".join(report["errors"]))

    def test_rejects_sensitive_public_artifact_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            artifact = root / "artifact.txt"
            artifact.write_text("visible serial EPTESTSERIAL000000\n", encoding="utf-8")
            import hashlib

            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = self.load_real_manifest()
            states = manifest["states"]
            assert isinstance(states, list)
            sensitive_artifact = {
                "path": "artifact.txt",
                "sha256": digest,
                "kind": "operator_note",
                "description": "synthetic sensitive artifact",
            }
            for state in states:
                assert isinstance(state, dict)
                state["artifacts"] = [dict(sensitive_artifact)]

            report = evaluate(manifest, repository_root=root)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("public artifact contains raw ADB serial", "\n".join(report["errors"]))

    def test_runtime_rejects_schema_required_top_level_gaps(self) -> None:
        manifest = self.load_real_manifest()
        repository = manifest["repository"]
        assert isinstance(repository, dict)
        del manifest["notes"]
        repository.pop("branch")
        repository.pop("baseline")
        repository.pop("notes")

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("notes: must contain at least one note", report["errors"])
        self.assertIn("repository.branch: must be a non-empty string", report["errors"])
        self.assertIn("repository.baseline: must be a non-empty string", report["errors"])
        self.assertIn("repository.notes: must contain at least one note", report["errors"])

    def test_runtime_rejects_schema_forbidden_extra_fields(self) -> None:
        manifest = self.load_real_manifest()
        repository = manifest["repository"]
        device = manifest["device"]
        states = manifest["states"]
        assert isinstance(repository, dict)
        assert isinstance(device, dict)
        assert isinstance(states, list)
        first_state = states[0]
        assert isinstance(first_state, dict)
        artifacts = first_state["artifacts"]
        assert isinstance(artifacts, list)
        first_artifact = artifacts[0]
        assert isinstance(first_artifact, dict)

        manifest["unexpected_top_level"] = True
        repository["unexpected_repository_field"] = True
        device["unexpected_device_field"] = True
        first_state["unexpected_state_field"] = True
        first_artifact["unexpected_artifact_field"] = True

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("manifest.unexpected_top_level: unexpected field", report["errors"])
        self.assertIn("repository.unexpected_repository_field: unexpected field", report["errors"])
        self.assertIn("device.unexpected_device_field: unexpected field", report["errors"])
        self.assertIn("states[0].unexpected_state_field: unexpected field", report["errors"])
        self.assertIn("states[0].artifacts[0].unexpected_artifact_field: unexpected field", report["errors"])

    def test_non_pass_state_cannot_close(self) -> None:
        manifest = self.load_real_manifest()
        states = manifest["states"]
        assert isinstance(states, list)
        states[0]["can_close_state"] = True

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("states[0].can_close_state: non-pass state cannot close", report["errors"])

    def test_rejects_bad_artifact_hash(self) -> None:
        manifest = self.load_real_manifest()
        states = manifest["states"]
        assert isinstance(states, list)
        artifacts = states[2]["artifacts"]
        assert isinstance(artifacts, list)
        artifacts[0]["sha256"] = "0" * 64

        report = evaluate(manifest, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("sha256: mismatch", "\n".join(report["errors"]))

    def test_complete_synthetic_manifest_can_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            artifact = root / "artifact.txt"
            artifact.write_text("device evidence\n", encoding="utf-8")
            import hashlib

            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "kind": MANIFEST_KIND,
                "run_id": "synthetic-pass",
                "created_at": "2026-08-24T00:00:00Z",
                "evidence_boundary": "synthetic unit-test fixture",
                "can_close_readme_phase1_actionable_errors_gate": True,
                "repository": {
                    "name": "TaoSama/vibe-screen",
                    "branch": "codex/unit-test",
                    "collected_at_commit": "a" * 40,
                    "evaluated_at_commit": "a" * 40,
                    "baseline": "origin/main",
                    "notes": ["synthetic repository fixture"],
                },
                "device": dict(EXPECTED_DEVICE),
                "states": [
                    {
                        "id": state_id,
                        "status": "pass",
                        "classification": "real_device_retained",
                        "owner": "unit-test",
                        "observed_on_device": True,
                        "can_close_state": True,
                        "closure_requirements": ["retained artifact"],
                        "blockers": [],
                        "notes": ["synthetic pass fixture"],
                        "artifacts": [
                            {
                                "path": "artifact.txt",
                                "sha256": digest,
                                "kind": "operator_note",
                                "description": "synthetic retained artifact",
                            }
                        ],
                        }
                    for state_id in REQUIRED_STATE_IDS
                ],
                "notes": ["synthetic pass fixture"],
            }

            report = evaluate(manifest, repository_root=root)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_readme_phase1_actionable_errors_gate"])

    def test_all_states_pass_without_top_level_close_claim_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            artifact = root / "artifact.txt"
            artifact.write_text("device evidence\n", encoding="utf-8")
            import hashlib

            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "kind": MANIFEST_KIND,
                "run_id": "synthetic-no-close",
                "created_at": "2026-08-24T00:00:00Z",
                "evidence_boundary": "synthetic unit-test fixture",
                "can_close_readme_phase1_actionable_errors_gate": False,
                "repository": {
                    "name": "TaoSama/vibe-screen",
                    "branch": "codex/unit-test",
                    "collected_at_commit": "a" * 40,
                    "evaluated_at_commit": "a" * 40,
                    "baseline": "origin/main",
                    "notes": ["synthetic repository fixture"],
                },
                "device": dict(EXPECTED_DEVICE),
                "states": [
                    {
                        "id": state_id,
                        "status": "pass",
                        "classification": "real_device_retained",
                        "owner": "unit-test",
                        "observed_on_device": True,
                        "can_close_state": True,
                        "closure_requirements": ["retained artifact"],
                        "blockers": [],
                        "notes": ["synthetic pass fixture"],
                        "artifacts": [
                            {
                                "path": "artifact.txt",
                                "sha256": digest,
                                "kind": "operator_note",
                                "description": "synthetic retained artifact",
                            }
                        ],
                        }
                    for state_id in REQUIRED_STATE_IDS
                ],
                "notes": ["synthetic pass fixture"],
            }

            report = evaluate(manifest, repository_root=root)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["can_close_readme_phase1_actionable_errors_gate"])
        self.assertIn("readme_gate_closure_claim", report["insufficient_state_ids"])

    def test_cli_allow_blocked_exits_zero_for_real_blocked_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output_path = Path(directory_name) / "gate.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(MANIFEST_PATH),
                    "--repository-root",
                    str(REPOSITORY_ROOT),
                    "--output",
                    str(output_path),
                    "--allow-blocked",
                ],
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(report["verdict"], "blocked")
        self.assertEqual(report["source"]["manifest"], str(MANIFEST_PATH))

    def test_cli_without_allow_blocked_exits_nonzero_for_real_blocked_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output_path = Path(directory_name) / "gate.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(MANIFEST_PATH),
                    "--repository-root",
                    str(REPOSITORY_ROOT),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
            )

        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
