#!/usr/bin/env python3
"""Validate an external-camera latency evidence package.

The latency summarizer accepts raw sample rows so offline fixtures can exercise
pass/fail profiles. This checker is stricter: it requires provenance for the
camera, raw recording, sample annotations, device/build, and trigger method
before a latency profile can pass.
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

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must be {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(str(item) for item in schema["enum"])
        errors.append(f"{path} must be one of: {allowed}")

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        errors.append(f"{path} must be {_describe_json_type(expected_type)}")
        return errors

    if expected_type == "object":
        assert isinstance(value, dict)
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


def _validate_required_metadata(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("measurement_method") != METHOD_EXTERNAL_CAMERA:
        errors.append("measurement_method must be external-camera")

    for section in REQUIRED_TOP_LEVEL_OBJECTS:
        section_document = _require_object(manifest, section, errors)
        for field in REQUIRED_TEXT_FIELDS[section]:
            _as_non_empty_text(section_document.get(field), f"{section}.{field}", errors)

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

    setup = manifest.get("measurement_setup") if isinstance(manifest.get("measurement_setup"), dict) else {}
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
        if local_type in ("host", "srflx") and remote_type in ("host", "srflx"):
            pass
        else:
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
    if summary.get("measurement_method") != METHOD_EXTERNAL_CAMERA:
        errors.append("summary.measurement_method must be external-camera")
    if summary.get("latency_kind") != profile["kind"]:
        errors.append(f"summary.latency_kind must be {profile['kind']}")
    expected_transport = profile["transport"]
    if expected_transport is not None and summary.get("transport") != expected_transport:
        errors.append(f"summary.transport must be {expected_transport}")

    return errors


def _validate_referenced_files(
    manifest_path: Path,
    manifest: dict[str, Any],
) -> tuple[list[str], dict[str, Path | None]]:
    errors: list[str] = []
    recording = manifest.get("recording") if isinstance(manifest.get("recording"), dict) else {}
    samples = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    raw_references = {
        "recording.raw_video": recording.get("raw_video"),
        "samples.file": samples.get("file"),
    }
    references: dict[str, Path | None] = {}
    for field, raw_path in raw_references.items():
        path = _resolve_package_path(manifest_path, raw_path, field, errors)
        references[field] = path
        if path is not None and not path.is_file():
            errors.append(f"{field} does not exist: {path}")

    digest_bindings = (
        ("recording.sha256", recording.get("sha256"), references["recording.raw_video"]),
        ("samples.sha256", samples.get("sha256"), references["samples.file"]),
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
    reference_errors, references = _validate_referenced_files(manifest_path, manifest)
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
            endpoint_uncertainty_ms = float(
                manifest["measurement_setup"]["max_frame_annotation_uncertainty_ms"]
            )
            observed_ms = float(gate["observed_ms"])
            threshold_ms = float(gate["threshold_ms"])
            conservative_observed_ms = observed_ms + (2 * endpoint_uncertainty_ms)
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(conservative_observed_ms) and conservative_observed_ms > threshold_ms:
                formal_verdict = "insufficient"
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
