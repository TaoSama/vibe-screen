from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.manifest import ManifestError, build_manifest, repository_state, write_manifest


class ManifestTests(unittest.TestCase):
    def test_repository_state_supports_unborn_repository(self) -> None:
        def fake_run(command, **kwargs):
            if command[-1] == "--is-inside-work-tree":
                return subprocess.CompletedProcess(command, 0, "true\n", "")
            if command[1:3] == ["status", "--porcelain=v1"]:
                return subprocess.CompletedProcess(command, 0, "?? file\n", "")
            return subprocess.CompletedProcess(command, 128, "", "no HEAD")

        with patch("vibescreen_evidence.manifest.subprocess.run", side_effect=fake_run):
            state = repository_state(Path("."))
        self.assertEqual(state["revision"], "UNBORN")
        self.assertTrue(state["dirty"])

    def test_non_repository_is_rejected(self) -> None:
        completed = subprocess.CompletedProcess(["git"], 128, "", "not a repository")
        with patch("vibescreen_evidence.manifest.subprocess.run", return_value=completed):
            with self.assertRaises(ManifestError):
                repository_state(Path("."))

    @patch("vibescreen_evidence.manifest.repository_state")
    def test_build_and_atomic_write(self, state) -> None:
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        manifest = build_manifest(kind="soak", command=["soak", "--duration", "30m"], repo=Path("."))
        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "manifest.json"
            write_manifest(output, manifest)
            self.assertEqual(json.loads(output.read_text())["kind"], "soak")
            self.assertFalse(output.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
