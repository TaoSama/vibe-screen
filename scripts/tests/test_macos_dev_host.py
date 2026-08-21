from __future__ import annotations

import plistlib
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
        self.assertIn("Source commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", report)
        self.assertIn("Expected source commit: not checked", report)
        self.assertIn("Source match policy: fail-closed", report)
        self.assertIn("Certificate SHA-1: 9AAE572BF6D764E3436A6109197D345B5A87998C", report)
        self.assertIn("CDHash: e4ac7dab68720d647550f2e031f40070ab291e8b", report)
        self.assertIn("kTCCServiceAccessibility|dev.telemachus.display|0|0|4|1786811429", report)
        self.assertIn("Status: FAIL", report)
        self.assertIn("System Settings -> Privacy & Security", report)
        self.assertIn("Required remediation", report)
        self.assertIn("security find-identity -v -p codesigning", report)

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

    def test_missing_identity_error_removes_ad_hoc_escape_hatch(self) -> None:
        original = (
            "codesign identity 'Vibe Screen Dev' not found in the keychain. "
            "Create the 'Vibe Screen Dev' self-signed identity (or set "
            "$VIBE_SCREEN_SIGN_IDENTITY to an existing identity), or pass "
            "'--sign-identity -' for an ad-hoc build. Ad-hoc signing changes "
            "the code-signing hash on every rebuild and invalidates macOS "
            "Screen Recording/Accessibility grants."
        )
        with mock.patch.object(
            macos_dev_host.package_macos,
            "resolve_sign_identity",
            side_effect=SystemExit(original),
        ):
            errors = macos_dev_host.collect_signing_identity_errors("Vibe Screen Dev")

        joined = "\n".join(errors)
        self.assertIn("codesign identity 'Vibe Screen Dev' not found", joined)
        self.assertIn("Ad-hoc signing is not allowed for local device reruns", joined)
        self.assertNotIn("or pass '--sign-identity -'", joined)

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

    def test_validate_preflight_rejects_missing_or_stale_source_identity(self) -> None:
        expected = macos_dev_host.package_macos.SourceIdentity(
            commit="b" * 40,
            tree="c" * 40,
            dirty=False,
        )

        missing_errors = macos_dev_host.validate_source_identity(
            self.metadata(source_commit=None, source_tree=None, source_dirty=None),
            expected,
        )
        self.assertIn("does not record its source commit/tree identity", "\n".join(missing_errors))

        stale_errors = macos_dev_host.validate_source_identity(
            self.metadata(source_commit="a" * 40, source_tree="d" * 40, source_dirty=True),
            expected,
        )
        joined = "\n".join(stale_errors)
        self.assertIn("was packaged from a dirty source tree", joined)
        self.assertIn("does not match current HEAD", joined)
        self.assertIn("does not match current tree", joined)

    def test_validate_preflight_allows_source_mismatch_when_explicitly_requested(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(source_commit="a" * 40),
            macos_dev_host.PermissionStatus(
                database_path=Path("TCC.db"),
                readable=True,
                rows=(
                    macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
                    macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
                ),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            expected_source=macos_dev_host.package_macos.SourceIdentity(
                commit="b" * 40,
                tree="c" * 40,
                dirty=False,
            ),
            allow_source_mismatch=True,
        )

        self.assertEqual(errors, [])

    def test_preflight_command_records_ad_hoc_blocker_with_bundle_and_tcc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="-",
                tcc_db=Path("TCC.db"),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
                mock.patch.object(
                    macos_dev_host,
                    "query_tcc_rows",
                    return_value=macos_dev_host.PermissionStatus(
                        database_path=Path("TCC.db"),
                        readable=True,
                        rows=(
                            macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
                            macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
                        ),
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "current_source_identity",
                    return_value=macos_dev_host.package_macos.SourceIdentity(
                        commit="a" * 40,
                        tree="b" * 40,
                        dirty=False,
                    ),
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.preflight_command(args)

            self.assertEqual(result, 2)
            self.assertIn("refusing --sign-identity -", report.read_text(encoding="utf-8"))

    def test_collect_signing_identity_errors_reports_missing_identity(self) -> None:
        with mock.patch.object(
            macos_dev_host.package_macos,
            "resolve_sign_identity",
            side_effect=SystemExit("missing identity"),
        ):
            self.assertEqual(macos_dev_host.collect_signing_identity_errors("Missing Dev"), ["missing identity"])

    def test_preflight_command_refuses_nondefault_path_before_reading_bundle_or_tcc(self) -> None:
        args = mock.Mock(
            install_path=Path("/tmp/Vibe Screen.app"),
            sign_identity="Vibe Screen Dev",
            tcc_db=Path("TCC.db"),
            report=Path("report.txt"),
            source_root=Path("."),
            allow_source_mismatch=False,
        )
        with (
            mock.patch.object(macos_dev_host, "collect_signing_metadata") as metadata_mock,
            mock.patch.object(macos_dev_host, "query_tcc_rows") as tcc_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "nonstandard install path"):
                macos_dev_host.preflight_command(args)
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
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host.package_macos, "resolve_sign_identity"),
                mock.patch.object(
                    macos_dev_host,
                    "current_source_identity",
                    return_value=macos_dev_host.package_macos.SourceIdentity(
                        commit="a" * 40,
                        tree="b" * 40,
                        dirty=False,
                    ),
                ),
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

    def test_preflight_command_resolves_configured_identity_before_reading_bundle(self) -> None:
        args = mock.Mock(
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            sign_identity="Missing Dev",
            tcc_db=Path("TCC.db"),
            report=Path("report.txt"),
            source_root=Path("."),
            allow_source_mismatch=False,
        )
        with (
            mock.patch.object(
                macos_dev_host.package_macos,
                "resolve_sign_identity",
                side_effect=SystemExit("missing identity"),
            ) as resolve_mock,
            mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()) as metadata_mock,
            mock.patch.object(
                macos_dev_host,
                "query_tcc_rows",
                return_value=macos_dev_host.PermissionStatus(Path("TCC.db"), (), True),
            ) as tcc_mock,
            mock.patch.object(
                macos_dev_host,
                "current_source_identity",
                return_value=macos_dev_host.package_macos.SourceIdentity(
                    commit="a" * 40,
                    tree="b" * 40,
                    dirty=False,
                ),
            ),
            mock.patch.object(macos_dev_host, "write_report"),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            result = macos_dev_host.preflight_command(args)
        resolve_mock.assert_called_once_with("Missing Dev")
        metadata_mock.assert_called_once()
        tcc_mock.assert_called_once()
        self.assertEqual(result, 2)

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
            source_root=Path("."),
            allow_source_mismatch=False,
        )
        with (
            mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")),
            mock.patch.object(macos_dev_host, "safe_replace_app"),
            mock.patch.object(
                macos_dev_host,
                "current_source_identity",
                return_value=macos_dev_host.package_macos.SourceIdentity(
                    commit="a" * 40,
                    tree="b" * 40,
                    dirty=False,
                ),
            ),
            mock.patch.object(
                macos_dev_host,
                "metadata_and_permissions",
                return_value=(
                    self.metadata(),
                    macos_dev_host.PermissionStatus(Path("TCC.db"), (), True),
                    macos_dev_host.package_macos.SourceIdentity(
                        commit="a" * 40,
                        tree="b" * 40,
                        dirty=False,
                    ),
                    [],
                ),
            ) as metadata_mock,
            mock.patch.object(macos_dev_host, "write_report"),
            redirect_stdout(StringIO()),
        ):
            macos_dev_host.install_command(args)
        metadata_mock.assert_called_once_with(
            macos_dev_host.DEFAULT_INSTALL_PATH,
            Path("TCC.db"),
            expected_sign_identity="Vibe Screen Dev",
            source_root=Path("."),
            allow_source_mismatch=False,
        )

    @staticmethod
    def metadata(
        *,
        authorities: tuple[str, ...] = ("Vibe Screen Dev", "Vibe Screen Dev Root"),
        signature: str | None = None,
        source_commit: str | None = "a" * 40,
        source_tree: str | None = "b" * 40,
        source_dirty: bool | None = False,
    ) -> macos_dev_host.SigningMetadata:
        requirement = (
            'identifier "dev.telemachus.display" and certificate leaf = '
            'H"9aae572bf6d764e3436a6109197d345b5a87998c"'
        )
        return macos_dev_host.SigningMetadata(
            app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            identifier="dev.telemachus.display",
            source_commit=source_commit,
            source_tree=source_tree,
            source_dirty=source_dirty,
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


class MacOSDevHostXCTestToolchainTests(unittest.TestCase):
    def test_collect_xctest_toolchain_status_rejects_command_line_tools(self) -> None:
        def fake_command_status(*command: str) -> tuple[int, str]:
            responses = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Library/Developer/CommandLineTools"),
                ("/usr/bin/xcrun", "--find", "swift"): (0, "/Library/Developer/CommandLineTools/usr/bin/swift"),
                ("/usr/bin/swift", "--version"): (0, "Apple Swift version 6.3.3\nTarget: arm64-apple-macosx26.0"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (1, "xcrun: error: unable to find utility \"xcodebuild\""),
                ("/usr/bin/xcodebuild", "-version"): (1, "xcode-select: error: tool 'xcodebuild' requires Xcode"),
                ("/usr/bin/xcrun", "--find", "xctest"): (1, "xcrun: error: unable to find utility \"xctest\""),
            }
            return responses[command]

        with mock.patch.object(macos_dev_host, "command_status", side_effect=fake_command_status):
            status = macos_dev_host.collect_xctest_toolchain_status()

        joined = "\n".join(status.errors)
        self.assertIn("Command Line Tools", joined)
        self.assertIn("xcrun --find xcodebuild failed", joined)
        self.assertIn("xcrun --find xctest failed", joined)
        self.assertIn("XCTest.framework not found", joined)
        report = macos_dev_host.format_xctest_toolchain_report(status)
        self.assertIn("Status: FAIL", report)
        self.assertIn("XCTest.framework: missing", report)
        self.assertIn("sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer", report)

    def test_collect_xctest_toolchain_status_accepts_full_xcode(self) -> None:
        def fake_command_status(*command: str) -> tuple[int, str]:
            responses = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Applications/Xcode.app/Contents/Developer"),
                ("/usr/bin/xcrun", "--find", "swift"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift",
                ),
                ("/usr/bin/swift", "--version"): (0, "Apple Swift version 6.3\nTarget: arm64-apple-macosx26.0"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild"),
                ("/usr/bin/xcodebuild", "-version"): (0, "Xcode 26.0\nBuild version 17A000"),
                ("/usr/bin/xcrun", "--find", "xctest"): (0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xctest"),
            }
            return responses[command]

        with (
            mock.patch.object(macos_dev_host, "command_status", side_effect=fake_command_status),
            mock.patch.object(
                macos_dev_host,
                "find_xctest_framework_path",
                return_value="/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/Library/Frameworks/XCTest.framework",
            ),
        ):
            status = macos_dev_host.collect_xctest_toolchain_status()

        self.assertEqual(status.errors, ())
        self.assertIn("Status: PASS", macos_dev_host.format_xctest_toolchain_report(status))
        self.assertIn("XCTest.framework", macos_dev_host.format_xctest_toolchain_report(status))

    def test_collect_xctest_toolchain_status_warns_about_path_xcrun_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            wrapper = Path(temporary_directory) / "xcrun"
            wrapper.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

            with mock.patch.dict("os.environ", {"PATH": f"{temporary_directory}:/usr/bin"}):
                warning = macos_dev_host.detect_path_xcrun_wrapper()

        self.assertIsNotNone(warning)
        self.assertIn("preflight uses /usr/bin/xcrun", warning or "")

    def test_xctest_preflight_command_writes_report_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest.txt"
            args = mock.Mock(report=report)
            status = macos_dev_host.XCTestToolchainStatus(
                developer_dir="/Library/Developer/CommandLineTools",
                swift_path="/Library/Developer/CommandLineTools/usr/bin/swift",
                swift_version="Apple Swift version 6.3.3",
                xcodebuild_path=None,
                xcodebuild_version=None,
                xctest_path=None,
                xctest_framework_path=None,
                path_xcrun_warning=None,
                errors=("active developer directory is Command Line Tools",),
            )
            with (
                mock.patch.object(macos_dev_host, "collect_xctest_toolchain_status", return_value=status),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Status: FAIL", report.read_text(encoding="utf-8"))


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
