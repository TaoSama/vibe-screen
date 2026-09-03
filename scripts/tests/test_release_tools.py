from __future__ import annotations

import hashlib
import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webrtc_m150_notices import NOTICE_RELATIVE_PATH, validate_notice_bundle
import generate_webrtc_m150_notices
import harmony_device_gate
import harmony_host_interop_preflight
import package_macos
import prepare_release
import android_stylus_acceptance
from phase3.evidence_privacy import scan_content as scan_phase3_evidence_content
import macos_dev_host
from phase3_webrtc.model import SUPPORTED_COTURN_VERSIONS


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SCRIPT = REPOSITORY_ROOT / "scripts/archive_artifact.py"
PREPARE_SCRIPT = REPOSITORY_ROOT / "scripts/prepare_release.py"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/release.yml"
PHASE0_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/phase0.yml"
IOS_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/ios.yml"
MAKEFILE = REPOSITORY_ROOT / "Makefile"
PHASE3_RUNNER = REPOSITORY_ROOT / "scripts/phase3_webrtc/run_local_e2e.py"
PHASE3_SOURCE_ARTIFACTS = REPOSITORY_ROOT / "scripts/phase3_webrtc/source_artifacts.py"
ANDROID_BUILD = REPOSITORY_ROOT / "baseline/AndroidClient/app/build.gradle.kts"
MAC_HOST_ENTITLEMENTS = REPOSITORY_ROOT / "baseline/MacHost/Telemachus.entitlements"
CURRENT_HOST_LAUNCH_DOCS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "docs/getting-started.md",
    REPOSITORY_ROOT / "docs/testing.md",
)
CURRENT_HOST_LAUNCH_DOC_GLOBS = (
    "docs/runbook/*.md",
    "docs/changes/*/RUNBOOK.md",
    "docs/changes/*/TECH.md",
)
FORBIDDEN_HOST_LAUNCH_LINE_PATTERNS = (
    (
        "direct LaunchServices Host start",
        re.compile(
            r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=.*\s+)*(?:/usr/bin/)?open\b'
            r'(?=.*(?:Vibe Screen|\.build/release-artifacts/Vibe Screen\.app))'
        ),
    ),
    (
        "direct Host executable start",
        re.compile(
            r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=.*\s+)*["\']?'
            r'/Applications/Vibe Screen\.app/Contents/MacOS/Vibe Screen["\']?(?:\s|&|$)'
        ),
    ),
    (
        "direct build-output Host start",
        re.compile(
            r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=.*\s+)*["\']?'
            r'(?:baseline/MacHost/)?\.build/(?:debug|release)/.*Vibe(?:\\ | )Screen'
        ),
    ),
    (
        "direct swift-run Host start",
        re.compile(r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=.*\s+)*swift\s+run\s+["\']?Vibe Screen["\']?'),
    ),
)
OFFLINE_HOST_SELF_TEST_FLAG_PATTERN = re.compile(r'--[A-Za-z0-9-]*self-test\b')
FORBIDDEN_HOST_LAUNCH_SCRIPT_PATTERNS = (
    (
        "direct LaunchServices Host start",
        re.compile(
            r'["\'](?:/usr/bin/)?open["\'][^\n]*'
            r'(?:Vibe Screen|\.build/release-artifacts/Vibe Screen\.app)'
        ),
    ),
    (
        "direct Host executable start",
        re.compile(
            r'(?:subprocess\.|run_command\(|run\()[^\n]*'
            r'/Applications/Vibe Screen\.app/Contents/MacOS/Vibe Screen'
        ),
    ),
)
VERSION = "1.2.3"
TAG = f"v{VERSION}"
COMMIT = "a" * 40
CREATED = "2026-08-05T10:00:00+08:00"


def workflow_job_body(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"missing workflow job {job_name!r}")
    return match.group("body")


def workflow_job_timeout(workflow: str, job_name: str) -> int:
    body = workflow_job_body(workflow, job_name)
    match = re.search(r"(?m)^    timeout-minutes: ([0-9]+)$", body)
    if match is None:
        raise AssertionError(f"missing job-level timeout for {job_name!r}")
    return int(match.group(1))


class AndroidStylusAcceptanceTests(unittest.TestCase):
    def test_dumpsys_parser_finds_stylus_axes_and_buttons(self) -> None:
        devices = android_stylus_acceptance.parse_input_devices(
            """
Input Reader State:
  Device 5: goodix_stylus_input
    Descriptor: abc123
    Sources: 0x00001002 TOUCHSCREEN
    Motion Ranges:
      Motion Range: X source=0x00001002 min=0.0 max=1440.0 flat=0.0 fuzz=0.0 resolution=0.0
      Motion Range: Y source=0x00001002 min=0.0 max=2880.0 flat=0.0 fuzz=0.0 resolution=0.0
      Motion Range: PRESSURE source=0x00004002 min=0.0 max=1.0 flat=0.0 fuzz=0.0 resolution=0.0
      Motion Range: TILT source=0x00004002 min=0.0 max=1.5708 flat=0.0 fuzz=0.0 resolution=0.0
    Buttons: BUTTON_STYLUS_PRIMARY BUTTON_STYLUS_SECONDARY
  Device 4: goodix_stylus_input
    Sources: KEYBOARD | TOUCHSCREEN | STYLUS
    Motion Ranges:
      PRESSURE: source=TOUCHSCREEN | STYLUS, min=0.000, max=1.000
      ORIENTATION: source=TOUCHSCREEN | STYLUS, min=-3.142, max=3.142
      TILT: source=TOUCHSCREEN | STYLUS, min=0.000, max=1.571
  Device 6: qwerty
    Sources: KEYBOARD
  Device 7: gdix_input_agent
    Sources: KEYBOARD | TOUCHSCREEN
    Motion Ranges:
      PRESSURE: source=TOUCHSCREEN, min=0.000, max=1.000
  BatteryController:
    Device Monitors: 1 monitors
      0: DeviceId=4, Name='goodix_stylus_input', NativeBattery=State{<not present>}
"""
        )

        candidates = android_stylus_acceptance.select_stylus_candidates(devices)

        self.assertEqual(2, len(candidates))
        self.assertEqual("goodix_stylus_input", candidates[0].name)
        self.assertTrue(candidates[0].required_axes_present)
        self.assertFalse(candidates[0].pass_eligible)
        self.assertEqual(("STYLUS_PRIMARY", "STYLUS_SECONDARY"), candidates[0].buttons)
        self.assertEqual(("ORIENTATION", "PRESSURE", "TILT"), candidates[1].axes)
        self.assertTrue(candidates[1].pass_eligible)

    def test_capability_without_physical_observation_stays_blocked(self) -> None:
        args = argparse.Namespace(observed_physical_drawing=False, drawing_observation="", host_log=None)
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=("STYLUS_PRIMARY",),
        )

        self.assertEqual(
            "blocked_physical_stylus_not_observed",
            android_stylus_acceptance.conclusion_status(args, [candidate]),
        )

    def test_required_axes_without_stylus_source_cannot_pass(self) -> None:
        args = argparse.Namespace(observed_physical_drawing=False, drawing_observation="", host_log=None)
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=(),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )

        self.assertEqual(
            "blocked_no_required_stylus_capability",
            android_stylus_acceptance.conclusion_status(args, [candidate]),
        )

    def test_android_dumpsys_redaction_removes_window_tokens(self) -> None:
        redacted = android_stylus_acceptance.redact_android_dumpsys_text(
            "token=0xb400007b62b3a410 applicationInfo.token=<null> "
            "inputChannelToken=android.os.BinderProxy@fb7681c\n"
        )

        self.assertEqual(
            redacted,
            "token=<redacted> applicationInfo.token=<redacted> "
            "inputChannelToken=<redacted>\n",
        )
        self.assertNotIn("BinderProxy@fb7681c", redacted)

    def test_appended_diag_log_rejects_rotated_or_rewritten_logs(self) -> None:
        self.assertEqual(
            "\nnew stylus line",
            android_stylus_acceptance.appended_diag_log("old line", "old line\nnew stylus line"),
        )
        self.assertEqual("new complete log", android_stylus_acceptance.appended_diag_log("", "new complete log"))
        with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "changed or rotated"):
            android_stylus_acceptance.appended_diag_log("old line", "different log")

    def test_read_new_host_log_rejects_replaced_truncated_or_oversized_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host.log"
            host_log.write_text("old host line\n", encoding="utf-8")
            cursor = android_stylus_acceptance.host_log_cursor(host_log)

            host_log.write_text("old host line\nnew host line\n", encoding="utf-8")
            self.assertEqual("new host line\n", android_stylus_acceptance.read_new_host_log(host_log, cursor, 1024))

            host_log.write_text("short", encoding="utf-8")
            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "truncated"):
                android_stylus_acceptance.read_new_host_log(host_log, cursor, 1024)

            replacement = Path(temporary_directory) / "replacement.log"
            replacement.write_text("old host line\nnew host line\n", encoding="utf-8")
            replacement.replace(host_log)
            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "identity changed"):
                android_stylus_acceptance.read_new_host_log(host_log, cursor, 1024)

            refreshed_cursor = android_stylus_acceptance.host_log_cursor(host_log)
            host_log.write_text("old host line\nnew host line\nexcess\n", encoding="utf-8")
            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "above limit"):
                android_stylus_acceptance.read_new_host_log(host_log, refreshed_cursor, 1)

    def test_host_log_cursor_reports_stat_errors_as_evidence_errors(self) -> None:
        host_log = mock.Mock(spec=Path)
        host_log.stat.side_effect = OSError("permission denied")

        with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "cannot stat host log"):
            android_stylus_acceptance.host_log_cursor(host_log)

    def test_main_reports_missing_host_log_before_adb_for_observed_drawing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "evidence"
            with mock.patch.object(android_stylus_acceptance, "describe_device_locks", return_value=[]):
                with mock.patch.object(android_stylus_acceptance, "check_device_locks", return_value=[]):
                    with mock.patch.object(android_stylus_acceptance, "adb") as adb_mock:
                        with mock.patch.object(sys, "stderr") as stderr:
                            result = android_stylus_acceptance.main([
                                "--adb",
                                "adb",
                                "--serial",
                                "DEVICE_SERIAL",
                                "--observed-physical-drawing",
                                "--drawing-observation",
                                "physical stylus produced visible ink",
                                "--output-dir",
                                str(output_dir),
                            ])

        self.assertEqual(2, result)
        adb_mock.assert_not_called()
        self.assertIn("error: --host-log is required", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_main_writes_lock_blocked_evidence_without_adb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "evidence"
            lock_details = [{"path": "/tmp/vibe-screen-device-android.lock", "detail": "owned"}]
            with mock.patch.object(android_stylus_acceptance, "describe_device_locks", return_value=lock_details):
                with mock.patch.object(android_stylus_acceptance, "adb") as adb_mock:
                    result = android_stylus_acceptance.main([
                        "--adb",
                        "adb",
                        "--serial",
                        "DEVICE_SERIAL",
                        "--output-dir",
                        str(output_dir),
                        "--write-blocked-on-lock",
                    ])

            self.assertEqual(2, result)
            adb_mock.assert_not_called()
            evidence = json.loads((output_dir / "stylus-evidence.json").read_text(encoding="utf-8"))
            summary = json.loads((output_dir / "stylus-summary.json").read_text(encoding="utf-8"))
            self.assertEqual("blocked_device_coordination_lock", evidence["status"])
            self.assertFalse(summary["observations"]["adb_was_run"])
            self.assertNotIn("dumpsys-input.txt", summary["artifact_paths"])
            self.assertFalse((output_dir / "dumpsys-input.txt").exists())

    def test_passing_status_requires_host_log_and_observation(self) -> None:
        args = argparse.Namespace(observed_physical_drawing=True, drawing_observation="", host_log=None)
        with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "drawing-observation"):
            android_stylus_acceptance.conclusion_status(args, [])

    def test_write_evidence_records_host_log_name_without_absolute_path(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "evidence"
            host_log = root / "Users" / "operator" / "Library" / "Logs" / "Telemachus" / "telemachus.log"
            host_log.parent.mkdir(parents=True)
            host_log.write_text("old host line\n", encoding="utf-8")
            args = argparse.Namespace(
                host_log=host_log,
                observed_physical_drawing=True,
                observe_seconds=0,
                drawing_observation="physical stylus produced visible ink",
            )

            android_stylus_acceptance.write_evidence(
                output_dir,
                args,
                [],
                {},
                "Input Reader State:\n",
                [candidate],
                "",
                None,
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                "pass",
            )

            summary = json.loads((output_dir / "stylus-evidence.json").read_text(encoding="utf-8"))
            gate_summary = json.loads((output_dir / "stylus-summary.json").read_text(encoding="utf-8"))

        self.assertEqual("telemachus.log", summary["host_log_name"])
        self.assertEqual(summary["run_id"], gate_summary["run_id"])
        self.assertNotIn("host_log", summary)
        self.assertNotIn("operator", json.dumps(summary))

    def test_write_evidence_normalizes_dumpsys_artifact_whitespace(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        args = argparse.Namespace(
            host_log=Path("host-stylus.log"),
            observed_physical_drawing=True,
            observe_seconds=0,
            drawing_observation="physical stylus produced visible ink",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "evidence"

            android_stylus_acceptance.write_evidence(
                output_dir,
                args,
                [],
                {},
                "Input Reader State:  \n  UniqueId:  \n",
                [candidate],
                "Stylus forwarded: samples=1 extended=true rawSource=0x4002 rawAction=2 rawTools=[stylus] phase=INPUT_PHASE_CHANGED contact=contact tool=pen buttons=0 pressure=0.5 tiltX=1 tiltY=-1  \n",
                None,
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0  \n",
                "pass",
            )

            dumpsys_text = (output_dir / "dumpsys-input.txt").read_text(encoding="utf-8")
            self.assertTrue(dumpsys_text.endswith("\n"))
            self.assertFalse(any(line.endswith(" ") for line in dumpsys_text.splitlines()))
            self.assertIn("tiltY=-1  ", (output_dir / "android-diag.log").read_text(encoding="utf-8"))
            self.assertIn("tiltY=-45.0  ", (output_dir / "host-stylus.log").read_text(encoding="utf-8"))

    def test_write_evidence_redacts_raw_artifact_secrets(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        args = argparse.Namespace(
            host_log=Path("host-stylus.log"),
            observed_physical_drawing=True,
            observe_seconds=0,
            drawing_observation="physical stylus produced visible ink",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "evidence"
            sample_ip = ".".join(["192", "168", "1", "20"])
            sample_db_url = "post" + "gres://" + "user:pass@host/database"
            sample_prod_db_url = "post" + "gres://" + "user:pass@host/prod"
            sample_channel_token = "android.os." + "Binder" + "Proxy@55c37ef"

            android_stylus_acceptance.write_evidence(
                output_dir,
                args,
                [],
                {},
                (
                    f"applicationInfo.token=abc123 token=def456 {sample_db_url}\n"
                    f"inputChannelToken={sample_channel_token} {sample_prod_db_url}\n"
                ),
                [candidate],
                f"SC: Connected to {sample_ip}:54321 token=diag-token\n",
                None,
                "Stylus injected: input=1 token=host-token key=host-secret\n",
                "pass",
            )

            dumpsys_text = (output_dir / "dumpsys-input.txt").read_text(encoding="utf-8")
            diag_text = (output_dir / "android-diag.log").read_text(encoding="utf-8")
            host_text = (output_dir / "host-stylus.log").read_text(encoding="utf-8")

        self.assertIn("applicationInfo.token=<redacted-token>", dumpsys_text)
        self.assertIn("token=<redacted-secret>", dumpsys_text)
        self.assertIn("inputChannelToken=<redacted-secret>", dumpsys_text)
        self.assertIn("<redacted-db-url>", dumpsys_text)
        self.assertIn("<redacted-ip>", diag_text)
        self.assertIn("token=<redacted-secret>", diag_text)
        self.assertIn("token=<redacted-secret>", host_text)
        self.assertIn("key=<redacted-secret>", host_text)
        self.assertNotIn(sample_ip, diag_text)
        self.assertNotIn("abc123", dumpsys_text)
        self.assertNotIn(sample_db_url, dumpsys_text)
        self.assertNotIn(sample_prod_db_url, dumpsys_text)
        self.assertNotIn(sample_channel_token, dumpsys_text)
        self.assertNotIn("host-secret", host_text)

    def test_passing_status_requires_stylus_injection_fields_in_host_log(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text("Stylus injected: input=1 pressure=0.5\n", encoding="utf-8")
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )

            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=2 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN "
                "buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "single stylus injection line"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    diag_log,
                    host_log_excerpt="Stylus injected: input=1 pressure=0.5",
                )

    def test_passing_status_ignores_preexisting_host_log_without_new_excerpt(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )
            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=2 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN "
                "buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "new Host stylus log excerpt"):
                android_stylus_acceptance.conclusion_status(args, [candidate], diag_log)

    def test_passing_status_requires_android_diag_stylus_forwarding_fields(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "Android diag log"):
                android_stylus_acceptance.conclusion_status(args, [candidate], "")
            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "single stylus forwarding line"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    "Stylus forwarded: transport=stream samples=1 extended=false pressure=0.625 tiltX=45.0 tiltY=-45.0",
                )
            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "single stylus forwarding line"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    "Stylus forwarded: transport=stream samples=1 extended=false rawSource=0x1002 rawAction=2 rawTools=[finger] "
                    "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0",
                )

    def test_passing_status_accepts_host_log_with_pressure_and_signed_tilt(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )

            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=2 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN "
                "buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
            )

            host_log_excerpt = host_log.read_text(encoding="utf-8")
            self.assertEqual(
                "pass",
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    diag_log,
                    host_log_excerpt=host_log_excerpt,
                ),
            )

    def test_passing_status_rejects_hover_only_host_log(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                "contact=PROXIMITY tool=pen buttons=0 pressure=0 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )
            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=2 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN "
                "buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "contact, non-zero pressure"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    diag_log,
                    host_log_excerpt=host_log.read_text(encoding="utf-8"),
                )

    def test_passing_status_rejects_host_log_without_phase(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 "
                "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )
            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=2 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=CONTACT tool=PEN "
                "buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0"
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "contact, non-zero pressure"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    diag_log,
                    host_log_excerpt=host_log.read_text(encoding="utf-8"),
                )

    def test_passing_status_rejects_hover_only_android_diag(self) -> None:
        candidate = android_stylus_acceptance.InputDeviceCapability(
            name="goodix_stylus_input",
            descriptor="abc123",
            sources=("STYLUS",),
            axes=("PRESSURE", "TILT"),
            buttons=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 pointer=7 phase=INPUT_PHASE_CHANGED "
                "contact=contact tool=pen buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
                host_stable_signed_tcc_ready=True,
            )
            diag_log = (
                "Stylus forwarded: transport=stream samples=1 extended=true "
                "rawSource=0x5002 rawAction=7 rawTools=[stylus] "
                "phase=INPUT_PHASE_CHANGED contact=PROXIMITY tool=PEN "
                "buttons=0 pressure=0 tiltX=45.0 tiltY=-45.0"
            )

            with self.assertRaisesRegex(android_stylus_acceptance.EvidenceError, "contact, non-zero pressure"):
                android_stylus_acceptance.conclusion_status(
                    args,
                    [candidate],
                    diag_log,
                    host_log_excerpt=host_log.read_text(encoding="utf-8"),
                )

    def test_observed_drawing_without_required_capability_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            host_log = Path(temporary_directory) / "host-stylus.log"
            host_log.write_text(
                "Stylus injected: input=1 contact=contact buttons=0 pressure=0.625 tiltX=45.0 tiltY=-45.0\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                observed_physical_drawing=True,
                drawing_observation="physical stylus produced visible ink",
                host_log=host_log,
            )

            self.assertEqual(
                "blocked_no_required_stylus_capability",
                android_stylus_acceptance.conclusion_status(args, []),
            )

    def test_render_readme_uses_none_for_empty_candidate_fields(self) -> None:
        summary = {
            "status": "blocked_physical_stylus_not_observed",
            "device_identity": {
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "os_release": "16",
                "api_level": "36",
                "serialno": "AB0123CD456789EF",
                "fingerprint": "test",
                "wm_size": "Physical size: 1264x2800",
                "wm_density": "Physical density: 560",
            },
            "stylus_candidates": [{
                "name": "goodix_stylus_input",
                "sources": [],
                "axes": ["PRESSURE", "TILT"],
                "buttons": [],
            }],
        }

        readme = android_stylus_acceptance.render_readme(summary)

        self.assertIn("  - Sources: none", readme)
        self.assertIn("  - Buttons: none", readme)
        self.assertIn("  - Pass eligible: no", readme)
        self.assertFalse(any(line.endswith(" ") for line in readme.splitlines()))

    def test_render_readme_describes_lock_blocked_without_device_identity(self) -> None:
        summary = {
            "status": "blocked_device_coordination_lock",
            "requested_serial": "AB0123CD456789EF",
            "device_identity": {},
            "existing_locks": [{"path": "/tmp/vibe-screen-device-android.lock", "detail": "present"}],
            "stylus_candidates": [],
        }

        readme = android_stylus_acceptance.render_readme(summary)

        self.assertIn("ADB was not run. Requested serial: AB0123CD456789EF.", readme)
        self.assertIn("## Device coordination locks", readme)
        self.assertIn("/tmp/vibe-screen-device-android.lock", readme)
        self.assertIn("## Stylus input devices", readme)
        self.assertIn("No input-device snapshot was collected because ADB was not run.", readme)
        self.assertNotIn("dumpsys-input.txt", readme)
        self.assertNotIn("android-diag.log", readme)


