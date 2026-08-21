"""Fail-closed Phase 3 public Internet evidence helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PREFLIGHT_SCHEMA = "dev.vibescreen.phase3-public-internet-preflight/v1"
VERIFIER_SCHEMA = "dev.vibescreen.phase3-remote-turn-verifier/v1"
SOAK_SCHEMA = "dev.vibescreen.phase3-public-internet-soak/v1"
BLOCKED_RESULT = "blocked"
PASS_RESULT = "pass"
FAIL_RESULT = "fail"
MINIMUM_SECRET_BYTES = 32
DEFAULT_TIMEOUT_SECONDS = 10.0
TWO_HOUR_SECONDS = 2 * 60 * 60
MINIMUM_TWO_HOUR_SECONDS = int(TWO_HOUR_SECONDS * 0.98)
PLACEHOLDER_HOST_RE = re.compile(r"(^|\.)(example|example\.(?:com|net|org)|invalid)$", re.IGNORECASE)
SUPPORTED_TURN_TRANSPORTS = {"udp", "tcp", "tls"}
REQUIRED_COTURN_LINES = {
    "use-auth-secret",
    "fingerprint",
    "no-multicast-peers",
    "tls-listening-port=5349",
    "cert=/run/secrets/tls_certificate",
    "pkey=/run/secrets/tls_private_key",
}
REQUIRED_COTURN_DENIES = {
    "denied-peer-ip=10.0.0.0-10.255.255.255",
    "denied-peer-ip=100.64.0.0-100.127.255.255",
    "denied-peer-ip=127.0.0.0-127.255.255.255",
    "denied-peer-ip=169.254.0.0-169.254.255.255",
    "denied-peer-ip=172.16.0.0-172.31.255.255",
    "denied-peer-ip=192.168.0.0-192.168.255.255",
    "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
}
REQUIRED_DEPLOYMENT_PREREQUISITES = (
    "production relay config with authority_mode=production_authority",
    "PostgreSQL storage with sslmode=verify-full for relay and authority",
    "public TURN DNS name resolving only to globally routable addresses",
    "TURN TLS on turns: port 5349 with a deployed certificate chain",
    "file-backed TURN REST secret shared only by relay and coturn",
    "coturn production ACL with private, CGNAT, loopback, link-local, and ULA denies",
    "Authority and relay readiness verified before routing clients",
    "Android device and macOS Host artifacts built from the recorded source revision",
    "two-hour mixed direct/relay/network-change soak with nonce-reuse checks",
)


class PublicInternetEvidenceError(RuntimeError):
    """Raised when public Internet evidence cannot be trusted."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "result": PASS_RESULT if self.passed else BLOCKED_RESULT,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TurnURI:
    scheme: str
    host: str
    port: int
    transport: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicInternetEvidenceError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise PublicInternetEvidenceError(f"{label} must be a JSON object")
    return value


