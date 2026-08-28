from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence.adb import ADBClient
from vibescreen_evidence.usb_live_smoke import (
    DIAG_LOG_COMMAND,
    LOGCAT_TAGS,
    DeviceLockError,
    build_lock_blocked_document,
    collect_usb_live_smoke,
    enforce_device_lock_policy,
    filter_logcat_by_pids,
    label_guard,
    parse_adb_reverse,
    parse_decoder_summary,
    parse_foreground_state,
    parse_package_metadata,
    parse_pids,
    parse_telemetry_summary,
)


LOGCAT_SAMPLE = """\
08-20 18:00:56.419 29380   670 I VibeScreenTelemetry: {"schema_version":1,"timestamp_ms":1787220056419,"event":"connection_opened","host":"127.0.0.1","port":54321,"session_epoch":1}
08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats","session_epoch":1,"fps":60.0,"mbps":35.2}
08-20 18:00:58.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats","session_epoch":1,"fps":59.8,"mbps":34.9}
08-20 18:00:56.447 29380   686 D VD      : setupDecoder: 2000x1200, decoder=c2.qti.hevc.decoder
08-20 18:00:56.569 29380   702 D VD      : First output frame! size=1, flags=1
08-20 18:00:57.468 29380   670 D VD      : Decode stats: input=60, output=59, dropped=0, availBufs=10
08-20 18:00:57.472 29380   702 D VD      : Output #60: decoder latency avg=6.1ms max=30.0ms over 60 samples, input bufs avail=10, dropped=0
"""

WINDOW_SAMPLE = """\
  mCurrentFocus=Window{48b4735 u0 dev.telemachus.display/dev.telemachus.display.MainActivity}
  mFocusedApp=ActivityRecord{12376650 u0 dev.telemachus.display/.MainActivity t349}
"""

ACTIVITY_SAMPLE = """\
  topResumedActivity=ActivityRecord{12376650 u0 dev.telemachus.display/.MainActivity t349}
"""


