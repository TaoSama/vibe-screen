import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.reconnect_timing import (
    DISRUPTION_ADB_REVERSE,
    DISRUPTION_CLIENT_KILL,
    DISRUPTION_LAN_NETWORK,
    ReconnectTimingEvidenceError,
    parse_android_diag_events,
    parse_android_logcat_events,
    summarize,
)


MODULE = "vibescreen_evidence.reconnect_timing"


def complete_attempt(disruption: str = DISRUPTION_CLIENT_KILL, transport: str = "usb") -> dict:
    attempt = {
        "name": disruption,
        "disruption": disruption,
        "transport": transport,
        "host_pid_before": 1234,
        "host_pid_after": 1234,
        "host_connection_epoch": 2,
        "android_session_epoch": 1,
        "config_epoch": 1,
        "events": {
            "disruption_started_ms": 10_000,
            "protocol_v1_accepted_ms": 10_600,
            "first_frame_ms": 10_780,
            "first_frame_session_epoch": 1,
            "first_output_frame_ms": 10_830,
            "first_output_frame_session_epoch": 1,
        },
    }
    if disruption == DISRUPTION_ADB_REVERSE:
        attempt["adb_reverse_restored"] = True
    if disruption == DISRUPTION_LAN_NETWORK:
        attempt["trusted_lan_encrypted"] = True
        attempt["trusted_lan_legacy_plaintext"] = False
    return attempt


