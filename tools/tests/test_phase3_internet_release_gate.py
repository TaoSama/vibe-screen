from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence.phase3_internet_release_gate import REQUIRED_RAW_ARTIFACTS, derive_gate, main
from tools.tests.latency_test_helpers import write_minimal_mov


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_COMMIT_SHA = "b9070c0b558aaf9dbe6f3e39a98359ea53f7ad71"
TEST_TREE_SHA = "c1a2b3c4d5e6f7890abcdeffedcba09876543210"
TEST_HOST_SHA256 = "a" * 64
TEST_CLIENT_SHA256 = "b" * 64


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def touch(path: Path, value: str = "evidence\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def release_manifest(*, public: bool = True, turn: bool = True, codename: str = "pacific") -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase3_internet_release_manifest",
        "device": {
            "adb_serial": "[redacted]",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": codename,
            "android_release": "16",
            "sdk": "36",
        },
        "session": {
            "network_scope": "public_internet" if public else "local_loopback",
            "turn_scope": "deployed_remote_turn" if turn else "forced_local_coturn",
            "routes": ["direct", "relay"],
            "public_internet_path": public,
            "deployed_remote_turn": turn,
            "real_android_device": True,
            "real_macos_host": True,
            "identity_signed_host": True,
            "screen_recording_granted": True,
            "real_capture_to_mediacodec": True,
            "visible_input_effects": True,
            "network_handoff_recovered": True,
            "cross_service_revocation": True,
            "packet_capture_confidentiality": True,
            "no_synthetic_media": True,
            "usb_transport": False,
            "trusted_lan_only": False,
            "private_network_only": False,
            "same_private_network": not public,
            "loopback": not public,
            "synthetic_loopback": False,
            "synthetic_peer": False,
            "forced_local_coturn": not turn,
            "plaintext_fallback": False,
        },
    }


def latency_report() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "verdict": "pass",
        "latency_kind": "glass-to-glass",
        "transport": "internet",
        "measurement_method": "external-camera",
        "gate": {
            "profile": "internet-glass-to-glass-sub150",
            "can_close_performance_gate": True,
            "requires_external_hardware": True,
        },
    }


def latency_manifest(route: str) -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "run_id": f"bench-{route}",
        "latency_kind": "glass-to-glass",
        "transport": "internet",
        "measurement_method": "external-camera",
        "gate_profile": "internet-glass-to-glass-sub150",
        "evidence_provenance": {
            "source": "real-device-capture",
            "collection_context": "bench capture for the phase 3 release gate",
            "operator_assertion": "This package records retained direct device evidence.",
            "current_base": {
                "repository_revision": TEST_COMMIT_SHA,
                "source_tree": TEST_TREE_SHA,
                "dirty": False,
            },
        },
        "camera": {
            "manufacturer": "Bench Camera Co",
            "model": "Retained 240",
            "mode": "1080p240",
            "frame_rate_fps": 240,
            "shutter_mode": "fixed",
        },
        "recording": {
            "raw_video": "raw-camera.mov",
            "recorded_at": "2026-08-23T00:00:00Z",
            "operator": "bench operator",
            "sha256": "",
            "container": "mov",
            "file_size_bytes": 0,
            "frame_count": 600,
            "duration_ms": 2500,
        },
        "samples": {
            "file": "samples.csv",
            "format": "csv",
            "sha256": "",
            "annotation_method": "manual-frame-count",
            "annotator": "bench annotator",
        },
        "gate_artifacts": {
            "internet_public_route_record": {
                "file": "internet-public-route-record.txt",
                "sha256": "",
                "description": "Public Internet route and active stream proof.",
            }
        },
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "os_version": "Android 16 / SDK 36",
            "sdk": 36,
            "build_fingerprint": "nubia/pacific/pacific:16/test-keys",
        },
        "host": {"model": "Mac16,8", "macos_version": "26.4.1"},
        "build": {
            "repository_revision": TEST_COMMIT_SHA,
            "source_tree": TEST_TREE_SHA,
            "source_dirty": False,
            "host_artifact": "Vibe Screen.app sha256 retained in commands.txt",
            "host_artifact_sha256": TEST_HOST_SHA256,
            "host_artifact_provenance": "codesign and sha256 retained in commands.txt",
            "client_artifact": "app-debug.apk sha256 retained in commands.txt",
            "client_artifact_sha256": TEST_CLIENT_SHA256,
            "client_artifact_provenance": "APK sha256 retained in commands.txt",
        },
        "measurement_setup": {
            "stimulus": "mac display flash visible to the camera",
            "start_event_definition": "first camera frame where the Mac stimulus changes",
            "end_event_definition": "first camera frame where the Android render shows the same change",
            "lighting": "stable indoor light",
            "mounting": "fixed tripod framing both screens",
            "clock_domain": "single-external-camera-timebase",
            "max_frame_annotation_uncertainty_ms": 1.0,
            "notes": "Bench validation package with retained artifacts.",
        },
        "internet_route": {
            "route": f"{route}-public-internet" if route == "direct" else "forced-public-turn",
            "turn_deployment": {
                "provider": "example provider",
                "region": "remote-region-1",
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
                "local_candidate_type": "host" if route == "direct" else "relay",
                "remote_candidate_type": "srflx" if route == "direct" else "relay",
                "relay_protocol": "not-used" if route == "direct" else "turn-tls",
            },
            "network_topology": {
                "host_network": "home ISP",
                "device_network": "remote carrier",
                "same_private_network": False,
            },
        },
    }


