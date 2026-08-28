from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harmony_readiness


COMMIT = "a" * 40
TREE = "b" * 40
CERT_HASH = "1" * 64
HOST_HASH = "2" * 64


def completed(command: list[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def fake_runner(command, **_kwargs):
    if command[:3] == ["/mock/hdc", "list", "targets"]:
        return completed(command, "HMTEST123 device product:MatePad Mini\n")
    if command[:5] == ["/mock/hdc", "-t", "HMTEST123", "shell", "param"]:
        prop = command[-1]
        values = {
            "const.product.manufacturer": "Huawei",
            "const.product.model": "MatePad Mini",
            "const.product.name": "MatePad Mini",
            "const.ohos.fullname": "HarmonyOS NEXT 5.0.0",
            "const.ohos.apiversion": "12",
            "const.product.serial": "raw-" + "private-serial",
        }
        return completed(command, values.get(prop, ""))
    if command[0] in {"/mock/hvigor", "/mock/ohpm", "/mock/hdc"}:
        return completed(command, f"{Path(command[0]).name} 1.0\n")
    if command[:3] == ["git", "rev-parse", "HEAD^{tree}"]:
        return completed(command, TREE)
    raise AssertionError(f"unexpected command: {command}")


def fake_which(name: str) -> str | None:
    return {
        "hvigor": "/mock/hvigor",
        "ohpm": "/mock/ohpm",
        "hdc": "/mock/hdc",
    }.get(name)


def make_signed_hap(directory: Path) -> tuple[Path, Path]:
    hap = directory / "vibe-screen-harmony-0.1.0.hap"
    with zipfile.ZipFile(hap, "w") as archive:
        archive.writestr("module.json", "{}")
        archive.writestr("META-INF/CERT.RSA", "signed")
    sha = harmony_readiness.sha256_file(hap)
    sums = directory / "SHA256SUMS"
    sums.write_text(f"{sha}  {hap.name}\n", encoding="utf-8")
    return hap, sums


class HarmonyReadinessTests(unittest.TestCase):
    def test_parse_hdc_targets_ignores_headers_and_empty_rows(self) -> None:
        targets = harmony_readiness.parse_hdc_targets(
            "List of devices attached\nempty\nHMTEST123 device product:MatePad Mini\n"
        )

        self.assertEqual(targets, [("HMTEST123", "device", "HMTEST123 device product:MatePad Mini")])

    def test_missing_tools_fail_closed_without_throwing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name)
            args = argparse.Namespace(
                repo=repo,
                deveco_studio_app=repo / "missing.app",
                target=None,
                hap=None,
                sha256sums=None,
                signature_certificate_sha256=None,
                bundle_name="dev.vibescreen.harmony",
                version_name="0.1.0",
                host_commit=None,
                host_build_sha256=None,
            )
            with mock.patch.object(
                harmony_readiness,
                "repository_state",
                return_value={"revision": COMMIT, "dirty": False, "status_porcelain": []},
            ):
                report = harmony_readiness.collect_readiness(args, which_runner=lambda _name: None)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("hvigor not found on PATH", report["blocking_reasons"])
        self.assertIn("hdc is unavailable", report["blocking_reasons"])
        self.assertIsNone(report["device"])

    def test_collects_pass_readiness_with_toolchain_hap_and_matepad(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name)
            deveco = repo / "DevEco-Studio.app"
            deveco.mkdir()
            hap, sums = make_signed_hap(repo)
            args = argparse.Namespace(
                repo=repo,
                deveco_studio_app=deveco,
                target=None,
                hap=hap,
                sha256sums=sums,
                signature_certificate_sha256=CERT_HASH,
                bundle_name="dev.vibescreen.harmony",
                version_name="0.1.0",
                host_commit=COMMIT,
                host_build_sha256=HOST_HASH,
            )
            with (
                mock.patch.object(
                    harmony_readiness,
                    "repository_state",
                    return_value={"revision": COMMIT, "dirty": False, "status_porcelain": []},
                ),
                mock.patch.object(harmony_readiness, "_git_tree", return_value=TREE),
            ):
                report = harmony_readiness.collect_readiness(
                    args,
                    command=["scripts/harmony_readiness.py", "--output", "out.json"],
                    command_runner=fake_runner,
                    which_runner=fake_which,
                )

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["blocking_reasons"], [])
        self.assertTrue(report["device"]["is_matepad_mini"])
        self.assertNotIn("raw-" + "private-serial", json.dumps(report))
        self.assertEqual(report["device_gate_prefill"]["repository"]["tree"], TREE)
        self.assertEqual(report["device_gate_prefill"]["artifact"]["signature_certificate_sha256"], CERT_HASH)
        self.assertEqual(report["device_gate_prefill"]["device"]["platform"], "HarmonyOS NEXT")
        self.assertIn("sha256:", report["device_gate_prefill"]["device"]["hdc_target"])

    def test_public_report_redacts_command_paths_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            repo = Path(directory_name)
            external_hap = Path("/Users/example/private/device-release.hap")
            probe = harmony_readiness.Probe(
                name="hdc",
                status="blocked",
                path="/Users/example/bin/hdc",
                detail="failed reading " + "/Users/example/Library/" + "Application Support/" + "com.apple.TCC/" + "TCC" + ".db",
            )

            command = harmony_readiness.public_command(
                [
                    "scripts/harmony_readiness.py",
                    "--output",
                    str(repo / "out.json"),
                    "--target",
                    "HMREAL" + "123456",
                    f"--hap={external_hap}",
                ],
                repo=repo,
            )
            public_probe = harmony_readiness.public_probe(probe, repo=repo)
            serialized = json.dumps({"command": command, "probe": public_probe})

        self.assertNotIn("HMREAL" + "123456", serialized)
        self.assertNotIn("/Users/example", serialized)
        self.assertNotIn("Application Support/" + "com.apple.TCC", serialized)
        self.assertNotIn("TCC" + ".db", serialized)
        self.assertIn("sha256:", serialized)
        self.assertIn("<external>/device-release.hap", serialized)

    def test_rejects_hap_without_checksum_or_signature_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            hap = directory / "unsigned.hap"
            with zipfile.ZipFile(hap, "w") as archive:
                archive.writestr("module.json", "{}")

            artifact, reasons = harmony_readiness.inspect_hap(
                directory,
                hap,
                None,
                CERT_HASH,
                "dev.vibescreen.harmony",
                "0.1.0",
            )

        self.assertTrue(artifact.hap_zip_readable)
        self.assertIn("HAP archive has no recognizable signature marker; verify signing output manually", reasons)
        self.assertIn("SHA256SUMS manifest not found beside the HAP; pass --sha256sums", reasons)

    def test_cli_returns_blocked_exit_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "readiness.json"
            with mock.patch.object(
                harmony_readiness,
                "repository_state",
                return_value={"revision": COMMIT, "dirty": False, "status_porcelain": []},
            ):
                exit_code = harmony_readiness.main(["--output", str(output), "--repo", directory_name])

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, harmony_readiness.BLOCKED_EXIT)
        self.assertEqual(report["kind"], "harmony_readiness_preflight")
        self.assertEqual(report["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
