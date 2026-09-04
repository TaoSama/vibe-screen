from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.clipboard_e2e_gate import derive_gate, main


OFFLINE_CONTRACT_FIXTURE = (
    Path(__file__).parents[2]
    / "docs"
    / "changes"
    / "2026-08-16-android-macos-clipboard"
    / "fixtures"
    / "clipboard-product-flow-offline-contract.json"
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
    android_to_macos = {
        "transport": "usb",
        "marker": "android-to-macos-marker-123",
        "change_id_hex": "00112233445566778899aabbccddeeff",
        "sha256": "a" * 64,
        "origin_device_id": "android-p0110-pacific",
        "byte_length": 28,
        "mime_type": "text/plain",
        "session_epoch": 1,
        "final_marker": "android-to-macos-marker-123",
        "overwrite_marker": "android-to-macos-overwrite-123",
        "cancelled_marker": "android-to-macos-cancelled-123",
        "failed_marker": "android-to-macos-failed-123",
        "deny_marker": "android-to-macos-denied-123",
        "source_system_clipboard": "android_clipboardmanager",
        "destination_system_clipboard": "macos_nspasteboard",
        "protocol_v1_session": True,
        "system_source_clipboard_read": True,
        "explicit_user_action": True,
        "receiver_user_approval": True,
        "remote_system_clipboard_write": True,
        "final_marker_match": True,
        "session_id_verified": True,
        "session_epoch_verified": True,
        "final_sha256_match": True,
        "origin_device_id_verified": True,
        "send_failure_absent": True,
        "write_failure_absent": True,
        "cleanup_completed": True,
        "utf8_valid": True,
        "overwrite_confirmed": True,
        "cancel_does_not_write": True,
        "failure_does_not_write": True,
        "deny_wins_observed": True,
    }
    macos_to_android = {
        "transport": "usb",
        "marker": "macos-to-android-marker-123",
        "change_id_hex": "ffeeddccbbaa99887766554433221100",
        "sha256": "b" * 64,
        "origin_device_id": "macos-host-current-source",
        "byte_length": 28,
        "mime_type": "text/plain",
        "session_epoch": 1,
        "final_marker": "macos-to-android-marker-123",
        "overwrite_marker": "macos-to-android-overwrite-123",
        "cancelled_marker": "macos-to-android-cancelled-123",
        "failed_marker": "macos-to-android-failed-123",
        "deny_marker": "macos-to-android-denied-123",
        "source_system_clipboard": "macos_nspasteboard",
        "destination_system_clipboard": "android_clipboardmanager",
        "protocol_v1_session": True,
        "system_source_clipboard_read": True,
        "explicit_user_action": True,
        "receiver_user_approval": True,
        "remote_system_clipboard_write": True,
        "final_marker_match": True,
        "session_id_verified": True,
        "session_epoch_verified": True,
        "final_sha256_match": True,
        "origin_device_id_verified": True,
        "send_failure_absent": True,
        "write_failure_absent": True,
        "cleanup_completed": True,
        "utf8_valid": True,
        "overwrite_confirmed": True,
        "cancel_does_not_write": True,
        "failure_does_not_write": True,
        "deny_wins_observed": True,
    }
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_macos_clipboard_product_e2e",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": 36,
        },
        "synthetic": False,
        "offline_only": False,
        "directions": {
            "android_clipboardmanager_to_macos_nspasteboard": dict(android_to_macos),
            "macos_nspasteboard_to_android_clipboardmanager": dict(macos_to_android),
        },
    }
    document.update(overrides)
    return document


def write_pass_inputs(root: Path) -> dict[str, Path]:
    paths = {
        "host": root / "host-readiness.json",
        "usb": root / "usb-smoke-preflight.json",
        "lan": root / "trusted-lan-preflight.json",
        "android_log": root / "android-clipboard-instrumentation.txt",
        "product": root / "product-e2e.json",
    }
    write_json(paths["host"], host_readiness())
    write_json(paths["usb"], usb_preflight())
    write_json(paths["lan"], lan_preflight())
    paths["android_log"].write_text("OK (3 tests)\n", encoding="utf-8")
    write_json(paths["product"], product_e2e())
    return paths


