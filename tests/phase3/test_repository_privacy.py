from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRECTORIES = {
    ".build",
    ".git",
    ".gradle",
    ".swiftpm",
    "__pycache__",
    "DerivedData",
    "build",
    "node_modules",
}


class RepositoryPrivacyTests(unittest.TestCase):
    def test_branch_does_not_extend_historical_endpoint_exposure(self) -> None:
        baseline_paths = self._git("ls-tree", "-r", "--name-only", "origin/main").splitlines()
        endpoint_pattern = re.compile(
            r"device-(?P<ip>(?:[0-9]{1,3}\.){3}[0-9]{1,3})-(?P<port>[0-9]{2,5})(?:/|$)"
        )
        endpoints = {
            (match.group("ip"), match.group("port"))
            for path in baseline_paths
            if (match := endpoint_pattern.search(path))
        }
        self.assertTrue(endpoints, "Public baseline endpoint history was not discoverable")

        prohibited_variants = {
            variant.encode("ascii")
            for ip, port in endpoints
            for variant in (ip, f"{ip}:{port}", f"{ip}-{port}", f"device-{ip}-{port}")
        }
        violations = []
        for directory, child_directories, filenames in os.walk(ROOT):
            child_directories[:] = [
                name for name in child_directories if name not in EXCLUDED_DIRECTORIES
            ]
            directory_path = Path(directory)
            for filename in filenames:
                path = directory_path / filename
                relative_path = path.relative_to(ROOT)
                try:
                    content = path.read_bytes()
                except OSError:
                    continue
                path_bytes = relative_path.as_posix().encode("utf-8")
                if not any(value in path_bytes or value in content for value in prohibited_variants):
                    continue
                baseline = subprocess.run(
                    ["git", "show", f"origin/main:{relative_path.as_posix()}"],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                )
                if baseline.returncode != 0 or baseline.stdout != content:
                    violations.append(f"branch-owned:{relative_path}")

        name_status = self._git("diff", "--name-status", "-M", "origin/main...HEAD").encode()
        added_patch_lines = b"\n".join(
            line
            for line in self._git("diff", "--unified=0", "origin/main...HEAD").encode().splitlines()
            if line.startswith(b"+") and not line.startswith(b"+++")
        )
        for value in prohibited_variants:
            if value in name_status:
                violations.append(f"diff-metadata:{value!r}")
            if value in added_patch_lines:
                violations.append(f"diff-addition:{value!r}")
        self.assertEqual(violations, [])

    def _git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def test_makefile_has_no_device_endpoint_default(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("EVIDENCE_SERIAL ?=\n", makefile)
        self.assertIn("error: set EVIDENCE_SERIAL explicitly", makefile)


if __name__ == "__main__":
    unittest.main()
