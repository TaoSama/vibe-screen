import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.vibescreen_evidence.latency import (
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    GATE_INPUT_P95_SUB50,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)
from tools.vibescreen_evidence.latency_evidence import build_latency_evidence_report
from tools.vibescreen_evidence.latency_manifest import (
    LatencyManifestError,
    build_latency_manifest,
)
from tools.tests.latency_test_helpers import minimal_mov


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_manifest"


def _base_metadata() -> dict[str, object]:
    return {
        "run_id": "bench-latency-manifest",
        "latency_kind": "glass-to-glass",
        "transport": "usb",
        "gate_profile": GATE_USB_GLASS_TO_GLASS_SUB50,
        "camera": {
            "manufacturer": "Bench Camera Co",
            "model": "Retained 240",
            "mode": "1080p240",
            "frame_rate_fps": 240,
            "shutter_mode": "fixed",
        },
        "recording_operator": "bench operator",
        "recording_frame_count": 600,
        "recording_duration_ms": 2500,
        "samples_format": "csv",
        "annotation_method": "manual-frame-count",
        "annotator": "bench annotator",
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "os_version": "Android 16 / SDK 36",
        },
        "host": {"model": "Mac16,8", "macos_version": "26.4.1"},
        "build": {
            "repository_revision": "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
            "host_artifact": "Vibe Screen.app sha256 retained in commands.txt",
            "client_artifact": "app-debug.apk sha256 retained in commands.txt",
        },
        "measurement_setup": {
            "stimulus": "mac display flash visible to the camera",
            "start_event_definition": "first camera frame where the Mac stimulus changes",
            "end_event_definition": "first camera frame where the Android render shows the same change",
            "lighting": "stable indoor light",
            "mounting": "fixed tripod framing both screens",
            "clock_domain": "single-external-camera-timebase",
            "max_frame_annotation_uncertainty_ms": 4.2,
            "notes": "Bench validation package with retained artifacts.",
        },
        "recorded_at": "2026-08-21T00:00:00Z",
    }


def _write_fixture_files(root: Path) -> tuple[Path, Path]:
    raw_video = root / "raw-camera-capture.mov"
    samples = root / "samples.csv"
    raw_video.write_bytes(minimal_mov())
    samples.write_text(
        "start_frame,end_frame,camera_fps\n"
        "10,18,240\n110,119,240\n210,219,240\n310,319,240\n410,419,240\n",
        encoding="utf-8",
    )
    return raw_video, samples


def _write_synchronized_clock_samples(root: Path) -> Path:
    samples = root / "samples.csv"
    samples.write_text("latency_ms\n13.2\n18.9\n15.6\n22.8\n20.1\n", encoding="utf-8")
    return samples


def _write_artifact(root: Path, name: str = "usb-connection.txt") -> Path:
    artifact = root / name
    if name == "usb-connection.txt":
        contents = "usb connection setup and active stream proof\n"
    elif name == "internet-public-route-record.txt":
        contents = "public route proof with active stream record\n"
    elif name == "input-actuation.txt":
        contents = "physical input actuation visible mac result proof\n"
    else:
        contents = "lan network preflight and active stream proof\n"
    artifact.write_text(contents, encoding="utf-8")
    return artifact


def _write_synchronization_artifact(root: Path) -> Path:
    artifact = root / "synchronization-record.txt"
    artifact.write_text(
        "clock synchronization proof with skew drift uncertainty and total error budget\n",
        encoding="utf-8",
    )
    return artifact


def _valid_internet_route() -> dict[str, object]:
    return {
        "route": "forced-public-turn",
        "turn_deployment": {
            "provider": "example provider",
            "region": "us-west",
            "public_hostname": "1.1.1.1",
            "resolved_ip": "1.1.1.1",
            "tls": "turns",
            "credential_source": "authority-issued short-lived credential",
        },
        "remote_peer": {
            "operator": "remote tester",
            "network": "remote carrier",
            "public_ip_asn": "AS64500",
            "location": "remote lab",
        },
        "candidate_pair": {
            "local_candidate_type": "relay",
            "remote_candidate_type": "relay",
            "relay_protocol": "turn-tls",
        },
        "network_topology": {
            "host_network": "home ISP",
            "device_network": "remote carrier",
            "same_private_network": False,
        },
    }


