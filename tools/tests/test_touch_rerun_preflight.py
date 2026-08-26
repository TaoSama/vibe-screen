from __future__ import annotations

import json
import queue
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence import touch_rerun_preflight
from vibescreen_evidence.touch_rerun_preflight import (
    ACCESSIBILITY_SERVICE,
    SCREEN_CAPTURE_SERVICE,
    build_blocked_error_document,
    collect_tcc,
    USER_TCC_DB,
    SYSTEM_TCC_DB,
    TouchRerunPreflightError,
    write_json,
    _public_path,
    _query_tcc_db,
    _blockers,
)


PRIVACY_DB_FILENAME = "privacy.sqlite"


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
            db_path = Path(directory) / PRIVACY_DB_FILENAME
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
            user_db = Path(directory) / "user-privacy.sqlite"
            system_db = Path(directory) / "system-privacy.sqlite"
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
            system_db = Path(directory) / "system-privacy.sqlite"
            self.write_tcc_db(
                system_db,
                [(SCREEN_CAPTURE_SERVICE, "dev.telemachus.display", 0, 2, 4, 20)],
            )

            tcc = collect_tcc([missing_db, system_db], "dev.telemachus.display")

        self.assertEqual(tcc["missing_db_paths"], [str(missing_db)])
        self.assertTrue(tcc["screen_recording"]["authorized"])

    def test_tcc_query_times_out_instead_of_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / PRIVACY_DB_FILENAME
            db_path.write_bytes(b"placeholder")
            queues = []

            class FakeQueue:
                def __init__(self):
                    self.closed = False
                    self.joined = False

                def get(self, timeout=None):
                    raise queue.Empty

                def close(self):
                    self.closed = True

                def join_thread(self):
                    self.joined = True

            class FakeProcess:
                exitcode = None

                def __init__(self, target, args):
                    self.terminated = False
                    self.killed = False

                def start(self):
                    return None

                def join(self, timeout=None):
                    return None

                def is_alive(self):
                    return not self.terminated and not self.killed

                def terminate(self):
                    self.terminated = True

                def kill(self):
                    self.killed = True

            class FakeContext:
                def Queue(self, maxsize=0):
                    result = FakeQueue()
                    queues.append(result)
                    return result

                Process = FakeProcess

            with patch(
                "vibescreen_evidence.touch_rerun_preflight.multiprocessing.get_context",
                return_value=FakeContext(),
            ):
                with self.assertRaisesRegex(TouchRerunPreflightError, "timed out"):
                    _query_tcc_db(db_path, "dev.telemachus.display", timeout_seconds=0.01)
            self.assertTrue(queues[0].closed)
            self.assertTrue(queues[0].joined)

    def test_tcc_query_reports_exited_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / PRIVACY_DB_FILENAME
            db_path.write_bytes(b"placeholder")

            class FakeQueue:
                def get(self, timeout=None):
                    raise queue.Empty

                def close(self):
                    return None

                def join_thread(self):
                    return None

            class FakeProcess:
                exitcode = 0

                def __init__(self, target, args):
                    pass

                def start(self):
                    return None

                def join(self, timeout=None):
                    return None

                def is_alive(self):
                    return False

            class FakeContext:
                def Queue(self, maxsize=0):
                    return FakeQueue()

                Process = FakeProcess

            with patch(
                "vibescreen_evidence.touch_rerun_preflight.multiprocessing.get_context",
                return_value=FakeContext(),
            ):
                with self.assertRaisesRegex(TouchRerunPreflightError, "exited without a result \(exit 0\)"):
                    _query_tcc_db(db_path, "dev.telemachus.display", timeout_seconds=0.01)

    def test_tcc_worker_preserves_unexpected_exception_detail(self) -> None:
        queue_instance = unittest.mock.Mock()
        with patch(
            "vibescreen_evidence.touch_rerun_preflight._query_tcc_db_direct",
            side_effect=RuntimeError("simulated worker failure"),
        ):
            touch_rerun_preflight._query_tcc_db_worker(
                queue_instance, Path(PRIVACY_DB_FILENAME), "dev.telemachus.display"
            )

        queue_instance.put.assert_called_once()
        status, payload = queue_instance.put.call_args.args[0]
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError('simulated worker failure')", payload)

    def test_tcc_query_context_falls_back_when_fork_is_unavailable(self) -> None:
        fallback_context = object()
        with patch(
            "vibescreen_evidence.touch_rerun_preflight.multiprocessing.get_context",
            side_effect=[ValueError("no fork"), fallback_context],
        ) as get_context:
            self.assertIs(touch_rerun_preflight._tcc_query_context(), fallback_context)

        self.assertEqual(get_context.call_count, 2)

    def test_main_writes_blocked_document_for_unexpected_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "touch-rerun-preflight.json"
            with patch(
                "vibescreen_evidence.touch_rerun_preflight.build_document",
                side_effect=RuntimeError("unexpected failure"),
            ):
                result = touch_rerun_preflight.main(["--output", str(output)])

            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(document["result"], "blocked")
        self.assertIn("unexpected failure", document["blockers"][0])

    def test_public_path_redacts_user_home(self) -> None:
        self.assertEqual(
            _public_path(USER_TCC_DB),
            "<user-tcc-db>",
        )
        self.assertEqual(
            _public_path(SYSTEM_TCC_DB),
            "<system-tcc-db>",
        )

    def test_build_document_omits_android_serial_fields(self) -> None:
        with patch(
            "vibescreen_evidence.touch_rerun_preflight.collect_host_bundle",
            return_value={"identifier": "dev.telemachus.display", "binary_sha256": "abc"},
        ), patch(
            "vibescreen_evidence.touch_rerun_preflight.collect_tcc",
            return_value={
                "screen_recording": {"authorized": True},
                "accessibility": {"authorized": True},
            },
        ), patch(
            "vibescreen_evidence.touch_rerun_preflight.collect_android",
            return_value={
                "adb_serial": "TEST_DEVICE_SERIAL",
                "device_serial": "TEST_DEVICE_SERIAL",
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": 36,
            },
        ):
            document = touch_rerun_preflight.build_document(
                bundle_path=Path("/Applications/Vibe Screen.app"),
                tcc_dbs=[Path("/tmp") / PRIVACY_DB_FILENAME],
                serial="TEST_DEVICE_SERIAL",
                adb_path="adb",
                adb_timeout=15.0,
                expected_host_sha256="abc",
            )

        self.assertNotIn("adb_serial", document["android_device"])
        self.assertNotIn("device_serial", document["android_device"])
        self.assertEqual(document["android_device"]["model"], "P0110")

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
