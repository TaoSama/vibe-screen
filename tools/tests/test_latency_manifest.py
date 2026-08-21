import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import GATE_INPUT_P95_SUB50, GATE_USB_GLASS_TO_GLASS_SUB50
from tools.vibescreen_evidence.latency_evidence import build_latency_evidence_report
from tools.vibescreen_evidence.latency_manifest import (
    LatencyManifestError,
    build_latency_manifest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_manifest"


def _base_metadata() -> dict[str, object]:
    return {
        "run_id": "fixture-latency-manifest",
        "latency_kind": "glass-to-glass",
        "transport": "usb",
        "gate_profile": GATE_USB_GLASS_TO_GLASS_SUB50,
        "camera": {
            "manufacturer": "Fixture Camera Co",
            "model": "Synthetic 240",
            "mode": "1080p240",
            "frame_rate_fps": 240,
            "shutter_mode": "fixed",
        },
        "recording_operator": "fixture",
        "samples_format": "csv",
        "annotation_method": "manual-frame-count",
        "annotator": "fixture",
        "device": {
            "manufacturer": "Fixture",
            "model": "Fixture Device",
            "codename": "fixture",
            "os_version": "Android fixture",
        },
        "host": {"model": "Fixture Mac", "macos_version": "fixture"},
        "build": {
            "repository_revision": "fixture-revision",
            "host_artifact": "fixture-host",
            "client_artifact": "fixture-client",
        },
        "measurement_setup": {
            "stimulus": "mac display flash visible to the camera",
            "start_event_definition": "first camera frame where the Mac stimulus changes",
            "end_event_definition": "first camera frame where the Android render shows the same change",
            "lighting": "stable indoor light",
            "mounting": "fixed tripod framing both screens",
            "clock_domain": "single-external-camera-timebase",
            "max_frame_annotation_uncertainty_ms": 4.2,
            "notes": "Synthetic test package only.",
        },
        "recorded_at": "2026-08-21T00:00:00Z",
    }


def _write_fixture_files(root: Path) -> tuple[Path, Path]:
    raw_video = root / "raw-camera-placeholder.mov"
    samples = root / "samples.csv"
    raw_video.write_bytes(b"synthetic camera placeholder")
    samples.write_text(
        "start_frame,end_frame,camera_fps\n"
        "100,108,240\n200,209,240\n300,309,240\n400,409,240\n500,509,240\n",
        encoding="utf-8",
    )
    return raw_video, samples


def _write_synchronized_clock_samples(root: Path) -> Path:
    samples = root / "samples.csv"
    samples.write_text("latency_ms\n12.5\n18.3\n15.1\n22.4\n19.7\n", encoding="utf-8")
    return samples


class LatencyManifestBuilderTest(unittest.TestCase):
    def test_builds_manifest_that_formal_checker_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            metadata = _base_metadata()

            manifest = build_latency_manifest(
                evidence_dir=root,
                raw_video=raw_video,
                samples=samples,
                **metadata,
            )
            (root / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )
            raw_video_sha256 = hashlib.sha256(raw_video.read_bytes()).hexdigest()

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(manifest["recording"]["raw_video"], raw_video.name)
        self.assertEqual(manifest["samples"]["file"], samples.name)
        self.assertEqual(manifest["recording"]["sha256"], raw_video_sha256)

    def test_rejects_profile_kind_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            metadata = _base_metadata()
            metadata["latency_kind"] = "input"

            with self.assertRaisesRegex(LatencyManifestError, "requires latency kind"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    **metadata,
                )

    def test_rejects_referenced_files_outside_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            raw_video, _samples = _write_fixture_files(root)
            outside_samples = Path(directory) / "outside-samples.csv"
            outside_samples.write_text("latency_ms\n10\n", encoding="utf-8")
            metadata = _base_metadata()

            with self.assertRaisesRegex(LatencyManifestError, "inside the evidence directory"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=outside_samples,
                    **metadata,
                )


class LatencyManifestCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def valid_cli_args(self, root: Path, raw_video: Path, samples: Path) -> list[str]:
        return [
            "--evidence-dir",
            str(root),
            "--run-id",
            "cli-latency-manifest",
            "--latency-kind",
            "glass-to-glass",
            "--transport",
            "usb",
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
            "--raw-video",
            str(raw_video),
            "--samples",
            str(samples),
            "--samples-format",
            "csv",
            "--annotation-method",
            "manual-frame-count",
            "--camera-manufacturer",
            "Fixture Camera Co",
            "--camera-model",
            "Synthetic 240",
            "--camera-mode",
            "1080p240",
            "--camera-frame-rate-fps",
            "240",
            "--camera-shutter-mode",
            "fixed",
            "--recorded-at",
            "2026-08-21T00:00:00Z",
            "--operator",
            "fixture",
            "--annotator",
            "fixture",
            "--host-model",
            "Fixture Mac",
            "--macos-version",
            "fixture",
            "--repository-revision",
            "fixture-revision",
            "--host-artifact",
            "fixture-host",
            "--client-artifact",
            "fixture-client",
            "--stimulus",
            "mac display flash visible to the camera",
            "--start-event-definition",
            "first camera frame where the Mac stimulus changes",
            "--end-event-definition",
            "first camera frame where the Android render shows the same change",
            "--lighting",
            "stable indoor light",
            "--mounting",
            "fixed tripod framing both screens",
            "--max-frame-annotation-uncertainty-ms",
            "4.2",
            "--notes",
            "Synthetic test package only.",
        ]

    def valid_synchronized_clock_cli_args(self, root: Path, samples: Path) -> list[str]:
        return [
            "--evidence-dir",
            str(root),
            "--run-id",
            "cli-synchronized-clock-manifest",
            "--measurement-method",
            "synchronized-clock",
            "--latency-kind",
            "input",
            "--transport",
            "usb",
            "--gate-profile",
            GATE_INPUT_P95_SUB50,
            "--samples",
            str(samples),
            "--samples-format",
            "csv",
            "--annotation-method",
            "direct-latency-ms",
            "--annotator",
            "fixture",
            "--device-manufacturer",
            "Fixture",
            "--device-model",
            "Fixture Device",
            "--device-codename",
            "fixture",
            "--device-os-version",
            "Android fixture",
            "--host-model",
            "Fixture Mac",
            "--macos-version",
            "fixture",
            "--repository-revision",
            "fixture-revision",
            "--host-artifact",
            "fixture-host",
            "--client-artifact",
            "fixture-client",
            "--stimulus",
            "physical touch on Android screen",
            "--start-event-definition",
            "Android touch event timestamp",
            "--end-event-definition",
            "macOS CGEvent injection timestamp",
            "--lighting",
            "n/a",
            "--mounting",
            "n/a",
            "--host-clock-source",
            "macOS system clock",
            "--device-clock-source",
            "Android elapsedRealtimeNanos",
            "--sync-procedure",
            "ADB round-trip calibration",
            "--before-skew-ms",
            "1.2",
            "--after-skew-ms",
            "1.5",
            "--max-drift-ms",
            "0.8",
            "--total-error-budget-ms",
            "3.5",
            "--input-timestamp-method",
            "Android MotionEvent.eventTime captured at touch dispatch",
            "--result-timestamp-method",
            "macOS CGEvent timestamp captured at injection",
            "--notes",
            "Synthetic synchronized-clock package only.",
        ]

    def test_cli_writes_schema_compatible_manifest_from_device_info(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            device_info = root / "device-info.json"
            device_info.write_text(
                json.dumps(
                    {
                        "device": {
                            "manufacturer": "nubia",
                            "model": "P0110",
                            "device": "pacific",
                            "android_release": "16",
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                *self.valid_cli_args(root, raw_video, samples),
                "--device-info",
                str(device_info),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(manifest["device"]["manufacturer"], "nubia")
        self.assertEqual(manifest["device"]["codename"], "pacific")
        self.assertEqual(report["verdict"], "pass")

    def test_cli_writes_schema_compatible_synchronized_clock_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = _write_synchronized_clock_samples(root)

            result = self.run_cli(*self.valid_synchronized_clock_cli_args(root, samples))

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(manifest["measurement_method"], "synchronized-clock")
        self.assertNotIn("camera", manifest)
        self.assertNotIn("recording", manifest)
        self.assertEqual(
            manifest["measurement_setup"]["clock_domain"],
            "synchronized-host-device-clocks",
        )
        self.assertEqual(report["verdict"], "pass")

    def test_cli_rejects_non_finite_camera_frame_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            arguments = self.valid_cli_args(root, raw_video, samples)
            index = arguments.index("--camera-frame-rate-fps") + 1
            arguments[index] = "nan"

            result = self.run_cli(*arguments)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("camera.frame_rate_fps must be finite", result.stderr)

    def test_cli_rejects_non_finite_annotation_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            arguments = self.valid_cli_args(root, raw_video, samples)
            index = arguments.index("--max-frame-annotation-uncertainty-ms") + 1
            arguments[index] = "inf"

            result = self.run_cli(*arguments)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "measurement_setup.max_frame_annotation_uncertainty_ms must be finite",
            result.stderr,
        )

    def test_cli_rejects_output_outside_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            raw_video, samples = _write_fixture_files(root)
            output = Path(directory) / "manifest.json"

            result = self.run_cli(
                *self.valid_cli_args(root, raw_video, samples),
                "--output",
                str(output),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output must be directly inside the evidence directory", result.stderr)

    def test_cli_rejects_nested_output_inside_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)

            result = self.run_cli(
                *self.valid_cli_args(root, raw_video, samples),
                "--output",
                "nested/manifest.json",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output must be directly inside the evidence directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
