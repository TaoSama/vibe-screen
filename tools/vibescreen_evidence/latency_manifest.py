"""Create a formal latency evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_PROFILES,
    GATE_USB_GLASS_TO_GLASS_SUB50,
    KIND_GLASS_TO_GLASS,
    KIND_INPUT,
    METHOD_EXTERNAL_CAMERA,
    METHOD_SYNCHRONIZED_CLOCK,
    TRANSPORT_LAN,
    TRANSPORT_USB,
)

ANNOTATION_DIRECT_LATENCY_MS = "direct-latency-ms"
ANNOTATION_MANUAL_FRAME_COUNT = "manual-frame-count"
CLOCK_DOMAIN_EXTERNAL_CAMERA = "single-external-camera-timebase"
CLOCK_DOMAIN_SYNCHRONIZED_CLOCK = "synchronized-host-device-clocks"
MEASUREMENT_METHODS = (METHOD_EXTERNAL_CAMERA, METHOD_SYNCHRONIZED_CLOCK)
PROFILE_ARTIFACT_FIELDS = {
    GATE_USB_GLASS_TO_GLASS_SUB50: "usb_connection",
    GATE_LAN_GLASS_TO_GLASS_SUB80: "lan_network_preflight",
    GATE_INPUT_P95_SUB50: "input_actuation_record",
}


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


def _artifact_reference(path: Path, evidence_dir: Path, field: str, description: str) -> dict[str, str]:
    relative = _package_relative_path(path, evidence_dir, field)
    return {
        "file": relative,
        "sha256": _sha256(evidence_dir.resolve() / relative),
        "description": _non_empty(description, f"{field}.description"),
    }


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


def _required_text(value: str | None, field: str) -> str:
    if value is None:
        raise LatencyManifestError(f"{field} is required")
    return _non_empty(value, field)


def _required_finite_number(value: float | None, field: str) -> float:
    if value is None:
        raise LatencyManifestError(f"{field} is required")
    if not math.isfinite(value):
        raise LatencyManifestError(f"{field} must be finite")
    return value


def _non_negative_finite_number(value: float | None, field: str) -> float:
    number = _required_finite_number(value, field)
    if number < 0:
        raise LatencyManifestError(f"{field} must not be negative")
    return number


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
    samples: Path,
    run_id: str,
    latency_kind: str,
    transport: str,
    gate_profile: str,
    samples_format: str,
    annotation_method: str,
    annotator: str,
    device: dict[str, str],
    host: dict[str, str],
    build: dict[str, str],
    measurement_setup: dict[str, Any],
    measurement_method: str = METHOD_EXTERNAL_CAMERA,
    raw_video: Path | None = None,
    camera: dict[str, Any] | None = None,
    recording_operator: str | None = None,
    synchronization: dict[str, Any] | None = None,
    gate_artifact: Path | None = None,
    gate_artifact_description: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build a manifest matching tools/schemas/latency-evidence.schema.json."""
    if measurement_method not in MEASUREMENT_METHODS:
        raise LatencyManifestError(f"unsupported measurement method: {measurement_method}")
    _validate_profile(latency_kind, transport, gate_profile)
    if measurement_method == METHOD_SYNCHRONIZED_CLOCK and latency_kind != KIND_INPUT:
        raise LatencyManifestError("synchronized-clock measurement_method requires latency_kind input")
    if measurement_method == METHOD_SYNCHRONIZED_CLOCK and annotation_method != ANNOTATION_DIRECT_LATENCY_MS:
        raise LatencyManifestError(
            "synchronized-clock measurement_method requires samples.annotation_method direct-latency-ms"
        )
    if gate_artifact is None:
        raise LatencyManifestError(
            f"gate artifact is required for {gate_profile}: {PROFILE_ARTIFACT_FIELDS[gate_profile]}"
        )
    if gate_artifact_description is None:
        raise LatencyManifestError("gate artifact description is required")

    samples_relative = _package_relative_path(samples, evidence_dir, "samples file")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": _non_empty(run_id, "run_id"),
        "latency_kind": latency_kind,
        "transport": transport,
        "measurement_method": measurement_method,
        "gate_profile": gate_profile,
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
        "gate_artifacts": {
            PROFILE_ARTIFACT_FIELDS[gate_profile]: _artifact_reference(
                gate_artifact,
                evidence_dir,
                f"gate_artifacts.{PROFILE_ARTIFACT_FIELDS[gate_profile]}",
                gate_artifact_description,
            )
        },
    }
    if measurement_method == METHOD_EXTERNAL_CAMERA:
        if raw_video is None:
            raise LatencyManifestError("raw video is required for external-camera")
        if camera is None:
            raise LatencyManifestError("camera metadata is required for external-camera")
        if recording_operator is None:
            raise LatencyManifestError("recording.operator is required for external-camera")
        raw_video_relative = _package_relative_path(raw_video, evidence_dir, "raw video")
        manifest["camera"] = camera
        manifest["recording"] = {
            "raw_video": raw_video_relative,
            "recorded_at": recorded_at
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "operator": _non_empty(recording_operator, "recording.operator"),
            "sha256": _sha256(evidence_dir.resolve() / raw_video_relative),
        }
    else:
        if synchronization is None:
            raise LatencyManifestError("synchronization metadata is required for synchronized-clock")
        manifest["synchronization"] = synchronization
    return manifest


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("manifest.json"))
    parser.add_argument("--run-id")
    parser.add_argument(
        "--measurement-method",
        choices=MEASUREMENT_METHODS,
        default=METHOD_EXTERNAL_CAMERA,
    )
    parser.add_argument("--latency-kind", choices=(KIND_GLASS_TO_GLASS, KIND_INPUT), required=True)
    parser.add_argument("--transport", choices=(TRANSPORT_USB, TRANSPORT_LAN), required=True)
    parser.add_argument("--gate-profile", choices=tuple(GATE_PROFILES), required=True)
    parser.add_argument("--raw-video", type=Path)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--samples-format", choices=("csv", "json"), required=True)
    parser.add_argument(
        "--annotation-method",
        choices=(ANNOTATION_MANUAL_FRAME_COUNT, ANNOTATION_DIRECT_LATENCY_MS),
        required=True,
    )
    parser.add_argument("--camera-manufacturer")
    parser.add_argument("--camera-model")
    parser.add_argument("--camera-mode")
    parser.add_argument("--camera-frame-rate-fps", type=float)
    parser.add_argument("--camera-shutter-mode")
    parser.add_argument("--recorded-at")
    parser.add_argument("--operator")
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
    parser.add_argument("--max-frame-annotation-uncertainty-ms", type=float)
    parser.add_argument("--host-clock-source")
    parser.add_argument("--device-clock-source")
    parser.add_argument("--sync-procedure")
    parser.add_argument("--before-skew-ms", type=float)
    parser.add_argument("--after-skew-ms", type=float)
    parser.add_argument("--max-drift-ms", type=float)
    parser.add_argument("--total-error-budget-ms", type=float)
    parser.add_argument("--input-timestamp-method")
    parser.add_argument("--result-timestamp-method")
    parser.add_argument("--gate-artifact", type=Path, required=True)
    parser.add_argument("--gate-artifact-description", required=True)
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
    is_external_camera = args.measurement_method == METHOD_EXTERNAL_CAMERA
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
    measurement_setup: dict[str, Any] = {
        "stimulus": _non_empty(args.stimulus, "measurement_setup.stimulus"),
        "start_event_definition": _non_empty(
            args.start_event_definition, "measurement_setup.start_event_definition"
        ),
        "end_event_definition": _non_empty(
            args.end_event_definition, "measurement_setup.end_event_definition"
        ),
        "lighting": _non_empty(args.lighting, "measurement_setup.lighting"),
        "mounting": _non_empty(args.mounting, "measurement_setup.mounting"),
        "notes": _non_empty(args.notes, "measurement_setup.notes"),
    }
    if is_external_camera:
        frame_rate_fps = _required_finite_number(
            args.camera_frame_rate_fps, "camera.frame_rate_fps"
        )
        if frame_rate_fps < 120:
            raise LatencyManifestError("camera.frame_rate_fps must be at least 120")
        annotation_uncertainty_ms = _non_negative_finite_number(
            args.max_frame_annotation_uncertainty_ms,
            "measurement_setup.max_frame_annotation_uncertainty_ms",
        )
        camera = {
            "manufacturer": _required_text(args.camera_manufacturer, "camera.manufacturer"),
            "model": _required_text(args.camera_model, "camera.model"),
            "mode": _required_text(args.camera_mode, "camera.mode"),
            "frame_rate_fps": frame_rate_fps,
            "shutter_mode": _required_text(args.camera_shutter_mode, "camera.shutter_mode"),
        }
        measurement_setup["clock_domain"] = CLOCK_DOMAIN_EXTERNAL_CAMERA
        measurement_setup["max_frame_annotation_uncertainty_ms"] = annotation_uncertainty_ms
        synchronization = None
    else:
        synchronization = {
            "host_clock_source": _required_text(
                args.host_clock_source, "synchronization.host_clock_source"
            ),
            "device_clock_source": _required_text(
                args.device_clock_source, "synchronization.device_clock_source"
            ),
            "sync_procedure": _required_text(
                args.sync_procedure, "synchronization.sync_procedure"
            ),
            "before_skew_ms": _non_negative_finite_number(
                args.before_skew_ms, "synchronization.before_skew_ms"
            ),
            "after_skew_ms": _non_negative_finite_number(
                args.after_skew_ms, "synchronization.after_skew_ms"
            ),
            "max_drift_ms": _non_negative_finite_number(
                args.max_drift_ms, "synchronization.max_drift_ms"
            ),
            "total_error_budget_ms": _non_negative_finite_number(
                args.total_error_budget_ms, "synchronization.total_error_budget_ms"
            ),
            "input_timestamp_method": _required_text(
                args.input_timestamp_method, "synchronization.input_timestamp_method"
            ),
            "result_timestamp_method": _required_text(
                args.result_timestamp_method, "synchronization.result_timestamp_method"
            ),
        }
        if synchronization["total_error_budget_ms"] >= 5:
            raise LatencyManifestError(
                "synchronization.total_error_budget_ms must be less than 5 ms"
            )
        component_sum = (
            synchronization["before_skew_ms"]
            + synchronization["after_skew_ms"]
            + synchronization["max_drift_ms"]
        )
        if component_sum > synchronization["total_error_budget_ms"]:
            raise LatencyManifestError(
                "synchronization skew and drift components must fit total_error_budget_ms"
            )
        camera = None
        measurement_setup["clock_domain"] = CLOCK_DOMAIN_SYNCHRONIZED_CLOCK

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
        measurement_method=args.measurement_method,
        synchronization=synchronization,
        gate_artifact=args.gate_artifact,
        gate_artifact_description=args.gate_artifact_description,
        recorded_at=args.recorded_at,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = args.output
        if not output.is_absolute():
            output = args.evidence_dir / output
        if output.resolve().parent != args.evidence_dir.resolve():
            raise LatencyManifestError(
                "output must be directly inside the evidence directory"
            )
        manifest = manifest_from_args(args)
        _write_json(output, manifest)
    except (LatencyManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
