from __future__ import annotations

import argparse
import json
import plistlib
import queue
import re
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

TEST_PRIVACY_DATABASE = Path("privacy.db")


PRIVACY_DB_FILENAME = "privacy.sqlite"
SOURCE_COMMIT = "a" * 40
SOURCE_TREE = "b" * 40


def allowed_tcc_rows() -> tuple[macos_dev_host.TCCRow, ...]:
    return (
        macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
        macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
        macos_dev_host.TCCRow("kTCCServiceMicrophone", "dev.telemachus.display", 0, 2, 4, 3),
    )


def source_identity(
    *,
    commit: str = SOURCE_COMMIT,
    tree: str = SOURCE_TREE,
    dirty: bool = False,
) -> macos_dev_host.package_macos.SourceIdentity:
    return macos_dev_host.package_macos.SourceIdentity(commit=commit, tree=tree, dirty=dirty)


class MacOSDevHostMetadataTests(unittest.TestCase):
    def test_run_best_effort_reports_missing_executable(self) -> None:
        with mock.patch.object(macos_dev_host.subprocess, "run", side_effect=FileNotFoundError("/missing/vibe-screen-tool")):
            exit_code, output = macos_dev_host.run_best_effort("/missing/vibe-screen-tool")

        self.assertEqual(exit_code, 127)
        self.assertIn("command unavailable", output)
        self.assertIn("vibe-screen-tool", output)

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

    def test_designated_requirement_parser_accepts_root_certificate_hash(self) -> None:
        requirement = macos_dev_host.parse_designated_requirement(
            'designated => identifier "dev.telemachus.display" and certificate root = H"9aae572bf6d764e3436a6109197d345b5a87998c"\n'
        )

        self.assertEqual(
            macos_dev_host.parse_leaf_certificate_hash(requirement),
            "9AAE572BF6D764E3436A6109197D345B5A87998C",
        )

    def test_validate_preflight_rejects_wrong_root_certificate_hash(self) -> None:
        metadata = self.metadata()
        metadata = macos_dev_host.SigningMetadata(
            app_path=metadata.app_path,
            identifier=metadata.identifier,
            source_commit=metadata.source_commit,
            source_tree=metadata.source_tree,
            source_dirty=metadata.source_dirty,
            binary_sha256=metadata.binary_sha256,
            authorities=metadata.authorities,
            cdhash=metadata.cdhash,
            designated_requirement=(
                'identifier "dev.telemachus.display" and certificate root = '
                'H"B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"'
            ),
            signature=metadata.signature,
            team_identifier=metadata.team_identifier,
            leaf_certificate_hash=macos_dev_host.parse_leaf_certificate_hash(
                'identifier "dev.telemachus.display" and certificate root = '
                'H"B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"'
            ),
        )

        errors = macos_dev_host.validate_preflight(
            metadata,
            macos_dev_host.PermissionStatus(
                database_path=TEST_PRIVACY_DATABASE,
                rows=(
                    macos_dev_host.TCCRow(
                        service=macos_dev_host.SCREEN_CAPTURE_SERVICES[0],
                        client=macos_dev_host.EXPECTED_BUNDLE_ID,
                        client_type=0,
                        auth_value=macos_dev_host.ALLOWED_AUTH_VALUE,
                        auth_reason=None,
                        last_modified=None,
                    ),
                    macos_dev_host.TCCRow(
                        service=macos_dev_host.ACCESSIBILITY_SERVICE,
                        client=macos_dev_host.EXPECTED_BUNDLE_ID,
                        client_type=0,
                        auth_value=macos_dev_host.ALLOWED_AUTH_VALUE,
                        auth_reason=None,
                        last_modified=None,
                    ),
                ),
                readable=True,
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
        )

        self.assertIn(
            "Host signing leaf SHA-1 is 'B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'",
            "\n".join(errors),
        )

    def test_validate_preflight_rejects_malformed_certificate_requirement(self) -> None:
        metadata = self.metadata()
        metadata = macos_dev_host.SigningMetadata(
            app_path=metadata.app_path,
            identifier=metadata.identifier,
            source_commit=metadata.source_commit,
            source_tree=metadata.source_tree,
            source_dirty=metadata.source_dirty,
            binary_sha256=metadata.binary_sha256,
            authorities=metadata.authorities,
            cdhash=metadata.cdhash,
            designated_requirement='identifier "dev.telemachus.display" and certificate root = H"not-a-sha1"',
            signature=metadata.signature,
            team_identifier=metadata.team_identifier,
            leaf_certificate_hash=macos_dev_host.parse_leaf_certificate_hash(
                'identifier "dev.telemachus.display" and certificate root = H"not-a-sha1"'
            ),
        )

        errors = macos_dev_host.validate_preflight(
            metadata,
            macos_dev_host.PermissionStatus(
                database_path=TEST_PRIVACY_DATABASE,
                rows=(
                    macos_dev_host.TCCRow(
                        service=macos_dev_host.SCREEN_CAPTURE_SERVICES[0],
                        client=macos_dev_host.EXPECTED_BUNDLE_ID,
                        client_type=0,
                        auth_value=macos_dev_host.ALLOWED_AUTH_VALUE,
                        auth_reason=None,
                        last_modified=None,
                    ),
                    macos_dev_host.TCCRow(
                        service=macos_dev_host.ACCESSIBILITY_SERVICE,
                        client=macos_dev_host.EXPECTED_BUNDLE_ID,
                        client_type=0,
                        auth_value=macos_dev_host.ALLOWED_AUTH_VALUE,
                        auth_reason=None,
                        last_modified=None,
                    ),
                ),
                readable=True,
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
        )

        self.assertIn("Host signing leaf SHA-1 is 'missing'", "\n".join(errors))

    def test_run_best_effort_reports_missing_command(self) -> None:
        exit_code, output = macos_dev_host.run_best_effort(
            "/definitely/missing/vibe-screen-tool"
        )

        self.assertEqual(exit_code, 127)
        self.assertEqual(output, "command unavailable: vibe-screen-tool")
        self.assertNotIn("/definitely/missing/vibe-screen-tool", output)

    def test_signing_prerequisite_report_uses_shared_device_evidence_wording(self) -> None:
        report = macos_dev_host.format_signing_prerequisite_report(
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            sign_identity="Vibe Screen Dev",
            error="codesign identity not found",
        )

        self.assertIn("before rerunning device evidence", report)
        self.assertNotIn("touch evidence", report)

    def test_xctest_preflight_command_passes_with_full_xcode_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)
            command_outputs = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Applications/Xcode.app/Contents/Developer"),
                ("/usr/bin/xcrun", "--find", "swift"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift",
                ),
                ("/usr/bin/swift", "--version"): (0, "Swift version 6.0"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild",
                ),
                ("/usr/bin/xcodebuild", "-version"): (0, "Xcode 16.4\nBuild version 16F6"),
                ("/usr/bin/xcrun", "--find", "xctest"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/usr/bin/xctest",
                ),
            }

            with (
                mock.patch.object(
                    macos_dev_host,
                    "run_best_effort",
                    side_effect=lambda *command, timeout_seconds=None: command_outputs[command],
                ),
                mock.patch.object(macos_dev_host, "has_xctest_framework", return_value=True),
                redirect_stdout(StringIO()) as stdout,
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            self.assertEqual(result, 0)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Status: PASS", report_text)
            self.assertIn("xcodebuild -version: exit_code=0", report_text)
            self.assertIn("macOS Host XCTest toolchain preflight passed", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_xctest_preflight_command_blocks_missing_xctest_framework(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)
            command_outputs = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Applications/Xcode.app/Contents/Developer"),
                ("/usr/bin/xcrun", "--find", "swift"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift",
                ),
                ("/usr/bin/swift", "--version"): (0, "Swift version 6.0"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (
                    0,
                    "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild",
                ),
                ("/usr/bin/xcodebuild", "-version"): (0, "Xcode 16.4\nBuild version 16F6"),
            }

            with (
                mock.patch.object(
                    macos_dev_host,
                    "run_best_effort",
                    side_effect=lambda *command, timeout_seconds=None: command_outputs[command],
                ),
                mock.patch.object(macos_dev_host, "has_xctest_framework", return_value=False),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            self.assertEqual(result, 2)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("XCTest.framework present: false", report_text)
            self.assertIn("XCTest.framework was not found", report_text)
            self.assertIn("XCTest.framework was not found", stderr.getvalue())

    def test_xctest_preflight_command_blocks_command_line_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)
            command_outputs = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Library/Developer/CommandLineTools"),
                ("/usr/bin/xcrun", "--find", "swift"): (0, "/usr/bin/swift"),
                ("/usr/bin/swift", "--version"): (0, "Swift version 6.0"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (72, "unable to find utility xcodebuild"),
                ("/usr/bin/xcodebuild", "-version"): (127, "command unavailable: /usr/bin/xcodebuild"),
                ("/usr/bin/xcrun", "--find", "xctest"): (72, "unable to find utility xctest"),
            }

            with (
                mock.patch.object(
                    macos_dev_host,
                    "run_best_effort",
                    side_effect=lambda *command, timeout_seconds=None: command_outputs[command],
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            self.assertEqual(result, 2)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("full Xcode is not selected", report_text)
            self.assertIn("xcodebuild is not available", report_text)
            self.assertIn("Command Line Tools cannot run this XCTest suite", stderr.getvalue())

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
        self.assertIn("Source commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", report)
        self.assertIn("Source tree: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", report)
        self.assertIn("kTCCServiceAccessibility|dev.telemachus.display|0|0|4|1786811429", report)
        self.assertIn("Microphone not allowed", report)
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
        self.assertIn("Microphone is not authorized", "\n".join(errors))

    def test_refuse_ad_hoc_identity_for_local_install(self) -> None:
        with self.assertRaisesRegex(SystemExit, "stable signing identity"):
            macos_dev_host.refuse_ad_hoc_identity("-")

    def test_run_best_effort_reports_missing_command_without_raising(self) -> None:
        with mock.patch.object(
            subprocess,
            "run",
            side_effect=FileNotFoundError(2, "No such file or directory", "/usr/bin/defaults"),
        ):
            exit_code, output = macos_dev_host.run_best_effort("/usr/bin/defaults", "export")

        self.assertEqual(exit_code, 127)
        self.assertEqual(output, "command unavailable: defaults")

    def test_validate_preflight_rejects_unexpected_named_identity(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(authorities=("Other Dev",)),
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            expected_sign_identity="Vibe Screen Dev",
        )

        self.assertIn("expected configured identity", "\n".join(errors))

    def test_validate_preflight_rejects_wrong_signing_leaf_sha1(self) -> None:
        metadata = self.metadata()
        metadata = macos_dev_host.SigningMetadata(
            app_path=metadata.app_path,
            identifier=metadata.identifier,
            source_commit=metadata.source_commit,
            source_tree=metadata.source_tree,
            source_dirty=metadata.source_dirty,
            binary_sha256=metadata.binary_sha256,
            authorities=metadata.authorities,
            cdhash=metadata.cdhash,
            designated_requirement=(
                'identifier "dev.telemachus.display" and certificate leaf = '
                'H"0123456789abcdef0123456789abcdef01234567"'
            ),
            signature=metadata.signature,
            team_identifier=metadata.team_identifier,
            leaf_certificate_hash="0123456789ABCDEF0123456789ABCDEF01234567",
        )
        errors = macos_dev_host.validate_preflight(
            metadata,
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            expected_sign_identity="Vibe Screen Dev",
        )

        self.assertIn("Host signing leaf SHA-1", "\n".join(errors))
        self.assertIn(macos_dev_host.EXPECTED_SIGNING_LEAF_SHA1, "\n".join(errors))

    def test_validate_preflight_accepts_pinned_sha1_config_without_name_match(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(authorities=("Vibe Screen Dev Renamed",)),
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            expected_sign_identity=macos_dev_host.EXPECTED_SIGNING_LEAF_SHA1,
        )

        self.assertEqual(errors, [])

    def test_validate_preflight_rejects_source_mismatch(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(source_commit="c" * 40),
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
        )

        self.assertIn("installed Host source provenance does not match", "\n".join(errors))

    def test_validate_preflight_rejects_dirty_current_source(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(),
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=True,
            ),
        )

        self.assertIn("source repository is dirty", "\n".join(errors))

    def test_validate_preflight_allows_historical_source_mismatch_escape_hatch(self) -> None:
        errors = macos_dev_host.validate_preflight(
            self.metadata(source_commit="c" * 40, source_dirty=True),
            macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=True,
            ),
            allow_source_mismatch=True,
        )

        self.assertEqual(errors, [])

    def test_installable_host_bundle_accepts_current_clean_pinned_leaf_bundle(self) -> None:
        errors = macos_dev_host.validate_installable_host_bundle(
            self.metadata(),
            expected_sign_identity="Vibe Screen Dev",
            source_identity=source_identity(),
        )

        self.assertEqual(errors, [])

    def test_installable_host_bundle_rejects_dirty_or_missing_source_provenance(self) -> None:
        scenarios = (
            (
                "missing current source",
                self.metadata(),
                None,
                "current source identity is unavailable",
            ),
            (
                "current source repository is dirty",
                self.metadata(),
                source_identity(dirty=True),
                "source repository is dirty",
            ),
            (
                "packaged from dirty source",
                self.metadata(source_dirty=True),
                source_identity(),
                "packaged from a dirty source tree",
            ),
            (
                "missing source commit",
                self.metadata(source_commit=None),
                source_identity(),
                "lacks source commit/tree provenance",
            ),
            (
                "source commit mismatch",
                self.metadata(source_commit="c" * 40),
                source_identity(),
                "source provenance does not match",
            ),
        )
        for label, metadata, current_source, expected in scenarios:
            with self.subTest(label=label):
                errors = macos_dev_host.validate_installable_host_bundle(
                    metadata,
                    expected_sign_identity="Vibe Screen Dev",
                    source_identity=current_source,
                )

                self.assertIn(expected, "\n".join(errors))

    def test_installable_host_bundle_rejects_ad_hoc_wrong_leaf_and_missing_codesign_fields(self) -> None:
        scenarios = (
            (
                "ad-hoc",
                self.metadata(authorities=(), signature="adhoc", leaf_certificate_hash=None),
                "Host is ad-hoc signed",
            ),
            (
                "wrong leaf",
                self.metadata(leaf_certificate_hash="0123456789ABCDEF0123456789ABCDEF01234567"),
                "Host signing leaf SHA-1",
            ),
            (
                "missing cdhash",
                self.metadata(cdhash=None),
                "codesign CDHash is missing",
            ),
            (
                "missing designated requirement",
                self.metadata(designated_requirement="", leaf_certificate_hash=None),
                "codesign designated requirement is missing",
            ),
        )
        for label, metadata, expected in scenarios:
            with self.subTest(label=label):
                errors = macos_dev_host.validate_installable_host_bundle(
                    metadata,
                    expected_sign_identity="Vibe Screen Dev",
                    source_identity=source_identity(),
                )

                self.assertIn(expected, "\n".join(errors))

    def test_preflight_command_reports_ad_hoc_blocker_before_reading_bundle_or_tcc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="-",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
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
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host.package_macos, "resolve_sign_identity"),
                mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
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
                    "query_tcc_rows",
                    return_value=macos_dev_host.PermissionStatus(
                        database_path=Path(PRIVACY_DB_FILENAME),
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
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.preflight_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Accessibility is not authorized", report.read_text(encoding="utf-8"))
            self.assertIn("macOS Host preflight failed", stderr.getvalue())

    def test_preflight_command_records_missing_configured_identity_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Missing Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
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
                        database_path=Path(PRIVACY_DB_FILENAME),
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
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result, 2)
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("missing identity", report_text)
            self.assertIn("Configured identity: Missing Dev", report_text)
        resolve_mock.assert_called_once_with("Missing Dev")
        metadata_mock.assert_not_called()
        tcc_mock.assert_not_called()

    def test_preflight_command_records_metadata_inspection_error_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Missing Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(
                    macos_dev_host.package_macos,
                    "resolve_sign_identity",
                    return_value="Missing Dev",
                ) as resolve_mock,
                mock.patch.object(
                    macos_dev_host,
                    "collect_signing_metadata",
                    side_effect=SystemExit("Host bundle not found"),
                ) as metadata_mock,
                mock.patch.object(
                    macos_dev_host,
                    "current_source_identity",
                    return_value=macos_dev_host.package_macos.SourceIdentity(
                        commit="a" * 40,
                        tree="b" * 40,
                        dirty=False,
                    ),
                ),
                mock.patch.object(macos_dev_host, "query_tcc_rows") as tcc_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.preflight_command(args)
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(result, 2)
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("Host bundle not found", report_text)
            self.assertIn("Verification: not inspected", report_text)
            self.assertNotIn("Traceback", report_text)
        resolve_mock.assert_called_once_with("Missing Dev")
        metadata_mock.assert_called_once_with(macos_dev_host.DEFAULT_INSTALL_PATH)
        tcc_mock.assert_not_called()

    def test_xctest_preflight_passes_with_full_xcode_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)

            def fake_run(*command: str, timeout_seconds: int | None = None) -> tuple[int, str]:
                del timeout_seconds
                if command == ("/usr/bin/xcode-select", "-p"):
                    return 0, "/Applications/Xcode.app/Contents/Developer"
                if command == ("/usr/bin/xcrun", "--find", "swift"):
                    return 0, "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift"
                if command == ("/usr/bin/xcrun", "--find", "xcodebuild"):
                    return 0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild"
                if command == ("/usr/bin/xcodebuild", "-version"):
                    return 0, "Xcode 16.4\nBuild version 16F6"
                if command == ("/usr/bin/swift", "--version"):
                    return 0, "Apple Swift version 6.3.3"
                raise AssertionError(command)

            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=fake_run),
                mock.patch.object(macos_dev_host, "has_xctest_framework", return_value=True),
                redirect_stdout(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            report_text = report.read_text(encoding="utf-8")
            self.assertEqual(result, 0)
            self.assertIn("Status: PASS", report_text)
            self.assertIn("Blocking issues:\n- none", report_text)

    def test_xctest_preflight_fails_closed_for_command_line_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)

            def fake_run(*command: str, timeout_seconds: int | None = None) -> tuple[int, str]:
                del timeout_seconds
                if command == ("/usr/bin/xcode-select", "-p"):
                    return 0, "/Library/Developer/CommandLineTools"
                if command == ("/usr/bin/xcrun", "--find", "swift"):
                    return 0, "/usr/bin/swift"
                if command == ("/usr/bin/xcrun", "--find", "xcodebuild"):
                    return 1, "unable to find utility xcodebuild"
                if command == ("/usr/bin/xcodebuild", "-version"):
                    return 127, "command unavailable: /usr/bin/xcodebuild"
                if command == ("/usr/bin/swift", "--version"):
                    return 0, "Apple Swift version 6.3.3"
                raise AssertionError(command)

            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=fake_run),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            report_text = report.read_text(encoding="utf-8")
            self.assertEqual(result, 2)
            self.assertIn("Status: FAIL", report_text)
            self.assertIn("full Xcode is not selected", report_text)
            self.assertIn("xcodebuild is not available", report_text)
            self.assertIn("does not build, install, sign, modify TCC, or touch devices", report_text)

    def test_parse_args_accepts_xctest_preflight_command(self) -> None:
        with mock.patch.object(sys, "argv", ["macos_dev_host.py", "xctest-preflight"]):
            args = macos_dev_host.parse_args()

        self.assertEqual(args.command, "xctest-preflight")
        self.assertEqual(args.report, macos_dev_host.DEFAULT_XCTEST_PREFLIGHT_REPORT)

    def test_parse_args_defaults_readiness_to_skip_login_item_probe(self) -> None:
        with mock.patch.object(sys, "argv", ["macos_dev_host.py", "readiness"]):
            args = macos_dev_host.parse_args()

        self.assertEqual(args.command, "readiness")
        self.assertFalse(args.probe_login_item)

    def test_parse_args_accepts_explicit_login_item_probe_for_readiness(self) -> None:
        with mock.patch.object(sys, "argv", ["macos_dev_host.py", "readiness", "--probe-login-item"]):
            args = macos_dev_host.parse_args()

        self.assertEqual(args.command, "readiness")
        self.assertTrue(args.probe_login_item)

    def test_parse_args_accepts_legacy_login_item_diagnostic_alias(self) -> None:
        with mock.patch.object(sys, "argv", ["macos_dev_host.py", "readiness", "--include-login-item-diagnostic"]):
            args = macos_dev_host.parse_args()

        self.assertEqual(args.command, "readiness")
        self.assertTrue(args.probe_login_item)

    def test_parse_args_readiness_login_item_diagnostic_is_opt_in(self) -> None:
        for flag in (
            "--include-login-item-diagnostic",
            "--inspect-login-items",
            "--probe-login-item",
            "--probe-login-items",
        ):
            with self.subTest(flag=flag):
                with mock.patch.object(
                    sys,
                    "argv",
                    ["macos_dev_host.py", "readiness", flag],
                ):
                    args = macos_dev_host.parse_args()

                self.assertEqual(args.command, "readiness")
                self.assertTrue(args.probe_login_item)

    def test_readiness_help_warns_login_item_probe_can_prompt_for_admin(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["macos_dev_host.py", "readiness", "--help"]),
            redirect_stdout(StringIO()) as stdout,
        ):
            with self.assertRaises(SystemExit) as error:
                macos_dev_host.parse_args()

        self.assertEqual(error.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--include-login-item-diagnostic", help_text)
        self.assertIn("--inspect-login-items", help_text)
        self.assertIn("--probe-login-item", help_text)
        self.assertIn("--probe-login-items", help_text)
        self.assertIn("/usr/bin/sfltool", help_text)
        self.assertIn("dumpbtm", help_text)
        self.assertIn("administrator authorization", help_text)

    def test_read_login_item_readiness_uses_sfltool_only_inside_explicit_probe_function(self) -> None:
        with mock.patch.object(
            macos_dev_host,
            "run_best_effort",
            return_value=(0, "bundle id dev.telemachus.display allowed = 1"),
        ) as run_mock:
            readiness = macos_dev_host.read_login_item_readiness()

        self.assertEqual(readiness.state, "enabled")
        self.assertTrue(readiness.sfltool_dumpbtm_was_run)
        run_mock.assert_called_once_with("/usr/bin/sfltool", "dumpbtm", timeout_seconds=15)

    def test_read_login_item_readiness_fails_closed_when_sfltool_fails(self) -> None:
        with mock.patch.object(
            macos_dev_host,
            "run_best_effort",
            return_value=(124, "command timed out after 15s"),
        ):
            readiness = macos_dev_host.read_login_item_readiness()

        self.assertEqual(readiness.state, "unverified")
        self.assertFalse(readiness.matched)
        self.assertTrue(readiness.sfltool_dumpbtm_was_run)
        self.assertIn("command timed out", readiness.detail)

    def test_xctest_preflight_does_not_run_host_readiness_probe(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["macos_dev_host.py", "xctest-preflight"]),
            mock.patch.object(macos_dev_host, "xctest_preflight_command", return_value=0) as xctest_mock,
            mock.patch.object(macos_dev_host, "preflight_command") as preflight_mock,
            mock.patch.object(macos_dev_host, "read_login_item_readiness") as login_probe,
        ):
            result = macos_dev_host.main()

        self.assertEqual(result, 0)
        xctest_mock.assert_called_once()
        preflight_mock.assert_not_called()
        login_probe.assert_not_called()

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
            tcc_db=TEST_PRIVACY_DATABASE,
            report=Path("report.txt"),
            source_root=Path("."),
            allow_source_mismatch=False,
        )
        with (
            mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")),
            mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
            mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
            mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity()),
            mock.patch.object(
                macos_dev_host,
                "inspect_host_without_throwing",
                return_value=macos_dev_host.HostInspection(
                    metadata=self.metadata(),
                    source_identity=macos_dev_host.package_macos.SourceIdentity(
                        commit="a" * 40,
                        tree="b" * 40,
                        dirty=False,
                    ),
                    permissions=macos_dev_host.PermissionStatus(TEST_PRIVACY_DATABASE, (), True),
                    errors=[],
                ),
            ) as inspection_mock,
            mock.patch.object(macos_dev_host, "write_report"),
            redirect_stdout(StringIO()),
        ):
            macos_dev_host.install_command(args)
        replace_mock.assert_called_once_with(
            Path("built.app"),
            macos_dev_host.DEFAULT_INSTALL_PATH,
            macos_dev_host.EXPECTED_BUNDLE_ID,
            expected_sign_identity="Vibe Screen Dev",
            source_identity=source_identity(),
        )
        inspection_mock.assert_called_once_with(
            macos_dev_host.DEFAULT_INSTALL_PATH,
            TEST_PRIVACY_DATABASE,
            expected_sign_identity="Vibe Screen Dev",
            source_root=Path("."),
            allow_source_mismatch=False,
        )

    def test_install_command_returns_nonzero_for_post_install_preflight_errors_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=TEST_PRIVACY_DATABASE,
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity()),
                mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")) as package_mock,
                mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=self.metadata(),
                        source_identity=source_identity(),
                        permissions=macos_dev_host.PermissionStatus(TEST_PRIVACY_DATABASE, (), True),
                        errors=["Screen Recording is not authorized for the installed Host"],
                    ),
                ),
                redirect_stdout(StringIO()) as stdout,
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.install_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Installed", stdout.getvalue())
            self.assertIn("not ready for device evidence", stdout.getvalue())
            self.assertIn("macOS Host install preflight failed", stderr.getvalue())
            self.assertIn("Screen Recording is not authorized", report.read_text(encoding="utf-8"))
        package_mock.assert_called_once_with(Path("out"), "Vibe Screen Dev")
        replace_mock.assert_called_once()

    def test_install_command_blocks_dirty_current_source_before_packaging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=TEST_PRIVACY_DATABASE,
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity(dirty=True)),
                mock.patch.object(macos_dev_host, "package_dev_app") as package_mock,
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()) as stderr,
            ):
                result = macos_dev_host.install_command(args)

            self.assertEqual(result, 2)
            self.assertIn("source repository is dirty", report.read_text(encoding="utf-8"))
            self.assertIn("failed before replacing", stderr.getvalue())
        package_mock.assert_not_called()
        replace_mock.assert_not_called()

    def test_install_command_refuses_source_mismatch_escape_hatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=TEST_PRIVACY_DATABASE,
                report=report,
                source_root=Path("."),
                allow_source_mismatch=True,
            )
            with (
                mock.patch.object(macos_dev_host, "current_source_identity") as source_mock,
                mock.patch.object(macos_dev_host, "package_dev_app") as package_mock,
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.install_command(args)

            self.assertEqual(result, 2)
            self.assertIn("install refuses --allow-source-mismatch", report.read_text(encoding="utf-8"))
        source_mock.assert_not_called()
        package_mock.assert_not_called()
        replace_mock.assert_not_called()

    def test_install_command_blocks_packaged_wrong_leaf_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=TEST_PRIVACY_DATABASE,
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            wrong_leaf = self.metadata(leaf_certificate_hash="0123456789ABCDEF0123456789ABCDEF01234567")
            with (
                mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity()),
                mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")) as package_mock,
                mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=wrong_leaf),
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.install_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Host signing leaf SHA-1", report.read_text(encoding="utf-8"))
        package_mock.assert_called_once_with(Path("out"), "Vibe Screen Dev")
        replace_mock.assert_not_called()

    def test_install_command_records_metadata_inspection_error_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity()),
                mock.patch.object(macos_dev_host, "package_dev_app", return_value=Path("built.app")) as package_mock,
                mock.patch.object(
                    macos_dev_host,
                    "collect_signing_metadata",
                    side_effect=SystemExit("Host bundle not found"),
                ) as metadata_mock,
                mock.patch.object(macos_dev_host, "safe_replace_app") as replace_mock,
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=None,
                        source_identity=macos_dev_host.package_macos.SourceIdentity(
                            commit="c" * 40,
                            tree="d" * 40,
                            dirty=False,
                        ),
                        permissions=macos_dev_host.missing_permission_status("Host bundle signing was not inspected"),
                        errors=["Host bundle not found"],
                    ),
                ) as inspection_mock,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.install_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Status: FAIL", report.read_text(encoding="utf-8"))
            self.assertIn("Verification: not inspected", report.read_text(encoding="utf-8"))
            self.assertIn("Host bundle not found", report.read_text(encoding="utf-8"))
        package_mock.assert_called_once_with(Path("out"), "Vibe Screen Dev")
        metadata_mock.assert_called_once_with(Path("built.app"))
        replace_mock.assert_not_called()
        inspection_mock.assert_not_called()

    def test_install_command_reports_missing_signing_identity_without_installing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                output_dir=Path("out"),
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                source_root=Path("."),
                allow_source_mismatch=False,
            )
            with (
                mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity()),
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
            self.assertIn("not an Android device-identity result", " ".join(report_text.split()))
        package_mock.assert_called_once_with(Path("out"), "Vibe Screen Dev")
        replace_mock.assert_not_called()


    def test_xctest_preflight_command_passes_with_full_xcode_and_xctest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)
            calls = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Applications/Xcode.app/Contents/Developer"),
                ("/usr/bin/xcrun", "--find", "swift"): (0, "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift"),
                ("/usr/bin/swift", "--version"): (0, "Apple Swift version 6.1"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild"),
                ("/usr/bin/xcodebuild", "-version"): (0, "Xcode 16.4\nBuild version 16F6"),
                ("/usr/bin/xcrun", "--find", "xctest"): (0, "/Applications/Xcode.app/Contents/Developer/usr/bin/xctest"),
            }

            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=lambda *command, **_: calls[command]),
                mock.patch.object(macos_dev_host, "has_xctest_framework", return_value=True),
                redirect_stdout(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            report_text = report.read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertIn("Status: PASS", report_text)
        self.assertIn("Xcode 16.4", report_text)
        self.assertIn("xcodebuild -version: exit_code=0", report_text)

    def test_xctest_preflight_command_fails_closed_for_command_line_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "xctest-toolchain.txt"
            args = mock.Mock(report=report)
            calls = {
                ("/usr/bin/xcode-select", "-p"): (0, "/Library/Developer/CommandLineTools"),
                ("/usr/bin/xcrun", "--find", "swift"): (0, "/usr/bin/swift"),
                ("/usr/bin/swift", "--version"): (0, "Apple Swift version 6.1"),
                ("/usr/bin/xcrun", "--find", "xcodebuild"): (1, "unable to find utility xcodebuild"),
                ("/usr/bin/xcodebuild", "-version"): (1, "xcodebuild requires Xcode"),
                ("/usr/bin/xcrun", "--find", "xctest"): (1, "unable to find utility xctest"),
            }

            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=lambda *command, **_: calls[command]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            report_text = report.read_text(encoding="utf-8")

        self.assertEqual(result, 2)
        self.assertIn("Status: FAIL", report_text)
        self.assertIn("full Xcode is not selected", report_text)
        self.assertIn("xcodebuild is not available", report_text)
        self.assertNotIn(str(Path.home()), report_text)

    @staticmethod
    def metadata(
        *,
        app_path: Path = macos_dev_host.DEFAULT_INSTALL_PATH,
        identifier: str = macos_dev_host.EXPECTED_BUNDLE_ID,
        authorities: tuple[str, ...] = ("Vibe Screen Dev", "Vibe Screen Dev Root"),
        signature: str | None = None,
        source_commit: str | None = SOURCE_COMMIT,
        source_tree: str | None = SOURCE_TREE,
        source_dirty: bool | None = False,
        binary_sha256: str = "aa1cdba1d65b8a4ed7e9376fcd329b3c8dbb6e635dbf61f1c1b61af727fb592d",
        cdhash: str | None = "e4ac7dab68720d647550f2e031f40070ab291e8b",
        designated_requirement: str | None = None,
        leaf_certificate_hash: str | None = macos_dev_host.EXPECTED_SIGNING_LEAF_SHA1,
    ) -> macos_dev_host.SigningMetadata:
        requirement = designated_requirement
        if requirement is None:
            requirement = (
                'identifier "dev.telemachus.display" and certificate leaf = '
                'H"9aae572bf6d764e3436a6109197d345b5a87998c"'
            )
        return macos_dev_host.SigningMetadata(
            app_path=app_path,
            identifier=identifier,
            source_commit=source_commit,
            source_tree=source_tree,
            source_dirty=source_dirty,
            binary_sha256=binary_sha256,
            authorities=authorities,
            cdhash=cdhash,
            designated_requirement=requirement,
            signature=signature,
            team_identifier=None,
            leaf_certificate_hash=leaf_certificate_hash,
        )

    def test_parse_entitlement_keys_detects_true_virtual_hid_entitlement(self) -> None:
        output = """
Executable=/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.developer.hid.virtual.device</key>
  <true/>
  <key>com.example.disabled</key>
  <false/>
</dict>
</plist>
"""

        keys = macos_dev_host.parse_entitlement_keys(output)

        self.assertEqual(keys, (macos_dev_host.VIRTUAL_HID_ENTITLEMENT,))

    def test_parse_entitlement_keys_ignores_missing_or_malformed_plist(self) -> None:
        self.assertEqual(macos_dev_host.parse_entitlement_keys("no plist here"), ())
        self.assertEqual(macos_dev_host.parse_entitlement_keys("<plist><dict><key>broken</key></dict>"), ())

    @staticmethod
    def login_ready_inputs() -> tuple[
        macos_dev_host.HostStartupSettings,
        macos_dev_host.LoginItemReadiness,
        macos_dev_host.HostDisplayReadiness,
        macos_dev_host.LogReadiness,
    ]:
        return (
            macos_dev_host.HostStartupSettings(
                domain="dev.telemachus.display",
                readable=True,
                auto_start_streaming_on_launch=True,
                startup_mode="usb",
                has_completed_onboarding=True,
                display_source="currentMain",
                selected_display_uuid=None,
                selected_display_id=None,
                stored_keys=(),
                defaults_used=(),
            ),
            macos_dev_host.LoginItemReadiness("enabled", True, "enabled", ("enabled",), True),
            macos_dev_host.HostDisplayReadiness(True, 1, ({"id": "1", "source": "CoreGraphics"},), active_display_count=1),
            macos_dev_host.LogReadiness("<user-host-log>", True, ("Auto-start deferred",)),
        )

    def test_readiness_document_keeps_controller_blocked_without_virtual_hid_entitlement(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        document = macos_dev_host.build_readiness_document(
            inspection,
            macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
            macos_dev_host.EntitlementStatus(
                app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                virtual_hid=False,
                keys=(),
                raw_output="",
            ),
            *self.login_ready_inputs(),
        )

        self.assertEqual(document["status"], "blocked")
        self.assertTrue(document["can_start_trusted_lan_gate"])
        self.assertTrue(document["can_start_native_hid_gate"])
        self.assertTrue(document["can_start_headless_login_gate"])
        self.assertFalse(document["can_start_controller_runtime_gate"])
        self.assertFalse(document["can_close_runtime_gates"])
        self.assertIn(macos_dev_host.VIRTUAL_HID_ENTITLEMENT, "\n".join(document["blockers"]))

    def test_readiness_document_reports_pass_when_shared_and_controller_prerequisites_pass(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        document = macos_dev_host.build_readiness_document(
            inspection,
            macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
            macos_dev_host.EntitlementStatus(
                app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                virtual_hid=True,
                keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                raw_output="",
            ),
            *self.login_ready_inputs(),
        )

        self.assertEqual(document["status"], "pass")
        self.assertTrue(document["can_start_trusted_lan_gate"])
        self.assertTrue(document["can_start_controller_runtime_gate"])
        self.assertTrue(document["can_start_headless_login_gate"])
        self.assertTrue(document["can_close_runtime_gates"])
        self.assertEqual(document["login_headless_status"], "ready")
        self.assertIn("does_not_prove", document["login_headless"])
        self.assertEqual(document["blockers"], [])
        self.assertEqual(
            document["safety"],
            {
                "read_only": True,
                "starts_host": False,
                "modifies_tcc": False,
                "modifies_keychain": False,
                "modifies_android": False,
                "closes_runtime_gates": False,
            },
        )

    def test_readiness_document_default_skips_login_item_probe(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=TEST_PRIVACY_DATABASE,
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        with mock.patch.object(macos_dev_host, "read_login_item_readiness") as login_probe:
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=True,
                    keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                    raw_output="",
                ),
                settings=self.login_ready_inputs()[0],
                displays=self.login_ready_inputs()[2],
                logs=self.login_ready_inputs()[3],
            )

        login_probe.assert_not_called()
        self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
        self.assertFalse(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])
        self.assertEqual(
            document["login_headless"]["login_item"]["detail"],
            macos_dev_host.LOGIN_ITEM_DIAGNOSTIC_OPT_IN_DETAIL,
        )
        self.assertFalse(document["can_start_headless_login_gate"])

    def test_login_headless_allows_lan_startup_mode(self) -> None:
        settings, login_item, displays, logs = self.login_ready_inputs()
        settings = macos_dev_host.HostStartupSettings(
            domain=settings.domain,
            readable=settings.readable,
            auto_start_streaming_on_launch=settings.auto_start_streaming_on_launch,
            startup_mode="lan",
            has_completed_onboarding=settings.has_completed_onboarding,
            display_source=settings.display_source,
            selected_display_uuid=settings.selected_display_uuid,
            selected_display_id=settings.selected_display_id,
            stored_keys=settings.stored_keys,
            defaults_used=settings.defaults_used,
            error=settings.error,
        )

        blockers = macos_dev_host.login_headless_blockers(settings, login_item, displays, logs)

        self.assertEqual(blockers, [])

    def test_default_readiness_document_skips_login_item_probe(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path("privacy.db"),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        with (
            mock.patch.object(macos_dev_host, "read_startup_settings", return_value=self.login_ready_inputs()[0]),
            mock.patch.object(macos_dev_host, "read_login_item_readiness", side_effect=AssertionError("sfltool probe must be opt-in")),
            mock.patch.object(macos_dev_host, "read_display_readiness", return_value=self.login_ready_inputs()[2]),
            mock.patch.object(macos_dev_host, "summarize_host_log", return_value=self.login_ready_inputs()[3]),
        ):
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=True,
                    keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                    raw_output="",
                ),
        )

        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
        self.assertFalse(document["can_start_headless_login_gate"])
        self.assertIn("Launch at Login is not verified enabled: unverified", "\n".join(document["blockers"]))

    def test_read_display_readiness_counts_system_profiler_online_displays_as_active(self) -> None:
        profiler_displays = (
            {
                "id": "1",
                "name": "Color LCD",
                "main": "1",
                "logical": "1512 x 982 @ 120.00Hz",
                "physical": "3024 x 1964",
                "source": "system_profiler",
            },
        )

        with (
            mock.patch.object(
                macos_dev_host,
                "run_best_effort",
                return_value=(0, ""),
            ),
            mock.patch.object(
                macos_dev_host,
                "read_system_profiler_displays",
                return_value=list(profiler_displays),
            ),
        ):
            readiness = macos_dev_host.read_display_readiness()

        self.assertTrue(readiness.readable)
        self.assertEqual(readiness.display_count, 1)
        self.assertEqual(readiness.active_display_count, 1)
        self.assertEqual(readiness.displays, profiler_displays)

    def test_readiness_document_blocks_all_start_flags_when_signing_or_tcc_is_missing(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=None,
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.missing_permission_status("Host bundle signing was not inspected"),
            errors=["missing signing identity", "Host bundle not found"],
        )

        document = macos_dev_host.build_readiness_document(
            inspection,
            macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
            macos_dev_host.EntitlementStatus(
                app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                virtual_hid=True,
                keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                raw_output="",
            ),
            *self.login_ready_inputs(),
        )

        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["signing_tcc_status"], "blocked")
        self.assertFalse(document["can_start_host_rss_gate"])
        self.assertFalse(document["can_start_trusted_lan_gate"])
        self.assertFalse(document["can_start_native_hid_gate"])
        self.assertFalse(document["can_start_stylus_gate"])
        self.assertFalse(document["can_start_hardware_keyboard_gate"])
        self.assertIsNone(document["permissions"]["screen_recording_granted"])
        self.assertIsNone(document["permissions"]["accessibility_granted"])

    def test_readiness_document_records_false_for_readable_denied_tcc_permissions(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=MacOSDevHostMetadataTests.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=macos_dev_host.USER_TCC_DATABASE_LABEL,
                rows=(),
                readable=True,
            ),
            errors=["Screen Recording is not authorized for the installed Host"],
        )

        document = macos_dev_host.build_readiness_document(
            inspection,
            macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
            macos_dev_host.EntitlementStatus(
                app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                virtual_hid=True,
                keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                raw_output="",
            ),
            *self.login_ready_inputs(),
        )

        self.assertFalse(document["permissions"]["screen_recording_granted"])
        self.assertFalse(document["permissions"]["accessibility_granted"])
        self.assertFalse(document["permissions"]["microphone_granted"])
        self.assertFalse(document["can_start_controller_runtime_gate"])
        self.assertFalse(document["can_start_headless_login_gate"])
        self.assertFalse(document["can_close_runtime_gates"])

    def test_readiness_document_blocks_headless_login_when_login_item_or_display_is_unverified(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=TEST_PRIVACY_DATABASE,
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        document = macos_dev_host.build_readiness_document(
            inspection,
            macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
            macos_dev_host.EntitlementStatus(
                app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                virtual_hid=True,
                keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                raw_output="",
            ),
            macos_dev_host.HostStartupSettings(
                domain="dev.telemachus.display",
                readable=True,
                auto_start_streaming_on_launch=True,
                startup_mode="usb",
                has_completed_onboarding=True,
                display_source="currentMain",
                selected_display_uuid=None,
                selected_display_id=None,
                stored_keys=(),
                defaults_used=(),
            ),
            macos_dev_host.LoginItemReadiness("unverified", False, "sfltool timed out", ()),
            macos_dev_host.HostDisplayReadiness(
                True,
                1,
                ({"id": "1", "source": "system_profiler"},),
                active_display_count=0,
            ),
            macos_dev_host.LogReadiness("<user-host-log>", True, ("Auto-start deferred",)),
        )

        self.assertEqual(document["status"], "blocked")
        self.assertTrue(document["can_start_trusted_lan_gate"])
        self.assertTrue(document["can_start_controller_runtime_gate"])
        self.assertFalse(document["can_start_headless_login_gate"])
        self.assertEqual(document["login_headless_status"], "blocked")
        blockers = "\n".join(document["blockers"])
        self.assertIn("Launch at Login is not verified enabled", blockers)
        self.assertIn("no active display is visible", blockers)

    def test_readiness_document_skips_login_item_probe_by_default(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=self.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=TEST_PRIVACY_DATABASE,
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )
        settings, _login_item, displays, logs = self.login_ready_inputs()

        with mock.patch.object(
            macos_dev_host,
            "read_login_item_readiness",
            side_effect=AssertionError("readiness document must not run the login-item probe by default"),
        ):
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=True,
                    keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                    raw_output="",
                ),
                settings=settings,
                displays=displays,
                logs=logs,
            )

        self.assertEqual(document["status"], "blocked")
        self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
        self.assertEqual(
            document["login_headless"]["login_item"]["detail"],
            macos_dev_host.LOGIN_ITEM_DIAGNOSTIC_OPT_IN_DETAIL,
        )

    def test_login_headless_evidence_redacts_local_paths(self) -> None:
        host_log_text = str(Path.home() / "Library" / "Logs" / "Telemachus" / "telemachus.log")
        generic_home_text = str(Path.home() / "private-app" / "state.log")

        login_item = macos_dev_host.parse_login_item_state(
            f"bundle id dev.telemachus.display path {host_log_text} also {generic_home_text} allowed = 1"
        )
        log_path = Path.home() / "custom-host.log"

        self.assertIn("<user-home>", "\n".join(login_item.evidence))
        self.assertIn("<user-host-log>", "\n".join(login_item.evidence))
        self.assertNotIn(str(Path.home()), "\n".join(login_item.evidence))
        self.assertEqual(macos_dev_host.host_log_path_label(log_path), "<user-home>/custom-host.log")
        self.assertEqual(
            macos_dev_host.ascii_report_text(f"Auto-start log at {host_log_text}"),
            "Auto-start log at <user-host-log>",
        )

    def test_inspect_listener_reports_missing_listener_without_raising(self) -> None:
        with mock.patch.object(
            macos_dev_host,
            "run",
            side_effect=subprocess.CalledProcessError(1, ["lsof"], output=""),
        ):
            status = macos_dev_host.inspect_listener(54321)

        self.assertFalse(status.observed)
        self.assertEqual(status.port, 54321)
        self.assertEqual(status.error, "listener not observed")

    def test_inspect_listener_redacts_lsof_user_column(self) -> None:
        output = (
            "COMMAND     PID     USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "VibeScreen  1234    localuser 7u  IPv4 0x123 0t0 TCP 127.0.0.1:54321 (LISTEN)"
        )

        with mock.patch.object(macos_dev_host, "run", return_value=output):
            status = macos_dev_host.inspect_listener(54321)

        self.assertTrue(status.observed)
        self.assertIn("<redacted-user>", status.output)
        self.assertIn("<redacted-ipv4>:54321", status.output)
        self.assertNotIn("localuser", status.output)
        self.assertNotIn("127." + "0.0.1", status.output)

    def test_readiness_command_writes_source_bound_blocked_json_when_identity_and_bundle_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Missing Dev",
                tcc_db=TEST_PRIVACY_DATABASE,
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                port=54321,
                probe_login_item=False,
            )

            with (
                mock.patch.object(
                    macos_dev_host.package_macos,
                    "resolve_sign_identity",
                    side_effect=SystemExit("missing identity"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "current_source_identity",
                    return_value=macos_dev_host.package_macos.SourceIdentity(
                        commit="c" * 40,
                        tree="d" * 40,
                        dirty=False,
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "collect_signing_metadata",
                    side_effect=SystemExit(f"Host bundle not found: {macos_dev_host.DEFAULT_INSTALL_PATH}"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(
                        port=54321,
                        observed=False,
                        output="",
                        error="listener not observed",
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=False,
                        keys=(),
                        raw_output="",
                        error="bundle missing",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=self.login_ready_inputs()[0]),
                mock.patch.object(
                    macos_dev_host,
                    "read_login_item_readiness",
                    side_effect=AssertionError("default readiness command must not run the login-item probe"),
                ) as login_probe,
                mock.patch.object(
                    macos_dev_host,
                    "run_best_effort",
                    side_effect=AssertionError("default readiness must not run shell probes"),
                ) as run_best_effort_mock,
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=self.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=self.login_ready_inputs()[3]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 2)
            document = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "blocked")
            self.assertFalse(document["can_start_trusted_lan_gate"])
            self.assertFalse(document["can_start_controller_runtime_gate"])
            self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
            self.assertFalse(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])
            self.assertIn("not probed", document["login_headless"]["login_item"]["detail"])
            self.assertFalse(document["can_close_runtime_gates"])
            self.assertEqual(document["host"]["current_source_commit"], "c" * 40)
            self.assertEqual(document["host"]["current_source_tree"], "d" * 40)
            self.assertFalse(document["host"]["current_source_dirty"])
            self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
            self.assertFalse(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])
            self.assertEqual(
                document["login_headless"]["login_item"]["detail"],
                macos_dev_host.LOGIN_ITEM_DIAGNOSTIC_OPT_IN_DETAIL,
            )
            self.assertIn("probe not run", document["login_headless"]["login_item"]["detail"])
            self.assertNotIn("sfltool", document["login_headless"]["login_item"]["detail"])
            self.assertIn("Host bundle not found", report.read_text(encoding="utf-8"))
            login_probe.assert_not_called()
            run_best_effort_mock.assert_not_called()

    def test_readiness_command_login_item_diagnostic_is_explicit_opt_in_with_ready_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path("privacy.db"),
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                port=54321,
                probe_login_item=True,
            )

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=self.metadata(),
                        source_identity=macos_dev_host.package_macos.SourceIdentity(
                            commit="a" * 40,
                            tree="b" * 40,
                            dirty=False,
                        ),
                        permissions=macos_dev_host.PermissionStatus(
                            database_path=Path("privacy.db"),
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
                        errors=[],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=True,
                        keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=self.login_ready_inputs()[0]),
                mock.patch.object(macos_dev_host, "read_login_item_readiness", return_value=self.login_ready_inputs()[1]) as login_mock,
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=self.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=self.login_ready_inputs()[3]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 0)
            login_mock.assert_called_once_with()
            document = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(document["login_headless"]["login_item"]["state"], "enabled")
            self.assertTrue(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])

    def test_readiness_command_probes_login_item_only_when_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.txt"
            json_output = Path(temporary_directory) / "readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                json_output=json_output,
                port=54321,
                source_root=Path("."),
                allow_source_mismatch=False,
                probe_login_item=True,
            )
            metadata = self.metadata()
            source_identity = macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            )
            permissions = macos_dev_host.PermissionStatus(
                database_path=Path("privacy.sqlite"),
                readable=True,
                rows=allowed_tcc_rows(),
            )

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(metadata, source_identity, permissions, []),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=True,
                        keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=self.login_ready_inputs()[0]),
                mock.patch.object(macos_dev_host, "read_login_item_readiness", return_value=self.login_ready_inputs()[1]) as login_probe_mock,
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=self.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=self.login_ready_inputs()[3]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 0)
            document = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(document["login_headless_status"], "ready")
            self.assertEqual(document["login_headless"]["login_item"]["state"], "enabled")
            self.assertTrue(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])
        login_probe_mock.assert_called_once_with()

    def test_readiness_command_checks_login_item_only_when_opted_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                probe_login_item=True,
            )
            settings, login_item, displays, logs = self.login_ready_inputs()

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=self.metadata(),
                        source_identity=macos_dev_host.package_macos.SourceIdentity(
                            commit="a" * 40,
                            tree="b" * 40,
                            dirty=False,
                        ),
                        permissions=macos_dev_host.PermissionStatus(
                            database_path=Path(PRIVACY_DB_FILENAME),
                            readable=True,
                            rows=allowed_tcc_rows(),
                        ),
                        errors=[],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=True,
                        keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=settings),
                mock.patch.object(macos_dev_host, "read_login_item_readiness", return_value=login_item) as login_item_probe,
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=displays),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=logs),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 0)
            login_item_probe.assert_called_once_with()
            document = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "pass")
            self.assertEqual(document["login_headless"]["login_item"]["state"], "enabled")
            self.assertTrue(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])

    def test_readiness_command_login_item_diagnostic_is_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                tcc_db=TEST_PRIVACY_DATABASE,
                sign_identity="Missing Dev",
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                probe_login_item=True,
            )

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=None,
                        source_identity=None,
                        permissions=macos_dev_host.PermissionStatus(
                            database_path=macos_dev_host.USER_TCC_DATABASE_LABEL,
                            rows=(),
                            readable=False,
                            error="permission state unavailable",
                        ),
                        errors=["Host bundle not found"],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(
                        port=54321,
                        observed=False,
                        output="",
                        error="listener not observed",
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=False,
                        keys=(),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_login_item_readiness", return_value=self.login_ready_inputs()[1]) as login_probe,
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=self.login_ready_inputs()[0]),
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=self.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=self.login_ready_inputs()[3]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 2)
            login_probe.assert_called_once_with()
            document = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(document["login_headless"]["login_item"]["state"], "enabled")
            self.assertTrue(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])

    def test_inspect_host_without_throwing_keeps_source_identity_when_bundle_inspection_fails(self) -> None:
        source_identity = macos_dev_host.package_macos.SourceIdentity(
            commit="e" * 40,
            tree="f" * 40,
            dirty=False,
        )

        with (
            mock.patch.object(
                macos_dev_host.package_macos,
                "resolve_sign_identity",
                side_effect=SystemExit("missing identity"),
            ),
            mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity),
            mock.patch.object(
                macos_dev_host,
                "collect_signing_metadata",
                side_effect=SystemExit("Host bundle not found"),
            ),
        ):
            inspection = macos_dev_host.inspect_host_without_throwing(
                macos_dev_host.DEFAULT_INSTALL_PATH,
                Path("TCC.db"),
                expected_sign_identity="Missing Dev",
                source_root=Path("."),
            )

        self.assertIsNone(inspection.metadata)
        self.assertEqual(inspection.source_identity, source_identity)
        self.assertFalse(inspection.permissions.readable)
        self.assertEqual(inspection.permissions.error, "Host bundle signing was not inspected")
        self.assertIn("missing identity", "\n".join(inspection.errors))
        self.assertIn("Host bundle not found", "\n".join(inspection.errors))

    def test_inspect_host_without_throwing_accepts_name_resolving_to_pinned_sha1(self) -> None:
        source_identity = macos_dev_host.package_macos.SourceIdentity(
            commit="a" * 40,
            tree="b" * 40,
            dirty=False,
        )

        with (
            mock.patch.object(
                macos_dev_host.package_macos,
                "resolve_sign_identity",
                return_value=macos_dev_host.EXPECTED_SIGNING_LEAF_SHA1,
            ),
            mock.patch.object(macos_dev_host, "current_source_identity", return_value=source_identity),
            mock.patch.object(macos_dev_host, "collect_signing_metadata", return_value=self.metadata()),
            mock.patch.object(
                macos_dev_host,
                "query_tcc_rows",
                return_value=macos_dev_host.PermissionStatus(
                    database_path=Path(PRIVACY_DB_FILENAME),
                    readable=True,
                    rows=allowed_tcc_rows(),
                ),
            ),
        ):
            inspection = macos_dev_host.inspect_host_without_throwing(
                macos_dev_host.DEFAULT_INSTALL_PATH,
                Path(PRIVACY_DB_FILENAME),
                expected_sign_identity="Vibe Screen Dev",
                source_root=Path("."),
            )

        self.assertEqual(inspection.errors, [])

    def test_xctest_preflight_passes_with_full_xcode_and_xctest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            developer_dir = Path(temporary_directory) / "Xcode.app" / "Contents" / "Developer"
            xctest = developer_dir / "Platforms" / "MacOSX.platform" / "Developer" / "Library" / "Frameworks" / "XCTest.framework"
            xctest.mkdir(parents=True)
            output = Path(temporary_directory) / "xctest-preflight.json"

            def fake_run(*command: str, timeout_seconds: int | None = None) -> tuple[int, str]:
                del timeout_seconds
                if command == ("/usr/bin/xcode-select", "-p"):
                    return 0, str(developer_dir)
                if command == ("/usr/bin/xcodebuild", "-version"):
                    return 0, "Xcode 16.4\nBuild version 16F6"
                if command == ("/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"):
                    return 0, str(developer_dir / "Platforms" / "MacOSX.platform" / "Developer" / "SDKs" / "MacOSX.sdk")
                return 1, "unexpected command"

            args = argparse.Namespace(json_output=output)
            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=fake_run),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(document["status"], "passed")
            self.assertTrue(document["can_run_swiftpm_xctest"])
            self.assertTrue(document["is_full_xcode"])
            self.assertTrue(document["has_xctest"])
            self.assertEqual(document["xcode_version"], "16.4")
            self.assertEqual(document["xcode_build"], "16F6")
            self.assertFalse(document["blockers"])

    def test_xctest_preflight_blocks_command_line_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            developer_dir = Path(temporary_directory) / "CommandLineTools"
            developer_dir.mkdir()
            output = Path(temporary_directory) / "xctest-preflight.json"

            def fake_run(*command: str, timeout_seconds: int | None = None) -> tuple[int, str]:
                del timeout_seconds
                if command == ("/usr/bin/xcode-select", "-p"):
                    return 0, str(developer_dir)
                if command == ("/usr/bin/xcodebuild", "-version"):
                    return 1, "xcodebuild requires Xcode"
                if command == ("/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"):
                    return 0, str(developer_dir / "SDKs" / "MacOSX.sdk")
                return 1, "unexpected command"

            args = argparse.Namespace(json_output=output)
            with (
                mock.patch.object(macos_dev_host, "run_best_effort", side_effect=fake_run),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.xctest_preflight_command(args)

            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(document["status"], "blocked")
            self.assertFalse(document["can_run_swiftpm_xctest"])
            self.assertFalse(document["is_full_xcode"])
            self.assertFalse(document["has_xctest"])
            self.assertIn("Full Xcode is required", "\n".join(document["blockers"]))


class MacOSDevHostTCCTests(unittest.TestCase):
    def test_run_best_effort_reports_missing_command_without_throwing(self) -> None:
        with mock.patch.object(
            macos_dev_host.subprocess,
            "run",
            side_effect=FileNotFoundError("missing executable"),
        ):
            exit_code, output = macos_dev_host.run_best_effort("/usr/bin/defaults", "export")

        self.assertEqual(exit_code, 127)
        self.assertIn("command unavailable: defaults", output)

    def test_tcc_database_paths_includes_system_database_for_default_user_database(self) -> None:
        paths = macos_dev_host.tcc_database_paths(macos_dev_host.default_tcc_database())

        self.assertEqual(paths[0], macos_dev_host.default_tcc_database().resolve())
        self.assertIn(macos_dev_host.SYSTEM_TCC_DATABASE, paths)

    def test_default_tcc_database_labels_do_not_expose_local_paths(self) -> None:
        self.assertEqual(
            macos_dev_host.tcc_database_report_label(macos_dev_host.default_tcc_database()),
            macos_dev_host.USER_TCC_DATABASE_LABEL,
        )
        self.assertEqual(
            macos_dev_host.tcc_database_report_label(macos_dev_host.SYSTEM_TCC_DATABASE),
            macos_dev_host.SYSTEM_TCC_DATABASE_LABEL,
        )

    def test_tcc_database_paths_honors_explicit_test_database(self) -> None:
        explicit = Path("/tmp/test-tcc.db")

        self.assertEqual(macos_dev_host.tcc_database_paths(explicit), (explicit.resolve(),))

    def test_query_tcc_rows_uses_read_only_database_and_permission_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / PRIVACY_DB_FILENAME
            self.write_tcc_database(
                database_path,
                [
                    ("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 10),
                    ("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 11),
                    ("kTCCServiceMicrophone", "dev.telemachus.display", 0, 2, 4, 12),
                    ("kTCCServiceAccessibility", "other.bundle", 0, 0, 4, 12),
                ],
            )

            status = macos_dev_host.query_tcc_rows("dev.telemachus.display", database_path)

            self.assertTrue(status.readable)
            self.assertEqual(len(status.rows), 3)
            self.assertTrue(status.is_allowed(macos_dev_host.SCREEN_CAPTURE_SERVICES))
            self.assertTrue(status.is_allowed((macos_dev_host.ACCESSIBILITY_SERVICE,)))
            self.assertTrue(status.is_allowed(macos_dev_host.MICROPHONE_SERVICES))

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
                [
                    ("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 11),
                    ("kTCCServiceMicrophone", "dev.telemachus.display", 0, 2, 4, 12),
                ],
            )

            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                (user_database, system_database),
            )

            self.assertTrue(status.readable)
            self.assertEqual(len(status.rows), 3)
            self.assertTrue(status.is_allowed(macos_dev_host.SCREEN_CAPTURE_SERVICES))
            self.assertTrue(status.is_allowed((macos_dev_host.ACCESSIBILITY_SERVICE,)))
            self.assertTrue(status.is_allowed(macos_dev_host.MICROPHONE_SERVICES))

    def test_query_tcc_rows_fails_closed_when_database_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                Path(temporary_directory) / "missing-privacy.sqlite",
            )

        self.assertFalse(status.readable)
        self.assertIn("TCC database not found", status.error or "")

    def test_query_tcc_database_redacts_sqlite_read_errors(self) -> None:
        user_database = macos_dev_host.default_tcc_database()
        with mock.patch.object(
            macos_dev_host.sqlite3,
            "connect",
            side_effect=sqlite3.OperationalError(f"unable to open database file: {user_database}"),
        ):
            status = macos_dev_host._query_tcc_database_direct(
                "dev.telemachus.display",
                user_database,
            )

        self.assertFalse(status.readable)
        self.assertIn(macos_dev_host.USER_TCC_DATABASE_LABEL, status.error or "")
        self.assertNotIn(str(Path.home()), status.error or "")

    def test_query_tcc_rows_redacts_default_database_paths(self) -> None:
        with mock.patch.object(
            macos_dev_host,
            "query_tcc_database",
            side_effect=lambda _bundle_id, path: macos_dev_host.PermissionStatus(
                database_path=macos_dev_host.tcc_database_report_label(path),
                rows=(),
                readable=False,
                error="unable to open database file",
            ),
        ):
            status = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                macos_dev_host.tcc_database_paths(macos_dev_host.default_tcc_database()),
            )

        self.assertEqual(
            status.database_path,
            f"{macos_dev_host.USER_TCC_DATABASE_LABEL}; {macos_dev_host.SYSTEM_TCC_DATABASE_LABEL}",
        )
        self.assertIn(macos_dev_host.USER_TCC_DATABASE_LABEL, status.error or "")
        self.assertIn(macos_dev_host.SYSTEM_TCC_DATABASE_LABEL, status.error or "")
        self.assertNotIn(str(Path.home()), status.database_path)
        self.assertNotIn(str(Path.home()), status.error or "")

    def test_run_best_effort_reports_missing_command(self) -> None:
        status, output = macos_dev_host.run_best_effort("/definitely/missing/vibe-screen-tool")

        self.assertEqual(status, 127)
        self.assertEqual(output, "command unavailable: vibe-screen-tool")

    def test_readiness_artifacts_keep_default_tcc_paths_redacted(self) -> None:
        with mock.patch.object(
            macos_dev_host,
            "query_tcc_database",
            side_effect=lambda _bundle_id, path: macos_dev_host.PermissionStatus(
                database_path=macos_dev_host.tcc_database_report_label(path),
                rows=(),
                readable=False,
                error="unable to open database file",
            ),
        ):
            permissions = macos_dev_host.query_tcc_rows(
                "dev.telemachus.display",
                macos_dev_host.tcc_database_paths(macos_dev_host.default_tcc_database()),
            )

        report = macos_dev_host.format_report(
            MacOSDevHostMetadataTests.metadata(),
            permissions,
            ["cannot verify TCC permissions read-only: " + str(permissions.error)],
        )
        inspection = macos_dev_host.HostInspection(
            metadata=MacOSDevHostMetadataTests.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=permissions,
            errors=["cannot verify TCC permissions read-only: " + str(permissions.error)],
        )
        settings, _login_item, displays, logs = MacOSDevHostMetadataTests.login_ready_inputs()
        with mock.patch.object(macos_dev_host, "read_login_item_readiness") as login_probe:
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=False, output="", error="listener not observed"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=False,
                    keys=(),
                    raw_output="",
                ),
                settings=settings,
                displays=displays,
                logs=logs,
            )
        login_probe.assert_not_called()
        serialized_document = json.dumps(document, sort_keys=True)

        for artifact in (report, serialized_document):
            self.assertIn(macos_dev_host.USER_TCC_DATABASE_LABEL, artifact)
            self.assertIn(macos_dev_host.SYSTEM_TCC_DATABASE_LABEL, artifact)
            self.assertNotIn(str(Path.home()), artifact)
            self.assertNotIn(str(macos_dev_host.SYSTEM_TCC_DATABASE), artifact)
            self.assertNotIn("TCC" + ".db", artifact)

    def test_readiness_document_default_does_not_probe_login_item(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=MacOSDevHostMetadataTests.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path(PRIVACY_DB_FILENAME),
                readable=True,
                rows=allowed_tcc_rows(),
            ),
            errors=[],
        )

        with mock.patch.object(macos_dev_host, "read_login_item_readiness") as login_item_probe:
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=True,
                    keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                    raw_output="",
                ),
                settings=MacOSDevHostMetadataTests.login_ready_inputs()[0],
                displays=MacOSDevHostMetadataTests.login_ready_inputs()[2],
                logs=MacOSDevHostMetadataTests.login_ready_inputs()[3],
            )

        login_item_probe.assert_not_called()
        self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
        self.assertFalse(document["login_headless"]["login_item"]["sfltool_dumpbtm_was_run"])
        self.assertIn("probe not run", document["login_headless"]["login_item"]["detail"])
        self.assertIn("Launch at Login is not verified enabled: unverified", "\n".join(document["blockers"]))

    def test_readiness_command_skips_login_item_probe_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                port=54321,
                probe_login_item=False,
            )

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=MacOSDevHostMetadataTests.metadata(),
                        source_identity=macos_dev_host.package_macos.SourceIdentity(
                            commit="a" * 40,
                            tree="b" * 40,
                            dirty=False,
                        ),
                        permissions=macos_dev_host.PermissionStatus(
                            database_path=Path(PRIVACY_DB_FILENAME),
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
                        errors=[],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=True,
                        keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[0]),
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[3]),
                mock.patch.object(macos_dev_host, "read_login_item_readiness") as login_item_probe,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            document = json.loads(json_output.read_text(encoding="utf-8"))

        self.assertEqual(result, 2)
        login_item_probe.assert_not_called()
        self.assertEqual(document["login_headless"]["login_item"]["state"], "unverified")
        self.assertIn("probe not run", document["login_headless"]["login_item"]["detail"])

    def test_readiness_command_only_probes_login_item_when_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            report = root / "host-signing-and-permissions.txt"
            json_output = root / "host-readiness.json"
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path(PRIVACY_DB_FILENAME),
                report=report,
                json_output=json_output,
                source_root=Path("."),
                allow_source_mismatch=False,
                probe_login_item=True,
            )

            with (
                mock.patch.object(
                    macos_dev_host,
                    "inspect_host_without_throwing",
                    return_value=macos_dev_host.HostInspection(
                        metadata=MacOSDevHostMetadataTests.metadata(),
                        source_identity=macos_dev_host.package_macos.SourceIdentity(
                            commit="a" * 40,
                            tree="b" * 40,
                            dirty=False,
                        ),
                        permissions=macos_dev_host.PermissionStatus(
                            database_path=Path(PRIVACY_DB_FILENAME),
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
                        errors=[],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_listener",
                    return_value=macos_dev_host.ListenerStatus(port=54321, observed=True, output="Vibe Screen LISTEN"),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "inspect_entitlements",
                    return_value=macos_dev_host.EntitlementStatus(
                        app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                        virtual_hid=True,
                        keys=(macos_dev_host.VIRTUAL_HID_ENTITLEMENT,),
                        raw_output="",
                    ),
                ),
                mock.patch.object(macos_dev_host, "read_startup_settings", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[0]),
                mock.patch.object(macos_dev_host, "read_display_readiness", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[2]),
                mock.patch.object(macos_dev_host, "summarize_host_log", return_value=MacOSDevHostMetadataTests.login_ready_inputs()[3]),
                mock.patch.object(
                    macos_dev_host,
                    "read_login_item_readiness",
                    return_value=MacOSDevHostMetadataTests.login_ready_inputs()[1],
                ) as login_item_probe,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            document = json.loads(json_output.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        login_item_probe.assert_called_once_with()
        self.assertEqual(document["login_headless"]["login_item"]["state"], "enabled")

    def test_readiness_document_fails_closed_when_defaults_tool_is_missing(self) -> None:
        inspection = macos_dev_host.HostInspection(
            metadata=MacOSDevHostMetadataTests.metadata(),
            source_identity=macos_dev_host.package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
            permissions=macos_dev_host.PermissionStatus(
                database_path=macos_dev_host.USER_TCC_DATABASE_LABEL,
                rows=(),
                readable=False,
                error="unable to open database file",
            ),
            errors=["cannot verify TCC permissions read-only"],
        )

        with mock.patch.object(
            macos_dev_host.subprocess,
            "run",
            side_effect=FileNotFoundError(2, "No such file or directory", "/usr/bin/defaults"),
        ):
            document = macos_dev_host.build_readiness_document(
                inspection,
                macos_dev_host.ListenerStatus(port=54321, observed=False, output="", error="listener not observed"),
                macos_dev_host.EntitlementStatus(
                    app_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                    virtual_hid=False,
                    keys=(),
                    raw_output="",
                ),
                login_item=macos_dev_host.LoginItemReadiness("unverified", False, "not checked", ()),
                displays=macos_dev_host.HostDisplayReadiness(False, 0, (), "not checked", None),
                logs=macos_dev_host.LogReadiness("<user-host-log>", False, "not checked", ()),
        )

        self.assertEqual(document["status"], "blocked")
        self.assertEqual(
            document["login_headless"]["startup_settings"]["error"],
            "command unavailable: defaults",
        )
        serialized_document = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(Path.home()), serialized_document)
        self.assertNotIn("/usr/bin/defaults", serialized_document)

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
        self.assertNotIn("Microphone is not authorized", joined_errors)

    def test_query_tcc_database_accepts_schema_without_optional_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / PRIVACY_DB_FILENAME
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
            database_path = Path(temporary_directory) / PRIVACY_DB_FILENAME
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
            database_path = Path(temporary_directory) / PRIVACY_DB_FILENAME
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
            macos_dev_host._query_tcc_database_worker(
                queue_instance, "dev.telemachus.display", Path(PRIVACY_DB_FILENAME)
            )

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

    def test_safe_replace_app_preserves_existing_app_when_staging_signature_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            self.write_app(install, executable=b"old")
            wrong_leaf = MacOSDevHostMetadataTests.metadata(
                app_path=source,
                leaf_certificate_hash="0123456789ABCDEF0123456789ABCDEF01234567",
            )

            with mock.patch.object(
                macos_dev_host,
                "collect_signing_metadata",
                return_value=wrong_leaf,
            ):
                with self.assertRaisesRegex(SystemExit, "refusing to install non-evidence-ready"):
                    macos_dev_host.safe_replace_app(
                        source,
                        install,
                        macos_dev_host.EXPECTED_BUNDLE_ID,
                        expected_sign_identity="Vibe Screen Dev",
                        source_identity=source_identity(),
                    )

            self.assertEqual((install / "Contents/MacOS/Vibe Screen").read_bytes(), b"old")

    def test_safe_replace_app_restores_existing_app_when_final_signature_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            self.write_app(install, executable=b"old")
            staged_metadata = MacOSDevHostMetadataTests.metadata(app_path=source)
            installed_bad_metadata = MacOSDevHostMetadataTests.metadata(
                app_path=install,
                designated_requirement="",
                leaf_certificate_hash=None,
            )

            with mock.patch.object(
                macos_dev_host,
                "collect_signing_metadata",
                side_effect=(staged_metadata, installed_bad_metadata),
            ):
                with self.assertRaisesRegex(SystemExit, "codesign designated requirement is missing"):
                    macos_dev_host.safe_replace_app(
                        source,
                        install,
                        macos_dev_host.EXPECTED_BUNDLE_ID,
                        expected_sign_identity="Vibe Screen Dev",
                        source_identity=source_identity(),
                    )

            self.assertEqual((install / "Contents/MacOS/Vibe Screen").read_bytes(), b"old")

    def test_safe_replace_app_removes_new_install_when_final_gate_fails_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            staged_metadata = MacOSDevHostMetadataTests.metadata(app_path=source)
            installed_bad_metadata = MacOSDevHostMetadataTests.metadata(
                app_path=install,
                cdhash=None,
            )

            with mock.patch.object(
                macos_dev_host,
                "collect_signing_metadata",
                side_effect=(staged_metadata, installed_bad_metadata),
            ):
                with self.assertRaisesRegex(SystemExit, "codesign CDHash is missing"):
                    macos_dev_host.safe_replace_app(
                        source,
                        install,
                        macos_dev_host.EXPECTED_BUNDLE_ID,
                        expected_sign_identity="Vibe Screen Dev",
                        source_identity=source_identity(),
                    )

            self.assertFalse(install.exists())

    def test_safe_replace_app_removes_new_install_when_permission_fails_after_move_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")

            def require_or_raise(app_path: Path, **_: object) -> macos_dev_host.SigningMetadata:
                if app_path == install:
                    raise PermissionError("simulated permission failure")
                return MacOSDevHostMetadataTests.metadata(app_path=app_path)

            with mock.patch.object(
                macos_dev_host,
                "require_installable_host_bundle",
                side_effect=require_or_raise,
            ):
                with self.assertRaisesRegex(SystemExit, "requires permission"):
                    macos_dev_host.safe_replace_app(
                        source,
                        install,
                        macos_dev_host.EXPECTED_BUNDLE_ID,
                        expected_sign_identity="Vibe Screen Dev",
                        source_identity=source_identity(),
                    )

            self.assertFalse(install.exists())

    def test_safe_replace_app_installs_when_staged_and_final_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.app"
            install = root / "Vibe Screen.app"
            self.write_app(source, executable=b"new")
            staged_metadata = MacOSDevHostMetadataTests.metadata(app_path=source)
            installed_metadata = MacOSDevHostMetadataTests.metadata(app_path=install)

            with mock.patch.object(
                macos_dev_host,
                "collect_signing_metadata",
                side_effect=(staged_metadata, installed_metadata),
            ):
                macos_dev_host.safe_replace_app(
                    source,
                    install,
                    macos_dev_host.EXPECTED_BUNDLE_ID,
                    expected_sign_identity="Vibe Screen Dev",
                    source_identity=source_identity(),
                )

            self.assertEqual((install / "Contents/MacOS/Vibe Screen").read_bytes(), b"new")

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
                mock.patch.object(
                    macos_dev_host,
                    "collect_signing_metadata",
                    return_value=MacOSDevHostMetadataTests.metadata(app_path=source),
                ),
                mock.patch.object(Path, "rename", rename_or_fail),
            ):
                with self.assertRaisesRegex(OSError, "simulated final rename failure"):
                    macos_dev_host.safe_replace_app(
                        source,
                        install,
                        macos_dev_host.EXPECTED_BUNDLE_ID,
                        expected_sign_identity="Vibe Screen Dev",
                        source_identity=source_identity(),
                    )

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
