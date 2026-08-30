#!/usr/bin/env python3
"""Read-only relay deployment readiness preflight.

This command checks the public prerequisites for the Phase 3 relay stack without
claiming a production pass. DNS, public readiness, and optional remote host
checks are run only when the operator supplies the prerequisites; any missing or
blocked prerequisite produces a BLOCKED report. Private SSH alias values, host
addresses, usernames, tokens, and filesystem paths are never written to the
report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse


SCHEMA = "dev.vibescreen.phase3-relay-deployment-readiness/v1"
PASS_RESULT = "pass"
BLOCKED_RESULT = "blocked"
DEFAULT_RELAY_HOST = "relay.taoai.site"
DEFAULT_READY_URL = "https://relay.taoai.site/readyz"
DEFAULT_TIMEOUT_SECONDS = 10.0
MINIMUM_DEPLOYMENT_AVAILABLE_KIB = 5 * 1024 * 1024
MAXIMUM_DEPLOYMENT_USED_PERCENT = 85
SSH_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
COMPOSE_PROJECT_NAME = "vibe-screen-phase3-production"
UNKNOWN_CONTAINER_SERVICE = "__unknown__"
REQUIRED_LISTENERS = frozenset(
    {
        ("tcp", 3478),
        ("udp", 3478),
        ("tcp", 5349),
        ("tcp", 8088),
        ("tcp", 8090),
    }
)
REQUIRED_CONTAINER_SERVICES = frozenset({"signaling", "relay", "coturn"})


class PreflightError(RuntimeError):
    """Raised when one deployment-readiness check cannot pass."""


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _check(name: str, operation: Callable[[], tuple[str, str]]) -> dict[str, str]:
    try:
        result, detail = operation()
    except PreflightError as error:
        return {"name": name, "result": BLOCKED_RESULT, "detail": str(error)}
    return {"name": name, "result": result, "detail": detail}


def _block(message: str) -> tuple[str, str]:
    raise PreflightError(message)


def _validate_ssh_alias(alias: str | None) -> tuple[str, str] | None:
    if not alias:
        return BLOCKED_RESULT, "operator SSH alias was not provided"
    if not SSH_ALIAS_PATTERN.fullmatch(alias) or alias.startswith("-"):
        return BLOCKED_RESULT, "SSH alias contains invalid characters"
    return None


def _safe_remote_result(completed: subprocess.CompletedProcess[bytes], label: str) -> tuple[str, str]:
    if completed.returncode != 0:
        return BLOCKED_RESULT, f"{label} returned non-zero"
    if completed.stderr.strip():
        return BLOCKED_RESULT, f"{label} reported stderr"
    return PASS_RESULT, f"{label} completed"


def dns_check(relay_host: str, *, family: int, timeout_seconds: float) -> dict[str, Any]:
    addresses = _resolve(relay_host, family=family, timeout_seconds=timeout_seconds)
    if not addresses:
        raise PreflightError("relay DNS resolved to no addresses")
    return {
        "record_count": len(addresses),
        "resolved_address_hashes": sorted(stable_hash(address) for address in addresses),
    }


def dns_status(relay_host: str, *, family: int, timeout_seconds: float) -> tuple[str, str]:
    dns_check(relay_host, family=family, timeout_seconds=timeout_seconds)
    return PASS_RESULT, "ok"


def _resolve(host: str, *, family: int, timeout_seconds: float) -> list[str]:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError

    try:
        signal.signal(signal.SIGALRM, handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        infos = socket.getaddrinfo(host, None, family=family, type=socket.SOCK_STREAM)
    except TimeoutError as error:
        raise PreflightError("relay DNS resolution timed out") from error
    except OSError as error:
        raise PreflightError("relay DNS resolution failed") from error
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        if previous_handler is None:
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
        else:
            signal.signal(signal.SIGALRM, previous_handler)
    return sorted({info[4][0] for info in infos})


def check_public_readyz(url: str, *, timeout_seconds: float) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        _block("relay readiness URL must use HTTPS")
    request_context = ssl.create_default_context()
    req = request.Request(url, headers={"User-Agent": "vibe-screen-phase3-relay-readiness-preflight"})
    try:
        with request.urlopen(req, timeout=timeout_seconds, context=request_context) as response:
            status = response.status
            body = response.read(64 * 1024)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise PreflightError("public relay readiness probe failed") from error
    if status < 200 or status >= 300:
        _block("public relay readiness returned non-2xx")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PreflightError("public relay readiness did not return JSON") from error
    if not isinstance(value, dict) or value.get("status") != "ok":
        _block("public relay readiness did not report status=ok")


def public_readyz_status(url: str, *, timeout_seconds: float) -> tuple[str, str]:
    check_public_readyz(url, timeout_seconds=timeout_seconds)
    return PASS_RESULT, "ok"


def ssh_alias_available(alias: str | None) -> tuple[str, str]:
    invalid = _validate_ssh_alias(alias)
    if invalid is not None:
        return invalid
    completed = _run(["ssh", "-G", alias], timeout_seconds=5.0)
    if completed.returncode != 0:
        return BLOCKED_RESULT, "SSH alias config lookup failed"
    return PASS_RESULT, "SSH alias config is available"


def remote_command(alias: str | None, args: Sequence[str], *, timeout_seconds: float, label: str) -> tuple[str, str]:
    invalid = _validate_ssh_alias(alias)
    if invalid is not None:
        return BLOCKED_RESULT, "remote host command skipped without SSH alias" if not alias else invalid[1]
    completed = _run(["ssh", alias, *list(args)], timeout_seconds=timeout_seconds)
    return _safe_remote_result(completed, label)


def parse_deployment_df(stdout: bytes) -> tuple[int, int]:
    text = stdout.decode("utf-8", errors="replace")
    for line in text.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 6 or columns[-1] != "/":
            continue
        try:
            available_kib = int(columns[3])
            used_percent = int(columns[4].rstrip("%"))
        except ValueError as error:
            raise PreflightError("deployment disk usage could not be parsed") from error
        return available_kib, used_percent
    raise PreflightError("deployment filesystem row was not found")


def _format_listener(listener: tuple[str, int]) -> str:
    protocol, port = listener
    return f"{protocol}/{port}"


def _port_from_endpoint(endpoint: str) -> int | None:
    try:
        raw_port = endpoint.rsplit(":", 1)[1]
        return int(raw_port)
    except (IndexError, ValueError):
        return None


def parse_listening_ports(stdout: bytes) -> set[tuple[str, int]]:
    observed: set[tuple[str, int]] = set()
    text = stdout.decode("utf-8", errors="replace")
    for line in text.splitlines():
        columns = line.split()
        if len(columns) < 5:
            continue
        protocol = columns[0].lower()
        if protocol.startswith("tcp"):
            protocol = "tcp"
        elif protocol.startswith("udp"):
            protocol = "udp"
        else:
            continue
        port = _port_from_endpoint(columns[4])
        if port is not None:
            observed.add((protocol, port))
    if not observed:
        raise PreflightError("deployment listening-port snapshot is empty")
    return observed


def parse_container_services(stdout: bytes) -> set[str]:
    services: set[str] = set()
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        identifier = line.strip()
        if not identifier:
            continue
        if identifier in REQUIRED_CONTAINER_SERVICES:
            services.add(identifier)
            continue
        matched = False
        for service in REQUIRED_CONTAINER_SERVICES:
            if identifier.startswith(f"{COMPOSE_PROJECT_NAME}-{service}-"):
                services.add(service)
                matched = True
                break
        if not matched:
            services.add(UNKNOWN_CONTAINER_SERVICE)
    if not services:
        raise PreflightError("deployment container snapshot is empty")
    return services


def _run(args: Sequence[str], *, timeout_seconds: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError("deployment preflight command could not complete") from error


def check_docker_engine(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    return remote_command(alias, ["docker", "--version"], timeout_seconds=timeout_seconds, label="docker engine check")


def check_docker_compose(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    return remote_command(alias, ["docker", "compose", "version"], timeout_seconds=timeout_seconds, label="docker compose check")


def check_disk_headroom(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    invalid = _validate_ssh_alias(alias)
    if invalid is not None:
        return BLOCKED_RESULT, "remote host command skipped without SSH alias" if not alias else invalid[1]
    completed = _run(["ssh", alias, "df", "-Pk", "/"], timeout_seconds=timeout_seconds)
    result, detail = _safe_remote_result(completed, "deployment disk headroom check")
    if result != PASS_RESULT:
        return result, detail
    available_kib, used_percent = parse_deployment_df(completed.stdout)
    if available_kib < MINIMUM_DEPLOYMENT_AVAILABLE_KIB or used_percent > MAXIMUM_DEPLOYMENT_USED_PERCENT:
        return BLOCKED_RESULT, "deployment filesystem headroom is below production threshold"
    return PASS_RESULT, "deployment filesystem has sufficient production headroom"


def check_listening_ports(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    invalid = _validate_ssh_alias(alias)
    if invalid is not None:
        return BLOCKED_RESULT, "remote host command skipped without SSH alias" if not alias else invalid[1]
    completed = _run(["ssh", alias, "ss", "-H", "-ltnup"], timeout_seconds=timeout_seconds)
    result, detail = _safe_remote_result(completed, "listening port check")
    if result != PASS_RESULT:
        return result, detail
    observed = parse_listening_ports(completed.stdout)
    missing = REQUIRED_LISTENERS - observed
    if missing:
        formatted = ", ".join(_format_listener(listener) for listener in sorted(missing))
        return BLOCKED_RESULT, f"deployment listeners missing required ports: {formatted}"
    return PASS_RESULT, f"required deployment listeners observed: {len(REQUIRED_LISTENERS)}"


def check_existing_containers(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    invalid = _validate_ssh_alias(alias)
    if invalid is not None:
        return BLOCKED_RESULT, "remote host command skipped without SSH alias" if not alias else invalid[1]
    completed = _run(
        [
            "ssh",
            alias,
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={COMPOSE_PROJECT_NAME}",
            "--filter",
            "status=running",
            "--format",
            "{{.Names}}",
        ],
        timeout_seconds=timeout_seconds,
    )
    result, detail = _safe_remote_result(completed, "container status check")
    if result != PASS_RESULT:
        return result, detail
    services = parse_container_services(completed.stdout)
    missing = REQUIRED_CONTAINER_SERVICES - services
    has_unknown = UNKNOWN_CONTAINER_SERVICE in services
    if missing:
        return BLOCKED_RESULT, f"deployment containers missing required services: {', '.join(sorted(missing))}"
    if has_unknown:
        return BLOCKED_RESULT, "deployment containers include unexpected services"
    return PASS_RESULT, f"required deployment containers observed: {len(REQUIRED_CONTAINER_SERVICES)}"


def check_reverse_proxy(alias: str | None, *, timeout_seconds: float) -> tuple[str, str]:
    return remote_command(
        alias,
        ["curl", "-fsS", "http://127.0.0.1:8088/readyz"],
        timeout_seconds=timeout_seconds,
        label="local reverse proxy readiness check",
    )


def build_report(
    *,
    relay_host: str,
    ready_url: str,
    ssh_alias: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    checks: list[dict[str, str]] = []

    dns_values = {
        "dns_a_records": {"record_count": 0, "resolved_address_hashes": []},
        "dns_aaaa_records": {"record_count": 0, "resolved_address_hashes": []},
    }

    def record_dns_status(name: str, family: int) -> tuple[str, str]:
        dns_values[name] = dns_check(
            relay_host,
            family=family,
            timeout_seconds=timeout_seconds,
        )
        return PASS_RESULT, "ok"

    dns_operations = (
        ("dns_a_records", lambda: record_dns_status("dns_a_records", socket.AF_INET)),
        ("dns_aaaa_records", lambda: record_dns_status("dns_aaaa_records", socket.AF_INET6)),
    )
    for name, operation in (
        *dns_operations,
        ("ssh_alias_available", lambda: ssh_alias_available(ssh_alias)),
        ("docker_engine", lambda: check_docker_engine(ssh_alias, timeout_seconds=timeout_seconds)),
        ("docker_compose", lambda: check_docker_compose(ssh_alias, timeout_seconds=timeout_seconds)),
        ("disk_headroom", lambda: check_disk_headroom(ssh_alias, timeout_seconds=timeout_seconds)),
        ("listening_ports", lambda: check_listening_ports(ssh_alias, timeout_seconds=timeout_seconds)),
        ("existing_containers", lambda: check_existing_containers(ssh_alias, timeout_seconds=timeout_seconds)),
        ("reverse_proxy", lambda: check_reverse_proxy(ssh_alias, timeout_seconds=timeout_seconds)),
        ("public_readyz", lambda: public_readyz_status(ready_url, timeout_seconds=timeout_seconds)),
    ):
        check = _check(name, operation)
        checks.append(check)

    safe["dns"] = {
        "relay_host_hash": stable_hash(relay_host),
        "a_record_count": dns_values["dns_a_records"]["record_count"],
        "aaaa_record_count": dns_values["dns_aaaa_records"]["record_count"],
        "resolved_address_hashes": sorted(
            set(dns_values["dns_a_records"]["resolved_address_hashes"])
            | set(dns_values["dns_aaaa_records"]["resolved_address_hashes"])
        ),
    }

    safe["ssh_alias_provided"] = bool(ssh_alias)
    safe["ready_url_hash"] = stable_hash(ready_url)
    result = PASS_RESULT if all(check["result"] == PASS_RESULT for check in checks) else BLOCKED_RESULT
    return {
        "schema": SCHEMA,
        "kind": "phase3_relay_deployment_readiness",
        "result": result,
        "checks": checks,
        "deployment": safe,
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "operator_paths_recorded": False,
            "ssh_alias_recorded": False,
        },
        "limitations": [] if result == PASS_RESULT else ["blocked_before_relay_deployment"],
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-host", default=DEFAULT_RELAY_HOST)
    parser.add_argument("--ready-url", default=DEFAULT_READY_URL)
    parser.add_argument("--ssh-alias")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-blocked", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    if args.timeout_seconds <= 0:
        print("error: --timeout-seconds must be positive", file=sys.stderr)
        return 2
    try:
        report = build_report(
            relay_host=args.relay_host,
            ready_url=args.ready_url,
            ssh_alias=args.ssh_alias,
            timeout_seconds=args.timeout_seconds,
        )
        write_json(args.output, report)
    except (OSError, PreflightError) as error:
        print(f"Phase 3 relay deployment readiness preflight: FAIL ({error})", file=sys.stderr)
        return 1
    if report["result"] == BLOCKED_RESULT:
        print("Phase 3 relay deployment readiness preflight: BLOCKED", file=sys.stderr)
        return 0 if args.allow_blocked else 2
    print("Phase 3 relay deployment readiness preflight: PASS", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
