from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.device_info import _package_version, _write_json, collect_device_info


class FakeClient:
    serial = "device:5555"

    def connect(self):
        return "connected to device:5555"

    def require_device(self):
        return None

    def adb_version(self):
        return "Android Debug Bridge version 1.0.41"

    def identity(self):
        return {"adb_serial": self.serial, "model": "test-device"}

    def shell(self, *arguments):
        self.arguments = arguments
        return "  versionCode=42 minSdk=26\n  versionName=1.2.3\n"


class DeviceInfoTests(unittest.TestCase):
    def test_collects_identity_versions_and_package(self) -> None:
        document = collect_device_info(FakeClient(), packages=["dev.vibescreen"])
        self.assertEqual(document["schema_version"], SCHEMA_VERSION)
        self.assertEqual(document["device"]["model"], "test-device")
        self.assertEqual(document["packages"][0]["version_code"], 42)
        self.assertEqual(document["packages"][0]["version_name"], "1.2.3")

    def test_no_connect_still_requires_ready_device(self) -> None:
        client = FakeClient()
        collect_device_info(client, connect=False)
        self.assertNotIn("connection", client.__dict__)

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "device" / "info.json"
            _write_json(path, {"ok": True})
            self.assertEqual(json.loads(path.read_text()), {"ok": True})
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_package_parser_uses_dumpsys(self) -> None:
        client = FakeClient()
        _package_version(client, "dev.vibescreen")
        self.assertEqual(client.arguments, ("dumpsys", "package", "dev.vibescreen"))


if __name__ == "__main__":
    unittest.main()
