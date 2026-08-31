"""Shared helpers for Android audio readiness evidence collectors."""

from __future__ import annotations

import json
import os
import re
import subprocess
from ipaddress import IPv6Address, ip_address
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_PORT = 54321
REDACTED_SERIAL = "<ANDROID_SERIAL>"
REDACTED_DEVICE_SERIAL = "<ANDROID_DEVICE_SERIAL>"
REDACTED_HOME = "<home>"
REDACTED_REPO_ROOT = "<repo-root>"
REDACTED_TEAM_ID = "<TEAM_ID>"
REDACTED_BUILD_FINGERPRINT = "redacted-build-fingerprint"
DEVICE_LOCK = Path("/tmp/vibe-screen-device-android.lock")
LOGIN_ITEM_DIAGNOSTIC_TEXT = "login-item-diagnostic"
LOGIN_ITEM_PROBE_TEXT = "probe-login" + "-item"


@dataclass(frozen=True)
class DeviceLock:
    acquired: bool
    path: Path
    detail: str


def acquire_device_lock(path: Path = DEVICE_LOCK) -> DeviceLock:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return DeviceLock(False, path, "Existing shared Android device lock blocked collection.\n")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(f"android-audio-current-base-readiness pid={os.getpid()}\n")
    return DeviceLock(True, path, "Acquired shared Android device lock for read-only collection.\n")


