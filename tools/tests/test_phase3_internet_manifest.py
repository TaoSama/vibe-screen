from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.manifest import ManifestError
from vibescreen_evidence.phase3_internet_manifest import (
    KIND,
    REQUIRED_ARTIFACTS,
    REQUIRED_BOUNDARIES,
    build_manifest,
    main,
)


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "phase3-internet-manifest.schema.json"


def certificate(path: Path) -> Path:
    path.write_text(
        "-----BEGIN CERTIFICATE-----\nredacted\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    return path


def make_manifest(**overrides):
    arguments = {
        "command": ["make", "phase3-internet-soak"],
        "repo": Path("."),
        "turn_realm": "relay.prod.test",
        "turn_uris": [
            "turn:relay.prod.test:3478?transport=udp",
            "turns:relay.prod.test:5349?transport=tcp",
        ],
        "authority_source_id": "turn-prod-a",
        "tls_certificate": certificate(Path(overrides.pop("directory")) / "fullchain.pem"),
        "signaling_origin": "https://signaling.prod.test",
        "relay_origin": "https://relay.prod.test",
        "duration_seconds": 7200,
        "planned_network_handoffs": ["wifi_to_cellular"],
        "notes": None,
    }
    arguments.update(overrides)
    return build_manifest(**arguments)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)


def assert_required_schema_fields(test_case: unittest.TestCase, value, schema):
    test_case.assertEqual(set(value), set(schema["properties"]))
    for field in schema.get("required", []):
        test_case.assertIn(field, value)


class Phase3InternetManifestTests(unittest.TestCase):
    @mock.patch("vibescreen_evidence.phase3_internet_manifest.require_public_remote_host")
    @mock.patch("vibescreen_evidence.phase3_internet_manifest.repository_state")
    def test_build_manifest_records_public_boundaries_without_raw_endpoints(self, state, public_host):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        public_host.return_value = ("8.8.8.8",)
        with tempfile.TemporaryDirectory() as directory_name:
            manifest = make_manifest(directory=directory_name)

        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["kind"], KIND)
        self.assertIn("real_remote_turn", manifest["evidence_boundaries"])
        self.assertEqual(manifest["evidence_boundaries"], REQUIRED_BOUNDARIES)
        self.assertEqual(manifest["required_artifacts"], REQUIRED_ARTIFACTS)
        self.assertFalse(manifest["privacy"]["raw_endpoints_recorded"])
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert_required_schema_fields(self, manifest, schema)
        rendered = json.dumps(manifest)
        self.assertNotIn("relay.prod.test", rendered)
        self.assertNotIn("turn-prod-a", rendered)

    @mock.patch("vibescreen_evidence.phase3_internet_manifest.require_public_remote_host")
    @mock.patch("vibescreen_evidence.phase3_internet_manifest.repository_state")
    def test_rejects_short_duration_missing_handoff_and_local_turn(self, state, public_host):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        public_host.return_value = ("8.8.8.8",)
        with tempfile.TemporaryDirectory() as directory_name:
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, duration_seconds=7199)
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, planned_network_handoffs=[])
            public_host.side_effect = ManifestError("local host")
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, turn_uris=["turn:127.0.0.1:3478?transport=udp"])

    @mock.patch("vibescreen_evidence.phase3_internet_manifest.require_public_remote_host")
    @mock.patch("vibescreen_evidence.phase3_internet_manifest.repository_state")
    def test_rejects_non_public_or_non_https_origins(self, state, public_host):
        state.return_value = {"revision": "abc", "dirty": False, "status_porcelain": []}
        public_host.return_value = ("8.8.8.8",)
        with tempfile.TemporaryDirectory() as directory_name:
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, signaling_origin="http://signaling.prod.test")
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, relay_origin="https://relay.prod.test/path")
            def reject_localhost(host):
                if host == "localhost":
                    raise ManifestError("local host")
                return ("8.8.8.8",)

            public_host.side_effect = reject_localhost
            with self.assertRaises(ManifestError):
                make_manifest(directory=directory_name, signaling_origin="https://localhost")

    @mock.patch("vibescreen_evidence.phase3_internet_manifest.require_public_remote_host")
    def test_cli_writes_manifest(self, public_host):
        public_host.return_value = ("8.8.8.8",)
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            init_repo(directory)
            cert = certificate(directory / "fullchain.pem")
            output = directory / "manifest.json"
            exit_code = main(
                [
                    "--output",
                    str(output),
                    "--repo",
                    str(directory),
                    "--turn-realm",
                    "relay.prod.test",
                    "--turn-uri",
                    "turns:relay.prod.test:5349?transport=tcp",
                    "--authority-source-id",
                    "turn-prod-a",
                    "--tls-certificate",
                    str(cert),
                    "--signaling-origin",
                    "https://signaling.prod.test",
                    "--relay-origin",
                    "https://relay.prod.test",
                    "--planned-network-handoffs",
                    "wifi_to_cellular",
                    "--",
                    "make",
                    "phase3-internet-soak",
                ]
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["kind"], KIND)


if __name__ == "__main__":
    unittest.main()
