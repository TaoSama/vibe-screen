from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.usb_smoke_preflight import build_document, collect_locks, write_json


class USBSmokePreflightTests(unittest.TestCase):
    def test_ready_document_requires_matching_device_reverse_listener_app_and_host_preflight(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["adb", "-s", "EP0110PZ0B9110300B"]:
                tail = command[3:]
                if tail == ["get-state"]:
                    return subprocess.CompletedProcess(command, 0, "device\n", "")
                if tail == ["shell", "getprop", "ro.product.manufacturer"]:
                    return subprocess.CompletedProcess(command, 0, "nubia\n", "")
                if tail == ["shell", "getprop", "ro.product.model"]:
                    return subprocess.CompletedProcess(command, 0, "P0110\n", "")
                if tail == ["shell", "getprop", "ro.product.device"]:
                    return subprocess.CompletedProcess(command, 0, "pacific\n", "")
                if tail == ["shell", "getprop", "ro.product.name"]:
                    return subprocess.CompletedProcess(command, 0, "pacific\n", "")
                if tail == ["shell", "getprop", "ro.build.version.release"]:
                    return subprocess.CompletedProcess(command, 0, "16\n", "")
                if tail == ["shell", "getprop", "ro.build.version.sdk"]:
                    return subprocess.CompletedProcess(command, 0, "36\n", "")
                if tail == ["shell", "getprop", "ro.build.fingerprint"]:
                    return subprocess.CompletedProcess(command, 0, "nubia/pacific/test\n", "")
                if tail == ["shell", "getprop", "ro.product.cpu.abi"]:
                    return subprocess.CompletedProcess(command, 0, "arm64-v8a\n", "")
                if tail == ["shell", "getprop", "ro.serialno"]:
                    return subprocess.CompletedProcess(command, 0, "EP0110PZ0B9110300B\n", "")
                if tail == ["reverse", "--list"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        "EP0110PZ0B9110300B tcp:54321 tcp:54321\n",
                        "",
                    )
                if tail == ["shell", "pidof", "dev.telemachus.display"]:
                    return subprocess.CompletedProcess(command, 0, "19904\n", "")
                if tail == ["shell", "dumpsys", "window"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        "mCurrentFocus=Window{ dev.telemachus.display/.MainActivity }\n",
                        "",
                    )
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 0, "Vibe 12 TCP 127.0.0.1:54321 (LISTEN)\n", "")
            if command[-3:-1] == ["preflight", "--report"]:
                Path(command[-1]).write_text("Status: PASS\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "macOS Host touch-rerun preflight passed\n", "")
            return subprocess.CompletedProcess(command, 1, "", f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory:
            document = build_document(
                serial="EP0110PZ0B9110300B",
                repository_root=Path("/repo"),
                adb_path="adb",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                package_name="dev.telemachus.display",
                port=54321,
                lock_globs=[str(Path(directory) / "missing-*.lock")],
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                },
                host_preflight_report=Path(directory) / "host.txt",
                command_runner=run,
            )

        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["result"], "ready")
        self.assertEqual(document["blockers"], [])
        self.assertEqual(document["android_device"]["manufacturer"], "nubia")
        self.assertTrue(document["adb_reverse"]["configured"])
        self.assertTrue(document["android_app"]["foreground"])
        self.assertTrue(document["host_listener"]["listening"])
        self.assertTrue(document["host_preflight"]["passed"])

    def test_blocked_document_records_operational_blockers_without_claiming_pass(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["adb", "-s", "EP0110PZ0B9110300B"]:
                tail = command[3:]
                if tail == ["get-state"]:
                    return subprocess.CompletedProcess(command, 0, "device\n", "")
                if tail == ["shell", "getprop", "ro.product.manufacturer"]:
                    return subprocess.CompletedProcess(command, 0, "nubia\n", "")
                if tail == ["shell", "getprop", "ro.product.model"]:
                    return subprocess.CompletedProcess(command, 0, "P0110\n", "")
                if tail == ["shell", "getprop", "ro.product.device"]:
                    return subprocess.CompletedProcess(command, 0, "pacific\n", "")
                if tail == ["shell", "getprop", "ro.product.name"]:
                    return subprocess.CompletedProcess(command, 0, "pacific\n", "")
                if tail == ["shell", "getprop", "ro.build.version.release"]:
                    return subprocess.CompletedProcess(command, 0, "16\n", "")
                if tail == ["shell", "getprop", "ro.build.version.sdk"]:
                    return subprocess.CompletedProcess(command, 0, "36\n", "")
                if tail == ["shell", "getprop", "ro.build.fingerprint"]:
                    return subprocess.CompletedProcess(command, 0, "nubia/pacific/test\n", "")
                if tail == ["shell", "getprop", "ro.product.cpu.abi"]:
                    return subprocess.CompletedProcess(command, 0, "arm64-v8a\n", "")
                if tail == ["shell", "getprop", "ro.serialno"]:
                    return subprocess.CompletedProcess(command, 0, "EP0110PZ0B9110300B\n", "")
                if tail == ["reverse", "--list"]:
                    return subprocess.CompletedProcess(command, 0, "", "")
                if tail == ["shell", "pidof", "dev.telemachus.display"]:
                    return subprocess.CompletedProcess(command, 0, "19904\n", "")
                if tail == ["shell", "dumpsys", "window"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        "mCurrentFocus=Window{ dev.telemachus.display/.MainActivity }\n",
                        "",
                    )
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            if command[-3:-1] == ["preflight", "--report"]:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    "codesign identity 'Vibe Screen Dev' not found in the keychain.\n",
                )
            return subprocess.CompletedProcess(command, 1, "", f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as directory:
            document = build_document(
                serial="EP0110PZ0B9110300B",
                repository_root=Path("/repo"),
                adb_path="adb",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                package_name="dev.telemachus.display",
                port=54321,
                lock_globs=[str(Path(directory) / "missing-*.lock")],
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                },
                host_preflight_report=Path(directory) / "host.txt",
                command_runner=run,
            )

        self.assertEqual(document["result"], "blocked")
        joined = "\n".join(document["blockers"])
        self.assertIn("ADB reverse tcp:54321 -> tcp:54321 is not configured", joined)
        self.assertIn("Mac Host is not listening on TCP 54321", joined)
        self.assertIn("Vibe Screen Dev", joined)
        self.assertTrue(document["safety"]["read_only"])
        self.assertFalse(document["safety"]["starts_host"])

    def test_lock_blocks_android_probes(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            if command[-3:-1] == ["preflight", "--report"]:
                return subprocess.CompletedProcess(command, 0, "macOS Host touch-rerun preflight passed\n", "")
            return subprocess.CompletedProcess(command, 1, "", "unexpected adb probe")

        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            document = build_document(
                serial="EP0110PZ0B9110300B",
                repository_root=Path("/repo"),
                adb_path="adb",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                package_name="dev.telemachus.display",
                port=54321,
                lock_globs=[str(Path(directory) / "vibe-screen-*.lock")],
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                },
                host_preflight_report=Path(directory) / "host.txt",
                command_runner=run,
            )

        self.assertEqual(document["locks"], [str(lock)])
        self.assertIsNone(document["android_device"])
        self.assertFalse(any(command[:1] in (["adb"], ["lsof"]) for command in commands))
        self.assertIn("device lease lock is present", "\n".join(document["blockers"]))

    def test_collect_locks_sorts_and_deduplicates_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "vibe-screen-a.lock"
            second = Path(directory) / "vibe-screen-b.lock"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")

            locks = collect_locks([str(Path(directory) / "vibe-screen-*.lock"), str(first)])

        self.assertEqual(locks, [str(first), str(second)])

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight" / "usb.json"
            write_json(path, {"result": "blocked"})
            self.assertEqual(json.loads(path.read_text()), {"result": "blocked"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
