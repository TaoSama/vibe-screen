from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.phase2_tablet_preflight import derive_preflight, main


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def touch(path: Path, value: str = "evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def manifest(device_class: str = "physical_8_9_inch_tablet", size: str | None = "8.8") -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_sustained_use_manifest",
        "device": {
            "device_class": device_class,
            "tablet_size_inches": size,
            "identity": {
                "adb_serial": "serial-1",
                "manufacturer": "Example",
                "model": "SmallTab",
                "codename": "smalltab",
                "android_release": "16",
            },
        },
    }


def p0110_physical_tablet_manifest() -> dict:
    document = manifest(device_class="physical_8_9_inch_tablet")
    document["device"]["identity"] = {
        "adb_serial": "P0110_TEST_SERIAL",
        "device_serial": "P0110_TEST_SERIAL",
        "manufacturer": "nubia",
        "model": "P0110",
        "codename": "pacific",
        "android_release": "16",
    }
    return document


def p0110_device_info() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "android_device_info",
        "device": {
            "adb_serial": "P0110_TEST_SERIAL",
            "device_serial": "P0110_TEST_SERIAL",
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
        },
    }


def device_info() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "android_device_info",
        "device": {
            "adb_serial": "serial-1",
            "manufacturer": "Example",
            "model": "SmallTab",
            "device": "smalltab",
            "android_release": "16",
        },
    }


def soak_gate(verdict: str = "pass") -> dict:
    criteria = {
        "thermal_status_max": {"passed": verdict == "pass", "measured": 1, "maximum": 2},
        "battery_temperature_celsius_max": {"passed": verdict == "pass", "measured": 36, "maximum": 45},
    }
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_tablet_productization_gate",
        "derivation_status": "complete",
        "verdict": verdict,
        "criteria": criteria,
    }


def device_environment_observations() -> dict:
    observations = {
        "android_device_lock_checked": True,
        "device_identity_recorded": True,
        "device_identity_matches_claim": True,
        "physical_8_9_inch_tablet_observed": True,
        "stand_mounted_setup_observed": True,
        "eight_hour_environment_window_observed": True,
        "battery_power_samples_retained": True,
        "thermal_samples_retained": True,
        "raw_platform_dumps_retained": True,
        "controlled_thermal_load_observed": True,
        "thermal_load_recovery_observed": True,
        "settings_status_matches_platform": True,
        "run_readme_retained": True,
    }
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_device_environment_observations",
        "observations": observations,
    }


def device_memory_gate(verdict: str = "pass") -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_device_memory_gate",
        "verdict": verdict,
    }


def device_environment_summary(verdict: str = "pass", *, can_close: bool = True) -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_device_environment_gate",
        "verdict": verdict,
        "can_close_device_environment_gate": can_close,
        "can_close_stand_charging_gate": can_close,
    }


def hardware_keyboard_summary(verdict: str = "pass") -> dict:
    observed = verdict == "pass"
    observations = {
        "android_device_lock_acquired": True,
        "device_identity_recorded": True,
        "device_identity_matches_claim": True,
        "apk_identity_recorded": True,
        "physical_keyboard_attached": observed,
        "android_keyboard_source_observed": observed,
        "protocol_keyboard_capability_negotiated": observed,
        "protocol_usb_hid_modifier_capability_negotiated": observed,
        "android_production_forwarding_observed": observed,
        "android_focus_ime_boundary_observed": observed,
        "selected_display_stream_observed": observed,
        "host_listener_observed": True,
        "host_stable_signed_tcc_ready": True,
        "host_key_injection_observed": observed,
        "host_ack_cgevent_log_observed": observed,
        "key_press_release_observed": observed,
        "modifier_press_release_observed": observed,
        "shortcut_combo_observed": observed,
        "modifier_release_no_leak_observed": observed,
        "visible_mac_result_observed": observed,
        "host_logs_retained": observed,
        "android_logs_retained": observed,
    }
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase2_hardware_keyboard_workflow",
        "profile": "phase2-hardware-keyboard-workflow",
        "verdict": verdict,
        "can_close_hardware_keyboard_gate": observed,
        "observations": observations,
    }


