from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_real_media_current_base import KIND, derive_gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "vibescreen_evidence.phase3_real_media_current_base"
SCHEMA_PATH = REPOSITORY_ROOT / "tools/schemas/phase3-real-media-current-base.schema.json"
CURRENT_COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPOSITORY_ROOT,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def continuity_result(
    *,
    verdict: str = "pass",
    commit: str = CURRENT_COMMIT,
    dirty: bool = False,
    network_path: str = "public_internet",
    host_signing: str = "identity_signed",
    screen_recording: str = "granted",
    media_source: str = "real_screencapturekit_or_cgdisplaystream",
    capture_frames: int = 3,
    videotoolbox_frames: int = 120,
    route: str | None = "relay",
    output_frames: int = 120,
    dropped_frames: int = 0,
    decoder_errors: int = 0,
    synthetic_marker: bool = False,
    device: dict[str, object] | None = None,
) -> dict[str, object]:
    if device is None:
        device = {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": 36,
            "hardware_serial": "[redacted]",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "phase3_real_media_continuity_preflight",
        "created_at": "2026-08-23T00:00:00+00:00",
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "conditions": {
            "network_path": network_path,
            "host_signing": host_signing,
            "screen_recording": screen_recording,
            "minimum_output_frames": 120,
            "maximum_dropped_frames": 0,
        },
        "repository": {
            "revision": commit,
            "branch": "codex/phase3-real-media-continuity",
            "dirty": dirty,
        },
        "device": device,
        "inputs": [],
        "continuity_summary": {
            "media_source": media_source,
            "public_internet_path": network_path == "public_internet",
            "selected_webrtc_route": route,
            "protocol_v1_media_epochs": [7],
            "protocol_v1_session_epoch": 7,
            "capture_sources": ["ScreenCaptureKit"],
            "capture_frame_count": capture_frames,
            "videotoolbox_output_frames": videotoolbox_frames,
            "videotoolbox_output_epochs": [7],
            "mediacodec_first_input_frame": True,
            "mediacodec_first_input_epochs": [7],
            "mediacodec_first_output_frame": True,
            "mediacodec_first_output_epochs": [7],
            "shared_pipeline_epochs": [7],
            "continuous_output_frames": output_frames,
            "dropped_frames": dropped_frames,
            "decoder_error_count": decoder_errors,
        },
        "host_observation": {
            "screen_recording_blocked": False,
            "synthetic_markers": ["synthetic Protocol v1"] if synthetic_marker else [],
        },
        "android_observation": {"synthetic_markers": []},
        "stages": [],
        "reasons": [] if verdict == "pass" else ["fixture reason"],
        "release_gate_effect": "none",
    }


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def write_png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    return path


