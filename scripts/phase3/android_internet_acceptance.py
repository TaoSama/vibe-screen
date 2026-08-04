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
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


class AcceptanceError(RuntimeError):
    """Raised when a required device observation cannot be proved."""


@dataclass
class CommandRecord:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class Adb:
    def __init__(self, executable: str, serial: str, records: list[CommandRecord]) -> None:
        self.executable = executable
        self.serial = serial
        self.records = records

    def host(self, arguments: Sequence[str], timeout: float = 30) -> str:
        return self._run([self.executable, *arguments], timeout)

    def device(self, arguments: Sequence[str], timeout: float = 30) -> str:
        return self._run([self.executable, "-s", self.serial, *arguments], timeout)

    def _run(self, command: list[str], timeout: float) -> str:
        started = time.monotonic()
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AcceptanceError(f"cannot run {command[0]}: {error}") from error
        record = CommandRecord(command, result.returncode, result.stdout, result.stderr, time.monotonic() - started)
        self.records.append(record)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no output"
            raise AcceptanceError(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
        return result.stdout.strip()


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
        raise AcceptanceError(f"missing required {label} evidence matching: {pattern}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace, records: list[CommandRecord] | None = None) -> dict[str, Any]:
    apk = args.apk.resolve()
    if not apk.is_file():
        raise AcceptanceError(f"APK does not exist: {apk}")
    if records is None:
        records = []
    adb = Adb(args.adb, args.serial, records)
    started_at = datetime.now(timezone.utc).isoformat()
    connect_output = adb.host(["connect", args.serial], timeout=args.command_timeout)
    state = adb.device(["get-state"], timeout=args.command_timeout)
    if state != "device":
        raise AcceptanceError(f"ADB state is {state!r}, expected 'device'")
    identity = {
        "serial": args.serial,
        "manufacturer": _property(adb, "ro.product.manufacturer"),
        "model": _property(adb, "ro.product.model"),
        "device": _property(adb, "ro.product.device"),
        "sdk": _property(adb, "ro.build.version.sdk"),
        "fingerprint": _property(adb, "ro.build.fingerprint"),
    }
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
    adb.device(["logcat", "-c"])
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
    after_input = _observe(adb, args.package)
    _require_pattern("input acknowledgement", args.input_pattern, after_input)

    adb.device(["shell", "am", "force-stop", args.package])
    adb.device(["logcat", "-c"])
    time.sleep(args.disconnect_wait)
    launch_and_connect()
    reconnect_observation = _observe(adb, args.package)
    _require_pattern("reconnect", args.reconnect_pattern, reconnect_observation)
    _require_pattern("post-reconnect streaming", args.streaming_pattern, reconnect_observation)

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
        "adb_connect": connect_output,
        "device": identity,
        "apk": {"path": str(apk), "sha256": _sha256(apk)},
        "application": {"package": args.package, "activity": args.activity, "version_name": version_match.group(1) if version_match else None},
        "assertions": {
            "streaming_pattern": args.streaming_pattern,
            "input_pattern": args.input_pattern,
            "reconnect_pattern": args.reconnect_pattern,
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
    parser.add_argument("--serial", default="100.72.246.116:5555")
    parser.add_argument("--expected-model", default="2201123C")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--package", default="dev.telemachus.display")
    parser.add_argument("--activity", default=".MainActivity")
    parser.add_argument("--connect-tap", type=coordinate_pair, help="tap X,Y after launch; omit if auto-connect is configured")
    parser.add_argument("--input-swipe", type=swipe, default=(500, 900, 700, 900, 250))
    parser.add_argument("--streaming-pattern", required=True, help="regex that proves decoded streaming, not mere connectivity")
    parser.add_argument("--input-pattern", required=True, help="regex that proves host-side input acknowledgement")
    parser.add_argument("--reconnect-pattern", required=True, help="regex that proves a new session after forced app disconnect")
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
        try:
            _write_json(
                args.evidence,
                {
                    "schema_version": 1,
                    "result": "failed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(error),
                    "commands": [record.__dict__ for record in records],
                },
            )
        except OSError as write_error:
            print(f"error: could not write failure evidence: {write_error}", file=sys.stderr)
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"PASS: evidence written to {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
