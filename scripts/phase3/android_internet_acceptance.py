#!/usr/bin/env python3
"""Run fail-closed Android Internet transport acceptance over ADB TCP.

The script installs and launches a caller-selected APK, requires observable
streaming and reconnect evidence, injects a swipe as input, restarts the app to
force a disconnect/reconnect, then performs a bounded process-alive soak. It
never treats installation or process liveness alone as streaming proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


MANDATORY_DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
INTERNET_LEASE_LOCK = Path("/tmp/vibe-screen-device-internet.lock")
MAX_HOST_INPUT_EVIDENCE_BYTES = 1024 * 1024


class AcceptanceError(RuntimeError):
    """Raised when a required device observation cannot be proved."""


@dataclass
class CommandRecord:
    argv: list[str]
    returncode: int
    stdout_sha256: str
    stdout_bytes: int
    stderr_sha256: str
    stderr_bytes: int
    elapsed_seconds: float


@dataclass(frozen=True)
class HostEvidenceCursor:
    device: int
    inode: int
    offset: int


class Adb:
    def __init__(
        self,
        executable: str,
        serial: str,
        records: list[CommandRecord],
        device_locks: Sequence[Path],
        internet_lease_lock: Path,
        lease_token: str,
    ) -> None:
        self.executable = executable
        self.serial = serial
        self.records = records
        self.device_locks = tuple(device_locks)
        self.internet_lease_lock = internet_lease_lock
        self._lease_token = lease_token

    def host(self, arguments: Sequence[str], timeout: float = 30) -> str:
        return self._run([self.executable, *arguments], timeout)

    def device(self, arguments: Sequence[str], timeout: float = 30) -> str:
        return self._run([self.executable, "-s", self.serial, *arguments], timeout)

    def _run(self, command: list[str], timeout: float) -> str:
        _require_device_lease_authorized(
            self.device_locks,
            self.internet_lease_lock,
            self._lease_token,
        )
        started = time.monotonic()
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise AcceptanceError(f"ADB command timed out after {timeout:g} seconds") from error
        except OSError as error:
            raise AcceptanceError(f"cannot run ADB executable: {error.strerror or type(error).__name__}") from error
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        recorded_command = [self._redact_argument(argument) for argument in command]
        record = CommandRecord(
            recorded_command,
            result.returncode,
            _sha256_text(stdout),
            len(stdout.encode("utf-8")),
            _sha256_text(stderr),
            len(stderr.encode("utf-8")),
            time.monotonic() - started,
        )
        self.records.append(record)
        if result.returncode != 0:
            raise AcceptanceError(
                f"ADB command failed ({result.returncode}): {' '.join(recorded_command)}; "
                f"stdout_sha256={record.stdout_sha256}, stderr_sha256={record.stderr_sha256}"
            )
        return stdout.strip()

    def _redact_argument(self, argument: str) -> str:
        redacted = argument
        for sensitive_value, replacement in (
            (self._lease_token, "<redacted>"),
            (self.serial, "<device-endpoint>"),
        ):
            if sensitive_value:
                redacted = redacted.replace(sensitive_value, replacement)
        if Path(redacted).is_absolute():
            return "<local-path>"
        return redacted


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coordination_locks(additional_locks: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys((*MANDATORY_DEVICE_LOCKS, *additional_locks)))


def _require_device_lease_authorized(
    unavailable_locks: Sequence[Path],
    internet_lease_lock: Path,
    lease_token: str,
) -> None:
    if not lease_token:
        raise AcceptanceError("Internet device lease token cannot be empty")
    for device_lock in unavailable_locks:
        try:
            device_lock.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise AcceptanceError(
                f"cannot verify that device lease lock is absent at {device_lock}: {error}; "
                "do not run ADB until every coordination lock can be verified"
            ) from error
        raise AcceptanceError(
            f"device lease lock exists at {device_lock}; no ADB command was run. "
            "Wait for the lease owner to finish and remove the lock before retrying"
        )
    try:
        owner = internet_lease_lock.read_bytes()
    except FileNotFoundError as error:
        raise AcceptanceError(
            f"required Internet device lease is missing at {internet_lease_lock}; obtain the lease before running ADB"
        ) from error
    except OSError as error:
        raise AcceptanceError(f"cannot verify Internet device lease at {internet_lease_lock}: {error}") from error
    if owner != lease_token.encode("utf-8"):
        raise AcceptanceError(
            f"Internet device lease owner does not match at {internet_lease_lock}; no ADB command was run"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AcceptanceError(f"cannot hash APK {path}: {error}") from error
    return digest.hexdigest()


def _property(adb: Adb, name: str) -> str:
    value = adb.device(["shell", "getprop", name])
    if not value:
        raise AcceptanceError(f"device property {name} is empty")
    return value


def _device_identity(adb: Adb) -> dict[str, str]:
    return {
        "manufacturer": _property(adb, "ro.product.manufacturer"),
        "model": _property(adb, "ro.product.model"),
        "device": _property(adb, "ro.product.device"),
        "os_release": _property(adb, "ro.build.version.release"),
        "api_level": _property(adb, "ro.build.version.sdk"),
    }


def _observe(adb: Adb, package: str) -> str:
    logcat = adb.device(["logcat", "-d", "-v", "threadtime"], timeout=60)
    window = adb.device(["shell", "dumpsys", "window", "windows"])
    package_state = adb.device(["shell", "dumpsys", "package", package], timeout=60)
    return "\n".join((logcat, window, package_state))


def _require_pattern(label: str, pattern: str, observation: str) -> None:
    try:
        matched = re.search(pattern, observation, re.IGNORECASE | re.MULTILINE)
    except re.error as error:
        raise AcceptanceError(f"invalid {label} regex: {error}") from error
    if matched is None:
        raise AcceptanceError(f"missing required {label} evidence")


def _extract_session_epoch(label: str, pattern: str, observation: str) -> int:
    try:
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as error:
        raise AcceptanceError(f"invalid {label} session epoch regex: {error}") from error
    if "epoch" not in compiled.groupindex:
        raise AcceptanceError("session epoch regex must define a named group '(?P<epoch>...)'")
    match = compiled.search(observation)
    if match is None:
        raise AcceptanceError(f"missing required {label} session epoch evidence")
    try:
        epoch = int(match.group("epoch"))
    except (TypeError, ValueError) as error:
        raise AcceptanceError(f"{label} session epoch is not an integer") from error
    if epoch < 0:
        raise AcceptanceError(f"{label} session epoch cannot be negative")
    return epoch


def _require_session_epoch_advance(initial_epoch: int, reconnect_epoch: int) -> None:
    if reconnect_epoch <= initial_epoch:
        raise AcceptanceError(
            "reconnect session epoch did not advance: "
            f"initial={initial_epoch}, reconnect={reconnect_epoch}"
        )


def _capture_host_evidence_cursor(path: Path) -> HostEvidenceCursor:
    try:
        status = path.stat()
    except OSError as error:
        raise AcceptanceError(f"cannot read host-side input evidence file metadata {path}: {error}") from error
    if not path.is_file():
        raise AcceptanceError(f"host-side input evidence path is not a regular file: {path}")
    return HostEvidenceCursor(status.st_dev, status.st_ino, status.st_size)


def _read_new_host_evidence(path: Path, cursor: HostEvidenceCursor) -> bytes:
    try:
        with path.open("rb") as source:
            status = os.fstat(source.fileno())
            if (status.st_dev, status.st_ino) != (cursor.device, cursor.inode):
                raise AcceptanceError(f"host-side input evidence file changed identity during acceptance: {path}")
            if status.st_size < cursor.offset:
                raise AcceptanceError(f"host-side input evidence file was truncated during acceptance: {path}")
            appended_size = status.st_size - cursor.offset
            if appended_size > MAX_HOST_INPUT_EVIDENCE_BYTES:
                raise AcceptanceError(
                    f"host-side input evidence exceeds {MAX_HOST_INPUT_EVIDENCE_BYTES} appended bytes"
                )
            source.seek(cursor.offset)
            appended = source.read(MAX_HOST_INPUT_EVIDENCE_BYTES + 1)
            if len(appended) > MAX_HOST_INPUT_EVIDENCE_BYTES:
                raise AcceptanceError(
                    f"host-side input evidence exceeds {MAX_HOST_INPUT_EVIDENCE_BYTES} appended bytes"
                )
            return appended
    except AcceptanceError:
        raise
    except OSError as error:
        raise AcceptanceError(f"cannot read host-side input evidence file {path}: {error}") from error


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            destination.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _redact_failure_message(error: Exception, args: argparse.Namespace) -> str:
    message = str(error)
    sensitive_values = [args.lease_token, args.serial]
    path_values = [args.apk, args.host_input_evidence, args.evidence, *args.device_lock]
    for sensitive_value in sensitive_values:
        if sensitive_value:
            message = message.replace(str(sensitive_value), "<redacted>")
    for path in path_values:
        rendered_paths = {str(path)}
        try:
            rendered_paths.add(str(path.resolve()))
        except OSError:
            pass
        for rendered_path in rendered_paths:
            if rendered_path:
                message = message.replace(rendered_path, "<local-path>")
    return message


def run(args: argparse.Namespace, records: list[CommandRecord] | None = None) -> dict[str, Any]:
    device_locks = _coordination_locks(args.device_lock)
    _require_device_lease_authorized(device_locks, INTERNET_LEASE_LOCK, args.lease_token)
    if records is None:
        records = []
    return _run_acceptance(args, records, device_locks)


def _run_acceptance(
    args: argparse.Namespace,
    records: list[CommandRecord],
    device_locks: Sequence[Path],
) -> dict[str, Any]:
    apk = args.apk.resolve()
    if not apk.is_file():
        raise AcceptanceError(f"APK does not exist: {apk}")
    host_evidence_path = args.host_input_evidence.resolve()
    _capture_host_evidence_cursor(host_evidence_path)
    adb = Adb(args.adb, args.serial, records, device_locks, INTERNET_LEASE_LOCK, args.lease_token)
    started_at = datetime.now(timezone.utc).isoformat()
    adb.host(["connect", args.serial], timeout=args.command_timeout)
    state = adb.device(["get-state"], timeout=args.command_timeout)
    if state != "device":
        raise AcceptanceError(f"ADB state is {state!r}, expected 'device'")
    identity = _device_identity(adb)
    if args.expected_model and identity["model"] != args.expected_model:
        raise AcceptanceError(f"connected model {identity['model']!r} does not equal expected {args.expected_model!r}")
    adb.device(["install", "-r", "-t", str(apk)], timeout=args.install_timeout)
    installed = adb.device(["shell", "dumpsys", "package", args.package], timeout=60)
    if "versionName=" not in installed:
        raise AcceptanceError(f"package {args.package} has no observable versionName after install")
    version_match = re.search(r"versionName=([^\s]+)", installed)
    adb.device(["logcat", "-c"])

    component = f"{args.package}/{args.activity}"

    def launch_and_connect() -> None:
        adb.device(["shell", "am", "force-stop", args.package])
        adb.device(["shell", "am", "start", "-W", "-n", component], timeout=60)
        time.sleep(args.launch_wait)
        if args.connect_tap:
            adb.device(["shell", "input", "tap", str(args.connect_tap[0]), str(args.connect_tap[1])])
            time.sleep(args.connect_wait)

    launch_and_connect()
    first_observation = _observe(adb, args.package)
    _require_pattern("streaming", args.streaming_pattern, first_observation)
    first_session_epoch = _extract_session_epoch("initial", args.session_epoch_pattern, first_observation)
    adb.device(["logcat", "-c"])
    host_evidence_cursor = _capture_host_evidence_cursor(host_evidence_path)
    adb.device(
        [
            "shell",
            "input",
            "swipe",
            str(args.input_swipe[0]),
            str(args.input_swipe[1]),
            str(args.input_swipe[2]),
            str(args.input_swipe[3]),
            str(args.input_swipe[4]),
        ]
    )
    time.sleep(args.input_wait)
    host_input_evidence = _read_new_host_evidence(host_evidence_path, host_evidence_cursor)
    _require_pattern(
        "host-side input acknowledgement",
        args.host_input_pattern,
        host_input_evidence.decode("utf-8", errors="replace"),
    )

    adb.device(["shell", "am", "force-stop", args.package])
    adb.device(["logcat", "-c"])
    time.sleep(args.disconnect_wait)
    launch_and_connect()
    reconnect_observation = _observe(adb, args.package)
    _require_pattern("reconnect", args.reconnect_pattern, reconnect_observation)
    _require_pattern("post-reconnect streaming", args.streaming_pattern, reconnect_observation)
    reconnect_session_epoch = _extract_session_epoch(
        "reconnect",
        args.session_epoch_pattern,
        reconnect_observation,
    )
    _require_session_epoch_advance(first_session_epoch, reconnect_session_epoch)

    soak_started = time.monotonic()
    soak_samples: list[dict[str, Any]] = []
    while time.monotonic() - soak_started < args.soak_seconds:
        pid = adb.device(["shell", "pidof", args.package])
        if not pid:
            raise AcceptanceError("application process exited during soak")
        sample = {"elapsed_seconds": round(time.monotonic() - soak_started, 3), "pid": pid}
        soak_samples.append(sample)
        time.sleep(min(args.soak_interval, max(0, args.soak_seconds - (time.monotonic() - soak_started))))
    final_observation = _observe(adb, args.package)
    _require_pattern("final streaming", args.streaming_pattern, final_observation)
    return {
        "schema_version": 1,
        "result": "passed",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "device": identity,
        "apk": {"sha256": _sha256(apk)},
        "application": {"package": args.package, "activity": args.activity, "version_name": version_match.group(1) if version_match else None},
        "assertions": {
            "streaming": "passed",
            "host_input_acknowledgement": "passed",
            "reconnect": "passed",
            "session_epoch_advanced": "passed",
        },
        "session_epochs": {
            "initial": first_session_epoch,
            "reconnect": reconnect_session_epoch,
        },
        "host_input_evidence": {
            "appended_bytes": len(host_input_evidence),
            "appended_sha256": hashlib.sha256(host_input_evidence).hexdigest(),
        },
        "soak_samples": soak_samples,
        "commands": [record.__dict__ for record in records],
    }


def coordinate_pair(value: str) -> tuple[int, int]:
    try:
        x, y = (int(part) for part in value.split(",", 1))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected X,Y integers") from error
    if x < 0 or y < 0:
        raise argparse.ArgumentTypeError("coordinates cannot be negative")
    return x, y


def swipe(value: str) -> tuple[int, int, int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected X1,Y1,X2,Y2,DURATION_MS integers") from error
    if len(parts) != 5 or any(part < 0 for part in parts):
        raise argparse.ArgumentTypeError("expected five non-negative integers")
    return parts  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="explicit lease-controlled ADB endpoint or device serial")
    parser.add_argument("--expected-model", help="optional expected ro.product.model value for a named device run")
    parser.add_argument("--adb", default="adb")
    parser.add_argument(
        "--device-lock",
        type=Path,
        action="append",
        default=[],
        help="additional device lease lock checked alongside the mandatory soak and Android locks; repeatable",
    )
    parser.add_argument(
        "--lease-token",
        required=True,
        help="UTF-8 owner token that must exactly match the Internet lease bytes (no implicit trimming)",
    )
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--package", default="dev.telemachus.display")
    parser.add_argument("--activity", default=".MainActivity")
    parser.add_argument("--connect-tap", type=coordinate_pair, help="tap X,Y after launch; omit if auto-connect is configured")
    parser.add_argument("--input-swipe", type=swipe, default=(500, 900, 700, 900, 250))
    parser.add_argument("--streaming-pattern", required=True, help="regex that proves decoded streaming, not mere connectivity")
    parser.add_argument(
        "--host-input-evidence",
        type=Path,
        required=True,
        help="host-produced append-only log used independently of Android observations",
    )
    parser.add_argument(
        "--host-input-pattern",
        required=True,
        help="regex that must match host evidence appended after the injected swipe",
    )
    parser.add_argument("--reconnect-pattern", required=True, help="regex that proves a new session after forced app disconnect")
    parser.add_argument(
        "--session-epoch-pattern",
        required=True,
        help="regex with named group 'epoch', matched independently before and after reconnect",
    )
    parser.add_argument("--evidence", type=Path, required=True, help="JSON output; keep generated evidence outside Git by default")
    parser.add_argument("--launch-wait", type=float, default=2)
    parser.add_argument("--connect-wait", type=float, default=8)
    parser.add_argument("--input-wait", type=float, default=2)
    parser.add_argument("--disconnect-wait", type=float, default=2)
    parser.add_argument("--soak-seconds", type=float, default=60)
    parser.add_argument("--soak-interval", type=float, default=10)
    parser.add_argument("--command-timeout", type=float, default=30)
    parser.add_argument("--install-timeout", type=float, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if min(args.launch_wait, args.connect_wait, args.input_wait, args.disconnect_wait, args.soak_seconds) < 0:
        print("error: wait and soak values cannot be negative", file=sys.stderr)
        return 2
    if min(args.soak_interval, args.command_timeout, args.install_timeout) <= 0:
        print("error: intervals and command timeouts must be positive", file=sys.stderr)
        return 2
    records: list[CommandRecord] = []
    try:
        report = run(args, records)
        _write_json(args.evidence, report)
    except (AcceptanceError, OSError) as error:
        safe_error = _redact_failure_message(error, args)
        try:
            _write_json(
                args.evidence,
                {
                    "schema_version": 1,
                    "result": "failed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error": safe_error,
                    "commands": [record.__dict__ for record in records],
                },
            )
        except OSError as write_error:
            print(f"error: could not write failure evidence: {write_error}", file=sys.stderr)
        print(f"error: {safe_error}", file=sys.stderr)
        return 1
    print(f"PASS: evidence written to {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
