from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence.file_transfer_bulk_current_base_gate import derive_gate
from vibescreen_evidence.file_transfer_bulk_current_base_manifest import (
    ANDROID_CHILD_ID,
    SOURCE_DOCS,
    WEBRTC_CHILD_ID,
    build_manifest,
)


MODULE = "vibescreen_evidence.file_transfer_bulk_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "file-transfer-bulk-current-base-gate.schema.json"


def make_docs(root: Path) -> None:
    for path in SOURCE_DOCS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")


def make_manifest(root: Path, *, dirty: bool = False) -> dict[str, object]:
    make_docs(root)
    status = [" M README.md"] if dirty else []
    with patch("vibescreen_evidence.file_transfer_bulk_current_base_manifest.repository_state") as state:
        state.return_value = {"revision": "abc", "dirty": dirty, "status_porcelain": status}
        return build_manifest(command=[], repo=root)


def mark_child_pass(manifest: dict[str, object], child_id: str) -> None:
    child = manifest["child_gates"][child_id]
    assert isinstance(child, dict)
    if child_id == ANDROID_CHILD_ID:
        child.update(
            {
                "present": True,
                "kind": "android_macos_file_transfer_smoke",
                "verdict": "pass",
                "gate_closed": True,
                "can_close": True,
                "path": "file-transfer-android-smoke-gate.json",
                "blockers": [],
            }
        )
    else:
        child.update(
            {
                "present": True,
                "kind": "phase3_webrtc_bulk_product_flow_gate",
                "verdict": "pass",
                "gate_closed": True,
                "can_close": True,
                "path": "webrtc-bulk-product-flow-gate.json",
                "blockers": [],
            }
        )


def write_manifest(root: Path, manifest: dict[str, object]) -> Path:
    path = root / "file-transfer-bulk-current-base-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class FileTransferBulkCurrentBaseGateTests(unittest.TestCase):
    def test_default_manifest_blocks_without_child_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            report = derive_gate(make_manifest(root))

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_android_usb_lan_file_transfer"])
        self.assertFalse(report["can_close_webrtc_bulk_product_flow"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertFalse(report["can_claim_clipboard_gate"])
        self.assertIn("blocked: child.android_usb_lan_file_transfer", report["blockers"])
        self.assertIn("blocked: child.webrtc_bulk_product_flow", report["blockers"])

    def test_android_only_pass_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(report["can_close_android_usb_lan_file_transfer"])
        self.assertFalse(report["can_close_webrtc_bulk_product_flow"])
        self.assertFalse(report["can_close_current_base_aggregate"])

    def test_webrtc_only_pass_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["can_close_android_usb_lan_file_transfer"])
        self.assertTrue(report["can_close_webrtc_bulk_product_flow"])
        self.assertFalse(report["can_close_current_base_aggregate"])

    def test_both_child_gates_pass_closes_aggregate_without_claiming_clipboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_current_base_aggregate"])
        self.assertFalse(report["can_claim_clipboard_gate"])

    def test_dirty_manifest_context_blocks_even_with_child_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root, dirty=True)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("blocked: metadata.repository_clean", report["blockers"])

    def test_missing_source_docs_blocks_even_with_child_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            source_docs = manifest["source_docs"]
            assert isinstance(source_docs, dict)
            source_docs["missing"] = ["docs/changes/2026-08-21-file-transfer-e2e/TEST.md"]
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_current_base_aggregate"])
        self.assertIn("blocked: metadata.source_docs", report["blockers"])

    def test_p0110_webrtc_boundary_violation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            manifest["evidence_boundary"]["p0110_can_close_webrtc_bulk_public_internet"] = True
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: boundary.p0110_not_webrtc_bulk", report["blockers"])

    def test_p0110_usb_lan_boundary_violation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            manifest["evidence_boundary"]["p0110_can_close_usb_lan_file_transfer"] = False
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: boundary.p0110_usb_lan_only", report["blockers"])

    def test_clipboard_boundary_violation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            manifest["evidence_boundary"]["aggregate_claims_clipboard_gate"] = True
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_claim_clipboard_gate"])
        self.assertIn("blocked: boundary.clipboard_separate", report["blockers"])

    def test_external_collector_boundary_violation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            mark_child_pass(manifest, ANDROID_CHILD_ID)
            mark_child_pass(manifest, WEBRTC_CHILD_ID)
            manifest["evidence_boundary"]["aggregate_runs_external_collectors"] = True
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("blocked: boundary.no_external_collectors", report["blockers"])

    def test_wrong_android_child_kind_blocks_even_with_pass_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            child = manifest["child_gates"][ANDROID_CHILD_ID]
            assert isinstance(child, dict)
            child.update(
                {
                    "present": True,
                    "kind": "android_macos_clipboard_e2e_gate",
                    "verdict": "pass",
                    "gate_closed": True,
                    "can_close": True,
                    "blockers": [
                        "child gate report kind mismatch: expected android_macos_file_transfer_smoke, got 'android_macos_clipboard_e2e_gate'"
                    ],
                    "not_proven": ["real Android USB/LAN file transfer product evidence"],
                }
            )
            mark_child_pass(manifest, WEBRTC_CHILD_ID)

            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_android_usb_lan_file_transfer"])
        self.assertFalse(report["can_close_current_base_aggregate"])
        android_check = report["checks"][f"child.{ANDROID_CHILD_ID}"]
        self.assertFalse(android_check["passed"])
        self.assertIn("kind mismatch", " ".join(android_check["evidence"]))

    def test_failed_child_gate_makes_aggregate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            child = manifest["child_gates"][ANDROID_CHILD_ID]
            assert isinstance(child, dict)
            child["present"] = True
            child["verdict"] = "fail"
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_current_base_aggregate"])

    def test_webrtc_failed_child_gate_makes_aggregate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            child = manifest["child_gates"][WEBRTC_CHILD_ID]
            assert isinstance(child, dict)
            child["present"] = True
            child["verdict"] = "fail"
            report = derive_gate(manifest)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_current_base_aggregate"])

    def test_manifest_contract_violation_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = make_manifest(root)
            del manifest["child_gates"]
            report = derive_gate(manifest)

        self.assertEqual(report["derivation_status"], "failed")
        self.assertEqual(report["verdict"], "blocked")

    def test_report_matches_schema_required_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            report = derive_gate(make_manifest(root))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_cli_writes_blocked_report_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest_path = write_manifest(root, make_manifest(root))
            output_path = root / "gate.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