def real_media_report(*, verdict: str = "pass") -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase3_real_media_continuity_preflight",
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "conditions": {
            "network_path": "public_internet",
            "host_signing": "identity_signed",
            "screen_recording": "granted",
        },
        "continuity_summary": {
            "public_internet_path": True,
            "media_source": "real_screencapturekit_or_cgdisplaystream",
            "capture_sources": ["ScreenCaptureKit"],
            "videotoolbox_output_epochs": [7],
            "mediacodec_first_input_epochs": [7],
            "mediacodec_first_output_epochs": [7],
            "shared_pipeline_epochs": [7],
            "mediacodec_first_input_frame": True,
            "mediacodec_first_output_frame": True,
            "continuous_output_frames": 180,
        },
        "host_observation": {
            "internet_product_session_started": True,
            "webrtc_transport_observed": True,
            "capture_started": True,
            "real_capture_first_frame": True,
            "videotoolbox_configured": True,
            "videotoolbox_output_observed": True,
            "synthetic_markers": [],
        },
        "android_observation": {
            "internet_stream_active": True,
            "decoder_configured": True,
            "first_input_frame": True,
            "first_output_frame": True,
            "synthetic_markers": [],
        },
    }


def device_info(*, codename: str = "pacific") -> dict:
    return {
        "device": {
            "adb_serial": "[redacted]",
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": codename,
            "android_version": "16",
            "sdk": 36,
        },
    }


def datachannel_record_layer() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase3_datachannel_record_layer_evidence",
        "status": "pass",
        "network_scope": "public_internet",
        "turn_scope": "deployed_remote_turn",
        "synthetic_media": False,
        "usb_transport": False,
        "trusted_lan_only": False,
        "private_network_only": False,
        "same_private_network": False,
        "loopback": False,
        "synthetic_loopback": False,
        "synthetic_peer": False,
        "forced_local_coturn": False,
        "plaintext_fallback": False,
        "webrtc_adapter": {"fake_engine": False, "synthetic_loopback": False},
        "record_layer": {
            "algorithm": "AES-256-GCM",
            "header_as_aad": True,
            "session_epoch_bound": True,
            "key_epoch_bound": True,
            "directional_key_separation": True,
            "channel_key_separation": True,
            "replay_protection": True,
            "wrong_channel_rejected": True,
            "packet_capture_no_plaintext": True,
            "nonce_reuse_detected": False,
            "plaintext_fallback": False,
        },
        "routes": {
            "direct": {
                "route": "direct",
                "public_internet_path": True,
                "same_private_network": False,
                "loopback": False,
                "synthetic_peer": False,
                "usb_adb_reverse": False,
                "trusted_lan_only": False,
            },
            "relay": {
                "route": "relay",
                "public_internet_path": True,
                "same_private_network": False,
                "loopback": False,
                "synthetic_peer": False,
                "usb_adb_reverse": False,
                "trusted_lan_only": False,
                "forced_local_coturn": False,
                "turn_deployment": {
                    "provider": "fixture provider",
                    "region": "remote-region-1",
                    "public_hostname": "turn.example.net",
                    "resolved_ip": "1.1.1.1",
                },
            },
        },
        "channels": {
            "control": {
                "label": "vibescreen.control.v1",
                "ordered": True,
                "reliable": True,
                "application_records_observed": True,
            },
            "media": {
                "label": "vibescreen.media.v1",
                "ordered": False,
                "max_retransmits": 0,
                "application_records_observed": True,
            },
            "audio": {
                "label": "vibescreen.audio.v1",
                "ordered": False,
                "max_retransmits": 0,
                "capability_gated": True,
                "application_records_observed": True,
                "product_flow_implemented": False,
                "phase3_scope": "transport_boundary_only",
            },
            "bulk": {
                "label": "vibescreen.bulk.v1",
                "ordered": True,
                "reliable": True,
                "capability_gated": True,
                "application_records_observed": True,
                "product_flow_implemented": False,
                "phase3_scope": "transport_boundary_only",
            },
        },
        "product_flows": {
            "audio_capture_playback": "not_claimed",
            "clipboard_sync": "not_claimed",
            "file_transfer": "not_claimed",
        },
        "raw_sources": ["direct-session.jsonl", "relay-session.jsonl", "packet-capture-notes.md"],
    }


