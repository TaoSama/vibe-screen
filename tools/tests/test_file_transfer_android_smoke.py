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


def artifact_by_role(direction: dict[str, object], role: str) -> dict[str, object]:
    artifacts = direction["retained_artifacts"]
    assert isinstance(artifacts, list)
    for artifact in artifacts:
        assert isinstance(artifact, dict)
        if artifact.get("role") == role:
            return artifact
    raise AssertionError(f"missing artifact role {role}")


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
            {"role": "source_file", "path": "android-to-macos/source-file.bin"},
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
        {"role": "source_file", "path": "macos-to-android/source-file.bin"},
        {"role": "sender_action", "path": "macos-to-android/sender-action.txt"},
        {"role": "receiver_approval", "path": "macos-to-android/receiver-approval.txt"},
        {"role": "protocol_packets", "path": "macos-to-android/protocol-packets.jsonl"},
        {"role": "remote_file", "path": "macos-to-android/remote-file.bin"},
        {"role": "sha256_verification", "path": "macos-to-android/sha256-verification.txt"},
    ]
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_macos_file_transfer_product_e2e",
        "host_backed_product_session": True,
        "real_macos_host": True,
        "real_android_device": True,
        "same_session_bidirectional_transfer": True,
        "host_readiness_bound_to_session": True,
        "device_identity_bound_to_session": True,
        "destination_file_bytes_retained": True,
        "no_host_ui_only": False,
        "summary_only": False,
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


def write_direction_artifacts(
    root: Path,
    directory: str,
    *,
    payload: bytes,
    source_endpoint: str,
    destination_endpoint: str,
    transfer_id_hex: str,
    session_epoch: int,
    sha256: str,
) -> None:
    direction_dir = root / directory
    direction_dir.mkdir(parents=True, exist_ok=True)
    (direction_dir / "source-file.bin").write_bytes(payload)
    (direction_dir / "remote-file.bin").write_bytes(payload)
    (direction_dir / "sender-action.txt").write_text(
        f"sender_action source={source_endpoint} transfer_id_hex={transfer_id_hex}\n",
        encoding="utf-8",
    )
    (direction_dir / "receiver-approval.txt").write_text(
        f"receiver_approval approved destination={destination_endpoint} transfer_id_hex={transfer_id_hex}\n",
        encoding="utf-8",
    )
    (direction_dir / "protocol-packets.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "event": event,
                    "transfer_id_hex": transfer_id_hex,
                    "session_epoch": session_epoch,
                }
            )
            + "\n"
            for event in ("file_offer", "file_request", "file_chunk", "file_complete")
        ),
        encoding="utf-8",
    )
    (direction_dir / "sha256-verification.txt").write_text(
        f"sha256 verified {sha256}\n",
        encoding="utf-8",
    )


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
    write_direction_artifacts(
        root,
        "android-to-macos",
        payload=b"p0110 android-to-macos payload\n",
        source_endpoint="android_saf_selected_file",
        destination_endpoint="macos_saved_file",
        transfer_id_hex="00112233445566778899aabbccddeeff",
        session_epoch=7,
        sha256=hashlib.sha256(b"p0110 android-to-macos payload\n").hexdigest(),
    )
    write_direction_artifacts(
        root,
        "macos-to-android",
        payload=b"p0110 macos-to-android payload\n",
        source_endpoint="macos_selected_file",
        destination_endpoint="android_downloads_file",
        transfer_id_hex="ffeeddccbbaa99887766554433221100",
        session_epoch=7,
        sha256=hashlib.sha256(b"p0110 macos-to-android payload\n").hexdigest(),
    )
    for artifact_path in (
        "cancel-cleanup/cancel-request.txt",
        "cancel-cleanup/cleanup-state.txt",
    ):
        path = root / artifact_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"retained product artifact: {artifact_path}\n", encoding="utf-8")
    return paths