def stylus_summary(verdict: str = "pass") -> dict:
    observed = verdict == "pass"
    observations = {
        "adb_was_run": True,
        "device_identity_recorded": True,
        "device_identity_matches_claim": True,
        "pass_eligible_stylus_capability": True,
        "physical_drawing_observed": observed,
        "android_stylus_forwarding_observed": observed,
        "host_stylus_injection_observed": observed,
        "visible_drawing_result_observed": observed,
        "android_diag_log_retained": observed,
        "host_log_window_retained": observed,
        "collector_reported_passed": observed,
    }
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "physical_stylus_drawing_app",
        "profile": "physical-stylus-drawing-app",
        "verdict": verdict,
        "can_close_physical_stylus_gate": observed,
        "observations": observations,
    }


def populate_complete_bundle(root: Path, *, device_class: str = "physical_8_9_inch_tablet", soak_verdict: str = "pass") -> None:
    write_json(root / "phase2-tablet-manifest.json", manifest(device_class=device_class))
    write_json(root / "device-info.json", device_info())
    for relative in (
        "README.md",
        "device.txt",
        "host.txt",
        "build.txt",
        "apk-sha256.txt",
        "soak-8h/samples.jsonl",
        "soak-8h/summary.json",
        "soak-8h/host-telemetry.jsonl",
        "adb-battery-before.txt",
        "adb-battery-after.txt",
        "adb-power-before.txt",
        "adb-power-after.txt",
        "thermal-before.txt",
        "thermal-after.txt",
        "thermal-before.err",
        "thermal-after.err",
        "raw-logcat.txt",
        "host.log",
        "reconnects.log",
        "frame-drops.log",
        "decoder-telemetry.jsonl",
    ):
        touch(root / relative)
    touch(root / "screenshots/sustained-use-portrait.png", "png")
    touch(root / "screenshots/sustained-use-landscape.png", "png")
    write_json(root / "orientation-evidence.json", {"status": "pass"})
    write_json(root / "stylus-evidence.json", {"status": "pass", "observed_physical_drawing": True})
    write_json(
        root / "hardware-keyboard-evidence.json",
        {"status": "pass", "observed_physical_keyboard": True, "host_input_observed": True},
    )
    write_json(root / "soak-8h" / "phase2-tablet-gate.json", soak_gate(soak_verdict))
    write_json(root / "phase2-device-environment-observations.json", device_environment_observations())
    write_json(root / "soak-8h" / "phase2-device-memory-gate.json", device_memory_gate())
    write_json(root / "soak-8h" / "phase2-device-environment-summary.json", device_environment_summary())
    write_json(
        root / "recovery-evidence.json",
        {
            "status": "pass",
            "scenarios": {
                "foreground_background": "pass",
                "transport_reconnect": {"status": "pass"},
                "login_startup_or_headless": {"status": "pass"},
            },
            "stale_frame_or_input_accepted": False,
        },
    )


