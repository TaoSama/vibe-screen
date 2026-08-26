from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import harmony_device_gate
from vibescreen_evidence import harmony_hap_readiness as readiness


class HarmonyHapReadinessTests(unittest.TestCase):
    def repository(self, status: str = "clean") -> readiness.RepositoryState:
        return readiness.RepositoryState("a" * 40, "b" * 40, status, " M README.md" if status != "clean" else "")

    def tool_status(self, name: str, available: bool = True) -> readiness.ToolStatus:
        return readiness.ToolStatus(name, f"/tool/{name}" if available else "", available, f"{name} 1.0" if available else "", 0 if available else None)

    def toolchain(self) -> readiness.ToolchainState:
        return readiness.ToolchainState(
            "/Applications/DevEco-Studio.app",
            "5.0.0",
            "/sdk/harmony",
            "API 12",
            "5.0.0(12)",
            self.tool_status("ohpm"),
            self.tool_status("hvigor"),
            self.tool_status("hdc"),
        )

    def signing(self) -> readiness.SigningState:
        return readiness.SigningState(
            "apps/harmony/build-profile.json5",
            True,
            ["release.cer"],
            "c" * 64,
            "",
        )

    def artifact(self) -> readiness.ArtifactState:
        return readiness.ArtifactState(
            "apps/harmony/dist/0.1.0/vibe-screen-harmony-0.1.0.hap",
            True,
            "d" * 64,
            1234,
            True,
            ["META-INF/CERT.SF"],
            "apps/harmony/dist/0.1.0/SHA256SUMS",
            "e" * 64,
            True,
        )

    def device(self) -> readiness.DeviceState:
        return readiness.DeviceState(
            "matepad-target",
            True,
            "matepad-target device",
            "Huawei",
            "MatePad Mini",
            "MatePad Mini",
            "HarmonyOS NEXT build 1",
            "f" * 64,
            "bundleName: dev.vibescreen.harmony",
            True,
        )

    def lifecycle(self, status: str = "pass") -> list[readiness.LifecycleStep]:
        return [
            readiness.LifecycleStep(step, status, [f"{step}.txt"], "observed")
            for step in readiness.LIFECYCLE_STEPS
        ]

    def test_summary_passes_when_every_requirement_is_recorded(self) -> None:
        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            self.device(),
            self.lifecycle(),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )

        summary = readiness.summarize(observations, "run-pass")

        self.assertEqual(summary["verdict"], "pass")
        self.assertTrue(summary["can_close_hap_lifecycle_readiness"])
        self.assertEqual(summary["missing_requirements"], [])

    def test_harmony_sdk_api_must_be_recorded_as_supported_version(self) -> None:
        self.assertFalse(readiness.harmony_sdk_api_is_supported(""))
        self.assertFalse(readiness.harmony_sdk_api_is_supported("installed SDK path present"))
        self.assertFalse(readiness.harmony_sdk_api_is_supported("API 11"))
        self.assertTrue(readiness.harmony_sdk_api_is_supported("API 12"))
        self.assertTrue(readiness.harmony_sdk_api_is_supported("5.0.0(12)"))

    def test_public_text_sanitizer_redacts_local_paths_and_private_key_markers(self) -> None:
        user_path = "/" + "Users/example/Library/Application Support/" + "TCC" + "." + "db"
        private_key_marker = "-----BEGIN " + "PRIVATE" + " KEY----- secret -----END " + "PRIVATE" + " KEY-----"
        text = readiness.sanitize_public_text(
            f"see {user_path} and {private_key_marker}"
        )

        self.assertNotIn("/" + "Users/", text)
        self.assertNotIn("TCC" + "." + "db", text)
        self.assertNotIn("PRIVATE" + " KEY", text)
        self.assertIn("<redacted>", text)

    def test_explicit_harmony_sdk_path_is_recorded_without_absolute_user_path(self) -> None:
        sdk_path, sdk_api = readiness.detect_harmony_sdk("/" + "Users/example/Harmony/Sdk", "API 12")

        self.assertEqual(sdk_path, "<external>/Sdk")
        self.assertEqual(sdk_api, "API 12")

    def test_summary_blocks_when_deveco_hdc_and_hap_are_missing(self) -> None:
        blocked_toolchain = readiness.ToolchainState("", "", "", "", "5.0.0(12)", self.tool_status("ohpm", False), self.tool_status("hvigor", False), self.tool_status("hdc", False))
        observations = readiness.build_observations(
            self.repository(),
            blocked_toolchain,
            readiness.SigningState("build-profile.json5", False, [], "", "signingConfigs is empty"),
            readiness.ArtifactState("missing.hap", False, "", 0, False, [], "SHA256SUMS", "", False),
            readiness.DeviceState("", False, "hdc not found", "", "", "", "", "", "", False),
            self.lifecycle("insufficient"),
            None,
        )

        summary = readiness.summarize(observations, "run-blocked")

        self.assertEqual(summary["verdict"], "blocked")
        self.assertFalse(summary["can_close_hap_lifecycle_readiness"])
        fields = {item["field"] for item in summary["missing_requirements"]}
        self.assertIn("deveco_studio_available", fields)
        self.assertIn("signed_hap_present", fields)
        self.assertIn("hdc_target_selected", fields)

    def test_summary_fails_when_existing_hap_is_not_signed_zip(self) -> None:
        bad_artifact = readiness.ArtifactState("bad.hap", True, "d" * 64, 10, False, [], "SHA256SUMS", "e" * 64, False)
        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            bad_artifact,
            self.device(),
            self.lifecycle(),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )

        summary = readiness.summarize(observations, "run-fail")

        self.assertEqual(summary["verdict"], "fail")
        self.assertIn("signed_hap_present", {item["field"] for item in summary["missing_requirements"]})

    def test_summary_is_insufficient_when_only_lifecycle_observations_are_missing(self) -> None:
        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            self.device(),
            self.lifecycle("insufficient"),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )

        self.assertEqual(readiness.summarize(observations, "run-insufficient")["verdict"], "insufficient")

    def test_build_result_distinguishes_missing_tools_from_compile_failures(self) -> None:
        missing_tools = readiness.CommandResult(["make", "release"], 2, "", "HarmonyOS build blocked: hvigorw/hvigor not found")
        compile_failure = readiness.CommandResult(["make", "release"], 2, "", "ArkTS compile failed")

        self.assertEqual(readiness.build_result_status(missing_tools), "blocked")
        self.assertEqual(readiness.build_result_status(compile_failure), "fail")

    def test_collect_signing_rejects_private_key_containers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            private_container = Path(temporary_directory) / "release.private"
            private_container.write_bytes(b"not committed but still private material")

            with self.assertRaisesRegex(readiness.ReadinessError, "public certificate"):
                readiness.collect_signing(Path(temporary_directory), private_container, "")

    def test_collect_signing_rejects_malformed_certificate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(readiness.ReadinessError, "64-character hex"):
                readiness.collect_signing(Path(temporary_directory), None, "not-a-sha")

    def test_hdc_target_and_list_output_are_redacted(self) -> None:
        raw_target = "ABC123456789"
        redacted = readiness.redact_hdc_target(raw_target)

        self.assertRegex(redacted, r"^redacted-hdc-target-[0-9a-f]{12}$")
        self.assertNotIn(raw_target, redacted)
        output = readiness.redact_hdc_targets_output(f"{raw_target} device usb\n")
        self.assertIn(redacted, output)
        self.assertNotIn(raw_target, output)
        failed_output = readiness.hdc_target_list_evidence(
            readiness.CommandResult(["hdc", "list", "targets", "-v"], 127, "", "hdc not found"),
            "no HDC target listed",
        )
        self.assertEqual(failed_output, "# hdc list targets failed with exit 127\n# no HDC target listed\n")

    def test_requested_missing_hdc_target_is_not_recorded_as_device_evidence(self) -> None:
        with (
            mock.patch.object(readiness, "list_hdc_targets", return_value=readiness.CommandResult(["hdc", "list", "targets", "-v"], 0, "OTHER device\n", "")),
            mock.patch.object(readiness, "hdc_shell") as shell,
        ):
            device = readiness.collect_device(self.tool_status("hdc"), "MISSING-SERIAL", readiness.DEFAULT_PACKAGE, "/usr/bin/hdc")

        self.assertFalse(device.target_selected)
        self.assertEqual(device.hdc_target, "")
        self.assertEqual(device.serial_hash, "")
        shell.assert_not_called()

    def test_inspect_hap_records_signature_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hap = root / "signed.hap"
            sums = root / "SHA256SUMS"
            with zipfile.ZipFile(hap, "w") as archive:
                archive.writestr("META-INF/CERT.SF", "signature")
                archive.writestr("entry/module.json", "{}")
            sums.write_text("hash signed.hap\n", encoding="utf-8")

            artifact = readiness.inspect_hap(hap, sums)

        self.assertTrue(artifact.exists)
        self.assertTrue(artifact.zip_readable)
        self.assertEqual(artifact.signature_entries, ["META-INF/CERT.SF"])
        self.assertRegex(artifact.sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(artifact.sha256sums_sha256, r"^[0-9a-f]{64}$")
        self.assertFalse(artifact.sha256sums_contains_hap)

    def test_signed_hap_requires_sha256sums_linkage(self) -> None:
        artifact_without_linkage = readiness.ArtifactState(
            "apps/harmony/dist/0.1.0/vibe-screen-harmony-0.1.0.hap",
            True,
            "d" * 64,
            1234,
            True,
            ["META-INF/CERT.SF"],
            "apps/harmony/dist/0.1.0/SHA256SUMS",
            "e" * 64,
            False,
        )

        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            artifact_without_linkage,
            self.device(),
            self.lifecycle(),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )

        summary = readiness.summarize(observations, "run-missing-sums-linkage")

        self.assertEqual(summary["verdict"], "fail")
        self.assertIn("signed_hap_present", {item["field"] for item in summary["missing_requirements"]})

    def test_lifecycle_observations_require_evidence_for_recorded_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "lifecycle.json"
            path.write_text(json.dumps({"steps": {"install": {"status": "pass", "evidence": []}}}), encoding="utf-8")

            with self.assertRaisesRegex(readiness.ReadinessError, "install.evidence"):
                readiness.load_lifecycle(path)

    def test_pass_lifecycle_observations_require_local_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            (evidence_dir / "install-hilog.txt").write_text("ok", encoding="utf-8")
            path = root / "lifecycle.json"
            path.write_text(
                json.dumps(
                    {
                        "steps": {
                            "install": {"status": "pass", "evidence": ["install-hilog.txt"]},
                            "upgrade": {"status": "pass", "evidence": ["../upgrade.txt"]},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(readiness.ReadinessError, "upgrade.evidence pass entries"):
                readiness.load_lifecycle(path, evidence_dir)

    def test_pass_lifecycle_observations_accept_existing_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for step in readiness.LIFECYCLE_STEPS:
                (root / f"{step}.txt").write_text("observed", encoding="utf-8")
            path = root / "lifecycle.json"
            path.write_text(
                json.dumps(
                    {
                        "steps": {
                            step: {"status": "pass", "evidence": [f"{step}.txt"]}
                            for step in readiness.LIFECYCLE_STEPS
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                [step.status for step in readiness.load_lifecycle(path, root)],
                ["pass"] * len(readiness.LIFECYCLE_STEPS),
            )

    def test_matepad_identity_requires_harmony_os_build(self) -> None:
        android_matepad = readiness.DeviceState(
            "redacted-target",
            True,
            "redacted-target device",
            "Huawei",
            "MatePad Mini",
            "MatePad Mini",
            "Android 16",
            "f" * 64,
            "bundleName: dev.vibescreen.harmony",
            True,
        )

        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            android_matepad,
            self.lifecycle("insufficient"),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )

        self.assertIn(
            "matepad_mini_identity_recorded",
            {item["field"] for item in readiness.summarize(observations, "run")["missing_requirements"]},
        )

    def test_generated_device_manifest_is_allow_blocked_valid_and_requires_new_lifecycle_gates(self) -> None:
        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            self.device(),
            self.lifecycle("insufficient"),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )
        summary = readiness.summarize(observations, "run")
        result = readiness.ReadinessResult(
            readiness.SCHEMA,
            "run",
            "2026-08-21T00:00:00Z",
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            self.device(),
            self.lifecycle("insufficient"),
            observations,
            summary,
        )

        manifest = readiness.device_gate_manifest(result, readiness.DEFAULT_PACKAGE)

        gate_ids = {gate["id"] for gate in manifest["gates"]}
        self.assertIn("hap_in_place_upgrade", gate_ids)
        self.assertIn("hap_rollback_behavior", gate_ids)
        self.assertIn("hap_uninstall_cleanup", gate_ids)
        self.assertIn("resume_capable_host_interop", gate_ids)
        secure_pairing_gate = next(
            gate for gate in manifest["gates"] if gate["id"] == "huks_backed_secure_pairing"
        )
        self.assertEqual(
            {
                "schema": harmony_device_gate.SECURE_PAIRING_MANIFEST_SCHEMA,
                "path": "harmony-secure-pairing.json",
                "status": "blocked",
            },
            secure_pairing_gate["secure_pairing_manifest"],
        )
        warnings = harmony_device_gate.validate_manifest(manifest, allow_blocked=True)
        self.assertIn("hap_in_place_upgrade: blocked", warnings)

    def test_generated_device_manifest_does_not_promote_non_matepad_identity(self) -> None:
        android_like_device = readiness.DeviceState(
            "not-matepad",
            True,
            "not-matepad device",
            "nubia",
            "P0110",
            "pacific",
            "Android 16",
            "f" * 64,
            "bundleName: dev.vibescreen.harmony",
            True,
        )
        observations = readiness.build_observations(
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            android_like_device,
            self.lifecycle("insufficient"),
            readiness.CommandResult(["make", "release"], 0, "ok", ""),
        )
        result = readiness.ReadinessResult(
            readiness.SCHEMA,
            "run",
            "2026-08-21T00:00:00Z",
            self.repository(),
            self.toolchain(),
            self.signing(),
            self.artifact(),
            android_like_device,
            self.lifecycle("insufficient"),
            observations,
            readiness.summarize(observations, "run"),
        )

        manifest = readiness.device_gate_manifest(result, readiness.DEFAULT_PACKAGE)

        self.assertIn("blocked", manifest["device"]["model"])
        self.assertIn("blocked", manifest["device"]["platform"])
        harmony_device_gate.validate_manifest(manifest, allow_blocked=True)

    def test_main_returns_insufficient_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            lifecycle_path = Path(temporary_directory) / "lifecycle.json"
            lifecycle_path.write_text(
                json.dumps({"steps": {step: {"status": "insufficient", "evidence": [f"{step}.txt"]} for step in readiness.LIFECYCLE_STEPS}}),
                encoding="utf-8",
            )
            with (
                mock.patch.object(readiness, "repository_state", return_value=self.repository()),
                mock.patch.object(readiness, "collect_toolchain", return_value=self.toolchain()),
                mock.patch.object(readiness, "collect_signing", return_value=self.signing()),
                mock.patch.object(readiness, "inspect_hap", return_value=self.artifact()),
                mock.patch.object(readiness, "collect_device", return_value=self.device()),
            ):
                exit_code = readiness.main(["--evidence-dir", str(evidence_dir), "--run-id", "run-insufficient", "--lifecycle-observations", str(lifecycle_path)])

            self.assertEqual(exit_code, readiness.INSUFFICIENT_EXIT)
            summary = json.loads((evidence_dir / "harmony-hap-readiness-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["verdict"], "insufficient")

    def test_main_returns_fail_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(readiness, "repository_state", return_value=self.repository()),
                mock.patch.object(readiness, "collect_toolchain", return_value=self.toolchain()),
                mock.patch.object(readiness, "collect_signing", return_value=self.signing()),
                mock.patch.object(readiness, "inspect_hap", return_value=readiness.ArtifactState("bad.hap", True, "d" * 64, 10, False, [], "SHA256SUMS", "e" * 64, False)),
                mock.patch.object(readiness, "collect_device", return_value=self.device()),
            ):
                exit_code = readiness.main(["--evidence-dir", str(evidence_dir), "--run-id", "run-fail"] )

            self.assertEqual(exit_code, 1)
            summary = json.loads((evidence_dir / "harmony-hap-readiness-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["verdict"], "fail")

    def test_main_writes_blocked_evidence_when_environment_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            evidence_dir = Path(temporary_directory) / "evidence"
            with (
                mock.patch.object(readiness, "repository_state", return_value=self.repository()),
                mock.patch.object(
                    readiness,
                    "collect_toolchain",
                    return_value=readiness.ToolchainState("", "", "", "", "5.0.0(12)", self.tool_status("ohpm", False), self.tool_status("hvigor", False), self.tool_status("hdc", False)),
                ),
            ):
                exit_code = readiness.main(["--evidence-dir", str(evidence_dir), "--run-id", "run-blocked"])

            self.assertEqual(exit_code, readiness.BLOCKED_EXIT)
            summary = json.loads((evidence_dir / "harmony-hap-readiness-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["verdict"], "blocked")
            self.assertTrue((evidence_dir / "harmony-device-gates.json").exists())
            self.assertIn("HarmonyOS HAP lifecycle readiness: blocked", (evidence_dir / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
