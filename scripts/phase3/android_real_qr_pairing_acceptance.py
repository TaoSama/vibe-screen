#!/usr/bin/env python3
"""Fail-closed real-camera QR pairing acceptance runner.

Drives real rear-camera CameraX ImageAnalysis + ZXing decode on Android,
pairing request presentation, in-memory host authority acceptance,
verified pairing, strict lease import, and UI revocation, all within
a no-Host harness (no MacHost server, no adb reverse).

Presents the pairing offer QR code via an AppKit/CoreImage window on macOS
(qr_presenter.swift) without requiring macOS TCC permissions.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

SCHEMA = "dev.vibescreen.phase3-real-qr-pairing/v1"
BLOCKED_SCHEMA = "dev.vibescreen.phase3-real-qr-pairing-blocked/v1"
MARKER_SCHEMA = "dev.vibescreen.phase3-real-qr-scan-marker/v1"
PRESENTER_READY_SCHEMA = "dev.vibescreen.phase3-real-qr-presenter-ready/v1"

DEFAULT_APP_PACKAGE = "dev.telemachus.display"
DEFAULT_TEST_PACKAGE = "dev.telemachus.display.test"
DEFAULT_TEST_RUNNER = f"{DEFAULT_TEST_PACKAGE}/androidx.test.runner.AndroidJUnitRunner"
DEFAULT_TEST_CLASS = f"{DEFAULT_APP_PACKAGE}.RealQrInternetPairingInstrumentedTest"
REAL_QR_OPT_IN_ARGUMENT = "vibeScreenRealQrAcceptance"

OFFER_FILENAME = "internet_pairing_offer.txt"
MARKER_FILENAME = "qr_scan_marker.json"
DEFAULT_PRESENTER_READY_FILENAME = "qr_scan_marker_request.txt"

DEVICE_LOCK_PATH = Path("/tmp/vibe-screen-device-android.lock")
HOST_PORT = 54321

EXPECTED_PASS_MARKER = (
    "PHASE3_REAL_QR_PAIRING_PASS real_camerax_zxing=true in_memory_authority=true "
    "pairing=true strict_lease_import=true local_revoke=true secure_dialogs=true"
)

EVIDENCE_BOUNDARIES = {
    "camera_input": "real_camerax_imageanalysis_rear_camera",
    "qr_decoder": "real_zxing_qrcodereader",
    "host_server": "no_host_server_in_memory_authority_only",
    "adb_reverse": "not_used",
    "transport_mode": "no_host_harness",
}

USER_PATH_PATTERN = re.compile(
    r'(?:/Users/[^\s<>\x22\x27]+|/home/[^\s<>\x22\x27]+|/Volumes/[^\s<>\x22\x27]+)',
    re.IGNORECASE,
)
IPV4_PATTERN = re.compile(
    r'(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?![0-9.])'
)
PAIRING_URL_PATTERN = re.compile(
    r'vibescreen://[^\s<>\x22\x27]+',
    re.IGNORECASE,
)


class AcceptanceError(RuntimeError):
    """Raised when real QR pairing acceptance fails or cannot be proved."""


@dataclass(frozen=True)
class DeviceIdentity:
    manufacturer: str
    model: str
    device: str
    android_release: str
    sdk: int


class AcceptanceContext:
    def __init__(self) -> None:
        self.started_at_utc: str = datetime.now(timezone.utc).isoformat()
        self.device_identity: DeviceIdentity | None = None


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def redact_text(text: str, serial: str | None = None) -> str:
    redacted = text
    if serial:
        redacted = redacted.replace(serial, "<ANDROID_SERIAL>")
    redacted = USER_PATH_PATTERN.sub("<path>", redacted)
    redacted = IPV4_PATTERN.sub("<ipv4>", redacted)
    redacted = PAIRING_URL_PATTERN.sub("<URL>", redacted)
    return redacted


def sanitize_and_summarize_log(raw_log: str, serial: str | None = None, max_chars: int = 500) -> tuple[str, str]:
    """Returns a (sha256_hash, truncated_redacted_summary) tuple for safe error reporting."""
    log_sha = sha256_hex(raw_log)
    redacted = redact_text(raw_log, serial)
    lines = [line.strip() for line in redacted.splitlines() if line.strip()]
    tail = "\n".join(lines[-10:])
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
    return log_sha, tail or "<empty>"


def write_atomic_0600(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(
            str(temp_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_path), str(path))
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


class DeviceLock:
    """Coordinates safe exclusive access to /tmp/vibe-screen-device-android.lock."""

    def __init__(self, lock_path: Path = DEVICE_LOCK_PATH, serial: str = "") -> None:
        self.lock_path = lock_path
        self.serial = serial
        self.acquired = False

    def __enter__(self) -> DeviceLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        owner_data = {
            "task": "android_real_qr_pairing_acceptance",
            "pid": os.getpid(),
            "serial": self.serial,
            "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        payload = json.dumps(owner_data, indent=2, sort_keys=True) + "\n"
        try:
            fd = os.open(
                str(self.lock_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as error:
            raise AcceptanceError(
                f"Device coordination lock already exists at {self.lock_path}; another task or test may be using the device"
            ) from error
        except OSError as error:
            raise AcceptanceError(
                f"Failed to acquire device coordination lock at {self.lock_path}: {error}"
            ) from error

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            self.acquired = True
        except Exception:
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        finally:
            self.acquired = False


def check_no_host_server(
    port: int = HOST_PORT,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> bool:
    """Verifies that no MacHost server is running on target port via dual socket probes and lsof.

    Only explicit ECONNREFUSED is treated as 'no server listening'.
    Any successful connection, timeout, or unexpected error fails closed.
    """
    # 1. Dual socket probes (IPv4 + IPv6)
    # IPv4 probe
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            try:
                s.connect(("127.0.0.1", port))
                return False  # Active IPv4 listener detected!
            except ConnectionRefusedError:
                pass  # Explicit ECONNREFUSED
            except OSError as err:
                if err.errno == errno.ECONNREFUSED:
                    pass
                else:
                    return False  # Timeout / EPERM / other error -> fail closed
    except Exception:
        return False

    # IPv6 probe
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            try:
                s.connect(("::1", port))
                return False  # Active IPv6 listener detected!
            except ConnectionRefusedError:
                pass  # Explicit ECONNREFUSED
            except OSError as err:
                if err.errno == errno.ECONNREFUSED:
                    pass
                elif err.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                    pass  # IPv6 loopback not configured on host machine
                else:
                    return False  # Timeout / other error -> fail closed
    except OSError as err:
        if err.errno not in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
            return False
    except Exception:
        return False

    # 2. lsof check
    runner = command_runner or subprocess.run
    try:
        proc = runner(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        if proc.returncode == 0:
            return False
        if proc.returncode != 1:
            return False
    except Exception:
        return False

    return True


def require_serial(serial: str | None) -> str:
    """Ensures a non-empty ADB device serial is provided."""
    if not serial or not serial.strip():
        raise AcceptanceError("ADB device serial is required and cannot be empty")
    return serial.strip()


def check_device_state(
    serial: str,
    adb_path: str = "adb",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Verifies that adb get-state returns 'device'."""
    clean_serial = require_serial(serial)
    cmd = [adb_path, "-s", clean_serial, "get-state"]
    try:
        proc = command_runner(cmd, capture_output=True, text=True, check=False, timeout=10.0)
    except Exception as error:
        raise AcceptanceError(f"Failed to query ADB device state: {error}") from error

    if proc.returncode != 0:
        raise AcceptanceError(
            f"ADB device {clean_serial} get-state failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    state = proc.stdout.strip()
    if state != "device":
        raise AcceptanceError(
            f"ADB device {clean_serial} state is not 'device' (got '{state}')"
        )


def check_no_adb_reverse(
    serial: str,
    adb_path: str = "adb",
    port: int = HOST_PORT,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Verifies that no adb reverse mapping exists for target port. Fail-closed on error."""
    clean_serial = require_serial(serial)
    cmd = [adb_path, "-s", clean_serial, "reverse", "--list"]
    try:
        proc = command_runner(cmd, capture_output=True, text=True, check=False, timeout=10.0)
        if proc.returncode != 0:
            raise AcceptanceError(
                f"adb reverse --list failed with exit code {proc.returncode}: {proc.stderr.strip()}"
            )
        return str(port) not in proc.stdout
    except AcceptanceError:
        raise
    except Exception as error:
        raise AcceptanceError(f"Failed to check ADB reverse mappings: {error}") from error


def get_device_identity(
    serial: str,
    adb_path: str = "adb",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DeviceIdentity:
    """Reads and validates device identity via getprop. Fails closed if empty or invalid."""
    clean_serial = require_serial(serial)
    check_device_state(clean_serial, adb_path, command_runner)

    def getprop(name: str) -> str:
        cmd = [adb_path, "-s", clean_serial, "shell", "getprop", name]
        try:
            res = command_runner(cmd, capture_output=True, text=True, check=False, timeout=10.0)
            if res.returncode != 0:
                raise AcceptanceError(f"getprop {name} failed (exit {res.returncode}): {res.stderr.strip()}")
            return res.stdout.strip()
        except AcceptanceError:
            raise
        except Exception as error:
            raise AcceptanceError(f"Failed to query device property {name}: {error}") from error

    manufacturer = getprop("ro.product.manufacturer")
    model = getprop("ro.product.model")
    device = getprop("ro.product.device")
    android_release = getprop("ro.build.version.release")
    sdk_raw = getprop("ro.build.version.sdk")

    if not manufacturer:
        raise AcceptanceError("Device manufacturer property (ro.product.manufacturer) is empty")
    if not model:
        raise AcceptanceError("Device model property (ro.product.model) is empty")
    if not device:
        raise AcceptanceError("Device property (ro.product.device) is empty")
    if not android_release:
        raise AcceptanceError("Device Android release property (ro.build.version.release) is empty")
    if not sdk_raw.isdigit() or int(sdk_raw) <= 0:
        raise AcceptanceError(f"Device SDK version (ro.build.version.sdk) must be a positive integer: got '{sdk_raw}'")

    return DeviceIdentity(
        manufacturer=manufacturer,
        model=model,
        device=device,
        android_release=android_release,
        sdk=int(sdk_raw),
    )


def run_as_read_file(
    package: str,
    filename: str,
    serial: str,
    adb_path: str = "adb",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    """Reads an app-private file with run-as without device-shell quoting."""
    clean_serial = require_serial(serial)
    validate_app_private_filename(filename)
    path = f"files/{filename}"
    exists_cmd = [adb_path, "-s", clean_serial, "shell", "run-as", package, "ls", path]
    read_cmd = [adb_path, "-s", clean_serial, "shell", "run-as", package, "cat", path]
    try:
        exists = command_runner(exists_cmd, capture_output=True, text=True, check=False, timeout=10.0)
        if exists.returncode == 1 and "No such file or directory" in exists.stderr:
            return None
        if exists.returncode != 0:
            raise AcceptanceError(
                f"Failed to inspect app-private file {filename} (exit {exists.returncode}): {exists.stderr.strip()}"
            )
        proc = command_runner(read_cmd, capture_output=True, text=True, check=False, timeout=10.0)
        if proc.returncode != 0:
            raise AcceptanceError(
                f"Failed to read app-private file {filename} (exit {proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout.strip()
    except AcceptanceError:
        raise
    except Exception as error:
        raise AcceptanceError(f"Failed to read app-private file {filename}: {error}") from error


def run_as_write_file(
    package: str,
    filename: str,
    content: str,
    serial: str,
    adb_path: str = "adb",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Writes an app-private file via adb shell run-as with 0600 mode."""
    clean_serial = require_serial(serial)
    validate_app_private_filename(filename)
    path = f"files/{filename}"
    write_cmd = [adb_path, "-s", clean_serial, "shell", "run-as", package, "tee", path]
    chmod_cmd = [adb_path, "-s", clean_serial, "exec-out", "run-as", package, "chmod", "600", path]
    try:
        written = command_runner(write_cmd, input=content, capture_output=True, text=True, check=False, timeout=10.0)
        if written.returncode != 0:
            raise AcceptanceError(
                f"Failed to write app-private file {filename} (exit {written.returncode}): {written.stderr.strip()}"
            )
        chmod = command_runner(chmod_cmd, capture_output=True, text=True, check=False, timeout=10.0)
        if chmod.returncode != 0:
            raise AcceptanceError(
                f"Failed to protect app-private file {filename} (exit {chmod.returncode}): {chmod.stderr.strip()}"
            )
    except AcceptanceError:
        raise
    except Exception as error:
        raise AcceptanceError(f"Failed to write app-private file {filename}: {error}") from error


def run_as_delete_file(
    package: str,
    filename: str,
    serial: str | None,
    adb_path: str = "adb",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Deletes an app-private file via adb exec-out run-as."""
    clean_serial = require_serial(serial)
    validate_app_private_filename(filename)
    cmd = [adb_path, "-s", clean_serial, "exec-out", "run-as", package, "rm", "-f", f"files/{filename}"]
    try:
        proc = command_runner(cmd, capture_output=True, text=True, check=False, timeout=10.0)
        if proc.returncode != 0:
            raise AcceptanceError(
                f"Failed to delete app-private file {filename} (exit {proc.returncode}): {proc.stderr.strip()}"
            )
    except AcceptanceError:
        raise
    except Exception as error:
        raise AcceptanceError(f"Failed to delete app-private file {filename}: {error}") from error


def validate_app_private_filename(filename: str) -> None:
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", filename):
        raise AcceptanceError(f"Unsafe app-private filename: {filename!r}")


def attach_exception_note(error: BaseException, note: str) -> None:
    """Preserves teardown diagnostics on Python versions before add_note()."""
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(note)
        return
    message = str(error)
    error.args = (f"{message}\n{note}", *error.args[1:])


class PresenterController:
    """Controls the Swift QR code presenter window process."""

    def __init__(
        self,
        script_path: Path,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        startup_timeout: float = 15.0,
    ) -> None:
        self.script_path = script_path
        self.popen_factory = popen_factory
        self.startup_timeout = startup_timeout
        self.proc: Any | None = None

    def start(
        self,
        payload: str,
        timeout_seconds: float = 60.0,
        scale: float = 16.0,
    ) -> None:
        config = {
            "payload": payload,
            "timeout_seconds": timeout_seconds,
            "scale": scale,
        }
        # Swift presenter accepts strictly no CLI arguments. All config is passed via stdin JSON.
        cmd = ["swift", str(self.script_path)]
        self.proc = self.popen_factory(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if self.proc.stdin is not None:
            try:
                self.proc.stdin.write(json.dumps(config) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

        self._wait_ready()

    def _wait_ready(self) -> None:
        if self.proc is None:
            raise AcceptanceError("Presenter process was not started")

        ready_event = threading.Event()
        ready_lines: list[str] = []
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            try:
                if self.proc and self.proc.stdout:
                    while True:
                        line = self.proc.stdout.readline()
                        if not line:
                            break
                        ready_lines.append(line)
                        if "QR_PRESENTER_READY" in line:
                            break
            except Exception:
                pass
            finally:
                ready_event.set()

        def read_stderr() -> None:
            try:
                if self.proc and self.proc.stderr:
                    err = self.proc.stderr.read()
                    if err:
                        stderr_lines.append(err)
            except Exception:
                pass

        t_out = threading.Thread(target=read_stdout, daemon=True)
        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        ready_event.wait(timeout=self.startup_timeout)

        # 1. Check if process terminated prematurely
        if self.proc.poll() is not None:
            t_err.join(timeout=1.0)
            err_msg = "".join(stderr_lines).strip()
            ret = self.proc.returncode
            self.stop()
            raise AcceptanceError(
                f"Presenter process crashed or exited prematurely (code {ret}): {err_msg or 'no stderr'}"
            )

        # 2. Check if ready marker was received
        has_ready = any("QR_PRESENTER_READY" in line for line in ready_lines)
        if not has_ready:
            t_err.join(timeout=1.0)
            err_msg = "".join(stderr_lines).strip()
            self.stop()
            raise AcceptanceError(
                f"Presenter failed to signal QR_PRESENTER_READY within {self.startup_timeout}s: {err_msg or 'no output'}"
            )

    def stop(self) -> None:
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3.0)
            except Exception:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=1.0)
                except Exception:
                    pass
            finally:
                self.proc = None


def validate_qr_marker(
    marker_raw: str,
    expected_payload_sha256: str,
) -> dict[str, Any]:
    """Validates the QR scan marker recorded by CameraX ImageAnalysis + ZXing."""
    try:
        data = json.loads(marker_raw)
    except Exception as error:
        first_codepoint = ord(marker_raw[0]) if marker_raw else None
        raise AcceptanceError(
            "QR scan marker is invalid JSON "
            f"(bytes={len(marker_raw.encode('utf-8'))}, sha256={sha256_hex(marker_raw)}, "
            f"first_codepoint={first_codepoint}, starts_object={marker_raw.startswith('{')}): {error}"
        ) from error

    if data.get("schema") != MARKER_SCHEMA:
        raise AcceptanceError(f"Unexpected QR scan marker schema: {data.get('schema')}")
    if data.get("source") != "CameraX ImageAnalysis":
        raise AcceptanceError(f"Unexpected QR scan source: {data.get('source')}")
    if data.get("decoder") != "ZXing QRCodeReader":
        raise AcceptanceError(f"Unexpected QR scan decoder: {data.get('decoder')}")

    marker_sha256 = data.get("payload_sha256")
    if marker_sha256 != expected_payload_sha256:
        raise AcceptanceError(
            f"QR scan payload SHA256 mismatch: expected {expected_payload_sha256}, got {marker_sha256}"
        )

    for field in ("frame_width", "frame_height", "luma_width", "luma_height"):
        val = data.get(field)
        if not isinstance(val, int) or val <= 0:
            raise AcceptanceError(f"QR scan marker {field} must be positive integer: {val}")

    return data


def run_acceptance(
    args: argparse.Namespace,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    context: AcceptanceContext | None = None,
) -> dict[str, Any]:
    started_at = context.started_at_utc if context else datetime.now(timezone.utc).isoformat()
    serial = require_serial(getattr(args, "serial", None))

    validate_app_private_filename(args.offer_file)
    validate_app_private_filename(args.marker_file)
    validate_app_private_filename(args.presenter_ready_file)

    # Safe exclusive lock coordination
    lock_path = getattr(args, "device_lock", DEVICE_LOCK_PATH)
    device_lock = DeviceLock(lock_path=lock_path, serial=serial)
    device_lock.acquire()

    try:
        presenter_script = Path(args.presenter_script).resolve()
        if not args.skip_presenter and not presenter_script.is_file():
            raise AcceptanceError(f"Presenter script not found: {presenter_script}")
        presenter = PresenterController(presenter_script, popen_factory)
    except Exception:
        device_lock.release()
        raise
    instrumentation_proc: Any | None = None
    offer_sha256: str | None = None
    marker_data: dict[str, Any] | None = None
    postflight_errors: list[str] = []
    log_path: Path | None = None

    try:
        # Step 1: Prechecks
        if not check_no_host_server(port=HOST_PORT, command_runner=command_runner):
            raise AcceptanceError(f"Host server is running on port {HOST_PORT}; acceptance requires no-Host harness")
        if not check_no_adb_reverse(serial, args.adb, port=HOST_PORT, command_runner=command_runner):
            raise AcceptanceError(f"ADB reverse is configured for port {HOST_PORT}; acceptance requires no-Host harness")

        device_identity = get_device_identity(serial, args.adb, command_runner)
        if context is not None:
            context.device_identity = device_identity

        # Clean existing app-private files
        run_as_delete_file(args.package, args.offer_file, serial, args.adb, command_runner)
        run_as_delete_file(args.package, args.marker_file, serial, args.adb, command_runner)
        run_as_delete_file(args.package, args.presenter_ready_file, serial, args.adb, command_runner)

        # Create 0600 temp file for instrumentation stdout redirection to prevent pipe deadlock
        fd, temp_name = tempfile.mkstemp(prefix="instrumentation_stdout_", suffix=".log")
        os.close(fd)
        log_path = Path(temp_name)
        os.chmod(log_path, 0o600)

        instrumentation_cmd = [
            args.adb,
            "-s",
            serial,
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            args.test_class,
            "-e",
            REAL_QR_OPT_IN_ARGUMENT,
            "true",
            args.test_runner,
        ]

        deadline = time.monotonic() + args.timeout
        with open(log_path, "w+", encoding="utf-8", errors="replace") as log_file:
            instrumentation_proc = popen_factory(
                instrumentation_cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

            def read_inst_log() -> str:
                try:
                    log_file.flush()
                except Exception:
                    pass
                if log_path.exists():
                    return log_path.read_text(encoding="utf-8", errors="replace")
                if instrumentation_proc.poll() is not None and hasattr(instrumentation_proc, "stdout") and instrumentation_proc.stdout:
                    if hasattr(instrumentation_proc.stdout, "read"):
                        return instrumentation_proc.stdout.read() or ""
                if instrumentation_proc.poll() is not None and hasattr(instrumentation_proc, "communicate"):
                    out, _ = instrumentation_proc.communicate()
                    return out or ""
                return ""

            # Step 2: Poll for offer file
            raw_offer: str | None = None
            while time.monotonic() < deadline and instrumentation_proc.poll() is None:
                raw_offer = run_as_read_file(args.package, args.offer_file, serial, args.adb, command_runner)
                if raw_offer:
                    break
                time.sleep(args.poll_interval)

            if not raw_offer:
                if instrumentation_proc.poll() is not None:
                    raw_log = read_inst_log()
                    log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                    raise AcceptanceError(
                        f"Instrumentation terminated before producing offer (exit {instrumentation_proc.returncode}, log_sha256={log_sha}): {summary}"
                    )
                raise AcceptanceError(f"Timed out waiting for {args.offer_file}")

            offer_sha256 = sha256_hex(raw_offer)

            # Step 3: Present QR code
            if not args.skip_presenter:
                presenter.start(
                    raw_offer,
                    timeout_seconds=max(30.0, deadline - time.monotonic()),
                )

            # Step 3.5: Write presenter-ready sentinel into app-private storage before camera scan
            sentinel_content = json.dumps({
                "schema": PRESENTER_READY_SCHEMA,
                "ready": True,
                "payload_sha256": offer_sha256,
                "marker_file": args.marker_file,
                "written_at_utc": datetime.now(timezone.utc).isoformat(),
            })
            run_as_write_file(args.package, args.presenter_ready_file, sentinel_content, serial, args.adb, command_runner)

            # Step 4: Poll for marker file
            raw_marker: str | None = None
            while time.monotonic() < deadline and instrumentation_proc.poll() is None:
                raw_marker = run_as_read_file(args.package, args.marker_file, serial, args.adb, command_runner)
                if raw_marker:
                    break
                time.sleep(args.poll_interval)

            if not raw_marker:
                if instrumentation_proc.poll() is not None:
                    raw_log = read_inst_log()
                    log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                    raise AcceptanceError(
                        f"Instrumentation terminated before CameraX QR decode (exit {instrumentation_proc.returncode}, log_sha256={log_sha}): {summary}"
                    )
                raw_log = read_inst_log()
                log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                raise AcceptanceError(
                    f"Timed out waiting for CameraX QR decode marker ({args.marker_file}, "
                    f"log_sha256={log_sha}): {summary}"
                )

            marker_data = validate_qr_marker(raw_marker, offer_sha256)

            # CameraX and ZXing decoded successfully! Presenter is no longer needed.
            presenter.stop()

            # Step 5: Await instrumentation completion
            remaining = max(1.0, deadline - time.monotonic())
            try:
                if hasattr(instrumentation_proc, "wait"):
                    instrumentation_proc.wait(timeout=remaining)
                elif hasattr(instrumentation_proc, "communicate"):
                    instrumentation_proc.communicate(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                instrumentation_proc.kill()
                raw_log = read_inst_log()
                log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                raise AcceptanceError(f"Instrumentation timed out (log_sha256={log_sha}): {summary}") from error

            raw_log = read_inst_log()
            if instrumentation_proc.returncode != 0:
                log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                raise AcceptanceError(
                    f"Instrumentation failed with exit code {instrumentation_proc.returncode} (log_sha256={log_sha}): {summary}"
                )

            if EXPECTED_PASS_MARKER not in raw_log:
                log_sha, summary = sanitize_and_summarize_log(raw_log, serial)
                raise AcceptanceError(
                    f"Instrumentation missing required pass marker line (log_sha256={log_sha}): {summary}"
                )

    finally:
        in_flight_exc = sys.exc_info()[1]
        cleanup_errors: list[Exception] = []

        # Teardown: Stop presenter
        try:
            presenter.stop()
        except Exception as err:
            cleanup_errors.append(err)

        # Kill local instrumentation process if still alive
        if instrumentation_proc is not None and instrumentation_proc.poll() is None:
            try:
                instrumentation_proc.kill()
                if hasattr(instrumentation_proc, "wait"):
                    instrumentation_proc.wait(timeout=2.0)
            except Exception as err:
                cleanup_errors.append(err)

        # Force-stop test package and app package on device
        try:
            command_runner([args.adb, "-s", serial, "shell", "am", "force-stop", args.test_package], capture_output=True, text=True, check=False, timeout=10.0)
        except Exception as err:
            cleanup_errors.append(err)
        try:
            command_runner([args.adb, "-s", serial, "shell", "am", "force-stop", args.package], capture_output=True, text=True, check=False, timeout=10.0)
        except Exception as err:
            cleanup_errors.append(err)

        # Clean device files
        for f in (args.offer_file, args.marker_file, args.presenter_ready_file):
            try:
                run_as_delete_file(args.package, f, serial, args.adb, command_runner)
            except Exception as err:
                cleanup_errors.append(err)

        # Clean local temp log file
        if log_path is not None and log_path.exists():
            try:
                log_path.unlink()
            except OSError as err:
                cleanup_errors.append(err)

        # Postflight checks
        try:
            if not check_no_adb_reverse(serial, args.adb, port=HOST_PORT, command_runner=command_runner):
                postflight_errors.append(f"Postflight detected ADB reverse on port {HOST_PORT}")
        except Exception as error:
            postflight_errors.append(f"Postflight ADB reverse check failed: {error}")

        try:
            if not check_no_host_server(port=HOST_PORT, command_runner=command_runner):
                postflight_errors.append(f"Postflight detected Host server on port {HOST_PORT}")
        except Exception as error:
            postflight_errors.append(f"Postflight host server check failed: {error}")

        # Safe release of device coordination lock
        try:
            device_lock.release()
        except Exception as err:
            cleanup_errors.append(err)

        if in_flight_exc is not None:
            for err in cleanup_errors:
                attach_exception_note(in_flight_exc, f"Teardown cleanup error: {err}")
            for err_msg in postflight_errors:
                attach_exception_note(in_flight_exc, f"Teardown postflight error: {err_msg}")
        else:
            if cleanup_errors:
                raise AcceptanceError(f"Teardown cleanup failed: {'; '.join(str(e) for e in cleanup_errors)}")
            if postflight_errors:
                raise AcceptanceError("; ".join(postflight_errors))

    # Explicit evidence that device files were removed
    offer_remaining = run_as_read_file(args.package, args.offer_file, serial, args.adb, command_runner)
    marker_remaining = run_as_read_file(args.package, args.marker_file, serial, args.adb, command_runner)
    sentinel_remaining = run_as_read_file(args.package, args.presenter_ready_file, serial, args.adb, command_runner)
    if offer_remaining or marker_remaining or sentinel_remaining:
        raise AcceptanceError("Device files were not cleanly removed after acceptance run")

    finished_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema": SCHEMA,
        "result": "pass",
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "device": asdict(device_identity),
        "assertions": {
            "real_camerax_zxing": "pass",
            "in_memory_authority": "pass",
            "pairing": "pass",
            "strict_lease_import": "pass",
            "local_revoke": "pass",
            "secure_dialogs": "pass",
            "no_host_server": "pass",
            "no_adb_reverse": "pass",
            "device_file_cleanup": "pass",
        },
        "marker": marker_data,
        "evidence_boundaries": dict(EVIDENCE_BOUNDARIES),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--serial",
        "-s",
        type=str,
        required=True,
        help="ADB device serial (required; fail-closed).",
    )
    parser.add_argument(
        "--adb",
        type=str,
        default="adb",
        help="Path to adb executable (default: adb).",
    )
    parser.add_argument(
        "--package",
        type=str,
        default=DEFAULT_APP_PACKAGE,
        help=f"Target Android application package (default: {DEFAULT_APP_PACKAGE}).",
    )
    parser.add_argument(
        "--test-package",
        type=str,
        default=DEFAULT_TEST_PACKAGE,
        help=f"Android test package (default: {DEFAULT_TEST_PACKAGE}).",
    )
    parser.add_argument(
        "--test-runner",
        type=str,
        default=DEFAULT_TEST_RUNNER,
        help=f"Android test runner component (default: {DEFAULT_TEST_RUNNER}).",
    )
    parser.add_argument(
        "--test-class",
        type=str,
        default=DEFAULT_TEST_CLASS,
        help=f"Instrumentation test class (default: {DEFAULT_TEST_CLASS}).",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Output path for the JSON evidence report (0600 file).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Overall acceptance timeout in seconds (default: 120.0).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Device file polling interval in seconds (default: 0.5).",
    )
    parser.set_defaults(
        offer_file=OFFER_FILENAME,
        marker_file=MARKER_FILENAME,
        presenter_ready_file=DEFAULT_PRESENTER_READY_FILENAME,
    )
    parser.add_argument(
        "--device-lock",
        type=Path,
        default=DEVICE_LOCK_PATH,
        help=f"Path to device coordination lock (default: {DEVICE_LOCK_PATH}).",
    )
    parser.add_argument(
        "--presenter-script",
        type=Path,
        default=Path(__file__).parent / "qr_presenter.swift",
        help="Path to the Swift QR presenter script.",
    )
    parser.add_argument(
        "--skip-presenter",
        action="store_true",
        help="Skip launching the AppKit QR presenter window.",
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Exit 0 and write a failed/blocked report if acceptance cannot complete.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> int:
    context = AcceptanceContext()
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as err:
        return err.code if isinstance(err.code, int) else 1

    evidence_path = args.evidence.resolve()

    try:
        report = run_acceptance(
            args,
            command_runner=command_runner,
            popen_factory=popen_factory,
            context=context,
        )
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        write_atomic_0600(evidence_path, encoded.encode("utf-8"))
        print(f"PASS: Real QR pairing acceptance evidence written to {evidence_path}")
        return 0
    except (AcceptanceError, Exception) as error:
        safe_error = redact_text(str(error), getattr(args, "serial", None))
        is_blocked = bool(args.allow_blocked)
        failure_report: dict[str, Any] = {
            "schema": BLOCKED_SCHEMA if is_blocked else SCHEMA,
            "result": "blocked" if is_blocked else "fail",
            "timing_utc": {
                "started": context.started_at_utc,
                "finished": datetime.now(timezone.utc).isoformat(),
            },
            "blocker" if is_blocked else "error": safe_error,
            "evidence_boundaries": dict(EVIDENCE_BOUNDARIES),
        }
        if context.device_identity is not None:
            failure_report["device"] = asdict(context.device_identity)

        encoded = json.dumps(failure_report, indent=2, sort_keys=True) + "\n"
        write_atomic_0600(evidence_path, encoded.encode("utf-8"))
        print(f"FAIL: Real QR pairing acceptance: {safe_error}", file=sys.stderr)
        return 0 if args.allow_blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
