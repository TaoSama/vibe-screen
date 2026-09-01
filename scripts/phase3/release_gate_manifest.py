#!/usr/bin/env python3
"""Validate a Phase 3 Secure Internet release-gate evidence manifest.

This checker is intentionally a necessary-condition gate. It verifies that a
future curated evidence package explicitly claims the release-blocking real-world
observations before documentation may describe Phase 3 as released. It does not
make local, synthetic, or blocked evidence into a pass.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "dev.vibescreen.phase3-release-gate-manifest/v1"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
PUBLIC_ASN = re.compile(r"^AS[1-9][0-9]*$")
CANDIDATE_PAIR_PATTERN = re.compile(
    r"^(direct|relay)\(local=([a-z0-9_-]+),remote=([a-z0-9_-]+),"
    r"protocol=([a-z0-9_-]+)\)$"
)
SUPPORTED_CANDIDATE_TYPES = {"host", "srflx", "prflx", "relay"}
SUPPORTED_CANDIDATE_PROTOCOLS = {"udp", "tcp", "tls"}
LIVE_PRODUCTION_EVIDENCE_KIND = "live_production"
DETERMINISTIC_IMPAIRMENT_TOOL_MARKERS = (
    "network_profile",
    "deterministic",
    "simulation",
    "ns_3",
    "ns3",
    "mininet",
    "gns3",
)


class ManifestError(ValueError):
    """Raised when a release-gate manifest cannot be read."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


@dataclass(frozen=True)
class GateRule:
    name: str
    description: str
    required_fields: tuple[str, ...]
    validate: Callable[[Mapping[str, Any], str], list[str]]


@dataclass(frozen=True)
class EvidenceChecksumIndex:
    root: Path
    checksums: Mapping[str, str]


COMMON_GATE_REQUIRED_FIELDS = (
    "synthetic_media",
    "local_loopback_only",
    "usb_transport",
    "trusted_lan_only",
    "private_network_only",
    "same_private_network",
    "loopback",
    "synthetic_loopback",
    "synthetic_peer",
)
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
PRIVATE_DNS_SUFFIXES = (
    ".corp",
    ".home",
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".private",
)
REQUIRED_NETWORK_CONDITION_FIELDS = (
    "controlled_impairment",
    "impairment_tool",
    "impairment_profile",
    "route_before",
    "route_after",
)
REQUIRED_FRESH_SESSION_FIELDS = (
    "fresh_session_requested",
    "ice_restart_attempted",
    "old_session_closed",
    "initial_session_epoch",
    "recovered_session_epoch",
    "stream_pause_detected",
    "stream_resume_detected",
    "recovery_started_at_monotonic_ms",
    "recovery_completed_at_monotonic_ms",
)
REVOCATION_SUMMARY_GATE_FIELDS = (
    "status",
    "evidence_kind",
    "chain_id",
    "tombstone_id",
    "allocation_id",
    "device_revoked",
    "session_revoked",
    "authority_tombstone_observed",
    "signaling_rejection_observed",
    "future_turn_credential_rejected",
    "same_allocation_turn_credential_rejected",
    "stale_credential_reuse_rejected",
    "post_revocation_packet_count_zero",
    "revocation_chain_consistent",
)
REVOCATION_SUMMARY_GATE_ALIASES = {
    "active_session_disconnected": "signaling_rejection_observed",
    "direct_reconnect_rejected": "future_turn_credential_rejected",
    "relay_reconnect_rejected": "future_turn_credential_rejected",
    "turn_allocation_disconnected": "active_allocation_disconnected",
    "post_revocation_traffic_rejected": "post_revocation_traffic_denied",
}


def _as_mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(f"{path}: expected object")
    return {}


def _as_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    errors.append(f"{path}: expected list")
    return []


