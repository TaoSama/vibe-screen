from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.revocation_propagation_verifier import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    SCHEMA,
    VerificationError,
    main,
    verify_report,
)


class RevocationPropagationVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def report_path(self, payload: dict[str, object]) -> Path:
        path = Path(self.tempdir.name) / "report.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def complete_report(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "observed_at": "2026-08-21T00:00:00Z",
            "source": {
                "commit": "30520507",
                "topology": "staging",
                "authority_url_kind": "https",
                "coturn_source_id": "turn-prod-1",
                "deployment_id": "revocation-propagation-staging-1",
            },
            "authority_revocation": {
                "device_revoked": True,
                "session_revoked": True,
                "revocation_status": 204,
                "audit_event_observed": True,
            },
            "signaling": {
                "active_session_rejected": True,
                "rejection_status": 404,
                "long_poll_woke_fail_closed": True,
            },
            "relay_admission": {
                "new_grant_rejected": True,
                "new_grant_status": 403,
                "same_allocation_retry_rejected": True,
                "same_allocation_retry_status": 403,
                "stale_grant_reuse_rejected": True,
                "stale_grant_status": 486,
                "grant_ttl_seconds": 60,
            },
            "coturn_allocation": {
                "active_before_revocation": True,
                "allocation_id": "allocation-before-revoke",
                "disconnect_observed": True,
                "disconnect_method": "coturn-admin-delete-allocation",
                "disconnect_observed_at": "2026-08-21T00:00:05Z",
            },
            "data_plane": {
                "traffic_established_before_revocation": True,
                "post_revocation_traffic_denied": True,
                "relayed_packets_after_revocation": 0,
                "denial_observed_at": "2026-08-21T00:00:06Z",
            },
            "notes": ["synthetic report used by unit tests"],
        }

    def test_complete_report_passes(self) -> None:
        result = verify_report(self.complete_report())
        self.assertEqual(result.status, PASS)
        self.assertEqual(result.missing, ())
        self.assertEqual(result.failures, ())

    def test_missing_active_disconnect_blocks_release_gate(self) -> None:
        report = self.complete_report()
        report["source"] = dict(report["source"], topology="blocked")
        report["coturn_allocation"] = {
            "active_before_revocation": True,
            "allocation_id": "allocation-before-revoke",
        }

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("active coturn allocation disconnect", result.missing)
        self.assertEqual(result.failures, ())

    def test_missing_stale_credential_reuse_blocks_release_gate(self) -> None:
        report = self.complete_report()
        report["relay_admission"] = {
            "new_grant_rejected": True,
            "new_grant_status": 403,
            "same_allocation_retry_rejected": True,
            "same_allocation_retry_status": 403,
            "grant_ttl_seconds": 60,
        }

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("stale TURN credential reuse rejection", result.missing)

    def test_post_revocation_relayed_packets_fail(self) -> None:
        report = self.complete_report()
        report["data_plane"] = {
            "traffic_established_before_revocation": True,
            "post_revocation_traffic_denied": False,
            "relayed_packets_after_revocation": 3,
        }

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn("post-revocation data-plane traffic denial", result.failures)
        self.assertIn("post-revocation relayed packet count must be zero", result.failures)

    def test_secret_fields_are_rejected_before_evaluation(self) -> None:
        report = self.complete_report()
        report["relay_admission"] = dict(report["relay_admission"], password="do-not-store")
        path = self.report_path(report)

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--report", str(path)]), 2)

    def test_secret_like_field_suffixes_are_rejected(self) -> None:
        report = self.complete_report()
        report["notes"] = [{"access_token": "do-not-store"}]
        path = self.report_path(report)

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--report", str(path)]), 2)

    def test_unknown_fields_are_rejected(self) -> None:
        report = self.complete_report()
        report["coturn_allocation"] = dict(report["coturn_allocation"], raw_log="not accepted")
        with self.assertRaisesRegex(VerificationError, "unknown fields"):
            verify_report(report)

    def test_cli_writes_blocked_summary_and_exit_code(self) -> None:
        report = self.complete_report()
        report["coturn_allocation"] = {
            "active_before_revocation": True,
            "allocation_id": "allocation-before-revoke",
        }
        report_path = self.report_path(report)
        summary_path = Path(self.tempdir.name) / "summary.json"

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main(["--report", str(report_path), "--write-summary", str(summary_path)])

        self.assertEqual(exit_code, 4)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], BLOCKED)
        self.assertIn("active coturn allocation disconnect", summary["missing"])

    def test_cli_returns_failure_status_for_observed_traffic_after_revoke(self) -> None:
        report = self.complete_report()
        report["data_plane"] = {
            "traffic_established_before_revocation": True,
            "post_revocation_traffic_denied": True,
            "relayed_packets_after_revocation": 1,
        }
        report_path = self.report_path(report)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--report", str(report_path)]), 1)

    def test_missing_authority_audit_event_blocks_release_gate(self) -> None:
        report = self.complete_report()
        del report["authority_revocation"]["audit_event_observed"]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("authority revocation audit event", result.missing)

    def test_missing_long_poll_wakeup_blocks_release_gate(self) -> None:
        report = self.complete_report()
        del report["signaling"]["long_poll_woke_fail_closed"]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("signaling long-poll wakeup fail-closed", result.missing)

    def test_same_allocation_retry_after_revoke_is_required(self) -> None:
        report = self.complete_report()
        del report["relay_admission"]["same_allocation_retry_rejected"]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("post-revocation same allocation credential retry rejection", result.missing)


if __name__ == "__main__":
    unittest.main()
