"""Fail-closed preflight for trusted-LAN Android device acceptance.

The collector intentionally stops before Host launch, QR/token exchange, stream
startup, or reconnect. It records whether the current machine and explicit
Android device are ready to begin a real trusted-LAN smoke run.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import ipaddress
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError
from .manifest import ManifestError, repository_state


EXPECTED_MANUFACTURER = "nubia"
EXPECTED_MODEL = "P0110"
EXPECTED_DEVICE = "pacific"
EXPECTED_ANDROID_RELEASE = "16"
EXPECTED_SDK = 36
DEFAULT_HOST_PORT = 54321
DEFAULT_HOST_PREFLIGHT_COMMAND = (sys.executable, "scripts/macos_dev_host.py", "preflight")
REDACTED_DEVICE_SERIAL = "<device-serial>"
DEVICE_LOCK_TEMPLATE = "/tmp/vibe-screen-android-{serial}.lock"
SSID_REDACTIONS = (
    (re.compile(r"(SSID: )[^,\n]+"), r"\1<redacted>"),
    (re.compile(r"(BSSID: )[^,\n]+"), r"\1<redacted>"),
    (re.compile(r"(link/ether\s+)[0-9a-fA-F:]{17}"), r"\1<redacted>"),
)
IPV4_RE = re.compile(r"\binet\s+(\d+\.\d+\.\d+\.\d+)(?:/\d+)?")
IPV4_ENDPOINT_RE = re.compile(r"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?::[0-9]{1,5})?(?![0-9.])")
IFACE_RE = re.compile(r"^([A-Za-z0-9_.-]+):\s+flags=")
EXCLUDED_INTERFACE_PREFIXES = ("lo", "utun", "ipsec", "ppp", "gif", "stf")
EXCLUDED_INTERFACE_NAMES = {"awdl0", "llw0"}
CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")


class TrustedLANPreflightError(RuntimeError):
    """Raised when the preflight cannot collect trustworthy evidence."""


class DeviceLockError(TrustedLANPreflightError):
    """Raised when another process already owns the Android device lock."""

    def __init__(self, *, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.detail = detail


@dataclass(frozen=True)
class CommandCapture:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "command": [redact_command_part(part) for part in self.command],
            "returncode": self.returncode,
            "stdout": sanitize_text(self.stdout),
            "stderr": sanitize_text(self.stderr),
            "timed_out": self.timed_out,
        }


def sanitize_text(value: str) -> str:
    sanitized = value.replace("\r", "")
    for pattern, replacement in SSID_REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    sanitized = redact_lsof_user_columns(sanitized)
    return redact_network_endpoints(sanitized).strip()


def redact_lsof_user_columns(value: str) -> str:
    if "COMMAND" not in value or "USER" not in value or "NODE NAME" not in value:
        return value
    lines = []
    for line in value.splitlines():
        if line.startswith("COMMAND"):
            lines.append(line)
            continue
        lines.append(re.sub(r"^(\S+\s+\d+\s+)(\S+)(\s+)", r"\1<redacted-user>\3", line))
    return "\n".join(lines)


def redact_network_endpoints(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            return match.group(0)
        if address in CARRIER_GRADE_NAT:
            return "<redacted-cgnat-ipv4>"
        return match.group(0)

    return IPV4_ENDPOINT_RE.sub(replace, value)


def redact_device_serial(value: str, serials: Sequence[str]) -> str:
    redacted = value
    for serial in sorted({serial for serial in serials if serial}, key=len, reverse=True):
        redacted = redacted.replace(serial, REDACTED_DEVICE_SERIAL)
    return redacted


def redact_network_endpoints_in_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_network_endpoints(value)
    if isinstance(value, list):
        return [redact_network_endpoints_in_value(item) for item in value]
    if isinstance(value, dict):
        return {
            redact_network_endpoints(str(key)): redact_network_endpoints_in_value(item)
            for key, item in value.items()
        }
    return value


def redact_public_value(value: Any, serials: Sequence[str]) -> Any:
    if isinstance(value, str):
        return redact_device_serial(redact_network_endpoints(value), serials)
    if isinstance(value, list):
        return [redact_public_value(item, serials) for item in value]
    if isinstance(value, dict):
        return {
            redact_device_serial(redact_network_endpoints(str(key)), serials): redact_public_value(item, serials)
            for key, item in value.items()
        }
    return value


def redact_command_part(value: str) -> str:
    lowered = value.lower()
    if lowered.startswith("telemachus://") or lowered.startswith("vibescreen://"):
        return "<redacted-pairing-url>"
    if "token=" in lowered:
        return "<redacted-token-argument>"
    return value


def device_lock_path(serial: str) -> Path:
    return Path(DEVICE_LOCK_TEMPLATE.format(serial=serial))


@dataclass(frozen=True)
class DeviceLockSnapshot:
    path: str
    acquired: bool
    detail: str

    def as_json(self) -> dict[str, Any]:
        return {"path": self.path, "acquired": self.acquired, "detail": self.detail}


class DeviceLock:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.path = device_lock_path(serial)
        self._handle: Any | None = None
        self.snapshot = DeviceLockSnapshot(str(self.path), False, "not acquired")

    def __enter__(self) -> DeviceLockSnapshot:
        try:
            self._handle = self.path.open("a+", encoding="utf-8")
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            try:
                detail = self.path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                detail = "locked by another process"
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                detail = f"failed to acquire lock: {error}"
            raise DeviceLockError(path=self.path, detail=detail) from error
        self._handle.truncate(0)
        self._handle.seek(0)
        self._handle.write(
            "owner=trusted-lan-preflight\n"
            f"pid={os.getpid()}\n"
            f"serial={self.serial}\n"
            f"created_at={datetime.now(timezone.utc).isoformat()}\n"
        )
        self._handle.flush()
        self.snapshot = DeviceLockSnapshot(str(self.path), True, "acquired")
        return self.snapshot

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is None:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


def run_capture(
    command: Sequence[str], *, timeout_seconds: float = 15.0, cwd: Path | None = None
) -> CommandCapture:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return CommandCapture(
            list(command),
            None,
            error.stdout or "",
            error.stderr or "",
            timed_out=True,
        )
    except OSError as error:
        raise TrustedLANPreflightError(f"failed to run {shlex.join(command)}: {error}") from error
    return CommandCapture(
        list(command),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def collect_sfltool_processes(*, timeout_seconds: float) -> dict[str, Any]:
    return run_capture(["pgrep", "-x", "sfltool"], timeout_seconds=timeout_seconds).as_json()


def _stage(name: str, status: str, summary: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    stage = {"name": name, "status": status, "summary": summary}
    if details is not None:
        stage["details"] = details
    return stage


def _private_ipv4_candidates(ifconfig_output: str) -> list[str]:
    candidates: list[str] = []
    interface = ""
    for line in ifconfig_output.splitlines():
        match = IFACE_RE.match(line)
        if match:
            interface = match.group(1)
            continue
        address_match = IPV4_RE.search(line)
        if address_match is None:
            continue
        if interface in EXCLUDED_INTERFACE_NAMES or interface.startswith(EXCLUDED_INTERFACE_PREFIXES):
            continue
        address = address_match.group(1)
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_unspecified
            or parsed.is_global
        ):
            continue
        candidates.append(address)
    return candidates


def _default_route_interface(route_output: str) -> str | None:
    for line in route_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("interface:"):
            return stripped.split(":", 1)[1].strip() or None
    return None


def collect_host_network(host_port: int, *, timeout_seconds: float) -> dict[str, Any]:
    ifconfig = run_capture(["ifconfig"], timeout_seconds=timeout_seconds)
    route = run_capture(["route", "-n", "get", "default"], timeout_seconds=timeout_seconds)
    listener = run_capture(
        ["lsof", "-nP", f"-iTCP:{host_port}", "-sTCP:LISTEN"],
        timeout_seconds=timeout_seconds,
    )
    candidates = _private_ipv4_candidates(ifconfig.stdout)
    listener_output = listener.stdout.lower()
    ifconfig_status = ifconfig.as_json()
    ifconfig_status["stdout"] = "<omitted; parsed into mac_ipv4_candidates>"
    route_status = route.as_json()
    route_status["stdout"] = "<omitted; parsed into default_interface>"
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "mac_ipv4_candidates": candidates,
        "default_interface": _default_route_interface(route.stdout),
        "default_route": route_status,
        "ifconfig": ifconfig_status,
        "listener": listener.as_json(),
        "host_port": host_port,
        "has_lan_listener": any(f"{address}:{host_port}" in listener_output for address in candidates),
        "has_loopback_listener": f"127.0.0.1:{host_port}" in listener_output,
    }


def _run_adb_shell(
    serial: str, adb_path: str, timeout_seconds: float, *arguments: str
) -> CommandCapture:
    return run_capture(
        [adb_path, "-s", serial, "shell", *arguments], timeout_seconds=timeout_seconds
    )


def collect_android_network(
    serial: str,
    adb_path: str,
    timeout_seconds: float,
    mac_ipv4_candidates: Sequence[str],
) -> dict[str, Any]:
    wifi_status = _run_adb_shell(serial, adb_path, timeout_seconds, "cmd", "wifi", "status")
    wlan0 = _run_adb_shell(serial, adb_path, timeout_seconds, "ip", "addr", "show", "wlan0")
    routes = _run_adb_shell(serial, adb_path, timeout_seconds, "ip", "route")
    route_to_mac = {
        address: _run_adb_shell(
            serial, adb_path, timeout_seconds, "ip", "route", "get", address
        ).as_json()
        for address in mac_ipv4_candidates
    }
    wlan0_text = sanitize_text(wlan0.stdout).lower()
    wifi_text = sanitize_text(wifi_status.stdout).lower()
    wlan0_ipv4 = IPV4_RE.findall(wlan0.stdout)
    return {
        "wifi_status": wifi_status.as_json(),
        "wlan0": wlan0.as_json(),
        "routes": routes.as_json(),
        "route_to_mac": route_to_mac,
        "wifi_associated": "wifi is not connected" not in wifi_text and "ssid:" in wifi_text,
        "wlan0_up": "state up" in wlan0_text and "no-carrier" not in wlan0_text,
        "wlan0_ipv4": wlan0_ipv4,
        "has_route": any(_route_result_reaches_wifi(result) for result in route_to_mac.values()),
    }


def _route_result_reaches_wifi(result: dict[str, Any]) -> bool:
    if result.get("returncode") != 0:
        return False
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
    if "unreachable" in text or "no route" in text:
        return False
    return "dev wlan0" in text


def _validated_mac_candidates(
    requested_candidates: Sequence[str], discovered_candidates: Sequence[str]
) -> list[str]:
    requested = list(dict.fromkeys(requested_candidates))
    if not requested:
        return list(discovered_candidates)
    discovered = set(discovered_candidates)
    unknown = [address for address in requested if address not in discovered]
    if unknown:
        raise ValueError(
            "Mac LAN IPv4 candidate is not assigned to a discovered host interface: "
            + ", ".join(unknown)
        )
    return requested


def collect_host_preflight(
    command: Sequence[str], *, timeout_seconds: float, repo: Path
) -> dict[str, Any]:
    capture = run_capture(command, timeout_seconds=timeout_seconds, cwd=repo)
    return capture.as_json()


def _identity_stage(identity: dict[str, Any], expected_serial: str) -> dict[str, Any]:
    blockers = []
    if identity.get("adb_serial") != expected_serial:
        blockers.append(f"ADB serial is {identity.get('adb_serial')!r}, expected {expected_serial!r}")
    if str(identity.get("manufacturer", "")).lower() != EXPECTED_MANUFACTURER:
        blockers.append("device manufacturer is not nubia")
    if identity.get("model") != EXPECTED_MODEL:
        blockers.append("device model is not P0110")
    if identity.get("device") != EXPECTED_DEVICE:
        blockers.append("device codename is not pacific")
    if str(identity.get("android_release")) != EXPECTED_ANDROID_RELEASE:
        blockers.append("Android release is not 16")
    if str(identity.get("sdk")) != str(EXPECTED_SDK):
        blockers.append("Android SDK is not 36")
    status = "pass" if not blockers else "blocked"
    return _stage(
        "device_identity",
        status,
        "Nubia P0110/pacific/Android 16 identity confirmed"
        if not blockers
        else "; ".join(blockers),
        details={"expected_serial": expected_serial},
    )


def _network_stages(
    android_network: dict[str, Any], mac_ipv4_candidates: Sequence[str]
) -> list[dict[str, Any]]:
    return [
        _stage(
            "android_wifi_association",
            "pass" if android_network["wifi_associated"] else "blocked",
            "Wi-Fi is associated"
            if android_network["wifi_associated"]
            else "Wi-Fi is not associated",
        ),
        _stage(
            "android_wlan_ipv4",
            "pass" if android_network["wlan0_up"] and android_network["wlan0_ipv4"] else "blocked",
            "wlan0 has IPv4 " + ", ".join(android_network["wlan0_ipv4"])
            if android_network["wlan0_up"] and android_network["wlan0_ipv4"]
            else "wlan0 is down, has no carrier, or has no IPv4 address",
        ),
        _stage(
            "mac_lan_ipv4_candidate",
            "pass" if mac_ipv4_candidates else "blocked",
            "Mac LAN IPv4 candidate(s): " + ", ".join(mac_ipv4_candidates)
            if mac_ipv4_candidates
            else "No non-loopback Mac IPv4 candidate was found",
        ),
        _stage(
            "route_to_mac_lan",
            "pass" if android_network["has_route"] else "blocked",
            "Android can route to a Mac LAN IPv4 candidate over wlan0"
            if android_network["has_route"]
            else "Android has no wlan0 route to any Mac LAN IPv4 candidate",
        ),
    ]


def _host_preflight_stages(host_preflight: dict[str, Any]) -> list[dict[str, Any]]:
    output = f"{host_preflight.get('stdout', '')}\n{host_preflight.get('stderr', '')}".lower()
    ok = host_preflight.get("returncode") == 0 and not host_preflight.get("timed_out")
    signing_blocked = not ok and any(
        marker in output
        for marker in (
            "codesign identity",
            "signing identity",
            "vibe screen dev",
            "ad-hoc signed",
        )
    )
    return [
        _stage(
            "host_stable_signing",
            "pass" if ok else "blocked",
            "Host preflight passed stable signing checks"
            if ok
            else "Host stable signing is blocked before trusted-LAN evidence can start"
            if signing_blocked
            else "Host preflight failed before a stable signed Host could be verified",
            details={"host_preflight_returncode": host_preflight.get("returncode")},
        ),
        _stage(
            "screen_recording_tcc",
            "pass" if ok else "not_run" if signing_blocked else "blocked",
            "Screen Recording authorization was verified by host preflight"
            if ok
            else "TCC authorization was not evaluated because stable signing failed"
            if signing_blocked
            else "Host preflight did not verify Screen Recording authorization",
        ),
        _stage(
            "accessibility_tcc",
            "pass" if ok else "not_run" if signing_blocked else "blocked",
            "Accessibility authorization was verified by host preflight"
            if ok
            else "TCC authorization was not evaluated because stable signing failed"
            if signing_blocked
            else "Host preflight did not verify Accessibility authorization",
        ),
    ]


def _listener_stage(
    host_network: dict[str, Any], require_host_listener: bool
) -> dict[str, Any]:
    if host_network["has_lan_listener"]:
        return _stage(
            "host_listener",
            "pass",
            f"TCP {host_network['host_port']} is listening on a Mac LAN IPv4 address",
        )
    if require_host_listener:
        summary = f"TCP {host_network['host_port']} is not listening on a Mac LAN IPv4 address"
        if host_network["has_loopback_listener"]:
            summary += "; only loopback listener was observed"
        return _stage("host_listener", "blocked", summary)
    summary = f"TCP {host_network['host_port']} LAN listener was not required for this pre-launch preflight"
    if host_network["has_loopback_listener"]:
        summary += "; loopback listener was observed and is not LAN evidence"
    return _stage("host_listener", "not_run", summary)


def _post_preflight_acceptance_stages() -> list[dict[str, Any]]:
    return [
        _stage(
            "qr_token_admission", "not_run", "Preflight stopped before QR/token admission"
        ),
        _stage(
            "secure_record_negotiation",
            "not_run",
            "Preflight stopped before secure-record negotiation",
        ),
        _stage(
            "protocol_v1_lan", "not_run", "Preflight stopped before Protocol v1 LAN upgrade"
        ),
        _stage("first_decoder_output", "not_run", "Preflight stopped before stream decode"),
        _stage(
            "reconnect_preserved_host_pid",
            "not_run",
            "Preflight stopped before reconnect exercise",
        ),
        _stage(
            "latency_external_camera",
            "not_run",
            "External-camera LAN latency is a separate gate",
        ),
    ]


def _blockers_from_stages(stages: Sequence[dict[str, Any]]) -> list[str]:
    return [
        f"{stage['name']}: {stage['summary']}"
        for stage in stages
        if stage["status"] == "blocked"
    ]


def _sfltool_stage(sfltool_processes: dict[str, Any]) -> dict[str, Any]:
    process_ids = [line for line in str(sfltool_processes.get("stdout", "")).splitlines() if line.strip()]
    if sfltool_processes.get("timed_out") or sfltool_processes.get("returncode") not in (0, 1):
        return _stage(
            "sfltool_process_check",
            "blocked",
            "Could not confirm sfltool absence before trusted-LAN readiness collection",
            details={"returncode": sfltool_processes.get("returncode")},
        )
    if process_ids:
        return _stage(
            "sfltool_process_check",
            "blocked",
            "sfltool process is still running before trusted-LAN readiness collection",
            details={"process_count": len(process_ids)},
        )
    return _stage("sfltool_process_check", "pass", "No sfltool process was running")


def _device_lock_stage(device_lock: dict[str, Any]) -> dict[str, Any]:
    if device_lock.get("acquired") is True:
        return _stage(
            "device_lock",
            "pass",
            f"Acquired Android device lock {device_lock.get('path')}",
        )
    return _stage(
        "device_lock",
        "blocked",
        f"Could not acquire Android device lock {device_lock.get('path')}",
        details={"detail": device_lock.get("detail", "")},
    )


def _base_document(
    *,
    repo: Path,
    host_port: int,
    host_preflight_command: Sequence[str],
    require_host_listener: bool,
    sfltool_processes: dict[str, Any],
    device_lock: dict[str, Any] | None,
    stages: Sequence[dict[str, Any]],
    android_device: dict[str, Any] | None = None,
    host: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = _blockers_from_stages(stages)
    result = "ready" if not blockers else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "trusted_lan_preflight",
        "profile": "trusted-lan-current-worktree-preflight",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "blockers": blockers,
        "stages": list(stages),
        "claims": {
            "can_start_trusted_lan_smoke": result == "ready",
            "real_lan_stream": False,
            "trusted_lan_encrypted": False,
            "legacy_plaintext": False,
            "reconnect": False,
            "latency": False,
            "stability": False,
        },
        "repository": repository_state(repo.resolve()),
        "host": host
        or {
            "network": None,
            "preflight": None,
            "host_preflight_command": [redact_command_part(part) for part in host_preflight_command],
            "require_host_listener": require_host_listener,
        },
        "android_device": android_device or {"identity": None, "network": None},
        "device_lock": device_lock,
        "sfltool_process_check": sfltool_processes,
        "safety": {
            "read_only": True,
            "starts_host": False,
            "runs_instrumentation": False,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_wifi_credentials": False,
            "writes_pairing_token": False,
            "writes_qr_payload": False,
        },
    }


def build_document(
    *,
    serial: str,
    adb_path: str,
    adb_timeout: float,
    repo: Path,
    host_port: int,
    mac_host_ipv4: Sequence[str],
    host_preflight_command: Sequence[str],
    require_host_listener: bool,
) -> dict[str, Any]:
    if host_port <= 0 or host_port > 65535:
        raise ValueError("host_port must be between 1 and 65535")
    sfltool_processes = collect_sfltool_processes(timeout_seconds=adb_timeout)
    sfltool_stage = _sfltool_stage(sfltool_processes)
    if sfltool_stage["status"] == "blocked":
        document = _base_document(
            repo=repo,
            host_port=host_port,
            host_preflight_command=host_preflight_command,
            require_host_listener=require_host_listener,
            sfltool_processes=sfltool_processes,
            device_lock=None,
            stages=[sfltool_stage, *_post_preflight_acceptance_stages()],
        )
        return redact_public_value(document, [serial])

    try:
        with DeviceLock(serial) as lock:
            device_lock = lock.as_json()
            client = ADBClient(serial, adb_path=adb_path, timeout_seconds=adb_timeout)
            client.require_device()
            identity = client.identity()
            host_network = collect_host_network(host_port, timeout_seconds=adb_timeout)
            mac_candidates = _validated_mac_candidates(mac_host_ipv4, host_network["mac_ipv4_candidates"])
            android_network = collect_android_network(serial, adb_path, adb_timeout, mac_candidates)
            host_preflight = collect_host_preflight(host_preflight_command, timeout_seconds=30.0, repo=repo)
    except DeviceLockError as error:
        device_lock = DeviceLockSnapshot(str(error.path), False, error.detail).as_json()
        document = _base_document(
            repo=repo,
            host_port=host_port,
            host_preflight_command=host_preflight_command,
            require_host_listener=require_host_listener,
            sfltool_processes=sfltool_processes,
            device_lock=device_lock,
            stages=[sfltool_stage, _device_lock_stage(device_lock), *_post_preflight_acceptance_stages()],
        )
        return redact_public_value(document, [serial])

    stages = [
        sfltool_stage,
        _device_lock_stage(device_lock),
        _identity_stage(identity, serial),
        *_network_stages(android_network, mac_candidates),
        *_host_preflight_stages(host_preflight),
        _listener_stage(host_network, require_host_listener),
        *_post_preflight_acceptance_stages(),
    ]
    document = _base_document(
        repo=repo,
        host_port=host_port,
        host_preflight_command=host_preflight_command,
        require_host_listener=require_host_listener,
        sfltool_processes=sfltool_processes,
        device_lock=device_lock,
        stages=stages,
        host={
            "network": host_network,
            "preflight": host_preflight,
            "host_preflight_command": host_preflight["command"],
            "require_host_listener": require_host_listener,
        },
        android_device={"identity": identity, "network": android_network},
    )
    device_serial = str(identity.get("device_serial", ""))
    return redact_public_value(document, [serial, device_serial])


def write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--host-port", type=int, default=DEFAULT_HOST_PORT)
    parser.add_argument(
        "--mac-host-ipv4",
        action="append",
        default=[],
        help="Mac LAN IPv4 candidate to test from Android; repeatable. Defaults to non-loopback ifconfig IPv4 addresses.",
    )
    parser.add_argument(
        "--host-preflight-command",
        nargs="+",
        default=list(DEFAULT_HOST_PREFLIGHT_COMMAND),
        help="read-only Host signing/TCC preflight command",
    )
    parser.add_argument(
        "--require-host-listener",
        action="store_true",
        help="block unless TCP host-port is already listening on a Mac LAN IPv4 address",
    )
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    try:
        document = build_document(
            serial=args.serial,
            adb_path=args.adb,
            adb_timeout=args.adb_timeout,
            repo=args.repo,
            host_port=args.host_port,
            mac_host_ipv4=args.mac_host_ipv4,
            host_preflight_command=args.host_preflight_command,
            require_host_listener=args.require_host_listener,
        )
        write_json(args.output, document)
    except (ADBError, ManifestError, OSError, TrustedLANPreflightError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if document["result"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
