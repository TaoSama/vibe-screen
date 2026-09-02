"""Create a formal latency evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import platform
import shlex
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INTERNET_GLASS_TO_GLASS_SUB150,
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_PROFILES,
    GATE_USB_GLASS_TO_GLASS_SUB50,
    KIND_GLASS_TO_GLASS,
    KIND_INPUT,
    METHOD_EXTERNAL_CAMERA,
    METHOD_SYNCHRONIZED_CLOCK,
    TRANSPORT_INTERNET,
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
    GATE_INTERNET_GLASS_TO_GLASS_SUB150: "internet_public_route_record",
    GATE_INPUT_P95_SUB50: "input_actuation_record",
}
REAL_DEVICE_CAPTURE_SOURCE = "real-device-capture"
SYNTHETIC_FIXTURE_SOURCE = "synthetic-fixture"
EVIDENCE_PROVENANCE_SOURCES = (REAL_DEVICE_CAPTURE_SOURCE, SYNTHETIC_FIXTURE_SOURCE)
EXTERNAL_CAMERA_CONTAINERS = {
    ".mov": "mov",
    ".mp4": "mp4",
    ".m4v": "m4v",
}
SYNCHRONIZATION_BUDGET_COMPONENTS = (
    "before_skew_ms",
    "after_skew_ms",
    "max_drift_ms",
    "input_timestamp_uncertainty_ms",
    "result_timestamp_uncertainty_ms",
)


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


def _external_camera_container(path: Path) -> str:
    container = EXTERNAL_CAMERA_CONTAINERS.get(path.suffix.lower())
    if container is None:
        raise LatencyManifestError(
            "raw video must use a supported extension: .mov, .mp4, or .m4v"
        )
    return container


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


def _ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


def _resolve_hostname_ips(hostname: str) -> set[str]:
    resolved: set[str] = set()
    for family, _socktype, _proto, _canonical, sockaddr in socket.getaddrinfo(
        hostname.strip().rstrip("."),
        None,
        type=socket.SOCK_STREAM,
    ):
        if family not in (socket.AF_INET, socket.AF_INET6) or not sockaddr:
            continue
        address = _ip_address(str(sockaddr[0]).split("%", 1)[0])
        if address is not None:
            resolved.add(str(address))
    return resolved


def _resolved_turn_ip(public_hostname: str, supplied_resolved_ip: str | None) -> str:
    hostname_address = _ip_address(public_hostname)
    if hostname_address is not None:
        if not hostname_address.is_global:
            raise LatencyManifestError(
                "internet_route.turn_deployment.public_hostname must be a global IP "
                "or resolve to a global endpoint"
            )
        if supplied_resolved_ip is not None:
            supplied_address = _ip_address(
                _required_text(
                    supplied_resolved_ip,
                    "internet_route.turn_deployment.resolved_ip",
                )
            )
            if supplied_address != hostname_address:
                raise LatencyManifestError(
                    "internet_route.turn_deployment.resolved_ip must match the literal "
                    "TURN public_hostname address"
                )
        return str(hostname_address)

    try:
        resolved_addresses = _resolve_hostname_ips(public_hostname)
    except OSError as error:
        raise LatencyManifestError(
            f"internet_route.turn_deployment.public_hostname must resolve: {error}"
        ) from error
    if not resolved_addresses:
        raise LatencyManifestError(
            "internet_route.turn_deployment.public_hostname must resolve to an IP address"
        )
    non_global = []
    for address in resolved_addresses:
        parsed = _ip_address(address)
        if parsed is None or not parsed.is_global:
            non_global.append(address)
    if non_global:
        raise LatencyManifestError(
            "internet_route.turn_deployment.public_hostname must resolve only to "
            "global IP addresses"
        )
    if supplied_resolved_ip is None:
        return sorted(resolved_addresses)[0]
    supplied_address = _ip_address(
        _required_text(supplied_resolved_ip, "internet_route.turn_deployment.resolved_ip")
    )
    if supplied_address is None or not supplied_address.is_global:
        raise LatencyManifestError(
            "internet_route.turn_deployment.resolved_ip must be a global IP address"
        )
    if str(supplied_address) not in resolved_addresses:
        raise LatencyManifestError(
            "internet_route.turn_deployment.resolved_ip must match a retained DNS "
            "resolution for the TURN public_hostname"
        )
    return str(supplied_address)


def _normalized_internet_route(internet_route: dict[str, Any]) -> dict[str, Any]:
    route = dict(internet_route)
    raw_turn = route.get("turn_deployment")
    if not isinstance(raw_turn, dict):
        raise LatencyManifestError("internet_route.turn_deployment must be an object")
    turn = dict(raw_turn)
    public_hostname = _required_text(
        turn.get("public_hostname"), "internet_route.turn_deployment.public_hostname"
    )
    supplied_resolved_ip = turn.get("resolved_ip")
    if supplied_resolved_ip is not None and not isinstance(supplied_resolved_ip, str):
        raise LatencyManifestError("internet_route.turn_deployment.resolved_ip must be a string")
    turn["public_hostname"] = public_hostname
    turn["resolved_ip"] = _resolved_turn_ip(public_hostname, supplied_resolved_ip)
    route["turn_deployment"] = turn
    return route


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


def _positive_finite_number(value: float | None, field: str) -> float:
    number = _required_finite_number(value, field)
    if number <= 0:
        raise LatencyManifestError(f"{field} must be greater than zero")
    return number


def _positive_integer(value: int | None, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LatencyManifestError(f"{field} must be an integer")
    if value <= 0:
        raise LatencyManifestError(f"{field} must be greater than zero")
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
    evidence_provenance: dict[str, str] | None = None,
    measurement_method: str = METHOD_EXTERNAL_CAMERA,
    recording_frame_count: int | None = None,
    recording_duration_ms: float | None = None,
    raw_video: Path | None = None,
    camera: dict[str, Any] | None = None,
    recording_operator: str | None = None,
    synchronization: dict[str, Any] | None = None,
    gate_artifact: Path | None = None,
    gate_artifact_description: str | None = None,
    synchronization_artifact: Path | None = None,
    synchronization_artifact_description: str | None = None,
    internet_route: dict[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build a manifest matching tools/schemas/latency-evidence.schema.json."""
    if measurement_method not in MEASUREMENT_METHODS:
        raise LatencyManifestError(f"unsupported measurement method: {measurement_method}")
    _validate_profile(latency_kind, transport, gate_profile)
    if latency_kind == KIND_GLASS_TO_GLASS and measurement_method != METHOD_EXTERNAL_CAMERA:
        raise LatencyManifestError(
            "glass-to-glass latency requires external-camera measurement"
        )
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
    provenance = evidence_provenance or {
        "source": REAL_DEVICE_CAPTURE_SOURCE,
        "collection_context": "operator-collected latency evidence package",
        "operator_assertion": (
            "This package was collected from a real device run with retained artifacts."
        ),
    }
    if provenance.get("source") not in EVIDENCE_PROVENANCE_SOURCES:
        raise LatencyManifestError(
            "evidence_provenance.source must be real-device-capture or synthetic-fixture"
        )
    for field in ("collection_context", "operator_assertion"):
        if not isinstance(provenance.get(field), str) or not provenance[field].strip():
            raise LatencyManifestError(f"evidence_provenance.{field} must not be empty")

    samples_relative = _package_relative_path(samples, evidence_dir, "samples file")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": _non_empty(run_id, "run_id"),
        "latency_kind": latency_kind,
        "transport": transport,
        "measurement_method": measurement_method,
        "gate_profile": gate_profile,
        "evidence_provenance": {
            "source": str(provenance["source"]),
            "collection_context": _non_empty(
                str(provenance["collection_context"]),
                "evidence_provenance.collection_context",
            ),
            "operator_assertion": _non_empty(
                str(provenance["operator_assertion"]),
                "evidence_provenance.operator_assertion",
            ),
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
        raw_video_path = evidence_dir.resolve() / raw_video_relative
        manifest["camera"] = camera
        manifest["recording"] = {
            "raw_video": raw_video_relative,
            "recorded_at": recorded_at
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "operator": _non_empty(recording_operator, "recording.operator"),
            "sha256": _sha256(raw_video_path),
            "container": _external_camera_container(raw_video_path),
            "file_size_bytes": raw_video_path.stat().st_size,
            "frame_count": _positive_integer(
                recording_frame_count, "recording.frame_count"
            ),
            "duration_ms": _positive_finite_number(
                recording_duration_ms, "recording.duration_ms"
            ),
        }
    else:
        if synchronization is None:
            raise LatencyManifestError("synchronization metadata is required for synchronized-clock")
        if synchronization_artifact is None:
            raise LatencyManifestError(
                "synchronization artifact is required for synchronized-clock"
            )
        if synchronization_artifact_description is None:
            raise LatencyManifestError("synchronization artifact description is required")
        manifest["synchronization"] = synchronization
        manifest["gate_artifacts"]["synchronization_record"] = _artifact_reference(
            synchronization_artifact,
            evidence_dir,
            "gate_artifacts.synchronization_record",
            synchronization_artifact_description,
        )
    if transport == TRANSPORT_INTERNET:
        if internet_route is None:
            raise LatencyManifestError("internet_route metadata is required for internet transport")
        manifest["internet_route"] = _normalized_internet_route(internet_route)
    elif internet_route is not None:
        raise LatencyManifestError("internet_route metadata is only allowed for internet transport")
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
    parser.add_argument("--transport", choices=(TRANSPORT_USB, TRANSPORT_LAN, TRANSPORT_INTERNET), required=True)
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
    parser.add_argument("--recording-frame-count", type=int)
    parser.add_argument("--recording-duration-ms", type=float)
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
    parser.add_argument("--input-timestamp-uncertainty-ms", type=float)
    parser.add_argument("--result-timestamp-uncertainty-ms", type=float)
    parser.add_argument("--total-error-budget-ms", type=float)
    parser.add_argument("--input-timestamp-method")
    parser.add_argument("--result-timestamp-method")
    parser.add_argument("--gate-artifact", type=Path, required=True)
    parser.add_argument("--gate-artifact-description", required=True)
    parser.add_argument(
        "--synchronization-artifact",
        type=Path,
        help="retained synchronization proof file; required for --measurement-method synchronized-clock",
    )
    parser.add_argument(
        "--synchronization-artifact-description",
        help="description of the synchronization proof; required for --measurement-method synchronized-clock",
    )
    parser.add_argument(
        "--internet-route",
        choices=("direct-public-internet", "forced-public-turn"),
        help="selected public Internet route for internet latency evidence",
    )
    parser.add_argument("--turn-provider")
    parser.add_argument("--turn-region")
    parser.add_argument("--turn-public-hostname")
    parser.add_argument("--turn-resolved-ip")
    parser.add_argument("--turn-tls")
    parser.add_argument("--turn-credential-source")
    parser.add_argument("--remote-peer-operator")
    parser.add_argument("--remote-peer-network")
    parser.add_argument("--remote-peer-public-ip-asn")
    parser.add_argument("--remote-peer-location")
    parser.add_argument("--local-candidate-type")
    parser.add_argument("--remote-candidate-type")
    parser.add_argument("--relay-protocol")
    parser.add_argument("--host-network")
    parser.add_argument("--device-network")
    private_network_group = parser.add_mutually_exclusive_group()
    private_network_group.add_argument(
        "--same-private-network",
        action="store_true",
        default=None,
        help="record that peers were on the same private network; this blocks Internet gate closure",
    )
    private_network_group.add_argument(
        "--different-private-network",
        action="store_false",
        dest="same_private_network",
        help="record that peers were not on the same private network",
    )
    parser.add_argument("--notes", required=True)
    parser.add_argument(
        "--evidence-source",
        choices=EVIDENCE_PROVENANCE_SOURCES,
        default=REAL_DEVICE_CAPTURE_SOURCE,
        help=(
            "real-device-capture can close a gate when all checks pass; "
            "synthetic-fixture is for tests and always remains insufficient"
        ),
    )
    parser.add_argument(
        "--collection-context",
        help="where/how this latency package was collected",
    )
    parser.add_argument(
        "--operator-assertion",
        help="operator statement that the package is real evidence or a synthetic fixture",
    )
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
        recording_frame_count = _positive_integer(
            args.recording_frame_count, "recording.frame_count"
        )
        recording_duration_ms = _positive_finite_number(
            args.recording_duration_ms, "recording.duration_ms"
        )
        measurement_setup["clock_domain"] = CLOCK_DOMAIN_EXTERNAL_CAMERA
        measurement_setup["max_frame_annotation_uncertainty_ms"] = annotation_uncertainty_ms
        synchronization = None
    else:
        recording_frame_count = None
        recording_duration_ms = None
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
            "input_timestamp_uncertainty_ms": _non_negative_finite_number(
                args.input_timestamp_uncertainty_ms,
                "synchronization.input_timestamp_uncertainty_ms",
            ),
            "result_timestamp_uncertainty_ms": _non_negative_finite_number(
                args.result_timestamp_uncertainty_ms,
                "synchronization.result_timestamp_uncertainty_ms",
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
        component_sum = sum(
            float(synchronization[field]) for field in SYNCHRONIZATION_BUDGET_COMPONENTS
        )
        if component_sum > synchronization["total_error_budget_ms"]:
            raise LatencyManifestError(
                "synchronization error-budget components must fit total_error_budget_ms"
            )
        camera = None
        measurement_setup["clock_domain"] = CLOCK_DOMAIN_SYNCHRONIZED_CLOCK

    internet_route: dict[str, Any] | None = None
    if args.transport == TRANSPORT_INTERNET:
        if args.same_private_network is None:
            raise LatencyManifestError(
                "internet_route.network_topology.same_private_network must be explicitly recorded"
            )
        internet_route = {
            "route": _required_text(args.internet_route, "internet_route.route"),
            "turn_deployment": {
                "provider": _required_text(args.turn_provider, "internet_route.turn_deployment.provider"),
                "region": _required_text(args.turn_region, "internet_route.turn_deployment.region"),
                "public_hostname": _required_text(
                    args.turn_public_hostname, "internet_route.turn_deployment.public_hostname"
                ),
                **({"resolved_ip": args.turn_resolved_ip} if args.turn_resolved_ip is not None else {}),
                "tls": _required_text(args.turn_tls, "internet_route.turn_deployment.tls"),
                "credential_source": _required_text(
                    args.turn_credential_source, "internet_route.turn_deployment.credential_source"
                ),
            },
            "remote_peer": {
                "operator": _required_text(args.remote_peer_operator, "internet_route.remote_peer.operator"),
                "network": _required_text(args.remote_peer_network, "internet_route.remote_peer.network"),
                "public_ip_asn": _required_text(
                    args.remote_peer_public_ip_asn, "internet_route.remote_peer.public_ip_asn"
                ),
                "location": _required_text(args.remote_peer_location, "internet_route.remote_peer.location"),
            },
            "candidate_pair": {
                "local_candidate_type": _required_text(
                    args.local_candidate_type, "internet_route.candidate_pair.local_candidate_type"
                ),
                "remote_candidate_type": _required_text(
                    args.remote_candidate_type, "internet_route.candidate_pair.remote_candidate_type"
                ),
                "relay_protocol": _required_text(
                    args.relay_protocol, "internet_route.candidate_pair.relay_protocol"
                ),
            },
            "network_topology": {
                "host_network": _required_text(args.host_network, "internet_route.network_topology.host_network"),
                "device_network": _required_text(
                    args.device_network, "internet_route.network_topology.device_network"
                ),
                "same_private_network": args.same_private_network,
            },
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
        evidence_provenance={
            "source": args.evidence_source,
            "collection_context": args.collection_context
            or (
                "synthetic latency checker fixture"
                if args.evidence_source == SYNTHETIC_FIXTURE_SOURCE
                else "operator-collected latency evidence package"
            ),
            "operator_assertion": args.operator_assertion
            or (
                "This package is a synthetic fixture and must not close a latency gate."
                if args.evidence_source == SYNTHETIC_FIXTURE_SOURCE
                else "This package was collected from a real device run with retained artifacts."
            ),
        },
        measurement_method=args.measurement_method,
        recording_frame_count=recording_frame_count,
        recording_duration_ms=recording_duration_ms,
        synchronization=synchronization,
        gate_artifact=args.gate_artifact,
        gate_artifact_description=args.gate_artifact_description,
        synchronization_artifact=args.synchronization_artifact,
        synchronization_artifact_description=args.synchronization_artifact_description,
        internet_route=internet_route,
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
