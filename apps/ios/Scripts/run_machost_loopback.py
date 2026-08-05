#!/usr/bin/env python3
"""Build and run the real iOS Core <-> MacHost trusted-LAN loopback gate."""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MAC_HOST_PACKAGE = REPOSITORY_ROOT / "baseline" / "MacHost"
IOS_PACKAGE = REPOSITORY_ROOT / "apps" / "ios"


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
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"MacHost exited before readiness (status {process.returncode})")
        try:
            if "IOS_LOOPBACK_HOST_READY" in output.get(timeout=0.1):
                return
        except queue.Empty:
            pass
    raise TimeoutError(f"MacHost was not ready within {timeout:.1f}s")


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def run_case(
    host_binary: Path,
    client_binary: Path,
    startup_timeout: float,
    test_timeout: float,
    invalid_target: bool,
) -> bool:
    scenario = "invalid-target" if invalid_target else "lifecycle"
    host_command = [str(host_binary)]
    client_command = [str(client_binary)]
    print(f"MacHost loopback scenario: {scenario}", flush=True)
    host = subprocess.Popen(
        host_command,
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={
            **os.environ,
            "VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": scenario,
        },
    )
    lines: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=stream_lines, args=(host, lines), daemon=True)
    reader.start()
    try:
        wait_for_ready(host, lines, startup_timeout)
        print("+", " ".join(client_command), flush=True)
        client = subprocess.run(
            client_command,
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            timeout=test_timeout,
            env={
                **os.environ,
                "VIBE_SCREEN_IOS_LOOPBACK_SCENARIO": scenario,
            },
        )
        if client.stdout:
            print(client.stdout, end="")
        if client.stderr:
            print(client.stderr, end="", file=sys.stderr)
        host_status = host.wait(timeout=test_timeout)
        reader.join(timeout=1)
        if client.returncode != 0 or host_status != 0:
            print(
                f"MacHost loopback {scenario}: FAIL "
                f"(client={client.returncode}, host={host_status})",
                file=sys.stderr,
            )
            return False
        return True
    finally:
        terminate(host)


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
                "Telemachus",
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

    host_binary = swift_binary(MAC_HOST_PACKAGE, "Telemachus")
    client_binary = swift_binary(IOS_PACKAGE, "vibescreen-mac-host-loopback")
    for binary in (host_binary, client_binary):
        if not binary.is_file():
            raise FileNotFoundError(f"missing release binary: {binary}")

    lifecycle_passed = run_case(
        host_binary,
        client_binary,
        args.startup_timeout,
        args.test_timeout,
        invalid_target=False,
    )
    invalid_target_passed = run_case(
        host_binary,
        client_binary,
        args.startup_timeout,
        args.test_timeout,
        invalid_target=True,
    )
    if not lifecycle_passed or not invalid_target_passed:
        return 1
    print(
        "MacHost loopback: PASS "
        "(external lifecycle + invalid-target production-process integration)"
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
