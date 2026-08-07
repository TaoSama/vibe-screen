"""Process, HTTP, and local port helpers for the Phase 3 E2E."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from glob import glob
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from typing import Iterator, NoReturn
from urllib import error, request

from scripts.phase3_webrtc.model import COTURN_LEGACY_RESIDUE_PATTERNS, E2EFailure
from scripts.phase3_webrtc.privacy import (
    project_and_validate_public_diagnostic,
    write_private_text,
)


@dataclass(frozen=True)
class _RunCheckedOutcome:
    completed: subprocess.CompletedProcess[str] | None
    failure_message: str | None


@dataclass(frozen=True)
class _HTTPJSONOutcome:
    status: int | None
    payload: dict[str, object] | None
    failure_message: str | None


def _raise_sanitized_failure(message: str) -> NoReturn:
    raise E2EFailure(message) from None


def _perform_run_checked(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    environment: dict[str, str] | None = None,
    redact_values: tuple[str, ...] = (),
    diagnostic_path: Path | None = None,
    diagnostic_private_paths: tuple[Path | str, ...] = (),
    pass_fds: tuple[int, ...] = (),
) -> _RunCheckedOutcome:
    try:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                pass_fds=pass_fds,
            )
        except subprocess.TimeoutExpired as exception:
            timeout_output = exception.stdout or ""
            if isinstance(timeout_output, bytes):
                timeout_output = timeout_output.decode("utf-8", errors="replace")
            exception.output = None
            exception.stdout = None
            exception.stderr = None
            exception.__traceback__ = None
            exception.__cause__ = None
            exception.__context__ = None
            rendered_output = project_and_validate_public_diagnostic(
                timeout_output,
                secret_values=redact_values,
                private_paths=(cwd, Path.home(), *diagnostic_private_paths),
            )
            rendered_command = project_and_validate_public_diagnostic(
                " ".join(command),
                secret_values=redact_values,
                private_paths=(cwd, Path.home(), *diagnostic_private_paths),
            )
            if diagnostic_path is not None:
                write_private_text(diagnostic_path, rendered_output)
            return _RunCheckedOutcome(
                completed=None,
                failure_message=(
                    f"command timed out after {timeout}s: "
                    f"{rendered_command}\n{rendered_output}"
                ),
            )
        rendered_output = project_and_validate_public_diagnostic(
            completed.stdout,
            secret_values=redact_values,
            private_paths=(cwd, Path.home(), *diagnostic_private_paths),
        )
        if diagnostic_path is not None:
            write_private_text(diagnostic_path, rendered_output)
        if completed.returncode != 0:
            rendered_command = project_and_validate_public_diagnostic(
                " ".join(command),
                secret_values=redact_values,
                private_paths=(cwd, Path.home(), *diagnostic_private_paths),
            )
            return _RunCheckedOutcome(
                completed=None,
                failure_message=(
                    f"command failed ({completed.returncode}): "
                    f"{rendered_command}\n{rendered_output}"
                ),
            )
        return _RunCheckedOutcome(completed=completed, failure_message=None)
    except Exception as exception:
        exception.__traceback__ = None
        exception.__cause__ = None
        exception.__context__ = None
        return _RunCheckedOutcome(
            completed=None,
            failure_message="command execution failed before a safe result was available",
        )


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    environment: dict[str, str] | None = None,
    redact_values: tuple[str, ...] = (),
    diagnostic_path: Path | None = None,
    diagnostic_private_paths: tuple[Path | str, ...] = (),
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    outcome = _perform_run_checked(
        command,
        cwd=cwd,
        timeout=timeout,
        environment=environment,
        redact_values=redact_values,
        diagnostic_path=diagnostic_path,
        diagnostic_private_paths=diagnostic_private_paths,
        pass_fds=pass_fds,
    )
    command = []
    cwd = Path(".")
    timeout = 0
    environment = None
    redact_values = ()
    diagnostic_path = None
    diagnostic_private_paths = ()
    pass_fds = ()
    if outcome.failure_message is not None:
        _raise_sanitized_failure(outcome.failure_message)
    if outcome.completed is None:
        _raise_sanitized_failure("command execution returned no result")
    return outcome.completed


def version_output(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise E2EFailure(f"version command failed: {' '.join(command)}")
    return completed.stdout.strip()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def reserve_tcp_udp_port() -> int:
    for _ in range(32):
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_listener,
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_listener,
        ):
            tcp_listener.bind(("127.0.0.1", 0))
            port = int(tcp_listener.getsockname()[1])
            try:
                udp_listener.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise E2EFailure("could not reserve a local TCP/UDP port for coturn")


def _perform_http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 3,
) -> _HTTPJSONOutcome:
    try:
        headers = {"Accept": "application/json"}
        encoded = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body, separators=(",", ":")).encode()
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        call = request.Request(url, data=encoded, headers=headers, method=method)
        with request.urlopen(call, timeout=timeout) as response:
            return _HTTPJSONOutcome(
                status=response.status,
                payload=json.load(response),
                failure_message=None,
            )
    except error.HTTPError as exception:
        try:
            response_payload = exception.read()
            failure_message = (
                "local service HTTP request failed "
                f"(status={exception.code}, response_bytes={len(response_payload)}, "
                f"response_sha256={hashlib.sha256(response_payload).hexdigest()})"
            )
        except Exception:
            failure_message = "local service HTTP request failed without a safe response"
        finally:
            try:
                exception.close()
            except Exception:
                pass
            exception.fp = None
            exception.__traceback__ = None
            exception.__cause__ = None
            exception.__context__ = None
        return _HTTPJSONOutcome(
            status=None,
            payload=None,
            failure_message=failure_message,
        )
    except Exception as exception:
        exception.__traceback__ = None
        exception.__cause__ = None
        exception.__context__ = None
        return _HTTPJSONOutcome(
            status=None,
            payload=None,
            failure_message="local service HTTP request failed without a safe response",
        )


def http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 3,
) -> tuple[int, dict[str, object]]:
    outcome = _perform_http_json(
        method,
        url,
        token=token,
        body=body,
        timeout=timeout,
    )
    method = ""
    url = ""
    token = None
    body = None
    timeout = 0
    if outcome.failure_message is not None:
        _raise_sanitized_failure(outcome.failure_message)
    if outcome.status is None or outcome.payload is None:
        _raise_sanitized_failure("local service HTTP request returned no result")
    return outcome.status, outcome.payload


def http_text(url: str, token: str, timeout: float = 3) -> str:
    call = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(call, timeout=timeout) as response:
        return response.read().decode("utf-8")


def wait_for_health(base_url: str, process: subprocess.Popen[str], timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise E2EFailure(f"signaling exited before health check ({process.returncode})")
        try:
            status, payload = http_json("GET", f"{base_url}/healthz")
            if status == 200 and payload == {"status": "ok"}:
                return
        except (OSError, E2EFailure, http.client.HTTPException) as exception:
            last_error = str(exception)
        time.sleep(0.05)
    raise E2EFailure(f"signaling health timeout: {last_error}")


def stop_process(process: subprocess.Popen[str], timeout: int = 5) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


@contextmanager
def private_temporary_directory(prefix: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        yield root


def coturn_residue_snapshot() -> set[str]:
    return {
        path
        for pattern in COTURN_LEGACY_RESIDUE_PATTERNS
        for path in glob(pattern)
    }


def assert_no_new_coturn_residue(before: set[str]) -> None:
    created = sorted(coturn_residue_snapshot() - before)
    if created:
        names = ", ".join(Path(path).name for path in created)
        raise E2EFailure(f"coturn created legacy /var/tmp residue: {names}")
