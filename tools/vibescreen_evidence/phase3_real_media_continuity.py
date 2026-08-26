#!/usr/bin/env python3
"""Evaluate Phase 3 real-media continuity evidence from retained logs.

The evaluator is intentionally passive: it does not start the Host, touch ADB,
change macOS privacy settings, or claim the wider Phase 3 release gate. A
successful result only means the supplied artifacts show the narrow
ScreenCaptureKit/CGDisplayStream to Android MediaCodec continuity slice.

Exit codes are 0 for pass, 1 for blocked, 2 for runtime fail, and 3 for input
or invocation errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence, TextIO

from . import SCHEMA_VERSION


KIND = "phase3_real_media_continuity_preflight"
PASS = "pass"
FAIL = "fail"
BLOCKED = "blocked"
NETWORK_PATHS = frozenset(("public_internet", "local_direct", "local_forced_turn", "unknown"))
HOST_SIGNING = frozenset(("identity_signed", "ad_hoc", "unsigned", "unknown"))
SCREEN_RECORDING = frozenset(("granted", "blocked", "unknown"))

SYNTHETIC_MARKERS = (
    "synthetic Protocol v1",
    "synthetic_protocol_v1_device",
    "PHASE3_ANDROID_INTEROP",
    "VIBE-ANDROID-INTEROP",
    "VIBE-PRODUCT-E2E",
    "synthetic keyframe",
)
HOST_CAPTURE_STARTED_PATTERNS = (
    re.compile(r"SCStream capture started", re.IGNORECASE),
    re.compile(r"CGDisplayStream fallback started successfully", re.IGNORECASE),
)
HOST_CAPTURE_FIRST_FRAME_PATTERNS = (
    re.compile(r"First frame received from (ScreenCaptureKit|CGDisplayStream|display|window)", re.IGNORECASE),
)
HOST_VIDEOTOOLBOX_CONFIG_PATTERNS = (
    re.compile(r"VideoToolbox encoder configured", re.IGNORECASE),
)
HOST_VIDEOTOOLBOX_OUTPUT_PATTERNS = (
    re.compile(r"VideoToolbox output", re.IGNORECASE),
    re.compile(r"encoded frame", re.IGNORECASE),
)
HOST_VIDEOTOOLBOX_OUTPUT_EPOCH_PATTERN = re.compile(
    r"VideoToolbox output[^\n]*(?:media|session)[-_ ]?epoch[=: ]+(\d+)",
    re.IGNORECASE,
)
HOST_VIDEOTOOLBOX_OUTPUT_SOURCE_PATTERN = re.compile(
    r"VideoToolbox output[^\n]*capture_source=(ScreenCaptureKit|CGDisplayStream|SCStream)",
    re.IGNORECASE,
)
HOST_VIDEOTOOLBOX_OUTPUT_SOURCE_EPOCH_PATTERN = re.compile(
    r"VideoToolbox output[^\n]*(?:media|session)[-_ ]?epoch[=: ]+(\d+)[^\n]*capture_source=(ScreenCaptureKit|CGDisplayStream|SCStream)",
    re.IGNORECASE,
)
HOST_SESSION_PATTERNS = (
    re.compile(r"Secure Internet product session started", re.IGNORECASE),
    re.compile(r"InternetProductSession", re.IGNORECASE),
    re.compile(r"Phase 3 product", re.IGNORECASE),
)
HOST_WEBRTC_PATTERNS = (
    re.compile(r"\bICE\b(?:\s+(?:state|connected|gathering|candidate))?"),
    re.compile(r"\bDTLS\b"),
    re.compile(r"\bDataChannel\b", re.IGNORECASE),
    re.compile(r"selected candidate pair", re.IGNORECASE),
)
HOST_MEDIA_EPOCH_PATTERN = re.compile(r"(?:media|session)[-_ ]?epoch[=: ]+(\d+)", re.IGNORECASE)

ANDROID_STREAM_ACTIVE_PATTERN = re.compile(
    r"internet_stream_active session_epoch=(\d+) route=(direct|relay)",
    re.IGNORECASE,
)
ANDROID_FIRST_INPUT_PATTERNS = (
    re.compile(r"First video frame", re.IGNORECASE),
    re.compile(r"First frame: size=", re.IGNORECASE),
)
ANDROID_DECODER_CONFIGURED_PATTERNS = (
    re.compile(r"setupDecoder:", re.IGNORECASE),
    re.compile(r"Decoder started:", re.IGNORECASE),
)
ANDROID_FIRST_OUTPUT_PATTERN = re.compile(r"First output frame", re.IGNORECASE)
ANDROID_FIRST_INPUT_EPOCH_PATTERN = re.compile(
    r"First frame:[^\n]*session_epoch=(\d+)", re.IGNORECASE
)
ANDROID_FIRST_OUTPUT_EPOCH_PATTERN = re.compile(
    r"First output frame[^\n]*session_epoch=(\d+)", re.IGNORECASE
)
ANDROID_OUTPUT_INDEX_PATTERN = re.compile(r"Output #(\d+)", re.IGNORECASE)
ANDROID_OUTPUT_TOTAL_PATTERN = re.compile(r"Decode stats: input=\d+, output=(\d+)", re.IGNORECASE)
ANDROID_DROP_PATTERNS = (
    re.compile(r"Dropping frame", re.IGNORECASE),
    re.compile(r"frame_dropped", re.IGNORECASE),
)
ANDROID_ERROR_PATTERNS = (
    re.compile(r"Codec error", re.IGNORECASE),
    re.compile(r"codec_runtime_failure", re.IGNORECASE),
    re.compile(r"codec_configuration_failure", re.IGNORECASE),
    re.compile(r"decode direct feed error", re.IGNORECASE),
    re.compile(r"releaseOutputBuffer failed", re.IGNORECASE),
    re.compile(r"internet_session_error", re.IGNORECASE),
)
BLOCKING_HOST_PATTERNS = (
    re.compile(r"Screen recording permission not granted", re.IGNORECASE),
    re.compile(r"startServer aborted: Missing Screen Recording permission", re.IGNORECASE),
)


class ContinuityInputError(ValueError):
    """Raised when evidence input cannot be read or parsed."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ContinuityInputError(f"could not read {path}: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ContinuityInputError(f"could not hash {path}: {error}") from error
    return digest.hexdigest()