def read_secret_file(path: Path, label: str) -> str:
    try:
        metadata = path.stat()
    except OSError as error:
        raise PublicInternetEvidenceError(f"{label} is not readable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise PublicInternetEvidenceError(f"{label} must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PublicInternetEvidenceError(f"{label} must not grant group or world permissions")
    value = path.read_text(encoding="utf-8").strip()
    if len(value.encode("utf-8")) < MINIMUM_SECRET_BYTES:
        raise PublicInternetEvidenceError(f"{label} must contain at least {MINIMUM_SECRET_BYTES} bytes")
    if "\n" in value or "\r" in value:
        raise PublicInternetEvidenceError(f"{label} must contain exactly one line")
    return value


def _parse_host_port(authority: str, default_port: int) -> tuple[str, int]:
    if authority.startswith("["):
        close = authority.find("]")
        if close == -1:
            raise PublicInternetEvidenceError("TURN URI has malformed IPv6 host")
        host = authority[1:close]
        remainder = authority[close + 1 :]
        if remainder.startswith(":"):
            port_text = remainder[1:]
        elif remainder == "":
            port_text = str(default_port)
        else:
            raise PublicInternetEvidenceError("TURN URI has malformed host/port")
    else:
        parts = authority.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            host, port_text = parts
        else:
            host, port_text = authority, str(default_port)
    if not host:
        raise PublicInternetEvidenceError("TURN URI host is empty")
    try:
        port = int(port_text)
    except ValueError as error:
        raise PublicInternetEvidenceError("TURN URI port is not numeric") from error
    if port < 1 or port > 65535:
        raise PublicInternetEvidenceError("TURN URI port is outside 1..65535")
    return host, port


def parse_turn_uri(uri: str) -> TurnURI:
    if not isinstance(uri, str) or not uri.strip():
        raise PublicInternetEvidenceError("TURN URI must be a non-empty string")
    scheme, separator, rest = uri.partition(":")
    scheme = scheme.lower()
    if separator != ":" or scheme not in {"turn", "turns"}:
        raise PublicInternetEvidenceError("TURN URI must use turn: or turns:")
    authority, _, query = rest.partition("?")
    default_port = 5349 if scheme == "turns" else 3478
    host, port = _parse_host_port(authority, default_port)
    transport = "udp"
    if query:
        parsed_query = dict(
            item.split("=", 1) if "=" in item else (item, "")
            for item in query.split("&")
            if item
        )
        transport = parsed_query.get("transport", transport).lower()
    if transport not in SUPPORTED_TURN_TRANSPORTS:
        raise PublicInternetEvidenceError("TURN URI transport is unsupported")
    if scheme == "turns" and transport != "tcp":
        raise PublicInternetEvidenceError("turns: URI must use transport=tcp")
    return TurnURI(scheme=scheme, host=host, port=port, transport=transport)


def _is_placeholder_host(host: str) -> bool:
    normalized = host.strip(".").lower()
    return (
        normalized in {"localhost", "example", "invalid"}
        or normalized.endswith(".local")
        or normalized.endswith(".localhost")
        or normalized.endswith(".example")
        or normalized.endswith(".example.com")
        or normalized.endswith(".example.net")
        or normalized.endswith(".example.org")
        or normalized.endswith(".invalid")
    )


def _public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_global


def require_public_remote_host(host: str, *, resolve: bool = True) -> tuple[str, ...]:
    if _is_placeholder_host(host):
        raise PublicInternetEvidenceError("TURN host is local, reserved, or a placeholder")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise PublicInternetEvidenceError("TURN host address is not globally routable")
        return (host,)
    if not resolve:
        raise PublicInternetEvidenceError("TURN host DNS resolution is required for public evidence")
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as error:
        raise PublicInternetEvidenceError("TURN host could not be resolved") from error
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise PublicInternetEvidenceError("TURN host resolved to no addresses")
    if not all(_public_address(address) for address in addresses):
        raise PublicInternetEvidenceError("TURN host resolved to a non-public address")
    return tuple(addresses)


def _external_ip_public_part(value: str) -> str:
    public_part = value.split("/", 1)[0].strip()
    if not public_part or not _public_address(public_part):
        raise PublicInternetEvidenceError("COTURN_EXTERNAL_IP public side is not globally routable")
    return public_part


def _load_coturn_lines(path: Path) -> set[str]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PublicInternetEvidenceError("coturn production configuration is not readable") from error
    return {
        line.strip()
        for line in raw_lines
        if line.strip() and not line.lstrip().startswith("#")
    }


def _file_has_private_mode(path: Path, label: str) -> str:
    try:
        metadata = path.stat()
    except OSError as error:
        raise PublicInternetEvidenceError(f"{label} is not readable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise PublicInternetEvidenceError(f"{label} must be a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_url_ready(url: str, label: str, timeout: float) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise PublicInternetEvidenceError(f"{label} readiness URL is invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PublicInternetEvidenceError(f"{label} readiness URL must use HTTPS unless loopback")
    request = Request(url, headers={"User-Agent": "vibe-screen-phase3-preflight"})
    context = ssl.create_default_context() if parsed.scheme == "https" else None
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            status = response.status
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise PublicInternetEvidenceError(f"{label} readiness probe failed") from error
    if status < 200 or status >= 300:
        raise PublicInternetEvidenceError(f"{label} readiness returned non-2xx")


def _check(name: str, operation: Any) -> tuple[Check, Any | None]:
    try:
        value = operation()
    except PublicInternetEvidenceError as error:
        return Check(name, False, str(error)), None
    return Check(name, True, "ok"), value


def build_preflight_report(
    *,
    relay_config_path: Path,
    coturn_config_path: Path,
    turn_secret_file: Path | None,
    tls_certificate: Path | None,
    tls_private_key: Path | None,
    coturn_external_ip: str | None,
    authority_ready_url: str | None,
    relay_ready_url: str | None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    checks: list[Check] = []
    safe_relay: dict[str, Any] = {}
    safe_coturn: dict[str, Any] = {}
    readiness = {
        "authority_ready_checked": authority_ready_url is not None,
        "relay_ready_checked": relay_ready_url is not None,
    }

    def relay_config() -> dict[str, Any]:
        value = read_json(relay_config_path, "relay production config")
        if value.get("storage_backend") != "postgres":
            raise PublicInternetEvidenceError("relay storage_backend must be postgres")
        if value.get("authority_mode") != "production_authority":
            raise PublicInternetEvidenceError("relay authority_mode must be production_authority")
        authority_url = str(value.get("authority_url", ""))
        parsed_authority = urlparse(authority_url)
        if parsed_authority.scheme != "https" or not parsed_authority.hostname:
            raise PublicInternetEvidenceError("relay authority_url must be HTTPS")
        if _is_placeholder_host(parsed_authority.hostname):
            raise PublicInternetEvidenceError("relay authority_url still uses a placeholder hostname")
        # Authority is commonly private behind the public relay deployment; the
        # public reachability gate belongs to TURN and the readiness probes.
        source_id = str(value.get("authority_source_id", ""))
        if not source_id or "example" in source_id.lower():
            raise PublicInternetEvidenceError("relay authority_source_id must be production-specific")
        uris = value.get("turn_uris")
        if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) for uri in uris):
            raise PublicInternetEvidenceError("relay turn_uris must be a non-empty string array")
        parsed_uris = [parse_turn_uri(uri) for uri in uris]
        if not any(uri.scheme == "turns" and uri.port == 5349 for uri in parsed_uris):
            raise PublicInternetEvidenceError("relay turn_uris must include turns: on port 5349")
        resolved = {uri.host: require_public_remote_host(uri.host) for uri in parsed_uris}
        realm = str(value.get("turn_realm", ""))
        if not realm or _is_placeholder_host(realm):
            raise PublicInternetEvidenceError("turn_realm must be a production public DNS name")
        safe_relay.update(
            {
                "turn_uri_count": len(parsed_uris),
                "turns_uri_count": sum(1 for uri in parsed_uris if uri.scheme == "turns"),
                "turn_host_hashes": sorted(stable_hash(host) for host in resolved),
                "resolved_address_hashes": sorted(
                    stable_hash(address) for addresses in resolved.values() for address in addresses
                ),
                "storage_backend": value.get("storage_backend"),
                "authority_mode": value.get("authority_mode"),
                "authority_source_id_hash": stable_hash(source_id),
                "turn_realm_hash": stable_hash(realm),
            }
        )
        return value

    def coturn_config() -> set[str]:
        lines = _load_coturn_lines(coturn_config_path)
        missing = sorted(REQUIRED_COTURN_LINES - lines)
        if missing:
            raise PublicInternetEvidenceError("coturn production config is missing required TLS/auth lines")
        missing_denies = sorted(REQUIRED_COTURN_DENIES - lines)
        if missing_denies:
            raise PublicInternetEvidenceError("coturn production config is missing required private peer denies")
        if any(line.startswith("allowed-peer-ip=") for line in lines):
            raise PublicInternetEvidenceError("coturn production config must not include allowed-peer-ip overrides")
        if any(line in {"no-auth", "lt-cred-mech"} for line in lines):
            raise PublicInternetEvidenceError("coturn production config contains an incompatible auth mode")
        safe_coturn.update(
            {
                "tls_listening_port": 5349,
                "uses_shared_auth_material": True,
                "fingerprint": True,
                "private_peer_deny_count": sum(1 for line in lines if line.startswith("denied-peer-ip=")),
                "allowed_peer_ip_count": 0,
            }
        )
        return lines

    for name, operation in (
        ("relay_production_config", relay_config),
        ("coturn_production_config", coturn_config),
        ("turn_secret_file", lambda: read_secret_file(_require_path(turn_secret_file, "turn secret file"), "turn secret file")),
        ("tls_certificate", lambda: _certificate_fingerprint(_require_path(tls_certificate, "TLS certificate"))),
        ("tls_private_key", lambda: _private_key_check(_require_path(tls_private_key, "TLS private key"))),
        ("coturn_external_ip", lambda: _external_ip_public_part(_require_text(coturn_external_ip, "COTURN_EXTERNAL_IP"))),
        ("authority_readiness", lambda: _check_url_ready(_require_text(authority_ready_url, "authority readiness URL"), "authority", timeout_seconds)),
        ("relay_readiness", lambda: _check_url_ready(_require_text(relay_ready_url, "relay readiness URL"), "relay", timeout_seconds)),
    ):
        check, value = _check(name, operation)
        checks.append(check)
        if check.passed and name == "tls_certificate" and isinstance(value, str):
            safe_coturn["tls_certificate_sha256"] = value
        if check.passed and name == "tls_private_key":
            safe_coturn["tls_private_key_present"] = True
        if check.passed and name == "coturn_external_ip" and isinstance(value, str):
            safe_coturn["external_ip_hash"] = stable_hash(value)

    passed = all(check.passed for check in checks)
    return {
        "schema": PREFLIGHT_SCHEMA,
        "kind": "phase3_public_internet_remote_turn_preflight",
        "result": PASS_RESULT if passed else BLOCKED_RESULT,
        "created_at": utc_now(),
        "deployment_prerequisites": list(REQUIRED_DEPLOYMENT_PREREQUISITES),
        "checks": [check.as_json() for check in checks],
        "relay": safe_relay,
        "coturn": safe_coturn,
        "readiness": readiness,
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
        },
        "limitations": [] if passed else ["blocked_before_public_internet_or_remote_turn_evidence"],
    }


def _require_path(path: Path | None, label: str) -> Path:
    if path is None:
        raise PublicInternetEvidenceError(f"{label} must be provided")
    return path


def _require_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise PublicInternetEvidenceError(f"{label} must be provided")
    return value.strip()


def _certificate_fingerprint(path: Path) -> str:
    digest = _file_has_private_mode(path, "TLS certificate")
    content = path.read_text(encoding="utf-8", errors="ignore")
    if "BEGIN CERTIFICATE" not in content:
        raise PublicInternetEvidenceError("TLS certificate must contain a PEM certificate")
    return digest


def _private_key_check(path: Path) -> bool:
    try:
        metadata = path.stat()
    except OSError as error:
        raise PublicInternetEvidenceError("TLS private key is not readable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise PublicInternetEvidenceError("TLS private key must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PublicInternetEvidenceError("TLS private key must not grant group or world permissions")
    content = path.read_text(encoding="utf-8", errors="ignore")
    if "PRIVATE KEY" not in content:
        raise PublicInternetEvidenceError("TLS private key must contain PEM private key material")
    return True


def preflight_passed(report: dict[str, Any]) -> bool:
    return report.get("schema") == PREFLIGHT_SCHEMA and report.get("result") == PASS_RESULT


def _http_json(
    *,
    url: str,
    token: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "vibe-screen-phase3-remote-turn-verifier",
        },
        method="POST",
    )
    parsed = urlparse(url)
    context = ssl.create_default_context() if parsed.scheme == "https" else None
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            status = response.status
            response_body = response.read(1024 * 1024)
    except HTTPError as error:
        try:
            error.read(1024 * 1024)
        finally:
            return error.code, {}
    except (URLError, TimeoutError, OSError) as error:
        raise PublicInternetEvidenceError("relay credential request failed") from error
    try:
        value = json.loads(response_body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PublicInternetEvidenceError("relay credential response is not JSON") from error
    if not isinstance(value, dict):
        raise PublicInternetEvidenceError("relay credential response must be a JSON object")
    return status, value


def parse_turnutils_counts(output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in ("tot_send_msgs", "tot_recv_msgs"):
        matches = re.findall(rf"{name}=([0-9]+)", output)
        if matches:
            counts[name] = int(matches[-1])
    return counts


def _credential_turn_uris(value: dict[str, Any]) -> list[TurnURI]:
    uris = value.get("uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) for uri in uris):
        raise PublicInternetEvidenceError("credential response did not contain TURN URIs")
    parsed = [parse_turn_uri(uri) for uri in uris]
    for uri in parsed:
        require_public_remote_host(uri.host)
    if not any(uri.scheme == "turns" and uri.port == 5349 for uri in parsed):
        raise PublicInternetEvidenceError("credential response did not include remote TURN TLS")
    return parsed


def build_verifier_report(
    *,
    preflight_path: Path,
    relay_url: str,
    client_token_file: Path,
    device_id: str,
    session_id: str,
    allocation_id: str,
    peer_host: str,
    peer_port: int,
    turnutils_uclient: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    messages: int = 5,
) -> dict[str, Any]:
    preflight = read_json(preflight_path, "public Internet preflight")
    if not preflight_passed(preflight):
        raise PublicInternetEvidenceError("public Internet preflight did not pass")
    if not all(value.strip() for value in (relay_url, device_id, session_id, allocation_id)):
        raise PublicInternetEvidenceError("relay URL and allocation identity fields are required")
    parsed_relay = urlparse(relay_url)
    if parsed_relay.scheme not in {"https", "http"} or not parsed_relay.netloc:
        raise PublicInternetEvidenceError("relay URL is invalid")
    if parsed_relay.scheme == "http" and parsed_relay.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PublicInternetEvidenceError("relay URL must use HTTPS unless loopback-local to the production host")
    if peer_port < 1 or peer_port > 65535:
        raise PublicInternetEvidenceError("peer port is outside 1..65535")
    peer_addresses = require_public_remote_host(peer_host)
    token = read_secret_file(client_token_file, "relay client token file")
    credential_url = relay_url.rstrip("/") + "/v1/credentials"
    status, credential = _http_json(
        url=credential_url,
        token=token,
        payload={
            "device_id": device_id,
            "session_id": session_id,
            "allocation_id": allocation_id,
            "ttl_seconds": 600,
        },
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise PublicInternetEvidenceError(f"relay credential request returned {status}")
    username = credential.get("username")
    password = credential.get("password")
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise PublicInternetEvidenceError("relay credential response is incomplete")
    parsed_uris = _credential_turn_uris(credential)
    preflight_hosts = set(preflight.get("relay", {}).get("turn_host_hashes", []))
    if not preflight_hosts:
        raise PublicInternetEvidenceError("public Internet preflight did not record TURN host hashes")
    runtime_hosts = {stable_hash(uri.host) for uri in parsed_uris}
    if not runtime_hosts.issubset(preflight_hosts):
        raise PublicInternetEvidenceError("relay credential TURN hosts do not match the passed preflight")
    udp_uri = next((uri for uri in parsed_uris if uri.scheme == "turn" and uri.transport == "udp"), parsed_uris[0])
    command = [
        turnutils_uclient,
        "-v",
        "-G",
        "-c",
        "-n",
        str(messages),
        "-u",
        username,
        "-w",
        password,
        "-e",
        peer_host,
        "-r",
        str(peer_port),
        "-p",
        str(udp_uri.port),
        udp_uri.host,
    ]
    if udp_uri.scheme == "turns":
        command.insert(1, "-S")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublicInternetEvidenceError("turnutils_uclient did not complete") from error
    elapsed = time.monotonic() - started
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    counts = parse_turnutils_counts(output)
    if completed.returncode != 0:
        raise PublicInternetEvidenceError("turnutils_uclient returned non-zero")
    if counts.get("tot_send_msgs", 0) <= 0 or counts.get("tot_recv_msgs", 0) <= 0:
        raise PublicInternetEvidenceError("TURN verifier did not exchange relayed messages")
    if "success" not in output.lower():
        raise PublicInternetEvidenceError("TURN verifier did not report success")
    return {
        "schema": VERIFIER_SCHEMA,
        "kind": "phase3_remote_turn_verifier",
        "result": PASS_RESULT,
        "created_at": utc_now(),
        "preflight_result": PASS_RESULT,
        "turn_allocation": {
            "status_code": status,
            "username_hash": stable_hash(username),
            "ttl_seconds": credential.get("ttl_seconds"),
            "realm_hash": stable_hash(str(credential.get("realm", ""))),
            "turn_uri_count": len(parsed_uris),
            "turns_uri_count": sum(1 for uri in parsed_uris if uri.scheme == "turns"),
        },
        "turn": {
            "remote_host_hash": stable_hash(udp_uri.host),
            "peer_host_hash": stable_hash(peer_host),
            "peer_resolved_address_hashes": sorted(stable_hash(address) for address in peer_addresses),
            "peer_port": peer_port,
            "port": udp_uri.port,
            "transport": udp_uri.transport,
            "scheme": udp_uri.scheme,
            "tot_send_msgs": counts["tot_send_msgs"],
            "tot_recv_msgs": counts["tot_recv_msgs"],
            "elapsed_seconds": round(elapsed, 3),
        },
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
        },
        "limitations": [],
    }


def _duration_for_preset(preset: str) -> int:
    if preset == "2h":
        return TWO_HOUR_SECONDS
    if preset == "30m":
        return 30 * 60
    if preset == "8h":
        return 8 * 60 * 60
    raise PublicInternetEvidenceError("unsupported soak preset")


def build_blocked_soak_report(
    *,
    preflight_path: Path | None,
    verifier_path: Path | None,
    preset: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema": SOAK_SCHEMA,
        "kind": "phase3_public_internet_soak",
        "result": BLOCKED_RESULT,
        "created_at": utc_now(),
        "preset": preset,
        "required_duration_seconds": _duration_for_preset(preset),
        "blocker": reason,
        "preflight": _summarize_input_result(preflight_path, PREFLIGHT_SCHEMA),
        "verifier": _summarize_input_result(verifier_path, VERIFIER_SCHEMA),
        "deployment_prerequisites": list(REQUIRED_DEPLOYMENT_PREREQUISITES),
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
        },
        "limitations": ["blocked_before_two_hour_public_internet_soak"],
    }


def _summarize_input_result(path: Path | None, expected_schema: str) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "result": BLOCKED_RESULT}
    try:
        document = read_json(path, "soak input")
    except PublicInternetEvidenceError:
        return {"provided": True, "result": BLOCKED_RESULT}
    if document.get("schema") != expected_schema:
        return {"provided": True, "result": BLOCKED_RESULT}
    return {"provided": True, "result": document.get("result", BLOCKED_RESULT)}


def validate_soak_summary(summary: dict[str, Any], *, preset: str) -> dict[str, Any]:
    duration = summary.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise PublicInternetEvidenceError("soak summary duration_seconds is required")
    if preset == "2h" and duration < MINIMUM_TWO_HOUR_SECONDS:
        raise PublicInternetEvidenceError("two-hour Internet soak duration is insufficient")
    route_counts = summary.get("route_counts")
    if not isinstance(route_counts, dict):
        raise PublicInternetEvidenceError("soak summary route_counts is required")
    if route_counts.get("direct", 0) <= 0 or route_counts.get("relay", 0) <= 0:
        raise PublicInternetEvidenceError("soak must include both direct and relay route samples")
    if summary.get("network_handoffs", 0) <= 0:
        raise PublicInternetEvidenceError("soak must include at least one network handoff")
    if summary.get("nonce_reuse_detected") is not False:
        raise PublicInternetEvidenceError("soak must prove no nonce reuse")
    metrics = summary.get("metrics")
    if not isinstance(metrics, dict):
        raise PublicInternetEvidenceError("soak summary metrics are required")
    required_metrics = ("rss", "queue", "loss", "rtt", "fps", "bitrate", "relay_bytes", "ice_restarts", "drops", "thermal", "battery")
    missing = [name for name in required_metrics if name not in metrics]
    if missing:
        raise PublicInternetEvidenceError("soak summary is missing required metric families")
    return {
        "duration_seconds": duration,
        "route_counts": route_counts,
        "network_handoffs": summary.get("network_handoffs"),
        "nonce_reuse_detected": False,
        "metric_families": sorted(metrics),
    }


def build_soak_report(
    *,
    preflight_path: Path,
    verifier_path: Path,
    private_summary_path: Path,
    preset: str,
) -> dict[str, Any]:
    preflight = read_json(preflight_path, "public Internet preflight")
    if not preflight_passed(preflight):
        raise PublicInternetEvidenceError("public Internet preflight did not pass")
    verifier = read_json(verifier_path, "remote TURN verifier")
    if verifier.get("schema") != VERIFIER_SCHEMA or verifier.get("result") != PASS_RESULT:
        raise PublicInternetEvidenceError("remote TURN verifier did not pass")
    private_summary = read_json(private_summary_path, "private Internet soak summary")
    summary = validate_soak_summary(private_summary, preset=preset)
    return {
        "schema": SOAK_SCHEMA,
        "kind": "phase3_public_internet_soak",
        "result": PASS_RESULT,
        "created_at": utc_now(),
        "preset": preset,
        "required_duration_seconds": _duration_for_preset(preset),
        "preflight_result": PASS_RESULT,
        "verifier_result": PASS_RESULT,
        "summary": summary,
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
            "private_summary_uploaded": False,
        },
        "limitations": [],
    }
