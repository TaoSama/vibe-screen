#!/usr/bin/env python3
"""Validate an external-camera latency evidence package.

The latency summarizer accepts raw sample rows so offline fixtures can exercise
pass/fail profiles. This checker is stricter: it requires provenance for the
camera, raw recording, sample annotations, device/build, and trigger method
before a latency profile can pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
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
    GATE_INPUT_P95_SUB50,
)

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
    "samples": ("file", "format", "annotation_method", "annotator"),
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
    except json.JSONDecodeError as error:
        raise LatencyEvidenceError(f"invalid JSON in {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise LatencyEvidenceError(f"{label} must be a JSON object")
    return document


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


def _resolve_manifest_path(manifest_path: Path, raw_path: str | None) -> Path | None:
    if raw_path is None:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return manifest_path.parent / path


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
    try:
        frame_rate = float(camera.get("frame_rate_fps"))
        if frame_rate < 120:
            errors.append("camera.frame_rate_fps must be at least 120 for high-frame-rate evidence")
    except (TypeError, ValueError):
        errors.append("camera.frame_rate_fps must be numeric")

    setup = manifest.get("measurement_setup") if isinstance(manifest.get("measurement_setup"), dict) else {}
    if setup.get("clock_domain") != "single-external-camera-timebase":
        errors.append("measurement_setup.clock_domain must be single-external-camera-timebase")
    uncertainty = setup.get("max_frame_annotation_uncertainty_ms")
    if uncertainty in (None, ""):
        errors.append("measurement_setup.max_frame_annotation_uncertainty_ms is required")
    else:
        try:
            if float(uncertainty) < 0:
                errors.append("measurement_setup.max_frame_annotation_uncertainty_ms must not be negative")
        except (TypeError, ValueError):
            errors.append("measurement_setup.max_frame_annotation_uncertainty_ms must be numeric")

    return errors


def _validate_manifest_matches_summary(
    manifest: dict[str, Any], summary: dict[str, Any], gate_profile: str
) -> list[str]:
    errors: list[str] = []
    profile = GATE_PROFILES[gate_profile]

    if manifest.get("run_id") != summary.get("run_id"):
        errors.append("manifest.run_id must match summary.run_id")
    if manifest.get("latency_kind") != summary.get("latency_kind"):
        errors.append("manifest.latency_kind must match summary.latency_kind")
    if manifest.get("transport") != summary.get("transport"):
        errors.append("manifest.transport must match summary.transport")
    if manifest.get("measurement_method") != summary.get("measurement_method"):
        errors.append("manifest.measurement_method must match summary.measurement_method")
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


def _validate_referenced_files(manifest_path: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    recording = manifest.get("recording") if isinstance(manifest.get("recording"), dict) else {}
    samples = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    references = {
        "recording.raw_video": recording.get("raw_video"),
        "samples.file": samples.get("file"),
    }
    for field, raw_path in references.items():
        text_path = _as_non_empty_text(raw_path, field, errors)
        path = _resolve_manifest_path(manifest_path, text_path)
        if path is not None and not path.is_file():
            errors.append(f"{field} does not exist: {path}")
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
    errors = _validate_required_metadata(manifest)
    errors.extend(_validate_referenced_files(manifest_path, manifest))

    samples_section = manifest.get("samples") if isinstance(manifest.get("samples"), dict) else {}
    sample_format = samples_section.get("format")
    sample_path_text = samples_section.get("file") if isinstance(samples_section.get("file"), str) else None
    sample_path = _resolve_manifest_path(manifest_path, sample_path_text)
    summary: dict[str, Any] | None = None
    if sample_path is not None and sample_path.is_file() and sample_format in ("csv", "json"):
        try:
            with sample_path.open("r", encoding="utf-8", newline="") as stream:
                rows = load_samples(stream, sample_format)
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
    profile_verdict = summary.get("verdict") if summary is not None else "insufficient"
    verdict = "insufficient" if errors else str(profile_verdict)
    reasons = list(gate.get("reasons", [])) if isinstance(gate.get("reasons"), list) else []
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
            "summary_verdict": profile_verdict,
            "threshold_ms": gate.get("threshold_ms"),
            "observed_ms": gate.get("observed_ms"),
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
