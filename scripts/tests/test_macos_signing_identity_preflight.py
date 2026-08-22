from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import macos_signing_identity_preflight as preflight


class MacOSSigningIdentityPreflightTests(unittest.TestCase):
    def host_snapshot(self) -> dict[str, object]:
        return {
            "path": "/Applications/Vibe Screen.app",
            "inspected": False,
            "error": "Host bundle not found",
            "tcc_readable": True,
            "tcc_error": None,
            "tcc_interpretation": "Screen Recording not allowed; Accessibility not allowed.",
            "tcc_rows": [],
        }

    def test_parse_identities_extracts_names_and_count(self) -> None:
        output = """
  1) 0123456789abcdef0123456789ABCDEF01234567 "Vibe Screen Dev"
  2) ABCDEF0123456789ABCDEF0123456789ABCDEF01 "Other Dev"
     2 valid identities found
"""

        identities, count = preflight.parse_identities(output)

        self.assertEqual(count, 2)
        self.assertEqual(identities[0].sha1, "0123456789ABCDEF0123456789ABCDEF01234567")
        self.assertEqual(identities[0].name, "Vibe Screen Dev")
        self.assertEqual(identities[1].name, "Other Dev")

    def test_missing_identity_is_blocked_with_next_steps(self) -> None:
        result = preflight.CommandResult(
            argv=["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
            returncode=0,
            output_line_count=1,
            stderr="",
            raw_output="     0 valid identities found\n",
        )

        with (
            mock.patch.object(preflight, "run_security_find_identity", return_value=result),
            mock.patch.object(preflight, "collect_installed_host", return_value=self.host_snapshot()),
        ):
            report = preflight.collect_preflight("Vibe Screen Dev", created_at="2026-08-21T00:00:00Z")

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.valid_identity_count, 0)
        self.assertEqual(report.matching_identities, [])
        self.assertIn("not found", "\n".join(report.blockers))
        self.assertIn("VIBE_SCREEN_SIGN_IDENTITY", "\n".join(report.next_steps))

    def test_duplicate_identity_is_blocked(self) -> None:
        result = preflight.CommandResult(
            argv=["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
            returncode=0,
            output_line_count=3,
            stderr="",
            raw_output=(
                '  1) 1111111111111111111111111111111111111111 "Vibe Screen Dev"\n'
                '  2) 2222222222222222222222222222222222222222 "Vibe Screen Dev"\n'
                "     2 valid identities found\n"
            ),
        )

        with (
            mock.patch.object(preflight, "run_security_find_identity", return_value=result),
            mock.patch.object(preflight, "collect_installed_host", return_value=self.host_snapshot()),
        ):
            report = preflight.collect_preflight("Vibe Screen Dev", created_at="2026-08-21T00:00:00Z")

        self.assertEqual(report.status, "blocked")
        self.assertEqual(len(report.matching_identities), 2)
        self.assertIn("duplicate", "\n".join(report.blockers))

    def test_single_identity_passes_and_writes_reports(self) -> None:
        result = preflight.CommandResult(
            argv=["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
            returncode=0,
            output_line_count=2,
            stderr="",
            raw_output=(
                '  1) 1111111111111111111111111111111111111111 "Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                mock.patch.object(preflight, "run_security_find_identity", return_value=result),
                mock.patch.object(preflight, "collect_installed_host", return_value=self.host_snapshot()),
            ):
                report = preflight.collect_preflight("Vibe Screen Dev", created_at="2026-08-21T00:00:00Z")
            preflight.write_reports(Path(temporary_directory), report)

            self.assertEqual(report.status, "pass")
            self.assertEqual(report.matching_identities[0].sha1, "1111111111111111111111111111111111111111")
            json_report = (Path(temporary_directory) / "signing-identity-preflight.json").read_text()
            self.assertIn("\"status\": \"pass\"", json_report)
            self.assertNotIn("raw_output", json_report)
            markdown = (Path(temporary_directory) / "README.md").read_text()
            self.assertIn("Status: pass", markdown)
            self.assertIn("TCC interpretation", markdown)

    def test_collect_installed_host_records_bundle_and_tcc_errors(self) -> None:
        with (
            mock.patch.object(preflight.macos_dev_host, "collect_signing_metadata", side_effect=SystemExit("missing app")),
            mock.patch.object(
                preflight.macos_dev_host,
                "query_tcc_rows",
                return_value=preflight.macos_dev_host.PermissionStatus(
                    "TCC.db",
                    (),
                    False,
                    "/Users/example/Library/Application Support/com.apple.TCC/TCC.db: not readable; "
                    "/Library/Application Support/com.apple.TCC/TCC.db: not readable",
                ),
            ),
            mock.patch.object(
                preflight.macos_dev_host,
                "default_tcc_database",
                return_value=Path("/Users/example/Library/Application Support/com.apple.TCC/TCC.db"),
            ),
        ):
            host = preflight.collect_installed_host(Path("/Applications/Vibe Screen.app"), Path("TCC.db"))

        self.assertFalse(host["inspected"])
        self.assertEqual(host["error"], "missing app")
        self.assertEqual(
            host["tcc_error"],
            "current-user TCC database: not readable; system TCC database: not readable",
        )
        self.assertNotIn("/Users/example", host["tcc_interpretation"])


if __name__ == "__main__":
    unittest.main()
