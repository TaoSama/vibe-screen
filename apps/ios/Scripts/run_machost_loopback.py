#!/usr/bin/env python3
"""Build and run the real iOS Core <-> MacHost trusted-LAN loopback gate."""

from __future__ import annotations

import argparse
import errno
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAC_HOST_PACKAGE = REPOSITORY_ROOT / "baseline" / "MacHost"
IOS_PACKAGE = REPOSITORY_ROOT / "apps" / "ios"
LOOPBACK_PORT_ENVIRONMENT = "VIBE_SCREEN_IOS_LOOPBACK_PORT"
LOOPBACK_SCENARIO_ENVIRONMENT = "VIBE_SCREEN_IOS_LOOPBACK_SCENARIO"
LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT = "VIBE_SCREEN_IOS_LOOPBACK_LEGACY_PLAINTEXT"
LOOPBACK_SCENARIOS = frozenset({"lifecycle", "invalid-target"})
HOST_READY_PATTERN = re.compile(r"IOS_LOOPBACK_HOST_READY port=([0-9]+)")
PROCESS_TERMINATION_TIMEOUT = 3.0
LISTENER_SHUTDOWN_TIMEOUT = 3.0
LISTENER_SHUTDOWN_POLL_INTERVAL = 0.05
LISTENER_PROBE_TIMEOUT = 0.2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production MacHost and iOS Core trusted-LAN loopback integration gate."
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="reuse existing release binaries",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=20.0,
        help="seconds to wait for the host listener (default: 20)",
    )
    parser.add_argument(
        "--test-timeout",
        type=float,
        default=20.0,
        help="seconds to wait for each integration process (default: 20)",
    )
    parser.add_argument(
        "--legacy-plaintext",
        action="store_true",
        help="explicitly exercise the old plaintext trusted-LAN fallback instead of secure records",
    )
    return parser.parse_args()


