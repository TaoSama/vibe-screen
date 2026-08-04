from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.android_internet_acceptance import AcceptanceError, _require_pattern, coordinate_pair, swipe


class AndroidAcceptanceTests(unittest.TestCase):
    def test_coordinates_parse_without_shell_interpolation(self) -> None:
        self.assertEqual(coordinate_pair("540,1600"), (540, 1600))
        self.assertEqual(swipe("1,2,3,4,250"), (1, 2, 3, 4, 250))

    def test_invalid_coordinates_are_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            coordinate_pair("-1,2")
        with self.assertRaises(argparse.ArgumentTypeError):
            swipe("1,2,3")

    def test_required_observation_fails_closed(self) -> None:
        with self.assertRaises(AcceptanceError):
            _require_pattern("stream", r"decoded frame", "application merely launched")
        _require_pattern("stream", r"decoded frame", "decoded frame 42")

    def test_cli_writes_failure_evidence_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "failure.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3/android_internet_acceptance.py"),
                    "--apk",
                    str(Path(directory) / "missing.apk"),
                    "--streaming-pattern",
                    "frame",
                    "--input-pattern",
                    "ack",
                    "--reconnect-pattern",
                    "reconnect",
                    "--evidence",
                    str(evidence),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["result"], "failed")


if __name__ == "__main__":
    unittest.main()
