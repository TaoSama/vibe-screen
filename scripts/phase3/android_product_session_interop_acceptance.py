#!/usr/bin/env python3
"""Run the auditable Android M144 to Mac M150 product-session interop gate.

This is a synthetic Protocol v1 host acceptance, not UI, ScreenCaptureKit,
real-display, rotation, or soak evidence. A caller must already own the
Internet device lease; this runner never creates or removes that lease.

The 0600 lease is exact JSON with only ``owner``, ``pid``, ``task``, and
``commit``. ``task`` must be ``phase3-android-internet-acceptance``, ``commit``
must equal HEAD, and ``pid`` must identify a separate live lock-holder process.

The runner starts the real local signaling service, but never starts coturn.
The caller must first start a host/device-reachable local coturn, pass its
private ICE configuration, and retain a coturn raw log plus version record.

Before acquiring the device lease, the runner verifies a clean HEAD and builds
the Android app/test APKs, release Mac host, and trimmed signaling binary using
fixed repository commands and paths. It rechecks the identical clean source
after building; arbitrary caller-built artifacts and manifests are not accepted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


INTERNET_LEASE_LOCK = Path("/tmp/vibe-screen-device-internet.lock")
LEASE_TASK = "phase3-android-internet-acceptance"
DEVICE_LOCK_GLOB = "vibe-screen-device-*.lock"
MAX_LEASE_BYTES = 4096
MANDATORY_DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
APP_PACKAGE = "dev.telemachus.display"
TEST_RUNNER = f"{APP_PACKAGE}.test/androidx.test.runner.AndroidJUnitRunner"
TEST_CLASS = f"{APP_PACKAGE}.internet.InternetProductSessionInteropInstrumentedTest"
HOST_MARKER_PREFIX = "PHASE3_ANDROID_INTEROP_HOST_PASS"
DEVICE_MARKER_PREFIX = "PHASE3_ANDROID_INTEROP_DEVICE_PASS"
MARKER_FLAGS = (
    "kdf_kat=true",
    "transcript_kat=true",
    "video_config=true",
    "keyframe=true",
    "delta=true",
    "touch=true",
    "application_e2ee=true",
)
DEVICE_ONLY_FLAGS = ("protocol_v1=true", "lifecycle_store=test_isolated")


class InteropError(RuntimeError):
    """Raised when an acceptance gate cannot be proved."""


@dataclass
class CommandRecord:
    name: str
    returncode: int
    stdout_sha256: str
    stdout_bytes: int
    stderr_sha256: str
    stderr_bytes: int
    elapsed_seconds: float


@dataclass(frozen=True)
class IceConfiguration:
    stun_url: str
    turn_url: str
    username: str
    credential: str


@dataclass(frozen=True)
class LeaseSnapshot:
    device: int
    inode: int
    content: bytes
    owner: str
    pid: int
    task: str
    commit: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_no_other_device_locks(additional_locks: Sequence[Path]) -> None:
    discovered = tuple(Path("/tmp").glob(DEVICE_LOCK_GLOB))
    locks = dict.fromkeys((*MANDATORY_DEVICE_LOCKS, *additional_locks, *discovered))
    locks.pop(INTERNET_LEASE_LOCK, None)
    for lock in locks:
        try:
            lock.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise InteropError(f"cannot verify mandatory device lock state: {error}") from error
        raise InteropError("a mandatory device lock exists; no ADB command was run")


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lease_file(path: Path) -> tuple[os.stat_result, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise InteropError("required Internet device lease is unavailable") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_mode & 0o777 != 0o600:
            raise InteropError("Internet device lease must be a regular 0600 file")
        content = b""
        while len(content) <= MAX_LEASE_BYTES:
            chunk = os.read(descriptor, MAX_LEASE_BYTES + 1 - len(content))
            if not chunk:
                break
            content += chunk
        if not content or len(content) > MAX_LEASE_BYTES:
            raise InteropError("Internet device lease content is invalid")
    finally:
        os.close(descriptor)
    try:
        path_status = path.lstat()
    except OSError as error:
        raise InteropError("Internet device lease disappeared during verification") from error
    if (path_status.st_dev, path_status.st_ino) != (status.st_dev, status.st_ino):
        raise InteropError("Internet device lease changed during verification")
    return status, content


def capture_lease(expected_commit: str, additional_locks: Sequence[Path] = ()) -> LeaseSnapshot:
    _require_no_other_device_locks(additional_locks)
    status, content = _read_lease_file(INTERNET_LEASE_LOCK)
    try:
        root = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InteropError("Internet device lease JSON is invalid") from error
    if not isinstance(root, dict) or set(root) != {"owner", "pid", "task", "commit"}:
        raise InteropError("Internet device lease fields are invalid")
    owner, pid, task, commit = root["owner"], root["pid"], root["task"], root["commit"]
    if not isinstance(owner, str) or not owner or len(owner) > 256:
        raise InteropError("Internet device lease owner is invalid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid == os.getpid():
        raise InteropError("Internet device lease holder PID is not independent")
    if task != LEASE_TASK or commit != expected_commit:
        raise InteropError("Internet device lease task or commit does not match this run")
    if not _pid_is_alive(pid):
        raise InteropError("Internet device lease holder is not alive")
    return LeaseSnapshot(status.st_dev, status.st_ino, content, owner, pid, task, commit)


def require_lease(snapshot: LeaseSnapshot, expected_commit: str,
                  additional_locks: Sequence[Path] = ()) -> None:
    _require_no_other_device_locks(additional_locks)
    status, content = _read_lease_file(INTERNET_LEASE_LOCK)
    if (status.st_dev, status.st_ino) != (snapshot.device, snapshot.inode):
        raise InteropError("Internet device lease inode changed; no ADB command was run")
    if not hmac.compare_digest(content, snapshot.content):
        raise InteropError("Internet device lease bytes changed; no ADB command was run")
    if snapshot.task != LEASE_TASK or snapshot.commit != expected_commit or not _pid_is_alive(snapshot.pid):
        raise InteropError("Internet device lease authorization is no longer valid; no ADB command was run")


class Adb:
    def __init__(self, executable: str, endpoint: str, lease: LeaseSnapshot, expected_commit: str,
                 additional_locks: Sequence[Path], records: list[CommandRecord]) -> None:
        self.executable = executable
        self.endpoint = endpoint
        self.lease = lease
        self.expected_commit = expected_commit
        self.additional_locks = tuple(additional_locks)
        self.records = records

    def host(self, arguments: Sequence[str], *, timeout: float = 60,
             stdin: bytes | None = None, name: str = "adb-host") -> str:
        return self._run([self.executable, *arguments], timeout, stdin, name)

    def device(self, arguments: Sequence[str], *, timeout: float = 60,
               stdin: bytes | None = None, name: str = "adb-device") -> str:
        return self._run([self.executable, "-s", self.endpoint, *arguments], timeout, stdin, name)

    def _run(self, command: list[str], timeout: float, stdin: bytes | None, name: str) -> str:
        require_lease(self.lease, self.expected_commit, self.additional_locks)
        started = time.monotonic()
        try:
            result = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise InteropError(f"{name} could not complete") from error
        require_lease(self.lease, self.expected_commit, self.additional_locks)
        stdout = result.stdout or b""
        stderr = result.stderr or b""
        self.records.append(CommandRecord(
            name=name,
            returncode=result.returncode,
            stdout_sha256=sha256_bytes(stdout),
            stdout_bytes=len(stdout),
            stderr_sha256=sha256_bytes(stderr),
            stderr_bytes=len(stderr),
            elapsed_seconds=round(time.monotonic() - started, 3),
        ))
        if result.returncode != 0:
            raise InteropError(
                f"{name} failed ({result.returncode}); stdout_sha256={sha256_bytes(stdout)} "
                f"stderr_sha256={sha256_bytes(stderr)}"
            )
        return stdout.decode("utf-8", errors="replace").strip()


def _lp(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def derive_test_material(session_id: str, epoch: int, host_id: str, device_id: str) -> dict[str, Any]:
    shared = secrets.token_bytes(32)
    bootstrap = secrets.token_bytes(32)
    transcript = secrets.token_bytes(32)
    encoded = b"".join(
        _lp(part)
        for part in (
            b"vibescreen/identity/v1",
            b"vibescreen/product-session-context/v1",
            transcript,
            session_id.encode(),
            epoch.to_bytes(8, "big"),
            host_id.encode(),
            device_id.encode(),
            (1).to_bytes(8, "big"),
            (2).to_bytes(8, "big"),
        )
    )
    bound = hashlib.sha256(encoded).digest()
    prk = hmac.new(bootstrap, shared, hashlib.sha256).digest()
    material = b""
    previous = b""
    counter = 1
    while len(material) < 128:
        previous = hmac.new(prk, previous + bound + bytes([counter]), hashlib.sha256).digest()
        material += previous
        counter += 1
    key_id = hashlib.sha256(hashlib.sha256(bound + material[:128]).digest()).hexdigest()
    return {
        "shared": shared,
        "bootstrap": bootstrap,
        "transcript": transcript,
        "bound_hex": bound.hex(),
        "key_id": key_id,
    }


def signaling_config(bind_address: str, port: int) -> dict[str, Any]:
    return {
        "listen_address": f"{bind_address}:{port}",
        "session_ttl_seconds": 300,
        "max_session_ttl_seconds": 900,
        "max_active_sessions": 32,
        "session_creates_per_minute": 30,
        "messages_per_minute": 120,
        "max_request_body_bytes": 131072,
        "max_sdp_bytes": 65536,
        "max_candidate_bytes": 4096,
        "max_candidates_per_role": 64,
        "max_wait_seconds": 25,
        "max_waiters_per_role": 1,
        "cleanup_interval_seconds": 5,
    }


def http_json(method: str, url: str, *, token: str | None = None,
              body: dict[str, Any] | None = None, timeout: float = 10) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    data = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise InteropError("local signaling request failed") from error


def wait_ready(base_url: str, process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise InteropError("local signaling process exited before readiness")
        try:
            status, body = http_json("GET", f"{base_url}/readyz", timeout=1)
            if status == 200 and body == {"status": "ok"}:
                return
        except InteropError:
            pass
        time.sleep(0.1)
    raise InteropError("local signaling readiness timed out")


def validate_marker(output: str, prefix: str, route: str, epoch: int,
                    extra_flags: Sequence[str] = ()) -> str:
    matches = [line.strip() for line in output.splitlines() if prefix in line]
    if len(matches) != 1:
        raise InteropError(f"expected exactly one {prefix} marker")
    marker = matches[0]
    tokens = marker.split()
    if not tokens or tokens[0] != prefix:
        raise InteropError(f"{prefix} marker prefix is not exact")
    fields: dict[str, str] = {}
    for token in tokens[1:]:
        if token.count("=") != 1:
            raise InteropError(f"{prefix} marker field is malformed")
        key, value = token.split("=", 1)
        if not key or key in fields:
            raise InteropError(f"{prefix} marker contains a duplicate field")
        fields[key] = value
    expected = {"route": route, "epoch": str(epoch)}
    for flag in (*MARKER_FLAGS, *extra_flags):
        key, value = flag.split("=", 1)
        expected[key] = value
    if fields != expected:
        raise InteropError(f"{prefix} marker omitted a required fail-closed assertion")
    return marker


def validate_instrumentation_result(output: str) -> None:
    forbidden = ("FAILURES!!!", "INSTRUMENTATION_FAILED", "Process crashed", "shortMsg=Process crashed")
    if any(value in output for value in forbidden):
        raise InteropError("Android instrumentation reported a failing terminal state")
    if len(re.findall(r"(?m)^OK \(1 test\)\s*$", output)) != 1:
        raise InteropError("Android instrumentation did not finish exactly one successful test")


def private_config_device_commands(config_name: str) -> dict[str, Any]:
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", config_name) is None:
        raise InteropError("private config basename is invalid")
    path = f"files/{config_name}"
    return {
        "prepare": [
            ["shell", "run-as", APP_PACKAGE, "mkdir", "-p", "files"],
            ["shell", "run-as", APP_PACKAGE, "chmod", "700", "files"],
        ],
        "import": ["shell", "run-as", APP_PACKAGE, "dd", f"of={path}", "status=none"],
        "chmod": ["shell", "run-as", APP_PACKAGE, "chmod", "600", path],
        "consumed": ["shell", "run-as", APP_PACKAGE, "test", "!", "-e", path],
        "cleanup": ["shell", "run-as", APP_PACKAGE, "rm", "-f", path],
    }


def redact(value: str, sensitive: Sequence[str]) -> str:
    result = value
    for secret in sorted((item for item in sensitive if item), key=len, reverse=True):
        result = result.replace(secret, "<redacted>")
    return result


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_name, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary_name).unlink(missing_ok=True)


def read_private_external(path: Path, repo: Path, maximum_bytes: int, label: str) -> tuple[Path, bytes]:
    try:
        link_status = path.lstat()
        if stat.S_ISLNK(link_status.st_mode):
            raise InteropError(f"{label} must not be a symlink")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(repo.resolve())
        except ValueError:
            pass
        else:
            raise InteropError(f"{label} must be outside the repository")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise InteropError(f"{label} is unavailable") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_mode & 0o777 != 0o600:
            raise InteropError(f"{label} must be a regular 0600 file")
        if status.st_size <= 0 or status.st_size > maximum_bytes:
            raise InteropError(f"{label} is empty or unbounded")
        encoded = os.read(descriptor, maximum_bytes + 1)
        if len(encoded) != status.st_size:
            raise InteropError(f"{label} changed during its bounded read")
    finally:
        os.close(descriptor)
    return resolved, encoded


def read_private_ice_configuration(path: Path, repo: Path) -> IceConfiguration:
    _, encoded = read_private_external(path, repo, 16 * 1024, "ICE configuration")
    try:
        root = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InteropError("ICE configuration is unavailable or invalid") from error
    required = {"stun_url", "turn_url", "username", "credential"}
    if not isinstance(root, dict) or set(root) != required:
        raise InteropError("ICE configuration fields are invalid")
    if any(not isinstance(root[key], str) or not root[key] or len(root[key]) > 4096 for key in required):
        raise InteropError("ICE configuration values are invalid")
    if not root["stun_url"].startswith(("stun:", "stuns:")):
        raise InteropError("ICE configuration requires an explicit STUN URL")
    if not root["turn_url"].startswith(("turn:", "turns:")):
        raise InteropError("ICE configuration requires an explicit host- and device-reachable TURN URL")
    return IceConfiguration(root["stun_url"], root["turn_url"], root["username"], root["credential"])


def controlled_build(repo: Path, expected_source: dict[str, str], timeout: float) -> tuple[dict[str, Path], dict[str, str], list[CommandRecord]]:
    if repository_state(repo) != expected_source:
        raise InteropError("repository source changed before controlled build")
    android_root = repo / "baseline/AndroidClient"
    mac_root = repo / "baseline/MacHost"
    signaling_root = repo / "services/signaling"
    paths = {
        "app_apk": android_root / "app/build/outputs/apk/debug/app-debug.apk",
        "test_apk": android_root / "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk",
        "mac_host": mac_root / ".build/release/Telemachus",
        "signaling_binary": signaling_root / "build/vibe-signaling",
    }
    paths["signaling_binary"].parent.mkdir(parents=True, exist_ok=True)
    commands = (
        ("android-controlled-build", [str(android_root / "gradlew"), "--no-daemon", "clean", "assembleDebug", "assembleDebugAndroidTest"], android_root),
        ("mac-controlled-build", ["swift", "build", "-c", "release"], mac_root),
        ("signaling-controlled-build", ["go", "build", "-trimpath", "-o", str(paths["signaling_binary"]), "./cmd/vibe-signaling"], signaling_root),
    )
    records: list[CommandRecord] = []
    for name, command, cwd in commands:
        started = time.monotonic()
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise InteropError(f"{name} could not complete") from error
        stdout, stderr = result.stdout or b"", result.stderr or b""
        records.append(CommandRecord(name, result.returncode, sha256_bytes(stdout), len(stdout), sha256_bytes(stderr), len(stderr), round(time.monotonic() - started, 3)))
        if result.returncode != 0:
            raise InteropError(f"{name} failed ({result.returncode})")
    if repository_state(repo) != expected_source:
        raise InteropError("repository source changed or became dirty during controlled build")
    if any(not path.is_file() for path in paths.values()):
        raise InteropError("controlled build omitted a fixed artifact")
    artifacts = {f"{name}_sha256": sha256_file(path) for name, path in paths.items()}
    return paths, artifacts, records


def require_artifacts_unchanged(paths: dict[str, Path], artifacts: dict[str, str]) -> None:
    expected_keys = {f"{name}_sha256" for name in paths}
    if set(artifacts) != expected_keys:
        raise InteropError("controlled artifact manifest fields changed")
    try:
        current = {f"{name}_sha256": sha256_file(path) for name, path in paths.items()}
    except OSError as error:
        raise InteropError("a controlled artifact disappeared during acceptance") from error
    if current != artifacts:
        raise InteropError("a controlled artifact changed after its clean HEAD build")


def repository_state(repo: Path) -> dict[str, str]:
    def git(*arguments: str) -> str:
        result = subprocess.run(["git", *arguments], cwd=repo, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise InteropError("cannot capture repository source state")
        return result.stdout.strip()
    if git("status", "--porcelain"):
        raise InteropError("repository must be clean before device evidence is captured")
    head = git("rev-parse", "HEAD")
    origin_main = git("rev-parse", "origin/main")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", origin_main, head], cwd=repo, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ancestry.returncode != 0:
        raise InteropError("HEAD is not based on the recorded origin/main commit")
    return {"commit": head, "tree": git("rev-parse", "HEAD^{tree}"), "origin_main_commit": origin_main}


def toolchain(executable: str, arguments: Sequence[str]) -> dict[str, str]:
    result = subprocess.run([executable, *arguments], check=False, capture_output=True, text=True, timeout=30)
    rendered = (result.stdout or result.stderr).strip()
    return {
        "sha256": sha256_bytes(rendered.encode()),
        "first_line": rendered.splitlines()[0] if rendered else "unavailable",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    ice = read_private_ice_configuration(args.ice_config_file, repo)
    raw_dir = args.raw_output_dir.resolve()
    try:
        raw_dir.relative_to(repo)
    except ValueError:
        pass
    else:
        raise InteropError("raw output directory must be outside the repository")
    source = repository_state(repo)
    paths, artifacts, build_records = controlled_build(repo, source, args.build_timeout)
    lease = capture_lease(source["commit"], args.device_lock)
    coturn_log, coturn_log_bytes = read_private_external(
        args.coturn_log, repo, 10 * 1024 * 1024, "coturn raw log"
    )
    coturn_version, coturn_version_bytes = read_private_external(
        args.coturn_version_file, repo, 16 * 1024, "coturn version record"
    )

    records: list[CommandRecord] = list(build_records)
    adb = Adb(args.adb, args.adb_endpoint, lease, source["commit"], args.device_lock, records)
    adb_version_output = adb.host(["version"], name="adb-version-non-device")
    started = datetime.now(timezone.utc).isoformat()
    issuer_token = secrets.token_urlsafe(48)
    metrics_token = secrets.token_urlsafe(48)
    host_id = f"host-{secrets.token_hex(16)}"
    device_id = f"device-{secrets.token_hex(16)}"
    epoch = secrets.randbelow(2**31 - 1) + 1
    route = args.route
    force_relay = route == "relay"
    bind_endpoint = f"{args.signaling_bind_address}:{args.signaling_port}"
    host_url = f"http://{bind_endpoint}"
    device_url = f"http://127.0.0.1:{args.android_signaling_port}"
    sensitive: list[str] = [
        lease.owner, args.adb_endpoint, issuer_token, metrics_token,
        ice.stun_url, ice.turn_url, ice.username, ice.credential,
        bind_endpoint, host_url, device_url, host_id, device_id,
    ]

    with tempfile.TemporaryDirectory(prefix="vibe-android-interop-") as temporary:
        temp = Path(temporary)
        config_path = temp / "signaling.json"
        config = signaling_config(args.signaling_bind_address, args.signaling_port)
        write_private(config_path, (json.dumps(config) + "\n").encode())
        service_log_path = temp / "signaling.log"
        environment = os.environ.copy()
        environment.update({
            "VIBE_SIGNALING_ISSUER_TOKEN": issuer_token,
            "VIBE_SIGNALING_METRICS_TOKEN": metrics_token,
        })
        with service_log_path.open("wb") as service_log:
            require_artifacts_unchanged(paths, artifacts)
            signaling = subprocess.Popen(
                [str(paths["signaling_binary"]), "--config", str(config_path)],
                cwd=paths["signaling_binary"].parent,
                env=environment,
                stdout=service_log,
                stderr=subprocess.STDOUT,
            )
            require_artifacts_unchanged(paths, artifacts)
        host_process: subprocess.Popen[bytes] | None = None
        config_name: str | None = None
        reverse_installed = False
        try:
            wait_ready(host_url, signaling, args.timeout)
            status, session = http_json(
                "POST", f"{host_url}/v1/sessions", token=issuer_token,
                body={"request_id": f"android-interop-{secrets.token_hex(12)}", "ttl_seconds": 300},
            )
            if status != 201 or any(not session.get(key) for key in ("session_id", "host_token", "device_token")):
                raise InteropError("local signaling did not issue complete role credentials")
            session_id = str(session["session_id"])
            host_token = str(session["host_token"])
            device_token = str(session["device_token"])
            sensitive.extend((session_id, host_token, device_token))
            material = derive_test_material(session_id, epoch, host_id, device_id)
            sensitive.extend(
                base64.b64encode(material[key]).decode() for key in ("shared", "bootstrap", "transcript")
            )
            sensitive.extend((material["bound_hex"], material["key_id"]))

            adb.host(["connect", args.adb_endpoint], timeout=args.timeout, name="adb-connect")
            if adb.device(["get-state"], timeout=args.timeout, name="adb-state") != "device":
                raise InteropError("ADB endpoint is not in device state")
            identity = {
                "manufacturer": adb.device(
                    ["shell", "getprop", "ro.product.manufacturer"], name="identity-manufacturer"
                ),
                "model": adb.device(["shell", "getprop", "ro.product.model"], name="identity-model"),
                "device": adb.device(["shell", "getprop", "ro.product.device"], name="identity-device"),
                "release": adb.device(["shell", "getprop", "ro.build.version.release"], name="identity-release"),
            }
            expected = ("nubia", "P0110", "pacific", "16")
            actual = (identity["manufacturer"].lower(), identity["model"], identity["device"], identity["release"])
            if actual != expected:
                raise InteropError("connected device identity does not match the authorized acceptance target")
            require_artifacts_unchanged(paths, artifacts)
            adb.device(
                ["install", "-r", "-t", str(paths["app_apk"])],
                timeout=args.install_timeout,
                name="install-app",
            )
            require_artifacts_unchanged(paths, artifacts)
            require_artifacts_unchanged(paths, artifacts)
            adb.device(
                ["install", "-r", "-t", str(paths["test_apk"])],
                timeout=args.install_timeout,
                name="install-test",
            )
            require_artifacts_unchanged(paths, artifacts)
            adb.device(
                ["reverse", f"tcp:{args.android_signaling_port}", f"tcp:{args.signaling_port}"],
                name="adb-reverse-signaling",
            )
            reverse_installed = True

            ice_urls = [ice.stun_url, ice.turn_url]
            private_config = {
                "signaling_url": device_url,
                "session_id": session_id,
                "device_token": device_token,
                "session_epoch": epoch,
                "host_id": host_id,
                "device_id": device_id,
                "shared_secret_base64": base64.b64encode(material["shared"]).decode(),
                "bootstrap_secret_base64": base64.b64encode(material["bootstrap"]).decode(),
                "transcript_context_base64": base64.b64encode(material["transcript"]).decode(),
                "expected_bound_context_hex": material["bound_hex"],
                "expected_traffic_key_id": material["key_id"],
                "ice_urls": ice_urls,
                "ice_username": ice.username,
                "ice_credential": ice.credential,
                "allow_insecure_signaling": True,
            }
            encoded_config = (json.dumps(private_config, separators=(",", ":")) + "\n").encode()
            config_name = f"interop-{secrets.token_hex(8)}.json"
            config_commands = private_config_device_commands(config_name)
            for index, command in enumerate(config_commands["prepare"]):
                adb.device(command, name=f"private-config-prepare-{index + 1}")
            import_output = adb.device(
                config_commands["import"],
                stdin=encoded_config,
                name="private-config-import",
            )
            if import_output:
                raise InteropError("private config import unexpectedly produced output")
            adb.device(config_commands["chmod"], name="private-config-mode")
            adb.device(["logcat", "-c"], name="clear-device-marker-log")

            host_environment = os.environ.copy()
            host_environment.update({
                "VIBE_SIGNALING_URL": host_url,
                "VIBE_SIGNALING_SESSION_ID": session_id,
                "VIBE_SIGNALING_HOST_TOKEN": host_token,
                "VIBE_PRODUCT_SESSION_EPOCH": str(epoch),
                "VIBE_PRODUCT_HOST_ID": host_id,
                "VIBE_PRODUCT_DEVICE_ID": device_id,
                "VIBE_PRODUCT_SHARED_SECRET_BASE64": private_config["shared_secret_base64"],
                "VIBE_PRODUCT_BOOTSTRAP_SECRET_BASE64": private_config["bootstrap_secret_base64"],
                "VIBE_PRODUCT_TRANSCRIPT_CONTEXT_BASE64": private_config["transcript_context_base64"],
                "VIBE_PRODUCT_BOUND_CONTEXT_HEX": material["bound_hex"],
                "VIBE_PRODUCT_TRAFFIC_KEY_ID": material["key_id"],
                "VIBE_WEBRTC_ICE_URLS": ",".join(ice_urls),
                "VIBE_WEBRTC_ICE_USERNAME": ice.username,
                "VIBE_WEBRTC_ICE_CREDENTIAL": ice.credential,
                "VIBE_WEBRTC_FORCE_RELAY": str(force_relay).lower(),
            })
            host_log_path = temp / "host.log"
            with host_log_path.open("wb") as host_log:
                require_artifacts_unchanged(paths, artifacts)
                host_process = subprocess.Popen(
                    [str(paths["mac_host"]), "--phase3-product-android-interop-host"],
                    cwd=paths["mac_host"].parent,
                    env=host_environment,
                    stdout=host_log,
                    stderr=subprocess.STDOUT,
                )
                require_artifacts_unchanged(paths, artifacts)
            device_output = adb.device(
                ["shell", "am", "instrument", "-w", "-r", "-e", "class", TEST_CLASS,
                 "-e", "configFile", config_name, "-e", "forceRelay", str(force_relay).lower(), TEST_RUNNER],
                timeout=args.timeout,
                name=f"instrumentation-{route}",
            )
            validate_instrumentation_result(device_output)
            device_marker_log = adb.device(
                ["logcat", "-d", "-v", "raw", "-s", "System.out:I", "*:S"],
                name="read-device-marker-log",
            )
            adb.device(
                config_commands["consumed"],
                name="private-config-consumed",
            )
            try:
                host_process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired as error:
                host_process.kill()
                host_process.wait()
                raise InteropError("Mac interop host timed out") from error
            host_output = host_log_path.read_text(encoding="utf-8", errors="replace")
            if host_process.returncode != 0:
                raise InteropError("Mac interop host failed")
            host_marker = validate_marker(host_output, HOST_MARKER_PREFIX, route, epoch)
            device_marker = validate_marker(
                device_marker_log, DEVICE_MARKER_PREFIX, route, epoch, DEVICE_ONLY_FLAGS
            )

            service_output = service_log_path.read_text(encoding="utf-8", errors="replace")
            raw_values = {
                "host.log": redact(host_output, sensitive),
                "device.log": redact(device_output + "\n" + device_marker_log, sensitive),
                "signaling.log": redact(service_output, sensitive),
                "coturn.log": redact(coturn_log_bytes.decode("utf-8", errors="replace"), sensitive),
                "coturn-version.txt": redact(
                    coturn_version_bytes.decode("utf-8", errors="replace"), sensitive
                ),
            }
            for name, raw in raw_values.items():
                if any(secret and secret in raw for secret in sensitive):
                    raise InteropError("raw artifact privacy scan failed")
                write_private(raw_dir / route / name, raw.encode())
        finally:
            cleanup_failures: list[Exception] = []
            if config_name is not None:
                try:
                    adb.device(
                        private_config_device_commands(config_name)["cleanup"],
                        name="private-config-cleanup",
                    )
                except InteropError as error:
                    cleanup_failures.append(error)
            if reverse_installed:
                try:
                    adb.device(
                        ["reverse", "--remove", f"tcp:{args.android_signaling_port}"],
                        name="adb-reverse-cleanup",
                    )
                except InteropError as error:
                    cleanup_failures.append(error)
            if host_process is not None and host_process.poll() is None:
                host_process.kill()
                host_process.wait()
            if signaling.poll() is None:
                signaling.send_signal(signal.SIGTERM)
                try:
                    signaling.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    signaling.kill()
                    signaling.wait()
            if cleanup_failures:
                raise InteropError(
                    "device cleanup could not run under the valid lease; reacquire a matching live lease "
                    "before safely removing the private config and ADB reverse mapping"
                ) from cleanup_failures[0]

    java_toolchain = toolchain("java", ["-version"])
    swift_toolchain = toolchain("swift", ["--version"])
    require_artifacts_unchanged(paths, artifacts)
    require_lease(lease, source["commit"], args.device_lock)
    report = {
        "schema": "dev.vibescreen.phase3-android-product-interop/v1",
        "result": "pass",
        "route": route,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "artifacts": {
            **artifacts,
            "coturn_log_sha256": sha256_bytes(coturn_log_bytes),
            "coturn_version_record_sha256": sha256_bytes(coturn_version_bytes),
        },
        "toolchain": {
            "adb": {
                "sha256": sha256_bytes(adb_version_output.encode()),
                "first_line": adb_version_output.splitlines()[0] if adb_version_output else "unavailable",
                "device_operation": False,
                "lease_guarded": True,
            },
            "java": java_toolchain,
            "swift": swift_toolchain,
        },
        "device": {"product": "Nubia P0110", "codename": "pacific", "operating_system": "Android 16"},
        "assertions": {
            "real_android_app_and_instrumentation": "pass",
            "real_local_signaling_process": "pass",
            "caller_managed_reachable_coturn_route": "pass" if route == "relay" else "not_exercised",
            "selected_route": "pass",
            "protocol_v1": "pass",
            "aes_256_gcm_control": "pass",
            "aes_256_gcm_media": "pass",
            "synthetic_video_config_keyframe_delta": "pass",
            "authenticated_touch": "pass",
            "durable_security_state": "not_claimed_interop_uses_test_isolated_store",
        },
        "raw_markers": {
            "host_sha256": sha256_bytes(host_marker.encode()),
            "device_sha256": sha256_bytes(device_marker.encode()),
        },
        "commands": [asdict(record) for record in records],
        "evidence_boundaries": {
            "ui": "not_claimed",
            "screen_capture_kit": "not_claimed",
            "real_display_content": "not_claimed",
            "rotation": "open_harness_has_no_rotation_assertion",
            "disconnect_reconnect": "not_claimed",
            "revocation_repair": "not_claimed",
            "soak": "not_claimed",
        },
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("direct", "relay"), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--adb-endpoint", required=True)
    parser.add_argument("--device-lock", type=Path, action="append", default=[])
    parser.add_argument("--signaling-bind-address", required=True,
                        help="explicit host bind address; prefer 127.0.0.1 with adb reverse")
    parser.add_argument("--signaling-port", type=int, default=8088)
    parser.add_argument("--android-signaling-port", type=int, default=18088)
    parser.add_argument("--ice-config-file", type=Path, required=True,
                        help="0600 JSON containing explicit reachable STUN/TURN URLs and TURN credential")
    parser.add_argument("--coturn-log", type=Path, required=True,
                        help="caller-managed local coturn raw log retained and privacy-redacted")
    parser.add_argument("--coturn-version-file", type=Path, required=True,
                        help="caller-captured coturn version output")
    parser.add_argument("--raw-output-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=150)
    parser.add_argument("--install-timeout", type=float, default=180)
    parser.add_argument("--build-timeout", type=float, default=1800)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (1 <= args.signaling_port <= 65535 and 1 <= args.android_signaling_port <= 65535):
        print("error: signaling ports must be between 1 and 65535", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.install_timeout <= 0 or args.build_timeout <= 0:
        print("error: timeouts must be positive", file=sys.stderr)
        return 2
    try:
        report = run(args)
        write_private(args.evidence, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    except (InteropError, OSError) as error:
        message = redact(str(error), (args.adb_endpoint, args.signaling_bind_address,
                                      str(args.ice_config_file)))
        write_private(args.evidence, (json.dumps({
            "schema": "dev.vibescreen.phase3-android-product-interop/v1",
            "result": "fail",
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": message,
        }, indent=2, sort_keys=True) + "\n").encode())
        print(f"error: {message}", file=sys.stderr)
        return 1
    print(f"PASS: {args.route} evidence written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
