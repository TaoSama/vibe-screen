from __future__ import annotations

import os
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
    def test_controlled_device_endpoint_is_absent_from_files_and_paths(self) -> None:
        prohibited_endpoint = ("100.72." + "246.116:5555").encode("ascii")
        violations = []
        for directory, child_directories, filenames in os.walk(ROOT):
            child_directories[:] = [
                name for name in child_directories if name not in EXCLUDED_DIRECTORIES
            ]
            directory_path = Path(directory)
            for filename in filenames:
                path = directory_path / filename
                relative_path = path.relative_to(ROOT)
                if prohibited_endpoint.decode("ascii") in relative_path.as_posix():
                    violations.append(f"path:{relative_path}")
                    continue
                try:
                    content = path.read_bytes()
                except OSError:
                    continue
                if prohibited_endpoint in content:
                    violations.append(f"content:{relative_path}")
        self.assertEqual(violations, [])

    def test_makefile_has_no_device_endpoint_default(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("EVIDENCE_SERIAL ?=\n", makefile)
        self.assertIn("error: set EVIDENCE_SERIAL explicitly", makefile)


if __name__ == "__main__":
    unittest.main()
