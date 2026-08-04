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
BUILD_MANIFEST_SCHEMA = "dev.vibescreen.phase3-webrtc-build/v1"
BUILD_MANIFEST_NAME = "build-manifest.json"
GENERATED_SOURCE_PATH_PREFIXES = ("scripts/phase3_webrtc/.build/",)
SLICE_CONFIGURATION = {
    "transport": {
        "command": "--phase3-webrtc-signaling-self-test",
        "pass_marker": "Phase 3 WebRTC signaling self-test: PASS",
    },
    "product": {
        "command": "--phase3-product-signaling-self-test",
        "pass_marker": "Phase 3 product signaling self-test: PASS",
    },
}
PRODUCT_PLAINTEXT_SEEDS = (
    "VIBE-PRODUCT-E2E-KEYFRAME-PLAINTEXT-SEED",
    "VIBE-PRODUCT-E2E-DELTA-PLAINTEXT-SEED",
)
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
        "--slice", choices=tuple(SLICE_CONFIGURATION), default="transport",
        help="Transport preserves the original channel smoke; product runs Protocol v1 InternetProductSession composition.",
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
        for value in (item for item in redact_values if item):
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


def repository_revision(repo_root: Path) -> str:
    """Return the exact Git revision represented by the E2E evidence."""
    revision = version_output(["git", "rev-parse", "HEAD"], repo_root)
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", revision) is None:
        raise E2EFailure(f"git returned an invalid HEAD revision: {revision!r}")
    return revision.lower()


def git_bytes(arguments: list[str], repo_root: Path) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        error_text = completed.stderr.decode("utf-8", errors="replace").strip()
        raise E2EFailure(f"git {' '.join(arguments)} failed: {error_text}")
    return completed.stdout


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return bytes_sha256(encoded)


def repository_source_state(repo_root: Path) -> dict[str, Any]:
    """Describe the committed and dirty sources represented by a build."""
    revision = repository_revision(repo_root)
    tracked_diff = git_bytes(["diff", "--binary", "--no-ext-diff", "HEAD", "--"], repo_root)
    untracked_output = git_bytes(
        ["ls-files", "--others", "--exclude-standard", "-z"], repo_root
    )
    untracked_paths = sorted(
        os.fsdecode(raw_path)
        for raw_path in untracked_output.split(b"\0")
        if raw_path
    )
    untracked_manifest = []
    for relative_path in untracked_paths:
        normalized_path = relative_path.replace(os.sep, "/")
        if any(
            normalized_path.startswith(prefix)
            for prefix in GENERATED_SOURCE_PATH_PREFIXES
        ):
            continue
        path = repo_root / relative_path
        if path.is_symlink():
            content_hash = bytes_sha256(os.fsencode(os.readlink(path)))
        elif path.is_file():
            content_hash = sha256(path)
        else:
            raise E2EFailure(f"untracked source disappeared or is not a file: {relative_path}")
        untracked_manifest.append({"path": normalized_path, "sha256": content_hash})

    tracked_diff_sha256 = bytes_sha256(tracked_diff)
    untracked_manifest_sha256 = canonical_json_sha256(untracked_manifest)
    dirty = bool(tracked_diff or untracked_manifest)
    fingerprint_inputs = {
        "repository_commit": revision,
        "tracked_diff_sha256": tracked_diff_sha256,
        "untracked_manifest_sha256": untracked_manifest_sha256,
    }
    return {
        **fingerprint_inputs,
        "dirty": dirty,
        "evidence_qualification": (
            "non-commit evidence (dirty worktree)" if dirty else "commit evidence"
        ),
        "untracked_manifest": untracked_manifest,
        "source_fingerprint": canonical_json_sha256(fingerprint_inputs),
    }


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


def build_manifest_path(repo_root: Path) -> Path:
    return repo_root / "scripts/phase3_webrtc/.build" / BUILD_MANIFEST_NAME


def create_build_manifest(
    repo_root: Path,
    signaling_binary: Path,
    mac_binary: Path,
    source_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": BUILD_MANIFEST_SCHEMA,
        "source_fingerprint": source_state["source_fingerprint"],
        "artifacts": {
            "signaling": {
                "path": str(signaling_binary.relative_to(repo_root)),
                "sha256": sha256(signaling_binary),
            },
            "mac_host": {
                "path": str(mac_binary.relative_to(repo_root)),
                "sha256": sha256(mac_binary),
            },
        },
    }


