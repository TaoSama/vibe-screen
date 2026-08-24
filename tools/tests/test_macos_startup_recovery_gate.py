from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.macos_startup_recovery_gate import derive_gate


MODULE = "vibescreen_evidence.macos_startup_recovery_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "macos-startup-recovery-gate.schema.json"


def complete_evidence() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "macos_startup_recovery_evidence",
        "run_id": "2026-08-24-mac-mini-headless",
        "source_commit": "6cdb34a1",
        "mac_host": {
            "model": "Mac mini",
            "architecture": "arm64",
            "macos_version": "26.4.1",
            "macos_build": "25E123",
            "host_bundle_identifier": "dev.telemachus.display",
            "host_signing": "identity_signed",
            "host_cdhash": "abcd1234",
            "host_binary_sha256": "f" * 64,
            "screen_recording_permission": "granted",
            "accessibility_permission": "granted",
            "signing_report": "host-signing-and-permissions.txt",
            "permission_report": "host-signing-and-permissions.txt",
            "host_log": "telemachus.log",
        },
        "login_item": {
            "status": "enabled",
            "requires_approval": False,
            "reboot_or_logout_login_performed": True,
            "login_launch_observed": True,
            "manual_launch_used": False,
            "system_settings_artifact": "login-items.png",
            "launch_log": "login-launch.log",
        },
        "automatic_startup": {
            "auto_start_enabled": True,
            "startup_mode": "usb",
            "onboarding_completed": True,
            "first_server_start_observed": True,
            "client_render_observed": True,
            "startup_log": "startup.log",
            "client_render_artifact": "client-render.png",
        },
        "display": {
            "topology": "dummy_or_headless",
            "capturable_display_observed": True,
            "first_frame_observed": True,
            "display_uuid": "display-uuid",
            "claims_headless_from_attached_monitor": False,
            "dimensions": {
                "logical_width": 1920,
                "logical_height": 1080,
                "physical_width": 1920,
                "physical_height": 1080,
            },
            "display_report": "display.json",
            "first_frame_artifact": "first-frame.png",
        },
        "unattended_recovery": {
            "trigger": "listener_startup_failure",
            "observed": True,
            "retry_delays_seconds": [1, 2, 4, 8, 16, 30, 30, 30],
            "full_speed_loop_observed": False,
            "restart_succeeded": True,
            "bounded_exhaustion_observed": False,
            "logs_retained": True,
            "recovery_log": "unattended-recovery.log",
        },
        "window_recovery": {
            "move_observed": True,
            "disconnect_or_failure_trigger_observed": True,
            "restored_observed": True,
            "accessibility_error_observed": False,
            "original_frame": {"x": 100, "y": 100, "width": 800, "height": 600},
            "restored_frame": {"x": 100, "y": 100, "width": 800, "height": 600},
            "window_log": "window-recovery.log",
            "before_artifact": "window-before.png",
            "after_artifact": "window-after.png",
        },
        "remote_access": {
            "method": "screen_sharing",
            "operator_intervention_path_verified": True,
            "filevault_or_first_login_blocker_absent": True,
            "requires_unavailable_local_intervention": False,
            "access_artifact": "screen-sharing-settings.png",
        },
        "android_device": {
            "adb_serial": "redacted-p0110-serial",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": "36",
            "device_info": "device-info.json",
        },
    }


def write_artifacts(root: Path, evidence: dict) -> None:
    names: set[str] = set()
    for section in evidence.values():
        if not isinstance(section, dict):
            continue
        for value in section.values():
            if isinstance(value, str) and value.endswith((".txt", ".log", ".json", ".png")):
                names.add(value)
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact\n", encoding="utf-8")


