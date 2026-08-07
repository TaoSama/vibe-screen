import subprocess
import unittest

from vibescreen_evidence.adb import (
    ADBClient,
    ADBError,
    _parse_key_values,
    _parse_meminfo,
    _parse_thermal,
    _parse_total_pss,
)


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

        client = ADBClient("8a023e3a", command_runner=run)
        result = client.connect()

        self.assertEqual(result, "already connected to 8a023e3a")
        self.assertEqual(commands, [["adb", "-s", "8a023e3a", "get-state"]])


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
