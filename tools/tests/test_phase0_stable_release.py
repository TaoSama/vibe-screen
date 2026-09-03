from concurrent.futures import ThreadPoolExecutor
import datetime as _datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.phase0_stable_release import (
    REQUIRED_GATE_IDS,
    Phase0StableReleaseError,
    _write_summary,
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
COMPLETE_MANIFEST_STRENGTHS = {
    "upstream_provenance_and_license": "current-source",
    "protocol_contract_ci": "current-ci",
    "android_clean_build": "current-ci",
    "macos_release_build_xcode_tests": "current-ci",
    "macos_host_hardware_compatibility_matrix": "current-real-device",
    "android_device_usb_stream_reconnect_codec": "current-real-device",
    "telemetry_and_latency_archive": "current-real-device",
    "host_rss_2h_no_growth": "current-real-device",
    "native_pointer_hid_mouse": "current-real-device",
    "controller_runtime_acceptance": "current-real-device",
    "clipboard_android_macos_product_e2e": "current-real-device",
    "file_transfer_android_product_e2e": "current-real-device",
    "module_ownership_extraction": "current-source",
}


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
        "source": {
            "base_commit": "abc123",
            "base_ref": "origin/main",
            "audit_date": "2026-08-22",
            "owner": "Vibe Screen core team",
            "audit_source": "docs/audit.md",
        },
        "open_pr_snapshot": {
            "repository": "TaoSama/vibe-screen",
            "command": "gh pr list --repo TaoSama/vibe-screen --state open --limit 200 --json number,title,headRefName,headRefOid,baseRefName,updatedAt,isDraft,mergeStateStatus,url",
            "queried_at": "2026-08-22",
            "state": "open",
            "open_pr_numbers": [],
        },
        "required_gates": [
            {
                "id": gate_id,
                "title": gate_id.replace("_", " "),
                "verdict": "pass",
                "required_for_stable_release": True,
                "evidence_strength": COMPLETE_MANIFEST_STRENGTHS[gate_id],
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
        self.assertEqual(summary["source_guard"]["verdict"], "pass")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")

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
        self.assertIn(
            "host_rss_2h_no_growth: host_rss_gate has no current-source pass",
            summary["reasons"],
        )

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

    def test_runtime_gate_requires_gate_specific_closing_strength(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "native_pointer_hid_mouse")
        gate["evidence_strength"] = "current-source"

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            [gate["id"] for gate in summary["blocking_required_gates"]],
            ["native_pointer_hid_mouse"],
        )
        self.assertIn(
            "closing evidence strength for this gate",
            summary["blocking_required_gates"][0]["issues"][0],
        )

    def test_retained_real_device_strength_only_closes_android_baseline_gate(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "android_device_usb_stream_reconnect_codec")
        gate["evidence_strength"] = "real-device"

        summary = evaluate_manifest(
            manifest, readme_text="Phase 0 stable-release summary"
        )

        self.assertEqual(summary["aggregate_verdict"], "pass")
        self.assertTrue(summary["can_mark_phase0_stable_release"])

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

    def test_non_pass_required_gate_must_explain_blocker(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "host_rss_2h_no_growth")
        gate["verdict"] = "blocked"
        gate["blockers"] = []

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertIn(
            "non-pass required gate must list at least one blocker",
            summary["blocking_required_gates"][0]["issues"],
        )
        self.assertIn(
            "host_rss_2h_no_growth: non-pass required gate must list at least one blocker",
            summary["reasons"],
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

    def test_expected_source_commit_must_match_manifest_base_commit(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            readme_text=GUARDED_README_TEXT,
            expected_source_commit="def456",
        )

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn("source.base_commit", summary["reasons"][0])
        self.assertEqual(summary["readme_guard"]["verdict"], "pass")

    def test_owner_prs_require_open_pr_snapshot(self) -> None:
        manifest = complete_manifest()
        manifest.pop("open_pr_snapshot")
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [158])
        self.assertIn(
            "owner_prs require open_pr_snapshot",
            summary["owner_pr_guard"]["reasons"][0],
        )

    def test_owner_prs_must_match_current_open_pr_snapshot(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = []

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["owner_pr_guard"]["owner_prs"], [158])
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [158])
        self.assertIn("#158", summary["owner_pr_guard"]["reasons"][0])

    def test_owner_prs_can_match_current_open_pr_snapshot(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [158]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [158, 232]

        summary = evaluate_manifest(manifest, readme_text="Phase 0 stable-release summary")

        self.assertEqual(summary["aggregate_verdict"], "pass")
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")
        self.assertEqual(summary["owner_pr_guard"]["repository"], "TaoSama/vibe-screen")
        self.assertEqual(summary["owner_pr_guard"]["stale_owner_prs"], [])

    def test_owner_prs_reject_bool_values(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [True]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [1]

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "owner_prs must be a list of integers"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_bool_pr_numbers(self) -> None:
        manifest = complete_manifest()
        gate_by_id(manifest, "host_rss_2h_no_growth")["owner_prs"] = [1]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [True]

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "open_pr_numbers must be a list of integers"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_wrong_repository(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["repository"] = "TaoSama/other"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "open_pr_snapshot.repository"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_command_must_target_repository(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --repo TaoSama/other --state open --limit 200 --json number"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_missing_repo_option(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --state open --limit 200 --json number"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_accepts_gh_short_options(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list -R TaoSama/vibe-screen -s open --limit 200 --json number"
        )

        summary = evaluate_manifest(
            manifest,
            readme_text="Phase 0 stable-release summary",
            evaluation_date=_datetime.date(2026, 8, 22),
        )

        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")

    def test_open_pr_snapshot_rejects_malformed_command(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["command"] = (
            "gh pr list --repo 'TaoSama/vibe-screen --state open"
        )

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must list open PRs for TaoSama/vibe-screen"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_rejects_future_queried_at(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "2026-08-23"
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-23"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "queried_at must not be in the future"
        ):
            evaluate_manifest(
                manifest,
                readme_text=GUARDED_README_TEXT,
                evaluation_date=_datetime.date(2026, 8, 22),
            )

    def test_open_pr_snapshot_date_must_match_audit_date(self) -> None:
        manifest = complete_manifest()
        stale_owner = gate_by_id(manifest, "host_rss_2h_no_growth")
        stale_owner["owner_prs"] = [158]
        manifest["open_pr_snapshot"]["open_pr_numbers"] = [158]
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-21"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must match manifest source.audit_date"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_open_pr_snapshot_date_must_not_be_after_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["open_pr_snapshot"]["queried_at"] = "2026-08-23"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "must match manifest source.audit_date"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

    def test_manifest_source_requires_traceable_fields(self) -> None:
        manifest = complete_manifest()
        manifest["source"] = {"base_commit": "abc123", "audit_date": "20260822"}

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn("manifest source.base_ref must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.owner must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.audit_source must be a non-empty string", summary["reasons"])
        self.assertIn("manifest source.audit_date must use YYYY-MM-DD format", summary["reasons"])

    def test_manifest_source_rejects_future_audit_date(self) -> None:
        manifest = complete_manifest()
        manifest["source"]["audit_date"] = "2026-08-23"
        manifest.pop("open_pr_snapshot")

        summary = evaluate_manifest(
            manifest,
            readme_text=GUARDED_README_TEXT,
            evaluation_date=_datetime.date(2026, 8, 22),
        )

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertIn(
            "manifest source.audit_date must not be in the future",
            summary["reasons"],
        )

    def test_stale_manifest_requires_readme_guard_even_when_sub_gates_pass(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            readme_text="Phase 0 is stable.",
            expected_source_commit="def456",
        )

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["source_guard"]["verdict"], "insufficient")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")

    def test_expected_source_commit_allows_matching_manifest_base_commit(self) -> None:
        summary = evaluate_manifest(
            complete_manifest(),
            readme_text="Phase 0 stable-release summary",
            expected_source_commit="abc123",
        )

        self.assertEqual(summary["aggregate_verdict"], "pass")
        self.assertTrue(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["source_guard"]["verdict"], "pass")

    def test_hardware_compatibility_matrix_is_required(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = [
            gate
            for gate in manifest["required_gates"]
            if gate["id"] != "macos_host_hardware_compatibility_matrix"
        ]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            summary["missing_required_gate_ids"],
            ["macos_host_hardware_compatibility_matrix"],
        )

    def test_clipboard_product_e2e_is_required(self) -> None:
        manifest = complete_manifest()
        manifest["required_gates"] = [
            gate
            for gate in manifest["required_gates"]
            if gate["id"] != "clipboard_android_macos_product_e2e"
        ]

        summary = evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(
            summary["missing_required_gate_ids"],
            ["clipboard_android_macos_product_e2e"],
        )

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

    def test_missing_readme_guard_cannot_pass_aggregate(self) -> None:
        summary = evaluate_manifest(complete_manifest(), readme_text=None)

        self.assertEqual(summary["aggregate_verdict"], "insufficient")
        self.assertFalse(summary["can_mark_phase0_stable_release"])
        self.assertEqual(summary["readme_guard"]["verdict"], "insufficient")

    def test_empty_readme_guard_config_cannot_disable_default_guard(self) -> None:
        manifest = complete_manifest()
        manifest["readme_guard"] = {
            "required_phrases": [],
            "forbidden_regexes": [],
        }
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        summary = evaluate_manifest(manifest, readme_text="Phase 0 is now stable.")

        self.assertEqual(summary["aggregate_verdict"], "fail")
        self.assertEqual(summary["readme_guard"]["verdict"], "fail")
        self.assertTrue(summary["readme_guard"]["missing_required_phrases"])
        self.assertTrue(summary["readme_guard"]["forbidden_matches"])

    def test_invalid_readme_guard_regex_reports_manifest_error(self) -> None:
        manifest = complete_manifest()
        manifest["readme_guard"] = {"forbidden_regexes": ["("]}
        gate_by_id(manifest, "native_pointer_hid_mouse")["verdict"] = "open"

        with self.assertRaisesRegex(
            Phase0StableReleaseError, "invalid regex"
        ):
            evaluate_manifest(manifest, readme_text=GUARDED_README_TEXT)

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
        self.assertEqual(summary["closed_required_gate_count"], 6)
        self.assertEqual(summary["owner_pr_guard"]["verdict"], "pass")
        self.assertEqual(summary["owner_pr_guard"]["open_pr_numbers"], [])
        self.assertEqual(summary["owner_pr_guard"]["owner_prs"], [])
        macos_gate = gate_by_id(manifest, "macos_host_hardware_compatibility_matrix")
        self.assertEqual(macos_gate["verdict"], "open")
        self.assertIn(
            "docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-31-macos-host-compatibility-current-base-codex-task-blocked/macos-hardware-compatibility-gate.json",
            macos_gate["evidence_paths"],
        )
        self.assertIn(
            "docs/changes/2026-08-21-host-signing-tcc-preflight/evidence/2026-08-31-macos-host-compatibility-current-base-codex-task-blocked/README.md",
            macos_gate["evidence_paths"],
        )


class Phase0StableReleaseCliTest(unittest.TestCase):
    def test_cli_allows_open_aggregate_by_default_but_writes_summary(self) -> None:
        manifest = complete_manifest()
        gate = gate_by_id(manifest, "host_rss_2h_no_growth")
        gate["verdict"] = "blocked"
        gate["blockers"] = ["host_rss_gate has no current-source pass"]
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

    def test_summary_writer_uses_unique_atomic_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output_path = directory / "phase0-summary.json"

            def write_summary(index: int) -> None:
                _write_summary(
                    output_path,
                    {
                        "schema_version": "vibescreen.evidence/v1",
                        "kind": "phase0_stable_release_closure_summary",
                        "writer": index,
                    },
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_summary, range(40)))

            summary = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn(summary["writer"], range(40))
            self.assertFalse((directory / "phase0-summary.json.tmp").exists())
            self.assertEqual(list(directory.glob(".phase0-summary.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
