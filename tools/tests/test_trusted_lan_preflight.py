from __future__ import annotations

import json
import fcntl
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence.trusted_lan_preflight import (
    CommandCapture,
    DeviceLock,
    DeviceLockError,
    DeviceLockSnapshot,
    _default_route_interface,
    device_lock_path,
    _identity_stage,
    _private_ipv4_candidates,
    _route_result_reaches_wifi,
    _validated_mac_candidates,
    build_document,
    redact_local_runtime_paths,
    redact_network_endpoints,
    redact_lsof_user_columns,
    main,
    sanitize_text,
)


MODULE = "vibescreen_evidence.trusted_lan_preflight"


DEVICE_IDENTITY = {
    "adb_serial": "P0110_SERIAL_PLACEHOLDER",
    "device_serial": "P0110_SERIAL_PLACEHOLDER",
    "manufacturer": "nubia",
    "model": "P0110",
    "device": "pacific",
    "android_release": "16",
    "sdk": 36,
    "build_fingerprint": "nubia/pacific/pacific:16/test",
}


class FakeADBClient:
    def __init__(self, serial: str, *, adb_path: str = "adb", timeout_seconds: float = 15.0) -> None:
        self.serial = serial
        self.adb_path = adb_path
        self.timeout_seconds = timeout_seconds

    def require_device(self) -> None:
        return None

    def identity(self):
        return dict(DEVICE_IDENTITY, adb_serial=self.serial)


class FakeDeviceLock:
    def __init__(self, serial: str) -> None:
        self.serial = serial

    def __enter__(self) -> DeviceLockSnapshot:
        return DeviceLockSnapshot(
            "/tmp/vibe-screen-<runtime>/trusted-lan-locks/"
            "vibe-screen-android-<serial-hash>.lock",
            True,
            "acquired",
        )

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def clean_sfltool_processes() -> dict[str, object]:
    return CommandCapture(["pgrep", "-x", "sfltool"], 1, "", "").as_json()


