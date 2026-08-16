"""Collect a <=17-minute macOS Host memory regression diagnostic.

This command cannot close the formal two-hour RSS gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Sequence
import uuid

from . import SCHEMA_VERSION
from .host_memory_analysis import INTERPRETATION, analyze_records, thresholds
from .host_memory_parsers import (
    HeapSnapshot,
    MemoryToolParseError,
    parse_footprint_file,
    parse_heap_summary,
    parse_vmmap_summary,
)


DIAGNOSTIC_KIND = "host_memory_short_diagnostic"
SAMPLE_KIND = "host_memory_sample"
DEFAULT_DURATION_SECONDS = 15 * 60.0
MINIMUM_DURATION_SECONDS = 10 * 60.0
# Leave three minutes for the final heap snapshot and report generation so one
# invocation remains below the task's 20-minute command ceiling.
MAXIMUM_DURATION_SECONDS = 17 * 60.0
DEFAULT_INTERVAL_SECONDS = 30.0
MINIMUM_INTERVAL_SECONDS = 10.0
MAXIMUM_INTERVAL_SECONDS = 30.0
COMMAND_TIMEOUT_SECONDS = 20.0
DEFAULT_WATCHED_CLASSES = (
    "ObservationRegistrar",
    "_SetStorage<Int>",
    "AutoreleasePool",
    "NSAutoreleasePool",
    "FrameContext",
    "PixelBufferBox",
    "CVPixelBuffer",
    "IOSurface",
)


class DiagnosticArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise RuntimeError(f"{' '.join(command[:2])} failed: {detail}")
    return completed.stdout


def _heap_payload(snapshot: HeapSnapshot, watched: tuple[str, ...]) -> dict[str, Any]:
    selected = sorted(
        snapshot.classes, key=lambda item: item.allocated_bytes, reverse=True
    )[:20]
    selected_names = {item.name for item in selected}
    normalized_watched = tuple(name.casefold() for name in watched)
    selected.extend(
        item
        for item in snapshot.classes
        if item.name not in selected_names
        and any(name in item.name.casefold() for name in normalized_watched)
    )
    return {
        "node_count": snapshot.node_count,
        "allocated_bytes": snapshot.allocated_bytes,
        "classes": [
            {
                "name": item.name,
                "count": item.count,
                "allocated_bytes": item.allocated_bytes,
            }
            for item in selected
        ],
    }


def _capture_sample(
    pid: int,
    *,
    index: int,
    elapsed_seconds: float,
    footprint_path: Path,
    capture_heap: bool,
    watched_classes: tuple[str, ...],
) -> dict[str, Any]:
    errors: list[str] = []
    memory: dict[str, int] = {}
    heap: dict[str, Any] | None = None
    try:
        rss = _run_command(["/bin/ps", "-o", "rss=", "-p", str(pid)])
        memory["rss_bytes"] = int(rss.strip()) * 1024
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        errors.append(f"rss: {error}")
    try:
        _run_command(
            ["/usr/bin/footprint", "-j", str(footprint_path), "-p", str(pid)]
        )
        footprint = parse_footprint_file(footprint_path, pid=pid)
        memory.update(
            physical_footprint_bytes=footprint.physical_footprint_bytes,
            malloc_small_dirty_bytes=footprint.category_dirty_bytes.get(
                "MALLOC_SMALL", 0
            ),
            malloc_large_dirty_bytes=footprint.category_dirty_bytes.get(
                "MALLOC_LARGE", 0
            ),
            iosurface_dirty_bytes=sum(
                value
                for name, value in footprint.category_dirty_bytes.items()
                if "IOSurface" in name
            ),
        )
    except (RuntimeError, MemoryToolParseError, subprocess.TimeoutExpired) as error:
        errors.append(f"footprint: {error}")
    try:
        vmmap = parse_vmmap_summary(
            _run_command(["/usr/bin/vmmap", "-summary", str(pid)])
        )
        memory.update(
            vmmap_physical_footprint_bytes=vmmap.physical_footprint_bytes,
            malloc_zone_dirty_bytes=vmmap.malloc_zone_dirty_bytes,
            malloc_zone_allocated_bytes=vmmap.malloc_zone_allocated_bytes,
            malloc_zone_fragmentation_bytes=vmmap.malloc_zone_fragmentation_bytes,
        )
    except (RuntimeError, MemoryToolParseError, subprocess.TimeoutExpired) as error:
        errors.append(f"vmmap: {error}")
    if capture_heap:
        try:
            heap = _heap_payload(
                parse_heap_summary(
                    _run_command(["/usr/bin/heap", "-q", "-H", "-s", str(pid)])
                ),
                watched_classes,
            )
        except (RuntimeError, MemoryToolParseError, subprocess.TimeoutExpired) as error:
            errors.append(f"heap: {error}")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SAMPLE_KIND,
        "sample_index": index,
        "captured_at": _utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "memory": memory,
        "heap": heap,
        "errors": errors,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} line {line_number}: invalid JSON: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"{path} line {line_number}: record must be an object")
        records.append(record)
    return records


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _failure_report(pid: int, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": DIAGNOSTIC_KIND,
        "derivation_status": "failed",
        "verdict": "insufficient",
        "attribution": "inconclusive",
        "host_pid": pid,
        "window": {},
        "thresholds": thresholds(),
        "sufficiency": {},
        "metrics": {},
        "telemetry": {},
        "errors": [reason],
        "reasons": ["the short-run diagnostic could not be completed"],
        "interpretation": INTERPRETATION,
    }


def collect(
    *,
    pid: int,
    duration_seconds: float,
    interval_seconds: float,
    telemetry_path: Path,
    samples_path: Path,
    output_path: Path,
    watched_classes: tuple[str, ...],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    _run_command(["/bin/ps", "-o", "rss=", "-p", str(pid)])
    if not telemetry_path.is_file():
        raise ValueError(f"host telemetry file does not exist: {telemetry_path}")
    run_id = str(uuid.uuid4())
    started_at = _utc_now()
    started = monotonic()
    midpoint_captured = False
    records: list[dict[str, Any]] = []
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibescreen-memory-") as raw_temp:
        footprint_path = Path(raw_temp) / "footprint.json"
        with samples_path.open("w", encoding="utf-8") as output:
            index = 0
            while True:
                elapsed = min(duration_seconds, max(0.0, monotonic() - started))
                final = elapsed >= duration_seconds
                midpoint = not midpoint_captured and elapsed >= duration_seconds / 2
                if midpoint:
                    midpoint_captured = True
                record = _capture_sample(
                    pid,
                    index=index,
                    elapsed_seconds=elapsed,
                    footprint_path=footprint_path,
                    capture_heap=index == 0 or midpoint or final,
                    watched_classes=watched_classes,
                )
                record["elapsed_seconds"] = max(0.0, monotonic() - started)
                record["run_id"] = run_id
                records.append(record)
                output.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                output.flush()
                if any(error.startswith("rss:") for error in record["errors"]):
                    break
                if final:
                    break
                index += 1
                target = min(duration_seconds, index * interval_seconds)
                sleep(max(0.0, target - (monotonic() - started)))

    finished_at = _utc_now()
    analysis = analyze_records(
        records,
        _read_jsonl(telemetry_path),
        started_at=started_at,
        finished_at=finished_at,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": DIAGNOSTIC_KIND,
        "derivation_status": "complete",
        "run_id": run_id,
        "host_pid": pid,
        "window": {
            "started_at": started_at,
            "finished_at": finished_at,
            "requested_duration_seconds": duration_seconds,
            "interval_seconds": interval_seconds,
            "sample_count": len(records),
        },
        "watched_heap_class_substrings": list(watched_classes),
        "thresholds": thresholds(),
        **analysis,
        "interpretation": INTERPRETATION,
    }
    _write_json(output_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticArgumentParser(
        description=__doc__,
        epilog=(
            "Exit 0 means the complete short window passed; exit 2 means the "
            "short window failed on attributed memory growth or a production "
            "stream anomaly; exit 1 means the evidence was insufficient. No "
            "exit code closes the formal two-hour gate."
        ),
    )
    parser.add_argument("--host-pid", type=int, required=True)
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--telemetry-jsonl", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch-class", action="append", default=[])
    return parser


def _watched_classes(custom: Sequence[str]) -> tuple[str, ...]:
    normalized_custom = (name.strip() for name in custom)
    return tuple(
        dict.fromkeys(
            (*DEFAULT_WATCHED_CLASSES, *(name for name in normalized_custom if name))
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.host_pid <= 0:
        parser.error("--host-pid must be positive")
    if not MINIMUM_DURATION_SECONDS <= arguments.duration_seconds <= MAXIMUM_DURATION_SECONDS:
        parser.error("--duration-seconds must be between 600 and 1020")
    if not MINIMUM_INTERVAL_SECONDS <= arguments.interval_seconds <= MAXIMUM_INTERVAL_SECONDS:
        parser.error("--interval-seconds must be between 10 and 30")
    try:
        report = collect(
            pid=arguments.host_pid,
            duration_seconds=arguments.duration_seconds,
            interval_seconds=arguments.interval_seconds,
            telemetry_path=arguments.telemetry_jsonl,
            samples_path=arguments.samples,
            output_path=arguments.output,
            watched_classes=_watched_classes(arguments.watch_class),
        )
    except Exception as error:
        report = _failure_report(arguments.host_pid, str(error))
        try:
            _write_json(arguments.output, report)
        except OSError:
            print("error: host memory diagnostic output could not be written", file=sys.stderr)
            return 1
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return {"pass": 0, "fail": 2, "insufficient": 1}.get(
        report.get("verdict"), 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
