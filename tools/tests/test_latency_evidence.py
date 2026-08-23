import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.vibescreen_evidence.latency import (
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    GATE_INPUT_P95_SUB50,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)
from tools.vibescreen_evidence.latency_evidence import build_latency_evidence_report


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_evidence"
FIXTURE_DIR = REPOSITORY_ROOT / "tools" / "fixtures" / "latency"


class LatencyEvidenceReportTest(unittest.TestCase):
    def copy_valid_package(self, root: Path) -> dict[str, object]:
        source = FIXTURE_DIR / "external-camera-valid"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        (root / "samples.csv").write_bytes((source / "samples.csv").read_bytes())
        (root / "raw-camera-placeholder.mov").write_bytes(
            (source / "raw-camera-placeholder.mov").read_bytes()
        )
        (root / "usb-connection.txt").write_bytes(
            (source / "usb-connection.txt").read_bytes()
        )
        return manifest

    def copy_synchronized_clock_package(self, root: Path) -> dict[str, object]:
        source = FIXTURE_DIR / "synchronized-clock-input-valid"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        (root / "samples.csv").write_bytes((source / "samples.csv").read_bytes())
        (root / "input-actuation.txt").write_bytes((source / "input-actuation.txt").read_bytes())
        (root / "synchronization-record.txt").write_bytes(
            (source / "synchronization-record.txt").read_bytes()
        )
        return manifest

    def write_manifest(self, root: Path, manifest: dict[str, object]) -> None:
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def replace_samples(
        self, root: Path, manifest: dict[str, object], contents: str
    ) -> None:
        encoded = contents.encode("utf-8")
        (root / "samples.csv").write_bytes(encoded)
        samples = manifest["samples"]
        assert isinstance(samples, dict)
        samples["sha256"] = hashlib.sha256(encoded).hexdigest()

    def valid_internet_route(self) -> dict[str, object]:
        return {
            "route": "forced-public-turn",
            "turn_deployment": {
                "provider": "example provider",
                "region": "us-west",
                "public_hostname": "turn.example.net",
                "tls": "turns",
                "credential_source": "authority-issued short-lived credential",
            },
            "remote_peer": {
                "operator": "fixture",
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

    def make_internet_manifest(self, root: Path) -> dict[str, object]:
        manifest = self.copy_valid_package(root)
        manifest["transport"] = "internet"
        manifest["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
        self.replace_samples(root, manifest, "latency_ms\n90\n100\n110\n120\n130\n")
        samples = manifest["samples"]
        assert isinstance(samples, dict)
        samples["annotation_method"] = "direct-latency-ms"
        return manifest

    def test_valid_external_camera_package_passes(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "external-camera-valid" / "manifest.json",
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["gate"]["can_close_performance_gate"])
        self.assertEqual(report["gate"]["sample_count"], 5)
        self.assertEqual(report["gate"]["reasons"], [])

    def test_internet_latency_package_requires_public_route_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertTrue(
            any("internet_route is required" in reason for reason in report["gate"]["reasons"])
        )

    def test_internet_latency_package_accepts_public_forced_turn_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            manifest["internet_route"] = self.valid_internet_route()
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["transport"], "internet")
        self.assertEqual(report["gate"]["reasons"], [])

    def test_internet_latency_package_rejects_loopback_or_lan_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            internet_route = self.valid_internet_route()
            turn = internet_route["turn_deployment"]
            topology = internet_route["network_topology"]
            assert isinstance(turn, dict)
            assert isinstance(topology, dict)
            turn["public_hostname"] = "127.0.0.1"
            topology["same_private_network"] = True
            self.write_manifest(root, manifest | {"internet_route": internet_route})

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient")
        reasons = report["gate"]["reasons"]
        self.assertTrue(any("public Internet TURN hostname" in reason for reason in reasons))
        self.assertTrue(any("same_private_network must be false" in reason for reason in reasons))

    def test_internet_latency_package_rejects_missing_remote_peer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            internet_route = self.valid_internet_route()
            del internet_route["remote_peer"]
            self.write_manifest(root, manifest | {"internet_route": internet_route})

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(report["verdict"], "insufficient")
        reasons = report["gate"]["reasons"]
        self.assertTrue(any("manifest.internet_route.remote_peer is required" in reason for reason in reasons))
        self.assertTrue(any("internet_route.remote_peer.operator is required" in reason for reason in reasons))

    def test_non_internet_latency_package_rejects_internet_route_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest["internet_route"] = self.valid_internet_route()
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "internet_route is only allowed for the internet-glass-to-glass-sub150 profile",
            report["gate"]["reasons"],
        )

    def test_missing_raw_camera_artifact_is_insufficient(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "external-camera-missing-video" / "manifest.json",
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertTrue(
            any("recording.raw_video does not exist" in reason for reason in report["gate"]["reasons"])
        )

    def test_numeric_camera_frame_rate_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            manifest["camera"]["frame_rate_fps"] = 240
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "samples.csv").write_text((source / "samples.csv").read_text(encoding="utf-8"), encoding="utf-8")
            (root / "raw-camera-placeholder.mov").write_bytes(
                (source / "raw-camera-placeholder.mov").read_bytes()
            )
            (root / "usb-connection.txt").write_bytes(
                (source / "usb-connection.txt").read_bytes()
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")

    def test_manifest_mismatch_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            manifest["transport"] = "lan"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "samples.csv").write_text((source / "samples.csv").read_text(encoding="utf-8"), encoding="utf-8")
            (root / "raw-camera-placeholder.mov").write_text("placeholder", encoding="utf-8")
            (root / "usb-connection.txt").write_bytes(
                (source / "usb-connection.txt").read_bytes()
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("requires --transport usb" in reason for reason in report["gate"]["reasons"]))

    def test_modified_raw_camera_artifact_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            (root / "manifest.json").write_bytes((source / "manifest.json").read_bytes())
            (root / "samples.csv").write_bytes((source / "samples.csv").read_bytes())
            (root / "raw-camera-placeholder.mov").write_bytes(b"modified recording")
            (root / "usb-connection.txt").write_bytes(
                (source / "usb-connection.txt").read_bytes()
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertIn(
            "recording.sha256 does not match its referenced file",
            report["gate"]["reasons"],
        )

    def test_text_mov_placeholder_is_insufficient_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            raw_video = root / "raw-camera-placeholder.mov"
            raw_video.write_text("synthetic camera placeholder\n", encoding="utf-8")
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["sha256"] = hashlib.sha256(raw_video.read_bytes()).hexdigest()
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container, not a text placeholder",
            report["gate"]["reasons"],
        )

    def test_malformed_recording_digest_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURE_DIR / "external-camera-valid"
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            manifest["recording"]["sha256"] = "not-a-digest"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (root / "samples.csv").write_bytes((source / "samples.csv").read_bytes())
            (root / "raw-camera-placeholder.mov").write_bytes(
                (source / "raw-camera-placeholder.mov").read_bytes()
            )
            (root / "usb-connection.txt").write_bytes(
                (source / "usb-connection.txt").read_bytes()
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.sha256 must be a 64-character hexadecimal SHA-256 digest",
            report["gate"]["reasons"],
        )

    def test_modified_samples_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            self.write_manifest(root, manifest)
            (root / "samples.csv").write_text(
                "latency_ms\n1\n1\n1\n1\n1\n", encoding="utf-8"
            )

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "samples.sha256 does not match its referenced file",
            report["gate"]["reasons"],
        )

    def test_sample_frame_rate_must_match_camera_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            self.replace_samples(
                root,
                manifest,
                "start_frame,end_frame,camera_fps\n"
                "100,108,1000\n200,209,1000\n300,310,1000\n"
                "400,410,1000\n500,510,1000\n",
            )
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any(
                "camera_fps must match camera.frame_rate_fps" in reason
                for reason in report["gate"]["reasons"]
            )
        )

    def test_annotation_method_must_match_sample_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            self.replace_samples(root, manifest, "latency_ms\n1\n1\n1\n1\n1\n")
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "sample 1: manual-frame-count requires only start_frame, end_frame, and camera_fps",
            report["gate"]["reasons"],
        )

    def test_annotation_uncertainty_is_applied_to_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            setup = manifest["measurement_setup"]
            assert isinstance(setup, dict)
            setup["max_frame_annotation_uncertainty_ms"] = 7
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertGreater(report["gate"]["observed_with_uncertainty_ms"], 50)
        self.assertIn(
            "p95 plus start/end annotation uncertainty exceeds the gate threshold",
            report["gate"]["reasons"],
        )

    def test_annotation_uncertainty_is_counted_for_both_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            setup = manifest["measurement_setup"]
            assert isinstance(setup, dict)
            setup["max_frame_annotation_uncertainty_ms"] = 7
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertAlmostEqual(report["gate"]["observed_ms"], 37.5)
        self.assertAlmostEqual(report["gate"]["observed_with_uncertainty_ms"], 51.5)

    def test_schema_rejects_boolean_annotation_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            setup = manifest["measurement_setup"]
            assert isinstance(setup, dict)
            setup["max_frame_annotation_uncertainty_ms"] = False
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIsNone(report["gate"]["observed_ms"])
        self.assertIn(
            "manifest.measurement_setup.max_frame_annotation_uncertainty_ms must be a JSON number",
            report["gate"]["reasons"],
        )

    def test_schema_requires_external_camera_annotation_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            setup = manifest["measurement_setup"]
            assert isinstance(setup, dict)
            del setup["max_frame_annotation_uncertainty_ms"]
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.measurement_setup.max_frame_annotation_uncertainty_ms is required",
            report["gate"]["reasons"],
        )

    def test_schema_rejects_unknown_manifest_properties(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest["unexpected"] = "not allowed"
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIsNone(report["gate"]["observed_ms"])
        self.assertIn(
            "manifest.unexpected is not allowed by schema",
            report["gate"]["reasons"],
        )

    def test_referenced_files_must_stay_in_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            manifest = self.copy_valid_package(package)
            outside_samples = root / "outside-samples.csv"
            outside_samples.write_bytes((package / "samples.csv").read_bytes())
            samples = manifest["samples"]
            assert isinstance(samples, dict)
            samples["file"] = "../outside-samples.csv"
            self.write_manifest(package, manifest)

            report = build_latency_evidence_report(
                manifest_path=package / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "samples.file must stay within the evidence directory",
            report["gate"]["reasons"],
        )

    def test_profile_artifact_is_required_for_usb_glass_to_glass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest.pop("gate_artifacts", None)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertIn("manifest.gate_artifacts is required", report["gate"]["reasons"])
        self.assertIn(
            "gate_artifacts must be an object containing profile-specific retained artifacts",
            report["gate"]["reasons"],
        )
        self.assertTrue(
            any("gate_artifacts.usb_connection is required" in reason for reason in report["gate"]["reasons"])
        )

    def test_profile_artifact_must_stay_in_evidence_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "package"
            root.mkdir()
            manifest = self.copy_valid_package(root)
            gate_artifacts = manifest["gate_artifacts"]
            assert isinstance(gate_artifacts, dict)
            usb_connection = gate_artifacts["usb_connection"]
            assert isinstance(usb_connection, dict)
            usb_connection["file"] = "../outside-usb-connection.txt"
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "gate_artifacts.usb_connection.file must stay within the evidence directory",
            report["gate"]["reasons"],
        )

    def test_profile_artifact_sha256_must_match_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            gate_artifacts = manifest["gate_artifacts"]
            assert isinstance(gate_artifacts, dict)
            usb_connection = gate_artifacts["usb_connection"]
            assert isinstance(usb_connection, dict)
            usb_connection["sha256"] = "0" * 64
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "gate_artifacts.usb_connection.sha256 does not match its referenced file",
            report["gate"]["reasons"],
        )

    def test_profile_specific_artifact_key_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest["gate_artifacts"] = {
                "lan_network_preflight": {
                    "file": "usb-connection.txt",
                    "sha256": manifest["gate_artifacts"]["usb_connection"]["sha256"],
                    "description": "Wrong profile artifact key.",
                }
            }
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any(
                "gate_artifacts.usb_connection is required" in reason
                for reason in report["gate"]["reasons"]
            )
        )

    def test_lan_profile_requires_lan_preflight_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest["transport"] = "lan"
            manifest["gate_profile"] = "lan-glass-to-glass-sub80"
            manifest["gate_artifacts"] = {
                "lan_network_preflight": {
                    "file": "missing-lan-preflight.txt",
                    "sha256": "0" * 64,
                    "description": "Synthetic LAN preflight proof.",
                }
            }
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile="lan-glass-to-glass-sub80",
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any("gate_artifacts.lan_network_preflight.file does not exist" in reason for reason in report["gate"]["reasons"])
        )

    def test_input_profile_requires_physical_actuation_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest.pop("gate_artifacts", None)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any("gate_artifacts.input_actuation_record is required" in reason for reason in report["gate"]["reasons"])
        )

    def test_synchronized_clock_requires_sync_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            gate_artifacts = manifest["gate_artifacts"]
            assert isinstance(gate_artifacts, dict)
            gate_artifacts.pop("synchronization_record", None)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any("gate_artifacts.synchronization_record is required" in reason for reason in report["gate"]["reasons"])
        )

    def test_synchronized_clock_sync_artifact_sha256_must_match_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            gate_artifacts = manifest["gate_artifacts"]
            assert isinstance(gate_artifacts, dict)
            sync_record = gate_artifacts["synchronization_record"]
            assert isinstance(sync_record, dict)
            sync_record["sha256"] = "0" * 64
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "gate_artifacts.synchronization_record.sha256 does not match its referenced file",
            report["gate"]["reasons"],
        )

    def test_synchronized_clock_input_package_passes(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "synchronized-clock-input-valid" / "manifest.json",
            gate_profile=GATE_INPUT_P95_SUB50,
        )

        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(report["gate"]["can_close_performance_gate"])
        self.assertEqual(report["gate"]["sample_count"], 5)
        self.assertEqual(report["measurement_method"], "synchronized-clock")
        self.assertEqual(report["gate"]["reasons"], [])

    def test_synchronized_clock_requires_input_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["latency_kind"] = "glass-to-glass"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "synchronized-clock measurement_method requires latency_kind input",
            report["gate"]["reasons"],
        )

    def test_synchronized_clock_error_budget_must_be_below_5ms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["synchronization"]["total_error_budget_ms"] = 5.0
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any("total_error_budget_ms must be less than 5 ms" in reason
                for reason in report["gate"]["reasons"])
        )
        self.assertIn(
            "manifest.synchronization.total_error_budget_ms must be less than 5",
            report["gate"]["reasons"],
        )

    def test_synchronized_clock_allows_budget_just_below_5ms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["synchronization"]["total_error_budget_ms"] = 4.999
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["gate"]["reasons"], [])

    def test_synchronized_clock_rejects_manual_frame_count_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["samples"]["annotation_method"] = "manual-frame-count"
            self.replace_samples(
                root,
                manifest,
                "start_frame,end_frame,camera_fps\n"
                "100,105,240\n200,205,240\n300,305,240\n"
                "400,405,240\n500,505,240\n",
            )
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "synchronized-clock measurement_method requires samples.annotation_method direct-latency-ms",
            report["gate"]["reasons"],
        )
        self.assertIn(
            "manifest.samples.annotation_method must be direct-latency-ms",
            report["gate"]["reasons"],
        )

    def test_synchronized_clock_components_must_fit_total_budget(self) -> None:
        for field in ("before_skew_ms", "after_skew_ms", "max_drift_ms"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    manifest = self.copy_synchronized_clock_package(root)
                    manifest["synchronization"]["total_error_budget_ms"] = 3.0
                    manifest["synchronization"][field] = 3.1
                    self.write_manifest(root, manifest)

                    report = build_latency_evidence_report(
                        manifest_path=root / "manifest.json",
                        gate_profile=GATE_INPUT_P95_SUB50,
                    )

                self.assertEqual(report["verdict"], "insufficient")
                self.assertIn(
                    f"synchronization.{field} must be less than or equal to "
                    "synchronization.total_error_budget_ms",
                    report["gate"]["reasons"],
                )

    def test_synchronized_clock_component_sum_must_fit_total_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["synchronization"]["before_skew_ms"] = 1.4
            manifest["synchronization"]["after_skew_ms"] = 1.4
            manifest["synchronization"]["max_drift_ms"] = 1.3
            manifest["synchronization"]["total_error_budget_ms"] = 4.0
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "synchronization.before_skew_ms + synchronization.after_skew_ms + "
            "synchronization.max_drift_ms must be less than or equal to "
            "synchronization.total_error_budget_ms",
            report["gate"]["reasons"],
        )

    def test_synchronized_clock_budget_applied_to_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_synchronized_clock_package(root)
            manifest["synchronization"]["total_error_budget_ms"] = 4.5
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.replace_samples(
                root,
                manifest,
                "latency_ms\n45\n46\n47\n48\n49\n",
            )
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INPUT_P95_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any("synchronization error budget exceeds the gate threshold" in reason
                for reason in report["gate"]["reasons"])
        )


class LatencyEvidenceCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_passes_valid_external_camera_package(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "external-camera-valid" / "manifest.json"),
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "pass")
        self.assertEqual(output["measurement_method"], "external-camera")

    def test_cli_outputs_insufficient_json_for_missing_manifest(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "external-camera-valid" / "missing-manifest.json"),
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertIn("cannot read latency evidence manifest", output["gate"]["reasons"][0])
        self.assertEqual(result.stderr, "")

    def test_cli_outputs_insufficient_json_for_invalid_utf8_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_bytes(b"\xff")

            result = self.run_cli(
                str(manifest_path),
                "--gate-profile",
                GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertIn("invalid UTF-8 in latency evidence manifest", output["gate"]["reasons"][0])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
