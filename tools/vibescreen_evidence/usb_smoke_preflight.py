"""Collect fail-closed readiness for a short Android USB smoke run.

The preflight checks only whether prerequisites are already in place. It does
not install or launch Android, start the Host, create ADB reverse mappings,
modify TCC, or touch Keychain state. A blocked result is useful evidence, but it
is not a USB stream pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import getpass
import glob
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError
from .usb_live_smoke_summary import (
    DEFAULT_PORT,
    parse_adb_reverse,
    parse_foreground_state,
    parse_package_metadata,
    parse_pids,
)


DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_LOCK_GLOB = "/tmp/vibe-screen-*.lock"
DEFAULT_SERIAL_LABEL = "REDACTED_P0110_USB_SERIAL"
DEFAULT_EXPECTED_DEVICE = {
    "manufacturer": "nubia",
    "model": "P0110",
    "device": "pacific",
    "android_release": "16",
    "sdk": "36",
}
TCC_DIRECTORY_COMPONENTS = ("Application " + "Support", "com.apple" + ".TCC")
TCC_DATABASE_NAME = "TCC" + ".db"
HOST_LISTENER_PROCESS_MARKERS = ("vibe screen", "telemachus")

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
        return "\n".join(
            part for part in (self.stdout, self.stderr, self.error or "") if part
        ).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_probe(
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
        return ProbeResult(
            command_list, None, "", "", f"executable not found: {command_list[0]}"
        )
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


def collect_locks(lock_globs: Sequence[str], held_locks: Sequence[str] = ()) -> list[str]:
    held = {str(Path(lock).resolve()) for lock in held_locks}
    locks: list[str] = []
    for pattern in lock_globs:
        for match in glob.glob(pattern):
            if str(Path(match).resolve()) not in held:
                locks.append(match)
    return sorted(set(locks))


def collect_device(
    *,
    serial: str,
    adb_path: str,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
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
        return None, [blocker("android_device.state", f"Android device probe failed: {error}")]


def collect_reverse(
    *,
    serial: str,
    adb_path: str,
    port: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    result = run_probe(
        [adb_path, "-s", serial, "reverse", "--list"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    parsed = parse_adb_reverse(result.stdout, port=port) if result.returncode == 0 else None
    blockers: list[dict[str, str]] = []
    if result.returncode != 0 or result.error:
        blockers.append(
            blocker(
                "adb_reverse.probe",
                f"ADB reverse state could not be read: {result.combined_output or 'no output'}",
            )
        )
    elif parsed is not None and not parsed["present"]:
        blockers.append(
            blocker(
                "adb_reverse.present",
                f"ADB reverse tcp:{port} -> tcp:{port} is not configured for {serial}",
            )
        )
    return {
        "configured": bool(parsed and parsed["present"]),
        "parsed": parsed,
        "probe": result.as_dict(),
    }, blockers


def parse_lsof_listener_pids(output: str) -> list[int]:
    pids: list[int] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] == "COMMAND" or not fields[1].isdigit():
            continue
        pids.append(int(fields[1]))
    return sorted(set(pids))


def host_process_identity_matches(text: str) -> bool:
    normalized = text.replace("\\x20", " ").lower()
    return any(marker in normalized for marker in HOST_LISTENER_PROCESS_MARKERS)


def collect_listener_processes(
    pids: Sequence[int],
    *,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for pid in pids:
        result = run_probe(
            ["ps", "-p", str(pid), "-o", "comm="],
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        identity_text = "\n".join(
            part for part in (result.stdout, result.stderr, result.error or "") if part
        )
        processes.append(
            {
                "pid": pid,
                "matches_host_identity": host_process_identity_matches(identity_text),
                "probe": result.as_dict(),
            }
        )
    return processes


def collect_android_app_state(
    *,
    serial: str,
    adb_path: str,
    package_name: str,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    client = ADBClient(
        serial,
        adb_path=adb_path,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    errors: list[dict[str, str]] = []
    package = collect_optional(
        "android_app.package",
        errors,
        lambda: parse_package_metadata(
            client.shell("dumpsys", "package", package_name), package_name
        ),
    )
    pids = collect_optional(
        "android_app.pids",
        errors,
        lambda: parse_pids(client.shell("pidof", package_name)),
    )
    foreground = collect_optional(
        "android_app.foreground",
        errors,
        lambda: parse_foreground_state(
            client.shell("dumpsys", "window"),
            client.shell("dumpsys", "activity", "activities"),
            package_name,
        ),
    )
    blockers = list(errors)
    if package is not None and not package["installed"]:
        blockers.append(
            blocker(
                "android_app.package.installed",
                f"Android package is not installed: {package_name}",
            )
        )
    if pids is not None and not pids:
        blockers.append(
            blocker(
                "android_app.pids",
                f"Android app process is not running: {package_name}",
            )
        )
    if foreground is not None and not foreground["foreground"]:
        blockers.append(
            blocker(
                "android_app.foreground",
                f"Android app is not foreground: {package_name}",
            )
        )
    return {
        "package": package,
        "pids": pids or [],
        "running": bool(pids),
        "foreground": foreground,
    }, blockers


def collect_host_listener(
    *,
    port: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    result = run_probe(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    pids = parse_lsof_listener_pids(result.stdout) if result.returncode == 0 else []
    processes = collect_listener_processes(
        pids,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    host_owned = any(process["matches_host_identity"] for process in processes)
    blockers: list[dict[str, str]] = []
    if result.returncode not in (0, 1) or result.error:
        blockers.append(
            blocker(
                "host.listener.probe",
                "Mac Host listener state could not be read: "
                f"{result.combined_output or 'no output'}",
            )
        )
    elif not pids:
        blockers.append(blocker("host.listener", f"Mac Host is not listening on TCP {port}"))
    elif not host_owned:
        blockers.append(
            blocker(
                "host.listener.process",
                f"TCP {port} listener is not owned by Vibe Screen or Telemachus",
            )
        )
    return {
        "listening": bool(pids),
        "host_owned": host_owned,
        "pids": pids,
        "processes": processes,
        "probe": result.as_dict(),
    }, blockers


def collect_host_preflight(
    *,
    repository_root: Path,
    report_path: Path,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    command = [
        sys.executable,
        "scripts/macos_dev_host.py",
        "preflight",
        "--report",
        str(report_path),
    ]
    result = run_probe(
        command,
        timeout_seconds=timeout_seconds,
        cwd=repository_root,
        command_runner=command_runner,
    )
    report_text = ""
    report_exists = report_path.exists()
    if report_exists:
        report_text = report_path.read_text(encoding="utf-8", errors="replace")
    blockers: list[dict[str, str]] = []
    if result.returncode != 0 or result.error:
        detail = first_line(result.combined_output or report_text or "no output")
        blockers.append(
            blocker(
                "host.preflight",
                f"macOS Host stable-signing/TCC preflight failed: {detail}",
            )
        )
    return {
        "passed": result.returncode == 0 and result.error is None,
        "probe": result.as_dict(),
        "report_path": str(report_path),
        "report_exists": report_exists,
        "report_excerpt": report_text[:4000],
    }, blockers


def public_label_guard(identity: dict[str, Any] | None) -> dict[str, Any]:
    matches_expected = bool(
        identity
        and str(identity.get("manufacturer", "")).strip().lower() == "nubia"
        and str(identity.get("model", "")).strip().lower() == "p0110"
        and str(identity.get("device", "")).strip().lower() == "pacific"
    )
    return {
        "device_matches_expected_p0110": matches_expected,
        "recorded_as_expected_device_only": matches_expected,
        "evidence_scope": (
            "nubia_p0110_pacific_general_android_substitute_only"
            if matches_expected
            else "exact_recorded_android_device_only"
        ),
    }


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
    held_locks: Sequence[str],
    expected_device: dict[str, str | None],
    host_preflight_report: Path,
    command_runner: CommandRunner = subprocess.run,
    wall_clock=utc_now,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    locks = collect_locks(lock_globs, held_locks)
    if locks:
        blockers.append(
            blocker(
                "safety.locks",
                "device lease lock is present; no ADB, listener, or Host preflight probes were run",
            )
        )

    device: dict[str, Any] | None = None
    reverse: dict[str, Any] | None = None
    android_app: dict[str, Any] | None = None
    host_listener: dict[str, Any] | None = None
    host_preflight: dict[str, Any] | None = None

    if not locks:
        device, device_blockers = collect_device(
            serial=serial,
            adb_path=adb_path,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
        blockers.extend(device_blockers)
        if device is not None:
            blockers.extend(identity_mismatches(device, expected_device))
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

    result = "ready" if not blockers else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_smoke_preflight",
        "collected_at": wall_clock(),
        "result": result,
        "blockers": blockers,
        "configuration": {
            "serial": serial,
            "package": package_name,
            "port": port,
            "adb_timeout_seconds": adb_timeout,
            "host_preflight_timeout_seconds": host_preflight_timeout,
            "expected_device": expected_device,
            "lock_globs": list(lock_globs),
            "held_locks": [sanitize_lock_path(lock) for lock in held_locks],
        },
        "safety": {
            "read_only": True,
            "ran_adb": not locks,
            "checked_device_locks": True,
            "existing_locks": locks,
            "starts_host": False,
            "starts_android_app": False,
            "installs_apk": False,
            "changes_adb_reverse": False,
            "clears_logcat": False,
            "injects_input": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android_app_data": False,
        },
        "device": {
            "identity": device,
            "label_guard": public_label_guard(device),
        },
        "adb": {"reverse": reverse},
        "app": android_app,
        "host": {"listener": host_listener, "preflight": host_preflight},
        "claims": {
            "can_start_usb_smoke": result == "ready",
            "live_usb_stream_observed": False,
            "readme_gate_closure": False,
            "can_close_two_hour_soak_gate": False,
            "can_close_host_rss_no_growth_gate": False,
            "can_close_latency_gate": False,
            "can_close_native_pointer_hid_gate": False,
            "can_close_stylus_gate": False,
            "can_close_controller_gate": False,
            "device_matches_expected_p0110": bool(
                public_label_guard(device)["device_matches_expected_p0110"]
            ),
        },
    }


def identity_mismatches(
    device: dict[str, Any], expected: dict[str, str | None]
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for field, expected_value in expected.items():
        if expected_value is None:
            continue
        actual = str(device.get(field, ""))
        if actual != expected_value:
            mismatches.append(
                blocker(
                    f"device.identity.{field}",
                    f"device {field} is {actual!r}, expected {expected_value!r}",
                )
            )
    return mismatches


def normalize_expected_device(expected: dict[str, str | None]) -> dict[str, str]:
    return {
        field: str(expected.get(field) or default)
        for field, default in DEFAULT_EXPECTED_DEVICE.items()
    }


def blocker(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "no output")


def public_path(path: str | Path, repository_root: Path) -> str:
    path_value = Path(path)
    try:
        return str(path_value.resolve().relative_to(repository_root.resolve()))
    except (OSError, ValueError):
        return str(path)


def sanitize_lock_path(path: str) -> str:
    name = Path(path).name
    return f"/tmp/{name}" if name.startswith("vibe-screen-") else path


def sanitize_public_value(value: Any, *, serial: str, serial_label: str, repository_root: Path) -> Any:
    if isinstance(value, str):
        sanitized = value.replace(serial, serial_label) if serial else value
        sanitized = sanitize_lock_path(sanitized)
        user_tcc_database = Path.home() / "Library" / Path(*TCC_DIRECTORY_COMPONENTS) / TCC_DATABASE_NAME
        tcc_directory = "/".join(TCC_DIRECTORY_COMPONENTS)
        replacements = {
            str(user_tcc_database): "<user-tcc-db>",
            str(Path("/Library") / Path(*TCC_DIRECTORY_COMPONENTS) / TCC_DATABASE_NAME): "<system-tcc-db>",
            tcc_directory: "<tcc-dir>",
            TCC_DATABASE_NAME: "<tcc-db>",
            str(repository_root.resolve()): "<WORKSPACE>",
            str(Path.home()): "<HOME>",
            getpass.getuser(): "<HOST_USER>",
        }
        for needle, replacement in replacements.items():
            sanitized = sanitized.replace(needle, replacement)
        return sanitized
    if isinstance(value, list):
        return [
            sanitize_public_value(
                item,
                serial=serial,
                serial_label=serial_label,
                repository_root=repository_root,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(key): sanitize_public_value(
                item,
                serial=serial,
                serial_label=serial_label,
                repository_root=repository_root,
            )
            for key, item in value.items()
        }
    return value


def sanitize_public_document(
    document: dict[str, Any], *, serial: str, serial_label: str, repository_root: Path
) -> dict[str, Any]:
    sanitized = sanitize_public_value(
        document,
        serial=serial,
        serial_label=serial_label,
        repository_root=repository_root,
    )
    identity = sanitized.get("device", {}).get("identity")
    if isinstance(identity, dict):
        sanitized["device"]["identity"] = {
            "manufacturer": identity.get("manufacturer"),
            "model": identity.get("model"),
            "device": identity.get("device"),
            "android_release": identity.get("android_release"),
            "sdk": identity.get("sdk"),
        }
    return sanitized


def sanitize_public_text_file(
    path: Path, *, serial: str, serial_label: str, repository_root: Path
) -> None:
    if not path.exists():
        return
    sanitized = sanitize_public_value(
        path.read_text(encoding="utf-8", errors="replace"),
        serial=serial,
        serial_label=serial_label,
        repository_root=repository_root,
    )
    path.write_text(str(sanitized), encoding="utf-8")


def collect_optional(name: str, errors: list[dict[str, str]], collector):
    try:
        return collector()
    except (ADBError, ValueError) as error:
        errors.append(blocker(name, str(error)))
        return None


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
    parser.add_argument(
        "--serial-label",
        default=DEFAULT_SERIAL_LABEL,
        help="public label used instead of the raw ADB serial in retained evidence",
    )
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--host-preflight-timeout", type=float, default=60.0)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--lock-glob", action="append", default=[DEFAULT_LOCK_GLOB])
    parser.add_argument(
        "--held-lock",
        action="append",
        default=[],
        help=(
            "device lease lock already held by this caller; it is excluded from "
            "competing-lock detection while all other matching locks still block"
        ),
    )
    parser.add_argument("--expected-manufacturer")
    parser.add_argument("--expected-model")
    parser.add_argument("--expected-device")
    parser.add_argument("--expected-android-release")
    parser.add_argument("--expected-sdk")
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
    if host_report is None:
        host_report = Path("host-signing-and-permissions.txt")

    expected_device = normalize_expected_device({
        "manufacturer": arguments.expected_manufacturer,
        "model": arguments.expected_model,
        "device": arguments.expected_device,
        "android_release": arguments.expected_android_release,
        "sdk": arguments.expected_sdk,
    })
    document = build_document(
        serial=arguments.serial,
        repository_root=arguments.repository_root.resolve(),
        adb_path=arguments.adb,
        adb_timeout=arguments.adb_timeout,
        host_preflight_timeout=arguments.host_preflight_timeout,
        package_name=arguments.package,
        port=arguments.port,
        lock_globs=arguments.lock_glob,
        held_locks=arguments.held_lock,
        expected_device=expected_device,
        host_preflight_report=host_report,
    )
    public_document = sanitize_public_document(
        document,
        serial=arguments.serial,
        serial_label=arguments.serial_label,
        repository_root=arguments.repository_root,
    )
    sanitize_public_text_file(
        host_report,
        serial=arguments.serial,
        serial_label=arguments.serial_label,
        repository_root=arguments.repository_root,
    )
    write_json(output, public_document)
    return 0 if document["result"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
