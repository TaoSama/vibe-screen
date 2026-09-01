"""Fail-closed Phase 3 public Internet soak manifest and gate.

This module is intentionally a composition layer. It does not replace the
single-purpose public TURN, media-continuity, handoff, or revocation verifiers;
instead it consumes their privacy-reviewed summaries and refuses to produce a
release pass when any required observation is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state
from .soak_public_report import EvidenceInputError, read_json as _read_json

MANIFEST_KIND = "phase3_internet_soak_manifest"
GATE_KIND = "phase3_internet_soak_gate"
MINIMUM_DURATION_SECONDS = int(2 * 60 * 60 * 0.98)
MINIMUM_SAMPLE_COUNT = int(2 * 60 * 2 * 0.98)
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_MEDIA_GAP_SECONDS = 5.0
MAXIMUM_DROPPED_FRAMES = 0.0
REQUIRED_ROUTES = ("direct", "relay")
REQUIRED_METRIC_FAMILIES = (
    "host_rss",
    "client_memory",
    "queue",
    "loss",
    "rtt",
    "fps",
    "bitrate",
    "relay_bytes",
    "ice_restart",
    "drops",
    "thermal",
    "battery",
)
REQUIRED_ARTIFACTS = (
    "README.md",
    "phase3-internet-soak-manifest.json",
    "phase3-internet-soak-gate.json",
    "remote-turn-verifier.json",
    "media-continuity.json",
    "network-handoff.json",
    "revocation-propagation.json",
    "soak-exact-window-report.json",
    "privacy-scan.json",
    "SHA256SUMS",
)
INTERPRETATION = (
    "A pass means the supplied privacy-reviewed reports jointly satisfy the "
    "Phase 3 public Internet soak evidence contract. Missing production, TLS, "
    "secret, remote-peer, media, handoff, revocation, duration, or sampling "
    "evidence is blocked rather than inferred from local synthetic runs."
)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PLACEHOLDER_SUFFIXES = (
    ".local",
    ".localhost",
    ".example",
    ".example.com",
    ".example.net",
    ".example.org",
    ".invalid",
)
SENSITIVE_KEY_PARTS = ("secret", "token", "password", "credential", "private_key")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class Phase3InternetSoakError(RuntimeError):
    """Raised when a manifest cannot be built safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_hex(value: str | None, option: str) -> str:
    normalized = _non_empty(value, option).lower()
    if SHA256_HEX_PATTERN.fullmatch(normalized) is None:
        raise Phase3InternetSoakError(f"{option} must be a 64-character hex SHA-256 digest")
    return normalized


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _non_empty(value: str | None, option: str) -> str:
    if value is None or not value.strip():
        raise Phase3InternetSoakError(f"{option} is required")
    return value.strip()


def _parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = float(value)
        except (OverflowError, ValueError):
            return None
        if math.isfinite(converted):
            return converted
    return None


def _get(document: dict[str, Any], *path: str) -> Any:
    value: Any = document
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


def _is_public_host(host: str) -> bool:
    normalized = host.strip(".").lower()
    if (
        normalized in LOCAL_HOSTS
        or normalized in {"example.com", "example.net", "example.org"}
        or normalized.endswith(PLACEHOLDER_SUFFIXES)
    ):
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return "." in normalized and not normalized.endswith(".test")
    return address.is_global


