from __future__ import annotations

import plistlib
import json
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

    def test_preflight_command_refuses_ad_hoc_before_reading_bundle_or_tcc(self) -> None:
        args = mock.Mock(
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            sign_identity="-",
            tcc_db=Path("TCC.db"),
            report=Path("report.txt"),
        )
        with (
            mock.patch.object(macos_dev_host, "collect_signing_metadata") as metadata_mock,
            mock.patch.object(macos_dev_host, "query_tcc_rows") as tcc_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "stable signing identity"):
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

    def test_preflight_command_resolves_configured_identity_before_reading_bundle(self) -> None:
        args = mock.Mock(
            install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
            sign_identity="Missing Dev",
            tcc_db=Path("TCC.db"),
            report=Path("report.txt"),
        )
        with (
            mock.patch.object(
                macos_dev_host.package_macos,
                "resolve_sign_identity",
                side_effect=SystemExit("missing identity"),
            ) as resolve_mock,
            mock.patch.object(macos_dev_host, "collect_signing_metadata") as metadata_mock,
            mock.patch.object(macos_dev_host, "query_tcc_rows") as tcc_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "missing identity"):
                macos_dev_host.preflight_command(args)
        resolve_mock.assert_called_once_with("Missing Dev")
        metadata_mock.assert_not_called()
        tcc_mock.assert_not_called()

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

    def test_defaults_parser_extracts_startup_settings_and_defaults(self) -> None:
        defaults_output = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Telemachus_autoStartStreamingOnLaunch</key>
    <true/>
    <key>Telemachus_connectionMode</key>
    <string>wireless</string>
    <key>Telemachus_displaySource</key>
    <string>selectedDisplay</string>
    <key>Telemachus_hasCompletedOnboarding</key>
    <true/>
    <key>Telemachus_selectedDisplayID</key>
    <integer>123</integer>
    <key>Telemachus_selectedDisplayUUID</key>
    <string>display-uuid</string>
