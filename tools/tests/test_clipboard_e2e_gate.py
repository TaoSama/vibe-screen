from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.clipboard_e2e_gate import derive_gate, main, sanitize_text


OFFLINE_CONTRACT_FIXTURE = (
    Path(__file__).parents[2]
    / "docs"
    / "changes"
    / "2026-08-16-android-macos-clipboard"
    / "fixtures"
    / "clipboard-product-flow-offline-contract.json"
)

ANDROID_CLIPBOARD_METHODS = (
    "foregroundActivityCanUseAndroidSystemClipboardLocally",
    "foregroundActivityCanRoundTripUnicodeAndLargePlainTextLocally",
    "foregroundActivityHandlesNonTextClipboardItemSafely",
    "foregroundActivitySeesEmptyClipboardAsNoPrimaryClip",
    "foregroundActivityDoesNotTreatLaterTextItemAsFirstClipboardText",
    "foregroundActivityCanRoundTripExpandedLargePlainTextLocally",
    "setForegroundClipboardFromInstrumentationArgument",
    "assertForegroundClipboardMatchesInstrumentationArgument",
)
ANDROID_TO_MACOS_DIRECTION = "android_clipboardmanager_to_macos_nspasteboard"
MACOS_TO_ANDROID_DIRECTION = "macos_nspasteboard_to_android_clipboardmanager"
ANDROID_TO_MACOS_MARKER = "android-to-macos-marker-123"
MACOS_TO_ANDROID_MARKER = "macos-to-android-marker-123"
ANDROID_TO_MACOS_CHANGE_ID = "00112233445566778899aabbccddeeff"
MACOS_TO_ANDROID_CHANGE_ID = "ffeeddccbbaa99887766554433221100"
CLIPBOARD_SESSION_ID = "0123456789abcdeffedcba9876543210"
ANDROID_TO_MACOS_ORIGIN = "android-p0110-pacific"
MACOS_TO_ANDROID_ORIGIN = "macos-host-current-source"
ANDROID_TO_MACOS_EPOCH = 1
MACOS_TO_ANDROID_EPOCH = 1


