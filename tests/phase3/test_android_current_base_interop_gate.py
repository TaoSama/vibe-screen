from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.android_current_base_interop_gate import (
    GateError,
    evaluate,
    main,
    validate_report,
)


CURRENT_COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
HISTORICAL_COMMIT = "597518f948075e396352bc353afcec01a30303f3"
PRODUCT_BOUNDARIES = {
    "ui": "pairing_strict_signed_lease_import_local_revoke_repair_only_no_negative_lease_ui_case",
    "screen_capture_kit": "not_claimed",
    "real_display_content": "not_claimed",
    "android_mediacodec_decode": "not_claimed",
    "rotation": "open_harness_has_no_rotation_assertion",
    "disconnect_reconnect": "not_claimed",
    "revocation_repair": "local_android_keystore_and_profile_store_only",
    "soak": "not_claimed",
}
REAL_CAPTURE_BOUNDARIES = {
    **PRODUCT_BOUNDARIES,
    "real_screen_capture": "pass",
    "screen_capture_kit": "pass",
    "real_display_content": "pass",
    "videotoolbox_output": "pass",
    "android_mediacodec_decode": "pass",
    "mediacodec_first_output_frame": "pass",
    "continuous_fps_and_decode_latency": "pass",
    "disconnect_reconnect": "pass",
}
PUBLIC_BOUNDARIES = {
    **REAL_CAPTURE_BOUNDARIES,
    "public_internet_path": "pass",
    "public_nat_or_remote_turn": "pass",
}


def adb_gate(*, commit: str = CURRENT_COMMIT, tag: str = "same-lease") -> dict[str, object]:
    return {
        "schema": "dev.vibescreen.adb-lease-gate/v1",
        "run_id": "android-internet-test-run",
        "records": 48,
        "expected_records_per_adb_subprocess": 2,
        "owner_matches_initial": True,
        "pid": 12345,
        "task": "phase3-android-internet-acceptance",
        "commit": commit,
        "filesystem_device": 16777234,
        "inode": 134017315,
        "content_bytes": 171,
        "content_matches_initial": True,
        "lease_comparison_tag": tag,
    }


def route_report(route: str, *, commit: str = CURRENT_COMMIT) -> dict[str, object]:
    assertions = {
        "real_android_app_and_instrumentation": "pass",
        "real_local_signaling_process": "pass",
        "caller_managed_reachable_coturn_route": "pass" if route == "relay" else "not_exercised",
        "selected_route": "pass",
        "protocol_v1": "pass",
        "aes_256_gcm_control": "pass",
        "aes_256_gcm_media": "pass",
        "synthetic_video_config_keyframe_delta": "pass",
        "authenticated_touch": "pass",
        "durable_security_state": "not_claimed_interop_uses_test_isolated_store",
        "internet_ui_pairing_and_strict_signed_lease_import": "pass",
        "local_revoke_and_repair": "pass",
        "secure_credential_dialogs": "pass",
    }
    return {
        "schema": "dev.vibescreen.phase3-android-product-interop/v1",
        "result": "pass",
        "route": route,
        "source": {"commit": commit},
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": 36,
        },
        "assertions": assertions,
        "adb_gate": adb_gate(commit=commit),
        "evidence_boundaries": {
            **PRODUCT_BOUNDARIES,
        },
    }


def combined_report(*, commit: str = CURRENT_COMMIT) -> dict[str, object]:
    return {
        "schema": "dev.vibescreen.phase3-android-product-interop-combined/v1",
        "result": "pass",
        "routes": ["direct", "relay"],
        "source": {"commit": commit},
        "device": {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_version": "16",
            "sdk": 36,
        },
        "same_device_lease_holder": True,
        "runs": [route_report("direct", commit=commit), route_report("relay", commit=commit)],
        "evidence_boundaries": {
            **PRODUCT_BOUNDARIES,
        },
    }