class ClipboardE2EGateTests(unittest.TestCase):
    def test_missing_product_e2e_keeps_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["product"].unlink()

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_closed"])
        self.assertIn("bidirectional_product_e2e: missing product E2E evidence: product-e2e.json", result["blockers"])
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
                android_clipboard_instrumentation_log=paths["android_log"],
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
                android_clipboard_instrumentation_log=paths["android_log"],
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
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.transport trusted_lan is not ready",
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
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("bidirectional_product_e2e: synthetic or offline-only clipboard evidence cannot close this gate", result["blockers"])

    def test_offline_only_product_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], product_e2e(offline_only=True))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("bidirectional_product_e2e: synthetic or offline-only clipboard evidence cannot close this gate", result["blockers"])

    def test_wrong_product_evidence_kind_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], product_e2e(kind="android_clipboard_local_smoke"))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: product evidence kind must be android_macos_clipboard_product_e2e",
            result["blockers"],
        )

    def test_product_e2e_requires_both_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            directions.pop("macos_nspasteboard_to_android_clipboardmanager")
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: missing macos_nspasteboard_to_android_clipboardmanager direction evidence",
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
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["gate_closed"])
        self.assertEqual(result["not_proven"], [])

    def test_product_e2e_requires_exact_system_clipboard_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["source_system_clipboard"] = "android_local_smoke"
            android_to_macos["destination_system_clipboard"] = "macos_clipboard_core"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.source_system_clipboard must be android_clipboardmanager",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.destination_system_clipboard must be macos_nspasteboard",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_integrity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["change_id_hex"] = "not-a-change-id"
            android_to_macos["sha256"] = "not-a-sha"
            android_to_macos["byte_length"] = 1_048_577
            android_to_macos["session_epoch"] = 0
            android_to_macos["session_id_verified"] = False
            android_to_macos["session_epoch_verified"] = False
            android_to_macos["final_sha256_match"] = False
            android_to_macos["origin_device_id_verified"] = False
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.change_id_hex must be a 32-character hex change ID",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.sha256 must be a 64-character hex SHA-256 digest",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.byte_length must not exceed 1048576 bytes",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.session_epoch must be a positive integer",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.session_id_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.session_epoch_verified must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.final_sha256_match must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.origin_device_id_verified must be true",
            result["blockers"],
        )

    def test_product_e2e_requires_receiver_approval_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["receiver_user_approval"] = False
            android_to_macos["cleanup_completed"] = False
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.receiver_user_approval must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.cleanup_completed must be true",
            result["blockers"],
        )

    def test_product_e2e_requires_overwrite_cancel_failure_and_deny_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(android_to_macos, dict)
            assert isinstance(macos_to_android, dict)
            android_to_macos["overwrite_confirmed"] = False
            android_to_macos["cancel_does_not_write"] = False
            android_to_macos["failure_does_not_write"] = False
            android_to_macos["deny_wins_observed"] = False
            macos_to_android["final_marker"] = "wrong-final-marker"
            macos_to_android["overwrite_marker"] = macos_to_android["marker"]
            macos_to_android.pop("cancelled_marker")
            macos_to_android["failed_marker"] = macos_to_android["marker"]
            macos_to_android["deny_marker"] = macos_to_android["marker"]
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.overwrite_confirmed must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.cancel_does_not_write must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.failure_does_not_write must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.deny_wins_observed must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.final_marker must equal marker after the destination system clipboard write",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.overwrite_marker must be distinct from marker",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.cancelled_marker must identify the cancelled transfer marker",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.failed_marker must be distinct from marker",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.deny_marker must be distinct from marker",
            result["blockers"],
        )

    def test_product_e2e_requires_all_marker_roles_to_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["cancelled_marker"] = android_to_macos["overwrite_marker"]
            android_to_macos["deny_marker"] = android_to_macos["failed_marker"]
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.cancelled_marker must be distinct from overwrite_marker",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.deny_marker must be distinct from failed_marker",
            result["blockers"],
        )

    def test_product_e2e_requires_no_send_or_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(macos_to_android, dict)
            macos_to_android["send_failure_absent"] = False
            macos_to_android["write_failure_absent"] = False
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.send_failure_absent must be true",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.write_failure_absent must be true",
            result["blockers"],
        )

    def test_product_e2e_requires_text_plain_and_valid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["mime_type"] = "text/html"
            android_to_macos["utf8_valid"] = False
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.mime_type must be text/plain",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.utf8_valid must be true",
            result["blockers"],
        )

    def test_product_e2e_rejects_zero_byte_length_and_internet_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["byte_length"] = 0
            android_to_macos["transport"] = "internet"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.byte_length must be a positive integer",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.transport must be usb or trusted_lan",
            result["blockers"],
        )

    def test_product_e2e_requires_origin_device_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(android_to_macos, dict)
            assert isinstance(macos_to_android, dict)
            android_to_macos.pop("origin_device_id")
            macos_to_android["origin_device_id"] = "   "
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.origin_device_id must record the verified Protocol v1 origin device ID",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.origin_device_id must record the verified Protocol v1 origin device ID",
            result["blockers"],
        )

    def test_product_e2e_rejects_boolean_integer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["byte_length"] = True
            android_to_macos["session_epoch"] = True
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.byte_length must be a positive integer",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.session_epoch must be a positive integer",
            result["blockers"],
        )

    def test_product_e2e_requires_distinct_direction_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["marker"] = "same-marker-for-both-directions"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: direction markers must be distinct so one transfer cannot satisfy both directions",
            result["blockers"],
        )

    def test_product_e2e_requires_distinct_direction_change_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["change_id_hex"] = "00112233445566778899aabbccddeeff"
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: direction change IDs must be distinct so one transfer cannot satisfy both directions",
            result["blockers"],
        )

    def test_product_e2e_requires_distinct_direction_sha256_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            for direction in directions.values():
                assert isinstance(direction, dict)
                direction["sha256"] = "a" * 64
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: direction SHA-256 digests must be distinct so one payload cannot satisfy both directions",
            result["blockers"],
        )

    def test_offline_product_flow_contract_fixture_is_complete_but_cannot_close_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], json.loads(OFFLINE_CONTRACT_FIXTURE.read_text(encoding="utf-8")))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_closed"])
        self.assertIn(
            "bidirectional_product_e2e: synthetic or offline-only clipboard evidence cannot close this gate",
            result["blockers"],
        )

    def test_android_clipboard_smoke_accepts_gradle_instrumentation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "Starting 3 tests on P0110 - 16\n\n"
                "Tests run: 3,  Failures: 0,  Errors: 0\n"
                "Finished 3 tests on P0110 - 16\n\n"
                "BUILD SUCCESSFUL in 38s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        android_gate = next(item for item in result["checks"] if item["name"] == "android_clipboardmanager_smoke")
        self.assertEqual(android_gate["status"], "pass")
        self.assertEqual(result["verdict"], "pass")

    def test_android_clipboard_smoke_rejects_junit_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(
                "Starting 3 tests on P0110 - 16\n"
                "Tests run: 3,  Failures: 1,  Errors: 0\n"
                "Finished 3 tests on P0110 - 16\n"
                "BUILD SUCCESSFUL in 38s\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        android_gate = next(item for item in result["checks"] if item["name"] == "android_clipboardmanager_smoke")
        self.assertEqual(android_gate["status"], "blocked")
        self.assertEqual(result["verdict"], "blocked")

    def test_missing_device_identity_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["usb"], {"kind": "android_usb_smoke_preflight", "result": "pass", "claims": {"can_start_usb_smoke": True}})
            write_json(paths["lan"], {"kind": "trusted_lan_preflight", "result": "pass"})
            document = product_e2e()
            document.pop("device")
            write_json(paths["product"], document)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "device_identity: missing real P0110 device identity evidence from USB, trusted-LAN, or product evidence",
            result["blockers"],
        )
        identity_gate = next(item for item in result["checks"] if item["name"] == "device_identity")
        self.assertIsNone(identity_gate["identity"])
        self.assertEqual(identity_gate["expected_identity"]["codename"], "pacific")

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
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "fail")
        identity_gate = next(item for item in result["checks"] if item["name"] == "device_identity")
        self.assertIn("clipboard E2E evidence for this run must identify nubia P0110 / pacific", identity_gate["reasons"])

    def test_output_redacts_serial_home_and_tcc_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            raw_serial = "EPTESTSERIAL000000"
            user_path = "/Users/" + "localuser"
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
                    "--android-clipboard-instrumentation-log",
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
