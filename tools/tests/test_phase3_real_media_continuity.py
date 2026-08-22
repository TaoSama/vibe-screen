from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_real_media_continuity import KIND, evaluate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "vibescreen_evidence.phase3_real_media_continuity"


HOST_REAL_MEDIA_LOG = """
2026-08-21T08:00:00Z Secure Internet product session started
2026-08-21T08:00:01Z ICE connected; DTLS connected; DataChannel vibescreen.media.v1 open
2026-08-21T08:00:01Z selected candidate pair relay(host.example:5349)
2026-08-21T08:00:02Z SCStream capture started
2026-08-21T08:00:02Z First frame received from ScreenCaptureKit display
2026-08-21T08:00:02Z VideoToolbox encoder configured codec=hevc size=1920x1200
2026-08-21T08:00:02Z encoded frame media_epoch=42 config_epoch=2 keyframe=true bytes=42000
"""

ANDROID_REAL_MEDIA_LOG = """
08-21 08:00:01.000 I VibeInternet: internet_stream_active session_epoch=42 route=relay
08-21 08:00:01.010 D VD: setupDecoder: 1920x1200, decoder=c2.android.hevc.decoder
08-21 08:00:01.011 D VD: Decoder started: c2.android.hevc.decoder
08-21 08:00:01.020 D VD: First frame: size=42000, header=[0,0,0,1], keyframe=true, surface=true, valid=true
08-21 08:00:01.040 D VD: First output frame! size=1920x1200, flags=0
08-21 08:00:03.000 D VD: Decode stats: input=120, output=120, dropped=0
"""

SCHEMA_PATH = REPOSITORY_ROOT / "tools/schemas/phase3-real-media-continuity.schema.json"