def bulk_product_flow_gate() -> dict:
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase3_webrtc_bulk_product_flow_gate",
        "generated_at": "2026-08-29T00:00:00Z",
        "verdict": "pass",
        "gate_closed": True,
        "can_close_public_internet_bulk_product_flow_gate": True,
        "gate_can_close_phase3_release": False,
        "checks": {
            "public_relay_webrtc_route": {"passed": True, "evidence": ["bulk-route.json"], "blocking": True},
            "bulk_file_transfer_product_flow": {"passed": True, "evidence": ["bulk-transfer.json"], "blocking": True},
            "bulk_backpressure_and_cleanup": {"passed": True, "evidence": ["bulk-cleanup.json"], "blocking": True},
            "secure_record_layer": {"passed": True, "evidence": ["bulk-record-layer.json"], "blocking": True},
        },
        "closure_checklist": {
            "relay_production_prerequisites": {"passed": True, "evidence": ["public-nat-turn-preflight.json"]},
            "real_capture_to_mediacodec": {"passed": True, "evidence": ["real-media-continuity.json"]},
            "network_handoff": {"passed": True, "evidence": ["network-handoff.json"]},
            "cross_service_revocation": {"passed": True, "evidence": ["revocation-evidence.json"]},
            "external_camera_latency": {"passed": True, "evidence": ["latency/direct/latency-evidence.json", "latency/relay/latency-evidence.json"]},
            "two_hour_mixed_route_soak": {"passed": True, "evidence": ["soak-2h/exact-window-report.json"]},
            "packet_capture_confidentiality": {"passed": True, "evidence": ["packet-capture-confidentiality.json"]},
        },
        "safety": {
            "relay_preflight_does_not_close_product_e2e": True,
            "offline_tests_do_not_close_gate": True,
            "usb_lan_evidence_do_not_close_internet_gate": True,
            "synthetic_evidence_do_not_close_gate": True,
            "public_output_sanitized": True,
        },
        "blockers": [],
        "interpretation": "Fixture child gate pass cannot directly close Phase 3 release.",
    }


def status_pass(name: str) -> dict:
    requirements = {
        "network_handoff": (
            "phase3_network_handoff_evidence",
            {
                "public_internet_path": True,
                "independent_network_change": True,
                "ice_restart_observed": True,
                "new_session_epoch": True,
                "old_epoch_packets_rejected": True,
                "no_plaintext_fallback": True,
                "no_synthetic_media": True,
            },
        ),
        "cross_service_revocation": (
            "phase3_cross_service_revocation_evidence",
            {
                "active_peer_disconnected": True,
                "stale_credentials_rejected": True,
                "new_signaling_access_rejected": True,
                "new_turn_credentials_rejected": True,
                "coturn_allocation_terminated": True,
                "post_revocation_packet_count_zero": True,
                "no_plaintext_fallback": True,
                "no_synthetic_media": True,
            },
        ),
        "packet_capture_confidentiality": (
            "phase3_packet_capture_confidentiality_evidence",
            {
                "direct_route_reviewed": True,
                "relay_route_reviewed": True,
                "encrypted_application_records": True,
                "no_plaintext_screen_content": True,
                "no_credential_exposure": True,
                "no_pairing_secret_exposure": True,
                "no_synthetic_media": True,
            },
        ),
    }
    kind, observations = requirements[name]
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": kind,
        "status": "pass",
        "observations": observations,
        "raw_sources": ["host.log", "raw-logcat.txt"],
    }


