from __future__ import annotations

import plistlib
import queue
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import macos_dev_host


class MacOSDevHostMetadataTests(unittest.TestCase):
    def test_codesign_detail_parser_records_stable_identity_fields(self) -> None:
        fields = macos_dev_host.parse_codesign_details(
            """
Executable=/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen
Identifier=dev.telemachus.display
Format=app bundle with Mach-O thin (arm64)
Signature size=8988
Authority=Vibe Screen Dev
Authority=Vibe Screen Dev Root
TeamIdentifier=not set
CDHash=e4ac7dab68720d647550f2e031f40070ab291e8b
"""
        )

        self.assertEqual(fields["Identifier"], "dev.telemachus.display")
        self.assertEqual(fields["Authority"], ["Vibe Screen Dev", "Vibe Screen Dev Root"])
        self.assertEqual(fields["CDHash"], "e4ac7dab68720d647550f2e031f40070ab291e8b")

    def test_designated_requirement_parser_extracts_leaf_certificate_hash(self) -> None:
        requirement = macos_dev_host.parse_designated_requirement(
            'designated => identifier "dev.telemachus.display" and certificate leaf = H"9aae572bf6d764e3436a6109197d345b5a87998c"\n'
        )

        self.assertEqual(
            requirement,
            'identifier "dev.telemachus.display" and certificate leaf = H"9aae572bf6d764e3436a6109197d345b5a87998c"',
        )
        self.assertEqual(
            macos_dev_host.parse_leaf_certificate_hash(requirement),
            "9AAE572BF6D764E3436A6109197D345B5A87998C",
        )

    def test_report_records_identity_hash_permission_state_and_system_path(self) -> None:
        metadata = self.metadata()
        permissions = macos_dev_host.PermissionStatus(
            database_path=Path("TCC.db"),
            readable=True,
            rows=(
                macos_dev_host.TCCRow(
                    "kTCCServiceScreenCapture",
                    "dev.telemachus.display",
                    0,
                    2,
                    4,
                    1786811437,
                ),
                macos_dev_host.TCCRow(
                    "kTCCServiceAccessibility",
                    "dev.telemachus.display",
                    0,
                    0,
                    4,
                    1786811429,
                ),
            ),
        )
        errors = macos_dev_host.validate_preflight(
            metadata,
            permissions,
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
        )

        report = macos_dev_host.format_report(metadata, permissions, errors)

        self.assertIn("Identity: Vibe Screen Dev", report)
        self.assertIn("Certificate SHA-1: 9AAE572BF6D764E3436A6109197D345B5A87998C", report)
        self.assertIn("CDHash: e4ac7dab68720d647550f2e031f40070ab291e8b", report)
        self.assertIn("kTCCServiceAccessibility|dev.telemachus.display|0|0|4|1786811429", report)
        self.assertIn("Status: FAIL", report)
        self.assertIn("System Settings -> Privacy & Security", report)

    def test_validate_preflight_rejects_ad_hoc_and_missing_permissions(self) -> None:
        metadata = self.metadata(authorities=(), signature="adhoc")
        permissions = macos_dev_host.PermissionStatus(
            database_path=Path("TCC.db"),
            readable=True,
            rows=(),
        )

        errors = macos_dev_host.validate_preflight(
            metadata,
            permissions,
            install_path=Path("/tmp/Vibe Screen.app"),
        )

        self.assertIn("Host must be installed at the stable path", "\n".join(errors))
        self.assertIn("Host is ad-hoc signed", "\n".join(errors))
        self.assertIn("Screen Recording is not authorized", "\n".join(errors))
        self.assertIn("Accessibility is not authorized", "\n".join(errors))

    def test_refuse_ad_hoc_identity_for_local_install(self) -> None:
        with self.assertRaisesRegex(SystemExit, "stable signing identity"):
            macos_dev_host.refuse_ad_hoc_identity("-")

    def test_validate_preflight_rejects_unexpected_named_identity(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(authorities=("Other Dev",)),
            macos_dev_host.PermissionStatus(
                database_path=Path("TCC.db"),
                readable=True,
                rows=(
                    macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
                    macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
                ),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            expected_sign_identity="Vibe Screen Dev",
        )

        self.assertIn("expected configured identity", "\n".join(errors))

    def test_preflight_command_reports_ad_hoc_blocker_before_reading_bundle_or_tcc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="-",
                tcc_db=Path("TCC.db"),
                report=report,
            )
            with (
                mock.patch.object(macos_dev_host, "collect_signing_metadata") as metadata_mock,
                mock.patch.object(macos_dev_host, "query_tcc_rows") as tcc_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.preflight_command(args)
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result, 2)
            self.assertIn("Host signing prerequisite", report_text)
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("stable signing identity", report_text)
        metadata_mock.assert_not_called()
        tcc_mock.assert_not_called()

    def test_preflight_command_writes_report_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path("TCC.db"),
                report=report,
            )
            with (
                mock.patch.object(macos_dev_host.package_macos, "resolve_sign_identity"),
                mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
                mock.patch.object(
                    macos_dev_host,
                    "query_tcc_rows",
                    return_value=macos_dev_host.PermissionStatus(
                        database_path=Path("TCC.db"),
                        readable=True,
                        rows=(
                            macos_dev_host.TCCRow(
                                "kTCCServiceScreenCapture",
                                "dev.telemachus.display",
                                0,
                                2,
                                4,
                                1,
                            ),
                        ),
                    ),
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.preflight_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Accessibility is not authorized", report.read_text(encoding="utf-8"))

    def test_preflight_command_does_not_require_identity_in_keychain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Missing Dev",
                tcc_db=Path("TCC.db"),
                report=report,
            )
            with (
                mock.patch.object(
                    macos_dev_host.package_macos,
                    "resolve_sign_identity",
                    side_effect=SystemExit("missing identity"),
                ) as resolve_mock,
                mock.patch.object(
                    macos_dev_host,
                    "collect_signing_metadata",
                    return_value=self.metadata(authorities=("Missing Dev",)),
                ) as metadata_mock,
                mock.patch.object(
                    macos_dev_host,
                    "query_tcc_rows",
                    return_value=macos_dev_host.PermissionStatus(
                        database_path=Path("TCC.db"),
                        readable=True,
                        rows=(
                            macos_dev_host.TCCRow(
                                "kTCCServiceScreenCapture",
                                "dev.telemachus.display",
                                0,
                                2,
                                4,
                                1,
                            ),
                            macos_dev_host.TCCRow(
                                "kTCCServiceAccessibility",
                                "dev.telemachus.display",
                                0,
                                2,
                                4,
                                2,
                            ),
                        ),
                    ),
                ) as tcc_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.preflight_command(args)
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result, 0)
            self.assertIn("Status: PASS", report_text)
            self.assertIn("Identity: Missing Dev", report_text)
        resolve_mock.assert_not_called()
        metadata_mock.assert_called_once_with(macos_dev_host.DEFAULT_INSTALL_PATH)
        tcc_mock.assert_called_once()

    def test_collect_signing_metadata_reports_codesign_failure_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            MacOSDevHostInstallTests.write_app(app, executable=b"binary")
            with mock.patch.object(
                macos_dev_host,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["codesign"], output="bad signature"),
            ):
                with self.assertRaisesRegex(SystemExit, "bad signature"):
                    macos_dev_host.collect_signing_metadata(app)

    def test_install_command_checks_installed_identity_against_configured_identity(self) -> None:
        args = mock.Mock(
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            output_dir=Path("out"),
            sign_identity="Vibe Screen Dev",
            tcc_db=Path("TCC.db"),
            report=Path("report.txt"),
        )
        with (
            mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")),
            mock.patch.object(macos_dev_host, "safe_replace_app"),
            mock.patch.object(
                macos_dev_host,
                "metadata_and_permissions",
                return_value=(self.metadata(), macos_dev_host.PermissionStatus(Path("TCC.db"), (), True), []),
            ) as metadata_mock,
            mock.patch.object(macos_dev_host, "write_report"),
            redirect_stdout(StringIO()),
        ):
            macos_dev_host.install_command(args)
        metadata_mock.assert_called_once_with(
            macos_dev_host.DEFAULT_INSTALL_PATH,
            Path("TCC.db"),
            expected_sign_identity="Vibe Screen Dev",
        )

    def test_install_command_reports_missing_signing_identity_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=Path("TCC.db"),
                report=report,
            )
            with (
                mock.patch.object(
                    macos_dev_host,
                    "package_dev_app",
                    side_effect=SystemExit("codesign identity 'Vibe Screen Dev' not found in the keychain"),
                ) as package_mock,
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.install_command(args)
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result, 2)
            self.assertIn("Host signing prerequisite", report_text)
            self.assertIn("Vibe Screen Dev", report_text)
            self.assertIn("not an Android device identity or Xiaomi/fuxi result", " ".join(report_text.split()))
        package_mock.assert_called_once_with(Path("out"), "Vibe Screen Dev")
        replace_mock.assert_not_called()

    @staticmethod
    def metadata(
        *,
        authorities: tuple[str, ...] = ("Vibe Screen Dev", "Vibe Screen Dev Root"),
        signature: str | None = None,
    ) -> macos_dev_host.SigningMetadata:
        requirement = (
            'identifier "dev.telemachus.display" and certificate leaf = '
            'H"9aae572bf6d764e3436a6109197d345b5a87998c"'
        )
        return macos_dev_host.SigningMetadata(
            app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            identifier="dev.telemachus.display",
            binary_sha256="aa1cdba1d65b8a4ed7e9376fcd329b3c8dbb6e635dbf61f1c1b61af727fb592d",
            authorities=authorities,
            cdhash="e4ac7dab68720d647550f2e031f40070ab291e8b",
            designated_requirement=requirement,
            signature=signature,
            team_identifier=None,
            leaf_certificate_hash="9AAE572BF6D764E3436A6109197D345B5A87998C",
        )


