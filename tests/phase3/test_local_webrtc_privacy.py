from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.phase3_webrtc.model import E2EFailure, EVIDENCE_SCHEMA
from scripts.phase3_webrtc.privacy import (
    project_public_diagnostic,
    public_diagnostic_findings,
    write_private_text,
    write_public_diagnostic,
)
from scripts.phase3_webrtc.processes import assert_no_new_coturn_residue
from scripts.phase3_webrtc.public_evidence import (
    PUBLIC_PATHS,
    build_public_artifact_tree,
    validate_public_artifact_tree,
)
from scripts.phase3_webrtc.session import supported_coturn_version
from scripts.phase3_webrtc.source_artifacts import open_verified_external_executable


def private_evidence(mode: str) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "mode": mode,
        "slice": "product",
        "result": "pass",
        "evidence_qualification": "non-commit evidence (dirty worktree)",
        "signaling": {
            "real_process": True,
            "health": "pass",
            "ready": "pass",
            "authenticated_session": "pass",
            "accepted_messages": 12,
            "secret_log_scan": "pass",
        },
        "webrtc": {
            "implementation": "stasel/WebRTC 150.0.0 production adapter",
            "real_peer_connections": 2,
            "offer_answer_via_http_signaling": "pass",
            "ice_candidate_exchange": "pass",
            "application_e2ee": "AES-256-GCM Protocol v1 record layer pass",
            "data_channels": {
                "control": "ordered/reliable; bidirectional payload pass",
                "media": "unordered/maxRetransmits=0; bidirectional payload pass",
            },
            "selected_candidate_pair": (
                f"{mode}(local={'relay' if mode == 'relay' else 'host'},"
                f"remote={'relay' if mode == 'relay' else 'host'},protocol=udp)"
            ),
            "selected_route": mode,
        },
        "artifacts": {
            "signaling_sha256": "a" * 64,
            "mac_host_sha256": "b" * 64,
            "webrtc_framework_sha256": "3" * 64,
            "turnserver_sha256": "4" * 64 if mode == "relay" else "not_used",
        },
        "environment": {
            "platform": "private-hostname under /Users/alice",
            "python": "3.11",
            "go": "go version",
            "swift": "swift version",
            "repository_commit": "c" * 40,
            "repository_source": {
                "repository_commit": "c" * 40,
                "tracked_diff_sha256": "d" * 64,
                "untracked_manifest_sha256": "e" * 64,
                "dirty": True,
                "evidence_qualification": "non-commit evidence (dirty worktree)",
                "untracked_manifest": [
                    {"path": "/Users/alice/private.swift", "sha256": "f" * 64}
                ],
                "source_fingerprint": "1" * 64,
            },
        },
        "product_session": {
            "host": "InternetProductSession",
            "device": "synthetic Protocol v1 harness",
            "client_hello": "pass",
            "session_accepted_epoch": 1,
            "initial_video_config_ack_epoch": 1,
            "runtime_video_config_ack_epoch": 2,
            "runtime_rotation_degrees": 90,
            "media": "synthetic keyframe and delta pass",
            "touch_input": "pass",
            "seeded_plaintext_log_scan": "pass",
            "capture_or_stream_server_started": False,
        },
        "limitations": ["private free-form limitation"],
    }
    if mode == "relay":
        evidence["coturn"] = {
            "real_process": True,
            "version": "4.16.0",
            "forced_libwebrtc_relay": "pass",
            "executable_sha256": "4" * 64,
        }
    return evidence


