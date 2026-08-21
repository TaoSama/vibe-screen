"""Collect the read-only preflight state for a short Android USB smoke.

The collector is intentionally side-effect-light: it checks local lock files,
the explicit Android serial, ADB reverse state, the Android app process/window,
the local Host listener, and the stable-signed macOS Host preflight. It does
not launch the Host, change ADB reverse mappings, modify TCC, or touch
Keychain state.
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError


DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_PORT = 54321
DEFAULT_LOCK_GLOB = "/tmp/vibe-screen-*.lock"

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ProbeResult:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr, self.error or "") if part).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


def _run(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
    command_runner: CommandRunner = subprocess.run,
) -> ProbeResult:
    command_list = list(command)
    try:
        completed = command_runner(
            command_list,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )
    except FileNotFoundError:
        return ProbeResult(command_list, None, "", "", f"executable not found: {command_list[0]}")
    except subprocess.TimeoutExpired as error:
        return ProbeResult(
            command_list,
            None,
            error.stdout or "",
            error.stderr or "",
            f"timed out after {timeout_seconds:g}s",
        )
    except OSError as error:
        return ProbeResult(command_list, None, "", "", f"could not start command: {error}")
    return ProbeResult(
        command_list,
        completed.returncode,
        completed.stdout.strip(),
        completed.stderr.strip(),
    )


def collect_locks(lock_globs: Sequence[str]) -> list[str]:
    locks: list[str] = []
    for pattern in lock_globs:
        locks.extend(glob.glob(pattern))
    return sorted(set(locks))


def _identity_mismatches(device: dict[str, Any], expected: dict[str, str | None]) -> list[str]:
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        if expected_value is None:
            continue
        actual = str(device.get(field, ""))
        if actual != expected_value:
            mismatches.append(f"device {field} is '{actual}', expected '{expected_value}'")
    return mismatches


def collect_device(
    *,
    serial: str,
    adb_path: str,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any] | None, list[str]]:
    client = ADBClient(
        serial,
        adb_path=adb_path,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    try:
        client.require_device()
        return client.identity(), []
    except (ADBError, ValueError) as error:
        return None, [f"Android device probe failed: {error}"]


def collect_reverse(
    *,
    serial: str,
    adb_path: str,
    port: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    result = _run(
        [adb_path, "-s", serial, "reverse", "--list"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    expected = f"tcp:{port}"
    configured = result.returncode == 0 and any(
        expected in line and line.count(expected) >= 2 for line in result.stdout.splitlines()
    )
    blockers: list[str] = []
    if result.returncode != 0 or result.error:
        blockers.append(f"ADB reverse state could not be read: {result.combined_output or 'no output'}")
    elif not configured:
        blockers.append(f"ADB reverse {expected} -> {expected} is not configured for {serial}")
    return {"configured": configured, "probe": result.as_dict()}, blockers


def collect_android_app_state(
    *,
    serial: str,
    adb_path: str,
    package_name: str,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    pidof = _run(
        [adb_path, "-s", serial, "shell", "pidof", package_name],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    window = _run(
        [adb_path, "-s", serial, "shell", "dumpsys", "window"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    pids = [int(item) for item in pidof.stdout.split() if item.isdigit()] if pidof.returncode == 0 else []
    focus_lines = [
        line.strip()
        for line in window.stdout.splitlines()
        if "mCurrentFocus" in line or "mFocusedApp" in line
    ]
    foreground = any(package_name in line for line in focus_lines)
    blockers: list[str] = []
    if pidof.returncode not in (0, 1) or pidof.error:
        blockers.append(f"Android app process state could not be read: {pidof.combined_output or 'no output'}")
    elif not pids:
        blockers.append(f"Android app process is not running: {package_name}")
    if window.returncode != 0 or window.error:
        blockers.append(f"Android foreground window could not be read: {window.combined_output or 'no output'}")
    elif not foreground:
        blockers.append(f"Android app is not foreground: {package_name}")
    return {
        "package": package_name,
        "running": bool(pids),
        "pids": pids,
        "foreground": foreground,
        "focus_lines": focus_lines,
        "pidof": pidof.as_dict(),
        "window_probe": {
            "command": window.command,
            "returncode": window.returncode,
            "focus_lines": focus_lines,
            "error": window.error,
        },
    }, blockers


def collect_host_listener(
    *,
    port: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    result = _run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    listening = result.returncode == 0 and bool(result.stdout.strip())
    blockers: list[str] = []
    if result.returncode not in (0, 1) or result.error:
        blockers.append(f"Mac Host listener state could not be read: {result.combined_output or 'no output'}")
    elif not listening:
        blockers.append(f"Mac Host is not listening on TCP {port}")
    return {"listening": listening, "probe": result.as_dict()}, blockers


def collect_host_preflight(
    *,
    repository_root: Path,
    report_path: Path | None,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    if report_path is None:
        temporary_directory = tempfile.TemporaryDirectory()
        report_path = Path(temporary_directory.name) / "host-signing-and-permissions.txt"
    command = [sys.executable, "scripts/macos_dev_host.py", "preflight", "--report", str(report_path)]
    result = _run(command, timeout_seconds=timeout_seconds, cwd=repository_root, command_runner=command_runner)
    report_text = ""
    report_exists = report_path.exists()
    if report_exists:
        report_text = report_path.read_text(encoding="utf-8")
    if temporary_directory is not None:
        temporary_directory.cleanup()
    blockers: list[str] = []
    if result.returncode != 0 or result.error:
        detail = (result.combined_output or report_text or "no output").splitlines()[0]
        blockers.append(f"macOS Host stable-signing/TCC preflight failed: {detail}")
    return {
        "passed": result.returncode == 0 and result.error is None,
        "probe": result.as_dict(),
        "report_path": str(report_path),
        "report_exists": report_exists,
        "report_excerpt": report_text[:4000],
    }, blockers


def build_document(
    *,
    serial: str,
    repository_root: Path,
    adb_path: str,
    adb_timeout: float,
    host_preflight_timeout: float,
    package_name: str,
    port: int,
    lock_globs: Sequence[str],
    expected_device: dict[str, str | None],
    host_preflight_report: Path | None,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    blockers: list[str] = []
    locks = collect_locks(lock_globs)
    if locks:
        blockers.append("device lease lock is present; do not probe or start a competing run")

    device: dict[str, Any] | None = None
    reverse: dict[str, Any] | None = None
    android_app: dict[str, Any] | None = None
    if locks:
        device_blockers = ["Android probes skipped because a device lease lock is present"]
    else:
        device, device_blockers = collect_device(
            serial=serial,
            adb_path=adb_path,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
        if device is not None:
            device_blockers.extend(_identity_mismatches(device, expected_device))
            reverse, reverse_blockers = collect_reverse(
                serial=serial,
                adb_path=adb_path,
                port=port,
                timeout_seconds=adb_timeout,
                command_runner=command_runner,
            )
            android_app, app_blockers = collect_android_app_state(
                serial=serial,
                adb_path=adb_path,
                package_name=package_name,
                timeout_seconds=adb_timeout,
                command_runner=command_runner,
            )
            blockers.extend(reverse_blockers)
            blockers.extend(app_blockers)
    blockers.extend(device_blockers)

    host_listener: dict[str, Any] | None = None
    listener_blockers: list[str] = []
    if locks:
        listener_blockers.append("Mac Host listener probe skipped because a device lease lock is present")
    else:
        host_listener, listener_blockers = collect_host_listener(
            port=port,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
    host_preflight, preflight_blockers = collect_host_preflight(
        repository_root=repository_root,
        report_path=host_preflight_report,
        timeout_seconds=host_preflight_timeout,
        command_runner=command_runner,
    )
    blockers.extend(listener_blockers)
    blockers.extend(preflight_blockers)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_smoke_preflight",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "result": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "serial": serial,
        "expected_device": expected_device,
        "lock_globs": list(lock_globs),
        "locks": locks,
        "android_device": device,
        "android_app": android_app,
        "adb_reverse": reverse,
        "host_listener": host_listener,
        "host_preflight": host_preflight,
        "safety": {
            "read_only": True,
            "starts_host": False,
            "changes_adb_reverse": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android_app_data": False,
        },
    }


def write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--host-preflight-timeout", type=float, default=60.0)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--lock-glob", action="append", default=[DEFAULT_LOCK_GLOB])
    parser.add_argument("--expected-manufacturer")
    parser.add_argument("--expected-model")
    parser.add_argument("--expected-device")
    parser.add_argument("--expected-android-release")
    parser.add_argument("--host-preflight-report", type=Path)
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    if arguments.host_preflight_timeout <= 0:
        parser.error("--host-preflight-timeout must be positive")
    if arguments.port <= 0 or arguments.port > 65535:
        parser.error("--port must be in 1..65535")

    output = arguments.output
    host_report = arguments.host_preflight_report
    if host_report is None and output is not None:
        host_report = output.parent / "host-signing-and-permissions.txt"

    expected_device = {
        "manufacturer": arguments.expected_manufacturer,
        "model": arguments.expected_model,
        "device": arguments.expected_device,
        "android_release": arguments.expected_android_release,
    }
    document = build_document(
        serial=arguments.serial,
        repository_root=arguments.repository_root.resolve(),
        adb_path=arguments.adb,
        adb_timeout=arguments.adb_timeout,
        host_preflight_timeout=arguments.host_preflight_timeout,
        package_name=arguments.package,
        port=arguments.port,
        lock_globs=arguments.lock_glob,
        expected_device=expected_device,
        host_preflight_report=host_report,
    )
    write_json(output, document)
    return 0 if document["result"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
