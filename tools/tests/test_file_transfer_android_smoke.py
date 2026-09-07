from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.file_transfer_android_smoke import derive_gate, main


def file_transfer_control_bar_success_log() -> str:
    return (
        "Starting 2 tests on P0110 - 16\n\n"
        "dev.telemachus.display.ControlBarLayoutInstrumentedTest#"
        "fileTransferControlPreservesTouchTargetsWhenVisible: PASSED\n"
        "dev.telemachus.display.ControlBarLayoutInstrumentedTest#"
        "productionApplierCoversStackedColumnAndHiddenSelectorBoundaries: PASSED\n\n"
        "OK (2 tests)\n"
    )


def file_transfer_dialog_success_log() -> str:
    return (
        "Starting 3 tests on P0110 - 16\n\n"
        "09-07 19:45:49.660 I TestRunner: started: "
        "narrowAndLargeFontOfferDialogKeepsDecisionContentReadableAndScrollable"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n"
        "09-07 19:45:49.713 I TestRunner: finished: "
        "narrowAndLargeFontOfferDialogKeepsDecisionContentReadableAndScrollable"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n"
        "09-07 19:45:49.617 I TestRunner: started: "
        "offerLayoutKeepsDecisionCopyStructuredForDialogButtons"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n"
        "09-07 19:45:49.658 I TestRunner: finished: "
        "offerLayoutKeepsDecisionCopyStructuredForDialogButtons"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n"
        "09-07 19:45:49.715 I TestRunner: started: "
        "outgoingConfirmationLayoutKeepsPreflightDetailsReadableAndScrollable"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n"
        "09-07 19:45:49.759 I TestRunner: finished: "
        "outgoingConfirmationLayoutKeepsPreflightDetailsReadableAndScrollable"
        "(dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest)\n\n"
        "Tests run: 3,  Failures: 0,  Errors: 0\n"
        "Finished 3 tests on P0110 - 16\n"
        "BUILD SUCCESSFUL in 22s\n"
    )


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def host_readiness(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "vibescreen.host-readiness/v1",
        "kind": "macos_host_shared_prerequisite_readiness",
        "status": "pass",
        "can_close_runtime_gates": True,
        "blockers": [],
    }
    document.update(overrides)
    return document


def usb_preflight(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_smoke_preflight",
        "result": "pass",
        "device": {
            "identity": {
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": 36,
            }
        },
        "claims": {"can_start_usb_smoke": True},
        "blockers": [],
    }
    document.update(overrides)
    return document


def lan_preflight(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "trusted_lan_preflight",
        "result": "pass",
        "blockers": [],
    }
    document.update(overrides)
    return document


