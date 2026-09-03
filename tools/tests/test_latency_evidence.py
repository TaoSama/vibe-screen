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
from tools.tests.latency_test_helpers import minimal_mov


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.vibescreen_evidence.latency_evidence"
FIXTURE_DIR = REPOSITORY_ROOT / "tools" / "fixtures" / "latency"


class LatencyEvidenceReportTest(unittest.TestCase):
    def mark_real_capture_manifest(self, manifest: dict[str, object], run_id: str) -> None:
        manifest["run_id"] = run_id
        manifest["evidence_provenance"] = {
            "source": "real-device-capture",
            "collection_context": "bench capture in the current latency lab",
            "operator_assertion": "This package records a retained device capture run.",
        }
        replacements = {
            "Fixture": "Bench",
            "fixture": "bench",
            "Synthetic": "Retained",
            "synthetic": "retained",
            "checker": "validation",
        }

        def scrub(value: object, field_name: str | None = None) -> object:
            if isinstance(value, dict):
                return {key: scrub(child, str(key)) for key, child in value.items()}
            if isinstance(value, list):
                return [scrub(child, field_name) for child in value]
            if isinstance(value, str):
                for old, new in replacements.items():
                    value = value.replace(old, new)
            return value

        for section in ("camera", "recording", "samples", "device", "host", "build", "measurement_setup", "gate_artifacts"):
            if section in manifest:
                manifest[section] = scrub(manifest[section])

    def update_recording_metadata(self, root: Path, manifest: dict[str, object]) -> None:
        recording = manifest["recording"]
        assert isinstance(recording, dict)
        raw_video = root / str(recording["raw_video"])
        recording["sha256"] = hashlib.sha256(raw_video.read_bytes()).hexdigest()
        recording["file_size_bytes"] = raw_video.stat().st_size
        recording["container"] = raw_video.suffix.lower().lstrip(".")
        recording["frame_count"] = 600
        recording["duration_ms"] = 2500

    def copy_valid_package(self, root: Path) -> dict[str, object]:
        source = FIXTURE_DIR / "external-camera-valid"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        self.mark_real_capture_manifest(manifest, "bench-external-camera-valid")
        samples_bytes = (
            "start_frame,end_frame,camera_fps\n"
            "10,18,240\n110,119,240\n210,219,240\n"
            "310,319,240\n410,419,240\n"
        ).encode("utf-8")
        (root / "samples.csv").write_bytes(samples_bytes)
        recording = manifest["recording"]
        assert isinstance(recording, dict)
        recording["raw_video"] = "raw-camera-capture.mov"
        (root / "raw-camera-capture.mov").write_bytes(
            minimal_mov(b"retained-device-usb-video-fragment")
        )
        (root / "usb-connection.txt").write_text(
            "adb reverse tcp:54321 tcp:54321\nactive usb stream observed on real device\n",
            encoding="utf-8",
        )
        samples = manifest["samples"]
        assert isinstance(samples, dict)
        samples["sha256"] = hashlib.sha256(samples_bytes).hexdigest()
        self.update_recording_metadata(root, manifest)
        artifacts = manifest["gate_artifacts"]
        assert isinstance(artifacts, dict)
        usb_connection = artifacts["usb_connection"]
        assert isinstance(usb_connection, dict)
        usb_connection["sha256"] = hashlib.sha256((root / "usb-connection.txt").read_bytes()).hexdigest()
        return manifest

    def copy_synchronized_clock_package(self, root: Path) -> dict[str, object]:
        source = FIXTURE_DIR / "synchronized-clock-input-valid"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        self.mark_real_capture_manifest(manifest, "bench-synchronized-clock-input")
        samples_bytes = b"latency_ms\n13.1\n18.3\n15.1\n22.4\n19.7\n"
        (root / "samples.csv").write_bytes(samples_bytes)
        (root / "input-actuation.txt").write_text(
            "physical input actuation visible; visible mac-side result recorded\n",
            encoding="utf-8",
        )
        (root / "synchronization-record.txt").write_text(
            "clock synchronization proof: before skew, after skew, drift, input timestamp uncertainty, result timestamp uncertainty, total error budget\n",
            encoding="utf-8",
        )
        samples = manifest["samples"]
        assert isinstance(samples, dict)
        samples["sha256"] = hashlib.sha256(samples_bytes).hexdigest()
        artifacts = manifest["gate_artifacts"]
        assert isinstance(artifacts, dict)
        for key, filename in (
            ("input_actuation_record", "input-actuation.txt"),
            ("synchronization_record", "synchronization-record.txt"),
        ):
            artifact = artifacts[key]
            assert isinstance(artifact, dict)
            artifact["sha256"] = hashlib.sha256((root / filename).read_bytes()).hexdigest()
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

    def make_internet_manifest(self, root: Path) -> dict[str, object]:
        manifest = self.copy_valid_package(root)
        manifest["transport"] = "internet"
        manifest["gate_profile"] = GATE_INTERNET_GLASS_TO_GLASS_SUB150
        route_artifact = root / "internet-public-route-record.txt"
        route_artifact.write_text("public route proof with active stream\n", encoding="utf-8")
        manifest["gate_artifacts"] = {
            "internet_public_route_record": {
                "file": route_artifact.name,
                "sha256": hashlib.sha256(route_artifact.read_bytes()).hexdigest(),
                "description": "Public Internet route and active stream proof.",
            }
        }
        self.replace_samples(root, manifest, "latency_ms\n90\n100\n110\n120\n130\n")
        samples = manifest["samples"]
        assert isinstance(samples, dict)
        samples["annotation_method"] = "direct-latency-ms"
        return manifest

    def test_committed_external_camera_fixture_is_insufficient(self) -> None:
        report = build_latency_evidence_report(
            manifest_path=FIXTURE_DIR / "external-camera-valid" / "manifest.json",
            gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertEqual(report["gate"]["sample_count"], 5)
        self.assertTrue(
            any("synthetic latency fixtures cannot close" in reason for reason in report["gate"]["reasons"])
        )
        self.assertIn(
            "known repository latency fixture artifacts cannot close external latency gates",
            report["gate"]["reasons"],
        )

    def test_real_capture_manifest_under_fixture_path_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "tools" / "fixtures" / "latency" / "copied-real-package"
            root.mkdir(parents=True)
            manifest = self.copy_valid_package(root)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertIn(
            "latency manifests under tools/fixtures/latency cannot close external latency gates",
            report["gate"]["reasons"],
        )

    def test_known_fixture_digest_blocks_real_shaped_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            fixture_manifest = json.loads(
                (FIXTURE_DIR / "external-camera-valid" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["sha256"] = fixture_manifest["recording"]["sha256"]
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertIn(
            "known repository latency fixture artifacts cannot close external latency gates",
            report["gate"]["reasons"],
        )

    def test_real_device_shaped_external_camera_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
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
        self.assertEqual(
            report["internet_route"]["turn_deployment"]["resolved_ip"],
            "1.1.1.1",
        )
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

    def test_internet_latency_package_rejects_private_retained_turn_ip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            internet_route = self.valid_internet_route()
            turn = internet_route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["resolved_ip"] = "10.0.0.10"
            self.write_manifest(root, manifest | {"internet_route": internet_route})

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
            )

        self.assertEqual(report["gate"]["summary_verdict"], "pass")
        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "internet_route.turn_deployment.resolved_ip must record the retained resolved global IP for the TURN hostname",
            report["gate"]["reasons"],
        )

    def test_internet_latency_package_resolves_turn_hostname_to_retained_ip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            internet_route = self.valid_internet_route()
            turn = internet_route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["public_hostname"] = "turn.example.net"
            turn["resolved_ip"] = "1.1.1.1"
            self.write_manifest(root, manifest | {"internet_route": internet_route})

            with patch(
                "socket.getaddrinfo",
                side_effect=AssertionError("latency evidence verification must be offline"),
            ):
                report = build_latency_evidence_report(
                    manifest_path=root / "manifest.json",
                    gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
                )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(
            report["internet_route"]["turn_deployment"]["resolved_ip"],
            "1.1.1.1",
        )

    def test_internet_latency_package_accepts_archived_turn_hostname_without_live_dns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make_internet_manifest(root)
            internet_route = self.valid_internet_route()
            turn = internet_route["turn_deployment"]
            assert isinstance(turn, dict)
            turn["public_hostname"] = "turn.example.net"
            turn["resolved_ip"] = "1.1.1.1"
            self.write_manifest(root, manifest | {"internet_route": internet_route})

            with patch(
                "socket.getaddrinfo",
                side_effect=OSError("offline fixture"),
            ):
                report = build_latency_evidence_report(
                    manifest_path=root / "manifest.json",
                    gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
                )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["gate"]["reasons"], [])

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
            manifest = self.copy_valid_package(root)
            manifest["camera"]["frame_rate_fps"] = 240
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")

    def test_manifest_mismatch_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            manifest["transport"] = "lan"
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(any("manifest.transport must be usb" in reason for reason in report["gate"]["reasons"]))

    def test_modified_raw_camera_artifact_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            (root / str(recording["raw_video"])).write_bytes(b"modified recording")
            self.write_manifest(root, manifest)

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
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            raw_video.write_text("synthetic camera placeholder\n", encoding="utf-8")
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container with a supported layout",
            report["gate"]["reasons"],
        )

    def test_ebml_bytes_renamed_to_mov_are_insufficient_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(b"\x1aE\xdf\xa3" + b"matroska" + (b"\x00" * 64))
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container with a supported layout",
            report["gate"]["reasons"],
        )

    def test_ftyp_offset_without_media_samples_is_insufficient_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  mp42" + (b"\x00" * 32))
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container with a supported layout",
            report["gate"]["reasons"],
        )

    def test_fake_iso_bmff_box_tree_without_media_chunk_is_insufficient(self) -> None:
        def box(name: bytes, payload: bytes) -> bytes:
            return (len(payload) + 8).to_bytes(4, "big") + name + payload

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            stsd = box(b"stsd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + box(b"avc1", b"\x00" * 16))
            stsz = box(b"stsz", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + (1).to_bytes(4, "big"))
            stbl = box(b"stbl", stsd + stsz)
            minf = box(b"minf", stbl)
            hdlr = box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 8)
            mdia = box(b"mdia", hdlr + minf)
            trak = box(b"trak", box(b"tkhd", b"\x00" * 16) + mdia)
            moov = box(b"moov", box(b"mvhd", b"\x00" * 16) + trak)
            ftyp = box(b"ftyp", b"qt  \x00\x00\x00\00qt  ")
            raw_video.write_bytes(ftyp + box(b"mdat", b"X") + moov)
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container with a supported layout",
            report["gate"]["reasons"],
        )

    def test_readable_iso_bmff_video_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(minimal_mov(b"video-fragment"))
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")

    def test_iso_bmff_ftyp_must_be_at_required_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(b"notesftyp" + raw_video.read_bytes())
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.raw_video must be a readable camera video container with a supported layout",
            report["gate"]["reasons"],
        )

    def test_ebml_mkv_recording_is_insufficient_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            previous_raw_video = root / str(recording["raw_video"])
            previous_raw_video.unlink()
            recording["raw_video"] = "raw-camera-capture.mkv"
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(b"\x1aE\xdf\xa3" + b"matroska" + (b"\x00" * 32))
            recording["container"] = "mkv"
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any(
                reason in report["gate"]["reasons"]
                for reason in (
                    "manifest.recording.container must be one of: mov, mp4, m4v",
                    "recording.raw_video must use a supported external-camera container extension",
                    "recording.container must match recording.raw_video extension",
                )
            )
        )

    def test_ebml_webm_recording_is_insufficient_even_with_matching_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            previous_raw_video = root / str(recording["raw_video"])
            previous_raw_video.unlink()
            recording["raw_video"] = "raw-camera-capture.webm"
            raw_video = root / str(recording["raw_video"])
            raw_video.write_bytes(b"\x1aE\xdf\xa3" + b"webm" + (b"\x00" * 32))
            recording["container"] = "webm"
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertTrue(
            any(
                reason in report["gate"]["reasons"]
                for reason in (
                    "manifest.recording.container must be one of: mov, mp4, m4v",
                    "recording.raw_video must use a supported external-camera container extension",
                    "recording.container must match recording.raw_video extension",
                )
            )
        )

    def test_real_capture_raw_video_placeholder_filename_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            previous_raw_video = root / str(recording["raw_video"])
            raw_video = root / "synthetic-capture.mov"
            previous_raw_video.rename(raw_video)
            recording["raw_video"] = raw_video.name
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.recording.raw_video contains placeholder term 'synthetic'; real-device-capture latency evidence must use concrete run metadata",
            report["gate"]["reasons"],
        )

    def test_real_capture_samples_placeholder_filename_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            samples = manifest["samples"]
            assert isinstance(samples, dict)
            previous_samples = root / str(samples["file"])
            samples_file = root / "fixture-samples.csv"
            previous_samples.rename(samples_file)
            samples["file"] = samples_file.name
            samples["sha256"] = hashlib.sha256(samples_file.read_bytes()).hexdigest()
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.samples.file contains placeholder term 'fixture'; real-device-capture latency evidence must use concrete run metadata",
            report["gate"]["reasons"],
        )

    def test_real_capture_placeholder_term_in_file_names_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            previous_raw_video = root / str(recording["raw_video"])
            raw_video = root / "placeholder-capture.mov"
            previous_raw_video.rename(raw_video)
            recording["raw_video"] = raw_video.name
            self.update_recording_metadata(root, manifest)
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.recording.raw_video contains placeholder term 'placeholder'; real-device-capture latency evidence must use concrete run metadata",
            report["gate"]["reasons"],
        )

    def test_real_capture_gate_artifact_placeholder_filename_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            gate_artifacts = manifest["gate_artifacts"]
            assert isinstance(gate_artifacts, dict)
            usb_connection = gate_artifacts["usb_connection"]
            assert isinstance(usb_connection, dict)
            previous_artifact = root / str(usb_connection["file"])
            artifact = root / "placeholder-usb-connection.txt"
            previous_artifact.rename(artifact)
            usb_connection["file"] = artifact.name
            usb_connection["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.gate_artifacts.usb_connection.file contains placeholder term 'placeholder'; real-device-capture latency evidence must use concrete run metadata",
            report["gate"]["reasons"],
        )

    def test_real_capture_free_text_fixture_term_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            camera = manifest["camera"]
            setup = manifest["measurement_setup"]
            assert isinstance(camera, dict)
            assert isinstance(setup, dict)
            camera["mode"] = "fixture-mounted 1080p240 capture"
            setup["mounting"] = "device clamped in a machined fixture"
            setup["notes"] = "fixture label appears only in free-text lab notes"
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["gate"]["reasons"], [])

    def test_recording_file_size_bytes_must_match_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["file_size_bytes"] = int(recording["file_size_bytes"]) + 1
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.file_size_bytes must match recording.raw_video size",
            report["gate"]["reasons"],
        )

    def test_recording_duration_must_match_frame_count_and_frame_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["duration_ms"] = 3000
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.duration_ms must match recording.frame_count and camera.frame_rate_fps within one frame",
            report["gate"]["reasons"],
        )

    def test_recording_container_must_match_file_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["container"] = "mp4"
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "recording.container must match the raw video file extension",
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
            (root / "raw-camera-fixture.mov").write_bytes(
                (source / "raw-camera-fixture.mov").read_bytes()
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

    def test_recording_file_size_bytes_must_be_integer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["file_size_bytes"] = float(recording["file_size_bytes"]) + 0.5
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.recording.file_size_bytes must be an integer",
            report["gate"]["reasons"],
        )

    def test_recording_frame_count_must_be_integer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.copy_valid_package(root)
            recording = manifest["recording"]
            assert isinstance(recording, dict)
            recording["frame_count"] = 600.5
            self.write_manifest(root, manifest)

            report = build_latency_evidence_report(
                manifest_path=root / "manifest.json",
                gate_profile=GATE_USB_GLASS_TO_GLASS_SUB50,
            )

        self.assertEqual(report["verdict"], "insufficient")
        self.assertIn(
            "manifest.recording.frame_count must be an integer",
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
                    "description": "LAN active-stream preflight proof.",
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

        self.assertEqual(report["verdict"], "insufficient")
        self.assertFalse(report["gate"]["can_close_performance_gate"])
        self.assertEqual(report["gate"]["sample_count"], 5)
        self.assertEqual(report["measurement_method"], "synchronized-clock")
        self.assertTrue(
            any("synthetic latency fixtures cannot close" in reason for reason in report["gate"]["reasons"])
        )

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
        for field in (
            "before_skew_ms",
            "after_skew_ms",
            "max_drift_ms",
            "input_timestamp_uncertainty_ms",
            "result_timestamp_uncertainty_ms",
        ):
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
            "synchronization error-budget components must sum to less than or equal to "
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

    def test_cli_reports_committed_external_camera_fixture_insufficient(self) -> None:
        result = self.run_cli(
            str(FIXTURE_DIR / "external-camera-valid" / "manifest.json"),
            "--gate-profile",
            GATE_USB_GLASS_TO_GLASS_SUB50,
        )

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "insufficient")
        self.assertEqual(output["measurement_method"], "external-camera")
        self.assertFalse(output["gate"]["can_close_performance_gate"])

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
