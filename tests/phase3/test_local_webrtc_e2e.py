from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import (
    BUILD_MANIFEST_SCHEMA,
    E2EFailure,
    PRODUCT_PLAINTEXT_SEEDS,
)
from scripts.phase3_webrtc.privacy import assert_secret_free, write_evidence, write_private_text
from scripts.phase3_webrtc.processes import reserve_tcp_udp_port, run_checked
from scripts.phase3_webrtc.run_local_e2e import (
    print_success_summary,
    safe_failure_message,
    write_verified_evidence,
)
from scripts.phase3_webrtc.session import (
    supported_coturn_version,
    turnserver_command,
    validate_peer_output,
    write_turnserver_config,
)
from scripts.phase3_webrtc.source_artifacts import (
    build_binaries,
    build_manifest_path,
    create_build_manifest,
    locate_binaries,
    open_verified_binaries,
    open_verified_external_executable,
    repository_revision,
    repository_source_state,
    write_build_manifest,
)


def create_test_webrtc_framework(mac_host: Path, payload: bytes = b"verified") -> Path:
    framework = mac_host.parent / "WebRTC.framework"
    resources = framework / "Versions/A/Resources"
    resources.mkdir(parents=True)
    (framework / "Versions/A/WebRTC").write_bytes(b"\xca\xfe\xba\xbe" + payload)
    (resources / "Info.plist").write_bytes(b"plist")
    (resources / "PrivacyInfo.xcprivacy").write_bytes(b"privacy")
    (framework / "Versions/Current").symlink_to("A")
    (framework / "WebRTC").symlink_to("Versions/Current/WebRTC")
    (framework / "Resources").symlink_to("Versions/Current/Resources")
    return framework