def product_e2e(**overrides: object) -> dict[str, object]:
    android_to_macos_payload = b"p0110 android-to-macos payload\n"
    macos_to_android_payload = b"p0110 macos-to-android payload\n"
    direction = {
        "transport": "usb",
        "protocol_v1_session": True,
        "file_offer_observed": True,
        "receiver_request_observed": True,
        "content_chunks_observed": True,
        "source_file_read": True,
        "explicit_user_action": True,
        "receiver_approved": True,
        "remote_file_written": True,
        "session_id_verified": True,
        "final_sha256_match": True,
        "session_epoch_verified": True,
        "transfer_id_verified": True,
        "progress_observed": True,
        "source_endpoint_verified": True,
        "destination_endpoint_verified": True,
        "file_name": "vibe-screen-smoke.txt",
        "byte_length": len(android_to_macos_payload),
        "sha256": hashlib.sha256(android_to_macos_payload).hexdigest(),
        "transfer_id_hex": "00112233445566778899aabbccddeeff",
        "session_epoch": 7,
        "source_endpoint": "android_saf_selected_file",
        "destination_endpoint": "macos_saved_file",
        "retained_artifacts": [
            {"role": "sender_action", "path": "android-to-macos/sender-action.txt"},
            {"role": "receiver_approval", "path": "android-to-macos/receiver-approval.txt"},
            {"role": "protocol_packets", "path": "android-to-macos/protocol-packets.jsonl"},
            {"role": "remote_file", "path": "android-to-macos/remote-file.bin"},
            {"role": "sha256_verification", "path": "android-to-macos/sha256-verification.txt"},
        ],
    }
    macos_to_android = dict(direction)
    macos_to_android["file_name"] = "vibe-screen-smoke-macos-to-android.txt"
    macos_to_android["byte_length"] = len(macos_to_android_payload)
    macos_to_android["sha256"] = hashlib.sha256(macos_to_android_payload).hexdigest()
    macos_to_android["transfer_id_hex"] = "ffeeddccbbaa99887766554433221100"
    macos_to_android["source_endpoint"] = "macos_selected_file"
    macos_to_android["destination_endpoint"] = "android_downloads_file"
    macos_to_android["retained_artifacts"] = [
        {"role": "sender_action", "path": "macos-to-android/sender-action.txt"},
        {"role": "receiver_approval", "path": "macos-to-android/receiver-approval.txt"},
        {"role": "protocol_packets", "path": "macos-to-android/protocol-packets.jsonl"},
        {"role": "remote_file", "path": "macos-to-android/remote-file.bin"},
        {"role": "sha256_verification", "path": "macos-to-android/sha256-verification.txt"},
    ]
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_macos_file_transfer_product_e2e",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
        },
        "synthetic": False,
        "offline_only": False,
        "cancel_cleanup": {
            "cancel_requested": True,
            "cancel_acknowledged": True,
            "partial_file_removed_or_quarantined": True,
            "sender_state_cleared": True,
            "receiver_state_cleared": True,
            "retained_artifacts": [
                {"role": "cancel_request", "path": "cancel-cleanup/cancel-request.txt"},
                {"role": "cleanup_state", "path": "cancel-cleanup/cleanup-state.txt"},
            ],
        },
        "directions": {
            "android_to_macos_file_transfer": dict(direction),
            "macos_to_android_file_transfer": macos_to_android,
        },
    }
    document.update(overrides)
    return document


def write_pass_inputs(root: Path) -> dict[str, Path]:
    paths = {
        "host": root / "host-readiness.json",
        "usb": root / "usb-smoke-preflight.json",
        "lan": root / "trusted-lan-preflight.json",
        "android_log": root / "android-file-transfer-instrumentation.txt",
        "product": root / "file-transfer-product-e2e.json",
    }
    write_json(paths["host"], host_readiness())
    write_json(paths["usb"], usb_preflight())
    write_json(paths["lan"], lan_preflight())
    paths["android_log"].write_text(file_transfer_control_bar_success_log(), encoding="utf-8")
    write_json(paths["product"], product_e2e())
    for artifact_path in (
        "android-to-macos/sender-action.txt",
        "android-to-macos/receiver-approval.txt",
        "android-to-macos/protocol-packets.jsonl",
        "android-to-macos/sha256-verification.txt",
        "macos-to-android/sender-action.txt",
        "macos-to-android/receiver-approval.txt",
        "macos-to-android/protocol-packets.jsonl",
        "macos-to-android/sha256-verification.txt",
        "cancel-cleanup/cancel-request.txt",
        "cancel-cleanup/cleanup-state.txt",
    ):
        path = root / artifact_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"retained product artifact: {artifact_path}\n", encoding="utf-8")
    (root / "android-to-macos" / "remote-file.bin").write_bytes(b"p0110 android-to-macos payload\n")
    (root / "macos-to-android" / "remote-file.bin").write_bytes(b"p0110 macos-to-android payload\n")
    return paths


