import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.phase0_stable_release import (
    REQUIRED_GATE_IDS,
    Phase0StableReleaseError,
    evaluate_manifest,
)


MODULE = "vibescreen_evidence.phase0_stable_release"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase0-stable-release.schema.json"
MANIFEST_SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "phase0-stable-release-manifest.schema.json"
)
REPO_ROOT = Path(__file__).parents[2]
GUARDED_README_TEXT = (
    "Phase 0 remains in progress and this is a development preview "
    "rather than a stable release. Do not treat roadmap items below "
    "as shipped features."
)


def gate_by_id(manifest: dict[str, object], gate_id: str) -> dict[str, object]:
    gates = manifest["required_gates"]
    assert isinstance(gates, list)
    for gate in gates:
        assert isinstance(gate, dict)
        if gate["id"] == gate_id:
            return gate
    raise AssertionError(f"missing gate {gate_id}")


def complete_manifest() -> dict[str, object]:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase0_stable_release_closure",
        "phase": "phase0",
        "source": {"base_commit": "abc123"},
        "required_gates": [
            {
                "id": gate_id,
                "title": gate_id.replace("_", " "),
                "verdict": "pass",
                "required_for_stable_release": True,
                "evidence_strength": "current-real-device",
                "evidence_paths": [f"docs/evidence/{gate_id}.json"],
                "owner_prs": [],
                "blockers": [],
            }
            for gate_id in REQUIRED_GATE_IDS
        ],
    }