class MacOSStartupRecoveryGateTest(unittest.TestCase):
    def test_complete_real_integration_evidence_can_close_login_headless_gate(self) -> None:
        report = derive_gate(complete_evidence())

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_login_headless_gate"])
        self.assertTrue(report["can_claim_headless_mac_mini_operation"])
        self.assertEqual(report["open_reasons"], [])
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_physical_display_pass_does_not_claim_headless_operation(self) -> None:
        evidence = complete_evidence()
        evidence["display"]["topology"] = "physical"

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_login_headless_gate"])
        self.assertFalse(report["can_claim_headless_mac_mini_operation"])

    def test_headless_claim_requires_mac_mini_model(self) -> None:
        evidence = complete_evidence()
        evidence["mac_host"]["model"] = "MacBook Pro"

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["can_close_login_headless_gate"])
        self.assertFalse(report["can_claim_headless_mac_mini_operation"])

    def test_missing_real_reboot_and_display_evidence_blocks(self) -> None:
        evidence = complete_evidence()
        evidence["login_item"]["reboot_or_logout_login_performed"] = False
        evidence["display"]["capturable_display_observed"] = False
        evidence["display"]["first_frame_observed"] = False

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertIn(
            "login_item_registration_and_launch: login_item.reboot_or_logout_login_performed must be true",
            report["open_reasons"],
        )
        self.assertIn(
            "headless_or_dummy_display_capture: display.capturable_display_observed must be true",
            report["open_reasons"],
        )

    def test_manual_launch_and_relabelled_attached_monitor_fail(self) -> None:
        evidence = complete_evidence()
        evidence["login_item"]["manual_launch_used"] = True
        evidence["display"]["claims_headless_from_attached_monitor"] = True

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertIn(
            "login_item_registration_and_launch: manual Finder/Dock launch cannot be counted as login-startup evidence",
            report["open_reasons"],
        )
        self.assertIn(
            "headless_or_dummy_display_capture: an attached monitor cannot be relabeled as dummy/headless evidence",
            report["open_reasons"],
        )

    def test_screen_sharing_cannot_relabel_attached_monitor_as_headless(self) -> None:
        evidence = complete_evidence()
        evidence["display"]["topology"] = "screen_sharing"
        evidence["display"]["claims_headless_from_attached_monitor"] = True

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertFalse(report["can_claim_headless_mac_mini_operation"])
        self.assertIn(
            "headless_or_dummy_display_capture: an attached monitor cannot be relabeled as dummy/headless evidence",
            report["open_reasons"],
        )

    def test_unbounded_recovery_and_accessibility_errors_fail(self) -> None:
        evidence = complete_evidence()
        evidence["unattended_recovery"]["full_speed_loop_observed"] = True
        evidence["window_recovery"]["accessibility_error_observed"] = True

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertIn(
            "unattended_listener_recovery: unattended_recovery.full_speed_loop_observed must be false",
            report["open_reasons"],
        )
        self.assertIn(
            "window_restore_on_disconnect_or_failure: window recovery cannot pass with Accessibility errors",
            report["open_reasons"],
        )

    def test_recovery_policy_and_window_frame_evidence_block_when_missing(self) -> None:
        evidence = complete_evidence()
        evidence["unattended_recovery"]["retry_delays_seconds"] = [1, 2, 4]
        evidence["unattended_recovery"]["restart_succeeded"] = False
        evidence["unattended_recovery"]["bounded_exhaustion_observed"] = False
        evidence["display"]["display_uuid"] = ""
        evidence["window_recovery"]["original_frame"] = {}
        evidence["window_recovery"]["restored_frame"] = {}

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_login_headless_gate"])
        for reason in (
            "unattended_listener_recovery: unattended_recovery.retry_delays_seconds must match the bounded 1,2,4,8,16,30,30,30 policy",
            "unattended_listener_recovery: unattended_recovery must record restart_succeeded or bounded_exhaustion_observed",
            "headless_or_dummy_display_capture: display.display_uuid is required",
            "window_restore_on_disconnect_or_failure: window_recovery.original_frame is required",
            "window_restore_on_disconnect_or_failure: window_recovery.restored_frame is required",
        ):
            self.assertIn(reason, report["open_reasons"])

    def test_p0110_identity_guard_rejects_xiaomi_relabel(self) -> None:
        evidence = complete_evidence()
        evidence["android_device"]["codename"] = "fuxi"
        evidence["android_device"]["manufacturer"] = "Xiaomi"

        report = derive_gate(evidence)

        self.assertEqual(report["verdict"], "fail")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertIn(
            "android_identity_label_guard: android_device.manufacturer must be 'nubia' for Nubia P0110/pacific evidence",
            report["open_reasons"],
        )
        self.assertIn(
            "android_identity_label_guard: Nubia P0110 evidence must not be relabeled as Xiaomi/fuxi",
            report["open_reasons"],
        )

    def test_cli_writes_aggregate_consumable_blocked_report(self) -> None:
        evidence = complete_evidence()
        evidence["mac_host"]["screen_recording_permission"] = "missing"

        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            write_artifacts(directory, evidence)
            input_path = directory / "startup-evidence.json"
            output_path = directory / "macos-startup-recovery-gate.json"
            input_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--evidence",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertEqual(report["kind"], "macos_startup_recovery_gate")

    def test_cli_blocks_pass_shaped_json_without_retained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            input_path = directory / "startup-evidence.json"
            output_path = directory / "macos-startup-recovery-gate.json"
            input_path.write_text(json.dumps(complete_evidence()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--evidence",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_login_headless_gate"])
        self.assertTrue(any("must exist under the evidence root" in reason for reason in report["open_reasons"]))

    def test_report_matches_schema_required_top_level_fields(self) -> None:
        report = derive_gate(complete_evidence())
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)


if __name__ == "__main__":
    unittest.main()