class ReconnectTimingSummaryTest(unittest.TestCase):
    def test_pass_requires_all_disruption_scenarios(self) -> None:
        summary = summarize(
            {
                "attempts": [
                    complete_attempt(DISRUPTION_CLIENT_KILL, "usb"),
                    complete_attempt(DISRUPTION_ADB_REVERSE, "usb"),
                    complete_attempt(DISRUPTION_LAN_NETWORK, "lan"),
                ]
            },
            run_id="run-pass",
        )

        self.assertEqual(summary["run_id"], "run-pass")
        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_timing_gate"])
        self.assertEqual(summary["missing_required_disruptions"], [])
        self.assertEqual(summary["attempts"][0]["metrics"]["first_output_frame_ms"], 830.0)

    def test_single_scenario_can_be_requested_for_incremental_runs(self) -> None:
        summary = summarize(
            {"attempts": [complete_attempt(DISRUPTION_CLIENT_KILL, "usb")]},
            required_disruptions=[DISRUPTION_CLIENT_KILL],
        )

        self.assertEqual(summary["verdict"], "pass")
        self.assertFalse(summary["can_close_timing_gate"])
        self.assertTrue(summary["can_close_requested_scope"])
        self.assertEqual(summary["required_disruptions"], [DISRUPTION_CLIENT_KILL])
        self.assertEqual(
            set(summary["full_gate_missing_disruptions"]),
            {DISRUPTION_ADB_REVERSE, DISRUPTION_LAN_NETWORK},
        )

    def test_complete_gate_scope_is_reported_separately_from_requested_scope(self) -> None:
        summary = summarize(
            {
                "attempts": [
                    complete_attempt(DISRUPTION_CLIENT_KILL, "usb"),
                    complete_attempt(DISRUPTION_ADB_REVERSE, "usb"),
                    complete_attempt(DISRUPTION_LAN_NETWORK, "lan"),
                ]
            },
            required_disruptions=[DISRUPTION_CLIENT_KILL],
        )

        self.assertEqual(summary["verdict"], "pass")
        self.assertFalse(summary["can_close_timing_gate"])
        self.assertTrue(summary["can_close_requested_scope"])
        self.assertEqual(summary["full_gate_missing_disruptions"], [])

    def test_missing_disruption_keeps_gate_insufficient(self) -> None:
        summary = summarize({"attempts": [complete_attempt(DISRUPTION_CLIENT_KILL, "usb")]})

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_timing_gate"])
        self.assertFalse(summary["can_close_requested_scope"])
        self.assertEqual(
            set(summary["missing_required_disruptions"]),
            {DISRUPTION_ADB_REVERSE, DISRUPTION_LAN_NETWORK},
        )
        self.assertEqual(
            set(summary["full_gate_missing_disruptions"]),
            {DISRUPTION_ADB_REVERSE, DISRUPTION_LAN_NETWORK},
        )

    def test_full_gate_does_not_close_with_incomplete_attempt(self) -> None:
        incomplete_lan = complete_attempt(DISRUPTION_LAN_NETWORK, "lan")
        del incomplete_lan["events"]["first_output_frame_ms"]

        summary = summarize(
            {
                "attempts": [
                    complete_attempt(DISRUPTION_CLIENT_KILL, "usb"),
                    complete_attempt(DISRUPTION_ADB_REVERSE, "usb"),
                    incomplete_lan,
                ]
            }
        )

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertFalse(summary["can_close_timing_gate"])
        self.assertFalse(summary["can_close_requested_scope"])
        self.assertEqual(summary["full_gate_missing_disruptions"], [])

    def test_retry_logs_without_disruption_start_do_not_pass(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        del attempt["events"]["disruption_started_ms"]
        attempt["android_diag"] = "\n".join(
            [
                "[10100] MA: session ended kind=TRANSPORT_CLOSED retryable=true",
                "[10600] SC: Protocol v1 upgrade accepted",
                "[10780] VD: First frame: size=1, keyframe=true",
                "[10830] VD: First output frame! size=1, flags=1",
            ]
        )

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("missing disruption_started_ms", summary["attempts"][0]["reasons"])

    def test_missing_first_output_frame_is_insufficient(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        del attempt["events"]["first_output_frame_ms"]

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("missing first_output_frame_ms", summary["attempts"][0]["reasons"])

    def test_missing_session_epoch_markers_are_insufficient(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        del attempt["events"]["first_frame_session_epoch"]
        del attempt["events"]["first_output_frame_session_epoch"]

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("missing first_frame_session_epoch", summary["attempts"][0]["reasons"])
        self.assertIn("missing first_output_frame_session_epoch", summary["attempts"][0]["reasons"])

    def test_mismatched_session_epoch_markers_are_insufficient(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt["events"]["first_output_frame_session_epoch"] = 2

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn(
            "first_output_frame_session_epoch does not match android_session_epoch",
            summary["attempts"][0]["reasons"],
        )

    def test_slow_first_output_frame_fails(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt["events"]["first_output_frame_ms"] = 13_100

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "fail")
        self.assertIn("exceeds threshold", summary["attempts"][0]["reasons"][0])

    def test_host_pid_change_fails(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt["host_pid_after"] = 5678

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "fail")
        self.assertFalse(summary["attempts"][0]["same_host_pid"])

    def test_adb_reverse_attempt_requires_restored_mapping(self) -> None:
        attempt = complete_attempt(DISRUPTION_ADB_REVERSE, "usb")
        attempt["adb_reverse_restored"] = False

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_ADB_REVERSE])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("adb_reverse_restored", summary["attempts"][0]["reasons"][0])

    def test_adb_reverse_attempt_requires_usb_transport(self) -> None:
        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "requires usb transport"):
            summarize({"attempts": [complete_attempt(DISRUPTION_ADB_REVERSE, "lan")]})

    def test_lan_attempt_requires_lan_transport(self) -> None:
        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "requires lan transport"):
            summarize({"attempts": [complete_attempt(DISRUPTION_LAN_NETWORK, "usb")]})

    def test_lan_attempt_blocks_without_secure_record_markers(self) -> None:
        attempt = complete_attempt(DISRUPTION_LAN_NETWORK, "lan")
        attempt["trusted_lan_encrypted"] = False

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_LAN_NETWORK])

        self.assertEqual(summary["verdict"], "blocked")
        self.assertIn("trusted LAN encrypted", summary["attempts"][0]["blocking_reasons"][0])

    def test_blocked_record_never_closes_gate(self) -> None:
        summary = summarize({"blocked_reasons": ["Host 54321 listener unavailable"]})

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_timing_gate"])
        self.assertEqual(
            set(summary["full_gate_missing_disruptions"]),
            {DISRUPTION_CLIENT_KILL, DISRUPTION_ADB_REVERSE, DISRUPTION_LAN_NETWORK},
        )
        self.assertEqual(
            set(summary["missing_required_disruptions"]),
            {DISRUPTION_CLIENT_KILL, DISRUPTION_ADB_REVERSE, DISRUPTION_LAN_NETWORK},
        )
        self.assertEqual(summary["reasons"], ["Host 54321 listener unavailable"])
        self.assertEqual(
            summary["missing_required_disruptions"],
            summary["required_disruptions"],
        )

    def test_parses_android_diag_after_disruption_start(self) -> None:
        events = parse_android_diag_events(
            "\n".join(
                [
                    "[9000] SC: Protocol v1 upgrade accepted",
                    "[10050] MA: session ended kind=TRANSPORT_CLOSED retryable=true",
                    "[10600] SC: Protocol v1 upgrade accepted",
                    '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":4}',
                    "[10700] MA: onVideoConfiguration: 2000x1200 @ 0° epoch=9",
                    "[10800] VD: First frame: size=1, keyframe=true, session_epoch=4, config_epoch=9",
                    "[10850] VD: First output frame! size=1, flags=1, session_epoch=4",
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["protocol_v1_accepted_ms"], 10_600)
        self.assertEqual(events["android_session_epoch"], 4)
        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_ms"], 10_850)

    def test_parses_android_diag_skips_legacy_first_frame_marker(self) -> None:
        events = parse_android_diag_events(
            "\n".join(
                [
                    '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":4}',
                    "[10700] VD: First frame: size=1, keyframe=true, session_epoch=3, config_epoch=0",
                    "[10750] VD: First output frame! size=1, flags=1",
                    "[10800] VD: First frame: size=1, keyframe=true, session_epoch=4, config_epoch=9",
                    "[10850] VD: First output frame! size=1, flags=1, session_epoch=4",
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_ms"], 10_800)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_ms"], 10_850)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)

    def test_parses_android_diag_skips_zero_epoch_connection_opened(self) -> None:
        events = parse_android_diag_events(
            "\n".join(
                [
                    '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":0}',
                    '[10650] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":4}',
                    "[10800] VD: First frame: size=1, keyframe=true, session_epoch=4, config_epoch=9",
                    "[10850] VD: First output frame! size=1, flags=1, session_epoch=4",
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["android_session_epoch"], 4)
        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)

    def test_parses_android_logcat_telemetry_after_disruption_start(self) -> None:
        events = parse_android_logcat_events(
            "\n".join(
                [
                    '08-21 12:00:00.000 I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":9000,"session_epoch":3,"config_epoch":8}',
                    '08-21 12:00:01.000 I/VibeScreenTelemetry: {"event":"protocol_v1_accepted","timestamp_ms":10600,"session_epoch":4}',
                    '08-21 12:00:01.050 I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10650,"session_epoch":4}',
                    '08-21 12:00:01.200 I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
                    '08-21 12:00:01.250 I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10850,"session_epoch":4}',
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["protocol_v1_accepted_ms"], 10_600)
        self.assertEqual(events["android_session_epoch"], 4)
        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_ms"], 10_800)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_ms"], 10_850)

    def test_parses_android_logcat_skips_legacy_first_frame_marker(self) -> None:
        events = parse_android_logcat_events(
            "\n".join(
                [
                    'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10600,"session_epoch":4}',
                    'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10700,"session_epoch":3,"config_epoch":0}',
                    'I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10750,"session_epoch":0}',
                    'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
                    'I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10850,"session_epoch":4}',
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_ms"], 10_800)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_ms"], 10_850)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)

    def test_parses_android_logcat_skips_zero_epoch_connection_opened(self) -> None:
        events = parse_android_logcat_events(
            "\n".join(
                [
                    'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10600,"session_epoch":0}',
                    'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10650,"session_epoch":4}',
                    'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
                    'I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10850,"session_epoch":4}',
                ]
            ),
            after_ms=10_000,
        )

        self.assertEqual(events["android_session_epoch"], 4)
        self.assertEqual(events["config_epoch"], 9)
        self.assertEqual(events["first_frame_session_epoch"], 4)
        self.assertEqual(events["first_output_frame_session_epoch"], 4)

    def test_logcat_connection_and_first_frame_without_decoder_output_do_not_pass(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt.pop("events")
        attempt["disruption_started_at_ms"] = 10_000
        attempt["android_logcat"] = "\n".join(
            [
                'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10600,"session_epoch":4}',
                'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
            ]
        )

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("missing first_output_frame_ms", summary["attempts"][0]["reasons"])
        self.assertIn("missing first_output_frame_ms", summary["reasons"])

    def test_logcat_connection_opened_does_not_prove_protocol_v1(self) -> None:
        attempt = {
            "name": DISRUPTION_CLIENT_KILL,
            "disruption": DISRUPTION_CLIENT_KILL,
            "transport": "usb",
            "host_pid_before": 1234,
            "host_pid_after": 1234,
            "host_connection_epoch": 2,
            "disruption_started_at_ms": 10_000,
            "android_logcat": "\n".join(
                [
                    'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10600,"session_epoch":4}',
                    'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
                    'I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10850,"session_epoch":4}',
                ]
            ),
        }

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "insufficient")
        self.assertIn("missing protocol_v1_accepted_ms", summary["attempts"][0]["reasons"])

    def test_logcat_only_attempt_passes_with_protocol_v1_acceptance_event(self) -> None:
        attempt = {
            "name": DISRUPTION_CLIENT_KILL,
            "disruption": DISRUPTION_CLIENT_KILL,
            "transport": "usb",
            "host_pid_before": 1234,
            "host_pid_after": 1234,
            "host_connection_epoch": 2,
            "disruption_started_at_ms": 10_000,
            "android_logcat": "\n".join(
                [
                    'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10550,"session_epoch":4}',
                    'I/VibeScreenTelemetry: {"event":"protocol_v1_accepted","timestamp_ms":10600,"session_epoch":4}',
                    'I/VibeScreenTelemetry: {"event":"first_frame_received","timestamp_ms":10800,"session_epoch":4,"config_epoch":9}',
                    'I/VibeScreenTelemetry: {"event":"first_output_frame","timestamp_ms":10850,"session_epoch":4}',
                ]
            ),
        }

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "pass")
        self.assertEqual(summary["attempts"][0]["timestamps_ms"]["protocol_v1_accepted_ms"], 10_600)
        self.assertEqual(summary["attempts"][0]["android_session_epoch"], 4)
        self.assertEqual(summary["attempts"][0]["metrics"]["first_output_frame_ms"], 850.0)

    def test_rejects_mixed_android_diag_and_logcat_timebases(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt["android_diag"] = '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":4}'
        attempt["android_logcat"] = (
            'I/VibeScreenTelemetry: {"event":"connection_opened","timestamp_ms":10600,"session_epoch":4}'
        )

        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "android_diag or android_logcat"):
            summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

    def test_empty_attempt_epoch_fields_fall_back_to_parsed_events(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt.pop("events")
        attempt["host_connection_epoch"] = ""
        attempt["android_session_epoch"] = None
        attempt["config_epoch"] = ""
        attempt["disruption_started_at_ms"] = 10_000
        attempt["host_log"] = "Protocol v1 selected for connection epoch 2"
        attempt["android_diag"] = "\n".join(
            [
                "[10600] SC: Protocol v1 upgrade accepted",
                '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":1}',
                "[10700] MA: onVideoConfiguration: 2000x1200 @ 0° epoch=1",
                "[10800] VD: First frame: size=1, keyframe=true, session_epoch=1, config_epoch=1",
                "[10850] VD: First output frame! size=1, flags=1, session_epoch=1",
            ]
        )

        summary = summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

        self.assertEqual(summary["verdict"], "pass")
        self.assertEqual(summary["attempts"][0]["host_connection_epoch"], 2)
        self.assertEqual(summary["attempts"][0]["android_session_epoch"], 1)
        self.assertEqual(summary["attempts"][0]["config_epoch"], 1)

    def test_relative_log_paths_are_resolved_from_record_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "diag.log").write_text(
                "\n".join(
                    [
                        "[10000] MA: session ended kind=TRANSPORT_CLOSED retryable=true",
                        "[10600] SC: Protocol v1 upgrade accepted",
                        '[10600] VibeScreenTelemetry: {"event":"connection_opened","session_epoch":1}',
                        "[10700] MA: onVideoConfiguration: 2000x1200 @ 0° epoch=1",
                        "[10800] VD: First frame: size=1, keyframe=true, session_epoch=1, config_epoch=1",
                        "[10850] VD: First output frame! size=1, flags=1, session_epoch=1",
                    ]
                ),
                encoding="utf-8",
            )
            record = {
                "attempts": [
                    {
                        "disruption": DISRUPTION_CLIENT_KILL,
                        "transport": "usb",
                        "host_pid_before": 1234,
                        "host_pid_after": 1234,
                        "host_connection_epoch": 2,
                        "disruption_started_at_ms": 10_000,
                        "android_diag_path": "diag.log",
                    }
                ]
            }

            summary = summarize(
                record,
                required_disruptions=[DISRUPTION_CLIENT_KILL],
                base_dir=root,
            )

            self.assertEqual(summary["verdict"], "pass")
            self.assertEqual(summary["attempts"][0]["metrics"]["first_output_frame_ms"], 850.0)

    def test_rejects_unknown_disruption(self) -> None:
        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "attempt disruption"):
            summarize({"attempts": [{"disruption": "ordinary-log", "transport": "usb"}]})

    def test_rejects_boolean_timestamps(self) -> None:
        attempt = complete_attempt(DISRUPTION_CLIENT_KILL, "usb")
        attempt["events"]["first_output_frame_ms"] = True

        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "first_output_frame_ms"):
            summarize({"attempts": [attempt]}, required_disruptions=[DISRUPTION_CLIENT_KILL])

    def test_rejects_non_finite_threshold(self) -> None:
        with self.assertRaisesRegex(ReconnectTimingEvidenceError, "threshold_ms"):
            summarize({"attempts": [complete_attempt()]}, threshold_ms=float("nan"))


class ReconnectTimingCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", MODULE, *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_passes_single_requested_scenario(self) -> None:
        result = self.run_cli(
            "-",
            "--require-disruption",
            DISRUPTION_CLIENT_KILL,
            "--run-id",
            "cli-pass",
            stdin=json.dumps({"attempts": [complete_attempt(DISRUPTION_CLIENT_KILL, "usb")]}),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["run_id"], "cli-pass")
        self.assertEqual(output["verdict"], "pass")

    def test_cli_returns_distinct_blocked_exit(self) -> None:
        result = self.run_cli(
            "--blocked",
            "--blocker",
            "codesign identity missing",
            "--target-device",
            "Nubia P0110 / pacific / Android 16 / <redacted-adb-serial>",
        )

        self.assertEqual(result.returncode, 3, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["verdict"], "blocked")
        self.assertFalse(output["can_close_timing_gate"])
        self.assertEqual(output["device"]["target"], "Nubia P0110 / pacific / Android 16 / <redacted-adb-serial>")

    def test_cli_rejects_missing_input(self) -> None:
        result = self.run_cli()

        self.assertEqual(result.returncode, 1)
        self.assertIn("input is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
