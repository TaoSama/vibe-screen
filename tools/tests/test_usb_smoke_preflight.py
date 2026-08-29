from __future__ import annotations

import json
import getpass
import subprocess
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.usb_smoke_preflight import (
    build_document,
    collect_locks,
    sanitize_lock_path,
    host_process_identity_matches,
    main,
    parse_lsof_listener_pids,
    sanitize_public_document,
    sanitize_public_text_file,
    sanitize_public_value,
    write_json,
)


SERIAL = "REDACTED_P0110_USB_SERIAL"
LOCAL_TEST_SERIAL = "LOCAL_TEST_P0110_USB_SERIAL"
PACKAGE = "dev.telemachus.display"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "usb-smoke-preflight.schema.json"


class USBSmokePreflightTests(unittest.TestCase):
    def test_ready_document_requires_current_device_and_host_state(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            return _completed(command, _ready_responses(command))

        with tempfile.TemporaryDirectory() as directory:
            document = _build_document(directory, run)

        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["kind"], "android_usb_smoke_preflight")
        self.assertEqual(document["result"], "ready")
        self.assertEqual(document["blockers"], [])
        self.assertEqual(document["device"]["identity"]["manufacturer"], "nubia")
        self.assertTrue(document["device"]["label_guard"]["device_matches_expected_p0110"])
        self.assertTrue(document["device"]["label_guard"]["recorded_as_expected_device_only"])
        self.assertTrue(document["adb"]["reverse"]["configured"])
        self.assertTrue(document["app"]["foreground"]["foreground"])
        self.assertTrue(document["host"]["listener"]["listening"])
        self.assertTrue(document["host"]["listener"]["host_owned"])
        self.assertTrue(document["host"]["preflight"]["passed"])
        self.assertTrue(document["claims"]["can_start_usb_smoke"])
        self.assertFalse(document["claims"]["live_usb_stream_observed"])
        self.assertFalse(document["claims"]["readme_gate_closure"])
        assert_schema_shape(self, document)
        for command in commands:
            if command[0] == "adb":
                self.assertEqual(command[1:3], ["-s", SERIAL])
        flattened = "\n".join(" ".join(command) for command in commands)
        self.assertNotIn(" install ", flattened)
        self.assertNotIn(" am start ", flattened)
        self.assertNotIn(" reverse tcp:", flattened)
        self.assertNotIn(" logcat -c", flattened)

    def test_blocked_document_records_operational_blockers_without_claiming_pass(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["adb", "-s", SERIAL]:
                tail = command[3:]
                if tail == ["get-state"]:
                    return _completed(command, "device\n")
                if tuple(tail) in _P0110_PROP_RESPONSES:
                    return _completed(command, _P0110_PROP_RESPONSES[tuple(tail)])
                if tail == ["reverse", "--list"]:
                    return _completed(command, "")
                if tail == ["shell", "dumpsys", "package", PACKAGE]:
                    return _completed(command, "versionName=0.0.0\nversionCode=1\n")
                if tail == ["shell", "pidof", PACKAGE]:
                    return _completed(command, "19904\n")
                if tail == ["shell", "dumpsys", "window"]:
                    return _completed(command, _WINDOW_FOCUS)
                if tail == ["shell", "dumpsys", "activity", "activities"]:
                    return _completed(command, _ACTIVITY_FOCUS)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return _completed(command, "", returncode=1)
            if command[-3:-1] == ["preflight", "--report"]:
                return _completed(
                    command,
                    "",
                    stderr="codesign identity 'Vibe Screen Dev' not found in the keychain.\n",
                    returncode=1,
                )
            return _completed(command, "", stderr=f"unexpected command: {command}", returncode=1)

        with tempfile.TemporaryDirectory() as directory:
            document = _build_document(directory, run)

        self.assertEqual(document["result"], "blocked")
        joined = "\n".join(blocker["message"] for blocker in document["blockers"])
        self.assertIn("ADB reverse tcp:54321 -> tcp:54321 is not configured", joined)
        self.assertIn("Mac Host is not listening on TCP 54321", joined)
        self.assertIn("Vibe Screen Dev", joined)
        self.assertFalse(document["claims"]["can_start_usb_smoke"])
        self.assertFalse(document["claims"]["live_usb_stream_observed"])
        self.assertFalse(document["claims"]["can_close_latency_gate"])

    def test_unrelated_tcp_listener_blocks_ready_result(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["adb", "-s", SERIAL]:
                return _completed(command, _ready_responses(command))
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return _completed(command, "OtherApp 77 user TCP 127.0.0.1:54321 (LISTEN)\n")
            if command == ["ps", "-p", "77", "-o", "comm="]:
                return _completed(command, "/Applications/Other.app/Contents/MacOS/Other\n")
            if command[-3:-1] == ["preflight", "--report"]:
                Path(command[-1]).write_text("Status: PASS\n", encoding="utf-8")
                return _completed(command, "macOS Host touch-rerun preflight passed\n")
            return _completed(command, "", stderr=f"unexpected command: {command}", returncode=1)

        with tempfile.TemporaryDirectory() as directory:
            document = _build_document(directory, run)

        self.assertEqual(document["result"], "blocked")
        self.assertTrue(document["host"]["listener"]["listening"])
        self.assertFalse(document["host"]["listener"]["host_owned"])
        self.assertIn(
            "host.listener.process",
            [blocker["field"] for blocker in document["blockers"]],
        )
        self.assertFalse(document["claims"]["can_start_usb_smoke"])

    def test_identity_mismatch_blocks_unexpected_device_relabeling(self) -> None:
        def run(command, **kwargs):
            if command[:3] == ["adb", "-s", SERIAL]:
                tail = command[3:]
                if tail == ["get-state"]:
                    return _completed(command, "device\n")
                if tail == ["shell", "getprop", "ro.product.manufacturer"]:
                    return _completed(command, "Acme\n")
                if tail == ["shell", "getprop", "ro.product.model"]:
                    return _completed(command, "X1000\n")
                if tuple(tail) in (
                    ("shell", "getprop", "ro.product.device"),
                    ("shell", "getprop", "ro.product.name"),
                ):
                    return _completed(command, "otherdevice\n")
                if tail == ["shell", "getprop", "ro.build.version.release"]:
                    return _completed(command, "16\n")
                if tail == ["shell", "getprop", "ro.build.version.sdk"]:
                    return _completed(command, "36\n")
                if tail == ["shell", "getprop", "ro.build.fingerprint"]:
                    return _completed(command, "acme/otherdevice/test\n")
                if tail == ["shell", "getprop", "ro.product.cpu.abi"]:
                    return _completed(command, "arm64-v8a\n")
                if tail == ["shell", "getprop", "ro.serialno"]:
                    return _completed(command, SERIAL + "\n")
                if tail == ["reverse", "--list"]:
                    return _completed(command, "UsbFfs tcp:54321 tcp:54321\n")
                if tail == ["shell", "dumpsys", "package", PACKAGE]:
                    return _completed(command, "versionName=0.0.0\nversionCode=1\n")
                if tail == ["shell", "pidof", PACKAGE]:
                    return _completed(command, "19904\n")
                if tail == ["shell", "dumpsys", "window"]:
                    return _completed(command, _WINDOW_FOCUS)
                if tail == ["shell", "dumpsys", "activity", "activities"]:
                    return _completed(command, _ACTIVITY_FOCUS)
            if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
                return _completed(command, "Vibe 12 TCP 127.0.0.1:54321 (LISTEN)\n")
            if command[-3:-1] == ["preflight", "--report"]:
                Path(command[-1]).write_text("Status: PASS\n", encoding="utf-8")
                return _completed(command, "macOS Host touch-rerun preflight passed\n")
            return _completed(command, "", stderr=f"unexpected command: {command}", returncode=1)

        with tempfile.TemporaryDirectory() as directory:
            document = _build_document(directory, run)

        self.assertEqual(document["result"], "blocked")
        fields = [blocker["field"] for blocker in document["blockers"]]
        self.assertIn("device.identity.manufacturer", fields)
        self.assertIn("device.identity.model", fields)
        self.assertFalse(document["device"]["label_guard"]["device_matches_expected_p0110"])
        self.assertFalse(document["device"]["label_guard"]["recorded_as_expected_device_only"])

    def test_lock_blocks_all_runtime_probes(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            return _completed(command, "", stderr="unexpected probe", returncode=1)

        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            document = _build_document(
                directory,
                run,
                lock_globs=[str(Path(directory) / "vibe-screen-*.lock")],
            )

        self.assertEqual(document["result"], "blocked")
        self.assertEqual(document["safety"]["existing_locks"], [f"/tmp/{lock.name}"])
        self.assertFalse(document["safety"]["ran_adb"])
        self.assertEqual(commands, [])
        self.assertIsNone(document["host"]["listener"])
        self.assertIsNone(document["host"]["preflight"])
        self.assertIn("no ADB", document["blockers"][0]["message"])

    def test_owned_lock_allows_read_only_runtime_probes(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            return _completed(command, _ready_responses(command))

        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            document = _build_document(
                directory,
                run,
                lock_globs=[str(Path(directory) / "vibe-screen-*.lock")],
                allow_existing_locks=True,
            )

        self.assertEqual(document["result"], "ready")
        self.assertEqual(document["safety"]["existing_locks"], [f"/tmp/{lock.name}"])
        self.assertTrue(document["safety"]["allows_existing_locks"])
        self.assertTrue(document["safety"]["ran_adb"])
        self.assertTrue(any(command[:3] == ["adb", "-s", SERIAL] for command in commands))

    def test_collect_locks_sorts_and_deduplicates_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "vibe-screen-a.lock"
            second = Path(directory) / "vibe-screen-b.lock"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")

            locks = collect_locks([str(Path(directory) / "vibe-screen-*.lock"), str(first)])

        self.assertEqual(locks, [str(first), str(second)])

    def test_collect_locks_excludes_lock_held_by_current_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            held = Path(directory) / "vibe-screen-device-android.lock"
            other = Path(directory) / "vibe-screen-other.lock"
            held.write_text("owner\n", encoding="utf-8")
            other.write_text("owner\n", encoding="utf-8")

            locks = collect_locks(
                [str(Path(directory) / "vibe-screen-*.lock")],
                held_locks=[str(held)],
            )

        self.assertEqual(locks, [str(other)])

    def test_held_lock_does_not_skip_runtime_probes(self) -> None:
        commands: list[list[str]] = []

        def run(command, **kwargs):
            commands.append(command)
            return _completed(command, _ready_responses(command))

        with tempfile.TemporaryDirectory() as directory:
            held = Path(directory) / "vibe-screen-device-android.lock"
            held.write_text("owner\n", encoding="utf-8")
            document = build_document(
                serial=SERIAL,
                repository_root=Path("/repo"),
                adb_path="adb",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                package_name=PACKAGE,
                port=54321,
                lock_globs=[str(Path(directory) / "vibe-screen-*.lock")],
                held_locks=[str(held)],
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                    "sdk": "36",
                },
                host_preflight_report=Path(directory) / "host-signing-and-permissions.txt",
                command_runner=run,
                wall_clock=lambda: "2026-08-24T00:00:00Z",
            )

        self.assertEqual(document["result"], "ready")
        self.assertEqual(document["safety"]["existing_locks"], [])
        self.assertTrue(document["safety"]["ran_adb"])
        self.assertIn(["adb", "-s", SERIAL, "get-state"], commands)

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight" / "usb.json"
            write_json(path, {"result": "blocked"})
            self.assertEqual(json.loads(path.read_text()), {"result": "blocked"})
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_cli_exits_two_for_blocked_result_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            output = Path(directory) / "usb-smoke-preflight.json"
            status = main(
                [
                    "--serial",
                    SERIAL,
                    "--lock-glob",
                    str(lock),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(status, 2)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["result"], "blocked")
            self.assertFalse(document["safety"]["ran_adb"])

    def test_cli_redacts_raw_serial_and_local_paths_from_written_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "vibe-screen-device-android.lock"
            lock.write_text("owner\n", encoding="utf-8")
            output = Path(directory) / "usb-smoke-preflight.json"
            status = main(
                [
                    "--serial",
                    LOCAL_TEST_SERIAL,
                    "--lock-glob",
                    str(lock),
                    "--repository-root",
                    directory,
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(status, 2)
            text = output.read_text(encoding="utf-8")
            self.assertNotIn(LOCAL_TEST_SERIAL, text)
            self.assertIn(SERIAL, text)

    def test_public_sanitizer_redacts_serial_workspace_home_and_tcc_paths(self) -> None:
        home = str(Path.home())
        tcc_path = (
            f"{home}/Library/"
            + "Application "
            + "Support/"
            + "com.apple"
            + ".TCC/"
            + "TCC"
            + ".db"
        )
        host_user = getpass.getuser()
        document = {
            "command": ["adb", "-s", LOCAL_TEST_SERIAL, "get-state"],
            "lsof": f"Vibe\\x20S 12345 {host_user} 7u TCP 127.0.0.1:54321 (LISTEN)",
            "path": tcc_path,
            "workspace": "/repo/out/host-signing-and-permissions.txt",
        }

        sanitized = sanitize_public_value(
            document, serial=LOCAL_TEST_SERIAL, serial_label=SERIAL, repository_root=Path("/repo")
        )

        encoded = json.dumps(sanitized, sort_keys=True)
        self.assertNotIn(LOCAL_TEST_SERIAL, encoded)
        self.assertNotIn(home, encoded)
        self.assertNotIn(f"{host_user} 7u", encoded)
        self.assertNotIn("Application " + "Support/" + "com.apple" + ".TCC", encoded)
        self.assertNotIn("TCC" + ".db", encoded)
        self.assertIn(SERIAL, encoded)
        self.assertIn("<HOST_USER>", encoded)
        self.assertIn("<WORKSPACE>", encoded)
        self.assertIn("<user-tcc-db>", encoded)

    def test_public_text_file_sanitizer_redacts_auxiliary_host_report(self) -> None:
        home = str(Path.home())
        tcc_path = (
            f"{home}/Library/"
            + "Application "
            + "Support/"
            + "com.apple"
            + ".TCC/"
            + "TCC"
            + ".db"
        )
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "host-signing-and-permissions.txt"
            report.write_text(
                f"Database: {tcc_path}\nSerial: {LOCAL_TEST_SERIAL}\n",
                encoding="utf-8",
            )

            sanitize_public_text_file(
                report,
                serial=LOCAL_TEST_SERIAL,
                serial_label=SERIAL,
                repository_root=Path(directory),
            )

            text = report.read_text(encoding="utf-8")
            self.assertNotIn(LOCAL_TEST_SERIAL, text)
            self.assertNotIn(home, text)
            self.assertNotIn("Application " + "Support/" + "com.apple" + ".TCC", text)
            self.assertNotIn("TCC" + ".db", text)
            self.assertIn(SERIAL, text)
            self.assertIn("<user-tcc-db>", text)

    def test_public_document_limits_device_identity_to_allowed_public_fields(self) -> None:
        document = {
            "device": {
                "identity": {
                    "adb_serial": LOCAL_TEST_SERIAL,
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "product": "pacific",
                    "android_release": "16",
                    "sdk": 36,
                    "build_fingerprint": "nubia/pacific/private-build",
                    "abi": "arm64-v8a",
                    "device_serial": LOCAL_TEST_SERIAL,
                }
            }
        }

        sanitized = sanitize_public_document(
            document,
            serial=LOCAL_TEST_SERIAL,
            serial_label=SERIAL,
            repository_root=Path("/repo"),
        )

        self.assertEqual(
            sanitized["device"]["identity"],
            {
                "manufacturer": "nubia",
                "model": "P0110",
                "device": "pacific",
                "android_release": "16",
                "sdk": 36,
            },
        )

    def test_sdk_mismatch_blocks_ready_result(self) -> None:
        def run(command, **kwargs):
            response = _ready_responses(command)
            if command[3:] == ["shell", "getprop", "ro.build.version.sdk"]:
                response = 0, "35\n", ""
            return _completed(command, response)

        with tempfile.TemporaryDirectory() as directory:
            document = _build_document(directory, run)

        self.assertEqual(document["result"], "blocked")
        self.assertIn(
            "device.identity.sdk",
            [blocker["field"] for blocker in document["blockers"]],
        )
        self.assertFalse(document["claims"]["can_start_usb_smoke"])

    def test_cli_defaults_expected_identity_to_current_p0110(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "usb-smoke-preflight.json"
            status = main(
                [
                    "--serial",
                    "LOCAL_TEST_OTHER_SERIAL",
                    "--output",
                    str(output),
                    "--adb",
                    "missing-adb-for-test",
                ]
            )

            self.assertEqual(status, 2)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                document["configuration"]["expected_device"],
                {
                    "android_release": "16",
                    "device": "pacific",
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "sdk": "36",
                },
            )
            self.assertFalse(document["claims"]["can_start_usb_smoke"])

    def test_lsof_parser_and_host_identity_matcher(self) -> None:
        pids = parse_lsof_listener_pids(
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "Vibe\\x20S 92943 user 7u IPv4 0t0 TCP 127.0.0.1:54321 (LISTEN)\n"
            "Other 10 user 8u IPv4 0t0 TCP 127.0.0.1:54321 (LISTEN)\n"
            "Other 10 user 9u IPv4 0t0 TCP 127.0.0.1:54321 (LISTEN)\n"
        )

        self.assertEqual(pids, [10, 92943])
        self.assertTrue(
            host_process_identity_matches(
                "/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen"
            )
        )
        self.assertTrue(host_process_identity_matches("/tmp/Telemachus"))
        self.assertFalse(host_process_identity_matches("/Applications/Other.app/Other"))

    def test_schema_records_ready_and_blocked_invariants(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        ready_clause, blocked_clause = schema["allOf"]

        self.assertEqual(
            ready_clause["if"]["properties"]["result"],
            {"const": "ready"},
        )
        ready_properties = ready_clause["then"]["properties"]
        self.assertEqual(ready_properties["blockers"], {"maxItems": 0})
        self.assertEqual(
            ready_properties["safety"]["properties"]["ran_adb"],
            {"const": True},
        )
        identity_properties = ready_properties["device"]["properties"]["identity"][
            "properties"
        ]
        self.assertEqual(identity_properties["manufacturer"], {"const": "nubia"})
        self.assertEqual(identity_properties["model"], {"const": "P0110"})
        self.assertEqual(identity_properties["device"], {"const": "pacific"})
        self.assertEqual(identity_properties["android_release"], {"const": "16"})
        self.assertEqual(identity_properties["sdk"], {"const": 36})
        self.assertEqual(
            ready_properties["host"]["properties"]["listener"]["properties"][
                "host_owned"
            ],
            {"const": True},
        )
        self.assertEqual(
            ready_properties["claims"]["properties"]["can_start_usb_smoke"],
            {"const": True},
        )
        self.assertEqual(
            blocked_clause["then"]["properties"]["blockers"],
            {"minItems": 1},
        )
        self.assertEqual(
            blocked_clause["then"]["properties"]["claims"]["properties"][
                "can_start_usb_smoke"
            ],
            {"const": False},
        )

    def test_sanitize_lock_path_redacts_non_vibe_screen_lock_paths(self) -> None:
        # Vibe-screen locks are preserved under /tmp with the original file name.
        self.assertEqual(
            sanitize_lock_path("/tmp/vibe-screen-android-REDACTED.lock"),
            "/tmp/vibe-screen-android-REDACTED.lock",
        )
        self.assertEqual(
            sanitize_lock_path("/private/tmp/vibe-screen-device.lock"),
            "/tmp/vibe-screen-device.lock",
        )
        # Non-vibe-screen lock files must not leak arbitrary absolute paths.
        self.assertEqual(
            sanitize_lock_path("/Users/private-account/some.lock"),
            "<redacted-lock-path>",
        )
        self.assertEqual(
            sanitize_lock_path("/tmp/other.lock"),
            "<redacted-lock-path>",
        )
        # Non-lock strings are left unchanged so general sanitization still works.
        self.assertEqual(sanitize_lock_path("nubia"), "nubia")
        self.assertEqual(sanitize_lock_path("blocked"), "blocked")
        self.assertEqual(sanitize_lock_path("/Applications/Vibe Screen.app"), "/Applications/Vibe Screen.app")

    def test_existing_locks_are_sanitized_in_safety_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vibe_lock = Path(directory) / "vibe-screen-held.lock"
            other_lock = Path(directory) / "private-other.lock"
            vibe_lock.write_text("owner\n", encoding="utf-8")
            other_lock.write_text("owner\n", encoding="utf-8")

            document = build_document(
                serial=SERIAL,
                repository_root=Path("/repo"),
                adb_path="adb",
                adb_timeout=1.0,
                host_preflight_timeout=1.0,
                package_name=PACKAGE,
                port=54321,
                lock_globs=[str(Path(directory) / "*.lock")],
                held_locks=[str(vibe_lock)],
                expected_device={
                    "manufacturer": "nubia",
                    "model": "P0110",
                    "device": "pacific",
                    "android_release": "16",
                    "sdk": "36",
                },
                host_preflight_report=Path(directory) / "host-signing-and-permissions.txt",
                command_runner=lambda *a, **k: _completed([], ""),
                wall_clock=lambda: "2026-08-24T00:00:00Z",
            )

        existing = document["safety"]["existing_locks"]
        self.assertEqual(existing, ["<redacted-lock-path>"])
        self.assertNotIn(str(other_lock), existing)
        self.assertNotIn("/Users/", "\n".join(existing))


def _build_document(
    directory: str,
    command_runner,
    *,
    lock_globs: list[str] | None = None,
    allow_existing_locks: bool = False,
):
    return build_document(
        serial=SERIAL,
        repository_root=Path("/repo"),
        adb_path="adb",
        adb_timeout=1.0,
        host_preflight_timeout=1.0,
        package_name=PACKAGE,
        port=54321,
        lock_globs=lock_globs or [str(Path(directory) / "missing-*.lock")],
        held_locks=[],
        expected_device={
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "android_release": "16",
            "sdk": "36",
        },
        host_preflight_report=Path(directory) / "host-signing-and-permissions.txt",
        allow_existing_locks=allow_existing_locks,
        command_runner=command_runner,
        wall_clock=lambda: "2026-08-24T00:00:00Z",
    )


def _ready_responses(command: list[str]) -> tuple[int, str, str]:
    if command[:3] == ["adb", "-s", SERIAL]:
        tail = command[3:]
        if tail == ["get-state"]:
            return 0, "device\n", ""
        if tuple(tail) in _P0110_PROP_RESPONSES:
            return 0, _P0110_PROP_RESPONSES[tuple(tail)], ""
        if tail == ["reverse", "--list"]:
            return 0, "UsbFfs tcp:54321 tcp:54321\n", ""
        if tail == ["shell", "dumpsys", "package", PACKAGE]:
            return 0, "versionName=0.0.0\nversionCode=1\n", ""
        if tail == ["shell", "pidof", PACKAGE]:
            return 0, "19904\n", ""
        if tail == ["shell", "dumpsys", "window"]:
            return 0, _WINDOW_FOCUS, ""
        if tail == ["shell", "dumpsys", "activity", "activities"]:
            return 0, _ACTIVITY_FOCUS, ""
    if command[:3] == ["lsof", "-nP", "-iTCP:54321"]:
        return 0, "Vibe 12 TCP 127.0.0.1:54321 (LISTEN)\n", ""
    if command == ["ps", "-p", "12", "-o", "comm="]:
        return 0, "/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen\n", ""
    if command[-3:-1] == ["preflight", "--report"]:
        Path(command[-1]).write_text("Status: PASS\n", encoding="utf-8")
        return 0, "macOS Host touch-rerun preflight passed\n", ""
    return 1, "", f"unexpected command: {command}"


def _completed(
    command: list[str],
    response,
    *,
    returncode: int | None = None,
    stderr: str | None = None,
):
    if isinstance(response, tuple):
        code, stdout, err = response
        return subprocess.CompletedProcess(command, code, stdout, err)
    return subprocess.CompletedProcess(
        command,
        0 if returncode is None else returncode,
        response,
        stderr or "",
    )


def assert_schema_shape(test_case: unittest.TestCase, document: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    test_case.assertEqual(set(document), set(schema["properties"]))
    for field in schema["required"]:
        test_case.assertIn(field, document)
    test_case.assertEqual(
        set(document["configuration"]),
        set(schema["properties"]["configuration"]["properties"]),
    )
    test_case.assertIn("allow_existing_locks", document["configuration"])
    test_case.assertEqual(
        set(document["safety"]),
        set(schema["properties"]["safety"]["properties"]),
    )
    test_case.assertIn("allows_existing_locks", document["safety"])
    test_case.assertEqual(
        set(document["claims"]),
        set(schema["properties"]["claims"]["properties"]),
    )


_P0110_PROP_RESPONSES = {
    ("shell", "getprop", "ro.product.manufacturer"): "nubia\n",
    ("shell", "getprop", "ro.product.model"): "P0110\n",
    ("shell", "getprop", "ro.product.device"): "pacific\n",
    ("shell", "getprop", "ro.product.name"): "pacific\n",
    ("shell", "getprop", "ro.build.version.release"): "16\n",
    ("shell", "getprop", "ro.build.version.sdk"): "36\n",
    ("shell", "getprop", "ro.build.fingerprint"): "nubia/pacific/test\n",
    ("shell", "getprop", "ro.product.cpu.abi"): "arm64-v8a\n",
    ("shell", "getprop", "ro.serialno"): SERIAL + "\n",
}

_WINDOW_FOCUS = "mCurrentFocus=Window{ dev.telemachus.display/.MainActivity }\n"
_ACTIVITY_FOCUS = (
    "topResumedActivity=ActivityRecord{ dev.telemachus.display/.MainActivity }\n"
)


if __name__ == "__main__":
    unittest.main()