def write_latency_package(root: Path, route: str) -> None:
    raw_video = root / f"latency/{route}/raw-camera.mov"
    samples = root / f"latency/{route}/samples.csv"
    route_record = root / f"latency/{route}/internet-public-route-record.txt"
    write_minimal_mov(raw_video)
    touch(
        samples,
        "start_frame,end_frame,camera_fps\n"
        "100,124,240\n200,225,240\n300,326,240\n"
        "400,427,240\n500,528,240\n",
    )
    touch(route_record, "public Internet route proof\n")
    manifest = latency_manifest(route)
    manifest["recording"]["sha256"] = hashlib.sha256(raw_video.read_bytes()).hexdigest()
    manifest["recording"]["file_size_bytes"] = raw_video.stat().st_size
    manifest["samples"]["sha256"] = hashlib.sha256(samples.read_bytes()).hexdigest()
    manifest["gate_artifacts"]["internet_public_route_record"]["sha256"] = hashlib.sha256(
        route_record.read_bytes()
    ).hexdigest()
    write_json(root / f"latency/{route}/manifest.json", manifest)
    write_json(root / f"latency/{route}/latency-evidence.json", latency_report())


def exact_window_soak_report(*, duration: float = 7200.0) -> dict:
    count = 240
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "soak_exact_window_report",
        "derivation_status": "complete",
        "source_summary": {"status": "complete"},
        "window": {
            "duration_seconds": duration,
            "sample_records_in_window": count,
            "telemetry_records_in_window": count,
        },
        "metrics": {
            "samples": {"gaps": {"maximum_interval_seconds": 30.0}},
            "stream": {
                "fps": {"count": count},
                "reported_dropped_frames": {"sum": 0.0},
                "frame_queue_drop_total": 0.0,
            },
            "telemetry": {
                "stream_stats_gaps": {"maximum_interval_seconds": 30.0},
                "heartbeat_gaps": {"maximum_interval_seconds": 30.0},
                "accepted_heartbeat_count": count,
            },
            "memory_kib": {
                "host_rss": {
                    "first": 100.0,
                    "final": 110.0,
                    "slope_kib_per_minute": {"second_half": 0.1},
                },
                "client_total_pss": {
                    "first": 200.0,
                    "final": 205.0,
                    "slope_kib_per_minute": {"second_half": 0.1},
                },
            },
            "thermal": {"status": {"max": 1.0}},
        },
        "phase3_internet_scope": {
            "network_scope": "public_internet",
            "route_coverage": {"direct": True, "relay": True},
            "public_internet_path": True,
            "network_handoff_observed": True,
            "cross_service_revocation_observed": True,
            "packet_capture_confidentiality_observed": True,
            "no_synthetic_media": True,
            "no_plaintext_fallback": True,
            "nonce_reuse_detected": False,
        },
    }


def populate_bundle(root: Path) -> None:
    write_json(root / "phase3-internet-manifest.json", release_manifest())
    write_json(root / "device-info.json", device_info())
    write_latency_package(root, "direct")
    write_latency_package(root, "relay")
    write_json(root / "real-media-continuity.json", real_media_report())
    write_json(root / "datachannel-record-layer.json", datachannel_record_layer())
    write_json(root / "webrtc-bulk-product-flow-gate.json", bulk_product_flow_gate())
    write_json(root / "network-handoff.json", status_pass("network_handoff"))
    write_json(root / "revocation-evidence.json", status_pass("cross_service_revocation"))
    write_json(root / "packet-capture-confidentiality.json", status_pass("packet_capture_confidentiality"))
    write_json(root / "soak-2h/exact-window-report.json", exact_window_soak_report())
    for route, local_type, remote_type in (
        ("direct", "host", "srflx"),
        ("relay", "relay", "relay"),
    ):
        write_jsonl(
            root / f"{route}-session.jsonl",
            [
                {
                    "route": route,
                    "public_internet_path": True,
                    "same_private_network": False,
                    "no_plaintext_fallback": True,
                    "no_synthetic_media": True,
                    "usb_transport": False,
                    "trusted_lan_only": False,
                    "private_network_only": False,
                    "loopback": False,
                    "synthetic_loopback": False,
                    "synthetic_peer": False,
                    "forced_local_coturn": False,
                    "plaintext_fallback": False,
                    "selected_candidate_pair": {
                        "local_candidate_type": local_type,
                        "remote_candidate_type": remote_type,
                        "turn_public_hostname": "1.1.1.1",
                        "turn_resolved_ip": "1.1.1.1",
                    },
                }
            ],
        )
    write_jsonl(root / "soak-2h/samples.jsonl", [{"sample": index} for index in range(240)])
    write_jsonl(root / "soak-2h/host-telemetry.jsonl", [{"sample": index} for index in range(240)])
    (root / "apk-sha256.txt").write_text("a" * 64 + "  app.apk\n", encoding="utf-8")
    (root / "build.txt").write_text(
        "TeamIdentifier=TEAM123\nAuthority=Developer ID Application\nVerification: valid on disk\n",
        encoding="utf-8",
    )
    (root / "host.log").write_text(
        "Screen Recording permission granted\nselected candidate pair public_internet relay turn.example.net\n",
        encoding="utf-8",
    )
    for relative in (
        "README.md",
        "host.txt",
        "network-handoff.jsonl",
        "replay-revocation.jsonl",
        "packet-capture-notes.md",
        "privacy-manifest.json",
        "soak-2h/summary.json",
        "raw-logcat.txt",
    ):
        touch(root / relative)


