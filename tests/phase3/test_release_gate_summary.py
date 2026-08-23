from __future__ import annotations

import json
from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.release_gate_summary import (  # noqa: E402
    AGGREGATE_OWNER,
    CANDIDATE_PRS,
    HISTORICAL_ANDROID_BOUNDARY_DEFAULTS,
    RELEASE_GATES,
    REQUIRED_CURRENT_BASE_REAL_MEDIA_CHECKS,
    SCHEMA,
    build_summary,
    main,
)
from scripts.phase3_webrtc.model import EVIDENCE_SCHEMA  # noqa: E402
from scripts.phase3_webrtc.public_evidence import (  # noqa: E402
    PRODUCT_MEDIA_PROOF,
    PRODUCT_MEDIA_SOURCE,
    build_public_artifact_tree,
)
from scripts.phase3_webrtc.privacy import write_private_text, write_public_diagnostic  # noqa: E402


def private_product_evidence(
    mode: str, commit: str, *, dirty: bool = False
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "mode": mode,
        "slice": "product",
        "result": "pass",
        "signaling": {
            "real_process": True,
            "health": "pass",
            "ready": "pass",
            "authenticated_session": "pass",
            "accepted_messages": 12,
            "secret_log_scan": "pass",
        },
        "webrtc": {
            "implementation": "stasel/WebRTC 150.0.0 production adapter",
            "real_peer_connections": 2,
            "offer_answer_via_http_signaling": "pass",
            "ice_candidate_exchange": "pass",
            "application_e2ee": "AES-256-GCM Protocol v1 record layer pass",
            "data_channels": {
                "control": "ordered/reliable; bidirectional payload pass",
                "media": "unordered/maxRetransmits=0; bidirectional payload pass",
            },
            "selected_candidate_pair": (
                f"{mode}(local={'relay' if mode == 'relay' else 'host'},"
                f"remote={'relay' if mode == 'relay' else 'host'},protocol=udp)"
            ),
            "selected_route": mode,
        },
        "artifacts": {
            "signaling_sha256": "a" * 64,
            "mac_host_sha256": "b" * 64,
            "webrtc_framework_sha256": "c" * 64,
            "turnserver_sha256": "d" * 64 if mode == "relay" else "not_used",
        },
        "environment": {
            "repository_commit": commit,
            "repository_source": {
                "repository_commit": commit,
                "dirty": dirty,
                "source_fingerprint": "e" * 64,
            },
        },
        "product_session": {
            "host": "InternetProductSession",
            "device": "synthetic Protocol v1 harness",
            "client_hello": "pass",
            "session_accepted_epoch": 1,
            "initial_video_config_ack_epoch": 1,
            "runtime_video_config_ack_epoch": 2,
            "runtime_rotation_degrees": 90,
            "media": PRODUCT_MEDIA_PROOF,
            "media_source": PRODUCT_MEDIA_SOURCE,
            "touch_input": "pass",
            "seeded_plaintext_log_scan": "pass",
            "capture_or_stream_server_started": False,
        },
    }
    if mode == "relay":
        evidence["coturn"] = {
            "real_process": True,
            "version": "4.16.0",
            "forced_libwebrtc_relay": "pass",
            "executable_sha256": "d" * 64,
        }
    return evidence


