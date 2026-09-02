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
PROFILE_ARTIFACT_CONTENT_REQUIREMENTS = {
    "usb_connection": ("usb", "stream"),
    "lan_network_preflight": ("lan", "stream"),
    "internet_public_route_record": ("public", "route"),
    "input_actuation_record": ("physical", "input", "visible"),
    "synchronization_record": ("skew", "drift", "uncertainty", "budget"),
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
    "evidence_provenance",
    "camera",
    "recording",
    "samples",
    "device",
    "host",
    "build",
    "measurement_setup",
)

REQUIRED_TEXT_FIELDS = {
    "evidence_provenance": ("source", "collection_context", "operator_assertion"),
    "camera": ("manufacturer", "model", "mode", "shutter_mode"),
    "recording": ("raw_video", "recorded_at", "operator", "sha256", "container"),
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

REAL_DEVICE_CAPTURE_SOURCE = "real-device-capture"
SYNTHETIC_FIXTURE_SOURCE = "synthetic-fixture"
FIXTURE_PATH_PARTS = ("tools", "fixtures", "latency")
EXTERNAL_CAMERA_CONTAINERS = {
    ".mov": "mov",
    ".mp4": "mp4",
    ".m4v": "m4v",
}
KNOWN_SYNTHETIC_FIXTURE_SHA256 = {
    "32a49335961fadf449576f257d6d7b912a8c09ca5cb58e1450828e562592d967",
    "9e987eefb70a17590de3da63c50ea1732c142e34b5372ed4fe25c657553a6c99",
    "613180f782bb4693f040c48cfb23755229159965b53011c831f1081e7eaf2f6b",
    "6ad1942449f73bf4daad692c5034b478c1620415335977d5882aff876bc72c11",
    "d56a69969077d7fb6be3f9552a97e6e9ecfd7bdce00c80429543ef03a007c230",
    "03965cf7ffe46a7dd9fe18422883cf68a66f9861c06bc317e9f50a21b3db80eb",
}
SYNCHRONIZATION_BUDGET_COMPONENTS = (
    "before_skew_ms",
    "after_skew_ms",
    "max_drift_ms",
    "input_timestamp_uncertainty_ms",
    "result_timestamp_uncertainty_ms",
)
REAL_CAPTURE_PLACEHOLDER_TERMS = ("fixture", "synthetic", "placeholder")


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
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _describe_json_type(expected_type: str) -> str:
    if expected_type == "number":
        return "a JSON number"
    if expected_type == "integer":
        return "an integer"
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
    elif expected_type in ("integer", "number"):
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        number = float(value)
        if not math.isfinite(number):
            errors.append(f"{path} must be finite")
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and number < float(minimum):
            errors.append(f"{path} must be at least {minimum}")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, (int, float)) and number <= float(exclusive_minimum):
            errors.append(f"{path} must be greater than {exclusive_minimum}")
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