class HarmonyDeviceGateTests(unittest.TestCase):
    MARKER_BY_GATE = {
        "deveco_sdk_and_api_checker": "harmony-readiness.json",
        "signed_release_hap": "harmony-hap-readiness.json",
        "hap_install_launch": "harmony-hap-readiness.json",
        "hap_in_place_upgrade": "harmony-hap-readiness.json",
        "hap_rollback_behavior": "harmony-hap-readiness.json",
        "hap_uninstall_cleanup": "harmony-hap-readiness.json",
        "permission_denial_retry": "permission-denial-retry.log",
        "huks_backed_secure_pairing": "harmony-secure-pairing.json",
        "authenticated_transport_records": "harmony-authenticated-records.json",
        "credential_revocation_replay": "harmony-secure-pairing.json",
        "h264_hardware_decode": "harmony-avcodec-preflight.json",
        "hevc_hardware_decode": "harmony-avcodec-preflight.json",
        "host_protocol_v1_interop": "harmony-host-interop-preflight.json",
        "resume_background_foreground": "harmony-host-interop-preflight.json",
        "resume_network_roam": "harmony-host-interop-preflight.json",
        "resume_host_restart": "harmony-host-interop-preflight.json",
        "resume_capable_host_interop": "harmony-host-interop-preflight.json",
        "no_old_epoch_render": "harmony-host-interop-preflight.json",
        "ui_device_identity_record": "ui-tree.xml",
        "input_touch_keyboard_pointer_stylus": "input-observations.json",
        "eight_hour_soak": "soak-summary.json",
        "external_latency": "latency-report.json",
    }

    def gate_manifest(self, gate_id: str, status: str) -> dict[str, object]:
        gate: dict[str, object] = {
            "id": gate_id,
            "status": status,
            "evidence": [f"evidence/{self.MARKER_BY_GATE[gate_id]}"],
        }
        if gate_id in harmony_device_gate.AVCODEC_GATE_IDS:
            gate["evidence"] = [f"evidence/{gate_id}.txt", f"evidence/{harmony_device_gate.AVCODEC_MANIFEST_NAME}"]
        if gate_id == "huks_backed_secure_pairing":
            gate["secure_pairing_manifest"] = {
                "schema": harmony_device_gate.SECURE_PAIRING_MANIFEST_SCHEMA,
                "path": "harmony-secure-pairing.json",
                "status": status,
            }
        return gate

    def passing_manifest(self) -> dict[str, object]:
        manifest = harmony_device_gate.template_manifest()
        manifest["repository"] = {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "status": "clean",
        }
        manifest["artifact"] = {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": "1" * 64,
            "signature_certificate_sha256": "2" * 64,
            "sha256sums_sha256": "3" * 64,
        }
        manifest["device"] = {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "HarmonyOS NEXT build 1",
            "hdc_target": "redacted-hdc-target",
            "serial_hash": "4" * 64,
        }
        manifest["host"] = {
            "commit": "c" * 40,
            "build_sha256": "5" * 64,
            "protocol": "Protocol v1",
        }
        manifest["gates"] = [
            self.gate_manifest(gate_id, "pass")
            for gate_id in harmony_device_gate.REQUIRED_GATE_IDS
        ]
        return manifest

    def test_harmony_device_manifest_passes_when_all_real_device_gates_are_present(self) -> None:
        self.assertEqual(harmony_device_gate.validate_manifest(self.passing_manifest()), [])

    def test_harmony_device_manifest_requires_evidence_files_under_root(self) -> None:
        manifest = self.passing_manifest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)
            for gate in manifest["gates"]:
                for reference in gate["evidence"]:
                    artifact = evidence_root / reference
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    gate_id = gate["id"]
                    artifact.write_text(f"{gate_id} evidence\n", encoding="utf-8")

            self.assertEqual(harmony_device_gate.validate_manifest(manifest, evidence_root=evidence_root), [])

    def test_harmony_device_manifest_accepts_explicit_directory_evidence(self) -> None:
        manifest = self.passing_manifest()
        manifest["gates"][0]["evidence"] = ["screenshots/"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)
            for gate in manifest["gates"]:
                for reference in gate["evidence"]:
                    artifact = evidence_root / reference
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    if reference.endswith("/"):
                        artifact.mkdir(exist_ok=True)
                    else:
                        artifact.write_text(f"{gate['id']} evidence\n", encoding="utf-8")

            self.assertEqual(harmony_device_gate.validate_manifest(manifest, evidence_root=evidence_root), [])

    def test_harmony_device_manifest_rejects_missing_evidence_file_when_root_is_set(self) -> None:
        manifest = self.passing_manifest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)

            with self.assertRaisesRegex(harmony_device_gate.ManifestError, "missing evidence artifact"):
                harmony_device_gate.validate_manifest(manifest, evidence_root=evidence_root)

    def test_harmony_device_manifest_rejects_evidence_references_outside_root(self) -> None:
        blocked_references = ("/tmp/harmony.log", "../harmony.log", "https://example.test/harmony.log", ".")
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)
            for reference in blocked_references:
                manifest = self.passing_manifest()
                manifest["gates"][0]["evidence"] = [reference]
                with self.subTest(reference=reference):
                    with self.assertRaisesRegex(
                        harmony_device_gate.ManifestError,
                        "evidence root|got URL|escape evidence root|artifact below evidence root",
                    ):
                        harmony_device_gate.validate_manifest(manifest, evidence_root=evidence_root)

    def test_harmony_device_manifest_rejects_android_substitute(self) -> None:
        manifest = self.passing_manifest()
        manifest["device"] = {
            "platform": "Android",
            "manufacturer": "nubia",
            "model": "P0110",
            "product": "pacific",
            "os_build": "Android 16",
            "hdc_target": "not-applicable",
            "serial_hash": "4" * 64,
        }

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "Android evidence"):
            harmony_device_gate.validate_manifest(manifest)

    def test_harmony_device_manifest_rejects_blocked_gate_unless_readiness_mode(self) -> None:
        manifest = self.passing_manifest()
        manifest["gates"][0]["status"] = "blocked"

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "deveco_sdk_and_api_checker: blocked"):
            harmony_device_gate.validate_manifest(manifest)
        self.assertEqual(
            harmony_device_gate.validate_manifest(manifest, allow_blocked=True),
            ["deveco_sdk_and_api_checker: blocked"],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.assertEqual(
                harmony_device_gate.validate_manifest(
                    manifest,
                    allow_blocked=True,
                    evidence_root=Path(temporary_directory),
                ),
                ["deveco_sdk_and_api_checker: blocked"],
            )

    def test_harmony_device_manifest_allows_blocked_placeholders_only_in_readiness_mode(self) -> None:
        manifest = self.passing_manifest()
        manifest["toolchain"]["harmony_sdk_api"] = "blocked: HarmonyOS SDK API not recorded"
        manifest["device"]["platform"] = "blocked: HarmonyOS NEXT device identity not verified"
        manifest["device"]["manufacturer"] = "blocked: HDC MatePad Mini identity not recorded"
        manifest["device"]["model"] = "blocked: MatePad Mini identity not recorded"
        manifest["device"]["product"] = "blocked: MatePad Mini product not recorded"

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "blocked placeholder is not evidence"):
            harmony_device_gate.validate_manifest(manifest)
        warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)
        self.assertIn("toolchain.harmony_sdk_api: blocked: HarmonyOS SDK API not recorded", warnings)
        self.assertIn("device.platform: blocked: HarmonyOS NEXT device identity not verified", warnings)

    def test_harmony_device_template_is_readiness_only(self) -> None:
        manifest = harmony_device_gate.template_manifest()

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "placeholder zero value"):
            harmony_device_gate.validate_manifest(manifest)
        warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)
        self.assertEqual(len(warnings), len(harmony_device_gate.REQUIRED_GATE_IDS))

    def test_harmony_device_cli_allow_blocked_never_prints_acceptance_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "harmony-device-gates.json"
            manifest_path.write_text(json.dumps(harmony_device_gate.template_manifest()), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(REPOSITORY_ROOT / "scripts/harmony_device_gate.py"),
                    "--allow-blocked",
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        self.assertIn("not acceptance evidence", result.stdout)
        self.assertNotIn("passes all required real-device gates", result.stdout)

    def test_harmony_device_cli_strict_mode_defaults_evidence_root_to_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "harmony-device-gates.json"
            manifest_path.write_text(json.dumps(self.passing_manifest()), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(REPOSITORY_ROOT / "scripts/harmony_device_gate.py"),
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing evidence artifact", result.stderr)

    def test_harmony_device_manifest_requires_signed_artifact_hashes(self) -> None:
        manifest = self.passing_manifest()
        manifest["artifact"]["hap_sha256"] = "not-a-hash"

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "artifact.hap_sha256"):
            harmony_device_gate.validate_manifest(manifest)

    def test_harmony_device_manifest_rejects_dirty_source_outside_readiness_mode(self) -> None:
        manifest = self.passing_manifest()
        manifest["repository"]["status"] = "dirty"

        with self.assertRaisesRegex(harmony_device_gate.ManifestError, "repository.status"):
            harmony_device_gate.validate_manifest(manifest)
        self.assertEqual(
            harmony_device_gate.validate_manifest(manifest, allow_blocked=True),
            ["repository.status: dirty"],
        )

    def test_harmony_device_gate_make_target_uses_manifest_validator(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("harmony-device-gate", makefile)
        self.assertIn("scripts/harmony_device_gate.py", makefile)
        self.assertIn("--evidence-root", makefile)
        self.assertIn("$(EVIDENCE_DIR)/harmony-device-gates.json", makefile)

    def test_host_rss_makefile_requires_host_pid_for_two_hour_gate(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("HOST_PID ?=\n", makefile)
        self.assertIn("require-host-pid:", makefile)
        self.assertRegex(
            makefile,
            r"(?m)^soak-2h\s*:\s*require-evidence-serial\s+require-host-pid\s*$",
        )
        self.assertIn(
            "$(if $(strip $(HOST_PID)),--host-pid $(HOST_PID),$(if $(strip $(EVIDENCE_HOST_PID)),--host-pid $(EVIDENCE_HOST_PID),))",
            makefile,
        )
        self.assertIn("soak-2h-host-rss-gate: require-evidence-serial require-host-pid", makefile)
        self.assertIn("vibescreen_evidence.host_rss_gate", makefile)

    def test_reconnect_timing_make_targets_are_fail_closed(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn(
            "RECONNECT_TIMING_TARGET_DEVICE ?= Nubia P0110 / pacific / Android 16 / SDK 36 / $(EVIDENCE_SERIAL)",
            makefile,
        )
        self.assertIn("RECONNECT_TIMING_REQUIRE_DISRUPTIONS ?=", makefile)
        self.assertIn(
            "RECONNECT_TIMING_OBSERVATIONS_JSON ?= $(EVIDENCE_DIR)/reconnect-timing-observations.json",
            makefile,
        )
        self.assertRegex(
            makefile,
            r"(?m)^evidence-reconnect-timing-blocked:\s+require-evidence-serial\s*$",
        )
        self.assertIn("evidence-reconnect-timing-gate:", makefile)
        self.assertIn(
            "error: set EVIDENCE_DIR to a reconnect timing evidence directory",
            makefile,
        )
        self.assertIn("missing reconnect timing observations", makefile)
        self.assertIn("$(foreach disruption,$(RECONNECT_TIMING_REQUIRE_DISRUPTIONS),--require-disruption $(disruption))", makefile)
        self.assertIn("--base-dir $(EVIDENCE_DIR)", makefile)
        self.assertEqual(makefile.count("python3 -m vibescreen_evidence.reconnect_timing"), 2)

    def test_harmony_readiness_make_target_uses_fail_closed_collector(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        target_match = re.search(
            r"(?ms)^harmony-hap-readiness:\n(?P<body>.*?)(?=^[a-zA-Z0-9_.-]+:|\Z)",
            makefile,
        )
        self.assertIsNotNone(target_match)
        target_body = target_match.group("body")

        self.assertIn("harmony-readiness:", makefile)
        self.assertIn("scripts/harmony_readiness.py", makefile)
        self.assertIn("HARMONY_HDC_TARGET", makefile)
        self.assertIn("HARMONY_HAP", makefile)
        self.assertIn("HARMONY_SHA256SUMS", makefile)
        self.assertIn("HARMONY_SIGNATURE_CERTIFICATE_SHA256", makefile)
        self.assertIn("scripts/harmony_hap_readiness.py", target_body)
        self.assertIn("HARMONY_HAP_READINESS_DIR", target_body)
        self.assertIn("--evidence-dir \"$(HARMONY_HAP_READINESS_DIR)\"", target_body)
        self.assertIn("--hdc-target \"$(HARMONY_HDC_TARGET)\"", target_body)
        self.assertIn("HARMONY_HAP_READINESS_FLAGS", target_body)
        self.assertNotIn("--output", target_body)
        self.assertNotIn("--target", target_body)


class HarmonyHostInteropPreflightTests(unittest.TestCase):
    def passing_manifest(self) -> dict[str, object]:
        manifest = harmony_host_interop_preflight.template_manifest()
        manifest["repository"] = {"commit": "a" * 40, "tree": "b" * 40, "status": "clean"}
        manifest["artifact"] = {
            "bundle_name": "dev.vibescreen.harmony",
            "version_name": "0.1.0",
            "hap_sha256": "1" * 64,
            "signature_certificate_sha256": "2" * 64,
        }
        manifest["device"] = {
            "platform": "HarmonyOS NEXT",
            "manufacturer": "Huawei",
            "model": "MatePad Mini",
            "product": "MatePad Mini",
            "os_build": "HarmonyOS NEXT build 1",
            "hdc_target": "redacted-hdc-target",
            "serial_hash": "3" * 64,
        }
        manifest["host"] = {
            "commit": "c" * 40,
            "build_sha256": "4" * 64,
            "protocol": "Protocol v1",
            "resume_registry": "resume-capable",
        }
        manifest["transport"] = {"mode": "trusted_lan", "encrypted_records": True}
        manifest["reconnect"] = {
            "maximum_attempts": 8,
            "maximum_delay_ms": 8000,
            "maximum_observed_recovery_ms": 2500,
        }
        manifest["flows"] = [
            {"id": flow_id, "status": "pass", "evidence": [f"evidence/{flow_id}.txt"]}
            for flow_id in harmony_host_interop_preflight.REQUIRED_FLOW_IDS
        ]
        return manifest

    def test_harmony_host_interop_manifest_passes_when_all_flows_pass(self) -> None:
        self.assertEqual(harmony_host_interop_preflight.validate_manifest(self.passing_manifest()), [])

    def test_harmony_host_interop_manifest_requires_evidence_files_under_root(self) -> None:
        manifest = self.passing_manifest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)
            for flow in manifest["flows"]:
                artifact = evidence_root / flow["evidence"][0]
                artifact.parent.mkdir(parents=True, exist_ok=True)
                flow_id = flow["id"]
                artifact.write_text(f"{flow_id} evidence\n", encoding="utf-8")

            self.assertEqual(
                harmony_host_interop_preflight.validate_manifest(manifest, evidence_root=evidence_root),
                [],
            )

    def test_harmony_host_interop_manifest_rejects_evidence_references_outside_root(self) -> None:
        blocked_references = ("/tmp/harmony.log", "../harmony.log", "https://example.test/harmony.log", ".")
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_root = Path(temporary_directory)
            for reference in blocked_references:
                manifest = self.passing_manifest()
                manifest["flows"][0]["evidence"] = [reference]
                with self.subTest(reference=reference):
                    with self.assertRaisesRegex(
                        harmony_host_interop_preflight.InteropManifestError,
                        "evidence root|got URL|escape evidence root|artifact below evidence root",
                    ):
                        harmony_host_interop_preflight.validate_manifest(manifest, evidence_root=evidence_root)

    def test_harmony_host_interop_cli_strict_mode_defaults_evidence_root_to_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest_path = Path(temporary_directory) / "harmony-host-interop.json"
            manifest_path.write_text(json.dumps(self.passing_manifest()), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(REPOSITORY_ROOT / "scripts/harmony_host_interop_preflight.py"),
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing evidence artifact", result.stderr)

    def test_harmony_host_interop_rejects_android_substitute(self) -> None:
        manifest = self.passing_manifest()
        manifest["device"] = {
            "platform": "Android",
            "manufacturer": "nubia",
            "model": "P0110",
            "product": "pacific",
            "os_build": "Android 16",
            "hdc_target": "not-applicable",
            "serial_hash": "3" * 64,
        }

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "Android evidence"):
            harmony_host_interop_preflight.validate_manifest(manifest)

    def test_harmony_host_interop_requires_resume_capable_host(self) -> None:
        manifest = self.passing_manifest()
        manifest["host"]["resume_registry"] = "client-hello-only"

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "resume-capable"):
            harmony_host_interop_preflight.validate_manifest(manifest)

    def test_harmony_host_interop_requires_old_epoch_rejection_flows(self) -> None:
        manifest = self.passing_manifest()
        manifest["flows"] = [flow for flow in manifest["flows"] if flow["id"] != "old_epoch_media_rejected"]

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "old_epoch_media_rejected"):
            harmony_host_interop_preflight.validate_manifest(manifest)

    def test_harmony_host_interop_allows_blocked_structure_without_acceptance(self) -> None:
        manifest = harmony_host_interop_preflight.template_manifest()

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "placeholder zero value"):
            harmony_host_interop_preflight.validate_manifest(manifest)
        with tempfile.TemporaryDirectory() as temporary_directory:
            warnings = harmony_host_interop_preflight.validate_manifest(
                manifest,
                allow_blocked=True,
                evidence_root=Path(temporary_directory),
            )
            self.assertEqual(len(warnings), len(harmony_host_interop_preflight.REQUIRED_FLOW_IDS))

    def test_harmony_host_interop_rejects_unencrypted_trusted_lan(self) -> None:
        manifest = self.passing_manifest()
        manifest["transport"]["encrypted_records"] = False

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "authenticated records"):
            harmony_host_interop_preflight.validate_manifest(manifest)

    def test_harmony_host_interop_rejects_slow_reconnect(self) -> None:
        manifest = self.passing_manifest()
        manifest["reconnect"]["maximum_observed_recovery_ms"] = 3001

        with self.assertRaisesRegex(harmony_host_interop_preflight.InteropManifestError, "<= 3000"):
            harmony_host_interop_preflight.validate_manifest(manifest)

    def test_harmony_host_interop_preflight_writes_blocked_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            with mock.patch.object(
                harmony_host_interop_preflight,
                "probe_command",
                side_effect=lambda name, _version_args: harmony_host_interop_preflight.CommandProbe(
                    name, None, "not found"
                ),
            ):
                exit_code = harmony_host_interop_preflight.main(
                    ["--evidence-dir", str(evidence_dir), "--run-id", "run-test"]
                )

            self.assertEqual(exit_code, harmony_host_interop_preflight.BLOCKED_EXIT)
            summary = json.loads((evidence_dir / "harmony-host-interop-preflight.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["run_id"], "run-test")
            self.assertEqual(summary["verdict"], "blocked")
            self.assertFalse(summary["can_close_harmony_host_interop_gate"])
            self.assertTrue((evidence_dir / "harmony-host-interop-manifest-template.json").exists())
            self.assertIn("not acceptance evidence", (evidence_dir / "README.md").read_text(encoding="utf-8"))

    def test_harmony_host_interop_preflight_accepts_either_hvigor_binary(self) -> None:
        def fake_probe(name: str, _version_args: list[str]) -> harmony_host_interop_preflight.CommandProbe:
            path = "/usr/local/bin/hvigorw" if name == "hvigorw" else "/usr/local/bin/tool" if name in {"ohpm", "hdc"} else None
            return harmony_host_interop_preflight.CommandProbe(name, path, "version")

        with mock.patch.object(harmony_host_interop_preflight, "probe_command", side_effect=fake_probe):
            summary = harmony_host_interop_preflight.local_preflight("run-test")

        missing = next(
            (reason["reason"] for reason in summary["blocking_reasons"] if reason["field"] == "missing_commands"),
            "",
        )
        self.assertNotIn("hvigor", missing)
        probes = {probe["name"]: probe for probe in summary["command_probes"]}
        self.assertEqual(probes["hvigorw"]["path"], "hvigorw")
        self.assertEqual(probes["ohpm"]["path"], "tool")
        self.assertNotIn("/usr/local/bin", json.dumps(summary))

    def test_harmony_current_base_make_target_uses_owner_gate_validator(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("harmony-current-base-gate:", makefile)
        self.assertIn("vibescreen_evidence.harmony_current_base_gate", makefile)
        self.assertIn("--readiness", makefile)
        self.assertIn("--device-gates", makefile)
        self.assertIn("--evidence-root", makefile)
        self.assertIn("$(HARMONY_DEVICE_GATES_JSON)", makefile)


class ArchiveArtifactTests(unittest.TestCase):
    def test_archive_is_deterministic_when_source_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "Example.app"
            source.mkdir()
            binary = source / "Example"
            binary.write_bytes(b"binary")
            binary.chmod(0o755)
            first = root / "first.zip"
            second = root / "second.zip"

            subprocess.run(
                ["python3", str(ARCHIVE_SCRIPT), "--input", str(source), "--output", str(first)],
                check=True,
                capture_output=True,
                text=True,
            )
            binary.touch()
            subprocess.run(
                ["python3", str(ARCHIVE_SCRIPT), "--input", str(source), "--output", str(second)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )
            with zipfile.ZipFile(first) as archive:
                mode = archive.getinfo("Example.app/Example").external_attr >> 16
                self.assertEqual(mode & 0o777, 0o755)


class MacOSSigningIdentityTests(unittest.TestCase):
    def test_packaged_host_requests_virtual_hid_entitlement(self) -> None:
        entitlements = plistlib.loads(MAC_HOST_ENTITLEMENTS.read_bytes())

        self.assertIs(entitlements.get("com.apple.developer.hid.virtual.device"), True)

    def test_copy_audio_pcm_fixture_into_app_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            resources_dir = Path(temporary_directory) / "Vibe Screen.app" / "Contents" / "Resources"
            resources_dir.mkdir(parents=True)

            package_macos.copy_audio_pcm_fixture(resources_dir)

            destination = resources_dir / package_macos.AUDIO_PCM_FIXTURE_RELATIVE_PATH
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.read_bytes(), package_macos.AUDIO_PCM_FIXTURE_SOURCE.read_bytes())

    def test_explicit_ad_hoc_identity_skips_keychain_lookup(self) -> None:
        with mock.patch.object(package_macos.subprocess, "run") as run_mock:
            self.assertEqual(package_macos.resolve_sign_identity("-"), "-")
        run_mock.assert_not_called()

    def test_named_identity_is_returned_as_pinned_sha1_when_keychain_contains_it(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                f'  1) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            self.assertEqual(
                package_macos.resolve_sign_identity("Vibe Screen Dev"),
                package_macos.EXPECTED_SIGNING_LEAF_SHA1,
            )

    def test_pinned_sha1_identity_is_returned_when_keychain_contains_it(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                f'  1) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            self.assertEqual(
                package_macos.resolve_sign_identity(package_macos.EXPECTED_SIGNING_LEAF_SHA1.lower()),
                package_macos.EXPECTED_SIGNING_LEAF_SHA1,
            )

    def test_duplicate_same_sha1_identity_is_treated_as_one_keychain_identity(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                f'  1) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                f'  2) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                "     2 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            self.assertEqual(
                package_macos.resolve_sign_identity("Vibe Screen Dev"),
                package_macos.EXPECTED_SIGNING_LEAF_SHA1,
            )

    def test_named_identity_lookup_timeout_fails_closed(self) -> None:
        with mock.patch.object(
            package_macos.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(
                ("/usr/bin/security", "find-identity", "-v", "-p", "codesigning"),
                30,
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "security find-identity -v -p codesigning timed out"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_identity_lookup_nonzero_return_fails_closed_with_security_output(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=1,
            stdout="security: SecKeychainSearchCopyNext: The specified item could not be found.\n",
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "security find-identity.*failed"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_identity_lookup_requires_an_exact_name(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Production Vibe Screen Dev Certificate"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "not found in the keychain"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_missing_named_identity_fails_instead_of_using_ad_hoc(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout="     0 valid identities found\n",
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "not found in the keychain"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_same_named_wrong_leaf_identity_fails_closed(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "expected '9AAE572BF6D764E3436A6109197D345B5A87998C'"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_wrong_sha1_identity_fails_closed(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                f'  1) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "is not the pinned"):
                package_macos.resolve_sign_identity("0123456789abcdef0123456789abcdef01234567")

    def test_duplicate_named_identity_fails_instead_of_choosing_one(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Vibe Screen Dev"\n'
                '  2) FEDCBA9876543210FEDCBA9876543210FEDCBA98 '
                '"Vibe Screen Dev"\n'
                "     2 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "multiple codesign identities"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_duplicate_named_identity_with_expected_leaf_still_fails_closed(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                f'  1) {package_macos.EXPECTED_SIGNING_LEAF_SHA1} '
                '"Vibe Screen Dev"\n'
                '  2) B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA '
                '"Vibe Screen Dev"\n'
                "     2 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "multiple codesign identities"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_environment_ad_hoc_identity_requires_explicit_cli_option(self) -> None:
        with self.assertRaisesRegex(SystemExit, "Pass --sign-identity - explicitly"):
            package_macos.require_explicit_ad_hoc_preview("-", explicit_cli_option=False)

        package_macos.require_explicit_ad_hoc_preview("-", explicit_cli_option=True)

    def test_parse_signing_certificate_hash_accepts_leaf_only(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        self.assertEqual(
            package_macos.parse_signing_certificate_hash(
                f'identifier "dev.telemachus.display" and certificate leaf = H"{expected.lower()}"'
            ),
            expected,
        )
        self.assertIsNone(
            package_macos.parse_signing_certificate_hash(
                f'identifier "dev.telemachus.display" and certificate root = H"{expected.lower()}"'
            )
        )
        self.assertIsNone(
            package_macos.parse_signing_certificate_hash(
                'identifier "dev.telemachus.display" and certificate root = H"not-a-sha1"'
            )
        )
        self.assertIsNone(
            package_macos.parse_signing_certificate_hash(
                'identifier "dev.telemachus.display" and certificate 1 = H"' + expected + '"'
            )
        )

    def test_parse_signing_certificate_hash_prefers_leaf_when_root_is_present(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        root = "B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

        self.assertEqual(
            package_macos.parse_signing_certificate_hash(
                f'certificate root = H"{root}" and certificate leaf = H"{expected}"'
            ),
            expected,
        )

    def test_canonical_designated_requirement_contract_accepts_pure_and_equivalent_forms(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        for requirement in (
            f'identifier "dev.telemachus.display" and certificate leaf = H"{expected.lower()}"',
            f'certificate leaf = H"{expected}" and identifier "dev.telemachus.display"',
            f'(identifier "dev.telemachus.display") and (certificate leaf = H"{expected}")',
        ):
            with self.subTest(requirement=requirement):
                self.assertIsNone(
                    package_macos.canonical_designated_requirement_contract_error(requirement)
                )

    def test_canonical_designated_requirement_contract_rejects_drift(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        scenarios = (
            (
                "root-only",
                f'identifier "dev.telemachus.display" and certificate root = H"{expected}"',
                "unsupported clause",
            ),
            (
                "intermediate-only",
                f'identifier "dev.telemachus.display" and certificate 1 = H"{expected}"',
                "unsupported clause",
            ),
            (
                "missing identifier",
                f'certificate leaf = H"{expected}"',
                "exactly identifier and certificate leaf",
            ),
            (
                "wrong identifier",
                f'identifier "com.example.OtherHost" and certificate leaf = H"{expected}"',
                "expected 'dev.telemachus.display'",
            ),
            (
                "extra-or",
                f'identifier "dev.telemachus.display" and certificate leaf = H"{expected}" or anchor apple generic',
                "must not contain OR",
            ),
            (
                "extra-clause",
                f'identifier "dev.telemachus.display" and certificate leaf = H"{expected}" and anchor trusted',
                "exactly identifier and certificate leaf",
            ),
            (
                "leaf-plus-root",
                f'identifier "dev.telemachus.display" and certificate leaf = H"{expected}" and certificate root = H"{expected}"',
                "exactly identifier and certificate leaf",
            ),
            (
                "custom-requirement",
                f'identifier "dev.telemachus.display" and certificate leaf = H"{expected}" and cdhash H"14d6c458c817f38dfdf7cc1d31bfdcb1e8e11fa7"',
                "exactly identifier and certificate leaf",
            ),
            (
                "wrong leaf",
                'identifier "dev.telemachus.display" and certificate leaf = H"0123456789ABCDEF0123456789ABCDEF01234567"',
                "expected '9AAE572BF6D764E3436A6109197D345B5A87998C'",
            ),
        )
        for label, requirement, expected_error in scenarios:
            with self.subTest(label=label):
                self.assertRegex(
                    package_macos.canonical_designated_requirement_contract_error(requirement) or "",
                    expected_error,
                )

    def test_designated_requirement_contract_parser_handles_parens_and_quoted_and_literals(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        contract = package_macos.parse_designated_requirement_contract(
            f'((identifier "dev.telemachus.display")) and ((certificate leaf = H"{expected.lower()}"))'
        )

        self.assertEqual(contract.identifier, "dev.telemachus.display")
        self.assertEqual(contract.leaf_sha1, expected)
        contract = package_macos.parse_designated_requirement_contract(
            f'identifier "dev.and.telemachus.display" and certificate leaf = H"{expected}"'
        )
        self.assertEqual(contract.identifier, "dev.and.telemachus.display")
        self.assertRegex(
            package_macos.canonical_designated_requirement_contract_error(
                f'identifier "dev.and.telemachus.display" and certificate leaf = H"{expected}"'
            ) or "",
            "expected 'dev.telemachus.display'",
        )

    def test_parse_designated_requirement_requires_designated_marker(self) -> None:
        self.assertIsNone(
            package_macos.parse_designated_requirement(
                f'library => certificate leaf = H"{package_macos.EXPECTED_SIGNING_LEAF_SHA1}"'
            )
        )

    def test_parse_designated_requirement_identifier_accepts_quoted_or_bare_identifier(self) -> None:
        self.assertEqual(
            package_macos.parse_designated_requirement_identifier(
                'identifier "dev.telemachus.display" and certificate root = H"'
                + package_macos.EXPECTED_SIGNING_LEAF_SHA1
                + '"'
            ),
            "dev.telemachus.display",
        )
        self.assertEqual(
            package_macos.parse_designated_requirement_identifier(
                "identifier org.webrtc.WebRTC and anchor apple generic"
            ),
            "org.webrtc.WebRTC",
        )
        self.assertIsNone(package_macos.parse_designated_requirement_identifier("anchor apple generic"))

    def test_parse_args_rejects_environment_ad_hoc_without_explicit_cli_option(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["package_macos.py"]),
            mock.patch.dict(os.environ, {package_macos.SIGN_IDENTITY_ENV: "-"}),
        ):
            arguments = package_macos.parse_args()

        self.assertEqual(arguments.sign_identity, "-")
        self.assertFalse(arguments.sign_identity_explicit)
        with self.assertRaisesRegex(SystemExit, "Pass --sign-identity - explicitly"):
            package_macos.require_explicit_ad_hoc_preview(
                arguments.sign_identity,
                explicit_cli_option=arguments.sign_identity_explicit,
            )

    def test_parse_args_allows_explicit_cli_ad_hoc_preview(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["package_macos.py", "--sign-identity", "-"]),
            mock.patch.dict(os.environ, {package_macos.SIGN_IDENTITY_ENV: "Vibe Screen Dev"}),
        ):
            arguments = package_macos.parse_args()

        self.assertEqual(arguments.sign_identity, "-")
        self.assertTrue(arguments.sign_identity_explicit)
        package_macos.require_explicit_ad_hoc_preview(
            arguments.sign_identity,
            explicit_cli_option=arguments.sign_identity_explicit,
        )

    def test_ad_hoc_preview_notice_is_written_only_for_ad_hoc_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            resources = Path(temporary_directory) / "Resources"
            resources.mkdir()

            package_macos.write_ad_hoc_preview_notice(resources, "-")
            notice = resources / package_macos.AD_HOC_PREVIEW_NOTICE_NAME
            self.assertTrue(notice.is_file())
            self.assertIn("must not be used for macOS TCC", notice.read_text(encoding="utf-8"))

            notice.unlink()
            package_macos.write_ad_hoc_preview_notice(resources, package_macos.EXPECTED_SIGNING_LEAF_SHA1)
            self.assertFalse(notice.exists())

    def test_main_resolves_identity_before_validating_or_building(self) -> None:
        arguments = argparse.Namespace(sign_identity="Vibe Screen Dev", sign_identity_explicit=False)
        with (
            mock.patch.object(package_macos, "parse_args", return_value=arguments),
            mock.patch.object(
                package_macos,
                "resolve_sign_identity",
                side_effect=SystemExit("missing identity"),
            ) as resolve_mock,
            mock.patch.object(package_macos, "require_explicit_ad_hoc_preview") as preview_mock,
            mock.patch.object(package_macos, "validate_notice_bundle") as validate_mock,
            mock.patch.object(package_macos, "run") as run_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "missing identity"):
                package_macos.main()
        preview_mock.assert_called_once_with("Vibe Screen Dev", explicit_cli_option=False)
        resolve_mock.assert_called_once_with("Vibe Screen Dev")
        validate_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_main_refuses_dirty_source_before_reading_plist_or_building(self) -> None:
        arguments = argparse.Namespace(sign_identity="-", sign_identity_explicit=True)
        with (
            mock.patch.object(package_macos, "parse_args", return_value=arguments),
            mock.patch.object(package_macos, "resolve_sign_identity", return_value="-"),
            mock.patch.object(package_macos, "validate_notice_bundle") as validate_mock,
            mock.patch.object(
                package_macos,
                "collect_source_identity",
                return_value=package_macos.SourceIdentity(
                    commit="a" * 40,
                    tree="b" * 40,
                    dirty=True,
                ),
            ),
            mock.patch.object(package_macos, "read_source_plist") as plist_mock,
            mock.patch.object(package_macos, "run") as run_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "dirty source tree"):
                package_macos.main()

        validate_mock.assert_called_once_with(package_macos.REPOSITORY_ROOT)
        plist_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_clean_codesign_temporary_files_removes_framework_staging_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            framework = Path(temporary_directory) / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            current = framework / "Versions" / "Current"
            current.symlink_to("A")
            binary = version_dir / "WebRTC"
            binary.write_bytes(b"binary")
            stale = version_dir / "WebRTC.cstemp"
            stale.write_bytes(b"stale")
            nested_stale = version_dir / "WebRTC.cstemp.cstemp"
            nested_stale.write_bytes(b"nested stale")

            removed = package_macos.clean_codesign_temporary_files(framework)

            self.assertEqual(
                tuple(path.relative_to(framework).as_posix() for path in removed),
                ("Versions/A/WebRTC.cstemp", "Versions/A/WebRTC.cstemp.cstemp"),
            )
            self.assertTrue(binary.exists())
            self.assertTrue(current.is_symlink())
            self.assertFalse(stale.exists())
            self.assertFalse(nested_stale.exists())
            package_macos.require_no_codesign_temporary_files(framework)

    def test_clean_codesign_temporary_files_handles_directories_symlinks_and_missing_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            framework = root / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            stale_dir = version_dir / "WebRTC.cstemp"
            stale_dir.mkdir()
            (stale_dir / "partial").write_bytes(b"partial")
            real_binary = version_dir / "WebRTC"
            real_binary.write_bytes(b"binary")
            stale_link = version_dir / "WebRTC.cstemp.cstemp"
            stale_link.symlink_to("WebRTC")

            self.assertEqual(package_macos.codesign_temporary_files(root / "missing.framework"), ())
            removed = package_macos.clean_codesign_temporary_files(framework)

            self.assertEqual(
                tuple(path.relative_to(framework).as_posix() for path in removed),
                ("Versions/A/WebRTC.cstemp", "Versions/A/WebRTC.cstemp.cstemp"),
            )
            self.assertFalse(stale_dir.exists())
            self.assertFalse(stale_link.exists())
            self.assertTrue(real_binary.exists())

    def test_require_no_codesign_temporary_files_reports_relative_framework_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            framework = Path(temporary_directory) / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            (version_dir / "WebRTC.cstemp").write_bytes(b"stale")

            with self.assertRaisesRegex(SystemExit, r"Versions/A/WebRTC\.cstemp"):
                package_macos.require_no_codesign_temporary_files(framework)

    def test_codesign_temporary_files_matches_only_cstemp_extension_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stale = root / "WebRTC.CSTEMP"
            nested_stale = root / "WebRTC.cstemp.cstemp"
            template = root / "Resources" / "foo.cstemplate.dat"
            template.parent.mkdir()
            stale.write_bytes(b"stale")
            nested_stale.write_bytes(b"nested stale")
            template.write_bytes(b"not a codesign temporary file")

            temporary_files = package_macos.codesign_temporary_files(root)

            self.assertEqual(
                tuple(path.relative_to(root).as_posix() for path in temporary_files),
                ("WebRTC.CSTEMP", "WebRTC.cstemp.cstemp"),
            )

    def test_code_resources_scan_reports_sealed_cstemp_references_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            framework = Path(temporary_directory) / "WebRTC.framework"
            signature_dir = framework / "Versions" / "A" / "_CodeSignature"
            signature_dir.mkdir(parents=True)
            with (signature_dir / "CodeResources").open("wb") as code_resources:
                plistlib.dump(
                    {
                        "files": {
                            "Resources/Info.plist": {"hash": b"stable"},
                            "Resources/foo.cstemplate.dat": {"hash": b"stable-template"},
                            "WebRTC.cstemp": {"hash": b"stale"},
                            "WebRTC.cstemp.cstemp": {"hash": b"nested"},
                        },
                        "rules": {"^.*\.cstemp$": True, "cstemplates.dat": True},
                    },
                    code_resources,
                )

            self.assertEqual(package_macos.codesign_temporary_files(framework), ())
            references = package_macos.codesign_resource_seal_temporary_references(framework)

            self.assertIn("Versions/A/_CodeSignature/CodeResources:$/files/WebRTC.cstemp", references)
            self.assertIn("Versions/A/_CodeSignature/CodeResources:$/files/WebRTC.cstemp.cstemp", references)
            self.assertIn(r"Versions/A/_CodeSignature/CodeResources:$/rules/^.*\.cstemp$", references)
            self.assertNotIn(
                "Versions/A/_CodeSignature/CodeResources:$/files/Resources/foo.cstemplate.dat",
                references,
            )
            self.assertNotIn("Versions/A/_CodeSignature/CodeResources:$/rules/cstemplates.dat", references)
            with self.assertRaisesRegex(SystemExit, r"CodeResources.*WebRTC\.cstemp"):
                package_macos.require_no_codesign_resource_seal_temporary_references(framework)

    def test_sign_packaged_app_cleans_framework_and_signs_outer_bundle_last(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            stale = version_dir / "WebRTC.cstemp"
            stale.write_bytes(b"stale")
            app_stale = app / "Contents" / "Resources" / "Credits.html.cstemp"
            app_stale.parent.mkdir(parents=True, exist_ok=True)
            app_stale.write_bytes(b"stale")
            commands: list[tuple[str, ...]] = []

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                if command == (package_macos.CODESIGN, "--force", "--sign", "Vibe Screen Dev", str(framework)):
                    self.assertFalse(stale.exists())
                if command in (
                    (package_macos.CODESIGN, "-d", "-r-", str(app)),
                    (package_macos.CODESIGN, "-d", "-r-", str(framework)),
                ):
                    identifier = "org.webrtc.WebRTC" if command[-1] == str(framework) else "dev.telemachus.display"
                    return (
                        f'designated => identifier "{identifier}" and '
                        f'certificate leaf = H"{package_macos.EXPECTED_SIGNING_LEAF_SHA1}"'
                    )
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                package_macos.sign_packaged_app(app, framework, "Vibe Screen Dev")

            self.assertFalse(app_stale.exists())
            self.assertNotIn("--deep", commands[1])
            self.assertEqual(
                commands,
                [
                    (package_macos.CODESIGN, "--force", "--sign", "Vibe Screen Dev", str(framework)),
                    (package_macos.CODESIGN, "--verify", "--strict", "--verbose=2", str(framework)),
                    (
                        package_macos.CODESIGN,
                        "--force",
                        "--sign",
                        "Vibe Screen Dev",
                        "--entitlements",
                        str(package_macos.HOST_ROOT / "Telemachus.entitlements"),
                        str(app),
                    ),
                    (package_macos.CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(app)),
                    (package_macos.CODESIGN, "-d", "-r-", str(app)),
                    (package_macos.CODESIGN, "-d", "-r-", str(framework)),
                ],
            )

    def test_sign_packaged_app_refuses_temporary_files_left_by_framework_signing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            leaked = version_dir / "WebRTC.cstemp"
            commands: list[tuple[str, ...]] = []

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                if command == (package_macos.CODESIGN, "--force", "--sign", "Vibe Screen Dev", str(framework)):
                    leaked.write_bytes(b"leaked")
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                with self.assertRaisesRegex(SystemExit, "Refusing to continue"):
                    package_macos.sign_packaged_app(app, framework, "Vibe Screen Dev")

            self.assertEqual(
                commands,
                [
                    (package_macos.CODESIGN, "--force", "--sign", "Vibe Screen Dev", str(framework)),
                    (package_macos.CODESIGN, "--verify", "--strict", "--verbose=2", str(framework)),
                ],
            )

    def test_sign_packaged_app_refuses_temporary_files_left_by_outer_app_signing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            version_dir = framework / "Versions" / "A"
            version_dir.mkdir(parents=True)
            leaked = app / "Contents" / "Resources" / "Credits.html.cstemp"
            commands: list[tuple[str, ...]] = []

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                if command == (
                    package_macos.CODESIGN,
                    "--force",
                    "--sign",
                    "Vibe Screen Dev",
                    "--entitlements",
                    str(package_macos.HOST_ROOT / "Telemachus.entitlements"),
                    str(app),
                ):
                    leaked.parent.mkdir(parents=True, exist_ok=True)
                    leaked.write_bytes(b"leaked")
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                with self.assertRaisesRegex(SystemExit, "codesign temporary files remain"):
                    package_macos.sign_packaged_app(app, framework, "Vibe Screen Dev")

            self.assertEqual(
                commands,
                [
                    (package_macos.CODESIGN, "--force", "--sign", "Vibe Screen Dev", str(framework)),
                    (package_macos.CODESIGN, "--verify", "--strict", "--verbose=2", str(framework)),
                    (
                        package_macos.CODESIGN,
                        "--force",
                        "--sign",
                        "Vibe Screen Dev",
                        "--entitlements",
                        str(package_macos.HOST_ROOT / "Telemachus.entitlements"),
                        str(app),
                    ),
                    (package_macos.CODESIGN, "--verify", "--deep", "--strict", "--verbose=2", str(app)),
                ],
            )

    def test_verify_signed_app_certificate_contract_rejects_root_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
            with mock.patch.object(
                package_macos,
                "run",
                return_value=(
                    'designated => identifier "dev.telemachus.display" and '
                    f'certificate root = H"{expected.lower()}"'
                ),
            ) as run_mock:
                with self.assertRaisesRegex(SystemExit, "unsupported clause"):
                    package_macos.verify_signed_app_certificate_contract(app, expected)

        run_mock.assert_called_once_with(package_macos.CODESIGN, "-d", "-r-", str(app))

    def test_verify_signed_app_certificate_contract_rejects_wrong_root_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value=(
                    'designated => identifier "dev.telemachus.display" and '
                    'certificate root = H"B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"'
                ),
            ):
                with self.assertRaisesRegex(SystemExit, "unsupported clause"):
                    package_macos.verify_signed_app_certificate_contract(app, package_macos.EXPECTED_SIGNING_LEAF_SHA1)

    def test_verify_signed_app_certificate_contract_rejects_malformed_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value='designated => identifier "dev.telemachus.display" and certificate root = H"not-a-sha1"',
            ):
                with self.assertRaisesRegex(SystemExit, "unsupported clause"):
                    package_macos.verify_signed_app_certificate_contract(app, package_macos.EXPECTED_SIGNING_LEAF_SHA1)

    def test_verify_signed_app_certificate_contract_rejects_extra_or_and_custom_clauses(self) -> None:
        expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1
        scenarios = (
            (
                "extra-or",
                f'designated => identifier "dev.telemachus.display" and certificate leaf = H"{expected}" or anchor trusted',
                "must not contain OR",
            ),
            (
                "extra-clause",
                f'designated => identifier "dev.telemachus.display" and certificate leaf = H"{expected}" and anchor trusted',
                "exactly identifier and certificate leaf",
            ),
            (
                "leaf-plus-root",
                f'designated => identifier "dev.telemachus.display" and certificate leaf = H"{expected}" and certificate root = H"{expected}"',
                "exactly identifier and certificate leaf",
            ),
            (
                "wrong-identifier",
                f'designated => identifier "com.example.OtherHost" and certificate leaf = H"{expected}"',
                "uses identifier 'com.example.OtherHost'",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            for label, requirement_output, expected_error in scenarios:
                with self.subTest(label=label):
                    with mock.patch.object(package_macos, "run", return_value=requirement_output):
                        with self.assertRaisesRegex(SystemExit, expected_error):
                            package_macos.verify_signed_app_certificate_contract(
                                app,
                                package_macos.EXPECTED_SIGNING_LEAF_SHA1,
                            )

    def test_verify_signed_app_certificate_contract_rejects_missing_designated_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value=f'library => certificate leaf = H"{package_macos.EXPECTED_SIGNING_LEAF_SHA1}"',
            ):
                with self.assertRaisesRegex(SystemExit, "designated requirement is missing"):
                    package_macos.verify_signed_app_certificate_contract(app, package_macos.EXPECTED_SIGNING_LEAF_SHA1)

    def test_verify_signed_app_certificate_contract_rejects_wrong_identifier_even_for_ad_hoc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value='designated => identifier "com.example.OtherHost" and anchor apple generic',
            ):
                with self.assertRaisesRegex(SystemExit, "uses identifier 'com.example.OtherHost'"):
                    package_macos.verify_signed_app_certificate_contract(app, "-")

    def test_verify_signed_app_certificate_contract_wraps_codesign_requirement_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            error = subprocess.CalledProcessError(1, [package_macos.CODESIGN], output="not signed")
            with mock.patch.object(package_macos, "run", side_effect=error):
                with self.assertRaisesRegex(SystemExit, "inspection failed.*not signed"):
                    package_macos.verify_signed_app_certificate_contract(app, package_macos.EXPECTED_SIGNING_LEAF_SHA1)

    def test_verify_signed_app_certificate_contract_ad_hoc_accepts_cdhash_only_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value='designated => cdhash H"14d6c458c817f38dfdf7cc1d31bfdcb1e8e11fa7"',
            ) as run_mock:
                package_macos.verify_signed_app_certificate_contract(app, "-")

        run_mock.assert_called_once_with(package_macos.CODESIGN, "-d", "-r-", str(app))

    def test_verify_signed_app_certificate_contract_ad_hoc_accepts_expected_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            with mock.patch.object(
                package_macos,
                "run",
                return_value='designated => identifier "dev.telemachus.display" and anchor apple generic',
            ):
                package_macos.verify_signed_app_certificate_contract(app, "-")

    def test_sign_packaged_app_verifies_outer_app_and_framework_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            (framework / "Versions" / "A").mkdir(parents=True)
            commands: list[tuple[str, ...]] = []
            expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                if command in (
                    (package_macos.CODESIGN, "-d", "-r-", str(app)),
                    (package_macos.CODESIGN, "-d", "-r-", str(framework)),
                ):
                    identifier = "org.webrtc.WebRTC" if command[-1] == str(framework) else "dev.telemachus.display"
                    return (
                        f'designated => identifier "{identifier}" and '
                        f'certificate leaf = H"{expected}"'
                    )
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                package_macos.sign_packaged_app(app, framework, expected)

        self.assertIn((package_macos.CODESIGN, "-d", "-r-", str(app)), commands)
        self.assertIn((package_macos.CODESIGN, "-d", "-r-", str(framework)), commands)

    def test_sign_packaged_app_rejects_framework_requirement_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            (framework / "Versions" / "A").mkdir(parents=True)
            expected = package_macos.EXPECTED_SIGNING_LEAF_SHA1

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                if command == (package_macos.CODESIGN, "-d", "-r-", str(app)):
                    return (
                        'designated => identifier "dev.telemachus.display" and '
                        f'certificate leaf = H"{expected}"'
                    )
                if command == (package_macos.CODESIGN, "-d", "-r-", str(framework)):
                    return (
                        'designated => identifier "org.webmproject.webrtc" and '
                        'certificate leaf = H"B55280E7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"'
                    )
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                with self.assertRaisesRegex(SystemExit, r"WebRTC\.framework.*expected"):
                    package_macos.sign_packaged_app(app, framework, expected)

    def test_sign_packaged_app_ad_hoc_verifies_designated_requirement_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "Vibe Screen.app"
            framework = app / "Contents" / "Frameworks" / "WebRTC.framework"
            (framework / "Versions" / "A").mkdir(parents=True)
            commands: list[tuple[str, ...]] = []

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                if command == (package_macos.CODESIGN, "-d", "-r-", str(app)):
                    return 'designated => identifier "dev.telemachus.display" and anchor apple generic'
                if command == (package_macos.CODESIGN, "-d", "-r-", str(framework)):
                    return 'designated => identifier "org.webrtc.WebRTC" and anchor apple generic'
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                package_macos.sign_packaged_app(app, framework, "-")

        self.assertIn((package_macos.CODESIGN, "-d", "-r-", str(app)), commands)
        self.assertIn((package_macos.CODESIGN, "-d", "-r-", str(framework)), commands)

    def test_verify_reproducible_zip_rechecks_extracted_app_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            (app / "Contents").mkdir(parents=True)
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)

            with (
                mock.patch.object(package_macos, "run", return_value=""),
                mock.patch.object(
                    package_macos,
                    "verify_packaged_app_certificate_contracts",
                    side_effect=SystemExit("wrong app leaf"),
                ) as contract_mock,
            ):
                with self.assertRaisesRegex(SystemExit, "wrong app leaf"):
                    package_macos.verify_reproducible_zip(
                        archive,
                        "Vibe Screen.app",
                        sign_identity=package_macos.EXPECTED_SIGNING_LEAF_SHA1,
                    )

        self.assertEqual(Path(contract_mock.call_args.args[0]).name, "Vibe Screen.app")

    def test_verify_reproducible_zip_without_sign_identity_skips_certificate_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            (app / "Contents").mkdir(parents=True)
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)

            with (
                mock.patch.object(package_macos, "run", return_value=""),
                mock.patch.object(package_macos, "verify_packaged_app_certificate_contracts") as contract_mock,
            ):
                package_macos.verify_reproducible_zip(archive, "Vibe Screen.app")

        contract_mock.assert_not_called()

    def test_verify_reproducible_zip_extracts_and_strict_verifies_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            (app / "Contents" / "_CodeSignature").mkdir(parents=True)
            with (app / "Contents" / "_CodeSignature" / "CodeResources").open("wb") as code_resources:
                plistlib.dump({"files": {"Contents/MacOS/Vibe Screen": {"hash": b"stable"}}}, code_resources)
            framework_version = app / "Contents" / "Frameworks" / "WebRTC.framework" / "Versions" / "A"
            framework_version.mkdir(parents=True)
            (framework_version / "WebRTC").write_text("binary", encoding="utf-8")
            (framework_version.parent / "Current").symlink_to("A")
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)
            commands: list[tuple[str, ...]] = []
            observed_symlink_targets: list[str] = []

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                commands.append(command)
                current = Path(command[5]) / "Contents" / "Frameworks" / "WebRTC.framework" / "Versions" / "Current"
                self.assertTrue(current.is_symlink())
                observed_symlink_targets.append(os.readlink(current))
                return ""

            with mock.patch.object(package_macos, "run", side_effect=fake_run):
                package_macos.verify_reproducible_zip(archive, "Vibe Screen.app")

            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[:5], (package_macos.CODESIGN, "--verify", "--deep", "--strict", "--verbose=2"))
            self.assertEqual(Path(command[5]).name, "Vibe Screen.app")
            self.assertEqual(observed_symlink_targets, ["A"])

    def test_verify_reproducible_zip_fails_closed_when_code_resources_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            signature_dir = app / "Contents" / "_CodeSignature"
            signature_dir.mkdir(parents=True)
            (signature_dir / "CodeResources").write_text("not a plist", encoding="utf-8")
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)

            with mock.patch.object(package_macos, "run") as run_mock:
                with self.assertRaisesRegex(SystemExit, "unreadable or malformed"):
                    package_macos.verify_reproducible_zip(archive, "Vibe Screen.app")

        run_mock.assert_not_called()

    def test_extract_reproducible_zip_rejects_path_traversal_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "Vibe-Screen.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escaped.txt", "escape")

            with self.assertRaisesRegex(SystemExit, "archive contains unsafe path"):
                package_macos.extract_reproducible_zip(archive, root / "extract")

    def test_extract_reproducible_zip_rejects_unsafe_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases = {
                "absolute": ("/tmp/outside", "archive symlink target is absolute"),
                "escaping": ("../../../outside", "archive symlink target escapes extraction root"),
            }
            for name, (link_target, expected_error) in cases.items():
                with self.subTest(name=name):
                    archive = root / f"{name}.zip"
                    info = zipfile.ZipInfo("Vibe Screen.app/Contents/link")
                    info.create_system = 3
                    info.external_attr = (package_macos.stat.S_IFLNK | 0o777) << 16
                    with zipfile.ZipFile(archive, "w") as bundle:
                        bundle.writestr(info, link_target)

                    with self.assertRaisesRegex(SystemExit, expected_error):
                        package_macos.extract_reproducible_zip(archive, root / f"extract-{name}")

    def test_verify_reproducible_zip_fails_closed_when_extracted_app_has_codesign_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            resource = app / "Contents" / "Resources"
            resource.mkdir(parents=True)
            (resource / "Credits.html.cstemp").write_text("stale", encoding="utf-8")
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)

            with mock.patch.object(package_macos, "run", return_value=""):
                with self.assertRaisesRegex(SystemExit, "Credits.html.cstemp"):
                    package_macos.verify_reproducible_zip(archive, "Vibe Screen.app")

    def test_verify_reproducible_zip_fails_closed_when_code_resources_seals_removed_cstemp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = root / "Vibe Screen.app"
            signature_dir = (
                app
                / "Contents"
                / "Frameworks"
                / "WebRTC.framework"
                / "Versions"
                / "A"
                / "_CodeSignature"
            )
            signature_dir.mkdir(parents=True)
            with (signature_dir / "CodeResources").open("wb") as code_resources:
                plistlib.dump({"files": {"WebRTC.cstemp": {"hash": b"stale"}}}, code_resources)
            archive = root / "Vibe-Screen.zip"
            package_macos.create_reproducible_zip(app, archive)

            with mock.patch.object(package_macos, "run") as run_mock:
                with self.assertRaisesRegex(SystemExit, r"CodeResources.*WebRTC\.cstemp"):
                    package_macos.verify_reproducible_zip(archive, "Vibe Screen.app")

        run_mock.assert_not_called()

    def test_main_delegates_final_signing_to_packaged_app_signer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "artifacts"
            binary_dir = Path(temporary_directory) / "build"
            executable = binary_dir / package_macos.EXECUTABLE_NAME
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"binary")
            framework = binary_dir / package_macos.WEBRTC_FRAMEWORK_NAME
            (framework / "Versions" / "A").mkdir(parents=True)
            bundle_notice = (
                binary_dir
                / package_macos.RESOURCE_BUNDLE_NAME
                / "ThirdParty"
                / NOTICE_RELATIVE_PATH.name
            )
            bundle_notice.parent.mkdir(parents=True)
            bundle_notice.write_text("notice", encoding="utf-8")
            arguments = argparse.Namespace(
                version="1.2.3",
                output_dir=output_dir,
                sign_identity="Vibe Screen Dev",
                sign_identity_explicit=False,
            )

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                resolved_app = output_dir.resolve() / "Vibe Screen.app"
                if command == ("strip", "-S", str(resolved_app / "Contents" / "MacOS" / "Vibe Screen")):
                    return ""
                if command == ("swift", "build", "-c", "release", "-Xswiftc", "-file-prefix-map", "-Xswiftc", f"{package_macos.REPOSITORY_ROOT}=."):
                    return ""
                if command == (
                    "swift",
                    "build",
                    "-c",
                    "release",
                    "-Xswiftc",
                    "-file-prefix-map",
                    "-Xswiftc",
                    f"{package_macos.REPOSITORY_ROOT}=.",
                    "--show-bin-path",
                ):
                    return str(binary_dir)
                raise AssertionError(command)

            with (
                mock.patch.object(package_macos, "parse_args", return_value=arguments),
                mock.patch.object(package_macos, "resolve_sign_identity", return_value="Vibe Screen Dev"),
                mock.patch.object(package_macos, "validate_notice_bundle"),
                mock.patch.object(
                    package_macos,
                    "collect_source_identity",
                    return_value=package_macos.SourceIdentity(commit="a" * 40, tree="b" * 40, dirty=False),
                ),
                mock.patch.object(
                    package_macos,
                    "read_source_plist",
                    return_value={"CFBundleShortVersionString": "1.2.3", "CFBundleIdentifier": "dev.telemachus.display"},
                ),
                mock.patch.object(package_macos, "run", side_effect=fake_run),
                mock.patch.object(package_macos, "sign_packaged_app") as sign_mock,
                mock.patch.object(package_macos, "verify_reproducible_zip") as verify_archive_mock,
            ):
                self.assertEqual(package_macos.main(), 0)

            sign_mock.assert_called_once_with(
                output_dir.resolve() / "Vibe Screen.app",
                output_dir.resolve() / "Vibe Screen.app" / "Contents" / "Frameworks" / "WebRTC.framework",
                "Vibe Screen Dev",
            )
            verify_archive_mock.assert_called_once_with(
                output_dir.resolve() / f"Vibe-Screen-macos-1.2.3-{package_macos.platform.machine()}.zip",
                "Vibe Screen.app",
                sign_identity="Vibe Screen Dev",
            )

    def test_main_marks_explicit_ad_hoc_preview_as_not_for_tcc_or_device_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory) / "artifacts"
            binary_dir = Path(temporary_directory) / "build"
            executable = binary_dir / package_macos.EXECUTABLE_NAME
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"binary")
            framework = binary_dir / package_macos.WEBRTC_FRAMEWORK_NAME
            (framework / "Versions" / "A").mkdir(parents=True)
            bundle_notice = (
                binary_dir
                / package_macos.RESOURCE_BUNDLE_NAME
                / "ThirdParty"
                / NOTICE_RELATIVE_PATH.name
            )
            bundle_notice.parent.mkdir(parents=True)
            bundle_notice.write_text("notice", encoding="utf-8")
            arguments = argparse.Namespace(
                version="1.2.3",
                output_dir=output_dir,
                sign_identity="-",
                sign_identity_explicit=True,
            )

            def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
                resolved_app = output_dir.resolve() / "Vibe Screen.app"
                if command == ("strip", "-S", str(resolved_app / "Contents" / "MacOS" / "Vibe Screen")):
                    return ""
                if command == ("swift", "build", "-c", "release", "-Xswiftc", "-file-prefix-map", "-Xswiftc", f"{package_macos.REPOSITORY_ROOT}=."):
                    return ""
                if command == (
                    "swift",
                    "build",
                    "-c",
                    "release",
                    "-Xswiftc",
                    "-file-prefix-map",
                    "-Xswiftc",
                    f"{package_macos.REPOSITORY_ROOT}=.",
                    "--show-bin-path",
                ):
                    return str(binary_dir)
                raise AssertionError(command)

            with (
                mock.patch.object(package_macos, "parse_args", return_value=arguments),
                mock.patch.object(package_macos, "resolve_sign_identity", return_value="-"),
                mock.patch.object(package_macos, "validate_notice_bundle"),
                mock.patch.object(
                    package_macos,
                    "collect_source_identity",
                    return_value=package_macos.SourceIdentity(commit="a" * 40, tree="b" * 40, dirty=False),
                ),
                mock.patch.object(
                    package_macos,
                    "read_source_plist",
                    return_value={"CFBundleShortVersionString": "1.2.3", "CFBundleIdentifier": "dev.telemachus.display"},
                ),
                mock.patch.object(package_macos, "run", side_effect=fake_run),
                mock.patch.object(package_macos, "sign_packaged_app"),
                mock.patch.object(package_macos, "verify_reproducible_zip"),
                redirect_stderr(StringIO()) as stderr,
            ):
                self.assertEqual(package_macos.main(), 0)

            notice = output_dir.resolve() / "Vibe Screen.app" / "Contents" / "Resources" / package_macos.AD_HOC_PREVIEW_NOTICE_NAME
            self.assertTrue(notice.is_file())
            self.assertIn("must not be used for macOS TCC", notice.read_text(encoding="utf-8"))
            self.assertIn("ad-hoc signed macOS preview", stderr.getvalue())

    def test_host_report_marks_tcc_rows_unavailable_when_database_read_fails(self) -> None:
        report = macos_dev_host.format_report(
            metadata=None,
            permissions=macos_dev_host.PermissionStatus(
                database_path="<user-tcc-db>",
                rows=(),
                readable=False,
                error="unable to open database file",
            ),
            errors=["cannot verify TCC permissions read-only: unable to open database file"],
        )

        self.assertIn("(TCC rows unavailable: unable to open database file)", report)
        self.assertNotIn("(no matching rows)", report)


