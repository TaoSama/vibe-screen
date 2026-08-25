#!/usr/bin/env python3
"""Collect controller runtime readiness evidence for Android -> macOS input.

This read-only preflight records whether the named Android device currently
exposes a physical gamepad/joystick source and whether Host-side evidence shows
an identity-signed, virtual-HID-entitled build with virtual gamepad runtime
availability. It does not install apps, clear app data, change ADB mappings, or
synthesize input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
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

from vibescreen_evidence.controller_runtime import summarize  # noqa: E402

BLOCKED_EXIT = 2
DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_HOST_LOG = Path.home() / "Library/Logs/Telemachus/telemachus.log"
DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
REDACTED_DEVICE_SERIAL = "<device-serial>"


class ReadinessError(Exception):
    pass


class DeviceCoordinationLockError(ReadinessError):
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
    classes: str
    sources: str
    is_external: str
    descriptor: str


@dataclass(frozen=True)
class PackageIdentity:
    package_name: str
    version_name: str
    version_code: str
    first_install_time: str
    last_update_time: str
    raw_summary: str


@dataclass(frozen=True)
class HostSigningStatus:
    host_app: str | None
    identity_signed: bool
    virtual_hid_entitlement_present: bool
    team_identifier: str
    codesign_summary: str
    entitlement_summary: str


@dataclass(frozen=True)
class HostAvailabilityStatus:
    host_log: str
    virtual_gamepad_available: bool
    last_controller_line: str
    unavailable_reason: str


@dataclass(frozen=True)
class ReadinessResult:
    created_at: str
    source_commit: str
    device: DeviceIdentity
    package: PackageIdentity
    controller_devices: list[InputDeviceSummary]
    host_signing: HostSigningStatus
    host_availability: HostAvailabilityStatus
    observations: dict[str, Any]
    summary: dict[str, Any]


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


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def redact_home_path(value: str) -> str:
    home = str(Path.home())
    if not home:
        return value
    return value.replace(home, "~")


def redact_device_serial(value: str, serial: str) -> str:
    if not serial:
        return value
    return value.replace(serial, REDACTED_DEVICE_SERIAL)


def redact_evidence_text(value: str, serial: str = "") -> str:
    return redact_device_serial(redact_home_path(value), serial)


def redacted_device_identity(device: DeviceIdentity, serial: str) -> DeviceIdentity:
    return DeviceIdentity(
        serial=REDACTED_DEVICE_SERIAL,
        endpoint=redact_device_serial(device.endpoint, serial),
        manufacturer=device.manufacturer,
        model=device.model,
        device=device.device,
        android_release=device.android_release,
        sdk=device.sdk,
        fingerprint_sha256=device.fingerprint_sha256,
        display_size=device.display_size,
        display_density=device.display_density,
        battery_summary=device.battery_summary,
        boot_completed=device.boot_completed,
    )


def redacted_locks(locks: Sequence[dict[str, Any]], serial: str) -> list[dict[str, Any]]:
    sanitized = []
    for lock in locks:
        sanitized.append(
            {key: redact_evidence_text(str(value), serial) for key, value in lock.items()}
        )
    return sanitized


def read_source_commit() -> str:
    result = run_command(["git", "rev-parse", "HEAD"], timeout=10.0)
    if result.returncode != 0:
        raise ReadinessError(
            "failed to read source commit with git rev-parse HEAD: "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def describe_device_locks() -> list[dict[str, Any]]:
    descriptions: list[dict[str, Any]] = []
    for path in DEVICE_LOCKS:
        if not path.exists():
            continue
        try:
            stat = path.stat()
            detail = path.read_text(encoding="utf-8", errors="replace").strip()
            descriptions.append(
                {
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "detail": detail,
                }
            )
        except OSError as error:
            descriptions.append({"path": str(path), "read_error": str(error)})
    return descriptions


def enforce_device_lock_policy(allow_existing: bool) -> list[dict[str, Any]]:
    locks = describe_device_locks()
    if locks and not allow_existing:
        raise DeviceCoordinationLockError(
            "device coordination lock exists; no ADB command was run: "
            + ", ".join(str(lock.get("path", "")) for lock in locks)
        )
    return locks


def read_device_identity(serial: str) -> tuple[DeviceIdentity, str]:
    devices_text = adb(serial, ["devices", "-l"]).stdout
    devices = devices_text.splitlines()
    endpoint = next(
        (line for line in devices if line.startswith(serial + "\t") or line.startswith(serial + " ")),
        serial,
    )
    fingerprint = adb_shell(serial, "getprop", "ro.build.fingerprint")
    battery = adb_shell(serial, "dumpsys", "battery", timeout=20.0)
    battery_lines = [line.strip() for line in battery.splitlines() if line.strip()]
    return (
        DeviceIdentity(
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
        ),
        devices_text,
    )


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
                    current_name,
                    current_classes,
                    current_sources,
                    current_external,
                    current_descriptor,
                )
            )
        current_name = None
        current_classes = ""
        current_sources = ""
        current_external = "unknown"
        current_descriptor = ""

    for raw_line in dumpsys_input.splitlines():
        line = raw_line.rstrip()
        event_hub = re.match(r"\s*\d+:\s*(.+)", line)
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


def physical_controller_devices(devices: Sequence[InputDeviceSummary]) -> list[InputDeviceSummary]:
    candidates = []
    for device in devices:
        combined = f"{device.classes} {device.sources}".upper()
        external = device.is_external.lower() == "true"
        not_virtual = "VIRTUAL" not in device.classes.upper() and device.name.lower() != "virtual"
        if external and not_virtual and ("GAMEPAD" in combined or "JOYSTICK" in combined):
            candidates.append(device)
    return candidates


def read_package_identity(serial: str, package_name: str) -> tuple[PackageIdentity, str]:
    result = adb(serial, ["shell", "dumpsys", "package", package_name], timeout=30.0)
    text_value = result.stdout

    def first(pattern: str) -> str:
        match = re.search(pattern, text_value)
        return match.group(1).strip() if match else ""

    summary_lines = [
        line.strip()
        for line in text_value.splitlines()
        if any(
            marker in line
            for marker in (
                "versionName=",
                "versionCode=",
                "firstInstallTime=",
                "lastUpdateTime=",
                "PackageSignatures",
                "SigningInfo",
            )
        )
    ]
    return (
        PackageIdentity(
            package_name=package_name,
            version_name=first(r"versionName=([^\s]+)"),
            version_code=first(r"versionCode=([^\s]+)"),
            first_install_time=first(r"firstInstallTime=([^\n]+)"),
            last_update_time=first(r"lastUpdateTime=([^\n]+)"),
            raw_summary="\n".join(summary_lines),
        ),
        text_value,
    )


def package_identity_recorded(package: PackageIdentity) -> bool:
    return bool(
        package.version_name
        and package.version_code
        and (package.first_install_time or package.last_update_time)
    )


def inspect_host_signing(host_app: Path | None) -> HostSigningStatus:
    if host_app is None:
        return HostSigningStatus(None, False, False, "", "host app path not provided", "host app path not provided")
    if not host_app.exists():
        return HostSigningStatus(
            redact_home_path(str(host_app)),
            False,
            False,
            "",
            "host app path does not exist",
            "host app path does not exist",
        )
    signature = run_command(["codesign", "-dv", "--verbose=4", str(host_app)], timeout=20.0)
    codesign_text = signature.stdout + signature.stderr
    team_match = re.search(r"^TeamIdentifier=(.+)$", codesign_text, re.MULTILINE)
    team_identifier = team_match.group(1).strip() if team_match else ""
    identity_signed = signature.returncode == 0 and bool(team_identifier) and team_identifier != "not set"
    entitlements = run_command(["codesign", "-d", "--entitlements", ":-", str(host_app)], timeout=20.0)
    entitlement_text = entitlements.stdout + entitlements.stderr
    entitlement_present = virtual_hid_entitlement_present(entitlement_text)
    return HostSigningStatus(
        redact_home_path(str(host_app)),
        identity_signed,
        entitlement_present,
        team_identifier,
        redact_home_path(codesign_text.strip()),
        redact_home_path(entitlement_text.strip()),
    )


def virtual_hid_entitlement_present(entitlement_text: str) -> bool:
    plist_start = entitlement_text.find("<plist")
    plist_end = entitlement_text.find("</plist>")
    if plist_start == -1 or plist_end == -1:
        return False
    plist_xml = entitlement_text[plist_start : plist_end + len("</plist>")]
    try:
        entitlements = plistlib.loads(plist_xml.encode("utf-8"))
    except Exception:
        return False
    return entitlements.get("com.apple.developer.hid.virtual.device") is True


def tail_file(path: Path, max_bytes: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def inspect_host_availability(host_log: Path, max_bytes: int) -> HostAvailabilityStatus:
    log_tail = tail_file(host_log, max_bytes)
    last_line = ""
    unavailable_reason = ""
    available = False
    pattern = re.compile(r"Controller forwarding (?P<status>available|unavailable)(?:: (?P<reason>.*))?")
    for line in log_tail.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        last_line = line.strip()
        available = match.group("status") == "available"
        unavailable_reason = "" if available else (match.group("reason") or "unavailable").strip()
    return HostAvailabilityStatus(redact_home_path(str(host_log)), available, last_line, unavailable_reason)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_result(
    *,
    run_id: str,
    created_at: str,
    device: DeviceIdentity,
    package: PackageIdentity,
    controller_devices: list[InputDeviceSummary],
    host_signing: HostSigningStatus,
    host_availability: HostAvailabilityStatus,
    source_commit: str = "",
) -> ReadinessResult:
    observations = {
        "device_identity_recorded": True,
        "apk_identity_recorded": package_identity_recorded(package),
        "physical_controller_attached": bool(controller_devices),
        "android_controller_source_observed": bool(controller_devices),
        "protocol_controller_capability_negotiated": False,
        "android_production_forwarding_observed": False,
        "controller_connected_state_disconnected_observed": False,
        "host_identity_signed": host_signing.identity_signed,
        "host_virtual_hid_entitlement_present": host_signing.virtual_hid_entitlement_present,
        "host_virtual_gamepad_available": host_availability.virtual_gamepad_available,
        "mac_side_controller_response_observed": False,
        "neutral_release_on_disconnect_observed": False,
        "artifact_paths": [
            "README.md",
            "docs/testing.md",
            "docs/runbook/android-client.md",
            "docs/runbook/macos-host.md",
            "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/ControllerInputMapper.kt",
            "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/StreamInputDispatcher.kt",
            "baseline/MacHost/Sources/GameControllerVirtualHID.swift",
            "baseline/MacHost/Sources/GameControllerInput.swift",
        ],
    }
    notes = []
    if not controller_devices:
        notes.append("No physical Android gamepad/joystick source is visible in dumpsys input.")
    if host_availability.last_controller_line:
        notes.append(f"Latest Host controller availability line: {host_availability.last_controller_line}")
    if not host_signing.host_app:
        notes.append("No Host .app path was supplied, so signed entitlement status is recorded as unavailable.")
    notes.append(
        "This is readiness evidence only; a pass still requires live controller samples, "
        "Protocol v1 controller negotiation, Mac-side response, and neutral release on disconnect."
    )
    record = dict(observations)
    record["notes"] = " ".join(notes)
    summary = summarize(record, run_id=run_id)
    return ReadinessResult(
        created_at,
        source_commit,
        device,
        package,
        controller_devices,
        host_signing,
        host_availability,
        observations,
        summary,
    )


def write_readme(path: Path, result: ReadinessResult) -> None:
    summary = result.summary
    lines = [
        f"# Controller runtime readiness: {summary['verdict']}",
        "",
        f"Created: {result.created_at}",
        f"Run ID: {summary['run_id']}",
        f"Source commit: {result.source_commit}",
        (
            f"Device: {result.device.manufacturer} {result.device.model} / "
            f"{result.device.device} / Android {result.device.android_release} / "
            f"SDK {result.device.sdk} / serial {result.device.serial}"
        ),
        (
            f"APK: {result.package.package_name} {result.package.version_name or 'unknown'} "
            f"({result.package.version_code or 'unknown versionCode'})"
        ),
        f"Physical controller devices: {len(result.controller_devices)}",
        f"Host identity signed: {str(result.host_signing.identity_signed).lower()}",
        f"Host virtual HID entitlement: {str(result.host_signing.virtual_hid_entitlement_present).lower()}",
        f"Host virtual gamepad available: {str(result.host_availability.virtual_gamepad_available).lower()}",
        "",
        "## Missing requirements",
        "",
    ]
    if summary["missing_requirements"]:
        lines.extend(f"- {item['field']}: {item['requirement']}" for item in summary["missing_requirements"])
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Notes",
        "",
        result.summary.get("notes", "") or "No additional notes.",
        "",
        "This readiness bundle is not a controller runtime pass unless "
        "controller-runtime-summary.json has can_close_runtime_gate=true.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_lock_blocked_evidence(
    evidence_dir: Path,
    *,
    requested_serial: str,
    created_at: str,
    source_commit: str,
    run_id: str,
    locks: Sequence[dict[str, Any]],
    redact_identifiers: bool = False,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    safe_locks = redacted_locks(locks, requested_serial) if redact_identifiers else list(locks)
    safe_serial = REDACTED_DEVICE_SERIAL if redact_identifiers else requested_serial
    observations = {
        "notes": (
            "ADB was not run because a shared Android device coordination lock already exists. "
            "This is readiness evidence only; a pass still requires live controller samples, "
            "Protocol v1 controller negotiation, Mac-side response, and neutral release on disconnect."
        ),
        "artifact_paths": [
            "scripts/controller_runtime_readiness.py",
            "docs/runbook/controller-runtime-acceptance.md",
            "docs/testing.md",
        ],
    }
    summary = summarize(observations, run_id=run_id)
    write_json(evidence_dir / "controller-runtime-observations.json", observations)
    write_json(evidence_dir / "controller-runtime-summary.json", summary)
    write_json(
        evidence_dir / "controller-runtime-readiness.json",
        {
            "created_at": created_at,
            "source_commit": source_commit,
            "requested_serial": safe_serial,
            "lock_blocked": True,
            "existing_locks": safe_locks,
            "observations": observations,
            "summary": summary,
        },
    )
    write_json(evidence_dir / "device-locks.json", safe_locks)
    lines = [
        "# Controller runtime readiness: blocked",
        "",
        f"Created: {created_at}",
        f"Run ID: {run_id}",
        f"Source commit: {source_commit}",
        f"Requested serial: {safe_serial}",
        "",
        "## Blocking condition",
        "",
        "A shared Android device coordination lock existed before collection, so no ADB command was run.",
        "",
        "## Device coordination locks",
        "",
    ]
    for lock in locks:
        detail = str(lock.get("detail") or lock.get("read_error") or "present")
        lines.append(f"- {lock.get('path', '')}: {detail}")
    lines.extend(
        [
            "",
            "## Evidence files",
            "",
            "- controller-runtime-readiness.json: structured lock-blocked readiness state.",
            "- controller-runtime-observations.json: boolean gate inputs; missing runtime observations remain false.",
            "- controller-runtime-summary.json: gate summary from vibescreen_evidence.controller_runtime.",
            "- device-locks.json: lock paths and contents that blocked ADB use.",
            "",
            "This readiness bundle is not a controller runtime pass unless controller-runtime-summary.json has can_close_runtime_gate=true.",
        ]
    )
    (evidence_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB serial for the Android device under test.")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="Directory where readiness evidence files will be written.",
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help=f"Android package to inspect. Default: {DEFAULT_PACKAGE}",
    )
    parser.add_argument(
        "--host-log",
        type=Path,
        default=DEFAULT_HOST_LOG,
        help=f"Host log to inspect for controller availability. Default: {DEFAULT_HOST_LOG}",
    )
    parser.add_argument("--host-app", type=Path, help="Optional Host .app or executable path to inspect with codesign.")
    parser.add_argument(
        "--max-host-log-bytes",
        type=int,
        default=200_000,
        help="Maximum trailing Host log bytes to scan for controller availability.",
    )
    parser.add_argument("--run-id", help="Identifier shared with the evidence manifest.")
    parser.add_argument(
        "--source-commit",
        help="Git commit recorded as the source under test. Defaults to the current HEAD.",
    )
    parser.add_argument(
        "--redact-identifiers",
        action="store_true",
        help="Redact persistent device identifiers and local HOME paths in committed evidence files.",
    )
    parser.add_argument(
        "--allow-existing-device-lock",
        action="store_true",
        help="Continue despite a shared Android device coordination lock. Use only when you own that lock.",
    )
    parser.add_argument(
        "--write-blocked-on-lock",
        action="store_true",
        help="When a shared Android device lock exists, write blocked readiness evidence instead of running ADB.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.max_host_log_bytes <= 0:
        raise SystemExit("--max-host-log-bytes must be positive")
    created_at = utc_timestamp()
    run_id = args.run_id or created_at.replace(":", "").replace("-", "")
    try:
        source_commit = args.source_commit or read_source_commit()
        try:
            enforce_device_lock_policy(args.allow_existing_device_lock)
        except DeviceCoordinationLockError as error:
            if not args.write_blocked_on_lock:
                raise
            locks = describe_device_locks()
            write_lock_blocked_evidence(
                args.evidence_dir,
                requested_serial=args.serial,
                created_at=created_at,
                source_commit=source_commit,
                run_id=run_id,
                locks=locks,
                redact_identifiers=args.redact_identifiers,
            )
            print(str(error), file=sys.stderr)
            print("controller runtime readiness: blocked")
            print(f"summary: {args.evidence_dir / 'controller-runtime-summary.json'}")
            return BLOCKED_EXIT
        device, adb_devices_text = read_device_identity(args.serial)
        dumpsys_input = adb(args.serial, ["shell", "dumpsys", "input"], timeout=30.0).stdout
        package, package_raw = read_package_identity(args.serial, args.package)
        input_devices = parse_input_devices(dumpsys_input)
        controller_devices = physical_controller_devices(input_devices)
        host_signing = inspect_host_signing(args.host_app)
        host_availability = inspect_host_availability(args.host_log, args.max_host_log_bytes)
        evidence_device = redacted_device_identity(device, args.serial) if args.redact_identifiers else device
        result = build_result(
            run_id=run_id,
            created_at=created_at,
            source_commit=source_commit,
            device=evidence_device,
            package=package,
            controller_devices=controller_devices,
            host_signing=host_signing,
            host_availability=host_availability,
        )

        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.evidence_dir / "controller-runtime-readiness.json", asdict(result))
        write_json(args.evidence_dir / "device-info.json", asdict(result.device))
        observation_record = dict(result.observations)
        observation_record["notes"] = result.summary["notes"]
        observation_record["artifact_paths"] = result.summary["artifact_paths"]
        write_json(args.evidence_dir / "controller-runtime-observations.json", observation_record)
        write_json(args.evidence_dir / "controller-runtime-summary.json", result.summary)
        safe_adb_devices_text = (
            redact_device_serial(adb_devices_text, args.serial)
            if args.redact_identifiers
            else adb_devices_text
        )
        (args.evidence_dir / "adb-devices.txt").write_text(
            safe_adb_devices_text, encoding="utf-8"
        )
        (args.evidence_dir / "dumpsys-input.txt").write_text(dumpsys_input, encoding="utf-8")
        (args.evidence_dir / "dumpsys-package.txt").write_text(package_raw, encoding="utf-8")
        (args.evidence_dir / "host-controller-availability.txt").write_text(
            (host_availability.last_controller_line or "no controller availability line found") + "\n",
            encoding="utf-8",
        )
        if host_signing.codesign_summary or host_signing.entitlement_summary:
            (args.evidence_dir / "host-codesign.txt").write_text(
                host_signing.codesign_summary
                + "\n\n--- entitlements ---\n"
                + host_signing.entitlement_summary
                + "\n",
                encoding="utf-8",
            )
        write_readme(args.evidence_dir / "README.md", result)

        verdict = result.summary["verdict"]
        print(f"controller runtime readiness: {verdict}")
        print(f"summary: {args.evidence_dir / 'controller-runtime-summary.json'}")
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
