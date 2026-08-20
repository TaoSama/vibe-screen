from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence.touch_rerun_preflight import (
    ACCESSIBILITY_SERVICE,
    SCREEN_CAPTURE_SERVICE,
    build_document,
    collect_tcc,
    write_json,
    _blockers,
)


class TouchRerunPreflightTests(unittest.TestCase):
    def write_tcc_db(self, path: Path, rows: list[tuple[str, str, int, int, int, int]]) -> None:
        connection = sqlite3.connect(path)
        connection.execute(
            """
            create table access (
                service text not null,
                client text not null,
                client_type integer not null,
                auth_value integer not null,
                auth_reason integer not null,
                last_modified integer not null
            )
            """
        )
        connection.executemany("insert into access values (?, ?, ?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()

    def test_tcc_collection_marks_screen_and_accessibility_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "TCC.db"
            self.write_tcc_db(
                db_path,
                [
                    (SCREEN_CAPTURE_SERVICE, "dev.telemachus.display", 0, 2, 4, 10),
                    (ACCESSIBILITY_SERVICE, "dev.telemachus.display", 0, 2, 4, 11),
                ],
            )

            tcc = collect_tcc([db_path], "dev.telemachus.display")

        self.assertTrue(tcc["screen_recording"]["authorized"])
        self.assertTrue(tcc["accessibility"]["authorized"])
        self.assertEqual(tcc["accessibility"]["auth_value"], 2)
        self.assertEqual(tcc["accessibility"]["db_path"], str(db_path))

    def test_tcc_collection_merges_user_and_system_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user_db = Path(directory) / "user-TCC.db"
            system_db = Path(directory) / "system-TCC.db"
            self.write_tcc_db(
                user_db,
                [(SCREEN_CAPTURE_SERVICE, "dev.telemachus.display", 0, 0, 4, 10)],
            )
            self.write_tcc_db(
                system_db,
                [
                    (SCREEN_CAPTURE_SERVICE, "dev.telemachus.display", 0, 2, 4, 20),
                    (ACCESSIBILITY_SERVICE, "dev.telemachus.display", 0, 0, 4, 21),
                ],
            )

            tcc = collect_tcc([user_db, system_db], "dev.telemachus.display")

        self.assertTrue(tcc["screen_recording"]["authorized"])
        self.assertEqual(tcc["screen_recording"]["db_path"], str(system_db))
        self.assertFalse(tcc["accessibility"]["authorized"])

    def test_tcc_collection_records_missing_databases_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_db = Path(directory) / "missing.db"
            system_db = Path(directory) / "system-TCC.db"
            self.write_tcc_db(
                system_db,
                [(SCREEN_CAPTURE_SERVICE, "dev.telemachus.display", 0, 2, 4, 20)],
            )

            tcc = collect_tcc([missing_db, system_db], "dev.telemachus.display")

        self.assertEqual(tcc["missing_db_paths"], [str(missing_db)])
        self.assertTrue(tcc["screen_recording"]["authorized"])

    def test_blockers_require_expected_fixed_binary_permissions_and_device(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "old"},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": False},
            },
            android=None,
            expected_host_sha256="new",
            current_source=None,
            require_current_source=False,
        )

        self.assertIn(
            "installed Host binary SHA-256 does not match the expected fixed binary",
            blockers,
        )
        self.assertIn(
            "Accessibility is not authorized for the Host bundle identifier",
            blockers,
        )
        self.assertIn("no explicit Android device serial was recorded", blockers)

    def test_no_blockers_when_preconditions_are_present(self) -> None:
        blockers = _blockers(
            host={
                "binary_sha256": "abc",
                "source": {"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
            },
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={"model": "P0110"},
            expected_host_sha256="abc",
            current_source={"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
            require_current_source=True,
        )

        self.assertEqual(blockers, [])

    def test_current_source_requirement_blocks_legacy_or_stale_host(self) -> None:
        base = {
            "tcc": {
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            "android": {"model": "P0110"},
            "expected_host_sha256": None,
            "current_source": {"commit": "a" * 40, "tree": "b" * 40, "dirty": False},
            "require_current_source": True,
        }

        legacy = _blockers(host={"binary_sha256": "abc", "source": {}}, **base)
        self.assertIn("installed Host bundle does not record its source commit/tree identity", legacy)

        stale = _blockers(
            host={
                "binary_sha256": "abc",
                "source": {"commit": "c" * 40, "tree": "d" * 40, "dirty": False},
            },
            **base,
        )
        self.assertIn("installed Host bundle source commit does not match current HEAD", stale)
        self.assertIn("installed Host bundle source tree does not match current tree", stale)

    def test_current_source_requirement_blocks_dirty_repository_or_packaged_host(self) -> None:
        blockers = _blockers(
            host={
                "binary_sha256": "abc",
                "source": {"commit": "a" * 40, "tree": "b" * 40, "dirty": True},
            },
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={"model": "P0110"},
            expected_host_sha256=None,
            current_source={"commit": "a" * 40, "tree": "b" * 40, "dirty": True},
            require_current_source=True,
        )

        self.assertIn("repository source root is dirty", "\n".join(blockers))

    def test_current_source_is_not_required_for_historical_fixed_binary_preflight(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "abc", "source": {}},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={"model": "P0110"},
            expected_host_sha256="abc",
            current_source=None,
            require_current_source=False,
        )

        self.assertEqual(blockers, [])

    def test_build_document_records_current_source_requirement(self) -> None:
        with (
            patch(
                "vibescreen_evidence.touch_rerun_preflight.collect_host_bundle",
                return_value={
                    "identifier": "dev.telemachus.display",
                    "binary_sha256": "abc",
                    "source": {"commit": "old", "tree": "old-tree", "dirty": False},
                },
            ),
            patch(
                "vibescreen_evidence.touch_rerun_preflight.collect_tcc",
                return_value={
                    "screen_recording": {"authorized": True},
                    "accessibility": {"authorized": True},
                },
            ),
            patch(
                "vibescreen_evidence.touch_rerun_preflight.collect_android",
                return_value={"model": "P0110"},
            ),
            patch(
                "vibescreen_evidence.touch_rerun_preflight.collect_current_source",
                return_value={"commit": "new", "tree": "new-tree", "dirty": False},
            ),
        ):
            document = build_document(
                bundle_path=Path("/Applications/Vibe Screen.app"),
                tcc_dbs=[Path("TCC.db")],
                serial="EP0110PZ0B9110300B",
                adb_path="adb",
                adb_timeout=1.0,
                expected_host_sha256=None,
                source_root=Path("."),
                require_current_source=True,
            )

        self.assertEqual(document["result"], "blocked")
        self.assertTrue(document["current_source_required"])
        self.assertEqual(document["current_source"]["commit"], "new")
        self.assertIn("installed Host bundle source commit does not match current HEAD", document["blockers"])

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight" / "result.json"
            write_json(path, {"result": "blocked"})
            self.assertEqual(json.loads(path.read_text()), {"result": "blocked"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
