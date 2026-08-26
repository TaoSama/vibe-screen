from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.phase5_multi_client_current_base_gate import (
    REQUIRED_ARTIFACTS,
    REQUIRED_ARTIFACT_KINDS,
    REQUIRED_ARTIFACT_OBSERVATIONS,
    REQUIRED_TRUE_FIELDS,
    derive_gate,
    main,
)


def write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def base_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "phase5_multi_client_concurrency_evidence",
        "source_revision": "abc123",
        "client_count": 2,
        "stream_count": 2,
        "artifacts": list(REQUIRED_ARTIFACTS),
        "devices": [
            {
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": 36,
            },
            {
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": 36,
            },
        ],
        "ios_owner_status_recorded": True,
        "harmony_owner_status_recorded": True,
    }
    for field in REQUIRED_TRUE_FIELDS:
        manifest[field] = True
    manifest.update(overrides)
    return manifest


def write_required_artifacts(root: Path) -> None:
    for artifact in REQUIRED_ARTIFACTS:
        document: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "kind": REQUIRED_ARTIFACT_KINDS[artifact],
            "source_revision": "abc123",
        }
        for field in REQUIRED_ARTIFACT_OBSERVATIONS[artifact]:
            document[field] = True
        if artifact.startswith("android-client-"):
            document["device"] = {
                "manufacturer": "nubia",
                "model": "P0110",
                "codename": "pacific",
                "android_release": "16",
                "sdk": 36,
            }
        write_json(root / artifact, document)


class Phase5MultiClientCurrentBaseGateTests(unittest.TestCase):
    def test_missing_manifest_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            result = derive_gate(Path(directory_name))

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["can_close_phase5_multi_client_display_gate"])
        self.assertIn("blocked: evidence_manifest", result["reasons"])

    def test_single_client_multi_display_is_insufficient_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(
                root / "multi-client-concurrency.json",
                base_manifest(
                    client_count=1,
                    stream_count=2,
                    simultaneous_clients=False,
                    host_advertises_multi_client=False,
                    single_client_multiple_displays=True,
                ),
            )
            write_required_artifacts(root)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["can_use_single_client_display_evidence"])
        gate = next(item for item in result["gates"] if item["name"] == "multi_client_concurrency")
        self.assertIn("single-client multi-display evidence cannot close multi-client concurrency", gate["reasons"])

    def test_missing_retained_artifacts_blocks_even_when_manifest_claims_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            manifest = base_manifest(artifacts=[])
            write_json(root / "multi-client-concurrency.json", manifest)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        artifact_gate = next(item for item in result["gates"] if item["name"] == "retained_artifacts")
        self.assertIn("missing required artifact: host-routing.json", artifact_gate["reasons"])

    def test_nubia_p0110_identity_must_not_be_relabelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(
                root / "multi-client-concurrency.json",
                base_manifest(
                    devices=[
                        {
                            "manufacturer": "xiaomi",
                            "model": "P0110",
                            "codename": "fuxi",
                            "android_release": "16",
                            "sdk": 36,
                        }
                    ]
                ),
            )

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "fail")
        identity_gate = next(item for item in result["gates"] if item["name"] == "device_identity")
        self.assertIn("Nubia P0110 evidence must use codename pacific", identity_gate["reasons"])
        self.assertIn("P0110 evidence must not be relabeled as another manufacturer", identity_gate["reasons"])

    def test_declared_artifacts_without_files_do_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(root / "multi-client-concurrency.json", base_manifest())

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        artifact_gate = next(item for item in result["gates"] if item["name"] == "retained_artifacts")
        self.assertIn("missing required artifact: host-routing.json", artifact_gate["reasons"])

    def test_placeholder_artifact_json_does_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(root / "multi-client-concurrency.json", base_manifest())
            for artifact in REQUIRED_ARTIFACTS:
                write_json(root / artifact, {})

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        artifact_gate = next(item for item in result["gates"] if item["name"] == "retained_artifacts")
        self.assertIn("host-routing.json: schema_version must be vibescreen.evidence/v1", artifact_gate["reasons"])
        self.assertIn("host-routing.json: simultaneous_clients must be true", artifact_gate["reasons"])
        self.assertIn(
            "android-client-1.json: device must record manufacturer, model, codename, Android release, and SDK",
            artifact_gate["reasons"],
        )

    def test_header_only_artifacts_do_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(root / "multi-client-concurrency.json", base_manifest())
            for artifact in REQUIRED_ARTIFACTS:
                document: dict[str, object] = {
                    "schema_version": SCHEMA_VERSION,
                    "kind": REQUIRED_ARTIFACT_KINDS[artifact],
                    "source_revision": "abc123",
                }
                if artifact.startswith("android-client-"):
                    document["device"] = {
                        "manufacturer": "nubia",
                        "model": "P0110",
                        "codename": "pacific",
                        "android_release": "16",
                        "sdk": 36,
                    }
                write_json(root / artifact, document)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "blocked")
        artifact_gate = next(item for item in result["gates"] if item["name"] == "retained_artifacts")
        self.assertIn("host-routing.json: simultaneous_clients must be true", artifact_gate["reasons"])

    def test_complete_manifest_with_retained_artifact_files_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            write_json(root / "multi-client-concurrency.json", base_manifest())
            write_required_artifacts(root)

            result = derive_gate(root)

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["can_close_phase5_multi_client_display_gate"])
        self.assertTrue(result["can_claim_multi_client_concurrency"])

    def test_cli_writes_blocked_report_and_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            output = root / "phase5-multi-client-current-base-gate.json"

            exit_code = main(["--evidence-dir", str(root), "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