class PrepareReleaseTests(unittest.TestCase):
    def command(self, *extra: str) -> list[str]:
        return [
            "python3",
            str(PREPARE_SCRIPT),
            "--version",
            VERSION,
            "--tag",
            TAG,
            "--commit",
            COMMIT,
            "--created",
            CREATED,
            *extra,
        ]

    def write_artifacts(self, artifacts: Path, *, archive_content: bytes = b"binary") -> None:
        artifacts.mkdir()
        for name in (
            f"Vibe-Screen-macos-{VERSION}-arm64.zip",
            f"Vibe-Screen-android-{VERSION}-debug.apk",
            f"VibeScreen-ios-simulator-{VERSION}.zip",
        ):
            with zipfile.ZipFile(artifacts / name, "w") as archive:
                archive.writestr("payload.bin", archive_content)
        (artifacts / "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md").write_text(
            "# licenses\nGenerated from `debugRuntimeClasspath`.\n",
            encoding="utf-8",
        )
        (artifacts / "android-runtime.spdx.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "SPDXID": "SPDXRef-Package-example",
                            "name": "example:runtime:1.0.0",
                            "versionInfo": "1.0.0",
                            "downloadLocation": "NOASSERTION",
                            "licenseConcluded": "Apache-2.0",
                            "licenseDeclared": "Apache-2.0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_validation_rejects_prerelease_tag(self) -> None:
        command = self.command("--validate-only")
        command[command.index(VERSION)] = "1.2.3-rc.1"
        command[command.index(TAG)] = "v1.2.3-rc.1"
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable SemVer", result.stderr)

    def test_validation_rejects_android_version_code_collision(self) -> None:
        command = self.command("--validate-only")
        command[command.index(VERSION)] = "1.100.0"
        command[command.index(TAG)] = "v1.100.0"
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most 99", result.stderr)

    def test_macos_packaging_notice_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(FileNotFoundError, "notice bundle is missing"):
                validate_notice_bundle(root)
            notice = root / NOTICE_RELATIVE_PATH
            notice.parent.mkdir(parents=True)
            notice.write_text("incomplete notice", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                validate_notice_bundle(root)

        with mock.patch.object(
            generate_webrtc_m150_notices,
            "SOURCES",
            generate_webrtc_m150_notices.SOURCES[:-1],
        ):
            with self.assertRaisesRegex(ValueError, "exactly 32 components"):
                validate_notice_bundle(REPOSITORY_ROOT)
        altered_sources = list(generate_webrtc_m150_notices.SOURCES)
        altered_sources[0] = (*altered_sources[0][:-1], "abseil-cpp/NOTICE")
        with mock.patch.object(generate_webrtc_m150_notices, "SOURCES", tuple(altered_sources)):
            with self.assertRaisesRegex(ValueError, "source manifest SHA-256 mismatch"):
                validate_notice_bundle(REPOSITORY_ROOT)

    def test_release_notice_archive_fails_when_m150_bundle_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with mock.patch.object(prepare_release, "REPOSITORY_ROOT", root):
                with self.assertRaisesRegex(FileNotFoundError, "notice bundle is missing"):
                    prepare_release.write_notices_archive(
                        VERSION,
                        root / "artifacts",
                        root / "notices.zip",
                    )

    def test_prepare_generates_complete_release_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            output = root / "output"
            self.write_artifacts(artifacts)

            prepare_command = self.command("--artifacts-dir", str(artifacts), "--output-dir", str(output))
            subprocess.run(prepare_command, check=True, capture_output=True, text=True)
            subprocess.run(prepare_command, check=True, capture_output=True, text=True)

            checksum_lines = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(checksum_lines, sorted(checksum_lines, key=lambda line: line.split("  ", 1)[1]))
            self.assertEqual(len(checksum_lines), 5)
            sbom = json.loads((output / f"vibe-screen-{VERSION}.spdx.json").read_text(encoding="utf-8"))
            self.assertEqual(sbom["creationInfo"]["created"], "2026-08-05T02:00:00Z")
            package_names = {package["name"] for package in sbom["packages"]}
            self.assertTrue({"example:runtime:1.0.0", "webrtc", "swift-protobuf"} <= package_names)
            self.assertIn("boringssl", package_names)
            self.assertIn("libsrtp", package_names)
            component_packages = [
                package
                for package in sbom["packages"]
                if package["SPDXID"].startswith("SPDXRef-Package-webrtc-m150-component-")
            ]
            self.assertEqual(len(component_packages), 32)
            self.assertEqual(
                [package["name"] for package in sbom["packages"]].count("swift-protobuf"),
                1,
            )
            self.assertTrue(all(package["filesAnalyzed"] is False for package in sbom["packages"]))
            contains = [
                relationship
                for relationship in sbom["relationships"]
                if relationship["relationshipType"] == "CONTAINS"
            ]
            self.assertEqual(len(contains), 32)
            self.assertTrue(all(item["spdxElementId"] == "SPDXRef-Package-webrtc" for item in contains))
            notices = output / f"vibe-screen-{VERSION}-notices.zip"
            with zipfile.ZipFile(notices) as archive:
                suffix = NOTICE_RELATIVE_PATH.as_posix()
                self.assertTrue(any(name.endswith(suffix) for name in archive.namelist()))
            notes = (output / "RELEASE_NOTES.md").read_text(encoding="utf-8")
            self.assertIn(f"Vibe Screen {VERSION}", notes)
            self.assertNotIn("{{", notes)

    def test_prepare_rejects_secret_inside_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(
                artifacts,
                archive_content=b'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"',
            )

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("privacy/secret scan failed", result.stderr)
            self.assertIn("payload.bin", result.stderr)

    def test_prepare_rejects_private_user_path_inside_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts, archive_content=b"/home/release-runner/private/file")

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("user_absolute_path", result.stderr)

    def test_prepare_rejects_secret_in_final_sbom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts)
            sbom_path = artifacts / "android-runtime.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            sbom["packages"][0]["api_token"] = "0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"
            sbom_path.write_text(json.dumps(sbom), encoding="utf-8")

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"vibe-screen-{VERSION}.spdx.json", result.stderr)

    def test_prepare_rejects_secret_in_final_notices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts)
            (artifacts / "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md").write_text(
                'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"vibe-screen-{VERSION}-notices.zip", result.stderr)

    def test_release_scan_distinguishes_compiled_literals_from_sensitive_values(self) -> None:
        compiled_literals = (
            b"token=\x00\x01"
            b'\x00"signaling_token":"device-token-abcdefghijklmnopqrstuvwxyz"'
            b'\x00"credential":"turn-password"'
            b'\x00"signaling_url":"https://signal.example.test"'
        )
        self.assertEqual(prepare_release.release_scan_findings(compiled_literals), {})

        findings = prepare_release.release_scan_findings(
            b'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"'
        )
        self.assertIn("credential_material", findings)
        unquoted_findings = prepare_release.release_scan_findings(
            b"api_token=0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"
        )
        self.assertIn("credential_material", unquoted_findings)

    def test_release_scan_rejects_hardware_identifier_and_uncontrolled_endpoint(self) -> None:
        findings = prepare_release.release_scan_findings(
            b'{"hardware_serial":"C02REALSECRET",'
            b'"signaling_url":"https://signal.private.invalid"}'
        )
        self.assertIn("hardware_identifier", findings)
        self.assertIn("endpoint", findings)

    def test_evidence_privacy_scan_accepts_redacted_serial_placeholders(self) -> None:
        findings = scan_phase3_evidence_content(
            b'{"adb_serial":"<redacted-adb-serial>",'
            b'"hardware_serial":"[redacted-device-serial]"}'
        )

        self.assertNotIn("hardware_identifier", findings)

    def test_release_scan_rejects_windows_user_path(self) -> None:
        findings = prepare_release.release_scan_findings(
            b"C:\\Users\\random-user\\private.bin"
        )
        self.assertIn("user_absolute_path", findings)

    def test_macos_release_build_remaps_source_paths(self) -> None:
        package_script = (REPOSITORY_ROOT / "scripts/package_macos.py").read_text(encoding="utf-8")
        makefile = MAKEFILE.read_text(encoding="utf-8")
        phase3_source_artifacts = PHASE3_SOURCE_ARTIFACTS.read_text(encoding="utf-8")
        self.assertIn('"-file-prefix-map"', package_script)
        self.assertIn(
            'SWIFT_RELEASE_FILE_PREFIX_MAP := -Xswiftc -file-prefix-map -Xswiftc "$(realpath $(CURDIR))=."',
            makefile,
        )
        self.assertIn(
            "swift build -c release $(SWIFT_RELEASE_FILE_PREFIX_MAP)",
            makefile,
        )
        self.assertIn(
            "swift build -c release $(SWIFT_RELEASE_FILE_PREFIX_MAP) --show-bin-path",
            makefile,
        )
        self.assertIn("repo_root = repo_root.resolve()", phase3_source_artifacts)
        self.assertIn('swift_path_map = f"{repo_root}=."', phase3_source_artifacts)
        self.assertIn('"-file-prefix-map"', phase3_source_artifacts)
        self.assertIn('swift_path_map,', phase3_source_artifacts)
        self.assertIn('PRODUCT_NAME = "Vibe Screen"', package_script)
        self.assertIn('EXECUTABLE_NAME = PRODUCT_NAME', package_script)
        self.assertIn('SOURCE_COMMIT_PLIST_KEY = "VibeScreenSourceCommit"', package_script)
        self.assertIn('SOURCE_TREE_PLIST_KEY = "VibeScreenSourceTree"', package_script)
        self.assertIn('SOURCE_DIRTY_PLIST_KEY = "VibeScreenSourceDirty"', package_script)
        self.assertIn("if source_identity.dirty:", package_script)
        self.assertIn("refusing to package macOS Host from a dirty source tree", package_script)
        self.assertIn("require_no_codesign_resource_seal_temporary_references", package_script)
        self.assertIn('run("strip", "-S", str(macos_dir / EXECUTABLE_NAME))', package_script)
        self.assertIn('SIGN_IDENTITY_ENV = "VIBE_SCREEN_SIGN_IDENTITY"', package_script)
        self.assertNotIn("TELEMACHUS_SIGN_IDENTITY", package_script)
        phase0_workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "python3 scripts/package_macos.py --sign-identity -",
            phase0_workflow,
        )
        self.assertIn(
            'python3 scripts/package_macos.py --version "$RELEASE_VERSION" --sign-identity -',
            release_workflow,
        )
        release_macos_job = workflow_job_body(release_workflow, "macos")
        self.assertIn("timeout-minutes: 30", release_macos_job)
        self.assertIn('RELEASE_COMMIT: ${{ needs.validate.outputs.commit }}', release_macos_job)
        self.assertIn("Print :CFBundleIdentifier", release_macos_job)
        self.assertIn('= "dev.telemachus.display"', release_macos_job)
        self.assertIn("Print :VibeScreenSourceCommit", release_macos_job)
        self.assertIn('= "$RELEASE_COMMIT"', release_macos_job)
        self.assertIn("Print :VibeScreenSourceDirty", release_macos_job)
        self.assertIn('= "false"', release_macos_job)
        self.assertIn("name: vibe-screen-macos-ad-hoc-signed", phase0_workflow)
        self.assertNotIn(
            "#filePath",
            (REPOSITORY_ROOT / "baseline/MacHost/Sources/ProtocolV1SelfTest.swift").read_text(
                encoding="utf-8"
            ),
        )

    def test_bundled_plist_embeds_source_identity(self) -> None:
        plist = package_macos.bundled_plist(
            {"CFBundleIdentifier": "dev.telemachus.display"},
            "1.2.3",
            package_macos.SourceIdentity(
                commit="a" * 40,
                tree="b" * 40,
                dirty=False,
            ),
        )

        self.assertEqual(plist["CFBundleExecutable"], "Vibe Screen")
        self.assertEqual(plist["CFBundleVersion"], "1.2.3")
        self.assertEqual(plist["VibeScreenSourceCommit"], "a" * 40)
        self.assertEqual(plist["VibeScreenSourceTree"], "b" * 40)
        self.assertIs(plist["VibeScreenSourceDirty"], False)

    def test_collect_source_identity_reads_commit_tree_and_dirty_state(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run(*command: str, cwd: Path | None = None, timeout: float | None = None) -> str:
            calls.append(command)
            if command == ("git", "rev-parse", "HEAD"):
                return "a" * 40
            if command == ("git", "rev-parse", "HEAD^{tree}"):
                return "b" * 40
            if command == ("git", "status", "--porcelain"):
                return " M README.md"
            raise AssertionError(command)

        with mock.patch.object(package_macos, "run", side_effect=fake_run):
            identity = package_macos.collect_source_identity(Path("repo"))

        self.assertEqual(identity.commit, "a" * 40)
        self.assertEqual(identity.tree, "b" * 40)
        self.assertTrue(identity.dirty)
        self.assertEqual(
            calls,
            [
                ("git", "rev-parse", "HEAD"),
                ("git", "rev-parse", "HEAD^{tree}"),
                ("git", "status", "--porcelain"),
            ],
        )

    def test_release_workflow_binds_tag_to_all_successful_main_gates_and_debug_audit(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('test "$commit" = "$(git rev-parse refs/remotes/origin/main)"', workflow)
        self.assertNotIn("merge-base --is-ancestor", workflow)

        validate_job_match = re.search(
            r"(?ms)^  validate:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(validate_job_match)
        validate_job = validate_job_match.group("body")
        permissions_match = re.search(
            r"(?ms)^    permissions:\n(?P<body>(?:^      [a-z-]+: [a-z]+\n)+)",
            validate_job,
        )
        self.assertIsNotNone(permissions_match)
        validate_permissions = dict(
            line.strip().split(": ", 1)
            for line in permissions_match.group("body").splitlines()
        )
        self.assertEqual(
            validate_permissions,
            {"actions": "read", "contents": "read"},
        )

        self.assertEqual(validate_job.count("require_successful_main_run()"), 1)
        helper_contracts = (
            '"repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow}/runs"',
            "-f branch=main",
            "-f event=push",
            "-f status=success",
            'select(.head_sha == \\"$commit\\")',
        )
        for contract in helper_contracts:
            self.assertIn(contract, validate_job)
        gate_calls = set(
            re.findall(
                r'^          require_successful_main_run ([a-z0-9.]+) "([^"]+)"$',
                validate_job,
                flags=re.MULTILINE,
            )
        )
        self.assertEqual(
            gate_calls,
            {
                ("phase0.yml", "Phase 0 checks"),
                ("ios.yml", "iOS engineering gates"),
                ("harmony.yml", "HarmonyOS portable checks"),
            },
        )
        self.assertIn("-PdependencyAuditConfiguration=debugRuntimeClasspath", workflow)
        android_build = ANDROID_BUILD.read_text(encoding="utf-8")
        self.assertIn('getByName(dependencyAuditConfiguration)', android_build)
        self.assertIn('inputs.property("dependencyAuditConfiguration"', android_build)

    def test_macos_and_ios_jobs_have_timeout_headroom(self) -> None:
        phase0_workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        ios_workflow = IOS_WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(workflow_job_timeout(phase0_workflow, "macos"), 40)
        self.assertEqual(workflow_job_timeout(release_workflow, "macos"), 30)
        self.assertEqual(workflow_job_timeout(release_workflow, "ios-simulator"), 30)
        self.assertEqual(workflow_job_timeout(ios_workflow, "core"), 40)
        self.assertEqual(workflow_job_timeout(ios_workflow, "app-build-test-archive"), 30)

    def test_phase0_android_job_builds_instrumentation_test_apk(self) -> None:
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        android_job_match = re.search(
            r"(?ms)^  android:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(android_job_match)
        android_job = android_job_match.group("body")

        baseline_gate = "- run: make baseline-android-check"
        instrumentation_gate = (
            "- name: Build Android instrumentation test APK\n"
            "        run: cd baseline/AndroidClient && ./gradlew assembleDebugAndroidTest"
        )
        self.assertIn(baseline_gate, android_job)
        self.assertIn(instrumentation_gate, android_job)
        self.assertLess(android_job.index(baseline_gate), android_job.index(instrumentation_gate))
        self.assertEqual(android_job.count("assembleDebugAndroidTest"), 1)
        self.assertNotIn("connectedDebugAndroidTest", android_job)
        self.assertNotRegex(
            android_job,
            r"(?m)^\s*(?:-\s+)?(?:run:\s*)?(?:\S*/)?adb(?:\.exe)?(?:\s|$)",
        )
        for forbidden_device_operation in (
            "am instrument",
            "adb -s",
            "adb shell",
            "force-stop",
            "uninstall dev.telemachus.display.test",
            "reverse tcp:54321",
        ):
            with self.subTest(forbidden_device_operation=forbidden_device_operation):
                self.assertNotIn(forbidden_device_operation, android_job)

    def test_phase3_gate_discovers_current_and_legacy_runner_tests(self) -> None:
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn("run: make phase3-test", workflow)
        for discovery in (
            "python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v",
            "python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v",
        ):
            self.assertEqual(makefile.count(discovery), 1)
        runner = PHASE3_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("print(peer_output", runner)
        self.assertIn("print_success_summary(arguments.mode, arguments.slice)", runner)

    def test_baseline_macos_test_fails_closed_before_swiftpm_xctest(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("baseline-macos-xctest-preflight:", makefile)
        self.assertIn("baseline-macos-permission-prompt-contract:", makefile)
        self.assertIn("baseline-macos-host-cli-contract:", makefile)
        self.assertIn("baseline-macos-launch:", makefile)
        self.assertIn(
            "\tswift scripts/verify_macos_permission_prompt_contract.swift",
            makefile,
        )
        self.assertIn(
            "\tswift scripts/verify_macos_host_cli_contract.swift",
            makefile,
        )
        self.assertIn("\tbaseline-macos-xctest-preflight \\", makefile)
        self.assertIn("\tbaseline-macos-permission-prompt-contract \\", makefile)
        self.assertIn("\tbaseline-macos-host-cli-contract \\", makefile)
        self.assertIn("python3 scripts/macos_dev_host.py xctest-preflight", makefile)
        self.assertIn("python3 scripts/macos_dev_host.py launch", makefile)
        self.assertRegex(
            makefile,
            r"(?m)^baseline-macos-test: baseline-macos-permission-prompt-contract baseline-macos-host-cli-contract baseline-macos-xctest-preflight$",
        )
        self.assertRegex(
            makefile,
            r"(?m)^baseline-macos-self-test: baseline-macos-build baseline-macos-permission-prompt-contract$",
        )
        self.assertIn(
            "swift build -c release $(SWIFT_RELEASE_FILE_PREFIX_MAP) --show-bin-path",
            makefile,
        )
        self.assertNotIn(
            '"baseline/MacHost/.build/release/Vibe Screen" --host-self-test',
            makefile,
        )

        phase0_workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("- run: make baseline-macos-permission-prompt-contract", phase0_workflow)
        self.assertIn("make baseline-macos-permission-prompt-contract", release_workflow)
        self.assertLess(
            phase0_workflow.index("- run: make baseline-macos-permission-prompt-contract"),
            phase0_workflow.index("- run: make baseline-macos-test"),
        )
        self.assertLess(
            release_workflow.index("make baseline-macos-permission-prompt-contract"),
            release_workflow.index("make baseline-macos-test"),
        )

    def test_current_macos_host_docs_do_not_bypass_guarded_launcher(self) -> None:
        docs = list(CURRENT_HOST_LAUNCH_DOCS)
        for pattern in CURRENT_HOST_LAUNCH_DOC_GLOBS:
            docs.extend(REPOSITORY_ROOT.glob(pattern))

        violations: list[str] = []
        for path in sorted(set(docs)):
            relative = path.relative_to(REPOSITORY_ROOT)
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for label, pattern in FORBIDDEN_HOST_LAUNCH_LINE_PATTERNS:
                    if pattern.search(line) and not OFFLINE_HOST_SELF_TEST_FLAG_PATTERN.search(line):
                        violations.append(f"{relative}:{line_number}: {label}: {line.strip()}")

        self.assertEqual([], violations)

    def test_host_launching_make_targets_and_scripts_use_guarded_launcher(self) -> None:
        inspected_files = [MAKEFILE]
        inspected_files.extend(
            path
            for suffix in ("*.py", "*.sh")
            for path in (REPOSITORY_ROOT / "scripts").rglob(suffix)
            if "tests" not in path.relative_to(REPOSITORY_ROOT).parts
        )

        violations: list[str] = []
        for path in sorted(set(inspected_files)):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(REPOSITORY_ROOT)
            for line_number, line in enumerate(text.splitlines(), start=1):
                for label, pattern in FORBIDDEN_HOST_LAUNCH_LINE_PATTERNS:
                    if pattern.search(line) and not OFFLINE_HOST_SELF_TEST_FLAG_PATTERN.search(line):
                        violations.append(f"{relative}:{line_number}: {label}: {line.strip()}")
            for label, pattern in FORBIDDEN_HOST_LAUNCH_SCRIPT_PATTERNS:
                for match in pattern.finditer(text):
                    line_number = text.count("\n", 0, match.start()) + 1
                    line = text.splitlines()[line_number - 1]
                    if OFFLINE_HOST_SELF_TEST_FLAG_PATTERN.search(line):
                        continue
                    violations.append(f"{relative}:{line_number}: {label}: {match.group(0)}")

        self.assertEqual([], violations)

    def test_host_display_rotation_gate_make_target_runs_formal_verifier(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^host-display-rotation-gate:")
        self.assertIn(
            "python3 -m vibescreen_evidence.host_display_rotation_gate",
            makefile,
        )
        self.assertIn(
            '"$(EVIDENCE_DIR)/host-display-rotation.json" --check-artifacts',
            makefile,
        )
        self.assertIn(
            '--output "$(EVIDENCE_DIR)/host-display-rotation-gate.json"',
            makefile,
        )

    def test_phase0_macos_job_gates_local_synthetic_product_direct_and_forced_relay_e2e(
        self,
    ) -> None:
        self.assertEqual(
            SUPPORTED_COTURN_VERSIONS,
            ("4.15.0", "4.16.0", "4.17.0", "4.17.2"),
        )
        workflow_coturn_versions = "|".join(SUPPORTED_COTURN_VERSIONS)
        makefile_coturn_versions = " ".join(SUPPORTED_COTURN_VERSIONS)
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        macos_job_match = re.search(
            r"(?ms)^  macos:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(macos_job_match)
        macos_job = macos_job_match.group("body")
        for contract in (
            "runs-on: macos-15",
            "timeout-minutes: 40",
            "go-version: 1.25.12",
            'python-version: "3.11"',
            "brew install coturn",
            'turnserver_path="$(brew --prefix coturn)/bin/turnserver"',
            workflow_coturn_versions,
            "Unsupported Homebrew coturn version",
            "Install local Phase 3 synthetic product E2E dependencies",
            "Gate local synthetic Protocol v1 harness direct and forced-relay product E2E",
            "make phase3-local-synthetic-product-e2e",
            'jq -e -s --arg commit "$GITHUB_SHA"',
            ".environment.repository_commit == $commit",
            ".environment.repository_source.dirty == false",
            "id: phase3_synthetic_gate",
            "--output .build/phase3-local-synthetic-product-e2e/public",
            "steps.phase3_synthetic_gate.outcome == 'success'",
            "steps.phase3_synthetic_public_summaries.outcome == 'success'",
            "name: phase3-local-synthetic-product-e2e-public",
            "path: .build/phase3-local-synthetic-product-e2e/public",
            "if-no-files-found: error",
            "--output .build/phase3-local-synthetic-product-e2e/public-failure --failure-diagnostic",
            "steps.phase3_synthetic_gate.outcome == 'failure'",
            "name: phase3-local-synthetic-product-e2e-failure-diagnostic",
            "path: .build/phase3-local-synthetic-product-e2e/public-failure",
            "include-hidden-files: true",
        ):
            self.assertIn(contract, macos_job)
        self.assertNotIn("--allow-missing", macos_job)
        self.assertRegex(
            macos_job,
            r"(?ms)Validate local Phase 3 synthetic product E2E public summaries.*?"
            r"if: \$\{\{ always\(\) && steps\.phase3_synthetic_gate\.outcome == 'success' \}\}.*?"
            r"public_artifacts\.py.*?--output \.build/phase3-local-synthetic-product-e2e/public\s*$",
        )
        self.assertNotIn("make phase3-local-product-e2e", macos_job)
        self.assertNotIn(".build/phase3-local-product-e2e", macos_job)
        self.assertNotRegex(
            macos_job,
            r"(?m)^\s+path: \.build/phase3-local-synthetic-product-e2e\s*$",
        )
        self.assertIn(
            ".build/phase3-local-synthetic-product-e2e/relay.json >/dev/null",
            macos_job,
        )

        makefile = MAKEFILE.read_text(encoding="utf-8")
        for contract in (
            "phase3-local-synthetic-product-e2e:",
            "PHASE3_LOCAL_SYNTHETIC_E2E_DIR ?= "
            ".build/phase3-local-synthetic-product-e2e",
            "PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS ?= 90",
            "phase3-local-product-e2e:",
            "phase3-local-product-e2e is deprecated; use "
            "phase3-local-synthetic-product-e2e",
            "synthetic Protocol v1 harness with real VideoToolbox HEVC "
            "payloads only; no Android device, ScreenCaptureKit capture, "
            "or MediaCodec decode",
            "$(MAKE) phase3-local-synthetic-product-e2e",
            f"PHASE3_COTURN_COMPATIBLE_VERSIONS := {makefile_coturn_versions}",
            "--mode direct --slice product",
            "--mode relay --slice product --skip-build",
            "--diagnostics-dir",
            '--output "$(PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR)"',
            "@jq -e 'select(",
            '.product_session.device == "synthetic Protocol v1 harness"',
            '.product_session.media_source == "videotoolbox-hevc"',
            ".product_session.capture_or_stream_server_started == false",
            '.coturn.forced_libwebrtc_relay == "pass"',
        ):
            self.assertIn(contract, makefile)
        self.assertEqual(makefile.count('json" >/dev/null'), 2)
        self.assertNotIn(".build/phase3-local-product-e2e", makefile)
        self.assertNotIn("PHASE3_LOCAL_E2E_", makefile)


if __name__ == "__main__":
    unittest.main()
