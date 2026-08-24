#!/usr/bin/env python3
"""Validate a formal latency evidence package.

The latency summarizer accepts raw sample rows so offline fixtures can exercise
pass/fail profiles. This checker is stricter: it requires provenance for the
measurement method (external-camera or synchronized-clock), sample annotations,
device/build, and trigger method before a latency profile can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_PROFILES,
    GATE_USB_GLASS_TO_GLASS_SUB50,
    METHOD_EXTERNAL_CAMERA,
    METHOD_SYNCHRONIZED_CLOCK,
    LatencyInputError,
    load_samples,
    summarize,
)


FORMAL_LATENCY_PROFILES = (
    GATE_USB_GLASS_TO_GLASS_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    GATE_INPUT_P95_SUB50,
)
PROFILE_ARTIFACT_REQUIREMENTS = {
    GATE_USB_GLASS_TO_GLASS_SUB50: (
        "usb_connection",
        "retain ADB reverse/USB connection setup and active USB stream proof",
    ),
    GATE_LAN_GLASS_TO_GLASS_SUB80: (
        "lan_network_preflight",
        "retain LAN network preflight plus active trusted-LAN stream proof",
    ),
    GATE_INTERNET_GLASS_TO_GLASS_SUB150: (
        "internet_public_route_record",
        "retain public Internet route, remote peer, TURN endpoint, and active stream proof",
    ),
    GATE_INPUT_P95_SUB50: (
        "input_actuation_record",
        "retain real physical input actuation and visible Mac-side result proof",
    ),
}
SYNCHRONIZED_CLOCK_ARTIFACT_REQUIREMENT = (
    "synchronization_record",
    "retain clock synchronization proof, skew checks, drift check, and timing error-budget derivation",
)

SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
ANNOTATION_MANUAL_FRAME_COUNT = "manual-frame-count"
ANNOTATION_DIRECT_LATENCY_MS = "direct-latency-ms"
ANNOTATION_METHODS = (
    ANNOTATION_MANUAL_FRAME_COUNT,
    ANNOTATION_DIRECT_LATENCY_MS,
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "latency-evidence.schema.json"

REQUIRED_TOP_LEVEL_OBJECTS = (
    "camera",
    "recording",
    "samples",
    "device",
    "host",
    "build",
    "measurement_setup",
)

REQUIRED_TEXT_FIELDS = {
    "camera": ("manufacturer", "model", "mode", "shutter_mode"),
    "recording": ("raw_video", "recorded_at", "operator", "sha256"),
    "synchronization": (
        "host_clock_source",
        "device_clock_source",
        "sync_procedure",
        "input_timestamp_method",
        "result_timestamp_method",
    ),
    "samples": ("file", "format", "sha256", "annotation_method", "annotator"),
    "device": ("manufacturer", "model", "codename", "os_version"),
    "host": ("model", "macos_version"),
    "build": ("repository_revision", "host_artifact", "client_artifact"),
    "measurement_setup": (
        "stimulus",
        "start_event_definition",
        "end_event_definition",
        "lighting",
        "mounting",
        "clock_domain",
        "notes",
    ),
}


class LatencyEvidenceError(ValueError):
    """Raised when a formal latency evidence package cannot be read."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise LatencyEvidenceError(f"cannot read {label} {path}: {error}") from error
    except UnicodeDecodeError as error:
        raise LatencyEvidenceError(f"invalid UTF-8 in {label} {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise LatencyEvidenceError(f"invalid JSON in {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise LatencyEvidenceError(f"{label} must be a JSON object")
    return document


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _describe_json_type(expected_type: str) -> str:
    if expected_type == "number":
        return "a JSON number"
    if expected_type == "object":
        return "an object"
    if expected_type == "string":
        return "a string"
    if expected_type == "boolean":
        return "a boolean"
    return expected_type


def _validate_schema_node(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []

    for child_schema in schema.get("allOf", []):
        if isinstance(child_schema, dict):
            errors.extend(_validate_schema_node(value, child_schema, path))

    condition_schema = schema.get("if")
    then_schema = schema.get("then")
    if (
        isinstance(condition_schema, dict)
        and isinstance(then_schema, dict)
        and not _validate_schema_node(value, condition_schema, path)
    ):
        errors.extend(_validate_schema_node(value, then_schema, path))

    not_schema = schema.get("not")
    if isinstance(not_schema, dict) and not _validate_schema_node(value, not_schema, path):
        errors.append(f"{path} must not match disallowed schema")

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must be {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(item) for item in schema["enum"])
        errors.append(f"{path} must be one of: {allowed}")

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        errors.append(f"{path} must be {_describe_json_type(expected_type)}")
        return errors

    object_keywords = (
        isinstance(schema.get("properties"), dict)
        or isinstance(schema.get("required"), list)
        or schema.get("additionalProperties") is False
    )
    if isinstance(value, dict) and (expected_type == "object" or object_keywords):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for field in required:
            if isinstance(field, str) and field not in value:
                errors.append(f"{path}.{field} is required")
        if schema.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{path}.{field} is not allowed by schema")
        for field, child_schema in properties.items():
            if field in value and isinstance(child_schema, dict):
                errors.extend(_validate_schema_node(value[field], child_schema, f"{path}.{field}"))
    elif expected_type == "string":
        assert isinstance(value, str)
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"{path} must not be empty")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.fullmatch(pattern, value) is None:
            errors.append(f"{path} must match {pattern}")
    elif expected_type == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        number = float(value)
        if not math.isfinite(number):
            errors.append(f"{path} must be finite")
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and number < float(minimum):
            errors.append(f"{path} must be at least {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and number > float(maximum):
            errors.append(f"{path} must be at most {maximum}")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(exclusive_maximum, (int, float)) and number >= float(exclusive_maximum):
            errors.append(f"{path} must be less than {exclusive_maximum}")

    return errors


def _validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    schema = _load_json(SCHEMA_PATH, "latency evidence schema")
    return _validate_schema_node(manifest, schema, "manifest")


def _as_non_empty_text(value: Any, field: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} is required")
        return None
    return value.strip()


def _require_object(document: dict[str, Any], field: str, errors: list[str]) -> dict[str, Any]:
    value = document.get(field)
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return {}
    return value


def _resolve_package_path(
    manifest_path: Path,
    raw_path: Any,
    field: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path.strip())
    if path.is_absolute():
        errors.append(f"{field} must be relative to the evidence directory")
        return None
    package_root = manifest_path.parent.resolve()
    try:
        resolved_path = (package_root / path).resolve()
        resolved_path.relative_to(package_root)
    except (OSError, ValueError):
        errors.append(f"{field} must stay within the evidence directory")
        return None
    return resolved_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_iso_bmff_boxes(data: bytes, start: int = 0, end: int | None = None):
    limit = len(data) if end is None else min(end, len(data))
    offset = start
    while offset + 8 <= limit:
        size = int.from_bytes(data[offset:offset + 4], "big")
        box_type = data[offset + 4:offset + 8]
        header_size = 8
        if size == 1:
            if offset + 16 > limit:
                break
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = limit - offset
        if size < header_size or offset + size > limit:
            break
        content_start = offset + header_size
        box_end = offset + size
        yield box_type, content_start, box_end
        offset = box_end


def _walk_iso_bmff_boxes(data: bytes, start: int, end: int):
    for box_type, content_start, box_end in _iter_iso_bmff_boxes(data, start, end):
        yield box_type, content_start, box_end
        if box_type in {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"moof", b"traf"}:
            yield from _walk_iso_bmff_boxes(data, content_start, box_end)


def _looks_like_iso_bmff_video(data: bytes) -> bool:
    if len(data) < 32 or data[4:8] != b"ftyp":
        return False
    top_level = list(_iter_iso_bmff_boxes(data))
    if not any(box_type == b"ftyp" for box_type, _start, _end in top_level):
        return False
    if not any(box_type == b"mdat" and end > start for box_type, start, end in top_level):
        return False
    moov_ranges = [(start, end) for box_type, start, end in top_level if box_type == b"moov"]
    mdat_ranges = [(start, end) for box_type, start, end in top_level if box_type == b"mdat"]
    has_video_handler = False
    has_video_samples = False
    has_fragmented_video_samples = False
    has_video_sample_description = False
    has_chunk_offset_into_media = False
    for moov_start, moov_end in moov_ranges:
        for box_type, content_start, content_end in _walk_iso_bmff_boxes(data, moov_start, moov_end):
            if box_type == b"hdlr" and content_start + 12 <= content_end:
                has_video_handler = has_video_handler or data[content_start + 8:content_start + 12] == b"vide"
            elif box_type == b"stsd" and content_start + 16 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                sample_entry = data[content_start + 12:content_start + 16]
                has_video_sample_description = has_video_sample_description or (
                    entry_count > 0 and sample_entry in {b"avc1", b"avc3", b"hvc1", b"hev1", b"mp4v"}
                )
            elif box_type == b"stsz" and content_start + 12 <= content_end:
                default_sample_size = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                sample_count = int.from_bytes(data[content_start + 8:content_start + 12], "big")
                has_sample_sizes = False
                if sample_count > 0:
                    if default_sample_size > 0:
                        has_sample_sizes = True
                    elif content_start + 12 + (sample_count * 4) <= content_end:
                        has_sample_sizes = any(
                            int.from_bytes(
                                data[content_start + 12 + (index * 4):content_start + 16 + (index * 4)],
                                "big",
                            )
                            > 0
                            for index in range(sample_count)
                        )
                has_video_samples = has_video_samples or has_sample_sizes
            elif box_type == b"stco" and content_start + 12 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                if entry_count > 0:
                    chunk_offset = int.from_bytes(data[content_start + 8:content_start + 12], "big")
                    has_chunk_offset_into_media = has_chunk_offset_into_media or any(
                        start <= chunk_offset < end for start, end in mdat_ranges
                    )
            elif box_type == b"co64" and content_start + 16 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                if entry_count > 0:
                    chunk_offset = int.from_bytes(data[content_start + 8:content_start + 16], "big")
                    has_chunk_offset_into_media = has_chunk_offset_into_media or any(
                        start <= chunk_offset < end for start, end in mdat_ranges
                    )
            elif box_type == b"trun" and content_start + 8 <= content_end:
                sample_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                has_fragmented_video_samples = has_fragmented_video_samples or sample_count > 0
    for moof_start, moof_end in ((start, end) for box_type, start, end in top_level if box_type == b"moof"):
        for box_type, content_start, content_end in _walk_iso_bmff_boxes(data, moof_start, moof_end):
            if box_type == b"trun" and content_start + 8 <= content_end:
                sample_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                has_fragmented_video_samples = has_fragmented_video_samples or sample_count > 0
    has_progressive_samples = has_video_samples and has_chunk_offset_into_media
    return has_video_handler and has_video_sample_description and (
        has_progressive_samples or has_fragmented_video_samples
    )


def _looks_like_camera_video(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    header = data[:64]
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov", ".m4v"}:
        return _looks_like_iso_bmff_video(data)
    if suffix in {".mkv", ".webm"}:
        return len(data) >= 128 and header.startswith(b"\x1a\x45\xdf\xa3")
    return False


def _validate_required_metadata(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    measurement_method = manifest.get("measurement_method")
    if measurement_method not in (METHOD_EXTERNAL_CAMERA, METHOD_SYNCHRONIZED_CLOCK):
        errors.append("measurement_method must be external-camera or synchronized-clock")

    is_external_camera = measurement_method == METHOD_EXTERNAL_CAMERA
    is_synchronized_clock = measurement_method == METHOD_SYNCHRONIZED_CLOCK

    required_sections = list(REQUIRED_TOP_LEVEL_OBJECTS)
    if is_synchronized_clock:
        required_sections = [s for s in required_sections if s not in ("camera", "recording")]
        required_sections.append("synchronization")

    for section in required_sections:
        section_document = _require_object(manifest, section, errors)
        for field in REQUIRED_TEXT_FIELDS.get(section, ()):
            _as_non_empty_text(section_document.get(field), f"{section}.{field}", errors)

    if is_external_camera:
        camera = manifest.get("camera") if isinstance(manifest.get("camera"), dict) else {}
        frame_rate_value = camera.get("frame_rate_fps")
        if isinstance(frame_rate_value, bool) or not isinstance(frame_rate_value, (int, float)):
            errors.append("camera.frame_rate_fps must be a finite number")
        else:
            frame_rate = float(frame_rate_value)
            if not math.isfinite(frame_rate):
                errors.append("camera.frame_rate_fps must be a finite number")
            elif frame_rate < 120:
                errors.append("camera.frame_rate_fps must be at least 120 for high-frame-rate evidence")

    samples = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    if samples.get("annotation_method") not in ANNOTATION_METHODS:
        errors.append(
            "samples.annotation_method must be manual-frame-count or direct-latency-ms"
        )
    elif is_synchronized_clock and samples.get("annotation_method") != ANNOTATION_DIRECT_LATENCY_MS:
        errors.append(
            "synchronized-clock measurement_method requires samples.annotation_method direct-latency-ms"
        )

    setup = manifest.get("measurement_setup") if isinstance(manifest.get("measurement_setup"), dict) else {}
    if is_external_camera:
        if setup.get("clock_domain") != "single-external-camera-timebase":
            errors.append("measurement_setup.clock_domain must be single-external-camera-timebase")
        uncertainty = setup.get("max_frame_annotation_uncertainty_ms")
        if uncertainty in (None, ""):
            errors.append("measurement_setup.max_frame_annotation_uncertainty_ms is required")
        else:
            try:
                uncertainty_ms = float(uncertainty)
                if not math.isfinite(uncertainty_ms):
                    errors.append(
                        "measurement_setup.max_frame_annotation_uncertainty_ms must be finite"
                    )
                elif uncertainty_ms < 0:
                    errors.append("measurement_setup.max_frame_annotation_uncertainty_ms must not be negative")
            except (TypeError, ValueError):
                errors.append("measurement_setup.max_frame_annotation_uncertainty_ms must be numeric")
    elif is_synchronized_clock:
        if setup.get("clock_domain") != "synchronized-host-device-clocks":
            errors.append("measurement_setup.clock_domain must be synchronized-host-device-clocks")
        if manifest.get("latency_kind") != "input":
            errors.append("synchronized-clock measurement_method requires latency_kind input")
        sync = manifest.get("synchronization") if isinstance(manifest.get("synchronization"), dict) else {}
        sync_components: dict[str, float] = {}
        for field in ("before_skew_ms", "after_skew_ms", "max_drift_ms"):
            value = sync.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"synchronization.{field} must be a finite number")
                continue
            number = float(value)
            if not math.isfinite(number):
                errors.append(f"synchronization.{field} must be finite")
            elif number < 0:
                errors.append(f"synchronization.{field} must not be negative")
            else:
                sync_components[field] = number
        budget_value = sync.get("total_error_budget_ms")
        if isinstance(budget_value, bool) or not isinstance(budget_value, (int, float)):
            errors.append("synchronization.total_error_budget_ms must be a finite number")
        else:
            budget_ms = float(budget_value)
            if not math.isfinite(budget_ms):
                errors.append("synchronization.total_error_budget_ms must be finite")
            elif budget_ms < 0:
                errors.append("synchronization.total_error_budget_ms must not be negative")
            elif budget_ms >= 5:
                errors.append(
                    "synchronization.total_error_budget_ms must be less than 5 ms "
                    "(10% of the sub-50 ms P95 input gate)"
                )
            else:
                for field, component_ms in sync_components.items():
                    if component_ms > budget_ms:
                        errors.append(
                            f"synchronization.{field} must be less than or equal to "
                            "synchronization.total_error_budget_ms"
                        )
                if len(sync_components) == 3 and sum(sync_components.values()) > budget_ms:
                    errors.append(
                        "synchronization.before_skew_ms + synchronization.after_skew_ms + "
                        "synchronization.max_drift_ms must be less than or equal to "
                        "synchronization.total_error_budget_ms"
                    )

    return errors


def _looks_local_or_private_hostname(hostname: str) -> bool:
    normalized = hostname.strip().lower().rstrip(".")
    if normalized in {"localhost", "loopback"} or normalized.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(normalized.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


def _ip_address(value: Any) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


def _validate_retained_turn_endpoint(public_hostname: Any, resolved_ip: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(public_hostname, str) or not public_hostname.strip():
        return errors
    retained_address = _ip_address(resolved_ip)
    if retained_address is None or not retained_address.is_global:
        errors.append(
            "internet_route.turn_deployment.resolved_ip must record the retained "
            "resolved global IP for the TURN hostname"
        )
        return errors

    hostname_address = _ip_address(public_hostname)
    if hostname_address is not None and hostname_address != retained_address:
        errors.append(
            "internet_route.turn_deployment.resolved_ip must match the literal "
            "TURN public_hostname address"
        )
    return errors


def _validate_internet_route(manifest: dict[str, Any], gate_profile: str) -> list[str]:
    if gate_profile != GATE_INTERNET_GLASS_TO_GLASS_SUB150:
        if "internet_route" in manifest:
            return ["internet_route is only allowed for the internet-glass-to-glass-sub150 profile"]
        return []

    errors: list[str] = []
    route = manifest.get("internet_route")
    if not isinstance(route, dict):
        return [
            "internet_route is required for internet-glass-to-glass-sub150 and must "
            "record the public TURN deployment, remote peer, selected candidate pair, "
            "and non-LAN network topology"
        ]

    turn = route.get("turn_deployment") if isinstance(route.get("turn_deployment"), dict) else {}
    public_hostname = turn.get("public_hostname")
    if isinstance(public_hostname, str) and _looks_local_or_private_hostname(public_hostname):
        errors.append(
            "internet_route.turn_deployment.public_hostname must be a public Internet "
            "TURN hostname or global IP, not localhost, .local, loopback, or private address"
        )
    errors.extend(_validate_retained_turn_endpoint(public_hostname, turn.get("resolved_ip")))

    remote_peer = route.get("remote_peer") if isinstance(route.get("remote_peer"), dict) else {}
    for field in ("operator", "network", "public_ip_asn", "location"):
        value = remote_peer.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"internet_route.remote_peer.{field} is required for Internet latency evidence")

    topology = route.get("network_topology") if isinstance(route.get("network_topology"), dict) else {}
    if topology.get("same_private_network") is not False:
        errors.append(
            "internet_route.network_topology.same_private_network must be false; "
            "trusted LAN or loopback routes cannot close the Internet latency gate"
        )

    candidate_pair = route.get("candidate_pair") if isinstance(route.get("candidate_pair"), dict) else {}
    selected_route = route.get("route")
    local_type = candidate_pair.get("local_candidate_type")
    remote_type = candidate_pair.get("remote_candidate_type")
    relay_protocol = candidate_pair.get("relay_protocol")
    if selected_route == "forced-public-turn":
        if local_type != "relay" or remote_type != "relay":
            errors.append(
                "internet_route.candidate_pair must record relay/relay candidate types "
                "for forced-public-turn evidence"
            )
        if relay_protocol not in ("turn-udp", "turn-tcp", "turn-tls"):
            errors.append(
                "internet_route.candidate_pair.relay_protocol must be turn-udp, turn-tcp, "
                "or turn-tls for forced-public-turn evidence"
            )
    elif selected_route == "direct-public-internet":
        if local_type not in ("host", "srflx") or remote_type not in ("host", "srflx"):
            errors.append(
                "internet_route.candidate_pair must record host/srflx candidate types "
                "for direct-public-internet evidence"
            )

    return errors


def _validate_manifest_matches_summary(
    manifest: dict[str, Any], summary: dict[str, Any], gate_profile: str
) -> list[str]:
    errors: list[str] = []
    profile = GATE_PROFILES[gate_profile]

    if manifest.get("gate_profile") != gate_profile:
        errors.append("manifest.gate_profile must match --gate-profile")
    manifest_method = manifest.get("measurement_method")
    if manifest_method not in (METHOD_EXTERNAL_CAMERA, METHOD_SYNCHRONIZED_CLOCK):
        errors.append("manifest.measurement_method must be external-camera or synchronized-clock")
    if summary.get("measurement_method") != manifest_method:
        errors.append("summary.measurement_method must match manifest.measurement_method")
    if summary.get("latency_kind") != profile["kind"]:
        errors.append(f"summary.latency_kind must be {profile['kind']}")
    expected_transport = profile["transport"]
    if expected_transport is not None and summary.get("transport") != expected_transport:
        errors.append(f"summary.transport must be {expected_transport}")

    return errors


def _validate_referenced_files(
    manifest_path: Path,
    manifest: dict[str, Any],
    gate_profile: str,
) -> tuple[list[str], dict[str, Path | None]]:
    errors: list[str] = []
    is_external_camera = manifest.get("measurement_method") == METHOD_EXTERNAL_CAMERA
    recording = manifest.get("recording") if isinstance(manifest.get("recording"), dict) else {}
    samples = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    raw_references: dict[str, Any] = {"samples.file": samples.get("file")}
    if is_external_camera:
        raw_references["recording.raw_video"] = recording.get("raw_video")
    gate_artifacts = manifest.get("gate_artifacts")
    if not isinstance(gate_artifacts, dict):
        errors.append(
            "gate_artifacts must be an object containing profile-specific retained artifacts"
        )
        gate_artifacts = {}
    required_artifact, requirement = PROFILE_ARTIFACT_REQUIREMENTS[gate_profile]
    artifact = gate_artifacts.get(required_artifact)
    if not isinstance(artifact, dict):
        errors.append(f"gate_artifacts.{required_artifact} is required: {requirement}")
    else:
        raw_references[f"gate_artifacts.{required_artifact}.file"] = artifact.get("file")
    sync_artifact: dict[str, Any] | None = None
    if manifest.get("measurement_method") == METHOD_SYNCHRONIZED_CLOCK:
        sync_artifact_key, sync_requirement = SYNCHRONIZED_CLOCK_ARTIFACT_REQUIREMENT
        candidate = gate_artifacts.get(sync_artifact_key)
        if not isinstance(candidate, dict):
            errors.append(f"gate_artifacts.{sync_artifact_key} is required: {sync_requirement}")
        else:
            sync_artifact = candidate
            raw_references[f"gate_artifacts.{sync_artifact_key}.file"] = candidate.get("file")
    references: dict[str, Path | None] = {}
    for field, raw_path in raw_references.items():
        path = _resolve_package_path(manifest_path, raw_path, field, errors)
        references[field] = path
        if path is not None and not path.is_file():
            errors.append(f"{field} does not exist: {path}")

    digest_bindings: list[tuple[str, Any, Path | None]] = [
        ("samples.sha256", samples.get("sha256"), references["samples.file"]),
    ]
    if is_external_camera:
        digest_bindings.append(
            ("recording.sha256", recording.get("sha256"), references.get("recording.raw_video"))
        )
    if isinstance(artifact, dict):
        digest_bindings.append(
            (
                f"gate_artifacts.{required_artifact}.sha256",
                artifact.get("sha256"),
                references.get(f"gate_artifacts.{required_artifact}.file"),
            )
        )
    if sync_artifact is not None:
        sync_artifact_key = SYNCHRONIZED_CLOCK_ARTIFACT_REQUIREMENT[0]
        digest_bindings.append(
            (
                f"gate_artifacts.{sync_artifact_key}.sha256",
                sync_artifact.get("sha256"),
                references.get(f"gate_artifacts.{sync_artifact_key}.file"),
            )
        )
    for field, expected_sha256, path in digest_bindings:
        if not isinstance(expected_sha256, str) or SHA256_PATTERN.fullmatch(expected_sha256) is None:
            errors.append(f"{field} must be a 64-character hexadecimal SHA-256 digest")
        elif path is not None and path.is_file():
            try:
                actual_sha256 = _sha256(path)
            except OSError as error:
                errors.append(f"cannot hash {path}: {error}")
            else:
                if actual_sha256 != expected_sha256.lower():
                    errors.append(f"{field} does not match its referenced file")
    raw_video = references.get("recording.raw_video")
    if is_external_camera and raw_video is not None and raw_video.is_file() and not _looks_like_camera_video(raw_video):
        errors.append("recording.raw_video must be a readable camera video container with a supported layout")
    return errors, references


def _validate_sample_annotations(
    manifest: dict[str, Any], rows: Sequence[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    samples = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    camera = manifest.get("camera") if isinstance(manifest.get("camera"), dict) else {}
    annotation_method = samples.get("annotation_method")
    try:
        declared_frame_rate = float(camera.get("frame_rate_fps"))
    except (TypeError, ValueError):
        declared_frame_rate = math.nan

    for index, row in enumerate(rows, start=1):
        has_latency = row.get("latency_ms") not in (None, "")
        frame_fields = ("start_frame", "end_frame", "camera_fps")
        present_frame_fields = [field for field in frame_fields if row.get(field) not in (None, "")]
        if annotation_method == ANNOTATION_MANUAL_FRAME_COUNT:
            if has_latency or len(present_frame_fields) != len(frame_fields):
                errors.append(
                    f"sample {index}: manual-frame-count requires only start_frame, "
                    "end_frame, and camera_fps"
                )
                continue
            try:
                sample_frame_rate = float(row["camera_fps"])
            except (TypeError, ValueError):
                continue
            if (
                math.isfinite(declared_frame_rate)
                and math.isfinite(sample_frame_rate)
                and not math.isclose(sample_frame_rate, declared_frame_rate, rel_tol=0, abs_tol=1e-6)
            ):
                errors.append(f"sample {index}: camera_fps must match camera.frame_rate_fps")
        elif annotation_method == ANNOTATION_DIRECT_LATENCY_MS:
            if not has_latency or present_frame_fields:
                errors.append(f"sample {index}: direct-latency-ms requires only latency_ms")
    return errors


def _failure_report(manifest_path: Path, gate_profile: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": None,
        "kind": "latency_evidence_gate",
        "status": "failed",
        "derivation_status": "failed",
        "verdict": "insufficient",
        "latency_kind": None,
        "transport": None,
        "measurement_method": None,
        "gate": {
            "profile": gate_profile,
            "can_close_performance_gate": False,
            "summary_verdict": "insufficient",
            "threshold_ms": None,
            "observed_ms": None,
            "sample_count": None,
            "min_sample_count": None,
            "requires_external_hardware": True,
            "reasons": [reason],
        },
        "metrics": {},
        "source": {"manifest": str(manifest_path)},
    }


def build_latency_evidence_report(
    *,
    manifest_path: Path,
    gate_profile: str,
) -> dict[str, Any]:
    """Validate formal external-camera metadata and return a gate report."""
    manifest = _load_json(manifest_path, "latency evidence manifest")
    schema_errors = _validate_manifest_schema(manifest)
    errors = list(schema_errors)
    errors.extend(_validate_required_metadata(manifest))
    errors.extend(_validate_internet_route(manifest, gate_profile))
    reference_errors, references = _validate_referenced_files(manifest_path, manifest, gate_profile)
    errors.extend(reference_errors)

    samples_section = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    sample_format = samples_section.get("format")
    sample_path = references.get("samples.file")
    summary: dict[str, Any] | None = None
    if (
        not schema_errors
        and sample_path is not None
        and sample_path.is_file()
        and sample_format in ("csv", "json")
    ):
        try:
            with sample_path.open("r", encoding="utf-8", newline="") as stream:
                rows = load_samples(stream, sample_format)
            errors.extend(_validate_sample_annotations(manifest, rows))
            summary = summarize(
                rows,
                kind=str(manifest.get("latency_kind")),
                measurement_method=str(manifest.get("measurement_method")),
                transport=str(manifest.get("transport")),
                run_id=str(manifest.get("run_id")),
                gate_profile=gate_profile,
            )
        except (OSError, LatencyInputError) as error:
            errors.append(f"cannot summarize samples: {error}")
    elif sample_format not in ("csv", "json"):
        errors.append("samples.format must be csv or json")

    if summary is not None:
        errors.extend(_validate_manifest_matches_summary(manifest, summary, gate_profile))

    gate = summary.get("gate", {}) if summary is not None else {}
    summary_verdict = summary.get("verdict") if summary is not None else "insufficient"
    reasons = list(gate.get("reasons", [])) if isinstance(gate.get("reasons"), list) else []
    formal_verdict = str(summary_verdict)
    conservative_observed_ms: float | None = None
    if summary is not None and summary_verdict == "pass":
        try:
            observed_ms = float(gate["observed_ms"])
            threshold_ms = float(gate["threshold_ms"])
            if manifest.get("measurement_method") == METHOD_SYNCHRONIZED_CLOCK:
                total_uncertainty_ms = float(
                    manifest["synchronization"]["total_error_budget_ms"]
                )
                conservative_observed_ms = observed_ms + total_uncertainty_ms
            else:
                endpoint_uncertainty_ms = float(
                    manifest["measurement_setup"]["max_frame_annotation_uncertainty_ms"]
                )
                conservative_observed_ms = observed_ms + (2 * endpoint_uncertainty_ms)
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(conservative_observed_ms) and conservative_observed_ms > threshold_ms:
                formal_verdict = "insufficient"
                if manifest.get("measurement_method") == METHOD_SYNCHRONIZED_CLOCK:
                    reasons.append(
                        "p95 plus synchronization error budget exceeds the gate threshold"
                    )
                else:
                    reasons.append(
                        "p95 plus start/end annotation uncertainty exceeds the gate threshold"
                    )
    verdict = "insufficient" if errors else formal_verdict
    reasons.extend(errors)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest.get("run_id"),
        "kind": "latency_evidence_gate",
        "status": "complete",
        "derivation_status": "complete",
        "verdict": verdict,
        "latency_kind": manifest.get("latency_kind"),
        "transport": manifest.get("transport"),
        "measurement_method": manifest.get("measurement_method"),
        "internet_route": manifest.get("internet_route") if manifest.get("transport") == "internet" else None,
        "gate": {
            "profile": gate_profile,
            "can_close_performance_gate": verdict == "pass",
            "summary_verdict": summary_verdict,
            "threshold_ms": gate.get("threshold_ms"),
            "observed_ms": gate.get("observed_ms"),
            "observed_with_uncertainty_ms": conservative_observed_ms,
            "sample_count": gate.get("sample_count"),
            "min_sample_count": gate.get("min_sample_count"),
            "requires_external_hardware": True,
            "reasons": reasons,
        },
        "metrics": summary.get("metrics") if summary is not None else {},
        "source": {"manifest": str(manifest_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a formal external-camera latency evidence package."
    )
    parser.add_argument("manifest", type=Path, help="latency evidence manifest JSON")
    parser.add_argument(
        "--gate-profile",
        choices=FORMAL_LATENCY_PROFILES,
        required=True,
        help="formal latency gate profile to evaluate",
    )
    parser.add_argument("--output", type=Path, help="write report JSON to this path")
    return parser


def _write_report(report: dict[str, Any], output: Path | None) -> bool:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
        return True
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    except OSError as error:
        print(f"error: cannot write {output}: {error}", file=sys.stderr)
        return False
    return True


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_latency_evidence_report(
            manifest_path=args.manifest,
            gate_profile=args.gate_profile,
        )
    except LatencyEvidenceError as error:
        report = _failure_report(args.manifest, args.gate_profile, str(error))

    if not _write_report(report, args.output):
        return 2
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