def retained_artifact(direction: str, role: str, path: str) -> dict[str, object]:
    content = retained_artifact_content(direction, role, path)
    return {
        "direction": direction,
        "role": role,
        "path": path,
        "byte_length": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def retained_artifact_content(direction: str, role: str, path: str) -> bytes:
    payload = direction_payload(direction)
    if role == "destination_clipboard_write":
        return str(payload["marker"]).encode("utf-8")
    if role == "source_clipboard_read":
        return str(payload["marker"]).encode("utf-8")
    if role == "protocol_packets":
        records = [
            {
                "event": "clipboard_offer",
                "direction": direction,
                "change_id_hex": payload["change_id_hex"],
                "session_id_hex": payload["session_id_hex"],
                "session_epoch": payload["session_epoch"],
                "origin_device_id": payload["origin_device_id"],
                "mime_type": "text/plain",
                "byte_length": payload["byte_length"],
                "sha256": payload["sha256"],
            },
            {
                "event": "clipboard_request",
                "direction": direction,
                "change_id_hex": payload["change_id_hex"],
                "session_id_hex": payload["session_id_hex"],
                "session_epoch": payload["session_epoch"],
                "origin_device_id": payload["origin_device_id"],
            },
            {
                "event": "clipboard_content",
                "direction": direction,
                "change_id_hex": payload["change_id_hex"],
                "session_id_hex": payload["session_id_hex"],
                "session_epoch": payload["session_epoch"],
                "origin_device_id": payload["origin_device_id"],
                "mime_type": "text/plain",
                "byte_length": payload["byte_length"],
                "sha256": payload["sha256"],
            },
        ]
        text = "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n"
        return text.encode("utf-8")
    return f"retained product artifact: direction={direction} role={role} path={path}\n".encode("utf-8")


def direction_payload(direction: str) -> dict[str, object]:
    if direction == ANDROID_TO_MACOS_DIRECTION:
        marker = ANDROID_TO_MACOS_MARKER
        return {
            "marker": marker,
            "change_id_hex": ANDROID_TO_MACOS_CHANGE_ID,
            "origin_device_id": ANDROID_TO_MACOS_ORIGIN,
            "session_id_hex": CLIPBOARD_SESSION_ID,
            "session_epoch": ANDROID_TO_MACOS_EPOCH,
            "sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
            "byte_length": len(marker.encode("utf-8")),
        }
    marker = MACOS_TO_ANDROID_MARKER
    return {
        "marker": marker,
        "change_id_hex": MACOS_TO_ANDROID_CHANGE_ID,
        "origin_device_id": MACOS_TO_ANDROID_ORIGIN,
        "session_id_hex": CLIPBOARD_SESSION_ID,
        "session_epoch": MACOS_TO_ANDROID_EPOCH,
        "sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
        "byte_length": len(marker.encode("utf-8")),
    }


def retained_artifact_content_for_path(path: str) -> bytes:
    if path.startswith("android-to-macos/"):
        direction = ANDROID_TO_MACOS_DIRECTION
    else:
        direction = MACOS_TO_ANDROID_DIRECTION
    role = Path(path).stem.replace("-", "_")
    if role == "negative_boundary":
        role = "negative_boundary_verification"
    return retained_artifact_content(direction, role, path)


def android_clipboard_success_log() -> str:
    method_lines = "\n".join(
        f"dev.telemachus.display.ClipboardManagerInstrumentedTest#{method}: PASSED"
        for method in ANDROID_CLIPBOARD_METHODS
    )
    return (
        "Starting 8 tests on P0110 - 16\n\n"
        f"{method_lines}\n\n"
        "Tests run: 8,  Failures: 0,  Errors: 0\n"
        "Finished 8 tests on P0110 - 16\n\n"
        "BUILD SUCCESSFUL in 38s\n"
    )


def android_clipboard_legacy_five_test_log() -> str:
    legacy_methods = (
        "foregroundActivityCanUseAndroidSystemClipboardLocally",
        "foregroundActivityCanRoundTripUnicodeAndLargePlainTextLocally",
        "foregroundActivityHandlesNonTextClipboardItemSafely",
        "setForegroundClipboardFromInstrumentationArgument",
        "assertForegroundClipboardMatchesInstrumentationArgument",
    )
    method_lines = "\n".join(
        f"dev.telemachus.display.ClipboardManagerInstrumentedTest#{method}: PASSED"
        for method in legacy_methods
    )
    return (
        "Starting 5 tests on P0110 - 16\n\n"
        f"{method_lines}\n\n"
        "Tests run: 5,  Failures: 0,  Errors: 0\n"
        "Finished 5 tests on P0110 - 16\n\n"
        "BUILD SUCCESSFUL in 16s\n"
    )


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def host_readiness(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "vibescreen.host-readiness/v1",
        "kind": "macos_host_shared_prerequisite_readiness",
        "status": "pass",
        "signing_tcc_status": "ready",
        "can_close_runtime_gates": True,
        "permissions": {
            "readable": True,
            "screen_recording_granted": True,
            "accessibility_granted": True,
            "microphone_granted": True,
            "screen_recording_identity_bound": True,
            "accessibility_identity_bound": True,
            "microphone_identity_bound": True,
        },
        "listener": {"port": 54321, "observed": True},
        "host": {},
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
        "claims": {
            "can_start_usb_smoke": True,
            "host_listener_observed": True,
            "adb_reverse_tcp_54321_present": True,
            "android_app_foreground": True,
        },
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
    android_to_macos_payload = direction_payload(ANDROID_TO_MACOS_DIRECTION)
    macos_to_android_payload = direction_payload(MACOS_TO_ANDROID_DIRECTION)
    android_artifacts = [
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "source_clipboard_read", "android-to-macos/source-clipboard-read.txt"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "sender_action", "android-to-macos/sender-action.txt"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "receiver_approval", "android-to-macos/receiver-approval.txt"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "protocol_packets", "android-to-macos/protocol-packets.jsonl"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "destination_clipboard_write", "android-to-macos/destination-clipboard-write.txt"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "final_verification", "android-to-macos/final-verification.txt"),
        retained_artifact(ANDROID_TO_MACOS_DIRECTION, "negative_boundary_verification", "android-to-macos/negative-boundary.txt"),
    ]
    macos_artifacts = [
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "source_clipboard_read", "macos-to-android/source-clipboard-read.txt"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "sender_action", "macos-to-android/sender-action.txt"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "receiver_approval", "macos-to-android/receiver-approval.txt"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "protocol_packets", "macos-to-android/protocol-packets.jsonl"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "destination_clipboard_write", "macos-to-android/destination-clipboard-write.txt"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "final_verification", "macos-to-android/final-verification.txt"),
        retained_artifact(MACOS_TO_ANDROID_DIRECTION, "negative_boundary_verification", "macos-to-android/negative-boundary.txt"),
    ]
    android_to_macos = {
        "transport": "usb",
        "marker": android_to_macos_payload["marker"],
        "change_id_hex": android_to_macos_payload["change_id_hex"],
        "session_id_hex": android_to_macos_payload["session_id_hex"],
        "sha256": android_to_macos_payload["sha256"],
        "origin_device_id": android_to_macos_payload["origin_device_id"],
        "byte_length": android_to_macos_payload["byte_length"],
        "mime_type": "text/plain",
        "session_epoch": android_to_macos_payload["session_epoch"],
        "final_marker": android_to_macos_payload["marker"],
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
        "retained_artifacts": android_artifacts,
    }
    macos_to_android = {
        "transport": "usb",
        "marker": macos_to_android_payload["marker"],
        "change_id_hex": macos_to_android_payload["change_id_hex"],
        "session_id_hex": macos_to_android_payload["session_id_hex"],
        "sha256": macos_to_android_payload["sha256"],
        "origin_device_id": macos_to_android_payload["origin_device_id"],
        "byte_length": macos_to_android_payload["byte_length"],
        "mime_type": "text/plain",
        "session_epoch": macos_to_android_payload["session_epoch"],
        "final_marker": macos_to_android_payload["marker"],
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
        "retained_artifacts": macos_artifacts,
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
            ANDROID_TO_MACOS_DIRECTION: dict(android_to_macos),
            MACOS_TO_ANDROID_DIRECTION: dict(macos_to_android),
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
    paths["android_log"].write_text(android_clipboard_success_log(), encoding="utf-8")
    product = product_e2e()
    write_json(paths["product"], product)
    directions = product["directions"]
    assert isinstance(directions, dict)
    for direction, direction_record in directions.items():
        assert isinstance(direction, str)
        assert isinstance(direction_record, dict)
        retained_artifacts = direction_record["retained_artifacts"]
        assert isinstance(retained_artifacts, list)
        for artifact in retained_artifacts:
            assert isinstance(artifact, dict)
            role = artifact["role"]
            artifact_path = artifact["path"]
            assert isinstance(role, str)
            assert isinstance(artifact_path, str)
            path = root / artifact_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(retained_artifact_content(direction, role, artifact_path))
    return paths


def refresh_retained_artifact_metadata(product_path: Path, artifact_path: Path, retained_path: str) -> None:
    document = json.loads(product_path.read_text(encoding="utf-8"))
    content = artifact_path.read_bytes()
    directions = document["directions"]
    assert isinstance(directions, dict)
    for direction_record in directions.values():
        assert isinstance(direction_record, dict)
        retained_artifacts = direction_record["retained_artifacts"]
        assert isinstance(retained_artifacts, list)
        for artifact in retained_artifacts:
            assert isinstance(artifact, dict)
            if artifact.get("path") == retained_path:
                artifact["byte_length"] = len(content)
                artifact["sha256"] = hashlib.sha256(content).hexdigest()
                write_json(product_path, document)
                return
    raise AssertionError(f"missing retained artifact metadata for {retained_path}")


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

    def test_android_clipboard_log_must_execute_complete_smoke_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text("OK (0 tests)\n", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show at least 8 executed tests",
            result["blockers"],
        )

    def test_android_clipboard_log_rejects_legacy_three_test_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text("OK (3 tests)\n", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show at least 8 executed tests",
            result["blockers"],
        )

    def test_android_clipboard_log_rejects_legacy_five_test_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text(android_clipboard_legacy_five_test_log(), encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show at least 8 executed tests",
            result["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith(
                    "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show passed expected test methods: "
                )
                and "foregroundActivitySeesEmptyClipboardAsNoPrimaryClip" in blocker
                and "foregroundActivityDoesNotTreatLaterTextItemAsFirstClipboardText" in blocker
                and "foregroundActivityCanRoundTripExpandedLargePlainTextLocally" in blocker
                for blocker in result["blockers"]
            ),
            result["blockers"],
        )

    def test_android_clipboard_log_rejects_count_without_expected_method_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text("OK (8 tests)\n", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(
            any(
                blocker.startswith(
                    "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show passed expected test methods: "
                )
                for blocker in result["blockers"]
            ),
            result["blockers"],
        )

    def test_android_clipboard_log_rejects_build_success_without_test_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            paths["android_log"].write_text("BUILD SUCCESSFUL in 1s\n", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show at least 8 executed tests",
            result["blockers"],
        )

    def test_preflight_blockers_propagate_without_closing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["host"],
                host_readiness(
                    status="blocked",
                    can_close_runtime_gates=False,
                    blockers=["installed Host is not ready for clipboard E2E"],
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
        self.assertIn("host_readiness: installed Host is not ready for clipboard E2E", result["blockers"])
        lan_gate = next(item for item in result["checks"] if item["name"] == "trusted_lan_preflight")
        self.assertIn("android_wifi_association: Wi-Fi is not associated", lan_gate["reasons"])

    def test_host_readiness_requires_structured_signing_tcc_listener_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["host"],
                {
                    "schema_version": "vibescreen.host-readiness/v1",
                    "kind": "macos_host_shared_prerequisite_readiness",
                    "status": "pass",
                    "can_close_runtime_gates": True,
                    "blockers": [],
                },
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "host_readiness: Host readiness signing_tcc_status must be ready, got None",
            result["blockers"],
        )
        self.assertIn(
            "host_readiness: Host readiness listener must be present",
            result["blockers"],
        )
        self.assertIn(
            "host_readiness: Host readiness permissions must be present",
            result["blockers"],
        )

    def test_host_readiness_requires_clipboard_listener_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["host"],
                host_readiness(listener={"port": 12345, "observed": True}),
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "host_readiness: Host readiness listener.port must be 54321",
            result["blockers"],
        )

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

    def test_usb_preflight_requires_key_ready_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(
                paths["usb"],
                usb_preflight(claims={"can_start_usb_smoke": True}),
            )
            write_json(paths["lan"], lan_preflight(result="blocked", blockers=["LAN not used for this USB evidence"]))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
                repo_root=root,
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "real_transport_ready: usb: USB preflight claims.host_listener_observed must be true",
            result["blockers"],
        )
        self.assertIn(
            "real_transport_ready: usb: USB preflight claims.adb_reverse_tcp_54321_present must be true",
            result["blockers"],
        )
        self.assertIn(
            "real_transport_ready: usb: USB preflight claims.android_app_foreground must be true",
            result["blockers"],
        )

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

    def test_non_boolean_synthetic_or_offline_only_product_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], product_e2e(synthetic="true", offline_only=1))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("bidirectional_product_e2e: synthetic or offline-only clipboard evidence cannot close this gate", result["blockers"])

    def test_false_like_synthetic_or_offline_only_product_evidence_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            write_json(paths["product"], product_e2e(synthetic=0, offline_only="false"))

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "pass")

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

    def test_report_records_repo_relative_product_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
                repo_root=root,
            )

        self.assertEqual(
            result["source"],
            {
                "host_readiness": "host-readiness.json",
                "usb_preflight": "usb-smoke-preflight.json",
                "trusted_lan_preflight": "trusted-lan-preflight.json",
                "android_clipboard_instrumentation_log": "android-clipboard-instrumentation.txt",
                "product_e2e": "product-e2e.json",
            },
        )

    def test_report_sanitizes_non_repo_relative_product_source(self) -> None:
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

        self.assertEqual(
            result["source"],
            {
                "host_readiness": "host-readiness.json",
                "usb_preflight": "usb-smoke-preflight.json",
                "trusted_lan_preflight": "trusted-lan-preflight.json",
                "android_clipboard_instrumentation_log": "android-clipboard-instrumentation.txt",
                "product_e2e": "product-e2e.json",
            },
        )
        self.assertNotIn(directory_name, json.dumps(result["source"]))

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
            android_to_macos["session_id_hex"] = "not-a-session-id"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.session_id_hex must be a 32-character hex session ID",
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

    def test_product_e2e_requires_retained_artifact_hash_metadata(self) -> None:
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
            android_artifacts = android_to_macos["retained_artifacts"]
            macos_artifacts = macos_to_android["retained_artifacts"]
            assert isinstance(android_artifacts, list)
            assert isinstance(macos_artifacts, list)
            first_android_artifact = android_artifacts[0]
            first_macos_artifact = macos_artifacts[0]
            assert isinstance(first_android_artifact, dict)
            assert isinstance(first_macos_artifact, dict)
            first_android_artifact.pop("byte_length")
            first_macos_artifact["sha256"] = "not-a-sha"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[0].byte_length must record the retained artifact byte length",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.retained_artifacts[0].sha256 must record the retained artifact SHA-256 digest",
            result["blockers"],
        )

    def test_product_e2e_rejects_retained_artifact_hash_mismatch(self) -> None:
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
            android_artifacts = android_to_macos["retained_artifacts"]
            macos_artifacts = macos_to_android["retained_artifacts"]
            assert isinstance(android_artifacts, list)
            assert isinstance(macos_artifacts, list)
            android_sender_artifact = android_artifacts[1]
            macos_sender_artifact = macos_artifacts[1]
            assert isinstance(android_sender_artifact, dict)
            assert isinstance(macos_sender_artifact, dict)
            android_sender_artifact["byte_length"] = 1
            macos_sender_artifact["sha256"] = "0" * 64
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[1].byte_length 1 must equal retained artifact size "
            f"{len(retained_artifact_content_for_path('android-to-macos/sender-action.txt'))}",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.retained_artifacts[1].sha256 must equal retained artifact SHA-256",
            result["blockers"],
        )

    def test_product_e2e_requires_destination_artifact_to_match_direction_payload(self) -> None:
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
            android_to_macos["byte_length"] = 1
            macos_to_android["sha256"] = "0" * 64
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.destination_clipboard_write artifact size "
            f"{len(retained_artifact_content_for_path('android-to-macos/destination-clipboard-write.txt'))} must equal direction.byte_length 1",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.destination_clipboard_write artifact SHA-256 must equal direction.sha256",
            result["blockers"],
        )

    def test_product_e2e_requires_source_artifact_to_match_direction_payload(self) -> None:
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
            android_to_macos["byte_length"] = 1
            macos_to_android["sha256"] = "0" * 64
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.source_clipboard_read artifact size "
            f"{len(retained_artifact_content_for_path('android-to-macos/source-clipboard-read.txt'))} must equal direction.byte_length 1",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.source_clipboard_read artifact SHA-256 must equal direction.sha256",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_packets_to_match_direction_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text(
                json.dumps(
                    {
                        "event": "clipboard_offer",
                        "change_id_hex": "ffffffffffffffffffffffffffffffff",
                        "session_epoch": 99,
                        "origin_device_id": "other-origin",
                    }
                )
                + "\nnot-json\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact must be JSONL; malformed line(s): [2]",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact missing event(s): clipboard_content, clipboard_request",
            result["blockers"],
        )
        self.assertIn(
            f"bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact must include change_id_hex {ANDROID_TO_MACOS_CHANGE_ID}",
            result["blockers"],
        )
        self.assertIn(
            f"bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact must include session_id_hex {CLIPBOARD_SESSION_ID}",
            result["blockers"],
        )
        self.assertIn(
            f"bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact must include session_epoch {ANDROID_TO_MACOS_EPOCH}",
            result["blockers"],
        )
        self.assertIn(
            f"bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets artifact must include origin_device_id {ANDROID_TO_MACOS_ORIGIN}",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_event_records_to_match_direction_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            records = [
                {"event": "clipboard_offer", "direction": ANDROID_TO_MACOS_DIRECTION},
                {"event": "clipboard_request", "direction": ANDROID_TO_MACOS_DIRECTION},
                {"event": "clipboard_content", "direction": ANDROID_TO_MACOS_DIRECTION},
                {
                    "event": "unrelated_diagnostic",
                    "change_id_hex": ANDROID_TO_MACOS_CHANGE_ID,
                    "session_epoch": ANDROID_TO_MACOS_EPOCH,
                    "origin_device_id": ANDROID_TO_MACOS_ORIGIN,
                },
            ]
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text(
                "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets "
            "event record(s) must include matching change_id_hex, session_id_hex, session_epoch, "
            "origin_device_id, and offer/content payload metadata: "
            "clipboard_content, clipboard_offer, clipboard_request",
            result["blockers"],
        )

    def test_product_e2e_rejects_ambiguous_protocol_event_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            payload = direction_payload(ANDROID_TO_MACOS_DIRECTION)
            record = {
                "event": "clipboard_offer",
                "message_type": "clipboard_request",
                "packet_type": "clipboard_content",
                "direction": ANDROID_TO_MACOS_DIRECTION,
                "change_id_hex": payload["change_id_hex"],
                "session_id_hex": payload["session_id_hex"],
                "session_epoch": payload["session_epoch"],
                "origin_device_id": payload["origin_device_id"],
                "mime_type": "text/plain",
                "byte_length": payload["byte_length"],
                "sha256": payload["sha256"],
            }
            artifact_path = root / "android-to-macos" / "protocol-packets.jsonl"
            artifact_path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
            refresh_retained_artifact_metadata(
                paths["product"], artifact_path, "android-to-macos/protocol-packets.jsonl"
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets "
            "event record(s) must identify exactly one clipboard event; ambiguous line(s): [1]",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_event_records_to_match_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            payload = direction_payload(ANDROID_TO_MACOS_DIRECTION)
            records = [
                {
                    "event": "clipboard_offer",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": "11111111111111111111111111111111",
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/plain",
                    "byte_length": payload["byte_length"],
                    "sha256": payload["sha256"],
                },
                {
                    "event": "clipboard_request",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": "22222222222222222222222222222222",
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                },
                {
                    "event": "clipboard_content",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": "33333333333333333333333333333333",
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/plain",
                    "byte_length": payload["byte_length"],
                    "sha256": payload["sha256"],
                },
            ]
            artifact_path = root / "android-to-macos" / "protocol-packets.jsonl"
            artifact_path.write_text(
                "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            refresh_retained_artifact_metadata(
                paths["product"], artifact_path, "android-to-macos/protocol-packets.jsonl"
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets "
            "event record(s) must include matching change_id_hex, session_id_hex, session_epoch, "
            "origin_device_id, and offer/content payload metadata: clipboard_content, clipboard_offer, clipboard_request",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_offer_and_content_payload_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            payload = direction_payload(ANDROID_TO_MACOS_DIRECTION)
            records = [
                {
                    "event": "clipboard_offer",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/html",
                    "byte_length": payload["byte_length"],
                    "sha256": payload["sha256"],
                },
                {
                    "event": "clipboard_request",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                },
                {
                    "event": "clipboard_content",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/plain",
                    "byte_length": 1,
                    "sha256": "0" * 64,
                },
            ]
            artifact_path = root / "android-to-macos" / "protocol-packets.jsonl"
            artifact_path.write_text(
                "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            refresh_retained_artifact_metadata(
                paths["product"], artifact_path, "android-to-macos/protocol-packets.jsonl"
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets "
            "event record(s) must include matching change_id_hex, session_id_hex, session_epoch, "
            "origin_device_id, and offer/content payload metadata: clipboard_content, clipboard_offer",
            result["blockers"],
        )

    def test_product_e2e_requires_protocol_event_records_to_declare_matching_direction(self) -> None:
        cases = (
            (ANDROID_TO_MACOS_DIRECTION, MACOS_TO_ANDROID_DIRECTION, "android-to-macos/protocol-packets.jsonl"),
            (MACOS_TO_ANDROID_DIRECTION, ANDROID_TO_MACOS_DIRECTION, "macos-to-android/protocol-packets.jsonl"),
        )
        for label, wrong_direction, retained_path in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory_name:
                root = Path(directory_name)
                paths = write_pass_inputs(root)
                payload = direction_payload(label)
                records = [
                    {
                        "event": "clipboard_offer",
                        "direction": wrong_direction,
                        "change_id_hex": payload["change_id_hex"],
                        "session_id_hex": payload["session_id_hex"],
                        "session_epoch": payload["session_epoch"],
                        "origin_device_id": payload["origin_device_id"],
                        "mime_type": "text/plain",
                        "byte_length": payload["byte_length"],
                        "sha256": payload["sha256"],
                    },
                    {
                        "event": "clipboard_request",
                        "change_id_hex": payload["change_id_hex"],
                        "session_id_hex": payload["session_id_hex"],
                        "session_epoch": payload["session_epoch"],
                        "origin_device_id": payload["origin_device_id"],
                    },
                    {
                        "event": "clipboard_content",
                        "direction": label,
                        "change_id_hex": payload["change_id_hex"],
                        "session_id_hex": payload["session_id_hex"],
                        "session_epoch": payload["session_epoch"],
                        "origin_device_id": payload["origin_device_id"],
                        "mime_type": "text/plain",
                        "byte_length": payload["byte_length"],
                        "sha256": payload["sha256"],
                    },
                ]
                artifact_path = root / retained_path
                artifact_path.write_text(
                    "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
                    encoding="utf-8",
                )
                refresh_retained_artifact_metadata(paths["product"], artifact_path, retained_path)

                result = derive_gate(
                    host_readiness=paths["host"],
                    usb_preflight=paths["usb"],
                    trusted_lan_preflight=paths["lan"],
                    android_clipboard_instrumentation_log=paths["android_log"],
                    product_e2e=paths["product"],
                )

            self.assertEqual(result["verdict"], "blocked")
            self.assertIn(
                f"bidirectional_product_e2e: {label}.protocol_packets "
                f"event record(s) must declare direction {label}: clipboard_offer, clipboard_request",
                result["blockers"],
            )

    def test_product_e2e_rejects_boolean_protocol_event_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            payload = direction_payload(ANDROID_TO_MACOS_DIRECTION)
            records = [
                {
                    "event": "clipboard_offer",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/plain",
                    "byte_length": payload["byte_length"],
                    "sha256": payload["sha256"],
                },
                {
                    "event": "clipboard_request",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": True,
                    "origin_device_id": payload["origin_device_id"],
                },
                {
                    "event": "clipboard_content",
                    "direction": ANDROID_TO_MACOS_DIRECTION,
                    "change_id_hex": payload["change_id_hex"],
                    "session_id_hex": payload["session_id_hex"],
                    "session_epoch": payload["session_epoch"],
                    "origin_device_id": payload["origin_device_id"],
                    "mime_type": "text/plain",
                    "byte_length": payload["byte_length"],
                    "sha256": payload["sha256"],
                },
            ]
            artifact_path = root / "android-to-macos" / "protocol-packets.jsonl"
            artifact_path.write_text(
                "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
                encoding="utf-8",
            )
            refresh_retained_artifact_metadata(
                paths["product"], artifact_path, "android-to-macos/protocol-packets.jsonl"
            )

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.protocol_packets "
            "event record(s) must include matching change_id_hex, session_id_hex, session_epoch, "
            "origin_device_id, and offer/content payload metadata: "
            "clipboard_request",
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

    def test_product_e2e_requires_same_session_id_and_transport(self) -> None:
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
            macos_to_android["session_id_hex"] = "11111111111111111111111111111111"
            macos_to_android["session_epoch"] = 2
            macos_to_android["transport"] = "trusted_lan"
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
            "bidirectional_product_e2e: direction session IDs must match for same-session bidirectional product evidence",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: direction transports must match for same-session bidirectional product evidence",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: direction session_epoch values must match for same-session bidirectional product evidence",
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
            paths["android_log"].write_text(android_clipboard_success_log(), encoding="utf-8")

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

    def test_android_clipboard_smoke_rejects_failed_raw_instrumentation_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            passed_methods = [method for method in ANDROID_CLIPBOARD_METHODS if method != "foregroundActivityCanUseAndroidSystemClipboardLocally"]
            raw_log = ["INSTRUMENTATION_STATUS: numtests=8"]
            for method in passed_methods:
                raw_log.extend(
                    [
                        "INSTRUMENTATION_STATUS: class=dev.telemachus.display.ClipboardManagerInstrumentedTest",
                        f"INSTRUMENTATION_STATUS: test={method}",
                        "INSTRUMENTATION_STATUS_CODE: 0",
                    ]
                )
            raw_log.extend(
                [
                    "INSTRUMENTATION_STATUS: class=dev.telemachus.display.ClipboardManagerInstrumentedTest",
                    "INSTRUMENTATION_STATUS: test=foregroundActivityCanUseAndroidSystemClipboardLocally",
                    "INSTRUMENTATION_STATUS_CODE: -2",
                    "OK (8 tests)",
                    "INSTRUMENTATION_CODE: -1",
                ]
            )
            paths["android_log"].write_text("\n".join(raw_log), encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must not show failed expected test methods: foregroundActivityCanUseAndroidSystemClipboardLocally=-2",
            result["blockers"],
        )

    def test_android_clipboard_smoke_rejects_method_names_only_in_stack_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            stack_trace = "\n".join(f"at {method}(ClipboardManagerInstrumentedTest.kt:1)" for method in ANDROID_CLIPBOARD_METHODS)
            paths["android_log"].write_text(f"{stack_trace}\nOK (8 tests)\n", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(
            any(
                blocker.startswith(
                    "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must show passed expected test methods: "
                )
                for blocker in result["blockers"]
            ),
            result["blockers"],
        )

    def test_android_clipboard_smoke_rejects_failed_raw_instrumentation_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            raw_log = ["INSTRUMENTATION_STATUS: numtests=8"]
            for method in ANDROID_CLIPBOARD_METHODS:
                raw_log.extend(
                    [
                        "INSTRUMENTATION_STATUS: class=dev.telemachus.display.ClipboardManagerInstrumentedTest",
                        f"INSTRUMENTATION_STATUS: test={method}",
                        "INSTRUMENTATION_STATUS_CODE: 0",
                    ]
                )
            raw_log.extend(["OK (8 tests)", "INSTRUMENTATION_CODE: 0"])
            paths["android_log"].write_text("\n".join(raw_log), encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation log must finish with INSTRUMENTATION_CODE -1",
            result["blockers"],
        )

    def test_android_clipboard_smoke_rejects_mismatched_raw_numtests(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            raw_log = ["INSTRUMENTATION_STATUS: numtests=5"]
            for method in ANDROID_CLIPBOARD_METHODS:
                raw_log.extend(
                    [
                        "INSTRUMENTATION_STATUS: class=dev.telemachus.display.ClipboardManagerInstrumentedTest",
                        f"INSTRUMENTATION_STATUS: test={method}",
                        "INSTRUMENTATION_STATUS_CODE: 0",
                    ]
                )
            raw_log.extend(["OK (8 tests)", "INSTRUMENTATION_CODE: -1"])
            paths["android_log"].write_text("\n".join(raw_log), encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "android_clipboardmanager_smoke: Android ClipboardManager instrumentation numtests must match the executed test count",
            result["blockers"],
        )

    def test_sanitize_text_does_not_redact_clipboard_test_method_names(self) -> None:
        method = "foregroundActivityCanRoundTripExpandedLargePlainTextLocally"
        self.assertEqual(sanitize_text(method), method)
        self.assertEqual(sanitize_text("serial EP0110PZ0B9110300B"), "serial REDACTED_P0110_USB_SERIAL")

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

    def test_device_identity_sources_must_match_product_device(self) -> None:
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
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "fail")
        self.assertIn(
            "device_identity: usb device identity must match product device identity",
            result["blockers"],
        )
        self.assertIn(
            "device_identity: clipboard E2E evidence for this run must identify nubia P0110 / pacific",
            result["blockers"],
        )

    def test_android_origin_device_id_must_identify_product_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["origin_device_id"] = "xiaomi-fuxi-wrong-device"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.origin_device_id must not include a non-P0110 Android device identity",
            result["blockers"],
        )

    def test_android_origin_device_id_must_match_verified_usb_device_when_product_device_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            document.pop("device")
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["origin_device_id"] = "xiaomi-fuxi-wrong-device"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.origin_device_id must not include a non-P0110 Android device identity",
            result["blockers"],
        )

    def test_android_origin_device_id_rejects_mixed_device_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["origin_device_id"] = "p0110-pacific-xiaomi-fuxi-mixed"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.origin_device_id must not include a non-P0110 Android device identity",
            result["blockers"],
        )

    def test_macos_origin_device_id_must_identify_macos_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(macos_to_android, dict)
            macos_to_android["origin_device_id"] = "android-p0110-pacific"
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
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.origin_device_id must not include an Android device identity",
            result["blockers"],
        )

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

    def test_product_e2e_requires_retained_direction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            android_to_macos["retained_artifacts"] = [
                {"role": "source_clipboard_read", "path": "/tmp/source.txt"},
                {"role": "sender_action", "path": "../sender-action.txt"},
                {"role": "protocol_packets", "path": "missing/protocol-packets.jsonl"},
            ]
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[0].path must be evidence-relative",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[1].path must stay inside the evidence bundle",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[2].path missing retained artifact missing/protocol-packets.jsonl",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing receiver_approval artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing destination_clipboard_write artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing final_verification artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing negative_boundary_verification artifact",
            result["blockers"],
        )

    def test_clipboard_retained_artifact_symlink_escape_cannot_pass(self) -> None:
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
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            sender_artifact = retained_artifacts[1]
            assert isinstance(sender_artifact, dict)
            sender_artifact["path"] = "android-to-macos/sender-action-link.txt"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[1].path must stay inside the evidence bundle",
            result["blockers"],
        )

    def test_clipboard_retained_artifacts_must_be_non_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            (root / "android-to-macos" / "protocol-packets.jsonl").write_text("", encoding="utf-8")

            result = derive_gate(
                host_readiness=paths["host"],
                usb_preflight=paths["usb"],
                trusted_lan_preflight=paths["lan"],
                android_clipboard_instrumentation_log=paths["android_log"],
                product_e2e=paths["product"],
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[3].path retained artifact android-to-macos/protocol-packets.jsonl must be non-empty",
            result["blockers"],
        )

    def test_clipboard_retained_artifact_paths_must_be_distinct_per_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            receiver_artifact = retained_artifacts[2]
            assert isinstance(receiver_artifact, dict)
            receiver_artifact["path"] = "android-to-macos/sender-action.txt"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[2].path must be distinct from sender_action artifact path",
            result["blockers"],
        )

    def test_clipboard_retained_artifact_paths_must_be_distinct_across_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            macos_to_android = directions["macos_nspasteboard_to_android_clipboardmanager"]
            assert isinstance(macos_to_android, dict)
            retained_artifacts = macos_to_android["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            source_artifact = retained_artifacts[0]
            assert isinstance(source_artifact, dict)
            source_artifact["path"] = "android-to-macos/source-clipboard-read.txt"
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
            "bidirectional_product_e2e: macos_nspasteboard_to_android_clipboardmanager.retained_artifacts[0].path for source_clipboard_read must be distinct from android_clipboardmanager_to_macos_nspasteboard source_clipboard_read artifact path",
            result["blockers"],
        )

    def test_clipboard_retained_artifact_roles_must_be_exact_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            unknown_artifact = retained_artifacts[0]
            duplicate_artifact = retained_artifacts[2]
            assert isinstance(unknown_artifact, dict)
            assert isinstance(duplicate_artifact, dict)
            unknown_artifact["role"] = "clipboard_summary"
            duplicate_artifact["role"] = "sender_action"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[0].role must be one of source_clipboard_read, sender_action, receiver_approval, protocol_packets, destination_clipboard_write, final_verification, negative_boundary_verification",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[2].role duplicates sender_action artifact",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing source_clipboard_read artifact",
            result["blockers"],
        )

    def test_clipboard_retained_artifact_direction_must_match_parent_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            paths = write_pass_inputs(root)
            document = product_e2e()
            directions = document["directions"]
            assert isinstance(directions, dict)
            android_to_macos = directions["android_clipboardmanager_to_macos_nspasteboard"]
            assert isinstance(android_to_macos, dict)
            retained_artifacts = android_to_macos["retained_artifacts"]
            assert isinstance(retained_artifacts, list)
            source_artifact = retained_artifacts[0]
            receiver_artifact = retained_artifacts[2]
            assert isinstance(source_artifact, dict)
            assert isinstance(receiver_artifact, dict)
            source_artifact.pop("direction")
            receiver_artifact["direction"] = "macos_nspasteboard_to_android_clipboardmanager"
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
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[0].direction must be android_clipboardmanager_to_macos_nspasteboard",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts[2].direction must be android_clipboardmanager_to_macos_nspasteboard",
            result["blockers"],
        )
        self.assertIn(
            "bidirectional_product_e2e: android_clipboardmanager_to_macos_nspasteboard.retained_artifacts missing receiver_approval artifact",
            result["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
