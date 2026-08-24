from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase3_adaptive_media_current_base import KIND, derive_gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE = "vibescreen_evidence.phase3_adaptive_media_current_base"
SCHEMA_PATH = REPOSITORY_ROOT / "tools/schemas/phase3-adaptive-media-current-base.schema.json"
CURRENT_COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=REPOSITORY_ROOT,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def adaptive_report(
    *,
    verdict: str = "pass",
    commit: str = CURRENT_COMMIT,
    dirty: bool = False,
    network_scope: str = "public_internet",
    public_internet_path: bool = True,
    local_loopback_only: bool = False,
    controlled_impairment: bool = True,
    real_network_impairment: bool = True,
    real_webrtc_statistics: bool = True,
    static_latency_fixture: bool = False,
    synthetic_media: bool = False,
    impairment_tool: str = "linux-netns-tc-router",
    downgrade_observations: int = 2,
    upgrade_observations: int = 5,
    profile_events: list[dict[str, object]] | None = None,
    config_epochs: list[int] | None = None,
    video_config_acknowledged: bool = True,
    keyframe_after_config_ack: bool = True,
    latest_proposal_wins: bool = True,
    stale_owner_or_generation_rejected: bool = True,
    rollback_fail_closed: bool = True,
    oscillation_detected: bool = False,
    transport_restart_count: int = 0,
    no_transport_restart: bool = True,
    session_epoch_unchanged: bool = True,
    media_channel_continuous: bool = True,
    device: dict[str, object] | None = None,
    raw_sources: list[str] | None = None,
) -> dict[str, object]:
    if device is None:
        device = {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": 36,
            "hardware_serial": "EP0110PZ0B9110300B",
        }
    if profile_events is None:
        profile_events = [
            {"direction": "baseline", "config_epoch": 10, "bitrate_bps": 12000000, "fps": 60, "acked": True},
            {"direction": "downgrade", "config_epoch": 11, "bitrate_bps": 2500000, "fps": 20, "acked": True},
            {"direction": "upgrade", "config_epoch": 12, "bitrate_bps": 6000000, "fps": 30, "acked": True},
        ]
    if config_epochs is None:
        config_epochs = [10, 11, 12]
    if raw_sources is None:
        raw_sources = ["host.log", "raw-logcat.txt", "webrtc-stats.jsonl"]
    return {
        "schema": "dev.vibescreen.phase3-adaptive-media-fluctuation/v1",
        "schema_version": SCHEMA_VERSION,
        "kind": "phase3_adaptive_media_fluctuation_report",
        "created_at": "2026-08-24T00:00:00+00:00",
        "verdict": verdict,
        "repository": {
            "revision": commit,
            "branch": "codex/phase3-adaptive-media-current-base",
            "dirty": dirty,
        },
        "device": device,
        "run_context": {
            "network_scope": network_scope,
            "public_internet_path": public_internet_path,
            "local_loopback_only": local_loopback_only,
            "controlled_impairment": controlled_impairment,
            "real_network_impairment": real_network_impairment,
            "real_webrtc_statistics": real_webrtc_statistics,
            "static_latency_fixture": static_latency_fixture,
            "synthetic_media": synthetic_media,
            "impairment_tool": impairment_tool,
        },
        "adaptive_media": {
            "fast_drop": {"observed": True, "downgrade_within_observations": downgrade_observations},
            "slow_rise": {"observed": True, "upgrade_after_observations": upgrade_observations},
            "profile_events": profile_events,
            "config_epochs": config_epochs,
            "video_config_acknowledged": video_config_acknowledged,
            "keyframe_after_config_ack": keyframe_after_config_ack,
            "latest_proposal_wins": latest_proposal_wins,
            "stale_owner_or_generation_rejected": stale_owner_or_generation_rejected,
            "rollback_fail_closed": rollback_fail_closed,
            "oscillation_detected": oscillation_detected,
        },
        "transport_continuity": {
            "selected_transport": "webrtc",
            "selected_candidate_pair": "srflx-to-relay over public Internet",
            "no_transport_restart": no_transport_restart,
            "session_epoch_unchanged": session_epoch_unchanged,
            "media_channel_continuous": media_channel_continuous,
            "transport_restart_count": transport_restart_count,
        },
        "raw_sources": raw_sources,
    }


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def assert_schema_shape(test_case: unittest.TestCase, document: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    test_case.assertEqual(set(document), set(schema["properties"]))
    for key in schema["required"]:
        test_case.assertIn(key, document)
    test_case.assertEqual(set(document["checks"]), set(schema["properties"]["checks"]["properties"]))


class Phase3AdaptiveMediaCurrentBaseGateTests(unittest.TestCase):
    def derive(self, root: Path, report: dict[str, object] | None = None) -> dict[str, object]:
        report_path = write_json(root / "adaptive-media-fluctuation.json", report or adaptive_report())
        return derive_gate(report_path=report_path, repo=REPOSITORY_ROOT, current_commit=CURRENT_COMMIT)

    def test_complete_real_fluctuation_report_passes_child_gate_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory))

        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["kind"], KIND)
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["can_claim_current_base_adaptive_media_fluctuation"])
        self.assertFalse(result["gate_can_close_phase3_release"])
        self.assertEqual(result["release_gate_effect"], "child_gate_only")
        self.assertEqual(result["owner"]["role"], "phase3_adaptive_media_current_base_owner")
        self.assertEqual(result["device"]["manufacturer"], "nubia")
        self.assertEqual(result["device"]["model"], "P0110")
        self.assertEqual(result["device"]["codename"], "pacific")
        self.assertEqual(result["device"]["android_version"], "16")
        self.assertEqual(result["device"]["sdk"], 36)
        self.assertEqual(result["reasons"], [])
        assert_schema_shape(self, result)

    def test_static_latency_fixture_cannot_pass_as_adaptive_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(static_latency_fixture=True))

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_claim_current_base_adaptive_media_fluctuation"])
        self.assertIn("blocked: no_static_fixture_or_synthetic_media", result["reasons"])

    def test_local_loopback_and_synthetic_media_are_blocked(self) -> None:
        cases = {
            "loopback": adaptive_report(network_scope="local_loopback", public_internet_path=False, local_loopback_only=True),
            "synthetic_media": adaptive_report(synthetic_media=True),
        }
        for label, report in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), report)

            self.assertEqual(result["verdict"], "blocked")

    def test_deterministic_network_profile_tool_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                adaptive_report(impairment_tool="scripts/phase3/network_profile.py deterministic fixture"),
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: impairment_tool", result["reasons"])

    def test_missing_real_webrtc_statistics_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(real_webrtc_statistics=False))

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: real_webrtc_statistics", result["reasons"])

    def test_fast_drop_and_slow_rise_are_required(self) -> None:
        cases = {
            "slow_drop": adaptive_report(downgrade_observations=3),
            "fast_rise": adaptive_report(upgrade_observations=2),
        }
        for label, report in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), report)

            self.assertEqual(result["verdict"], "blocked")

    def test_bitrate_fps_and_config_epoch_evidence_are_required(self) -> None:
        cases = {
            "flat_bitrate": adaptive_report(
                profile_events=[
                    {"direction": "baseline", "config_epoch": 10, "bitrate_bps": 12000000, "fps": 60, "acked": True},
                    {"direction": "downgrade", "config_epoch": 11, "bitrate_bps": 12000000, "fps": 60, "acked": True},
                    {"direction": "upgrade", "config_epoch": 12, "bitrate_bps": 12000000, "fps": 60, "acked": True},
                ]
            ),
            "non_monotonic_epoch": adaptive_report(config_epochs=[10, 10, 11]),
            "missing_ack": adaptive_report(video_config_acknowledged=False),
        }
        for label, report in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), report)

            self.assertEqual(result["verdict"], "blocked")

    def test_policy_safety_boundaries_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(stale_owner_or_generation_rejected=False))

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: policy_safety_boundaries", result["reasons"])

    def test_transport_restart_is_a_failure_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                adaptive_report(transport_restart_count=1, no_transport_restart=False),
            )

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: transport_continuity", result["reasons"])

    def test_unsafe_oscillation_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(oscillation_detected=True))

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: no_unsafe_oscillation", result["reasons"])

    def test_old_or_dirty_report_is_blocked(self) -> None:
        cases = {
            "old_commit": adaptive_report(commit="b" * 40),
            "dirty_source": adaptive_report(dirty=True),
        }
        for label, report in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), report)

            self.assertEqual(result["verdict"], "blocked")
            self.assertFalse(result["can_claim_current_base_adaptive_media_fluctuation"])

    def test_nubia_p0110_identity_must_stay_pacific(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                adaptive_report(
                    device={
                        "manufacturer": "nubia",
                        "model": "P0110",
                        "codename": "fuxi",
                        "android_version": "16",
                        "sdk": 36,
                    }
                ),
            )

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: android_device_identity", result["reasons"])
        serialized = json.dumps(result, sort_keys=True)
        self.assertIn("P0110", serialized)
        self.assertNotIn("EP0110PZ0B9110300B", serialized)

    def test_raw_fixture_sources_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(raw_sources=["fixtures/latency-summary.json"]))

        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("blocked: raw_sources_retained", result["reasons"])

    def test_raw_sources_must_include_host_android_and_webrtc_stats(self) -> None:
        cases = {
            "missing_host": ["raw-logcat.txt", "webrtc-stats.jsonl"],
            "missing_android": ["host.log", "webrtc-stats.jsonl"],
            "missing_webrtc_stats": ["host.log", "raw-logcat.txt"],
        }
        for label, raw_sources in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = self.derive(Path(directory), adaptive_report(raw_sources=raw_sources))

            self.assertEqual(result["verdict"], "blocked")
            self.assertIn("blocked: raw_sources_retained", result["reasons"])

    def test_report_status_fail_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(Path(directory), adaptive_report(verdict="fail"))

        self.assertEqual(result["verdict"], "fail")
        self.assertIn("fail: report_passed", result["reasons"])

    def test_sensitive_strings_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.derive(
                Path(directory),
                adaptive_report(
                    raw_sources=["/Users/alice/webrtc-stats.jsonl", "host=203.0.113.7", "alice@example.com"],
                ),
            )

        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("/Users/alice", serialized)
        self.assertNotIn("203.0.113.7", serialized)
        self.assertNotIn("alice@example.com", serialized)
        self.assertIn("[redacted", serialized)


class Phase3AdaptiveMediaCurrentBaseCliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = "tools"
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def test_cli_writes_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = write_json(root / "adaptive-media-fluctuation.json", adaptive_report())
            output = root / "adaptive-media-current-base.json"

            result = self.run_cli(
                "--report",
                str(report),
                "--current-commit",
                CURRENT_COMMIT,
                "--output",
                str(output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["verdict"], "pass")

    def test_cli_returns_blocked_for_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = write_json(
                root / "adaptive-media-fluctuation.json",
                adaptive_report(network_scope="local_loopback", public_internet_path=False, local_loopback_only=True),
            )

            result = self.run_cli("--report", str(report), "--current-commit", CURRENT_COMMIT)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["verdict"], "blocked")
        self.assertIn("blocked: public_internet_scope", result.stderr)


if __name__ == "__main__":
    unittest.main()
