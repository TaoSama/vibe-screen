from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr

from scripts.phase3.session_authority_readiness import (
    BLOCKED,
    FAIL,
    PASS,
    SCHEMA,
    VerificationError,
    main,
    verify_report,
)


def complete_report() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "observed_at": "2026-08-25T00:00:00Z",
        "source": {
            "commit": "b07600d999bd2c4eb5a11a08459e87b9afc568f4",
            "tree_status": "clean",
            "deployment_id": "authority-auto-issuance-current-base",
            "profile_endpoint": "product_authority",
        },
        "product_flow": {
            "authority_profile_endpoint_called_by_product_flow": True,
            "operator_manual_profile_copy": False,
            "manual_unsigned_lease_file_transfer": False,
            "user_visible_pairing_or_session_flow": True,
            "product_flow_artifact_hash": "sha256:" + "a" * 64,
        },
        "account_device": {
            "account_registered_by_product_flow": True,
            "device_registered_by_product_flow": True,
            "account_device_binding_observed": True,
            "authority_audit_event_observed": True,
        },
        "authority": {
            "profile_created_or_replayed": True,
            "request_digest_bound": True,
            "strict_replay_rejected": True,
            "session_epoch_monotonic": True,
            "session_ttl_seconds": 600,
            "unsigned_lease_returned_to_product_flow": True,
        },
        "mac_signer": {
            "signed_authority_supplied_epoch": True,
            "local_high_water_mark_reserved": True,
            "mismatched_epoch_rejected": True,
            "host_identity_bound": True,
            "signature_observed_by_product_flow": True,
        },
        "android_import": {
            "signed_lease_imported_by_product_flow": True,
            "host_signature_verified": True,
            "session_epoch_accepted": True,
            "manual_import_ui_used": False,
        },
        "signaling": {
            "host_role_authorized": True,
            "client_role_authorized": True,
            "cross_role_token_rejected": True,
            "expired_session_rejected": True,
        },
        "turn": {
            "present": True,
            "authority_or_relay_issued_short_lived": True,
            "static_turn_password_in_product": False,
            "credential_ttl_seconds": 600,
            "rotation_or_expiry_observed": True,
        },
        "privacy": {
            "raw_tokens_recorded": False,
            "raw_credentials_recorded": False,
            "raw_device_identifiers_recorded": False,
            "operator_paths_recorded": False,
        },
        "notes": ["sanitized current-base fixture"],
    }


def fake_bearer_header_fixture() -> str:
    return "Authorization: " + "Bearer fixture-not-a-real-token"


class SessionAuthorityReadinessTests(unittest.TestCase):
    def test_complete_product_flow_passes(self) -> None:
        result = verify_report(complete_report())
        self.assertEqual(result.status, PASS)
        self.assertEqual(result.blockers, ())
        self.assertEqual(result.failures, ())

    def test_manual_operator_copy_blocks_even_when_authority_control_plane_passes(self) -> None:
        report = complete_report()
        report["product_flow"]["authority_profile_endpoint_called_by_product_flow"] = False  # type: ignore[index]
        report["product_flow"]["operator_manual_profile_copy"] = True  # type: ignore[index]
        report["product_flow"]["manual_unsigned_lease_file_transfer"] = True  # type: ignore[index]
        report["android_import"]["manual_import_ui_used"] = True  # type: ignore[index]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("operator manual profile copy is still required", result.blockers)
        self.assertIn("manual unsigned lease transfer is still required", result.blockers)
        self.assertIn("manual Android import UI was still used", result.blockers)

    def test_static_turn_password_is_fail_not_readiness_blocker(self) -> None:
        report = complete_report()
        report["turn"]["static_turn_password_in_product"] = True  # type: ignore[index]

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn("static TURN password is present in product flow", result.failures)

    def test_missing_account_registration_is_blocked(self) -> None:
        report = complete_report()
        del report["account_device"]["account_registered_by_product_flow"]  # type: ignore[index]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("account registration was not product-driven", result.missing)

    def test_rejects_secret_like_fields_and_values(self) -> None:
        report = complete_report()
        report["authority"]["signaling_token"] = "<redacted>"  # type: ignore[index]
        with self.assertRaisesRegex(VerificationError, "secret material"):
            verify_report(report)

        report = complete_report()
        report["notes"] = [fake_bearer_header_fixture()]
        with self.assertRaisesRegex(VerificationError, "secret material"):
            verify_report(report)

    def test_cli_writes_blocked_summary_with_distinct_exit_code(self) -> None:
        report = complete_report()
        report["product_flow"]["operator_manual_profile_copy"] = True  # type: ignore[index]
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            report_path = directory / "report.json"
            summary_path = directory / "summary.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["--report", str(report_path), "--write-summary", str(summary_path)])

            self.assertEqual(exit_code, 4)
            self.assertIn("BLOCKED", stderr.getvalue())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], BLOCKED)
            self.assertEqual(summary_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
