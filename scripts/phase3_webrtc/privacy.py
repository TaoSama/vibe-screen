"""Private writes and public-safe diagnostic projection."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterable

from scripts.phase3_webrtc.model import (
    E2EFailure,
    PRODUCT_PLAINTEXT_SEEDS,
    PUBLIC_DIAGNOSTIC_SCHEMA,
)

TRACEBACK_MARKER = re.compile(r"traceback\s*\(most recent call last\)\s*:", re.IGNORECASE)
POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![:A-Za-z0-9._-])/(?:[^/\s\"'<>|,;)\]]+(?:/[^/\s\"'<>|,;)\]]+)*)"
)
WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:\\\\\?\\)?[A-Z]:[\\/]"
    r"(?:[^\\/\s\"'<>|,;)\]]+[\\/]?)*"
)
WINDOWS_UNC_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])\\\\(?:\?\\UNC\\)?"
    r"[^\\/\s\"'<>|]+[\\/][^\\/\s\"'<>|]+"
    r"(?:[\\/][^\\/\s\"'<>|]+)*"
)
IPV4_ADDRESS = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
IPV6_CANDIDATE = re.compile(
    r"(?<![0-9A-Fa-f:.])(?:[0-9A-Fa-f]{0,4}:){2,}"
    r"(?:[0-9A-Fa-f]{0,4}|(?:\d{1,3}\.){3}\d{1,3})"
    r"(?:%[A-Za-z0-9_.-]+)?(?![0-9A-Fa-f:.])"
)
BRACKETED_IPV6_ENDPOINT = re.compile(
    r"(?i)\[[0-9A-Fa-f:.]+(?:%[A-Za-z0-9_.-]+)?\]:\d{1,10}"
)
HOST_PORT_ENDPOINT = re.compile(
    r"(?i)(?<![A-Za-z0-9_.:-])"
    r"(?P<host>[A-Za-z0-9_](?:[A-Za-z0-9_.-]{0,251}[A-Za-z0-9_])?)"
    r":(?P<port>\d+)(?![\d:])"
)
BEARER_CREDENTIAL = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URI_USERINFO = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")
TURN_USERINFO = re.compile(
    r"(?i)\bturns?:[^\s/@:]+:[^\s/@]+@[^\s\"'<>]+"
)
ENDPOINT_URI = re.compile(
    r"(?i)\b(?:https?|wss?)://[^\s\"'<>]+|\b(?:turns?|stuns?):[^\s\"'<>]+"
)
BARE_FQDN = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}(?![A-Za-z0-9_.-])"
)
NAMED_CREDENTIAL = re.compile(
    r"(?i)([\"']?[A-Za-z0-9_-]*(?:authorization|api[-_]?key|cookie|credential|password|passwd|pwd|private[-_]?key|secret|seed|token|username)[A-Za-z0-9_-]*[\"']?)"
    r"(\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}]+)"
)
NAMED_PRIVATE_IDENTIFIER = re.compile(
    r"(?i)([\"']?[A-Za-z0-9_-]*(?:serial(?:[-_]?number)?|device[-_]?id|endpoint|hostname)[A-Za-z0-9_-]*[\"']?)"
    r"(\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}]+)"
)


def redact_text(text: str, redact_values: Iterable[str]) -> str:
    rendered = text
    for value in (item for item in redact_values if item):
        rendered = rendered.replace(value, "<redacted>")
    return rendered


def _redact_ip_addresses(text: str) -> str:
    def redact(candidate: re.Match[str]) -> str:
        value = candidate.group(0)
        address_value = value.split("%", 1)[0]
        try:
            address = ipaddress.ip_address(address_value)
        except ValueError:
            return value
        return "<redacted-address>"

    rendered = IPV6_CANDIDATE.sub(redact, text)
    return IPV4_ADDRESS.sub(redact, rendered)


def _redact_host_port_endpoints(text: str) -> str:
    def redact_bracketed_ipv6(candidate: re.Match[str]) -> str:
        endpoint = candidate.group(0)
        host, port_text = endpoint[1:].rsplit("]:", 1)
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            return endpoint
        return "<redacted-endpoint>"

    def redact_host_port(candidate: re.Match[str]) -> str:
        return "<redacted-endpoint>"

    rendered = BRACKETED_IPV6_ENDPOINT.sub(redact_bracketed_ipv6, text)
    return HOST_PORT_ENDPOINT.sub(redact_host_port, rendered)


def project_public_diagnostic(
    text: str,
    *,
    secret_values: Iterable[str] = (),
    private_paths: Iterable[Path | str] = (),
) -> str:
    """Return diagnostics safe for unconditional CI artifact retention."""
    traceback = TRACEBACK_MARKER.search(text)
    if traceback is not None:
        text = text[:traceback.start()] + "<redacted-traceback>\n"
    path_values = tuple(str(path) for path in private_paths if str(path))
    rendered = redact_text(text, (*secret_values, *PRODUCT_PLAINTEXT_SEEDS, *path_values))
    rendered = BEARER_CREDENTIAL.sub("Bearer <redacted>", rendered)
    rendered = ENDPOINT_URI.sub("<redacted-endpoint>", rendered)
    rendered = URI_USERINFO.sub("<redacted-credential>@", rendered)
    rendered = TURN_USERINFO.sub("<redacted-endpoint>", rendered)
    rendered = NAMED_CREDENTIAL.sub("<redacted-credential>", rendered)
    rendered = NAMED_PRIVATE_IDENTIFIER.sub("<redacted-private-identifier>", rendered)
    rendered = WINDOWS_UNC_PATH.sub("<redacted-path>", rendered)
    rendered = WINDOWS_ABSOLUTE_PATH.sub("<redacted-path>", rendered)
    rendered = POSIX_ABSOLUTE_PATH.sub("<redacted-path>", rendered)
    rendered = _redact_host_port_endpoints(rendered)
    rendered = _redact_ip_addresses(rendered)
    rendered = BARE_FQDN.sub("<redacted-hostname>", rendered)
    return POSIX_ABSOLUTE_PATH.sub("<redacted-path>", rendered)


def project_and_validate_public_diagnostic(
    text: str,
    *,
    secret_values: Iterable[str] = (),
    private_paths: Iterable[Path | str] = (),
) -> str:
    projected = project_public_diagnostic(
        text,
        secret_values=secret_values,
        private_paths=private_paths,
    )
    findings = public_diagnostic_findings(projected)
    if findings:
        categories = ",".join(sorted(set(findings)))
        raise E2EFailure(
            f"diagnostic projection failed the public privacy scan: {categories}"
        )
    return projected


def write_private_text(path: Path, rendered: str) -> None:
    parent_fd, leaf = _open_secure_parent(path, create=True)
    temporary_leaf = f".{leaf}.{secrets.token_hex(12)}.tmp"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary_leaf,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            destination.write(rendered)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(
            temporary_leaf,
            leaf,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        written = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(written.st_mode):
            raise E2EFailure("private output replacement did not create a regular file")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_leaf, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _open_secure_parent(path: Path, *, create: bool) -> tuple[int, str]:
    configured = Path(os.path.abspath(path))
    absolute = configured.parent.resolve(strict=False) / configured.name
    components = absolute.parts
    if len(components) < 2 or absolute.name in ("", ".", ".."):
        raise E2EFailure("private output must name a file")
    descriptor = os.open(
        components[0], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        for component in components[1:-1]:
            if component in ("", ".", ".."):
                raise E2EFailure("private output contains an invalid path component")
            try:
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except OSError:
                raise E2EFailure(
                    "private output path contains a symlink or non-directory"
                ) from None
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, absolute.name
    except Exception:
        os.close(descriptor)
        raise


def remove_private_file(path: Path) -> None:
    """Unlink one owned file from a directory bound by file descriptor."""
    try:
        parent_fd, leaf = _open_secure_parent(path, create=False)
    except FileNotFoundError:
        return
    try:
        try:
            current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISDIR(current.st_mode):
            raise E2EFailure("private output must be a file, not a directory")
        os.unlink(leaf, dir_fd=parent_fd)
    except OSError:
        raise E2EFailure("private output could not be removed safely") from None
    finally:
        os.close(parent_fd)


def remove_private_diagnostics(directory: Path) -> None:
    for leaf in ("peer.json", "signaling.json", "turnserver.json"):
        remove_private_file(directory / leaf)


def write_public_diagnostic(
    path: Path,
    text: str,
    *,
    secret_values: Iterable[str] = (),
    private_paths: Iterable[Path | str] = (),
    status: str = "captured",
    metadata: dict[str, Any] | None = None,
) -> None:
    projected = project_and_validate_public_diagnostic(
        text, secret_values=secret_values, private_paths=private_paths
    )
    record = {
        "schema": PUBLIC_DIAGNOSTIC_SCHEMA,
        "component": path.stem,
        "status": status,
        "raw_bytes": len(text.encode("utf-8", errors="replace")),
        "raw_lines": len(text.splitlines()),
        "raw_sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "raw_uploaded": False,
        "privacy_projection": "allowlist-summary-only",
        "markers": {
            "pass": "PASS" in text,
            "fail": "FAIL" in text,
            "timeout": "timed out" in text.lower(),
        },
    }
    if metadata:
        record["metadata"] = metadata
    write_private_text(path.with_suffix(".json"), json.dumps(record, indent=2, sort_keys=True) + "\n")


def write_evidence(path: Path | None, evidence: dict[str, Any]) -> None:
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered, end="")
        return
    write_private_text(path, rendered)
    print("Evidence record written.")


def assert_secret_free(text: str, secret_values: Iterable[str], label: str) -> None:
    leaked = [secret for secret in secret_values if secret and secret in text]
    if leaked:
        raise E2EFailure(f"{label} leaked {len(leaked)} generated secret value(s)")


def public_diagnostic_findings(text: str) -> list[str]:
    findings: list[str] = []
    if TRACEBACK_MARKER.search(text):
        findings.append("traceback")
    if any(seed in text for seed in PRODUCT_PLAINTEXT_SEEDS):
        findings.append("plaintext_seed")
    if (
        POSIX_ABSOLUTE_PATH.search(text)
        or WINDOWS_ABSOLUTE_PATH.search(text)
        or WINDOWS_UNC_PATH.search(text)
    ):
        findings.append("absolute_path")
    if (
        BEARER_CREDENTIAL.search(text)
        or NAMED_CREDENTIAL.search(text)
        or URI_USERINFO.search(text)
        or TURN_USERINFO.search(text)
    ):
        findings.append("credential")
    if NAMED_PRIVATE_IDENTIFIER.search(text):
        findings.append("private_identifier")
    if ENDPOINT_URI.search(text):
        findings.append("endpoint")
    if BARE_FQDN.search(text):
        findings.append("hostname")
    if _redact_host_port_endpoints(text) != text:
        findings.append("endpoint")
    if _redact_ip_addresses(text) != text:
        findings.append("ip_address")
    return findings
