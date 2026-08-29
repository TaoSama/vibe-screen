#!/usr/bin/env python3
"""Collect read-only Android audio current-base readiness evidence.

The collector writes sanitized public artifacts for the Protocol v1 Android
audio playback gate. It never starts the Host or app, changes ADB reverse,
clears logcat, requests macOS permissions, or opts in to the macOS login-item
diagnostic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from android_audio_readiness_support import (
    ARTIFACT_PATHS,
    DEFAULT_PACKAGE,
    DEFAULT_PORT,
    HOST_AUDIO_MARKERS,
    REDACTED_SERIAL,
    acquire_device_lock,
    adb,
    device_identity,
    host_build_identity_recorded,
    host_listener_observed,
    host_stable_signed_tcc_ready,
    load_json,
    marker_summary,
    matching_lines,
    package_summary,
    redact_json,
    redact_text,
    release_device_lock,
    run_command,
    sfltool_note,
    utc_now,
    write_command_result,
    write_json,
    write_text,
)

ANDROID_AUDIO_MARKERS = (
    "CAPABILITY_AUDIO",
    "AudioConfig",
    "AudioConfigResult",
    "AudioTrack",
    "audio_capture_started",
    "audio_capture_start_failed",
    "audio_capture_failed",
    "audio_frame",
    "audio_send",
    "channel 3",
    "channel=3",
    "pcm",
    "s16",
)

NON_PRODUCT_AUDIO_MARKERS = (
    "audio loopback",
    "loopback audio",
    "synthetic audio",
    "audio synthetic",
    "synthetic harness",
    "loopback-only",
)

LOOPBACK_TRANSPORT_MARKERS = (
    "client connected via loopback",
    "loopback usb",
    "loopback (usb)",
)

# A real protocol session can only be claimed when the retained logs include
# enough production session proof. A raw string match for "protocol v1" in old
# or unrelated logs is not current evidence for this run.
PROTOCOL_V1_SESSION_PROOF_MARKERS = (
    "v1 negotiated",
    "protocol_v1 negotiated",
    "capabilities exchanged",
    "capabilities configured",
    "selected for connection epoch",
    "protocol v1 selected",
)


def has_non_product_audio_marker(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in NON_PRODUCT_AUDIO_MARKERS)


def collect_host_readiness(evidence_dir: Path, port: int, serial: str) -> None:
    preflight_report = evidence_dir / "macos-dev-host-preflight-current-base.txt"
    readiness_report = evidence_dir / "macos-dev-host-readiness-current-base.txt"
    readiness_json = evidence_dir / "host-readiness.json"
    preflight = run_command(
        [sys.executable, "scripts/macos_dev_host.py", "preflight", "--source-root", ".", "--report", str(preflight_report)],
        timeout_seconds=60.0,
    )
    write_command_result(evidence_dir / "macos-dev-host-preflight-current-base.command.txt", preflight, serial)
    readiness = run_command(
        [
            sys.executable,
            "scripts/macos_dev_host.py",
            "readiness",
            "--source-root",
            ".",
            "--report",
            str(readiness_report),
            "--json-output",
            str(readiness_json),
            "--port",
            str(port),
        ],
        timeout_seconds=60.0,
    )
    write_command_result(evidence_dir / "macos-dev-host-readiness-current-base.command.txt", readiness, serial)
    for path in (preflight_report, readiness_report):
        if path.exists():
            write_text(path, redact_text(path.read_text(encoding="utf-8", errors="replace"), serial))
    if readiness_json.exists():
        write_json(readiness_json, redact_json(load_json(readiness_json), serial))


def is_iso_date_prefix(label: str) -> bool:
    if len(label) < 10:
        return False
    prefix = label[:10]
    return prefix[4] == "-" and prefix[7] == "-" and prefix[:4].isdigit() and prefix[5:7].isdigit() and prefix[8:10].isdigit()


def build_observations(
    *,
    run_id: str,
    device: dict[str, Any],
    package: dict[str, Any] | None,
    host_readiness: dict[str, Any],
    android_text: str,
    host_text: str,
    adb_state: str,
    network_text: str,
) -> dict[str, Any]:
    android_markers = marker_summary(android_text, ANDROID_AUDIO_MARKERS)
    host_markers = marker_summary(host_text, HOST_AUDIO_MARKERS)
    combined = f"{android_text}\n{host_text}".lower()
    protocol_v1_session_observed = (
        any(marker in combined for marker in PROTOCOL_V1_SESSION_PROOF_MARKERS)
        and not any(marker in combined for marker in LOOPBACK_TRANSPORT_MARKERS)
    )
    has_lan_route = "wlan0" in network_text and "<ipv4>" in network_text and "state UP" in network_text
    return {
        "run_id": run_id,
        "transport": "usb",
        "android_device_lock_acquired": adb_state == "device",
        "device_identity_recorded": bool(device.get("manufacturer") and device.get("model") and device.get("device")),
        "device_identity_matches_claim": str(device.get("manufacturer", "")).lower() == "nubia" and str(device.get("model", "")).lower() == "p0110" and str(device.get("device", "")).lower() == "pacific",
        "apk_identity_recorded": package is not None,
        "host_build_identity_recorded": host_build_identity_recorded(host_readiness),
        "host_stable_signed_tcc_ready": host_stable_signed_tcc_ready(host_readiness),
        "host_listener_observed": host_listener_observed(host_readiness),
        "protocol_v1_session_observed": protocol_v1_session_observed,
        "audio_capability_negotiated": android_markers["CAPABILITY_AUDIO"] or "capability_audio" in combined,
        "audio_config_accepted": (android_markers["AudioConfig"] or host_markers["AudioConfig"]) and "accepted" in combined,
        "host_microphone_capture_started": host_markers["audio_capture_started"],
        "host_audio_packets_sent": host_markers["audio_frame"] or host_markers["audio_send"] or host_markers["channel 3"] or host_markers["channel=3"],
        "android_audio_track_started": android_markers["AudioTrack"] and ("start" in combined or "play" in combined),
        "android_audio_packets_written": android_markers["AudioTrack"] and ("write" in combined or "wrote" in combined),
        "playback_output_confirmed": False,
        "disconnect_cleanup_observed": "audio_capture_stopped" in combined and "disconnect" in combined,
        "host_logs_retained": bool(host_text.strip()) and "not found" not in host_text.lower(),
        "android_logs_retained": bool(android_text.strip()),
        "no_synthetic_or_loopback_markers": not any(marker in combined for marker in NON_PRODUCT_AUDIO_MARKERS),
        "device": {
            "adb_serial": REDACTED_SERIAL,
            "manufacturer": str(device.get("manufacturer", "")),
            "model": str(device.get("model", "")),
            "device": str(device.get("device", "")),
            "android_release": str(device.get("android_release", "")),
            "sdk": device.get("sdk") if isinstance(device.get("sdk"), int) else None,
            "build_fingerprint": str(device.get("build_fingerprint", "")),
        },
        "artifact_paths": ARTIFACT_PATHS,
        "blocking_notes": [
            "Device identity is nubia P0110 / pacific / Android 16 / SDK 36 / <ANDROID_SERIAL>; this is not Xiaomi 13/fuxi evidence.",
            "Read-only Host readiness did not prove stable signing plus Microphone/TCC readiness for the current-source Host bundle.",
            "No retained production session evidence proves CAPABILITY_AUDIO, accepted AudioConfig, Host channel 3 packets, Android AudioTrack writes, playback output, or cleanup.",
            "Trusted-LAN playback remains blocked because usable wlan0 IPv4 route evidence is " + ("present but audio evidence is missing." if has_lan_route else "missing."),
            "pgrep -x sfltool was captured at start and end; no forbidden login-item database dump command or login-item diagnostic opt-in was run.",
        ],
        "notes": "Fail-closed current-base readiness record only. The real nubia P0110 / pacific / Android 16 / SDK 36 device was visible to ADB, but the retained environment did not satisfy the Host stable signing, Microphone/TCC, Protocol v1 audio negotiation, channel 3 packet flow, Android AudioTrack write, or playback confirmation requirements. This record does not close the real USB or trusted-LAN playback gate.",
    }


def write_readme(evidence_dir: Path, *, commit: str, summary: dict[str, Any]) -> None:
    missing_fields = ", ".join(item["field"] for item in summary.get("missing_requirements", [])) or "none"
    blocking_fields = ", ".join(item["field"] for item in summary.get("blocking_reasons", [])) or "none"
    run_label = evidence_dir.name or "current-base-refresh"
    if is_iso_date_prefix(run_label):
        run_label = run_label[:10]
    content = f"""# P0110 Android audio current-base refresh - {run_label}

