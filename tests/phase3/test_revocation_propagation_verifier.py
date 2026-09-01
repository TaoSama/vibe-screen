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
from scripts.phase3.release_gate_manifest import (  # noqa: E402
    revocation_summary_to_manifest_gate,
    validate_manifest,
)
from tools.vibescreen_evidence.phase3_internet_soak import _evaluate_revocation  # noqa: E402


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
                "topology": "production",
                "authority_url_kind": "https",
                "coturn_source_id": "turn-prod-1",
                "deployment_id": "revocation-propagation-staging-1",
                "evidence_kind": "live_production",
                "public_internet_path": True,
                "remote_turn_deployment": True,
                "synthetic_fixture": False,
            },
            "authority_revocation": {
                "chain_id": "chain-1",
                "tombstone_id": "tombstone-1",
                "device_revoked": True,
                "session_revoked": True,
                "tombstone_persisted": True,
                "tombstone_persisted_at": "2026-08-21T00:00:00Z",
                "revocation_status": 204,
                "audit_event_observed": True,
            },
            "signaling": {
                "chain_id": "chain-1",
                "rejected_tombstone_id": "tombstone-1",
                "active_session_rejected": True,
                "rejection_status": 404,
                "long_poll_woke_fail_closed": True,
                "rejection_observed_at": "2026-08-21T00:00:01Z",
            },
            "relay_admission": {
                "chain_id": "chain-1",
                "rejected_tombstone_id": "tombstone-1",
                "credential_allocation_id": "allocation-before-revoke",
                "new_grant_rejected": True,
                "new_grant_status": 403,
                "same_allocation_retry_rejected": True,
                "same_allocation_retry_status": 403,
                "stale_grant_reuse_rejected": True,
                "stale_grant_status": 486,
                "grant_ttl_seconds": 60,
                "rejection_observed_at": "2026-08-21T00:00:02Z",
            },
            "coturn_allocation": {
                "chain_id": "chain-1",
                "revoked_tombstone_id": "tombstone-1",
                "active_before_revocation": True,
                "allocation_id": "allocation-before-revoke",
                "disconnect_observed": True,
                "disconnect_method": "coturn-admin-delete-allocation",
                "disconnect_observed_at": "2026-08-21T00:00:05Z",
            },
            "data_plane": {
                "chain_id": "chain-1",
                "rejected_tombstone_id": "tombstone-1",
                "allocation_id": "allocation-before-revoke",
                "traffic_established_before_revocation": True,
                "post_revocation_traffic_denied": True,
                "rejected_after_disconnect": True,
                "relayed_packets_after_revocation": 0,
                "denial_observed_at": "2026-08-21T00:00:06Z",
            },
            "notes": ["synthetic report used by unit tests"],
        }

    def release_manifest_with_revocation_gate(
        self, revocation_gate: dict[str, object]
    ) -> dict[str, object]:
        manifest: dict[str, object] = {
            "schema": "dev.vibescreen.phase3-release-gate-manifest/v1",
            "result": "pass",
            "source": {"commit": "b" * 40, "tree_status": "clean"},
            "device": {
                "manufacturer": "Nubia",
                "model": "P0110",
                "codename": "pacific",
                "os_version": "Android 16",
                "evidence_role": "general_android_substitute",
            },
            "artifacts": {"mac_host_sha256": "a" * 64, "android_apk_sha256": "a" * 64},
            "claims": ["revocation gate fixture"],
            "gates": {},
        }
        gates = manifest["gates"]
        assert isinstance(gates, dict)
        for gate in (
            "public_internet_direct_path",
            "remote_turn_relay_path",
            "real_screencapturekit_to_android_media",
            "network_handoff_recovery",
            "packet_capture_confidentiality",
            "external_camera_latency",
            "webrtc_datachannel_record_layer",
            "two_hour_mixed_route_soak",
        ):
            gates[gate] = {"status": "blocked", "synthetic_media": True}
        gates["cross_service_revocation"] = revocation_gate
        return manifest

    def test_complete_report_passes(self) -> None:
        result = verify_report(self.complete_report())
        self.assertEqual(result.status, PASS)
        self.assertEqual(result.missing, ())
        self.assertEqual(result.failures, ())

    def test_pass_summary_feeds_soak_revocation_check(self) -> None:
        summary = verify_report(self.complete_report()).as_dict()
        reasons: list[str] = []

        result = _evaluate_revocation(summary, reasons)

        self.assertTrue(result["passed"])
        self.assertEqual(reasons, [])

    def test_pass_summary_maps_to_release_manifest_revocation_gate(self) -> None:
        summary = verify_report(self.complete_report()).as_dict()
        revocation_gate = {
            "status": "pass",
            "synthetic_media": False,
            "local_loopback_only": False,
            "usb_transport": False,
            "trusted_lan_only": False,
            "private_network_only": False,
            "same_private_network": False,
            "loopback": False,
            "synthetic_loopback": False,
            "synthetic_peer": False,
            "evidence_files": ["logs/revocation.jsonl"],
        }
        revocation_gate.update(revocation_summary_to_manifest_gate(summary))

        errors = validate_manifest(self.release_manifest_with_revocation_gate(revocation_gate))
        revocation_errors = [error for error in errors if "gates.cross_service_revocation" in error]

        self.assertEqual(revocation_errors, [])

    def test_local_fixture_cannot_pass_as_live_production(self) -> None:
        report = self.complete_report()
        report["source"] = dict(
            report["source"],
            topology="local",
            evidence_kind="offline_fixture",
            public_internet_path=False,
            remote_turn_deployment=False,
            synthetic_fixture=True,
        )

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("live production evidence classification", result.missing)
        self.assertIn("production topology", result.missing)
        self.assertIn("public Internet path evidence", result.missing)
        self.assertIn("remote TURN deployment evidence", result.missing)
        self.assertIn("non-synthetic evidence boundary", result.missing)

    def test_missing_active_disconnect_blocks_release_gate(self) -> None:
        report = self.complete_report()
        report["coturn_allocation"] = {
            "chain_id": "chain-1",
            "revoked_tombstone_id": "tombstone-1",
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
        report["data_plane"] = dict(
            report["data_plane"],
            post_revocation_traffic_denied=False,
            relayed_packets_after_revocation=3,
        )

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
        report["data_plane"] = dict(report["data_plane"], relayed_packets_after_revocation=1)
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

    def test_chain_id_mismatch_fails_closed(self) -> None:
        report = self.complete_report()
        report["signaling"] = dict(report["signaling"], chain_id="chain-2")

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn("signaling.chain_id must match authority_revocation.chain_id", result.failures)

    def test_tombstone_mismatch_fails_closed(self) -> None:
        report = self.complete_report()
        report["relay_admission"] = dict(report["relay_admission"], rejected_tombstone_id="other")

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn(
            "relay_admission.rejected_tombstone_id must match authority_revocation.tombstone_id",
            result.failures,
        )

    def test_allocation_mismatch_fails_closed(self) -> None:
        report = self.complete_report()
        report["data_plane"] = dict(report["data_plane"], allocation_id="other-allocation")

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn(
            "data_plane.allocation_id must match coturn_allocation.allocation_id",
            result.failures,
        )

    def test_out_of_order_chain_timestamps_fail_closed(self) -> None:
        report = self.complete_report()
        report["data_plane"] = dict(
            report["data_plane"], denial_observed_at="2026-08-21T00:00:03Z"
        )

        result = verify_report(report)

        self.assertEqual(result.status, FAIL)
        self.assertIn(
            "post-revocation traffic rejection timestamp must be at or after coturn allocation disconnect timestamp",
            result.failures,
        )

    def test_missing_tombstone_persistence_blocks_release_gate(self) -> None:
        report = self.complete_report()
        del report["authority_revocation"]["tombstone_persisted"]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("authority tombstone persistence", result.missing)

    def test_rejection_after_disconnect_is_required(self) -> None:
        report = self.complete_report()
        del report["data_plane"]["rejected_after_disconnect"]

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("post-revocation traffic rejection after coturn disconnect", result.missing)

    def test_missing_packet_count_summary_does_not_claim_zero_packets(self) -> None:
        report = self.complete_report()
        del report["data_plane"]["relayed_packets_after_revocation"]

        summary = verify_report(report).as_dict()

        self.assertEqual(summary["status"], BLOCKED)
        self.assertIsNone(summary["post_revocation_packet_count_zero"])

    def test_turn_credential_ttl_over_target_warns_without_passing_local_fixture(self) -> None:
        report = self.complete_report()
        report["source"] = dict(report["source"], evidence_kind="local_control_plane")
        report["relay_admission"] = dict(report["relay_admission"], grant_ttl_seconds=120)

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("live production evidence classification", result.missing)
        self.assertIn("TURN credential TTL exceeds the current short-lived exposure target", result.warnings)

    def test_blocked_fixture_summary_retains_chain_schema_gap_instead_of_pass(self) -> None:
        report = self.complete_report()
        report["source"] = {
            "commit": "30520507",
            "topology": "blocked",
            "authority_url_kind": "local-service-tests",
            "evidence_kind": "local_control_plane",
            "coturn_source_id": "turn-node-1",
            "deployment_id": "no-live-coturn-disconnect-or-data-plane-proof",
        }
        report["coturn_allocation"] = {"active_before_revocation": True}
        report["data_plane"] = {}

        result = verify_report(report)

        self.assertEqual(result.status, BLOCKED)
        self.assertIn("live production evidence classification", result.missing)
        self.assertIn("active coturn allocation identity", result.missing)
        self.assertIn("post-revocation traffic rejection chain id", result.missing)
        self.assertEqual(result.failures, ())


if __name__ == "__main__":
    unittest.main()
