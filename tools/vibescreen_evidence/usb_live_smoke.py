"""Collect a read-only Android USB live-stream smoke summary.

The collector samples only existing state from an explicitly selected Android
device. It does not install, launch, stop, clear logcat, create ADB reverse
rules, or probe the Host listener. A shared Android device lock therefore stops
collection before the first ADB command unless the caller explicitly opts in.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError
from .usb_live_smoke_summary import (
    DEFAULT_PORT,
    filter_logcat_by_pids,
    label_guard,
    live_smoke_blockers,
    parse_adb_reverse,
    parse_decoder_summary,
    parse_foreground_state,
    parse_package_metadata,
    parse_pids,
    parse_telemetry_summary,
)


DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_LOGCAT_LINES = 1500
DEFAULT_MAX_LOG_BYTES = 256 * 1024
DEVICE_LOCKS = (
    Path("/tmp/vibe-screen-device-soak.lock"),
    Path("/tmp/vibe-screen-device-android.lock"),
)
LOGCAT_TAGS = ("MA", "VD", "StreamClient", "VibeScreenTelemetry")
DIAG_LOG_COMMAND = "cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null"


@dataclass(frozen=True)
class TextSnapshot:
    name: str
    text: str
    available: bool = True
    error: str | None = None
    truncated: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "error": self.error,
            "line_count": len(self.text.splitlines()) if self.text else 0,
            "bytes": len(self.text.encode("utf-8")),
            "truncated": self.truncated,
        }


class DeviceLockError(RuntimeError):
    """Raised when a shared Android device lock blocks ADB collection."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def describe_device_locks(
    lock_paths: Sequence[Path] | None = None,
) -> list[dict[str, Any]]:
    paths = lock_paths or DEVICE_LOCKS
    locks: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        record: dict[str, Any] = {"path": str(path)}
        try:
            stat = path.stat()
            record["size_bytes"] = stat.st_size
            record["modified_at"] = datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat().replace("+00:00", "Z")
            record["detail"] = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError as error:
            record["read_error"] = str(error)
        locks.append(record)
    return locks


def enforce_device_lock_policy(
    *, allow_existing: bool, lock_paths: Sequence[Path] | None = None
) -> list[dict[str, Any]]:
    locks = describe_device_locks(lock_paths)
    if locks and not allow_existing:
        raise DeviceLockError(
            "device coordination lock exists; no ADB command was run: "
            + ", ".join(str(lock.get("path", "")) for lock in locks)
        )
    return locks