class FileTransferAndroidSmokeGateTests(unittest.TestCase):
    def test_make_target_records_repo_relative_source_paths(self) -> None:
        makefile = Path(__file__).parents[2] / "Makefile"
        recipe = makefile.read_text(encoding="utf-8").split(
            "file-transfer-android-smoke:",
            1,
        )[1]
        recipe = recipe.split("\n\n", 1)[0]

        self.assertIn("--repo-root .", recipe)

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

    def test_product_e2e_requires_same_transport_and_session_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            macos_to_android = directions["macos_to_android_file_transfer"]
            assert isinstance(macos_to_android, dict)
            macos_to_android["transport"] = "trusted_lan"
            macos_to_android["session_epoch"] = 8
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
            "bidirectional_product_e2e: direction transports must match for same-session bidirectional product evidence",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: direction session_epoch values must match for same-session bidirectional product evidence",
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

    def test_android_log_rejects_compact_file_transfer_skipped_or_ignored_marker(self) -> None:
        for marker in ("S", "I"):
            with self.subTest(marker=marker):
                with tempfile.TemporaryDirectory() as directory_name:
                    root = Path(directory_name)
                    paths = write_pass_inputs(root)
                    paths["android_log"].write_text(
                        f"dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest:..{marker}\n"
                        "Tests run: 3,  Failures: 0,  Errors: 0\n"
                        "Finished 3 tests on P0110 - 16\n"
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
            "device_identity: missing real Android device identity evidence from USB, trusted-LAN, or product evidence",
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts missing source_file artifact",
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
            sender_artifact = artifact_by_role(android_to_macos, "sender_action")
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[1].path must stay inside the evidence bundle",
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[3].path retained artifact android-to-macos/protocol-packets.jsonl must be non-empty",
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

    def test_source_file_artifact_sha256_must_match_direction_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "source-file.bin").write_bytes(b"wrong-source")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.source_file artifact size 12 must equal byte_length 31",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.source_file artifact SHA-256 must equal direction.sha256",
            result["blockers"],
        )

    def test_protocol_packets_artifact_must_be_jsonl_with_transfer_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text(
                "not json\n",
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.protocol_packets artifact must be JSONL; malformed line(s): [1]",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.protocol_packets artifact missing event(s): file_chunk, file_complete, file_offer, file_request",
            result["blockers"],
        )

    def test_protocol_packets_artifact_requires_distinct_structured_event_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text(
                json.dumps(
                    {
                        "event": "file_offer file_request file_chunk file_complete",
                        "transfer_id_hex": "00112233445566778899aabbccddeeff",
                        "session_epoch": 7,
                    }
                )
                + "\n",
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.protocol_packets artifact missing event(s): file_chunk, file_complete, file_offer, file_request",
            result["blockers"],
        )

    def test_sha256_verification_artifact_must_include_direction_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "sha256-verification.txt").write_text(
                "sha256 verified another digest\n",
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
        directions = product_e2e()["directions"]
        assert isinstance(directions, dict)
        android_to_macos = directions["android_to_macos_file_transfer"]
        assert isinstance(android_to_macos, dict)
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.sha256_verification artifact must record "
            f"sha256 verified {android_to_macos['sha256']}",
            result["blockers"],
        )

    def test_retained_role_artifacts_reject_contradictory_summary_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "sender-action.txt").write_text(
                "sender_action not performed source=android_saf_selected_file "
                "transfer_id_hex=00112233445566778899aabbccddeeff\n",
                encoding="utf-8",
            )
            (root / "android-to-macos" / "receiver-approval.txt").write_text(
                "receiver_approval NOT approved destination=macos_saved_file "
                "transfer_id_hex=00112233445566778899aabbccddeeff\n",
                encoding="utf-8",
            )
            directions = product_e2e()["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_to_macos_file_transfer"]
            assert isinstance(android_to_macos, dict)
            (root / "android-to-macos" / "sha256-verification.txt").write_text(
                f"sha256 mismatch {android_to_macos['sha256']}\n",
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.sender_action artifact must record an affirmative sender_action",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.receiver_approval artifact must record receiver_approval approved",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.sha256_verification artifact must record "
            f"sha256 verified {android_to_macos['sha256']}",
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
            receiver_artifact = artifact_by_role(android_to_macos, "receiver_approval")
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[2].path must be distinct from sender_action artifact path",
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
            sender_artifact = artifact_by_role(macos_to_android, "sender_action")
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
            "bidirectional_product_e2e: macos_to_android_file_transfer.retained_artifacts[1].path for sender_action must be distinct from android_to_macos_file_transfer sender_action artifact path",
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
            unknown_artifact = artifact_by_role(android_to_macos, "source_file")
            duplicate_artifact = artifact_by_role(android_to_macos, "protocol_packets")
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
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[0].role must be one of source_file, sender_action, receiver_approval, protocol_packets, remote_file, sha256_verification",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts[3].role duplicates receiver_approval artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_to_macos_file_transfer.retained_artifacts missing source_file artifact",
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

    def test_product_e2e_requires_host_backed_context_not_no_host_or_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            document["host_backed_product_session"] = False
            document["same_session_bidirectional_transfer"] = False
            document["destination_file_bytes_retained"] = False
            document["no_host_ui_only"] = True
            document["summary_only"] = True
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
            "bidirectional_product_e2e: product evidence host_backed_product_session must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence same_session_bidirectional_transfer must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence destination_file_bytes_retained must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence no_host_ui_only must be false",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence summary_only must be false",
            result["blockers"],
        )

    def test_product_e2e_requires_all_product_context_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            for field in (
                "real_macos_host",
                "real_android_device",
                "host_readiness_bound_to_session",
                "device_identity_bound_to_session",
            ):
                document.pop(field)
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
            "bidirectional_product_e2e: product evidence real_macos_host must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence real_android_device must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence host_readiness_bound_to_session must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: product evidence device_identity_bound_to_session must be true",
            result["blockers"],
        )

    def test_product_e2e_requires_current_schema_version(self) -> None:
        for schema_version in (None, "vibescreen.evidence/v0"):
            with self.subTest(schema_version=schema_version):
                with tempfile.TemporaryDirectory() as directory_name:
                    root = Path(directory_name)
                    paths = write_pass_inputs(root)
                    document = product_e2e()
                    if schema_version is None:
                        document.pop("schema_version")
                    else:
                        document["schema_version"] = schema_version
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
                    "bidirectional_product_e2e: product evidence schema_version must be "
                    f"{SCHEMA_VERSION}",
                    result["blockers"],
                )
                self.assertIn(
                    "cancel_cleanup: product evidence schema_version must be "
                    f"{SCHEMA_VERSION}",
                    result["blockers"],
                )

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
        self.assertTrue(result["safety"]["no_host_ui_evidence_do_not_close_gate"])
        self.assertTrue(result["safety"]["summary_only_evidence_do_not_close_gate"])
        self.assertTrue(result["safety"]["retained_remote_file_bytes_required"])
        self.assertTrue(result["product_e2e_closure"]["host_backed_product_session_required"])
        self.assertTrue(result["product_e2e_closure"]["same_session_bidirectional_transfer_required"])

    def test_xiaomi_fuxi_identity_is_allowed_when_preflight_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            xiaomi_identity = {
                "manufacturer": "xiaomi",
                "model": "2211133C",
                "codename": "fuxi",
                "android_release": "16",
                "sdk": 36,
            }
            write_json(
                paths["usb"],
                usb_preflight(device={"identity": {**xiaomi_identity, "device": "fuxi"}}),
            )
            write_json(paths["product"], product_e2e(device=xiaomi_identity))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_file_transfer_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        identity_gate = next(item for item in result["checks"] if item["name"] == "device_identity")
        self.assertEqual(identity_gate["status"], "pass")

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
        self.assertTrue(
            any("mixed or relabeled identity fields are rejected" in reason for reason in identity_gate["reasons"]),
            identity_gate["reasons"],
        )

    def test_product_and_transport_device_identities_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["usb"],
                usb_preflight(
                    device={
                        "identity": {
                            "manufacturer": "xiaomi",
                            "model": "2211133C",
                            "device": "fuxi",
                            "android_release": "16",
                            "sdk": 36,
                        }
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
        self.assertTrue(
            any("usb_preflight reported" in reason for reason in identity_gate["reasons"]),
            identity_gate["reasons"],
        )

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