class LocalWebRTCE2ETests(unittest.TestCase):
    def _assert_replace_restore_executes_verified_snapshot(self, mode: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            (repo / ".gitignore").write_text(
                "scripts/phase3_webrtc/.build/\nbaseline/MacHost/.build/\n.build/\n",
                encoding="utf-8",
            )
            (repo / "source.txt").write_text("source\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            signaling = repo / "scripts/phase3_webrtc/.build/signaling/vibe-signaling"
            mac_host = repo / "baseline/MacHost/.build/release/Telemachus"
            verified_bytes = b"#!/bin/sh\nprintf 'verified:%s\\n' \"$1\"\n"
            malicious_bytes = b"#!/bin/sh\nprintf 'malicious:%s\\n' \"$1\"\n"
            for binary in (signaling, mac_host):
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(verified_bytes)
                binary.chmod(0o700)
            framework = create_test_webrtc_framework(mac_host)
            write_build_manifest(
                repo,
                create_build_manifest(repo, signaling, mac_host, repository_source_state(repo)),
            )

            private_directories: list[Path] = []
            with mock.patch(
                "scripts.phase3_webrtc.source_artifacts._descriptor_execution_path",
                return_value=None,
            ), open_verified_binaries(repo) as snapshots:
                for snapshot in snapshots[:2]:
                    if snapshot.private_directory is not None:
                        private_directories.append(snapshot.private_directory)
                    original = snapshot.source_path.with_name(snapshot.source_path.name + ".original")
                    snapshot.source_path.replace(original)
                    snapshot.source_path.write_bytes(malicious_bytes)
                    snapshot.source_path.chmod(0o700)
                    try:
                        snapshot.validate_execution_target()
                        completed = subprocess.run(
                            [str(snapshot.execution_path), mode],
                            cwd=snapshot.cwd,
                            pass_fds=snapshot.pass_fds,
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                        )
                    finally:
                        snapshot.source_path.unlink()
                        original.replace(snapshot.source_path)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(completed.stdout, f"verified:{mode}\n")
                    self.assertEqual(snapshot.sha256, hashlib.sha256(verified_bytes).hexdigest())
                    self.assertEqual(snapshot.source_path.read_bytes(), verified_bytes)
                mac_snapshot = snapshots[1]
                self.assertEqual(
                    mac_snapshot.environment_overrides,
                    {"DYLD_FRAMEWORK_PATH": str(mac_snapshot.private_directory)},
                )
                original_framework = framework.with_name("WebRTC.framework.original")
                framework.replace(original_framework)
                create_test_webrtc_framework(mac_host, b"malicious")
                try:
                    mac_snapshot.validate_execution_target()
                    self.assertNotEqual(
                        (framework / "Versions/A/WebRTC").read_bytes(),
                        (
                            mac_snapshot.private_directory
                            / "WebRTC.framework/Versions/A/WebRTC"
                        ).read_bytes(),
                    )
                finally:
                    shutil.rmtree(framework)
                    original_framework.replace(framework)
                self.assertEqual(
                    (framework / "Versions/A/WebRTC").read_bytes(),
                    b"\xca\xfe\xba\xbeverified",
                )
            self.assertTrue(all(not path.exists() for path in private_directories))

    def test_direct_replace_restore_executes_verified_snapshot(self) -> None:
        self._assert_replace_restore_executes_verified_snapshot("direct")

    def test_relay_replace_restore_executes_verified_snapshot(self) -> None:
        self._assert_replace_restore_executes_verified_snapshot("relay")

    def test_turnserver_replace_restore_executes_verified_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            turnserver = root / "turnserver"
            verified = b"#!/bin/sh\nif [ \"$1\" = --version ]; then echo 4.16.0; else echo verified; fi\n"
            malicious = b"#!/bin/sh\nif [ \"$1\" = --version ]; then echo 4.16.0; else echo malicious; fi\n"
            turnserver.write_bytes(verified)
            turnserver.chmod(0o700)
            snapshot_directory: Path | None = None
            with mock.patch(
                "scripts.phase3_webrtc.source_artifacts._descriptor_execution_path",
                return_value=None,
            ), open_verified_external_executable(turnserver, "coturn binary") as snapshot:
                snapshot_directory = snapshot.private_directory
                original = root / "turnserver.original"
                turnserver.replace(original)
                turnserver.write_bytes(malicious)
                turnserver.chmod(0o700)
                try:
                    self.assertEqual(supported_coturn_version(snapshot, root), "4.16.0")
                    snapshot.validate_execution_target()
                    completed = subprocess.run(
                        turnserver_command(snapshot, root / "turnserver.conf"),
                        cwd=root,
                        pass_fds=snapshot.pass_fds,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                finally:
                    turnserver.unlink()
                    original.replace(turnserver)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, "verified\n")
                self.assertEqual(snapshot.sha256, hashlib.sha256(verified).hexdigest())
                self.assertEqual(turnserver.read_bytes(), verified)
            self.assertIsNotNone(snapshot_directory)
            self.assertFalse(snapshot_directory.exists())

    def test_coturn_port_reservation_checks_tcp_and_udp_then_releases(self) -> None:
        port = reserve_tcp_udp_port()
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_listener,
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_listener,
        ):
            tcp_listener.bind(("127.0.0.1", port))
            udp_listener.bind(("127.0.0.1", port))

    @mock.patch("scripts.phase3_webrtc.processes.subprocess.run")
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

    @mock.patch("scripts.phase3_webrtc.processes.subprocess.run")
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
            repo = Path(temporary).resolve()
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

    def test_repository_source_state_hashes_assume_unchanged_worktree_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            source = repo / "source.txt"
            source.write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "add", "source.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            clean = repository_source_state(repo)
            subprocess.run(
                ["git", "update-index", "--assume-unchanged", "source.txt"],
                cwd=repo,
                check=True,
            )
            source.write_text("hidden change\n", encoding="utf-8")

            hidden = repository_source_state(repo)

            self.assertTrue(hidden["dirty"])
            self.assertNotEqual(clean["source_fingerprint"], hidden["source_fingerprint"])

    def test_repository_source_state_hashes_skip_worktree_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            source = repo / "source.txt"
            source.write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "add", "source.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            clean = repository_source_state(repo)
            subprocess.run(
                ["git", "update-index", "--skip-worktree", "source.txt"],
                cwd=repo,
                check=True,
            )
            source.write_text("hidden change\n", encoding="utf-8")

            hidden = repository_source_state(repo)

            self.assertTrue(hidden["dirty"])
            self.assertNotEqual(clean["source_fingerprint"], hidden["source_fingerprint"])

    def test_skip_build_requires_matching_source_and_binary_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            source = repo / "source.txt"
            source.write_text("source\n", encoding="utf-8")
            (repo / ".gitignore").write_text(
                "scripts/phase3_webrtc/.build/\nbaseline/MacHost/.build/\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "source.txt", ".gitignore"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            signaling = repo / "scripts/phase3_webrtc/.build/signaling/vibe-signaling"
            mac_host = repo / "baseline/MacHost/.build/release/Telemachus"
            signaling.parent.mkdir(parents=True)
            mac_host.parent.mkdir(parents=True)
            signaling.write_bytes(b"signaling")
            mac_host.write_bytes(b"mac")
            create_test_webrtc_framework(mac_host)
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

    @mock.patch("scripts.phase3_webrtc.source_artifacts.repository_source_state")
    @mock.patch("scripts.phase3_webrtc.source_artifacts.run_checked")
    def test_build_uses_default_release_mac_binary(
        self, run: mock.Mock, source_state: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            signaling_root = repo / "services/signaling"
            signaling_root.mkdir(parents=True)
            mac_host = repo / "baseline/MacHost/.build/release/Telemachus"
            mac_host.parent.mkdir(parents=True)
            mac_host.write_bytes(b"mac-host")
            create_test_webrtc_framework(mac_host)
            source_state.return_value = {"source_fingerprint": "source-state"}

            def create_build_outputs(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                if command[0] == "go":
                    output = Path(command[command.index("-o") + 1])
                    output.write_bytes(b"signaling")
                return subprocess.CompletedProcess(command, 0, stdout="")

            run.side_effect = create_build_outputs

            signaling, selected_mac_host, outputs = build_binaries(repo, timeout=45)

            self.assertEqual(selected_mac_host, mac_host)
            self.assertEqual(signaling.read_bytes(), b"signaling")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[1].args[0], ["swift", "build", "-c", "release"])
            self.assertEqual(outputs, ["", ""])
            self.assertEqual(locate_binaries(repo), (signaling, mac_host))

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
            with self.assertRaisesRegex(E2EFailure, "build manifest is missing"):
                locate_binaries(repo)

    @mock.patch("scripts.phase3_webrtc.source_artifacts.repository_source_state")
    def test_skip_build_rejects_manifest_artifact_outside_repository(
        self, source_state: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "repo"
            repo.mkdir()
            outside = root / "outside-binary"
            outside.write_bytes(b"outside")
            source_state.return_value = {"source_fingerprint": "source-state"}
            write_build_manifest(
                repo,
                {
                    "schema": BUILD_MANIFEST_SCHEMA,
                    "source_fingerprint": "source-state",
                    "artifacts": {
                        "signaling": {
                            "path": "../outside-binary",
                            "sha256": "ignored",
                        },
                        "mac_host": {
                            "path": "baseline/MacHost/.build/release/Telemachus",
                            "sha256": "ignored",
                        },
                    },
                    "runtime_artifacts": {
                        "direct": {"turnserver_sha256": "not_used"},
                        "relay": {"turnserver_sha256": "not_recorded"},
                    },
                },
            )

            with self.assertRaisesRegex(E2EFailure, "must be inside the repository"):
                locate_binaries(repo)

    def test_turnserver_credentials_are_stored_in_private_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "turnserver.conf"
            pidfile = Path(temporary) / "turnserver.pid"
            runtime_log = Path(temporary) / "turnserver.log"
            write_turnserver_config(
                config,
                turn_port=3478,
                username="user",
                password="secret",
                realm="phase3.local",
                pidfile=pidfile,
                runtime_log=runtime_log,
            )
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            configuration = config.read_text(encoding="utf-8")
            self.assertIn("user=user:secret", configuration)
            self.assertIn(f"pidfile={pidfile}", configuration)
            self.assertIn(f"log-file={runtime_log}", configuration)
            self.assertIn("no-stdout-log", configuration)
            self.assertIn("simple-log", configuration)
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

            def record_mode_and_replace(
                source: object, destination: object, **kwargs: object
            ) -> None:
                source_dir_fd = kwargs.get("src_dir_fd")
                self.assertIsInstance(source_dir_fd, int)
                temporary_modes.append(
                    os.stat(str(source), dir_fd=source_dir_fd).st_mode & 0o777
                )
                real_replace(source, destination, **kwargs)

            with (
                mock.patch(
                    "scripts.phase3_webrtc.privacy.os.replace",
                    side_effect=record_mode_and_replace,
                ),
                mock.patch("builtins.print"),
            ):
                write_evidence(evidence, {"result": "pass"})
            self.assertEqual(temporary_modes, [0o600])
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(evidence.parent.glob(f".{evidence.name}.*.tmp")), [])

    def test_atomic_writer_binds_parent_directory_across_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configured_parent = root / ".build/owned"
            configured_parent.mkdir(parents=True)
            moved_parent = root / ".build/moved"
            outside = root / "outside"
            outside.mkdir()
            destination = configured_parent / "evidence.json"
            real_replace = os.replace
            swapped = False

            def swap_then_replace(source: object, target: object, **kwargs: object) -> None:
                nonlocal swapped
                if not swapped:
                    configured_parent.rename(moved_parent)
                    configured_parent.symlink_to(outside, target_is_directory=True)
                    swapped = True
                real_replace(source, target, **kwargs)

            with mock.patch(
                "scripts.phase3_webrtc.privacy.os.replace",
                side_effect=swap_then_replace,
            ):
                write_private_text(destination, "private\n")

            self.assertEqual((moved_parent / "evidence.json").read_text(), "private\n")
            self.assertFalse((outside / "evidence.json").exists())

    def test_failed_command_writes_only_redacted_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = Path(temporary) / "peer.log"
            secret = "generated-runtime-secret"
            with self.assertRaises(E2EFailure) as raised:
                run_checked(
                    [
                        sys.executable,
                        "-c",
                        f"import sys; print('{secret}'); raise SystemExit(7)",
                    ],
                    cwd=ROOT,
                    timeout=5,
                    redact_values=(secret,),
                    diagnostic_path=diagnostic,
                )

            self.assertNotIn(secret, str(raised.exception))
            self.assertEqual(diagnostic.read_text(encoding="utf-8"), "<redacted>\n")
            self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)

    @mock.patch("scripts.phase3_webrtc.processes.subprocess.run")
    def test_timed_out_command_writes_redacted_partial_diagnostics(
        self, run: mock.Mock
    ) -> None:
        secret = "timeout-runtime-secret"
        run.side_effect = subprocess.TimeoutExpired(
            ["peer"], timeout=5, output=f"waiting for {secret}\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = Path(temporary) / "peer.log"
            with self.assertRaisesRegex(E2EFailure, "timed out after 5s") as raised:
                run_checked(
                    ["peer"],
                    cwd=ROOT,
                    timeout=5,
                    redact_values=(secret,),
                    diagnostic_path=diagnostic,
                )

            self.assertNotIn(secret, str(raised.exception))
            self.assertEqual(
                diagnostic.read_text(encoding="utf-8"),
                "waiting for <redacted>\n",
            )

    def test_verified_evidence_is_removed_if_source_changes_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.json"
            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.assert_evidence_matches_current_build",
                    side_effect=(None, E2EFailure("source fingerprint changed")),
                ),
                self.assertRaisesRegex(E2EFailure, "source fingerprint changed"),
            ):
                write_verified_evidence(
                    ROOT,
                    evidence_path,
                    {"result": "pass"},
                )
            self.assertFalse(evidence_path.exists())

    def test_verified_evidence_removes_stale_file_on_prevalidation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.json"
            evidence_path.write_text('{"result":"pass"}\n', encoding="utf-8")
            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.assert_evidence_matches_current_build",
                    side_effect=RuntimeError("prevalidation failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "prevalidation failed"),
            ):
                write_verified_evidence(ROOT, evidence_path, {"result": "pass"})
            self.assertFalse(evidence_path.exists())

    def test_verified_evidence_removes_partial_file_on_writer_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.json"

            def fail_after_write(path: Path, rendered: str) -> None:
                path.write_text(rendered, encoding="utf-8")
                raise OSError("writer failed after replace")

            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.assert_evidence_matches_current_build"
                ),
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.write_private_text",
                    side_effect=fail_after_write,
                ),
                self.assertRaisesRegex(OSError, "writer failed after replace"),
            ):
                write_verified_evidence(ROOT, evidence_path, {"result": "pass"})
            self.assertFalse(evidence_path.exists())

    def test_verified_evidence_removes_file_on_postvalidation_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.json"
            with (
                mock.patch(
                    "scripts.phase3_webrtc.run_local_e2e.assert_evidence_matches_current_build",
                    side_effect=(None, RuntimeError("postvalidation failed")),
                ),
                self.assertRaisesRegex(RuntimeError, "postvalidation failed"),
            ):
                write_verified_evidence(ROOT, evidence_path, {"result": "pass"})
            self.assertFalse(evidence_path.exists())

    def test_verified_evidence_without_output_path_prints_no_private_json(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch(
                "scripts.phase3_webrtc.run_local_e2e.assert_evidence_matches_current_build"
            ),
            redirect_stdout(stdout),
        ):
            write_verified_evidence(
                ROOT,
                None,
                {"private_path": "/Users/alice/private", "token": "secret"},
            )
        self.assertEqual(
            stdout.getvalue(),
            "Evidence record validated; no output path provided.\n",
        )

    def test_success_summary_is_fixed_and_does_not_echo_peer_output(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            print_success_summary("direct", "product")
        self.assertEqual(
            stdout.getvalue(),
            "Phase 3 local synthetic E2E: PASS (mode=direct, slice=product)\n",
        )

    def test_failure_summary_projects_serial_endpoint_address_and_path(self) -> None:
        message = safe_failure_message(
            E2EFailure(
                "serial=ABC123 endpoint=https://private.example/internal "
                "address=10.0.0.8 peer=8.8.4.4:3478 "
                "relay=[2001:4860:4860::8844]:443 "
                "backup=relay.example.test:5349 path=/Users/alice/private"
            ),
            ROOT,
        )
        for private_value in (
            "ABC123",
            "private.example",
            "10.0.0.8",
            "8.8.4.4",
            "2001:4860:4860::8844",
            "relay.example.test",
            "/Users/alice",
        ):
            self.assertNotIn(private_value, message)

    def test_product_output_requires_complete_protocol_evidence(self) -> None:
        output = (
            "Phase 3 product signaling self-test: PASS "
            "(productSession=true, protocolV1=true, route=relay, epoch=1, "
            "configEpoch=2, rotation=90, keyframe=true, delta=true, input=true, applicationE2EE=true, "
            "selectedCandidatePair=relay(local=relay,remote=relay,protocol=udp), "
            "controlChannel=ordered-reliable, mediaChannel=unordered-zero-retransmit)"
        )

        self.assertEqual(
            validate_peer_output(output, mode="relay", slice_name="product"),
            "relay(local=relay,remote=relay,protocol=udp)",
        )

        with self.assertRaisesRegex(E2EFailure, "malformed or untrusted"):
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
            "selectedCandidatePair=direct(local=host,remote=host,protocol=udp), "
            "controlChannel=ordered-reliable, mediaChannel=unordered-zero-retransmit)"
        )
        with self.assertRaisesRegex(E2EFailure, "relay candidate types|relay route"):
            validate_peer_output(output, mode="relay", slice_name="product")

    def test_product_output_rejects_unsupported_candidate_protocol(self) -> None:
        output = (
            "Phase 3 product signaling self-test: PASS "
            "(productSession=true, protocolV1=true, route=direct, epoch=1, "
            "configEpoch=2, rotation=90, keyframe=true, delta=true, input=true, "
            "applicationE2EE=true, "
            "selectedCandidatePair=direct(local=host,remote=host,"
            "protocol=udp-private-token), controlChannel=ordered-reliable, "
            "mediaChannel=unordered-zero-retransmit)"
        )
        with self.assertRaisesRegex(E2EFailure, "unsupported candidate protocol"):
            validate_peer_output(output, mode="direct", slice_name="product")

    def test_seeded_plaintext_scan_fails_closed(self) -> None:
        with self.assertRaisesRegex(E2EFailure, "leaked 1"):
            assert_secret_free(
                f"prefix {PRODUCT_PLAINTEXT_SEEDS[0]} suffix",
                list(PRODUCT_PLAINTEXT_SEEDS),
                "peer output",
            )


if __name__ == "__main__":
    unittest.main()