class ParserTests(unittest.TestCase):
    def test_parse_adb_reverse_matches_expected_port(self):
        result = parse_adb_reverse("UsbFfs tcp:54321 tcp:54321\n")
        self.assertTrue(result["present"])
        self.assertEqual(result["entry"], "UsbFfs tcp:54321 tcp:54321")

    def test_parse_adb_reverse_absent(self):
        result = parse_adb_reverse("")
        self.assertFalse(result["present"])
        self.assertIsNone(result["entry"])

    def test_parse_pids(self):
        self.assertEqual(parse_pids("29380"), [29380])
        self.assertEqual(parse_pids(""), [])

    def test_parse_foreground_state_detects_package(self):
        result = parse_foreground_state(WINDOW_SAMPLE, ACTIVITY_SAMPLE, "dev.telemachus.display")
        self.assertTrue(result["foreground"])
        self.assertEqual(result["foreground_package"], "dev.telemachus.display")

    def test_parse_foreground_state_prefers_matching_package_component(self):
        result = parse_foreground_state(
            "mCurrentFocus=Window{u0 com.android.systemui/.Other}\n",
            ACTIVITY_SAMPLE,
            "dev.telemachus.display",
        )

        self.assertTrue(result["foreground"])
        self.assertEqual(result["foreground_package"], "dev.telemachus.display")

    def test_parse_foreground_state_absent(self):
        result = parse_foreground_state("mCurrentFocus=Window{... com.other/.Other}", "", "dev.telemachus.display")
        self.assertFalse(result["foreground"])

    def test_parse_package_metadata(self):
        output = "  versionName=0.0.0\n  versionCode=100000\n  firstInstallTime=2026-08-20\n  lastUpdateTime=2026-08-20\n"
        result = parse_package_metadata(output, "dev.telemachus.display")
        self.assertTrue(result["installed"])
        self.assertEqual(result["version_name"], "0.0.0")
        self.assertEqual(result["version_code"], 100000)

    def test_parse_telemetry_summary(self):
        result = parse_telemetry_summary(LOGCAT_SAMPLE)
        self.assertEqual(result["event_counts"]["connection_opened"], 1)
        self.assertEqual(result["stream_stats"]["count"], 2)
        self.assertEqual(result["stream_stats"]["fps_max"], 60.0)
        self.assertEqual(result["stream_stats"]["positive_fps_count"], 2)
        self.assertEqual(result["connection"]["opened_count"], 1)

    def test_parse_telemetry_summary_counts_missing_or_non_positive_fps(self):
        result = parse_telemetry_summary(
            'I VibeScreenTelemetry: {"event":"stream_stats"}\n'
            'I VibeScreenTelemetry: {"event":"stream_stats","fps":0}\n'
            'I VibeScreenTelemetry: {"event":"stream_stats","fps":-1}\n'
        )

        self.assertEqual(result["stream_stats"]["count"], 3)
        self.assertEqual(result["stream_stats"]["positive_fps_count"], 0)
        self.assertEqual(result["stream_stats"]["non_positive_fps_count"], 2)

    def test_parse_decoder_summary(self):
        result = parse_decoder_summary(LOGCAT_SAMPLE)
        self.assertEqual(result["decoder"], "c2.qti.hevc.decoder")
        self.assertEqual(result["video_size"], {"width": 2000, "height": 1200})
        self.assertTrue(result["first_output_frame_observed"])
        self.assertEqual(result["latest_output_counter"], 60)
        self.assertEqual(result["max_reported_dropped"], 0)

    def test_decoder_counters_are_enough_when_startup_lines_rolled_out(self):
        result = parse_decoder_summary(
            "08-20 D VD: Decode stats: input=646320, output=646319, dropped=0, availBufs=10\n"
            "08-20 D VD: Output #646320: decoder latency avg=5.0ms max=8.3ms "
            "over 60 samples, input bufs avail=10, dropped=0\n"
        )

        self.assertIsNone(result["decoder"])
        self.assertFalse(result["first_output_frame_observed"])
        self.assertEqual(result["latest_output_counter"], 646320)

    def test_filter_logcat_by_pids_keeps_current_process_lines(self):
        text = (
            '08-20 18:00:57.468 11111   670 I VibeScreenTelemetry: {"event":"stream_stats","fps":60.0}\n'
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"event":"stream_stats","fps":59.8}\n'
            '08-20 18:00:57.468 29380   702 D VD      : Output #60: decoder latency avg=6.1ms max=30.0ms over 60 samples, input bufs avail=10, dropped=0\n'
        )

        filtered = filter_logcat_by_pids(text, [29380])

        self.assertIn("29380", filtered)
        self.assertNotIn("11111", filtered)

    def test_filter_logcat_by_pids_keeps_pidless_lines_only_with_current_pid_context(self):
        text = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"event":"stream_stats","fps":59.8}\n'
            'I VibeScreenTelemetry: {"event":"stream_stats","fps":58.2}\n'
            'D VD      : setupDecoder: 1512x982, decoder=c2.qti.hevc.decoder\n'
            'D VD      : Output #60: decoder latency avg=5.8ms max=31.3ms over 60 samples, input bufs avail=9, dropped=0\n'
            'I OtherTag: unrelated line\n'
        )

        filtered = filter_logcat_by_pids(text, [29380])

        self.assertIn("29380", filtered)
        self.assertIn("c2.qti.hevc.decoder", filtered)
        self.assertIn("Output #60", filtered)
        self.assertNotIn("OtherTag", filtered)
        self.assertLess(filtered.index('"fps":59.8'), filtered.index('"fps":58.2'))

        stale_filtered = filter_logcat_by_pids(text.replace(" 29380 ", " 11111 "), [29380])
        self.assertEqual(stale_filtered, "")

class LabelGuardTests(unittest.TestCase):
    def test_p0110_is_not_fuxi(self):
        identity = {"manufacturer": "nubia", "model": "P0110", "device": "pacific", "product": "pacific"}
        guard = label_guard(identity)
        self.assertFalse(guard["device_is_fuxi"])
        self.assertFalse(guard["recorded_as_fuxi"])
        self.assertTrue(guard["device_is_nubia_p0110_pacific"])
        self.assertIn("Xiaomi 13", guard["do_not_relabel_as"])

    def test_fuxi_is_detected(self):
        identity = {"manufacturer": "Xiaomi", "model": "2211133C", "device": "fuxi", "product": "fuxi"}
        guard = label_guard(identity)
        self.assertTrue(guard["device_is_fuxi"])
        self.assertFalse(guard["recorded_as_fuxi"])

    def test_none_identity_is_not_fuxi(self):
        guard = label_guard(None)
        self.assertFalse(guard["device_is_fuxi"])