class FileTransferAndroidSmokeGateTests(unittest.TestCase):
    def test_missing_product_e2e_keeps_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["product"].unlink()

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_closed"])
        self.assertIn("bidirectional_product_e2e: missing product E2E evidence: file-transfer-product-e2e.json", result["blockers"])
        self.assertIn("cancel_cleanup: missing product E2E evidence: file-transfer-product-e2e.json", result["blockers"])
        self.assertTrue(result["safety"]["offline_tests_do_not_close_gate"])

    def test_preflight_blockers_propagate_without_closing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["host"],
                host_readiness(
                    status="blocked",
                    can_close_runtime_gates=False,
                    blockers=["installed Host lacks source commit/tree provenance"],
                ),
            )
            write_json(
                paths["lan"],
                lan_preflight(result="blocked", blockers=["android_wifi_association: Wi-Fi is not associated"]),
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("host_readiness: installed Host lacks source commit/tree provenance", result["blockers"])
        lan_gate = next(item for item in result["checks"] if item["name"] == "trusted_lan_preflight")
        self.assertIn("android_wifi_association: Wi-Fi is not associated", lan_gate["reasons"])

    def test_one_ready_real_transport_is_enough_for_transport_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["lan"],
                lan_preflight(result="blocked", blockers=["android_wifi_association: Wi-Fi is not associated"]),
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        transport_gate = next(item for item in result["checks"] if item["name"] == "real_transport_ready")
        self.assertEqual(transport_gate["status"], "pass")
        lan_gate = next(item for item in result["checks"] if item["name"] == "trusted_lan_preflight")
        self.assertEqual(lan_gate["status"], "blocked")

    def test_product_e2e_must_use_ready_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["lan"],
                lan_preflight(result="blocked", blockers=["android_wifi_association: Wi-Fi is not associated"]),
            )
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["transport"] = "trusted_lan"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.transport trusted_lan is not ready",
            result["blockers"],
        )

    def test_android_log_requires_unittest_ok_summary_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "debug: OK (not a test summary)\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show an OK result",
            result["blockers"],
        )
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show any executed tests",
            result["blockers"],
        )

    def test_android_log_rejects_zero_executed_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "test session start\nOK (0 tests)\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show any executed tests",
            result["blockers"],
        )
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show an OK result",
            result["blockers"],
        )

    def test_android_log_rejects_missing_ok_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "BUILD SUCCESSFUL in 1s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show any executed tests",
            result["blockers"],
        )
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show an OK result",
            result["blockers"],
        )

    def test_android_log_accepts_crlf_ok_summary_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "test session start\r\n"
                "dev.telemachus.display.ControlBarLayoutInstrumentedTest:..\r\n"
                "OK (2 tests)\r\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        android_gate = next(
            item for item in result["checks"] if item["name"] == "android_file_transfer_smoke"
        )
        self.assertEqual(android_gate["status"], "pass")

    def test_android_log_accepts_file_transfer_dialog_method_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(file_transfer_dialog_success_log(), encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        android_gate = next(
            item for item in result["checks"] if item["name"] == "android_file_transfer_smoke"
        )
        self.assertEqual(android_gate["status"], "pass")

    def test_android_log_accepts_later_file_transfer_class_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "dev.telemachus.display.SettingsDialogLayoutInstrumentedTest:.\n"
                "Tests run: 1,  Failures: 0,  Errors: 0\n"
                "dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest:..\n"
                "Tests run: 2,  Failures: 0,  Errors: 0\n"
                "Finished 2 tests on P0110 - 16\n"
                "BUILD SUCCESSFUL in 12s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        android_gate = next(
            item for item in result["checks"] if item["name"] == "android_file_transfer_smoke"
        )
        self.assertEqual(android_gate["status"], "pass")

    def test_android_log_rejects_unrelated_instrumentation_ok_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "Starting 2 tests on P0110 - 16\n\n"
                "dev.telemachus.display.SettingsDialogLayoutInstrumentedTest:..\n\n"
                "OK (2 tests)\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log must name a "
            "file-transfer UI smoke class and either list an expected file-transfer method or show "
            "at least 2 executed tests",
            result["blockers"],
        )
        self.assertNotIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log does not show an OK result",
            result["blockers"],
        )

    def test_android_log_rejects_failure_summary_even_with_file_transfer_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest:.F\n\n"
                "FAILURES!!!\n"
                "Tests run: 2,  Failures: 1,  Errors: 0\n"
                "BUILD FAILED in 12s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log contains a failure result",
            result["blockers"],
        )

    def test_android_log_rejects_later_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "dev.telemachus.display.SettingsDialogLayoutInstrumentedTest:.\n"
                "Tests run: 1,  Failures: 0,  Errors: 0\n"
                "dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest:.F\n"
                "Tests run: 2,  Failures: 1,  Errors: 0\n"
                "Finished 2 tests on P0110 - 16\n"
                "BUILD SUCCESSFUL in 12s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log contains a failure result",
            result["blockers"],
        )

    def test_android_log_rejects_file_transfer_class_warning_with_unrelated_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "W/TestRunner: dev.telemachus.display.ControlBarLayoutInstrumentedTest not found, ignoring\n"
                "dev.telemachus.display.SettingsDialogLayoutInstrumentedTest:..\n\n"
                "OK (2 tests)\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log must name a "
            "file-transfer UI smoke class and either list an expected file-transfer method or show "
            "at least 2 executed tests",
            result["blockers"],
        )

    def test_android_log_rejects_skipped_file_transfer_smoke_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "dev.telemachus.display.ControlBarLayoutInstrumentedTest#"
                "fileTransferControlPreservesTouchTargetsWhenVisible: SKIPPED\n"
                "dev.telemachus.display.ControlBarLayoutInstrumentedTest#"
                "productionApplierCoversStackedColumnAndHiddenSelectorBoundaries: PASSED\n\n"
                "OK (1 test)\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_file_transfer_smoke: Android file-transfer instrumentation log contains a "
            "skipped or failed file-transfer smoke method",
            result["blockers"],
        )

    def test_missing_device_identity_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["usb"], {"kind": "android_usb_smoke_preflight", "result": "pass", "claims": {"can_start_usb_smoke": True}})
            document = product_e2e()
            document.pop("device")
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "device_identity: missing real P0110 device identity evidence from USB, trusted-LAN, or product evidence",
            result["blockers"],
        )

    def test_product_e2e_requires_offer_request_content_and_hex_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["file_offer_observed"] = False
            android_to_macos.pop("receiver_request_observed")
            android_to_macos["content_chunks_observed"] = False
            android_to_macos["sha256"] = "not-a-sha"
            android_to_macos["transfer_id_hex"] = "not-a-transfer-id"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("bidirectional_product_e2e: android_to_macos_file_transfer.file_offer_observed must be true", result["blockers"])
        self.assertIn("bidirectional_product_e2e: android_to_macos_file_transfer.receiver_request_observed must be true", result["blockers"])
        self.assertIn("bidirectional_product_e2e: android_to_macos_file_transfer.content_chunks_observed must be true", result["blockers"])
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.sha256 must be a 64-character hex SHA-256 digest",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.transfer_id_hex must be a 32-character hex transfer ID",
            result["blockers"],
        )

    def test_product_e2e_requires_exact_file_endpoints_session_id_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            macos_to_android = directions["macos_to_android_file_transfer"]
            assert isinstance(android_to_macos, dict)
            assert isinstance(macos_to_android, dict)
            android_to_macos["source_endpoint"] = "android_app_private_fixture"
            android_to_macos["destination_endpoint"] = "macos_temp_fixture"
            android_to_macos["source_endpoint_verified"] = False
            android_to_macos["destination_endpoint_verified"] = False
            android_to_macos["session_id_verified"] = False
            android_to_macos["progress_observed"] = False
            android_to_macos["transfer_id_verified"] = False
            macos_to_android["byte_length"] = True
            macos_to_android["session_epoch"] = True
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.source_endpoint must be android_saf_selected_file",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.destination_endpoint must be macos_saved_file",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.source_endpoint_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.destination_endpoint_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.session_id_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.progress_observed must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.transfer_id_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_to_android_file_transfer.byte_length must be a positive integer",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_to_android_file_transfer.session_epoch must be a positive integer",
            result["blockers"],
        )

    def test_product_e2e_requires_distinct_direction_transfer_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["transfer_id_hex"] = "00112233445566778899aabbccddeeff"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: direction transfer IDs must be distinct so one file exchange cannot satisfy both directions",
            result["blockers"],
        )

    def test_product_e2e_requires_distinct_direction_file_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["file_name"] = "same-file.txt"
                direction["sha256"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: direction SHA-256 digests must be distinct so one file payload cannot satisfy both directions",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: direction file names must be distinct so one file exchange cannot satisfy both directions",
            result["blockers"],
        )

    def test_product_e2e_requires_retained_direction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["retained_artifacts"] = [
                {"role": "sender_action", "path": "/tmp/sender-action.txt"},
                {"role": "receiver_approval", "path": "../receiver-approval.txt"},
                {"role": "protocol_packets", "path": "missing/protocol-packets.jsonl"},
            ]
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[0].path must be evidence-relative",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[1].path must stay inside the evidence bundle",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[2].path missing retained artifact missing/protocol-packets.jsonl",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts missing remote_file artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts missing sha256_verification artifact",
            result["blockers"],
        )

    def test_retained_artifact_symlink_escape_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            parent = Path(directory_name)
            root = parent / "evidence"
            outside = parent / "outside.txt"
            outside.write_text("outside retained artifact\n", encoding="utf-8")
            paths = write_pass_inputs(root)
            symlink = root / "android-to-macos" / "sender-action-link.txt"
            symlink.unlink(missing_ok=True)
            symlink.symlink_to(outside)

            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            sender_artifact = retained_artifacts[0]
            assert isinstance(sender_artifact, dict)
            sender_artifact["path"] = "android-to-macos/sender-action-link.txt"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[0].path must stay inside the evidence bundle",
            result["blockers"],
        )

    def test_retained_artifacts_must_be_non_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text("", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[2].path retained artifact android-to-macos/protocol-packets.jsonl must be non-empty",
            result["blockers"],
        )

    def test_remote_file_artifact_size_must_match_direction_byte_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "remote-file.bin").write_bytes(b"wrong-size")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(
            any(
                blocker.startswith(
                    "bidirectional_product_e2e: android_to_macos_file_transfer.remote_file artifact size 10 must equal byte_length "
                )
                for blocker in result["blockers"]
            ),
            result["blockers"],
        )

    def test_remote_file_artifact_sha256_must_match_direction_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            payload = bytearray((root / "android-to-macos" / "remote-file.bin").read_bytes())
            payload[-2] = ord("X")
            (root / "android-to-macos" / "remote-file.bin").write_bytes(payload)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.remote_file artifact SHA-256 must equal direction.sha256",
            result["blockers"],
        )

    def test_retained_artifact_paths_must_be_distinct_per_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            receiver_artifact = retained_artifacts[1]
            assert isinstance(receiver_artifact, dict)
            receiver_artifact["path"] = "android-to-macos/sender-action.txt"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[1].path must be distinct from sender_action artifact path",
            result["blockers"],
        )

    def test_retained_artifact_paths_must_be_distinct_across_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            macos_to_android = directions["macos_to_android_file_transfer"]
            assert isinstance(macos_to_android, dict)
            retained_artifacts = macos_to_android["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            sender_artifact = retained_artifacts[0]
            assert isinstance(sender_artifact, dict)
            sender_artifact["path"] = "android-to-macos/sender-action.txt"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: macos_to_android_file_transfer.retained_artifacts[0].path for sender_action must be distinct from android_to_macos_file_transfer sender_action artifact path",
            result["blockers"],
        )

    def test_cancel_cleanup_artifacts_must_be_distinct_from_direction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            cancel_cleanup = document["cancel_cleanup"]
            assert isinstance(cancel_cleanup, dict)
            retained_artifacts = cancel_cleanup["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            cleanup_artifact = retained_artifacts[1]
            assert isinstance(cleanup_artifact, dict)
            cleanup_artifact["path"] = "android-to-macos/sender-action.txt"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "cancel_cleanup: cancel_cleanup.retained_artifacts[1].path for cleanup_state must be distinct from android_to_macos_file_transfer sender_action artifact path",
            result["blockers"],
        )

    def test_retained_artifact_roles_must_be_exact_and_unique_per_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            unknown_artifact = retained_artifacts[0]
            duplicate_artifact = retained_artifacts[2]
            assert isinstance(unknown_artifact, dict)
            assert isinstance(duplicate_artifact, dict)
            unknown_artifact["role"] = "transfer_summary"
            duplicate_artifact["role"] = "receiver_approval"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[0].role must be one of sender_action, receiver_approval, protocol_packets, remote_file, sha256_verification",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[2].role duplicates receiver_approval artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts missing sender_action artifact",
            result["blockers"],
        )

    def test_cancel_cleanup_requires_retained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            cancel_cleanup = document["cancel_cleanup"]
            assert isinstance(cancel_cleanup, dict)
            cancel_cleanup["retained_artifacts"] = []
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "cancel_cleanup: cancel_cleanup.retained_artifacts must retain product evidence artifacts",
            result["blockers"],
        )

    def test_cancel_cleanup_artifact_roles_must_be_exact_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            cancel_cleanup = document["cancel_cleanup"]
            assert isinstance(cancel_cleanup, dict)
            retained_artifacts = cancel_cleanup["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            unknown_artifact = retained_artifacts[1]
            assert isinstance(unknown_artifact, dict)
            unknown_artifact["role"] = "cleanup_summary"
            retained_artifacts.append({"role": "cancel_request", "path": "cancel-cleanup/cancel-request-copy.txt"})
            (root / "cancel-cleanup" / "cancel-request-copy.txt").write_text(
                "retained product artifact: cancel-cleanup/cancel-request-copy.txt\n",
                encoding="utf-8",
            )
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "cancel_cleanup: cancel_cleanup.retained_artifacts[1].role must be one of cancel_request, cleanup_state",
            result["blockers"],
        )
        self.assertIn(
            "cancel_cleanup: cancel_cleanup.retained_artifacts[2].role duplicates cancel_request artifact",
            result["blockers"],
        )
        self.assertIn(
            "cancel_cleanup: cancel_cleanup.retained_artifacts missing cleanup_state artifact",
            result["blockers"],
        )

    def test_synthetic_product_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], product_e2e(synthetic=True))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("bidirectional_product_e2e: synthetic or offline-only file-transfer evidence cannot close this gate", result["blockers"])

    def test_complete_bidirectional_product_e2e_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["gate_closed"])
        self.assertEqual(result["not_proven"], [])

    def test_p0110_identity_guard_rejects_xiaomi_relabel(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["product"],
                product_e2e(
                    device={
                        "manufacturer": "xiaomi",
                        "model": "P0110",
                        "codename": "fuxi",
                        "android_release": "16",
                        "sdk": 36,
                    }
                ),
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "fail")
        identity_gate = next(item for item in result["checks"] if item["name"] == "device_identity")
        self.assertIn("file-transfer evidence for this run must identify nubia P0110 / pacific", identity_gate["reasons"])

    def test_output_redacts_serial_home_and_tcc_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            raw_serial = "EP" + "0" * 14
            user_path = "/Users/" + "exampleuser"
            tcc_path = "Application Support/" + "com.apple" + ".TCC/" + "TCC" + ".db"
            write_json(
                paths["host"],
                host_readiness(
                    status="blocked",
                    can_close_runtime_gates=False,
                    blockers=[f"serial {raw_serial} path {user_path}/Library/{tcc_path}"],
                ),
            )

            output = root / "gate.json"
            exit_code = main(
                [
                    "--host-readiness",
                    str(paths["host"]),
                    "--usb-preflight",
                    str(paths["usb"]),
                    "--trusted-lan-preflight",
                    str(paths["lan"]),
                    "--android-file-transfer-instrumentation-log",
                    str(paths["android_log"]),
                    "--product-e2e",
                    str(paths["product"]),
                    "--serial",
                    raw_serial,
                    "--output",
                    str(output),
                ]
            )
            text = output.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 2)
        self.assertNotIn(raw_serial, text)
        self.assertNotIn(user_path, text)
        self.assertNotIn(tcc_path.rsplit("/", 1)[0], text)
        self.assertNotIn(tcc_path.rsplit("/", 1)[1], text)


if __name__ == "__main__":
    unittest.main()
