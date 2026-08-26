from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.coturn_allocation_exporter import (  # noqa: E402
    INPUT_SCHEMA,
    METADATA_SCHEMA,
    ExporterError,
    build_metadata,
    normalize_collector_input,
)


class CoturnAllocationExporterTests(unittest.TestCase):
    def valid_input(self) -> dict[str, object]:
        return {
            "schema": INPUT_SCHEMA,
            "source_id": "turn-prod-1",
            "boot_id": "boot-20260825",
            "observed_at": "2026-08-25T01:02:03Z",
            "allocations": [
                {
                    "allocation_id": "allocation-1",
                    "turn_username": "1780000000:device-1",
                    "device_id": "device-1",
                    "session_id": "session-1",
                    "sequence": 7,
                    "ingress_bytes": 1024,
                    "egress_bytes": 2048,
                    "closed": False,
                }
            ],
        }

    def test_normalizes_trusted_collector_input_to_reconcile_snapshot(self) -> None:
        export = normalize_collector_input(self.valid_input())

        self.assertEqual(export["source_id"], "turn-prod-1")
        self.assertEqual(export["boot_id"], "boot-20260825")
        self.assertEqual(
            export["snapshot"],
            {
                "source_id": "turn-prod-1",
                "observed_at": "2026-08-25T01:02:03Z",
                "allocations": [
                    {
                        "allocation_id": "allocation-1",
                        "device_id": "device-1",
                        "session_id": "session-1",
                        "sequence": 7,
                        "ingress_bytes": 1024,
                        "egress_bytes": 2048,
                        "closed": False,
                    }
                ],
            },
        )
        metadata = build_metadata(export)
        self.assertEqual(metadata["schema"], METADATA_SCHEMA)
        self.assertEqual(metadata["allocation_count"], 1)
        self.assertEqual(
            metadata["release_gate_boundary"],
            "structured_export_only_not_public_internet_or_live_disconnect_evidence",
        )

    def test_rejects_turn_username_not_bound_to_device_id(self) -> None:
        payload = self.valid_input()
        payload["allocations"][0]["turn_username"] = "1780000000:other-device"  # type: ignore[index]

        with self.assertRaisesRegex(ExporterError, "map to device_id"):
            normalize_collector_input(payload)

    def test_rejects_secret_like_fields_anywhere(self) -> None:
        payload = self.valid_input()
        payload["allocations"][0]["turn_password"] = "must-not-enter-evidence"  # type: ignore[index]

        with self.assertRaisesRegex(ExporterError, "secret-like"):
            normalize_collector_input(payload)

    def test_cli_writes_snapshot_and_metadata_with_restricted_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            collector = root / "collector.json"
            snapshot = root / "snapshot.json"
            metadata = root / "metadata.json"
            collector.write_text(json.dumps(self.valid_input()), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/phase3/coturn_allocation_exporter.py"),
                    "--input",
                    str(collector),
                    "--output",
                    str(snapshot),
                    "--metadata-output",
                    str(metadata),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(snapshot.read_text(encoding="utf-8"))["source_id"], "turn-prod-1")
            self.assertEqual(json.loads(metadata.read_text(encoding="utf-8"))["schema"], METADATA_SCHEMA)
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            self.assertEqual(metadata.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
