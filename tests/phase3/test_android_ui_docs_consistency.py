from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROOT_README = ROOT / "README.md"
ANDROID_BUILD_GRADLE = ROOT / "baseline/AndroidClient/app/build.gradle.kts"


def clients_section(readme: str) -> str:
    start = readme.index("\n### Clients\n")
    end = readme.index("\n### Protocol and transport\n", start)
    return readme[start:end]


class AndroidUiDocsConsistencyTests(unittest.TestCase):
    def test_readme_does_not_present_compose_as_current_android_ui_without_source(self) -> None:
        readme = ROOT_README.read_text(encoding="utf-8")
        build_gradle = ANDROID_BUILD_GRADLE.read_text(encoding="utf-8")

        clients = clients_section(readme)
        self.assertIn("currently uses Kotlin, XML Views/ViewBinding", clients)
        self.assertIn("Compose remains the target direction", clients)

        kotlin_source_root = ROOT / "baseline/AndroidClient/app/src/main/java"
        has_compose_dependency = bool(re.search(r"androidx\.compose", build_gradle))
        has_compose_source = any(
            path.suffix in {".kt", ".java"} and "Compose" in path.name
            for path in kotlin_source_root.rglob("*")
        )
        self.assertFalse(
            has_compose_dependency or has_compose_source,
            "Android client currently uses XML Views/ViewBinding, not Compose",
        )


if __name__ == "__main__":
    unittest.main()
