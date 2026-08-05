from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3.android_product_session_interop_acceptance import (
    DEVICE_MARKER_PREFIX,
    HOST_MARKER_PREFIX,
    INTERNET_LEASE_LOCK,
    MANDATORY_DEVICE_LOCKS,
    Adb,
    InteropError,
    LEASE_TASK,
    build_parser,
    capture_lease,
    controlled_build,
    derive_test_material,
    redact,
    read_private_ice_configuration,
    read_private_external,
    require_artifacts_unchanged,
    require_lease,
    signaling_config,
    validate_instrumentation_result,
    validate_marker,
    write_private,
)


class AndroidProductSessionInteropAcceptanceTests(unittest.TestCase):
    def test_cli_requires_explicit_route_endpoint_bind_turn_and_artifacts(self) -> None:
        required = {
            action.dest
            for action in build_parser()._actions
            if getattr(action, "required", False)
        }
        self.assertTrue({
            "route", "repo", "adb_endpoint", "signaling_bind_address", "ice_config_file",
            "coturn_log", "coturn_version_file", "raw_output_dir", "evidence",
        }.issubset(required))

    def _lease_bytes(self, commit: str = "a" * 40, *, pid: int = 424242) -> bytes:
        return json.dumps({
            "owner": "acceptance-owner",
            "pid": pid,
            "task": LEASE_TASK,
            "commit": commit,
        }, separators=(",", ":")).encode()

    def test_structured_lease_requires_exact_task_commit_independent_live_holder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = root / "internet.lock"
            other = root / "other.lock"
            write_private(lease, self._lease_bytes())
            with mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.INTERNET_LEASE_LOCK", lease
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.MANDATORY_DEVICE_LOCKS", ()
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.DEVICE_LOCK_GLOB", "no-test-locks-*"
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance._pid_is_alive", return_value=True
            ):
                snapshot = capture_lease("a" * 40)
                require_lease(snapshot, "a" * 40)
                lease.write_bytes(self._lease_bytes("b" * 40))
                with self.assertRaisesRegex(InteropError, "bytes changed"):
                    require_lease(snapshot, "a" * 40)
                write_private(lease, self._lease_bytes("a" * 40))
                with self.assertRaisesRegex(InteropError, "inode changed"):
                    require_lease(snapshot, "a" * 40)
                other.write_text("busy", encoding="utf-8")
                with self.assertRaisesRegex(InteropError, "mandatory device lock"):
                    capture_lease("a" * 40, [other])
            self.assertEqual(MANDATORY_DEVICE_LOCKS[0], Path("/tmp/vibe-screen-device-soak.lock"))
            self.assertEqual(INTERNET_LEASE_LOCK, Path("/tmp/vibe-screen-device-internet.lock"))

    def test_lease_rejects_dead_same_process_and_wrong_task_or_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / "internet.lock"
            patches = (
                mock.patch(
                    "scripts.phase3.android_product_session_interop_acceptance.INTERNET_LEASE_LOCK", lease
                ),
                mock.patch(
                    "scripts.phase3.android_product_session_interop_acceptance.MANDATORY_DEVICE_LOCKS", ()
                ),
                mock.patch(
                    "scripts.phase3.android_product_session_interop_acceptance.DEVICE_LOCK_GLOB",
                    "no-test-locks-*",
                ),
            )
            write_private(lease, self._lease_bytes(pid=os.getpid()))
            with patches[0], patches[1], patches[2]:
                with self.assertRaisesRegex(InteropError, "not independent"):
                    capture_lease("a" * 40)
            write_private(lease, self._lease_bytes())
            with mock.patch("scripts.phase3.android_product_session_interop_acceptance.INTERNET_LEASE_LOCK", lease), \
                 mock.patch("scripts.phase3.android_product_session_interop_acceptance.MANDATORY_DEVICE_LOCKS", ()), \
                 mock.patch("scripts.phase3.android_product_session_interop_acceptance.DEVICE_LOCK_GLOB", "no-test-locks-*"), \
                 mock.patch("scripts.phase3.android_product_session_interop_acceptance._pid_is_alive", return_value=False):
                with self.assertRaisesRegex(InteropError, "not alive"):
                    capture_lease("a" * 40)
                with self.assertRaisesRegex(InteropError, "task or commit"):
                    capture_lease("b" * 40)

    def test_adb_rechecks_lease_before_every_subprocess_and_records_only_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / "internet.lock"
            write_private(lease, self._lease_bytes())
            records = []
            completed = subprocess.CompletedProcess([], 0, stdout=b"private output", stderr=b"")
            with mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.INTERNET_LEASE_LOCK", lease
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.MANDATORY_DEVICE_LOCKS", ()
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.DEVICE_LOCK_GLOB", "no-test-locks-*"
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance._pid_is_alive", return_value=True
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.subprocess.run",
                return_value=completed,
            ) as run_process:
                snapshot = capture_lease("a" * 40)
                adb = Adb("adb", "private-endpoint", snapshot, "a" * 40, [], records)
                self.assertEqual(adb.device(["get-state"], name="state"), "private output")
                lease.unlink()
                with self.assertRaisesRegex(InteropError, "unavailable"):
                    adb.device(["get-state"], name="state-2")
            run_process.assert_called_once()
            self.assertEqual(records[0].name, "state")
            self.assertFalse(hasattr(records[0], "stdout"))
            self.assertNotIn("private-endpoint", json.dumps(records[0].__dict__))
            self.assertNotIn("private output", json.dumps(records[0].__dict__))

    def test_adb_rechecks_lease_after_subprocess_before_accepting_or_recording_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / "internet.lock"
            write_private(lease, self._lease_bytes())
            records = []
            with mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.INTERNET_LEASE_LOCK", lease
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.MANDATORY_DEVICE_LOCKS", ()
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.DEVICE_LOCK_GLOB", "no-test-locks-*"
            ), mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance._pid_is_alive", return_value=True
            ):
                snapshot = capture_lease("a" * 40)
                adb = Adb("adb", "private-endpoint", snapshot, "a" * 40, [], records)

                def delete_lease(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
                    lease.unlink()
                    return subprocess.CompletedProcess([], 0, stdout=b"device", stderr=b"")

                with mock.patch(
                    "scripts.phase3.android_product_session_interop_acceptance.subprocess.run",
                    side_effect=delete_lease,
                ):
                    with self.assertRaisesRegex(InteropError, "unavailable"):
                        adb.device(["get-state"], name="state")
            self.assertEqual(records, [])

    def test_controlled_build_uses_fixed_commands_and_rechecks_clean_source(self) -> None:
        source = {"commit": "a" * 40, "tree": "b" * 40, "origin_main_commit": "c" * 40}
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def build(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                if "assembleDebugAndroidTest" in command:
                    outputs = [
                        repo / "baseline/AndroidClient/app/build/outputs/apk/debug/app-debug.apk",
                        repo / "baseline/AndroidClient/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk",
                    ]
                elif command[:3] == ["swift", "build", "-c"]:
                    outputs = [repo / "baseline/MacHost/.build/release/Telemachus"]
                else:
                    outputs = [repo / "services/signaling/build/vibe-signaling"]
                for output in outputs:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(output.name.encode())
                return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

            with mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.repository_state",
                side_effect=(source, source),
            ) as state, mock.patch(
                "scripts.phase3.android_product_session_interop_acceptance.subprocess.run",
                side_effect=build,
            ) as process:
                paths, artifacts, records = controlled_build(repo, source, 30)
            self.assertEqual(state.call_count, 2)
            self.assertEqual(len(process.call_args_list), 3)
            self.assertIn("assembleDebugAndroidTest", process.call_args_list[0].args[0])
            self.assertEqual(process.call_args_list[1].args[0], ["swift", "build", "-c", "release"])
            self.assertIn("-trimpath", process.call_args_list[2].args[0])
            self.assertEqual(set(paths), {"app_apk", "test_apk", "mac_host", "signaling_binary"})
            self.assertEqual(len(artifacts), 4)
            self.assertEqual([record.returncode for record in records], [0, 0, 0])

    def test_controlled_artifact_replacement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "app.apk"
            artifact.write_bytes(b"original")
            paths = {"app_apk": artifact}
            artifacts = {"app_apk_sha256": hashlib.sha256(b"original").hexdigest()}
            require_artifacts_unchanged(paths, artifacts)
            artifact.write_bytes(b"replaced")
            with self.assertRaisesRegex(InteropError, "changed after"):
                require_artifacts_unchanged(paths, artifacts)

    def test_marker_validation_requires_exact_route_epoch_and_all_crypto_media_touch_flags(self) -> None:
        common = (
            "kdf_kat=true transcript_kat=true video_config=true keyframe=true "
            "delta=true touch=true application_e2ee=true"
        )
        host = f"{HOST_MARKER_PREFIX} route=relay epoch=42 {common}"
        device = f"{DEVICE_MARKER_PREFIX} route=relay epoch=42 {common} protocol_v1=true"
        self.assertEqual(validate_marker(host, HOST_MARKER_PREFIX, "relay", 42), host)
        self.assertEqual(
            validate_marker(device, DEVICE_MARKER_PREFIX, "relay", 42, ("protocol_v1=true",)),
            device,
        )
        for broken in (
            host.replace("route=relay", "route=direct"),
            host.replace("epoch=42", "epoch=41"),
            host.replace(" touch=true", ""),
            host.replace(HOST_MARKER_PREFIX, HOST_MARKER_PREFIX + "_EVIL"),
            host + " route=direct",
            host + " unknown=true",
            host + "\n" + host,
        ):
            with self.assertRaises(InteropError):
                validate_marker(broken, HOST_MARKER_PREFIX, "relay", 42)

    def test_instrumentation_requires_clean_single_test_terminal_result(self) -> None:
        validate_instrumentation_result("marker\nOK (1 test)\n")
        for output in ("OK (2 tests)\n", "FAILURES!!!\nOK (1 test)\n", "INSTRUMENTATION_FAILED"):
            with self.assertRaises(InteropError):
                validate_instrumentation_result(output)

    def test_kdf_material_is_well_formed_and_binds_epoch_and_roles(self) -> None:
        with mock.patch(
            "scripts.phase3.android_product_session_interop_acceptance.secrets.token_bytes",
            side_effect=(b"s" * 32, b"b" * 32, b"t" * 32, b"s" * 32, b"b" * 32, b"t" * 32),
        ):
            first = derive_test_material("session", 7, "host", "device")
            second = derive_test_material("session", 8, "host", "device")
        self.assertEqual(len(first["bound_hex"]), 64)
        self.assertEqual(len(first["key_id"]), 64)
        self.assertNotEqual(first["bound_hex"], second["bound_hex"])
        self.assertNotEqual(first["key_id"], second["key_id"])

    def test_signaling_configuration_uses_explicit_bind_and_bounded_real_service_limits(self) -> None:
        config = signaling_config("192.0.2.10", 18088)
        self.assertEqual(config["listen_address"], "192.0.2.10:18088")
        self.assertEqual(config["max_waiters_per_role"], 1)
        self.assertGreater(config["max_candidates_per_role"], 0)

    def test_ice_urls_and_turn_credentials_are_loaded_only_from_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ice.json"
            write_private(path, json.dumps({
                "stun_url": "stun:reachable.example:3478",
                "turn_url": "turn:reachable.example:3478?transport=udp",
                "username": "private-user",
                "credential": "private-credential",
            }).encode())
            repo = Path(directory) / "repo"
            repo.mkdir()
            ice = read_private_ice_configuration(path, repo)
            self.assertEqual(ice.turn_url, "turn:reachable.example:3478?transport=udp")
            path.chmod(0o644)
            with self.assertRaisesRegex(InteropError, "0600"):
                read_private_ice_configuration(path, repo)

    def test_private_inputs_reject_repo_paths_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            inside = repo / "secret.log"
            write_private(inside, b"secret")
            with self.assertRaisesRegex(InteropError, "outside"):
                read_private_external(inside, repo, 100, "coturn raw log")
            outside = root / "outside.log"
            write_private(outside, b"secret")
            link = root / "link.log"
            link.symlink_to(outside)
            with self.assertRaisesRegex(InteropError, "symlink"):
                read_private_external(link, repo, 100, "coturn raw log")

    def test_private_atomic_writer_is_0600_and_redactor_removes_all_registered_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.log"
            write_private(output, b"private-content")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(output.parent.glob(f".{output.name}.*")), [])
        sensitive = ["private-endpoint", "bearer-token", "turn-secret", "session-id"]
        raw = " ".join(sensitive)
        cleaned = redact(raw, sensitive)
        for value in sensitive:
            self.assertNotIn(value, cleaned)


if __name__ == "__main__":
    unittest.main()