def current_base_real_media_gate(
    commit: str,
    *,
    verdict: str = "pass",
    can_claim: bool = True,
    release_gate_effect: str = "child_gate_only",
    checks: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    required_checks = {
        key: {"passed": True, "expected": "fixture evidence is present", "evidence": ["fixture"]}
        for key in REQUIRED_CURRENT_BASE_REAL_MEDIA_CHECKS
    }
    if checks:
        required_checks.update(checks)
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "phase3_real_media_current_base_gate",
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "can_claim_current_base_real_media_continuity": can_claim,
        "current_base": {
            "repository_commit": commit,
            "continuity_repository_revision": commit,
            "continuity_repository_dirty": False,
        },
        "owner": {
            "role": "phase3_real_media_current_base_owner",
            "pull_request": "pending-draft-pr",
            "head_ref": "codex/phase3-real-media-evidence-gate",
            "repository": "TaoSama/vibe-screen",
            "scope": "fixture current-base real-media child gate",
        },
        "source": {
            "continuity_result": {
                "category": "real_media_continuity",
                "path": "real-media-continuity.json",
                "extension": ".json",
                "exists": True,
                "sha256": "a" * 64,
                "bytes": 42,
            },
            "continuity_repository_revision": commit,
            "continuity_repository_branch": "codex/phase3-real-media-continuity",
            "continuity_repository_dirty": False,
        },
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": 36,
        },
        "android_visible_ui": {
            "artifact_kind": "device_screenshot",
            "operator_note": "decoded Mac desktop content visible in the Android UI",
            "artifacts": [
                {
                    "category": "android_visible_ui",
                    "path": "android-visible-ui.png",
                    "extension": ".png",
                    "exists": True,
                    "sha256": "b" * 64,
                    "bytes": 42,
                    "artifact_kind": "device_screenshot",
                }
            ],
        },
        "checks": required_checks,
        "continuity_summary": {
            "media_source": "real_screencapturekit_or_cgdisplaystream",
            "public_internet_path": True,
            "selected_webrtc_route": "relay",
            "continuous_output_frames": 120,
            "dropped_frames": 0,
            "decoder_error_count": 0,
        },
        "reasons": [] if verdict == "pass" else ["fixture blocked"],
        "release_gate_effect": release_gate_effect,
        "interpretation": "fixture current-base real-media child gate result",
    }


