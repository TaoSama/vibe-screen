from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.run_local_e2e import (
    E2EFailure,
    PRODUCT_PLAINTEXT_SEEDS,
    assert_secret_free,
    build_manifest_path,
    create_build_manifest,
    locate_binaries,
    repository_revision,
    repository_source_state,
    turnserver_command,
    validate_peer_output,
    write_build_manifest,
    write_evidence,
    write_turnserver_config,
)


class LocalWebRTCE2ETests(unittest.TestCase):
    @mock.patch("scripts.phase3_webrtc.run_local_e2e.subprocess.run")
    def test_repository_revision_reads_head_from_requested_root(
        self, run: mock.Mock
    ) -> None:
        revision = "A" * 40
        run.return_value = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"], 0, stdout=f"{revision}\n"
        )

        self.assertEqual(repository_revision(ROOT), revision.lower())
        run.assert_called_once_with(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )

    @mock.patch("scripts.phase3_webrtc.run_local_e2e.subprocess.run")
    def test_repository_revision_rejects_non_revision_output(
        self, run: mock.Mock
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"], 0, stdout="HEAD\n"
        )

        with self.assertRaisesRegex(E2EFailure, "invalid HEAD revision"):
            repository_revision(ROOT)

    def test_repository_source_state_records_tracked_and_untracked_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)

            clean = repository_source_state(repo)
            self.assertFalse(clean["dirty"])
            self.assertEqual(clean["evidence_qualification"], "commit evidence")

            tracked.write_text("changed\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("new\n", encoding="utf-8")
            dirty = repository_source_state(repo)
            self.assertTrue(dirty["dirty"])
            self.assertEqual(
                dirty["evidence_qualification"],
                "non-commit evidence (dirty worktree)",
            )
            self.assertNotEqual(clean["tracked_diff_sha256"], dirty["tracked_diff_sha256"])
            self.assertEqual(
                [entry["path"] for entry in dirty["untracked_manifest"]],
                ["untracked.txt"],
            )
            self.assertNotEqual(clean["source_fingerprint"], dirty["source_fingerprint"])

    def test_skip_build_requires_matching_source_and_binary_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            source = repo / "source.txt"
            source.write_text("source\n", encoding="utf-8")
            subprocess.run(["git", "add", "source.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            signaling = repo / "scripts/phase3_webrtc/.build/signaling/vibe-signaling"
            mac_host = repo / "scripts/phase3_webrtc/.build/swift/release/Telemachus"
            signaling.parent.mkdir(parents=True)
            mac_host.parent.mkdir(parents=True)
            signaling.write_bytes(b"signaling")
            mac_host.write_bytes(b"mac")
            manifest = create_build_manifest(
                repo, signaling, mac_host, repository_source_state(repo)
            )
            write_build_manifest(repo, manifest)

            self.assertEqual(locate_binaries(repo), (signaling, mac_host))

            source.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(E2EFailure, "source fingerprint"):
                locate_binaries(repo)
            source.write_text("source\n", encoding="utf-8")
            signaling.write_bytes(b"tampered")
            with self.assertRaisesRegex(E2EFailure, "binary hash"):
                locate_binaries(repo)

    def test_skip_build_fails_closed_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for binary in (
                repo / "scripts/phase3_webrtc/.build/signaling/vibe-signaling",
                repo / "scripts/phase3_webrtc/.build/swift/release/Telemachus",
            ):
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b"binary")
            self.assertFalse(build_manifest_path(repo).exists())
            with self.assertRaisesRegex(E2EFailure, "requires a build manifest"):
                locate_binaries(repo)

    def test_turnserver_credentials_are_stored_in_private_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "turnserver.conf"
            write_turnserver_config(
                config,
                turn_port=3478,
                username="user",
                password="secret",
                realm="phase3.local",
            )
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertIn("user=user:secret", config.read_text(encoding="utf-8"))
            command = turnserver_command(Path("/usr/local/bin/turnserver"), config)
            self.assertEqual(
                command,
                ["/usr/local/bin/turnserver", "-c", str(config)],
            )
            self.assertNotIn("user", " ".join(command))
            self.assertNotIn("secret", " ".join(command))

    def test_evidence_file_is_written_atomically_with_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence.json"
            temporary_modes = []
            real_replace = os.replace

            def record_mode_and_replace(source: Path, destination: Path) -> None:
                temporary_modes.append(Path(source).stat().st_mode & 0o777)
                real_replace(source, destination)

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.os.replace",
                    side_effect=record_mode_and_replace,
                ),
                mock.patch("builtins.print"),
            ):
                write_evidence(evidence, {"result": "pass"})
            self.assertEqual(temporary_modes, [0o600])
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(evidence.parent.glob(f".{evidence.name}.*.tmp")), [])

    def test_product_output_requires_complete_protocol_evidence(self) -> None:
        output = (
            "Phase 3 product signaling self-test: PASS "
            "(productSession=true, protocolV1=true, route=relay, epoch=1, "
            "configEpoch=2, rotation=90, keyframe=true, delta=true, input=true, applicationE2EE=true, "
            "selectedCandidatePair=relay(local=relay,remote=relay,protocol=udp))"
        )

        self.assertEqual(
            validate_peer_output(output, mode="relay", slice_name="product"),
            "relay(local=relay,remote=relay,protocol=udp)",
        )

        with self.assertRaisesRegex(E2EFailure, "omitted evidence markers"):
            validate_peer_output(
                output.replace("delta=true, ", ""),
                mode="relay",
                slice_name="product",
            )

    def test_product_output_rejects_route_mismatch(self) -> None:
        output = (
            "Phase 3 product signaling self-test: PASS "
            "(productSession=true, protocolV1=true, route=direct, epoch=1, "
            "configEpoch=2, rotation=90, keyframe=true, delta=true, input=true, applicationE2EE=true, "
            "selectedCandidatePair=direct(local=host,remote=host,protocol=udp))"
        )
        with self.assertRaisesRegex(E2EFailure, "relay route"):
            validate_peer_output(output, mode="relay", slice_name="product")

    def test_seeded_plaintext_scan_fails_closed(self) -> None:
        with self.assertRaisesRegex(E2EFailure, "leaked 1"):
            assert_secret_free(
                f"prefix {PRODUCT_PLAINTEXT_SEEDS[0]} suffix",
                list(PRODUCT_PLAINTEXT_SEEDS),
                "peer output",
            )


if __name__ == "__main__":
    unittest.main()
