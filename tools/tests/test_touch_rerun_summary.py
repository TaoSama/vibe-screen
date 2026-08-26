from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
import io

from vibescreen_evidence.touch_rerun_summary import build_summary, main


PREFLIGHT_READY = {
    "result": "ready",
    "blockers": [],
    "android_device": {
        "adb_serial": "TEST_DEVICE_SERIAL",
        "manufacturer": "nubia",
        "model": "P0110",
        "device": "pacific",
        "device_serial": "TEST_DEVICE_SERIAL",
        "android_release": "16",
        "sdk": 36,
    },
}

INSTRUMENTATION_OK = """INSTRUMENTATION_STATUS: class=dev.telemachus.display.TouchGestureAcceptanceDriverInstrumentedTest
INSTRUMENTATION_RESULT: stream=

Time: 12.345

OK (1 test)


INSTRUMENTATION_CODE: -1
"""

HOST_LOG_OK = """2026-08-20T12:33:25Z Protocol v1 selected for connection epoch 7
2026-08-20T12:33:25Z Starting input receive loop... (touch=on)
2026-08-20T12:33:30Z Touch gesture: right click injected
2026-08-20T12:33:31Z Touch gesture: drag began
2026-08-20T12:33:31Z Touch gesture: drag ended
2026-08-20T12:33:32Z Touch gesture: two-finger scroll began
2026-08-20T12:33:33Z Touch gesture: pinch began
"""

EVENT_TAP_OK = """EVENT_TAP_READY
2.404 type=1 name=leftMouseDown command=false button=0 click=1 wheel1=0 wheel2=0 x=2746.0 y=660.0 flags=0x20000000
2.405 type=2 name=leftMouseUp command=false button=0 click=1 wheel1=0 wheel2=0 x=2746.0 y=660.0 flags=0x20000000
3.456 type=3 name=rightMouseDown command=false button=1 click=1 wheel1=0 wheel2=0 x=2746.0 y=660.0 flags=0x20000000
3.456 type=4 name=rightMouseUp command=false button=1 click=0 wheel1=0 wheel2=0 x=2746.0 y=660.0 flags=0x20000000
4.513 type=6 name=leftMouseDragged command=false button=0 click=1 wheel1=0 wheel2=0 x=2990.4 y=660.0 flags=0x20000000
5.167 type=22 name=scrollWheel command=false button=0 click=0 wheel1=20 wheel2=0 x=2746.0 y=755.0 flags=0x20000000
5.819 type=22 name=scrollWheel command=true button=0 click=0 wheel1=9 wheel2=0 x=2746.0 y=660.0 flags=0x20100000
EVENT_TAP_DONE
"""


class TouchRerunSummaryTests(unittest.TestCase):
    def write_inputs(
        self,
        directory: Path,
        *,
        preflight: dict = PREFLIGHT_READY,
        instrumentation: str = INSTRUMENTATION_OK,
        host_log: str = HOST_LOG_OK,
        event_tap: str = EVENT_TAP_OK,
    ) -> dict[str, Path]:
        paths = {
            "preflight_path": directory / "touch-rerun-preflight.json",
            "instrumentation_path": directory / "touch-gesture-instrumentation.txt",
            "host_log_path": directory / "host-log-touch-gesture-window.log",
            "event_tap_path": directory / "listen-only-event-tap.log",
        }
        paths["preflight_path"].write_text(json.dumps(preflight), encoding="utf-8")
        paths["instrumentation_path"].write_text(instrumentation, encoding="utf-8")
        paths["host_log_path"].write_text(host_log, encoding="utf-8")
        paths["event_tap_path"].write_text(event_tap, encoding="utf-8")
        return paths

    def test_passes_complete_p0110_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self.write_inputs(Path(directory_name))
            summary = build_summary(
                **paths,
                expected_android_manufacturer="nubia",
                expected_android_model="P0110",
                expected_android_device="pacific",
                expected_android_release="16",
                expected_android_sdk=36,
            )

        self.assertEqual(summary["result"], "pass")
        self.assertTrue(summary["can_close_touch_rerun_gate"])
        self.assertEqual(summary["device_scope"], "general_android_substitute")
        self.assertEqual(summary["blockers"], [])
        self.assertEqual(summary["android_device"]["model"], "P0110")
        self.assertNotIn("adb_serial", summary["android_device"])
        self.assertNotIn("device_serial", summary["android_device"])

    def test_blocks_when_preflight_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self.write_inputs(
                Path(directory_name),
                preflight={**PREFLIGHT_READY, "result": "blocked", "blockers": ["missing TCC"]},
            )
            summary = build_summary(**paths)

        self.assertEqual(summary["result"], "blocked")
        self.assertIn("preflight_ready", summary["blockers"])
        self.assertFalse(summary["can_close_touch_rerun_gate"])

    def test_blocks_when_expected_device_identity_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self.write_inputs(Path(directory_name))
            summary = build_summary(
                **paths,
                expected_android_manufacturer="Xiaomi",
                expected_android_model="2211133C",
                expected_android_device="fuxi",
            )

        self.assertEqual(summary["result"], "blocked")
        self.assertIn("expected_android_identity_observed", summary["blockers"])

    def test_blocks_when_host_log_or_event_tap_lacks_required_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self.write_inputs(
                Path(directory_name),
                host_log=HOST_LOG_OK.replace("Touch gesture: pinch began", ""),
                event_tap=EVENT_TAP_OK.replace("name=scrollWheel command=true", "name=scrollWheel command=false"),
            )
            summary = build_summary(**paths)

        self.assertIn("pinch_observed", summary["blockers"])
        self.assertIn("pinch_zoom_event_observed", summary["blockers"])

    def test_cli_writes_blocked_summary_when_input_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "summary.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--preflight",
                        str(directory / "missing-preflight.json"),
                        "--instrumentation",
                        str(directory / "missing-instrumentation.txt"),
                        "--host-log",
                        str(directory / "missing-host.log"),
                        "--event-tap",
                        str(directory / "missing-event-tap.log"),
                        "--output",
                        str(output),
                    ]
                )
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["result"], "blocked")
        self.assertFalse(summary["can_close_touch_rerun_gate"])
        self.assertIn("could not read", stderr.getvalue())

    def test_cli_writes_blocked_summary_for_incomplete_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            paths = self.write_inputs(
                directory,
                host_log=HOST_LOG_OK.replace("Touch gesture: pinch began", ""),
            )
            output = directory / "summary.json"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--preflight",
                        str(paths["preflight_path"]),
                        "--instrumentation",
                        str(paths["instrumentation_path"]),
                        "--host-log",
                        str(paths["host_log_path"]),
                        "--event-tap",
                        str(paths["event_tap_path"]),
                        "--output",
                        str(output),
                    ]
                )
            summary = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertEqual(summary["result"], "blocked")
        self.assertIn("pinch_observed", summary["blockers"])


if __name__ == "__main__":
    unittest.main()