def _turn_uri_summary(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme not in {"turn", "turns"}:
        raise Phase3InternetSoakError("--turn-uri must use turn: or turns: with a host")
    host = parsed.hostname
    port = parsed.port
    query = parsed.query
    if host is None:
        authority = parsed.path
        if authority.startswith("["):
            close = authority.find("]")
            if close == -1:
                raise Phase3InternetSoakError("--turn-uri has malformed IPv6 host")
            host = authority[1:close]
            remainder = authority[close + 1 :]
            if remainder.startswith(":"):
                port = int(remainder[1:])
        else:
            host_part, separator, port_part = authority.rpartition(":")
            if separator and port_part.isdigit():
                host = host_part
                port = int(port_part)
            else:
                host = authority
    if not host:
        raise Phase3InternetSoakError("--turn-uri must use turn: or turns: with a host")
    transport = "udp"
    if query:
        for part in query.split("&"):
            key, separator, value = part.partition("=")
            if separator and key.lower() == "transport":
                transport = value.lower()
    if parsed.scheme == "turns" and transport != "tcp":
        raise Phase3InternetSoakError("turns: URIs must use transport=tcp")
    if transport not in {"udp", "tcp"}:
        raise Phase3InternetSoakError("TURN transport must be udp or tcp")
    return {
        "uri_sha256": _stable_hash(uri),
        "scheme": parsed.scheme,
        "host_sha256": _stable_hash(host.lower()),
        "port": port or (5349 if parsed.scheme == "turns" else 3478),
        "transport": transport,
        "public_host_declared": _is_public_host(host),
    }


def _origin_summary(origin: str, option: str) -> dict[str, Any]:
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise Phase3InternetSoakError(f"{option} must be an https origin without path/query")
    if not _is_public_host(parsed.hostname):
        raise Phase3InternetSoakError(f"{option} must name a public host")
    return {
        "origin_sha256": _stable_hash(origin.rstrip("/")),
        "scheme": parsed.scheme,
        "host_sha256": _stable_hash(parsed.hostname.lower()),
    }


def _safe_path_label(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.name


def _read_optional(path: Path | None, label: str, *, root: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, f"missing {label}"
    display_path = _safe_path_label(root, path) if root is not None else path.as_posix()
    try:
        return _read_json(path, label), None
    except EvidenceInputError as error:
        cause = error.__cause__
        if isinstance(cause, FileNotFoundError):
            return None, f"{label}: missing {display_path}"
        if isinstance(cause, PermissionError):
            return None, f"{label}: could not read {display_path}: permission denied"
        if isinstance(cause, OSError):
            return None, f"{label}: could not read {display_path}: {cause.strerror or cause.__class__.__name__}"
        return None, str(error).replace(str(path), display_path)


def _reject_secret_material(document: Any, context: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                if normalized.endswith("_source") or normalized.endswith("_sha256"):
                    findings.extend(_reject_secret_material(value, f"{context}.{key}"))
                    continue
                raw = value if isinstance(value, str) else ""
                if raw not in {"", "<redacted>", "[redacted]", "redacted", None}:
                    findings.append(f"{context}.{key} must not contain raw secret material")
            findings.extend(_reject_secret_material(value, f"{context}.{key}"))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            findings.extend(_reject_secret_material(value, f"{context}[{index}]"))
    return findings


def build_manifest(
    *,
    repo: Path,
    command: Sequence[str],
    turn_uris: Sequence[str],
    signaling_origin: str,
    relay_origin: str,
    authority_source_id: str,
    remote_peer: str,
    tls_certificate_sha256: str,
    turn_secret_source: str,
    deployment_readiness: Sequence[str],
    planned_handoffs: Sequence[str],
    host_build: str,
    android_artifact_sha256: str,
    duration_seconds: int,
    sample_interval_seconds: int,
    notes: str | None = None,
) -> dict[str, Any]:
    if duration_seconds < MINIMUM_DURATION_SECONDS:
        raise Phase3InternetSoakError("--duration-seconds must cover at least a two-hour soak window")
    if sample_interval_seconds <= 0 or sample_interval_seconds > 30:
        raise Phase3InternetSoakError("--sample-interval-seconds must be in the range 1..30")
    if not turn_uris:
        raise Phase3InternetSoakError("at least one --turn-uri is required")
    if turn_secret_source not in {"file", "secret_manager"}:
        raise Phase3InternetSoakError("--turn-secret-source must be file or secret_manager")
    if not deployment_readiness:
        raise Phase3InternetSoakError("--deployment-readiness must name checked production readiness probes")
    if not planned_handoffs:
        raise Phase3InternetSoakError("--planned-handoffs must name at least one network handoff")
    if not _is_public_host(remote_peer):
        raise Phase3InternetSoakError("--remote-peer must identify an independently reachable public peer")

    turn_summaries = [_turn_uri_summary(uri) for uri in turn_uris]
    if not any(item["scheme"] == "turns" and item["transport"] == "tcp" for item in turn_summaries):
        raise Phase3InternetSoakError("at least one turns:?transport=tcp URI is required")
    if not all(item["public_host_declared"] for item in turn_summaries):
        raise Phase3InternetSoakError("every TURN URI must name a public host")
    tls_digest = _sha256_hex(tls_certificate_sha256, "--tls-certificate-sha256")
    android_artifact_digest = _sha256_hex(android_artifact_sha256, "--android-artifact-sha256")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_now(),
        "command": list(command),
        "repository": repository_state(repo.resolve()),
        "deployment": {
            "turn_uris": turn_summaries,
            "signaling_origin": _origin_summary(signaling_origin, "--signaling-origin"),
            "relay_origin": _origin_summary(relay_origin, "--relay-origin"),
            "authority_source_id": _non_empty(authority_source_id, "--authority-source-id"),
            "remote_peer_sha256": _stable_hash(remote_peer.lower()),
            "remote_peer_kind": "public_independent_peer",
            "tls_certificate_sha256": tls_digest,
            "turn_secret_source": turn_secret_source,
            "readiness_probes": list(deployment_readiness),
        },
        "build": {
            "host_build": _non_empty(host_build, "--host-build"),
            "android_artifact_sha256": android_artifact_digest,
        },
        "session": {
            "duration_seconds": duration_seconds,
            "sample_interval_seconds": sample_interval_seconds,
            "required_routes": list(REQUIRED_ROUTES),
            "planned_handoffs": list(planned_handoffs),
        },
        "required_metric_families": list(REQUIRED_METRIC_FAMILIES),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "limitations": [
            "This manifest predeclares the public Internet soak boundary; it does not close the gate without the verifier output and raw evidence bundle.",
            "Raw endpoints, device identifiers, tokens, TURN passwords, and private logs must stay out of tracked evidence.",
        ],
        "notes": notes,
    }


def _criteria_record(measured: Any, expected: Any, passed: bool) -> dict[str, Any]:
    return {"measured": measured, "expected": expected, "passed": passed}


def _status_pass(report: dict[str, Any]) -> bool:
    return report.get("result") == "pass" or report.get("status") == "pass" or report.get("verdict") == "pass"


def _availability(label: str, report: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    return {"provided": report is not None, "error": error}


def _soak_value(report: dict[str, Any], *paths: Sequence[str]) -> Any:
    for path in paths:
        value = _get(report, *path)
        if value is not None:
            return value
    return None


def _route_samples(report: dict[str, Any], route: str) -> float | None:
    value = _soak_value(
        report,
        ("routes", route, "sample_count"),
        ("route_samples", route),
        ("metrics", "routes", route, "sample_count"),
    )
    return _finite_number(value)


def _metric_families(report: dict[str, Any]) -> set[str]:
    value = report.get("metric_families")
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    metrics = report.get("metrics")
    if isinstance(metrics, dict):
        found = set(metrics)
        aliases = {
            "memory_kib": "host_rss",
            "stream": "fps",
            "telemetry": "queue",
            "network": "rtt",
        }
        found.update(alias for key, alias in aliases.items() if key in metrics)
        return found
    return set()


def _evaluate_manifest(manifest: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if manifest is None:
        reasons.append("phase3 Internet soak manifest is missing")
        return _criteria_record(None, MANIFEST_KIND, False)
    passed = manifest.get("schema_version") == SCHEMA_VERSION and manifest.get("kind") == MANIFEST_KIND
    deployment = manifest.get("deployment") if isinstance(manifest.get("deployment"), dict) else {}
    build = manifest.get("build") if isinstance(manifest.get("build"), dict) else {}
    session = manifest.get("session") if isinstance(manifest.get("session"), dict) else {}
    turn_uris = deployment.get("turn_uris") if isinstance(deployment.get("turn_uris"), list) else []
    has_public_tls_turn = any(
        isinstance(item, dict)
        and item.get("scheme") == "turns"
        and item.get("transport") == "tcp"
        and item.get("public_host_declared") is True
        for item in turn_uris
    )
    readiness = deployment.get("readiness_probes") if isinstance(deployment.get("readiness_probes"), list) else []
    manifest_checks = {
        "shape": passed,
        "public_tls_turn": has_public_tls_turn,
        "remote_peer": deployment.get("remote_peer_kind") == "public_independent_peer",
        "secret_source": deployment.get("turn_secret_source") in {"file", "secret_manager"},
        "tls_fingerprint": isinstance(deployment.get("tls_certificate_sha256"), str)
        and SHA256_HEX_PATTERN.fullmatch(deployment["tls_certificate_sha256"]) is not None,
        "android_artifact_sha256": isinstance(build.get("android_artifact_sha256"), str)
        and SHA256_HEX_PATTERN.fullmatch(build["android_artifact_sha256"]) is not None,
        "readiness": len(readiness) >= 3,
        "duration": _finite_number(session.get("duration_seconds")) is not None and float(session["duration_seconds"]) >= MINIMUM_DURATION_SECONDS,
        "handoff_plan": bool(session.get("planned_handoffs")),
    }
    failed = [name for name, value in manifest_checks.items() if not value]
    for name in failed:
        reasons.append(f"manifest missing {name}")
    return {"checks": manifest_checks, "passed": not failed}


def _evaluate_remote_turn(report: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if report is None:
        reasons.append("public remote TURN verifier report is missing")
        return _criteria_record(None, "pass with remote relay packet exchange", False)
    relay_packets = _finite_number(
        _soak_value(report, ("relay_packets", "received"), ("packets", "received"), ("turn", "received_packets"))
    )
    sent_packets = _finite_number(
        _soak_value(report, ("relay_packets", "sent"), ("packets", "sent"), ("turn", "sent_packets"))
    )
    remote_peer = report.get("remote_peer") == "public" or report.get("real_remote_peer") is True
    public_route = report.get("public_internet") is True or report.get("route_scope") == "public_internet"
    passed = _status_pass(report) and remote_peer and public_route and (sent_packets or 0) > 0 and (relay_packets or 0) > 0
    if not passed:
        reasons.append("public remote TURN report does not prove public relay packet exchange")
    return {
        "status_pass": _status_pass(report),
        "remote_peer": remote_peer,
        "public_route": public_route,
        "sent_packets": sent_packets,
        "received_packets": relay_packets,
        "passed": passed,
    }


def _evaluate_media(report: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if report is None:
        reasons.append("real media continuity report is missing")
        return _criteria_record(None, "pass with real capture and Android decode", False)
    decoded = _finite_number(_soak_value(report, ("decoded_frames",), ("media", "decoded_frames")))
    dropped = _finite_number(_soak_value(report, ("dropped_frames",), ("media", "dropped_frames")))
    max_gap = _finite_number(_soak_value(report, ("maximum_frame_gap_seconds",), ("media", "maximum_frame_gap_seconds")))
    real_capture = report.get("real_screencapturekit") is True or _get(report, "media", "real_screencapturekit") is True
    android_decoder = report.get("real_android_decoder") is True or _get(report, "media", "real_android_decoder") is True
    passed = (
        _status_pass(report)
        and real_capture
        and android_decoder
        and (decoded or 0) > 0
        and (dropped is not None and dropped <= MAXIMUM_DROPPED_FRAMES)
        and (max_gap is not None and max_gap <= MAXIMUM_MEDIA_GAP_SECONDS)
    )
    if not passed:
        reasons.append("media continuity report does not prove continuous real ScreenCaptureKit-to-Android decode")
    return {
        "status_pass": _status_pass(report),
        "real_screencapturekit": real_capture,
        "real_android_decoder": android_decoder,
        "decoded_frames": decoded,
        "dropped_frames": dropped,
        "maximum_frame_gap_seconds": max_gap,
        "passed": passed,
    }


def _evaluate_handoff(report: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if report is None:
        reasons.append("network handoff report is missing")
        return _criteria_record(None, "pass with at least one handoff", False)
    count = _finite_number(_soak_value(report, ("network_handoff_count",), ("handoffs", "count")))
    stale_rejected = report.get("stale_media_rejected") is True or _get(report, "handoffs", "stale_media_rejected") is True
    plaintext = report.get("plaintext_fallback_observed") is True or _get(report, "handoffs", "plaintext_fallback_observed") is True
    recovered = report.get("fresh_session_recovered") is True or report.get("ice_restart_completed") is True or _get(report, "handoffs", "fresh_session_recovered") is True
    passed = _status_pass(report) and (count or 0) >= 1 and stale_rejected and recovered and not plaintext
    if not passed:
        reasons.append("network handoff report does not prove fresh-session recovery without plaintext fallback")
    return {
        "status_pass": _status_pass(report),
        "network_handoff_count": count,
        "stale_media_rejected": stale_rejected,
        "fresh_session_recovered": recovered,
        "plaintext_fallback_observed": plaintext,
        "passed": passed,
    }


def _evaluate_revocation(report: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if report is None:
        reasons.append("revocation propagation report is missing")
        return _criteria_record(None, "pass with allocation disconnect and packet denial", False)
    missing = report.get("missing")
    failures = report.get("failures")
    post_packets = _finite_number(_soak_value(report, ("relayed_packets_after_revocation",), ("data_plane", "relayed_packets_after_revocation")))
    live_production = report.get("evidence_kind") == "live_production"
    public_internet = report.get("public_internet_path") is True
    remote_turn = report.get("remote_turn_deployment") is True
    non_synthetic = report.get("synthetic_fixture") is False
    chain_consistent = report.get("revocation_chain_consistent") is True
    disconnect = report.get("active_allocation_disconnected") is True or _get(report, "coturn_allocation", "disconnect_observed") is True
    stale = report.get("stale_credential_reuse_rejected") is True or _get(report, "relay_credential", "stale_credential_reuse_rejected") is True
    packet_denial = report.get("post_revocation_traffic_denied") is True or _get(report, "data_plane", "post_revocation_traffic_denied") is True
    summary_clean = missing in (None, []) and failures in (None, [])
    passed = (
        _status_pass(report)
        and summary_clean
        and live_production
        and public_internet
        and remote_turn
        and non_synthetic
        and chain_consistent
        and disconnect
        and stale
        and packet_denial
        and (post_packets == 0)
    )
    if not passed:
        reasons.append("revocation report does not prove live production chain binding, active allocation disconnect, stale credential rejection, and zero post-revocation relay packets")
    return {
        "status_pass": _status_pass(report),
        "summary_clean": summary_clean,
        "live_production": live_production,
        "public_internet_path": public_internet,
        "remote_turn_deployment": remote_turn,
        "synthetic_fixture": report.get("synthetic_fixture"),
        "revocation_chain_consistent": chain_consistent,
        "active_allocation_disconnected": disconnect,
        "stale_credential_reuse_rejected": stale,
        "post_revocation_traffic_denied": packet_denial,
        "relayed_packets_after_revocation": post_packets,
        "passed": passed,
    }


def _evaluate_soak(report: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    if report is None:
        reasons.append("two-hour soak exact-window report is missing")
        return _criteria_record(None, "complete two-hour mixed-route soak", False)
    duration = _finite_number(
        _soak_value(report, ("duration_seconds",), ("window", "duration_seconds"), ("session", "duration_seconds"))
    )
    sample_count = _finite_number(
        _soak_value(report, ("sample_count",), ("window", "sample_records_in_window"), ("metrics", "samples", "count"))
    )
    max_gap = _finite_number(
        _soak_value(report, ("maximum_sample_gap_seconds",), ("metrics", "samples", "gaps", "maximum_window_gap_seconds"))
    )
    errors = report.get("errors")
    source_errors = _get(report, "source_summary", "errors")
    status_ok = _status_pass(report) or report.get("derivation_status") == "complete" or report.get("status") == "complete"
    route_criteria = {route: _route_samples(report, route) for route in REQUIRED_ROUTES}
    families = _metric_families(report)
    missing_families = [family for family in REQUIRED_METRIC_FAMILIES if family not in families]
    nonce_reuse = report.get("nonce_reuse_detected") is True or _get(report, "security", "nonce_reuse_detected") is True
    plaintext = report.get("plaintext_fallback_observed") is True or _get(report, "security", "plaintext_fallback_observed") is True
    passed = (
        status_ok
        and (duration or 0) >= MINIMUM_DURATION_SECONDS
        and (sample_count or 0) >= MINIMUM_SAMPLE_COUNT
        and (max_gap is not None and max_gap <= MAXIMUM_SAMPLE_GAP_SECONDS)
        and errors in (None, [])
        and source_errors in (None, [])
        and all((route_criteria[route] or 0) > 0 for route in REQUIRED_ROUTES)
        and not missing_families
        and not nonce_reuse
        and not plaintext
    )
    if not passed:
        reasons.append("soak report does not prove a clean two-hour mixed-route public Internet window")
    return {
        "status_ok": status_ok,
        "duration_seconds": duration,
        "sample_count": sample_count,
        "maximum_sample_gap_seconds": max_gap,
        "route_samples": route_criteria,
        "missing_metric_families": missing_families,
        "nonce_reuse_detected": nonce_reuse,
        "plaintext_fallback_observed": plaintext,
        "passed": passed,
    }


def derive_gate(
    *,
    manifest_path: Path | None,
    remote_turn_path: Path | None,
    media_continuity_path: Path | None,
    network_handoff_path: Path | None,
    revocation_path: Path | None,
    soak_report_path: Path | None,
    blocked_reason: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    manifest, manifest_error = _read_optional(manifest_path, "manifest", root=root)
    remote_turn, remote_turn_error = _read_optional(remote_turn_path, "remote TURN report", root=root)
    media, media_error = _read_optional(media_continuity_path, "media continuity report", root=root)
    handoff, handoff_error = _read_optional(network_handoff_path, "network handoff report", root=root)
    revocation, revocation_error = _read_optional(revocation_path, "revocation report", root=root)
    soak, soak_error = _read_optional(soak_report_path, "soak report", root=root)

    input_errors = [
        error
        for error in (manifest_error, remote_turn_error, media_error, handoff_error, revocation_error, soak_error)
        if error is not None
    ]
    reasons.extend(input_errors)

    secret_findings: list[str] = []
    for label, report in (
        ("manifest", manifest),
        ("remote_turn", remote_turn),
        ("media", media),
        ("handoff", handoff),
        ("revocation", revocation),
        ("soak", soak),
    ):
        if report is not None:
            secret_findings.extend(f"{label}:{finding}" for finding in _reject_secret_material(report))
    reasons.extend(secret_findings)

    criteria = {
        "manifest": _evaluate_manifest(manifest, reasons),
        "remote_turn": _evaluate_remote_turn(remote_turn, reasons),
        "media_continuity": _evaluate_media(media, reasons),
        "network_handoff": _evaluate_handoff(handoff, reasons),
        "revocation": _evaluate_revocation(revocation, reasons),
        "soak": _evaluate_soak(soak, reasons),
    }
    failed = [name for name, criterion in criteria.items() if not criterion.get("passed")]
    unsafe = bool(secret_findings) or any(
        bool(criterion.get("plaintext_fallback_observed")) or bool(criterion.get("nonce_reuse_detected"))
        for criterion in criteria.values()
    )
    if unsafe:
        verdict = "fail"
    elif failed or input_errors:
        verdict = "blocked"
    else:
        verdict = "pass"
    if blocked_reason and verdict == "blocked":
        reasons.insert(0, blocked_reason)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "created_at": _utc_now(),
        "derivation_status": "complete",
        "verdict": verdict,
        "thresholds": {
            "minimum_duration_seconds": MINIMUM_DURATION_SECONDS,
            "minimum_sample_count": MINIMUM_SAMPLE_COUNT,
            "maximum_sample_gap_seconds": MAXIMUM_SAMPLE_GAP_SECONDS,
            "maximum_media_gap_seconds": MAXIMUM_MEDIA_GAP_SECONDS,
            "maximum_dropped_frames": MAXIMUM_DROPPED_FRAMES,
            "required_routes": list(REQUIRED_ROUTES),
            "required_metric_families": list(REQUIRED_METRIC_FAMILIES),
        },
        "inputs": {
            "manifest": _availability("manifest", manifest, manifest_error),
            "remote_turn": _availability("remote TURN report", remote_turn, remote_turn_error),
            "media_continuity": _availability("media continuity report", media, media_error),
            "network_handoff": _availability("network handoff report", handoff, handoff_error),
            "revocation": _availability("revocation report", revocation, revocation_error),
            "soak": _availability("soak report", soak, soak_error),
        },
        "criteria": criteria,
        "reasons": reasons,
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "interpretation": INTERPRETATION,
    }


def _manifest_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("manifest", help="write a Phase 3 Internet soak manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--turn-uri", action="append", default=[])
    parser.add_argument("--signaling-origin", required=True)
    parser.add_argument("--relay-origin", required=True)
    parser.add_argument("--authority-source-id", required=True)
    parser.add_argument("--remote-peer", required=True)
    parser.add_argument("--tls-certificate-sha256", required=True)
    parser.add_argument("--turn-secret-source", required=True, choices=["file", "secret_manager"])
    parser.add_argument("--deployment-readiness", required=True, help="comma-separated readiness probes checked before the run")
    parser.add_argument("--planned-handoffs", required=True, help="comma-separated network handoffs planned for the run")
    parser.add_argument("--host-build", required=True)
    parser.add_argument("--android-artifact-sha256", required=True)
    parser.add_argument("--duration-seconds", type=int, default=2 * 60 * 60)
    parser.add_argument("--sample-interval-seconds", type=int, default=30)
    parser.add_argument("--notes")
    parser.add_argument("command", nargs=argparse.REMAINDER)


def _gate_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("gate", help="evaluate the Phase 3 Internet soak gate")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--remote-turn", type=Path)
    parser.add_argument("--media-continuity", type=Path)
    parser.add_argument("--network-handoff", type=Path)
    parser.add_argument("--revocation", type=Path)
    parser.add_argument("--soak-report", type=Path)
    parser.add_argument("--blocked-reason")
    parser.add_argument("--allow-blocked", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    _manifest_parser(subparsers)
    _gate_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command_name == "manifest":
            command = args.command
            if command[:1] == ["--"]:
                command = command[1:]
            document = build_manifest(
                repo=args.repo,
                command=command,
                turn_uris=args.turn_uri,
                signaling_origin=args.signaling_origin,
                relay_origin=args.relay_origin,
                authority_source_id=args.authority_source_id,
                remote_peer=args.remote_peer,
                tls_certificate_sha256=args.tls_certificate_sha256,
                turn_secret_source=args.turn_secret_source,
                deployment_readiness=_parse_csv(args.deployment_readiness),
                planned_handoffs=_parse_csv(args.planned_handoffs),
                host_build=args.host_build,
                android_artifact_sha256=args.android_artifact_sha256,
                duration_seconds=args.duration_seconds,
                sample_interval_seconds=args.sample_interval_seconds,
                notes=args.notes,
            )
            _write_json(args.output, document)
            return 0

        document = derive_gate(
            manifest_path=args.manifest,
            remote_turn_path=args.remote_turn,
            media_continuity_path=args.media_continuity,
            network_handoff_path=args.network_handoff,
            revocation_path=args.revocation,
            soak_report_path=args.soak_report,
            blocked_reason=args.blocked_reason,
            root=args.output.parent,
        )
        _write_json(args.output, document)
    except (OSError, ManifestError, Phase3InternetSoakError, EvidenceInputError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    verdict = document["verdict"]
    if verdict == "pass":
        print(f"PASS: Phase 3 Internet soak gate written to {args.output}")
        return 0
    if verdict == "fail":
        print(f"FAIL: Phase 3 Internet soak gate written to {args.output}", file=sys.stderr)
        return 2
    print(f"BLOCKED: Phase 3 Internet soak gate written to {args.output}", file=sys.stderr)
    return 0 if args.allow_blocked else 3


if __name__ == "__main__":
    raise SystemExit(main())
