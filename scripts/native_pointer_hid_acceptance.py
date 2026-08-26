#!/usr/bin/env python3
"""Collect native HID mouse acceptance evidence for Android -> macOS input.

The script is intentionally read-only with respect to the Android app: it does
not install, clear data, uninstall, reset permissions, or modify settings. It
captures the connected device identity, verifies that Android currently exposes
an external mouse-like input source, then waits for a human to move and click a
physical USB/Bluetooth mouse attached to the Android device while the Vibe Screen
USB/LAN Protocol v1 session is already streaming. The pass/fail decision requires
matching Android forwarding logs, newly appended Host injection logs, and an
operator note describing the visible Mac pointer/click result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = REPOSITORY_ROOT / "tools"
if str(TOOLS_PATH) not in sys.path:
    sys.path.insert(0, str(TOOLS_PATH))

from vibescreen_evidence.native_pointer_hid import summarize as summarize_native_pointer_hid


BLOCKED_EXIT = 2
DEFAULT_HOST_LOG = Path.home() / "Library/Logs/Telemachus/telemachus.log"
DEFAULT_OBSERVATION_SECONDS = 20.0
DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
ANDROID_DUMPSYS_TOKEN_RE = re.compile(r"\b(?:applicationInfo\.)?token=(?:0x[0-9a-fA-F]+|<null>)")
POINTER_PATTERNS = {
    "move": re.compile(r"Pointer injected: phase=(?:INPUT_PHASE_)?changed\b|Pointer injected: phase=changed\b"),
    "press": re.compile(r"Pointer injected: phase=(?:INPUT_PHASE_)?began\b|Pointer injected: phase=began\b"),
    "release": re.compile(r"Pointer injected: phase=(?:INPUT_PHASE_)?ended\b|Pointer injected: phase=ended\b"),
}
ANDROID_LOGCAT_TAG = "MA"
ANDROID_MOUSE_SOURCE_PATTERN = r"\S*(?:MOUSE|MOUSE_RELATIVE|TOUCHPAD|TRACKBALL)\S*"
ANDROID_POINTER_PATTERNS = {
    "move": re.compile(rf"native pointer forwarded action=MOVE\b.*\bsource={ANDROID_MOUSE_SOURCE_PATTERN}"),
    "press": re.compile(rf"native pointer forwarded action=BUTTON_PRESS\b.*\bsource={ANDROID_MOUSE_SOURCE_PATTERN}"),
    "release": re.compile(rf"native pointer forwarded action=BUTTON_RELEASE\b.*\bsource={ANDROID_MOUSE_SOURCE_PATTERN}"),
}


class AcceptanceError(Exception):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class DeviceIdentity:
    serial: str
    endpoint: str
    manufacturer: str
    model: str
    device: str
    android_release: str
    sdk: str
    fingerprint_sha256: str
    display_size: str
    display_density: str
    battery_summary: str
    boot_completed: str


@dataclass(frozen=True)
class InputDeviceSummary:
    name: str
    sources: str
    is_external: str


@dataclass(frozen=True)
class RedactedDeviceIdentity:
    serial: str
    endpoint: str
    manufacturer: str
    model: str
    device: str
    android_release: str
    sdk: str
    fingerprint_sha256: str
    display_size: str
    display_density: str
    battery_summary: str
    boot_completed: str


@dataclass(frozen=True)
class HostLogCursor:
    device: int
    inode: int
    offset: int


@dataclass(frozen=True)
class CoordinationLock:
    path: str
    detail: str


@dataclass(frozen=True)
class AcceptanceResult:
    status: str
    reason: str
    created_at: str
    observation_seconds: float
    device: RedactedDeviceIdentity
    external_mouse_devices: list[InputDeviceSummary]
    host_log: str
    host_log_appended_bytes: int
    host_log_appended_sha256: str
    host_stable_signed_tcc_ready: bool
    android_logcat_bytes: int
    android_logcat_sha256: str
    required_pointer_events: list[str]
    observed_host_pointer_events: list[str]
    observed_android_pointer_events: list[str]
    visible_mac_result: str
    existing_locks: list[CoordinationLock]
    adb_was_run: bool
    requested_serial: str


def redacted_device_identity(identity: DeviceIdentity) -> RedactedDeviceIdentity:
    return RedactedDeviceIdentity(
        serial=f"redacted-{identity.device}-serial",
        endpoint=f"redacted adb endpoint product:{identity.device} model:{identity.model} device:{identity.device}",
        manufacturer=identity.manufacturer,
        model=identity.model,
        device=identity.device,
        android_release=identity.android_release,
        sdk=identity.sdk,
        fingerprint_sha256="redacted-build-fingerprint-sha256",
        display_size=identity.display_size,
        display_density=identity.display_density,
        battery_summary=identity.battery_summary,
        boot_completed=identity.boot_completed,
    )


def redacted_requested_serial(serial: str) -> str:
    return "redacted-requested-serial" if serial.strip() else "not provided"


def run_command(command: Sequence[str], *, timeout: float = 15.0) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise AcceptanceError(f"required command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise AcceptanceError(f"command timed out: {' '.join(command)}") from error
    return CommandResult(list(command), completed.returncode, completed.stdout, completed.stderr)


def adb(serial: str, args: Sequence[str], *, timeout: float = 15.0) -> CommandResult:
    result = run_command(["adb", "-s", serial, *args], timeout=timeout)
    if result.returncode != 0:
        raise AcceptanceError(
            f"adb command failed ({result.returncode}): adb -s {serial} {' '.join(args)}\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )
    return result


def adb_shell(serial: str, *args: str, timeout: float = 15.0) -> str:
    return adb(serial, ["shell", *args], timeout=timeout).stdout.strip()


def describe_device_locks() -> list[CoordinationLock]:
    locks = []
    for path in DEVICE_LOCKS:
        try:
            if path.is_dir():
                locks.append(CoordinationLock(str(path), "present as directory"))
                continue
            detail = path.read_text(encoding="utf-8", errors="replace").strip()
        except FileNotFoundError:
            continue
        except OSError as error:
            try:
                mode = stat.filemode(path.stat().st_mode)
            except OSError:
                mode = "unknown mode"
            detail = f"present but unreadable ({mode}): {error}"
        locks.append(CoordinationLock(str(path), detail or "present"))
    return locks


def lock_blocked_result(
    *,
    created_at: str,
    requested_serial: str,
    locks: Sequence[CoordinationLock],
    required_events: Sequence[str],
) -> AcceptanceResult:
    return AcceptanceResult(
        status="blocked_device_coordination_lock",
        reason="Android device coordination lock exists; no ADB command was run and native pointer HID acceptance could not start.",
        created_at=created_at,
        observation_seconds=0.0,
        device=RedactedDeviceIdentity(
            serial="not-collected-device-lock",
            endpoint="not collected because a device coordination lock exists",
            manufacturer="not collected",
            model="not collected",
            device="device-lock-blocked",
            android_release="not collected",
            sdk="not collected",
            fingerprint_sha256="not collected",
            display_size="not collected",
            display_density="not collected",
            battery_summary="not collected",
            boot_completed="not collected",
        ),
        external_mouse_devices=[],
        host_log="host-log-appended.txt",
        host_log_appended_bytes=0,
        host_log_appended_sha256=hashlib.sha256(b"").hexdigest(),
        host_stable_signed_tcc_ready=False,
        android_logcat_bytes=0,
        android_logcat_sha256=hashlib.sha256(b"").hexdigest(),
        required_pointer_events=list(required_events),
        observed_host_pointer_events=[],
        observed_android_pointer_events=[],
        visible_mac_result="",
        existing_locks=list(locks),
        adb_was_run=False,
        requested_serial=redacted_requested_serial(requested_serial),
    )


def read_device_identity(serial: str) -> DeviceIdentity:
    devices = run_command(["adb", "devices", "-l"]).stdout.splitlines()
    endpoint = next((line for line in devices if line.startswith(serial + "\t") or line.startswith(serial + " ")), serial)
    fingerprint = adb_shell(serial, "getprop", "ro.build.fingerprint")
    battery = adb_shell(serial, "dumpsys", "battery", timeout=20.0)
    battery_lines = [line.strip() for line in battery.splitlines() if line.strip()]
    return DeviceIdentity(
        serial=serial,
        endpoint=endpoint,
        manufacturer=adb_shell(serial, "getprop", "ro.product.manufacturer"),
        model=adb_shell(serial, "getprop", "ro.product.model"),
        device=adb_shell(serial, "getprop", "ro.product.device"),
        android_release=adb_shell(serial, "getprop", "ro.build.version.release"),
        sdk=adb_shell(serial, "getprop", "ro.build.version.sdk"),
        fingerprint_sha256=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
        display_size=adb_shell(serial, "wm", "size"),
        display_density=adb_shell(serial, "wm", "density"),
        battery_summary="; ".join(battery_lines[:12]),
        boot_completed=adb_shell(serial, "getprop", "sys.boot_completed"),
    )


def parse_input_devices(dumpsys_input: str) -> list[InputDeviceSummary]:
    summaries: list[InputDeviceSummary] = []
    current_name: str | None = None
    current_external: str | None = None
    current_sources: str | None = None
    for raw_line in dumpsys_input.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"\s*Device\s+[^:]+:\s*(.+)", line)
        if match:
            if current_name and current_sources:
                summaries.append(
                    InputDeviceSummary(
                        name=current_name,
                        sources=current_sources,
                        is_external=current_external or "unknown",
                    )
                )
            current_name = match.group(1).strip()
            current_external = None
            current_sources = None
            continue
        if current_name is None:
            continue
        external = re.match(r"\s*IsExternal:\s*(.+)", line)
        if external:
            current_external = external.group(1).strip()
            continue
        sources = re.match(r"\s*Sources:\s*(.+)", line)
        if sources:
            current_sources = sources.group(1).strip()
    if current_name and current_sources:
        summaries.append(
            InputDeviceSummary(
                name=current_name,
                sources=current_sources,
                is_external=current_external or "unknown",
            )
        )
    return summaries


def external_mouse_devices(devices: Sequence[InputDeviceSummary]) -> list[InputDeviceSummary]:
    candidates = []
    for device in devices:
        sources = device.sources.upper()
        external = device.is_external.lower() == "true"
        if external and (
            "MOUSE" in sources
            or "MOUSE_RELATIVE" in sources
            or "TOUCHPAD" in sources
            or "TRACKBALL" in sources
        ):
            candidates.append(device)
    return candidates


def host_log_cursor(path: Path) -> HostLogCursor:
    try:
        stat = path.stat()
        return HostLogCursor(device=stat.st_dev, inode=stat.st_ino, offset=stat.st_size)
    except FileNotFoundError as error:
        raise AcceptanceError(f"host log does not exist: {path}") from error


def read_new_host_log(path: Path, cursor: HostLogCursor, max_bytes: int) -> bytes:
    try:
        with path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            if stat.st_dev != cursor.device or stat.st_ino != cursor.inode:
                raise AcceptanceError(f"host log identity changed during acceptance: {path}")
            current_size = stat.st_size
            if current_size < cursor.offset:
                raise AcceptanceError(f"host log was truncated during acceptance: {path}")
            appended = current_size - cursor.offset
            if appended > max_bytes:
                raise AcceptanceError(f"host log appended {appended} bytes, above limit {max_bytes}")
            handle.seek(cursor.offset)
            data = handle.read(appended)
        if len(data) != appended:
            raise AcceptanceError(f"host log was truncated during acceptance: {path}")
        return data
    except OSError as error:
        raise AcceptanceError(f"cannot read host log {path}: {error}") from error


class LogcatCapture:
    def __init__(self, serial: str, max_bytes: int) -> None:
        self.serial = serial
        self.max_bytes = max_bytes
        self.marker = f"vibescreen-native-pointer-start-{uuid.uuid4().hex}"
        self.start_time = ""

    def __enter__(self) -> "LogcatCapture":
        self.start_time = adb_shell(self.serial, "date", "+%m-%d %H:%M:%S.000", timeout=5.0)
        adb(self.serial, ["shell", "log", "-t", ANDROID_LOGCAT_TAG, self.marker], timeout=5.0)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def stop(self) -> bytes:
        result = adb(
            self.serial,
            ["logcat", "-d", "-v", "time", "-T", self.start_time, "-s", f"{ANDROID_LOGCAT_TAG}:D", "*:S"],
            timeout=10.0,
        )
        data = self.after_marker(result.stdout).encode("utf-8", errors="replace")
        if len(data) > self.max_bytes:
            raise AcceptanceError(f"android logcat captured {len(data)} bytes, above limit {self.max_bytes}")
        return data

    def after_marker(self, logcat_text: str) -> str:
        lines = logcat_text.splitlines()
        marker_index = next((index for index, line in enumerate(lines) if self.marker in line), None)
        if marker_index is None:
            raise AcceptanceError("android logcat marker was not found in captured observation window")
        return evidence_text("\n".join(lines[marker_index + 1 :]))


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def observed_events(log_text: str) -> list[str]:
    return [name for name, pattern in POINTER_PATTERNS.items() if pattern.search(log_text)]


def observed_android_events(log_text: str) -> list[str]:
    return [name for name, pattern in ANDROID_POINTER_PATTERNS.items() if pattern.search(log_text)]


def evidence_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def redact_android_dumpsys_text(text: str) -> str:
    return ANDROID_DUMPSYS_TOKEN_RE.sub(lambda match: match.group(0).split("=", 1)[0] + "=<redacted>", text)


def write_result(path: Path, result: AcceptanceResult, dumpsys_input: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    result_path = path / "result.json"
    result_payload = asdict(result)
    result_path.write_text(json.dumps(result_payload, indent=2) + "\n", encoding="utf-8")
    gate_summary = summarize_native_pointer_hid(result_payload, run_id=result.created_at, source_path=result_path)
    (path / "native-pointer-hid-summary.json").write_text(
        json.dumps(gate_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (path / "dumpsys-input.txt").write_text(evidence_text(redact_android_dumpsys_text(dumpsys_input)), encoding="utf-8")
    summary = [
        f"# Native pointer HID acceptance: {result.status}",
        "",
        f"Created: {result.created_at}",
        f"Reason: {result.reason}",
        f"Device: {result.device.manufacturer} {result.device.model} / {result.device.device} / Android {result.device.android_release} / serial {result.device.serial}",
        f"Requested serial: {result.requested_serial}",
        f"ADB was run: {str(result.adb_was_run).lower()}",
        f"External mouse devices: {len(result.external_mouse_devices)}",
        f"Observed Android pointer events: {', '.join(result.observed_android_pointer_events) or 'none'}",
        f"Observed Host pointer events: {', '.join(result.observed_host_pointer_events) or 'none'}",
        f"Stable signed/TCC Host ready: {str(result.host_stable_signed_tcc_ready).lower()}",
        f"Visible Mac result: {result.visible_mac_result or 'not recorded'}",
        "",
        "## Artifacts",
        "",
        "- `result.json`: structured gate result, device identity, source devices, and checksums.",
        "- `native-pointer-hid-summary.json`: independent gate summary with `can_close_native_pointer_hid_gate`.",
        "- `dumpsys-input.txt`: Android input-device snapshot with line-ending whitespace normalized.",
        "- `android-logcat-native-pointer.txt`: bounded Android logcat window for native pointer forwarding.",
        "- `host-log-appended.txt`: bounded Host log window for pointer injection.",
        "",
        "A pass also requires stable signed/TCC-ready Host evidence; pass `--host-stable-signed-tcc-ready` only after `scripts/macos_dev_host.py preflight` succeeds.",
        "This evidence must remain scoped to the exact device identity above.",
        "Persistent device identifiers and local workstation paths are redacted in `result.json`; raw device inventory remains in `dumpsys-input.txt`.",
    ]
    if result.existing_locks:
        summary.extend(["", "## Device coordination locks", ""])
        for existing_lock in result.existing_locks:
            summary.append(f"- {existing_lock.path}: {existing_lock.detail}")
    (path / "README.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB serial for the Android device under test.")
    parser.add_argument(
        "--host-log",
        type=Path,
        default=DEFAULT_HOST_LOG,
        help=f"Host log to inspect for Pointer injected lines. Default: {DEFAULT_HOST_LOG}",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="Directory where result.json, dumpsys-input.txt, and README.md will be written.",
    )
    parser.add_argument(
        "--observe-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_SECONDS,
        help="Seconds to wait while the operator moves and clicks the physical mouse.",
    )
    parser.add_argument(
        "--max-host-log-bytes",
        type=int,
        default=1_000_000,
        help="Maximum appended host log bytes to read after observation.",
    )
    parser.add_argument(
        "--max-android-logcat-bytes",
        type=int,
        default=1_000_000,
        help="Maximum Android logcat bytes to retain for the observation window.",
    )
    parser.add_argument(
        "--visible-result-note",
        default="",
        help="Operator note describing the visible Mac pointer movement and click result.",
    )
    parser.add_argument(
        "--host-stable-signed-tcc-ready",
        action="store_true",
        help=(
            "Set only after scripts/macos_dev_host.py preflight passes for a stable signed Host "
            "with Screen Recording and Accessibility permissions."
        ),
    )
    parser.add_argument(
        "--require-events",
        choices=sorted(POINTER_PATTERNS),
        nargs="+",
        default=["move", "press", "release"],
        help="Pointer event kinds required for PASS.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Only perform prerequisite checks and write evidence. Useful for blocked dry runs.",
    )
    parser.add_argument(
        "--allow-existing-device-lock",
        action="store_true",
        help="Continue despite a shared Android device coordination lock. Use only when you own that lock.",
    )
    parser.add_argument(
        "--write-blocked-on-lock",
        action="store_true",
        help="When a shared Android device lock exists, write blocked evidence instead of running ADB.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.observe_seconds < 0:
        raise SystemExit("--observe-seconds must be non-negative")
    if args.max_host_log_bytes <= 0:
        raise SystemExit("--max-host-log-bytes must be positive")
    if args.max_android_logcat_bytes <= 0:
        raise SystemExit("--max-android-logcat-bytes must be positive")

    created_at = utc_timestamp()
    try:
        existing_locks = describe_device_locks()
        if existing_locks and not args.allow_existing_device_lock:
            if not args.write_blocked_on_lock:
                raise AcceptanceError(
                    "device coordination lock exists; no ADB command was run: "
                    + ", ".join(lock.path for lock in existing_locks)
                )
            result = lock_blocked_result(
                created_at=created_at,
                requested_serial=args.serial,
                locks=existing_locks,
                required_events=args.require_events,
            )
            write_result(args.evidence_dir, result, "")
            (args.evidence_dir / "host-log-appended.txt").write_bytes(b"")
            (args.evidence_dir / "android-logcat-native-pointer.txt").write_bytes(b"")
            print(result.reason, file=sys.stderr)
            return BLOCKED_EXIT

        identity = read_device_identity(args.serial)
        dumpsys_input = adb(args.serial, ["shell", "dumpsys", "input"], timeout=30.0).stdout
        input_devices = parse_input_devices(dumpsys_input)
        mouse_devices = external_mouse_devices(input_devices)
        if not mouse_devices:
            result = AcceptanceResult(
                status="blocked",
                reason="No external Android input device with MOUSE, MOUSE_RELATIVE, TOUCHPAD, or TRACKBALL source is currently attached.",
                created_at=created_at,
                observation_seconds=0.0,
                device=redacted_device_identity(identity),
                external_mouse_devices=[],
                host_log="host-log-appended.txt",
                host_log_appended_bytes=0,
                host_log_appended_sha256=hashlib.sha256(b"").hexdigest(),
                host_stable_signed_tcc_ready=False,
                android_logcat_bytes=0,
                android_logcat_sha256=hashlib.sha256(b"").hexdigest(),
                required_pointer_events=list(args.require_events),
                observed_host_pointer_events=[],
                observed_android_pointer_events=[],
                visible_mac_result="",
                existing_locks=existing_locks,
                adb_was_run=True,
                requested_serial=redacted_requested_serial(args.serial),
            )
            write_result(args.evidence_dir, result, dumpsys_input)
            (args.evidence_dir / "host-log-appended.txt").write_bytes(b"")
            (args.evidence_dir / "android-logcat-native-pointer.txt").write_bytes(b"")
            print(result.reason, file=sys.stderr)
            return BLOCKED_EXIT

        cursor = host_log_cursor(args.host_log)
        if args.no_wait:
            appended_log = b""
            android_logcat = b""
        else:
            print(
                "Move the physical mouse attached to the Android device, then left-click and release. "
                f"Waiting {args.observe_seconds:.1f}s...",
                file=sys.stderr,
            )
            with LogcatCapture(args.serial, args.max_android_logcat_bytes) as logcat_capture:
                time.sleep(args.observe_seconds)
                android_logcat = logcat_capture.stop()
            appended_log = read_new_host_log(args.host_log, cursor, args.max_host_log_bytes)
        appended_text = appended_log.decode("utf-8", errors="replace")
        android_text = android_logcat.decode("utf-8", errors="replace")
        observed_host = observed_events(appended_text)
        observed_android = observed_android_events(android_text)
        missing_host = [name for name in args.require_events if name not in observed_host]
        missing_android = [name for name in args.require_events if name not in observed_android]
        missing_host_ready = not args.host_stable_signed_tcc_ready
        missing_visible_result = not args.visible_result_note.strip()
        missing_reasons = []
        if missing_android:
            missing_reasons.append("missing Android native pointer log events: " + ", ".join(missing_android))
        if missing_host:
            missing_reasons.append("missing Host pointer injection events: " + ", ".join(missing_host))
        if missing_host_ready:
            missing_reasons.append("missing stable signed/TCC-ready Host preflight evidence")
        if missing_visible_result:
            missing_reasons.append("missing visible Mac pointer/click result note")
        status = "passed" if not missing_reasons else ("blocked" if missing_host_ready else "failed")
        reason = "All required native pointer evidence was observed." if not missing_reasons else "; ".join(missing_reasons)
        result = AcceptanceResult(
            status=status,
            reason=reason,
            created_at=created_at,
            observation_seconds=0.0 if args.no_wait else float(args.observe_seconds),
            device=redacted_device_identity(identity),
            external_mouse_devices=mouse_devices,
            host_log="host-log-appended.txt",
            host_log_appended_bytes=len(appended_log),
            host_log_appended_sha256=hashlib.sha256(appended_log).hexdigest(),
            host_stable_signed_tcc_ready=bool(args.host_stable_signed_tcc_ready),
            android_logcat_bytes=len(android_logcat),
            android_logcat_sha256=hashlib.sha256(android_logcat).hexdigest(),
            required_pointer_events=list(args.require_events),
            observed_host_pointer_events=observed_host,
            observed_android_pointer_events=observed_android,
            visible_mac_result=args.visible_result_note.strip(),
            existing_locks=existing_locks,
            adb_was_run=True,
            requested_serial=redacted_requested_serial(args.serial),
        )
        write_result(args.evidence_dir, result, dumpsys_input)
        (args.evidence_dir / "host-log-appended.txt").write_bytes(appended_log)
        (args.evidence_dir / "android-logcat-native-pointer.txt").write_bytes(android_logcat)
        if status != "passed":
            print(reason, file=sys.stderr)
            return BLOCKED_EXIT if status == "blocked" else 1
        print(reason)
        return 0
    except AcceptanceError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