class Phase3InternetReleaseGateTest(unittest.TestCase):
    def test_missing_public_manifest_blocks_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertTrue(any("phase3-internet-manifest" in reason for reason in result["reasons"]))

    def test_local_loopback_manifest_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "phase3-internet-manifest.json", release_manifest(public=False, turn=False))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        manifest_gate = next(gate for gate in result["gates"] if gate["name"] == "public_internet_session_manifest")
        self.assertEqual(manifest_gate["status"], "blocked")
        self.assertTrue(any("public_internet" in reason for reason in manifest_gate["reasons"]))
        self.assertTrue(any("deployed_remote_turn" in reason for reason in manifest_gate["reasons"]))

    def test_manifest_routes_must_be_strings(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            manifest = release_manifest()
            manifest["session"]["routes"] = [{"route": "direct"}, ["relay"]]
            write_json(root / "phase3-internet-manifest.json", manifest)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        manifest_gate = next(gate for gate in result["gates"] if gate["name"] == "public_internet_session_manifest")
        self.assertEqual(manifest_gate["status"], "blocked")
        self.assertIn("session.routes must contain exactly direct and relay", manifest_gate["reasons"])

    def test_nubia_p0110_must_keep_pacific_codename(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "phase3-internet-manifest.json", release_manifest(codename="fuxi"))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        self.assertTrue(any("P0110" in reason and "pacific" in reason for reason in result["reasons"]))

    def test_device_info_must_match_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "device-info.json", device_info(codename="fuxi"))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        identity_gate = next(gate for gate in result["gates"] if gate["name"] == "device_identity_cross_check")
        self.assertEqual(identity_gate["status"], "blocked")
        self.assertTrue(any("codename" in reason for reason in identity_gate["reasons"]))

    def test_device_info_must_record_adb_serial_or_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            observed = device_info()
            del observed["device"]["adb_serial"]
            write_json(root / "device-info.json", observed)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        identity_gate = next(gate for gate in result["gates"] if gate["name"] == "device_identity_cross_check")
        self.assertEqual(identity_gate["status"], "blocked")
        self.assertIn("device-info identity must include adb_serial", identity_gate["reasons"])

    def test_blocked_real_media_keeps_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "real-media-continuity.json", real_media_report(verdict="blocked"))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        media_gate = next(gate for gate in result["gates"] if gate["name"] == "real_capture_to_mediacodec")
        self.assertEqual(media_gate["status"], "blocked")

    def test_real_media_synthetic_marker_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = real_media_report()
            report["host_observation"]["synthetic_markers"] = ["synthetic Protocol v1"]
            write_json(root / "real-media-continuity.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        media_gate = next(gate for gate in result["gates"] if gate["name"] == "real_capture_to_mediacodec")
        self.assertIn(
            "real-media host_observation.synthetic_markers must be empty",
            media_gate["reasons"],
        )

    def test_real_media_requires_source_metadata_and_shared_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = real_media_report()
            report["continuity_summary"]["capture_sources"] = []
            report["continuity_summary"]["shared_pipeline_epochs"] = []
            write_json(root / "real-media-continuity.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        media_gate = next(gate for gate in result["gates"] if gate["name"] == "real_capture_to_mediacodec")
        self.assertIn(
            "real-media continuity_summary.capture_sources must be present",
            media_gate["reasons"],
        )
        self.assertIn(
            "real-media continuity_summary.shared_pipeline_epochs must be present",
            media_gate["reasons"],
        )

    def test_real_media_rejects_invalid_source_and_unobserved_shared_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = real_media_report()
            report["continuity_summary"]["capture_sources"] = ["synthetic-harness"]
            report["continuity_summary"]["shared_pipeline_epochs"] = [8]
            write_json(root / "real-media-continuity.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        media_gate = next(gate for gate in result["gates"] if gate["name"] == "real_capture_to_mediacodec")
        self.assertIn(
            "real-media continuity_summary.capture_sources must name real capture sources",
            media_gate["reasons"],
        )
        self.assertIn(
            "real-media continuity_summary.shared_pipeline_epochs must be observed in VideoToolbox and MediaCodec epoch lists",
            media_gate["reasons"],
        )

    def test_missing_datachannel_record_layer_blocks_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            (root / "datachannel-record-layer.json").unlink()

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        raw_gate = next(gate for gate in result["gates"] if gate["name"] == "raw_evidence_bundle")
        datachannel_gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_datachannel_record_layer")
        self.assertIn("missing or empty required artifact: datachannel-record-layer.json", raw_gate["reasons"])
        self.assertEqual(datachannel_gate["status"], "blocked")

    def test_datachannel_record_layer_requires_aes256gcm_and_replay_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = datachannel_record_layer()
            report["record_layer"]["algorithm"] = "AES-128-GCM"
            report["record_layer"]["nonce_reuse_detected"] = True
            report["record_layer"]["replay_protection"] = False
            report["record_layer"]["wrong_channel_rejected"] = False
            write_json(root / "datachannel-record-layer.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_datachannel_record_layer")
        self.assertIn("datachannel record_layer.algorithm must be AES-256-GCM", gate["reasons"])
        self.assertIn("datachannel record_layer.nonce_reuse_detected must be false", gate["reasons"])
        self.assertIn("datachannel record_layer.replay_protection must be true", gate["reasons"])
        self.assertIn("datachannel record_layer.wrong_channel_rejected must be true", gate["reasons"])

    def test_datachannel_record_layer_rejects_synthetic_media(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = datachannel_record_layer()
            report["synthetic_media"] = True
            write_json(root / "datachannel-record-layer.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_datachannel_record_layer")
        self.assertIn("datachannel synthetic_media must be false", gate["reasons"])

    def test_datachannel_product_flow_claims_are_not_transport_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = datachannel_record_layer()
            report["product_flows"]["clipboard_sync"] = "pass"
            report["channels"]["audio"]["product_flow_implemented"] = True
            write_json(root / "datachannel-record-layer.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_datachannel_record_layer")
        self.assertIn(
            "datachannel product_flows.clipboard_sync must be not_claimed for transport-boundary evidence",
            gate["reasons"],
        )
        self.assertIn("datachannel channels.audio.product_flow_implemented must be False", gate["reasons"])

    def test_missing_bulk_product_flow_child_gate_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            (root / "webrtc-bulk-product-flow-gate.json").unlink()

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_bulk_product_flow")
        self.assertEqual(gate["status"], "blocked")
        self.assertTrue(any("missing" in reason for reason in gate["reasons"]))

    def test_blocked_bulk_product_flow_child_gate_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = bulk_product_flow_gate()
            report["verdict"] = "blocked"
            report["gate_closed"] = False
            report["can_close_public_internet_bulk_product_flow_gate"] = False
            report["closure_checklist"]["relay_production_prerequisites"]["passed"] = False
            write_json(root / "webrtc-bulk-product-flow-gate.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_bulk_product_flow")
        self.assertIn("bulk product-flow gate verdict must be pass", gate["reasons"])
        self.assertIn(
            "bulk product-flow closure_checklist.relay_production_prerequisites must pass",
            gate["reasons"],
        )

    def test_bulk_product_flow_child_gate_missing_schema_field_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = bulk_product_flow_gate()
            del report["generated_at"]
            write_json(root / "webrtc-bulk-product-flow-gate.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_bulk_product_flow")
        self.assertIn("bulk product-flow gate schema violation: $.generated_at is required", gate["reasons"])

    def test_datachannel_rejects_usb_lan_loopback_and_local_turn(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = datachannel_record_layer()
            report["trusted_lan_only"] = True
            report["routes"]["direct"]["same_private_network"] = True
            report["routes"]["direct"]["usb_adb_reverse"] = True
            report["routes"]["relay"]["forced_local_coturn"] = True
            report["routes"]["relay"]["turn_deployment"]["public_hostname"] = "localhost"
            report["routes"]["relay"]["turn_deployment"]["resolved_ip"] = "10.0.0.1"
            write_json(root / "datachannel-record-layer.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        gate = next(gate for gate in result["gates"] if gate["name"] == "webrtc_datachannel_record_layer")
        self.assertIn("datachannel trusted_lan_only must be false", gate["reasons"])
        self.assertIn("datachannel routes.direct.same_private_network must be false", gate["reasons"])
        self.assertIn("datachannel routes.direct.usb_adb_reverse must be false", gate["reasons"])
        self.assertIn("datachannel routes.relay.forced_local_coturn must be false", gate["reasons"])
        self.assertIn("datachannel routes.relay.turn_deployment.public_hostname must be public", gate["reasons"])
        self.assertIn("datachannel routes.relay.turn_deployment.resolved_ip must be public", gate["reasons"])

    def test_missing_raw_latency_samples_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            (root / "latency/direct/samples.csv").unlink()

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        raw_gate = next(gate for gate in result["gates"] if gate["name"] == "raw_evidence_bundle")
        self.assertEqual(raw_gate["status"], "blocked")
        self.assertIn(
            "missing or empty required artifact: latency/direct/samples.csv",
            raw_gate["reasons"],
        )

    def test_latency_report_pass_with_tampered_manifest_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            manifest = json.loads((root / "latency/direct/manifest.json").read_text(encoding="utf-8"))
            manifest["internet_route"]["turn_deployment"]["public_hostname"] = "127.0.0.1"
            manifest["internet_route"]["network_topology"]["same_private_network"] = True
            write_json(root / "latency/direct/manifest.json", manifest)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        latency_gate = next(gate for gate in result["gates"] if gate["name"] == "direct_external_camera_latency")
        self.assertIn(
            "direct formal latency package verdict is 'insufficient', not 'pass'",
            latency_gate["reasons"],
        )
        self.assertTrue(any("public Internet TURN hostname" in reason for reason in latency_gate["reasons"]))

    def test_non_internet_latency_report_cannot_close_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = latency_report()
            report["transport"] = "usb"
            report["gate"]["profile"] = "usb-glass-to-glass-sub50"
            write_json(root / "latency/direct/latency-evidence.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        latency_gate = next(gate for gate in result["gates"] if gate["name"] == "direct_external_camera_latency")
        self.assertIn("direct latency transport must be internet", latency_gate["reasons"])
        self.assertIn(
            "direct latency gate profile must be internet-glass-to-glass-sub150",
            latency_gate["reasons"],
        )

    def test_latency_route_must_match_direct_or_relay_slot(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "latency/direct/manifest.json", latency_manifest("relay"))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        latency_gate = next(gate for gate in result["gates"] if gate["name"] == "direct_external_camera_latency")
        self.assertIn(
            "direct latency manifest internet_route.route must be direct-public-internet",
            latency_gate["reasons"],
        )

    def test_session_jsonl_must_match_latency_route_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_jsonl(
                root / "relay-session.jsonl",
                [
                    {
                        "route": "relay",
                        "public_internet_path": True,
                        "same_private_network": False,
                        "no_plaintext_fallback": True,
                        "no_synthetic_media": True,
                        "usb_transport": False,
                        "trusted_lan_only": False,
                        "private_network_only": False,
                        "loopback": False,
                        "synthetic_loopback": False,
                        "synthetic_peer": False,
                        "forced_local_coturn": False,
                        "plaintext_fallback": False,
                        "selected_candidate_pair": {
                            "local_candidate_type": "host",
                            "remote_candidate_type": "srflx",
                            "turn_public_hostname": "turn.example.net",
                        },
                    }
                ],
            )

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        latency_gate = next(gate for gate in result["gates"] if gate["name"] == "relay_external_camera_latency")
        self.assertIn(
            "relay session JSONL must match latency manifest public route metadata",
            latency_gate["reasons"],
        )

    def test_session_jsonl_must_match_retained_turn_resolved_ip(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_jsonl(
                root / "relay-session.jsonl",
                [
                    {
                        "route": "relay",
                        "public_internet_path": True,
                        "same_private_network": False,
                        "no_plaintext_fallback": True,
                        "no_synthetic_media": True,
                        "usb_transport": False,
                        "trusted_lan_only": False,
                        "private_network_only": False,
                        "loopback": False,
                        "synthetic_loopback": False,
                        "synthetic_peer": False,
                        "forced_local_coturn": False,
                        "plaintext_fallback": False,
                        "selected_candidate_pair": {
                            "local_candidate_type": "relay",
                            "remote_candidate_type": "relay",
                            "turn_public_hostname": "turn.example.net",
                            "turn_resolved_ip": "8.8.8.8",
                        },
                    }
                ],
            )

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        latency_gate = next(gate for gate in result["gates"] if gate["name"] == "relay_external_camera_latency")
        self.assertIn(
            "relay session JSONL must match latency manifest public route metadata",
            latency_gate["reasons"],
        )

    def test_explicit_status_paths_resolve_relative_to_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            cwd = Path(raw_directory)
            root = cwd / "evidence" / "run"
            populate_bundle(root)
            output = cwd / "gate.json"
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                exit_code = main([
                    "--evidence-dir",
                    "evidence/run",
                    "--output",
                    str(output),
                    "--handoff-evidence",
                    "evidence/run/network-handoff.json",
                    "--revocation-evidence",
                    "evidence/run/revocation-evidence.json",
                    "--packet-capture-evidence",
                    "evidence/run/packet-capture-confidentiality.json",
                ])
            finally:
                os.chdir(old_cwd)
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        for name in ("network_handoff", "cross_service_revocation", "packet_capture_confidentiality"):
            gate = next(item for item in report["gates"] if item["name"] == name)
            self.assertEqual(gate["status"], "pass")

    def test_explicit_status_paths_prefer_cwd_over_evidence_dir_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            cwd = Path(raw_directory)
            root = cwd / "evidence" / "run"
            populate_bundle(root)
            write_json(root / "network-handoff.json", {
                "schema_version": "vibescreen.evidence/v1",
                "kind": "phase3_network_handoff_evidence",
                "verdict": "blocked",
                "observations": {},
                "raw_sources": ["fixture"],
            })
            write_json(cwd / "network-handoff.json", status_pass("network_handoff"))
            output = cwd / "gate.json"
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                exit_code = main([
                    "--evidence-dir",
                    "evidence/run",
                    "--output",
                    str(output),
                    "--handoff-evidence",
                    "network-handoff.json",
                ])
            finally:
                os.chdir(old_cwd)
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        gate = next(item for item in report["gates"] if item["name"] == "network_handoff")
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["evidence"], ["network-handoff.json"])

    def test_build_and_host_markers_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            (root / "build.txt").write_text("unsigned local build\n", encoding="utf-8")
            (root / "host.log").write_text("local loopback session\n", encoding="utf-8")

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        raw_gate = next(gate for gate in result["gates"] if gate["name"] == "raw_evidence_bundle")
        self.assertIn("build.txt must include identity-signed Host codesign evidence", raw_gate["reasons"])
        self.assertIn("host.log must include Screen Recording granted evidence", raw_gate["reasons"])
        self.assertIn("host.log must include selected public Internet ICE candidate evidence", raw_gate["reasons"])

    def test_empty_status_pass_shell_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "network-handoff.json", {"status": "pass"})

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        handoff_gate = next(gate for gate in result["gates"] if gate["name"] == "network_handoff")
        self.assertEqual(handoff_gate["status"], "insufficient")
        self.assertTrue(any("observations" in reason for reason in handoff_gate["reasons"]))

    def test_soak_without_phase3_public_scope_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            report = exact_window_soak_report()
            del report["phase3_internet_scope"]
            write_json(root / "soak-2h/exact-window-report.json", report)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        soak_gate = next(gate for gate in result["gates"] if gate["name"] == "two_hour_mixed_route_soak")
        self.assertIn(
            "phase3_internet_scope is required for Phase 3 release soak evidence",
            soak_gate["reasons"],
        )

    def test_soak_raw_rows_must_back_report_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_jsonl(root / "soak-2h/samples.jsonl", [{"sample": 1}])

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        soak_gate = next(gate for gate in result["gates"] if gate["name"] == "two_hour_mixed_route_soak")
        self.assertIn(
            "soak-2h/samples.jsonl must contain at least sample_records_in_window rows",
            soak_gate["reasons"],
        )

    def test_short_soak_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)
            write_json(root / "soak-2h/exact-window-report.json", exact_window_soak_report(duration=1800.0))

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        soak_gate = next(gate for gate in result["gates"] if gate["name"] == "two_hour_mixed_route_soak")
        self.assertEqual(soak_gate["status"], "insufficient")
        self.assertIn("soak criterion did not pass: duration_seconds", soak_gate["reasons"])

    def test_complete_public_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            populate_bundle(root)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["gate_can_close_phase3_release"])
        self.assertEqual(result["reasons"], [])

    def test_cli_writes_report_and_returns_nonzero_for_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)
            output = root / "gate.json"
            populate_bundle(root)
            write_json(root / "phase3-internet-manifest.json", release_manifest(public=False))
            with redirect_stdout(io.StringIO()):
                exit_code = main(["--evidence-dir", str(root), "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["verdict"], "blocked")

    def test_missing_inputs_do_not_leak_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            root = Path(raw_directory)

            result = derive_gate(root)

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(raw_directory, serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertIn("datachannel-record-layer.json", serialized)
        self.assertIn("latency/direct/latency-evidence.json", serialized)

    def test_android_evidence_template_names_match_required_raw_artifacts(self) -> None:
        template = (
            REPOSITORY_ROOT
            / "docs"
            / "changes"
            / "2026-08-04-phase-3-secure-internet"
            / "TEST.md"
        ).read_text(encoding="utf-8")

        for relative in REQUIRED_RAW_ARTIFACTS:
            self.assertIn(relative, template)


if __name__ == "__main__":
    unittest.main()
