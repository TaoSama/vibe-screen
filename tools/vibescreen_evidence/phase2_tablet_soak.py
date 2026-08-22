"""Orchestrate Phase 2 tablet sustained-use evidence collection.

The full gate still requires a real eight-hour run on a physical 8-9 inch
tablet. This runner makes that run reproducible and writes blocked/readiness
evidence when the current host/device state cannot legitimately start it.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
from typing import Any, Callable, Sequence
import uuid

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError
from .manifest import ManifestError
from .phase2_tablet_gate import derive_gate
from .phase2_tablet_manifest import build_manifest
from .soak import SoakRunner, parse_duration
from .soak_report import derive_report


SOAK_LOCK = Path("/tmp/vibe-screen-device-soak.lock")
ANDROID_LOCK = Path("/tmp/vibe-screen-device-android.lock")
DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_SOAK_DURATION_SECONDS = 8 * 60 * 60.0
DEFAULT_PREFLIGHT_DURATION_SECONDS = 2.0
DEFAULT_INTERVAL_SECONDS = 30.0
DEFAULT_HOST_RSS_SOURCE = "soak --host-pid sampling via ps -o rss="
DEFAULT_ANDROID_PSS_SOURCE = "ADB dumpsys meminfo app TOTAL PSS"
BLOCKED_EXIT = 2
READY_EXIT = 0


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Phase2SoakError(RuntimeError):
    """Raised when evidence orchestration cannot continue."""


class NullContext:
    def __enter__(self) -> "NullContext":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = "\n".join(line.rstrip() for line in content.splitlines()) + ("\n" if content.endswith("\n") else "")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: Sequence[str],
    *,
    timeout_seconds: float = 20.0,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CommandResult:
    try:
        completed = command_runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CommandResult(124, "", str(error))
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def write_command_output(
    command: Sequence[str],
    stdout_path: Path,
    *,
    stderr_path: Path | None = None,
    timeout_seconds: float = 20.0,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    result = run_command(command, timeout_seconds=timeout_seconds, command_runner=command_runner)
    write_text(stdout_path, result.stdout)
    if stderr_path is not None:
        write_text(stderr_path, result.stderr)
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path) if stderr_path is not None else None,
    }


def existing_locks(paths: Sequence[Path] | None = None) -> list[dict[str, Any]]:
    if paths is None:
        paths = (SOAK_LOCK, ANDROID_LOCK)
    locks: list[dict[str, Any]] = []
    for path in paths:
        try:
            stat = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            locks.append({"path": str(path), "detail": "unreadable: " + str(error)})
            continue
        detail = None
        if path.is_file():
            try:
                detail = path.read_text(encoding="utf-8", errors="replace")[:1000]
            except OSError as error:
                detail = "present but unreadable: " + str(error)
        locks.append({"path": str(path), "mode": oct(stat.st_mode & 0o777), "detail": detail})
    return locks


class DeviceLock:
    def __init__(self, path: Path, *, owner: dict[str, Any]) -> None:
        self.path = path
        self.owner = owner
        self.acquired = False

    def __enter__(self) -> "DeviceLock":
        payload = json.dumps(self.owner, indent=2, sort_keys=True) + "\n"
        descriptor = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self.acquired:
            return
        try:
            current = self.path.read_text(encoding="utf-8")
        except OSError:
            current = ""
        expected = json.dumps(self.owner, indent=2, sort_keys=True) + "\n"
        if current == expected:
            self.path.unlink(missing_ok=True)


def copy_optional_log(source: Path | None, destination: Path, artifacts: list[dict[str, Any]]) -> None:
    if source is None:
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        artifacts.append({"path": destination.name, "kind": "host_log_copy"})
    except OSError:
        return


def write_log_derivatives(raw_logcat: Path, output_dir: Path) -> dict[str, int]:
    try:
        lines = raw_logcat.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    telemetry: list[str] = []
    reconnects: list[str] = []
    drops: list[str] = []
    for line in lines:
        if "VibeScreenTelemetry" in line:
            match = re.search(r"(\{.*\})", line)
            if match:
                telemetry.append(match.group(1))
        lowered = line.lower()
        if any(token in lowered for token in ("reconnect", "connection_closed", "heartbeat_timeout")):
            reconnects.append(line)
        if any(token in lowered for token in ("frame_dropped", "dropping frame", "dropped=")):
            drops.append(line)
    write_text(output_dir / "decoder-telemetry.jsonl", "\n".join(telemetry) + ("\n" if telemetry else ""))
    write_text(output_dir / "reconnects.log", "\n".join(reconnects) + ("\n" if reconnects else ""))
    write_text(output_dir / "frame-drops.log", "\n".join(drops) + ("\n" if drops else ""))
    return {
        "telemetry_events": len(telemetry),
        "reconnect_log_lines": len(reconnects),
        "frame_drop_log_lines": len(drops),
    }


def collect_static_artifacts(
    *,
    output_dir: Path,
    serial: str,
    adb_path: str,
    adb_timeout: float,
    host_pid: int | None,
    package_name: str,
    apk: Path | None,
    apk_sha256: str | None,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]], str | None]:
    errors: list[str] = []
    artifacts: list[dict[str, Any]] = []
    client = ADBClient(serial, adb_path=adb_path, timeout_seconds=adb_timeout, command_runner=command_runner)
    device_info: dict[str, Any] | None = None
    try:
        from .device_info import collect_device_info

        device_info = collect_device_info(client, packages=[package_name])
        write_json(output_dir / "device-info.json", device_info)
        artifacts.append({"path": "device-info.json", "kind": "device_info"})
    except (ADBError, OSError, ValueError) as error:
        errors.append("device-info: " + str(error))

    adb_commands = [
        (("shell", "getprop"), "device.txt", None),
        (("shell", "wm", "size"), "wm-size.txt", None),
        (("shell", "wm", "density"), "wm-density.txt", None),
        (("shell", "dumpsys", "battery"), "adb-battery-before.txt", None),
        (("shell", "dumpsys", "power"), "adb-power-before.txt", None),
        (("shell", "dumpsys", "thermalservice"), "thermal-before.txt", "thermal-before.err"),
        (("shell", "pidof", package_name), "android-pid.txt", None),
    ]
    for arguments, stdout_name, stderr_name in adb_commands:
        command = [adb_path, "-s", serial, *arguments]
        record = write_command_output(
            command,
            output_dir / stdout_name,
            stderr_path=output_dir / stderr_name if stderr_name else None,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
        artifacts.append({"path": stdout_name, "kind": "raw_adb", "returncode": record["returncode"]})
        if stderr_name:
            artifacts.append({"path": stderr_name, "kind": "raw_adb_stderr"})
        if record["returncode"] != 0 and stdout_name != "android-pid.txt":
            errors.append(stdout_name + ": " + shlex.join(command) + " exited " + str(record["returncode"]))

    host_lines = [
        "collected_at=" + utc_now(),
        "platform=" + platform.platform(),
        "machine=" + platform.machine(),
        "host_pid=" + (str(host_pid) if host_pid is not None else "not provided"),
    ]
    if host_pid is not None:
        ps = run_command(["ps", "-p", str(host_pid), "-o", "pid=,comm="], command_runner=command_runner)
        host_lines.append("ps_returncode=" + str(ps.returncode))
        host_lines.append(ps.stdout.strip())
        if ps.returncode != 0:
            errors.append("host-pid: process " + str(host_pid) + " is not visible")
    write_text(output_dir / "host.txt", "\n".join(line for line in host_lines if line) + "\n")
    artifacts.append({"path": "host.txt", "kind": "host_identity"})

    if apk is not None:
        try:
            apk_sha256 = sha256_file(apk)
            write_text(output_dir / "apk-sha256.txt", apk_sha256 + "  " + str(apk) + "\n")
        except OSError as error:
            errors.append("apk-sha256: " + str(error))
    elif apk_sha256 is not None:
        write_text(output_dir / "apk-sha256.txt", apk_sha256 + "\n")
    if apk_sha256:
        artifacts.append({"path": "apk-sha256.txt", "kind": "android_artifact"})
    write_text(output_dir / "build.txt", "command=" + shlex.join(sys.argv) + "\n" + "cwd=" + str(Path.cwd()) + "\n")
    artifacts.append({"path": "build.txt", "kind": "command"})
    return device_info, errors, artifacts, apk_sha256


def record_missing_apk_identity(output_dir: Path, artifacts: list[dict[str, Any]]) -> None:
    write_text(
        output_dir / "apk-identity-missing.txt",
        "APK identity was not provided; preflight evidence is readiness-only and cannot close the Phase 2 gate.\n",
    )
    artifacts.append({"path": "apk-identity-missing.txt", "kind": "android_artifact_missing"})


def collect_after_artifacts(
    *,
    output_dir: Path,
    serial: str,
    adb_path: str,
    adb_timeout: float,
    package_name: str,
    artifacts: list[dict[str, Any]],
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[str]:
    errors: list[str] = []
    adb_commands = [
        (("shell", "dumpsys", "battery"), "adb-battery-after.txt", None),
        (("shell", "dumpsys", "power"), "adb-power-after.txt", None),
        (("shell", "dumpsys", "thermalservice"), "thermal-after.txt", "thermal-after.err"),
        (("shell", "pidof", package_name), "android-pid-after.txt", None),
    ]
    for arguments, stdout_name, stderr_name in adb_commands:
        command = [adb_path, "-s", serial, *arguments]
        record = write_command_output(
            command,
            output_dir / stdout_name,
            stderr_path=output_dir / stderr_name if stderr_name else None,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
        artifacts.append({"path": stdout_name, "kind": "raw_adb", "returncode": record["returncode"]})
        if stderr_name:
            artifacts.append({"path": stderr_name, "kind": "raw_adb_stderr"})
        if record["returncode"] != 0 and stdout_name != "android-pid-after.txt":
            errors.append(stdout_name + ": " + shlex.join(command) + " exited " + str(record["returncode"]))
    return errors


def append_preflight_blockers(
    blockers: list[str],
    *,
    device_class: str,
    device_info: dict[str, Any] | None,
    host_pid: int | None,
    telemetry_jsonl: Path | None,
) -> None:
    if device_info is None:
        blockers.append("ADB device identity could not be collected")
    if device_class != "physical_8_9_inch_tablet":
        blockers.append("device_class is not physical_8_9_inch_tablet, so this run cannot close the tablet hardware gate")
    if host_pid is None:
        blockers.append("host PID was not provided, so Host RSS cannot be sampled")
    if telemetry_jsonl is None:
        blockers.append("host telemetry JSONL path was not provided")
    elif not telemetry_jsonl.exists():
        blockers.append("host telemetry JSONL does not exist yet; start the Host with VIBE_SCREEN_TELEMETRY_PATH before the formal run")


def start_logcat(serial: str, adb_path: str, output: Path) -> tuple[subprocess.Popen[str] | None, Any | None]:
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command([adb_path, "-s", serial, "logcat", "-c"], timeout_seconds=10)
    handle = output.open("w", encoding="utf-8")
    command = [
        adb_path,
        "-s",
        serial,
        "logcat",
        "-v",
        "time",
        "VibeScreenTelemetry:I",
        "Telemachus:I",
        "VibeScreen:I",
        "AndroidRuntime:E",
        "*:S",
    ]
    try:
        return subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, text=True), handle
    except OSError:
        handle.close()
        return None, None


def stop_process(process: subprocess.Popen[str] | None, handle: Any | None) -> None:
    if process is not None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    if handle is not None:
        handle.close()


def write_readme(output_dir: Path, readiness: dict[str, Any]) -> None:
    lines = [
        "# Phase 2 tablet soak " + str(readiness["mode"]),
        "",
        "Result: " + str(readiness["result"]) + ".",
        "",
        "This evidence record does not close the Phase 2 eight-hour tablet gate unless phase2-soak-readiness.json reports can_close_phase2_gate=true and the raw physical-tablet artifacts are present. Preflight records do not include a formal soak-8h/phase2-tablet-gate.json pass artifact. Missing or invalid APK identity is readiness-only blocker context, not formal APK pass evidence.",
        "",
        "## Command",
        "",
        "    " + shlex.join(readiness.get("command", [])),
        "",
        "## Blockers",
    ]
    blockers = readiness.get("blockers", [])
    if blockers:
        lines.extend("- " + str(item) for item in blockers)
    else:
        lines.append("- None recorded by the readiness runner.")
    log_metrics = readiness.get("android_log_metrics", {})
    if log_metrics:
        lines.extend(["", "## Android Log Metrics"])
        for key in ("telemetry_events", "reconnect_log_lines", "frame_drop_log_lines"):
            if key in log_metrics:
                lines.append("- " + key + ": " + str(log_metrics[key]))
    lines.extend(["", "## Artifacts"])
    for artifact in readiness.get("artifacts", []):
        lines.append("- " + str(artifact.get("path")))
    lines.append("")
    write_text(output_dir / "README.md", "\n".join(lines))


def build_readiness(
    *,
    mode: str,
    command: Sequence[str],
    output_dir: Path,
    device_class: str,
    blockers: Sequence[str],
    artifacts: Sequence[dict[str, Any]],
    soak_summary: dict[str, Any] | None,
    gate: dict[str, Any] | None,
    android_log_metrics: dict[str, int] | None = None,
) -> dict[str, Any]:
    result = "blocked" if blockers else ("pass" if gate and gate.get("verdict") == "pass" else "ready")
    if mode == "run" and gate is not None and gate.get("verdict") != "pass":
        result = "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "phase2_tablet_soak_readiness",
        "run_id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "mode": mode,
        "command": list(command),
        "output_dir": str(output_dir),
        "device_class": device_class,
        "result": result,
        "can_close_phase2_gate": bool(gate and gate.get("verdict") == "pass" and not blockers),
        "blockers": list(blockers),
        "artifacts": list(artifacts),
        "soak_summary_status": soak_summary.get("status") if soak_summary else None,
        "phase2_gate_verdict": gate.get("verdict") if gate else None,
        "android_log_metrics": android_log_metrics or {},
    }


def build_blocked_on_lock_readiness(
    *,
    arguments: argparse.Namespace,
    command: Sequence[str],
    locks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    blockers = ["device coordination lock exists; no ADB command was run"]
    artifacts = [
        {"path": str(lock.get("path", "")), "kind": "blocking_lock"}
        for lock in locks
    ]
    readiness = build_readiness(
        mode=arguments.mode,
        command=command,
        output_dir=arguments.output_dir,
        device_class=arguments.device_class,
        blockers=blockers,
        artifacts=artifacts,
        soak_summary=None,
        gate=None,
        android_log_metrics=None,
    )
    write_json(arguments.output_dir / "phase2-soak-readiness.json", readiness)
    write_readme(arguments.output_dir, readiness)
    return readiness


def acquire_device_locks(owner: dict[str, Any]) -> ExitStack:
    stack = ExitStack()
    try:
        for lock_path in (ANDROID_LOCK, SOAK_LOCK):
            stack.enter_context(DeviceLock(lock_path, owner=owner))
    except Exception:
        stack.close()
        raise
    return stack


def is_sha256_digest(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-fA-F]{64}", value.strip()))


def runner_required_artifacts(mode: str, *, has_apk_identity: bool = True) -> list[str]:
    apk_artifact = "apk-sha256.txt" if has_apk_identity else "apk-identity-missing.txt"
    if mode == "preflight":
        return [
            "README.md",
            "phase2-soak-readiness.json",
            "phase2-tablet-manifest.json",
            "device-info.json",
            "device.txt",
            "host.txt",
            "build.txt",
            apk_artifact,
            "soak-preflight/samples.jsonl",
            "soak-preflight/summary.json",
            "adb-battery-before.txt",
            "adb-battery-after.txt",
            "adb-power-before.txt",
            "adb-power-after.txt",
            "thermal-before.txt",
            "thermal-before.err",
            "thermal-after.txt",
            "thermal-after.err",
            "raw-logcat.txt",
            "reconnects.log",
            "frame-drops.log",
            "decoder-telemetry.jsonl",
        ]
    return [
        "README.md",
        "phase2-soak-readiness.json",
        "phase2-tablet-manifest.json",
        "device-info.json",
        "device.txt",
        "host.txt",
        "build.txt",
        "apk-sha256.txt",
        "soak-8h/samples.jsonl",
        "soak-8h/summary.json",
        "soak-8h/host-telemetry.jsonl",
        "soak-8h/exact-window-report.json",
        "soak-8h/phase2-tablet-gate.json",
        "adb-battery-before.txt",
        "adb-battery-after.txt",
        "adb-power-before.txt",
        "adb-power-after.txt",
        "thermal-before.txt",
        "thermal-before.err",
        "thermal-after.txt",
        "thermal-after.err",
        "raw-logcat.txt",
        "reconnects.log",
        "frame-drops.log",
        "decoder-telemetry.jsonl",
    ]


def run_or_preflight(arguments: argparse.Namespace, command: Sequence[str]) -> dict[str, Any]:
    output_dir = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    artifacts: list[dict[str, Any]] = []
    device_info: dict[str, Any] | None = None
    soak_summary: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
    android_log_metrics: dict[str, int] = {}

    owner = {"pid": os.getpid(), "serial": arguments.serial, "created_at": utc_now(), "output_dir": str(output_dir)}
    if arguments.allow_existing_device_lock:
        lock_context = NullContext()
    else:
        # Acquire both coordination locks in a consistent order so no other
        # Android operation can interleave before the first ADB command.
        try:
            lock_context = acquire_device_locks(owner)
        except FileExistsError:
            return build_blocked_on_lock_readiness(
                arguments=arguments,
                command=command,
                locks=existing_locks(),
            )

    with lock_context:
        apk_sha256_argument = arguments.apk_sha256.strip() if arguments.apk_sha256 is not None else None
        has_valid_apk_sha256_argument = is_sha256_digest(apk_sha256_argument)
        missing_apk_identity = arguments.apk is None and not has_valid_apk_sha256_argument
        if missing_apk_identity:
            if apk_sha256_argument:
                blockers.append("--apk-sha256 must be a 64-character hexadecimal digest")
            else:
                blockers.append("APK identity was not provided; preflight cannot close the Phase 2 gate")
        device_info, setup_errors, setup_artifacts, apk_sha256 = collect_static_artifacts(
            output_dir=output_dir,
            serial=arguments.serial,
            adb_path=arguments.adb,
            adb_timeout=arguments.adb_timeout,
            host_pid=arguments.host_pid,
            package_name=arguments.package,
            apk=arguments.apk,
            apk_sha256=apk_sha256_argument if has_valid_apk_sha256_argument else None,
        )
        blockers.extend(setup_errors)
        artifacts.extend(setup_artifacts)
        if arguments.mode == "preflight" and apk_sha256 is None:
            record_missing_apk_identity(output_dir, artifacts)
        append_preflight_blockers(
            blockers,
            device_class=arguments.device_class,
            device_info=device_info,
            host_pid=arguments.host_pid,
            telemetry_jsonl=arguments.host_telemetry_jsonl,
        )
        if device_info is not None:
            try:
                manifest = build_manifest(
                    command=command,
                    repo=arguments.repo,
                    device_info=device_info,
                    device_class=arguments.device_class,
                    tablet_size_inches=arguments.tablet_size_inches,
                    stand_setup=arguments.stand_setup,
                    charger=arguments.charger,
                    cable_or_dock=arguments.cable_or_dock,
                    ambient_temperature_celsius=arguments.ambient_temperature_celsius,
                    transport=arguments.transport,
                    video_preferences=arguments.video_preferences,
                    duration_seconds=int(arguments.duration),
                    sample_interval_seconds=int(arguments.interval),
                    host_pid=arguments.host_pid,
                    host_rss_source=DEFAULT_HOST_RSS_SOURCE,
                    android_pss_source=DEFAULT_ANDROID_PSS_SOURCE,
                    require_host_pid=arguments.mode == "run",
                    thermal_limit_status=arguments.thermal_limit_status,
                    battery_temperature_limit_celsius=arguments.battery_temperature_limit_celsius,
                    maximum_net_battery_drain_percent=arguments.maximum_net_battery_drain_percent,
                    recovery_scenarios=[item.strip() for item in arguments.recovery_scenarios.split(",") if item.strip()],
                    host_identity=arguments.host_identity,
                    host_build=arguments.host_build,
                    apk_sha256=apk_sha256,
                    notes=arguments.notes,
                )
                manifest["required_artifacts"] = runner_required_artifacts(
                    arguments.mode,
                    has_apk_identity=apk_sha256 is not None,
                )
                write_json(output_dir / "phase2-tablet-manifest.json", manifest)
                artifacts.append({"path": "phase2-tablet-manifest.json", "kind": "phase2_manifest"})
            except (ManifestError, OSError, ValueError) as error:
                blockers.append("phase2-tablet-manifest: " + str(error))

        if arguments.mode != "run" or not blockers:
            soak_dir = output_dir / ("soak-8h" if arguments.mode == "run" else "soak-preflight")
            logcat, logcat_handle = start_logcat(arguments.serial, arguments.adb, output_dir / "raw-logcat.txt")
            logcat_started = logcat is not None and logcat_handle is not None
            if not logcat_started:
                blockers.append("logcat capture failed to start; Android logcat evidence is unavailable")
            try:
                if arguments.mode != "run" or logcat_started:
                    runner = SoakRunner(
                        ADBClient(arguments.serial, adb_path=arguments.adb, timeout_seconds=arguments.adb_timeout),
                        duration_seconds=arguments.duration if arguments.mode == "run" else arguments.preflight_duration,
                        interval_seconds=arguments.interval,
                        output_jsonl=soak_dir / "samples.jsonl",
                        summary_json=soak_dir / "summary.json",
                        package_name=arguments.package,
                        host_pid=arguments.host_pid,
                        telemetry_jsonl=arguments.host_telemetry_jsonl,
                        require_stream_telemetry=arguments.mode == "run",
                        run_id=manifest.get("run_id") if manifest else None,
                    )
                    soak_summary = runner.run()
                    artifacts.extend([
                        {"path": str(soak_dir.relative_to(output_dir) / "samples.jsonl"), "kind": "soak_samples"},
                        {"path": str(soak_dir.relative_to(output_dir) / "summary.json"), "kind": "soak_summary"},
                    ])
                    if soak_summary.get("status") != "complete":
                        message = "short soak/preflight did not complete cleanly" if arguments.mode != "run" else "eight-hour soak did not complete cleanly"
                        blockers.append(message)
                    if arguments.mode == "run" and arguments.host_telemetry_jsonl is not None:
                        try:
                            report = derive_report(
                                soak_dir / "summary.json",
                                soak_dir / "samples.jsonl",
                                arguments.host_telemetry_jsonl,
                            )
                            write_json(soak_dir / "exact-window-report.json", report)
                            gate = derive_gate(
                                soak_dir / "exact-window-report.json",
                                manifest_path=output_dir / "phase2-tablet-manifest.json",
                                evidence_dir=output_dir,
                            )
                            write_json(soak_dir / "phase2-tablet-gate.json", gate)
                            artifacts.extend([
                                {"path": str(soak_dir.relative_to(output_dir) / "exact-window-report.json"), "kind": "soak_report"},
                                {"path": str(soak_dir.relative_to(output_dir) / "phase2-tablet-gate.json"), "kind": "phase2_gate"},
                            ])
                            if gate.get("verdict") != "pass":
                                blockers.append("phase2 tablet gate verdict was " + str(gate.get("verdict")))
                        except (OSError, ValueError) as error:
                            blockers.append("phase2 tablet gate derivation failed: " + str(error))
            finally:
                stop_process(logcat, logcat_handle)
                android_log_metrics = write_log_derivatives(output_dir / "raw-logcat.txt", output_dir)
                artifacts.extend([
                    {"path": "raw-logcat.txt", "kind": "android_logcat"},
                    {"path": "decoder-telemetry.jsonl", "kind": "android_telemetry"},
                    {"path": "reconnects.log", "kind": "android_log_filter"},
                    {"path": "frame-drops.log", "kind": "android_log_filter"},
                ])
                copy_optional_log(arguments.host_log, output_dir / "host.log", artifacts)
                blockers.extend(
                    collect_after_artifacts(
                        output_dir=output_dir,
                        serial=arguments.serial,
                        adb_path=arguments.adb,
                        adb_timeout=arguments.adb_timeout,
                        package_name=arguments.package,
                        artifacts=artifacts,
                        command_runner=subprocess.run,
                    )
                )
    readiness = build_readiness(
        mode=arguments.mode,
        command=command,
        output_dir=output_dir,
        device_class=arguments.device_class,
        blockers=blockers,
        artifacts=artifacts,
        soak_summary=soak_summary,
        gate=gate,
        android_log_metrics=android_log_metrics,
    )
    write_json(output_dir / "phase2-soak-readiness.json", readiness)
    write_readme(output_dir, readiness)
    return readiness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["preflight", "run"], default="preflight")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--host-pid", type=int)
    parser.add_argument("--host-telemetry-jsonl", type=Path)
    parser.add_argument("--host-log", type=Path)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--apk-sha256")
    parser.add_argument("--device-class", required=True, choices=["physical_8_9_inch_tablet", "android_substitute"])
    parser.add_argument("--tablet-size-inches")
    parser.add_argument("--stand-setup", required=True)
    parser.add_argument("--charger", required=True)
    parser.add_argument("--cable-or-dock", required=True)
    parser.add_argument("--ambient-temperature-celsius", type=float)
    parser.add_argument("--transport", choices=["usb", "lan"], default="usb")
    parser.add_argument("--video-preferences", required=True)
    parser.add_argument("--host-identity", required=True)
    parser.add_argument("--host-build", required=True)
    parser.add_argument("--duration", type=parse_duration, default=DEFAULT_SOAK_DURATION_SECONDS)
    parser.add_argument("--preflight-duration", type=parse_duration, default=DEFAULT_PREFLIGHT_DURATION_SECONDS)
    parser.add_argument("--interval", type=parse_duration, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--thermal-limit-status", type=int, default=2)
    parser.add_argument("--battery-temperature-limit-celsius", type=float)
    parser.add_argument("--maximum-net-battery-drain-percent", type=int)
    parser.add_argument("--recovery-scenarios", default="")
    parser.add_argument("--notes")
    parser.add_argument("--allow-existing-device-lock", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    if arguments.host_pid is not None and arguments.host_pid <= 0:
        parser.error("--host-pid must be positive")
    if arguments.interval < 1 or arguments.interval > 60:
        parser.error("--interval must be between 1s and 60s for Phase 2 evidence")
    if arguments.mode == "run" and arguments.apk is None and not is_sha256_digest(arguments.apk_sha256):
        parser.error("formal --apk-sha256 must be a 64-character hexadecimal digest")
    command = [sys.executable, "-m", "vibescreen_evidence.phase2_tablet_soak", *(argv or sys.argv[1:])]
    try:
        readiness = run_or_preflight(arguments, command)
    except (OSError, ValueError, Phase2SoakError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(readiness, sort_keys=True, allow_nan=False))
    if readiness["can_close_phase2_gate"]:
        return 0
    return BLOCKED_EXIT if readiness["result"] == "blocked" else READY_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
