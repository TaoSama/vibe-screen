import subprocess
import unittest

from vibescreen_evidence.adb import (
    ADBClient,
    ADBError,
    _parse_battery,
    _parse_key_values,
    _parse_meminfo,
    _parse_thermal,
    _parse_total_pss,
)
from vibescreen_evidence.android_instrumentation_cleanup import (
    CleanupCommandResult,
    EXPECTED_CLEANUP_SCOPE,
    InstrumentationCleanupError,
    cleanup_android_instrumentation_test_package,
    require_instrumentation_cleanup_ok,
)


class AndroidInstrumentationCleanupTest(unittest.TestCase):
    def _runner(self, responses):
        calls = []

        def run(name, package_name, command):
            calls.append((name, package_name, command))
            response = responses.get(name, (0, "", ""))
            return CleanupCommandResult(
                name=name,
                package_name=package_name,
                command=tuple(command),
                returncode=response[0],
                stdout=response[1],
                stderr=response[2],
            )

        return run, calls

    def test_cleanup_force_stops_uninstalls_and_verifies_test_package_only(self):
        runner, calls = self._runner({"uninstall_test_package": (0, "Success\n", "")})

        result = cleanup_android_instrumentation_test_package(runner)

        self.assertTrue(result.ok)
        self.assertEqual(result.cleanup_scope, EXPECTED_CLEANUP_SCOPE)
        self.assertEqual(
            calls,
            [
                (
                    "force_stop_test_package",
                    "dev.telemachus.display.test",
                    ("shell", "am", "force-stop", "dev.telemachus.display.test"),
                ),
                (
                    "uninstall_test_package",
                    "dev.telemachus.display.test",
                    ("uninstall", "dev.telemachus.display.test"),
                ),
                (
                    "verify_test_package_absent",
                    "dev.telemachus.display.test",
                    ("shell", "pm", "list", "packages", "dev.telemachus.display.test"),
                ),
            ],
        )

    def test_cleanup_is_idempotent_when_test_package_is_already_absent(self):
        runner, _calls = self._runner(
            {
                "uninstall_test_package": (
                    1,
                    "Failure [DELETE_FAILED_INTERNAL_ERROR]\n",
                    "Unknown package: dev.telemachus.display.test\n",
                )
            }
        )

        result = cleanup_android_instrumentation_test_package(runner)

        self.assertTrue(result.ok)
        self.assertTrue(result.commands[1].package_was_absent)

    def test_cleanup_fails_closed_when_test_package_remains_installed(self):
        runner, _calls = self._runner(
            {
                "verify_test_package_absent": (
                    0,
                    "package:dev.telemachus.display.test\n",
                    "",
                )
            }
        )

        result = cleanup_android_instrumentation_test_package(runner)

        self.assertFalse(result.ok)
        with self.assertRaises(InstrumentationCleanupError):
            require_instrumentation_cleanup_ok(result)


class ADBClientTest(unittest.TestCase):
    def test_commands_are_scoped_to_explicit_serial(self):
        commands = []

        def run(command, **kwargs):
            commands.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "device\n", "")

        client = ADBClient("device.example:5555", command_runner=run)
        client.require_device()

        self.assertEqual(
            commands[0][0],
            ["adb", "-s", "device.example:5555", "get-state"],
        )
        self.assertFalse(commands[0][1]["check"])
        self.assertEqual(commands[0][1]["timeout"], 15.0)

    def test_nonzero_exit_has_actionable_error(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "device offline\n")

        client = ADBClient("serial", command_runner=run)
        with self.assertRaisesRegex(ADBError, "device offline"):
            client.require_device()

    def test_timeout_is_converted_to_adb_error(self):
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        client = ADBClient("serial", timeout_seconds=3, command_runner=run)
        with self.assertRaisesRegex(ADBError, "timed out after 3s"):
            client.require_device()

    def test_process_collection_treats_absence_as_not_running(self):
        def run(command, **kwargs):
            output = "PID NAME\n10 other.app\n11 dev.vibescreen.client:decoder\n"
            return subprocess.CompletedProcess(command, 0, output, "")

        client = ADBClient("serial", command_runner=run)
        errors = []
        process = client._collect_process("dev.vibescreen.client", errors)
        self.assertEqual(process["pids"], [11])
        self.assertTrue(process["running"])
        self.assertEqual(errors, [])

    def test_connect_requires_adb_confirmation_and_ready_state(self):
        responses = iter(
            [
                subprocess.CompletedProcess([], 0, "connected to device.example:5555\n", ""),
                subprocess.CompletedProcess([], 0, "device\n", ""),
            ]
        )
        client = ADBClient("device.example:5555", command_runner=lambda *args, **kwargs: next(responses))
        self.assertEqual(client.connect(), "connected to device.example:5555")

    def test_connect_over_usb_serial_only_checks_readiness(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "device\n", "")

        client = ADBClient("<redacted-xiaomi-adb-serial>", command_runner=run)
        result = client.connect()

        self.assertEqual(result, "already connected to <redacted-xiaomi-adb-serial>")
        self.assertEqual(commands, [["adb", "-s", "<redacted-xiaomi-adb-serial>", "get-state"]])

    def test_command_and_exec_out_are_scoped_to_explicit_serial(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "ok\n", "")

        client = ADBClient("<redacted-adb-serial>", command_runner=run)

        self.assertEqual(client.command("reverse", "--list"), "ok")
        self.assertEqual(client.exec_out("run-as", "dev.telemachus.display", "id"), "ok")
        self.assertEqual(
            commands,
            [
                ["adb", "-s", "<redacted-adb-serial>", "reverse", "--list"],
                [
                    "adb",
                    "-s",
                    "<redacted-adb-serial>",
                    "exec-out",
                    "run-as",
                    "dev.telemachus.display",
                    "id",
                ],
            ],
        )