class Phase3ReleaseGateSummaryTests(unittest.TestCase):
    def test_release_gate_name_set_is_explicit(self) -> None:
        self.assertEqual(
            [name for name, _, _, _ in RELEASE_GATES],
            [
                "public_internet_path",
                "real_remote_turn",
                "screencapturekit_to_android_mediacodec",
                "visible_input_effects",
                "network_handoff",
                "cross_service_revocation",
                "packet_capture_confidentiality",
                "two_hour_mixed_route_soak",
                "production_services",
                "independent_security_review",
            ],
        )

    def test_release_gate_owners_and_status_are_explicit(self) -> None:
        summary = build_summary(
            ROOT,
            local_public_dir=ROOT / "missing-public",
            android_interop_acceptance=ROOT / "missing-android.json",
            blocked_real_media_acceptance=ROOT / "missing-blocked.json",
            current_commit="c" * 40,
        )

        self.assertEqual(summary["aggregate_owner"], AGGREGATE_OWNER)
        self.assertEqual(summary["aggregate_owner"]["pull_request"], 258)
        self.assertIn(
            {
                "pull_request": 258,
                "role": "current_base_aggregate_owner",
                "recommendation": "use_as_unique_aggregate_owner",
                "reason": "current-base summary is executable and keeps all public release gates open",
            },
            summary["candidate_prs"],
        )
        self.assertEqual(
            {candidate["pull_request"] for candidate in summary["candidate_prs"]},
            {candidate["pull_request"] for candidate in CANDIDATE_PRS},
        )
        self.assertTrue(
            all(isinstance(candidate["pull_request"], int) for candidate in summary["candidate_prs"])
        )
        owner_by_gate = {gate["gate"]: gate["owner_pr"] for gate in summary["release_gates"]}
        self.assertEqual(owner_by_gate["public_internet_path"], 194)
        self.assertEqual(owner_by_gate["real_remote_turn"], 194)
        self.assertEqual(owner_by_gate["screencapturekit_to_android_mediacodec"], 173)
        self.assertEqual(owner_by_gate["network_handoff"], 224)
        self.assertEqual(owner_by_gate["cross_service_revocation"], 190)
        self.assertEqual(owner_by_gate["two_hour_mixed_route_soak"], 214)
        self.assertEqual(owner_by_gate["production_services"], 254)
        for gate in summary["release_gates"]:
            self.assertEqual(gate["status"], "open")
            self.assertTrue(gate["evidence_state"].startswith("blocked_"))

    def test_summary_keeps_release_gates_open_for_current_local_public_artifacts(self) -> None:
        commit = "1" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private"
            private.mkdir(mode=0o700)
            for mode in ("direct", "relay"):
                write_private_text(
                    private / f"{mode}.json",
                    json.dumps(private_product_evidence(mode, commit)),
                )
            for relative_path in (
                "direct-logs/peer.log",
                "direct-logs/signaling.log",
                "relay-logs/peer.log",
                "relay-logs/signaling.log",
            ):
                write_public_diagnostic(private / relative_path, "PASS")
            write_public_diagnostic(
                private / "relay-logs/turnserver.log",
                "PASS",
                metadata={"version": "4.16.0"},
            )
            public = private / "public"
            build_public_artifact_tree(private, public)

            summary = build_summary(
                root,
                local_public_dir=public,
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit=commit,
            )

        self.assertEqual(summary["schema"], SCHEMA)
        self.assertEqual(summary["result"], "open")
        local = summary["readiness_observations"][0]
        self.assertEqual(local["status"], "pass")
        self.assertTrue(local["current_base"])
        self.assertEqual(local["path"], "private/public")
        self.assertEqual(local["release_gate_impact"], "readiness_only")
        self.assertIn("no_public_internet_path", local["limitations"])
        self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))
        self.assertIn(
            "screencapturekit_to_android_mediacodec",
            {gate["gate"] for gate in summary["release_gates"]},
        )

    def test_local_public_artifacts_are_not_current_base_when_dirty(self) -> None:
        commit = "8" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private"
            private.mkdir(mode=0o700)
            for mode in ("direct", "relay"):
                write_private_text(
                    private / f"{mode}.json",
                    json.dumps(private_product_evidence(mode, commit, dirty=True)),
                )
            for relative_path in (
                "direct-logs/peer.log",
                "direct-logs/signaling.log",
                "relay-logs/peer.log",
                "relay-logs/signaling.log",
            ):
                write_public_diagnostic(private / relative_path, "PASS")
            write_public_diagnostic(
                private / "relay-logs/turnserver.log",
                "PASS",
                metadata={"version": "4.16.0"},
            )
            public = private / "public"
            build_public_artifact_tree(private, public)

            summary = build_summary(
                root,
                local_public_dir=public,
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit=commit,
            )

        local = summary["readiness_observations"][0]
        self.assertEqual(local["status"], "pass")
        self.assertFalse(local["current_base"])
        self.assertEqual(local["release_gate_impact"], "readiness_only")
        self.assertEqual(summary["result"], "open")

    def test_invalid_local_public_artifacts_are_reported_without_closing_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public"
            public.mkdir(mode=0o700)
            unexpected = public / "unexpected.json"
            unexpected.write_text("{}", encoding="utf-8")
            unexpected.chmod(0o600)

            summary = build_summary(
                root,
                local_public_dir=public,
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit="9" * 40,
            )

        local = summary["readiness_observations"][0]
        self.assertEqual(local["status"], "invalid")
        self.assertEqual(local["release_gate_impact"], "none")
        self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))

    def test_historical_android_interop_is_not_current_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance = root / "acceptance.json"
            acceptance.write_text(
                json.dumps(
                    {
                        "result": "pass",
                        "device": {"product": "Nubia P0110", "codename": "pacific"},
                        "routes": ["direct", "relay"],
                        "evidence_boundaries": {
                            "disconnect_reconnect": "not_claimed",
                            "real_display_content": "not_claimed",
                            "screen_capture_kit": "not_claimed",
                            "soak": "not_claimed",
                        },
                        "source": {"commit": "2" * 40},
                        "runs": [
                            {
                                "adb_gate": {"commit": "2" * 40},
                                "assertions": {
                                    "real_android_app_and_instrumentation": "pass",
                                    "real_local_signaling_process": "pass",
                                    "synthetic_video_config_keyframe_delta": "pass",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=acceptance,
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit="3" * 40,
            )

        android = summary["readiness_observations"][1]
        self.assertEqual(android["kind"], "historical_android_local_interop")
        self.assertEqual(android["path"], "acceptance.json")
        self.assertFalse(android["current_base"])
        self.assertTrue(android["run_commits_match_source"])
        self.assertEqual(android["relay_kind"], "forced_local_coturn")
        self.assertEqual(
            android["source_assertions"],
            {
                "real_android_app_and_instrumentation": "pass",
                "real_local_signaling_process": "pass",
                "synthetic_video_config_keyframe_delta": "pass",
            },
        )
        for key, value in HISTORICAL_ANDROID_BOUNDARY_DEFAULTS.items():
            self.assertEqual(android["evidence_boundaries"][key], value)
        self.assertEqual(android["release_gate_impact"], "readiness_only")
        self.assertEqual(summary["result"], "open")

    def test_historical_android_interop_requires_consistent_run_commits_for_current_base(self) -> None:
        commit = "4" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance = root / "acceptance.json"
            acceptance.write_text(
                json.dumps(
                    {
                        "result": "pass",
                        "source": {"commit": commit},
                        "runs": [
                            {"adb_gate": {"commit": commit}},
                            {"adb_gate": {"commit": "5" * 40}},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=acceptance,
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit=commit,
            )

        android = summary["readiness_observations"][1]
        self.assertFalse(android["current_base"])
        self.assertFalse(android["run_commits_match_source"])
        self.assertEqual(android["status"], "invalid")
        self.assertEqual(android["release_gate_impact"], "none")

    def test_historical_android_interop_rejects_public_or_real_media_claims(self) -> None:
        commit = "d" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance = root / "acceptance.json"
            acceptance.write_text(
                json.dumps(
                    {
                        "result": "pass",
                        "device": {"product": "P0110", "codename": "pacific"},
                        "routes": ["direct", "relay"],
                        "evidence_boundaries": {
                            "disconnect_reconnect": "not_claimed",
                            "real_display_content": "claimed",
                            "screen_capture_kit": "claimed",
                            "soak": "not_claimed",
                        },
                        "source": {"commit": commit},
                        "runs": [
                            {
                                "adb_gate": {"commit": commit},
                                "assertions": {
                                    "real_android_app_and_instrumentation": "pass",
                                    "real_local_signaling_process": "pass",
                                    "synthetic_video_config_keyframe_delta": "pass",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=acceptance,
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit=commit,
            )

        android = summary["readiness_observations"][1]
        self.assertEqual(android["status"], "invalid")
        self.assertFalse(android["current_base"])
        self.assertEqual(android["release_gate_impact"], "none")
        self.assertIn("real_display_content", " ".join(android["errors"]))
        self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))

    def test_historical_android_interop_rejects_missing_required_assertions(self) -> None:
        commit = "e" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance = root / "acceptance.json"
            acceptance.write_text(
                json.dumps(
                    {
                        "result": "pass",
                        "device": {"product": "P0110", "codename": "pacific"},
                        "routes": ["direct", "relay"],
                        "evidence_boundaries": {
                            "disconnect_reconnect": "not_claimed",
                            "real_display_content": "not_claimed",
                            "screen_capture_kit": "not_claimed",
                            "soak": "not_claimed",
                        },
                        "source": {"commit": commit},
                        "runs": [{"adb_gate": {"commit": commit}, "assertions": {}}],
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=acceptance,
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_commit=commit,
            )

        android = summary["readiness_observations"][1]
        self.assertEqual(android["status"], "invalid")
        self.assertFalse(android["current_base"])
        self.assertEqual(android["release_gate_impact"], "none")

    def test_blocked_real_media_observation_preserves_blocker_and_false_claims(self) -> None:
        commit = "6" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.json"
            blocked.write_text(
                json.dumps(
                    {
                        "result": "blocked",
                        "source_commit": commit,
                        "source_dirty_before_run": False,
                        "source_matched_origin_main": True,
                        "device": {"product": "P0110", "codename": "pacific"},
                        "blocker": {"component": "macOS Screen Recording permission"},
                        "claims": {
                            "real_capture": False,
                            "real_media_delivery": False,
                            "hardware_decode": False,
                            "internet_or_turn": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=blocked,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][2]
        self.assertEqual(observation["kind"], "current_main_real_media_attempt")
        self.assertTrue(observation["current_base"])
        self.assertEqual(observation["status"], "blocked")
        self.assertTrue(observation["source_clean_before_run"])
        self.assertTrue(observation["source_matched_origin_main"])
        self.assertEqual(observation["release_gate_impact"], "blocked_readiness_only")
        self.assertTrue(all(claim is False for claim in observation["claims"].values()))
        self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))

    def test_current_base_real_media_child_gate_is_observed_without_closing_release(self) -> None:
        commit = "c" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_gate = root / "current-base-real-media.json"
            child_gate.write_text(
                json.dumps(current_base_real_media_gate(commit)),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_base_real_media_gate=child_gate,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][3]
        self.assertEqual(observation["kind"], "current_base_real_media_gate")
        self.assertEqual(observation["status"], "pass")
        self.assertTrue(observation["current_base"])
        self.assertTrue(observation["can_claim_current_base_real_media_continuity"])
        self.assertEqual(observation["release_gate_impact"], "child_gate_only")
        self.assertEqual(summary["result"], "open")
        self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))

    def test_current_base_real_media_child_gate_rejects_wrong_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_gate = root / "current-base-real-media.json"
            child_gate.write_text(
                json.dumps(current_base_real_media_gate("d" * 40)),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_base_real_media_gate=child_gate,
                current_commit="e" * 40,
            )

        observation = summary["readiness_observations"][3]
        self.assertFalse(observation["current_base"])
        self.assertFalse(observation["can_claim_current_base_real_media_continuity"])

    def test_current_base_real_media_child_gate_rejects_incomplete_pass_result(self) -> None:
        commit = "c" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_gate = root / "current-base-real-media.json"
            forged = current_base_real_media_gate(commit)
            forged["checks"] = {
                "current_base_commit": {"passed": True},
                "visible_android_ui": {"passed": True},
                "public_internet_path": {"passed": True},
                "real_capture_first_frame": {"passed": True},
                "videotoolbox_output": {"passed": True},
                "android_mediacodec_decode": {"passed": True},
                "no_synthetic_media": {"passed": True},
            }
            child_gate.write_text(json.dumps(forged), encoding="utf-8")

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=root / "missing-blocked.json",
                current_base_real_media_gate=child_gate,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][3]
        self.assertEqual(observation["status"], "invalid")
        self.assertFalse(observation["current_base"])
        self.assertIn("continuity_passed", " ".join(observation["errors"]))

    def test_current_base_real_media_child_gate_rejects_inconsistent_claim_state(self) -> None:
        cases = (
            current_base_real_media_gate(
                "c" * 40,
                can_claim=False,
                release_gate_effect="child_gate_only",
            ),
            current_base_real_media_gate(
                "c" * 40,
                can_claim=True,
                release_gate_effect="none",
            ),
            current_base_real_media_gate(
                "c" * 40,
                verdict="blocked",
                can_claim=True,
                release_gate_effect="none",
            ),
            current_base_real_media_gate(
                "c" * 40,
                verdict="blocked",
                can_claim=False,
                release_gate_effect="child_gate_only",
            ),
            current_base_real_media_gate(
                "c" * 40,
                checks={"screen_recording_granted": {"passed": False}},
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child_gate = root / "current-base-real-media.json"
                child_gate.write_text(json.dumps(forged), encoding="utf-8")

                summary = build_summary(
                    root,
                    local_public_dir=root / "missing-public",
                    android_interop_acceptance=root / "missing-android.json",
                    blocked_real_media_acceptance=root / "missing-blocked.json",
                    current_base_real_media_gate=child_gate,
                    current_commit="c" * 40,
                )

            observation = summary["readiness_observations"][3]
            self.assertEqual(observation["status"], "invalid")
            self.assertFalse(observation["current_base"])

    def test_blocked_real_media_dirty_source_is_not_current_base(self) -> None:
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.json"
            blocked.write_text(
                json.dumps(
                    {
                        "result": "blocked",
                        "source_commit": commit,
                        "source_dirty_before_run": True,
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=blocked,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][2]
        self.assertFalse(observation["current_base"])
        self.assertFalse(observation["source_clean_before_run"])
        self.assertEqual(observation["status"], "invalid")
        self.assertEqual(observation["release_gate_impact"], "none")

    def test_blocked_real_media_rejects_contradictory_pass_result(self) -> None:
        commit = "f" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.json"
            blocked.write_text(
                json.dumps(
                    {
                        "result": "pass",
                        "source_commit": commit,
                        "source_dirty_before_run": False,
                        "source_matched_origin_main": True,
                        "device": {"product": "P0110", "codename": "pacific"},
                        "blocker": {"component": "macOS Screen Recording permission"},
                        "claims": {
                            "real_capture": False,
                            "real_media_delivery": False,
                            "hardware_decode": False,
                            "internet_or_turn": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=blocked,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][2]
        self.assertEqual(observation["status"], "invalid")
        self.assertFalse(observation["current_base"])
        self.assertEqual(observation["release_gate_impact"], "none")
        self.assertIn("result must be blocked", " ".join(observation["errors"]))

    def test_blocked_real_media_rejects_positive_real_media_claims(self) -> None:
        commit = "1" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked.json"
            blocked.write_text(
                json.dumps(
                    {
                        "result": "blocked",
                        "source_commit": commit,
                        "source_dirty_before_run": False,
                        "source_matched_origin_main": True,
                        "device": {"product": "P0110", "codename": "pacific"},
                        "blocker": {"component": "macOS Screen Recording permission"},
                        "claims": {
                            "real_capture": True,
                            "real_media_delivery": False,
                            "hardware_decode": False,
                            "internet_or_turn": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_summary(
                root,
                local_public_dir=root / "missing-public",
                android_interop_acceptance=root / "missing-android.json",
                blocked_real_media_acceptance=blocked,
                current_commit=commit,
            )

        observation = summary["readiness_observations"][2]
        self.assertEqual(observation["status"], "invalid")
        self.assertFalse(observation["current_base"])
        self.assertEqual(observation["release_gate_impact"], "none")
        self.assertIn("real_capture", " ".join(observation["errors"]))

    def test_summary_observations_never_have_release_gate_pass_impact(self) -> None:
        summary = build_summary(
            ROOT,
            local_public_dir=ROOT / "missing-public",
            android_interop_acceptance=ROOT / "missing-android.json",
            blocked_real_media_acceptance=ROOT / "missing-blocked.json",
            current_commit="7" * 40,
        )

        self.assertEqual(
            {
                observation["release_gate_impact"]
                for observation in summary["readiness_observations"]
            },
            {"none"},
        )

    def test_require_release_pass_exits_nonzero_without_claiming_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.json"
            stderr = io.StringIO()
            with (
                patch(
                    "scripts.phase3.release_gate_summary.git_revision",
                    return_value="b" * 40,
                ),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "--repo",
                        str(ROOT),
                        "--current-commit",
                        "b" * 40,
                        "--local-public-dir",
                        str(Path(directory) / "missing-public"),
                        "--android-interop-acceptance",
                        str(Path(directory) / "missing-android.json"),
                        "--blocked-real-media-acceptance",
                        str(Path(directory) / "missing-blocked.json"),
                        "--output",
                        str(output),
                        "--require-release-pass",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("release gate remains open", stderr.getvalue())
            summary = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(summary["result"], "open")
            self.assertTrue(all(gate["status"] == "open" for gate in summary["release_gates"]))

    def test_current_commit_must_match_checked_out_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with (
                patch(
                    "scripts.phase3.release_gate_summary.git_revision",
                    return_value="a" * 40,
                ),
                redirect_stderr(stderr),
            ):
                exit_code = main(
                    [
                        "--repo",
                        str(ROOT),
                        "--current-commit",
                        "b" * 40,
                        "--local-public-dir",
                        str(Path(directory) / "missing-public"),
                        "--android-interop-acceptance",
                        str(Path(directory) / "missing-android.json"),
                        "--blocked-real-media-acceptance",
                        str(Path(directory) / "missing-blocked.json"),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertIn("does not match the checked-out repository HEAD", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