def collect_usb_live_smoke(
    client: ADBClient,
    *,
    package_name: str = DEFAULT_PACKAGE,
    port: int = DEFAULT_PORT,
    logcat_lines: int = DEFAULT_LOGCAT_LINES,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
    existing_locks: Sequence[dict[str, Any]] = (),
    wall_clock=utc_now,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    device_state = _try_collect(
        "adb.get_state",
        errors,
        lambda: client.command("get-state"),
    )
    device_identity = (
        _try_collect("device.identity", errors, client.identity)
        if device_state == "device"
        else None
    )
    reverse = _try_collect(
        "adb.reverse",
        errors,
        lambda: parse_adb_reverse(client.command("reverse", "--list"), port=port),
    )
    package = _try_collect(
        "app.package",
        errors,
        lambda: parse_package_metadata(
            client.shell("dumpsys", "package", package_name),
            package_name,
        ),
    )
    pids = _try_collect(
        "app.pidof",
        errors,
        lambda: parse_pids(client.shell("pidof", package_name)),
    )
    foreground = _try_collect(
        "app.foreground",
        errors,
        lambda: parse_foreground_state(
            client.shell("dumpsys", "window"),
            client.shell("dumpsys", "activity", "activities"),
            package_name,
        ),
    )
    logcat = _try_snapshot(
        "logcat",
        errors,
        lambda: client.command(
            "logcat",
            "-d",
            "-v",
            "threadtime",
            "-t",
            str(logcat_lines),
            "-s",
            *LOGCAT_TAGS,
        ),
        max_bytes=max_log_bytes,
    )
    diag_log = _try_snapshot(
        "diag_log",
        errors,
        lambda: client.exec_out("run-as", package_name, "sh", "-c", DIAG_LOG_COMMAND),
        max_bytes=max_log_bytes,
    )
    current_pid_logcat = filter_logcat_by_pids(logcat.text, pids or [])
    telemetry = parse_telemetry_summary(current_pid_logcat)
    decoder = parse_decoder_summary(current_pid_logcat)
    diagnostic_telemetry = parse_telemetry_summary(diag_log.text)
    diagnostic_decoder = parse_decoder_summary(diag_log.text)
    blockers = live_smoke_blockers(
        device_state=device_state,
        device_identity=device_identity,
        reverse=reverse,
        package=package,
        pids=pids,
        foreground=foreground,
        telemetry=telemetry,
        decoder=decoder,
    )
    verdict = "pass" if not blockers else "insufficient"
    live_stream_observed = verdict == "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_live_smoke",
        "collected_at": wall_clock(),
        "verdict": verdict,
        "blocking_reasons": blockers,
        "configuration": {
            "serial": client.serial,
            "package": package_name,
            "port": port,
            "logcat_tags": list(LOGCAT_TAGS),
            "logcat_lines": logcat_lines,
            "max_log_bytes": max_log_bytes,
        },
        "safety": {
            "read_only": True,
            "ran_adb": True,
            "checked_device_locks": True,
            "existing_locks": list(existing_locks),
            "starts_host": False,
            "starts_android_app": False,
            "installs_apk": False,
            "changes_adb_reverse": False,
            "clears_logcat": False,
            "injects_input": False,
        },
        "device": {
            "state": device_state,
            "identity": device_identity,
            "label_guard": label_guard(device_identity),
        },
        "adb": {"reverse": reverse},
        "app": {
            "package": package,
            "pids": pids or [],
            "running": bool(pids),
            "foreground": foreground,
        },
        "logs": {
            "sources": [logcat.summary(), diag_log.summary()],
            "live_evidence": {
                "source": "logcat_current_pid",
                "current_pids": list(pids or []),
                "matched_line_count": len(current_pid_logcat.splitlines()),
            },
            "telemetry": telemetry,
            "decoder": decoder,
            "diagnostic": {
                "source": "app_private_diag_log_context_only",
                "telemetry": diagnostic_telemetry,
                "decoder": diagnostic_decoder,
            },
        },
        "claims": {
            "live_usb_stream_observed": live_stream_observed,
            "readme_gate_closure": False,
            "can_close_two_hour_soak_gate": False,
            "can_close_host_rss_no_growth_gate": False,
            "can_close_latency_gate": False,
            "can_close_native_pointer_hid_gate": False,
            "can_close_stylus_gate": False,
            "can_close_controller_gate": False,
            "device_is_fuxi": bool(label_guard(device_identity)["device_is_fuxi"]),
        },
        "errors": errors,
    }


def _try_collect(name: str, errors: list[dict[str, str]], collector):
    try:
        return collector()
    except (ADBError, ValueError) as error:
        errors.append({"source": name, "message": str(error)})
        return None


def _try_snapshot(
    name: str,
    errors: list[dict[str, str]],
    collector,
    *,
    max_bytes: int,
) -> TextSnapshot:
    try:
        text = collector()
    except ADBError as error:
        errors.append({"source": name, "message": str(error)})
        return TextSnapshot(name=name, text="", available=False, error=str(error))
    trimmed, truncated = tail_text(text, max_bytes=max_bytes)
    return TextSnapshot(name=name, text=trimmed, truncated=truncated)


def tail_text(text: str, *, max_bytes: int) -> tuple[str, bool]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    trimmed = encoded[-max_bytes:].decode("utf-8", errors="replace")
    first_newline = trimmed.find("\n")
    if first_newline >= 0:
        trimmed = trimmed[first_newline + 1 :]
    return trimmed, True


