#!/usr/bin/env python3
"""Fail-closed preflight for Phase 3 public NAT/TURN deployment evidence.

The command verifies the shape of a production TURN deployment package and
optionally validates sanitized remote-connectivity evidence. Missing public
addresses, credentials, quota controls, readiness probes, or remote TURN
connectivity are reported as BLOCKED. Local coturn, loopback, and synthetic peer
records are never promoted to public Internet pass evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Sequence
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

_OPENSSL_RUN = subprocess.run

SCHEMA = "dev.vibescreen.phase3-public-nat-turn-preflight/v1"
CONNECTIVITY_SCHEMA = "dev.vibescreen.phase3-public-nat-turn-connectivity/v1"
DEPLOYMENT_SCHEMA = "dev.vibescreen.phase3-public-nat-turn-deployment/v1"
PASS_RESULT = "pass"
BLOCKED_RESULT = "blocked"
MINIMUM_SECRET_BYTES = 32
MAXIMUM_TURN_TTL_SECONDS = 1800
DEFAULT_TIMEOUT_SECONDS = 10.0

REQUIRED_COTURN_LINES = {
    "use-auth-secret",
    "fingerprint",
    "no-multicast-peers",
    "no-cli",
    "no-tlsv1",
    "no-tlsv1_1",
    "tls-listening-port=5349",
    "cert=/run/secrets/tls_certificate",
    "pkey=/run/secrets/tls_private_key",
}
REQUIRED_COTURN_DENIES = {
    "denied-peer-ip=0.0.0.0-0.255.255.255",
    "denied-peer-ip=10.0.0.0-10.255.255.255",
    "denied-peer-ip=100.64.0.0-100.127.255.255",
    "denied-peer-ip=127.0.0.0-127.255.255.255",
    "denied-peer-ip=169.254.0.0-169.254.255.255",
    "denied-peer-ip=172.16.0.0-172.31.255.255",
    "denied-peer-ip=192.0.0.0-192.0.0.255",
    "denied-peer-ip=192.0.2.0-192.0.2.255",
    "denied-peer-ip=192.168.0.0-192.168.255.255",
    "denied-peer-ip=198.18.0.0-198.19.255.255",
    "denied-peer-ip=198.51.100.0-198.51.100.255",
    "denied-peer-ip=203.0.113.0-203.0.113.255",
    "denied-peer-ip=224.0.0.0-239.255.255.255",
    "denied-peer-ip=240.0.0.0-255.255.255.255",
    "denied-peer-ip=0:0:0:0:0:0:0:0-ff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=::ffff:0:0-::ffff:ffff:ffff",
    "denied-peer-ip=64:ff9b::-64:ff9b::ffff:ffff",
    "denied-peer-ip=64:ff9b:1::-64:ff9b:1:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=100::-100::ffff:ffff:ffff:ffff",
    "denied-peer-ip=2001::-2001:1ff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=2001:db8::-2001:db8:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=2002::-2002:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=fec0::-feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "denied-peer-ip=ff00::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
}
REQUIRED_RUNTIME_INPUTS = (
    "turn_secret_file",
    "tls_certificate",
    "tls_private_key",
    "coturn_external_ip",
    "authority_readiness",
    "relay_readiness",
    "connectivity_evidence",
    "external_connectivity_canary",
    "deployment_evidence",
)
BLOCKED_LIMITATION = "blocked_before_public_nat_turn_deployment_gate"
PRIVATE_DNS_SUFFIXES = (".corp", ".internal", ".lan", ".test")
MINIMUM_CREDENTIAL_REQUESTS_PER_MINUTE = 2
MINIMUM_CONCURRENT_SESSIONS_PER_DEVICE = 2
MINIMUM_DAILY_BYTES_PER_DEVICE = 1024 * 1024 * 1024
MINIMUM_USAGE_EVENT_BYTES = 1024 * 1024
MINIMUM_COTURN_USER_QUOTA = 2
MINIMUM_COTURN_TOTAL_QUOTA = 10
MINIMUM_COTURN_MAX_BPS = 1_000_000
MINIMUM_REMOTE_OBSERVER_COUNT = 2
SENSITIVE_EVIDENCE_KEYS = frozenset(
    {
        "admin_token",
        "api_key",
        "authorization",
        "bearer",
        "credential",
        "device_token",
        "host_token",
        "password",
        "private_key",
        "raw_credential",
        "secret",
        "shared_secret",
        "signaling_token",
        "token",
        "turn_password",
    }
)
SENSITIVE_EVIDENCE_SUFFIXES = ("token", "password", "secret", "credential", "private_key")
SENSITIVE_EVIDENCE_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class PreflightError(RuntimeError):
    """Raised when one preflight check cannot prove its requirement."""


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"cannot read {label}: {type(error).__name__}") from error
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must be a JSON object")
    return value


def reject_sensitive_evidence(value: Any, *, label: str, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise PreflightError(f"{label} contains a non-string key")
            normalized = key.lower().replace("-", "_")
            if normalized in SENSITIVE_EVIDENCE_KEYS or normalized.endswith(SENSITIVE_EVIDENCE_SUFFIXES):
                raise PreflightError(f"{label} must not contain secret-like field names")
            reject_sensitive_evidence(child, label=label, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_evidence(child, label=label, path=f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in SENSITIVE_EVIDENCE_VALUE_PATTERNS:
            if pattern.search(value):
                raise PreflightError(f"{label} must not contain secret material")


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


def _check(name: str, operation: Callable[[], Any]) -> tuple[dict[str, str], Any | None]:
    try:
        value = operation()
    except PreflightError as error:
        return {"name": name, "result": BLOCKED_RESULT, "detail": str(error)}, None
    return {"name": name, "result": PASS_RESULT, "detail": "ok"}, value


def _raise(message: str) -> None:
    raise PreflightError(message)


def _placeholder_host(host: str) -> bool:
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
        or normalized.endswith(PRIVATE_DNS_SUFFIXES)
    )


def _is_global_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if (
        parsed.is_unspecified
        or parsed.is_multicast
        or getattr(parsed, "is_site_local", False)
        or (parsed.version == 6 and ipaddress.IPv6Address("fec0::") <= parsed <= ipaddress.IPv6Address("feff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))
    ):
        return False
    return parsed.is_global


def _reject_non_dotted_ipv4_mapped(value: str) -> None:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return
    if not isinstance(parsed, ipaddress.IPv6Address) or parsed.ipv4_mapped is None:
        return
    try:
        ipaddress.IPv4Address(value.strip().lower().rsplit(":ffff:", 1)[1])
    except ValueError:
        raise PreflightError("IPv4-mapped addresses must use dotted IPv4 notation")


def require_public_host(host: str, *, resolve: bool) -> tuple[str, ...]:
    if not isinstance(host, str) or not host.strip():
        raise PreflightError("public host is empty")
    if _placeholder_host(host):
        raise PreflightError("host is local, reserved, or a placeholder")
    try:
        _reject_non_dotted_ipv4_mapped(host)
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_global_address(host):
            raise PreflightError("host address is not globally routable")
        return (host,)
    if not resolve:
        raise PreflightError("DNS resolution is required for public NAT/TURN pass evidence")
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as error:
        raise PreflightError("host DNS resolution failed") from error
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise PreflightError("host resolved to no addresses")
    if not all(_is_global_address(address) for address in addresses):
        raise PreflightError("host resolved to a non-public address")
    return tuple(addresses)


def parse_turn_uri(uri: str) -> dict[str, Any]:
    if not isinstance(uri, str) or not uri.strip():
        raise PreflightError("TURN URI must be a non-empty string")
    scheme, separator, rest = uri.partition(":")
    scheme = scheme.lower()
    if separator != ":" or scheme not in {"turn", "turns"}:
        raise PreflightError("TURN URI must use turn: or turns:")
    authority, _, query = rest.partition("?")
    default_port = 5349 if scheme == "turns" else 3478
    host, port = _parse_authority(authority, default_port)
    transport = "udp"
    if query:
        for item in query.split("&"):
            key, _, value = item.partition("=")
            if key == "transport":
                transport = value.lower()
    if transport not in {"udp", "tcp", "tls"}:
        raise PreflightError("TURN URI transport is unsupported")
    if scheme == "turns" and transport != "tcp":
        raise PreflightError("turns: URI must use transport=tcp")
    return {"scheme": scheme, "host": host, "port": port, "transport": transport}


def _parse_authority(authority: str, default_port: int) -> tuple[str, int]:
    if authority.startswith("["):
        close = authority.find("]")
        if close < 0:
            raise PreflightError("TURN URI has malformed IPv6 host")
        host = authority[1:close]
        remainder = authority[close + 1 :]
        port_text = remainder[1:] if remainder.startswith(":") else str(default_port)
    else:
        parts = authority.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            host, port_text = parts
        else:
            host, port_text = authority, str(default_port)
    try:
        port = int(port_text)
    except ValueError as error:
        raise PreflightError("TURN URI port is not numeric") from error
    if not host or port < 1 or port > 65535:
        raise PreflightError("TURN URI host or port is invalid")
    return host, port


def validate_relay_config(path: Path, *, resolve_dns: bool) -> dict[str, Any]:
    config = read_json(path, "relay production config")
    if config.get("storage_backend") != "postgres":
        raise PreflightError("relay storage_backend must be postgres")
    if config.get("authority_mode") != "production_authority":
        raise PreflightError("relay authority_mode must be production_authority")
    authority_url = str(config.get("authority_url", ""))
    parsed_authority = urlparse(authority_url)
    if parsed_authority.scheme != "https" or not parsed_authority.hostname:
        raise PreflightError("relay authority_url must be HTTPS")
    if _placeholder_host(parsed_authority.hostname):
        raise PreflightError("relay authority_url still uses a placeholder hostname")
    authority_addresses = require_public_host(parsed_authority.hostname, resolve=resolve_dns)
    authority_source_id = str(config.get("authority_source_id", ""))
    if not authority_source_id or "example" in authority_source_id.lower():
        raise PreflightError("relay authority_source_id must be production-specific")
    turn_realm = str(config.get("turn_realm", ""))
    if _placeholder_host(turn_realm):
        raise PreflightError("turn_realm must be a production public DNS name")
    turn_uris = config.get("turn_uris")
    if not isinstance(turn_uris, list) or not turn_uris or not all(isinstance(uri, str) for uri in turn_uris):
        raise PreflightError("turn_uris must be a non-empty string array")
    parsed_turn_uris = [parse_turn_uri(uri) for uri in turn_uris]
    if not any(uri["scheme"] == "turns" and uri["port"] == 5349 for uri in parsed_turn_uris):
        raise PreflightError("turn_uris must include turns: on port 5349")
    resolved_addresses: list[str] = []
    for uri in parsed_turn_uris:
        resolved_addresses.extend(require_public_host(uri["host"], resolve=resolve_dns))
    _validate_relay_quotas(config)
    return {
        "turn_uri_count": len(parsed_turn_uris),
        "turns_uri_count": sum(1 for uri in parsed_turn_uris if uri["scheme"] == "turns"),
        "turn_host_hashes": sorted({stable_hash(uri["host"]) for uri in parsed_turn_uris}),
        "resolved_address_hashes": sorted(stable_hash(address) for address in resolved_addresses),
        "authority_host_hash": stable_hash(parsed_authority.hostname),
        "authority_resolved_address_hashes": sorted(stable_hash(address) for address in authority_addresses),
        "authority_source_id_hash": stable_hash(authority_source_id),
        "turn_realm_hash": stable_hash(turn_realm),
        "credential_ttl_seconds": config.get("credential_ttl_seconds"),
        "max_concurrent_sessions_per_device": config.get("max_concurrent_sessions_per_device"),
        "daily_bytes_per_device": config.get("daily_bytes_per_device"),
    }


def relay_turn_realm(path: Path) -> str:
    config = read_json(path, "relay production config")
    turn_realm = config.get("turn_realm")
    if not isinstance(turn_realm, str) or not turn_realm.strip():
        raise PreflightError("turn_realm must be configured before TLS validation")
    return turn_realm.strip().rstrip(".").lower()


def _positive_int(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PreflightError(f"relay {key} must be a positive integer")
    return value


def _validate_relay_quotas(config: dict[str, Any]) -> None:
    ttl = _positive_int(config, "credential_ttl_seconds")
    maximum_ttl = _positive_int(config, "max_credential_ttl_seconds")
    if ttl > maximum_ttl or maximum_ttl > MAXIMUM_TURN_TTL_SECONDS:
        raise PreflightError("relay credential TTL bounds are not production-safe")
    requests_per_minute = _positive_int(config, "credential_requests_per_minute")
    concurrent_sessions = _positive_int(config, "max_concurrent_sessions_per_device")
    daily_bytes = _positive_int(config, "daily_bytes_per_device")
    usage_event_bytes = _positive_int(config, "max_usage_event_bytes")
    if requests_per_minute < MINIMUM_CREDENTIAL_REQUESTS_PER_MINUTE:
        raise PreflightError("relay credential request quota is too low for production canaries")
    if concurrent_sessions < MINIMUM_CONCURRENT_SESSIONS_PER_DEVICE:
        raise PreflightError("relay concurrent-session quota is too low for direct/relay verification")
    if daily_bytes < MINIMUM_DAILY_BYTES_PER_DEVICE:
        raise PreflightError("relay daily byte quota is too low for production soak evidence")
    if usage_event_bytes < MINIMUM_USAGE_EVENT_BYTES:
        raise PreflightError("relay usage-event byte cap is too low for production accounting")


def validate_coturn_config(path: Path) -> dict[str, Any]:
    try:
        lines = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except (OSError, UnicodeDecodeError) as error:
        raise PreflightError("coturn production configuration is not readable") from error
    missing = sorted(REQUIRED_COTURN_LINES - lines)
    if missing:
        raise PreflightError("coturn production config is missing required TLS/auth lines")
    missing_denies = sorted(REQUIRED_COTURN_DENIES - lines)
    if missing_denies:
        raise PreflightError("coturn production config is missing private peer denies")
    if any(line.startswith("allowed-peer-ip=") for line in lines):
        raise PreflightError("coturn production config must not include allowed-peer-ip overrides")
    if "denied-peer-ip=::" in lines:
        raise PreflightError("coturn production config must not use ambiguous single-address IPv6 unspecified deny")
    if "no-auth" in lines:
        raise PreflightError("coturn production config must not disable authentication")
    quota = _line_int(lines, "user-quota")
    total_quota = _line_int(lines, "total-quota")
    max_bps = _line_int(lines, "max-bps")
    min_port = _line_int(lines, "min-port")
    max_port = _line_int(lines, "max-port")
    if min_port < 1024 or max_port > 65535 or min_port >= max_port:
        raise PreflightError("coturn relay port range is invalid")
    if quota < MINIMUM_COTURN_USER_QUOTA:
        raise PreflightError("coturn user-quota is too low for production ICE allocation checks")
    if total_quota < MINIMUM_COTURN_TOTAL_QUOTA:
        raise PreflightError("coturn total-quota is too low for production rollout checks")
    if max_bps < MINIMUM_COTURN_MAX_BPS:
        raise PreflightError("coturn max-bps is too low for production media verification")
    return {
        "tls_listening_port": 5349,
        "private_peer_deny_count": sum(1 for line in lines if line.startswith("denied-peer-ip=")),
        "allowed_peer_ip_count": 0,
        "user_quota": quota,
        "total_quota": total_quota,
        "max_bps": max_bps,
        "relay_port_min": min_port,
        "relay_port_max": max_port,
    }


def _line_int(lines: set[str], key: str) -> int:
    prefix = f"{key}="
    matches = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        raise PreflightError(f"coturn {key} must be set exactly once")
    try:
        value = int(matches[0])
    except ValueError as error:
        raise PreflightError(f"coturn {key} must be an integer") from error
    if value <= 0:
        raise PreflightError(f"coturn {key} must be positive")
    return value


def validate_secret_file(path: Path | None, label: str, *, require_private_mode: bool = True) -> str:
    if path is None:
        raise PreflightError(f"{label} must be provided")
    try:
        metadata = path.stat()
    except OSError as error:
        raise PreflightError(f"{label} is not readable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise PreflightError(f"{label} must be a regular file")
    if require_private_mode and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PreflightError(f"{label} must not grant group or world permissions")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise PreflightError(f"{label} cannot be read") from error
    if label == "turn secret file":
        text = data.decode("utf-8", errors="strict").strip()
        if len(text.encode("utf-8")) < MINIMUM_SECRET_BYTES or "\n" in text or "\r" in text:
            raise PreflightError(f"{label} must contain exactly one secret line of at least {MINIMUM_SECRET_BYTES} bytes")
    return hashlib.sha256(data).hexdigest()


def validate_pem_file(path: Path | None, label: str, marker: str, *, require_private_mode: bool) -> str:
    digest = validate_secret_file(path, label, require_private_mode=require_private_mode)
    assert path is not None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as error:
        raise PreflightError(f"{label} cannot be read") from error
    if marker not in text:
        raise PreflightError(f"{label} must contain PEM {marker.lower()} material")
    return digest


def _openssl(args: Sequence[str], *, input_text: str | None = None, timeout_seconds: float = 10.0) -> str:
    try:
        completed = _OPENSSL_RUN(
            ["openssl", *args],
            input=input_text,
            text=True,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError("openssl validation could not run") from error
    if completed.returncode != 0:
        raise PreflightError("openssl validation failed")
    return completed.stdout


def _certificate_names(certificate: Path) -> set[str]:
    text = _openssl(["x509", "-in", str(certificate), "-noout", "-subject", "-ext", "subjectAltName"])
    names: set[str] = set()
    for match in re.finditer(r"DNS:([^,\s]+)", text):
        names.add(match.group(1).strip().rstrip(".").lower())
    subject_match = re.search(r"(?:^|[,/=])\s*CN\s*=\s*([^,/]*)", text, flags=re.MULTILINE)
    if subject_match:
        names.add(subject_match.group(1).strip().rstrip(".").lower())
    return names


def _hostname_matches_certificate_name(hostname: str, candidate: str) -> bool:
    if not candidate:
        return False
    if candidate.startswith("*."):
        suffix = candidate[1:]
        return hostname.endswith(suffix) and hostname.count(".") == candidate.count(".")
    return hostname == candidate


def validate_tls_identity(certificate: Path | None, private_key: Path | None, turn_realm: str) -> dict[str, bool]:
    if certificate is None:
        raise PreflightError("TLS certificate must be provided")
    if private_key is None:
        raise PreflightError("TLS private key must be provided")
    assert certificate is not None
    assert private_key is not None

    names = _certificate_names(certificate)
    if not any(_hostname_matches_certificate_name(turn_realm, name) for name in names):
        raise PreflightError("TLS certificate SAN/CN does not match turn_realm")

    certificate_pubkey = _openssl(["x509", "-in", str(certificate), "-pubkey", "-noout"])
    private_key_pubkey = _openssl(["pkey", "-in", str(private_key), "-pubout"])
    if stable_hash(certificate_pubkey) != stable_hash(private_key_pubkey):
        raise PreflightError("TLS certificate and private key do not match")

    return {
        "tls_certificate_hostname_matched": True,
        "tls_key_pair_matched": True,
    }


def validate_external_ip(value: str | None) -> str:
    if value is None or not value.strip():
        raise PreflightError("COTURN_EXTERNAL_IP must be provided")
    parts = [part.strip() for part in value.split("/")]
    if len(parts) > 2 or any(not part for part in parts):
        raise PreflightError("COTURN_EXTERNAL_IP must be an IP or public/private IP mapping")
    for part in parts:
        _reject_non_dotted_ipv4_mapped(part)
        try:
            ipaddress.ip_address(part)
        except ValueError as error:
            raise PreflightError("COTURN_EXTERNAL_IP must be an IP or public/private IP mapping") from error
    public_part = parts[0]
    if not _is_global_address(public_part):
        raise PreflightError("COTURN_EXTERNAL_IP public side is not globally routable")
    return stable_hash(public_part)


def check_ready_url(url: str | None, label: str, *, resolve_dns: bool, timeout_seconds: float) -> bool:
    if url is None or not url.strip():
        raise PreflightError(f"{label} readiness URL must be provided")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PreflightError(f"{label} readiness URL must use HTTPS")
    if _placeholder_host(parsed.hostname):
        raise PreflightError(f"{label} readiness URL uses a placeholder host")
    require_public_host(parsed.hostname, resolve=resolve_dns)
    req = request.Request(url, headers={"User-Agent": "vibe-screen-phase3-public-nat-turn-preflight"})
    try:
        with request.urlopen(req, timeout=timeout_seconds, context=ssl.create_default_context()) as response:
            status = response.status
            body = response.read(64 * 1024)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise PreflightError(f"{label} readiness probe failed") from error
    if status < 200 or status >= 300:
        raise PreflightError(f"{label} readiness returned non-2xx")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"{label} readiness did not return JSON") from error
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise PreflightError(f"{label} readiness did not report status=ok")
    return True


def validate_connectivity_evidence(path: Path | None, *, resolve_dns: bool) -> dict[str, Any]:
    if path is None:
        raise PreflightError("public NAT/TURN connectivity evidence must be provided")
    evidence = read_json(path, "public NAT/TURN connectivity evidence")
    if evidence.get("schema") != CONNECTIVITY_SCHEMA:
        raise PreflightError("connectivity evidence has the wrong schema")
    required_booleans = {
        "public_internet_path": True,
        "remote_turn": True,
        "forced_local_coturn": False,
        "loopback": False,
        "synthetic_peer": False,
    }
    for key, expected in required_booleans.items():
        if evidence.get(key) is not expected:
            raise PreflightError(f"connectivity evidence {key} must be {expected}")
    if evidence.get("result") != PASS_RESULT:
        raise PreflightError("connectivity evidence result must be pass")
    pair = evidence.get("selected_candidate_pair")
    if not isinstance(pair, dict):
        raise PreflightError("selected_candidate_pair is required")
    if pair.get("selected_route") != "relay" or pair.get("local_candidate_type") != "relay":
        raise PreflightError("selected candidate pair must prove a relayed route")
    turn_host = str(pair.get("turn_host", ""))
    resolved = require_public_host(turn_host, resolve=resolve_dns)
    probe = evidence.get("connectivity")
    if not isinstance(probe, dict):
        raise PreflightError("connectivity probe result is required")
    if probe.get("result") != PASS_RESULT:
        raise PreflightError("connectivity probe must pass")
    sent = _positive_probe_int(probe, "packets_sent")
    received = _positive_probe_int(probe, "packets_received")
    privacy = evidence.get("privacy")
    if not isinstance(privacy, dict):
        raise PreflightError("connectivity privacy block is required")
    if privacy.get("raw_endpoints_recorded") is not False:
        raise PreflightError("connectivity evidence must not record raw endpoints")
    if privacy.get("sensitive_values_recorded") is not False:
        raise PreflightError("connectivity evidence must not record sensitive values")
    return {
        "turn_host_hash": stable_hash(turn_host),
        "resolved_address_hashes": sorted(stable_hash(address) for address in resolved),
        "packets_sent": sent,
        "packets_received": received,
        "candidate_pair": {
            "selected_route": pair.get("selected_route"),
            "local_candidate_type": pair.get("local_candidate_type"),
            "remote_candidate_type": pair.get("remote_candidate_type"),
            "protocol": pair.get("protocol"),
        },
    }


def validate_deployment_evidence(path: Path | None, *, resolve_dns: bool) -> dict[str, Any]:
    if path is None:
        raise PreflightError("public NAT/TURN deployment evidence must be provided")
    evidence = read_json(path, "public NAT/TURN deployment evidence")
    reject_sensitive_evidence(evidence, label="deployment evidence")
    if evidence.get("schema") != DEPLOYMENT_SCHEMA:
        raise PreflightError("deployment evidence has the wrong schema")
    if evidence.get("result") != PASS_RESULT:
        raise PreflightError("deployment evidence result must be pass")
    required_booleans = {
        "public_stun_endpoint_observed": True,
        "public_turn_udp_tcp_observed": True,
        "public_turn_tls_observed": True,
        "tls_certificate_hostname_valid": True,
        "tls_minimum_version_observed": True,
        "credential_rotation_observed": True,
        "old_credential_rejected_after_ttl": True,
        "quota_enforcement_observed": True,
        "monitoring_dashboards_observed": True,
        "alert_rules_observed": True,
        "remote_observer_outside_host_network": True,
        "real_remote_peer_path": True,
        "local_coturn_loopback": False,
        "synthetic_peer": False,
    }
    for key, expected in required_booleans.items():
        if evidence.get(key) is not expected:
            raise PreflightError(f"deployment evidence {key} must be {expected}")
    endpoints = evidence.get("public_endpoints")
    if not isinstance(endpoints, dict):
        raise PreflightError("deployment evidence public_endpoints is required")
    stun_host = _endpoint_host(endpoints, "stun")
    turn_host = _endpoint_host(endpoints, "turn")
    turns_host = _endpoint_host(endpoints, "turns")
    stun_addresses = require_public_host(stun_host, resolve=resolve_dns)
    turn_addresses = require_public_host(turn_host, resolve=resolve_dns)
    turns_addresses = require_public_host(turns_host, resolve=resolve_dns)
    tls = evidence.get("tls")
    if not isinstance(tls, dict):
        raise PreflightError("deployment evidence tls block is required")
    if tls.get("minimum_version") not in {"TLS1.2", "TLS1.3"}:
        raise PreflightError("deployment evidence TLS version must be TLS1.2 or TLS1.3")
    days = tls.get("certificate_expires_in_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 7:
        raise PreflightError("deployment evidence TLS certificate lifetime is too short")
    quotas = evidence.get("quotas")
    if not isinstance(quotas, dict):
        raise PreflightError("deployment evidence quotas block is required")
    if _positive_int(quotas, "credential_requests_per_minute") < MINIMUM_CREDENTIAL_REQUESTS_PER_MINUTE:
        raise PreflightError("deployment credential request quota is too low")
    if _positive_int(quotas, "max_concurrent_sessions_per_device") < MINIMUM_CONCURRENT_SESSIONS_PER_DEVICE:
        raise PreflightError("deployment concurrent-session quota is too low")
    if _positive_int(quotas, "daily_bytes_per_device") < MINIMUM_DAILY_BYTES_PER_DEVICE:
        raise PreflightError("deployment daily byte quota is too low")
    rotation = evidence.get("credential_rotation")
    if not isinstance(rotation, dict):
        raise PreflightError("deployment evidence credential_rotation block is required")
    if _positive_int(rotation, "new_credential_ttl_seconds") > MAXIMUM_TURN_TTL_SECONDS:
        raise PreflightError("deployment credential TTL is too high")
    monitoring = evidence.get("monitoring")
    if not isinstance(monitoring, dict):
        raise PreflightError("deployment evidence monitoring block is required")
    for key in ("allocation_metrics", "auth_failure_metrics", "relay_byte_metrics", "quota_decision_metrics"):
        if monitoring.get(key) is not True:
            raise PreflightError(f"deployment monitoring {key} must be true")
    if _positive_int(monitoring, "canary_history_count") < 1:
        raise PreflightError("deployment monitoring canary history is missing")
    observers = evidence.get("remote_observers")
    if not isinstance(observers, list) or len(observers) < MINIMUM_REMOTE_OBSERVER_COUNT:
        raise PreflightError("deployment evidence must include independent remote observers")
    for index, observer in enumerate(observers):
        if not isinstance(observer, dict):
            raise PreflightError("deployment remote observer entries must be objects")
        if observer.get("outside_host_network") is not True or observer.get("observed_relay_candidate") is not True:
            raise PreflightError(f"deployment remote observer {index} did not prove remote relay")
    privacy = evidence.get("privacy")
    if not isinstance(privacy, dict):
        raise PreflightError("deployment privacy block is required")
    for key in ("raw_endpoints_recorded", "sensitive_values_recorded", "raw_device_identifiers_recorded", "operator_paths_recorded"):
        if privacy.get(key) is not False:
            raise PreflightError(f"deployment privacy {key} must be false")
    return {
        "public_endpoint_hashes": {
            "stun": stable_hash(stun_host),
            "turn": stable_hash(turn_host),
            "turns": stable_hash(turns_host),
        },
        "resolved_address_hashes": sorted(stable_hash(address) for address in (*stun_addresses, *turn_addresses, *turns_addresses)),
        "tls": {
            "minimum_version": tls.get("minimum_version"),
            "certificate_expires_in_days": days,
        },
        "quotas": {
            "credential_requests_per_minute": quotas.get("credential_requests_per_minute"),
            "max_concurrent_sessions_per_device": quotas.get("max_concurrent_sessions_per_device"),
            "daily_bytes_per_device": quotas.get("daily_bytes_per_device"),
        },
        "credential_rotation": {
            "new_credential_ttl_seconds": rotation.get("new_credential_ttl_seconds"),
            "old_credential_rejected_after_ttl": True,
        },
        "monitoring": {
            "canary_history_count": monitoring.get("canary_history_count"),
            "alert_rules_observed": True,
        },
        "remote_observer_count": len(observers),
    }


def _endpoint_host(endpoints: dict[str, Any], key: str) -> str:
    value = endpoints.get(key)
    if not isinstance(value, dict):
        raise PreflightError(f"deployment endpoint {key} is required")
    host = value.get("host")
    if not isinstance(host, str) or not host.strip():
        raise PreflightError(f"deployment endpoint {key} host is required")
    return host


def run_connectivity_command(command: Sequence[str] | None, *, resolve_dns: bool, timeout_seconds: float) -> dict[str, Any]:
    if not command:
        raise PreflightError("external public NAT/TURN connectivity command must be provided")
    if any(not item for item in command):
        raise PreflightError("external connectivity command contains an empty argument")
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError("external public NAT/TURN connectivity command did not complete") from error
    if completed.returncode != 0:
        raise PreflightError("external public NAT/TURN connectivity command returned non-zero")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PreflightError("external connectivity command did not emit JSON on stdout") from error
    if not isinstance(value, dict):
        raise PreflightError("external connectivity command stdout must be a JSON object")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        json.dump(value, temporary)
    try:
        return validate_connectivity_evidence(temporary_path, resolve_dns=resolve_dns)
    finally:
        temporary_path.unlink(missing_ok=True)


def _positive_probe_int(probe: dict[str, Any], key: str) -> int:
    value = probe.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PreflightError(f"connectivity {key} must be a positive integer")
    return value


def _connectivity_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("turn_host_hash") == right.get("turn_host_hash")
        and left.get("candidate_pair") == right.get("candidate_pair")
        and left.get("packets_sent") == right.get("packets_sent")
        and left.get("packets_received") == right.get("packets_received")
    )


def build_report(
    *,
    relay_config: Path,
    coturn_config: Path,
    turn_secret_file: Path | None,
    tls_certificate: Path | None,
    tls_private_key: Path | None,
    coturn_external_ip: str | None,
    authority_ready_url: str | None,
    relay_ready_url: str | None,
    connectivity_evidence: Path | None,
    connectivity_command: Sequence[str] | None,
    deployment_evidence: Path | None = None,
    resolve_dns: bool = True,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    safe_relay: dict[str, Any] = {}
    safe_coturn: dict[str, Any] = {}
    safe_connectivity: dict[str, Any] = {}
    safe_deployment: dict[str, Any] = {}
    reviewed_connectivity: dict[str, Any] | None = None
    canary_connectivity: dict[str, Any] | None = None

    for name, operation in (
        ("relay_production_config", lambda: validate_relay_config(relay_config, resolve_dns=resolve_dns)),
        ("coturn_production_config", lambda: validate_coturn_config(coturn_config)),
        ("turn_secret_file", lambda: validate_secret_file(turn_secret_file, "turn secret file")),
        ("tls_certificate", lambda: validate_pem_file(tls_certificate, "TLS certificate", "CERTIFICATE", require_private_mode=False)),
        ("tls_private_key", lambda: validate_pem_file(tls_private_key, "TLS private key", "PRIVATE KEY", require_private_mode=True)),
        ("tls_certificate_identity", lambda: validate_tls_identity(tls_certificate, tls_private_key, relay_turn_realm(relay_config))),
        ("coturn_external_ip", lambda: validate_external_ip(coturn_external_ip)),
        ("authority_readiness", lambda: check_ready_url(authority_ready_url, "authority", resolve_dns=resolve_dns, timeout_seconds=timeout_seconds)),
        ("relay_readiness", lambda: check_ready_url(relay_ready_url, "relay", resolve_dns=resolve_dns, timeout_seconds=timeout_seconds)),
        ("dns_resolution", lambda: True if resolve_dns else (_raise("DNS resolution cannot be skipped for public NAT/TURN pass evidence"))),
        ("connectivity_evidence", lambda: validate_connectivity_evidence(connectivity_evidence, resolve_dns=resolve_dns)),
        ("external_connectivity_canary", lambda: run_connectivity_command(connectivity_command, resolve_dns=resolve_dns, timeout_seconds=timeout_seconds)),
        ("deployment_evidence", lambda: validate_deployment_evidence(deployment_evidence, resolve_dns=resolve_dns)),
    ):
        check, value = _check(name, operation)
        checks.append(check)
        if check["result"] == PASS_RESULT and isinstance(value, dict):
            if name == "relay_production_config":
                safe_relay = value
            elif name == "coturn_production_config":
                safe_coturn.update(value)
            elif name == "connectivity_evidence":
                reviewed_connectivity = value
                safe_connectivity.setdefault("reviewed_evidence", value)
            elif name == "external_connectivity_canary":
                canary_connectivity = value
                safe_connectivity.update(value)
                safe_connectivity["canary_evidence"] = value
            elif name == "deployment_evidence":
                safe_deployment = value
            elif name == "tls_certificate_identity":
                safe_coturn.update(value)
        elif check["result"] == PASS_RESULT and isinstance(value, str):
            if name == "turn_secret_file":
                safe_coturn["turn_secret_sha256"] = value
            elif name == "tls_certificate":
                safe_coturn["tls_certificate_sha256"] = value
            elif name == "tls_private_key":
                safe_coturn["tls_private_key_present"] = True
            elif name == "coturn_external_ip":
                safe_coturn["external_ip_hash"] = value

    if reviewed_connectivity is not None and canary_connectivity is not None:
        if _connectivity_matches(reviewed_connectivity, canary_connectivity):
            checks.append({"name": "connectivity_evidence_matches_canary", "result": PASS_RESULT, "detail": "ok"})
        else:
            checks.append({
                "name": "connectivity_evidence_matches_canary",
                "result": BLOCKED_RESULT,
                "detail": "reviewed connectivity evidence does not match the external canary output",
            })
    result = PASS_RESULT if all(check["result"] == PASS_RESULT for check in checks) else BLOCKED_RESULT
    return {
        "schema": SCHEMA,
        "kind": "phase3_public_nat_turn_preflight",
        "result": result,
        "checks": checks,
        "relay": safe_relay,
        "coturn": safe_coturn,
        "connectivity": safe_connectivity,
        "deployment": safe_deployment,
        "required_runtime_inputs": list(REQUIRED_RUNTIME_INPUTS),
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
        },
        "limitations": [] if result == PASS_RESULT else [BLOCKED_LIMITATION],
    }


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-config", type=Path, default=Path("deploy/phase3/config/relay.production.json"))
    parser.add_argument("--coturn-config", type=Path, default=Path("deploy/phase3/coturn/production.conf"))
    parser.add_argument("--turn-secret-file", type=Path)
    parser.add_argument("--tls-certificate", type=Path)
    parser.add_argument("--tls-private-key", type=Path)
    parser.add_argument("--coturn-external-ip")
    parser.add_argument("--authority-ready-url")
    parser.add_argument("--relay-ready-url")
    parser.add_argument("--connectivity-evidence", type=Path)
    parser.add_argument("--deployment-evidence", type=Path)
    parser.add_argument(
        "--connectivity-command",
        nargs=argparse.REMAINDER,
        help=(
            "external canary command that emits connectivity evidence JSON on stdout; "
            "required for pass. This option consumes all following arguments, so place "
            "--output and other preflight flags before --connectivity-command."
        ),
    )
    parser.add_argument("--skip-dns-resolution", action="store_true")
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
            relay_config=args.relay_config,
            coturn_config=args.coturn_config,
            turn_secret_file=args.turn_secret_file,
            tls_certificate=args.tls_certificate,
            tls_private_key=args.tls_private_key,
            coturn_external_ip=args.coturn_external_ip,
            authority_ready_url=args.authority_ready_url,
            relay_ready_url=args.relay_ready_url,
            connectivity_evidence=args.connectivity_evidence,
            connectivity_command=args.connectivity_command,
            deployment_evidence=args.deployment_evidence,
            resolve_dns=not args.skip_dns_resolution,
            timeout_seconds=args.timeout_seconds,
        )
        write_json(args.output, report)
    except (OSError, PreflightError) as error:
        print(f"Phase 3 public NAT/TURN preflight: FAIL ({error})", file=sys.stderr)
        return 1
    if report["result"] == BLOCKED_RESULT:
        print("Phase 3 public NAT/TURN preflight: BLOCKED", file=sys.stderr)
        return 0 if args.allow_blocked else 2
    print("Phase 3 public NAT/TURN preflight: PASS", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
