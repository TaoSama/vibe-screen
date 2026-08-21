from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_internet_soak import (
    GATE_KIND,
    MANIFEST_KIND,
    build_manifest,
    derive_gate,
    main,
)


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class Phase3InternetSoakTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @patch("vibescreen_evidence.phase3_internet_soak.repository_state")
    def manifest(self, repository_state):
        repository_state.return_value = {"revision": "abc1234", "dirty": False, "status_porcelain": []}
        return build_manifest(
            repo=self.root,
            command=["make", "phase3-internet-soak-gate"],
            turn_uris=["turns:relay.vibescreen.dev:5349?transport=tcp"],
            signaling_origin="https://signaling.vibescreen.dev",
            relay_origin="https://relay.vibescreen.dev",
            authority_source_id="turn-prod-1",
            remote_peer="peer.vibescreen.dev",
            tls_certificate_sha256="a" * 64,
            turn_secret_source="secret_manager",
            deployment_readiness=["authority-readyz", "relay-readyz", "coturn-tls"],
            planned_handoffs=["wifi-to-cellular"],
            host_build="Vibe Screen release abc1234",
            android_artifact_sha256="b" * 64,
            duration_seconds=7200,
            sample_interval_seconds=30,
            notes=None,
        )

    def complete_inputs(self) -> dict[str, Path]:
        manifest = _write(self.root / "manifest.json", self.manifest())
        remote_turn = _write(
            self.root / "remote-turn.json",
            {
                "result": "pass",
                "remote_peer": "public",
                "route_scope": "public_internet",
                "relay_packets": {"sent": 4, "received": 4},
            },
        )
        media = _write(
            self.root / "media.json",
            {
                "result": "pass",
                "real_screencapturekit": True,
                "real_android_decoder": True,
                "decoded_frames": 430000,
                "dropped_frames": 0,
                "maximum_frame_gap_seconds": 1.4,
            },
        )
        handoff = _write(
            self.root / "handoff.json",
            {
                "result": "pass",
                "network_handoff_count": 1,
                "stale_media_rejected": True,
                "fresh_session_recovered": True,
                "plaintext_fallback_observed": False,
            },
        )
        revocation = _write(
            self.root / "revocation.json",
            {
                "status": "pass",
                "missing": [],
                "failures": [],
                "active_allocation_disconnected": True,
                "stale_credential_reuse_rejected": True,
                "post_revocation_traffic_denied": True,
                "relayed_packets_after_revocation": 0,
            },
        )
        soak = _write(
            self.root / "soak.json",
            {
                "derivation_status": "complete",
                "window": {"duration_seconds": 7200, "sample_records_in_window": 240},
                "metrics": {"samples": {"gaps": {"maximum_window_gap_seconds": 31}}},
                "routes": {"direct": {"sample_count": 120}, "relay": {"sample_count": 120}},
                "metric_families": [
                    "host_rss",
                    "client_memory",
                    "queue",
                    "loss",
                    "rtt",
                    "fps",
                    "bitrate",
                    "relay_bytes",
                    "ice_restart",
                    "drops",
                    "thermal",
                    "battery",
                ],
                "nonce_reuse_detected": False,
                "plaintext_fallback_observed": False,
                "errors": [],
            },
        )
        return {
            "manifest_path": manifest,
            "remote_turn_path": remote_turn,
            "media_continuity_path": media,
            "network_handoff_path": handoff,
            "revocation_path": revocation,
            "soak_report_path": soak,
        }

    def test_manifest_records_public_inputs_without_raw_endpoints(self) -> None:
        manifest = self.manifest()

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], MANIFEST_KIND)
        self.assertEqual(manifest["deployment"]["turn_uris"][0]["scheme"], "turns")
        self.assertNotIn("relay.vibescreen.dev", json.dumps(manifest))
        self.assertIn("phase3-internet-soak-gate.json", manifest["required_artifacts"])

    def test_complete_gate_passes(self) -> None:
        gate = derive_gate(**self.complete_inputs())

        self.assertEqual(gate["kind"], GATE_KIND)
        self.assertEqual(gate["verdict"], "pass")
        self.assertEqual(gate["reasons"], [])

    def test_missing_remote_turn_blocks_instead_of_passing(self) -> None:
        inputs = self.complete_inputs()
        inputs["remote_turn_path"] = None

        gate = derive_gate(**inputs, blocked_reason="no public deployment")

        self.assertEqual(gate["verdict"], "blocked")
        self.assertTrue(gate["inputs"]["remote_turn"]["error"].startswith("missing"))
        self.assertIn("no public deployment", gate["reasons"][0])

    def test_media_gap_blocks_release_gate(self) -> None:
        inputs = self.complete_inputs()
        _write(
            inputs["media_continuity_path"],
            {
                "result": "pass",
                "real_screencapturekit": True,
                "real_android_decoder": True,
                "decoded_frames": 100,
                "dropped_frames": 0,
                "maximum_frame_gap_seconds": 7.0,
            },
        )

        gate = derive_gate(**inputs)

        self.assertEqual(gate["verdict"], "blocked")
        self.assertFalse(gate["criteria"]["media_continuity"]["passed"])

    def test_plaintext_fallback_fails_gate(self) -> None:
        inputs = self.complete_inputs()
        _write(
            inputs["soak_report_path"],
            {
                "derivation_status": "complete",
                "window": {"duration_seconds": 7200, "sample_records_in_window": 240},
                "metrics": {"samples": {"gaps": {"maximum_window_gap_seconds": 31}}},
                "routes": {"direct": {"sample_count": 120}, "relay": {"sample_count": 120}},
                "metric_families": list(__import__("vibescreen_evidence.phase3_internet_soak", fromlist=["REQUIRED_METRIC_FAMILIES"]).REQUIRED_METRIC_FAMILIES),
                "nonce_reuse_detected": False,
                "plaintext_fallback_observed": True,
                "errors": [],
            },
        )

        gate = derive_gate(**inputs)

        self.assertEqual(gate["verdict"], "fail")
        self.assertTrue(gate["criteria"]["soak"]["plaintext_fallback_observed"])

    def test_handoff_plaintext_fallback_fails_gate(self) -> None:
        inputs = self.complete_inputs()
        _write(
            inputs["network_handoff_path"],
            {
                "result": "pass",
                "network_handoff_count": 1,
                "stale_media_rejected": True,
                "fresh_session_recovered": True,
                "plaintext_fallback_observed": True,
            },
        )

        gate = derive_gate(**inputs)

        self.assertEqual(gate["verdict"], "fail")
        self.assertTrue(gate["criteria"]["network_handoff"]["plaintext_fallback_observed"])

    def test_secret_like_report_is_failed(self) -> None:
        inputs = self.complete_inputs()
        _write(inputs["remote_turn_path"], {"result": "pass", "credential": "raw-secret"})

        gate = derive_gate(**inputs)

        self.assertEqual(gate["verdict"], "fail")
        self.assertTrue(any("secret material" in reason for reason in gate["reasons"]))

    def test_cli_gate_exit_codes_blocked_and_allowed_blocked(self) -> None:
        output = self.root / "gate.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            blocked_code = main(["gate", "--output", str(output), "--blocked-reason", "missing deployment"])
        self.assertEqual(blocked_code, 3)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["verdict"], "blocked")

        with contextlib.redirect_stderr(io.StringIO()):
            allowed_code = main(["gate", "--output", str(output), "--allow-blocked"])
        self.assertEqual(allowed_code, 0)


if __name__ == "__main__":
    unittest.main()