class ADBPowerCollectionTest(unittest.TestCase):
    @staticmethod
    def _client(responder):
        return ADBClient("serial", command_runner=responder)

    def test_valid_power_values_are_parsed_without_errors(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "-512000\n", "")

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertEqual(errors, [])
        self.assertEqual(
            power,
            {
                "current_now_ua": -512000,
                "current_average_ua": -512000,
                "charge_counter_uah": -512000,
                "voltage_now_uv": -512000,
            },
        )

    def test_permission_denied_marks_unavailable_not_error(self):
        def run(command, **kwargs):
            stderr = f"cat: {command[-1]}: Permission denied\n"
            return subprocess.CompletedProcess(command, 1, "", stderr)

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertEqual(errors, [])
        self.assertTrue(all(value is None for value in power.values()))

    def test_missing_node_marks_unavailable_not_error(self):
        def run(command, **kwargs):
            stderr = f"cat: {command[-1]}: No such file or directory\n"
            return subprocess.CompletedProcess(command, 1, "", stderr)

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertEqual(errors, [])
        self.assertTrue(all(value is None for value in power.values()))

    def test_unclassified_local_failures_are_recorded_as_errors(self):
        for detail in (
            "Is a directory",
            "I/O error",
        ):
            with self.subTest(detail=detail):
                def run(command, **kwargs):
                    stderr = f"cat: {command[-1]}: {detail}\n" if detail else ""
                    return subprocess.CompletedProcess(command, 1, "", stderr)

                errors = []
                power = self._client(run)._collect_power(errors)

                self.assertTrue(all(value is None for value in power.values()))
                self.assertEqual(len(errors), len(power))
                self.assertTrue(all(detail in error for error in errors))

    def test_unclassified_empty_failure_is_recorded_as_error(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "")

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertTrue(all(value is None for value in power.values()))
        self.assertEqual(len(errors), len(power))
        self.assertTrue(all("no output" in error for error in errors))

    def test_successful_non_numeric_value_is_unavailable_not_error(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "unknown\n", "")

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertEqual(errors, [])
        self.assertTrue(all(value is None for value in power.values()))

    def test_adb_timeout_is_recorded_as_error(self):
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertTrue(all(value is None for value in power.values()))
        self.assertEqual(len(errors), len(power))
        self.assertTrue(all("timed out" in error for error in errors))
        self.assertTrue(all(error.startswith("power.") for error in errors))

    def test_device_offline_nonzero_exit_is_recorded_as_error(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "error: device offline\n")

        errors = []
        power = self._client(run)._collect_power(errors)

        self.assertTrue(all(value is None for value in power.values()))
        self.assertEqual(len(errors), len(power))
        self.assertTrue(all("device offline" in error for error in errors))


class ADBParserTest(unittest.TestCase):
    def test_memory_and_total_pss_parsing(self):
        self.assertEqual(
            _parse_meminfo("MemTotal: 1234 kB\nMemFree: 42 kB\n"),
            {"MemTotal": 1234, "MemFree": 42},
        )
        self.assertEqual(_parse_total_pss("  TOTAL PSS: 987 TOTAL RSS: 111"), 987)
        self.assertEqual(_parse_total_pss(" TOTAL  321  1 2 3\n"), 321)

    def test_battery_values_are_typed(self):
        self.assertEqual(
            _parse_key_values("  AC powered: false\n  level: 73\n  technology: Li-ion\n"),
            {"AC_powered": False, "level": 73, "technology": "Li-ion"},
        )

    def test_battery_parser_derives_android_plugged_bitmask(self):
        self.assertEqual(
            _parse_battery(
                "  AC powered: true\n"
                "  USB powered: false\n"
                "  Wireless powered: false\n"
                "  Dock powered: true\n"
                "  status: 2\n"
                "  level: 73\n"
            ),
            {
                "AC_powered": True,
                "USB_powered": False,
                "Wireless_powered": False,
                "Dock_powered": True,
                "plugged": 9,
                "status": 2,
                "level": 73,
            },
        )

    def test_thermal_temperatures_are_structured(self):
        parsed = _parse_thermal(
            "Thermal Status: 2\n"
            "Temperature{mValue=41.5, mType=3, mName=skin, mStatus=1}"
        )
        self.assertEqual(parsed["status"], 2)
        self.assertEqual(
            parsed["temperatures"],
            [{"celsius": 41.5, "type": 3, "name": "skin", "status": 1}],
        )


if __name__ == "__main__":
    unittest.main()
