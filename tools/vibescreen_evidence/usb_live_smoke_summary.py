"""Pure parsing and verdict helpers for Android USB live smoke evidence."""

from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any, Sequence


DEFAULT_PORT = 54321

_COMPONENT_PATTERN = re.compile(
    r"(?P<package>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)/(?P<activity>[.$\w]+)"
)
_DECODER_SETUP_PATTERN = re.compile(
    r"setupDecoder:\s*(?P<width>\d+)x(?P<height>\d+),\s*decoder=(?P<decoder>[-\w.]+)"
)
_DECODE_STATS_PATTERN = re.compile(
    r"Decode stats:\s*input=(?P<input>\d+),\s*output=(?P<output>\d+),\s*"
    r"dropped=(?P<dropped>\d+),\s*availBufs=(?P<available_buffers>\d+)"
)
_OUTPUT_LATENCY_PATTERN = re.compile(
    r"Output #(?P<output>\d+):\s*decoder latency avg=(?P<avg>[0-9.]+)ms\s*"
    r"max=(?P<max>[0-9.]+)ms\s*over\s*(?P<samples>\d+)\s*samples,\s*"
    r"input bufs avail=(?P<available_buffers>\d+),\s*dropped=(?P<dropped>\d+)"
)
_LOGCAT_THREADTIME_PATTERN = re.compile(
    r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+"
    r"(?P<pid>\d+)\s+\d+\s+[VDIWEF]\s+"
)


def parse_adb_reverse(output: str, *, port: int = DEFAULT_PORT) -> dict[str, Any]:
    entries = [line.strip() for line in output.splitlines() if line.strip()]
    expected = f"tcp:{port}"
    matching = [line for line in entries if _reverse_entry_matches(line, expected)]
    return {
        "port": port,
        "present": bool(matching),
        "entry": matching[-1] if matching else None,
        "entries": entries,
    }


def _reverse_entry_matches(line: str, expected: str) -> bool:
    fields = line.split()
    return len(fields) >= 2 and fields[-2:] == [expected, expected]


def parse_pids(output: str) -> list[int]:
    pids: list[int] = []
    for field in output.split():
        if field.isdigit():
            pids.append(int(field))
    return pids


def parse_foreground_state(
    window_output: str,
    activity_output: str,
    package_name: str,
) -> dict[str, Any]:
    focus_lines = [
        line.strip()
        for line in window_output.splitlines()
        if "mCurrentFocus" in line
        or "mFocusedApp" in line
        or "topResumedActivity" in line
    ]
    activity_lines = [
        line.strip()
        for line in activity_output.splitlines()
        if "topResumedActivity" in line
        or "mResumedActivity" in line
        or "ResumedActivity" in line
    ]
    all_focus_lines = focus_lines + [
        line for line in activity_lines if line not in focus_lines
    ]
    components = [_component_from_line(line) for line in all_focus_lines]
    components = [component for component in components if component is not None]
    foreground_component = next(
        (
            component
            for component in components
            if component["package"] == package_name
        ),
        components[0] if components else None,
    )
    foreground_package = foreground_component["package"] if foreground_component else None
    package_in_focus = any(package_name in line for line in all_focus_lines)
    return {
        "foreground": bool(package_in_focus),
        "foreground_package": foreground_package,
        "foreground_component": foreground_component["component"]
        if foreground_component
        else None,
        "focus_lines": all_focus_lines[:12],
    }


def _component_from_line(line: str) -> dict[str, str] | None:
    match = _COMPONENT_PATTERN.search(line)
    if not match:
        return None
    package_name = match.group("package")
    activity = match.group("activity")
    return {
        "package": package_name,
        "activity": activity,
        "component": f"{package_name}/{activity}",
    }


def parse_package_metadata(output: str, package_name: str) -> dict[str, Any]:
    version_name_match = re.search(r"^\s*versionName=(.+)$", output, re.MULTILINE)
    version_code_match = re.search(r"^\s*versionCode=(\d+)", output, re.MULTILINE)
    first_install_match = re.search(r"^\s*firstInstallTime=(.+)$", output, re.MULTILINE)
    last_update_match = re.search(r"^\s*lastUpdateTime=(.+)$", output, re.MULTILINE)
    installed = "Unable to find package" not in output and bool(
        version_name_match or version_code_match
    )
    return {
        "package": package_name,
        "installed": installed,
        "version_name": version_name_match.group(1).strip()
        if version_name_match
        else None,
        "version_code": int(version_code_match.group(1))
        if version_code_match
        else None,
        "first_install_time": first_install_match.group(1).strip()
        if first_install_match
        else None,
        "last_update_time": last_update_match.group(1).strip()
        if last_update_match
        else None,
    }