def _require_nonempty_string(value: Any, path: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: expected non-empty string")
        return ""
    return value.strip()


def _require_bool(value: Any, path: str, expected: bool, errors: list[str]) -> None:
    if value is not expected:
        errors.append(f"{path}: expected {str(expected).lower()}")


def _require_positive_number(value: Any, path: str, errors: list[str]) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        errors.append(f"{path}: expected positive number")
        return 0.0
    return float(value)


def _require_minimum_number(value: Any, path: str, minimum: float, errors: list[str]) -> float:
    observed = _require_positive_number(value, path, errors)
    if observed and observed < minimum:
        errors.append(f"{path}: expected >= {minimum:g}")
    return observed


def _require_nonnegative_number(value: Any, path: str, errors: list[str]) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        errors.append(f"{path}: expected non-negative number")
        return None
    return float(value)


def _require_percentage(value: Any, path: str, errors: list[str]) -> float | None:
    observed = _require_nonnegative_number(value, path, errors)
    if observed is not None and observed > 100:
        errors.append(f"{path}: expected <= 100")
    return observed


def _require_integer_at_least(value: Any, path: str, minimum: int, errors: list[str]) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{path}: expected integer >= {minimum}")
        return 0
    if value < minimum:
        errors.append(f"{path}: expected integer >= {minimum}")
    return value


def _require_not_local_only(gate: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for field in COMMON_GATE_REQUIRED_FIELDS:
        _require_bool(gate.get(field, False), f"{path}.{field}", False, errors)


def revocation_summary_to_manifest_gate(summary: Mapping[str, Any]) -> dict[str, Any]:
    gate = {field: summary.get(field) for field in REVOCATION_SUMMARY_GATE_FIELDS}
    gate.update(
        {
            gate_field: summary.get(summary_field)
            for gate_field, summary_field in REVOCATION_SUMMARY_GATE_ALIASES.items()
        }
    )
    return gate


def _is_public_hostname_or_ip(value: str) -> bool:
    normalized = value.strip().lower().rstrip(".")
    if not normalized:
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return (
            normalized not in LOCAL_HOSTNAMES
            and "." in normalized
            and not normalized.endswith(PRIVATE_DNS_SUFFIXES)
        )
    return bool(address.is_global)


def _validate_network_conditions(gate: Mapping[str, Any], path: str, errors: list[str]) -> None:
    _require_bool(gate.get("controlled_impairment"), f"{path}.controlled_impairment", True, errors)
    tool = _require_nonempty_string(gate.get("impairment_tool"), f"{path}.impairment_tool", errors)
    tool_normalized = tool.lower().replace("-", "_")
    if tool and any(marker in tool_normalized for marker in DETERMINISTIC_IMPAIRMENT_TOOL_MARKERS):
        errors.append(f"{path}.impairment_tool: deterministic simulator cannot close a release gate")
    profile = _as_mapping(gate.get("impairment_profile"), f"{path}.impairment_profile", errors)
    if profile:
        for field in ("latency_ms", "jitter_ms"):
            _require_nonnegative_number(profile.get(field), f"{path}.impairment_profile.{field}", errors)
        _require_percentage(profile.get("loss_percent"), f"{path}.impairment_profile.loss_percent", errors)
        _require_positive_number(profile.get("bandwidth_kbps"), f"{path}.impairment_profile.bandwidth_kbps", errors)
    route_before = _require_nonempty_string(gate.get("route_before"), f"{path}.route_before", errors)
    route_after = _require_nonempty_string(gate.get("route_after"), f"{path}.route_after", errors)
    if route_before and route_before not in {"direct", "relay"}:
        errors.append(f"{path}.route_before: expected direct or relay")
    if route_after and route_after not in {"direct", "relay"}:
        errors.append(f"{path}.route_after: expected direct or relay")


def _validate_candidate_pair(
    value: str,
    path: str,
    expected_route: str,
    errors: list[str],
) -> None:
    match = CANDIDATE_PAIR_PATTERN.fullmatch(value)
    if match is None:
        errors.append(f"{path}: expected route(local=type,remote=type,protocol=transport)")
        return
    route, local_candidate, remote_candidate, protocol = match.groups()
    if route != expected_route:
        errors.append(f"{path}: expected {expected_route} candidate pair")
    for label, candidate in (("local", local_candidate), ("remote", remote_candidate)):
        if candidate not in SUPPORTED_CANDIDATE_TYPES:
            errors.append(f"{path}.{label}: unsupported candidate type {candidate}")
    if protocol not in SUPPORTED_CANDIDATE_PROTOCOLS:
        errors.append(f"{path}.protocol: unsupported candidate transport {protocol}")
    if expected_route == "direct" and "relay" in {local_candidate, remote_candidate}:
        errors.append(f"{path}: direct gate cannot include relay candidates")
    if expected_route == "relay" and (local_candidate, remote_candidate) != ("relay", "relay"):
        errors.append(f"{path}: relay gate requires relay local and remote candidates")


def _validate_fresh_session_recovery(gate: Mapping[str, Any], path: str, errors: list[str]) -> None:
    for field in (
        "fresh_session_requested",
        "ice_restart_attempted",
        "old_session_closed",
        "stream_pause_detected",
        "stream_resume_detected",
    ):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
    initial_epoch = _require_integer_at_least(gate.get("initial_session_epoch"), f"{path}.initial_session_epoch", 0, errors)
    recovered_epoch = _require_integer_at_least(gate.get("recovered_session_epoch"), f"{path}.recovered_session_epoch", 1, errors)
    if recovered_epoch <= initial_epoch:
        errors.append(f"{path}.recovered_session_epoch: expected > initial_session_epoch")
    started = _require_nonnegative_number(
        gate.get("recovery_started_at_monotonic_ms"),
        f"{path}.recovery_started_at_monotonic_ms",
        errors,
    )
    completed = _require_nonnegative_number(
        gate.get("recovery_completed_at_monotonic_ms"),
        f"{path}.recovery_completed_at_monotonic_ms",
        errors,
    )
    if started is not None and completed is not None and completed <= started:
        errors.append(f"{path}.recovery_completed_at_monotonic_ms: expected > recovery_started_at_monotonic_ms")


def _validate_direct_path(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _require_bool(gate.get("public_internet_path"), f"{path}.public_internet_path", True, errors)
    _require_bool(gate.get("remote_public_route_observed"), f"{path}.remote_public_route_observed", True, errors)
    _require_bool(gate.get("local_loopback_address", False), f"{path}.local_loopback_address", False, errors)
    _require_bool(gate.get("usb_adb_reverse", False), f"{path}.usb_adb_reverse", False, errors)
    host_network = _require_nonempty_string(gate.get("host_network"), f"{path}.host_network", errors)
    device_network = _require_nonempty_string(gate.get("device_network"), f"{path}.device_network", errors)
    remote_public_asn = _require_nonempty_string(
        gate.get("remote_public_asn"),
        f"{path}.remote_public_asn",
        errors,
    )
    if remote_public_asn and not PUBLIC_ASN.fullmatch(remote_public_asn):
        errors.append(f"{path}.remote_public_asn: expected ASN in AS<number> format")
    if host_network and device_network and host_network == device_network:
        errors.append(f"{path}.device_network: expected a different public network than host_network")
    if gate.get("route") != "direct":
        errors.append(f"{path}.route: expected direct")
    selected_pair = _require_nonempty_string(gate.get("selected_candidate_pair"), f"{path}.selected_candidate_pair", errors)
    if selected_pair:
        _validate_candidate_pair(selected_pair, f"{path}.selected_candidate_pair", "direct", errors)
    return errors


def _validate_turn_path(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _require_bool(gate.get("public_internet_path"), f"{path}.public_internet_path", True, errors)
    _require_bool(gate.get("remote_turn_deployment"), f"{path}.remote_turn_deployment", True, errors)
    _require_bool(gate.get("local_coturn_only", False), f"{path}.local_coturn_only", False, errors)
    _require_bool(gate.get("forced_local_coturn", False), f"{path}.forced_local_coturn", False, errors)
    for field in ("turn_provider", "turn_region"):
        _require_nonempty_string(gate.get(field), f"{path}.{field}", errors)
    for field in ("turn_public_hostname", "turn_resolved_public_ip"):
        value = _require_nonempty_string(gate.get(field), f"{path}.{field}", errors)
        if value and not _is_public_hostname_or_ip(value):
            errors.append(f"{path}.{field}: expected public hostname or IP")
    if gate.get("route") != "relay":
        errors.append(f"{path}.route: expected relay")
    selected_pair = _require_nonempty_string(gate.get("selected_candidate_pair"), f"{path}.selected_candidate_pair", errors)
    if selected_pair:
        _validate_candidate_pair(selected_pair, f"{path}.selected_candidate_pair", "relay", errors)
    return errors


def _validate_real_media(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    if gate.get("capture_source") not in {"ScreenCaptureKit", "CGDisplayStream"}:
        errors.append(f"{path}.capture_source: expected ScreenCaptureKit or CGDisplayStream")
    if gate.get("android_decoder") != "MediaCodec":
        errors.append(f"{path}.android_decoder: expected MediaCodec")
    for field in ("screen_capture_frames", "encoded_frames", "android_decoded_frames"):
        _require_minimum_number(gate.get(field), f"{path}.{field}", 1, errors)
    _require_bool(gate.get("first_android_output_observed"), f"{path}.first_android_output_observed", True, errors)
    return errors


def _validate_handoff(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _validate_network_conditions(gate, path, errors)
    _validate_fresh_session_recovery(gate, path, errors)
    _require_minimum_number(gate.get("handoff_count"), f"{path}.handoff_count", 1, errors)
    _require_bool(gate.get("session_epoch_advanced"), f"{path}.session_epoch_advanced", True, errors)
    _require_bool(gate.get("stale_epoch_rejected"), f"{path}.stale_epoch_rejected", True, errors)
    _require_bool(gate.get("recovered_streaming"), f"{path}.recovered_streaming", True, errors)
    recovery = _require_positive_number(gate.get("recovery_seconds"), f"{path}.recovery_seconds", errors)
    started = gate.get("recovery_started_at_monotonic_ms")
    completed = gate.get("recovery_completed_at_monotonic_ms")
    if (
        recovery
        and isinstance(started, (int, float))
        and not isinstance(started, bool)
        and isinstance(completed, (int, float))
        and not isinstance(completed, bool)
        and completed > started
    ):
        observed_recovery = (float(completed) - float(started)) / 1000
        if abs(observed_recovery - recovery) > 0.001:
            errors.append(f"{path}.recovery_seconds: expected to match monotonic recovery interval")
    limit = gate.get("approved_limit_seconds", 5)
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
        errors.append(f"{path}.approved_limit_seconds: expected positive number")
    elif recovery and recovery > float(limit):
        errors.append(f"{path}.recovery_seconds: exceeded approved limit {float(limit):g}")
    return errors


def _validate_soak(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _validate_network_conditions(gate, path, errors)
    _require_minimum_number(gate.get("duration_seconds"), f"{path}.duration_seconds", 7200, errors)
    routes = {item for item in _as_list(gate.get("routes"), f"{path}.routes", errors) if isinstance(item, str)}
    if not {"direct", "relay"}.issubset(routes):
        errors.append(f"{path}.routes: expected both direct and relay")
    _require_minimum_number(gate.get("network_change_count"), f"{path}.network_change_count", 1, errors)
    for field in ("bounded_queues", "bounded_memory", "no_nonce_reuse", "no_steady_latency_growth"):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
    return errors


def _validate_revocation(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    for field in (
        "device_revoked",
        "session_revoked",
        "authority_tombstone_observed",
        "signaling_rejection_observed",
        "future_turn_credential_rejected",
        "same_allocation_turn_credential_rejected",
        "stale_credential_reuse_rejected",
        "active_session_disconnected",
        "direct_reconnect_rejected",
        "relay_reconnect_rejected",
        "turn_allocation_disconnected",
        "post_revocation_traffic_rejected",
        "post_revocation_packet_count_zero",
    ):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
    if gate.get("evidence_kind") != LIVE_PRODUCTION_EVIDENCE_KIND:
        errors.append(f"{path}.evidence_kind: expected {LIVE_PRODUCTION_EVIDENCE_KIND}")
    _require_bool(gate.get("revocation_chain_consistent"), f"{path}.revocation_chain_consistent", True, errors)
    for field in ("chain_id", "tombstone_id", "allocation_id"):
        _require_nonempty_string(gate.get(field), f"{path}.{field}", errors)
    return errors


def _validate_packet_capture(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    for field in ("capture_reviewed", "no_plaintext_media", "no_plaintext_input", "no_credentials"):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
    return errors


def _validate_latency(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    if gate.get("method") != "external_camera":
        errors.append(f"{path}.method: expected external_camera")
    _require_minimum_number(gate.get("sample_count"), f"{path}.sample_count", 5, errors)
    for field in ("direct_p95_ms", "relay_p95_ms"):
        _require_positive_number(gate.get(field), f"{path}.{field}", errors)
    return errors


def _validate_record_layer(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _require_bool(gate.get("public_internet_path"), f"{path}.public_internet_path", True, errors)
    _require_bool(gate.get("remote_turn_deployment"), f"{path}.remote_turn_deployment", True, errors)
    _require_bool(gate.get("fake_webrtc_engine", False), f"{path}.fake_webrtc_engine", False, errors)
    _require_bool(gate.get("forced_local_coturn", False), f"{path}.forced_local_coturn", False, errors)
    if gate.get("aead") != "AES-256-GCM":
        errors.append(f"{path}.aead: expected AES-256-GCM")
    for field in (
        "aad_binds_session_epoch",
        "key_epoch_bound",
        "directional_key_separation",
        "channel_binding_enforced",
        "replay_rejected",
        "wrong_channel_rejected",
        "packet_capture_no_plaintext",
    ):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
    for field in ("nonce_reuse_detected", "plaintext_fallback"):
        _require_bool(gate.get(field), f"{path}.{field}", False, errors)
    channels = _as_list(gate.get("channels"), f"{path}.channels", errors)
    channel_set = {channel for channel in channels if isinstance(channel, str)}
    expected_channels = {"control", "media", "audio", "bulk"}
    if channel_set != expected_channels:
        errors.append(f"{path}.channels: expected control, media, audio, and bulk")
    product_flows = _as_mapping(gate.get("product_flows"), f"{path}.product_flows", errors)
    for flow in ("audio_capture_playback", "clipboard_sync", "file_transfer"):
        if product_flows.get(flow) != "not_claimed":
            errors.append(f"{path}.product_flows.{flow}: expected not_claimed for transport-boundary evidence")
    return errors


GATE_RULES: tuple[GateRule, ...] = (
    GateRule(
        "public_internet_direct_path",
        "Direct WebRTC selected across a genuine public Internet path.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "route",
            "public_internet_path",
            "selected_candidate_pair",
            "remote_public_route_observed",
            "local_loopback_address",
            "usb_adb_reverse",
            "host_network",
            "device_network",
            "remote_public_asn",
        ),
        _validate_direct_path,
    ),
    GateRule(
        "remote_turn_relay_path",
        "Forced relay selected through a real remote TURN deployment.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "route",
            "public_internet_path",
            "remote_turn_deployment",
            "local_coturn_only",
            "forced_local_coturn",
            "turn_public_hostname",
            "turn_resolved_public_ip",
            "turn_provider",
            "turn_region",
            "selected_candidate_pair",
        ),
        _validate_turn_path,
    ),
    GateRule(
        "real_screencapturekit_to_android_media",
        "Real macOS capture/encoder output reaches Android MediaCodec.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "capture_source",
            "android_decoder",
            "screen_capture_frames",
            "encoded_frames",
            "android_decoded_frames",
            "first_android_output_observed",
        ),
        _validate_real_media,
    ),
    GateRule(
        "network_handoff_recovery",
        "A real Wi-Fi/cellular/VPN handoff recovers with a fresh epoch.",
        COMMON_GATE_REQUIRED_FIELDS
        + REQUIRED_NETWORK_CONDITION_FIELDS
        + REQUIRED_FRESH_SESSION_FIELDS
        + (
            "handoff_count",
            "session_epoch_advanced",
            "stale_epoch_rejected",
            "recovered_streaming",
            "recovery_seconds",
        ),
        _validate_handoff,
    ),
    GateRule(
        "cross_service_revocation",
        "Revocation propagates through signaling and TURN and terminates active use.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "evidence_kind",
            "chain_id",
            "tombstone_id",
            "allocation_id",
            "device_revoked",
            "session_revoked",
            "authority_tombstone_observed",
            "signaling_rejection_observed",
            "future_turn_credential_rejected",
            "same_allocation_turn_credential_rejected",
            "stale_credential_reuse_rejected",
            "active_session_disconnected",
            "direct_reconnect_rejected",
            "relay_reconnect_rejected",
            "turn_allocation_disconnected",
            "post_revocation_traffic_rejected",
            "post_revocation_packet_count_zero",
            "revocation_chain_consistent",
        ),
        _validate_revocation,
    ),
    GateRule(
        "packet_capture_confidentiality",
        "Packet captures show no media, input, or credential plaintext.",
        COMMON_GATE_REQUIRED_FIELDS + ("capture_reviewed", "no_plaintext_media", "no_plaintext_input", "no_credentials"),
        _validate_packet_capture,
    ),
    GateRule(
        "external_camera_latency",
        "Direct and relay latency claims use external-camera measurements.",
        COMMON_GATE_REQUIRED_FIELDS + ("method", "sample_count", "direct_p95_ms", "relay_p95_ms"),
        _validate_latency,
    ),
    GateRule(
        "webrtc_datachannel_record_layer",
        "WebRTC DataChannels carry AES-256-GCM application records for control, media, audio, and bulk without closing product-flow gates.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "public_internet_path",
            "remote_turn_deployment",
            "fake_webrtc_engine",
            "forced_local_coturn",
            "aead",
            "aad_binds_session_epoch",
            "key_epoch_bound",
            "directional_key_separation",
            "channel_binding_enforced",
            "replay_rejected",
            "wrong_channel_rejected",
            "packet_capture_no_plaintext",
            "nonce_reuse_detected",
            "plaintext_fallback",
            "channels",
            "product_flows",
        ),
        _validate_record_layer,
    ),
    GateRule(
        "two_hour_mixed_route_soak",
        "Two-hour mixed direct/relay/network-change soak remains bounded.",
        COMMON_GATE_REQUIRED_FIELDS
        + REQUIRED_NETWORK_CONDITION_FIELDS
        + (
            "duration_seconds",
            "routes",
            "network_change_count",
            "bounded_queues",
            "bounded_memory",
            "no_nonce_reuse",
            "no_steady_latency_growth",
        ),
        _validate_soak,
    ),
)


def gate_matrix() -> list[dict[str, object]]:
    return [
        {
            "gate": rule.name,
            "description": rule.description,
            "required_fields": list(rule.required_fields),
            "current_status": "open",
        }
        for rule in GATE_RULES
    ]


def _normalize_relative_evidence_path(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or candidate == Path(""):
        return None
    return candidate.as_posix()


def _load_evidence_checksum_index(
    evidence_root: Path | None, errors: list[str]
) -> EvidenceChecksumIndex | None:
    if evidence_root is None:
        return None
    try:
        root = evidence_root.resolve()
    except (OSError, RuntimeError):
        errors.append("evidence_root: evidence root could not be resolved")
        return None

    checksum_path = root / "SHA256SUMS"
    checksums: dict[str, str] = {}
    if not checksum_path.is_file():
        errors.append("SHA256SUMS: missing under evidence root")
        return EvidenceChecksumIndex(root=root, checksums=checksums)
    try:
        checksum_path.resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError):
        errors.append("SHA256SUMS: expected file under evidence root")
        return EvidenceChecksumIndex(root=root, checksums=checksums)

    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        errors.append(f"SHA256SUMS: cannot read checksum manifest: {error}")
        return EvidenceChecksumIndex(root=root, checksums=checksums)

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if "  " not in line:
            errors.append(f"SHA256SUMS line {line_number}: malformed checksum line")
            continue
        digest, relative_path = line.split("  ", maxsplit=1)
        if (
            not digest
            or not relative_path
            or "  " in relative_path
            or digest.strip() != digest
            or relative_path.strip() != relative_path
            or any(character.isspace() for character in relative_path)
        ):
            errors.append(f"SHA256SUMS line {line_number}: malformed checksum line")
            continue
        if not HEX_SHA256.fullmatch(digest):
            errors.append(f"SHA256SUMS line {line_number}: expected lowercase SHA-256")
            continue
        normalized = _normalize_relative_evidence_path(relative_path)
        if normalized is None:
            errors.append(f"SHA256SUMS line {line_number}: expected relative path under evidence root")
            continue
        try:
            (root / normalized).resolve().relative_to(root)
        except (OSError, RuntimeError, ValueError):
            errors.append(f"SHA256SUMS line {line_number}: expected relative path under evidence root")
            continue
        if normalized in checksums:
            errors.append(f"SHA256SUMS line {line_number}: duplicate checksum entry for {normalized}")
            continue
        checksums[normalized] = digest
    return EvidenceChecksumIndex(root=root, checksums=checksums)


def _validate_evidence_files(
    gate: Mapping[str, Any],
    path: str,
    errors: list[str],
    checksum_index: EvidenceChecksumIndex | None,
) -> None:
    files = _as_list(gate.get("evidence_files"), f"{path}.evidence_files", errors)
    if not files:
        errors.append(f"{path}.evidence_files: expected at least one evidence file")
        return
    for index, item in enumerate(files):
        file_path = _require_nonempty_string(item, f"{path}.evidence_files[{index}]", errors)
        if not file_path:
            continue
        normalized = _normalize_relative_evidence_path(file_path)
        if normalized is None:
            errors.append(f"{path}.evidence_files[{index}]: expected relative file path under evidence root")
            continue
        if checksum_index is not None:
            try:
                resolved_candidate = (checksum_index.root / normalized).resolve()
            except (OSError, RuntimeError):
                errors.append(f"{path}.evidence_files[{index}]: expected file under evidence root")
                continue
            try:
                resolved_candidate.relative_to(checksum_index.root)
            except ValueError:
                errors.append(f"{path}.evidence_files[{index}]: expected file under evidence root")
                continue
            if not resolved_candidate.is_file():
                errors.append(f"{path}.evidence_files[{index}]: file does not exist under evidence root")
                continue
            expected_digest = checksum_index.checksums.get(normalized)
            if expected_digest is None:
                errors.append(f"{path}.evidence_files[{index}]: missing checksum entry in SHA256SUMS")
                continue
            try:
                actual_digest = hashlib.sha256(resolved_candidate.read_bytes()).hexdigest()
            except OSError as error:
                errors.append(f"{path}.evidence_files[{index}]: cannot read evidence file: {error}")
                continue
            if actual_digest != expected_digest:
                errors.append(f"{path}.evidence_files[{index}]: SHA256SUMS hash mismatch")


def _validate_device_identity(document: Mapping[str, Any], errors: list[str]) -> None:
    device = _as_mapping(document.get("device"), "device", errors)
    observed_values = {
        field: _require_nonempty_string(device.get(field), f"device.{field}", errors).lower()
        for field in ("manufacturer", "model", "codename", "os_version")
    }
    role = device.get("evidence_role")
    if role not in {"primary_xiaomi_13", "general_android_substitute"}:
        errors.append("device.evidence_role: expected primary_xiaomi_13 or general_android_substitute")
    is_primary_xiaomi_13 = (
        "xiaomi" in observed_values["manufacturer"]
        and observed_values["model"] == "2211133c"
        and observed_values["codename"] == "fuxi"
    )
    is_nubia_p0110 = (
        "nubia" in observed_values["manufacturer"]
        and observed_values["model"] == "p0110"
        and observed_values["codename"] == "pacific"
    )
    if role == "primary_xiaomi_13" and not is_primary_xiaomi_13:
        errors.append("device.evidence_role: primary_xiaomi_13 requires Xiaomi 2211133C/fuxi identity")
    if role == "general_android_substitute" and is_primary_xiaomi_13:
        errors.append("device.evidence_role: Xiaomi 2211133C/fuxi evidence must use primary_xiaomi_13")
    claims_text = json.dumps(document.get("claims", []), ensure_ascii=False).lower()
    observed_text = " ".join(observed_values.values())
    is_nubia = is_nubia_p0110 or any(marker in observed_text for marker in ("nubia", "p0110", "pacific"))
    is_xiaomi = is_primary_xiaomi_13 or any(marker in observed_text for marker in ("xiaomi", "2211133c", "fuxi"))
    claims_xiaomi = any(marker in claims_text for marker in ("xiaomi", "2211133c", "fuxi"))
    claims_nubia = any(marker in claims_text for marker in ("nubia", "p0110", "pacific"))
    if is_nubia and claims_xiaomi:
        errors.append("claims: Nubia P0110/pacific evidence cannot be relabeled as Xiaomi/fuxi")
    if is_xiaomi and claims_nubia:
        errors.append("claims: Xiaomi/fuxi evidence cannot be relabeled as Nubia/P0110/pacific")


def _validate_claims(document: Mapping[str, Any], errors: list[str]) -> None:
    claims = _as_list(document.get("claims"), "claims", errors)
    if not claims:
        errors.append("claims: expected at least one human-readable claim")
        return
    for index, item in enumerate(claims):
        _require_nonempty_string(item, f"claims[{index}]", errors)


def validate_manifest(document: Mapping[str, Any], *, evidence_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if document.get("schema") != SCHEMA:
        errors.append(f"schema: expected {SCHEMA}")
    if document.get("result") != "pass":
        errors.append("result: expected pass; blocked/local/synthetic evidence cannot close the release gate")

    source = _as_mapping(document.get("source"), "source", errors)
    commit = _require_nonempty_string(source.get("commit"), "source.commit", errors)
    if commit and not HEX_COMMIT.fullmatch(commit):
        errors.append("source.commit: expected full 40-character lowercase hex commit")
    if source.get("tree_status") != "clean":
        errors.append("source.tree_status: expected clean")

    artifacts = _as_mapping(document.get("artifacts"), "artifacts", errors)
    for field in ("mac_host_sha256", "android_apk_sha256"):
        value = _require_nonempty_string(artifacts.get(field), f"artifacts.{field}", errors)
        if value and not HEX_SHA256.fullmatch(value):
            errors.append(f"artifacts.{field}: expected lowercase SHA-256")

    _validate_device_identity(document, errors)
    _validate_claims(document, errors)

    gates = _as_mapping(document.get("gates"), "gates", errors)
    checksum_index = _load_evidence_checksum_index(evidence_root, errors)
    allowed_gates = {rule.name for rule in GATE_RULES}
    for gate_name in gates:
        if gate_name not in allowed_gates:
            errors.append(f"gates.{gate_name}: unknown release gate")
    for rule in GATE_RULES:
        gate_path = f"gates.{rule.name}"
        gate = _as_mapping(gates.get(rule.name), gate_path, errors)
        if not gate:
            continue
        if gate.get("status") != "pass":
            errors.append(f"{gate_path}.status: expected pass")
        for field in rule.required_fields:
            if field not in gate:
                errors.append(f"{gate_path}.{field}: missing required field")
        _validate_evidence_files(gate, gate_path, errors, checksum_index)
        errors.extend(rule.validate(gate, gate_path))

    return errors


def load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ManifestError([f"{path}: invalid JSON: {error}"]) from error
    except OSError as error:
        raise ManifestError([f"{path}: cannot read: {error}"]) from error
    if not isinstance(value, dict):
        raise ManifestError([f"{path}: expected JSON object"])
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, help="release-gate manifest JSON to validate")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="optional directory used to require every evidence_files entry to exist",
    )
    parser.add_argument("--print-matrix", action="store_true", help="print the current open release-gate matrix")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_matrix:
        print(json.dumps({"schema": SCHEMA, "gates": gate_matrix()}, indent=2, sort_keys=True))
        if args.manifest is None:
            return 0
    if args.manifest is None:
        print("error: manifest is required unless --print-matrix is used", file=sys.stderr)
        return 2
    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest, evidence_root=args.evidence_root)
    if errors:
        print(json.dumps({"result": "fail", "errors": errors}, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"result": "pass", "schema": SCHEMA}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
