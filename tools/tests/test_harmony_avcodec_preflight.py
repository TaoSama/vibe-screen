from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibescreen_evidence import harmony_avcodec_preflight
from vibescreen_evidence.manifest import ManifestError


def passing_manifest() -> dict[str, object]:
    manifest = harmony_avcodec_preflight.template_manifest()
    manifest["repository"] = {
        "revision": "a" * 40,
        "tree": "b" * 40,
        "dirty": False,
        "status_porcelain": [],
    }
    manifest["toolchain"] = {
        "deveco_studio_version": "DevEco Studio 6.0",
        "harmony_sdk_api": "API 12",
        "harmony_sdk_version": "5.0.0(12)",
        "hvigor_version": "5.0.2",
        "ohpm_version": "5.0.2",
        "hdc_version": "Ver: 3.1.0",
    }
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
    }
    for codec in manifest["codecs"]:
        codec["status"] = "pass"
        codec["decoder_name"] = f"avcodec.hardware.{codec['codec']}"
        codec["gates"] = {
            gate: "pass" for gate in harmony_avcodec_preflight.REQUIRED_CODEC_GATE_KEYS
        }
        codec["artifacts"] = [f"evidence/{codec['codec']}-hilog.txt"]
    return manifest


class HarmonyAvcodecPreflightTests(unittest.TestCase):
    def test_manifest_requires_h264_and_hevc_hardware_gates(self) -> None:
        manifest = passing_manifest()

        self.assertEqual(harmony_avcodec_preflight.validate_manifest(manifest), [])

    def test_manifest_rejects_android_identity(self) -> None:
        manifest = passing_manifest()
        manifest["device"] = {
            "platform": "Android",
            "manufacturer": "nubia",
            "model": "P0110",
            "product": "pacific",
            "os_build": "Android 16 SDK 36",
            "hdc_target": "not-applicable",
            "serial_hash": "3" * 64,
        }

        with self.assertRaisesRegex(ManifestError, "Android or simulator"):
            harmony_avcodec_preflight.validate_manifest(manifest)

    def test_manifest_rejects_blocked_or_missing_lifecycle_gate(self) -> None:
        manifest = passing_manifest()
        manifest["codecs"][0]["gates"]["flush_completed"] = "blocked"

        with self.assertRaisesRegex(ManifestError, "flush_completed"):
            harmony_avcodec_preflight.validate_manifest(manifest)

        manifest = passing_manifest()
        del manifest["codecs"][1]["gates"]["release_completed"]
        with self.assertRaisesRegex(ManifestError, "release_completed"):
            harmony_avcodec_preflight.validate_manifest(manifest)

    def test_manifest_rejects_software_decoder_name(self) -> None:
        manifest = passing_manifest()
        manifest["codecs"][1]["decoder_name"] = "software hevc decoder"

        with self.assertRaisesRegex(ManifestError, "hardware decoder identity"):
            harmony_avcodec_preflight.validate_manifest(manifest)

    def test_strict_manifest_rejects_leftover_blockers(self) -> None:
        manifest = passing_manifest()
        manifest["blockers"] = [harmony_avcodec_preflight.CODEC_RUN_BLOCKER]

        with self.assertRaisesRegex(ManifestError, "blockers"):
            harmony_avcodec_preflight.validate_manifest(manifest)
        self.assertEqual(
            harmony_avcodec_preflight.validate_manifest(manifest, allow_blocked=True),
            [],
        )

    def test_manifest_requires_schema_fields_checked_by_json_schema(self) -> None:
        for field in ("run_id", "created_at"):
            manifest = passing_manifest()
            del manifest[field]
            with self.subTest(field=field):
                with self.assertRaisesRegex(ManifestError, field):
                    harmony_avcodec_preflight.validate_manifest(manifest)

        manifest = passing_manifest()
        del manifest["repository"]["status_porcelain"]
        with self.assertRaisesRegex(ManifestError, "status_porcelain"):
            harmony_avcodec_preflight.validate_manifest(manifest)

    def test_template_is_blocked_readiness_not_acceptance(self) -> None:
        manifest = harmony_avcodec_preflight.template_manifest()

        with self.assertRaisesRegex(ManifestError, "placeholder zero value"):
            harmony_avcodec_preflight.validate_manifest(manifest)
        warnings = harmony_avcodec_preflight.validate_manifest(manifest, allow_blocked=True)
        self.assertGreaterEqual(len(warnings), len(harmony_avcodec_preflight.REQUIRED_CODEC_GATE_KEYS) * 2)

    def test_collector_writes_blocked_manifest_without_harmony_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "harmony-avcodec-preflight.json"
            with patch.object(harmony_avcodec_preflight, "_tool_probe") as tool_probe:
                tool_probe.side_effect = lambda name, _args: harmony_avcodec_preflight.ToolProbe(
                    name=name, path=None, version=None, error="not found"
                )
                exit_code = harmony_avcodec_preflight.main(["--output", str(output), "--repo", "."])
            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertIn("not found", "\n".join(document["blockers"]))
        warnings = harmony_avcodec_preflight.validate_manifest(document, allow_blocked=True)
        self.assertTrue(warnings)

    def test_repository_tree_is_read_from_requested_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name) / "repo"
            with (
                patch.object(harmony_avcodec_preflight, "repository_state") as repository_state,
                patch.object(harmony_avcodec_preflight, "_run") as run,
            ):
                repository_state.return_value = {"revision": "a" * 40, "dirty": False, "status_porcelain": []}
                run.return_value.stdout = "b" * 40
                run.return_value.returncode = 0

                state = harmony_avcodec_preflight._repository_with_tree(repo)

        self.assertEqual("b" * 40, state["tree"])
        run.assert_called_once_with(["git", "rev-parse", "HEAD^{tree}"], timeout_seconds=15.0, cwd=repo)

    def test_collector_stays_blocked_until_real_codec_artifacts_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            output = directory / "harmony-avcodec-preflight.json"
            hap = directory / "entry-release-signed.hap"
            hap.write_bytes(b"signed hap placeholder for hashing")
            with (
                patch.object(harmony_avcodec_preflight, "_tool_probe") as tool_probe,
                patch.object(harmony_avcodec_preflight, "_run") as run,
            ):
                tool_probe.side_effect = lambda name, _args: harmony_avcodec_preflight.ToolProbe(
                    name=name, path=f"/tools/{name}", version=f"{name} 1.0", error=None
                )
                run.return_value.stdout = "redacted-target MatePad Mini"
                run.return_value.stderr = ""
                run.return_value.returncode = 0
                exit_code = harmony_avcodec_preflight.main(
                    ["--output", str(output), "--repo", ".", "--hdc-target", "redacted-target", "--hap", str(hap)]
                )
            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 2)
        self.assertIn(harmony_avcodec_preflight.CODEC_RUN_BLOCKER, document["blockers"])
        self.assertTrue(all(codec["status"] == "blocked" for codec in document["codecs"]))


if __name__ == "__main__":
    unittest.main()
