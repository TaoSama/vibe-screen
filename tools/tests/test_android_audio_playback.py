import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.android_audio_playback import (
    BOOLEAN_FIELDS,
    AndroidAudioPlaybackEvidenceError,
    summarize,
)


MODULE = "vibescreen_evidence.android_audio_playback"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "android-audio-playback.schema.json"


class AndroidAudioPlaybackEvidenceTest(unittest.TestCase):
    def complete_record(self) -> dict[str, object]:
        record: dict[str, object] = {field: True for field in BOOLEAN_FIELDS}
        record["transport"] = "usb"
        record["device"] = {
            "adb_serial": "<ANDROID_SERIAL>",
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
            "sdk": 36,
            "build_fingerprint": "nubia/pacific/pacific:16/example:userdebug/test-keys",
        }
        record["artifact_paths"] = [
            "device-info.json",
            "host-audio.log",
            "android-audio-logcat.txt",
            "audible-playback-note.txt",
        ]
        record["notes"] = "nubia P0110/pacific USB audio smoke completed."
        return record

    def write_artifacts(self, evidence_dir: Path, record: dict[str, object]) -> None:
        for artifact in record["artifact_paths"]:
            path = evidence_dir / str(artifact)
            path.write_text(f"retained {artifact}\n", encoding="utf-8")

    def test_pass_requires_every_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, run_id="run-1", evidence_dir=evidence_dir)

        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_android_audio_playback_gate"])
        self.assertEqual(summary["transport"], "usb")
        self.assertEqual(summary["missing_requirements"], [])
        self.assertTrue(summary["observations"]["device_identity_structured"])
        self.assertTrue(summary["observations"]["retained_artifacts_available"])

    def test_trusted_lan_is_supported_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["transport"] = "trusted-lan"
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["transport"], "trusted_lan")
        self.assertEqual(summary["verdict"], "pass")

    def test_all_true_booleans_without_retained_artifacts_cannot_pass(self) -> None:
        summary = summarize(self.complete_record())

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_android_audio_playback_gate"])
        self.assertIn(
            "retained_artifacts_available",
            [item["field"] for item in summary["blocking_reasons"]],
        )

    def test_rejects_unstructured_device_identity_on_pass_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["device"] = {"model": "P0110"}
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["device_identity_structured"])
        self.assertIn(
            "device_identity_structured",
            [item["field"] for item in summary["blocking_reasons"]],
        )

    def test_rejects_mixed_p0110_and_fuxi_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["device"] = {
                "adb_serial": "<ANDROID_SERIAL>",
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "fuxi",
                "android_release": "16",
                "sdk": 36,
                "build_fingerprint": "xiaomi/fuxi/fuxi:16/example:userdebug/test-keys",
            }
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["device_identity_structured"])

    def test_blocks_when_host_signing_tcc_or_listener_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["host_stable_signed_tcc_ready"] = False
            record["host_listener_observed"] = False
            record["protocol_v1_session_observed"] = False
            record["notes"] = "Vibe Screen Dev signing identity missing; Host listener absent."
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_android_audio_playback_gate"])
        self.assertEqual(
            {item["field"] for item in summary["blocking_reasons"]},
            {
                "host_stable_signed_tcc_ready",
                "host_listener_observed",
                "protocol_v1_session_observed",
            },
        )
        self.assertIn(record["notes"], summary["blocking_notes"])

    def test_blocks_for_loopback_or_unknown_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["transport"] = "loopback"
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["transport_supported"])
        self.assertIn(
            "transport_supported",
            [item["field"] for item in summary["blocking_reasons"]],
        )

    def test_insufficient_when_audible_confirmation_is_missing_after_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["playback_output_confirmed"] = False
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertEqual(summary["blocking_reasons"], [])
        self.assertFalse(summary["can_close_android_audio_playback_gate"])

    def test_android_only_logs_cannot_close_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            record["host_microphone_capture_started"] = False
            record["host_audio_packets_sent"] = False
            record["host_logs_retained"] = False
            self.write_artifacts(evidence_dir, record)

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertTrue(summary["android_only_logs_are_not_playback_evidence"])
        self.assertFalse(summary["can_close_android_audio_playback_gate"])

    def test_summary_matches_schema_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir)
            record = self.complete_record()
            self.write_artifacts(evidence_dir, record)
            summary = summarize(record, evidence_dir=evidence_dir)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        observation_schema = schema["properties"]["observations"]

        self.assertEqual(set(summary), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, summary)
        self.assertEqual(set(summary["observations"]), set(observation_schema["properties"]))
        for field in observation_schema["required"]:
            self.assertIn(field, summary["observations"])

    def test_rejects_non_boolean_observations(self) -> None:
        record = self.complete_record()
        record["audio_config_accepted"] = "true"

        with self.assertRaisesRegex(AndroidAudioPlaybackEvidenceError, "audio_config_accepted"):
            summarize(record)

    def test_rejects_non_object_device(self) -> None:
        record = self.complete_record()
        record["device"] = "nubia P0110"

        with self.assertRaisesRegex(AndroidAudioPlaybackEvidenceError, "device"):
            summarize(record)

    def test_absolute_artifact_outside_evidence_dir_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "evidence"
            evidence_dir.mkdir()
            outside = Path(tmpdir) / "host-audio.log"
            outside.write_text("host audio\n", encoding="utf-8")
            record = self.complete_record()
            record["artifact_paths"] = [
                "device-info.json",
                str(outside),
                "android-audio-logcat.txt",
                "audible-playback-note.txt",
            ]
            for artifact in (
                "device-info.json",
                "android-audio-logcat.txt",
                "audible-playback-note.txt",
            ):
                (evidence_dir / artifact).write_text("retained\n", encoding="utf-8")

            summary = summarize(record, evidence_dir=evidence_dir)

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["observations"]["retained_artifacts_available"])
        self.assertFalse(summary["artifact_checks"][1]["under_evidence_dir"])

    def test_rejects_empty_artifact_paths(self) -> None:
        record = self.complete_record()
        record["artifact_paths"] = ["host.log", ""]

        with self.assertRaisesRegex(AndroidAudioPlaybackEvidenceError, "artifact_paths"):
            summarize(record)

    def test_rejects_empty_run_id(self) -> None:
        with self.assertRaisesRegex(AndroidAudioPlaybackEvidenceError, "run_id"):
            summarize(self.complete_record(), run_id="")


class AndroidAudioPlaybackCliTest(unittest.TestCase):
    def test_cli_outputs_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--run-id", "run-cli"],
            input=json.dumps({"transport": "usb", "device_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["run_id"], "run-cli")
        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_android_audio_playback_gate"])
        self.assertTrue(summary["loopback_or_synthetic_is_not_playback_evidence"])
        self.assertFalse(summary["observations"]["device_identity_structured"])

    def test_require_pass_returns_nonzero_for_blocked_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", MODULE, "-", "--require-pass"],
            input=json.dumps({"transport": "usb", "device_identity_recorded": True}),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["can_close_android_audio_playback_gate"])


if __name__ == "__main__":
    unittest.main()