def assert_schema_shape(test_case: unittest.TestCase, document: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    test_case.assertEqual(set(document), set(schema["properties"]))
    for key in schema["required"]:
        test_case.assertIn(key, document)
    test_case.assertEqual(set(document["checks"]), set(schema["properties"]["checks"]["properties"]))


class Phase3RealMediaCurrentBaseGateTests(unittest.TestCase):
    def derive(
        self,
        root: Path,
        result: dict[str, object] | None = None,
        *,
        ui: bool = True,
        ui_note: str | None = "Android UI shows decoded Mac desktop content on the Vibe Screen surface.",
        current_commit: str = CURRENT_COMMIT,
    ) -> dict[str, object]:
        continuity = write_json(root / "real-media-continuity.json", result or continuity_result())
        ui_paths = [write_png(root / "android-visible-ui.png")] if ui else []
        return derive_gate(
            continuity_result=continuity,
            repo=REPOSITORY_ROOT,
            android_ui_evidence=ui_paths,
            android_ui_note=ui_note,
            current_commit=current_commit,
        )

    def test_complete_current_base_media_and_visible_ui_passes_child_gate_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory))

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["kind"], KIND)
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["can_claim_current_base_real_media_continuity"])
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertEqual(result["release_gate_effect"], "child_gate_only")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["owner"]["role"], "phase3_real_media_current_base_owner")
        self.assertEqual(result["device"]["manufacturer"], "nubia")
        self.assertEqual(result["device"]["model"], "P0110")
        self.assertEqual(result["device"]["codename"], "pacific")
        self.assertEqual(result["device"]["android_version"], "16")
        self.assertEqual(result["device"]["sdk"], 36)
        self.assertTrue(result["checks"]["visible_android_ui"]["passed"])
        assert_schema_shape(self, result)

    def test_missing_visible_ui_artifact_blocks_otherwise_complete_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), ui=False)

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_claim_current_base_real_media_continuity"])
        self.assertIn("blocked: visible_android_ui", result["reasons"])

    def test_empty_ui_note_blocks_artifact_only_claim(self) -> None:
        for note in (None, "   "):
            with self.subTest(note=note), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), ui_note=note)

            self.assertEqual(result["verdict"], "blocked")
            self.assertIn("blocked: visible_android_ui", result["reasons"])

    def test_text_file_cannot_be_used_as_visible_ui_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuity = write_json(root / "real-media-continuity.json", continuity_result())
            fake_ui = root / "android-visible-ui.txt"
            fake_ui.write_text("decoded video visible", encoding="utf-8")

            result = derive_gate(
                continuity_result=continuity,
                repo=REPOSITORY_ROOT,
                android_ui_evidence=[fake_ui],
                android_ui_note="visible",
                current_commit=CURRENT_COMMIT,
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: visible_android_ui", result["reasons"])

    def test_old_or_dirty_continuity_result_is_not_current_base(self) -> None:
        cases = {
            "old_commit": continuity_result(commit="b" * 40),
            "dirty_source": continuity_result(dirty=True),
        }
        for label, continuity in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), continuity)

            self.assertEqual(result["verdict"], "blocked")
            self.assertFalse(result["can_claim_current_base_real_media_continuity"])

    def test_forced_local_turn_cannot_substitute_for_public_internet_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                continuity_result(network_path="local_forced_turn", route="relay"),
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: public_internet_path", result["reasons"])

    def test_synthetic_marker_blocks_even_with_visible_ui_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity_result(synthetic_marker=True))

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: no_synthetic_media", result["reasons"])

    def test_missing_capture_source_metadata_blocks(self) -> None:
        continuity = continuity_result()
        continuity["continuity_summary"]["capture_sources"] = []
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: real_capture_source_metadata", result["reasons"])

    def test_missing_shared_pipeline_epoch_blocks(self) -> None:
        continuity = continuity_result()
        continuity["continuity_summary"]["shared_pipeline_epochs"] = []
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity)

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: shared_pipeline_epoch", result["reasons"])

    def test_missing_device_identity_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity_result(device={"model": "P0110"}))

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: android_device_identity", result["reasons"])

    def test_boolean_sdk_does_not_satisfy_device_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                continuity_result(
                    device={
                        "manufacturer": "nubia",
                        "model": "P0110",
                        "codename": "pacific",
                        "android_version": "16",
                        "sdk": True,
                    }
                ),
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: android_device_identity", result["reasons"])

    def test_device_info_collector_shape_is_normalized_without_unique_ids(self) -> None:
        device = {
            "adb_serial": "EP0110PZ0B9110300B",
            "device_serial": "EP0110PZ0B9110300B",
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
            "sdk": 36,
            "build_fingerprint": "nubia/pacific/fingerprint",
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity_result(device=device))

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(
            result["device"],
            {
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_version": "16",
                "sdk": 36,
            },
        )
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("EP0110PZ0B9110300B", serialized)
        self.assertNotIn("fingerprint", serialized)

    def test_decoder_errors_fail_after_required_stages_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), continuity_result(decoder_errors=1))

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: no_decoder_errors", result["reasons"])

    def test_external_paths_and_ui_notes_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuity = write_json(
                root / "real-media-continuity.json",
                continuity_result(
                    device={
                        "manufacturer": "nubia",
                        "model": "P0110",
                        "codename": "pacific",
                        "android_version": "16",
                        "sdk": 36,
                        "hardware_serial": "device serial: ABC123",
                    }
                ),
            )
            external = root / "external"
            external.mkdir()
            ui = write_png(external / "android-visible-ui.png")
            result = derive_gate(
                continuity_result=continuity,
                repo=REPOSITORY_ROOT,
                android_ui_evidence=[ui],
                android_ui_note="source=/Users/alice/frame.png account=alice@example.com host=203.0.113.7",
                current_commit=CURRENT_COMMIT,
            )

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertNotIn("203.0.113.7", serialized)
        self.assertNotIn("ABC123", serialized)
        self.assertIn("[external]/android-visible-ui.png", serialized)
        self.assertIn("[redacted", serialized)


class Phase3RealMediaCurrentBaseCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = "tools"
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_cli_writes_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuity = write_json(root / "real-media-continuity.json", continuity_result())
            ui = write_png(root / "android-visible-ui.png")
            output = root / "current-base-real-media.json"

            result = self.run_cli(
                "--continuity-result",
                str(continuity),
                "--android-ui-evidence",
                str(ui),
                "--android-ui-note",
                "Android UI shows decoded Mac desktop content.",
                "--current-commit",
                CURRENT_COMMIT,
                "--output",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["verdict"], "pass")

    def test_cli_returns_blocked_for_missing_ui(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuity = write_json(root / "real-media-continuity.json", continuity_result())

            result = self.run_cli(
                "--continuity-result",
                str(continuity),
                "--current-commit",
                CURRENT_COMMIT,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "blocked")
        self.assertIn("blocked: visible_android_ui", result.stderr)


if __name__ == "__main__":
    unittest.main()
