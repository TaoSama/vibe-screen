from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure, PUBLIC_GATE_FAILURE_SCHEMA
from scripts.phase3_webrtc.public_evidence import (
    build_gate_failure_diagnostic,
    build_public_artifact_tree,
)


class PublicOutputLifecycleTests(unittest.TestCase):
    def test_missing_root_rejects_stale_custom_output_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "missing-private"
            outside = root / "stale-public"
            outside.mkdir()
            sentinel = outside / "pass.json"
            sentinel.write_text('{"result":"pass"}\n', encoding="utf-8")

            with self.assertRaisesRegex(E2EFailure, "exactly <private-root>/public"):
                build_public_artifact_tree(
                    source,
                    outside,
                    allow_missing=True,
                )

            self.assertEqual(
                sentinel.read_text(encoding="utf-8"),
                '{"result":"pass"}\n',
            )

    def test_missing_root_default_output_returns_empty_without_creating_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "missing-private"
            output = source / "public"

            self.assertEqual(
                build_public_artifact_tree(source, output, allow_missing=True),
                0,
            )
            self.assertFalse(source.exists())
            self.assertFalse(output.exists())

    def test_empty_existing_root_removes_stale_custom_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            source.mkdir()
            output = source / "public"
            output.mkdir()
            (output / "pass.json").write_text(
                '{"result":"pass"}\n',
                encoding="utf-8",
            )

            self.assertEqual(
                build_public_artifact_tree(source, output, allow_missing=True),
                0,
            )
            self.assertFalse(output.exists())

    def test_output_symlink_is_unlinked_without_touching_target_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            source.mkdir()
            target = root / "outside"
            target.mkdir()
            sentinel = target / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            output = source / "public"
            os.symlink(target, output)

            with self.assertRaisesRegex(E2EFailure, "must not be a symlink"):
                build_public_artifact_tree(source, output, allow_missing=True)

            self.assertFalse(output.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_failure_diagnostic_is_fixed_and_contains_no_pass_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            source.mkdir()
            (source / "direct.json").write_text(
                '{"result":"pass","private":"must-not-project"}\n',
                encoding="utf-8",
            )
            output = source / "public-failure"

            self.assertEqual(build_gate_failure_diagnostic(source, output), 1)

            files = [path for path in output.rglob("*") if path.is_file()]
            self.assertEqual([path.name for path in files], ["gate-failure.json"])
            rendered = files[0].read_text(encoding="utf-8")
            self.assertNotIn("pass", rendered.lower())
            self.assertNotIn("must-not-project", rendered)
            self.assertEqual(
                json.loads(rendered),
                {
                    "gate": "direct-and-relay-product-e2e",
                    "private_runner_output_uploaded": False,
                    "schema": PUBLIC_GATE_FAILURE_SCHEMA,
                    "status": "failed",
                    "successful_evidence_uploaded": False,
                },
            )


if __name__ == "__main__":
    unittest.main()