Status: blocked before real USB/LAN audio playback acceptance
Device: nubia P0110 / pacific / Android 16 / SDK 36
ADB serial: {REDACTED_SERIAL}
Source commit: {commit} (origin/main at current-base refresh)

## Goal

Re-check the current origin/main baseline for the Protocol v1 Android audio
playback gate using the connected P0110 as a general Android substitute. A
passing record still requires a real USB or trusted-LAN production session with
a stable signed Microphone/TCC-ready macOS Host, negotiated CAPABILITY_AUDIO,
accepted PCM S16LE AudioConfig, Host channel 3 audio packet flow, Android
production AudioTrack start/write evidence, audible or instrumentation-backed
playback confirmation, and cleanup on disconnect or reconfiguration.

## Observed state

- device-info.json records nubia P0110 / pacific / Android 16 / SDK 36; this
  evidence must not be relabeled as Xiaomi 13/fuxi.
- adb-devices.txt, adb-reverse-list.txt, and usb-live-smoke.json retain the
  read-only Android/USB state using {REDACTED_SERIAL} in public artifacts.
- host-readiness.json and the macOS Host reports were collected without any
  login-item diagnostic opt-in. They do not prove a stable signed,
  current-source, Microphone/TCC-ready Host for this audio gate.
- android-audio-logcat.txt, android-audio-diag.txt, host-audio-log.txt, and
  audio-log-search.txt do not contain enough retained production evidence for
  CAPABILITY_AUDIO, accepted AudioConfig, Host channel 3 packet flow, Android
  AudioTrack writes, playback confirmation, or cleanup.
