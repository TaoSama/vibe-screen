from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence.trusted_lan_preflight import (
    _default_route_interface,
    _identity_stage,
    _private_ipv4_candidates,
    _route_result_reaches_wifi,
    build_document,
    redact_network_endpoints,
    main,
    sanitize_text,
)


MODULE = "vibescreen_evidence.trusted_lan_preflight"


DEVICE_IDENTITY = {
    "adb_serial": "EP0110PZ0B9110300B",
    "device_serial": "EP0110PZ0B9110300B",
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


class TrustedLANPreflightTests(unittest.TestCase):
    def test_sanitizes_wifi_identifiers_and_pairing_tokens(self) -> None:
        text = sanitize_text("SSID: Office-WiFi, BSSID: aa:bb:cc:dd:ee:ff\n")

        self.assertIn("SSID: <redacted>", text)
        self.assertIn("BSSID: <redacted>", text)
        self.assertNotIn("Office-WiFi", text)

    def test_redacts_cgnat_lan_endpoints_from_public_output(self) -> None:
        private_endpoint = "100." + "72.239.103"
        redacted = redact_network_endpoints(f"route to {private_endpoint}:54321 via 10.0.0.1")

        self.assertIn("<redacted-cgnat-ipv4>", redacted)
        self.assertIn("10.0.0.1", redacted)
        self.assertNotIn(private_endpoint, redacted)

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

    def test_identity_stage_requires_exact_p0110_identity(self) -> None:
        stage = _identity_stage(dict(DEVICE_IDENTITY, model="2211133C", device="fuxi"), "EP0110PZ0B9110300B")

        self.assertEqual(stage["status"], "blocked")
        self.assertIn("device model is not P0110", stage["summary"])
        self.assertIn("device codename is not pacific", stage["summary"])

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_blocked_network_and_signing_keep_all_lan_claims_false(
        self,
        host_network,
        android_network,
        host_preflight,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
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
            "returncode": 1,
            "stdout": "",
            "stderr": "codesign identity 'Vibe Screen Dev' not found",
            "timed_out": False,
        }

        document = build_document(
            serial="EP0110PZ0B9110300B",
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
        self.assertEqual(document["safety"]["starts_host"], False)
        self.assertEqual(document["safety"]["writes_pairing_token"], False)

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_ready_preflight_only_allows_starting_smoke_not_closing_gates(
        self,
        host_network,
        android_network,
        host_preflight,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
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
        host_preflight.return_value = {"returncode": 0, "stdout": "Status: PASS", "stderr": "", "timed_out": False}

        document = build_document(
            serial="EP0110PZ0B9110300B",
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

    @patch("vibescreen_evidence.trusted_lan_preflight.repository_state")
    @patch("vibescreen_evidence.trusted_lan_preflight.ADBClient", FakeADBClient)
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_preflight")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_android_network")
    @patch("vibescreen_evidence.trusted_lan_preflight.collect_host_network")
    def test_document_redacts_cgnat_candidates_after_real_route_probe(
        self,
        host_network,
        android_network,
        host_preflight,
        repository_state,
    ) -> None:
        repository_state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
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
                    "command": ["adb", "-s", "EP0110PZ0B9110300B", "shell", "ip", "route", "get", private_endpoint],
                    "returncode": 2,
                    "stdout": "",
                    "stderr": "RTNETLINK answers: Network is unreachable",
                    "timed_out": False,
                }
            },
        }
        host_preflight.return_value = {"returncode": 0, "stdout": "Status: PASS", "stderr": "", "timed_out": False}

        document = build_document(
            serial="EP0110PZ0B9110300B",
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
        self.assertIn("<redacted-cgnat-ipv4>", encoded)


class TrustedLANPreflightCliTests(unittest.TestCase):
    def test_cli_returns_blocked_exit_code_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trusted-lan-preflight.json"
            with patch(f"{MODULE}.build_document") as build_document:
                build_document.return_value = {"result": "blocked", "blockers": ["wifi"]}
                exit_code = main(
                    [
                        "--serial",
                        "EP0110PZ0B9110300B",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["result"], "blocked")


if __name__ == "__main__":
    unittest.main()