def build_lock_blocked_document(
    *,
    serial: str,
    package_name: str,
    port: int,
    logcat_lines: int = DEFAULT_LOGCAT_LINES,
    max_log_bytes: int = DEFAULT_MAX_LOG_BYTES,
    locks: Sequence[dict[str, Any]],
    wall_clock=utc_now,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "android_usb_live_smoke",
        "collected_at": wall_clock(),
        "verdict": "blocked",
        "blocking_reasons": [
            {
                "field": "safety.existing_locks",
                "message": "shared Android device coordination lock exists; no ADB command was run",
            }
        ],
        "configuration": {
            "serial": serial,
            "package": package_name,
            "port": port,
            "logcat_tags": list(LOGCAT_TAGS),
            "logcat_lines": logcat_lines,
            "max_log_bytes": max_log_bytes,
        },
        "safety": {
            "read_only": True,
            "ran_adb": False,
            "checked_device_locks": True,
            "existing_locks": list(locks),
            "starts_host": False,
            "starts_android_app": False,
            "installs_apk": False,
            "changes_adb_reverse": False,
            "clears_logcat": False,
            "injects_input": False,
        },
        "device": {"state": None, "identity": None, "label_guard": label_guard(None)},
        "adb": {"reverse": None},
        "app": {"package": None, "pids": [], "running": False, "foreground": None},
        "logs": {
            "sources": [],
            "live_evidence": {
                "source": "logcat_current_pid",
                "current_pids": [],
                "matched_line_count": 0,
            },
            "telemetry": parse_telemetry_summary(""),
            "decoder": parse_decoder_summary(""),
            "diagnostic": {
                "source": "app_private_diag_log_context_only",
                "telemetry": parse_telemetry_summary(""),
                "decoder": parse_decoder_summary(""),
            },
        },
        "claims": {
            "live_usb_stream_observed": False,
            "readme_gate_closure": False,
            "can_close_two_hour_soak_gate": False,
            "can_close_host_rss_no_growth_gate": False,
            "can_close_latency_gate": False,
            "can_close_native_pointer_hid_gate": False,
            "can_close_stylus_gate": False,
            "can_close_controller_gate": False,
            "device_is_fuxi": False,
        },
        "errors": [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android application package")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="USB reverse TCP port")
    parser.add_argument("--logcat-lines", type=int, default=DEFAULT_LOGCAT_LINES)
    parser.add_argument("--max-log-bytes", type=int, default=DEFAULT_MAX_LOG_BYTES)
    parser.add_argument(
        "--allow-existing-device-lock",
        action="store_true",
        help="Continue despite a shared Android device lock. Use only when you own that lock.",
    )
    parser.add_argument(
        "--write-blocked-on-lock",
        action="store_true",
        help=(
            "When a shared Android device lock exists, write blocked evidence "
            "instead of running ADB."
        ),
    )
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    if arguments.port <= 0 or arguments.port > 65535:
        parser.error("--port must be in 1..65535")
    if arguments.logcat_lines <= 0:
        parser.error("--logcat-lines must be positive")
    if arguments.max_log_bytes <= 0:
        parser.error("--max-log-bytes must be positive")
    try:
        locks = enforce_device_lock_policy(allow_existing=arguments.allow_existing_device_lock)
    except DeviceLockError as error:
        if not arguments.write_blocked_on_lock:
            print(f"error: {error}", file=sys.stderr)
            return 2
        document = build_lock_blocked_document(
            serial=arguments.serial,
            package_name=arguments.package,
            port=arguments.port,
            logcat_lines=arguments.logcat_lines,
            max_log_bytes=arguments.max_log_bytes,
            locks=describe_device_locks(),
        )
        write_json(arguments.output, document)
        return 2

    client = ADBClient(
        arguments.serial,
        adb_path=arguments.adb,
        timeout_seconds=arguments.adb_timeout,
    )
    document = collect_usb_live_smoke(
        client,
        package_name=arguments.package,
        port=arguments.port,
        logcat_lines=arguments.logcat_lines,
        max_log_bytes=arguments.max_log_bytes,
        existing_locks=locks,
    )
    write_json(arguments.output, document)
    if document["verdict"] == "pass":
        return 0
    if document["verdict"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
