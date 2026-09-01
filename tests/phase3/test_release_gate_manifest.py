from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.phase3.release_gate_manifest import (
    GATE_RULES,
    SCHEMA,
    gate_matrix,
    main,
    revocation_summary_to_manifest_gate,
    validate_manifest,
)


SHA256 = "a" * 64
COMMIT = "b" * 40
PHASE3_EVIDENCE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "docs/changes/2026-08-04-phase-3-secure-internet/evidence"
)
EXPECTED_GATE_NAMES = {
    "public_internet_direct_path",
    "remote_turn_relay_path",
    "real_screencapturekit_to_android_media",
    "network_handoff_recovery",
    "cross_service_revocation",
    "packet_capture_confidentiality",
    "external_camera_latency",
    "webrtc_datachannel_record_layer",
    "two_hour_mixed_route_soak",
}


def write_evidence_file(root: Path, relative_path: str, content: str = "{}\n") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_sha256sums(root: Path, relative_paths: list[str]) -> None:
    lines = []
    for relative_path in relative_paths:
        digest = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative_path}\n")
    (root / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


def write_default_evidence_root(root: Path) -> None:
    write_evidence_file(root, "logs/direct-session.jsonl")
    write_sha256sums(root, ["logs/direct-session.jsonl"])


def passing_manifest() -> dict[str, object]:
    evidence_file = "logs/direct-session.jsonl"
    gate_defaults = {
        "status": "pass",
        "synthetic_media": False,
        "local_loopback_only": False,
        "usb_transport": False,
        "trusted_lan_only": False,
        "private_network_only": False,
        "same_private_network": False,
        "loopback": False,
        "synthetic_loopback": False,
        "synthetic_peer": False,
        "evidence_files": [evidence_file],
    }
    return {
        "schema": SCHEMA,
        "result": "pass",
        "source": {"commit": COMMIT, "tree_status": "clean"},
        "device": {
            "manufacturer": "Nubia",
            "model": "P0110",
            "codename": "pacific",
            "os_version": "Android 16",
            "evidence_role": "general_android_substitute",
        },
        "artifacts": {"mac_host_sha256": SHA256, "android_apk_sha256": SHA256},
        "claims": ["General Android substitute Phase 3 Internet release gate"],
        "gates": {
            "public_internet_direct_path": gate_defaults
            | {
                "route": "direct",
                "public_internet_path": True,
                "selected_candidate_pair": "direct(local=host,remote=srflx,protocol=udp)",
                "remote_public_route_observed": True,
                "local_loopback_address": False,
                "usb_adb_reverse": False,
                "host_network": "home ISP",
                "device_network": "remote carrier",
                "remote_public_asn": "AS64500",
            },
            "remote_turn_relay_path": gate_defaults
            | {
                "route": "relay",
                "public_internet_path": True,
                "remote_turn_deployment": True,
                "local_coturn_only": False,
                "selected_candidate_pair": "relay(local=relay,remote=relay,protocol=udp)",
                "forced_local_coturn": False,
                "turn_public_hostname": "turn.example.net",
                "turn_resolved_public_ip": "1.1.1.1",
                "turn_provider": "fixture provider",
                "turn_region": "remote-region-1",
            },
            "real_screencapturekit_to_android_media": gate_defaults
            | {
                "capture_source": "ScreenCaptureKit",
                "android_decoder": "MediaCodec",
                "screen_capture_frames": 10,
                "encoded_frames": 10,
                "android_decoded_frames": 10,
                "first_android_output_observed": True,
            },
            "network_handoff_recovery": gate_defaults
            | {
                "handoff_count": 2,
                "controlled_impairment": True,
                "impairment_tool": "linux-netns-tc",
                "impairment_profile": {
                    "latency_ms": 95,
                    "jitter_ms": 20,
                    "loss_percent": 2.0,
                    "bandwidth_kbps": 6000,
                },
                "route_before": "direct",
                "route_after": "relay",
                "fresh_session_requested": True,
                "ice_restart_attempted": True,
                "old_session_closed": True,
                "initial_session_epoch": 7,
                "recovered_session_epoch": 8,
                "stream_pause_detected": True,
                "stream_resume_detected": True,
                "recovery_started_at_monotonic_ms": 1000,
                "recovery_completed_at_monotonic_ms": 5200,
                "session_epoch_advanced": True,
                "stale_epoch_rejected": True,
                "recovered_streaming": True,
                "recovery_seconds": 4.2,
                "approved_limit_seconds": 5,
            },
            "cross_service_revocation": gate_defaults
            | {
                "evidence_kind": "live_production",
                "chain_id": "chain-1",
                "tombstone_id": "tombstone-1",
                "allocation_id": "allocation-1",
                "device_revoked": True,
                "session_revoked": True,
                "authority_tombstone_observed": True,
                "signaling_rejection_observed": True,
                "future_turn_credential_rejected": True,
                "same_allocation_turn_credential_rejected": True,
                "stale_credential_reuse_rejected": True,
                "active_session_disconnected": True,
                "direct_reconnect_rejected": True,
                "relay_reconnect_rejected": True,
                "turn_allocation_disconnected": True,
                "post_revocation_traffic_rejected": True,
                "post_revocation_packet_count_zero": True,
                "revocation_chain_consistent": True,
            },
            "packet_capture_confidentiality": gate_defaults
            | {
                "capture_reviewed": True,
                "no_plaintext_media": True,
                "no_plaintext_input": True,
                "no_credentials": True,
            },
            "external_camera_latency": gate_defaults
            | {
                "method": "external_camera",
                "sample_count": 60,
                "direct_p95_ms": 120,
                "relay_p95_ms": 145,
            },
            "webrtc_datachannel_record_layer": gate_defaults
            | {
                "public_internet_path": True,
                "remote_turn_deployment": True,
                "fake_webrtc_engine": False,
                "forced_local_coturn": False,
                "aead": "AES-256-GCM",
                "aad_binds_session_epoch": True,
                "key_epoch_bound": True,
                "directional_key_separation": True,
                "channel_binding_enforced": True,
                "replay_rejected": True,
                "wrong_channel_rejected": True,
                "packet_capture_no_plaintext": True,
                "nonce_reuse_detected": False,
                "plaintext_fallback": False,
                "channels": ["control", "media", "audio", "bulk"],
                "product_flows": {
                    "audio_capture_playback": "not_claimed",
                    "clipboard_sync": "not_claimed",
                    "file_transfer": "not_claimed",
                },
            },
            "two_hour_mixed_route_soak": gate_defaults
            | {
                "duration_seconds": 7200,
                "routes": ["direct", "relay"],
                "controlled_impairment": True,
                "impairment_tool": "linux-netns-tc",
                "impairment_profile": {
                    "latency_ms": 120,
                    "jitter_ms": 35,
                    "loss_percent": 2.0,
                    "bandwidth_kbps": 10000,
                },
                "route_before": "direct",
                "route_after": "relay",
                "network_change_count": 3,
                "bounded_queues": True,
                "bounded_memory": True,
                "no_nonce_reuse": True,
                "no_steady_latency_growth": True,
            },
        },
    }


class ReleaseGateManifestTests(unittest.TestCase):
    def revocation_summary(self, status: str) -> dict[str, object]:
        return {
            "status": status,
            "evidence_kind": "live_production",
            "chain_id": "chain-1",
            "tombstone_id": "tombstone-1",
            "allocation_id": "allocation-1",
            "device_revoked": True,
            "session_revoked": True,
            "authority_tombstone_observed": True,
            "signaling_rejection_observed": True,
            "future_turn_credential_rejected": True,
            "same_allocation_turn_credential_rejected": True,
            "stale_credential_reuse_rejected": True,
            "active_allocation_disconnected": True,
            "post_revocation_traffic_denied": True,
            "post_revocation_packet_count_zero": True,
            "revocation_chain_consistent": True,
        }

    def test_gate_matrix_lists_every_gate_as_open(self) -> None:
        matrix = gate_matrix()
        self.assertEqual({item["gate"] for item in matrix}, EXPECTED_GATE_NAMES)
        self.assertEqual({rule.name for rule in GATE_RULES}, EXPECTED_GATE_NAMES)
        self.assertTrue(all(item["current_status"] == "open" for item in matrix))
        by_gate = {item["gate"]: set(item["required_fields"]) for item in matrix}
        self.assertIn(
            "first_android_output_observed",
            by_gate["real_screencapturekit_to_android_media"],
        )
        self.assertIn("recovery_seconds", by_gate["network_handoff_recovery"])
        self.assertIn("controlled_impairment", by_gate["network_handoff_recovery"])
        self.assertIn("no_steady_latency_growth", by_gate["two_hour_mixed_route_soak"])
        self.assertIn("aead", by_gate["webrtc_datachannel_record_layer"])
        self.assertIn("product_flows", by_gate["webrtc_datachannel_record_layer"])
        self.assertIn("stale_credential_reuse_rejected", by_gate["cross_service_revocation"])
        self.assertIn("device_revoked", by_gate["cross_service_revocation"])
        self.assertIn("session_revoked", by_gate["cross_service_revocation"])
        self.assertIn("revocation_chain_consistent", by_gate["cross_service_revocation"])

    def test_complete_manifest_passes_with_existing_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_default_evidence_root(root)

            self.assertEqual(validate_manifest(passing_manifest(), evidence_root=root), [])

    def test_missing_gate_fails_closed(self) -> None:
        manifest = passing_manifest()
        gates = dict(manifest["gates"])  # type: ignore[arg-type]
        del gates["remote_turn_relay_path"]
        manifest["gates"] = gates

        errors = validate_manifest(manifest)

        self.assertIn("gates.remote_turn_relay_path: expected object", errors)

    def test_missing_local_or_synthetic_negative_fields_fail_closed(self) -> None:
        manifest = passing_manifest()
        gates = manifest["gates"]  # type: ignore[assignment]
        negative_fields = (
            "synthetic_media",
            "local_loopback_only",
            "usb_transport",
            "trusted_lan_only",
            "private_network_only",
            "same_private_network",
            "loopback",
            "synthetic_loopback",
            "synthetic_peer",
        )
        for gate in gates.values():  # type: ignore[union-attr]
            for field in negative_fields:
                del gate[field]

        errors = validate_manifest(manifest)

        for gate_name in EXPECTED_GATE_NAMES:
            for field in negative_fields:
                self.assertIn(f"gates.{gate_name}.{field}: missing required field", errors)

    def test_missing_remote_turn_local_coturn_negative_field_fails_closed(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["remote_turn_relay_path"]  # type: ignore[index]
        del gate["local_coturn_only"]

        self.assertIn(
            "gates.remote_turn_relay_path.local_coturn_only: missing required field",
            validate_manifest(manifest),
        )

    def test_blocked_local_or_synthetic_evidence_cannot_close_gate(self) -> None:
        manifest = passing_manifest()
        manifest["result"] = "blocked"
        gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
        gate["status"] = "blocked"
        gate["synthetic_media"] = True
        gate["local_loopback_only"] = True
        gate["public_internet_path"] = False

        errors = validate_manifest(manifest)

        self.assertIn(
            "result: expected pass; blocked/local/synthetic evidence cannot close the release gate",
            errors,
        )
        self.assertIn("gates.public_internet_direct_path.status: expected pass", errors)
        self.assertIn("gates.public_internet_direct_path.synthetic_media: expected false", errors)
        self.assertIn("gates.public_internet_direct_path.local_loopback_only: expected false", errors)
        self.assertIn("gates.public_internet_direct_path.public_internet_path: expected true", errors)

    def test_usb_trusted_lan_private_network_fields_fail_closed_when_true(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["webrtc_datachannel_record_layer"]  # type: ignore[index]
        gate["usb_transport"] = True
        gate["trusted_lan_only"] = True
        gate["private_network_only"] = True
        gate["same_private_network"] = True
        gate["loopback"] = True
        gate["synthetic_loopback"] = True
        gate["synthetic_peer"] = True

        errors = validate_manifest(manifest)

        for field in (
            "usb_transport",
            "trusted_lan_only",
            "private_network_only",
            "same_private_network",
            "loopback",
            "synthetic_loopback",
            "synthetic_peer",
        ):
            self.assertIn(f"gates.webrtc_datachannel_record_layer.{field}: expected false", errors)

    def test_direct_srflx_same_private_network_cannot_close_public_gate(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
        gate["same_private_network"] = True
        gate["host_network"] = "office-wifi"
        gate["device_network"] = "office-wifi"
        gate["remote_public_route_observed"] = False
        gate["usb_adb_reverse"] = True

        errors = validate_manifest(manifest)

        self.assertIn("gates.public_internet_direct_path.same_private_network: expected false", errors)
        self.assertIn("gates.public_internet_direct_path.remote_public_route_observed: expected true", errors)
        self.assertIn("gates.public_internet_direct_path.usb_adb_reverse: expected false", errors)
        self.assertIn(
            "gates.public_internet_direct_path.device_network: expected a different public network than host_network",
            errors,
        )

    def test_local_coturn_is_rejected_for_remote_turn_gate(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["remote_turn_relay_path"]  # type: ignore[index]
        gate["remote_turn_deployment"] = False
        gate["local_coturn_only"] = True
        gate["forced_local_coturn"] = True
        gate["turn_public_hostname"] = "localhost"
        gate["turn_resolved_public_ip"] = "192.168.1.10"
        gate["selected_candidate_pair"] = "direct(local=host,remote=host,protocol=udp)"

        errors = validate_manifest(manifest)

        self.assertIn("gates.remote_turn_relay_path.remote_turn_deployment: expected true", errors)
        self.assertIn("gates.remote_turn_relay_path.local_coturn_only: expected false", errors)
        self.assertIn("gates.remote_turn_relay_path.forced_local_coturn: expected false", errors)
        self.assertIn("gates.remote_turn_relay_path.turn_public_hostname: expected public hostname or IP", errors)
        self.assertIn("gates.remote_turn_relay_path.turn_resolved_public_ip: expected public hostname or IP", errors)
        self.assertIn(
            "gates.remote_turn_relay_path.selected_candidate_pair: expected relay candidate pair",
            errors,
        )
        self.assertIn(
            "gates.remote_turn_relay_path.selected_candidate_pair: relay gate requires relay local and remote candidates",
            errors,
        )

    def test_private_turn_hostnames_are_rejected_for_remote_turn_gate(self) -> None:
        for hostname in ("relay.corp", "turn.internal", "relay.lan", "turn"):
            with self.subTest(hostname=hostname):
                manifest = passing_manifest()
                gate = manifest["gates"]["remote_turn_relay_path"]  # type: ignore[index]
                gate["turn_public_hostname"] = hostname

                self.assertIn(
                    "gates.remote_turn_relay_path.turn_public_hostname: expected public hostname or IP",
                    validate_manifest(manifest),
                )

    def test_direct_path_remote_public_asn_requires_as_number(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
        gate["remote_public_asn"] = "AS-fake"

        self.assertIn(
            "gates.public_internet_direct_path.remote_public_asn: expected ASN in AS<number> format",
            validate_manifest(manifest),
        )

    def test_record_layer_requires_aes256gcm_channel_binding_nonce_and_replay_proof(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["webrtc_datachannel_record_layer"]  # type: ignore[index]
        gate["aead"] = "AES-128-GCM"
        gate["nonce_reuse_detected"] = True
        gate["channel_binding_enforced"] = False
        gate["replay_rejected"] = False
        gate["channels"] = ["control", "media"]

        errors = validate_manifest(manifest)

        self.assertIn("gates.webrtc_datachannel_record_layer.aead: expected AES-256-GCM", errors)
        self.assertIn("gates.webrtc_datachannel_record_layer.nonce_reuse_detected: expected false", errors)
        self.assertIn("gates.webrtc_datachannel_record_layer.channel_binding_enforced: expected true", errors)
        self.assertIn("gates.webrtc_datachannel_record_layer.replay_rejected: expected true", errors)
        self.assertIn("gates.webrtc_datachannel_record_layer.channels: expected control, media, audio, and bulk", errors)

    def test_audio_clipboard_file_transfer_product_flows_fail_closed_without_real_product_evidence(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["webrtc_datachannel_record_layer"]  # type: ignore[index]
        gate["product_flows"] = {
            "audio_capture_playback": "pass",
            "clipboard_sync": "not_claimed",
            "file_transfer": "not_claimed",
        }

        errors = validate_manifest(manifest)

        self.assertIn(
            "gates.webrtc_datachannel_record_layer.product_flows.audio_capture_playback: expected not_claimed for transport-boundary evidence",
            errors,
        )

    def test_candidate_pair_format_is_validated(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
        gate["selected_candidate_pair"] = "direct(local=host,remote=bogus,protocol=quic)"

        errors = validate_manifest(manifest)

        self.assertIn(
            "gates.public_internet_direct_path.selected_candidate_pair.remote: unsupported candidate type bogus",
            errors,
        )
        self.assertIn(
            "gates.public_internet_direct_path.selected_candidate_pair.protocol: unsupported candidate transport quic",
            errors,
        )

    def test_latency_gate_requires_existing_external_camera_sample_floor(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["external_camera_latency"]  # type: ignore[index]
        gate["sample_count"] = 4

        self.assertIn(
            "gates.external_camera_latency.sample_count: expected >= 5",
            validate_manifest(manifest),
        )

    def test_handoff_gate_requires_fresh_session_timeline(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["network_handoff_recovery"]  # type: ignore[index]
        gate["recovered_session_epoch"] = 7
        gate["old_session_closed"] = False
        gate["recovery_completed_at_monotonic_ms"] = 999

        errors = validate_manifest(manifest)

        self.assertIn(
            "gates.network_handoff_recovery.old_session_closed: expected true",
            errors,
        )
        self.assertIn(
            "gates.network_handoff_recovery.recovered_session_epoch: expected > initial_session_epoch",
            errors,
        )
        self.assertIn(
            "gates.network_handoff_recovery.recovery_completed_at_monotonic_ms: expected > recovery_started_at_monotonic_ms",
            errors,
        )

    def test_deterministic_network_profile_cannot_close_real_network_gate(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["network_handoff_recovery"]  # type: ignore[index]
        gate["impairment_tool"] = "scripts/phase3/network_profile.py"

        self.assertIn(
            "gates.network_handoff_recovery.impairment_tool: deterministic simulator cannot close a release gate",
            validate_manifest(manifest),
        )

        for simulator in ("ns-3", "mininet", "gns3"):
            with self.subTest(simulator=simulator):
                gate["impairment_tool"] = simulator
                self.assertIn(
                    "gates.network_handoff_recovery.impairment_tool: deterministic simulator cannot close a release gate",
                    validate_manifest(manifest),
                )

        gate["impairment_tool"] = "deterministic_contract_simulation_only"
        self.assertIn(
            "gates.network_handoff_recovery.impairment_tool: deterministic simulator cannot close a release gate",
            validate_manifest(manifest),
        )

    def test_impairment_loss_percent_must_be_bounded(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["network_handoff_recovery"]  # type: ignore[index]
        gate["impairment_profile"]["loss_percent"] = 150  # type: ignore[index]

        self.assertIn(
            "gates.network_handoff_recovery.impairment_profile.loss_percent: expected <= 100",
            validate_manifest(manifest),
        )

    def test_handoff_recovery_seconds_must_match_monotonic_interval(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["network_handoff_recovery"]  # type: ignore[index]
        gate["recovery_seconds"] = 1

        self.assertIn(
            "gates.network_handoff_recovery.recovery_seconds: expected to match monotonic recovery interval",
            validate_manifest(manifest),
        )

    def test_cross_service_revocation_requires_live_chain_detail(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["cross_service_revocation"]  # type: ignore[index]
        gate["evidence_kind"] = "offline_fixture"
        gate["device_revoked"] = False
        gate["session_revoked"] = False
        gate["stale_credential_reuse_rejected"] = False
        gate["post_revocation_packet_count_zero"] = False
        gate["revocation_chain_consistent"] = False

        errors = validate_manifest(manifest)

        self.assertIn("gates.cross_service_revocation.evidence_kind: expected live_production", errors)
        self.assertIn(
            "gates.cross_service_revocation.device_revoked: expected true",
            errors,
        )
        self.assertIn(
            "gates.cross_service_revocation.session_revoked: expected true",
            errors,
        )
        self.assertIn(
            "gates.cross_service_revocation.stale_credential_reuse_rejected: expected true",
            errors,
        )
        self.assertIn(
            "gates.cross_service_revocation.post_revocation_packet_count_zero: expected true",
            errors,
        )
        self.assertIn(
            "gates.cross_service_revocation.revocation_chain_consistent: expected true",
            errors,
        )

    def test_cross_service_revocation_requires_chain_identifiers(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["cross_service_revocation"]  # type: ignore[index]
        del gate["chain_id"]
        gate["tombstone_id"] = ""
        del gate["allocation_id"]

        errors = validate_manifest(manifest)

        self.assertIn("gates.cross_service_revocation.chain_id: expected non-empty string", errors)
        self.assertIn("gates.cross_service_revocation.tombstone_id: expected non-empty string", errors)
        self.assertIn("gates.cross_service_revocation.allocation_id: expected non-empty string", errors)

    def test_cross_service_revocation_rejects_fail_summary_even_when_observations_pass(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["cross_service_revocation"]  # type: ignore[index]
        gate.update(revocation_summary_to_manifest_gate(self.revocation_summary("fail")))

        errors = validate_manifest(manifest)

        self.assertIn("gates.cross_service_revocation.status: expected pass", errors)

    def test_cross_service_revocation_rejects_blocked_summary_even_when_observations_pass(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["cross_service_revocation"]  # type: ignore[index]
        gate.update(revocation_summary_to_manifest_gate(self.revocation_summary("blocked")))

        errors = validate_manifest(manifest)

        self.assertIn("gates.cross_service_revocation.status: expected pass", errors)

    def test_cross_service_revocation_validator_requires_device_and_session_revoked(self) -> None:
        gate = passing_manifest()["gates"]["cross_service_revocation"]  # type: ignore[index]
        gate["device_revoked"] = False
        gate["session_revoked"] = False
        rule = next(rule for rule in GATE_RULES if rule.name == "cross_service_revocation")

        errors = rule.validate(gate, "gates.cross_service_revocation")

        self.assertIn("gates.cross_service_revocation.device_revoked: expected true", errors)
        self.assertIn("gates.cross_service_revocation.session_revoked: expected true", errors)

    def test_unknown_gate_fails_closed(self) -> None:
        manifest = passing_manifest()
        manifest["gates"]["unexpected_gate"] = {  # type: ignore[index]
            "status": "pass",
            "synthetic_media": False,
            "local_loopback_only": False,
            "evidence_files": ["logs/direct-session.jsonl"],
        }

        self.assertIn("gates.unexpected_gate: unknown release gate", validate_manifest(manifest))

    def test_soak_gate_requires_controlled_network_conditions(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["two_hour_mixed_route_soak"]  # type: ignore[index]
        gate["controlled_impairment"] = False
        gate["route_after"] = "unknown"
        gate["impairment_profile"]["bandwidth_kbps"] = 0  # type: ignore[index]

        errors = validate_manifest(manifest)

        self.assertIn(
            "gates.two_hour_mixed_route_soak.controlled_impairment: expected true",
            errors,
        )
        self.assertIn(
            "gates.two_hour_mixed_route_soak.route_after: expected direct or relay",
            errors,
        )
        self.assertIn(
            "gates.two_hour_mixed_route_soak.impairment_profile.bandwidth_kbps: expected positive number",
            errors,
        )

    def test_nubia_evidence_cannot_claim_xiaomi_identity(self) -> None:
        manifest = passing_manifest()
        manifest["claims"] = ["Xiaomi 13 fuxi Internet release gate"]

        self.assertIn(
            "claims: Nubia P0110/pacific evidence cannot be relabeled as Xiaomi/fuxi",
            validate_manifest(manifest),
        )

    def test_device_evidence_role_must_match_observed_identity(self) -> None:
        manifest = passing_manifest()
        manifest["device"]["evidence_role"] = "primary_xiaomi_13"  # type: ignore[index]

        self.assertIn(
            "device.evidence_role: primary_xiaomi_13 requires Xiaomi 2211133C/fuxi identity",
            validate_manifest(manifest),
        )

        manifest = passing_manifest()
        manifest["device"] = {
            "manufacturer": "Xiaomi",
            "model": "2211133C",
            "codename": "fuxi",
            "os_version": "Android 16",
            "evidence_role": "general_android_substitute",
        }

        self.assertIn(
            "device.evidence_role: Xiaomi 2211133C/fuxi evidence must use primary_xiaomi_13",
            validate_manifest(manifest),
        )

    def test_claims_are_required_and_must_be_strings(self) -> None:
        manifest = passing_manifest()
        manifest["claims"] = []

        self.assertIn(
            "claims: expected at least one human-readable claim",
            validate_manifest(manifest),
        )

        manifest = passing_manifest()
        manifest["claims"] = ["valid", 123]

        self.assertIn("claims[1]: expected non-empty string", validate_manifest(manifest))

    def test_committed_phase3_evidence_does_not_close_release_gate(self) -> None:
        evidence_dirs = [path for path in sorted(PHASE3_EVIDENCE_ROOT.iterdir()) if path.is_dir()]
        self.assertTrue(evidence_dirs)
        for evidence_dir in evidence_dirs:
            manifest_path = evidence_dir / "release-gate-manifest.json"
            with self.subTest(evidence=evidence_dir.name):
                if not manifest_path.exists():
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertNotEqual(validate_manifest(manifest, evidence_root=evidence_dir), [])

    def test_evidence_files_must_be_relative_and_present_when_root_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SHA256SUMS").write_text("", encoding="utf-8")
            manifest = passing_manifest()
            gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
            gate["evidence_files"] = ["../private.log", "missing.jsonl"]

            errors = validate_manifest(manifest, evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: expected relative file path under evidence root",
            errors,
        )
        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[1]: file does not exist under evidence root",
            errors,
        )

    def test_evidence_files_require_sha256sums_when_root_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn("SHA256SUMS: missing under evidence root", errors)

    def test_evidence_files_require_checksum_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")
            (root / "SHA256SUMS").write_text("", encoding="utf-8")

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: missing checksum entry in SHA256SUMS",
            errors,
        )

    def test_evidence_files_reject_duplicate_checksum_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")
            digest = hashlib.sha256((root / "logs/direct-session.jsonl").read_bytes()).hexdigest()
            (root / "SHA256SUMS").write_text(
                f"{digest}  logs/direct-session.jsonl\n{digest}  logs/direct-session.jsonl\n",
                encoding="utf-8",
            )

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn(
            "SHA256SUMS line 2: duplicate checksum entry for logs/direct-session.jsonl",
            errors,
        )

    def test_evidence_files_reject_malformed_checksum_lines_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")
            (root / "SHA256SUMS").write_text(
                "not-a-valid-line\n"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA  logs/direct-session.jsonl\n",
                encoding="utf-8",
            )

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn("SHA256SUMS line 1: malformed checksum line", errors)
        self.assertIn("SHA256SUMS line 2: expected lowercase SHA-256", errors)

    def test_evidence_files_reject_single_space_checksum_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")
            digest = hashlib.sha256((root / "logs/direct-session.jsonl").read_bytes()).hexdigest()
            (root / "SHA256SUMS").write_text(
                f"{digest} logs/direct-session.jsonl\n",
                encoding="utf-8",
            )

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn("SHA256SUMS line 1: malformed checksum line", errors)

    def test_evidence_files_reject_checksum_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            root.mkdir()
            write_evidence_file(root, "logs/direct-session.jsonl")
            digest = hashlib.sha256((root / "logs/direct-session.jsonl").read_bytes()).hexdigest()
            (root / "SHA256SUMS").write_text(
                f"{digest}  ../outside.log\n{digest}  /tmp/outside.log\n",
                encoding="utf-8",
            )

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn("SHA256SUMS line 1: expected relative path under evidence root", errors)
        self.assertIn("SHA256SUMS line 2: expected relative path under evidence root", errors)

    def test_evidence_files_reject_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_evidence_file(root, "logs/direct-session.jsonl")
            (root / "SHA256SUMS").write_text(
                f"{'0' * 64}  logs/direct-session.jsonl\n",
                encoding="utf-8",
            )

            errors = validate_manifest(passing_manifest(), evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: SHA256SUMS hash mismatch",
            errors,
        )

    def test_current_revocation_evidence_fixture_files_match_sha256sums(self) -> None:
        evidence_root = (
            PHASE3_EVIDENCE_ROOT / "2026-08-25-revocation-propagation-current-base"
        )
        manifest = passing_manifest()
        fixture_files = [
            "README.md",
            "commands.txt",
            "privacy-scan.json",
            "revocation-propagation-current-base-blocked.json",
            "revocation-propagation-current-base-summary.json",
        ]
        for gate in manifest["gates"].values():  # type: ignore[union-attr]
            gate["evidence_files"] = fixture_files

        errors = validate_manifest(manifest, evidence_root=evidence_root)

        self.assertEqual(errors, [])

    def test_evidence_files_must_not_escape_evidence_root_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "private.log").write_text("private evidence\n", encoding="utf-8")
            (root / "leaked.log").symlink_to(outside / "private.log")
            (root / "SHA256SUMS").write_text(
                f"{'0' * 64}  leaked.log\n",
                encoding="utf-8",
            )

            manifest = passing_manifest()
            gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
            gate["evidence_files"] = ["leaked.log"]

            errors = validate_manifest(manifest, evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: expected file under evidence root",
            errors,
        )

    def test_evidence_files_symlink_loop_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loop-a.log").symlink_to("loop-b.log")
            (root / "loop-b.log").symlink_to("loop-a.log")
            (root / "SHA256SUMS").write_text(
                f"{'0' * 64}  loop-a.log\n",
                encoding="utf-8",
            )

            manifest = passing_manifest()
            gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
            gate["evidence_files"] = ["loop-a.log"]

            errors = validate_manifest(manifest, evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: expected file under evidence root",
            errors,
        )

    def test_cli_prints_matrix_and_validates_manifest(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--print-matrix"]), 0)
        self.assertIn("public_internet_direct_path", stdout.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_default_evidence_root(root)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(passing_manifest()), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main([str(manifest_path), "--evidence-root", str(root)]), 0)
            self.assertIn('"result": "pass"', stdout.getvalue())

    def test_cli_reports_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps({"schema": SCHEMA}), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main([str(manifest_path)]), 1)
            self.assertIn("result: expected pass", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