class LocalWebRTCPrivacyTests(unittest.TestCase):
    def test_public_projection_redacts_paths_addresses_credentials_and_seeds(self) -> None:
        secret = "runtime-super-secret"
        raw = "\n".join(
            (
                "/Users/alice/work/file.swift /home/runner/build /private/tmp/item",
                "/var/tmp/turn_123.log /tmp /etc/hosts",
                r"C:\ D:/Users/Alice/file.txt \\server\share\folder",
                r"\\?\C:\Users\Alice\secret \\?\UNC\server\share\secret",
                "10.2.3.4 172.16.0.1 192.168.5.6 127.0.0.1 169.254.1.2",
                "8.8.8.8 ::1 fe80::abcd%en0 fc00::1234 2001:4860:4860::8888",
                "::ffff:192.0.2.128 8.8.4.4:3478 [2001:4860:4860::8844]:443",
                "relay.example.test:5349 turnserver:3478 invalid.example:999999",
                "Authorization: Bearer token-value cookie=session-value",
                'Authorization: Basic dXNlcjpwYXNz token: abc def password="two word"',
                "api_key=key-value password=hunter2 seed=seed-value",
                "serial_number=ABC123 device_id=device-private hostname=runner.internal",
                "endpoint=https://private.example/internal https://other.internal/path",
                "turn://user:pass@127.0.0.1:3478",
                "https://web-user:web-pass@secure.example.test/private",
                "turn:turn-user:turn-pass@relay.example.test:3478?transport=udp",
                "bare.private.example.test passwd=one pwd=two private_key=three",
                "VIBE-PRODUCT-E2E-KEYFRAME-PLAINTEXT-SEED",
                secret,
            )
        )

        projected = project_public_diagnostic(raw, secret_values=(secret,))

        self.assertEqual(public_diagnostic_findings(projected), [])
        self.assertEqual(project_public_diagnostic(projected), projected)
        for private_fragment in (
            "alice",
            "runner",
            "10.2.3.4",
            "8.8.8.8",
            "8.8.4.4",
            "fe80::abcd",
            "2001:4860:4860::8888",
            "2001:4860:4860::8844",
            "192.0.2.128",
            "%en0",
            "relay.example.test",
            "turnserver:3478",
            "invalid.example",
            "token-value",
            "session-value",
            "dXNlcjpwYXNz",
            "abc def",
            "two word",
            "hunter2",
            "ABC123",
            "device-private",
            "runner.internal",
            "private.example",
            "other.internal",
            "user:pass",
            "web-user",
            "turn-user",
            "bare.private.example.test",
            "passwd",
            "private_key",
            "PLAINTEXT-SEED",
            secret,
        ):
            self.assertNotIn(private_fragment, projected)

    def test_public_scan_rejects_bare_network_locations(self) -> None:
        for endpoint, expected in (
            ("8.8.8.8", "<redacted-address>"),
            ("8.8.4.4:3478", "<redacted-endpoint>"),
            ("2001:4860:4860::8888", "<redacted-address>"),
            ("::ffff:192.0.2.128", "<redacted-address>"),
            ("[2001:4860:4860::8844]:443", "<redacted-endpoint>"),
            ("relay.example.test:5349", "<redacted-endpoint>"),
            ("relay_host:5349", "<redacted-endpoint>"),
            ("turnserver:3478", "<redacted-endpoint>"),
            ("invalid.example:999999", "<redacted-endpoint>"),
        ):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(public_diagnostic_findings(endpoint))
                self.assertEqual(project_public_diagnostic(endpoint), expected)

    def test_projection_remains_closed_after_hostname_redaction(self) -> None:
        raw = (
            "dyld[123]: Library not loaded: @rpath/WebRTC.framework/Versions/A/WebRTC\n"
            "  Referenced from: <ABC> "
            "/Users/runner/work/vibe-screen/.build/release/Vibe Screen"
        )

        projected = project_public_diagnostic(raw)

        self.assertEqual(public_diagnostic_findings(projected), [])
        self.assertEqual(project_public_diagnostic(projected), projected)
        self.assertNotIn("/Versions/A/WebRTC", projected)
        self.assertNotIn("/Users/runner", projected)

    def test_traceback_projection_truncates_case_insensitively(self) -> None:
        raw = "safe prefix\ntRaCeBaCk (most recent call last):\n/private/path.py"
        projected = project_public_diagnostic(raw)
        self.assertEqual(projected, "safe prefix\n<redacted-traceback>\n")
        self.assertEqual(public_diagnostic_findings(projected), [])

    def test_public_tree_contains_only_allowlist_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            public = source / "public"
            source.mkdir(mode=0o700)
            for mode in ("direct", "relay"):
                write_private_text(
                    source / f"{mode}.json",
                    json.dumps(private_evidence(mode)),
                )
            diagnostic_inputs = (
                ("direct-logs/peer.log", "direct peer PASS /Users/alice 10.0.0.1"),
                ("direct-logs/signaling.log", "signaling PASS token=private"),
                ("relay-logs/peer.log", "relay peer PASS 192.168.1.20"),
                ("relay-logs/signaling.log", "relay signaling PASS /tmp/private"),
                ("relay-logs/turnserver.log", "turn PASS turn://user:pass@127.0.0.1"),
            )
            for relative_path, raw in diagnostic_inputs:
                metadata = {"version": "4.16.0"} if "turnserver" in relative_path else None
                write_public_diagnostic(
                    source / relative_path,
                    raw,
                    metadata=metadata,
                )

            self.assertEqual(
                build_public_artifact_tree(source, public),
                len(PUBLIC_PATHS),
            )
            self.assertEqual(
                validate_public_artifact_tree(public, require_complete=True),
                len(PUBLIC_PATHS),
            )
            self.assertEqual(
                {
                    path.relative_to(public).as_posix()
                    for path in public.rglob("*")
                    if path.is_file()
                },
                PUBLIC_PATHS,
            )
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in public.rglob("*.json")
            )
            self.assertNotIn("/Users/alice", rendered)
            self.assertNotIn("10.0.0.1", rendered)
            self.assertNotIn("turn://user:pass", rendered)
            self.assertNotIn("private-hostname", rendered)

    def test_projection_failure_removes_stale_public_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            public = source / "public"
            source.mkdir(mode=0o700)
            public.mkdir(mode=0o700)
            stale = public / "stale.json"
            stale.write_text("{}", encoding="utf-8")
            stale.chmod(0o600)
            (source / "direct.json").write_bytes(b"\xff")

            with self.assertRaisesRegex(E2EFailure, "strict UTF-8 JSON"):
                build_public_artifact_tree(source, public, allow_missing=True)

            self.assertFalse(public.exists())

    def test_projection_rejects_missing_application_e2ee_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            source.mkdir(mode=0o700)
            evidence = private_evidence("direct")
            evidence["webrtc"].pop("application_e2ee")
            write_private_text(source / "direct.json", json.dumps(evidence))

            with self.assertRaisesRegex(E2EFailure, "application_e2ee"):
                build_public_artifact_tree(
                    source,
                    source / "public",
                    allow_missing=True,
                )

    def test_projection_rejects_tampered_application_e2ee_proof(self) -> None:
        for value in (False, True, "pass", "AES-256-GCM disabled"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "private"
                source.mkdir(mode=0o700)
                evidence = private_evidence("direct")
                evidence["webrtc"]["application_e2ee"] = value
                write_private_text(source / "direct.json", json.dumps(evidence))

                with self.assertRaisesRegex(
                    E2EFailure, "application E2EE|must be a non-empty string"
                ):
                    build_public_artifact_tree(
                        source,
                        source / "public",
                        allow_missing=True,
                    )

    def test_projection_rejects_missing_or_tampered_product_host(self) -> None:
        for value in (None, "LegacyProductSession", False):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "private"
                source.mkdir(mode=0o700)
                evidence = private_evidence("direct")
                if value is None:
                    evidence["product_session"].pop("host")
                else:
                    evidence["product_session"]["host"] = value
                write_private_text(source / "direct.json", json.dumps(evidence))

                with self.assertRaisesRegex(E2EFailure, "product_session.host|host session"):
                    build_public_artifact_tree(
                        source,
                        source / "public",
                        allow_missing=True,
                    )

    def test_projection_requires_complete_real_private_proof(self) -> None:
        mutations = (
            ("signaling", "real_process", False),
            ("signaling", "authenticated_session", "not-run"),
            ("webrtc", "real_peer_connections", 1),
            ("webrtc", "offer_answer_via_http_signaling", "not-run"),
            ("webrtc", "ice_candidate_exchange", "not-run"),
        )
        for section, field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "private"
                source.mkdir(mode=0o700)
                evidence = private_evidence("direct")
                evidence[section][field] = value
                write_private_text(source / "direct.json", json.dumps(evidence))

                with self.assertRaises(E2EFailure):
                    build_public_artifact_tree(
                        source, source / "public", allow_missing=True
                    )

    def test_projection_rejects_incomplete_data_channel_and_product_proof(self) -> None:
        for section, field in (
            ("data_channels", "control"),
            ("data_channels", "media"),
            ("product_session", "client_hello"),
            ("product_session", "media"),
            ("product_session", "touch_input"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "private"
                source.mkdir(mode=0o700)
                evidence = private_evidence("direct")
                target = (
                    evidence["webrtc"]["data_channels"]
                    if section == "data_channels"
                    else evidence["product_session"]
                )
                target.pop(field)
                write_private_text(source / "direct.json", json.dumps(evidence))

                with self.assertRaises(E2EFailure):
                    build_public_artifact_tree(
                        source, source / "public", allow_missing=True
                    )

    def test_projection_rejects_cross_mode_source_or_artifact_mismatch(self) -> None:
        for section, field, value in (
            ("source", "source_fingerprint", "9" * 64),
            ("artifacts", "mac_host_sha256", "8" * 64),
        ):
            with self.subTest(section=section), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "private"
                source.mkdir(mode=0o700)
                direct = private_evidence("direct")
                relay = private_evidence("relay")
                if section == "source":
                    relay["environment"]["repository_source"][field] = value
                else:
                    relay[section][field] = value
                write_private_text(source / "direct.json", json.dumps(direct))
                write_private_text(source / "relay.json", json.dumps(relay))

                with self.assertRaisesRegex(E2EFailure, "different source|different artifact"):
                    build_public_artifact_tree(
                        source, source / "public", allow_missing=True
                    )

    def test_projection_rejects_relay_label_with_host_candidate_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            source.mkdir(mode=0o700)
            evidence = private_evidence("relay")
            evidence["webrtc"]["selected_candidate_pair"] = (
                "relay(local=host,remote=host,protocol=udp)"
            )
            write_private_text(source / "relay.json", json.dumps(evidence))

            with self.assertRaisesRegex(E2EFailure, "relay candidate types"):
                build_public_artifact_tree(
                    source, source / "public", allow_missing=True
                )

    def test_projection_rejects_symlinked_private_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            source.mkdir(mode=0o700)
            target = root / "evidence.json"
            target.write_text(json.dumps(private_evidence("direct")), encoding="utf-8")
            os.symlink(target, source / "direct.json")

            with self.assertRaisesRegex(E2EFailure, "regular file"):
                build_public_artifact_tree(
                    source,
                    source / "public",
                    allow_missing=True,
                )

    def test_projection_rejects_symlinked_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-private"
            real_source.mkdir(mode=0o700)
            real_public = real_source / "public"
            real_public.mkdir(mode=0o700)
            sentinel = real_public / "keep.json"
            sentinel.write_text("{}", encoding="utf-8")
            source_link = root / "private-link"
            os.symlink(real_source, source_link)

            with self.assertRaisesRegex(E2EFailure, "real directory"):
                build_public_artifact_tree(
                    source_link,
                    source_link / "public",
                    allow_missing=True,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "{}")

    def test_projection_rejects_output_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            source.mkdir(mode=0o700)
            target = root / "outside"
            target.mkdir(mode=0o700)
            sentinel = target / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            output = source / "public"
            os.symlink(target, output)

            with self.assertRaisesRegex(E2EFailure, "must not be a symlink"):
                build_public_artifact_tree(source, output, allow_missing=True)
            self.assertFalse(output.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_projection_rejects_output_outside_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            source.mkdir(mode=0o700)
            with self.assertRaisesRegex(E2EFailure, "<private-root>/public"):
                build_public_artifact_tree(
                    source,
                    root / "public",
                    allow_missing=True,
                )

    def test_public_validator_rejects_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary)
            unexpected = public / "raw.log"
            unexpected.write_text("raw", encoding="utf-8")
            unexpected.chmod(0o600)
            with self.assertRaisesRegex(E2EFailure, "unexpected public artifact"):
                validate_public_artifact_tree(public)

    def test_public_validator_rejects_unknown_json_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "private"
            public = source / "public"
            source.mkdir(mode=0o700)
            write_private_text(
                source / "direct.json",
                json.dumps(private_evidence("direct")),
            )
            build_public_artifact_tree(source, public, allow_missing=True)
            direct = public / "direct.json"
            value = json.loads(direct.read_text(encoding="utf-8"))
            value["notes"] = "unreviewed free-form text"
            direct.write_text(json.dumps(value), encoding="utf-8")
            direct.chmod(0o600)

            with self.assertRaisesRegex(E2EFailure, "invalid keys"):
                validate_public_artifact_tree(public)

    def test_public_validator_rejects_cross_mode_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            public = source / "public"
            source.mkdir(mode=0o700)
            for mode in ("direct", "relay"):
                write_private_text(
                    source / f"{mode}.json", json.dumps(private_evidence(mode))
                )
            build_public_artifact_tree(source, public, allow_missing=True)
            relay = public / "relay.json"
            value = json.loads(relay.read_text(encoding="utf-8"))
            value["source"]["source_fingerprint"] = "9" * 64
            write_private_text(relay, json.dumps(value))

            with self.assertRaisesRegex(E2EFailure, "different source or artifacts"):
                validate_public_artifact_tree(public)

    def test_public_projection_rejects_unsupported_candidate_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            source.mkdir(mode=0o700)
            evidence = private_evidence("direct")
            evidence["webrtc"]["selected_candidate_pair"] = (
                "direct(local=host,remote=host,protocol=udp-private-token)"
            )
            write_private_text(source / "direct.json", json.dumps(evidence))

            with self.assertRaisesRegex(E2EFailure, "unsupported protocol"):
                build_public_artifact_tree(
                    source,
                    source / "public",
                    allow_missing=True,
                )

    def test_public_validator_rejects_unsupported_candidate_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private"
            public = source / "public"
            source.mkdir(mode=0o700)
            write_private_text(
                source / "direct.json",
                json.dumps(private_evidence("direct")),
            )
            build_public_artifact_tree(source, public, allow_missing=True)
            direct = public / "direct.json"
            value = json.loads(direct.read_text(encoding="utf-8"))
            value["webrtc"]["candidate_transport"] = "udp-private-token"
            direct.write_text(json.dumps(value), encoding="utf-8")
            direct.chmod(0o600)

            with self.assertRaisesRegex(E2EFailure, "transport is unsupported"):
                validate_public_artifact_tree(public)

    @mock.patch(
        "scripts.phase3_webrtc.processes.coturn_residue_snapshot",
        return_value={"/var/tmp/turn_999.log"},
    )
    def test_new_coturn_legacy_residue_fails_closed(self, _: mock.Mock) -> None:
        with self.assertRaisesRegex(E2EFailure, "legacy /var/tmp residue"):
            assert_no_new_coturn_residue(set())

    def test_unsupported_coturn_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            turnserver = Path(temporary) / "turnserver"
            turnserver.write_text("#!/bin/sh\necho 4.18.0\n", encoding="utf-8")
            turnserver.chmod(0o700)
            with open_verified_external_executable(
                turnserver, "coturn binary"
            ) as snapshot:
                with self.assertRaisesRegex(E2EFailure, "unsupported coturn version"):
                    supported_coturn_version(snapshot, ROOT)


if __name__ == "__main__":
    unittest.main()