def run_checked(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


def swift_binary(package: Path, product: str) -> Path:
    result = subprocess.run(
        [
            "swift",
            "build",
            "--package-path",
            str(package),
            "-c",
            "release",
            "--show-bin-path",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(result.stdout.strip()) / product


def stream_lines(process: subprocess.Popen[str], output: queue.Queue[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[host] {line}", end="", flush=True)
        output.put(line)


def wait_for_ready(
    process: subprocess.Popen[str], output: queue.Queue[str], timeout: float
) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = output.get(timeout=0.1).strip()
        except queue.Empty:
            if process.poll() is not None:
                raise RuntimeError(
                    f"MacHost exited before readiness (status {process.returncode})"
                )
            continue
        if not line.startswith("IOS_LOOPBACK_HOST_READY"):
            continue
        match = HOST_READY_PATTERN.fullmatch(line)
        if match is None:
            raise RuntimeError(f"MacHost emitted malformed readiness: {line}")
        port = int(match.group(1))
        return validate_loopback_port(port, allow_ephemeral=False)
    raise TimeoutError(f"MacHost was not ready within {timeout:.1f}s")


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_TERMINATION_TIMEOUT)


def close_process_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def validate_loopback_port(
    port: int,
    *,
    allow_ephemeral: bool,
) -> int:
    minimum_port = 0 if allow_ephemeral else 1
    if (
        isinstance(port, bool)
        or not isinstance(port, int)
        or not minimum_port <= port <= 65_535
    ):
        raise ValueError(
            f"loopback port must be between {minimum_port} and 65535; got {port!r}"
        )
    return port


def loopback_environment(
    scenario: str,
    port: int,
    *,
    allow_ephemeral: bool,
    legacy_plaintext: bool = False,
) -> dict[str, str]:
    if scenario not in LOOPBACK_SCENARIOS:
        raise ValueError(f"unknown loopback scenario: {scenario}")
    validate_loopback_port(port, allow_ephemeral=allow_ephemeral)
    environment = {
        **os.environ,
        LOOPBACK_SCENARIO_ENVIRONMENT: scenario,
        LOOPBACK_PORT_ENVIRONMENT: str(port),
    }
    if legacy_plaintext:
        environment[LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT] = "1"
    else:
        environment.pop(LOOPBACK_LEGACY_PLAINTEXT_ENVIRONMENT, None)
    return environment


def wait_for_listener_shutdown(
    port: int,
    timeout: float = LISTENER_SHUTDOWN_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    last_observation = "connection succeeded"
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(LISTENER_PROBE_TIMEOUT)
            try:
                probe.connect(("127.0.0.1", port))
            except OSError as error:
                if error.errno == errno.ECONNREFUSED:
                    return
                last_observation = str(error)
        time.sleep(LISTENER_SHUTDOWN_POLL_INTERVAL)
    raise RuntimeError(
        f"MacHost listener on port {port} still accepted or intercepted new "
        f"connections after {timeout:.1f}s: "
        f"{last_observation}"
    )


def run_case(
    host_binary: Path,
    client_binary: Path,
    startup_timeout: float,
    test_timeout: float,
    invalid_target: bool,
    legacy_plaintext: bool,
) -> int:
    scenario = "invalid-target" if invalid_target else "lifecycle"
    host_command = [str(host_binary)]
    client_command = [str(client_binary)]
    print(f"MacHost loopback scenario: {scenario}", flush=True)
    host: Optional[subprocess.Popen[str]] = None
    client: Optional[subprocess.Popen[str]] = None
    reader: Optional[threading.Thread] = None
    listening_port: Optional[int] = None
    lines: queue.Queue[str] = queue.Queue()
    try:
        host = subprocess.Popen(
            host_command,
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=loopback_environment(
                scenario,
                0,
                allow_ephemeral=True,
                legacy_plaintext=legacy_plaintext,
            ),
        )
        host_reader = threading.Thread(
            target=stream_lines,
            args=(host, lines),
            daemon=True,
        )
        host_reader.start()
        reader = host_reader
        listening_port = wait_for_ready(host, lines, startup_timeout)
        print("+", " ".join(client_command), flush=True)
        client = subprocess.Popen(
            client_command,
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=loopback_environment(
                scenario,
                listening_port,
                allow_ephemeral=False,
                legacy_plaintext=legacy_plaintext,
            ),
        )
        client_stdout, client_stderr = client.communicate(timeout=test_timeout)
        if client_stdout:
            print(client_stdout, end="")
        if client_stderr:
            print(client_stderr, end="", file=sys.stderr)
        host_status = host.wait(timeout=test_timeout)
        reader.join(timeout=PROCESS_TERMINATION_TIMEOUT)
        if client.returncode != 0 or host_status != 0:
            raise RuntimeError(
                f"MacHost loopback {scenario} failed on port {listening_port} "
                f"(client={client.returncode}, host={host_status})"
            )
        return listening_port
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_errors: list[Exception] = []
        if client is not None:
            try:
                terminate(client)
            except Exception as error:
                cleanup_errors.append(error)
            try:
                close_process_streams(client)
            except Exception as error:
                cleanup_errors.append(error)
        if host is not None:
            try:
                terminate(host)
            except Exception as error:
                cleanup_errors.append(error)
        if reader is not None:
            try:
                reader.join(timeout=PROCESS_TERMINATION_TIMEOUT)
                if reader.is_alive():
                    cleanup_errors.append(
                        RuntimeError("MacHost output reader did not stop")
                    )
            except Exception as error:
                cleanup_errors.append(error)
        if host is not None:
            try:
                close_process_streams(host)
            except Exception as error:
                cleanup_errors.append(error)
        if listening_port is not None:
            try:
                wait_for_listener_shutdown(listening_port)
            except Exception as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            message = (
                "MacHost loopback cleanup failed: "
                + "; ".join(str(error) for error in cleanup_errors)
            )
            if primary_error is not None:
                if hasattr(primary_error, "add_note"):
                    primary_error.add_note(message)
                else:
                    print(message, file=sys.stderr)
            else:
                raise RuntimeError(message) from cleanup_errors[0]


def main() -> int:
    args = parse_args()
    if args.startup_timeout <= 0 or args.test_timeout <= 0:
        raise ValueError("timeouts must be positive")

    if not args.skip_build:
        run_checked(
            [
                "swift",
                "build",
                "--package-path",
                str(MAC_HOST_PACKAGE),
                "-c",
                "release",
                "--product",
                "Vibe Screen",
            ]
        )
        run_checked(
            [
                "swift",
                "build",
                "--package-path",
                str(IOS_PACKAGE),
                "-c",
                "release",
                "--product",
                "vibescreen-mac-host-loopback",
            ]
        )

    host_binary = swift_binary(MAC_HOST_PACKAGE, "Vibe Screen")
    client_binary = swift_binary(IOS_PACKAGE, "vibescreen-mac-host-loopback")
    for binary in (host_binary, client_binary):
        if not binary.is_file():
            raise FileNotFoundError(f"missing release binary: {binary}")

    lifecycle_port = run_case(
        host_binary,
        client_binary,
        args.startup_timeout,
        args.test_timeout,
        invalid_target=False,
        legacy_plaintext=args.legacy_plaintext,
    )
    invalid_target_port = run_case(
        host_binary,
        client_binary,
        args.startup_timeout,
        args.test_timeout,
        invalid_target=True,
        legacy_plaintext=args.legacy_plaintext,
    )
    print(
        "MacHost loopback: PASS "
        "(external lifecycle + invalid-target production-process integration, "
        f"encryptedRecords:{str(not args.legacy_plaintext).lower()},"
        f"explicitLegacyFallback:{str(args.legacy_plaintext).lower()},"
        f"ports=lifecycle:{lifecycle_port},invalid-target:{invalid_target_port})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"MacHost loopback: FAIL ({error})", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as error:
        print(f"MacHost loopback: FAIL (command exited {error.returncode})", file=sys.stderr)
        raise SystemExit(error.returncode or 1)
    except subprocess.TimeoutExpired as error:
        print(f"MacHost loopback: FAIL (process timeout: {error.cmd})", file=sys.stderr)
        raise SystemExit(1)
