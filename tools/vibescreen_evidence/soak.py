"""ADB soak runner producing raw JSONL samples and a compact summary."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Sequence
import uuid

from . import SCHEMA_VERSION
from .adb import ADBClient, ADBError


PRESET_SECONDS = {"30m": 30 * 60.0, "2h": 2 * 60 * 60.0, "8h": 8 * 60 * 60.0}


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)\s*", value)
    if not match:
        raise argparse.ArgumentTypeError("duration must use ms, s, m, or h (for example 30m)")
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    duration = float(match.group(1)) * multipliers[match.group(2)]
    if duration <= 0:
        raise argparse.ArgumentTypeError("duration must be positive")
    return duration


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _host_rss_kb(pid: int, command_runner: Callable[..., Any]) -> int:
    try:
        completed = command_runner(
            ["ps", "-o", "rss=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"host RSS collection failed: {error}") from error
    if completed.returncode != 0 or not completed.stdout.strip().isdigit():
        detail = completed.stderr.strip() or completed.stdout.strip() or "process not found"
        raise RuntimeError(f"host RSS collection failed for PID {pid}: {detail}")
    return int(completed.stdout.strip())


class SoakRunner:
    def __init__(
        self,
        client: ADBClient,
        *,
        duration_seconds: float,
        interval_seconds: float,
        output_jsonl: Path,
        summary_json: Path,
        package_name: str | None = None,
        host_pid: int | None = None,
        telemetry_jsonl: Path | None = None,
        require_stream_telemetry: bool = False,
        disconnect_hook: Sequence[str] = (),
        reconnect_hook: Sequence[str] = (),
        auto_reconnect: bool = True,
        run_id: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], str] = _utc_now,
        command_runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        if duration_seconds <= 0 or interval_seconds <= 0:
            raise ValueError("duration and interval must be positive")
        self.client = client
        self.duration_seconds = duration_seconds
        self.interval_seconds = interval_seconds
        self.output_jsonl = output_jsonl
        self.summary_json = summary_json
        self.package_name = package_name
        self.host_pid = host_pid
        self.telemetry_jsonl = telemetry_jsonl
        self.require_stream_telemetry = require_stream_telemetry
        self.disconnect_hook = tuple(disconnect_hook)
        self.reconnect_hook = tuple(reconnect_hook)
        self.auto_reconnect = auto_reconnect
        self.run_id = run_id or str(uuid.uuid4())
        self._monotonic = monotonic
        self._sleep = sleep
        self._wall_clock = wall_clock
        self._command_runner = command_runner
        self._hook_errors: list[str] = []
        self._reconnect_count = 0

    def run(self) -> dict[str, Any]:
        self.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        self.summary_json.parent.mkdir(parents=True, exist_ok=True)
        identity: dict[str, Any] = {}
        environment_errors: list[str] = []
        try:
            adb_version = self.client.adb_version()
        except ADBError as error:
            adb_version = None
            environment_errors.append(str(error))
        try:
            self.client.connect()
            identity = self.client.identity()
        except ADBError as error:
            environment_errors.append(str(error))

        samples: list[dict[str, Any]] = []
        started = self._monotonic()
        was_connected: bool | None = None
        interrupted = False
        try:
            with self.output_jsonl.open("w", encoding="utf-8") as output:
                sample_index = 0
                while sample_index == 0 or self._monotonic() - started < self.duration_seconds:
                    elapsed = max(0.0, self._monotonic() - started)
                    sample, connected = self._capture_sample(
                        sample_index, elapsed, identity, was_connected
                    )
                    was_connected = connected
                    samples.append(sample)
                    output.write(json.dumps(sample, sort_keys=True) + "\n")
                    output.flush()
                    sample_index += 1
                    remaining = self.duration_seconds - (self._monotonic() - started)
                    if remaining <= 0:
                        break
                    next_sample = started + sample_index * self.interval_seconds
                    wait_seconds = next_sample - self._monotonic()
                    if wait_seconds <= 0:
                        wait_seconds = min(remaining, self.interval_seconds)
                    self._sleep(max(0.0, min(remaining, wait_seconds)))
        except KeyboardInterrupt:
            interrupted = True

        errors = environment_errors + self._hook_errors
        for sample in samples:
            errors.extend(sample.get("errors", []))
        metrics = self._summarize(samples)
        if self.package_name and metrics["process_running_sample_count"] != metrics["sample_count"]:
            errors.append("application process was not running for every soak sample")
        telemetry_metrics, telemetry_errors = self._summarize_stream_telemetry()
        metrics["stream_telemetry"] = telemetry_metrics
        errors.extend(telemetry_errors)
        status = "partial" if interrupted or errors else "complete"
        if not samples:
            status = "failed"
        summary = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "kind": "soak",
            "status": status,
            "started_at": samples[0]["captured_at"] if samples else self._wall_clock(),
            "finished_at": self._wall_clock(),
            "configuration": {
                "serial": self.client.serial,
                "duration_seconds": self.duration_seconds,
                "interval_seconds": self.interval_seconds,
                "package": self.package_name,
                "host_pid": self.host_pid,
                "telemetry_jsonl": str(self.telemetry_jsonl) if self.telemetry_jsonl else None,
                "require_stream_telemetry": self.require_stream_telemetry,
            },
            "environment": {"adb_version": adb_version, "device_identity": identity},
            "metrics": metrics,
            "errors": errors,
        }
        encoded_summary = json.dumps(summary, indent=2, sort_keys=True) + "\n"
        temporary_summary = self.summary_json.with_suffix(self.summary_json.suffix + ".tmp")
        temporary_summary.write_text(encoded_summary, encoding="utf-8")
        temporary_summary.replace(self.summary_json)
        return summary

    def _summarize_stream_telemetry(self) -> tuple[dict[str, Any], list[str]]:
        counts: dict[str, int] = defaultdict(int)
        errors: list[str] = []
        if self.telemetry_jsonl is not None and self.telemetry_jsonl.exists():
            try:
                for line_number, line in enumerate(
                    self.telemetry_jsonl.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as error:
                        errors.append(f"stream telemetry line {line_number}: {error}")
                        continue
                    event = record.get("event")
                    if isinstance(event, str):
                        counts[event] += 1
            except OSError as error:
                errors.append(f"stream telemetry could not be read: {error}")
        if self.require_stream_telemetry and counts.get("stream_stats", 0) == 0:
            errors.append("required stream_stats telemetry was not observed")
        return {"event_counts": dict(sorted(counts.items()))}, errors

    def _capture_sample(
        self,
        sample_index: int,
        elapsed_seconds: float,
        identity: dict[str, Any],
        was_connected: bool | None,
    ) -> tuple[dict[str, Any], bool]:
        errors: list[str] = []
        connected = True
        try:
            self.client.require_device()
        except ADBError as error:
            connected = False
            errors.append(str(error))

        if not connected and was_connected is not False:
            self._run_hook("disconnect", self.disconnect_hook)
        if not connected and self.auto_reconnect:
            try:
                self.client.connect()
                connected = True
                self._reconnect_count += 1
                self._run_hook("reconnect", self.reconnect_hook)
            except ADBError as error:
                errors.append(f"reconnect: {error}")

        if connected and not identity:
            try:
                identity.update(self.client.identity())
            except ADBError as error:
                errors.append(f"device identity: {error}")

        sample: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "sample_index": sample_index,
            "captured_at": self._wall_clock(),
            "elapsed_seconds": round(elapsed_seconds, 6),
            "device": {"identity": identity, "connected": connected},
            "host": {},
            "errors": errors,
        }
        if connected:
            collected = self.client.sample(self.package_name)
            sample["device"].update(collected["device"])
            sample["errors"].extend(collected["errors"])
        if self.host_pid is not None:
            try:
                sample["host"]["rss_kb"] = _host_rss_kb(
                    self.host_pid, self._command_runner
                )
            except RuntimeError as error:
                sample["errors"].append(str(error))
        return sample, connected

    def _run_hook(self, event: str, command: Sequence[str]) -> None:
        if not command:
            return
        environment = os.environ.copy()
        environment.update(
            {
                "VIBESCREEN_EVENT": event,
                "VIBESCREEN_RUN_ID": self.run_id,
                "VIBESCREEN_ADB_SERIAL": self.client.serial,
            }
        )
        try:
            completed = self._command_runner(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self._hook_errors.append(f"{event} hook could not run: {error}")
            return
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            self._hook_errors.append(
                f"{event} hook failed ({completed.returncode}): {detail}"
            )

    def _summarize(self, samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
        sample_list = list(samples)
        numeric: dict[str, list[float]] = defaultdict(list)
        for sample in sample_list:
            paths = {
                "app_total_pss_kb": ("device", "memory", "app_total_pss_kb"),
                "system_mem_available_kb": (
                    "device",
                    "memory",
                    "system_kb",
                    "MemAvailable",
                ),
                "system_mem_free_kb": ("device", "memory", "system_kb", "MemFree"),
                "battery_level_percent": ("device", "battery", "level"),
                "current_now_ua": ("device", "power", "current_now_ua"),
                "charge_counter_uah": ("device", "power", "charge_counter_uah"),
                "voltage_now_uv": ("device", "power", "voltage_now_uv"),
                "host_rss_kb": ("host", "rss_kb"),
            }
            temperatures = sample.get("device", {}).get("thermal", {}).get("temperatures", [])
            numeric["device_temperature_c"].extend(
                float(value["celsius"])
                for value in temperatures
                if isinstance(value.get("celsius"), (int, float))
            )
            for name, path in paths.items():
                value: Any = sample
                for component in path:
                    value = value.get(component) if isinstance(value, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric[name].append(float(value))
        statistics = {
            name: {
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "samples": len(values),
            }
            for name, values in numeric.items()
            if values
        }
        return {
            "sample_count": len(sample_list),
            "connected_sample_count": sum(
                bool(sample.get("device", {}).get("connected")) for sample in sample_list
            ),
            "process_running_sample_count": sum(
                sample.get("device", {}).get("process", {}).get("running") is True
                for sample in sample_list
            ),
            "samples_with_errors": sum(bool(sample.get("errors")) for sample in sample_list),
            "reconnect_count": self._reconnect_count,
            "statistics": statistics,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="exact ADB device serial")
    duration = parser.add_mutually_exclusive_group(required=True)
    duration.add_argument("--preset", choices=sorted(PRESET_SECONDS))
    duration.add_argument("--duration", type=parse_duration, help="custom duration, e.g. 45m")
    parser.add_argument("--interval", type=parse_duration, default=parse_duration("30s"))
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--package", help="Android package whose process/RSS is sampled")
    parser.add_argument("--host-pid", type=int, help="optional host process PID")
    parser.add_argument("--telemetry-jsonl", type=Path, help="host JSONL written via VIBE_SCREEN_TELEMETRY_PATH")
    parser.add_argument("--require-stream-telemetry", action="store_true")
    parser.add_argument("--adb", default="adb", help="ADB executable path")
    parser.add_argument("--adb-timeout", type=float, default=15.0)
    parser.add_argument("--disconnect-hook", help="command run once when disconnect is detected")
    parser.add_argument("--reconnect-hook", help="command run after automatic reconnect")
    parser.add_argument("--no-auto-reconnect", action="store_true")
    parser.add_argument("--run-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.host_pid is not None and arguments.host_pid <= 0:
        parser.error("--host-pid must be positive")
    if arguments.adb_timeout <= 0:
        parser.error("--adb-timeout must be positive")
    duration = PRESET_SECONDS[arguments.preset] if arguments.preset else arguments.duration
    summary_path = arguments.summary_json or arguments.output_jsonl.with_suffix(".summary.json")
    try:
        runner = SoakRunner(
            ADBClient(
                arguments.serial,
                adb_path=arguments.adb,
                timeout_seconds=arguments.adb_timeout,
            ),
            duration_seconds=duration,
            interval_seconds=arguments.interval,
            output_jsonl=arguments.output_jsonl,
            summary_json=summary_path,
            package_name=arguments.package,
            host_pid=arguments.host_pid,
            telemetry_jsonl=arguments.telemetry_jsonl,
            require_stream_telemetry=arguments.require_stream_telemetry,
            disconnect_hook=shlex.split(arguments.disconnect_hook or ""),
            reconnect_hook=shlex.split(arguments.reconnect_hook or ""),
            auto_reconnect=not arguments.no_auto_reconnect,
            run_id=arguments.run_id,
        )
        summary = runner.run()
    except (ADBError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