def write_build_manifest(repo_root: Path, manifest: dict[str, Any]) -> None:
    path = build_manifest_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_binaries(repo_root: Path, timeout: int) -> tuple[Path, Path, list[str]]:
    source_state = repository_source_state(repo_root)
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
    completed_source_state = repository_source_state(repo_root)
    if completed_source_state["source_fingerprint"] != source_state["source_fingerprint"]:
        raise E2EFailure("repository sources changed while binaries were building")
    write_build_manifest(
        repo_root,
        create_build_manifest(repo_root, signaling_binary, mac_binary, source_state),
    )
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
    manifest_path = build_manifest_path(repo_root)
    if not manifest_path.is_file():
        raise E2EFailure("--skip-build requires a build manifest; rebuild without --skip-build")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exception:
        raise E2EFailure(f"invalid --skip-build manifest: {exception}") from exception
    if manifest.get("schema") != BUILD_MANIFEST_SCHEMA:
        raise E2EFailure("--skip-build manifest has an unsupported schema")
    source_state = repository_source_state(repo_root)
    if manifest.get("source_fingerprint") != source_state["source_fingerprint"]:
        raise E2EFailure("--skip-build binaries do not match the current source fingerprint")
    expected_artifacts = {
        "signaling": paths[0],
        "mac_host": paths[1],
    }
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise E2EFailure("--skip-build manifest omits artifact hashes")
    for name, binary in expected_artifacts.items():
        artifact = artifacts.get(name)
        if not isinstance(artifact, dict) or artifact.get("sha256") != sha256(binary):
            raise E2EFailure(f"--skip-build {name} binary hash does not match its manifest")
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


def validate_peer_output(output: str, *, mode: str, slice_name: str) -> str:
    slice_configuration = SLICE_CONFIGURATION[slice_name]
    if slice_configuration["pass_marker"] not in output:
        raise E2EFailure(f"macOS peer output lacks PASS marker:\n{output}")
    if "applicationE2EE=true" not in output:
        raise E2EFailure(f"macOS peer did not prove application record encryption:\n{output}")
    pair_match = re.search(
        r"selectedCandidatePair=([a-z]+\(local=[^,]+,remote=[^,]+,protocol=[^)]+\))",
        output,
    )
    if slice_name == "transport":
        if pair_match is None or not pair_match.group(1).startswith(f"{mode}("):
            raise E2EFailure(f"macOS peer did not prove a {mode} candidate pair:\n{output}")
        return pair_match.group(1)

    product_route = re.search(r"\broute=(direct|relay)\b", output)
    if product_route is None or product_route.group(1) != mode:
        raise E2EFailure(f"macOS peer did not prove a {mode} route:\n{output}")
    if pair_match is None or not pair_match.group(1).startswith(f"{mode}("):
        raise E2EFailure(f"macOS product peer did not prove a {mode} candidate pair:\n{output}")
    required_product_markers = (
        "productSession=true", "protocolV1=true", "epoch=1",
        "configEpoch=2", "rotation=90", "keyframe=true", "delta=true", "input=true",
    )
    missing_product_markers = [marker for marker in required_product_markers if marker not in output]
    if missing_product_markers:
        raise E2EFailure(
            "macOS product peer omitted evidence markers "
            f"{missing_product_markers}:\n{output}"
        )
    return pair_match.group(1)


