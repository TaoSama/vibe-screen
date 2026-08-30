from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.network_recovery_blocked_evidence import (
    BLOCKED_GATES,
    SCHEMA,
    build_evidence,
    build_parser,
    build_readme,
    main,
)
from scripts.phase3.release_gate_manifest import validate_manifest


class NetworkRecoveryBlockedEvidenceTests(unittest.TestCase):
    def test_blocked_evidence_never_claims_release_gate(self) -> None:
        args = build_parser().parse_args(["--output-dir", "/tmp/unused"])
        evidence = build_evidence(
            args,
            {"commit": "b" * 40, "tree_status": "dirty", "status_sha256": "c" * 64},
        )

        self.assertEqual(evidence["schema"], SCHEMA)
        self.assertEqual(evidence["result"], "blocked")
        self.assertTrue(evidence["blocked_before_adb"])
        self.assertEqual(evidence["blocked_gates"], list(BLOCKED_GATES))
        self.assertEqual(evidence["device"]["model"], "P0110")
        self.assertFalse(evidence["device"]["adb_serial_used"])
        self.assertEqual(evidence["adb_command_required_for_future_run"], "adb -s <device-serial> ...")
        self.assertFalse(evidence["claims"]["phase3_release_gate_closed"])

    def test_blocked_evidence_keeps_adb_command_aligned_with_configured_serial(self) -> None:
        args = build_parser().parse_args(
            [
                "--output-dir",
                "/tmp/unused",
                "--device-manufacturer",
                "Samsung",
                "--device-model",
                "Galaxy",
                "--device-codename",
                "galaxy",
                "--device-serial",
                "SAMSUNG123",
            ]
        )
        evidence = build_evidence(
            args,
            {"commit": "b" * 40, "tree_status": "dirty", "status_sha256": "c" * 64},
        )

        self.assertEqual(evidence["device"]["manufacturer"], "Samsung")
        self.assertEqual(evidence["adb_command_required_for_future_run"], "adb -s SAMSUNG123 ...")
        self.assertIn("adb -s SAMSUNG123 ...", build_readme(evidence))
        self.assertNotIn("<device-serial>", build_readme(evidence))

    def test_cli_writes_blocked_manifest_that_fails_pass_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"
            completed_values = {
                ("rev-parse", "HEAD"): subprocess.CompletedProcess([], 0, stdout="b" * 40 + "\n"),
                ("status", "--porcelain=v1"): subprocess.CompletedProcess([], 0, stdout=""),
            }

            def fake_run(command, **_kwargs):
                return completed_values[tuple(command[1:])]

            with mock.patch("scripts.phase3.network_recovery_blocked_evidence.subprocess.run", side_effect=fake_run):
                self.assertEqual(main(["--repo-root", str(ROOT), "--output-dir", str(output_dir)]), 0)

            blocked = json.loads((output_dir / "blocked-evidence.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "release-gate-manifest.json").read_text(encoding="utf-8"))
            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            self.assertEqual(blocked["result"], "blocked")
            self.assertIn("adb -s <device-serial> ...", readme)
            self.assertTrue((output_dir / "README.md").is_file())
            self.assertNotEqual(validate_manifest(manifest, evidence_root=output_dir), [])


if __name__ == "__main__":
    unittest.main()
