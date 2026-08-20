#!/usr/bin/env python3
"""Collect read-only Android stylus evidence and write an acceptance note.

The script separates device capability evidence from drawing-app acceptance.
dumpsys input can prove that Android exposes stylus axes and buttons, but it
cannot prove a physical pen reached the app, crossed Protocol v1, and produced
a pressure/tilt-aware line on macOS. That final gate stays blocked unless the
caller records an observed physical stylus drawing run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_OUTPUT_ROOT = Path("docs/changes/2026-08-19-physical-stylus-acceptance/evidence")
DEFAULT_OBSERVATION_SECONDS = 20.0
DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
REQUIRED_STYLUS_AXES = ("PRESSURE", "TILT")
STYLUS_BUTTON_NAMES = ("STYLUS_PRIMARY", "STYLUS_SECONDARY")
NUMBER_RE = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
CONTACT_RE = re.compile(r"\bcontact=(?:contact|CONTACT|STYLUS_CONTACT_STATE_CONTACT)\b")
PHASE_RE = re.compile(r"\bphase=([^\s]+)")
PRESSURE_RE = re.compile(rf"\bpressure=({NUMBER_RE})\b")
TERMINAL_PHASES = {
    "cancelled",
    "ended",
    "INPUT_PHASE_CANCELLED",
    "INPUT_PHASE_ENDED",
}
HOST_STYLUS_LOG_PATTERNS = {
    "stylus_injection": re.compile(r"\bStylus injected:"),
    "contact": re.compile(r"\bcontact=\S+"),
    "tool": re.compile(r"\btool=\S+"),
    "buttons": re.compile(r"\bbuttons=\d+\b"),
    "pressure": PRESSURE_RE,
    "tilt_x": re.compile(rf"\btiltX={NUMBER_RE}\b"),
    "tilt_y": re.compile(rf"\btiltY={NUMBER_RE}\b"),
}
ANDROID_STYLUS_LINE_PATTERNS = (
    re.compile(r"\bStylus forwarded:"),
    re.compile(r"\bsamples=\d+\b"),
    re.compile(r"\bextended=(?:true|false)\b"),
    re.compile(r"\brawSource=0x[0-9a-fA-F]+\b"),
    re.compile(r"\brawAction=\d+\b"),
    re.compile(r"\brawTools=\[[^]]*(?:stylus|eraser)[^]]*]"),
    re.compile(r"\bphase=\S+"),
    re.compile(r"\bcontact=\S+"),
    re.compile(r"\btool=\S+"),
    re.compile(r"\bbuttons=\d+\b"),
    PRESSURE_RE,
    re.compile(rf"\btiltX={NUMBER_RE}\b"),
    re.compile(rf"\btiltY={NUMBER_RE}\b"),
)
HOST_STYLUS_LINE_PATTERNS = tuple(HOST_STYLUS_LOG_PATTERNS.values())


class EvidenceError(RuntimeError):
    """Raised when evidence cannot be collected or interpreted."""


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


@dataclass(frozen=True)
class InputDeviceCapability:
    name: str
    descriptor: str | None
    sources: tuple[str, ...]
    axes: tuple[str, ...]
    buttons: tuple[str, ...]

    @property
    def has_stylus_source(self) -> bool:
        return "STYLUS" in self.sources

    @property
    def required_axes_present(self) -> bool:
        return all(axis in self.axes for axis in REQUIRED_STYLUS_AXES)

    @property
    def pass_eligible(self) -> bool:
        return self.has_stylus_source and self.required_axes_present


@dataclass(frozen=True)
class HostLogCursor:
    device: int
    inode: int
    offset: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect read-only stylus capability evidence from an Android device."
    )
    parser.add_argument("--adb", default="adb", help="ADB executable path.")
    parser.add_argument("--serial", required=True, help="ADB device serial or endpoint.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android package for private diag log collection.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Evidence output directory. Defaults to a timestamped directory under docs/changes.",
    )
    parser.add_argument("--skip-diag-log", action="store_true", help="Do not read the app private diag log with run-as.")
    parser.add_argument(
        "--allow-existing-device-lock",
        action="store_true",
        help="Continue despite a coordination lock. Use only when you own that lock.",
    )
    parser.add_argument(
        "--write-blocked-on-lock",
        action="store_true",
        help="When a device coordination lock exists, write blocked readiness evidence instead of running ADB.",
    )
    parser.add_argument(
        "--observed-physical-drawing",
        action="store_true",
        help="Mark acceptance passed only when a human observed a real stylus drawing in a macOS drawing app.",
    )
    parser.add_argument(
        "--drawing-observation",
        default="",
        help="One-sentence observed drawing result, required with --observed-physical-drawing.",
    )
    parser.add_argument(
        "--host-log",
        type=Path,
        default=None,
        help="Host log excerpt captured during the physical stylus drawing run; required for pass.",
    )
    parser.add_argument(
        "--observe-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_SECONDS,
        help="Seconds to wait for a human physical stylus drawing run before checking newly appended logs.",
    )
    parser.add_argument(
        "--max-host-log-bytes",
        type=int,
        default=1_000_000,
        help="Maximum appended Host log bytes to read during a passing observation run.",
    )
    return parser.parse_args(argv)


def run(command: Sequence[str], timeout: float = 30) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(list(command), check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise EvidenceError(f"command timed out after {timeout:g}s: {' '.join(command)}") from error
    except OSError as error:
        raise EvidenceError(f"cannot run command {' '.join(command)}: {error}") from error
    return CommandResult(
        argv=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        elapsed_seconds=time.monotonic() - started,
    )


def require_success(result: CommandResult) -> str:
    if result.returncode != 0:
        detail = result.stderr.strip()
        raise EvidenceError(f"command failed ({result.returncode}): {' '.join(result.argv)}; {detail}")
    return result.stdout


def check_device_locks(allow_existing: bool) -> list[str]:
    existing = [str(path) for path in DEVICE_LOCKS if path.exists()]
    if existing and not allow_existing:
        raise EvidenceError("device coordination lock exists; no ADB command was run: " + ", ".join(existing))
    return existing


def describe_device_locks() -> list[dict[str, object]]:
    descriptions: list[dict[str, object]] = []
    for path in DEVICE_LOCKS:
        if not path.exists():
            continue
        try:
            stat = path.stat()
            detail = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as error:
            descriptions.append({"path": str(path), "read_error": str(error)})
            continue
        descriptions.append({
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "detail": detail,
        })
    return descriptions


def adb(adb_path: str, serial: str, *arguments: str, timeout: float = 30) -> CommandResult:
    return run([adb_path, "-s", serial, *arguments], timeout=timeout)


def collect_device_identity(adb_path: str, serial: str) -> dict[str, str]:
    properties = {
        "serialno": "ro.serialno",
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "device": "ro.product.device",
        "os_release": "ro.build.version.release",
        "api_level": "ro.build.version.sdk",
        "fingerprint": "ro.build.fingerprint",
    }
    identity: dict[str, str] = {}
    for key, prop in properties.items():
        identity[key] = require_success(adb(adb_path, serial, "shell", "getprop", prop)).strip()
    for key, command in (("wm_size", ("wm", "size")), ("wm_density", ("wm", "density"))):
        result = adb(adb_path, serial, "shell", *command)
        if result.returncode == 0:
            identity[key] = result.stdout.strip()
    return identity


def parse_input_devices(dumpsys_input: str) -> list[InputDeviceCapability]:
    devices: list[InputDeviceCapability] = []
    current_lines: list[str] = []
    for line in dumpsys_input.splitlines():
        if re.match(r"^\s*(?:Device\s+)?\d+:\s+", line):
            if current_lines:
                parsed = parse_input_device_block(current_lines)
                if parsed is not None:
                    devices.append(parsed)
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)
    if current_lines:
        parsed = parse_input_device_block(current_lines)
        if parsed is not None:
            devices.append(parsed)
    return devices


def parse_input_device_block(lines: Sequence[str]) -> InputDeviceCapability | None:
    header = lines[0].strip() if lines else ""
    name_match = re.match(r"(?:Device\s+)?\d+:\s+(.+?)\s*$", header)
    if not name_match:
        return None
    name = name_match.group(1).strip()
    if "DeviceId=" in name:
        return None
    descriptor: str | None = None
    sources: set[str] = set()
    axes: set[str] = set()
    buttons: set[str] = set()
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if line.startswith("Descriptor:"):
            descriptor = line.split(":", 1)[1].strip()
        elif line.startswith("Sources:"):
            sources.update(extract_source_names(line))
        axes.update(extract_abs_state_axes(line))
        axis = extract_axis_name(line)
        if axis:
            axes.add(axis)
        buttons.update(extract_button_names(line))
    return InputDeviceCapability(name, descriptor, tuple(sorted(sources)), tuple(sorted(axes)), tuple(sorted(buttons)))


def extract_source_names(line: str) -> set[str]:
    _, _, value = line.partition(":")
    return {
        token.strip().upper()
        for token in re.split(r"[|, ]+", value)
        if token.strip() and not token.strip().startswith("0x")
    }


def extract_axis_name(line: str) -> str | None:
    for pattern in (
        r"Motion Range:\s*([A-Z0-9_]+)\b",
        r"^([A-Z0-9_]+):\s*source=",
        r"Axis\s+([A-Z0-9_]+)\b",
        r"\bAXIS_([A-Z0-9_]+)\b",
    ):
        match = re.search(pattern, line)
        if match:
            return normalize_axis_name(match.group(1))
    return None


def extract_abs_state_axes(line: str) -> set[str]:
    axes: set[str] = set()
    if "ABS_PRESSURE" in line:
        axes.add("PRESSURE")
    if "ABS_TILT_X" in line or "ABS_TILT_Y" in line:
        axes.add("TILT")
    return axes


def normalize_axis_name(axis: str) -> str:
    axis = axis.upper()
    return axis[5:] if axis.startswith("AXIS_") else axis


def extract_button_names(line: str) -> set[str]:
    buttons: set[str] = set()
    upper = line.upper()
    if "BUTTON_STYLUS_PRIMARY" in upper or "STYLUS_PRIMARY" in upper:
        buttons.add("STYLUS_PRIMARY")
    if "BUTTON_STYLUS_SECONDARY" in upper or "STYLUS_SECONDARY" in upper:
        buttons.add("STYLUS_SECONDARY")
    return buttons


def select_stylus_candidates(devices: Sequence[InputDeviceCapability]) -> list[InputDeviceCapability]:
    candidates: list[InputDeviceCapability] = []
    for device in devices:
        name_has_stylus = "stylus" in device.name.lower() or "pen" in device.name.lower()
        has_tilt_pressure = device.required_axes_present
        if name_has_stylus or "STYLUS" in device.sources or has_tilt_pressure:
            candidates.append(device)
    return candidates


def read_diag_log(adb_path: str, serial: str, package: str) -> tuple[str, str | None]:
    command = "cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null"
    result = adb(adb_path, serial, "exec-out", "run-as", package, "sh", "-c", command, timeout=30)
    if result.returncode != 0:
        return "", result.stderr.strip() or "run-as diag log read failed"
    return result.stdout, None


def appended_diag_log(before: str, after: str) -> str:
    if after.startswith(before):
        return after[len(before):]
    if not before:
        return after
    raise EvidenceError("Android diag log changed or rotated during observation; cannot isolate new stylus lines")


def host_log_cursor(path: Path) -> HostLogCursor:
    try:
        stat = path.stat()
        return HostLogCursor(device=stat.st_dev, inode=stat.st_ino, offset=stat.st_size)
    except FileNotFoundError as error:
        raise EvidenceError(f"host log does not exist: {path}") from error


def read_new_host_log(path: Path, cursor: HostLogCursor, max_bytes: int) -> str:
    try:
        with path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            if stat.st_dev != cursor.device or stat.st_ino != cursor.inode:
                raise EvidenceError(f"host log identity changed during observation: {path}")
            current_size = stat.st_size
            if current_size < cursor.offset:
                raise EvidenceError(f"host log was truncated during observation: {path}")
            appended = current_size - cursor.offset
            if appended > max_bytes:
                raise EvidenceError(f"host log appended {appended} bytes, above limit {max_bytes}")
            handle.seek(cursor.offset)
            data = handle.read(appended)
    except OSError as error:
        raise EvidenceError(f"cannot read host log {path}: {error}") from error
    return data.decode("utf-8", errors="replace")


def wait_for_physical_drawing(args: argparse.Namespace, host_cursor: HostLogCursor | None) -> str:
    if not args.observed_physical_drawing:
        return ""
    if args.observe_seconds < 0:
        raise EvidenceError("--observe-seconds must be non-negative")
    if args.max_host_log_bytes <= 0:
        raise EvidenceError("--max-host-log-bytes must be positive")
    assert args.host_log is not None
    assert host_cursor is not None
    if args.observe_seconds > 0:
        print(
            "Draw in the macOS test app using the physical Android stylus. "
            f"Waiting {args.observe_seconds:.1f}s...",
            file=sys.stderr,
        )
        time.sleep(args.observe_seconds)
    return read_new_host_log(args.host_log, host_cursor, args.max_host_log_bytes)


def create_output_dir(output_dir: Path | None, identity: dict[str, str]) -> Path:
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    target = DEFAULT_OUTPUT_ROOT / f"{stamp}-{slug(identity.get('model') or 'android-device')}-{slug(identity.get('device') or 'unknown')}-stylus"
    target.mkdir(parents=True, exist_ok=False)
    return target


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "unknown"


def conclusion_status(
    args: argparse.Namespace,
    candidates: Sequence[InputDeviceCapability],
    diag_log: str = "",
    diag_error: str | None = None,
    host_log_excerpt: str = "",
) -> str:
    has_required_capability = any(candidate.pass_eligible for candidate in candidates)
    if args.observed_physical_drawing:
        if not args.drawing_observation.strip():
            raise EvidenceError("--drawing-observation is required with --observed-physical-drawing")
        if not args.host_log:
            raise EvidenceError("--host-log is required with --observed-physical-drawing")
        if not args.host_log.exists():
            raise EvidenceError(f"host log does not exist: {args.host_log}")
        if not has_required_capability:
            return "blocked_no_required_stylus_capability"
        validate_android_diag_for_pass(diag_log, diag_error)
        validate_host_log_text_for_pass(host_log_excerpt)
        return "pass"
    if has_required_capability:
        return "blocked_physical_stylus_not_observed"
    return "blocked_no_required_stylus_capability"


def validate_host_log_text_for_pass(text: str) -> None:
    if not text.strip():
        raise EvidenceError("new Host stylus log excerpt is required for pass and was empty")
    if not any(
        all(pattern.search(line) for pattern in HOST_STYLUS_LINE_PATTERNS)
        and is_contact_pressure_sample(line)
        for line in text.splitlines()
    ):
        raise EvidenceError(
            "host log is missing a single stylus injection line with contact, non-zero pressure, and all required fields"
        )


def validate_android_diag_for_pass(diag_log: str, diag_error: str | None) -> None:
    if diag_error:
        raise EvidenceError("Android diag log is required for pass; run-as failed: " + diag_error)
    if not diag_log.strip():
        raise EvidenceError("Android diag log is required for pass and was empty")
    if not any(
        all(pattern.search(line) for pattern in ANDROID_STYLUS_LINE_PATTERNS)
        and is_contact_pressure_sample(line)
        for line in diag_log.splitlines()
    ):
        raise EvidenceError(
            "Android diag log is missing a single stylus forwarding line with contact, non-zero pressure, and all required fields"
        )


def is_contact_pressure_sample(line: str) -> bool:
    if not CONTACT_RE.search(line):
        return False
    phase = PHASE_RE.search(line)
    if phase is None or phase.group(1) in TERMINAL_PHASES:
        return False
    pressure = PRESSURE_RE.search(line)
    if not pressure:
        return False
    try:
        return float(pressure.group(1)) > 0.0
    except ValueError:
        return False


def write_evidence(
    output_dir: Path,
    args: argparse.Namespace,
    existing_locks: Sequence[str],
    identity: dict[str, str],
    dumpsys_input: str,
    candidates: Sequence[InputDeviceCapability],
    diag_log: str,
    diag_error: str | None,
    host_log_excerpt: str,
    status: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dumpsys-input.txt").write_text(dumpsys_input, encoding="utf-8")
    if diag_log:
        (output_dir / "android-diag.log").write_text(diag_log, encoding="utf-8")
    if host_log_excerpt:
        (output_dir / "host-stylus.log").write_text(host_log_excerpt, encoding="utf-8")
    summary = {
        "status": status,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "device_identity": identity,
        "existing_locks": list(existing_locks),
        "stylus_candidates": [candidate.__dict__ for candidate in candidates],
        "pass_eligible_stylus_candidates": [candidate.__dict__ for candidate in candidates if candidate.pass_eligible],
        "diag_log_read_error": diag_error,
        "host_log": str(args.host_log) if args.host_log else None,
        "host_log_appended_bytes": len(host_log_excerpt.encode("utf-8")) if host_log_excerpt else 0,
        "host_log_appended_sha256": hashlib.sha256(host_log_excerpt.encode("utf-8")).hexdigest(),
        "observation_seconds": float(args.observe_seconds) if args.observed_physical_drawing else 0.0,
        "observed_physical_drawing": bool(args.observed_physical_drawing),
        "drawing_observation": args.drawing_observation.strip(),
    }
    (output_dir / "stylus-evidence.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(render_readme(summary), encoding="utf-8")


def write_lock_blocked_evidence(output_dir: Path, args: argparse.Namespace, locks: Sequence[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "status": "blocked_device_coordination_lock",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "requested_serial": args.serial,
        "device_identity": {},
        "existing_locks": list(locks),
        "stylus_candidates": [],
        "pass_eligible_stylus_candidates": [],
        "diag_log_read_error": "ADB not run because a device coordination lock exists.",
        "host_log": str(args.host_log) if args.host_log else None,
        "host_log_appended_bytes": 0,
        "host_log_appended_sha256": hashlib.sha256(b"").hexdigest(),
        "observation_seconds": 0.0,
        "observed_physical_drawing": False,
        "drawing_observation": "",
    }
    (output_dir / "stylus-evidence.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "README.md").write_text(render_readme(summary), encoding="utf-8")


def render_readme(summary: dict[str, object]) -> str:
    identity = summary["device_identity"]
    assert isinstance(identity, dict)
    candidates = summary["stylus_candidates"]
    assert isinstance(candidates, list)
    status = str(summary["status"])
    if status == "pass":
        conclusion = "Physical stylus drawing-app confirmation passed for this exact device/run. Keep the raw host and Android logs with this evidence."
    elif status == "blocked_physical_stylus_not_observed":
        conclusion = "Blocked: Android exposes stylus-capable input hardware, but this run did not observe a physical stylus drawing in a macOS drawing app. The README gate stays open."
    elif status == "blocked_device_coordination_lock":
        conclusion = "Blocked: an Android device coordination lock existed, so this run did not execute ADB commands or observe physical stylus input. The README gate stays open."
    else:
        conclusion = "Blocked: this device snapshot did not expose the required stylus pressure and tilt capability set, so drawing-app acceptance cannot start from this evidence."
    lines = [
        "# Android physical stylus acceptance evidence",
        "",
        "## Conclusion",
        "",
        f"- Status: {status}",
        f"- Result: {conclusion}",
        "",
    ]
    lines.extend(["## Device", ""])
    if identity:
        lines.extend([
            f"- Manufacturer: {identity.get('manufacturer', '')}",
            f"- Model/device: {identity.get('model', '')} / {identity.get('device', '')}",
            f"- Android: {identity.get('os_release', '')} / API {identity.get('api_level', '')}",
            f"- Serial property: {identity.get('serialno', '')}",
            f"- Fingerprint: {identity.get('fingerprint', '')}",
            f"- Display: {identity.get('wm_size', '')} / {identity.get('wm_density', '')}",
            "",
        ])
    else:
        requested_serial = summary.get("requested_serial")
        if requested_serial:
            lines.append(f"ADB was not run. Requested serial: {requested_serial}.")
        else:
            lines.append("ADB was not run, so no device identity was collected.")
        lines.append("")
    existing_locks = summary.get("existing_locks", [])
    if status == "blocked_device_coordination_lock" and isinstance(existing_locks, list):
        lines.extend([
            "## Device coordination locks",
            "",
        ])
        for lock in existing_locks:
            if isinstance(lock, dict):
                lines.append(f"- {lock.get('path', '')}: {lock.get('detail') or 'present'}")
        lines.append("")
    lines.extend(["## Stylus input devices", ""])
    if status == "blocked_device_coordination_lock":
        lines.append("No input-device snapshot was collected because ADB was not run.")
    elif not candidates:
        lines.append("No stylus candidate appeared in dumpsys input.")
    else:
        for candidate in candidates:
            assert isinstance(candidate, dict)
            lines.extend([
                f"- {candidate.get('name', '')}",
                f"  - Sources: {format_list(candidate.get('sources', []))}",
                f"  - Axes: {format_list(candidate.get('axes', []))}",
                f"  - Buttons: {format_list(candidate.get('buttons', []))}",
                f"  - Pass eligible: {'yes' if candidate_is_pass_eligible(candidate) else 'no'}",
            ])
    lines.extend([
        "",
        "## Evidence files",
        "",
        "- stylus-evidence.json: structured summary and status.",
        "- host-stylus.log: new Host log bytes from the passing observation window, required only for a passing physical drawing run.",
    ])
    if status != "blocked_device_coordination_lock":
        lines.extend([
            "- dumpsys-input.txt: raw read-only Android input-device snapshot.",
            "- android-diag.log: app private diagnostic log, present only when run-as succeeded and required for a passing physical drawing run.",
        ])
    lines.extend([
        "",
        "## Gate rule",
        "",
        "Do not close the physical-stylus drawing-app gate from device capability alone. A pass requires a real stylus contacting the Android device while the Protocol v1 session is active, host stylus injection logs for pressure/tilt/barrel/proximity as applicable, and a visible macOS drawing-app result.",
        "",
    ])
    return "\n".join(lines)


def format_list(value: object) -> str:
    if not isinstance(value, (list, tuple)):
        return "none"
    items = [str(item).strip() for item in value if str(item).strip()]
    return ", ".join(items) if items else "none"


def candidate_is_pass_eligible(candidate: dict[str, object]) -> bool:
    sources = {str(source) for source in candidate.get("sources", []) if str(source)}
    axes = {str(axis) for axis in candidate.get("axes", []) if str(axis)}
    return "STYLUS" in sources and all(axis in axes for axis in REQUIRED_STYLUS_AXES)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        lock_details = describe_device_locks()
        if lock_details and not args.allow_existing_device_lock:
            if args.write_blocked_on_lock:
                output_dir = create_output_dir(args.output_dir, {"model": args.serial, "device": "lock-blocked"})
                write_lock_blocked_evidence(output_dir, args, lock_details)
                print(f"blocked_device_coordination_lock: wrote {output_dir}")
                return 2
            raise EvidenceError(
                "device coordination lock exists; no ADB command was run: "
                + ", ".join(str(lock.get("path", "")) for lock in lock_details)
            )
        existing_locks = check_device_locks(args.allow_existing_device_lock)
        require_success(adb(args.adb, args.serial, "start-server", timeout=30))
        require_success(adb(args.adb, args.serial, "get-state"))
        identity = collect_device_identity(args.adb, args.serial)
        dumpsys_input = require_success(adb(args.adb, args.serial, "shell", "dumpsys", "input", timeout=60))
        candidates = select_stylus_candidates(parse_input_devices(dumpsys_input))
        diag_before = ""
        diag_before_error = None
        if args.observed_physical_drawing and not args.skip_diag_log:
            diag_before, diag_before_error = read_diag_log(args.adb, args.serial, args.package)
            if diag_before_error:
                raise EvidenceError("Android diag log is required for pass; run-as failed: " + diag_before_error)
        host_cursor = host_log_cursor(args.host_log) if args.observed_physical_drawing else None
        host_log_excerpt = wait_for_physical_drawing(args, host_cursor)
        diag_log = ""
        diag_error = None
        if not args.skip_diag_log:
            diag_log, diag_error = read_diag_log(args.adb, args.serial, args.package)
            if args.observed_physical_drawing and diag_error is None:
                diag_log = appended_diag_log(diag_before, diag_log)
            elif args.observed_physical_drawing and diag_error is not None and diag_before_error is None:
                raise EvidenceError("Android diag log is required for pass; run-as failed: " + diag_error)
        status = conclusion_status(args, candidates, diag_log, diag_error, host_log_excerpt)
        output_dir = create_output_dir(args.output_dir, identity)
        write_evidence(
            output_dir,
            args,
            existing_locks,
            identity,
            dumpsys_input,
            candidates,
            diag_log,
            diag_error,
            host_log_excerpt,
            status,
        )
    except EvidenceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"{status}: wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
