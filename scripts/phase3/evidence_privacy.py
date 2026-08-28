from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable


SCHEMA = "dev.vibescreen.evidence-privacy-scan/v1"
RULE_VERSION = "2026-08-23.1"
DERIVED_FILES = frozenset({"SHA256SUMS", "privacy-scan.json"})
CATEGORIES = (
    "network_endpoint",
    "hardware_identifier",
    "credential_material",
    "url",
    "user_absolute_path",
)

IPV4_CANDIDATE = re.compile(
    rb"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?![0-9.])"
)
URL_PATTERN = re.compile(rb"\b(?:https?|turns?|stuns?)://[^\s<>\"']+", re.IGNORECASE)
USER_PATH_PATTERN = re.compile(
    rb"(?:/Users/[^\s<>\"']+|/home/[^\s<>\"']+|/Volumes/[^\s<>\"']+|[A-Za-z]:\\\\Users\\\\[^\s<>\"']+)",
    re.IGNORECASE,
)
HARDWARE_IDENTIFIER_PATTERNS = (
    re.compile(rb'"adb_serial"\s*:\s*"(?!\[?redacted\]?\")[^\"]+"', re.IGNORECASE),
    re.compile(rb'"hardware_serial"\s*:\s*"(?!\[?redacted\]?\")[^\"]+"', re.IGNORECASE),
    re.compile(rb"\b(?:adb|hardware|device) serial\s*:\s*(?!\[?redacted\]?\b)[^\r\n]+", re.IGNORECASE),
)
DIRECT_CREDENTIAL_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE),
)
SENSITIVE_KEY = (
    rb"(?:credential|token|password|secret|shared_secret_base64|bootstrap_secret_base64|"
    rb"sharedSecretBase64|bootstrapSecretBase64|"
    rb"[A-Za-z][A-Za-z0-9_-]*[_-](?:shared_secret_base64|bootstrap_secret_base64)|"
    rb"[A-Za-z][A-Za-z0-9_-]*(?:SharedSecretBase64|BootstrapSecretBase64)|"
    rb"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)*[_-](?:credential|token|password|secret)|"
    rb"[A-Za-z][A-Za-z0-9]*(?:Credential|Token|Password|Secret))"
)
QUOTED_ASSIGNMENT_VALUE = rb'(?:"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\')'
JSON_ASSIGNMENT_VALUE = rb"(?:" + QUOTED_ASSIGNMENT_VALUE + rb"|[^\s,}\]\r\n]+)"
KEY_VALUE_ASSIGNMENT_VALUE = rb"(?:" + QUOTED_ASSIGNMENT_VALUE + rb"|[^\s,;\r\n]+)"
JSON_CREDENTIAL_ASSIGNMENT = re.compile(
    rb'["\'](?P<key>' + SENSITIVE_KEY + rb')["\']\s*:\s*(?P<value>' + JSON_ASSIGNMENT_VALUE + rb')',
    re.IGNORECASE,
)
KEY_VALUE_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?<![A-Za-z0-9_-])(?P<key>" + SENSITIVE_KEY + rb")\s*=\s*(?P<value>" + KEY_VALUE_ASSIGNMENT_VALUE + rb")",
    re.IGNORECASE,
)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def finding_id(content: bytes) -> str:
    return f"sha256:{sha256_bytes(content)[:16]}"


def _network_violations(content: bytes) -> list[str]:
    violations: list[str] = []
    for match in IPV4_CANDIDATE.finditer(content):
        candidate = match.group().decode("ascii")
        address_text = candidate.rsplit(":", 1)[0] if ":" in candidate else candidate
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified:
            continue
        violations.append(finding_id(match.group()))
    return violations


