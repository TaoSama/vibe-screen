#!/usr/bin/env python3
"""Validate a Phase 3 Secure Internet release-gate evidence manifest.

This checker is intentionally a necessary-condition gate. It verifies that a
future curated evidence package explicitly claims the release-blocking real-world
observations before documentation may describe Phase 3 as released. It does not
make local, synthetic, or blocked evidence into a pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "dev.vibescreen.phase3-release-gate-manifest/v1"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")


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


COMMON_GATE_REQUIRED_FIELDS = ("synthetic_media", "local_loopback_only")


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


def _require_not_local_only(gate: Mapping[str, Any], path: str, errors: list[str]) -> None:
    _require_bool(gate.get("synthetic_media", False), f"{path}.synthetic_media", False, errors)
    _require_bool(gate.get("local_loopback_only", False), f"{path}.local_loopback_only", False, errors)


def _validate_direct_path(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _require_bool(gate.get("public_internet_path"), f"{path}.public_internet_path", True, errors)
    if gate.get("route") != "direct":
        errors.append(f"{path}.route: expected direct")
    selected_pair = _require_nonempty_string(gate.get("selected_candidate_pair"), f"{path}.selected_candidate_pair", errors)
    if selected_pair and not selected_pair.startswith("direct("):
        errors.append(f"{path}.selected_candidate_pair: expected direct candidate pair")
    return errors


def _validate_turn_path(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
    _require_bool(gate.get("public_internet_path"), f"{path}.public_internet_path", True, errors)
    _require_bool(gate.get("remote_turn_deployment"), f"{path}.remote_turn_deployment", True, errors)
    _require_bool(gate.get("local_coturn_only", False), f"{path}.local_coturn_only", False, errors)
    if gate.get("route") != "relay":
        errors.append(f"{path}.route: expected relay")
    selected_pair = _require_nonempty_string(gate.get("selected_candidate_pair"), f"{path}.selected_candidate_pair", errors)
    if selected_pair and not selected_pair.startswith("relay("):
        errors.append(f"{path}.selected_candidate_pair: expected relay candidate pair")
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
    _require_minimum_number(gate.get("handoff_count"), f"{path}.handoff_count", 1, errors)
    _require_bool(gate.get("session_epoch_advanced"), f"{path}.session_epoch_advanced", True, errors)
    _require_bool(gate.get("stale_epoch_rejected"), f"{path}.stale_epoch_rejected", True, errors)
    _require_bool(gate.get("recovered_streaming"), f"{path}.recovered_streaming", True, errors)
    recovery = _require_positive_number(gate.get("recovery_seconds"), f"{path}.recovery_seconds", errors)
    limit = gate.get("approved_limit_seconds", 5)
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
        errors.append(f"{path}.approved_limit_seconds: expected positive number")
    elif recovery and recovery > float(limit):
        errors.append(f"{path}.recovery_seconds: exceeded approved limit {float(limit):g}")
    return errors


def _validate_soak(gate: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    _require_not_local_only(gate, path, errors)
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
    for field in ("active_session_disconnected", "direct_reconnect_rejected", "relay_reconnect_rejected", "turn_allocation_disconnected"):
        _require_bool(gate.get(field), f"{path}.{field}", True, errors)
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


GATE_RULES: tuple[GateRule, ...] = (
    GateRule(
        "public_internet_direct_path",
        "Direct WebRTC selected across a genuine public Internet path.",
        COMMON_GATE_REQUIRED_FIELDS + ("route", "public_internet_path", "selected_candidate_pair"),
        _validate_direct_path,
    ),
    GateRule(
        "remote_turn_relay_path",
        "Forced relay selected through a real remote TURN deployment.",
        COMMON_GATE_REQUIRED_FIELDS
        + ("route", "public_internet_path", "remote_turn_deployment", "local_coturn_only", "selected_candidate_pair"),
        _validate_turn_path,
    ),
    GateRule(
        "real_screencapturekit_to_android_media",
        "Real macOS capture/encoder output reaches Android MediaCodec.",
        COMMON_GATE_REQUIRED_FIELDS
        + ("capture_source", "android_decoder", "screen_capture_frames", "encoded_frames", "android_decoded_frames"),
        _validate_real_media,
    ),
    GateRule(
        "network_handoff_recovery",
        "A real Wi-Fi/cellular/VPN handoff recovers with a fresh epoch.",
        COMMON_GATE_REQUIRED_FIELDS
        + ("handoff_count", "session_epoch_advanced", "stale_epoch_rejected", "recovered_streaming"),
        _validate_handoff,
    ),
    GateRule(
        "cross_service_revocation",
        "Revocation propagates through signaling and TURN and terminates active use.",
        COMMON_GATE_REQUIRED_FIELDS
        + (
            "active_session_disconnected",
            "direct_reconnect_rejected",
            "relay_reconnect_rejected",
            "turn_allocation_disconnected",
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
        "two_hour_mixed_route_soak",
        "Two-hour mixed direct/relay/network-change soak remains bounded.",
        COMMON_GATE_REQUIRED_FIELDS
        + ("duration_seconds", "routes", "network_change_count", "bounded_queues", "bounded_memory", "no_nonce_reuse"),
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


def _validate_evidence_files(
    gate: Mapping[str, Any],
    path: str,
    errors: list[str],
    evidence_root: Path | None,
) -> None:
    files = _as_list(gate.get("evidence_files"), f"{path}.evidence_files", errors)
    if not files:
        errors.append(f"{path}.evidence_files: expected at least one evidence file")
        return
    for index, item in enumerate(files):
        file_path = _require_nonempty_string(item, f"{path}.evidence_files[{index}]", errors)
        if not file_path:
            continue
        candidate = Path(file_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"{path}.evidence_files[{index}]: expected repository-relative file path")
            continue
        if evidence_root is not None and not (evidence_root / candidate).is_file():
            errors.append(f"{path}.evidence_files[{index}]: file does not exist under evidence root")


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
        _validate_evidence_files(gate, gate_path, errors, evidence_root)
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
