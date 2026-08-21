"""Preflight the fixed-binary touch-gesture rerun gate without side effects.

The check is intentionally read-only: it inspects the installed Host bundle,
TCC rows, and an explicit Android device identity. It does not launch the Host,
run instrumentation, change ADB reverse rules, or modify any macOS privacy
state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import plistlib
import queue
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError


SCREEN_CAPTURE_SERVICE = "kTCCServiceScreenCapture"
ACCESSIBILITY_SERVICE = "kTCCServiceAccessibility"
AUTHORIZED_TCC_VALUE = 2
DEFAULT_BUNDLE_PATH = Path("/Applications/Vibe Screen.app")
USER_TCC_DB = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
SYSTEM_TCC_DB = Path("/Library/Application Support/com.apple.TCC/TCC.db")
TCC_QUERY_TIMEOUT_SECONDS = 5.0


class TouchRerunPreflightError(RuntimeError):
    """Raised when read-only preflight evidence cannot be collected."""


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str


def _run(command: Sequence[str], *, timeout_seconds: float = 15.0) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TouchRerunPreflightError(f"failed to run {' '.join(command)}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise TouchRerunPreflightError(
            f"{' '.join(command)} exited with {completed.returncode}: {detail}"
        )
    return CommandResult(completed.stdout.strip(), completed.stderr.strip())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise TouchRerunPreflightError(f"could not read {path}: {error}") from error
    return digest.hexdigest()


def _public_path(path: Path) -> str:
    try:
        relative_path = path.resolve().relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return str(path)
    return str(Path("<user-home>") / relative_path)


def _bundle_identifier(bundle_path: Path) -> str:
    info_path = bundle_path / "Contents/Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        raise TouchRerunPreflightError(f"could not read bundle identifier: {error}") from error
    identifier = info.get("CFBundleIdentifier")
    if not isinstance(identifier, str) or not identifier:
        raise TouchRerunPreflightError(f"missing CFBundleIdentifier in {info_path}")
    return identifier


def _codesign_summary(bundle_path: Path) -> dict[str, Any]:
    details = _run(["codesign", "-dv", "--verbose=4", str(bundle_path)]).stderr
    verify = _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(bundle_path)])
    authorities = re.findall(r"^Authority=(.+)$", details, flags=re.MULTILINE)
    cdhash_match = re.search(r"^CDHash=(.+)$", details, flags=re.MULTILINE)
    return {
        "authorities": authorities,
        "cdhash": cdhash_match.group(1).strip() if cdhash_match else None,
        "verify": verify.stderr or verify.stdout,
    }


def collect_host_bundle(bundle_path: Path) -> dict[str, Any]:
    if not bundle_path.exists():
        raise TouchRerunPreflightError(f"Host bundle not found: {bundle_path}")
    identifier = _bundle_identifier(bundle_path)
    executable = bundle_path / "Contents/MacOS/Vibe Screen"
    if not executable.exists():
        raise TouchRerunPreflightError(f"Host executable not found: {executable}")
    return {
        "bundle_path": str(bundle_path),
        "identifier": identifier,
        "binary_sha256": _sha256(executable),
        "codesign": _codesign_summary(bundle_path),
    }


def _query_tcc_db(db_path: Path, bundle_identifier: str, *, timeout_seconds: float = TCC_QUERY_TIMEOUT_SECONDS) -> dict[str, dict[str, Any]]:
    if not db_path.exists():
        return {}
    context = _tcc_query_context()
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_query_tcc_db_worker, args=(result_queue, db_path, bundle_identifier))
    try:
        process.start()
        process.join(timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            if process.is_alive():
                process.kill()
                process.join()
            raise TouchRerunPreflightError(f"TCC database query timed out after {timeout_seconds:g}s")
        try:
            status, payload = result_queue.get(timeout=1.0)
        except queue.Empty as error:
            exitcode = process.exitcode if process.exitcode is not None else "unknown"
            raise TouchRerunPreflightError(
                f"TCC database query exited without a result (exit {exitcode})"
            ) from error
        if status == "ok":
            return payload
        raise TouchRerunPreflightError(str(payload))
    finally:
        result_queue.close()
        result_queue.join_thread()


def _tcc_query_context() -> multiprocessing.context.BaseContext:
    try:
        return multiprocessing.get_context("fork")
    except ValueError:
        return multiprocessing.get_context()


def _query_tcc_db_worker(result_queue: multiprocessing.Queue, db_path: Path, bundle_identifier: str) -> None:
    try:
        result_queue.put(("ok", _query_tcc_db_direct(db_path, bundle_identifier)))
    except Exception as error:
        result_queue.put(("error", repr(error)))


def _query_tcc_db_direct(db_path: Path, bundle_identifier: str) -> dict[str, dict[str, Any]]:
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise TouchRerunPreflightError(f"could not open TCC database read-only: {error}") from error
    try:
        rows = connection.execute(
            """
            select service, client, client_type, auth_value, auth_reason, last_modified
            from access
            where client = ? and service in (?, ?)
            order by service
            """,
            (bundle_identifier, ACCESSIBILITY_SERVICE, SCREEN_CAPTURE_SERVICE),
        ).fetchall()
    except sqlite3.Error as error:
        raise TouchRerunPreflightError(f"could not query TCC database: {error}") from error
    finally:
        connection.close()

    return {
        service: {
            "service": service,
            "client": client,
            "client_type": client_type,
            "auth_value": auth_value,
            "auth_reason": auth_reason,
            "last_modified": last_modified,
            "authorized": auth_value == AUTHORIZED_TCC_VALUE,
            "db_path": _public_path(db_path),
        }
        for service, client, client_type, auth_value, auth_reason, last_modified in rows
    }


def collect_tcc(db_paths: Sequence[Path], bundle_identifier: str) -> dict[str, Any]:
    if not db_paths:
        raise TouchRerunPreflightError("at least one TCC database path is required")
    by_service: dict[str, dict[str, Any]] = {}
    inspected: list[str] = []
    missing: list[str] = []
    for db_path in db_paths:
        inspected.append(_public_path(db_path))
        if not db_path.exists():
            missing.append(_public_path(db_path))
            continue
        for service, row in _query_tcc_db(db_path, bundle_identifier).items():
            current = by_service.get(service)
            if current is None or row["last_modified"] >= current["last_modified"]:
                by_service[service] = row
    return {
        "db_paths": inspected,
        "missing_db_paths": missing,
        "bundle_identifier": bundle_identifier,
        "screen_recording": by_service.get(SCREEN_CAPTURE_SERVICE),
        "accessibility": by_service.get(ACCESSIBILITY_SERVICE),
    }


def collect_android(serial: str | None, adb_path: str, timeout_seconds: float) -> dict[str, Any] | None:
    if serial is None:
        return None
    client = ADBClient(serial, adb_path=adb_path, timeout_seconds=timeout_seconds)
    client.require_device()
    return client.identity()


def _blockers(
    *,
    host: dict[str, Any],
    tcc: dict[str, Any],
    android: dict[str, Any] | None,
    expected_host_sha256: str | None,
    expected_android_manufacturer: str | None = None,
    expected_android_model: str | None = None,
    expected_android_device: str | None = None,
    expected_android_release: str | None = None,
    expected_android_sdk: int | None = None,
) -> list[str]:
    blockers: list[str] = []
    if expected_host_sha256 and host["binary_sha256"] != expected_host_sha256.lower():
        blockers.append(
            "installed Host binary SHA-256 does not match the expected fixed binary"
        )
    screen = tcc.get("screen_recording")
    if not screen or not screen.get("authorized"):
        blockers.append("Screen Recording is not authorized for the Host bundle identifier")
    accessibility = tcc.get("accessibility")
    if not accessibility or not accessibility.get("authorized"):
        blockers.append("Accessibility is not authorized for the Host bundle identifier")
    if android is None:
        blockers.append("no explicit Android device serial was recorded")
    else:
        expected_fields: list[tuple[str, str | int | None]] = [
            ("manufacturer", expected_android_manufacturer),
            ("model", expected_android_model),
            ("device", expected_android_device),
            ("android_release", expected_android_release),
            ("sdk", expected_android_sdk),
        ]
        for field, expected in expected_fields:
            if expected is None:
                continue
            actual = android.get(field)
            if actual != expected:
                blockers.append(
                    f"Android device {field} does not match expected value "
                    f"{expected!r} (actual {actual!r})"
                )
    return blockers


def build_document(
    *,
    bundle_path: Path,
    tcc_dbs: Sequence[Path],
    serial: str | None,
    adb_path: str,
    adb_timeout: float,
    expected_host_sha256: str | None,
    expected_android_manufacturer: str | None = None,
    expected_android_model: str | None = None,
    expected_android_device: str | None = None,
    expected_android_release: str | None = None,
    expected_android_sdk: int | None = None,
) -> dict[str, Any]:
    host = collect_host_bundle(bundle_path)
    tcc = collect_tcc(tcc_dbs, host["identifier"])
    android = collect_android(serial, adb_path, adb_timeout)
    blockers = _blockers(
        host=host,
        tcc=tcc,
        android=android,
        expected_host_sha256=expected_host_sha256,
        expected_android_manufacturer=expected_android_manufacturer,
        expected_android_model=expected_android_model,
        expected_android_device=expected_android_device,
        expected_android_release=expected_android_release,
        expected_android_sdk=expected_android_sdk,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "touch_fixed_binary_rerun_preflight",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "result": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "host": host,
        "tcc": tcc,
        "android_device": android,
        "expected_host_sha256": expected_host_sha256,
        "expected_android_device": {
            "manufacturer": expected_android_manufacturer,
            "model": expected_android_model,
            "device": expected_android_device,
            "android_release": expected_android_release,
            "sdk": expected_android_sdk,
        },
        "safety": {
            "read_only": True,
            "starts_host": False,
            "runs_instrumentation": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android_app_data": False,
        },
    }


def build_blocked_error_document(
    error: Exception,
    *,
    expected_host_sha256: str | None = None,
    expected_android_manufacturer: str | None = None,
    expected_android_model: str | None = None,
    expected_android_device: str | None = None,
    expected_android_release: str | None = None,
    expected_android_sdk: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "touch_fixed_binary_rerun_preflight",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "result": "blocked",
        "blockers": [f"preflight collection failed: {error}"],
        "host": None,
        "tcc": None,
        "android_device": None,
        "expected_host_sha256": expected_host_sha256,
        "expected_android_device": {
            "manufacturer": expected_android_manufacturer,
            "model": expected_android_model,
            "device": expected_android_device,
            "android_release": expected_android_release,
            "sdk": expected_android_sdk,
        },
        "safety": {
            "read_only": True,
            "starts_host": False,
            "runs_instrumentation": False,
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
    parser.add_argument("--serial", help="exact ADB device serial to record")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--host-bundle", type=Path, default=DEFAULT_BUNDLE_PATH)
    parser.add_argument(
        "--tcc-db",
        action="append",
        type=Path,
        help=(
            "TCC database path to inspect; repeatable. Defaults to the current "
            "user and system TCC databases."
        ),
    )
    parser.add_argument("--expected-host-sha256")
    parser.add_argument("--expected-android-manufacturer")
    parser.add_argument("--expected-android-model")
    parser.add_argument("--expected-android-device")
    parser.add_argument("--expected-android-release")
    parser.add_argument("--expected-android-sdk", type=int)
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    expected = arguments.expected_host_sha256
    if expected is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        parser.error("--expected-host-sha256 must be a 64-character hex digest")
    try:
        document = build_document(
            bundle_path=arguments.host_bundle,
            tcc_dbs=arguments.tcc_db or [USER_TCC_DB, SYSTEM_TCC_DB],
            serial=arguments.serial,
            adb_path=arguments.adb,
            adb_timeout=arguments.adb_timeout,
            expected_host_sha256=expected.lower() if expected else None,
            expected_android_manufacturer=arguments.expected_android_manufacturer,
            expected_android_model=arguments.expected_android_model,
            expected_android_device=arguments.expected_android_device,
            expected_android_release=arguments.expected_android_release,
            expected_android_sdk=arguments.expected_android_sdk,
        )
        write_json(arguments.output, document)
    except Exception as error:
        if arguments.output is not None:
            write_json(
                arguments.output,
                build_blocked_error_document(
                    error,
                    expected_host_sha256=expected.lower() if expected else None,
                    expected_android_manufacturer=arguments.expected_android_manufacturer,
                    expected_android_model=arguments.expected_android_model,
                    expected_android_device=arguments.expected_android_device,
                    expected_android_release=arguments.expected_android_release,
                    expected_android_sdk=arguments.expected_android_sdk,
                ),
            )
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