class MacOSDevHostTCCTests(unittest.TestCase):
    def test_tcc_database_paths_includes_system_database_for_default_user_database(self) -> None:
        paths = macos_dev_host.tcc_database_paths(macos_dev_host.default_tcc_database())

        self.assertEqual(paths[0], macos_dev_host.default_tcc_database().resolve())
        self.assertIn(macos_dev_host.SYSTEM_TCC_DATABASE, paths)

    def test_tcc_database_paths_honors_explicit_test_database(self) -> None:
        explicit = Path("/tmp/test-tcc.db")

        self.assertEqual(macos_dev_host.tcc_database_paths(explicit), (explicit.resolve(),))

    def test_query_tcc_rows_uses_read_only_database_and_permission_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "TCC.db"
            self.write_tcc_database(
                database_path,
                [
                    ("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 10),
                    ("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 11),
                    ("kTCCServiceAccessibility", "other.bundle", 0, 0, 4, 12),
                ],
            )

            status = macos_dev_host.query_tcc_rows("dev.telemachus.display", database_path)

            self.assertTrue(status.readable)
            self.assertEqual(len(status.rows), 2)
            self.assertTrue(status.is_allowed(macos_dev_host.SCREEN_CAPTURE_SERVICES))
            self.assertTrue(status.is_allowed((macos_dev_host.ACCESSIBILITY_SERVICE,)))

    def test_query_tcc_rows_combines_multiple_read_only_databases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            user_database = root / "user.db"
            system_database = root / "system.db"
            self.write_tcc_database(
                user_database,
                [("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 10)],
            )
            self.write_tcc_database(
                system_database,
                [("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 11)],
            )

            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                (user_database, system_database),
            )

            self.assertTrue(status.readable)
            self.assertEqual(len(status.rows), 2)
            self.assertTrue(status.is_allowed(macos_dev_host.SCREEN_CAPTURE_SERVICES))
            self.assertTrue(status.is_allowed((macos_dev_host.ACCESSIBILITY_SERVICE,)))

    def test_query_tcc_rows_fails_closed_when_database_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                Path(temporary_directory) / "missing-TCC.db",
            )

        self.assertFalse(status.readable)
        self.assertIn("TCC database not found", status.error or "")

    def test_query_tcc_rows_reports_partial_read_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            readable_database = root / "system.db"
            missing_database = root / "missing-user.db"
            self.write_tcc_database(
                readable_database,
                [
                    ("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 10),
                    ("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 11),
                ],
            )

            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                (missing_database, readable_database),
            )

        self.assertTrue(status.readable)
        self.assertIn("TCC database not found", status.error or "")
        self.assertIn("read warning", macos_dev_host.permission_interpretation(status))
        errors = macos_dev_host.validate_preflight(
            MacOSDevHostMetadataTests.metadata(),
            status,
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
        )
        joined_errors = "\n".join(errors)
        self.assertIn("cannot fully verify TCC permissions read-only", joined_errors)
        self.assertNotIn("Screen Recording is not authorized", joined_errors)
        self.assertNotIn("Accessibility is not authorized", joined_errors)

    def test_query_tcc_database_accepts_schema_without_optional_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "TCC.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE access(
                      service TEXT,
                      client TEXT,
                      client_type INTEGER,
                      auth_value INTEGER
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO access VALUES (?, ?, ?, ?)",
                    ("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2),
                )
                connection.commit()
            finally:
                connection.close()

            status = macos_dev_host.query_tcc_database("dev.telemachus.display", database_path)

        self.assertTrue(status.readable)
        self.assertEqual(len(status.rows), 1)
        self.assertEqual(status.rows[0].auth_value, 2)
        self.assertIsNone(status.rows[0].auth_reason)
        self.assertIsNone(status.rows[0].last_modified)

    def test_query_tcc_database_times_out_instead_of_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "TCC.db"
            database_path.write_bytes(b"placeholder")
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

            with mock.patch.object(macos_dev_host.multiprocessing, "get_context", return_value=FakeContext()):
                status = macos_dev_host.query_tcc_database(
                    "dev.telemachus.display",
                    database_path,
                    timeout_seconds=0.01,
                )

        self.assertFalse(status.readable)
        self.assertIn("timed out", status.error or "")
        self.assertTrue(queues[0].closed)
        self.assertTrue(queues[0].joined)

    def test_query_tcc_database_reports_exited_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "TCC.db"
            database_path.write_bytes(b"placeholder")

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

            with mock.patch.object(macos_dev_host.multiprocessing, "get_context", return_value=FakeContext()):
                status = macos_dev_host.query_tcc_database(
                    "dev.telemachus.display",
                    database_path,
                    timeout_seconds=0.01,
                )

        self.assertFalse(status.readable)
        self.assertIn("exited without a result (exit 0)", status.error or "")

    def test_query_tcc_database_preserves_worker_exception_detail(self) -> None:
        queue_instance = mock.Mock()
        with mock.patch.object(
            macos_dev_host,
            "_query_tcc_database_direct",
            side_effect=RuntimeError("simulated worker failure"),
        ):
            macos_dev_host._query_tcc_database_worker(queue_instance, "dev.telemachus.display", Path("TCC.db"))

        queue_instance.put.assert_called_once()
        status, payload = queue_instance.put.call_args.args[0]
        self.assertEqual(status, "error")
        self.assertIn("RuntimeError('simulated worker failure')", payload)

    @staticmethod
    def write_tcc_database(path: Path, rows: list[tuple[str, str, int, int, int, int]]) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                CREATE TABLE access(
                  service TEXT,
                  client TEXT,
                  client_type INTEGER,
                  auth_value INTEGER,
                  auth_reason INTEGER,
                  last_modified INTEGER
                )
                """
            )
            connection.executemany("INSERT INTO access VALUES (?, ?, ?, ?, ?, ?)", rows)
            connection.commit()
        finally:
            connection.close()


class MacOSDevHostInstallTests(unittest.TestCase):
    def test_require_expected_bundle_rejects_bundle_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Wrong.app"
            self.write_app(app, executable=b"binary", bundle_id="wrong.bundle")

            with self.assertRaisesRegex(SystemExit, "expected 'dev.telemachus.display'"):
                macos_dev_host.require_expected_bundle(app, macos_dev_host.EXPECTED_BUNDLE_ID)

    def test_safe_replace_app_preserves_existing_app_when_staging_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            self.write_app(install, executable=b"old")

            with mock.patch.object(
                macos_dev_host,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["codesign"]),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    macos_dev_host.safe_replace_app(source, install, macos_dev_host.EXPECTED_BUNDLE_ID)

            self.assertEqual((install / "Contents/MacOS/Vibe Screen").read_bytes(), b"old")

    def test_safe_replace_app_restores_existing_app_when_final_rename_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            self.write_app(install, executable=b"old")
            original_rename = Path.rename

            def rename_or_fail(path: Path, target: Path) -> Path:
                if path.name.startswith(".Vibe Screen.app.installing-"):
                    raise OSError("simulated final rename failure")
                return original_rename(path, target)

            with (
                mock.patch.object(macos_dev_host, "run", return_value=""),
                mock.patch.object(Path, "rename", rename_or_fail),
            ):
                with self.assertRaisesRegex(OSError, "simulated final rename failure"):
                    macos_dev_host.safe_replace_app(source, install, macos_dev_host.EXPECTED_BUNDLE_ID)

            self.assertEqual((install / "Contents/MacOS/Vibe Screen").read_bytes(), b"old")

    @staticmethod
    def write_app(path: Path, *, executable: bytes, bundle_id: str = macos_dev_host.EXPECTED_BUNDLE_ID) -> None:
        contents = path / "Contents"
        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as plist_file:
            plistlib.dump(
                {
                    "CFBundleIdentifier": bundle_id,
                    "CFBundleExecutable": "Vibe Screen",
                },
                plist_file,
            )
        (macos / "Vibe Screen").write_bytes(executable)


if __name__ == "__main__":
    unittest.main()
