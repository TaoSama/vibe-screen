from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure, EVIDENCE_SCHEMA
from scripts.phase3_webrtc.source_artifacts import repository_source_state


FIXTURE_SCHEMA = "dev.vibescreen.phase3-webrtc-e2e-test-fixture/v1"


def initialize_repository(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
    )


def commit_all(root: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


class SourceEvidencePolicyTests(unittest.TestCase):
    def test_current_repository_has_no_runtime_pass_evidence_outside_build(self) -> None:
        repository_source_state(ROOT)

    def test_rejects_tracked_runtime_pass_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            evidence = repo / "stale-evidence.json"
            evidence.write_text(
                json.dumps({"schema": EVIDENCE_SCHEMA, "result": "pass"}),
                encoding="utf-8",
            )
            commit_all(repo)

            with self.assertRaisesRegex(E2EFailure, "tracked Phase 3 runtime PASS"):
                repository_source_state(repo)

    def test_rejects_untracked_runtime_pass_evidence_outside_build_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            commit_all(repo)
            (repo / "stale-evidence.json").write_text(
                json.dumps({"schema": EVIDENCE_SCHEMA, "result": "pass"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(E2EFailure, "stored under .build"):
                repository_source_state(repo)

    def test_allows_explicitly_named_non_runtime_fixture_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            fixture = repo / "sample-evidence.fixture.json"
            fixture.write_text(
                json.dumps({"schema": FIXTURE_SCHEMA, "result": "pass"}),
                encoding="utf-8",
            )
            commit_all(repo)

            state = repository_source_state(repo)

            self.assertFalse(state["dirty"])

    def test_rejects_ignored_file_under_build_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / ".gitignore").write_text(
                "services/signaling/*.local\n", encoding="utf-8"
            )
            signaling = repo / "services/signaling"
            signaling.mkdir(parents=True)
            (signaling / "main.go").write_text("package main\n", encoding="utf-8")
            commit_all(repo)
            (signaling / "credentials.local").write_text("secret\n", encoding="utf-8")

            with self.assertRaisesRegex(E2EFailure, "ignored files exist"):
                repository_source_state(repo)

    def test_allows_ignored_build_outputs_under_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / ".gitignore").write_text("**/.build*/\n", encoding="utf-8")
            mac = repo / "baseline/MacHost"
            mac.mkdir(parents=True)
            (mac / "Package.swift").write_text("// fixture\n", encoding="utf-8")
            commit_all(repo)
            output = mac / ".build-security-debug/cache.bin"
            output.parent.mkdir()
            output.write_bytes(b"generated")

            state = repository_source_state(repo)

            self.assertFalse(state["dirty"])


if __name__ == "__main__":
    unittest.main()
