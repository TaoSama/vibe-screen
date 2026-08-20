from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.network_profile import DEFAULT_PROFILES, ProfileError, Segment, load_segments, simulate


class NetworkProfileTests(unittest.TestCase):
    def test_handoff_preserves_control_and_bounds_media(self) -> None:
        segments = load_segments("healthy", Path(__file__).parent / "profiles" / "handoff.json")
        result = simulate(segments, seed=17, media_queue_capacity=2)
        self.assertEqual(result.evidence_scope, "deterministic_contract_simulation_only")
        self.assertIn("not_webrtc_ice_or_turn_evidence", result.evidence_limitations)
        self.assertEqual(result.route_sequence, ["wifi", "transition", "cellular"])
        self.assertEqual(result.segments[1]["name"], "handoff-outage")
        self.assertEqual(result.control_sent, result.control_delivered)
        self.assertTrue(result.control_ordered)
        self.assertLessEqual(result.max_media_queue_depth, 2)
        self.assertGreater(result.media_network_drops + result.media_queue_drops, 0)
        self.assertEqual(result.handoffs, 2)
        self.assertEqual(result.final_network_id, "cellular")

    def test_seed_is_deterministic(self) -> None:
        segments = [Segment("lossy", 1000, 80, 30, 20.0, 3000, "wifi")]
        self.assertEqual(simulate(segments, seed=9), simulate(segments, seed=9))
        self.assertNotEqual(simulate(segments, seed=9).delivered_media_sequences, simulate(segments, seed=10).delivered_media_sequences)

    def test_healthy_link_does_not_create_artificial_backlog(self) -> None:
        result = simulate(DEFAULT_PROFILES["healthy"], seed=20260804)
        self.assertEqual(result.media_queue_drops, 0)
        self.assertGreater(result.media_delivered / result.media_sent, 0.95)

    def test_built_in_profiles_cover_network_gate_scenarios(self) -> None:
        self.assertIn("moderate", DEFAULT_PROFILES)
        self.assertIn("bandwidth-step", DEFAULT_PROFILES)
        self.assertIn("handoff", DEFAULT_PROFILES)
        self.assertIn("relay-loss", DEFAULT_PROFILES)
        step = simulate(DEFAULT_PROFILES["bandwidth-step"], seed=20260804)
        relay_loss = simulate(DEFAULT_PROFILES["relay-loss"], seed=20260804)
        self.assertEqual(step.route_sequence, ["wifi"])
        self.assertEqual(relay_loss.route_sequence, ["relay", "relay-outage", "relay"])

    def test_weak_link_prefers_recent_media(self) -> None:
        result = simulate(DEFAULT_PROFILES["weak"], seed=20260804)
        self.assertGreater(result.media_queue_drops, 0)
        self.assertNotEqual(result.delivered_media_sequences, sorted(result.delivered_media_sequences))
        self.assertIn(result.media_sent - 1, result.delivered_media_sequences)

    def test_invalid_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps([{"name": "missing fields"}]), encoding="utf-8")
            with self.assertRaises(ProfileError):
                load_segments("healthy", path)

    def test_total_loss_fails_closed_without_recursion(self) -> None:
        result = simulate([Segment("offline", 500, 10, 0, 100.0, 1000, "none")], seed=1)
        self.assertEqual(result.control_delivered, 0)
        self.assertFalse(result.control_ordered)
        self.assertEqual(result.media_delivered, 0)

    def test_cli_writes_atomic_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "result.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts/phase3/network_profile.py"), "--profile", "weak", "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["control_ordered"])
            self.assertFalse(output.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
