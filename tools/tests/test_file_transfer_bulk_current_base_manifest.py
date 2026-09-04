from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.manifest import ManifestError
from vibescreen_evidence.file_transfer_bulk_current_base_manifest import (
    ANDROID_CHILD_ID,
    SOURCE_DOCS,
    WEBRTC_CHILD_ID,
    build_manifest,
    main,
)


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "file-transfer-bulk-current-base-manifest.schema.json"


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


def child_gate(kind: str, flag: str, *, verdict: str = "pass") -> dict[str, object]:
    return {
        "kind": kind,
        "verdict": verdict,
        "gate_closed": verdict == "pass",
        flag: verdict == "pass",
        "blockers": [] if verdict == "pass" else ["still blocked"],
        "not_proven": [] if verdict == "pass" else ["product evidence"],
    }


class FileTransferBulkCurrentBaseManifestTests(unittest.TestCase):
    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_builds_fail_closed_manifest_without_external_collectors(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)

            manifest = build_manifest(command=["make", "file-transfer-bulk-current-base-gate"], repo=root)

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], "file_transfer_bulk_current_base_readiness_manifest")
        self.assertEqual(manifest["owner"]["aggregate"], "current-base-file-transfer-bulk")
        self.assertEqual(manifest["owner"]["readiness_baseline_pr"], "#265")
        self.assertEqual(manifest["source_docs"]["missing"], [])
        self.assertFalse(manifest["evidence_boundary"]["aggregate_runs_external_collectors"])
        self.assertFalse(manifest["evidence_boundary"]["p0110_can_close_webrtc_bulk_public_internet"])
        self.assertFalse(manifest["child_gates"][ANDROID_CHILD_ID]["present"])
        self.assertFalse(manifest["child_gates"][WEBRTC_CHILD_ID]["present"])

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_reads_existing_child_gate_summaries(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            android = root / "file-transfer-android-smoke-gate.json"
            webrtc = root / "webrtc-bulk-product-flow-gate.json"
            write_json(
                android,
                child_gate("android_macos_file_transfer_smoke", "can_close_file_transfer_android_smoke_gate"),
            )
            write_json(
                webrtc,
                child_gate(
                    "phase3_webrtc_bulk_product_flow_gate",
                    "can_close_public_internet_bulk_product_flow_gate",
                    verdict="blocked",
                ),
            )

            manifest = build_manifest(command=[], repo=root, android_gate=android, webrtc_gate=webrtc)

        self.assertTrue(manifest["child_gates"][ANDROID_CHILD_ID]["can_close"])
        self.assertEqual(manifest["child_gates"][WEBRTC_CHILD_ID]["verdict"], "blocked")
        self.assertEqual(manifest["child_gates"][ANDROID_CHILD_ID]["path"], android.name)

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_reads_real_child_gate_flag_names(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            android = root / "file-transfer-android-smoke-gate.json"
            webrtc = root / "webrtc-bulk-product-flow-gate.json"
            write_json(
                android,
                {
                    "kind": "android_macos_file_transfer_smoke",
                    "verdict": "pass",
                    "result": "pass",
                    "gate_closed": True,
                    "can_close_file_transfer_android_smoke_gate": True,
                    "blockers": [],
                    "not_proven": [],
                },
            )
            write_json(
                webrtc,
                {
                    "kind": "phase3_webrtc_bulk_product_flow_gate",
                    "verdict": "pass",
                    "gate_closed": True,
                    "can_close_public_internet_bulk_product_flow_gate": True,
                    "blockers": [],
                    "not_proven": [],
                },
            )

            manifest = build_manifest(command=[], repo=root, android_gate=android, webrtc_gate=webrtc)

        self.assertTrue(manifest["child_gates"][ANDROID_CHILD_ID]["can_close"])
        self.assertTrue(manifest["child_gates"][WEBRTC_CHILD_ID]["can_close"])

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_wrong_child_gate_kind_cannot_close_even_with_pass_flag(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            android = root / "clipboard-gate-misfiled-as-file-transfer.json"
            write_json(
                android,
                {
                    "kind": "android_macos_clipboard_e2e_gate",
                    "verdict": "pass",
                    "gate_closed": True,
                    "can_close_file_transfer_android_smoke_gate": True,
                    "blockers": [],
                    "not_proven": [],
                },
            )

            manifest = build_manifest(command=[], repo=root, android_gate=android)
            child = manifest["child_gates"][ANDROID_CHILD_ID]

        self.assertTrue(child["present"])
        self.assertFalse(child["can_close"])
        self.assertIn("kind mismatch", " ".join(child["blockers"]))
        self.assertIn("Real Android USB", child["not_proven"][0])

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_missing_child_gate_records_requirement_as_not_proven(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            manifest = build_manifest(command=[], repo=root)

        self.assertIn("Real Android USB", manifest["child_gates"][ANDROID_CHILD_ID]["not_proven"][0])
        self.assertIn("Real macOS and Android", manifest["child_gates"][WEBRTC_CHILD_ID]["not_proven"][0])

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_corrupted_child_gate_json_raises_manifest_error(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            bad_json = root / "file-transfer-android-smoke-gate.json"
            bad_json.write_text("{not valid json", encoding="utf-8")

            with self.assertRaises(ManifestError):
                build_manifest(command=[], repo=root, android_gate=bad_json)

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_non_dict_child_gate_json_raises_manifest_error(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            array_json = root / "webrtc-bulk-product-flow-gate.json"
            array_json.write_text("[]", encoding="utf-8")

            with self.assertRaises(ManifestError):
                build_manifest(command=[], repo=root, webrtc_gate=array_json)

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_manifest_matches_schema_required_top_level_fields(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            manifest = build_manifest(command=[], repo=root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(manifest), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, manifest)

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_missing_source_doc_is_recorded_not_probed(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            (root / SOURCE_DOCS[0]).parent.mkdir(parents=True, exist_ok=True)
            (root / SOURCE_DOCS[0]).write_text("fixture\n", encoding="utf-8")

            manifest = build_manifest(command=[], repo=root)

        self.assertIn(SOURCE_DOCS[1], manifest["source_docs"]["missing"])

    @patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state")
    def test_cli_writes_manifest(self, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            make_docs(root)
            output = root / "manifest.json"

            exit_code = main(["--repo", str(root), "--output", str(output), "--", "make", "gate"])
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["command"], ["make", "gate"])


if __name__ == "__main__":
    unittest.main()
