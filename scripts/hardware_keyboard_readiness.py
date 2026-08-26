#!/usr/bin/env python3
"""Collect Phase 2 hardware-keyboard readiness evidence.

The collector is intentionally fail-closed. It can prove current preconditions
and write a blocked or insufficient bundle, but it does not synthesize key input
or mark the hardware-keyboard workflow as accepted. A passing workflow still
requires a human-driven physical keyboard run with Android forwarding logs,
Host key-injection logs, and a visible Mac-side result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from vibescreen_evidence.hardware_keyboard import summarize  # noqa: E402

BLOCKED_EXIT = 2
DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_PORT = 54321
P0110_SERIAL = "EP0110PZ0B9110300B"
DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
REDACTED_DEVICE_SERIAL = "<device-serial>"
REDACTED_ADB_ENDPOINT = "<adb-endpoint>"
REDACTED_DEVICE_LOCK_PATH = "<device-lock>"
REDACTED_REPO_ROOT_PATH = "<repo-root>"
REDACTED_ANDROID_SDK_PATH = "<android-sdk>"
REDACTED_HOME_PATH = "<home>"
REDACTED_PYTHON_EXECUTABLE = "<python3.11>"
REDACTED_TMP_EVIDENCE_PATH = "<tmp-evidence>"
ANDROID_DUMPSYS_TOKEN_RE = re.compile(r"\b(?:applicationInfo\.)?token=(?:0x[0-9a-fA-F]+|<null>)")
TMP_EVIDENCE_PATH_RE = re.compile(r"/tmp/vibe-screen-[^\s\n]+")


class ReadinessError(Exception):
    pass


class DeviceCoordinationLockError(ReadinessError):
    pass


LOCAL_PATH_PATTERNS = (
    (re.compile(r"/Users/[^\s\n]+/Library/Android/sdk"), REDACTED_ANDROID_SDK_PATH),
    (re.compile(r"(?:/[^\s\n]+)*/python@3\.11/bin/python3\.11"), REDACTED_PYTHON_EXECUTABLE),
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class LockHandle:
    path: str | None
    acquired: bool
    existing_locks: list[dict[str, Any]]


@dataclass(frozen=True)
class DeviceIdentity:
    serial: str
    endpoint: str
    manufacturer: str
    model: str
    device: str
    product: str
    android_release: str
    sdk: str
    build_fingerprint: str
    abi: str
    device_serial: str


@dataclass(frozen=True)
class RedactedDeviceIdentity:
    serial: str
    endpoint: str
    manufacturer: str
    model: str
    device: str
    product: str
    android_release: str
    sdk: str
    build_fingerprint: str
    abi: str
    device_serial: str


@dataclass(frozen=True)
class PackageIdentity:
    package_name: str
    version_name: str
    version_code: int | None
    first_install_time: str
    last_update_time: str


@dataclass(frozen=True)
class InputDeviceSummary:
    name: str
    classes: str
    sources: str
    is_external: str
    descriptor: str


@dataclass(frozen=True)
class HostPreflight:
    listener_observed: bool
    signing_tcc_ready: bool
    listener_output: str
    codesign_identities_output: str
    preflight_output: str
    preflight_returncode: int


@dataclass(frozen=True)
class ReadinessResult:
    created_at: str
    device_lock: LockHandle
    device: RedactedDeviceIdentity | None
    package: PackageIdentity | None
    keyboard_devices: list[InputDeviceSummary]
    host: HostPreflight
    observations: dict[str, Any]
    summary: dict[str, Any]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_command(command: Sequence[str], *, timeout: float = 15.0) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command), check=False, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as error:
        raise ReadinessError(f"required command not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ReadinessError(f"command timed out: {' '.join(command)}") from error
    return CommandResult(list(command), completed.returncode, completed.stdout, completed.stderr)


def redact_evidence_text(value: str) -> str:
    redacted = value.replace(str(REPO_ROOT), REDACTED_REPO_ROOT_PATH)
    for pattern, replacement in LOCAL_PATH_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = re.sub(r"/Users/[^\s\n]+", "<user-home>", redacted)
    for user in {os.environ.get("USER"), os.environ.get("LOGNAME")}:
        if user:
            redacted = re.sub(rf"\b{re.escape(user)}\b", "<user>", redacted)
    return redacted


def adb(serial: str, args: Sequence[str], *, timeout: float = 15.0) -> CommandResult:
    result = run_command(["adb", "-s", serial, *args], timeout=timeout)
    if result.returncode != 0:
        raise ReadinessError(
            f"adb command failed ({result.returncode}): adb -s {serial} {' '.join(args)}\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )
    return result


def adb_shell(serial: str, *args: str, timeout: float = 15.0) -> str:
    return adb(serial, ["shell", *args], timeout=timeout).stdout.strip()


def describe_device_locks() -> list[dict[str, Any]]:
    descriptions: list[dict[str, Any]] = []
    for path in DEVICE_LOCKS:
        if not path.exists():
            continue
        try:
            stat = path.stat()
            descriptions.append(
                {
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "detail": redact_evidence_text(path.read_text(encoding="utf-8", errors="replace").strip()),
                }
            )
        except OSError as error:
            descriptions.append({"path": str(path), "read_error": str(error)})
    return descriptions


def acquire_device_lock(owner: str, *, allow_existing: bool) -> LockHandle:
    existing = describe_device_locks()
    if existing and not allow_existing:
        raise DeviceCoordinationLockError(
            "device coordination lock exists; no ADB command was run: "
            + ", ".join(str(lock.get("path", "")) for lock in existing)
        )
    if allow_existing:
        return LockHandle(None, True, existing)
    lock_path = DEVICE_LOCKS[-1]
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as error:
        raise DeviceCoordinationLockError(
            f"device coordination lock exists; no ADB command was run: {lock_path}"
        ) from error
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(
            f"owner={owner}\n"
            f"pid={os.getpid()}\n"
            f"worktree={redact_local_paths(str(Path.cwd()))}\n"
            f"created_at={utc_timestamp()}\n"
        )
    return LockHandle(str(lock_path), True, [])


def release_device_lock(handle: LockHandle) -> None:
    if handle.path is None:
        return
    try:
        Path(handle.path).unlink()
    except FileNotFoundError:
        return


def read_device_identity(serial: str) -> tuple[DeviceIdentity, str]:
    devices_text = adb(serial, ["devices", "-l"]).stdout
    endpoint = next(
        (line for line in devices_text.splitlines() if line.startswith(serial + "\t") or line.startswith(serial + " ")),
        serial,
    )
    return (
        DeviceIdentity(
            serial=serial,
            endpoint=endpoint,
            manufacturer=adb_shell(serial, "getprop", "ro.product.manufacturer"),
            model=adb_shell(serial, "getprop", "ro.product.model"),
            device=adb_shell(serial, "getprop", "ro.product.device"),
            product=adb_shell(serial, "getprop", "ro.product.name"),
            android_release=adb_shell(serial, "getprop", "ro.build.version.release"),
            sdk=adb_shell(serial, "getprop", "ro.build.version.sdk"),
            build_fingerprint=adb_shell(serial, "getprop", "ro.build.fingerprint"),
            abi=adb_shell(serial, "getprop", "ro.product.cpu.abi"),
            device_serial=adb_shell(serial, "getprop", "ro.serialno"),
        ),
        devices_text,
    )


def read_package_identity(serial: str, package_name: str) -> tuple[PackageIdentity | None, str]:
    result = adb(serial, ["shell", "dumpsys", "package", package_name], timeout=30.0)
    text_value = result.stdout
    if "Unable to find package" in text_value:
        return None, text_value

    def first(pattern: str) -> str:
        match = re.search(pattern, text_value)
        return match.group(1).strip() if match else ""

    raw_version_code = first(r"versionCode=([^\s]+)")
    version_code_match = re.match(r"(\d+)", raw_version_code)
    package = PackageIdentity(
        package_name=package_name,
        version_name=first(r"versionName=([^\s]+)"),
        version_code=int(version_code_match.group(1)) if version_code_match else None,
        first_install_time=first(r"firstInstallTime=([^\n]+)"),
        last_update_time=first(r"lastUpdateTime=([^\n]+)"),
    )
    return package, text_value


def parse_input_devices(dumpsys_input: str) -> list[InputDeviceSummary]:
    summaries: list[InputDeviceSummary] = []
    current_name: str | None = None
    current_classes = ""
    current_sources = ""
    current_external = "unknown"
    current_descriptor = ""

    def flush() -> None:
        nonlocal current_name, current_classes, current_sources, current_external, current_descriptor
        if current_name and (current_classes or current_sources):
            summaries.append(
                InputDeviceSummary(
                    name=current_name,
                    classes=current_classes,
                    sources=current_sources,
                    is_external=current_external,
                    descriptor=current_descriptor,
                )
            )
        current_name = None
        current_classes = ""
        current_sources = ""
        current_external = "unknown"
        current_descriptor = ""

    for raw_line in dumpsys_input.splitlines():
        line = raw_line.rstrip()
        event_hub = re.match(r"\s*-?\d+:\s*(.+)", line)
        reader = re.match(r"\s*Device\s+[^:]+:\s*(.+)", line)
        if event_hub or reader:
            flush()
            current_name = (event_hub or reader).group(1).strip()
            continue
        if current_name is None:
            continue
        classes = re.match(r"\s*Classes:\s*(.+)", line)
        if classes:
            current_classes = classes.group(1).strip()
            continue
        descriptor = re.match(r"\s*Descriptor:\s*(.+)", line)
        if descriptor:
            current_descriptor = descriptor.group(1).strip()
            continue
        external = re.match(r"\s*IsExternal:\s*(.+)", line)
        if external:
            current_external = external.group(1).strip()
            continue
        sources = re.match(r"\s*Sources:\s*(.+)", line)
        if sources:
            current_sources = sources.group(1).strip()
    flush()
    return summaries


def physical_keyboard_devices(devices: Sequence[InputDeviceSummary]) -> list[InputDeviceSummary]:
    keyboards: list[InputDeviceSummary] = []
    for device in devices:
        combined = f"{device.classes} {device.sources}".upper()
        is_external = device.is_external.lower() == "true"
        is_virtual = "VIRTUAL" in device.classes.upper() or device.name.lower() == "virtual"
        if is_external and not is_virtual and "KEYBOARD" in combined:
            keyboards.append(device)
    return keyboards


def package_identity_recorded(package: PackageIdentity | None) -> bool:
    return bool(
        package
        and package.version_name
        and package.version_code is not None
        and (package.first_install_time or package.last_update_time)
    )


def device_identity_matches_claim(serial: str, device: DeviceIdentity | None) -> bool:
    if device is None:
        return False
    if serial != P0110_SERIAL:
        return all((device.manufacturer, device.model, device.device, device.android_release, device.sdk))
    return is_nubia_p0110_android16(device)


def inspect_host(port: int, preflight_report: Path, *serials: str) -> HostPreflight:
    listener = run_command(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=10.0)
    identities = run_command(["security", "find-identity", "-v", "-p", "codesigning"], timeout=15.0)
    preflight = run_command(
        [sys.executable, str(REPO_ROOT / "scripts" / "macos_dev_host.py"), "preflight", "--report", str(preflight_report)],
        timeout=30.0,
    )
    listener_output = format_command_result(listener, *serials)
    identities_output = format_command_result(identities, *serials)
    preflight_output = format_command_result(preflight, *serials)
    return HostPreflight(
        listener_observed=listener.returncode == 0 and bool(listener.stdout.strip()),
        signing_tcc_ready=preflight.returncode == 0,
        listener_output=listener_output,
        codesign_identities_output=identities_output,
        preflight_output=preflight_output,
        preflight_returncode=preflight.returncode,
    )


def format_command_result(result: CommandResult, *serials: str) -> str:
    lines = [f"$ {redact_text(' '.join(result.command), *serials)}"]
    if result.stdout.strip():
        lines.append(redact_text(result.stdout.rstrip(), *serials))
    if result.stderr.strip():
        lines.append("stderr:")
        lines.append(redact_text(result.stderr.rstrip(), *serials))
    lines.append(f"exit_code={result.returncode}")
    return redact_evidence_text("\n".join(lines) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line.rstrip() for line in value.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    normalized = "\n".join(lines)
    if normalized:
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")


def redact_local_paths(value: str) -> str:
    redacted = value
    python_candidates = {sys.executable}
    try:
        python_candidates.add(str(Path(sys.executable).resolve()))
    except OSError:
        pass
    for python_path in sorted((path for path in python_candidates if path), key=len, reverse=True):
        redacted = redacted.replace(python_path, REDACTED_PYTHON_EXECUTABLE)
    for lock_path in DEVICE_LOCKS:
        redacted = redacted.replace(str(lock_path), REDACTED_DEVICE_LOCK_PATH)
    android_sdk_candidates = (
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    )
    for android_sdk in android_sdk_candidates:
        if android_sdk:
            redacted = redacted.replace(android_sdk, REDACTED_ANDROID_SDK_PATH)
    repo_root = str(REPO_ROOT)
    if repo_root:
        redacted = redacted.replace(repo_root, REDACTED_REPO_ROOT_PATH)
    redacted = TMP_EVIDENCE_PATH_RE.sub(REDACTED_TMP_EVIDENCE_PATH, redacted)
    home = str(Path.home())
    if home:
        redacted = redacted.replace(home, REDACTED_HOME_PATH)
    return redacted


def redact_text(value: str, *serials: str) -> str:
    redacted = value
    for serial in sorted(
        {serial for serial in serials if serial and serial != REDACTED_DEVICE_SERIAL},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(serial, REDACTED_DEVICE_SERIAL)
    return redact_lsof_user_columns(redact_local_paths(redacted))


def redact_android_dumpsys_text(value: str, *serials: str) -> str:
    redacted = redact_text(value, *serials)
    return ANDROID_DUMPSYS_TOKEN_RE.sub(lambda match: match.group(0).split("=", 1)[0] + "=<redacted>", redacted)


def redact_adb_devices_text(value: str, *serials: str) -> str:
    lines: list[str] = []
    for line in redact_text(value, *serials).splitlines():
        match = re.match(r"^(\S+)(\s+(?:device|offline|unauthorized)\b.*)$", line)
        if match and match.group(1) != REDACTED_DEVICE_SERIAL:
            line = REDACTED_ADB_ENDPOINT + match.group(2)
        lines.append(line)
    return "\n".join(lines)


def redact_lsof_user_columns(value: str) -> str:
    lines: list[str] = []
    lsof_table = False
    for line in value.splitlines():
        if re.match(r"^COMMAND\s+PID\s+USER\s+FD\s+TYPE", line):
            lsof_table = True
            lines.append(line)
            continue
        if lsof_table and line and not line.startswith(("$ ", "stderr:", "exit_code=")):
            columns = line.split(maxsplit=8)
            if len(columns) >= 9:
                columns[2] = "<user>"
                line = " ".join(columns)
        lines.append(line)
    return "\n".join(lines)


def redacted_lock_descriptions(locks: Sequence[dict[str, Any]], *serials: str) -> list[dict[str, Any]]:
    redacted_locks: list[dict[str, Any]] = []
    for lock in locks:
        redacted: dict[str, Any] = {}
        for key, value in lock.items():
            redacted[key] = redact_text(value, *serials) if isinstance(value, str) else value
        redacted_locks.append(redacted)
    return redacted_locks


def redacted_lock_handle(lock: LockHandle, *serials: str) -> LockHandle:
    return LockHandle(
        redact_text(lock.path, *serials) if lock.path else None,
        lock.acquired,
        redacted_lock_descriptions(lock.existing_locks, *serials),
    )


def redacted_device_identity(device: DeviceIdentity) -> RedactedDeviceIdentity:
    return RedactedDeviceIdentity(
        serial=REDACTED_DEVICE_SERIAL if device.serial else "",
        endpoint=redact_text(device.endpoint, device.serial, device.device_serial),
        manufacturer=device.manufacturer,
        model=device.model,
        device=device.device,
        product=device.product,
        android_release=device.android_release,
        sdk=device.sdk,
        build_fingerprint=device.build_fingerprint,
        abi=device.abi,
        device_serial=REDACTED_DEVICE_SERIAL if device.device_serial else "",
    )


def is_nubia_p0110_android16(device: DeviceIdentity) -> bool:
    return (
        device.manufacturer.lower() == "nubia"
        and device.model == "P0110"
        and device.device == "pacific"
        and device.android_release == "16"
        and device.sdk == "36"
    )


def device_info_document(
    *,
    created_at: str,
    connection: str,
    adb_version: str,
    device: RedactedDeviceIdentity,
    package: PackageIdentity | None,
) -> dict[str, Any]:
    try:
        sdk: int | str = int(device.sdk)
    except ValueError:
        sdk = device.sdk
    return {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "android_device_info",
        "collected_at": created_at,
        "connection": connection,
        "adb_version": redact_evidence_text(adb_version),
        "device": {
            "adb_serial": device.serial,
            "device_serial": device.device_serial,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "device": device.device,
            "product": device.product,
            "android_release": device.android_release,
            "sdk": sdk,
            "build_fingerprint": device.build_fingerprint,
            "abi": device.abi,
        },
        "packages": [
            {
                "package": package.package_name,
                "version_name": package.version_name or None,
                "version_code": package.version_code,
            }
        ]
        if package is not None
        else [],
    }


def build_observations(
    *,
    serial: str,
    lock_acquired: bool,
    device: DeviceIdentity | None,
    package: PackageIdentity | None,
    keyboard_devices: Sequence[InputDeviceSummary],
    host: HostPreflight,
    port: int,
) -> dict[str, Any]:
    notes: list[str] = []
    if device is None:
        notes.append("Android device identity was not collected.")
    elif is_nubia_p0110_android16(device):
        notes.append("Observed device must be recorded as nubia P0110 / pacific / Android 16, not another device identity or tablet hardware.")
    if not keyboard_devices:
        notes.append("No external Android-attached physical keyboard is visible in dumpsys input.")
    if not host.listener_observed:
        notes.append(f"No macOS Host listener was observed on TCP {port}.")
    if not host.signing_tcc_ready:
        notes.append("Stable signed Host Screen Recording/Accessibility readiness was not established by macOS Host preflight.")
    notes.append(
        "This readiness collector does not synthesize key events; a pass still requires physical key presses, "
        "an active selected-display stream, Android production forwarding/focus-boundary logs, Host key-injection "
        "or acknowledgement/CGEvent logs, modifier press/release and cleanup evidence, and a visible Mac-side result."
    )

    return {
        "run_id": utc_timestamp().replace(":", "").replace("-", ""),
        "android_device_lock_acquired": lock_acquired,
        "device_identity_recorded": device is not None,
        "device_identity_matches_claim": device_identity_matches_claim(serial, device),
        "apk_identity_recorded": package_identity_recorded(package),
        "physical_keyboard_attached": bool(keyboard_devices),
        "android_keyboard_source_observed": bool(keyboard_devices),
        "protocol_keyboard_capability_negotiated": False,
        "protocol_usb_hid_modifier_capability_negotiated": False,
        "android_production_forwarding_observed": False,
        "android_focus_ime_boundary_observed": False,
        "selected_display_stream_observed": False,
        "host_listener_observed": host.listener_observed,
        "host_stable_signed_tcc_ready": host.signing_tcc_ready,
        "host_key_injection_observed": False,
        "host_ack_cgevent_log_observed": False,
        "key_press_release_observed": False,
        "modifier_press_release_observed": False,
        "shortcut_combo_observed": False,
        "modifier_release_no_leak_observed": False,
        "visible_mac_result_observed": False,
        "host_logs_retained": False,
        "android_logs_retained": False,
        "artifact_paths": [
            "README.md",
            "hardware-keyboard-readiness.json",
            "hardware-keyboard-observations.json",
            "hardware-keyboard-summary.json",
            "device-lock.txt",
            "adb-devices.txt",
            "device-info.json",
            "dumpsys-input.txt",
            "dumpsys-package.txt",
            "host-listener.txt",
            "codesign-identities.txt",
            "host-preflight-command.txt",
            "host-signing-and-permissions.txt",
        ],
        "blocking_notes": notes,
        "notes": " ".join(notes),
    }


def write_readme(path: Path, result: ReadinessResult) -> None:
    summary = result.summary
    device_line = "Device: not collected"
    if result.device is not None:
        device_line = (
            f"Device: {result.device.manufacturer} {result.device.model} / "
            f"{result.device.device} / Android {result.device.android_release} / "
            f"SDK {result.device.sdk} / serial {result.device.serial}"
        )
    package_line = "APK: not observed"
    if result.package is not None:
        package_line = (
            f"APK: {result.package.package_name} "
            f"{result.package.version_name or 'unknown'} "
            f"({result.package.version_code or 'unknown versionCode'})"
        )
    lines = [
        f"# Phase 2 hardware-keyboard readiness: {summary['verdict']}",
        "",
        f"Created: {result.created_at}",
        f"Run ID: {summary['run_id']}",
        device_line,
        package_line,
        f"Android device lock acquired: {str(result.device_lock.acquired).lower()}",
        f"External keyboard devices visible: {len(result.keyboard_devices)}",
        f"Host listener observed: {str(result.host.listener_observed).lower()}",
        f"Stable signed/TCC Host ready: {str(result.host.signing_tcc_ready).lower()}",
        "",
        "## Keyboard devices",
        "",
    ]
    if result.keyboard_devices:
        for keyboard in result.keyboard_devices:
            lines.append(
                f"- {keyboard.name}: sources={keyboard.sources or 'unknown'}, "
                f"classes={keyboard.classes or 'unknown'}, descriptor={keyboard.descriptor or 'unknown'}"
            )
    else:
        lines.append("- none observed; synthetic ADB key events are not physical-keyboard evidence")
    lines.extend(["", "## Missing requirements", ""])
    if summary["missing_requirements"]:
        lines.extend(f"- {item['field']}: {item['requirement']}" for item in summary["missing_requirements"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Evidence files",
            "",
            "- hardware-keyboard-readiness.json: structured preflight snapshot.",
            "- hardware-keyboard-observations.json: boolean gate inputs for the summarizer.",
            "- hardware-keyboard-summary.json: fail-closed gate summary.",
            "- dumpsys-input.txt and adb-devices.txt: Android input and device snapshots when the lock allowed ADB.",
            "- host-listener.txt, codesign-identities.txt, host-preflight-command.txt, and host-signing-and-permissions.txt: Host preflight artifacts.",
            "",
            "This readiness bundle is not a hardware-keyboard workflow pass unless hardware-keyboard-summary.json has can_close_hardware_keyboard_gate=true.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def write_lock_blocked_evidence(evidence_dir: Path, *, serial: str, created_at: str, run_id: str, locks: Sequence[dict[str, Any]]) -> None:
    observations = {
        "run_id": run_id,
        "android_device_lock_acquired": False,
        "device_identity_recorded": False,
        "device_identity_matches_claim": False,
        "apk_identity_recorded": False,
        "physical_keyboard_attached": False,
        "android_keyboard_source_observed": False,
        "protocol_keyboard_capability_negotiated": False,
        "protocol_usb_hid_modifier_capability_negotiated": False,
        "android_production_forwarding_observed": False,
        "android_focus_ime_boundary_observed": False,
        "selected_display_stream_observed": False,
        "host_listener_observed": False,
        "host_stable_signed_tcc_ready": False,
        "host_key_injection_observed": False,
        "host_ack_cgevent_log_observed": False,
        "key_press_release_observed": False,
        "modifier_press_release_observed": False,
        "shortcut_combo_observed": False,
        "modifier_release_no_leak_observed": False,
        "visible_mac_result_observed": False,
        "host_logs_retained": False,
        "android_logs_retained": False,
        "artifact_paths": [
            "README.md",
            "device-locks.json",
            "hardware-keyboard-readiness.json",
            "hardware-keyboard-observations.json",
            "hardware-keyboard-summary.json",
        ],
        "blocking_notes": [
            "A shared Android device coordination lock existed before collection; no ADB command was run.",
            "Physical keyboard attachment, Host listener, and stable signed/TCC readiness were not evaluated after the lock block.",
        ],
        "notes": (
            f"Requested serial {REDACTED_DEVICE_SERIAL}. ADB was not run because a shared Android device coordination lock already exists. "
            "This blocked readiness record does not close the Phase 2 hardware-keyboard workflow gate."
        ),
    }
    summary = summarize(observations, run_id=run_id)
    host = HostPreflight(False, False, "not evaluated because device lock existed\n", "not evaluated because device lock existed\n", "not evaluated because device lock existed\n", 2)
    result = ReadinessResult(
        created_at=created_at,
        device_lock=LockHandle(None, False, redacted_lock_descriptions(locks, serial)),
        device=None,
        package=None,
        keyboard_devices=[],
        host=host,
        observations=observations,
        summary=summary,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_json(evidence_dir / "device-locks.json", redacted_lock_descriptions(locks, serial))
    write_json(evidence_dir / "hardware-keyboard-readiness.json", asdict(result))
    write_json(evidence_dir / "hardware-keyboard-observations.json", observations)
    write_json(evidence_dir / "hardware-keyboard-summary.json", summary)
    write_readme(evidence_dir / "README.md", result)


def collect_readiness(args: argparse.Namespace, *, created_at: str, run_id: str) -> ReadinessResult:
    lock = acquire_device_lock(args.lock_owner, allow_existing=args.allow_existing_device_lock)
    device: DeviceIdentity | None = None
    package: PackageIdentity | None = None
    keyboard_devices: list[InputDeviceSummary] = []
    host = HostPreflight(False, False, "", "", "", 1)
    try:
        device, adb_devices_text = read_device_identity(args.serial)
        dumpsys_input = adb(args.serial, ["shell", "dumpsys", "input"], timeout=30.0).stdout
        package, package_text = read_package_identity(args.serial, args.package)
        devices = parse_input_devices(dumpsys_input)
        keyboard_devices = physical_keyboard_devices(devices)
        host = inspect_host(args.port, args.evidence_dir / "host-signing-and-permissions.txt", device.serial, device.device_serial)

        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        write_text(
            args.evidence_dir / "device-lock.txt",
            redact_evidence_text(Path(lock.path).read_text(encoding="utf-8")) if lock.path else "existing lock allowed\n",
        )
        public_device = redacted_device_identity(device)
        write_text(args.evidence_dir / "adb-devices.txt", redact_adb_devices_text(adb_devices_text, device.serial, device.device_serial))
        write_json(
            args.evidence_dir / "device-info.json",
            device_info_document(
                created_at=created_at,
                connection=redact_text(f"already connected to {args.serial}", device.serial, device.device_serial),
                adb_version=redact_text(run_command(["adb", "version"], timeout=15.0).stdout.strip()),
                device=public_device,
                package=package,
            ),
        )
        write_text(args.evidence_dir / "dumpsys-input.txt", redact_android_dumpsys_text(dumpsys_input, device.serial, device.device_serial))
        write_text(args.evidence_dir / "dumpsys-package.txt", redact_text(package_text, device.serial, device.device_serial))
        write_text(args.evidence_dir / "host-listener.txt", host.listener_output)
        write_text(args.evidence_dir / "codesign-identities.txt", host.codesign_identities_output)
        write_text(args.evidence_dir / "host-preflight-command.txt", host.preflight_output)
        if (args.evidence_dir / "host-signing-and-permissions.txt").exists():
            write_text(
                args.evidence_dir / "host-signing-and-permissions.txt",
                redact_text(
                    (args.evidence_dir / "host-signing-and-permissions.txt").read_text(encoding="utf-8", errors="replace"),
                    device.serial,
                    device.device_serial,
                ),
            )
        else:
            write_text(
                args.evidence_dir / "host-signing-and-permissions.txt",
                "macOS Host preflight did not write a report. See host-preflight-command.txt for command output.\n",
            )
        observations = build_observations(
            serial=args.serial,
            lock_acquired=lock.acquired,
            device=device,
            package=package,
            keyboard_devices=keyboard_devices,
            host=host,
            port=args.port,
        )
        observations["run_id"] = run_id
        summary = summarize(observations, run_id=run_id)
        result = ReadinessResult(created_at, redacted_lock_handle(lock, device.serial, device.device_serial), public_device, package, keyboard_devices, host, observations, summary)
        write_json(args.evidence_dir / "hardware-keyboard-readiness.json", asdict(result))
        write_json(args.evidence_dir / "hardware-keyboard-observations.json", observations)
        write_json(args.evidence_dir / "hardware-keyboard-summary.json", summary)
        write_readme(args.evidence_dir / "README.md", result)
        return result
    finally:
        release_device_lock(lock)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB serial for the Android device under test.")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="Directory where readiness evidence files will be written.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help=f"Android package to inspect. Default: {DEFAULT_PACKAGE}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Host TCP listener port. Default: {DEFAULT_PORT}")
    parser.add_argument("--run-id", help="Identifier shared with the evidence bundle.")
    parser.add_argument("--lock-owner", default="phase2-hardware-keyboard-readiness", help="Owner string written to the Android device lock.")
    parser.add_argument("--allow-existing-device-lock", action="store_true", help="Continue despite an existing shared Android device lock. Use only when you own that lock.")
    parser.add_argument("--write-blocked-on-lock", action="store_true", help="When a shared Android device lock exists, write blocked evidence instead of running ADB.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.port <= 0:
        raise SystemExit("--port must be positive")
    created_at = utc_timestamp()
    run_id = args.run_id or created_at.replace(":", "").replace("-", "")
    try:
        try:
            result = collect_readiness(args, created_at=created_at, run_id=run_id)
        except DeviceCoordinationLockError as error:
            if not args.write_blocked_on_lock:
                raise
            locks = describe_device_locks()
            write_lock_blocked_evidence(
                args.evidence_dir,
                serial=args.serial,
                created_at=created_at,
                run_id=run_id,
                locks=locks,
            )
            print(str(error), file=sys.stderr)
            print("hardware keyboard readiness: blocked")
            print(f"summary: {args.evidence_dir / 'hardware-keyboard-summary.json'}")
            return BLOCKED_EXIT
        verdict = result.summary["verdict"]
        print(f"hardware keyboard readiness: {verdict}")
        print(f"summary: {args.evidence_dir / 'hardware-keyboard-summary.json'}")
        if verdict == "pass":
            return 0
        if verdict == "blocked":
            return BLOCKED_EXIT
        return 1
    except DeviceCoordinationLockError as error:
        print(str(error), file=sys.stderr)
        return BLOCKED_EXIT
    except ReadinessError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
