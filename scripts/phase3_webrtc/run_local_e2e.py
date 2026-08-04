#!/usr/bin/env python3
"""Run the real local Phase 3 signaling + macOS libwebrtc E2E."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
from urllib import error, request

DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_SESSION_TTL_SECONDS = 120
SIGNALING_VERSION = "0.1.0"
PASS_MARKER = "Phase 3 WebRTC signaling self-test: PASS"
RELAY_HOOK_ENVIRONMENT = (
    "VIBE_WEBRTC_ICE_URLS",
    "VIBE_WEBRTC_ICE_USERNAME",
    "VIBE_WEBRTC_ICE_CREDENTIAL",
    "VIBE_WEBRTC_FORCE_RELAY",
)


class E2EFailure(RuntimeError):
    """An evidence gate failed."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start real signaling and two macOS libwebrtc peers."
    )
    parser.add_argument(
        "--mode", choices=("direct", "relay"), default="direct",
        help="Direct runs the production signaling CLI; relay additionally proves local coturn allocation.",
    )
    parser.add_argument(
        "--repo-root", type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (default: inferred from this script).",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Write a redacted JSON evidence record to this path.",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Use existing release binaries after verifying that they exist.",
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-process timeout (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--turnserver", type=Path,
        default=Path("/opt/homebrew/opt/coturn/bin/turnserver"),
        help="coturn turnserver binary.",
    )
    parser.add_argument(
        "--turnutils-uclient", type=Path,
        default=Path("/opt/homebrew/opt/coturn/bin/turnutils_uclient"),
        help="coturn allocation/data client.",
    )
    parser.add_argument(
        "--turnutils-peer", type=Path,
        default=Path("/opt/homebrew/opt/coturn/bin/turnutils_peer"),
        help="coturn peer echo process.",
    )
    arguments = parser.parse_args()
    if arguments.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return arguments


def run_checked(
    command: list[str], *, cwd: Path, timeout: int, environment: dict[str, str] | None = None,
    redact_values: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        rendered_command = " ".join(command)
        rendered_output = completed.stdout
        for value in redact_values:
            rendered_command = rendered_command.replace(value, "<redacted>")
            rendered_output = rendered_output.replace(value, "<redacted>")
        raise E2EFailure(
            f"command failed ({completed.returncode}): {rendered_command}\n{rendered_output}"
        )
    return completed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_output(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise E2EFailure(f"version command failed: {' '.join(command)}")
    return completed.stdout.strip()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 3,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    encoded = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        encoded = json.dumps(body, separators=(",", ":")).encode()
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    call = request.Request(url, data=encoded, headers=headers, method=method)
    try:
        with request.urlopen(call, timeout=timeout) as response:
            return response.status, json.load(response)
    except error.HTTPError as exception:
        payload = exception.read().decode("utf-8", errors="replace")
        raise E2EFailure(f"HTTP {exception.code} from {url}: {payload}") from exception


def http_text(url: str, token: str, timeout: float = 3) -> str:
    call = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(call, timeout=timeout) as response:
        return response.read().decode("utf-8")


def wait_for_health(base_url: str, process: subprocess.Popen[str], timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise E2EFailure(f"signaling exited before health check ({process.returncode})")
        try:
            status, payload = http_json("GET", f"{base_url}/healthz")
            if status == 200 and payload == {"status": "ok"}:
                return
        except (OSError, E2EFailure, http.client.HTTPException) as exception:
            last_error = str(exception)
        time.sleep(0.05)
    raise E2EFailure(f"signaling health timeout: {last_error}")


def stop_process(process: subprocess.Popen[str], timeout: int = 5) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


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


def build_binaries(repo_root: Path, timeout: int) -> tuple[Path, Path, list[str]]:
    signaling_root = repo_root / "services/signaling"
    mac_root = repo_root / "baseline/MacHost"
    build_root = repo_root / "scripts/phase3_webrtc/.build"
    signaling_binary = build_root / "signaling/vibe-signaling"
    swift_scratch = build_root / "swift"
    mac_binary = swift_scratch / "release/Telemachus"
    signaling_binary.parent.mkdir(parents=True, exist_ok=True)
    outputs = []
    outputs.append(run_checked(
        ["go", "build", "-trimpath", "-ldflags", f"-X main.version={SIGNALING_VERSION}",
         "-o", str(signaling_binary), "./cmd/vibe-signaling"],
        cwd=signaling_root, timeout=timeout,
    ).stdout)
    outputs.append(run_checked(
        ["swift", "build", "-c", "release", "--scratch-path", str(swift_scratch)],
        cwd=mac_root, timeout=max(timeout, 300)
    ).stdout)
    return signaling_binary, mac_binary, outputs


def locate_binaries(repo_root: Path) -> tuple[Path, Path]:
    build_root = repo_root / "scripts/phase3_webrtc/.build"
    paths = (
        build_root / "signaling/vibe-signaling",
        build_root / "swift/release/Telemachus",
    )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise E2EFailure(f"--skip-build requested but binaries are missing: {', '.join(missing)}")
    return paths


def assert_secret_free(text: str, secret_values: list[str], label: str) -> None:
    leaked = [secret for secret in secret_values if secret and secret in text]
    if leaked:
        raise E2EFailure(f"{label} leaked {len(leaked)} generated secret value(s)")


def metric_value(metrics: str, name: str) -> int:
    for line in metrics.splitlines():
        if line.startswith(f"{name} "):
            return int(float(line.split()[1]))
    raise E2EFailure(f"missing signaling metric {name}")


def run_direct(
    repo_root: Path,
    signaling_binary: Path,
    mac_binary: Path,
    timeout: int,
    *,
    mode: str = "direct",
    peer_environment_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    issuer_token = secrets.token_urlsafe(48)
    metrics_token = secrets.token_urlsafe(48)
    port = reserve_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="vibe-phase3-signaling-") as temporary:
        temporary_root = Path(temporary)
        config_path = temporary_root / "signaling.json"
        config_path.write_text(json.dumps(signaling_config(port)), encoding="utf-8")
        log_path = temporary_root / "signaling.log"
        environment = os.environ.copy()
        environment.update({
            "VIBE_SIGNALING_ISSUER_TOKEN": issuer_token,
            "VIBE_SIGNALING_METRICS_TOKEN": metrics_token,
        })
        with log_path.open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(signaling_binary), "--config", str(config_path)],
                cwd=signaling_binary.parent,
                env=environment,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for_health(base_url, process, timeout)
                ready_status, ready = http_json("GET", f"{base_url}/readyz")
                if ready_status != 200 or ready != {"status": "ok"}:
                    raise E2EFailure(f"unexpected readiness response: {ready_status} {ready}")
                create_status, session = http_json(
                    "POST", f"{base_url}/v1/sessions", token=issuer_token,
                    body={"request_id": f"local-e2e-{secrets.token_hex(12)}",
                          "ttl_seconds": DEFAULT_SESSION_TTL_SECONDS},
                )
                if create_status != 201:
                    raise E2EFailure(f"expected session create 201, got {create_status}")
                required = ("session_id", "host_token", "device_token", "expires_at")
                if any(not session.get(key) for key in required):
                    raise E2EFailure("session response omitted role credentials")
                peer_environment = os.environ.copy()
                peer_environment.update({
                    "VIBE_SIGNALING_URL": base_url,
                    "VIBE_SIGNALING_SESSION_ID": session["session_id"],
                    "VIBE_SIGNALING_HOST_TOKEN": session["host_token"],
                    "VIBE_SIGNALING_DEVICE_TOKEN": session["device_token"],
                })
                peer_environment.update(peer_environment_overrides or {})
                relay_credential = (peer_environment_overrides or {}).get(
                    "VIBE_WEBRTC_ICE_CREDENTIAL", ""
                )
                peer_secrets = (
                    str(session["session_id"]),
                    str(session["host_token"]),
                    str(session["device_token"]),
                    relay_credential,
                )
                peer = run_checked(
                    [str(mac_binary), "--phase3-webrtc-signaling-self-test"],
                    cwd=mac_binary.parent, timeout=timeout, environment=peer_environment,
                    redact_values=peer_secrets,
                )
                if PASS_MARKER not in peer.stdout:
                    raise E2EFailure(f"macOS peer output lacks PASS marker:\n{peer.stdout}")
                if "applicationE2EE=true" not in peer.stdout:
                    raise E2EFailure(f"macOS peer did not prove application record encryption:\n{peer.stdout}")
                pair_match = re.search(
                    r"selectedCandidatePair=([a-z]+\(local=[^,]+,remote=[^,]+,protocol=[^)]+\))",
                    peer.stdout,
                )
                if pair_match is None or not pair_match.group(1).startswith(f"{mode}("):
                    raise E2EFailure(f"macOS peer did not prove a {mode} candidate pair:\n{peer.stdout}")
                metrics = http_text(f"{base_url}/metrics", metrics_token)
                accepted = metric_value(metrics, "vibescreen_signaling_messages_accepted_total")
                if accepted < 4:
                    raise E2EFailure(f"expected offer, answer, and ICE exchange; accepted={accepted}")
            finally:
                stop_process(process)
                log.flush()
                log.seek(0)
                service_log = log.read()

        secrets_to_scan = [issuer_token, metrics_token]
        if "session" in locals():
            secrets_to_scan.extend(
                str(session.get(key, "")) for key in ("session_id", "host_token", "device_token")
            )
        secrets_to_scan.append((peer_environment_overrides or {}).get("VIBE_WEBRTC_ICE_CREDENTIAL", ""))
        assert_secret_free(service_log, secrets_to_scan, "signaling log")
        assert_secret_free(peer.stdout, secrets_to_scan, "macOS peer output")
        evidence = {
            "schema": "dev.vibescreen.phase3-webrtc-e2e/v1",
            "mode": mode,
            "result": "pass",
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
                "selected_candidate_pair": pair_match.group(1),
                "selected_route": mode,
            },
            "artifacts": {
                "signaling_sha256": sha256(signaling_binary),
                "mac_host_sha256": sha256(mac_binary),
            },
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "go": version_output(["go", "version"], repo_root),
                "swift": version_output(["swift", "--version"], repo_root),
                "repository_commit": "unavailable: repository has no initial commit",
            },
            "limitations": [
                "Real peer E2E does not inject an artificial media backlog; latest-frame replacement is covered by --phase3-internet-self-test.",
            ],
        }
        return evidence, peer.stdout


def run_coturn_smoke(
    arguments: argparse.Namespace,
    peer_test: Callable[[dict[str, str]], tuple[dict[str, Any], str]] | None = None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], str] | None]:
    binaries = (arguments.turnserver, arguments.turnutils_uclient, arguments.turnutils_peer)
    missing = [str(path) for path in binaries if not path.is_file() or not os.access(path, os.X_OK)]
    if missing:
        raise E2EFailure(f"coturn binaries unavailable: {', '.join(missing)}")
    turn_port = reserve_port()
    peer_port = reserve_port()
    username = f"e2e-{secrets.token_hex(8)}"
    password = secrets.token_urlsafe(32)
    realm = "phase3.local"
    with tempfile.TemporaryDirectory(prefix="vibe-phase3-coturn-") as temporary:
        log_path = Path(temporary) / "turnserver.log"
        with log_path.open("w+", encoding="utf-8") as log:
            turn = subprocess.Popen([
                str(arguments.turnserver), "--no-cli", "--no-tls", "--no-dtls",
                "--fingerprint", "--lt-cred-mech", "--allow-loopback-peers",
                "--listening-ip=127.0.0.1",
                "--relay-ip=127.0.0.1", f"--listening-port={turn_port}",
                f"--realm={realm}", f"--user={username}:{password}",
            ], stdout=log, stderr=subprocess.STDOUT, text=True)
            peer = subprocess.Popen([
                str(arguments.turnutils_peer), "-L", "127.0.0.1", "-p", str(peer_port)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            try:
                time.sleep(2)
                if turn.poll() is not None or peer.poll() is not None:
                    raise E2EFailure("coturn or turnutils_peer exited before allocation test")
                client = run_checked([
                    str(arguments.turnutils_uclient), "-v", "-u", username, "-w", password,
                    "-e", "127.0.0.1", "-r", str(peer_port), "-p", str(turn_port),
                    "-n", "3", "-c", "127.0.0.1",
                ], cwd=Path(temporary), timeout=arguments.timeout_seconds, redact_values=(password,))
                assert_secret_free(client.stdout, [password], "turnutils output")
                if "tot_send_msgs=3" not in client.stdout or "tot_recv_msgs=3" not in client.stdout:
                    raise E2EFailure(f"TURN relay data counters did not match:\n{client.stdout}")
                peer_result = peer_test({
                    "VIBE_WEBRTC_ICE_URLS": f"turn:127.0.0.1:{turn_port}?transport=udp",
                    "VIBE_WEBRTC_ICE_USERNAME": username,
                    "VIBE_WEBRTC_ICE_CREDENTIAL": password,
                    "VIBE_WEBRTC_FORCE_RELAY": "true",
                }) if peer_test is not None else None
            finally:
                stop_process(peer)
                stop_process(turn)
                log.flush()
                log.seek(0)
                turn_log = log.read()
        assert_secret_free(turn_log, [password], "coturn log")
        coturn_evidence = {
            "real_process": True,
            "version": version_output([str(arguments.turnserver), "--version"], Path(temporary)),
            "allocation": "pass",
            "relayed_datagrams_sent": 3,
            "relayed_datagrams_received": 3,
            "secret_log_scan": "pass",
        }
        return coturn_evidence, peer_result


def production_relay_hook_available(repo_root: Path) -> bool:
    source = (repo_root / "baseline/MacHost/Sources/Phase3/InternetTransport/ProductionWebRTCEngineSelfTest.swift")
    text = source.read_text(encoding="utf-8")
    return all(name in text for name in RELAY_HOOK_ENVIRONMENT)


def write_evidence(path: Path | None, evidence: dict[str, Any]) -> None:
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    print(f"Evidence: {path}")


def main() -> int:
    arguments = parse_arguments()
    repo_root = arguments.repo_root.resolve()
    try:
        if arguments.skip_build:
            signaling_binary, mac_binary = locate_binaries(repo_root)
        else:
            signaling_binary, mac_binary, _ = build_binaries(repo_root, arguments.timeout_seconds)

        if arguments.mode == "direct":
            evidence, peer_output = run_direct(
                repo_root, signaling_binary, mac_binary, arguments.timeout_seconds
            )
            print(peer_output, end="" if peer_output.endswith("\n") else "\n")
            write_evidence(arguments.output, evidence)
            return 0

        if not production_relay_hook_available(repo_root):
            coturn, _ = run_coturn_smoke(arguments)
            evidence = {
                "schema": "dev.vibescreen.phase3-webrtc-e2e/v1",
                "mode": "relay",
                "result": "blocked",
                "coturn": coturn,
                "production_peer": {
                    "result": "not_run",
                    "reason": "macOS signaling self-test hard-codes STUN and forceRelay=false",
                    "required_environment": list(RELAY_HOOK_ENVIRONMENT),
                },
            }
            write_evidence(arguments.output, evidence)
            raise E2EFailure(
                "coturn allocation passed, but production forced-relay ICE is unavailable: "
                "the macOS CLI must accept ICE URLs/username/credential and forceRelay"
            )
        coturn, peer_result = run_coturn_smoke(
            arguments,
            peer_test=lambda relay_environment: run_direct(
                repo_root,
                signaling_binary,
                mac_binary,
                arguments.timeout_seconds,
                mode="relay",
                peer_environment_overrides=relay_environment,
            ),
        )
        if peer_result is None:
            raise E2EFailure("forced-relay peer test did not run")
        evidence, peer_output = peer_result
        evidence["coturn"] = coturn
        print(peer_output, end="" if peer_output.endswith("\n") else "\n")
        write_evidence(arguments.output, evidence)
        return 0
    except (E2EFailure, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exception:
        print(f"Phase 3 local WebRTC E2E: FAIL ({exception})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
