from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
import io
import uuid
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.manifest import ManifestError
from vibescreen_evidence.phase2_tablet_manifest import build_manifest, main


DEVICE_INFO = {
    "device": {
        "adb_serial": "EP0110PZ0B9110300B",
        "device_serial": "EP0110PZ0B9110300B",
        "manufacturer": "nubia",
        "model": "P0110",
        "device": "pacific",
        "android_release": "16",
        "sdk": "36",
        "build_fingerprint": "nubia/pacific/test",
        "abi": "arm64-v8a",
    }
}
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase2-tablet-manifest.schema.json"


def assert_required_schema_fields(test_case: unittest.TestCase, value, schema):
    test_case.assertEqual(set(value), set(schema["properties"]))
    for field in schema.get("required", []):
        test_case.assertIn(field, value)
    for field, child_schema in schema.get("properties", {}).items():
        if isinstance(value.get(field), dict) and isinstance(child_schema, dict):
            required = child_schema.get("required", [])
            for child_field in required:
                test_case.assertIn(child_field, value[field], f"{field}.{child_field}")


def make_manifest(**overrides):
    arguments = {
        "command": ["make", "soak-8h"],
        "repo": Path("."),
        "device_info": DEVICE_INFO,
        "device_class": "physical_8_9_inch_tablet",
        "tablet_size_inches": "8.8",
        "stand_setup": "desktop stand portrait",
        "charger": "vendor 45W USB-C charger",
        "cable_or_dock": "USB-C data cable",
        "ambient_temperature_celsius": 24.0,
        "transport": "usb",
        "video_preferences": "Balanced, 60 FPS, AUTO bitrate",
        "duration_seconds": 28800,
        "sample_interval_seconds": 30,
        "thermal_limit_status": 2,
        "battery_temperature_limit_celsius": 45.0,
        "maximum_net_battery_drain_percent": 5,
        "recovery_scenarios": ["background_foreground", "usb_reconnect"],
        "host_identity": "Mac mini M4, macOS 26.4.1",
        "host_build": "Vibe Screen release build abc123",
        "apk_sha256": "abc123",
        "notes": None,
    }
    arguments.update(overrides)
    return build_manifest(**arguments)


class Phase2TabletManifestTests(unittest.TestCase):
    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_build_manifest_records_identity_setup_thresholds_and_open_gate_limits(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        manifest = make_manifest()

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], "phase2_tablet_sustained_use_manifest")
        uuid.UUID(manifest["run_id"])
        self.assertEqual(manifest["device"]["identity"]["model"], "P0110")
        self.assertEqual(manifest["device"]["identity"]["codename"], "pacific")
        self.assertEqual(manifest["physical_setup"]["charger"], "vendor 45W USB-C charger")
        self.assertEqual(manifest["session"]["duration_seconds"], 28800)
        self.assertIn("stand_mounted_charging", manifest["required_gates"])
        self.assertIn("phase2-tablet-manifest.json", manifest["required_artifacts"])
        self.assertIn("samples.jsonl", manifest["required_artifacts"])
        self.assertTrue(any("does not close" in item for item in manifest["limitations"]))

    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_build_manifest_matches_schema_required_fields(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        manifest = make_manifest()
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        assert_required_schema_fields(self, manifest, schema)
        assert_required_schema_fields(
            self, manifest["device"]["identity"], schema["properties"]["device"]["properties"]["identity"]
        )

    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_android_substitute_manifest_carries_tablet_gate_limitation(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        manifest = make_manifest(device_class="android_substitute", tablet_size_inches=None)

        self.assertEqual(manifest["device"]["device_class"], "android_substitute")
        self.assertIn(
            "The recorded device class is not a physical 8-9 inch tablet, so this manifest cannot close the tablet hardware gate.",
            manifest["limitations"],
        )

    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_rejects_short_duration_or_sparse_sampling(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with self.assertRaises(ManifestError):
            make_manifest(duration_seconds=28799)
        with self.assertRaises(ManifestError):
            make_manifest(sample_interval_seconds=61)

    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_rejects_incomplete_device_identity(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with self.assertRaisesRegex(ManifestError, "codename"):
            make_manifest(device_info={"device": {"model": "P0110"}})

    @patch("vibescreen_evidence.phase2_tablet_manifest.repository_state")
    def test_cli_writes_manifest_with_device_info(self, state):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            device_info = directory / "device-info.json"
            output = directory / "manifest.json"
            device_info.write_text(json.dumps(DEVICE_INFO), encoding="utf-8")
            exit_code = main(
                [
                    "--output",
                    str(output),
                    "--repo",
                    str(directory),
                    "--device-info",
                    str(device_info),
                    "--device-class",
                    "android_substitute",
                    "--stand-setup",
                    "bench stand",
                    "--charger",
                    "vendor charger",
                    "--cable-or-dock",
                    "USB-C cable",
                    "--transport",
                    "usb",
                    "--video-preferences",
                    "Balanced 60 FPS",
                    "--host-identity",
                    "Mac mini",
                    "--host-build",
                    "release build",
                    "--apk-sha256",
                    "abc123",
                    "--",
                    "make",
                    "soak-8h",
                ]
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["command"], ["make", "soak-8h"])
        self.assertEqual(manifest["device"]["identity"]["codename"], "pacific")

    def test_cli_rejects_missing_device_info_file(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "manifest.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--output",
                        str(output),
                        "--device-info",
                        str(directory / "missing-device-info.json"),
                        "--device-class",
                        "android_substitute",
                        "--stand-setup",
                        "bench stand",
                        "--charger",
                        "vendor charger",
                        "--cable-or-dock",
                        "USB-C cable",
                        "--transport",
                        "usb",
                        "--video-preferences",
                        "Balanced 60 FPS",
                        "--host-identity",
                        "Mac mini",
                        "--host-build",
                        "release build",
                        "--apk-sha256",
                        "abc123",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("failed to read device info", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