class AndroidCurrentBaseInteropGateTests(unittest.TestCase):
    def test_withdrawn_marker_is_blocked(self) -> None:
        report = {
            "schema": "dev.vibescreen.phase3-android-interop/v1",
            "result": "withdrawn",
            "source_commit": None,
        }
        with self.assertRaisesRegex(GateError, "withdrawn"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_local_webrtc_loopback_is_not_android_interop(self) -> None:
        report = {
            "schema": "dev.vibescreen.phase3-webrtc-e2e/v1",
            "result": "pass",
            "source": {"commit": CURRENT_COMMIT},
        }
        with self.assertRaisesRegex(GateError, "loopback"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_historical_p0110_report_is_blocked_by_source_commit(self) -> None:
        with self.assertRaisesRegex(GateError, "current-base commit"):
            validate_report(
                combined_report(commit=HISTORICAL_COMMIT),
                expected_commit=CURRENT_COMMIT,
                profile="product-interop",
            )

    def test_product_interop_profile_accepts_current_direct_and_relay_subset(self) -> None:
        accepted = validate_report(
            combined_report(),
            expected_commit=CURRENT_COMMIT,
            profile="product-interop",
        )
        self.assertEqual(accepted, CURRENT_COMMIT)

    def test_product_interop_rejects_extra_real_or_public_pass_assertions(self) -> None:
        for assertion in (
            "screen_capture_kit",
            "android_mediacodec_decode",
            "public_internet_path",
            "public_nat_or_remote_turn",
            "soak",
        ):
            with self.subTest(assertion=assertion):
                report = combined_report()
                report["runs"][0]["assertions"][assertion] = "pass"  # type: ignore[index]
                with self.assertRaisesRegex(GateError, "must not claim pass"):
                    validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_product_interop_rejects_extra_real_world_boundary_pass_claims(self) -> None:
        for boundary in (
            "screen_capture_kit",
            "android_mediacodec_decode",
            "public_internet_path",
            "soak",
            "rotation",
            "disconnect_reconnect",
            "revocation_repair",
            "ui",
        ):
            with self.subTest(boundary=boundary):
                report = combined_report()
                report["evidence_boundaries"][boundary] = "pass"  # type: ignore[index]
                with self.assertRaisesRegex(GateError, "product-interop boundary"):
                    validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_product_interop_blocks_missing_android_mediacodec_boundary(self) -> None:
        report = combined_report()
        del report["evidence_boundaries"]["android_mediacodec_decode"]  # type: ignore[index]
        with self.assertRaisesRegex(
            GateError,
            "boundary must keep non-product proof open: android_mediacodec_decode",
        ):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_single_route_report_is_not_a_current_base_replacement(self) -> None:
        with self.assertRaisesRegex(GateError, "combined direct and relay"):
            validate_report(
                route_report("direct"),
                expected_commit=CURRENT_COMMIT,
                profile="product-interop",
            )

    def test_combined_report_requires_exactly_one_direct_and_one_relay_route(self) -> None:
        report = combined_report()
        report["runs"] = [route_report("direct"), route_report("direct")]
        with self.assertRaisesRegex(GateError, "duplicate route"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

        report = combined_report()
        report["runs"] = [route_report("direct"), route_report("relay"), route_report("direct")]
        with self.assertRaisesRegex(GateError, "exactly two route"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_combined_report_compares_direct_and_relay_adb_lease_identity(self) -> None:
        report = combined_report()
        report["runs"][1]["adb_gate"]["lease_comparison_tag"] = "different-lease"  # type: ignore[index]
        with self.assertRaisesRegex(GateError, "same adb lease identity"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_correct_commit_wrong_device_identity_is_blocked(self) -> None:
        report = combined_report()
        report["device"]["model"] = "2211133C"  # type: ignore[index]
        report["runs"][0]["device"]["model"] = "2211133C"  # type: ignore[index]
        with self.assertRaisesRegex(GateError, "nubia P0110"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="product-interop")

    def test_product_interop_subset_does_not_close_real_capture_profile(self) -> None:
        with self.assertRaisesRegex(GateError, "real-capture profile requires"):
            validate_report(
                combined_report(),
                expected_commit=CURRENT_COMMIT,
                profile="real-capture",
            )

    def test_real_capture_profile_requires_android_mediacodec_and_public_profile_requires_public_route(self) -> None:
        report = combined_report()
        report["evidence_boundaries"] = copy.deepcopy(REAL_CAPTURE_BOUNDARIES)
        for item in report["runs"]:  # type: ignore[index]
            item["assertions"].update(  # type: ignore[index]
                {
                    "real_screen_capture": "pass",
                    "screen_capture_kit": "pass",
                    "videotoolbox_output": "pass",
                    "android_mediacodec_decode": "pass",
                    "mediacodec_first_output_frame": "pass",
                    "continuous_fps_and_decode_latency": "pass",
                    "disconnect_reconnect": "pass",
                }
            )
            item["evidence_boundaries"] = copy.deepcopy(REAL_CAPTURE_BOUNDARIES)  # type: ignore[index]
        validate_report(report, expected_commit=CURRENT_COMMIT, profile="real-capture")
        with self.assertRaisesRegex(GateError, "public_internet_path"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="public-internet")

    def test_real_capture_profile_requires_boundaries_matching_required_assertions(self) -> None:
        report = combined_report()
        report["evidence_boundaries"] = copy.deepcopy(REAL_CAPTURE_BOUNDARIES)
        report["evidence_boundaries"]["disconnect_reconnect"] = "not_claimed"  # type: ignore[index]
        for item in report["runs"]:  # type: ignore[index]
            item["assertions"].update(  # type: ignore[index]
                {
                    "real_screen_capture": "pass",
                    "screen_capture_kit": "pass",
                    "videotoolbox_output": "pass",
                    "android_mediacodec_decode": "pass",
                    "mediacodec_first_output_frame": "pass",
                    "continuous_fps_and_decode_latency": "pass",
                    "disconnect_reconnect": "pass",
                }
            )
            item["evidence_boundaries"] = copy.deepcopy(REAL_CAPTURE_BOUNDARIES)  # type: ignore[index]
        with self.assertRaisesRegex(GateError, "disconnect_reconnect=pass"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="real-capture")

    def test_public_internet_profile_requires_public_boundaries_matching_assertions(self) -> None:
        report = combined_report()
        report["evidence_boundaries"] = copy.deepcopy(PUBLIC_BOUNDARIES)
        report["evidence_boundaries"]["public_nat_or_remote_turn"] = "not_claimed"  # type: ignore[index]
        for item in report["runs"]:  # type: ignore[index]
            item["assertions"].update(  # type: ignore[index]
                {
                    "real_screen_capture": "pass",
                    "screen_capture_kit": "pass",
                    "videotoolbox_output": "pass",
                    "android_mediacodec_decode": "pass",
                    "mediacodec_first_output_frame": "pass",
                    "continuous_fps_and_decode_latency": "pass",
                    "disconnect_reconnect": "pass",
                    "public_internet_path": "pass",
                    "public_nat_or_remote_turn": "pass",
                }
            )
            item["evidence_boundaries"] = copy.deepcopy(PUBLIC_BOUNDARIES)  # type: ignore[index]
        with self.assertRaisesRegex(GateError, "public_nat_or_remote_turn=pass"):
            validate_report(report, expected_commit=CURRENT_COMMIT, profile="public-internet")

    def test_cli_writes_blocked_result_for_checked_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "historical.json"
            output = Path(directory) / "gate.json"
            evidence.write_text(json.dumps(combined_report(commit=HISTORICAL_COMMIT)), encoding="utf-8")
            result = evaluate(evidence, expected_commit=CURRENT_COMMIT, profile="product-interop")
            self.assertEqual(result.result, "blocked")
            self.assertIn("current-base commit", result.reasons[0])
            output.write_text(json.dumps(result.to_json(), sort_keys=True), encoding="utf-8")
            self.assertEqual(json.loads(output.read_text())["result"], "blocked")

    def test_cli_requires_clean_worktree_when_expected_commit_is_not_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True, text=True)
            current = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            tracked.write_text("dirty\n", encoding="utf-8")

            evidence = Path(directory) / "evidence.json"
            output = Path(directory) / "gate.json"
            evidence.write_text(json.dumps(combined_report(commit=current)), encoding="utf-8")

            status = main(["--repo", str(repo), "--evidence", str(evidence), "--output", str(output)])

            self.assertEqual(status, 1)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["result"], "blocked")
            self.assertIn("worktree is not clean", written["reasons"][0])


if __name__ == "__main__":
    unittest.main()
