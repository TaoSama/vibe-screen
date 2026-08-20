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
    build_blocked_error_document,
    collect_tcc,
    USER_TCC_DB,
    write_json,
    _public_path,
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

    def test_public_path_redacts_user_home(self) -> None:
        self.assertEqual(
            _public_path(USER_TCC_DB),
            "<user-home>/Library/Application Support/com.apple.TCC/TCC.db",
        )
        self.assertEqual(
            _public_path(Path("/Library/Application Support/com.apple.TCC/TCC.db")),
            "/Library/Application Support/com.apple.TCC/TCC.db",
        )

    def test_blockers_require_expected_fixed_binary_permissions_and_device(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "old"},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": False},
            },
            android=None,
            expected_host_sha256="new",
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

    def test_blockers_require_expected_android_identity_when_supplied(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "abc"},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={
                "manufacturer": "Xiaomi",
                "model": "2211133C",
                "device": "fuxi",
                "android_release": "16",
                "sdk": 36,
            },
            expected_host_sha256="abc",
            expected_android_manufacturer="nubia",
            expected_android_model="P0110",
            expected_android_device="pacific",
            expected_android_release="16",
            expected_android_sdk=36,
        )

        self.assertIn(
            "Android device manufacturer does not match expected value 'nubia' (actual 'Xiaomi')",
            blockers,
        )
        self.assertIn(
            "Android device model does not match expected value 'P0110' (actual '2211133C')",
            blockers,
        )
        self.assertIn(
            "Android device device does not match expected value 'pacific' (actual 'fuxi')",
            blockers,
        )

    def test_no_blockers_when_preconditions_are_present(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "abc"},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={"model": "P0110"},
            expected_host_sha256="abc",
        )

        self.assertEqual(blockers, [])

    def test_no_blockers_when_expected_android_identity_matches(self) -> None:
        blockers = _blockers(
            host={"binary_sha256": "abc"},
            tcc={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
            android={
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": 36,
            },
            expected_host_sha256="abc",
            expected_android_manufacturer="nubia",
            expected_android_model="P0110",
            expected_android_device="pacific",
            expected_android_release="16",
            expected_android_sdk=36,
        )

        self.assertEqual(blockers, [])

    def test_blocked_error_document_is_safe_to_archive(self) -> None:
        document = build_blocked_error_document(
            RuntimeError("missing Host"),
            expected_host_sha256="abc",
            expected_android_manufacturer="nubia",
            expected_android_model="P0110",
            expected_android_device="pacific",
            expected_android_release="16",
            expected_android_sdk=36,
        )

        self.assertEqual(document["result"], "blocked")
        self.assertIn("missing Host", document["blockers"][0])
        self.assertEqual(document["expected_host_sha256"], "abc")
        self.assertEqual(document["expected_android_device"]["model"], "P0110")
        self.assertTrue(document["safety"]["read_only"])
        self.assertFalse(document["safety"]["runs_instrumentation"])

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight" / "result.json"
            write_json(path, {"result": "blocked"})
            self.assertEqual(json.loads(path.read_text()), {"result": "blocked"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