def write_log(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def assert_schema_shape(test_case: unittest.TestCase, document: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    test_case.assertTrue(set(document).issubset(set(schema["properties"])))
    for key in schema["required"]:
        test_case.assertIn(key, document)
    for key in ("conditions", "continuity_summary"):
        test_case.assertEqual(set(document[key]), set(schema["properties"][key]["properties"]))
    for record in document["inputs"]:
        test_case.assertEqual(set(record), set(schema["properties"]["inputs"]["items"]["properties"]))
    for stage in document["stages"]:
        test_case.assertEqual(set(stage), set(schema["properties"]["stages"]["items"]["properties"]))


class Phase3RealMediaContinuityTest(unittest.TestCase):
    def evaluate_logs(
        self,
        host_log: str = HOST_REAL_MEDIA_LOG,
        android_log: str = ANDROID_REAL_MEDIA_LOG,
        *,
        network_path: str = "public_internet",
        host_signing: str = "identity_signed",
        screen_recording: str = "granted",
    ) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host_path = write_log(root, "host.log", host_log)
            android_path = write_log(root, "android.log", android_log)
            return evaluate(
                host_logs=[host_path],
                android_logs=[android_path],
                repo=REPOSITORY_ROOT,
                network_path=network_path,
                host_signing=host_signing,
                screen_recording=screen_recording,
            )

    def test_complete_logs_pass_narrow_continuity_but_not_release_gate(self) -> None:
        result = self.evaluate_logs()

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["kind"], KIND)
        self.assertEqual(result["verdict"], "pass")
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertEqual(result["release_gate_effect"], "none")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["android_observation"]["route"], "relay")
        self.assertEqual(result["android_observation"]["reported_output_frame_count"], 120)
        self.assertEqual(result["continuity_summary"]["continuous_output_frames"], 120)
        self.assertEqual(
            result["continuity_summary"]["media_source"],
            "real_screencapturekit_or_cgdisplaystream",
        )
        self.assertTrue(result["continuity_summary"]["public_internet_path"])
        assert_schema_shape(self, result)

    def test_screen_recording_blocked_evidence_fails_closed(self) -> None:
        evidence_dir = (
            REPOSITORY_ROOT
            / "docs/changes/2026-08-04-phase-3-secure-internet/evidence"
            / "2026-08-18-nubia-p0110-current-main-real-media-blocked"
        )
        for path in (
            evidence_dir / "host-permission-window.log",
            evidence_dir / "android-blocked-window.log",
        ):
            if not path.is_file():
                self.skipTest(f"retained evidence log is absent: {path}")
        result = evaluate(
            host_logs=[evidence_dir / "host-permission-window.log"],
            android_logs=[evidence_dir / "android-blocked-window.log"],
            repo=REPOSITORY_ROOT,
            network_path="unknown",
            host_signing="identity_signed",
            screen_recording="blocked",
        )

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertTrue(result["host_observation"]["screen_recording_blocked"])
        self.assertIn(
            "ScreenCaptureKit/CGDisplayStream first-frame evidence is missing",
            result["reasons"],
        )
        self.assertIn(
            "Android MediaCodec first output frame evidence is missing",
            result["reasons"],
        )
        assert_schema_shape(self, result)

    def test_webrtc_marker_rejects_unrelated_substrings(self) -> None:
        host_log = HOST_REAL_MEDIA_LOG.replace(
            "ICE connected; DTLS connected; DataChannel vibescreen.media.v1 open",
            "device service notice slice complete",
        ).replace("selected candidate pair relay(host.example:5349)\n", "")
        android_log = ANDROID_REAL_MEDIA_LOG.replace(
            "internet_stream_active session_epoch=42 route=relay",
            "internet stream awaiting transport",
        )

        result = self.evaluate_logs(host_log=host_log, android_log=android_log)

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["host_observation"]["webrtc_transport_observed"])
        self.assertIn(
            "ICE/DTLS/DataChannel or Internet stream-active evidence is missing",
            result["reasons"],
        )

    def test_session_epoch_zero_counts_as_present(self) -> None:
        result = self.evaluate_logs(
            host_log=HOST_REAL_MEDIA_LOG.replace("media_epoch=42", "config_epoch=2"),
            android_log=ANDROID_REAL_MEDIA_LOG.replace("session_epoch=42", "session_epoch=0"),
        )

        self.assertNotIn(
            "Protocol v1 media/session epoch evidence is missing",
            result["reasons"],
        )

    def test_single_high_output_index_does_not_prove_continuity(self) -> None:
        result = self.evaluate_logs(
            android_log=ANDROID_REAL_MEDIA_LOG.replace(
                "Decode stats: input=120, output=120, dropped=0",
                "Output #120: decoder latency avg=6.1ms max=11.0ms input bufs avail=3, dropped=0",
            )
        )

        self.assertEqual(result["verdict"], "blocked")
        self.assertEqual(result["android_observation"]["maximum_output_frame_index"], 120)
        self.assertEqual(result["continuity_summary"]["continuous_output_frames"], 1)
        self.assertIn("Android output frame count is below 120", result["reasons"])

    def test_distinct_contiguous_output_indices_can_prove_continuity(self) -> None:
        output_lines = "\n".join(f"08-21 08:00:03.{index:03d} D VD: Output #{index}" for index in range(1, 121))
        result = self.evaluate_logs(
            android_log=ANDROID_REAL_MEDIA_LOG.replace(
                "Decode stats: input=120, output=120, dropped=0", output_lines
            )
        )

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["android_observation"]["maximum_output_frame_index"], 120)
        self.assertEqual(result["continuity_summary"]["continuous_output_frames"], 120)

    def test_observation_excerpts_and_external_paths_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external-evidence"
            external.mkdir()
            host_path = write_log(
                external,
                "host.log",
                HOST_REAL_MEDIA_LOG
                + "2026-08-21T08:00:04Z VideoToolbox failed for host=macbook-alice.local account=alice@example.com path=/Users/alice/raw.log peer=203.0.113.7\n",
            )
            android_path = write_log(
                external,
                "android.log",
                ANDROID_REAL_MEDIA_LOG
                + "08-21 08:00:04.000 E VideoDecoder: Codec error: turns://user:pass@example.invalid:5349 device serial: ABC123\n",
            )
            result = evaluate(
                host_logs=[host_path],
                android_logs=[android_path],
                repo=REPOSITORY_ROOT,
                network_path="public_internet",
                host_signing="identity_signed",
                screen_recording="granted",
                notes="source=/Users/alice/note.txt account=alice@example.com",
            )

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertNotIn("203.0.113.7", serialized)
        self.assertNotIn("turns://user:pass@example.invalid:5349", serialized)
        self.assertNotIn("ABC123", serialized)
        self.assertIn("[external]/host.log", serialized)
        self.assertIn("[redacted", serialized)

    def test_synthetic_marker_blocks_even_when_other_markers_exist(self) -> None:
        result = self.evaluate_logs(
            host_log=HOST_REAL_MEDIA_LOG + "synthetic Protocol v1 harness completed\n"
        )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn(
            "synthetic media markers are present in supplied logs", result["reasons"]
        )
        self.assertIn(
            "synthetic Protocol v1", result["host_observation"]["synthetic_markers"]
        )

    def test_started_capture_and_legacy_frame_count_do_not_replace_required_markers(self) -> None:
        host_log = HOST_REAL_MEDIA_LOG.replace(
            "First frame received from ScreenCaptureKit display\n", ""
        )
        android_log = ANDROID_REAL_MEDIA_LOG.replace(
            "Decode stats: input=120, output=120, dropped=0",
            "SC Frames received: 120",
        )

        result = self.evaluate_logs(host_log=host_log, android_log=android_log)

        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(result["host_observation"]["capture_started"])
        self.assertFalse(result["host_observation"]["real_capture_first_frame"])
        self.assertEqual(result["android_observation"]["maximum_output_frame_index"], 0)
        self.assertIn(
            "ScreenCaptureKit/CGDisplayStream first-frame evidence is missing",
            result["reasons"],
        )
        self.assertIn(
            "Android output frame count is below 120",
            result["reasons"],
        )

    def test_decoder_error_or_drop_fails_complete_runtime_evidence(self) -> None:
        result = self.evaluate_logs(
            android_log=ANDROID_REAL_MEDIA_LOG
            + "08-21 08:00:04.000 E VideoDecoder: Codec error: fixture\n"
            + "08-21 08:00:04.010 I VibeScreenTelemetry: {\"event\":\"frame_dropped\"}\n"
        )

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("Android decoder or Internet session errors were observed", result["reasons"])
        self.assertIn("Android dropped-frame count 1 exceeds 0", result["reasons"])


class Phase3RealMediaContinuityCliTest(unittest.TestCase):
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
            host_path = write_log(root, "host.log", HOST_REAL_MEDIA_LOG)
            android_path = write_log(root, "android.log", ANDROID_REAL_MEDIA_LOG)
            output_path = root / "result.json"

            result = self.run_cli(
                "--host-log",
                str(host_path),
                "--android-log",
                str(android_path),
                "--network-path",
                "public_internet",
                "--host-signing",
                "identity_signed",
                "--screen-recording",
                "granted",
                "--output",
                str(output_path),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["verdict"], "pass")

    def test_cli_returns_blocked_for_incomplete_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host_path = write_log(root, "host.log", "Screen recording permission not granted yet\n")
            android_path = write_log(root, "android.log", "session ended kind=TRANSPORT_CLOSED\n")

            result = self.run_cli(
                "--host-log",
                str(host_path),
                "--android-log",
                str(android_path),
                "--network-path",
                "unknown",
                "--host-signing",
                "unknown",
                "--screen-recording",
                "blocked",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("blocked:", result.stderr)
            self.assertEqual(json.loads(result.stdout)["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