- playback-confirmation-blocked.txt records that no audible or
  instrumentation-backed playback confirmation was collected.
- sfltool-start.txt and sfltool-end.txt were captured with pgrep -x sfltool ||
  true; no forbidden login-item database dump command was executed and no
  login-item probe flag was used.

## Gate result

android-audio-playback-summary.json reports:

- verdict={summary.get('verdict')}
- can_close_android_audio_playback_gate={str(summary.get('can_close_android_audio_playback_gate')).lower()}
- blocking fields: {blocking_fields}

Missing requirements include: {missing_fields}.

This is a fail-closed current-base readiness record only. It does not close the
real USB or trusted-LAN audio playback gate, and it must not be cited as Android
AudioTrack playback of Host PCM S16LE microphone capture.
"""
    write_text(evidence_dir / "README.md", content)


def collect(args: argparse.Namespace) -> int:
    evidence_dir = args.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    serial = args.serial
    run_id = evidence_dir.name
    lock = acquire_device_lock()
    write_text(evidence_dir / "sfltool-start.txt", sfltool_note(run_command(["pgrep", "-x", "sfltool"], timeout_seconds=5.0)))
    write_text(evidence_dir / "device-lock-acquired.txt", redact_text(lock.detail, serial))
    if not lock.acquired:
        write_text(evidence_dir / "sfltool-end.txt", sfltool_note(run_command(["pgrep", "-x", "sfltool"], timeout_seconds=5.0)))
        return 2
    try:
        return collect_with_lock(args, run_id, serial, evidence_dir)
    finally:
        release_device_lock(lock)


def collect_with_lock(args: argparse.Namespace, run_id: str, serial: str, evidence_dir: Path) -> int:
    base_commit_result = run_command(["git", "rev-parse", "origin/main"], timeout_seconds=10.0)
    commit = base_commit_result.stdout.strip() or run_command(["git", "rev-parse", "HEAD"], timeout_seconds=10.0).stdout.strip()
    write_command_result(evidence_dir / "current-base-worktree-status.txt", run_command(["git", "status", "--short", "--branch"], timeout_seconds=10.0), serial)
    write_text(evidence_dir / "collection-command.txt", redact_text(" ".join([Path(sys.executable).name, *sys.argv]) + "\n", serial))

    adb_state_result = adb(serial, ["get-state"], timeout_seconds=args.adb_timeout)
    adb_state = adb_state_result.stdout.strip() if adb_state_result.returncode == 0 else ""
    write_command_result(evidence_dir / "device-lock-adb-state.txt", adb_state_result, serial)
    write_command_result(evidence_dir / "adb-devices.txt", run_command(["adb", "devices", "-l"], timeout_seconds=args.adb_timeout), serial)
    reverse = adb(serial, ["reverse", "--list"], timeout_seconds=args.adb_timeout)
    write_command_result(evidence_dir / "adb-reverse-list.txt", reverse, serial)
    network = adb(serial, ["shell", "ip", "addr", "show", "wlan0"], timeout_seconds=args.adb_timeout)
    write_command_result(evidence_dir / "android-network.txt", network, serial)

    public_device = device_identity(serial)
    public_package = package_summary(serial, args.package)
    write_json(evidence_dir / "device-info.json", {
        "schema_version": "vibescreen.evidence/v1",
        "kind": "android_device_info",
        "collected_at": utc_now(),
        "connection": "already connected to <ANDROID_SERIAL>" if adb_state == "device" else "not connected",
        "adb_version": redact_text(run_command(["adb", "version"], timeout_seconds=args.adb_timeout).stdout.strip(), serial),
        "device": public_device,
        "packages": [public_package] if public_package else [],
    })

    usb_smoke_raw = evidence_dir / "usb-live-smoke.raw.json"
    usb_smoke = run_command([
        sys.executable,
        "-m",
        "vibescreen_evidence.usb_live_smoke",
        "--allow-existing-device-lock",
        "--serial",
        serial,
        "--package",
        args.package,
        "--port",
        str(args.port),
        "--output",
        str(usb_smoke_raw),
    ], timeout_seconds=45.0)
    write_command_result(evidence_dir / "usb-live-smoke.command.txt", usb_smoke, serial)
    if usb_smoke_raw.exists():
        write_json(evidence_dir / "usb-live-smoke.json", redact_json(load_json(usb_smoke_raw), serial))
        usb_smoke_raw.unlink()
    else:
        write_json(evidence_dir / "usb-live-smoke.json", {"verdict": "blocked", "error": redact_text(usb_smoke.stderr or usb_smoke.stdout, serial)})

    collect_host_readiness(evidence_dir, args.port, serial)
    write_command_result(evidence_dir / "host-54321-listener.txt", run_command(["/usr/sbin/lsof", "-nP", f"-iTCP:{args.port}", "-sTCP:LISTEN"], timeout_seconds=10.0), serial)

    plist_path = Path("/Applications/Vibe Screen.app/Contents/Info.plist")
    if plist_path.exists():
        write_command_result(evidence_dir / "host-info-plist.txt", run_command(["/usr/bin/plutil", "-p", str(plist_path)], timeout_seconds=10.0), serial)
    else:
        write_text(evidence_dir / "host-info-plist.txt", "Installed Host Info.plist was not found.\n")
    executable = Path("/Applications/Vibe Screen.app/Contents/MacOS/Vibe Screen")
    if executable.exists():
        strings_result = run_command(["strings", str(executable)], timeout_seconds=20.0)
        write_text(evidence_dir / "host-binary-audio-symbols.txt", redact_text(matching_lines(strings_result.stdout, HOST_AUDIO_MARKERS, limit=200), serial))
    else:
        write_text(evidence_dir / "host-binary-audio-symbols.txt", "Installed Host executable was unavailable.\n")

    host_log_path = Path.home() / "Library/Logs/Telemachus/telemachus.log"
    host_text = redact_text(host_log_path.read_text(encoding="utf-8", errors="replace")[-args.max_log_bytes:] if host_log_path.exists() else "Host audio log was not found at the expected development log path.\n", serial)
    write_text(evidence_dir / "host-audio-log.txt", host_text)
    logcat = adb(serial, ["logcat", "-d", "-v", "threadtime", "-t", str(args.logcat_lines), "-s", "MA", "VD", "StreamClient", "VibeScreenTelemetry"], timeout_seconds=30.0)
    android_log = redact_text((logcat.stdout or "")[-args.max_log_bytes:], serial)
    write_text(evidence_dir / "android-audio-logcat.txt", android_log if android_log.strip() else "No matching Android audio logcat lines were retained.\n")
    diag = adb(serial, ["exec-out", "run-as", args.package, "sh", "-c", "cat files/diag.log.old 2>/dev/null; cat files/diag.log 2>/dev/null"], timeout_seconds=30.0)
    android_diag = redact_text((diag.stdout or "")[-args.max_log_bytes:], serial)
    write_text(evidence_dir / "android-audio-diag.txt", android_diag if android_diag.strip() else "No app-private Android diagnostics were available.\n")
    combined_android = f"{android_log}\n{android_diag}"
    write_text(evidence_dir / "audio-log-search.txt", "Android markers:\n" + json.dumps(marker_summary(combined_android, ANDROID_AUDIO_MARKERS), indent=2, sort_keys=True) + "\n\nHost markers:\n" + json.dumps(marker_summary(host_text, HOST_AUDIO_MARKERS), indent=2, sort_keys=True) + "\n\nMatching lines:\n" + matching_lines(combined_android + "\n" + host_text, (*ANDROID_AUDIO_MARKERS, *HOST_AUDIO_MARKERS)))
    write_text(evidence_dir / "playback-confirmation-blocked.txt", "No audible or instrumentation-backed Android playback confirmation was collected for this current-base run.\n")
    write_text(evidence_dir / "sfltool-end.txt", sfltool_note(run_command(["pgrep", "-x", "sfltool"], timeout_seconds=5.0)))

    observations = build_observations(
        run_id=run_id,
        device=public_device,
        package=public_package,
        host_readiness=load_json(evidence_dir / "host-readiness.json"),
        android_text=combined_android,
        host_text=host_text,
        adb_state=adb_state,
        network_text=redact_text(network.stdout or "", serial),
    )
    write_json(evidence_dir / "android-audio-playback-observations.json", observations)
    owner = run_command(["make", "android-audio-playback-owner-record", f"EVIDENCE_DIR={evidence_dir}"], timeout_seconds=30.0)
    write_command_result(evidence_dir / "android-audio-playback-owner-record-command.txt", owner, serial)
    summary = load_json(evidence_dir / "android-audio-playback-summary.json")
    write_readme(evidence_dir, commit=commit, summary=summary)
    return owner.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="ADB serial for the Android device under test")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="directory for sanitized public evidence")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android package name")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="macOS Host listener port")
    parser.add_argument("--adb-timeout", type=float, default=15.0, help="ADB command timeout in seconds")
    parser.add_argument("--logcat-lines", type=int, default=2000, help="Android logcat tail lines to retain")
    parser.add_argument("--max-log-bytes", type=int, default=256 * 1024, help="maximum bytes retained from each log source")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port <= 0 or args.adb_timeout <= 0 or args.logcat_lines <= 0 or args.max_log_bytes <= 0:
        raise SystemExit("numeric arguments must be positive")
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