class Phase2TabletPreflightTest(unittest.TestCase):
    def test_complete_physical_tablet_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["reasons"], [])
        self.assertTrue(all(gate["status"] == "pass" for gate in result["gates"]))
        raw_gate = next(gate for gate in result["gates"] if gate["name"] == "raw_evidence_bundle")
        self.assertIn("soak-8h/samples.jsonl", raw_gate["evidence"])
        self.assertIn("soak-8h/host-telemetry.jsonl", raw_gate["evidence"])

    def test_missing_optional_host_log_does_not_block_raw_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "host.log").unlink()

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")
        self.assertFalse(any("host.log" in reason for reason in result["reasons"]))

    def test_android_substitute_is_blocked_not_tablet_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root, device_class="android_substitute")

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "blocked")
        physical_gate = next(gate for gate in result["gates"] if gate["name"] == "physical_8_9_inch_tablet")
        self.assertEqual(physical_gate["status"], "blocked")
        self.assertIn("android_substitute", physical_gate["reasons"][0])

    def test_known_phone_substitute_mislabeled_as_physical_tablet_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            write_json(root / "phase2-tablet-manifest.json", p0110_physical_tablet_manifest())
            write_json(root / "device-info.json", p0110_device_info())

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "blocked")
        physical_gate = next(gate for gate in result["gates"] if gate["name"] == "physical_8_9_inch_tablet")
        self.assertEqual(physical_gate["status"], "blocked")
        self.assertIn("Nubia P0110/pacific", physical_gate["reasons"][0])

    def test_missing_hardware_artifacts_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            write_json(root / "phase2-tablet-manifest.json", manifest())
            write_json(root / "device-info.json", device_info())

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("portrait" in reason for reason in result["reasons"]))
        self.assertTrue(any("hardware keyboard" in reason for reason in result["reasons"]))

    def test_hardware_keyboard_gate_accepts_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "hardware-keyboard-evidence.json").unlink()
            write_json(root / "hardware-keyboard-summary.json", hardware_keyboard_summary())

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")
        keyboard = next(gate for gate in result["gates"] if gate["name"] == "hardware_keyboard")
        self.assertEqual(keyboard["status"], "pass")

    def test_hardware_keyboard_gate_accepts_ack_cgevent_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "hardware-keyboard-evidence.json").unlink()
            summary = hardware_keyboard_summary()
            summary["observations"]["host_key_injection_observed"] = False
            write_json(root / "hardware-keyboard-summary.json", summary)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")
        keyboard = next(gate for gate in result["gates"] if gate["name"] == "hardware_keyboard")
        self.assertEqual(keyboard["status"], "pass")
        self.assertIn("hardware-keyboard-summary.json", keyboard["evidence"])

    def test_hardware_keyboard_gate_preserves_blocked_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "hardware-keyboard-evidence.json").unlink()
            write_json(root / "hardware-keyboard-summary.json", hardware_keyboard_summary("blocked"))

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "blocked")
        keyboard = next(gate for gate in result["gates"] if gate["name"] == "hardware_keyboard")
        self.assertEqual(keyboard["status"], "blocked")

    def test_hardware_keyboard_gate_rejects_contradictory_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "hardware-keyboard-evidence.json").unlink()
            summary = hardware_keyboard_summary()
            summary["can_close_hardware_keyboard_gate"] = False
            summary["observations"]["android_production_forwarding_observed"] = False
            write_json(root / "hardware-keyboard-summary.json", summary)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        keyboard = next(gate for gate in result["gates"] if gate["name"] == "hardware_keyboard")
        self.assertEqual(keyboard["status"], "insufficient")

    def test_stylus_gate_accepts_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "stylus-evidence.json").unlink()
            write_json(root / "stylus-summary.json", stylus_summary())

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")
        stylus = next(gate for gate in result["gates"] if gate["name"] == "physical_stylus")
        self.assertEqual(stylus["status"], "pass")
        self.assertIn("stylus-summary.json", stylus["evidence"])

    def test_stylus_gate_preserves_blocked_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "stylus-evidence.json").unlink()
            write_json(root / "stylus-summary.json", stylus_summary("blocked"))

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "blocked")
        stylus = next(gate for gate in result["gates"] if gate["name"] == "physical_stylus")
        self.assertEqual(stylus["status"], "blocked")

    def test_stylus_gate_rejects_contradictory_schema_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "stylus-evidence.json").unlink()
            summary = stylus_summary()
            summary["can_close_physical_stylus_gate"] = False
            summary["observations"]["host_stylus_injection_observed"] = False
            write_json(root / "stylus-summary.json", summary)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        stylus = next(gate for gate in result["gates"] if gate["name"] == "physical_stylus")
        self.assertEqual(stylus["status"], "insufficient")

    def test_hardware_keyboard_gate_requires_current_schema_pass_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "hardware-keyboard-evidence.json").unlink()
            summary = hardware_keyboard_summary()
            summary["observations"].pop("android_focus_ime_boundary_observed")
            write_json(root / "hardware-keyboard-summary.json", summary)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        keyboard = next(gate for gate in result["gates"] if gate["name"] == "hardware_keyboard")
        self.assertEqual(keyboard["status"], "insufficient")

    def test_soak_failure_fails_whole_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root, soak_verdict="fail")

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "fail")
        soak = next(gate for gate in result["gates"] if gate["name"] == "eight_hour_sustained_stream")
        self.assertEqual(soak["status"], "fail")

    def test_missing_derived_gates_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            (root / "soak-8h" / "phase2-device-memory-gate.json").unlink()
            (root / "soak-8h" / "phase2-device-environment-summary.json").unlink()
            (root / "phase2-device-environment-observations.json").unlink()

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("device-memory" in reason for reason in result["reasons"]))
        self.assertTrue(any("device-environment summary" in reason for reason in result["reasons"]))
        self.assertTrue(any("device-environment observations" in reason for reason in result["reasons"]))

    def test_blocked_device_environment_summary_keeps_bundle_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            write_json(
                root / "soak-8h" / "phase2-device-environment-summary.json",
                device_environment_summary("blocked", can_close=False),
            )

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(item for item in result["gates"] if item["name"] == "stand_charging_thermal_power")
        self.assertEqual(gate["status"], "blocked")

    def test_device_environment_observations_require_all_boolean_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            observations = device_environment_observations()
            del observations["observations"]["controlled_thermal_load_observed"]
            write_json(root / "phase2-device-environment-observations.json", observations)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        gate = next(item for item in result["gates"] if item["name"] == "device_environment_observations")
        self.assertEqual(gate["status"], "insufficient")
        self.assertTrue(any("controlled_thermal_load_observed" in reason for reason in gate["reasons"]))

    def test_cli_writes_report_and_returns_nonzero_for_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "preflight.json"
            populate_complete_bundle(root, device_class="android_substitute")
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--evidence-dir", str(root), "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["verdict"], "blocked")

    def test_device_key_codename_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            mismatched_manifest = manifest()
            mismatched_manifest["device"]["identity"]["codename"] = "wrong-name"
            write_json(root / "phase2-tablet-manifest.json", mismatched_manifest)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("codename='wrong-name'" in reason for reason in result["reasons"]))

    def test_explicit_codename_takes_precedence_over_device_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            info = device_info()
            info["device"]["device"] = "wrong-device-field"
            info["device"]["codename"] = "smalltab"
            write_json(root / "device-info.json", info)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "pass")

    def test_missing_stale_recovery_field_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            recovery = json.loads((root / "recovery-evidence.json").read_text(encoding="utf-8"))
            del recovery["stale_frame_or_input_accepted"]
            write_json(root / "recovery-evidence.json", recovery)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("stale_frame_or_input_accepted" in reason for reason in result["reasons"]))

    def test_recovery_requires_login_startup_or_headless_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            recovery = json.loads((root / "recovery-evidence.json").read_text(encoding="utf-8"))
            del recovery["scenarios"]["login_startup_or_headless"]
            write_json(root / "recovery-evidence.json", recovery)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("login_startup_or_headless" in reason for reason in result["reasons"]))

    def test_stale_frame_or_input_true_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_complete_bundle(root)
            recovery = json.loads((root / "recovery-evidence.json").read_text(encoding="utf-8"))
            recovery["stale_frame_or_input_accepted"] = True
            write_json(root / "recovery-evidence.json", recovery)

            result = derive_preflight(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(any("stale frame or input acceptance" in reason for reason in result["reasons"]))

    def test_report_evidence_dir_is_repo_relative_inside_repository(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        if not (repo_root / ".git").exists():
            self.skipTest("repository root .git marker is unavailable")
        relative = Path(".build/test-phase2-preflight-relative")
        root = repo_root / relative
        if root.exists():
            for path in sorted(root.glob("**/*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
        try:
            populate_complete_bundle(root, device_class="android_substitute")
            result = derive_preflight(root)
        finally:
            if root.exists():
                for path in sorted(root.glob("**/*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                root.rmdir()

        self.assertEqual(result["evidence_dir"], relative.as_posix())
        self.assertFalse(Path(result["evidence_dir"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
