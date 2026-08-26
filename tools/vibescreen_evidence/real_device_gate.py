"""Coordinate real-device readiness and retained gate evidence.

This runner is the fail-closed front door for Android device evidence. It checks
the local macOS Host identity/TCC preflight, ADB transport state, Android app
foreground state, Host listener state, and stream telemetry before a formal
latency, soak, or physical-input gate is claimed. It can also collect a short
soak sample and summarize retained gate reports, but it never grants macOS
privacy permissions, edits Keychain state, starts the Host, or fabricates an
acceptance result from readiness alone.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import json
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError
from .host_log_telemetry import PIPELINE_PATTERN
from .host_rss_gate import derive_gate as derive_host_rss_gate
from .manifest import ManifestError, repository_state
from .soak import SoakRunner, parse_duration
from .soak_public_report import EvidenceInputError, read_json as read_evidence_json


DEFAULT_PACKAGE = "dev.telemachus.display"
DEFAULT_PORT = 54321
DEFAULT_HOST_LOG = Path.home() / "Library/Logs/Telemachus/telemachus.log"
DEFAULT_LOCK_GLOBS = (
    "/tmp/vibe-screen-device-soak.lock",
    "/tmp/vibe-screen-device-android.lock",
)
READINESS_KIND = "android_real_device_gate_readiness"
REDACTED_ADB_SERIAL = "<redacted-adb-serial>"
USER_HOME_PATH_PREFIX = "/" + "Users" + "/"
TCC_DATABASE_PATTERN = re.compile(
    r"/[^\s:'\"]*?/" + "TCC" + r"(?:\." + "db" + r")?",
    flags=re.IGNORECASE,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ProbeResult:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None

    @property
    def combined_output(self) -> str:
        return "\n".join(
            part for part in (self.stdout, self.stderr, self.error or "") if part
        ).strip()

    def as_dict(self, *, include_stdout: bool = True, adb_serial: str | None = None) -> dict[str, Any]:
        document: dict[str, Any] = {
            "command": [_sanitize_text(part, adb_serial=adb_serial) for part in self.command],
            "returncode": self.returncode,
            "stderr": _sanitize_text(self.stderr, adb_serial=adb_serial),
            "error": _sanitize_text(self.error, adb_serial=adb_serial) if self.error else None,
        }
        if include_stdout:
            document["stdout"] = _sanitize_text(self.stdout, adb_serial=adb_serial)
        return document


def _sanitize_text(value: str, *, adb_serial: str | None = None) -> str:
    sanitized = value.replace("\r", "")
    if adb_serial:
        sanitized = sanitized.replace(adb_serial, REDACTED_ADB_SERIAL)
    home = str(Path.home())
    if home and home != "/":
        sanitized = sanitized.replace(home, "~")
    sanitized = re.sub(USER_HOME_PATH_PREFIX + r"[^\s:'\"]+", USER_HOME_PATH_PREFIX + "<redacted-user>", sanitized)
    sanitized = TCC_DATABASE_PATTERN.sub("<redacted-tcc-path>", sanitized)
    return sanitized


def _sanitize_value(value: Any, *, adb_serials: set[str]) -> Any:
    if isinstance(value, str):
        sanitized = value
        for serial in adb_serials:
            if serial:
                sanitized = _sanitize_text(sanitized, adb_serial=serial)
        if not adb_serials:
            sanitized = _sanitize_text(sanitized, adb_serial=None)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, adb_serials=adb_serials) for item in value]
    if isinstance(value, dict):
        return {
            str(_sanitize_value(key, adb_serials=adb_serials)): _sanitize_value(item, adb_serials=adb_serials)
            for key, item in value.items()
        }
    return value


def sanitize_document(document: dict[str, Any], *, adb_serial: str) -> dict[str, Any]:
    serials = {adb_serial}
    android_device = document.get("android_device")
    if isinstance(android_device, dict):
        for key in ("adb_serial", "device_serial"):
            value = android_device.get(key)
            if isinstance(value, str):
                serials.add(value)
    return _sanitize_value(document, adb_serials=serials)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    cwd: Path | None = None,
    command_runner: CommandRunner = subprocess.run,
) -> ProbeResult:
    command_list = list(command)
    try:
        completed = command_runner(
            command_list,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )
    except FileNotFoundError:
        return ProbeResult(command_list, None, "", "", f"executable not found: {command_list[0]}")
    except subprocess.TimeoutExpired as error:
        return ProbeResult(
            command_list,
            None,
            error.stdout or "",
            error.stderr or "",
            f"timed out after {timeout_seconds:g}s",
        )
    except OSError as error:
        return ProbeResult(command_list, None, "", "", f"could not start command: {error}")
    return ProbeResult(
        command_list,
        completed.returncode,
        completed.stdout.strip(),
        completed.stderr.strip(),
    )


def write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def collect_locks(lock_globs: Sequence[str]) -> list[str]:
    locks: list[str] = []
    for pattern in lock_globs:
        locks.extend(glob.glob(pattern))
    return sorted(set(locks))


def _identity_mismatches(
    device: dict[str, Any], expected: dict[str, str | int | None]
) -> list[str]:
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        if expected_value is None:
            continue
        actual = device.get(field)
        if str(actual) != str(expected_value):
            mismatches.append(f"device {field} is '{actual}', expected '{expected_value}'")
    return mismatches


def collect_device(
    *,
    serial: str,
    adb_path: str,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        client = ADBClient(
            serial,
            adb_path=adb_path,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        client.require_device()
        return client.identity(), []
    except (ADBError, ValueError) as error:
        return None, [f"Android device probe failed: {error}"]


def collect_adb_reverse(
    *,
    serial: str,
    adb_path: str,
    port: int,
    timeout_seconds: float,
    configure: bool,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    expected = f"tcp:{port}"
    configure_probe: ProbeResult | None = None
    if configure:
        configure_probe = _run(
            [adb_path, "-s", serial, "reverse", expected, expected],
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    list_probe = _run(
        [adb_path, "-s", serial, "reverse", "--list"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    configured = list_probe.returncode == 0 and any(
        expected in line and line.count(expected) >= 2
        for line in list_probe.stdout.splitlines()
    )
    blockers: list[str] = []
    if configure_probe is not None and (configure_probe.returncode != 0 or configure_probe.error):
        blockers.append(
            f"ADB reverse setup failed: {configure_probe.combined_output or 'no output'}"
        )
    if list_probe.returncode != 0 or list_probe.error:
        blockers.append(
            f"ADB reverse state could not be read: {list_probe.combined_output or 'no output'}"
        )
    elif not configured:
        blockers.append(f"ADB reverse {expected} -> {expected} is not configured for {serial}")
    return {
        "configured": configured,
        "expected_mapping": f"{expected} {expected}",
        "configured_by_runner": configure,
        "configure_probe": configure_probe.as_dict() if configure_probe is not None else None,
        "list_probe": list_probe.as_dict(),
    }, blockers


def _foreground_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if "mCurrentFocus" in line
        or "mFocusedApp" in line
        or "mResumedActivity" in line
        or "topResumedActivity" in line
    ]


def collect_android_app_state(
    *,
    serial: str,
    adb_path: str,
    package_name: str,
    timeout_seconds: float,
    launch: bool,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    launch_probe: ProbeResult | None = None
    if launch:
        launch_probe = _run(
            [
                adb_path,
                "-s",
                serial,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                f"{package_name}/.MainActivity",
                "--ez",
                "auto_connect",
                "true",
            ],
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )

    pidof = _run(
        [adb_path, "-s", serial, "shell", "pidof", package_name],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    window = _run(
        [adb_path, "-s", serial, "shell", "dumpsys", "window"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    activity = _run(
        [adb_path, "-s", serial, "shell", "dumpsys", "activity", "activities"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    pids = [int(item) for item in pidof.stdout.split() if item.isdigit()] if pidof.returncode == 0 else []
    focus_lines = _foreground_lines(window.stdout) + _foreground_lines(activity.stdout)
    foreground = any(package_name in line for line in focus_lines)
    blockers: list[str] = []
    if launch_probe is not None and (launch_probe.returncode != 0 or launch_probe.error):
        blockers.append(f"Android app launch failed: {launch_probe.combined_output or 'no output'}")
    if pidof.returncode not in (0, 1) or pidof.error:
        blockers.append(
            f"Android app process state could not be read: {pidof.combined_output or 'no output'}"
        )
    elif not pids:
        blockers.append(f"Android app process is not running: {package_name}")
    if (window.returncode != 0 or window.error) and (activity.returncode != 0 or activity.error):
        blockers.append(
            "Android foreground state could not be read: "
            + (window.combined_output or activity.combined_output or "no output")
        )
    elif not foreground:
        blockers.append(f"Android app is not foreground: {package_name}")
    return {
        "package": package_name,
        "running": bool(pids),
        "pids": pids,
        "foreground": foreground,
        "started_by_runner": launch,
        "focus_lines": focus_lines,
        "launch_probe": launch_probe.as_dict() if launch_probe is not None else None,
        "pidof": pidof.as_dict(),
        "window_probe": window.as_dict(include_stdout=False),
        "activity_probe": activity.as_dict(include_stdout=False),
    }, blockers


def collect_host_listener(
    *,
    port: int,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    probe = _run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    listeners = []
    for line in probe.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1].isdigit():
            listeners.append({"command": fields[0], "pid": int(fields[1]), "line": line})
    listening = probe.returncode == 0 and bool(listeners or probe.stdout.strip())
    blockers: list[str] = []
    if probe.returncode not in (0, 1) or probe.error:
        blockers.append(f"Mac Host listener state could not be read: {probe.combined_output or 'no output'}")
    elif not listening:
        blockers.append(f"Mac Host is not listening on TCP {port}")
    return {
        "port": port,
        "listening": listening,
        "listeners": listeners,
        "probe": probe.as_dict(),
    }, blockers


def collect_host_preflight(
    *,
    repository_root: Path,
    report_path: Path,
    timeout_seconds: float,
    command_runner: CommandRunner,
) -> tuple[dict[str, Any], list[str]]:
    command = [sys.executable, "scripts/macos_dev_host.py", "preflight", "--report", str(report_path)]
    probe = _run(command, timeout_seconds=timeout_seconds, cwd=repository_root, command_runner=command_runner)
    report_text = ""
    report_exists = report_path.exists()
    if report_exists:
        try:
            report_text = report_path.read_text(encoding="utf-8")
        except OSError as error:
            report_text = f"could not read report: {error}"
    blockers: list[str] = []
    if probe.returncode != 0 or probe.error:
        detail = probe.combined_output or report_text or "no output"
        blockers.append(
            "macOS Host stable-signing/TCC preflight failed: "
            + detail.splitlines()[0]
        )
    return {
        "passed": probe.returncode == 0 and probe.error is None,
        "report_path": str(report_path),
        "report_exists": report_exists,
        "report_excerpt": report_text[:4000],
        "probe": probe.as_dict(),
    }, blockers


def _parse_wall_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_stream_stats_from_jsonl(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    latest: dict[str, Any] | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return None, [f"could not read host telemetry JSONL: {error}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"host telemetry line {line_number}: {error}")
            continue
        if isinstance(record, dict) and record.get("event") == "stream_stats":
            latest = record
    return latest, errors


def collect_stream_telemetry(
    *,
    telemetry_jsonl: Path | None,
    host_log: Path | None,
    freshness_seconds: float,
    require_fresh: bool,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    now = now or datetime.now(timezone.utc)
    blockers: list[str] = []
    telemetry: dict[str, Any] = {
        "required": True,
        "freshness_seconds": freshness_seconds,
        "telemetry_jsonl": str(telemetry_jsonl) if telemetry_jsonl else None,
        "host_log": str(host_log) if host_log else None,
        "ready": False,
        "source": None,
        "latest_stream_stats": None,
        "latest_pipeline_line": None,
        "fresh": None,
        "errors": [],
    }

    if telemetry_jsonl is not None and telemetry_jsonl.exists():
        latest, errors = _latest_stream_stats_from_jsonl(telemetry_jsonl)
        telemetry["errors"].extend(errors)
        if latest is not None:
            timestamp = _parse_wall_time(latest.get("wall_time"))
            age_seconds = (now - timestamp).total_seconds() if timestamp else None
            fresh = age_seconds is not None and 0 <= age_seconds <= freshness_seconds
            telemetry.update(
                {
                    "ready": True if not require_fresh else fresh,
                    "source": "telemetry_jsonl",
                    "latest_stream_stats": latest,
                    "fresh": fresh,
                    "age_seconds": age_seconds,
                }
            )
            if require_fresh and not fresh:
                blockers.append("host stream_stats telemetry is not fresh")
            if telemetry["ready"]:
                return telemetry, blockers

    if host_log is not None and host_log.exists():
        try:
            text = host_log.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            telemetry["errors"].append(f"could not read host log: {error}")
        else:
            match = None
            for candidate in PIPELINE_PATTERN.finditer(text):
                match = candidate
            if match is not None:
                telemetry.update(
                    {
                        "ready": not require_fresh,
                        "source": "host_log",
                        "latest_pipeline_line": match.group(0),
                        "fresh": None,
                    }
                )
                if require_fresh:
                    blockers.append("host log Pipeline telemetry has no machine-readable freshness timestamp")
                else:
                    return telemetry, blockers

    if telemetry["source"] is None:
        blockers.append("no host stream_stats telemetry or Pipeline log line was observed")
    blockers.extend(str(error) for error in telemetry["errors"])
    return telemetry, blockers


def _collect_gate_closure_flags(value: Any) -> list[bool]:
    flags: list[bool] = []
    if isinstance(value, dict):
        for key, item in value.items():
            is_closure_flag = key.startswith("can_close") or key.startswith("gate_can_close")
            if is_closure_flag and isinstance(item, bool):
                flags.append(item)
            else:
                flags.extend(_collect_gate_closure_flags(item))
    elif isinstance(value, list):
        for item in value:
            flags.extend(_collect_gate_closure_flags(item))
    return flags


def _gate_status_from_report(path: Path, *, label: str) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    insufficiencies: list[str] = []
    try:
        report = read_evidence_json(path, label)
    except EvidenceInputError as error:
        return {"path": str(path), "readable": False}, [], [f"{label} is missing or invalid: {error}"]
    verdict = report.get("verdict") or report.get("result") or report.get("status")
    closure_flags = _collect_gate_closure_flags(report)
    can_close = bool(closure_flags) and all(closure_flags)
    if verdict in ("blocked", "failed", "fail"):
        errors.append(f"{label} reports {verdict}")
    elif not can_close:
        insufficiencies.append(f"{label} does not contain a passing gate closure verdict")
    return {
        "path": str(path),
        "readable": True,
        "verdict": verdict,
        "can_close": can_close,
        "closure_flags": closure_flags,
    }, errors, insufficiencies


def _soak_status_from_summary(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        summary = read_evidence_json(path, "soak summary")
    except EvidenceInputError as error:
        return {"path": str(path), "readable": False}, [f"soak summary is missing or invalid: {error}"]
    status = summary.get("status")
    errors = summary.get("errors")
    ready = status == "complete" and errors in (None, [])
    insufficiencies: list[str] = []
    if not ready:
        insufficiencies.append(f"soak summary status is {status}; complete error-free evidence is required")
    return {
        "path": str(path),
        "readable": True,
        "status": status,
        "ready": ready,
        "run_id": summary.get("run_id"),
        "error_count": len(errors) if isinstance(errors, list) else None,
    }, insufficiencies


def summarize_requested_gates(
    *,
    require_soak_summary: bool,
    require_host_rss_gate: bool,
    soak_summary: Path | None,
    soak_samples: Path | None,
    host_rss_gate_output: Path | None,
    latency_reports: Sequence[Path],
    input_summaries: Sequence[Path],
    required_latency_report_count: int = 0,
    required_input_summary_count: int = 0,
) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    insufficiencies: list[str] = []
    requested: dict[str, Any] = {
        "soak": {"required": require_soak_summary, "summary": None},
        "host_rss": {"required": require_host_rss_gate, "report": None},
        "latency": [],
        "input": [],
    }

    if soak_summary is not None:
        status, insufficient = _soak_status_from_summary(soak_summary)
        requested["soak"]["summary"] = status
        insufficiencies.extend(insufficient)
    elif require_soak_summary:
        insufficiencies.append("soak summary is required but --soak-summary was not provided")

    if require_host_rss_gate:
        if soak_summary is None or soak_samples is None:
            insufficiencies.append("Host RSS gate requires --soak-summary and --soak-samples")
        else:
            try:
                report = derive_host_rss_gate(soak_summary, soak_samples)
                requested["host_rss"]["report"] = report
                if host_rss_gate_output is not None:
                    write_json(host_rss_gate_output, report)
                if report.get("verdict") != "pass":
                    insufficiencies.append(
                        f"Host RSS gate verdict is {report.get('verdict')}"
                    )
            except (EvidenceInputError, OSError, ValueError) as error:
                insufficiencies.append(f"Host RSS gate could not be evaluated: {error}")

    for path in latency_reports:
        status, failed, insufficient = _gate_status_from_report(path, label="latency gate report")
        requested["latency"].append(status)
        blockers.extend(failed)
        insufficiencies.extend(insufficient)
    if len(latency_reports) < required_latency_report_count:
        insufficiencies.append(
            f"{required_latency_report_count} latency gate report(s) required, got {len(latency_reports)}"
        )

    for path in input_summaries:
        status, failed, insufficient = _gate_status_from_report(path, label="input gate summary")
        requested["input"].append(status)
        blockers.extend(failed)
        insufficiencies.extend(insufficient)
    if len(input_summaries) < required_input_summary_count:
        insufficiencies.append(
            f"{required_input_summary_count} input gate summary file(s) required, got {len(input_summaries)}"
        )

    return requested, blockers, insufficiencies


def _run_short_soak(
    *,
    serial: str,
    adb_path: str,
    adb_timeout: float,
    package_name: str,
    host_pid: int | None,
    duration_seconds: float,
    interval_seconds: float,
    samples_path: Path,
    summary_path: Path,
    telemetry_jsonl: Path | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        runner = SoakRunner(
            ADBClient(serial, adb_path=adb_path, timeout_seconds=adb_timeout),
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
            output_jsonl=samples_path,
            summary_json=summary_path,
            package_name=package_name,
            host_pid=host_pid,
            telemetry_jsonl=telemetry_jsonl,
            require_stream_telemetry=True,
        )
        summary = runner.run()
    except (ADBError, OSError, ValueError) as error:
        return None, [f"short soak collection failed: {error}"]
    if summary.get("status") != "complete":
        return summary, ["short soak summary is not complete"]
    return summary, []


def build_document(
    *,
    serial: str,
    repository_root: Path,
    evidence_dir: Path,
    adb_path: str = "adb",
    adb_timeout: float = 15.0,
    host_preflight_timeout: float = 30.0,
    package_name: str = DEFAULT_PACKAGE,
    port: int = DEFAULT_PORT,
    lock_globs: Sequence[str] = DEFAULT_LOCK_GLOBS,
    expected_device: dict[str, str | int | None] | None = None,
    host_preflight_report: Path | None = None,
    host_telemetry_jsonl: Path | None = None,
    host_log: Path | None = DEFAULT_HOST_LOG,
    stream_freshness_seconds: float = 120.0,
    require_fresh_stream: bool = True,
    configure_adb_reverse: bool = False,
    launch_android_app: bool = False,
    collect_short_soak: bool = False,
    short_soak_duration_seconds: float = 60.0,
    short_soak_interval_seconds: float = 15.0,
    host_pid: int | None = None,
    require_soak_summary: bool = False,
    require_host_rss_gate: bool = False,
    soak_summary: Path | None = None,
    soak_samples: Path | None = None,
    host_rss_gate_output: Path | None = None,
    latency_reports: Sequence[Path] = (),
    input_summaries: Sequence[Path] = (),
    required_latency_report_count: int = 0,
    required_input_summary_count: int = 0,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    blockers: list[str] = []
    insufficiencies: list[str] = []
    expected_device = expected_device or {}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    host_preflight_report = host_preflight_report or evidence_dir / "host-signing-and-permissions.txt"

    try:
        repository = repository_state(repository_root.resolve())
    except ManifestError as error:
        repository = {"revision": None, "dirty": None, "status_porcelain": [], "error": str(error)}
        blockers.append(f"repository state could not be recorded: {error}")

    locks = collect_locks(lock_globs)
    if locks:
        blockers.append("device lease lock is present; do not start or disturb a competing run")

    host_preflight, host_preflight_blockers = collect_host_preflight(
        repository_root=repository_root,
        report_path=host_preflight_report,
        timeout_seconds=host_preflight_timeout,
        command_runner=command_runner,
    )
    blockers.extend(host_preflight_blockers)

    host_listener, listener_blockers = collect_host_listener(
        port=port,
        timeout_seconds=adb_timeout,
        command_runner=command_runner,
    )
    blockers.extend(listener_blockers)

    android_device: dict[str, Any] | None = None
    adb_reverse: dict[str, Any] | None = None
    android_app: dict[str, Any] | None = None
    if locks:
        blockers.append("Android ADB probes skipped because a device lease lock is present")
    else:
        android_device, device_blockers = collect_device(
            serial=serial,
            adb_path=adb_path,
            timeout_seconds=adb_timeout,
            command_runner=command_runner,
        )
        blockers.extend(device_blockers)
        if android_device is not None:
            blockers.extend(_identity_mismatches(android_device, expected_device))
            adb_reverse, reverse_blockers = collect_adb_reverse(
                serial=serial,
                adb_path=adb_path,
                port=port,
                timeout_seconds=adb_timeout,
                configure=configure_adb_reverse,
                command_runner=command_runner,
            )
            android_app, app_blockers = collect_android_app_state(
                serial=serial,
                adb_path=adb_path,
                package_name=package_name,
                timeout_seconds=adb_timeout,
                launch=launch_android_app,
                command_runner=command_runner,
            )
            blockers.extend(reverse_blockers)
            blockers.extend(app_blockers)

    stream, stream_blockers = collect_stream_telemetry(
        telemetry_jsonl=host_telemetry_jsonl,
        host_log=host_log,
        freshness_seconds=stream_freshness_seconds,
        require_fresh=require_fresh_stream,
    )
    blockers.extend(stream_blockers)

    short_soak: dict[str, Any] | None = None
    if collect_short_soak:
        if blockers:
            insufficiencies.append("short soak skipped because readiness blockers are present")
        else:
            summary_path = evidence_dir / "short-soak-summary.json"
            samples_path = evidence_dir / "short-soak-samples.jsonl"
            short_soak, soak_blockers = _run_short_soak(
                serial=serial,
                adb_path=adb_path,
                adb_timeout=adb_timeout,
                package_name=package_name,
                host_pid=host_pid,
                duration_seconds=short_soak_duration_seconds,
                interval_seconds=short_soak_interval_seconds,
                samples_path=samples_path,
                summary_path=summary_path,
                telemetry_jsonl=host_telemetry_jsonl,
            )
            blockers.extend(soak_blockers)

    requested_gates, gate_blockers, gate_insufficiencies = summarize_requested_gates(
        require_soak_summary=require_soak_summary,
        require_host_rss_gate=require_host_rss_gate,
        soak_summary=soak_summary,
        soak_samples=soak_samples,
        host_rss_gate_output=host_rss_gate_output,
        latency_reports=latency_reports,
        input_summaries=input_summaries,
        required_latency_report_count=required_latency_report_count,
        required_input_summary_count=required_input_summary_count,
    )
    blockers.extend(gate_blockers)
    insufficiencies.extend(gate_insufficiencies)

    if blockers:
        result = "blocked"
    elif insufficiencies:
        result = "insufficient"
    else:
        result = "ready"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": READINESS_KIND,
        "collected_at": _utc_now(),
        "result": result,
        "blockers": blockers,
        "insufficiencies": insufficiencies,
        "repository": repository,
        "locks": locks,
        "expected_device": expected_device,
        "android_device": android_device,
        "host_preflight": host_preflight,
        "host_listener": host_listener,
        "transport": {
            "kind": "usb",
            "port": port,
            "adb_reverse": adb_reverse,
        },
        "android_app": android_app,
        "stream": stream,
        "short_soak": short_soak,
        "requested_gates": requested_gates,
        "safety": {
            "read_only": not (configure_adb_reverse or launch_android_app),
            "starts_host": False,
            "creates_adb_reverse": configure_adb_reverse,
            "launches_android_app": launch_android_app,
            "samples_device": collect_short_soak,
            "modifies_tcc": False,
            "modifies_keychain": False,
            "modifies_android_app_data": False,
        },
        "interpretation": (
            "This readiness record only proves whether prerequisites and supplied gate reports are present. "
            "It does not close latency, soak, Host RSS, or physical-input gates unless the referenced "
            "specialized gate reports independently pass."
        ),
    }


def _append_path(values: Iterable[str] | None) -> list[Path]:
    return [Path(value) for value in values or []]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    parser.add_argument("--output", type=Path, help="JSON output file (default: stdout)")
    parser.add_argument("--evidence-dir", type=Path, default=Path(".build/evidence/real-device-gate"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--host-preflight-timeout", type=float, default=30.0)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lock-glob", action="append", default=list(DEFAULT_LOCK_GLOBS))
    parser.add_argument("--expected-manufacturer")
    parser.add_argument("--expected-model")
    parser.add_argument("--expected-device")
    parser.add_argument("--expected-android-release")
    parser.add_argument("--expected-sdk", type=int)
    parser.add_argument("--host-preflight-report", type=Path)
    parser.add_argument("--host-telemetry-jsonl", type=Path)
    parser.add_argument("--host-log", type=Path, default=DEFAULT_HOST_LOG)
    parser.add_argument("--stream-freshness-seconds", type=float, default=120.0)
    parser.add_argument(
        "--allow-host-log-without-freshness",
        action="store_true",
        help="allow a timestamp-less Host Pipeline log line as stream readiness; use only for legacy diagnostics",
    )
    parser.add_argument("--configure-adb-reverse", action="store_true")
    parser.add_argument("--launch-android-app", action="store_true")
    parser.add_argument("--collect-short-soak", action="store_true")
    parser.add_argument("--short-soak-duration", type=parse_duration, default=parse_duration("60s"))
    parser.add_argument("--short-soak-interval", type=parse_duration, default=parse_duration("15s"))
    parser.add_argument("--host-pid", type=int)
    parser.add_argument("--require-soak-summary", action="store_true")
    parser.add_argument("--require-host-rss-gate", action="store_true")
    parser.add_argument("--soak-summary", type=Path)
    parser.add_argument("--soak-samples", type=Path)
    parser.add_argument("--host-rss-gate-output", type=Path)
    parser.add_argument("--latency-report", action="append", default=[])
    parser.add_argument("--input-summary", action="append", default=[])
    parser.add_argument("--require-latency-report", type=int, default=0)
    parser.add_argument("--require-input-summary", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    if args.host_preflight_timeout <= 0:
        parser.error("--host-preflight-timeout must be positive")
    if args.port <= 0 or args.port > 65535:
        parser.error("--port must be in 1..65535")
    if args.stream_freshness_seconds <= 0:
        parser.error("--stream-freshness-seconds must be positive")
    if args.host_pid is not None and args.host_pid <= 0:
        parser.error("--host-pid must be positive")
    if args.require_latency_report < 0:
        parser.error("--require-latency-report must be non-negative")
    if args.require_input_summary < 0:
        parser.error("--require-input-summary must be non-negative")

    document = build_document(
        serial=args.serial,
        repository_root=args.repo,
        evidence_dir=args.evidence_dir,
        adb_path=args.adb,
        adb_timeout=args.adb_timeout,
        host_preflight_timeout=args.host_preflight_timeout,
        package_name=args.package,
        port=args.port,
        lock_globs=args.lock_glob,
        expected_device={
            "manufacturer": args.expected_manufacturer,
            "model": args.expected_model,
            "device": args.expected_device,
            "android_release": args.expected_android_release,
            "sdk": args.expected_sdk,
        },
        host_preflight_report=args.host_preflight_report,
        host_telemetry_jsonl=args.host_telemetry_jsonl,
        host_log=args.host_log,
        stream_freshness_seconds=args.stream_freshness_seconds,
        require_fresh_stream=not args.allow_host_log_without_freshness,
        configure_adb_reverse=args.configure_adb_reverse,
        launch_android_app=args.launch_android_app,
        collect_short_soak=args.collect_short_soak,
        short_soak_duration_seconds=args.short_soak_duration,
        short_soak_interval_seconds=args.short_soak_interval,
        host_pid=args.host_pid,
        require_soak_summary=args.require_soak_summary,
        require_host_rss_gate=args.require_host_rss_gate,
        soak_summary=args.soak_summary,
        soak_samples=args.soak_samples,
        host_rss_gate_output=args.host_rss_gate_output,
        latency_reports=_append_path(args.latency_report),
        input_summaries=_append_path(args.input_summary),
        required_latency_report_count=args.require_latency_report,
        required_input_summary_count=args.require_input_summary,
    )
    output_document = sanitize_document(document, adb_serial=args.serial)
    write_json(args.output, output_document)
    if output_document["result"] == "ready":
        return 0
    print(
        f"{output_document['result']}: "
        + "; ".join(output_document["blockers"] + output_document["insufficiencies"]),
        file=sys.stderr,
    )
    return 2 if output_document["result"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