def _is_safe_credential_value(value: bytes) -> bool:
    stripped = value.strip()
    # JSON literals true/false/null are only safe when unquoted. A quoted
    # "false"/"true"/"null" is a string value that could be a credential.
    if stripped in (b"true", b"false", b"null"):
        return True
    if re.fullmatch(rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", stripped):
        return True
    normalized = stripped.strip(b"\"\'").strip().lower()
    if normalized in {
        b"",
        b"none",
        b"redacted",
        b"<redacted>",
        b"[redacted]",
        b"...",
    }:
        return True
    if re.fullmatch(rb"[<\[]redacted[-_a-z0-9]*[>\]]", normalized):
        return True
    return re.fullmatch(
        rb"\$(?:[a-z_][a-z0-9_]*|\{[a-z_][a-z0-9_]*\}|\([^)\r\n]*\))",
        normalized,
    ) is not None


def _is_safe_hardware_identifier_match(match: re.Match[bytes]) -> bool:
    value_match = re.search(rb":\s*(?P<value>\"(?:\\.|[^\"\\\r\n])*\")", match.group())
    if value_match is None:
        value_match = re.search(rb":\s*(?P<value>[^\r\n]+)$", match.group())
    return value_match is not None and _is_safe_credential_value(value_match.group("value"))


def _credential_violations(content: bytes) -> list[str]:
    violations = [
        finding_id(match.group())
        for pattern in DIRECT_CREDENTIAL_PATTERNS
        for match in pattern.finditer(content)
    ]
    for pattern in (JSON_CREDENTIAL_ASSIGNMENT, KEY_VALUE_CREDENTIAL_ASSIGNMENT):
        for match in pattern.finditer(content):
            if not _is_safe_credential_value(match.group("value")):
                violations.append(finding_id(match.group()))
    return violations


def scan_content(content: bytes) -> dict[str, list[str]]:
    findings = {
        "network_endpoint": _network_violations(content),
        "hardware_identifier": [
            finding_id(match.group())
            for pattern in HARDWARE_IDENTIFIER_PATTERNS
            for match in pattern.finditer(content)
            if not _is_safe_hardware_identifier_match(match)
        ],
        "credential_material": _credential_violations(content),
        "url": [
            finding_id(match.group())
            for match in URL_PATTERN.finditer(content)
        ],
        "user_absolute_path": [
            finding_id(match.group())
            for match in USER_PATH_PATTERN.finditer(content)
        ],
    }
    return {category: values for category, values in findings.items() if values}


def evidence_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in DERIVED_FILES:
            yield path


def build_manifest(root: Path) -> dict[str, object]:
    artifacts = []
    violations = []
    for path in evidence_files(root):
        content = path.read_bytes()
        findings = scan_content(content)
        relative_path = path.relative_to(root).as_posix()
        artifacts.append(
            {
                "path": relative_path,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
                "categories_checked": list(CATEGORIES),
                "result": "fail" if findings else "pass",
            }
        )
        if findings:
            violations.append({"path": relative_path, "findings": findings})

    return {
        "schema": SCHEMA,
        "rule_version": RULE_VERSION,
        "categories": list(CATEGORIES),
        "scope": {
            "root": ".",
            "excluded_derived_files": sorted(DERIVED_FILES),
        },
        "result": "fail" if violations else "pass",
        "artifacts": artifacts,
        "violations": violations,
    }


def serialized_manifest(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_manifest(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or verify a Phase 3 evidence privacy manifest")
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_dir = args.evidence_dir.resolve()
    output = (args.output or evidence_dir / "privacy-scan.json").resolve()
    manifest = build_manifest(evidence_dir)
    content = serialized_manifest(manifest)
    if args.check:
        if not output.is_file() or output.read_bytes() != content:
            print(f"privacy manifest is stale: {output}", file=sys.stderr)
            return 1
        if manifest["result"] != "pass":
            print(json.dumps(manifest["violations"], indent=2), file=sys.stderr)
            return 1
        return 0
    write_manifest(output, content)
    if manifest["result"] != "pass":
        print(json.dumps(manifest["violations"], indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
