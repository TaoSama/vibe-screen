#!/usr/bin/env python3
"""Validate Phase 3 public-Internet soak evidence.

This gate is intentionally separate from the local synthetic WebRTC evidence
projection. A passing manifest must prove a real Android device on a public
Internet/NAT/TURN path plus a mixed-route soak. If public credentials, a public
TURN host, or physical-device evidence are unavailable, the manifest may be
validated only with --allow-blocked and cannot close the release gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA = "dev.vibescreen.phase3-public-internet-soak/v1"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
RAW_SERIAL_PATTERN = re.compile(r"\b[A-Z0-9]{10,}\b")
FORBIDDEN_PASS_TEXT = (
    "local_loopback_only",
    "synthetic_protocol_v1_device",
    "no_android_device_or_ui",
    "no_real_screen_capture",
    "no_public_internet_path",
    "127.0.0.1",
    "localhost",
    "loopback",
)
FORBIDDEN_PUBLIC_ENDPOINT_TEXT = (
    *FORBIDDEN_PASS_TEXT,
    "example.com",
    "example.org",
    "example.net",
    ".example",
    ".invalid",
    ".localhost",
    ".test",
)
REQUIRED_GATE_IDS = (
    "source_clean",
    "release_artifacts",
    "real_android_device_identity",
    "public_signaling_tls",
    "public_turn_tls",
    "direct_public_internet_stream",
    "forced_public_turn_relay_stream",
    "nat_restricted_turn_fallback",
    "touch_and_keyboard_input",
    "network_handoff_epoch_advance",
    "active_revocation_enforced",
    "post_revocation_reconnect_rejected",
    "two_hour_mixed_route_soak",
    "external_latency_method",
    "secret_redaction_scan",
)
ANDROID_SUBSTITUTE = "android_substitute"
PRIMARY_XIAOMI_13 = "primary_xiaomi13"
NUBIA_P0110 = "nubia-p0110"
XIAOMI_13 = "xiaomi13"
EXPECTED_DEVICES = {
    NUBIA_P0110: {
        "acceptance_role": ANDROID_SUBSTITUTE,
        "manufacturer": "nubia",
        "model": "P0110",
        "device": "pacific",
        "os_release": "16",
    },
    XIAOMI_13: {
        "acceptance_role": PRIMARY_XIAOMI_13,
        "manufacturer": "Xiaomi",
        "model": "2211133C",
        "device": "fuxi",
        "os_release": "16",
    },
}


class ManifestError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path}: expected object")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}: expected non-empty string")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestError(f"{path}: expected boolean")
    return value


def _number(value: Any, path: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ManifestError(f"{path}: expected number >= {minimum}")
    return float(value)


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestError(f"{path}: expected integer >= {minimum}")
    return value


def _hex(value: Any, path: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, path).lower()
    if pattern.fullmatch(text) is None or set(text) == {"0"}:
        raise ManifestError(f"{path}: expected non-placeholder lowercase hex digest")
    return text


def _timestamp(value: Any, path: str) -> str:
    text = _string(value, path)
    if RFC3339_UTC.fullmatch(text) is None:
        raise ManifestError(f"{path}: expected UTC RFC3339 timestamp ending in Z")
    return text


def _require_keys(document: dict[str, Any], keys: Iterable[str], path: str) -> None:
    for key in keys:
        if key not in document:
            raise ManifestError(f"{path}.{key}: missing")


def _evidence_paths(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{path}: expected non-empty evidence path array")
    paths: list[str] = []
    for index, item in enumerate(value):
        text = _string(item, f"{path}[{index}]")
        if text.startswith("/") or ".." in Path(text).parts:
            raise ManifestError(f"{path}[{index}]: expected repository-relative artifact path")
        _reject_sensitive_text(text, f"{path}[{index}]")
        paths.append(text)
    return paths


def _reject_sensitive_text(value: str, path: str) -> None:
    lowered = value.lower()
    secret_markers = ("token", "credential", "password", "secret", "private_key")
    if any(marker in lowered for marker in secret_markers):
        raise ManifestError(f"{path}: must not contain secret-bearing labels")
    if RAW_SERIAL_PATTERN.search(value):
        raise ManifestError(f"{path}: looks like a raw device serial")


def _reject_local_or_synthetic_pass_text(document: dict[str, Any]) -> None:
    rendered = json.dumps(document, sort_keys=True)
    lowered = rendered.lower()
    for marker in FORBIDDEN_PASS_TEXT:
        if marker in lowered:
            raise ManifestError(f"passing public-Internet evidence contains local/synthetic marker: {marker}")


def _validate_repository(document: dict[str, Any]) -> None:
    repository = _mapping(document.get("repository"), "repository")
    _require_keys(repository, ("commit", "tree", "status"), "repository")
    _hex(repository["commit"], "repository.commit", HEX_40)
    _hex(repository["tree"], "repository.tree", HEX_40)
    if repository["status"] != "clean":
        raise ManifestError("repository.status: expected clean")


def _validate_artifacts(document: dict[str, Any]) -> None:
    artifacts = _mapping(document.get("artifacts"), "artifacts")
    _require_keys(
        artifacts,
        ("apk_sha256", "host_build_sha256", "signaling_image_sha256", "relay_image_sha256", "coturn_image_sha256"),
        "artifacts",
    )
    for key in (
        "apk_sha256",
        "host_build_sha256",
        "signaling_image_sha256",
        "relay_image_sha256",
        "coturn_image_sha256",
    ):
        _hex(artifacts[key], f"artifacts.{key}", HEX_64)


def _validate_device(document: dict[str, Any], expected_device: str | None) -> None:
    device = _mapping(document.get("device"), "device")
    _require_keys(
        device,
        (
            "platform",
            "acceptance_role",
            "manufacturer",
            "model",
            "device",
            "os_release",
            "api_level",
            "serial_hash",
        ),
        "device",
    )
    if device["platform"] != "Android":
        raise ManifestError("device.platform: expected Android")
    role = _string(device["acceptance_role"], "device.acceptance_role")
    if role not in {PRIMARY_XIAOMI_13, ANDROID_SUBSTITUTE}:
        raise ManifestError("device.acceptance_role: expected primary_xiaomi13 or android_substitute")
    _hex(device["serial_hash"], "device.serial_hash", HEX_64)
    for key in ("manufacturer", "model", "device", "os_release", "api_level"):
        _reject_sensitive_text(_string(device[key], f"device.{key}"), f"device.{key}")
    if expected_device:
        expected = EXPECTED_DEVICES[expected_device]
        for key, wanted in expected.items():
            if device[key] != wanted:
                raise ManifestError(f"device.{key}: expected {wanted}")
    if role == ANDROID_SUBSTITUTE and (device["model"] == "2211133C" or device["device"] == "fuxi"):
        raise ManifestError("device: primary Xiaomi identity cannot be labelled as substitute")
    if role == PRIMARY_XIAOMI_13 and (device["model"] != "2211133C" or device["device"] != "fuxi"):
        raise ManifestError("device: non-Xiaomi identity cannot close the primary Xiaomi gate")


def _validate_network(document: dict[str, Any]) -> None:
    network = _mapping(document.get("network"), "network")
    _require_keys(network, ("topology", "signaling_origin", "turn_origin", "nat_observation"), "network")
    topology = _string(network["topology"], "network.topology")
    if topology not in {"public_internet", "carrier_nat", "symmetric_nat"}:
        raise ManifestError("network.topology: expected a public Internet or NAT topology")
    for key in ("signaling_origin", "turn_origin", "nat_observation"):
        value = _string(network[key], f"network.{key}")
        _reject_sensitive_text(value, f"network.{key}")
        lowered = value.lower()
        if any(marker in lowered for marker in FORBIDDEN_PUBLIC_ENDPOINT_TEXT):
            raise ManifestError(f"network.{key}: local/synthetic endpoints cannot close the public gate")


def _validate_routes(document: dict[str, Any]) -> None:
    routes = _mapping(document.get("routes"), "routes")
    _require_keys(routes, ("direct", "forced_turn", "nat_fallback"), "routes")
    direct = _mapping(routes["direct"], "routes.direct")
    forced = _mapping(routes["forced_turn"], "routes.forced_turn")
    fallback = _mapping(routes["nat_fallback"], "routes.nat_fallback")
    if direct.get("selected_candidate_pair") != "direct":
        raise ManifestError("routes.direct.selected_candidate_pair: expected direct")
    if forced.get("selected_candidate_pair") != "relay":
        raise ManifestError("routes.forced_turn.selected_candidate_pair: expected relay")
    if fallback.get("direct_candidates_blocked") is not True or fallback.get("selected_candidate_pair") != "relay":
        raise ManifestError("routes.nat_fallback: expected blocked direct candidates and relay selection")
    for path, route in (("routes.direct", direct), ("routes.forced_turn", forced), ("routes.nat_fallback", fallback)):
        _require_keys(route, ("evidence",), path)
        _evidence_paths(route["evidence"], f"{path}.evidence")


def _validate_handoff(document: dict[str, Any]) -> None:
    handoff = _mapping(document.get("handoff"), "handoff")
    _require_keys(handoff, ("network_changes", "initial_session_epoch", "recovered_session_epoch", "recovery_p95_seconds", "evidence"), "handoff")
    changes = _integer(handoff["network_changes"], "handoff.network_changes", minimum=1)
    if changes < 2:
        raise ManifestError("handoff.network_changes: expected at least Wi-Fi/cellular or equivalent round trip")
    initial = _integer(handoff["initial_session_epoch"], "handoff.initial_session_epoch", minimum=1)
    recovered = _integer(handoff["recovered_session_epoch"], "handoff.recovered_session_epoch", minimum=1)
    if recovered <= initial:
        raise ManifestError("handoff.recovered_session_epoch: expected strict epoch advance")
    _number(handoff["recovery_p95_seconds"], "handoff.recovery_p95_seconds", minimum=0)
    _evidence_paths(handoff["evidence"], "handoff.evidence")


def _validate_revocation(document: dict[str, Any]) -> None:
    revocation = _mapping(document.get("revocation"), "revocation")
    _require_keys(
        revocation,
        (
            "authority_rejected_signaling",
            "authority_rejected_relay_credentials",
            "active_peerconnection_disconnected",
            "active_turn_allocation_disconnected",
            "post_revocation_reconnect_rejected",
            "evidence",
        ),
        "revocation",
    )
    for key in (
        "authority_rejected_signaling",
        "authority_rejected_relay_credentials",
        "active_peerconnection_disconnected",
        "active_turn_allocation_disconnected",
        "post_revocation_reconnect_rejected",
    ):
        if _bool(revocation[key], f"revocation.{key}") is not True:
            raise ManifestError(f"revocation.{key}: expected true")
    _evidence_paths(revocation["evidence"], "revocation.evidence")


def _validate_soak(document: dict[str, Any]) -> None:
    soak = _mapping(document.get("soak"), "soak")
    _require_keys(
        soak,
        (
            "duration_seconds",
            "mixed_direct_and_relay",
            "network_changes",
            "memory_growth_mb",
            "nonce_reuse_detected",
            "steadily_increasing_latency",
            "queue_bound_violations",
            "evidence",
        ),
        "soak",
    )
    if _number(soak["duration_seconds"], "soak.duration_seconds", minimum=0) < 7200:
        raise ManifestError("soak.duration_seconds: expected at least 7200 seconds")
    if _bool(soak["mixed_direct_and_relay"], "soak.mixed_direct_and_relay") is not True:
        raise ManifestError("soak.mixed_direct_and_relay: expected true")
    _integer(soak["network_changes"], "soak.network_changes", minimum=1)
    _number(soak["memory_growth_mb"], "soak.memory_growth_mb", minimum=0)
    for key in ("nonce_reuse_detected", "steadily_increasing_latency", "queue_bound_violations"):
        if _bool(soak[key], f"soak.{key}") is not False:
            raise ManifestError(f"soak.{key}: expected false")
    _evidence_paths(soak["evidence"], "soak.evidence")


def _validate_latency(document: dict[str, Any]) -> None:
    latency = _mapping(document.get("latency"), "latency")
    _require_keys(latency, ("method", "direct_p95_ms", "relay_p95_ms", "evidence"), "latency")
    if latency["method"] != "external_camera":
        raise ManifestError("latency.method: expected external_camera")
    _number(latency["direct_p95_ms"], "latency.direct_p95_ms", minimum=0)
    _number(latency["relay_p95_ms"], "latency.relay_p95_ms", minimum=0)
    _evidence_paths(latency["evidence"], "latency.evidence")


def _validate_privacy(document: dict[str, Any]) -> None:
    privacy = _mapping(document.get("privacy"), "privacy")
    _require_keys(privacy, ("secret_scan", "packet_capture", "evidence"), "privacy")
    secret_scan = _mapping(privacy["secret_scan"], "privacy.secret_scan")
    _require_keys(secret_scan, ("status", "artifacts_scanned"), "privacy.secret_scan")
    if secret_scan["status"] != "pass":
        raise ManifestError("privacy.secret_scan.status: expected pass")
    _integer(secret_scan["artifacts_scanned"], "privacy.secret_scan.artifacts_scanned", minimum=1)
    packet_capture = _mapping(privacy["packet_capture"], "privacy.packet_capture")
    _require_keys(packet_capture, ("application_payload_ciphertext_only",), "privacy.packet_capture")
    if _bool(packet_capture["application_payload_ciphertext_only"], "privacy.packet_capture.application_payload_ciphertext_only") is not True:
        raise ManifestError("privacy.packet_capture.application_payload_ciphertext_only: expected true")
    _evidence_paths(privacy["evidence"], "privacy.evidence")


def _validate_gates(document: dict[str, Any], allow_blocked: bool) -> list[str]:
    gates = document.get("gates")
    if not isinstance(gates, list):
        raise ManifestError("gates: expected array")
    by_id: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for index, gate_value in enumerate(gates):
        gate = _mapping(gate_value, f"gates[{index}]")
        _require_keys(gate, ("id", "status", "evidence"), f"gates[{index}]")
        gate_id = _string(gate["id"], f"gates[{index}].id")
        if gate_id in by_id:
            raise ManifestError(f"gates[{index}].id: duplicate {gate_id}")
        if gate["status"] not in {"pass", "blocked", "fail"}:
            raise ManifestError(f"gates[{index}].status: expected pass, blocked, or fail")
        _evidence_paths(gate["evidence"], f"gates[{index}].evidence")
        by_id[gate_id] = gate
    missing = [gate_id for gate_id in REQUIRED_GATE_IDS if gate_id not in by_id]
    if missing:
        raise ManifestError("missing required gates: " + ", ".join(missing))
    for gate_id in REQUIRED_GATE_IDS:
        status = by_id[gate_id]["status"]
        if status != "pass":
            message = f"{gate_id}: {status}"
            if allow_blocked and status == "blocked":
                warnings.append(message)
            else:
                raise ManifestError(message)
    return warnings


def validate_manifest(
    document: dict[str, Any], *, allow_blocked: bool = False, expected_device: str | None = None
) -> list[str]:
    if document.get("schema") != SCHEMA:
        raise ManifestError(f"schema: expected {SCHEMA}")
    result = document.get("result")
    if result not in {"pass", "blocked"}:
        raise ManifestError("result: expected pass or blocked")
    _timestamp(document.get("generated_at_utc"), "generated_at_utc")
    if result == "blocked" and not allow_blocked:
        raise ManifestError("blocked public-Internet soak manifest cannot close the gate")
    if result == "pass" and allow_blocked:
        raise ManifestError("--allow-blocked is only for blocked readiness manifests")

    warnings = _validate_gates(document, allow_blocked)
    if result == "blocked":
        if not warnings:
            raise ManifestError("blocked manifest must include at least one blocked gate")
        return warnings

    _validate_repository(document)
    _validate_artifacts(document)
    _validate_device(document, expected_device)
    _validate_network(document)
    _validate_routes(document)
    _validate_handoff(document)
    _validate_revocation(document)
    _validate_soak(document)
    _validate_latency(document)
    _validate_privacy(document)
    _reject_local_or_synthetic_pass_text(document)
    return warnings


def template_manifest() -> dict[str, Any]:
    placeholder_hash = "0" * 64
    placeholder_commit = "0" * 40
    return {
        "schema": SCHEMA,
        "result": "blocked",
        "generated_at_utc": "2026-08-21T00:00:00Z",
        "repository": {"commit": placeholder_commit, "tree": placeholder_commit, "status": "clean"},
        "device": {
            "platform": "Android",
            "acceptance_role": ANDROID_SUBSTITUTE,
            "manufacturer": "nubia",
            "model": "P0110",
            "device": "pacific",
            "os_release": "16",
            "api_level": "recorded API level",
            "serial_hash": placeholder_hash,
        },
        "gates": [
            {
                "id": gate_id,
                "status": "blocked",
                "evidence": ["evidence/blocked-public-internet-prerequisites.md"],
            }
            for gate_id in REQUIRED_GATE_IDS
        ],
        "blocked_reason": "public signaling/TURN credentials or server/device evidence unavailable",
        "notes": ["A blocked manifest is not acceptance evidence."],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Phase 3 public-Internet soak manifest.")
    parser.add_argument("manifest", nargs="?", type=Path, help="Path to the evidence manifest JSON.")
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Validate blocked readiness structure without closing the release gate.",
    )
    parser.add_argument(
        "--expected-device",
        choices=tuple(sorted(EXPECTED_DEVICES)),
        help="Require a specific known Android evidence device identity.",
    )
    parser.add_argument("--template", action="store_true", help="Print a redaction-safe blocked manifest template.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        print(json.dumps(template_manifest(), indent=2, sort_keys=True))
        return 0
    if args.manifest is None:
        raise SystemExit("manifest is required unless --template is used")
    document = json.loads(args.manifest.read_text(encoding="utf-8"))
    warnings = validate_manifest(
        _mapping(document, "manifest"),
        allow_blocked=args.allow_blocked,
        expected_device=args.expected_device,
    )
    if args.allow_blocked:
        print("Phase 3 public-Internet soak manifest is blocked and does not close the gate:")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("Phase 3 public-Internet soak manifest passes all required release gates.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, ManifestError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
