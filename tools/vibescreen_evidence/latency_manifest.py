"""Create a formal external-camera latency evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_PROFILES,
    KIND_GLASS_TO_GLASS,
    KIND_INPUT,
    METHOD_EXTERNAL_CAMERA,
    TRANSPORT_LAN,
    TRANSPORT_USB,
)

ANNOTATION_DIRECT_LATENCY_MS = "direct-latency-ms"
ANNOTATION_MANUAL_FRAME_COUNT = "manual-frame-count"
CLOCK_DOMAIN_EXTERNAL_CAMERA = "single-external-camera-timebase"


class LatencyManifestError(RuntimeError):
    """Raised when a latency manifest cannot be generated safely."""


def _run(command: Sequence[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LatencyManifestError(f"failed to run {shlex.join(command)}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise LatencyManifestError(
            f"{shlex.join(command)} exited with {result.returncode}: {detail}"
        )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise LatencyManifestError(f"cannot read {path}: {error}") from error
    return digest.hexdigest()


def _package_relative_path(path: Path, evidence_dir: Path, field: str) -> str:
    resolved = path.resolve()
    root = evidence_dir.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise LatencyManifestError(
            f"{field} must be inside the evidence directory: {resolved}"
        ) from error
    if not resolved.exists():
        raise LatencyManifestError(f"{field} does not exist: {resolved}")
    return relative.as_posix()


def _repository_revision(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo)


def _host_model() -> str:
    try:
        return _run(["sysctl", "-n", "hw.model"])
    except LatencyManifestError:
        return platform.machine() or "unknown"


def _macos_version() -> str:
    version = platform.mac_ver()[0]
    return version or platform.platform()


def _load_device_info(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LatencyManifestError(f"cannot read device info {path}: {error}") from error
    if not isinstance(document, dict):
        raise LatencyManifestError(f"device info must be a JSON object: {path}")
    device = document.get("device")
    if not isinstance(device, dict):
        raise LatencyManifestError(
            f"device info must contain a device object: {path}"
        )
    return {
        "manufacturer": str(device.get("manufacturer") or ""),
        "model": str(device.get("model") or ""),
        "codename": str(device.get("device") or device.get("codename") or ""),
        "os_version": str(device.get("android_release") or device.get("os_version") or ""),
    }


def _non_empty(value: str, field: str) -> str:
    if not value.strip():
        raise LatencyManifestError(f"{field} must not be empty")
    return value


def _validate_profile(kind: str, transport: str, gate_profile: str) -> None:
    profile = GATE_PROFILES[gate_profile]
    if profile["kind"] != kind:
        raise LatencyManifestError(
            f"gate profile {gate_profile} requires latency kind {profile['kind']}"
        )
    expected_transport = profile["transport"]
    if expected_transport is not None and expected_transport != transport:
        raise LatencyManifestError(
            f"gate profile {gate_profile} requires transport {expected_transport}"
        )


def build_latency_manifest(
    *,
    evidence_dir: Path,
    raw_video: Path,
    samples: Path,
    run_id: str,
    latency_kind: str,
    transport: str,
    gate_profile: str,
    camera: dict[str, Any],
    recording_operator: str,
    samples_format: str,
    annotation_method: str,
    annotator: str,
    device: dict[str, str],
    host: dict[str, str],
    build: dict[str, str],
    measurement_setup: dict[str, Any],
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build a manifest matching tools/schemas/latency-evidence.schema.json."""
    _validate_profile(latency_kind, transport, gate_profile)
    raw_video_relative = _package_relative_path(raw_video, evidence_dir, "raw video")
    samples_relative = _package_relative_path(samples, evidence_dir, "samples file")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": _non_empty(run_id, "run_id"),
        "latency_kind": latency_kind,
        "transport": transport,
        "measurement_method": METHOD_EXTERNAL_CAMERA,
        "gate_profile": gate_profile,
        "camera": camera,
        "recording": {
            "raw_video": raw_video_relative,
            "recorded_at": recorded_at
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "operator": _non_empty(recording_operator, "recording.operator"),
            "sha256": _sha256(evidence_dir.resolve() / raw_video_relative),
        },
        "samples": {
            "file": samples_relative,
            "format": samples_format,
            "sha256": _sha256(evidence_dir.resolve() / samples_relative),
            "annotation_method": annotation_method,
            "annotator": _non_empty(annotator, "samples.annotator"),
        },
        "device": device,
        "host": host,
        "build": build,
        "measurement_setup": measurement_setup,
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("manifest.json"))
    parser.add_argument("--run-id")
    parser.add_argument("--latency-kind", choices=(KIND_GLASS_TO_GLASS, KIND_INPUT), required=True)
    parser.add_argument("--transport", choices=(TRANSPORT_USB, TRANSPORT_LAN), required=True)
    parser.add_argument("--gate-profile", choices=tuple(GATE_PROFILES), required=True)
    parser.add_argument("--raw-video", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--samples-format", choices=("csv", "json"), required=True)
    parser.add_argument(
        "--annotation-method",
        choices=(ANNOTATION_MANUAL_FRAME_COUNT, ANNOTATION_DIRECT_LATENCY_MS),
        required=True,
    )
    parser.add_argument("--camera-manufacturer", required=True)
    parser.add_argument("--camera-model", required=True)
    parser.add_argument("--camera-mode", required=True)
    parser.add_argument("--camera-frame-rate-fps", type=float, required=True)
    parser.add_argument("--camera-shutter-mode", required=True)
    parser.add_argument("--recorded-at")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--annotator", required=True)
    parser.add_argument("--device-info", type=Path)
    parser.add_argument("--device-manufacturer")
    parser.add_argument("--device-model")
    parser.add_argument("--device-codename")
    parser.add_argument("--device-os-version")
    parser.add_argument("--host-model")
    parser.add_argument("--macos-version")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--repository-revision")
    parser.add_argument("--host-artifact", required=True)
    parser.add_argument("--client-artifact", required=True)
    parser.add_argument("--stimulus", required=True)
    parser.add_argument("--start-event-definition", required=True)
    parser.add_argument("--end-event-definition", required=True)
    parser.add_argument("--lighting", required=True)
    parser.add_argument("--mounting", required=True)
    parser.add_argument("--max-frame-annotation-uncertainty-ms", type=float, required=True)
    parser.add_argument("--notes", required=True)
    return parser


def _device_from_args(args: argparse.Namespace) -> dict[str, str]:
    device = _load_device_info(args.device_info) if args.device_info else {}
    values = {
        "manufacturer": args.device_manufacturer or device.get("manufacturer", ""),
        "model": args.device_model or device.get("model", ""),
        "codename": args.device_codename or device.get("codename", ""),
        "os_version": args.device_os_version or device.get("os_version", ""),
    }
    return {field: _non_empty(value, f"device.{field}") for field, value in values.items()}


def manifest_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.camera_frame_rate_fps < 120:
        raise LatencyManifestError("camera.frame_rate_fps must be at least 120")
    if args.max_frame_annotation_uncertainty_ms < 0:
        raise LatencyManifestError(
            "measurement_setup.max_frame_annotation_uncertainty_ms must not be negative"
        )
    camera = {
        "manufacturer": _non_empty(args.camera_manufacturer, "camera.manufacturer"),
        "model": _non_empty(args.camera_model, "camera.model"),
        "mode": _non_empty(args.camera_mode, "camera.mode"),
        "frame_rate_fps": args.camera_frame_rate_fps,
        "shutter_mode": _non_empty(args.camera_shutter_mode, "camera.shutter_mode"),
    }
    host = {
        "model": _non_empty(args.host_model or _host_model(), "host.model"),
        "macos_version": _non_empty(
            args.macos_version or _macos_version(), "host.macos_version"
        ),
    }
    build = {
        "repository_revision": _non_empty(
            args.repository_revision or _repository_revision(args.repo),
            "build.repository_revision",
        ),
        "host_artifact": _non_empty(args.host_artifact, "build.host_artifact"),
        "client_artifact": _non_empty(args.client_artifact, "build.client_artifact"),
    }
    measurement_setup = {
        "stimulus": _non_empty(args.stimulus, "measurement_setup.stimulus"),
        "start_event_definition": _non_empty(
            args.start_event_definition, "measurement_setup.start_event_definition"
        ),
        "end_event_definition": _non_empty(
            args.end_event_definition, "measurement_setup.end_event_definition"
        ),
        "lighting": _non_empty(args.lighting, "measurement_setup.lighting"),
        "mounting": _non_empty(args.mounting, "measurement_setup.mounting"),
        "clock_domain": CLOCK_DOMAIN_EXTERNAL_CAMERA,
        "max_frame_annotation_uncertainty_ms": args.max_frame_annotation_uncertainty_ms,
        "notes": _non_empty(args.notes, "measurement_setup.notes"),
    }
    return build_latency_manifest(
        evidence_dir=args.evidence_dir,
        raw_video=args.raw_video,
        samples=args.samples,
        run_id=args.run_id or args.evidence_dir.name,
        latency_kind=args.latency_kind,
        transport=args.transport,
        gate_profile=args.gate_profile,
        camera=camera,
        recording_operator=args.operator,
        samples_format=args.samples_format,
        annotation_method=args.annotation_method,
        annotator=args.annotator,
        device=_device_from_args(args),
        host=host,
        build=build,
        measurement_setup=measurement_setup,
        recorded_at=args.recorded_at,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = args.output
        if not output.is_absolute():
            output = args.evidence_dir / output
        manifest = manifest_from_args(args)
        _write_json(output, manifest)
    except (LatencyManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