class LatencyManifestBuilderTest(unittest.TestCase):
    def test_builds_manifest_that_formal_checker_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root)
            metadata = _base_metadata()

            manifest = build_latency_manifest(
                evidence_dir=root,
                raw_video=raw_video,
                samples=samples,
                gate_artifact=artifact,
                gate_artifact_description="USB active-stream proof.",
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
        self.assertEqual(manifest["gate_artifacts"]["usb_connection"]["file"], artifact.name)

    def test_rejects_profile_kind_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root)
            metadata = _base_metadata()
            metadata["latency_kind"] = "input"

            with self.assertRaisesRegex(LatencyManifestError, "requires latency kind"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    gate_artifact=artifact,
                    gate_artifact_description="USB active-stream proof.",
                    **metadata,
                )

    def test_rejects_referenced_files_outside_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            raw_video, _samples = _write_fixture_files(root)
            artifact = _write_artifact(root)
            outside_samples = Path(directory) / "outside-samples.csv"
            outside_samples.write_text("latency_ms\n10\n", encoding="utf-8")
            metadata = _base_metadata()

            with self.assertRaisesRegex(LatencyManifestError, "inside the evidence directory"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=outside_samples,
                    gate_artifact=artifact,
                    gate_artifact_description="USB active-stream proof.",
                    **metadata,
                )

    def test_rejects_inconsistent_recording_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root)
            metadata = _base_metadata()
            metadata["recording_duration_ms"] = 3000

            with self.assertRaisesRegex(
                LatencyManifestError,
                "recording.duration_ms must match recording.frame_count and camera.frame_rate_fps",
            ):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    gate_artifact=artifact,
                    gate_artifact_description="USB active-stream proof.",
                    **metadata,
                )

    def test_rejects_missing_direct_camera_frame_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root)
            metadata = _base_metadata()
            camera = dict(metadata["camera"])
            del camera["frame_rate_fps"]
            metadata["camera"] = camera

            with self.assertRaisesRegex(
                LatencyManifestError, "camera.frame_rate_fps is required"
            ):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    gate_artifact=artifact,
                    gate_artifact_description="USB active-stream proof.",
                    **metadata,
                )

    def test_requires_profile_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            metadata = _base_metadata()

            with self.assertRaisesRegex(LatencyManifestError, "gate artifact is required"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    **metadata,
                )

    def test_builds_internet_manifest_with_route_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            metadata = _base_metadata()
            metadata["transport"] = "internet"
            metadata["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150

            manifest = build_latency_manifest(
                evidence_dir=root,
                raw_video=raw_video,
                samples=samples,
                internet_route=_valid_internet_route(),
                gate_artifact=artifact,
                gate_artifact_description="Public Internet route and active stream proof.",
                **metadata,
            )
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(manifest["transport"], "internet")
        self.assertIn("internet_route", manifest)
        self.assertEqual(
            manifest["gate_artifacts"]["internet_public_route_record"]["file"],
            artifact.name,
        )
        self.assertEqual(report["verdict"], "pass")

    def test_internet_manifest_resolves_turn_hostname_when_retained_ip_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            metadata = _base_metadata()
            metadata["transport"] = "internet"
            metadata["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
            route = _valid_internet_route()
            turn = route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["public_hostname"] = "turn.example.net"
            del turn["resolved_ip"]

            with patch(
                "tools.vibescreen_evidence.latency_manifest._resolve_hostname_ips",
                return_value={"1.1.1.1"},
            ):
                manifest = build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    internet_route=route,
                    gate_artifact=artifact,
                    gate_artifact_description="Public Internet route and active stream proof.",
                    **metadata,
                )

        self.assertEqual(
            manifest["internet_route"]["turn_deployment"]["resolved_ip"],
            "1.1.1.1",
        )

    def test_internet_manifest_rejects_claimed_turn_ip_not_in_dns_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            metadata = _base_metadata()
            metadata["transport"] = "internet"
            metadata["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
            route = _valid_internet_route()
            turn = route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["public_hostname"] = "turn.example.net"
            turn["resolved_ip"] = "1.1.1.1"

            with patch(
                "tools.vibescreen_evidence.latency_manifest._resolve_hostname_ips",
                return_value={"8.8.8.8"},
            ):
                with self.assertRaisesRegex(LatencyManifestError, "must match a retained DNS resolution"):
                    build_latency_manifest(
                        evidence_dir=root,
                        raw_video=raw_video,
                        samples=samples,
                        internet_route=route,
                        gate_artifact=artifact,
                        gate_artifact_description="Public Internet route and active stream proof.",
                        **metadata,
                    )

    def test_internet_manifest_rejects_private_turn_hostname_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            metadata = _base_metadata()
            metadata["transport"] = "internet"
            metadata["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
            route = _valid_internet_route()
            turn = route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["public_hostname"] = "turn.example.net"
            turn["resolved_ip"] = "10.0.0.10"

            with patch(
                "tools.vibescreen_evidence.latency_manifest._resolve_hostname_ips",
                return_value={"10.0.0.10"},
            ):
                with self.assertRaisesRegex(LatencyManifestError, "must resolve only to global IP addresses"):
                    build_latency_manifest(
                        evidence_dir=root,
                        raw_video=raw_video,
                        samples=samples,
                        internet_route=route,
                        gate_artifact=artifact,
                        gate_artifact_description="Public Internet route and active stream proof.",
                        **metadata,
                    )

    def test_rejects_missing_internet_route_for_internet_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            metadata = _base_metadata()
            metadata["transport"] = "internet"
            metadata["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150

            with self.assertRaisesRegex(LatencyManifestError, "internet_route metadata is required"):
                build_latency_manifest(
                    evidence_dir=root,
                    raw_video=raw_video,
                    samples=samples,
                    gate_artifact=artifact,
                    gate_artifact_description="Public Internet route and active stream proof.",
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
        artifact = _write_artifact(root)
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
            "Bench Camera Co",
            "--camera-model",
            "Retained 240",
            "--camera-mode",
            "1080p240",
            "--camera-frame-rate-fps",
            "240",
            "--camera-shutter-mode",
            "fixed",
            "--recording-frame-count",
            "600",
            "--recording-duration-ms",
            "2500",
            "--recorded-at",
            "2026-08-21T00:00:00Z",
            "--operator",
            "bench operator",
            "--annotator",
            "bench annotator",
            "--host-model",
            "Mac16,8",
            "--macos-version",
            "26.4.1",
            "--repository-revision",
            "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
            "--host-artifact",
            "Vibe Screen.app sha256 retained in commands.txt",
            "--client-artifact",
            "app-debug.apk sha256 retained in commands.txt",
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
            "--gate-artifact",
            str(artifact),
            "--gate-artifact-description",
            "USB active-stream proof.",
            "--notes",
            "Bench validation package with retained artifacts.",
        ]

    def valid_synchronized_clock_cli_args(self, root: Path, samples: Path) -> list[str]:
        artifact = _write_artifact(root, "input-actuation.txt")
        synchronization_artifact = _write_synchronization_artifact(root)
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
            "bench annotator",
            "--device-manufacturer",
            "nubia",
            "--device-model",
            "P0110",
            "--device-codename",
            "pacific",
            "--device-os-version",
            "Android 16 / SDK 36",
            "--host-model",
            "Mac16,8",
            "--macos-version",
            "26.4.1",
            "--repository-revision",
            "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71",
            "--host-artifact",
            "Vibe Screen.app sha256 retained in commands.txt",
            "--client-artifact",
            "app-debug.apk sha256 retained in commands.txt",
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
            "--input-timestamp-uncertainty-ms",
            "0.0",
            "--result-timestamp-uncertainty-ms",
            "0.0",
            "--total-error-budget-ms",
            "3.5",
            "--input-timestamp-method",
            "Android MotionEvent.eventTime captured at touch dispatch",
            "--result-timestamp-method",
            "macOS CGEvent timestamp captured at injection",
            "--gate-artifact",
            str(artifact),
            "--gate-artifact-description",
            "Physical input actuation and visible Mac result proof.",
            "--synchronization-artifact",
            str(synchronization_artifact),
            "--synchronization-artifact-description",
            "Clock synchronization proof with skew drift uncertainty and budget.",
            "--notes",
            "Bench synchronized-clock package with retained artifacts.",
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
        self.assertIn("synchronization_record", manifest["gate_artifacts"])
        self.assertEqual(report["verdict"], "pass")

    def test_cli_rejects_synchronized_clock_without_sync_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = _write_synchronized_clock_samples(root)
            arguments = self.valid_synchronized_clock_cli_args(root, samples)
            start = arguments.index("--synchronization-artifact")
            del arguments[start : start + 4]

            result = self.run_cli(*arguments)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synchronization artifact is required", result.stderr)

    def test_cli_writes_schema_compatible_internet_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            artifact = _write_artifact(root, "internet-public-route-record.txt")
            arguments = self.valid_cli_args(root, raw_video, samples)
            arguments[arguments.index("--transport") + 1] = "internet"
            arguments[arguments.index("--gate-profile") + 1] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
            arguments[arguments.index("--gate-artifact") + 1] = str(artifact)
            arguments[arguments.index("--gate-artifact-description") + 1] = (
                "Public Internet route and active stream proof."
            )

            result = self.run_cli(
                *arguments,
                "--device-manufacturer",
                "nubia",
                "--device-model",
                "P0110",
                "--device-codename",
                "pacific",
                "--device-os-version",
                "Android 16 / SDK 36",
                "--internet-route",
                "forced-public-turn",
                "--turn-provider",
                "example provider",
                "--turn-region",
                "us-west",
                "--turn-public-hostname",
                "1.1.1.1",
                "--turn-resolved-ip",
                "1.1.1.1",
                "--turn-tls",
                "turns",
                "--turn-credential-source",
                "authority-issued short-lived credential",
                "--remote-peer-operator",
                "remote tester",
                "--remote-peer-network",
                "remote carrier",
                "--remote-peer-public-ip-asn",
                "AS64500",
                "--remote-peer-location",
                "remote lab",
                "--local-candidate-type",
                "relay",
                "--remote-candidate-type",
                "relay",
                "--relay-protocol",
                "turn-tls",
                "--host-network",
                "home ISP",
                "--device-network",
                "remote carrier",
                "--different-private-network",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(manifest["device"]["manufacturer"], "nubia")
        self.assertEqual(manifest["device"]["codename"], "pacific")
        self.assertEqual(manifest["internet_route"]["network_topology"]["same_private_network"], False)
        self.assertIn("internet_public_route_record", manifest["gate_artifacts"])
        self.assertEqual(report["verdict"], "pass")

    def test_cli_requires_explicit_internet_private_network_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_video, samples = _write_fixture_files(root)
            arguments = self.valid_cli_args(root, raw_video, samples)
            arguments[arguments.index("--transport") + 1] = "internet"
            arguments[arguments.index("--gate-profile") + 1] = GATE_INTERNET_GLASS_TO_GLASS_SUB150

            result = self.run_cli(
                *arguments,
                "--device-manufacturer",
                "nubia",
                "--device-model",
                "P0110",
                "--device-codename",
                "pacific",
                "--device-os-version",
                "Android 16 / SDK 36",
                "--internet-route",
                "forced-public-turn",
                "--turn-provider",
                "example provider",
                "--turn-region",
                "us-west",
                "--turn-public-hostname",
                "1.1.1.1",
                "--turn-resolved-ip",
                "1.1.1.1",
                "--turn-tls",
                "turns",
                "--turn-credential-source",
                "authority-issued short-lived credential",
                "--remote-peer-operator",
                "remote tester",
                "--remote-peer-network",
                "remote carrier",
                "--remote-peer-public-ip-asn",
                "AS64500",
                "--remote-peer-location",
                "remote lab",
                "--local-candidate-type",
                "relay",
                "--remote-candidate-type",
                "relay",
                "--relay-protocol",
                "turn-tls",
                "--host-network",
                "home ISP",
                "--device-network",
                "remote carrier",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("same_private_network must be explicitly recorded", result.stderr)

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