</dict>
</plist>
"""

        with mock.patch.object(macos_dev_host, "run_best_effort", return_value=(0, defaults_output)):
            settings = macos_dev_host.read_startup_settings()

        self.assertTrue(settings.readable)
        self.assertTrue(settings.auto_start_streaming_on_launch)
        self.assertEqual(settings.startup_mode, "wireless")
        self.assertTrue(settings.has_completed_onboarding)
        self.assertEqual(settings.display_source, "selectedDisplay")
        self.assertEqual(settings.selected_display_uuid, "display-uuid")
        self.assertEqual(settings.selected_display_id, 123)
        self.assertIn("startupMode=usb", settings.defaults_used)

    def test_login_item_parser_reports_enabled_and_requires_approval(self) -> None:
        enabled = macos_dev_host.parse_login_item_state(
            """
            bundle id: dev.telemachus.display
            app url: file:///Applications/Vibe%20Screen.app/
            enabled
            """
        )
        approval = macos_dev_host.parse_login_item_state(
            """
            bundle id: dev.telemachus.display
            requires approval in system settings
            """
        )

        self.assertEqual(enabled.state, "enabled")
        self.assertTrue(enabled.matched)
        self.assertEqual(approval.state, "requires_approval")

    def test_display_readiness_keeps_system_profiler_as_diagnostic_only(self) -> None:
        profiler_payload = json.dumps(
            {
                "SPDisplaysDataType": [
                    {
                        "spdisplays_ndrvs": [
                            {
                                "_name": "Color LCD",
                                "_spdisplays_displayID": "1",
                                "_spdisplays_resolution": "1512 x 982 @ 120.00Hz",
                                "_spdisplays_pixels": "3024 x 1964",
                                "spdisplays_main": "spdisplays_yes",
                                "spdisplays_online": "spdisplays_yes",
                            }
                        ]
                    }
                ]
            }
        )

        with mock.patch.object(
            macos_dev_host,
            "run_best_effort",
            side_effect=[(0, ""), (0, profiler_payload)],
        ):
            displays = macos_dev_host.read_display_readiness()

        self.assertTrue(displays.readable)
        self.assertEqual(displays.display_count, 1)
        self.assertEqual(displays.active_display_count, 0)
        self.assertEqual(displays.displays[0]["source"], "system_profiler")

    def test_readiness_payload_blocks_when_only_system_profiler_displays_exist(self) -> None:
        payload = macos_dev_host.build_readiness_payload(
            metadata=self.metadata(),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path("TCC.db"),
                readable=True,
                rows=(
                    macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
                    macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
                ),
            ),
            signing_errors=[],
            settings=macos_dev_host.HostStartupSettings(
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
            login_item=macos_dev_host.LoginItemReadiness(
                state="enabled",
                matched=True,
                detail="enabled",
                evidence=("enabled",),
            ),
            displays=macos_dev_host.HostDisplayReadiness(
                readable=True,
                display_count=1,
                displays=({"id": "1", "source": "system_profiler"},),
                active_display_count=0,
            ),
            logs=macos_dev_host.LogReadiness(
                path="telemachus.log",
                readable=True,
                markers=("Auto-start deferred until onboarding and Screen Recording are complete",),
            ),
        )

        self.assertEqual(payload["result"], "blocked")
        self.assertEqual(payload["display_inventory"]["display_count"], 1)
        self.assertEqual(payload["display_inventory"]["active_display_count"], 0)
        self.assertIn("no active display is visible", "\n".join(payload["blockers"]))

    def test_readiness_payload_keeps_integration_gates_open_when_ready(self) -> None:
        payload = macos_dev_host.build_readiness_payload(
            metadata=self.metadata(),
            permissions=macos_dev_host.PermissionStatus(
                database_path=Path("TCC.db"),
                readable=True,
                rows=(
                    macos_dev_host.TCCRow("kTCCServiceScreenCapture", "dev.telemachus.display", 0, 2, 4, 1),
                    macos_dev_host.TCCRow("kTCCServiceAccessibility", "dev.telemachus.display", 0, 2, 4, 2),
                ),
            ),
            signing_errors=[],
            settings=macos_dev_host.HostStartupSettings(
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
            login_item=macos_dev_host.LoginItemReadiness(
                state="enabled",
                matched=True,
                detail="enabled",
                evidence=("enabled",),
            ),
            displays=macos_dev_host.HostDisplayReadiness(
                readable=True,
                display_count=1,
                displays=({"id": "1", "main": "1", "logical": "1512x982", "physical": "3024x1964"},),
            ),
            logs=macos_dev_host.LogReadiness(
                path="telemachus.log",
                readable=True,
                markers=("Auto-start deferred until onboarding and Screen Recording are complete",),
            ),
        )

        self.assertEqual(payload["result"], "ready")
        self.assertEqual(payload["warnings"], [])
        self.assertIn("macOS launched Vibe Screen after logout/login or reboot", payload["does_not_prove"])
        self.assertIn("headless Mac mini exposes a capturable display", "\n".join(payload["does_not_prove"]))
        self.assertIn("capture a reboot or logout/login launch log", "\n".join(payload["recommended_next_evidence"]))

    def test_readiness_payload_reports_missing_login_onboarding_display_and_log_blockers(self) -> None:
        payload = macos_dev_host.build_readiness_payload(
            metadata=self.metadata(),
            permissions=macos_dev_host.PermissionStatus(database_path=Path("TCC.db"), readable=True, rows=()),
            signing_errors=["Screen Recording is not authorized for the installed Host"],
            settings=macos_dev_host.HostStartupSettings(
                domain="dev.telemachus.display",
                readable=True,
                auto_start_streaming_on_launch=False,
                startup_mode="internet",
                has_completed_onboarding=False,
                display_source="currentMain",
                selected_display_uuid=None,
                selected_display_id=None,
                stored_keys=(),
                defaults_used=(),
            ),
            login_item=macos_dev_host.LoginItemReadiness(
                state="requires_approval",
                matched=True,
                detail="approval required",
                evidence=("requires approval",),
            ),
            displays=macos_dev_host.HostDisplayReadiness(readable=True, display_count=0, displays=()),
            logs=macos_dev_host.LogReadiness(path="missing.log", readable=False, markers=(), error="Host log not found"),
        )

        blockers = "\n".join(payload["blockers"])
        self.assertEqual(payload["result"], "blocked")
        self.assertIn("Screen Recording is not authorized", blockers)
        self.assertIn("Launch at Login is not verified enabled", blockers)
        self.assertIn("Start streaming automatically is disabled", blockers)
        self.assertIn("startupMode is 'internet'", blockers)
        self.assertIn("onboarding has not completed", blockers)
        self.assertIn("no active display", blockers)
        self.assertIn("Host log not found", "\n".join(payload["warnings"]))

    def test_readiness_command_writes_text_and_json_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            args = mock.Mock(
                install_path=macos_dev_host.DEFAULT_INSTALL_PATH,
                sign_identity="Vibe Screen Dev",
                tcc_db=Path("TCC.db"),
                report=root / "readiness.txt",
                json_report=root / "readiness.json",
                log_path=Path("missing.log"),
            )
            with (
                mock.patch.object(macos_dev_host.package_macos, "resolve_sign_identity"),
                mock.patch.object(
                    macos_dev_host,
                    "metadata_and_permissions",
                    return_value=(
                        self.metadata(),
                        macos_dev_host.PermissionStatus(Path("TCC.db"), (), True),
                        ["Screen Recording is not authorized for the installed Host"],
                    ),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "read_startup_settings",
                    return_value=macos_dev_host.HostStartupSettings(
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
                ),
                mock.patch.object(
                    macos_dev_host,
                    "read_login_item_readiness",
                    return_value=macos_dev_host.LoginItemReadiness("enabled", True, "enabled", ()),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "read_display_readiness",
                    return_value=macos_dev_host.HostDisplayReadiness(True, 1, ({"id": "1"},)),
                ),
                mock.patch.object(
                    macos_dev_host,
                    "summarize_host_log",
                    return_value=macos_dev_host.LogReadiness("missing.log", True, ()),
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                result = macos_dev_host.readiness_command(args)

            self.assertEqual(result, 2)
            self.assertIn("Result: BLOCKED", args.report.read_text(encoding="utf-8"))
            self.assertIn('"result": "blocked"', args.json_report.read_text(encoding="utf-8"))

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

    def test_query_tcc_database_fails_closed_when_read_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "TCC.db"
            database_path.write_bytes(b"not queried in this test")
            with mock.patch.object(
                macos_dev_host,
                "run_best_effort",
                return_value=(124, "command timed out after 5s"),
            ):
                status = macos_dev_host.query_tcc_database("dev.telemachus.display", database_path)

        self.assertFalse(status.readable)
        self.assertIn("timed out", status.error or "")

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
