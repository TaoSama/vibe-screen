from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.actionable_error_states import (
    ActionableErrorStateError,
    KIND,
    parse_session_failure_kinds,
    evaluate,
    load_matrix,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "changes"
    / "2026-08-23-actionable-error-states"
    / "actionable-error-states.json"
)
SESSION_FAILURE_SOURCE = (
    REPOSITORY_ROOT
    / "baseline"
    / "AndroidClient"
    / "app"
    / "src"
    / "main"
    / "java"
    / "dev"
    / "telemachus"
    / "display"
    / "SessionFailure.kt"
)
MODULE = "vibescreen_evidence.actionable_error_states"
SCHEMA_PATH = REPOSITORY_ROOT / "tools" / "schemas" / "actionable-error-states-gate.schema.json"


class ActionableErrorStateGateTests(unittest.TestCase):
    def load_real_matrix(self) -> dict[str, object]:
        return load_matrix(MATRIX_PATH)

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
            if "minItems" in node:
                self.assertGreaterEqual(len(value), node["minItems"], path)
            for index, item in enumerate(value):
                self.assert_schema_node(item, node["items"], root, f"{path}[{index}]")
        elif expected_type == "string":
            self.assertIsInstance(value, str, path)
            if "minLength" in node:
                self.assertGreaterEqual(len(value), node["minLength"], path)
        elif expected_type == "integer":
            self.assertIsInstance(value, int, path)
            self.assertNotIsInstance(value, bool, path)
            if "minimum" in node:
                self.assertGreaterEqual(value, node["minimum"], path)
        elif expected_type == "boolean":
            self.assertIsInstance(value, bool, path)

    def test_real_matrix_passes_and_cannot_close_readme_gate(self) -> None:
        report = evaluate(
            self.load_real_matrix(),
            android_session_failure_kinds=parse_session_failure_kinds(SESSION_FAILURE_SOURCE),
            repository_root=REPOSITORY_ROOT,
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertFalse(report["can_close_readme_phase1_actionable_errors_gate"])
        self.assertEqual(report["missing_android_session_failure_kinds"], [])
        self.assertGreaterEqual(report["android_state_count"], 8)
        self.assertGreaterEqual(report["macos_host_state_count"], 8)
        self.assertEqual(report["matrix_kind"], KIND)

    def test_real_gate_report_matches_published_schema(self) -> None:
        report = evaluate(
            self.load_real_matrix(),
            android_session_failure_kinds=parse_session_failure_kinds(SESSION_FAILURE_SOURCE),
            repository_root=REPOSITORY_ROOT,
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assert_schema_node(report, schema, schema)

    def test_fail_gate_report_matches_published_schema(self) -> None:
        report = evaluate({})
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(report["verdict"], "fail")
        self.assert_schema_node(report, schema, schema)

    def test_fail_gate_report_omits_blank_session_failure_kinds_for_schema(self) -> None:
        matrix = self.load_real_matrix()
        states = matrix["states"]
        assert isinstance(states, list)
        states[0]["android_session_failure_kinds"] = [""]

        report = evaluate(matrix)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(report["verdict"], "fail")
        self.assertNotIn("", report["covered_android_session_failure_kinds"])
        self.assert_schema_node(report, schema, schema)

    def test_rejects_missing_required_pr_review(self) -> None:
        matrix = self.load_real_matrix()
        matrix["reviewed_open_prs"] = [242, 272]

        report = evaluate(matrix)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("reviewed_open_prs: missing required PR review(s) #243", report["errors"])

    def test_rejects_attempt_to_close_readme_gate_from_offline_matrix(self) -> None:
        matrix = self.load_real_matrix()
        matrix["readme_gate_closure"] = True
        states = matrix["states"]
        assert isinstance(states, list)
        states[0]["readme_gate_closure"] = True

        report = evaluate(matrix)

        self.assertIn("readme_gate_closure: must be false for this offline owner slice", report["errors"])
        self.assertIn("states[0].readme_gate_closure: must be false", report["errors"])
        self.assertFalse(report["can_close_readme_phase1_actionable_errors_gate"])

    def test_rejects_bare_localized_description_as_user_copy(self) -> None:
        matrix = self.load_real_matrix()
        states = matrix["states"]
        assert isinstance(states, list)
        states[0]["user_visible_copy"] = "localizedDescription"

        report = evaluate(matrix)

        self.assertIn("states[0].user_visible_copy: must not be a bare localizedDescription", report["errors"])

    def test_rejects_missing_offline_evidence_path(self) -> None:
        matrix = self.load_real_matrix()
        states = matrix["states"]
        assert isinstance(states, list)
        states[0]["offline_evidence"] = ["docs/runbook/missing-actionable-error-section.md#anchor"]

        report = evaluate(matrix, repository_root=REPOSITORY_ROOT)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn(
            "states[0].offline_evidence: missing repository path "
            "docs/runbook/missing-actionable-error-section.md",
            report["errors"],
        )

    def test_rejects_session_failure_enum_drift(self) -> None:
        matrix = self.load_real_matrix()

        report = evaluate(matrix, android_session_failure_kinds={"TRANSPORT_CLOSED", "NEW_KIND"})

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("android_session_failure_kinds: missing NEW_KIND", report["errors"])

    def test_session_failure_parser_ignores_nested_enum_body_braces(self) -> None:
        source = """
            package dev.telemachus.display

            internal enum class SessionFailureKind {
                TRANSPORT_CLOSED({ "diagnostic { detail }" }),
                HEARTBEAT_TIMEOUT,
                ;

                fun describe(): String {
                    return "not an enum entry"
                }
            }

            internal enum class OtherKind {
                SHOULD_NOT_APPEAR,
            }
        """
        with tempfile.TemporaryDirectory() as directory_name:
            source_path = Path(directory_name) / "SessionFailure.kt"
            source_path.write_text(source, encoding="utf-8")

            kinds = parse_session_failure_kinds(source_path)

        self.assertEqual(kinds, {"TRANSPORT_CLOSED", "HEARTBEAT_TIMEOUT"})

    def test_session_failure_parser_ignores_fake_enums_in_comments_and_strings(self) -> None:
        source = '''
            package dev.telemachus.display

            // enum class SessionFailureKind { COMMENT_ONLY }
            /* enum class SessionFailureKind { BLOCK_COMMENT_ONLY } */
            private const val fake = "enum class SessionFailureKind { STRING_ONLY }"
            private const val fakeTriple = """enum class SessionFailureKind { TRIPLE_STRING_ONLY }"""

            internal enum class SessionFailureKind {
                TRANSPORT_CLOSED,
                HEARTBEAT_TIMEOUT,
            }
        '''
        with tempfile.TemporaryDirectory() as directory_name:
            source_path = Path(directory_name) / "SessionFailure.kt"
            source_path.write_text(source, encoding="utf-8")

            kinds = parse_session_failure_kinds(source_path)

        self.assertEqual(kinds, {"TRANSPORT_CLOSED", "HEARTBEAT_TIMEOUT"})

    def test_evaluate_reports_drift_from_real_enum_after_fake_enum_prefixes(self) -> None:
        source = '''
            package dev.telemachus.display

            // enum class SessionFailureKind { COMMENT_ONLY }
            private const val fake = "enum class SessionFailureKind { STRING_ONLY }"

            internal enum class SessionFailureKind {
                TRANSPORT_CLOSED({ "diagnostic { detail }" }),
                NEW_KIND,
                ;
            }
        '''
        with tempfile.TemporaryDirectory() as directory_name:
            source_path = Path(directory_name) / "SessionFailure.kt"
            source_path.write_text(source, encoding="utf-8")

            kinds = parse_session_failure_kinds(source_path)

        report = evaluate(self.load_real_matrix(), android_session_failure_kinds=kinds)

        self.assertEqual(report["verdict"], "fail")
        self.assertIn("android_session_failure_kinds: missing NEW_KIND", report["errors"])

    def test_session_failure_parser_rejects_unbalanced_enum_body(self) -> None:
        source = """
            package dev.telemachus.display

            internal enum class SessionFailureKind {
                TRANSPORT_CLOSED({ "diagnostic" }),
                HEARTBEAT_TIMEOUT,
        """
        with tempfile.TemporaryDirectory() as directory_name:
            source_path = Path(directory_name) / "SessionFailure.kt"
            source_path.write_text(source, encoding="utf-8")

            with self.assertRaisesRegex(ActionableErrorStateError, "not balanced"):
                parse_session_failure_kinds(source_path)

    def test_rejects_too_few_host_states(self) -> None:
        matrix = self.load_real_matrix()
        states = matrix["states"]
        assert isinstance(states, list)
        matrix["states"] = [state for state in states if state["platform"] != "macos_host"]

        report = evaluate(matrix)

        self.assertIn("states: must contain at least 8 macOS Host states", report["errors"])

    def test_cli_writes_pass_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output_path = Path(directory_name) / "gate.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    str(MATRIX_PATH),
                    "--android-session-failure-source",
                    str(SESSION_FAILURE_SOURCE),
                    "--repository-root",
                    str(REPOSITORY_ROOT),
                    "--output",
                    str(output_path),
                ],
                cwd=str(REPOSITORY_ROOT / "tools"),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["verdict"], "pass")
        self.assertFalse(report["can_close_readme_phase1_actionable_errors_gate"])


if __name__ == "__main__":
    unittest.main()
