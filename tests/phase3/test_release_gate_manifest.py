from __future__ import annotations

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
    "two_hour_mixed_route_soak",
}


def passing_manifest() -> dict[str, object]:
    evidence_file = "logs/direct-session.jsonl"
    gate_defaults = {
        "status": "pass",
        "synthetic_media": False,
        "local_loopback_only": False,
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
            },
            "remote_turn_relay_path": gate_defaults
            | {
                "route": "relay",
                "public_internet_path": True,
                "remote_turn_deployment": True,
                "local_coturn_only": False,
                "selected_candidate_pair": "relay(local=relay,remote=relay,protocol=udp)",
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
                "recovery_seconds": 4.5,
                "approved_limit_seconds": 5,
            },
            "cross_service_revocation": gate_defaults
            | {
                "active_session_disconnected": True,
                "direct_reconnect_rejected": True,
                "relay_reconnect_rejected": True,
                "turn_allocation_disconnected": True,
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

    def test_complete_manifest_passes_with_existing_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            (root / "logs/direct-session.jsonl").write_text("{}\n", encoding="utf-8")

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
        for gate in gates.values():  # type: ignore[union-attr]
            del gate["synthetic_media"]
            del gate["local_loopback_only"]

        errors = validate_manifest(manifest)

        for gate_name in EXPECTED_GATE_NAMES:
            self.assertIn(f"gates.{gate_name}.synthetic_media: missing required field", errors)
            self.assertIn(f"gates.{gate_name}.local_loopback_only: missing required field", errors)

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

    def test_local_coturn_is_rejected_for_remote_turn_gate(self) -> None:
        manifest = passing_manifest()
        gate = manifest["gates"]["remote_turn_relay_path"]  # type: ignore[index]
        gate["remote_turn_deployment"] = False
        gate["local_coturn_only"] = True
        gate["selected_candidate_pair"] = "direct(local=host,remote=host,protocol=udp)"

        errors = validate_manifest(manifest)

        self.assertIn("gates.remote_turn_relay_path.remote_turn_deployment: expected true", errors)
        self.assertIn("gates.remote_turn_relay_path.local_coturn_only: expected false", errors)
        self.assertIn(
            "gates.remote_turn_relay_path.selected_candidate_pair: expected relay candidate pair",
            errors,
        )
        self.assertIn(
            "gates.remote_turn_relay_path.selected_candidate_pair: relay gate requires relay local and remote candidates",
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
            manifest = passing_manifest()
            gate = manifest["gates"]["public_internet_direct_path"]  # type: ignore[index]
            gate["evidence_files"] = ["../private.log", "missing.jsonl"]

            errors = validate_manifest(manifest, evidence_root=root)

        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[0]: expected repository-relative file path",
            errors,
        )
        self.assertIn(
            "gates.public_internet_direct_path.evidence_files[1]: file does not exist under evidence root",
            errors,
        )

    def test_cli_prints_matrix_and_validates_manifest(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--print-matrix"]), 0)
        self.assertIn("public_internet_direct_path", stdout.getvalue())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            (root / "logs/direct-session.jsonl").write_text("{}\n", encoding="utf-8")
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