class DeviceLockTests(unittest.TestCase):
    def test_lock_blocks_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "device.lock"
            lock.write_text("owner")
            with self.assertRaises(DeviceLockError):
                enforce_device_lock_policy(allow_existing=False, lock_paths=[lock])

    def test_allow_existing_lock_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "device.lock"
            lock.write_text("owner")
            locks = enforce_device_lock_policy(allow_existing=True, lock_paths=[lock])
            self.assertEqual(len(locks), 1)


class CollectionTests(unittest.TestCase):
    @staticmethod
    def _client(responses):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            key = tuple(command[3:]) if len(command) > 3 else tuple(command[2:])
            stdout = responses.get(key, "")
            return subprocess.CompletedProcess(command, 0, stdout, "")

        return ADBClient("EP0110PZ0B9110300B", command_runner=run), commands

    def test_all_adb_commands_include_serial(self):
        responses = {
            ("get-state",): "device",
            ("reverse", "--list"): "UsbFfs tcp:54321 tcp:54321",
            ("shell", "dumpsys", "package", "dev.telemachus.display"): "versionName=0.0.0\nversionCode=1",
            ("shell", "pidof", "dev.telemachus.display"): "29380",
            ("shell", "dumpsys", "window"): WINDOW_SAMPLE,
            ("shell", "dumpsys", "activity", "activities"): ACTIVITY_SAMPLE,
            ("logcat", "-d", "-v", "threadtime", "-t", "1500", "-s", *LOGCAT_TAGS): LOGCAT_SAMPLE,
            ("exec-out", "run-as", "dev.telemachus.display", "sh", "-c", DIAG_LOG_COMMAND): "",
        }
        # identity uses shell getprop
        def identity(self):
            return {"adb_serial": "EP0110PZ0B9110300B", "manufacturer": "nubia", "model": "P0110", "device": "pacific", "product": "pacific", "android_release": "16", "sdk": 36, "build_fingerprint": "nubia/pacific/pacific:16/...", "abi": "arm64-v8a", "device_serial": "EP0110PZ0B9110300B"}

        client, commands = self._client(responses)
        client.identity = lambda: identity(client)
        document = collect_usb_live_smoke(client)
        for command in commands:
            self.assertIn("-s", command)
            self.assertIn("EP0110PZ0B9110300B", command)
        flattened = "\n".join(" ".join(command) for command in commands)
        self.assertNotIn(" force-stop ", flattened)
        self.assertNotIn(" reverse tcp:", flattened)
        self.assertNotIn(" logcat -c", flattened)
        self.assertNotIn(" am start ", flattened)

    def test_recent_decoder_counters_without_startup_lines_can_pass(self):
        logcat = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats",'
            '"session_epoch":1,"fps":58.1,"mbps":32.1}\n'
            "08-20 18:00:57.472 29380   702 D VD      : Output #646320: decoder latency avg=5.0ms max=8.3ms "
            "over 60 samples, input bufs avail=10, dropped=0\n"
        )
        responses = self._passing_responses(logcat)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "pass")
        self.assertEqual(document["logs"]["decoder"]["latest_output_counter"], 646320)
        self.assertFalse(document["logs"]["decoder"]["first_output_frame_observed"])

    def test_current_stream_stats_and_decoder_plain_logs_can_pass(self):
        logcat = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats",'
            '"session_epoch":1,"fps":58.1,"mbps":32.1}\n'
            "08-20 18:00:57.471 29380   686 D VD      : setupDecoder: 1512x982, decoder=c2.qti.hevc.decoder\n"
            "08-20 18:00:57.472 29380   702 D VD      : Output #60: decoder latency avg=5.8ms max=31.3ms "
            "over 60 samples, input bufs avail=9, dropped=0\n"
            "08-20 18:00:57.473 29380   702 D VD      : Decode stats: input=120, output=120, dropped=0, availBufs=9\n"
        )
        responses = self._passing_responses(logcat)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "pass")
        self.assertEqual(document["logs"]["decoder"]["decoder"], "c2.qti.hevc.decoder")
        self.assertEqual(document["logs"]["decoder"]["latest_output_counter"], 60)
        self.assertEqual(document["logs"]["decoder"]["latest_decode_stats"]["output"], 120)
        self.assertEqual(document["logs"]["telemetry"]["stream_stats"]["positive_fps_count"], 1)

    def test_current_stream_stats_and_pidless_decoder_logcat_can_pass(self):
        logcat = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats",'
            '"session_epoch":1,"fps":58.1,"mbps":32.1}\n'
            "D VD      : setupDecoder: 1512x982, decoder=c2.qti.hevc.decoder\n"
            "D VD      : Output #60: decoder latency avg=5.8ms max=31.3ms "
            "over 60 samples, input bufs avail=9, dropped=0\n"
            "D VD      : Decode stats: input=120, output=120, dropped=0, availBufs=9\n"
        )
        responses = self._passing_responses(logcat)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "pass")
        self.assertEqual(document["logs"]["decoder"]["decoder"], "c2.qti.hevc.decoder")
        self.assertEqual(document["logs"]["decoder"]["latest_output_counter"], 60)
        self.assertEqual(document["logs"]["decoder"]["latest_decode_stats"]["output"], 120)

    def test_current_stream_stats_without_decoder_evidence_is_insufficient(self):
        logcat = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats",'
            '"session_epoch":1,"fps":58.1,"mbps":32.1}\n'
        )
        responses = self._passing_responses(logcat)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "insufficient")
        fields = [b["field"] for b in document["blocking_reasons"]]
        self.assertIn("logs.decoder.decoder", fields)
        self.assertIn("logs.decoder.first_output_frame", fields)
        self.assertIn("logs.decoder.counters", fields)

    def test_missing_numeric_positive_fps_is_insufficient(self):
        logcat = (
            '08-20 18:00:57.468 29380   670 I VibeScreenTelemetry: {"schema_version":1,"event":"stream_stats"}\n'
            "08-20 18:00:57.472 29380   702 D VD      : Output #646320: decoder latency avg=5.0ms max=8.3ms "
            "over 60 samples, input bufs avail=10, dropped=0\n"
        )
        responses = self._passing_responses(logcat)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "insufficient")
        fields = [b["field"] for b in document["blocking_reasons"]]
        self.assertIn("logs.telemetry.fps", fields)

    def test_old_pid_and_diag_logs_do_not_prove_current_live_stream(self):
        old_pid_logcat = LOGCAT_SAMPLE.replace(" 29380 ", " 11111 ")
        responses = self._passing_responses(old_pid_logcat)
        responses[("exec-out", "run-as", "dev.telemachus.display", "sh", "-c", DIAG_LOG_COMMAND)] = LOGCAT_SAMPLE
        client, _ = self._client(responses)
        client.identity = self._p0110_identity

        document = collect_usb_live_smoke(client)

        self.assertEqual(document["verdict"], "insufficient")
        self.assertEqual(document["logs"]["live_evidence"]["matched_line_count"], 0)
        self.assertEqual(document["logs"]["diagnostic"]["telemetry"]["stream_stats"]["count"], 2)
        self.assertFalse(document["claims"]["live_usb_stream_observed"])

    def test_pass_when_all_conditions_met(self):
        responses = self._passing_responses(LOGCAT_SAMPLE)
        client, _ = self._client(responses)
        client.identity = self._p0110_identity
        document = collect_usb_live_smoke(client)
        self.assertEqual(document["verdict"], "pass")
        self.assertTrue(document["claims"]["live_usb_stream_observed"])
        self.assertFalse(document["claims"]["readme_gate_closure"])
        self.assertFalse(document["claims"]["can_close_two_hour_soak_gate"])
        self.assertFalse(document["claims"]["can_close_host_rss_no_growth_gate"])
        self.assertFalse(document["claims"]["can_close_latency_gate"])
        self.assertFalse(document["claims"]["can_close_native_pointer_hid_gate"])
        self.assertFalse(document["claims"]["can_close_stylus_gate"])
        self.assertFalse(document["claims"]["can_close_controller_gate"])
        self.assertFalse(document["claims"]["device_is_fuxi"])

    def test_fail_closed_when_reverse_missing(self):
        responses = self._passing_responses(LOGCAT_SAMPLE)
        responses[("reverse", "--list")] = ""
        client, _ = self._client(responses)
        client.identity = self._p0110_identity
        document = collect_usb_live_smoke(client)
        self.assertEqual(document["verdict"], "insufficient")
        fields = [b["field"] for b in document["blocking_reasons"]]
        self.assertIn("adb.reverse", fields)

    @staticmethod
    def _p0110_identity():
        return {
            "adb_serial": "EP0110PZ0B9110300B",
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "product": "pacific",
            "android_release": "16",
            "sdk": 36,
            "build_fingerprint": "nubia/pacific/pacific:16/...",
            "abi": "arm64-v8a",
            "device_serial": "EP0110PZ0B9110300B",
        }

    @staticmethod
    def _passing_responses(logcat: str):
        return {
            ("get-state",): "device",
            ("reverse", "--list"): "UsbFfs tcp:54321 tcp:54321",
            ("shell", "dumpsys", "package", "dev.telemachus.display"): (
                "versionName=0.0.0\nversionCode=1"
            ),
            ("shell", "pidof", "dev.telemachus.display"): "29380",
            ("shell", "dumpsys", "window"): WINDOW_SAMPLE,
            ("shell", "dumpsys", "activity", "activities"): ACTIVITY_SAMPLE,
            ("logcat", "-d", "-v", "threadtime", "-t", "1500", "-s", *LOGCAT_TAGS): logcat,
            ("exec-out", "run-as", "dev.telemachus.display", "sh", "-c", DIAG_LOG_COMMAND): "",
        }

    def test_lock_blocked_document_does_not_run_adb(self):
        locks = [{"path": "/tmp/vibe-screen-device-android.lock"}]
        document = build_lock_blocked_document(
            serial="EP0110PZ0B9110300B",
            package_name="dev.telemachus.display",
            port=54321,
            locks=locks,
        )
        self.assertEqual(document["verdict"], "blocked")
        self.assertEqual(document["configuration"]["logcat_lines"], 1500)
        self.assertEqual(document["configuration"]["max_log_bytes"], 256 * 1024)
        self.assertIn("VibeScreenTelemetry", document["configuration"]["logcat_tags"])
        self.assertFalse(document["safety"]["ran_adb"])
        self.assertFalse(document["claims"]["live_usb_stream_observed"])
        self.assertFalse(document["claims"]["can_close_stylus_gate"])
        self.assertFalse(document["claims"]["can_close_controller_gate"])

    def test_lock_blocked_document_preserves_custom_log_limits(self):
        document = build_lock_blocked_document(
            serial="EP0110PZ0B9110300B",
            package_name="dev.telemachus.display",
            port=54321,
            logcat_lines=321,
            max_log_bytes=4096,
            locks=[],
        )

        self.assertEqual(document["configuration"]["logcat_lines"], 321)
        self.assertEqual(document["configuration"]["max_log_bytes"], 4096)

    def test_schema_rejects_unknown_claim_fields(self):
        schema_path = Path(__file__).parents[1] / "schemas" / "usb-live-smoke.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        claims_schema = schema["properties"]["claims"]

        self.assertFalse(claims_schema["additionalProperties"])
        self.assertIn("can_close_stylus_gate", claims_schema["required"])
        self.assertIn("can_close_controller_gate", claims_schema["required"])
        self.assertEqual(
            claims_schema["properties"]["can_close_stylus_gate"],
            {"const": False},
        )
        self.assertEqual(
            claims_schema["properties"]["can_close_controller_gate"],
            {"const": False},
        )


if __name__ == "__main__":
    unittest.main()