class TrustedLANPreflightTests(unittest.TestCase):
    def test_sanitizes_wifi_identifiers_and_pairing_tokens(self) -> None:
        text = sanitize_text("SSID: Office-WiFi, BSSID: aa:bb:cc:dd:ee:ff\n")

        self.assertIn("SSID: <redacted>", text)
        self.assertIn("BSSID: <redacted>", text)
        self.assertNotIn("Office-WiFi", text)

    def test_redacts_ipv4_endpoints_from_public_output(self) -> None:
        private_endpoint = "100." + "72.239.103"
        other_endpoint = "10." + "0.0.1"
        redacted = redact_network_endpoints(f"route to {private_endpoint}:54321 via {other_endpoint}")

        self.assertEqual(redacted.count("<redacted-ipv4>"), 2)
        self.assertIn("<redacted-ipv4>:54321", redacted)
        self.assertNotIn(private_endpoint, redacted)
        self.assertNotIn(other_endpoint, redacted)

    def test_redacts_serial_specific_runtime_lock_path(self) -> None:
        path = "/tmp/vibe-screen-<runtime>/trusted-lan-locks/vibe-screen-android-<serial-hash>.lock"

        self.assertEqual(redact_local_runtime_paths(path), "<android-device-lock>")

    def test_redacts_lsof_user_column_from_listener_output(self) -> None:
        redacted = redact_lsof_user_columns(
            "COMMAND     PID     USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "Vibe\\x20S 92943 localuser    7u  IPv4 0x1 0t0 TCP 127.0.0.1:54321 (LISTEN)"
        )

        self.assertIn("<redacted-user>", redacted)
        self.assertNotIn("localuser", redacted)

    def test_sanitize_text_redacts_lsof_user_column(self) -> None:
        sanitized = sanitize_text(
            "COMMAND     PID     USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
            "Vibe\\x20S 92943 localuser    7u  IPv4 0x1 0t0 TCP 127.0.0.1:54321 (LISTEN)"
        )

        self.assertIn("<redacted-user>", sanitized)
        self.assertNotIn("localuser", sanitized)

    def test_private_ipv4_candidates_exclude_loopback_link_local_and_multicast(self) -> None:
        candidates = _private_ipv4_candidates(
            "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n"
            "    inet 127.0.0.1 netmask 0xff000000\n"
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING> mtu 1500\n"
            "    inet 10.0.0.5 netmask 0xffffff00\n"
            "utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n"
            "    inet 10.4.56.211 --> 10.4.56.211 netmask 0xffffffff\n"
            "awdl0: flags=8943<UP,BROADCAST,RUNNING> mtu 1500\n"
            "    inet 169.254.1.20 netmask 0xffff0000\n"
        )

        self.assertEqual(candidates, ["10.0.0.5"])

    def test_public_ipv4_candidates_are_not_retained_as_lan_candidates(self) -> None:
        candidates = _private_ipv4_candidates(
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING> mtu 1500\n"
            "    inet 8.8.8.8 netmask 0xffffff00\n"
        )

        self.assertEqual(candidates, [])

    def test_default_route_keeps_interface_without_gateway_address(self) -> None:
        interface = _default_route_interface(
            "   route to: default\n"
            "destination: default\n"
            "    gateway: 10.0.0.1\n"
            "  interface: en0\n"
        )

        self.assertEqual(interface, "en0")

    def test_route_result_requires_wlan0_and_no_unreachable_marker(self) -> None:
        self.assertTrue(_route_result_reaches_wifi({"returncode": 0, "stdout": "10.0.0.1 dev wlan0 src 10.0.0.2"}))
        self.assertFalse(_route_result_reaches_wifi({"returncode": 0, "stdout": "10.0.0.1 dev rmnet0 src 10.0.0.2"}))
        self.assertFalse(_route_result_reaches_wifi({"returncode": 1, "stderr": "Network is unreachable"}))

    def test_mac_host_ipv4_override_must_match_discovered_candidate(self) -> None:
        self.assertEqual(_validated_mac_candidates(["10.0.0.5"], ["10.0.0.5", "10.0.0.6"]), ["10.0.0.5"])
        self.assertEqual(_validated_mac_candidates([], ["10.0.0.5"]), ["10.0.0.5"])
        with self.assertRaisesRegex(ValueError, "not assigned to a discovered host interface"):
            _validated_mac_candidates(["8.8.8.8"], ["10.0.0.5"])

    def test_identity_stage_requires_exact_p0110_identity(self) -> None:
        stage = _identity_stage(dict(DEVICE_IDENTITY, model="OTHER_MODEL", device="other_device"), "P0110_SERIAL_PLACEHOLDER")

        self.assertEqual(stage["status"], "blocked")
        self.assertIn("device model is not P0110", stage["summary"])
        self.assertIn("device codename is not pacific", stage["summary"])

    def test_device_lock_reuses_stale_unlocked_marker(self) -> None:
        serial = "TESTLOCK_STALE"
        with tempfile.TemporaryDirectory() as directory:
            with patch("vibescreen_evidence.trusted_lan_preflight.DEVICE_LOCK_DIR", Path(directory)):
                path = device_lock_path(serial)
                path.write_text("stale marker", encoding="utf-8")

                with DeviceLock(serial) as snapshot:
                    self.assertTrue(snapshot.acquired)
                    self.assertIn("TESTLOCK_STALE", path.read_text(encoding="utf-8"))

                self.assertFalse(path.exists())

    def test_device_lock_blocks_when_flocked_by_another_process(self) -> None:
        serial = "TESTLOCK_ACTIVE"
        with tempfile.TemporaryDirectory() as directory:
            with patch("vibescreen_evidence.trusted_lan_preflight.DEVICE_LOCK_DIR", Path(directory)):
                path = device_lock_path(serial)
                with path.open("w", encoding="utf-8") as handle:
                    handle.write("owner=other\n")
                    handle.flush()
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaises(DeviceLockError):
                        with DeviceLock(serial):
                            pass
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_device_lock_rejects_preexisting_symlink_without_following(self) -> None:
        serial = "P0110_SERIAL_PLACEHOLDER"
        with tempfile.TemporaryDirectory() as directory:
            with patch("vibescreen_evidence.trusted_lan_preflight.DEVICE_LOCK_DIR", Path(directory)):
                path = device_lock_path(serial)
                target = Path(directory) / "symlink-target"
                path.symlink_to(target)

                with self.assertRaisesRegex(DeviceLockError, "symlink"):
                    with DeviceLock(serial):
                        pass

                self.assertTrue(path.is_symlink())
                self.assertFalse(target.exists())
                self.assertNotIn(serial, os.readlink(path))

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.DeviceLock", FakeDeviceLock)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_blocked_network_and_signing_keep_all_lan_claims_false(
        self,
        host_network,
        android_network,
        host_preflight,
        sfltool_processes,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = clean_sfltool_processes()
        host_network.return_value = {
            "mac_ipv4_candidates": ["10.0.0.10"],
            "host_port": 54321,
            "has_lan_listener": False,
            "has_loopback_listener": True,
        }
        android_network.return_value = {
            "wifi_associated": False,
            "wlan0_up": False,
            "wlan0_ipv4": [],
            "has_route": False,
        }
        host_preflight.return_value = {
            "command": [sys.executable, "scripts/macos_dev_host.py", "preflight"],
            "returncode": 1,
            "stdout": "",
            "stderr": "codesign identity 'Vibe Screen Dev' not found",
            "timed_out": False,
        }

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )

        self.assertEqual(document["result"], "blocked")
        self.assertFalse(document["claims"]["can_start_trusted_lan_smoke"])
        self.assertFalse(document["claims"]["real_lan_stream"])
        self.assertFalse(document["claims"]["trusted_lan_encrypted"])
        self.assertIn("android_wifi_association: Wi-Fi is not associated", document["blockers"])
        self.assertEqual(document["device_lock"]["path"], "<android-device-lock>")
        self.assertEqual(document["android_device"]["identity"]["adb_serial"], "<device-serial>")
        self.assertEqual(document["safety"]["starts_host"], False)
        self.assertEqual(document["safety"]["writes_pairing_token"], False)

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.DeviceLock", FakeDeviceLock)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_ready_preflight_only_allows_starting_smoke_not_closing_gates(
        self,
        host_network,
        android_network,
        host_preflight,
        sfltool_processes,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = clean_sfltool_processes()
        host_network.return_value = {
            "mac_ipv4_candidates": ["10.0.0.10"],
            "host_port": 54321,
            "has_lan_listener": False,
            "has_loopback_listener": False,
        }
        android_network.return_value = {
            "wifi_associated": True,
            "wlan0_up": True,
            "wlan0_ipv4": ["10.0.0.20"],
            "has_route": True,
        }
        host_preflight.return_value = {
            "command": [sys.executable, "scripts/macos_dev_host.py", "preflight"],
            "returncode": 0,
            "stdout": "Status: PASS",
            "stderr": "",
            "timed_out": False,
        }

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )

        self.assertEqual(document["result"], "ready")
        self.assertTrue(document["claims"]["can_start_trusted_lan_smoke"])
        self.assertFalse(document["claims"]["real_lan_stream"])
        self.assertFalse(document["claims"]["reconnect"])
        self.assertEqual(document["host"]["host_preflight_command"], document["host"]["preflight"]["command"])

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.DeviceLock", FakeDeviceLock)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_document_redacts_cgnat_candidates_after_real_route_probe(
        self,
        host_network,
        android_network,
        host_preflight,
        sfltool_processes,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = clean_sfltool_processes()
        private_endpoint = "100." + "72.239.103"
        host_network.return_value = {
            "mac_ipv4_candidates": [private_endpoint],
            "host_port": 54321,
            "has_lan_listener": False,
            "has_loopback_listener": False,
        }
        android_network.return_value = {
            "wifi_associated": False,
            "wlan0_up": False,
            "wlan0_ipv4": [],
            "has_route": False,
            "route_to_mac": {
                private_endpoint: {
                    "command": ["adb", "-s", "P0110_SERIAL_PLACEHOLDER", "shell", "ip", "route", "get", private_endpoint],
                    "returncode": 2,
                    "stdout": "",
                    "stderr": "RTNETLINK answers: Network is unreachable",
                    "timed_out": False,
                }
            },
        }
        host_preflight.return_value = {
            "command": [sys.executable, "scripts/macos_dev_host.py", "preflight"],
            "returncode": 0,
            "stdout": "Status: PASS",
            "stderr": "",
            "timed_out": False,
        }

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )
        encoded = json.dumps(document)

        self.assertNotIn(private_endpoint, encoded)
        self.assertNotIn("P0110_SERIAL_PLACEHOLDER", encoded)
        self.assertIn("<redacted-ipv4>", encoded)

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    def test_sfltool_process_blocks_before_adb(self, sfltool_processes, adb_client, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = CommandCapture(["pgrep", "-x", "sfltool"], 0, "123\n", "").as_json()

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )

        self.assertEqual(document["result"], "blocked")
        self.assertIn("sfltool_process_check", document["blockers"][0])
        adb_client.assert_not_called()

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    def test_sfltool_probe_failure_blocks_before_adb(self, sfltool_processes, adb_client, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = CommandCapture(["pgrep", "-x", "sfltool"], 2, "", "pgrep failed").as_json()

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )

        self.assertEqual(document["result"], "blocked")
        self.assertIn("Could not confirm sfltool absence", document["stages"][0]["summary"])
        adb_client.assert_not_called()

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_sfltool_processes")
    @patch("vibescreen_evidence.trusted_lan_preflight.DeviceLock")
    def test_device_lock_blocks_before_adb(self, device_lock, sfltool_processes, adb_client, repository_state) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        sfltool_processes.return_value = clean_sfltool_processes()
        device_lock.return_value.__enter__.side_effect = DeviceLockError(
            path=Path("/tmp/vibe-screen-android-P0110_SERIAL_PLACEHOLDER.lock"),
            detail="owner=other pid=1 serial=P0110_SERIAL_PLACEHOLDER",
        )

        document = build_document(
            serial="P0110_SERIAL_PLACEHOLDER",
            adb_path="adb",
            adb_timeout=1,
            repo=Path("."),
            host_port=54321,
            mac_host_ipv4=[],
            host_preflight_command=[sys.executable, "scripts/macos_dev_host.py", "preflight"],
            require_host_listener=False,
        )

        self.assertEqual(document["result"], "blocked")
        self.assertIn("device_lock", document["blockers"][0])
        self.assertEqual(document["device_lock"]["path"], "<android-device-lock>")
        self.assertIn("serial=<device-serial>", document["device_lock"]["detail"])
        adb_client.assert_not_called()


class TrustedLANPreflightCliTests(unittest.TestCase):
    def test_cli_returns_blocked_exit_code_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trusted-lan-preflight.json"
            with patch(f"{MODULE}.build_document") as build_document:
                build_document.return_value = {"result": "blocked", "blockers": ["wifi"]}
                exit_code = main(
                    [
                        "--serial",
                        "P0110_SERIAL_PLACEHOLDER",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["result"], "blocked")


if __name__ == "__main__":
    unittest.main()