def run_direct(
    repo_root: Path,
    signaling_binary: Path,
    mac_binary: Path,
    timeout: int,
    *,
    mode: str = "direct",
    slice_name: str = "transport",
    peer_environment_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    slice_configuration = SLICE_CONFIGURATION[slice_name]
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
                    [str(mac_binary), slice_configuration["command"]],
                    cwd=mac_binary.parent, timeout=timeout, environment=peer_environment,
                    redact_values=peer_secrets,
                )
                selected_candidate_pair = validate_peer_output(
                    peer.stdout, mode=mode, slice_name=slice_name
                )
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
        scan_values = secrets_to_scan + list(PRODUCT_PLAINTEXT_SEEDS)
        assert_secret_free(service_log, scan_values, "signaling log")
        assert_secret_free(peer.stdout, scan_values, "macOS peer output")
        source_state = repository_source_state(repo_root)
        evidence = {
            "schema": "dev.vibescreen.phase3-webrtc-e2e/v1",
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
                "signaling_sha256": sha256(signaling_binary),
                "mac_host_sha256": sha256(mac_binary),
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
        return evidence, peer.stdout


def write_turnserver_config(
    path: Path, *, turn_port: int, username: str, password: str, realm: str
) -> None:
    configuration = "\n".join((
        "no-cli",
        "no-tls",
        "no-dtls",
        "fingerprint",
        "lt-cred-mech",
        "allow-loopback-peers",
        "listening-ip=127.0.0.1",
        "relay-ip=127.0.0.1",
        f"listening-port={turn_port}",
        f"realm={realm}",
        f"user={username}:{password}",
        "",
    ))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(configuration)


def turnserver_command(turnserver: Path, config_path: Path) -> list[str]:
    return [str(turnserver), "-c", str(config_path)]


def run_coturn_forced_relay(
    arguments: argparse.Namespace,
    peer_test: Callable[[dict[str, str]], tuple[dict[str, Any], str]],
) -> tuple[dict[str, Any], tuple[dict[str, Any], str]]:
    if not arguments.turnserver.is_file() or not os.access(arguments.turnserver, os.X_OK):
        raise E2EFailure(f"coturn binary unavailable: {arguments.turnserver}")
    turn_port = reserve_port()
    username = f"e2e-{secrets.token_hex(8)}"
    password = secrets.token_urlsafe(32)
    realm = "phase3.local"
    with tempfile.TemporaryDirectory(prefix="vibe-phase3-coturn-") as temporary:
        temporary_root = Path(temporary)
        log_path = temporary_root / "turnserver.log"
        config_path = temporary_root / "turnserver.conf"
        write_turnserver_config(
            config_path,
            turn_port=turn_port,
            username=username,
            password=password,
            realm=realm,
        )
        with log_path.open("w+", encoding="utf-8") as log:
            turn = subprocess.Popen(
                turnserver_command(arguments.turnserver, config_path),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                time.sleep(2)
                if turn.poll() is not None:
                    raise E2EFailure("coturn exited before the forced-relay peer test")
                peer_result = peer_test({
                    "VIBE_WEBRTC_ICE_URLS": f"turn:127.0.0.1:{turn_port}?transport=udp",
                    "VIBE_WEBRTC_ICE_USERNAME": username,
                    "VIBE_WEBRTC_ICE_CREDENTIAL": password,
                    "VIBE_WEBRTC_FORCE_RELAY": "true",
                })
            finally:
                stop_process(turn)
                log.flush()
                log.seek(0)
                turn_log = log.read()
        assert_secret_free(turn_log, [password], "coturn log")
        coturn_evidence = {
            "real_process": True,
            "version": version_output([str(arguments.turnserver), "--version"], Path(temporary)),
            "credential_config_mode": "0600",
            "credential_exposed_in_process_arguments": False,
            "forced_libwebrtc_relay": "pass",
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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            destination.write(rendered)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
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
                repo_root, signaling_binary, mac_binary, arguments.timeout_seconds,
                slice_name=arguments.slice,
            )
            print(peer_output, end="" if peer_output.endswith("\n") else "\n")
            write_evidence(arguments.output, evidence)
            return 0

        if not production_relay_hook_available(repo_root):
            evidence = {
                "schema": "dev.vibescreen.phase3-webrtc-e2e/v1",
                "mode": "relay",
                "result": "blocked",
                "production_peer": {
                    "result": "not_run",
                    "reason": "macOS signaling self-test hard-codes STUN and forceRelay=false",
                    "required_environment": list(RELAY_HOOK_ENVIRONMENT),
                },
            }
            write_evidence(arguments.output, evidence)
            raise E2EFailure(
                "production forced-relay ICE is unavailable: "
                "the macOS CLI must accept ICE URLs/username/credential and forceRelay"
            )
        coturn, peer_result = run_coturn_forced_relay(
            arguments,
            peer_test=lambda relay_environment: run_direct(
                repo_root,
                signaling_binary,
                mac_binary,
                arguments.timeout_seconds,
                mode="relay",
                slice_name=arguments.slice,
                peer_environment_overrides=relay_environment,
            ),
        )
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
