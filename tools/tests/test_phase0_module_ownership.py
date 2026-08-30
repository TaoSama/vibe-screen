import json
import subprocess
import sys
import tempfile
import unittest
import datetime as _datetime
from pathlib import Path

from vibescreen_evidence.phase0_module_ownership import (
    REQUIRED_BOUNDARY_IDS,
    Phase0ModuleOwnershipError,
    evaluate_manifest,
)


MODULE = "vibescreen_evidence.phase0_module_ownership"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase0-module-ownership.schema.json"
REPO_ROOT = Path(__file__).parents[2]
CURRENT_MANIFEST = (
    REPO_ROOT
    / "docs"
    / "changes"
    / "2026-08-22-phase0-stable-release-aggregate"
    / "phase0-module-ownership-manifest.json"
)


def boundary_by_id(manifest: dict[str, object], boundary_id: str) -> dict[str, object]:
    boundaries = manifest["module_boundaries"]
    assert isinstance(boundaries, list)
    for boundary in boundaries:
        assert isinstance(boundary, dict)
        if boundary["id"] == boundary_id:
            return boundary
    raise AssertionError(f"missing boundary {boundary_id}")


def complete_manifest() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase0_module_ownership_current_base_manifest",
        "phase": "phase0",
        "source": {
            "base_commit": "b54ee0e929c53459e6ba7e060f2c9de0c846f408",
            "base_ref": "origin/main",
            "audit_date": "2026-08-29",
            "owner": "test",
        },
        "module_boundaries": [
            {
                "id": boundary_id,
                "title": boundary_id.replace("_", " "),
                "required_for_phase0_stable": True,
                "status": "closed",
                "owner_surface": "owner",
                "evidence_paths": ["README.md"],
                "focused_tests": ["make test"],
                "blockers": [],
                "fail_closed_checklist": [],
            }
            for boundary_id in REQUIRED_BOUNDARY_IDS
        ],
    }


class Phase0ModuleOwnershipTest(unittest.TestCase):
    def test_all_closed_boundaries_can_close_module_ownership(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            repo_root=REPO_ROOT,
            evaluation_date=_datetime.date(2026, 8, 29),
        )

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_phase0_module_ownership_extraction"])
        self.assertEqual(summary["open_required_boundaries"], [])

    def test_partial_required_boundary_blocks_without_claiming_closure(self) -> None:
        manifest = complete_manifest()
        boundary = boundary_by_id(manifest, "decoder_ownership")
        boundary["status"] = "partial"
        boundary["blockers"] = ["decoder lifecycle is not extracted"]
        boundary["fail_closed_checklist"] = ["extract decoder owner"]

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_phase0_module_ownership_extraction"])
        self.assertEqual(
            [boundary["id"] for boundary in summary["open_required_boundaries"]],
            ["decoder_ownership"],
        )

    def test_open_boundary_without_blocker_is_insufficient(self) -> None:
        manifest = complete_manifest()
        boundary = boundary_by_id(manifest, "renderer_ownership")
        boundary["status"] = "open"
        boundary["blockers"] = []
        boundary["fail_closed_checklist"] = []

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "open required boundary must list blockers or a fail-closed checklist",
            summary["open_required_boundaries"][0]["issues"],
        )

    def test_closed_boundary_requires_focused_test_and_no_blocker(self) -> None:
        manifest = complete_manifest()
        boundary = boundary_by_id(manifest, "protocol_session_ownership")
        boundary["focused_tests"] = []
        boundary["blockers"] = ["still coupled"]

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "closed boundary must cite at least one focused test or gate",
            summary["open_required_boundaries"][0]["issues"],
        )
        self.assertIn(
            "closed boundary must not list blockers",
            summary["open_required_boundaries"][0]["issues"],
        )

    def test_missing_required_boundary_is_insufficient(self) -> None:
        manifest = complete_manifest()
        manifest["module_boundaries"] = manifest["module_boundaries"][:-1]

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["missing_required_boundary_ids"], ["ui_product_session_boundaries"])

    def test_missing_evidence_path_is_insufficient(self) -> None:
        manifest = complete_manifest()
        boundary = boundary_by_id(manifest, "transport_dependency_direction")
        boundary["evidence_paths"] = ["missing/current-base-evidence.txt"]

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(
            summary["open_required_boundaries"][0]["missing_evidence_paths"],
            ["missing/current-base-evidence.txt"],
        )

    def test_standalone_fragment_evidence_path_is_insufficient(self) -> None:
        manifest = complete_manifest()
        boundary = boundary_by_id(manifest, "transport_dependency_direction")
        boundary["evidence_paths"] = ["#non-document-fragment"]

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT, evaluation_date=_datetime.date(2026, 8, 29))

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(
            summary["open_required_boundaries"][0]["missing_evidence_paths"],
            ["#non-document-fragment"],
        )

    def test_rejects_malformed_base_commit(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["base_commit"] = "not-a-sha"

        with self.assertRaisesRegex(Phase0ModuleOwnershipError, "40-character Git SHA"):
            evaluate_manifest(manifest)

    def test_rejects_future_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "2026-08-30"

        with self.assertRaisesRegex(Phase0ModuleOwnershipError, "must not be in the future"):
            evaluate_manifest(manifest, evaluation_date=_datetime.date(2026, 8, 29))

    def test_rejects_non_iso_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "08/29/2026"

        with self.assertRaisesRegex(Phase0ModuleOwnershipError, "must be an ISO date"):
            evaluate_manifest(manifest, evaluation_date=_datetime.date(2026, 8, 29))

    def test_rejects_absolute_or_escaped_evidence_paths(self) -> None:
        for evidence_path in ["/etc/hosts", "../vibe-screen/README.md"]:
            with self.subTest(evidence_path=evidence_path):
                manifest = complete_manifest()
                boundary = boundary_by_id(manifest, "transport_dependency_direction")
                boundary["evidence_paths"] = [evidence_path]

                summary = evaluate_manifest(
                    manifest,
                    repo_root=REPO_ROOT,
                    evaluation_date=_datetime.date(2026, 8, 29),
                )

                self.assertEqual(summary["verdict"], "insufficient")
                self.assertEqual(
                    summary["open_required_boundaries"][0]["missing_evidence_paths"],
                    [evidence_path],
                )

    def test_current_manifest_records_open_work_and_stays_blocked(self) -> None:
        manifest = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))

        summary = evaluate_manifest(manifest, repo_root=REPO_ROOT)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_phase0_module_ownership_extraction"])
        self.assertEqual(summary["required_boundary_count"], len(REQUIRED_BOUNDARY_IDS))
        self.assertLess(
            summary["closed_required_boundary_count"],
            summary["required_boundary_count"],
        )
        self.assertIn(
            "ui_product_session_boundaries",
            {boundary["id"] for boundary in summary["open_required_boundaries"]},
        )

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            repo_root=REPO_ROOT,
            evaluation_date=_datetime.date(2026, 8, 29),
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)

    def test_cli_writes_blocked_summary_and_require_pass_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "summary.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(CURRENT_MANIFEST),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--output",
                    str(output),
                    "--require-pass",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(output.exists(), result.stderr)
            summary = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["verdict"], "blocked")
            self.assertFalse(summary["can_close_phase0_module_ownership_extraction"])


if __name__ == "__main__":
    unittest.main()
