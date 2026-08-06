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
import prepare_release
import generate_webrtc_m150_notices


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SCRIPT = REPOSITORY_ROOT / "scripts/archive_artifact.py"
PREPARE_SCRIPT = REPOSITORY_ROOT / "scripts/prepare_release.py"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/release.yml"
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
            f"Telemachus-macos-{VERSION}-arm64.zip",
            f"Telemachus-android-{VERSION}-debug.apk",
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
        self.assertIn('run("strip", "-S", str(macos_dir / APP_NAME))', package_script)
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


if __name__ == "__main__":
    unittest.main()
