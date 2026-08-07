"""Signaling, peer, and coturn orchestration for the Phase 3 E2E."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import secrets
import subprocess
import time
from typing import Any, Callable

from scripts.phase3_webrtc.model import (
    DEFAULT_SESSION_TTL_SECONDS,
    E2EFailure,
    EVIDENCE_SCHEMA,
    PRODUCT_PLAINTEXT_SEEDS,
    RELAY_HOOK_ENVIRONMENT,
    SLICE_CONFIGURATION,
    SUPPORTED_CANDIDATE_PROTOCOLS,
    SUPPORTED_CANDIDATE_TYPES,
    SUPPORTED_COTURN_VERSIONS,
)
from scripts.phase3_webrtc.privacy import (
    assert_secret_free,
    write_private_text,
    write_public_diagnostic,
)
from scripts.phase3_webrtc.processes import (
    assert_no_new_coturn_residue,
    coturn_residue_snapshot,
    http_json,
    http_text,
    private_temporary_directory,
    reserve_port,
    reserve_tcp_udp_port,
    run_checked,
    stop_process,
    version_output,
    wait_for_health,
)
from scripts.phase3_webrtc.source_artifacts import (
    VerifiedExecutable,
    open_verified_binaries,
    open_verified_external_executable,
    record_turnserver_execution,
    verify_build_manifest,
)


_CANDIDATE_PAIR_PATTERN = (
    r"(?P<candidate_pair>(?P<candidate_route>direct|relay)"
    r"\(local=(?P<local_candidate>[a-z0-9_-]+),"
    r"remote=(?P<remote_candidate>[a-z0-9_-]+),"
    r"protocol=(?P<candidate_protocol>[a-z0-9_-]+)\))"
)
_TRANSPORT_TERMINAL_PATTERN = re.compile(
    re.escape(SLICE_CONFIGURATION["transport"]["pass_marker"])
    + r" \(peerConnection=(?P<peer_connection>true|false), "
    + r"iceRestart=(?P<ice_restart>true|false|not-run), "
    + r"applicationE2EE=(?P<application_e2ee>true|false), "
    + r"transmissionEpochAdvanced=(?P<transmission_epoch_advanced>true|false), "
    + r"staleContextRejected=(?P<stale_context_rejected>true|false), "
    + r"controlOrderedReliableBidirectional="
    + r"(?P<control_ordered_reliable_bidirectional>true|false), "
    + r"mediaUnorderedZeroRetransmitBidirectional="
    + r"(?P<media_unordered_zero_retransmit_bidirectional>true|false), "
    + r"selectedCandidatePair="
    + _CANDIDATE_PAIR_PATTERN
    + r"\)"
)
_PRODUCT_TERMINAL_PATTERN = re.compile(
    re.escape(SLICE_CONFIGURATION["product"]["pass_marker"])
    + r" \(productSession=(?P<product_session>true|false), "
    + r"protocolV1=(?P<protocol_v1>true|false), "
    + r"route=(?P<route>direct|relay), "
    + r"epoch=(?P<epoch>[0-9]+), "
    + r"configEpoch=(?P<config_epoch>[0-9]+), "
    + r"rotation=(?P<rotation>[0-9]+), "
    + r"keyframe=(?P<keyframe>true|false), "
    + r"delta=(?P<delta>true|false), "
    + r"input=(?P<input>true|false), "
    + r"applicationE2EE=(?P<application_e2ee>true|false), "
    + r"selectedCandidatePair="
    + _CANDIDATE_PAIR_PATTERN
    + r", controlChannel=(?P<control_channel>[a-z0-9_-]+), "
    + r"mediaChannel=(?P<media_channel>[a-z0-9_-]+)\)"
)


def _single_peer_terminal_record(output: str) -> str:
    records = [
        line
        for line in output.splitlines()
        if line.startswith("Phase 3 ") and " self-test:" in line
    ]
    if len(records) != 1:
        raise E2EFailure(
            "macOS peer output must contain exactly one Phase 3 terminal record"
        )
    return records[0]


def _match_peer_terminal_record(
    output: str,
    pattern: re.Pattern[str],
) -> re.Match[str]:
    match = pattern.fullmatch(_single_peer_terminal_record(output))
    if match is None:
        raise E2EFailure("macOS peer terminal record is malformed or untrusted")
    return match


def _require_terminal_fields(
    match: re.Match[str],
    expected: dict[str, str],
) -> None:
    mismatched = [name for name, value in expected.items() if match[name] != value]
    if mismatched:
        raise E2EFailure(
            "macOS peer terminal record did not prove required fields: "
            + ",".join(mismatched)
        )


def signaling_config(port: int) -> dict[str, Any]:
    return {
        "listen_address": f"127.0.0.1:{port}",
        "session_ttl_seconds": DEFAULT_SESSION_TTL_SECONDS,
        "max_session_ttl_seconds": DEFAULT_SESSION_TTL_SECONDS,
        "max_active_sessions": 8,
        "session_creates_per_minute": 8,
        "messages_per_minute": 120,
        "max_request_body_bytes": 131072,
        "max_sdp_bytes": 65536,
        "max_candidate_bytes": 4096,
        "max_candidates_per_role": 64,
        "max_wait_seconds": 25,
        "max_waiters_per_role": 1,
        "cleanup_interval_seconds": 5,
    }


def metric_value(metrics: str, name: str) -> int:
    for line in metrics.splitlines():
        if line.startswith(f"{name} "):
            return int(float(line.split()[1]))
    raise E2EFailure(f"missing signaling metric {name}")


def validate_peer_output(output: str, *, mode: str, slice_name: str) -> str:
    if slice_name == "transport":
        match = _match_peer_terminal_record(output, _TRANSPORT_TERMINAL_PATTERN)
        _require_terminal_fields(match, {
            "peer_connection": "true",
            "ice_restart": "not-run",
            "application_e2ee": "true",
            "transmission_epoch_advanced": "true",
            "stale_context_rejected": "true",
            "control_ordered_reliable_bidirectional": "true",
            "media_unordered_zero_retransmit_bidirectional": "true",
        })
    elif slice_name == "product":
        match = _match_peer_terminal_record(output, _PRODUCT_TERMINAL_PATTERN)
        _require_terminal_fields(match, {
            "product_session": "true",
            "protocol_v1": "true",
            "epoch": "1",
            "config_epoch": "2",
            "rotation": "90",
            "keyframe": "true",
            "delta": "true",
            "input": "true",
            "application_e2ee": "true",
            "control_channel": "ordered-reliable",
            "media_channel": "unordered-zero-retransmit",
        })
    else:
        raise E2EFailure(f"unsupported Phase 3 peer slice: {slice_name}")
    if match["candidate_protocol"] not in SUPPORTED_CANDIDATE_PROTOCOLS:
        raise E2EFailure("macOS peer reported an unsupported candidate protocol")
    candidate_types = (match["local_candidate"], match["remote_candidate"])
    if any(value not in SUPPORTED_CANDIDATE_TYPES for value in candidate_types):
        raise E2EFailure("macOS peer reported an unsupported candidate type")
    if mode == "relay" and candidate_types != ("relay", "relay"):
        raise E2EFailure(
            "macOS peer did not prove TURN relay candidate types on both peers"
        )
    if mode == "direct" and "relay" in candidate_types:
        raise E2EFailure("macOS peer direct route unexpectedly selected a relay candidate")
    if slice_name == "transport":
        if match["candidate_route"] != mode:
            raise E2EFailure(f"macOS peer did not prove a {mode} candidate pair")
        return match["candidate_pair"]
    if match["route"] != mode:
        raise E2EFailure(f"macOS peer did not prove a {mode} route")
    if match["candidate_route"] != mode:
        raise E2EFailure(f"macOS product peer did not prove a {mode} candidate pair")
    return match["candidate_pair"]


def run_direct(
    repo_root: Path,
    signaling_binary: Path,
    mac_binary: Path,
    timeout: int,
    *,
    mode: str = "direct",
    slice_name: str = "transport",
    peer_environment_overrides: dict[str, str] | None = None,
    diagnostics_dir: Path | None = None,
) -> dict[str, Any]:
    with open_verified_binaries(
        repo_root,
        expected_signaling=signaling_binary,
        expected_mac_host=mac_binary,
    ) as (verified_signaling, verified_mac, source_state):
        return _run_direct_verified(
            repo_root,
            verified_signaling,
            verified_mac,
            source_state,
            timeout,
            mode=mode,
            slice_name=slice_name,
            peer_environment_overrides=peer_environment_overrides,
            diagnostics_dir=diagnostics_dir,
        )


def _run_direct_verified(
    repo_root: Path,
    signaling_binary: VerifiedExecutable,
    mac_binary: VerifiedExecutable,
    source_state: dict[str, Any],
    timeout: int,
    *,
    mode: str = "direct",
    slice_name: str = "transport",
    peer_environment_overrides: dict[str, str] | None = None,
    diagnostics_dir: Path | None = None,
) -> dict[str, Any]:
    slice_configuration = SLICE_CONFIGURATION[slice_name]
    issuer_token = secrets.token_urlsafe(48)
    metrics_token = secrets.token_urlsafe(48)
    port = reserve_port()
    base_url = f"http://127.0.0.1:{port}"
    with private_temporary_directory("vibe-phase3-signaling-") as temporary_root:
        config_path = temporary_root / "signaling.json"
        write_private_text(config_path, json.dumps(signaling_config(port)))
        raw_log_path = temporary_root / "signaling.log"
        write_private_text(raw_log_path, "")
        environment = os.environ.copy()
        environment.update({
            "VIBE_SIGNALING_ISSUER_TOKEN": issuer_token,
            "VIBE_SIGNALING_METRICS_TOKEN": metrics_token,
        })
        environment.update(signaling_binary.environment_overrides or {})
        with raw_log_path.open("r+", encoding="utf-8") as log:
            signaling_binary.validate_execution_target()
            process = subprocess.Popen(
                [str(signaling_binary.execution_path), "--config", str(config_path)],
                cwd=signaling_binary.cwd,
                env=environment,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                pass_fds=signaling_binary.pass_fds,
            )
            try:
                wait_for_health(base_url, process, timeout)
                ready_status, ready = http_json("GET", f"{base_url}/readyz")
                if ready_status != 200 or ready != {"status": "ok"}:
                    raise E2EFailure("unexpected signaling readiness response")
                create_status, session = http_json(
                    "POST",
                    f"{base_url}/v1/sessions",
                    token=issuer_token,
                    body={
                        "request_id": f"local-e2e-{secrets.token_hex(12)}",
                        "ttl_seconds": DEFAULT_SESSION_TTL_SECONDS,
                    },
                )
                if create_status != 201:
                    raise E2EFailure(f"expected session create 201, got {create_status}")
                required = ("session_id", "host_token", "device_token", "expires_at")
                if any(not session.get(key) for key in required):
                    raise E2EFailure("session response omitted role credentials")
                peer_environment = os.environ.copy()
                peer_environment.update({
                    "VIBE_SIGNALING_URL": base_url,
                    "VIBE_SIGNALING_SESSION_ID": str(session["session_id"]),
                    "VIBE_SIGNALING_HOST_TOKEN": str(session["host_token"]),
                    "VIBE_SIGNALING_DEVICE_TOKEN": str(session["device_token"]),
                })
                peer_environment.update(peer_environment_overrides or {})
                peer_environment.update(mac_binary.environment_overrides or {})
                relay_credential = (peer_environment_overrides or {}).get(
                    "VIBE_WEBRTC_ICE_CREDENTIAL", ""
                )
                relay_username = (peer_environment_overrides or {}).get(
                    "VIBE_WEBRTC_ICE_USERNAME", ""
                )
                peer_secrets = (
                    str(session["session_id"]),
                    str(session["host_token"]),
                    str(session["device_token"]),
                    relay_username,
                    relay_credential,
                )
                mac_binary.validate_execution_target()
                peer = run_checked(
                    [str(mac_binary.execution_path), slice_configuration["command"]],
                    cwd=mac_binary.cwd,
                    timeout=timeout,
                    environment=peer_environment,
                    redact_values=peer_secrets + PRODUCT_PLAINTEXT_SEEDS,
                    diagnostic_private_paths=(repo_root, temporary_root),
                    pass_fds=mac_binary.pass_fds,
                )
                assert_secret_free(
                    peer.stdout,
                    (*peer_secrets, *PRODUCT_PLAINTEXT_SEEDS),
                    "macOS peer output",
                )
                selected_candidate_pair = validate_peer_output(
                    peer.stdout, mode=mode, slice_name=slice_name
                )
                if diagnostics_dir is not None:
                    write_public_diagnostic(
                        diagnostics_dir / "peer.log",
                        peer.stdout,
                        secret_values=(*peer_secrets, *PRODUCT_PLAINTEXT_SEEDS),
                        private_paths=(repo_root, temporary_root, Path.home()),
                    )
                metrics = http_text(f"{base_url}/metrics", metrics_token)
                accepted = metric_value(metrics, "vibescreen_signaling_messages_accepted_total")
                if accepted < 4:
                    raise E2EFailure("signaling did not accept the complete SDP/ICE exchange")
            finally:
                stop_process(process)
                log.flush()
                log.seek(0)
                service_log = log.read()
                secret_values = [issuer_token, metrics_token]
                if "session" in locals():
                    secret_values.extend(
                        str(session.get(key, ""))
                        for key in ("session_id", "host_token", "device_token")
                    )
                secret_values.append(
                    (peer_environment_overrides or {}).get("VIBE_WEBRTC_ICE_USERNAME", "")
                )
                secret_values.append(
                    (peer_environment_overrides or {}).get("VIBE_WEBRTC_ICE_CREDENTIAL", "")
                )
                assert_secret_free(
                    service_log,
                    (*secret_values, *PRODUCT_PLAINTEXT_SEEDS),
                    "signaling log",
                )
                if diagnostics_dir is not None:
                    write_public_diagnostic(
                        diagnostics_dir / "signaling.log",
                        service_log,
                        secret_values=secret_values,
                        private_paths=(repo_root, temporary_root, Path.home()),
                    )
    verify_build_manifest(
        repo_root, signaling_binary.source_path, mac_binary.source_path
    )
    evidence: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "mode": mode,
        "slice": slice_name,
        "result": "pass",
        "evidence_qualification": source_state["evidence_qualification"],
        "signaling": {
            "real_process": True,
            "health": "pass",
            "ready": "pass",
            "authenticated_session": "pass",
            "accepted_messages": accepted,
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
            "selected_candidate_pair": selected_candidate_pair,
            "selected_route": mode,
        },
        "artifacts": {
            "signaling_sha256": signaling_binary.sha256,
            "mac_host_sha256": mac_binary.sha256,
            "webrtc_framework_sha256": (
                mac_binary.runtime_artifacts or {}
            ).get("webrtc_framework_sha256"),
            "turnserver_sha256": "not_used",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "go": version_output(["go", "version"], repo_root),
            "swift": version_output(["swift", "--version"], repo_root),
            "repository_commit": source_state["repository_commit"],
            "repository_source": source_state,
        },
        "limitations": [
            "Real peer E2E does not inject an artificial media backlog; latest-frame replacement is covered by --phase3-internet-self-test.",
        ],
    }
    if slice_name == "product":
        evidence["product_session"] = {
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
        }
        evidence["limitations"].append(
            "Product slice uses a local synthetic Protocol v1 device peer; it is not Android device or UI evidence."
        )
    return evidence


def write_turnserver_config(
    path: Path,
    *,
    turn_port: int,
    username: str,
    password: str,
    realm: str,
    pidfile: Path,
    runtime_log: Path,
) -> None:
    configuration = "\n".join((
        "no-cli", "no-tls", "no-dtls", "no-stdout-log", "simple-log",
        "fingerprint", "lt-cred-mech", "allow-loopback-peers",
        "listening-ip=127.0.0.1", "relay-ip=127.0.0.1",
        f"listening-port={turn_port}", f"realm={realm}",
        f"pidfile={pidfile}", f"log-file={runtime_log}",
        f"user={username}:{password}", "",
    ))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(configuration)


def turnserver_command(
    turnserver: VerifiedExecutable | Path,
    config_path: Path,
) -> list[str]:
    execution_path = (
        turnserver.execution_path
        if isinstance(turnserver, VerifiedExecutable)
        else turnserver
    )
    return [str(execution_path), "-c", str(config_path)]


def supported_coturn_version(turnserver: VerifiedExecutable, cwd: Path) -> str:
    turnserver.validate_execution_target()
    output = run_checked(
        [str(turnserver.execution_path), "--version"],
        cwd=cwd,
        timeout=10,
        pass_fds=turnserver.pass_fds,
    ).stdout.strip()
    versions = [
        line.strip()
        for line in output.splitlines()
        if re.fullmatch(r"\d+\.\d+\.\d+", line.strip())
    ]
    if len(versions) != 1 or versions[0] not in SUPPORTED_COTURN_VERSIONS:
        allowed = ",".join(SUPPORTED_COTURN_VERSIONS)
        raise E2EFailure(f"unsupported coturn version; allowed versions: {allowed}")
    return versions[0]


def run_coturn_forced_relay(
    arguments: Any,
    peer_test: Callable[[dict[str, str]], dict[str, Any]],
    diagnostics_dir: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    residue_before = coturn_residue_snapshot()
    try:
        with (
            open_verified_external_executable(
                arguments.turnserver, "coturn binary"
            ) as turnserver,
            private_temporary_directory("vibe-phase3-coturn-") as temporary_root,
        ):
            coturn_version = supported_coturn_version(turnserver, temporary_root)
            turn_port = reserve_tcp_udp_port()
            username = f"e2e-{secrets.token_hex(8)}"
            password = secrets.token_urlsafe(32)
            realm = "phase3.local"
            config_path = temporary_root / "turnserver.conf"
            pidfile = temporary_root / "turnserver.pid"
            runtime_log = temporary_root / "turnserver-runtime.log"
            stdio_log = temporary_root / "turnserver-stdio.log"
            write_private_text(runtime_log, "")
            write_private_text(stdio_log, "")
            write_turnserver_config(
                config_path,
                turn_port=turn_port,
                username=username,
                password=password,
                realm=realm,
                pidfile=pidfile,
                runtime_log=runtime_log,
            )
            environment = os.environ.copy()
            environment.update({
                "HOME": str(temporary_root),
                "TMPDIR": str(temporary_root),
                "TMP": str(temporary_root),
                "TEMP": str(temporary_root),
            })
            with stdio_log.open("r+", encoding="utf-8") as stdio:
                previous_umask = os.umask(0o077)
                try:
                    turnserver.validate_execution_target()
                    turn = subprocess.Popen(
                        turnserver_command(turnserver, config_path),
                        cwd=temporary_root,
                        env=environment,
                        stdout=stdio,
                        stderr=subprocess.STDOUT,
                        text=True,
                        pass_fds=turnserver.pass_fds,
                    )
                finally:
                    os.umask(previous_umask)
                try:
                    time.sleep(2)
                    if turn.poll() is not None:
                        raise E2EFailure("coturn exited before the forced-relay peer test")
                    if not pidfile.is_file():
                        raise E2EFailure("coturn did not create the configured temporary pidfile")
                    for private_path in (
                        temporary_root,
                        config_path,
                        pidfile,
                        runtime_log,
                        stdio_log,
                    ):
                        expected_mode = 0o700 if private_path == temporary_root else 0o600
                        if private_path.stat().st_mode & 0o777 != expected_mode:
                            raise E2EFailure(f"coturn temporary path mode is not {expected_mode:o}")
                    peer_result = peer_test({
                        "VIBE_WEBRTC_ICE_URLS": f"turn:127.0.0.1:{turn_port}?transport=udp",
                        "VIBE_WEBRTC_ICE_USERNAME": username,
                        "VIBE_WEBRTC_ICE_CREDENTIAL": password,
                        "VIBE_WEBRTC_FORCE_RELAY": "true",
                    })
                finally:
                    stop_process(turn)
                    stdio.flush()
                    stdio.seek(0)
                    stdio_text = stdio.read()
            runtime_text = runtime_log.read_text(encoding="utf-8", errors="replace")
            combined_log = f"runtime:\n{runtime_text}\nstdio:\n{stdio_text}"
            if diagnostics_dir is not None:
                write_public_diagnostic(
                    diagnostics_dir / "turnserver.log",
                    combined_log,
                    secret_values=(username, password),
                    private_paths=(temporary_root, repo_root or "", Path.home()),
                    metadata={"version": coturn_version},
                )
            for private_path in (config_path, pidfile, runtime_log, stdio_log):
                private_path.unlink(missing_ok=True)
            if any(temporary_root.iterdir()):
                raise E2EFailure("coturn temporary working directory was not fully cleaned")
            evidence = {
                "real_process": True,
                "version": coturn_version,
                "executable_sha256": turnserver.sha256,
                "allowed_versions": list(SUPPORTED_COTURN_VERSIONS),
                "temporary_working_directory_mode": "0700",
                "temporary_file_mode": "0600",
                "explicit_pidfile": True,
                "explicit_runtime_log": True,
                "credential_exposed_in_process_arguments": False,
                "forced_libwebrtc_relay": "pass",
                "public_diagnostic_projection": "pass",
            }
            artifacts = peer_result.get("artifacts")
            if not isinstance(artifacts, dict):
                raise E2EFailure("relay evidence omits artifact hashes")
            artifacts["turnserver_sha256"] = turnserver.sha256
            if repo_root is None:
                raise E2EFailure("relay execution requires a repository root")
            record_turnserver_execution(repo_root, turnserver.sha256)
            return evidence, peer_result
    finally:
        assert_no_new_coturn_residue(residue_before)


def production_relay_hook_available(repo_root: Path) -> bool:
    source = repo_root / "baseline/MacHost/Sources/Phase3/InternetTransport/ProductionWebRTCEngineSelfTest.swift"
    text = source.read_text(encoding="utf-8")
    return all(name in text for name in RELAY_HOOK_ENVIRONMENT)