def parse_telemetry_summary(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    events: list[dict[str, Any]] = []
    malformed_lines = 0
    for line in text.splitlines():
        if "VibeScreenTelemetry" not in line:
            continue
        start = line.find("{")
        if start < 0:
            malformed_lines += 1
            continue
        try:
            event, _ = decoder.raw_decode(line[start:])
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            malformed_lines += 1
    return summarize_telemetry_events(events, malformed_lines=malformed_lines)


def summarize_telemetry_events(
    events: Sequence[dict[str, Any]], *, malformed_lines: int = 0
) -> dict[str, Any]:
    event_counts = Counter(
        event.get("event") for event in events if isinstance(event.get("event"), str)
    )
    stream_stats = [event for event in events if event.get("event") == "stream_stats"]
    fps_values = [_number(event.get("fps")) for event in stream_stats]
    fps_values = [value for value in fps_values if value is not None]
    positive_fps_values = [value for value in fps_values if value > 0]
    mbps_values = [_number(event.get("mbps")) for event in stream_stats]
    mbps_values = [value for value in mbps_values if value is not None]
    session_epochs = sorted(
        {
            int(event["session_epoch"])
            for event in events
            if isinstance(event.get("session_epoch"), int)
        }
    )
    frame_drop_totals = [
        int(event["dropped_total"])
        for event in events
        if event.get("event") == "frame_dropped"
        and isinstance(event.get("dropped_total"), int)
    ]
    return {
        "total_events": len(events),
        "malformed_lines": malformed_lines,
        "event_counts": dict(sorted(event_counts.items())),
        "session_epochs": session_epochs,
        "stream_stats": {
            "count": len(stream_stats),
            "fps_min": min(fps_values) if fps_values else None,
            "fps_max": max(fps_values) if fps_values else None,
            "fps_avg": sum(fps_values) / len(fps_values) if fps_values else None,
            "positive_fps_count": len(positive_fps_values),
            "mbps_min": min(mbps_values) if mbps_values else None,
            "mbps_max": max(mbps_values) if mbps_values else None,
            "mbps_avg": sum(mbps_values) / len(mbps_values) if mbps_values else None,
            "latest": stream_stats[-1] if stream_stats else None,
            "non_positive_fps_count": sum(1 for value in fps_values if value <= 0),
        },
        "connection": {
            "opened_count": event_counts.get("connection_opened", 0),
            "closed_count": event_counts.get("connection_closed", 0),
            "reconnect_scheduled_count": event_counts.get("reconnect_scheduled", 0),
            "latest_opened": _last_event(events, "connection_opened"),
            "latest_closed": _last_event(events, "connection_closed"),
        },
        "frame_drops": {
            "event_count": event_counts.get("frame_dropped", 0),
            "latest_dropped_total": frame_drop_totals[-1] if frame_drop_totals else None,
            "max_dropped_total": max(frame_drop_totals) if frame_drop_totals else 0,
        },
    }


def filter_logcat_by_pids(text: str, pids: Sequence[int]) -> str:
    pid_strings = {str(pid) for pid in pids}
    if not pid_strings:
        return ""
    matching_lines = []
    for line in text.splitlines():
        match = _LOGCAT_THREADTIME_PATTERN.match(line)
        if match and match.group("pid") in pid_strings:
            matching_lines.append(line)
    return "\n".join(matching_lines)


def _last_event(events: Sequence[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_decoder_summary(text: str) -> dict[str, Any]:
    setups: list[dict[str, Any]] = []
    decode_stats: list[dict[str, int]] = []
    output_latency: list[dict[str, Any]] = []
    first_output_frame_observed = False

    for line in text.splitlines():
        setup_match = _DECODER_SETUP_PATTERN.search(line)
        if setup_match:
            setups.append(
                {
                    "width": int(setup_match.group("width")),
                    "height": int(setup_match.group("height")),
                    "decoder": setup_match.group("decoder"),
                }
            )
        if "First output frame!" in line:
            first_output_frame_observed = True
        stats_match = _DECODE_STATS_PATTERN.search(line)
        if stats_match:
            decode_stats.append(
                {key: int(value) for key, value in stats_match.groupdict().items()}
            )
        latency_match = _OUTPUT_LATENCY_PATTERN.search(line)
        if latency_match:
            output_latency.append(
                {
                    "output": int(latency_match.group("output")),
                    "avg_ms": float(latency_match.group("avg")),
                    "max_ms": float(latency_match.group("max")),
                    "samples": int(latency_match.group("samples")),
                    "available_buffers": int(latency_match.group("available_buffers")),
                    "dropped": int(latency_match.group("dropped")),
                }
            )

    latest_setup = setups[-1] if setups else None
    latest_stats = decode_stats[-1] if decode_stats else None
    latest_latency = output_latency[-1] if output_latency else None
    dropped_values = [row["dropped"] for row in decode_stats] + [
        row["dropped"] for row in output_latency
    ]
    return {
        "setup_count": len(setups),
        "decoder": latest_setup.get("decoder") if latest_setup else None,
        "video_size": (
            {"width": latest_setup["width"], "height": latest_setup["height"]}
            if latest_setup
            else None
        ),
        "first_output_frame_observed": first_output_frame_observed,
        "decode_stats_count": len(decode_stats),
        "latest_decode_stats": latest_stats,
        "output_latency_count": len(output_latency),
        "latest_output_counter": latest_latency.get("output") if latest_latency else None,
        "latest_output_latency": latest_latency,
        "max_reported_dropped": max(dropped_values) if dropped_values else None,
    }


def label_guard(identity: dict[str, Any] | None) -> dict[str, Any]:
    manufacturer = _lower_identity_value(identity, "manufacturer")
    model = _lower_identity_value(identity, "model")
    device = _lower_identity_value(identity, "device")
    product = _lower_identity_value(identity, "product")
    is_p0110 = (
        manufacturer == "nubia"
        and model == "p0110"
        and "pacific" in {device, product}
    )
    is_fuxi = "fuxi" in {device, product} or model in {"2211133c", "xiaomi 13"}
    return {
        "recorded_as_fuxi": False,
        "device_is_fuxi": is_fuxi,
        "device_is_nubia_p0110_pacific": is_p0110,
        "evidence_scope": (
            "nubia_p0110_pacific_general_android_substitute_only"
            if is_p0110
            else "exact_recorded_android_device_only"
        ),
        "do_not_relabel_as": [] if is_fuxi else ["Xiaomi 13", "fuxi"],
    }


def _lower_identity_value(identity: dict[str, Any] | None, key: str) -> str:
    if not identity:
        return ""
    value = identity.get(key)
    return value.strip().lower() if isinstance(value, str) else ""


def live_smoke_blockers(
    *,
    device_state: str | None,
    device_identity: dict[str, Any] | None,
    reverse: dict[str, Any] | None,
    package: dict[str, Any] | None,
    pids: Sequence[int] | None,
    foreground: dict[str, Any] | None,
    telemetry: dict[str, Any],
    decoder: dict[str, Any],
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if device_state != "device":
        blockers.append(
            {"field": "device.state", "message": "ADB target is not in device state"}
        )
    if device_identity is None:
        blockers.append(
            {
                "field": "device.identity",
                "message": "device identity could not be recorded",
            }
        )
    if reverse is None or not reverse.get("present"):
        blockers.append(
            {"field": "adb.reverse", "message": "adb reverse tcp port mapping is missing"}
        )
    if package is None or not package.get("installed"):
        blockers.append(
            {
                "field": "app.package",
                "message": "Vibe Screen Android package metadata is missing",
            }
        )
    if not pids:
        blockers.append(
            {"field": "app.pids", "message": "Vibe Screen Android process is not running"}
        )
    if foreground is None or not foreground.get("foreground"):
        blockers.append(
            {
                "field": "app.foreground",
                "message": "Vibe Screen Android activity is not foregrounded",
            }
        )
    if telemetry["stream_stats"]["count"] <= 0:
        blockers.append(
            {
                "field": "logs.telemetry.stream_stats",
                "message": "no stream_stats telemetry was observed",
            }
        )
    if telemetry["stream_stats"].get("non_positive_fps_count", 0) > 0:
        blockers.append(
            {
                "field": "logs.telemetry.fps",
                "message": "stream_stats contained non-positive FPS",
            }
        )
    if telemetry["stream_stats"].get("positive_fps_count", 0) <= 0:
        blockers.append(
            {
                "field": "logs.telemetry.fps",
                "message": "no stream_stats telemetry with positive numeric FPS was observed",
            }
        )
    has_counters = (
        decoder.get("latest_output_counter") is not None
        or decoder.get("latest_decode_stats") is not None
    )
    if decoder.get("decoder") is None and not has_counters:
        blockers.append(
            {"field": "logs.decoder.decoder", "message": "decoder setup was not observed"}
        )
    if not decoder.get("first_output_frame_observed") and not has_counters:
        blockers.append(
            {
                "field": "logs.decoder.first_output_frame",
                "message": "first output frame was not observed",
            }
        )
    if not has_counters:
        blockers.append(
            {
                "field": "logs.decoder.counters",
                "message": "decoder frame counters were not observed",
            }
        )
    return blockers