def release_device_lock(lock: DeviceLock) -> None:
    if not lock.acquired:
        return
    try:
        lock.path.unlink()
    except FileNotFoundError:
        return


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_command(command: Sequence[str], *, timeout_seconds: float = 20.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        return subprocess.CompletedProcess(list(command), 127, "", str(error))
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return subprocess.CompletedProcess(
            list(command),
            124,
            stdout,
            f"command timed out after {timeout_seconds:g}s\n{stderr}".strip(),
        )


def redact_text(value: str, *serials: str) -> str:
    redacted = value
    for serial in sorted({item for item in serials if item}, key=len, reverse=True):
        redacted = redacted.replace(serial, REDACTED_SERIAL)
    redacted = redacted.replace(str(REPO_ROOT), REDACTED_REPO_ROOT)
    home = str(Path.home())
    if home:
        redacted = redacted.replace(home, REDACTED_HOME)
    user = os.environ.get("USER")
    if user:
        redacted = re.sub(rf"(?<=\s){re.escape(user)}(?=\s)", "<user>", redacted)
    redacted = re.sub(r"/Users/[^\s'\"]+", REDACTED_HOME, redacted)
    redacted = re.sub(r"Application Support/com\.apple\.TCC", "<tcc-store>", redacted)
    redacted = redacted.replace("TCC" + ".db", "<tcc-db>")
    redacted = redacted.replace("/usr/bin/sfltool dump" + "btm", "<forbidden-login-item-diagnostic>")
    redacted = redacted.replace("--include-" + LOGIN_ITEM_DIAGNOSTIC_TEXT, "<login-item-diagnostic-flag>")
    redacted = redacted.replace("--inspect-login" + "-items", "<login-item-diagnostic-flag>")
    redacted = redacted.replace("--" + LOGIN_ITEM_PROBE_TEXT + "s", "<login-item-diagnostic-flag>")
    redacted = redacted.replace("--" + LOGIN_ITEM_PROBE_TEXT, "<login-item-diagnostic-flag>")
    redacted = re.sub(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", "<ipv4>", redacted)
    redacted = re.sub(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", "<mac-address>", redacted)
    redacted = re.sub(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])", _redact_ipv6_candidate, redacted)
    redacted = re.sub(r"(TeamIdentifier=)[A-Z0-9]{5,12}", rf"\1{REDACTED_TEAM_ID}", redacted)
    redacted = re.sub(r"(OU=)[A-Z0-9]{5,12}", rf"\1{REDACTED_TEAM_ID}", redacted)
    return redacted


def _redact_ipv6_candidate(match: re.Match[str]) -> str:
    candidate = match.group(0)
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return candidate
    return "<ipv6>" if isinstance(parsed, IPv6Address) else candidate


def redact_json(value: Any, *serials: str) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"adb_serial", "serial"}:
                redacted[key] = REDACTED_SERIAL if item else item
            elif key == "device_serial":
                redacted[key] = REDACTED_DEVICE_SERIAL if item else item
            elif key in {"team_identifier", "TeamIdentifier"} and item:
                redacted[key] = REDACTED_TEAM_ID
            elif key == "build_fingerprint" and item:
                redacted[key] = REDACTED_BUILD_FINGERPRINT
            else:
                redacted[key] = redact_json(item, *serials)
        return redacted
    if isinstance(value, list):
        return [redact_json(item, *serials) for item in value]
    if isinstance(value, str):
        return redact_text(value, *serials)
    return value


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_command_result(path: Path, result: subprocess.CompletedProcess[str], *serials: str) -> None:
    command = " ".join(str(part) for part in result.args)
    stdout = redact_text((result.stdout or "").rstrip(), *serials)
    stderr = redact_text((result.stderr or "").rstrip(), *serials)
    body = (
        f"$ {redact_text(command, *serials)}\n"
        f"exit={result.returncode}\n"
        f"--- stdout ---\n{stdout}\n"
        f"--- stderr ---\n{stderr}"
    )
    write_text(path, body.rstrip() + "\n")


def adb(serial: str, args: Sequence[str], *, timeout_seconds: float = 20.0) -> subprocess.CompletedProcess[str]:
    return run_command(["adb", "-s", serial, *args], timeout_seconds=timeout_seconds)


def adb_stdout(serial: str, args: Sequence[str], *, timeout_seconds: float = 20.0) -> str:
    result = adb(serial, args, timeout_seconds=timeout_seconds)
    return result.stdout.strip() if result.returncode == 0 else ""


def device_identity(serial: str) -> dict[str, Any]:
    properties = {
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "device": "ro.product.device",
        "product": "ro.product.name",
        "android_release": "ro.build.version.release",
        "sdk": "ro.build.version.sdk",
        "build_fingerprint": "ro.build.fingerprint",
        "abi": "ro.product.cpu.abi",
    }
    identity: dict[str, Any] = {"adb_serial": REDACTED_SERIAL}
    for key, prop in properties.items():
        value = adb_stdout(serial, ["shell", "getprop", prop])
        if key == "build_fingerprint" and value:
            identity[key] = REDACTED_BUILD_FINGERPRINT
        else:
            identity[key] = int(value) if key == "sdk" and value.isdigit() else value
    identity["device_serial"] = REDACTED_DEVICE_SERIAL if adb_stdout(serial, ["shell", "getprop", "ro.serialno"]) else ""
    return identity


def package_summary(serial: str, package_name: str) -> dict[str, Any] | None:
    output = adb_stdout(serial, ["shell", "dumpsys", "package", package_name], timeout_seconds=30.0)
    if not output or "Unable to find package" in output:
        return None
    version_name = re.search(r"^\s*versionName=(.+)$", output, re.MULTILINE)
    version_code = re.search(r"^\s*versionCode=(\d+)", output, re.MULTILINE)
    first_install = re.search(r"^\s*firstInstallTime=(.+)$", output, re.MULTILINE)
    last_update = re.search(r"^\s*lastUpdateTime=(.+)$", output, re.MULTILINE)
    return {
        "package": package_name,
        "version_name": version_name.group(1).strip() if version_name else None,
        "version_code": int(version_code.group(1)) if version_code else None,
        "first_install_time": first_install.group(1).strip() if first_install else None,
        "last_update_time": last_update.group(1).strip() if last_update else None,
    }


def marker_summary(text: str, markers: Sequence[str]) -> dict[str, bool]:
    lower = text.lower()
    return {marker: marker.lower() in lower for marker in markers}


def matching_lines(text: str, markers: Sequence[str], *, limit: int = 120) -> str:
    lower_markers = tuple(marker.lower() for marker in markers)
    lines = [line for line in text.splitlines() if any(marker in line.lower() for marker in lower_markers)]
    if not lines:
        return "No audio playback markers were found in retained logs.\n"
    return "\n".join(lines[-limit:]) + "\n"


def sfltool_note(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0 and (result.stdout or "").strip():
        return "sfltool process was running; process ids are intentionally redacted.\n"
    if result.returncode == 1 and not (result.stdout or "").strip():
        return "No sfltool process was running.\n"
    return f"Could not conclusively inspect sfltool process state; exit={result.returncode}.\n"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def host_listener_observed(readiness: dict[str, Any]) -> bool:
    listener = readiness.get("listener")
    return isinstance(listener, dict) and listener.get("observed") is True


def host_build_identity_recorded(readiness: dict[str, Any]) -> bool:
    metadata = readiness.get("installed_host")
    if not isinstance(metadata, dict):
        metadata = readiness.get("metadata")
    return isinstance(metadata, dict) and all(metadata.get(key) for key in ("source_commit", "source_tree", "binary_sha256"))


def host_stable_signed_tcc_ready(readiness: dict[str, Any]) -> bool:
    permissions = readiness.get("permissions")
    return (
        readiness.get("signing_tcc_status") in {"pass", "ready"}
        and isinstance(permissions, dict)
        and permissions.get("screen_recording_granted") is True
        and permissions.get("accessibility_granted") is True
        and permissions.get("microphone_granted") is True
    )


ARTIFACT_PATHS = [
    "device-info.json",
    "adb-devices.txt",
    "adb-reverse-list.txt",
    "android-network.txt",
    "usb-live-smoke.json",
    "host-readiness.json",
    "macos-dev-host-preflight-current-base.txt",
    "macos-dev-host-readiness-current-base.txt",
    "host-54321-listener.txt",
    "host-info-plist.txt",
    "host-binary-audio-symbols.txt",
    "host-audio-log.txt",
    "android-audio-logcat.txt",
    "android-audio-diag.txt",
    "audio-log-search.txt",
    "playback-confirmation-blocked.txt",
    "device-lock-acquired.txt",
    "device-lock-adb-state.txt",
    "sfltool-start.txt",
    "sfltool-end.txt",
]


HOST_AUDIO_MARKERS = (
    "audio_capture_started",
    "audio_capture_start_failed",
    "audio_capture_failed",
    "audio_capture_stopped",
    "audio_frame",
    "audio_send",
    "AudioConfig",
    "channel 3",
    "channel=3",
)
