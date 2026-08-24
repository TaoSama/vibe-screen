"""Evaluate Phase 3 public Internet soak and latency release evidence.

This checker is intentionally stricter than the generic latency and soak
helpers. It treats local loopback, forced local coturn, synthetic media, missing
raw latency samples, and missing two-hour soak telemetry as blockers rather than
release evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    KIND_GLASS_TO_GLASS,
    TRANSPORT_INTERNET,
)
from .latency_evidence import build_latency_evidence_report
from .soak_public_report import EvidenceInputError, read_json as _read_json


KIND = "phase3_internet_release_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"
MISSING = "missing"
MINIMUM_SOAK_DURATION_SECONDS = 2 * 60 * 60 * 0.98
MINIMUM_SOAK_SAMPLE_COUNT = 2 * 60 * 2 * 0.98
MINIMUM_SOAK_TELEMETRY_COUNT = 2 * 60 * 2 * 0.98
MAXIMUM_SAMPLE_GAP_SECONDS = 90.0
MAXIMUM_STREAM_STATS_GAP_SECONDS = 90.0
MAXIMUM_HEARTBEAT_GAP_SECONDS = 90.0
MAXIMUM_QUEUE_DROP_TOTAL = 0.0
MAXIMUM_DROPPED_FRAMES = 0.0
MAXIMUM_MEMORY_SECOND_HALF_SLOPE_KIB_PER_MINUTE = 40.0
MAXIMUM_MEMORY_SECOND_HALF_DRIFT_KIB = 8 * 1024.0
MAXIMUM_THERMAL_STATUS = 2.0

REQUIRED_RAW_ARTIFACTS = (
    "README.md",
    "phase3-internet-manifest.json",
    "device-info.json",
    "host.txt",
    "build.txt",
    "apk-sha256.txt",
    "direct-session.jsonl",
    "relay-session.jsonl",
    "network-handoff.jsonl",
    "replay-revocation.jsonl",
    "packet-capture-notes.md",
    "privacy-manifest.json",
    "real-media-continuity.json",
    "latency/direct/manifest.json",
    "latency/direct/samples.csv",
    "latency/direct/raw-camera.mov",
    "latency/relay/manifest.json",
    "latency/relay/samples.csv",
    "latency/relay/raw-camera.mov",
    "soak-2h/summary.json",
    "soak-2h/samples.jsonl",
    "soak-2h/host-telemetry.jsonl",
    "soak-2h/exact-window-report.json",
    "host.log",
    "raw-logcat.txt",
)

BUILD_SIGNING_PATTERNS = (
    re.compile(r"TeamIdentifier=\S+", re.IGNORECASE),
    re.compile(r"Authority=\S+", re.IGNORECASE),
    re.compile(r"Verification:\s+valid on disk", re.IGNORECASE),
)
HOST_SCREEN_RECORDING_PATTERNS = (
    re.compile(r"Screen Recording(?: permission)?(?: is)? granted", re.IGNORECASE),
    re.compile(r"screen_recording[_-]?granted[=: ]+true", re.IGNORECASE),
)
HOST_PUBLIC_ROUTE_PATTERNS = (
    re.compile(r"selected candidate pair", re.IGNORECASE),
    re.compile(r"public[_ -]?internet", re.IGNORECASE),
    re.compile(r"\b(relay|srflx)\b", re.IGNORECASE),
)

REQUIRED_SESSION_FIELDS = (
    "public_internet_path",
    "deployed_remote_turn",
    "real_android_device",
    "real_macos_host",
    "identity_signed_host",
    "screen_recording_granted",
    "real_capture_to_mediacodec",
    "visible_input_effects",
    "network_handoff_recovered",
    "cross_service_revocation",
    "packet_capture_confidentiality",
    "no_synthetic_media",
)

STATUS_GATE_REQUIREMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "network_handoff": (
        "phase3_network_handoff_evidence",
        (
            "public_internet_path",
            "independent_network_change",
            "ice_restart_observed",
            "new_session_epoch",
            "old_epoch_packets_rejected",
            "no_plaintext_fallback",
            "no_synthetic_media",
        ),
    ),
    "cross_service_revocation": (
        "phase3_cross_service_revocation_evidence",
        (
            "active_peer_disconnected",
            "stale_credentials_rejected",
            "new_signaling_access_rejected",
            "new_turn_credentials_rejected",
            "coturn_allocation_terminated",
            "post_revocation_packet_count_zero",
            "no_plaintext_fallback",
            "no_synthetic_media",
        ),
    ),
    "packet_capture_confidentiality": (
        "phase3_packet_capture_confidentiality_evidence",
        (
            "direct_route_reviewed",
            "relay_route_reviewed",
            "encrypted_application_records",
            "no_plaintext_screen_content",
            "no_credential_exposure",
            "no_pairing_secret_exposure",
            "no_synthetic_media",
        ),
    ),
}

PHASE3_SOAK_TRUE_FIELDS = (
    "public_internet_path",
    "network_handoff_observed",
    "cross_service_revocation_observed",
    "packet_capture_confidentiality_observed",
    "no_synthetic_media",
    "no_plaintext_fallback",
)

class Phase3GateError(RuntimeError):
    """Raised when the gate cannot read its own input package."""


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_optional_json(path: Path | None, label: str) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, f"missing {label}"
    try:
        return _read_json(path, label), None
    except EvidenceInputError as error:
        return None, str(error)


def _non_empty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _contains_all(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return all(pattern.search(text) for pattern in patterns)


def _contains_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return records
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def _existing_path(
    root: Path,
    candidates: Sequence[str],
    *,
    allow_cwd_relative: bool = False,
) -> Path | None:
    for relative in candidates:
        candidate = Path(relative)
        options = (candidate,)
        if not candidate.is_absolute():
            options = (candidate, root / candidate) if allow_cwd_relative else (root / candidate,)
        for path in options:
            if path.exists():
                return path
    return None


def _status_from_json(document: dict[str, Any] | None) -> str | None:
    if document is None:
        return None
    value = document.get("verdict", document.get("status", document.get("result")))
    return value if isinstance(value, str) else None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _is_redacted(value: str | None) -> bool:
    return value is None or value.strip().lower() in {"[redacted]", "redacted", "<redacted>"}


def _device_record(document: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {}
    nested = document.get("device")
    return nested if isinstance(nested, dict) else document


def _gate(
    name: str,
    status: str,
    *,
    evidence: Sequence[str] = (),
    reasons: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "evidence": list(evidence),
        "reasons": list(reasons),
    }


def _get(record: dict[str, Any], *path: str) -> Any:
    value: Any = record
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted):
            return converted
    return None


def _minimum(measured: float | None, minimum: float) -> dict[str, Any]:
    return {"measured": measured, "minimum": minimum, "passed": measured is not None and measured >= minimum}


def _maximum(measured: float | None, maximum: float) -> dict[str, Any]:
    return {"measured": measured, "maximum": maximum, "passed": measured is not None and measured <= maximum}


def _stats_count(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    return _finite_number(value.get("count")) if isinstance(value, dict) else None


def _stats_max(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    return _finite_number(value.get("max")) if isinstance(value, dict) else None


def _stats_drift(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path)
    if not isinstance(value, dict):
        return None
    first = _finite_number(value.get("first"))
    final = _finite_number(value.get("final"))
    if first is None or final is None:
        return None
    return final - first


def _second_half_slope(report: dict[str, Any], *path: str) -> float | None:
    value = _get(report, *path, "slope_kib_per_minute")
    if not isinstance(value, dict):
        return None
    return _finite_number(value.get("second_half"))


def _gap_max(report: dict[str, Any], *path: str) -> float | None:
    return _finite_number(_get(report, *path, "maximum_interval_seconds"))


def _session_manifest_gate(manifest: dict[str, Any] | None) -> dict[str, Any]:
    evidence = ["phase3-internet-manifest.json"]
    if manifest is None:
        return _gate(
            "public_internet_session_manifest",
            BLOCKED,
            evidence=evidence,
            reasons=["phase3-internet-manifest.json is missing or unreadable"],
        )
    reasons: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        reasons.append(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("kind") != "phase3_internet_release_manifest":
        reasons.append("kind must be phase3_internet_release_manifest")
    session = manifest.get("session")
    if not isinstance(session, dict):
        reasons.append("session must be an object")
        session = {}
    for field in REQUIRED_SESSION_FIELDS:
        if session.get(field) is not True:
            reasons.append(f"session.{field} must be true for Phase 3 release evidence")
    if session.get("network_scope") != "public_internet":
        reasons.append("session.network_scope must be public_internet")
    if session.get("turn_scope") != "deployed_remote_turn":
        reasons.append("session.turn_scope must be deployed_remote_turn")
    routes = session.get("routes")
    if (
        not isinstance(routes, list)
        or not all(isinstance(route, str) for route in routes)
        or set(routes) != {"direct", "relay"}
    ):
        reasons.append("session.routes must contain exactly direct and relay")
    device = manifest.get("device") if isinstance(manifest.get("device"), dict) else {}
    if not all(device.get(field) for field in ("manufacturer", "model", "codename", "android_release", "adb_serial")):
        reasons.append("device identity must include manufacturer, model, codename, android_release, and adb_serial")
    if (
        str(device.get("manufacturer", "")).lower() == "xiaomi"
        and str(device.get("codename", "")) != "fuxi"
    ):
        reasons.append("Xiaomi evidence must identify codename fuxi")
    if str(device.get("model", "")).upper() == "P0110" and str(device.get("codename", "")) != "pacific":
        reasons.append("Nubia P0110 evidence must identify codename pacific")
    return _gate(
        "public_internet_session_manifest",
        PASS if not reasons else BLOCKED,
        evidence=evidence,
        reasons=reasons,
    )


def _device_identity_gate(
    root: Path,
    manifest: dict[str, Any] | None,
    device_info: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = ["phase3-internet-manifest.json", "device-info.json"]
    if manifest is None or device_info is None:
        return _gate(
            "device_identity_cross_check",
            BLOCKED,
            evidence=[item for item in evidence if _non_empty(root / item)],
            reasons=["phase3-internet-manifest.json and device-info.json are required for device identity cross-check"],
        )
    manifest_device = _device_record(manifest.get("device") if isinstance(manifest.get("device"), dict) else None)
    observed_device = _device_record(device_info)
    reasons: list[str] = []
    field_pairs = (
        ("manufacturer", "manufacturer"),
        ("model", "model"),
        ("codename", "codename"),
        ("android_release", "android_version"),
        ("sdk", "sdk"),
    )
    for manifest_field, observed_field in field_pairs:
        manifest_value = _string_or_none(manifest_device.get(manifest_field))
        observed_value = _string_or_none(observed_device.get(observed_field))
        if observed_value is None and observed_field == "android_version":
            observed_value = _string_or_none(observed_device.get("android_release"))
        if manifest_value is None or observed_value is None:
            reasons.append(f"device identity must include {manifest_field}")
        elif manifest_value.lower() != observed_value.lower():
            reasons.append(
                f"device identity mismatch for {manifest_field}: "
                f"manifest {manifest_value!r} != device-info {observed_value!r}"
            )
    manifest_serial = _string_or_none(manifest_device.get("adb_serial"))
    observed_serial = _string_or_none(
        observed_device.get("adb_serial", observed_device.get("hardware_serial"))
    )
    if manifest_serial is None:
        reasons.append("device identity must include adb_serial")
    elif observed_serial is None:
        reasons.append("device-info identity must include adb_serial")
    elif not _is_redacted(manifest_serial) and not _is_redacted(observed_serial) and manifest_serial != observed_serial:
        reasons.append(
            f"device identity mismatch for adb_serial: manifest {manifest_serial!r} != device-info {observed_serial!r}"
        )
    return _gate(
        "device_identity_cross_check",
        PASS if not reasons else BLOCKED,
        evidence=[item for item in evidence if _non_empty(root / item)],
        reasons=reasons,
    )


def _raw_artifacts_gate(root: Path) -> dict[str, Any]:
    missing = [relative for relative in REQUIRED_RAW_ARTIFACTS if not _non_empty(root / relative)]
    evidence = [relative for relative in REQUIRED_RAW_ARTIFACTS if relative not in missing]
    reasons = ["missing or empty required artifact: " + relative for relative in missing]
    apk_sha = _read_text_or_empty(root / "apk-sha256.txt").strip()
    if "apk-sha256.txt" not in missing and re.fullmatch(r"[0-9a-fA-F]{64}(?:\s+\S+)?", apk_sha) is None:
        reasons.append("apk-sha256.txt must contain a SHA-256 digest")
    build_text = _read_text_or_empty(root / "build.txt")
    if "build.txt" not in missing and not _contains_all(build_text, BUILD_SIGNING_PATTERNS):
        reasons.append("build.txt must include identity-signed Host codesign evidence")
    host_text = _read_text_or_empty(root / "host.log")
    if "host.log" not in missing and not _contains_any(host_text, HOST_SCREEN_RECORDING_PATTERNS):
        reasons.append("host.log must include Screen Recording granted evidence")
    if "host.log" not in missing and not _contains_all(host_text, HOST_PUBLIC_ROUTE_PATTERNS):
        reasons.append("host.log must include selected public Internet ICE candidate evidence")
    for relative, expected_route in (
        ("direct-session.jsonl", "direct"),
        ("relay-session.jsonl", "relay"),
    ):
        if relative in missing:
            continue
        records = _jsonl_records(root / relative)
        matching_records = [
            record for record in records
            if record.get("route") == expected_route
            and record.get("public_internet_path") is True
            and record.get("selected_candidate_pair") is not None
            and record.get("no_plaintext_fallback") is True
            and record.get("no_synthetic_media") is True
        ]
        if not matching_records:
            reasons.append(
                f"{relative} must contain a JSONL record for {expected_route} public Internet session evidence"
            )
    return _gate(
        "raw_evidence_bundle",
        PASS if not reasons else BLOCKED,
        evidence=evidence,
        reasons=reasons,
    )


def _latency_manifest_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path.parent / "manifest.json"


def _latency_gate(root: Path, route: str, path: Path | None) -> dict[str, Any]:
    document, error = _read_optional_json(path, f"{route} latency evidence")
    evidence = [_relative(root, path)] if path is not None else []
    reasons: list[str] = []
    if error is not None:
        return _gate(f"{route}_external_camera_latency", BLOCKED, evidence=[item for item in evidence if item], reasons=[error])
    reported_verdict = _status_from_json(document)
    if reported_verdict != PASS:
        reasons.append(f"{route} latency verdict is {reported_verdict!r}, not 'pass'")
    if (document or {}).get("latency_kind") != KIND_GLASS_TO_GLASS:
        reasons.append(f"{route} latency must be glass-to-glass")
    if (document or {}).get("transport") != TRANSPORT_INTERNET:
        reasons.append(f"{route} latency transport must be internet")
    if (document or {}).get("measurement_method") != "external-camera":
        reasons.append(f"{route} latency must use external-camera measurement")
    gate = (document or {}).get("gate") if isinstance((document or {}).get("gate"), dict) else {}
    if gate.get("profile") != GATE_INTERNET_GLASS_TO_GLASS_SUB150:
        reasons.append(f"{route} latency gate profile must be {GATE_INTERNET_GLASS_TO_GLASS_SUB150}")
    if gate.get("can_close_performance_gate") is not True:
        reasons.append(f"{route} latency gate must report can_close_performance_gate=true")
    if gate.get("requires_external_hardware") is not True:
        reasons.append(f"{route} latency gate must require external hardware")

    manifest_path = _latency_manifest_path(path)
    manifest, manifest_error = _read_optional_json(manifest_path, f"{route} latency manifest")
    manifest_relative = _relative(root, manifest_path)
    if manifest_relative is not None:
        evidence.append(manifest_relative)
    if manifest_error is not None:
        reasons.append(manifest_error)
    else:
        formal_report = build_latency_evidence_report(
            manifest_path=manifest_path,
            gate_profile=GATE_INTERNET_GLASS_TO_GLASS_SUB150,
        )
        formal_verdict = _status_from_json(formal_report)
        if formal_verdict != PASS:
            reasons.append(f"{route} formal latency package verdict is {formal_verdict!r}, not 'pass'")
        formal_gate = formal_report.get("gate") if isinstance(formal_report.get("gate"), dict) else {}
        formal_reasons = formal_gate.get("reasons") if isinstance(formal_gate.get("reasons"), list) else []
        reasons.extend(f"{route} formal latency package: {reason}" for reason in formal_reasons)
        expected_route = "direct-public-internet" if route == "direct" else "forced-public-turn"
        manifest_route = _get(manifest or {}, "internet_route", "route")
        if manifest_route != expected_route:
            reasons.append(
                f"{route} latency manifest internet_route.route must be {expected_route}"
            )
        session_path = root / f"{route}-session.jsonl"
        session_records = _jsonl_records(session_path)
        candidate_pair = _get(manifest or {}, "internet_route", "candidate_pair")
        turn_hostname = _string_or_none(_get(manifest or {}, "internet_route", "turn_deployment", "public_hostname"))
        turn_resolved_ip = _string_or_none(_get(manifest or {}, "internet_route", "turn_deployment", "resolved_ip"))
        same_private_network = _get(manifest or {}, "internet_route", "network_topology", "same_private_network")
        if isinstance(candidate_pair, dict):
            expected_local_type = candidate_pair.get("local_candidate_type")
            expected_remote_type = candidate_pair.get("remote_candidate_type")
        else:
            expected_local_type = None
            expected_remote_type = None
        session_match = False
        for record in session_records:
            selected = record.get("selected_candidate_pair")
            if not isinstance(selected, dict):
                continue
            if (
                record.get("route") == route
                and record.get("public_internet_path") is True
                and record.get("same_private_network") is False
                and selected.get("local_candidate_type") == expected_local_type
                and selected.get("remote_candidate_type") == expected_remote_type
                and (selected.get("turn_public_hostname") == turn_hostname or record.get("turn_public_hostname") == turn_hostname)
                and (selected.get("turn_resolved_ip") == turn_resolved_ip or record.get("turn_resolved_ip") == turn_resolved_ip)
                and same_private_network is False
            ):
                session_match = True
                break
        if not session_match:
            reasons.append(f"{route} session JSONL must match latency manifest public route metadata")
    return _gate(
        f"{route}_external_camera_latency",
        PASS if not reasons else (FAIL if reported_verdict == FAIL else INSUFFICIENT),
        evidence=[item for item in evidence if item],
        reasons=reasons,
    )


def _real_media_gate(root: Path, path: Path | None) -> dict[str, Any]:
    document, error = _read_optional_json(path, "real media continuity evidence")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("real_capture_to_mediacodec", BLOCKED, evidence=[item for item in evidence if item], reasons=[error])
    reasons: list[str] = []
    if _status_from_json(document) != PASS:
        reasons.append("real-media continuity verdict must be pass")
    if (document or {}).get("kind") != "phase3_real_media_continuity_preflight":
        reasons.append("real-media kind must be phase3_real_media_continuity_preflight")
    if (document or {}).get("gate_can_close_phase3_release") is not False:
        reasons.append("real-media continuity file must remain a narrow preflight")
    conditions = (document or {}).get("conditions")
    if not isinstance(conditions, dict):
        reasons.append("real-media conditions are required")
        conditions = {}
    expected_conditions = {
        "network_path": "public_internet",
        "host_signing": "identity_signed",
        "screen_recording": "granted",
    }
    for field, expected_value in expected_conditions.items():
        if conditions.get(field) != expected_value:
            reasons.append(f"real-media conditions.{field} must be {expected_value!r}")
    summary = (document or {}).get("continuity_summary")
    if not isinstance(summary, dict):
        reasons.append("real-media continuity_summary is required")
        summary = {}
    expected = {
        "public_internet_path": True,
        "media_source": "real_screencapturekit_or_cgdisplaystream",
        "mediacodec_first_input_frame": True,
        "mediacodec_first_output_frame": True,
    }
    for field, expected_value in expected.items():
        if summary.get(field) != expected_value:
            reasons.append(f"real-media continuity_summary.{field} must be {expected_value!r}")
    output_frames = _finite_number(summary.get("continuous_output_frames"))
    if output_frames is None or output_frames < 120:
        reasons.append("real-media continuous_output_frames must be at least 120")
    host_observation = (document or {}).get("host_observation")
    if not isinstance(host_observation, dict):
        reasons.append("real-media host_observation is required")
        host_observation = {}
    android_observation = (document or {}).get("android_observation")
    if not isinstance(android_observation, dict):
        reasons.append("real-media android_observation is required")
        android_observation = {}
    for field in (
        "internet_product_session_started",
        "webrtc_transport_observed",
        "capture_started",
        "real_capture_first_frame",
        "videotoolbox_configured",
        "videotoolbox_output_observed",
    ):
        if host_observation.get(field) is not True:
            reasons.append(f"real-media host_observation.{field} must be true")
    for field in (
        "internet_stream_active",
        "decoder_configured",
        "first_input_frame",
        "first_output_frame",
    ):
        if android_observation.get(field) is not True:
            reasons.append(f"real-media android_observation.{field} must be true")
    if host_observation.get("synthetic_markers") != []:
        reasons.append("real-media host_observation.synthetic_markers must be empty")
    if android_observation.get("synthetic_markers") != []:
        reasons.append("real-media android_observation.synthetic_markers must be empty")
    return _gate(
        "real_capture_to_mediacodec",
        PASS if not reasons else (BLOCKED if _status_from_json(document) == BLOCKED else INSUFFICIENT),
        evidence=[item for item in evidence if item],
        reasons=reasons,
    )


def _status_file_gate(
    root: Path,
    name: str,
    candidates: Sequence[str],
    reason: str,
    *,
    allow_cwd_relative: bool = False,
) -> dict[str, Any]:
    path = _existing_path(root, candidates, allow_cwd_relative=allow_cwd_relative)
    document, error = _read_optional_json(path, name.replace("_", " "))
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate(name, BLOCKED, evidence=[item for item in evidence if item], reasons=[error])
    status = _status_from_json(document)
    reasons: list[str] = []
    expected_kind, required_fields = STATUS_GATE_REQUIREMENTS[name]
    if (document or {}).get("schema_version") != SCHEMA_VERSION:
        reasons.append(f"{name} schema_version must be {SCHEMA_VERSION}")
    if (document or {}).get("kind") != expected_kind:
        reasons.append(f"{name} kind must be {expected_kind}")
    observations = (document or {}).get("observations")
    if not isinstance(observations, dict):
        reasons.append(f"{name} observations must be an object")
        observations = {}
    for field in required_fields:
        if observations.get(field) is not True:
            reasons.append(f"{name} observations.{field} must be true")
    raw_sources = (document or {}).get("raw_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        reasons.append(f"{name} raw_sources must list the source logs or captures used")
    elif any(not isinstance(item, str) or not item.strip() for item in raw_sources):
        reasons.append(f"{name} raw_sources must contain non-empty strings")
    if status == PASS and not reasons:
        return _gate(name, PASS, evidence=[item for item in evidence if item])
    if status != PASS:
        reasons.append(reason)
    return _gate(
        name,
        BLOCKED if status == BLOCKED else INSUFFICIENT,
        evidence=[item for item in evidence if item],
        reasons=reasons,
    )


def _soak_gate(root: Path, path: Path | None) -> dict[str, Any]:
    document, error = _read_optional_json(path, "two-hour soak report")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("two_hour_mixed_route_soak", BLOCKED, evidence=[item for item in evidence if item], reasons=[error])
    reasons: list[str] = []
    if (document or {}).get("derivation_status") != "complete":
        reasons.append("soak exact-window report derivation_status must be complete")
    if _get(document or {}, "source_summary", "status") != "complete":
        reasons.append("source soak summary must be complete")
    scope = (document or {}).get("phase3_internet_scope")
    if not isinstance(scope, dict):
        reasons.append("phase3_internet_scope is required for Phase 3 release soak evidence")
        scope = {}
    if scope.get("network_scope") != "public_internet":
        reasons.append("phase3_internet_scope.network_scope must be public_internet")
    routes = scope.get("route_coverage")
    if not isinstance(routes, dict):
        reasons.append("phase3_internet_scope.route_coverage must be an object")
        routes = {}
    if routes.get("direct") is not True:
        reasons.append("phase3_internet_scope.route_coverage.direct must be true")
    if routes.get("relay") is not True:
        reasons.append("phase3_internet_scope.route_coverage.relay must be true")
    for field in PHASE3_SOAK_TRUE_FIELDS:
        if scope.get(field) is not True:
            reasons.append(f"phase3_internet_scope.{field} must be true")
    if scope.get("nonce_reuse_detected") is not False:
        reasons.append("phase3_internet_scope.nonce_reuse_detected must be false")
    window = (document or {}).get("window") if isinstance((document or {}).get("window"), dict) else {}
    metrics = (document or {}).get("metrics") if isinstance((document or {}).get("metrics"), dict) else {}
    criteria = {
        "duration_seconds": _minimum(_finite_number(window.get("duration_seconds")), MINIMUM_SOAK_DURATION_SECONDS),
        "sample_records_in_window": _minimum(_finite_number(window.get("sample_records_in_window")), MINIMUM_SOAK_SAMPLE_COUNT),
        "telemetry_records_in_window": _minimum(_finite_number(window.get("telemetry_records_in_window")), MINIMUM_SOAK_TELEMETRY_COUNT),
        "sample_gap_seconds": _maximum(_gap_max(metrics, "samples", "gaps"), MAXIMUM_SAMPLE_GAP_SECONDS),
        "stream_stats_gap_seconds": _maximum(_gap_max(metrics, "telemetry", "stream_stats_gaps"), MAXIMUM_STREAM_STATS_GAP_SECONDS),
        "heartbeat_gap_seconds": _maximum(_gap_max(metrics, "telemetry", "heartbeat_gaps"), MAXIMUM_HEARTBEAT_GAP_SECONDS),
        "frame_queue_drop_total": _maximum(_finite_number(_get(metrics, "stream", "frame_queue_drop_total")), MAXIMUM_QUEUE_DROP_TOTAL),
        "reported_dropped_frames": _maximum(_finite_number(_get(metrics, "stream", "reported_dropped_frames", "sum")), MAXIMUM_DROPPED_FRAMES),
        "thermal_status_max": _maximum(_stats_max(metrics, "thermal", "status"), MAXIMUM_THERMAL_STATUS),
        "client_rss_second_half_slope_kib_per_minute": _maximum(_second_half_slope(metrics, "memory_kib", "client_total_pss"), MAXIMUM_MEMORY_SECOND_HALF_SLOPE_KIB_PER_MINUTE),
        "host_rss_second_half_slope_kib_per_minute": _maximum(_second_half_slope(metrics, "memory_kib", "host_rss"), MAXIMUM_MEMORY_SECOND_HALF_SLOPE_KIB_PER_MINUTE),
        "client_rss_drift_kib": _maximum(_stats_drift(metrics, "memory_kib", "client_total_pss"), MAXIMUM_MEMORY_SECOND_HALF_DRIFT_KIB),
        "host_rss_drift_kib": _maximum(_stats_drift(metrics, "memory_kib", "host_rss"), MAXIMUM_MEMORY_SECOND_HALF_DRIFT_KIB),
        "stream_fps_samples": _minimum(_stats_count(metrics, "stream", "fps"), MINIMUM_SOAK_TELEMETRY_COUNT),
        "accepted_heartbeat_count": _minimum(_finite_number(_get(metrics, "telemetry", "accepted_heartbeat_count")), MINIMUM_SOAK_TELEMETRY_COUNT),
    }
    sample_records = _finite_number(window.get("sample_records_in_window"))
    telemetry_records = _finite_number(window.get("telemetry_records_in_window"))
    raw_sample_lines = _line_count(root / "soak-2h/samples.jsonl")
    raw_telemetry_lines = _line_count(root / "soak-2h/host-telemetry.jsonl")
    if sample_records is None or raw_sample_lines < sample_records:
        reasons.append("soak-2h/samples.jsonl must contain at least sample_records_in_window rows")
    if telemetry_records is None or raw_telemetry_lines < telemetry_records:
        reasons.append("soak-2h/host-telemetry.jsonl must contain at least telemetry_records_in_window rows")
    for name, criterion in criteria.items():
        if criterion["passed"] is not True:
            reasons.append(f"soak criterion did not pass: {name}")
    status = PASS if not reasons else INSUFFICIENT
    gate = _gate("two_hour_mixed_route_soak", status, evidence=[item for item in evidence if item], reasons=reasons)
    gate["criteria"] = criteria
    return gate


def _report_evidence_dir(root: Path) -> str:
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return root.relative_to(candidate).as_posix()
    return str(root)


def derive_gate(
    evidence_dir: Path,
    *,
    direct_latency: Path | None = None,
    relay_latency: Path | None = None,
    real_media: Path | None = None,
    soak_report: Path | None = None,
    handoff_evidence: Path | None = None,
    revocation_evidence: Path | None = None,
    packet_capture_evidence: Path | None = None,
) -> dict[str, Any]:
    root = evidence_dir.resolve()
    manifest_path = root / "phase3-internet-manifest.json"
    manifest, manifest_error = _read_optional_json(
        manifest_path if manifest_path.exists() else None,
        "Phase 3 Internet manifest",
    )
    device_info, _device_info_error = _read_optional_json(
        root / "device-info.json" if (root / "device-info.json").exists() else None,
        "device identity",
    )
    gates = [
        _session_manifest_gate(manifest),
        _device_identity_gate(root, manifest, device_info),
        _raw_artifacts_gate(root),
        _latency_gate(root, "direct", direct_latency or root / "latency/direct/latency-evidence.json"),
        _latency_gate(root, "relay", relay_latency or root / "latency/relay/latency-evidence.json"),
        _real_media_gate(root, real_media or root / "real-media-continuity.json"),
        _status_file_gate(
            root,
            "network_handoff",
            (str(handoff_evidence),) if handoff_evidence is not None else ("network-handoff.json",),
            "network handoff evidence must report pass",
            allow_cwd_relative=handoff_evidence is not None,
        ),
        _status_file_gate(
            root,
            "cross_service_revocation",
            (str(revocation_evidence),) if revocation_evidence is not None else ("revocation-evidence.json",),
            "cross-service revocation evidence must report pass",
            allow_cwd_relative=revocation_evidence is not None,
        ),
        _status_file_gate(
            root,
            "packet_capture_confidentiality",
            (str(packet_capture_evidence),) if packet_capture_evidence is not None else ("packet-capture-confidentiality.json",),
            "packet capture confidentiality evidence must report pass",
            allow_cwd_relative=packet_capture_evidence is not None,
        ),
        _soak_gate(root, soak_report or root / "soak-2h/exact-window-report.json"),
    ]
    reasons: list[str] = []
    if manifest_error is not None:
        reasons.append(manifest_error)
    for gate in gates:
        reasons.extend(f"{gate['name']}: {reason}" for reason in gate["reasons"])

    statuses = {gate["status"] for gate in gates}
    if FAIL in statuses:
        verdict = FAIL
    elif BLOCKED in statuses:
        verdict = BLOCKED
    elif MISSING in statuses or INSUFFICIENT in statuses:
        verdict = INSUFFICIENT
    else:
        verdict = PASS

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_dir": _report_evidence_dir(root),
        "verdict": verdict,
        "gate_can_close_phase3_release": verdict == PASS,
        "gates": gates,
        "reasons": reasons,
        "interpretation": (
            "A pass requires real Android and macOS peers over a genuine public Internet path, "
            "a deployed remote TURN route, real ScreenCaptureKit or CGDisplayStream frames "
            "decoded by Android MediaCodec, external-camera latency evidence for direct and "
            "relay routes, network handoff, cross-service revocation, packet-capture "
            "confidentiality, and a two-hour mixed-route soak. Local loopback, forced local "
            "coturn, synthetic media, missing raw samples, or blocked attempts cannot close "
            "the Phase 3 release gate."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--direct-latency", type=Path)
    parser.add_argument("--relay-latency", type=Path)
    parser.add_argument("--real-media", type=Path)
    parser.add_argument("--soak-report", type=Path)
    parser.add_argument("--handoff-evidence", type=Path)
    parser.add_argument("--revocation-evidence", type=Path)
    parser.add_argument("--packet-capture-evidence", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    output = arguments.output or (arguments.evidence_dir / "phase3-internet-release-gate.json")
    try:
        document = derive_gate(
            arguments.evidence_dir,
            direct_latency=arguments.direct_latency,
            relay_latency=arguments.relay_latency,
            real_media=arguments.real_media,
            soak_report=arguments.soak_report,
            handoff_evidence=arguments.handoff_evidence,
            revocation_evidence=arguments.revocation_evidence,
            packet_capture_evidence=arguments.packet_capture_evidence,
        )
        _write_json(output, document)
    except (OSError, EvidenceInputError, Phase3GateError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0 if document["verdict"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
