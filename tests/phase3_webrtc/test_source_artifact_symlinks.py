from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure
from scripts.phase3_webrtc.source_artifacts import repository_source_state


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


class SourceArtifactSymlinkTests(unittest.TestCase):
    def test_allows_only_the_repository_metadata_symlink_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / "README.md").write_text("source\n", encoding="utf-8")
            (repo / "CLAUDE.md").symlink_to("README.md")
            (repo / "AGENTS.md").symlink_to("CLAUDE.md")
            commit_all(repo)

            state = repository_source_state(repo)

            self.assertFalse(state["dirty"])

    def test_rejects_tracked_external_symlink_before_and_after_target_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            initialize_repository(repo)
            external = root / "external.swift"
            external.write_text("first\n", encoding="utf-8")
            (repo / "linked.swift").symlink_to(external)
            commit_all(repo)

            for content in ("first\n", "second\n"):
                external.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(E2EFailure, "tracked source symlink"):
                    repository_source_state(repo)

    def test_rejects_regular_tracked_file_replaced_by_external_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            initialize_repository(repo)
            source = repo / "source.swift"
            source.write_text("tracked\n", encoding="utf-8")
            commit_all(repo)
            external = root / "external.swift"
            external.write_text("external\n", encoding="utf-8")
            source.unlink()
            source.symlink_to(external)

            with self.assertRaisesRegex(E2EFailure, "untrusted symlink"):
                repository_source_state(repo)

    def test_rejects_untracked_external_symlink_after_target_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            initialize_repository(repo)
            (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            commit_all(repo)
            external = root / "external.txt"
            link = repo / "untracked.txt"
            external.write_text("first\n", encoding="utf-8")
            link.symlink_to(external)

            for content in ("first\n", "second\n"):
                external.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(E2EFailure, "untracked source path"):
                    repository_source_state(repo)

    def test_rejects_unapproved_repository_internal_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / "source.txt").write_text("source\n", encoding="utf-8")
            (repo / "alias.txt").symlink_to("source.txt")
            commit_all(repo)

            with self.assertRaisesRegex(E2EFailure, "tracked source symlink"):
                repository_source_state(repo)

    def test_rejects_metadata_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            initialize_repository(repo)
            (repo / "README.md").write_text("source\n", encoding="utf-8")
            (repo / "CLAUDE.md").symlink_to("../external.md")
            (repo / "AGENTS.md").symlink_to("CLAUDE.md")
            (root / "external.md").write_text("external\n", encoding="utf-8")
            commit_all(repo)

            with self.assertRaisesRegex(
                E2EFailure, "does not resolve inside the repository|target changed"
            ):
                repository_source_state(repo)

    def test_rejects_metadata_symlink_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / "README.md").write_text("source\n", encoding="utf-8")
            (repo / "CLAUDE.md").symlink_to("AGENTS.md")
            (repo / "AGENTS.md").symlink_to("CLAUDE.md")
            commit_all(repo)

            with self.assertRaisesRegex(E2EFailure, "does not resolve|target changed"):
                repository_source_state(repo)

    def test_rejects_broken_metadata_symlink_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            (repo / "README.md").write_text("source\n", encoding="utf-8")
            (repo / "CLAUDE.md").symlink_to("README.md")
            (repo / "AGENTS.md").symlink_to("CLAUDE.md")
            commit_all(repo)
            (repo / "README.md").unlink()

            with self.assertRaisesRegex(E2EFailure, "does not resolve"):
                repository_source_state(repo)

    def test_rejects_file_replacement_during_direct_hash_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            initialize_repository(repo)
            source = repo / "source.txt"
            source.write_bytes(b"a" * (1024 * 1024 + 1))
            commit_all(repo)
            real_read = os.read
            replaced = False

            def replace_after_read(descriptor: int, size: int) -> bytes:
                nonlocal replaced
                content = real_read(descriptor, size)
                if content and size == 1024 * 1024 and not replaced:
                    source.unlink()
                    source.write_bytes(b"replacement\n")
                    replaced = True
                return content

            with mock.patch(
                "scripts.phase3_webrtc.source_artifacts.os.read",
                side_effect=replace_after_read,
            ):
                with self.assertRaisesRegex(E2EFailure, "changed while"):
                    repository_source_state(repo)


if __name__ == "__main__":
    unittest.main()
