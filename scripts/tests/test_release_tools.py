from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webrtc_m150_notices import NOTICE_RELATIVE_PATH, validate_notice_bundle
import generate_webrtc_m150_notices
import package_macos
import prepare_release
from phase3_webrtc.model import SUPPORTED_COTURN_VERSIONS


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SCRIPT = REPOSITORY_ROOT / "scripts/archive_artifact.py"
PREPARE_SCRIPT = REPOSITORY_ROOT / "scripts/prepare_release.py"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/release.yml"
PHASE0_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/phase0.yml"
MAKEFILE = REPOSITORY_ROOT / "Makefile"
PHASE3_RUNNER = REPOSITORY_ROOT / "scripts/phase3_webrtc/run_local_e2e.py"
ANDROID_BUILD = REPOSITORY_ROOT / "baseline/AndroidClient/app/build.gradle.kts"
VERSION = "1.2.3"
TAG = f"v{VERSION}"
COMMIT = "a" * 40
CREATED = "2026-08-05T10:00:00+08:00"


class ArchiveArtifactTests(unittest.TestCase):
    def test_archive_is_deterministic_when_source_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "Example.app"
            source.mkdir()
            binary = source / "Example"
            binary.write_bytes(b"binary")
            binary.chmod(0o755)
            first = root / "first.zip"
            second = root / "second.zip"

            subprocess.run(
                ["python3", str(ARCHIVE_SCRIPT), "--input", str(source), "--output", str(first)],
                check=True,
                capture_output=True,
                text=True,
            )
            binary.touch()
            subprocess.run(
                ["python3", str(ARCHIVE_SCRIPT), "--input", str(source), "--output", str(second)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest(),
            )
            with zipfile.ZipFile(first) as archive:
                mode = archive.getinfo("Example.app/Example").external_attr >> 16
                self.assertEqual(mode & 0o777, 0o755)


class MacOSSigningIdentityTests(unittest.TestCase):
    def test_explicit_ad_hoc_identity_skips_keychain_lookup(self) -> None:
        with mock.patch.object(package_macos.subprocess, "run") as run_mock:
            self.assertEqual(package_macos.resolve_sign_identity("-"), "-")
        run_mock.assert_not_called()

    def test_named_identity_is_returned_when_keychain_contains_it(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Vibe Screen Dev"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            self.assertEqual(
                package_macos.resolve_sign_identity("Vibe Screen Dev"),
                "Vibe Screen Dev",
            )

    def test_identity_lookup_requires_an_exact_name(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Production Vibe Screen Dev Certificate"\n'
                "     1 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "not found in the keychain"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_missing_named_identity_fails_instead_of_using_ad_hoc(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout="     0 valid identities found\n",
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "not found in the keychain"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_duplicate_named_identity_fails_instead_of_choosing_one(self) -> None:
        lookup = subprocess.CompletedProcess(
            args=("security", "find-identity"),
            returncode=0,
            stdout=(
                '  1) 0123456789ABCDEF0123456789ABCDEF01234567 '
                '"Vibe Screen Dev"\n'
                '  2) FEDCBA9876543210FEDCBA9876543210FEDCBA98 '
                '"Vibe Screen Dev"\n'
                "     2 valid identities found\n"
            ),
        )
        with mock.patch.object(package_macos.subprocess, "run", return_value=lookup):
            with self.assertRaisesRegex(SystemExit, "multiple codesign identities"):
                package_macos.resolve_sign_identity("Vibe Screen Dev")

    def test_main_resolves_identity_before_validating_or_building(self) -> None:
        arguments = mock.Mock(sign_identity="Vibe Screen Dev")
        with (
            mock.patch.object(package_macos, "parse_args", return_value=arguments),
            mock.patch.object(
                package_macos,
                "resolve_sign_identity",
                side_effect=SystemExit("missing identity"),
            ) as resolve_mock,
            mock.patch.object(package_macos, "validate_notice_bundle") as validate_mock,
            mock.patch.object(package_macos, "run") as run_mock,
        ):
            with self.assertRaisesRegex(SystemExit, "missing identity"):
                package_macos.main()
        resolve_mock.assert_called_once_with("Vibe Screen Dev")
        validate_mock.assert_not_called()
        run_mock.assert_not_called()


class PrepareReleaseTests(unittest.TestCase):
    def command(self, *extra: str) -> list[str]:
        return [
            "python3",
            str(PREPARE_SCRIPT),
            "--version",
            VERSION,
            "--tag",
            TAG,
            "--commit",
            COMMIT,
            "--created",
            CREATED,
            *extra,
        ]

    def write_artifacts(self, artifacts: Path, *, archive_content: bytes = b"binary") -> None:
        artifacts.mkdir()
        for name in (
            f"Vibe-Screen-macos-{VERSION}-arm64.zip",
            f"Vibe-Screen-android-{VERSION}-debug.apk",
            f"VibeScreen-ios-simulator-{VERSION}.zip",
        ):
            with zipfile.ZipFile(artifacts / name, "w") as archive:
                archive.writestr("payload.bin", archive_content)
        (artifacts / "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md").write_text(
            "# licenses\nGenerated from `debugRuntimeClasspath`.\n",
            encoding="utf-8",
        )
        (artifacts / "android-runtime.spdx.json").write_text(
            json.dumps(
                {
                    "packages": [
                        {
                            "SPDXID": "SPDXRef-Package-example",
                            "name": "example:runtime:1.0.0",
                            "versionInfo": "1.0.0",
                            "downloadLocation": "NOASSERTION",
                            "licenseConcluded": "Apache-2.0",
                            "licenseDeclared": "Apache-2.0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_validation_rejects_prerelease_tag(self) -> None:
        command = self.command("--validate-only")
        command[command.index(VERSION)] = "1.2.3-rc.1"
        command[command.index(TAG)] = "v1.2.3-rc.1"
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stable SemVer", result.stderr)

    def test_validation_rejects_android_version_code_collision(self) -> None:
        command = self.command("--validate-only")
        command[command.index(VERSION)] = "1.100.0"
        command[command.index(TAG)] = "v1.100.0"
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most 99", result.stderr)

    def test_macos_packaging_notice_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(FileNotFoundError, "notice bundle is missing"):
                validate_notice_bundle(root)
            notice = root / NOTICE_RELATIVE_PATH
            notice.parent.mkdir(parents=True)
            notice.write_text("incomplete notice", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                validate_notice_bundle(root)

        with mock.patch.object(
            generate_webrtc_m150_notices,
            "SOURCES",
            generate_webrtc_m150_notices.SOURCES[:-1],
        ):
            with self.assertRaisesRegex(ValueError, "exactly 32 components"):
                validate_notice_bundle(REPOSITORY_ROOT)
        altered_sources = list(generate_webrtc_m150_notices.SOURCES)
        altered_sources[0] = (*altered_sources[0][:-1], "abseil-cpp/NOTICE")
        with mock.patch.object(generate_webrtc_m150_notices, "SOURCES", tuple(altered_sources)):
            with self.assertRaisesRegex(ValueError, "source manifest SHA-256 mismatch"):
                validate_notice_bundle(REPOSITORY_ROOT)

    def test_release_notice_archive_fails_when_m150_bundle_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with mock.patch.object(prepare_release, "REPOSITORY_ROOT", root):
                with self.assertRaisesRegex(FileNotFoundError, "notice bundle is missing"):
                    prepare_release.write_notices_archive(
                        VERSION,
                        root / "artifacts",
                        root / "notices.zip",
                    )

    def test_prepare_generates_complete_release_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            output = root / "output"
            self.write_artifacts(artifacts)

            prepare_command = self.command("--artifacts-dir", str(artifacts), "--output-dir", str(output))
            subprocess.run(prepare_command, check=True, capture_output=True, text=True)
            subprocess.run(prepare_command, check=True, capture_output=True, text=True)

            checksum_lines = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(checksum_lines, sorted(checksum_lines, key=lambda line: line.split("  ", 1)[1]))
            self.assertEqual(len(checksum_lines), 5)
            sbom = json.loads((output / f"vibe-screen-{VERSION}.spdx.json").read_text(encoding="utf-8"))
            self.assertEqual(sbom["creationInfo"]["created"], "2026-08-05T02:00:00Z")
            package_names = {package["name"] for package in sbom["packages"]}
            self.assertTrue({"example:runtime:1.0.0", "webrtc", "swift-protobuf"} <= package_names)
            self.assertIn("boringssl", package_names)
            self.assertIn("libsrtp", package_names)
            component_packages = [
                package
                for package in sbom["packages"]
                if package["SPDXID"].startswith("SPDXRef-Package-webrtc-m150-component-")
            ]
            self.assertEqual(len(component_packages), 32)
            self.assertEqual(
                [package["name"] for package in sbom["packages"]].count("swift-protobuf"),
                1,
            )
            self.assertTrue(all(package["filesAnalyzed"] is False for package in sbom["packages"]))
            contains = [
                relationship
                for relationship in sbom["relationships"]
                if relationship["relationshipType"] == "CONTAINS"
            ]
            self.assertEqual(len(contains), 32)
            self.assertTrue(all(item["spdxElementId"] == "SPDXRef-Package-webrtc" for item in contains))
            notices = output / f"vibe-screen-{VERSION}-notices.zip"
            with zipfile.ZipFile(notices) as archive:
                suffix = NOTICE_RELATIVE_PATH.as_posix()
                self.assertTrue(any(name.endswith(suffix) for name in archive.namelist()))
            notes = (output / "RELEASE_NOTES.md").read_text(encoding="utf-8")
            self.assertIn(f"Vibe Screen {VERSION}", notes)
            self.assertNotIn("{{", notes)

    def test_prepare_rejects_secret_inside_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(
                artifacts,
                archive_content=b'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"',
            )

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("privacy/secret scan failed", result.stderr)
            self.assertIn("payload.bin", result.stderr)

    def test_prepare_rejects_private_user_path_inside_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts, archive_content=b"/Users/release-runner/private/file")

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("user_absolute_path", result.stderr)

    def test_prepare_rejects_secret_in_final_sbom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts)
            sbom_path = artifacts / "android-runtime.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            sbom["packages"][0]["api_token"] = "0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"
            sbom_path.write_text(json.dumps(sbom), encoding="utf-8")

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"vibe-screen-{VERSION}.spdx.json", result.stderr)

    def test_prepare_rejects_secret_in_final_notices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifacts = root / "artifacts"
            self.write_artifacts(artifacts)
            (artifacts / "ANDROID_RUNTIME_DEPENDENCY_LICENSES.md").write_text(
                'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                self.command("--artifacts-dir", str(artifacts), "--output-dir", str(root / "output")),
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"vibe-screen-{VERSION}-notices.zip", result.stderr)

    def test_release_scan_distinguishes_compiled_literals_from_credentials(self) -> None:
        compiled_literals = (
            b"token=\x00\x01"
            b'\x00"signaling_token":"device-token-abcdefghijklmnopqrstuvwxyz"'
            b'\x00"credential":"turn-password"'
            b'\x00"signaling_url":"https://signal.example.test"'
        )
        self.assertEqual(prepare_release.release_scan_findings(compiled_literals), {})

        findings = prepare_release.release_scan_findings(
            b'api_token="0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"'
        )
        self.assertIn("credential_material", findings)
        unquoted_findings = prepare_release.release_scan_findings(
            b"api_token=0xP9vL2kQ7mN4sR8wT1yU6aD3fG5hJ0cB"
        )
        self.assertIn("credential_material", unquoted_findings)

    def test_release_scan_rejects_hardware_identifier_and_uncontrolled_endpoint(self) -> None:
        findings = prepare_release.release_scan_findings(
            b'{"hardware_serial":"C02REALSECRET",'
            b'"signaling_url":"https://signal.private.invalid"}'
        )
        self.assertIn("hardware_identifier", findings)
        self.assertIn("endpoint", findings)

    def test_release_scan_rejects_windows_user_path(self) -> None:
        findings = prepare_release.release_scan_findings(
            b"C:\\Users\\random-user\\private.bin"
        )
        self.assertIn("user_absolute_path", findings)

    def test_macos_release_build_remaps_source_paths(self) -> None:
        package_script = (REPOSITORY_ROOT / "scripts/package_macos.py").read_text(encoding="utf-8")
        self.assertIn('"-file-prefix-map"', package_script)
        self.assertIn('PRODUCT_NAME = "Vibe Screen"', package_script)
        self.assertIn('EXECUTABLE_NAME = PRODUCT_NAME', package_script)
        self.assertIn('run("strip", "-S", str(macos_dir / EXECUTABLE_NAME))', package_script)
        self.assertIn('SIGN_IDENTITY_ENV = "VIBE_SCREEN_SIGN_IDENTITY"', package_script)
        self.assertNotIn("TELEMACHUS_SIGN_IDENTITY", package_script)
        phase0_workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        release_workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "python3 scripts/package_macos.py --sign-identity -",
            phase0_workflow,
        )
        self.assertIn(
            'python3 scripts/package_macos.py --version "$RELEASE_VERSION" --sign-identity -',
            release_workflow,
        )
        self.assertIn("name: vibe-screen-macos-ad-hoc-signed", phase0_workflow)
        self.assertNotIn(
            "#filePath",
            (REPOSITORY_ROOT / "baseline/MacHost/Sources/ProtocolV1SelfTest.swift").read_text(
                encoding="utf-8"
            ),
        )

    def test_release_workflow_binds_tag_to_all_successful_main_gates_and_debug_audit(self) -> None:
        workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('test "$commit" = "$(git rev-parse refs/remotes/origin/main)"', workflow)
        self.assertNotIn("merge-base --is-ancestor", workflow)

        validate_job_match = re.search(
            r"(?ms)^  validate:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(validate_job_match)
        validate_job = validate_job_match.group("body")
        permissions_match = re.search(
            r"(?ms)^    permissions:\n(?P<body>(?:^      [a-z-]+: [a-z]+\n)+)",
            validate_job,
        )
        self.assertIsNotNone(permissions_match)
        validate_permissions = dict(
            line.strip().split(": ", 1)
            for line in permissions_match.group("body").splitlines()
        )
        self.assertEqual(
            validate_permissions,
            {"actions": "read", "contents": "read"},
        )

        self.assertEqual(validate_job.count("require_successful_main_run()"), 1)
        helper_contracts = (
            '"repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow}/runs"',
            "-f branch=main",
            "-f event=push",
            "-f status=success",
            'select(.head_sha == \\"$commit\\")',
        )
        for contract in helper_contracts:
            self.assertIn(contract, validate_job)
        gate_calls = set(
            re.findall(
                r'^          require_successful_main_run ([a-z0-9.]+) "([^"]+)"$',
                validate_job,
                flags=re.MULTILINE,
            )
        )
        self.assertEqual(
            gate_calls,
            {
                ("phase0.yml", "Phase 0 checks"),
                ("ios.yml", "iOS engineering gates"),
                ("harmony.yml", "HarmonyOS portable checks"),
            },
        )
        self.assertIn("-PdependencyAuditConfiguration=debugRuntimeClasspath", workflow)
        android_build = ANDROID_BUILD.read_text(encoding="utf-8")
        self.assertIn('getByName(dependencyAuditConfiguration)', android_build)
        self.assertIn('inputs.property("dependencyAuditConfiguration"', android_build)

    def test_phase0_android_job_builds_instrumentation_test_apk(self) -> None:
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        android_job_match = re.search(
            r"(?ms)^  android:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(android_job_match)
        android_job = android_job_match.group("body")

        baseline_gate = "- run: make baseline-android-check"
        instrumentation_gate = (
            "- name: Build Android instrumentation test APK\n"
            "        run: cd baseline/AndroidClient && ./gradlew assembleDebugAndroidTest"
        )
        self.assertIn(baseline_gate, android_job)
        self.assertIn(instrumentation_gate, android_job)
        self.assertLess(android_job.index(baseline_gate), android_job.index(instrumentation_gate))
        self.assertEqual(android_job.count("assembleDebugAndroidTest"), 1)
        self.assertNotIn("connectedDebugAndroidTest", android_job)

    def test_phase3_gate_discovers_current_and_legacy_runner_tests(self) -> None:
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        makefile = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn("run: make phase3-test", workflow)
        for discovery in (
            "python3 -m unittest discover -s tests/phase3 -p 'test_*.py' -v",
            "python3 -m unittest discover -s tests/phase3_webrtc -p 'test_*.py' -v",
        ):
            self.assertEqual(makefile.count(discovery), 1)
        runner = PHASE3_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("print(peer_output", runner)
        self.assertIn("print_success_summary(arguments.mode, arguments.slice)", runner)

    def test_phase0_macos_job_gates_local_synthetic_product_direct_and_forced_relay_e2e(
        self,
    ) -> None:
        self.assertEqual(
            SUPPORTED_COTURN_VERSIONS,
            ("4.15.0", "4.16.0", "4.17.0"),
        )
        workflow_coturn_versions = "|".join(SUPPORTED_COTURN_VERSIONS)
        makefile_coturn_versions = " ".join(SUPPORTED_COTURN_VERSIONS)
        workflow = PHASE0_WORKFLOW.read_text(encoding="utf-8")
        macos_job_match = re.search(
            r"(?ms)^  macos:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(macos_job_match)
        macos_job = macos_job_match.group("body")
        for contract in (
            "runs-on: macos-15",
            "timeout-minutes: 20",
            "go-version: 1.25.12",
            'python-version: "3.11"',
            "brew install coturn",
            'turnserver_path="$(brew --prefix coturn)/bin/turnserver"',
            workflow_coturn_versions,
            "Unsupported Homebrew coturn version",
            "Install local Phase 3 synthetic product E2E dependencies",
            "Gate local synthetic Protocol v1 harness direct and forced-relay product E2E",
            "make phase3-local-synthetic-product-e2e",
            'jq -e -s --arg commit "$GITHUB_SHA"',
            ".environment.repository_commit == $commit",
            ".environment.repository_source.dirty == false",
            "id: phase3_synthetic_gate",
            "--output .build/phase3-local-synthetic-product-e2e/public",
            "steps.phase3_synthetic_gate.outcome == 'success'",
            "steps.phase3_synthetic_public_summaries.outcome == 'success'",
            "name: phase3-local-synthetic-product-e2e-public",
            "path: .build/phase3-local-synthetic-product-e2e/public",
            "if-no-files-found: error",
            "--output .build/phase3-local-synthetic-product-e2e/public-failure --failure-diagnostic",
            "steps.phase3_synthetic_gate.outcome == 'failure'",
            "name: phase3-local-synthetic-product-e2e-failure-diagnostic",
            "path: .build/phase3-local-synthetic-product-e2e/public-failure",
            "include-hidden-files: true",
        ):
            self.assertIn(contract, macos_job)
        self.assertNotIn("--allow-missing", macos_job)
        self.assertRegex(
            macos_job,
            r"(?ms)Validate local Phase 3 synthetic product E2E public summaries.*?"
            r"if: \$\{\{ always\(\) && steps\.phase3_synthetic_gate\.outcome == 'success' \}\}.*?"
            r"public_artifacts\.py.*?--output \.build/phase3-local-synthetic-product-e2e/public\s*$",
        )
        self.assertNotIn("make phase3-local-product-e2e", macos_job)
        self.assertNotIn(".build/phase3-local-product-e2e", macos_job)
        self.assertNotRegex(
            macos_job,
            r"(?m)^\s+path: \.build/phase3-local-synthetic-product-e2e\s*$",
        )
        self.assertIn(
            ".build/phase3-local-synthetic-product-e2e/relay.json >/dev/null",
            macos_job,
        )

        makefile = MAKEFILE.read_text(encoding="utf-8")
        for contract in (
            "phase3-local-synthetic-product-e2e:",
            "PHASE3_LOCAL_SYNTHETIC_E2E_DIR ?= "
            ".build/phase3-local-synthetic-product-e2e",
            "PHASE3_LOCAL_SYNTHETIC_E2E_TIMEOUT_SECONDS ?= 90",
            "phase3-local-product-e2e:",
            "phase3-local-product-e2e is deprecated; use "
            "phase3-local-synthetic-product-e2e",
            "synthetic Protocol v1 harness only; no Android device or "
            "ScreenCaptureKit capture",
            "$(MAKE) phase3-local-synthetic-product-e2e",
            f"PHASE3_COTURN_COMPATIBLE_VERSIONS := {makefile_coturn_versions}",
            "--mode direct --slice product",
            "--mode relay --slice product --skip-build",
            "--diagnostics-dir",
            '--output "$(PHASE3_LOCAL_SYNTHETIC_E2E_PUBLIC_DIR)"',
            "@jq -e 'select(",
            '.product_session.device == "synthetic Protocol v1 harness"',
            ".product_session.capture_or_stream_server_started == false",
            '.coturn.forced_libwebrtc_relay == "pass"',
        ):
            self.assertIn(contract, makefile)
        self.assertEqual(makefile.count('json" >/dev/null'), 2)
        self.assertNotIn(".build/phase3-local-product-e2e", makefile)
        self.assertNotIn("PHASE3_LOCAL_E2E_", makefile)


if __name__ == "__main__":
    unittest.main()