def _run_git(repo: Path, args: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def repository_state(repo: Path) -> dict[str, Any]:
    status = _run_git(repo, ["status", "--porcelain=v1"])
    return {
        "revision": _run_git(repo, ["rev-parse", "HEAD"]),
        "branch": _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": None if status is None else bool(status),
    }


def _contains_any(text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _matching_lines(text: str, patterns: Iterable[re.Pattern[str]], *, limit: int = 8) -> list[str]:
    matches: list[str] = []
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in patterns):
            matches.append(line[:240])
        if len(matches) >= limit:
            break
    return matches


def _count_lines(text: str, patterns: Iterable[re.Pattern[str]]) -> int:
    return sum(1 for line in text.splitlines() if any(pattern.search(line) for pattern in patterns))


def _max_int_match(text: str, pattern: re.Pattern[str]) -> int:
    maximum = 0
    for match in pattern.finditer(text):
        try:
            maximum = max(maximum, int(match.group(1)))
        except (IndexError, ValueError):
            continue
    return maximum


def _observed_int_matches(text: str, pattern: re.Pattern[str]) -> set[int]:
    observed: set[int] = set()
    for match in pattern.finditer(text):
        try:
            observed.add(int(match.group(1)))
        except (IndexError, ValueError):
            continue
    return observed


def _observed_named_matches(text: str, pattern: re.Pattern[str]) -> list[str]:
    observed: list[str] = []
    for match in pattern.finditer(text):
        value = match.group(1)
        if value not in observed:
            observed.append(value)
    return observed


def _observed_output_source_epochs(text: str) -> dict[int, str]:
    observed: dict[int, str] = {}
    for match in HOST_VIDEOTOOLBOX_OUTPUT_SOURCE_EPOCH_PATTERN.finditer(text):
        observed[int(match.group(1))] = match.group(2)
    return observed


def _longest_contiguous_run(values: Iterable[int]) -> int:
    longest = 0
    current = 0
    previous: int | None = None
    for value in sorted(set(values)):
        if previous is None or value == previous + 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = value
    return longest


def _synthetic_markers(text: str) -> list[str]:
    lowered = text.lower()
    return [marker for marker in SYNTHETIC_MARKERS if marker.lower() in lowered]


SENSITIVE_PATTERNS = (
    (re.compile(r"\b(?:https?|turns?|stuns?)://[^\s<>\"']+", re.IGNORECASE), "[redacted-url]"),
    (re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?(?![0-9.])"), "[redacted-ip]"),
    (re.compile(r"(?:/Users/[^\s<>\"']+|/home/[^\s<>\"']+|/Volumes/[^\s<>\"']+|[A-Za-z]:\\Users\\[^\s<>\"']+)", re.IGNORECASE), "[redacted-path]"),
    (re.compile(r"([\w.-]+)@([\w.-]+\.[A-Za-z]{2,})"), "[redacted-account]"),
    (re.compile(r"(\"hardware_serial\"\s*:\s*\")(?!\[?redacted\]?\")[^\"]+(\")", re.IGNORECASE), r"\1[redacted]\2"),
    (re.compile(r"\b((?:hardware|device) serial\s*:\s*)(?!\[?redacted\]?\b)[^\r\n]+", re.IGNORECASE), r"\1[redacted]"),
    (re.compile(r"\b((?:host(?:name)?|account|user(?:name)?|email)=)[^\s,;]+", re.IGNORECASE), r"\1[redacted]"),
    (re.compile(r"\b(?:[A-Za-z0-9-]+\.)+(?:local|internal|lan|home|corp|com|net|org|io|dev)(?::\d+)?\b", re.IGNORECASE), "[redacted-host]"),
)


def _sanitize_fragment(value: str) -> str:
    sanitized = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized[:240]


def _sanitize_observation(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_fragment(value)
    if isinstance(value, list):
        return [_sanitize_observation(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_observation(item) for key, item in value.items()}
    return value


def _evidence_path(path: Path, repo: Path) -> str:
    resolved_repo = repo.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_repo).as_posix()
    except ValueError:
        return f"[external]/{path.name}"


def _parse_device_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise ContinuityInputError(f"could not parse device info {path}: {error}") from error
    if isinstance(document, dict):
        device = document.get("device")
        if isinstance(device, dict):
            return device
        return document
    raise ContinuityInputError(f"device info must be a JSON object: {path}")


def analyze_host(text: str) -> dict[str, Any]:
    media_epochs = sorted({int(value) for value in HOST_MEDIA_EPOCH_PATTERN.findall(text)})
    videotoolbox_output_epochs = sorted(
        {int(value) for value in HOST_VIDEOTOOLBOX_OUTPUT_EPOCH_PATTERN.findall(text)}
    )
    synthetic_markers = _synthetic_markers(text)
    capture_started = _contains_any(text, HOST_CAPTURE_STARTED_PATTERNS)
    capture_marker_count = _count_lines(text, HOST_CAPTURE_FIRST_FRAME_PATTERNS)
    capture_sources = _observed_named_matches(text, HOST_VIDEOTOOLBOX_OUTPUT_SOURCE_PATTERN)
    output_source_epochs = _observed_output_source_epochs(text)
    videotoolbox_output_frame_count = _count_lines(text, HOST_VIDEOTOOLBOX_OUTPUT_PATTERNS)
    if synthetic_markers:
        media_source = "synthetic"
    elif capture_marker_count:
        media_source = "real_screencapturekit_or_cgdisplaystream"
    else:
        media_source = "absent"
    return {
        "internet_product_session_started": _contains_any(text, HOST_SESSION_PATTERNS),
        "webrtc_transport_observed": _contains_any(text, HOST_WEBRTC_PATTERNS),
        "capture_started": capture_started,
        "real_capture_first_frame": _contains_any(text, HOST_CAPTURE_FIRST_FRAME_PATTERNS),
        "media_source": media_source,
        "capture_marker_count": capture_marker_count,
        "videotoolbox_configured": _contains_any(text, HOST_VIDEOTOOLBOX_CONFIG_PATTERNS),
        "videotoolbox_output_observed": _contains_any(text, HOST_VIDEOTOOLBOX_OUTPUT_PATTERNS),
        "videotoolbox_output_frame_count": videotoolbox_output_frame_count,
        "videotoolbox_output_epochs": videotoolbox_output_epochs,
        "capture_sources": capture_sources,
        "videotoolbox_output_source_epochs": sorted(output_source_epochs),
        "media_epochs": media_epochs,
        "screen_recording_blocked": _contains_any(text, BLOCKING_HOST_PATTERNS),
        "videotoolbox_error_lines": _matching_lines(
            text, (re.compile(r"VideoToolbox.*(?:error|failed)", re.IGNORECASE),)
        ),
        "blocking_lines": _matching_lines(text, BLOCKING_HOST_PATTERNS),
        "synthetic_markers": synthetic_markers,
    }


def analyze_android(text: str) -> dict[str, Any]:
    active = ANDROID_STREAM_ACTIVE_PATTERN.search(text)
    decoder_errors = _matching_lines(text, ANDROID_ERROR_PATTERNS, limit=12)
    drop_count = _count_lines(text, ANDROID_DROP_PATTERNS)
    observed_output_indices = _observed_int_matches(text, ANDROID_OUTPUT_INDEX_PATTERN)
    reported_output_frame_count = _max_int_match(text, ANDROID_OUTPUT_TOTAL_PATTERN)
    observed_output_frame_count = max(
        _longest_contiguous_run(observed_output_indices), reported_output_frame_count
    )
    return {
        "internet_stream_active": bool(active),
        "session_epoch": int(active.group(1)) if active else None,
        "route": active.group(2).lower() if active else None,
        "decoder_configured": _contains_any(text, ANDROID_DECODER_CONFIGURED_PATTERNS),
        "first_input_frame": _contains_any(text, ANDROID_FIRST_INPUT_PATTERNS),
        "first_input_frame_epochs": sorted(
            {int(value) for value in ANDROID_FIRST_INPUT_EPOCH_PATTERN.findall(text)}
        ),
        "first_output_frame": bool(ANDROID_FIRST_OUTPUT_PATTERN.search(text)),
        "first_output_frame_epochs": sorted(
            {int(value) for value in ANDROID_FIRST_OUTPUT_EPOCH_PATTERN.findall(text)}
        ),
        "maximum_output_frame_index": max(observed_output_indices) if observed_output_indices else 0,
        "observed_output_frame_count": observed_output_frame_count,
        "reported_output_frame_count": reported_output_frame_count,
        "drop_count": drop_count,
        "decoder_error_lines": decoder_errors,
        "transport_closed_count": len(re.findall(r"TRANSPORT_CLOSED", text, re.IGNORECASE)),
        "synthetic_markers": _synthetic_markers(text),
    }


def _append_required_stage(
    stages: list[dict[str, Any]],
    key: str,
    observed: bool,
    reason: str,
    blockers: list[str],
) -> None:
    stages.append({"key": key, "observed": observed, "reason": None if observed else reason})
    if not observed:
        blockers.append(reason)


def evaluate(
    *,
    host_logs: Sequence[Path],
    android_logs: Sequence[Path],
    repo: Path,
    network_path: str,
    host_signing: str,
    screen_recording: str,
    device_info: Path | None = None,
    minimum_output_frames: int = 120,
    maximum_dropped_frames: int = 0,
    notes: str | None = None,
) -> dict[str, Any]:
    if network_path not in NETWORK_PATHS:
        raise ContinuityInputError(f"network_path must be one of {sorted(NETWORK_PATHS)}")
    if host_signing not in HOST_SIGNING:
        raise ContinuityInputError(f"host_signing must be one of {sorted(HOST_SIGNING)}")
    if screen_recording not in SCREEN_RECORDING:
        raise ContinuityInputError(f"screen_recording must be one of {sorted(SCREEN_RECORDING)}")
    if minimum_output_frames <= 0:
        raise ContinuityInputError("minimum_output_frames must be positive")
    if maximum_dropped_frames < 0:
        raise ContinuityInputError("maximum_dropped_frames must be non-negative")

    host_text = "\n".join(_read_text(path) for path in host_logs)
    android_text = "\n".join(_read_text(path) for path in android_logs)
    host = analyze_host(host_text)
    android = analyze_android(android_text)

    blockers: list[str] = []
    failures: list[str] = []
    stages: list[dict[str, Any]] = []

    if network_path != "public_internet":
        blockers.append("public Internet route evidence is required for this continuity gate")
    if host_signing != "identity_signed":
        blockers.append("identity-signed Host evidence is required")
    if screen_recording != "granted" or host["screen_recording_blocked"]:
        blockers.append("macOS Screen Recording permission is not proven granted")

    synthetic = sorted(set(host["synthetic_markers"] + android["synthetic_markers"]))
    if synthetic:
        blockers.append("synthetic media markers are present in supplied logs")

    host_capture_sources = sorted(set(host["capture_sources"]))
    host_output_epochs = set(host["videotoolbox_output_source_epochs"])
    android_input_epochs = set(android["first_input_frame_epochs"])
    android_output_epochs = set(android["first_output_frame_epochs"])
    shared_pipeline_epochs = sorted(
        host_output_epochs & android_input_epochs & android_output_epochs
    )

    _append_required_stage(
        stages,
        "host_internet_product_session",
        host["internet_product_session_started"],
        "Host InternetProductSession start evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "ice_dtls_datachannel",
        host["webrtc_transport_observed"] or android["internet_stream_active"],
        "ICE/DTLS/DataChannel or Internet stream-active evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "android_internet_stream_active",
        android["internet_stream_active"],
        "Android Internet stream-active route evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "protocol_v1_media_epoch",
        bool(host["media_epochs"]) or android["session_epoch"] is not None,
        "Protocol v1 media/session epoch evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "real_capture_first_frame",
        host["real_capture_first_frame"],
        "ScreenCaptureKit/CGDisplayStream first-frame evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "real_capture_source_metadata",
        any(source in {"ScreenCaptureKit", "CGDisplayStream", "SCStream"} for source in host_capture_sources),
        "real capture-source metadata is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "videotoolbox_output",
        host["videotoolbox_output_observed"],
        "VideoToolbox encoded-output evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "videotoolbox_output_epoch",
        bool(host_output_epochs),
        "VideoToolbox output media epoch evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "android_decoder_configured",
        android["decoder_configured"],
        "Android MediaCodec decoder configuration evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "android_first_input_frame",
        android["first_input_frame"],
        "Android first encoded-frame input evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "android_first_output_frame",
        android["first_output_frame"],
        "Android MediaCodec first output frame evidence is missing",
        blockers,
    )
    _append_required_stage(
        stages,
        "shared_pipeline_epoch",
        bool(shared_pipeline_epochs),
        "Host VideoToolbox output and Android MediaCodec input/output do not share a session epoch",
        blockers,
    )
    enough_output = android["observed_output_frame_count"] >= minimum_output_frames
    _append_required_stage(
        stages,
        "android_continuous_output_frames",
        enough_output,
        f"Android output frame count is below {minimum_output_frames}",
        blockers,
    )

    if host["videotoolbox_error_lines"]:
        failures.append("Host VideoToolbox errors were observed")
    if android["decoder_error_lines"]:
        failures.append("Android decoder or Internet session errors were observed")
    if android["drop_count"] > maximum_dropped_frames:
        failures.append(
            f"Android dropped-frame count {android['drop_count']} exceeds {maximum_dropped_frames}"
        )

    verdict = PASS
    if blockers:
        verdict = BLOCKED
    elif failures:
        verdict = FAIL

    inputs = []
    for category, paths in (("host_log", host_logs), ("android_log", android_logs)):
        for path in paths:
            inputs.append(
                {
                    "category": category,
                    "path": _evidence_path(path, repo),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    if device_info is not None:
        inputs.append(
            {
                "category": "device_info",
                "path": _evidence_path(device_info, repo),
                "sha256": _sha256(device_info),
                "bytes": device_info.stat().st_size,
            }
        )

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "gate_can_close_phase3_release": False,
        "conditions": {
            "network_path": network_path,
            "host_signing": host_signing,
            "screen_recording": screen_recording,
            "minimum_output_frames": minimum_output_frames,
            "maximum_dropped_frames": maximum_dropped_frames,
        },
        "repository": repository_state(repo.resolve()),
        "device": _sanitize_observation(_parse_device_info(device_info)),
        "inputs": inputs,
        "continuity_summary": {
            "media_source": host["media_source"],
            "public_internet_path": network_path == "public_internet",
            "selected_webrtc_route": android["route"],
            "protocol_v1_media_epochs": host["media_epochs"],
            "protocol_v1_session_epoch": android["session_epoch"],
            "capture_sources": host_capture_sources,
            "capture_frame_count": host["capture_marker_count"],
            "videotoolbox_output_frames": host["videotoolbox_output_frame_count"],
            "videotoolbox_output_epochs": host["videotoolbox_output_epochs"],
            "videotoolbox_output_source_epochs": host["videotoolbox_output_source_epochs"],
            "mediacodec_first_input_frame": android["first_input_frame"],
            "mediacodec_first_input_epochs": android["first_input_frame_epochs"],
            "mediacodec_first_output_frame": android["first_output_frame"],
            "mediacodec_first_output_epochs": android["first_output_frame_epochs"],
            "shared_pipeline_epochs": shared_pipeline_epochs,
            "continuous_output_frames": android["observed_output_frame_count"],
            "dropped_frames": android["drop_count"],
            "decoder_error_count": len(android["decoder_error_lines"]),
        },
        "host_observation": _sanitize_observation(host),
        "android_observation": _sanitize_observation(android),
        "stages": stages,
        "reasons": blockers if blockers else failures,
        "release_gate_effect": "none",
    }
    if notes:
        document["notes"] = _sanitize_fragment(notes)
    return document


def _write_result(result: dict[str, Any], stream: TextIO) -> None:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate retained Phase 3 real-media continuity logs."
    )
    parser.add_argument("--host-log", action="append", type=Path, required=True)
    parser.add_argument("--android-log", action="append", type=Path, required=True)
    parser.add_argument("--device-info", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--network-path", choices=sorted(NETWORK_PATHS), required=True)
    parser.add_argument("--host-signing", choices=sorted(HOST_SIGNING), required=True)
    parser.add_argument("--screen-recording", choices=sorted(SCREEN_RECORDING), required=True)
    parser.add_argument("--minimum-output-frames", type=int, default=120)
    parser.add_argument("--maximum-dropped-frames", type=int, default=0)
    parser.add_argument("--notes")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = evaluate(
            host_logs=args.host_log,
            android_logs=args.android_log,
            repo=args.repo,
            network_path=args.network_path,
            host_signing=args.host_signing,
            screen_recording=args.screen_recording,
            device_info=args.device_info,
            minimum_output_frames=args.minimum_output_frames,
            maximum_dropped_frames=args.maximum_dropped_frames,
            notes=args.notes,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output:
                _write_result(result, output)
        else:
            _write_result(result, sys.stdout)
    except (ContinuityInputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 3

    if result["verdict"] == PASS:
        return 0
    for reason in result["reasons"]:
        print(f"{result['verdict']}: {reason}", file=sys.stderr)
    return 2 if result["verdict"] == FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