def _all_iso_chunk_offsets_in_media(
    data: bytes,
    content_start: int,
    entry_count: int,
    entry_width: int,
    mdat_ranges: Sequence[tuple[int, int]],
) -> bool:
    for index in range(entry_count):
        offset_start = content_start + 8 + (index * entry_width)
        chunk_offset = int.from_bytes(
            data[offset_start:offset_start + entry_width],
            "big",
        )
        if not any(start <= chunk_offset < end for start, end in mdat_ranges):
            return False
    return True


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
    total_mdat_bytes = sum(end - start for start, end in mdat_ranges)
    has_movie_header = False
    has_track_header = False
    has_video_handler = False
    has_video_samples = False
    has_fragmented_video_samples = False
    has_video_sample_description = False
    has_chunk_offset_into_media = False
    for moov_start, moov_end in moov_ranges:
        for box_type, content_start, content_end in _walk_iso_bmff_boxes(data, moov_start, moov_end):
            if box_type == b"mvhd":
                has_movie_header = True
            elif box_type == b"tkhd":
                has_track_header = True
            elif box_type == b"hdlr" and content_start + 12 <= content_end:
                has_video_handler = has_video_handler or data[content_start + 8:content_start + 12] == b"vide"
            elif box_type == b"stsd" and content_start + 16 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                sample_entry = data[content_start + 12:content_start + 16]
                has_video_sample_description = has_video_sample_description or (
                    entry_count > 0 and sample_entry in {b"avc1", b"avc3", b"hvc1", b"hev1"}
                )
            elif box_type == b"stsz" and content_start + 12 <= content_end:
                default_sample_size = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                sample_count = int.from_bytes(data[content_start + 8:content_start + 12], "big")
                has_sample_sizes = False
                total_sample_size = 0
                if sample_count > 0:
                    if default_sample_size > 0:
                        has_sample_sizes = True
                        total_sample_size = default_sample_size * sample_count
                    elif content_start + 12 + (sample_count * 4) <= content_end:
                        for index in range(sample_count):
                            sample_offset = content_start + 12 + (index * 4)
                            sample_size = int.from_bytes(
                                data[sample_offset:sample_offset + 4], "big"
                            )
                            total_sample_size += sample_size
                            has_sample_sizes = has_sample_sizes or sample_size > 0
                has_video_samples = has_video_samples or (
                    has_sample_sizes and 0 < total_sample_size <= total_mdat_bytes
                )
            elif box_type == b"stco" and content_start + 12 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                if entry_count > 0 and content_start + 8 + (entry_count * 4) <= content_end:
                    has_chunk_offset_into_media = has_chunk_offset_into_media or (
                        _all_iso_chunk_offsets_in_media(data, content_start, entry_count, 4, mdat_ranges)
                    )
            elif box_type == b"co64" and content_start + 16 <= content_end:
                entry_count = int.from_bytes(data[content_start + 4:content_start + 8], "big")
                if entry_count > 0 and content_start + 8 + (entry_count * 8) <= content_end:
                    has_chunk_offset_into_media = has_chunk_offset_into_media or (
                        _all_iso_chunk_offsets_in_media(data, content_start, entry_count, 8, mdat_ranges)
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
    return has_movie_header and has_track_header and has_video_handler and has_video_sample_description and (
        has_progressive_samples or has_fragmented_video_samples
    )


def _looks_like_camera_video(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".mov", ".m4v"}:
        return _looks_like_iso_bmff_video(data)
    return False


def _contains_fixture_path(path: Path) -> bool:
    normalized = tuple(path.resolve().parts)
    width = len(FIXTURE_PATH_PARTS)
    return any(
        normalized[index:index + width] == FIXTURE_PATH_PARTS
        for index in range(0, len(normalized) - width + 1)
    )


def _declared_number(
    value: Any,
    field: str,
    errors: list[str],
    *,
    minimum: float | None = None,
    exclusive_minimum: float | None = None,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{field} must be a finite number")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{field} must be finite")
        return None
    if minimum is not None and number < minimum:
        errors.append(f"{field} must be at least {minimum:g}")
    if exclusive_minimum is not None and number <= exclusive_minimum:
        errors.append(f"{field} must be greater than {exclusive_minimum:g}")
    return number


def _declared_integer(
    value: Any,
    field: str,
    errors: list[str],
    *,
    minimum: int | None = None,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field} must be an integer")
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{field} must be at least {minimum}")
    return value


def _validate_evidence_provenance(manifest_path: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    provenance = manifest.get("evidence_provenance")
    if not isinstance(provenance, dict):
        return errors
    source = provenance.get("source")
    if source not in (REAL_DEVICE_CAPTURE_SOURCE, SYNTHETIC_FIXTURE_SOURCE):
        errors.append(
            "evidence_provenance.source must be real-device-capture or synthetic-fixture"
        )
        return errors
    if source != REAL_DEVICE_CAPTURE_SOURCE:
        errors.append(
            "synthetic latency fixtures cannot close external latency gates; "
            "collect a real-device-capture package instead"
        )
    elif _contains_fixture_path(manifest_path):
        errors.append(
            "latency manifests under tools/fixtures/latency cannot close external latency gates"
        )
    return errors


def _validate_known_fixture_digests(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    candidate_sections: list[dict[str, Any]] = []
    for section_name in ("recording", "samples"):
        section = manifest.get(section_name)
        if isinstance(section, dict):
            candidate_sections.append(section)
    gate_artifacts = manifest.get("gate_artifacts")
    if isinstance(gate_artifacts, dict):
        candidate_sections.extend(
            value for value in gate_artifacts.values() if isinstance(value, dict)
        )
    for section in candidate_sections:
        digest = section.get("sha256")
        if isinstance(digest, str) and digest.lower() in KNOWN_SYNTHETIC_FIXTURE_SHA256:
            errors.append(
                "known repository latency fixture artifacts cannot close external latency gates"
            )
            break
    return errors


def _iter_manifest_text_fields(value: Any, prefix: str = "manifest"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_manifest_text_fields(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            yield from _iter_manifest_text_fields(child, f"{prefix}[{index}]")
    elif isinstance(value, str):
        yield prefix, value


def _validate_real_capture_placeholders(manifest: dict[str, Any]) -> list[str]:
    provenance = manifest.get("evidence_provenance")
    if not isinstance(provenance, dict) or provenance.get("source") != REAL_DEVICE_CAPTURE_SOURCE:
        return []
    for field, value in _iter_manifest_text_fields(manifest):
        normalized = value.lower()
        for term in REAL_CAPTURE_PLACEHOLDER_TERMS:
            if term in normalized:
                return [
                    f"{field} contains placeholder term {term!r}; real-device-capture "
                    "latency evidence must use concrete run metadata"
                ]
    return []


def _validate_artifact_content(
    field: str, path: Path | None, errors: list[str]
) -> None:
    artifact_key = field.split(".", 2)[1] if field.startswith("gate_artifacts.") else field
    required_tokens = PROFILE_ARTIFACT_CONTENT_REQUIREMENTS.get(artifact_key)
    if required_tokens is None or path is None or not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        errors.append(f"{field}.file must be UTF-8 text evidence")
        return
    except OSError as error:
        errors.append(f"cannot read {path}: {error}")
        return
    normalized = text.lower()
    missing = [token for token in required_tokens if token not in normalized]
    if missing:
        errors.append(
            f"{field}.file must describe {artifact_key.replace('_', ' ')} evidence "
            f"including: {', '.join(missing)}"
        )


def _validate_raw_camera_package_metadata(
    manifest: dict[str, Any], raw_video: Path | None
) -> list[str]:
    errors: list[str] = []
    if manifest.get("measurement_method") != METHOD_EXTERNAL_CAMERA:
        return errors
    recording = manifest.get("recording") if isinstance(manifest.get("recording"), dict) else {}
    camera = manifest.get("camera") if isinstance(manifest.get("camera"), dict) else {}
    declared_container = recording.get("container")
    if raw_video is not None:
        expected_container = EXTERNAL_CAMERA_CONTAINERS.get(raw_video.suffix.lower())
        if expected_container is None:
            errors.append(
                "recording.raw_video must use a supported external-camera container extension"
            )
        elif declared_container != expected_container:
            errors.append(
                "recording.container must match the raw video file extension"
            )
    if raw_video is not None and raw_video.is_file():
        declared_size = _declared_integer(
            recording.get("file_size_bytes"),
            "recording.file_size_bytes",
            errors,
            minimum=1,
        )
        if declared_size is not None and declared_size != raw_video.stat().st_size:
            errors.append("recording.file_size_bytes must match recording.raw_video size")
    else:
        _declared_integer(
            recording.get("file_size_bytes"),
            "recording.file_size_bytes",
            errors,
            minimum=1,
        )
    frame_count = _declared_integer(
        recording.get("frame_count"),
        "recording.frame_count",
        errors,
        minimum=1,
    )
    duration_ms = _declared_number(
        recording.get("duration_ms"),
        "recording.duration_ms",
        errors,
        exclusive_minimum=0,
    )
    frame_rate = _declared_number(
        camera.get("frame_rate_fps"),
        "camera.frame_rate_fps",
        errors,
        minimum=120,
    )
    if frame_count is not None and duration_ms is not None and frame_rate is not None:
        expected_duration_ms = frame_count * 1000.0 / frame_rate
        allowed_delta_ms = max(1000.0 / frame_rate, 1.0)
        if abs(duration_ms - expected_duration_ms) > allowed_delta_ms:
            errors.append(
                "recording.duration_ms must match recording.frame_count and "
                "camera.frame_rate_fps within one frame"
            )
    return errors


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
            _declared_number(
                uncertainty,
                "measurement_setup.max_frame_annotation_uncertainty_ms",
                errors,
                minimum=0,
            )
    elif is_synchronized_clock:
        if setup.get("clock_domain") != "synchronized-host-device-clocks":
            errors.append("measurement_setup.clock_domain must be synchronized-host-device-clocks")
        if manifest.get("latency_kind") != "input":
            errors.append("synchronized-clock measurement_method requires latency_kind input")
        sync = manifest.get("synchronization") if isinstance(manifest.get("synchronization"), dict) else {}
        sync_components: dict[str, float] = {}
        for field in SYNCHRONIZATION_BUDGET_COMPONENTS:
            number = _declared_number(
                sync.get(field),
                f"synchronization.{field}",
                errors,
                minimum=0,
            )
            if number is not None and number >= 0:
                sync_components[field] = number
        budget_ms = _declared_number(
            sync.get("total_error_budget_ms"),
            "synchronization.total_error_budget_ms",
            errors,
            minimum=0,
        )
        if budget_ms is not None and budget_ms >= 0:
            if budget_ms >= 5:
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
                if (
                    len(sync_components) == len(SYNCHRONIZATION_BUDGET_COMPONENTS)
                    and sum(sync_components.values()) > budget_ms
                ):
                    errors.append(
                        "synchronization error-budget components must sum to less than or equal to "
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
    for field, path in references.items():
        if field.startswith("gate_artifacts."):
            _validate_artifact_content(field.rsplit(".", 1)[0], path, errors)
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
    recording = manifest.get("recording") if isinstance(manifest.get("recording"), dict) else {}
    annotation_method = samples.get("annotation_method")
    try:
        declared_frame_rate = float(camera.get("frame_rate_fps"))
    except (TypeError, ValueError):
        declared_frame_rate = math.nan
    try:
        declared_frame_count = float(recording.get("frame_count"))
    except (TypeError, ValueError):
        declared_frame_count = math.nan

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
                start_frame = float(row["start_frame"])
                end_frame = float(row["end_frame"])
            except (TypeError, ValueError):
                continue
            if (
                math.isfinite(declared_frame_rate)
                and math.isfinite(sample_frame_rate)
                and not math.isclose(sample_frame_rate, declared_frame_rate, rel_tol=0, abs_tol=1e-6)
            ):
                errors.append(f"sample {index}: camera_fps must match camera.frame_rate_fps")
            if math.isfinite(declared_frame_count) and end_frame >= declared_frame_count:
                errors.append(
                    f"sample {index}: end_frame must be within recording.frame_count"
                )
            if start_frame < 0 or end_frame < 0:
                errors.append(f"sample {index}: frame indexes must not be negative")
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
    errors.extend(_validate_evidence_provenance(manifest_path, manifest))
    errors.extend(_validate_known_fixture_digests(manifest))
    errors.extend(_validate_real_capture_placeholders(manifest))
    errors.extend(_validate_required_metadata(manifest))
    errors.extend(_validate_internet_route(manifest, gate_profile))
    reference_errors, references = _validate_referenced_files(manifest_path, manifest, gate_profile)
    errors.extend(reference_errors)
    errors.extend(
        _validate_raw_camera_package_metadata(
            manifest, references.get("recording.raw_video")
        )
    )

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