class Phase0StableReleaseTest(unittest.TestCase):
    def test_pass_requires_all_required_gates(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(), readme_text="Phase 0 stable-release summary"
        )

        self.assertEqual(summary["aggregate_verdict"], "pass")
        self.assertTrue(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["blocking_required_gates"], [])

    def test_open_sub_gate_blocks_aggregate_without_failing_readme_guard(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "host_rss_2h_no_growth")
        gate["verdict"] = "blocked"
        gate["evidence_strength"] = "readiness"
        gate["evidence_paths"] = []
        gate["blockers"] = ["host_rss_gate has no current-source pass"]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "blocked")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            [gate["id"] for gate in summary["blocking_required_gates"]],
            ["host_rss_2h_no_growth"],
        )
        self.assertEqual(summary["readme_guard"]["verdict"], "pass")

    def test_readme_guard_fails_on_premature_shipped_claim(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "native_pointer_hid_mouse")
        gate["verdict"] = "open"
        gate["evidence_strength"] = "readiness"

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 is complete and ready as a stable release.",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_pass_with_readiness_strength_is_insufficient(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "upstream_provenance_and_license")
        gate["evidence_strength"] = "readiness"

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertIn(
            "closing evidence strength",
            summary["gate_summaries"][0]["issues"][0],
        )

    def test_pass_requires_allowlisted_closing_evidence_strength(self) -> None:
        non_closing_strengths = (
            "partial",
            "historical-fail",
            "partial-current-source",
        )
        for evidence_strength in non_closing_strengths:
            with self.subTest(evidence_strength=evidence_strength):
                manifest = complete_manifest()
                gate = gate_by_id(manifest, "host_rss_2h_no_growth")
                gate["evidence_strength"] = evidence_strength

                summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

                self.assertEqual(summary["aggregate_verdict"], "insufficient")
                self.assertFalse(summary["can_mark_phase0_stable_release"])
                self.assertEqual(
                    [gate["id"] for gate in summary["blocking_required_gates"]],
                    ["host_rss_2h_no_growth"],
                )

    def test_pass_gate_with_blockers_is_insufficient(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "host_rss_2h_no_growth")
        gate["blockers"] = ["host RSS still grows"]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            [gate["id"] for gate in summary["blocking_required_gates"]],
            ["host_rss_2h_no_growth"],
        )
        self.assertIn(
            "pass gate must not list unresolved blockers",
            summary["blocking_required_gates"][0]["issues"],
        )

    def test_required_gate_cannot_be_marked_optional_to_close_aggregate(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "host_rss_2h_no_growth")
        gate["required_for_stable_release"] = False

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            [gate["id"] for gate in summary["blocking_required_gates"]],
            ["host_rss_2h_no_growth"],
        )
        self.assertIn(
            "required Phase 0 gate cannot set required_for_stable_release=false",
            summary["blocking_required_gates"][0]["issues"],
        )

    def test_missing_required_gate_is_insufficient(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = manifest["required_gates"][:-1]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["missing_required_gate_ids"], ["module_ownership_extraction"])

    def test_readme_guard_fails_on_phase0_has_shipped_claim(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 has shipped while this text omits the guard.",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_readme_guard_fails_on_stable_production_ready_or_ga_claim(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"
        guarded_text = GUARDED_README_TEXT + " "
        claims = (
            "Phase 0 is now stable.",
            "Phase 0 is production-ready.",
            "Phase 0 has reached stable.",
            "Phase 0 GA.",
            "Phase 0 is generally available.",
        )
        for claim in claims:
            with self.subTest(claim=claim):
                summary = evaluate_manifest(manifest, readme_text=guarded_text + claim)

                self.assertEqual(summary["aggregate_verdict"], "fail")
                self.assertEqual(summary["readme_guard"]["verdict"], "fail")
                self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_non_required_gate_issue_still_enforces_readme_guard(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"].append(
            {
                "id": "future_release_gate",
                "title": "Future release gate",
                "verdict": "pass",
                "required_for_stable_release": False,
                "evidence_strength": "readiness",
                "evidence_paths": ["docs/evidence/future.json"],
                "owner_prs": [],
                "blockers": [],
            }
        )

        summary = evaluate_manifest(manifest, readme_text="Phase 0 status summary")

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["missing_required_phrases"])

    def test_rejects_invalid_manifest_shape(self) -> None:
        with self.assertRaisesRegex(Phase0StableReleaseError, "kind must be"):
            evaluate_manifest({"schema_version": "vibescreen.evidence/v1", "kind": "wrong"})

    def test_summary_matches_schema_required_fields(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(), readme_text="Phase 0 stable-release summary"
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)

    def test_manifest_schema_gate_ids_match_checker(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        gate_ids = schema["$defs"]["gate"]["properties"]["id"]["enum"]

        self.assertEqual(gate_ids, list(REQUIRED_GATE_IDS))

    def test_checked_in_manifest_keeps_phase0_open(self) -> None:
        manifest_path = (
            REPO_ROOT
            / "docs/changes/2026-08-22-phase0-stable-release-aggregate/phase0-stable-release-manifest.json"
        )
        readme_path = REPO_ROOT / "README.md"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        summary = evaluate_manifest(
            manifest, readme_text=readme_path.read_text(encoding="utf-8")
        )

        self.assertEqual(summary["aggregate_verdict"], "blocked")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "pass")
        self.assertEqual(summary["closed_required_gate_count"], 5)


class Phase0StableReleaseCliTest(unittest.TestCase):
    def test_cli_allows_open_aggregate_by_default_but_writes_summary(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["verdict"] = "blocked"
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest_path = directory / "manifest.json"
            readme_path = directory / "README.md"
            output_path = directory / "summary.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            readme_path.write_text(GUARDED_README_TEXT, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--readme",
                    str(readme_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output_path.read_text())["aggregate_verdict"], "blocked")

    def test_cli_require_pass_exits_nonzero_for_open_aggregate(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["verdict"] = "blocked"
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest_path = directory / "manifest.json"
            readme_path = directory / "README.md"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            readme_path.write_text(GUARDED_README_TEXT, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--readme",
                    str(readme_path),
                    "--require-pass",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("aggregate_verdict", result.stdout)


if __name__ == "__main__":
    unittest.main()
