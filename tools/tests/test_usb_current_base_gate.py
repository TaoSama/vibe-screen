import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibescreen_evidence import SCHEMA_VERSION
from vibescreen_evidence.usb_current_base_gate import (
    EXPECTED_DEVICE,
    MANIFEST_KIND,
    evaluate,
    write_json,
)

MODULE = "vibescreen_evidence.usb_current_base_gate"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "usb-current-base-gate.schema.json"
CURRENT_MAIN_SHA = "075dc157c36ba71df9f757e571015905881a7154"


def write_artifact(path: Path, content: str = "placeholder\n") -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    import hashlib
    return {"kind": "placeholder", "path": str(path), "sha256": hashlib.sha256(content.encode()).hexdigest(), "description": "test artifact"}


def live_artifact(path: Path, verdict: str = "insufficient", claims_live: bool = False) -> dict[str, object]:
    content = {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_live_smoke",
        "verdict": verdict,
        "claims": {"live_usb_stream_observed": claims_live},
    }
    return write_artifact(path, json.dumps(content) + "\n")


class UsbCurrentBaseGateTest(unittest.TestCase):
    def complete_manifest(self, root: Path) -> dict[str, object]:
        artifact = write_artifact(root / "usb-preflight.json")
        artifact["kind"] = "usb_smoke_preflight"
        repo_artifact = write_artifact(root / "git.txt")
        repo_artifact["kind"] = "repository_snapshot"
        host_artifact = write_artifact(root / "host-readiness.json")
        host_artifact["kind"] = "host_readiness"
        dev_artifact = write_artifact(root / "device.json")
        dev_artifact["kind"] = "device_identity"
        live = live_artifact(root / "usb-live-smoke.json")
        live["kind"] = "usb_live_smoke"
        live["description"] = "read-only USB live-smoke result"
        (root / "git-origin-main.txt").write_text(CURRENT_MAIN_SHA + "\n", encoding="utf-8")
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": MANIFEST_KIND,
            "run_id": "run-1",
            "created_at": "2026-08-31T00:00:00Z",
            "repository": {
                "branch": "codex/usb-current-base-owner-20260831b",
                "current_main_sha": CURRENT_MAIN_SHA,
                "dirty": False,
                "notes": ["clean current-base evidence bundle"],
            },
            "device": EXPECTED_DEVICE,
            "state": {
                "usb_preflight": {"observed": False},
                "usb_live_smoke": {"observed": False},
                "host_readiness": {"observed": False},
                "blockers": ["Host readiness is blocked before USB preflight can pass"],
            },
            "artifacts": [repo_artifact, artifact, live, host_artifact, dev_artifact],
            "can_close_readme_android_usb_current_base_gate": False,
            "notes": ["fail-closed current-base owner record"],
        }

    def test_blocked_fail_closed_record_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = evaluate(self.complete_manifest(root), repository_root=root)

        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["can_close_readme_android_usb_current_base_gate"])
        self.assertEqual(report["errors"], [])

    def test_missing_artifact_blocks_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = manifest["artifacts"][:-1]
            report = evaluate(manifest, repository_root=root)

        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("artifacts: missing required kind device_identity", report["errors"])

    def test_public_artifact_rejects_raw_serial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            bad = write_artifact(root / "bad.txt", "serial EP012345678901234567\n")
            manifest["artifacts"].append({"kind": "privacy_scan", "path": bad["path"], "sha256": bad["sha256"], "description": "bad artifact"})
            report = evaluate(manifest, repository_root=root)

        self.assertTrue(any("public artifact contains raw ADB serial" in error for error in report["errors"]))

    def test_public_artifact_allows_permission_hint_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            good = write_artifact(
                root / "good.txt",
                "Telemachus_pendingPostUpdatePermissionHintFingerprint\n",
            )
            manifest["artifacts"].append(
                {
                    "kind": "privacy_scan",
                    "path": good["path"],
                    "sha256": good["sha256"],
                    "description": "Host readiness key name that is not an ADB serial",
                }
            )
            report = evaluate(manifest, repository_root=root)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["verdict"], "blocked")

    def test_summary_schema_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = evaluate(self.complete_manifest(root), repository_root=root)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(report), set(schema["properties"]))
        for field in schema["required"]:
            self.assertIn(field, report)

    def test_pass_state_without_live_smoke_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = [
                artifact for artifact in manifest["artifacts"] if artifact["kind"] != "usb_live_smoke"
            ]
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_close_readme_android_usb_current_base_gate"])
        self.assertIn("artifacts: missing required kind usb_live_smoke", report["errors"])
        self.assertFalse(report["can_claim_current_base_usb_pass"])

    def test_pass_state_with_blocked_live_smoke_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = [
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] != "usb_live_smoke"
            ]
            blocked = live_artifact(root / "usb-live-smoke.json", verdict="blocked")
            blocked["kind"] = "usb_live_smoke"
            manifest["artifacts"].append(blocked)
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "usb_live_smoke.claims.live_usb_stream_observed" in error
                for error in report["errors"]
            )
        )

    def test_pass_state_with_blocked_live_smoke_and_true_claim_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = [
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] != "usb_live_smoke"
            ]
            blocked = live_artifact(
                root / "usb-live-smoke.json",
                verdict="blocked",
                claims_live=True,
            )
            blocked["kind"] = "usb_live_smoke"
            manifest["artifacts"].append(blocked)
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "usb_live_smoke.verdict" in error and "must be pass" in error
                for error in report["errors"]
            )
        )

    def test_pass_state_with_insufficient_live_smoke_and_true_claim_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = [
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] != "usb_live_smoke"
            ]
            blocked = live_artifact(
                root / "usb-live-smoke.json",
                verdict="insufficient",
                claims_live=True,
            )
            blocked["kind"] = "usb_live_smoke"
            manifest["artifacts"].append(blocked)
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "usb_live_smoke.verdict" in error and "must be pass" in error
                for error in report["errors"]
            )
        )

    def test_pass_state_with_insufficient_live_smoke_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest["artifacts"] = [
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] != "usb_live_smoke"
            ]
            live = live_artifact(
                root / "usb-live-smoke.json",
                verdict="insufficient",
                claims_live=False,
            )
            live["kind"] = "usb_live_smoke"
            manifest["artifacts"].append(live)
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "usb_live_smoke.claims.live_usb_stream_observed" in error
                for error in report["errors"]
            )
        )

    def test_stale_current_main_sha_fails_closed_even_with_pass_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            (root / "git-origin-main.txt").write_text("0" * 40 + "\n", encoding="utf-8")
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "retained repository snapshot does not match manifest current_main_sha"
                in error
                for error in report["errors"]
            )
        )

    def test_missing_current_main_sha_in_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            (root / "git-origin-main.txt").write_text("missing\n", encoding="utf-8")
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "retained snapshot does not record the current main SHA" in error
                for error in report["errors"]
            )
        )

    def test_pass_state_with_stale_host_readiness_provenance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            host_path = root / "host-readiness.json"
            host_path.write_text(
                json.dumps(
                    {
                        "host": {
                            "current_source_commit": "0" * 40,
                            "current_source_dirty": False,
                        }
                    }
                ),
                encoding="utf-8",
            )
            host_artifact = next(
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] == "host_readiness"
            )
            host_artifact["sha256"] = __import__("hashlib").sha256(host_path.read_bytes()).hexdigest()
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "host_readiness.host.current_source_commit" in error
                for error in report["errors"]
            )
        )

    def test_pass_state_with_stale_command_ledger_provenance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            command = root / "usb-smoke-preflight.command.txt"
            command.write_text(
                "Base: origin/main 0000000000000000000000000000000000000000\n",
                encoding="utf-8",
            )
            manifest["state"]["usb_preflight"]["observed"] = True
            manifest["state"]["usb_live_smoke"]["observed"] = True
            manifest["state"]["host_readiness"]["observed"] = True
            manifest["state"]["blockers"] = []
            report = evaluate(manifest, repository_root=root)

        self.assertNotEqual(report["verdict"], "pass")
        self.assertFalse(report["can_claim_current_base_usb_pass"])
        self.assertTrue(
            any(
                "usb_smoke_preflight.command: retained command ledger Base" in error
                for error in report["errors"]
            )
        )

    def test_cli_allow_blocked_returns_zero_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.complete_manifest(root)
            manifest_path = root / "usb-current-base.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "usb-current-base-gate.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    MODULE,
                    "--manifest",
                    str(manifest_path),
                    "--repository-root",
                    str(root),
                    "--output",
                    str(output),
                    "--allow-blocked",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
