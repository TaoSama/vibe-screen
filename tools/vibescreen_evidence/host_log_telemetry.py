"""Reshape live Telemachus host `Pipeline:` log lines into documented
`stream_stats` host-telemetry JSONL.

This is a faithful re-encoder, not a data source: it copies the fps/dropped
numbers the host already prints to its log into the versioned telemetry record
shape consumed by soak_report.py. It never synthesizes stream data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from typing import Sequence


SCHEMA_VERSION = 1
EVENT_NAME = "stream_stats"
PIPELINE_PATTERN = re.compile(
    r"Pipeline:\s*(?P<fps>[0-9]+(?:\.[0-9]+)?)fps,\s*"
    r"(?P<mbps>[0-9]+(?:\.[0-9]+)?)Mbps,\s*"
    r"avg frame age:\s*(?P<age_ms>[0-9]+(?:\.[0-9]+)?)ms,\s*"
    r"dropped:\s*(?P<dropped>[0-9]+)"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _last_pipeline_line(text: str) -> re.Match[str] | None:
    match = None
    for candidate in PIPELINE_PATTERN.finditer(text):
        match = candidate
    return match


def collect(
    log_path: Path,
    output_jsonl: Path,
    *,
    duration_seconds: float,
    interval_seconds: float,
    monotonic=time.monotonic,
    sleep=time.sleep,
    wall_clock=_utc_now,
) -> int:
    if duration_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("duration and interval must be positive")
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    started = monotonic()
    index = 0
    with output_jsonl.open("w", encoding="utf-8") as output:
        while index == 0 or monotonic() - started < duration_seconds:
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                print(f"warning: could not read {log_path}: {error}", file=sys.stderr)
                text = ""
            match = _last_pipeline_line(text)
            if match is not None:
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "event": EVENT_NAME,
                    "wall_time": wall_clock(),
                    "monotonic_ns": int(max(0.0, monotonic() - started) * 1_000_000_000),
                    "attributes": {
                        "fps": float(match.group("fps")),
                        "mbps": float(match.group("mbps")),
                        "avg_frame_age_ms": float(match.group("age_ms")),
                        "dropped": int(match.group("dropped")),
                    },
                }
                output.write(json.dumps(record, sort_keys=True) + "\n")
                output.flush()
                written += 1
            else:
                print("warning: no Pipeline line found in host log yet", file=sys.stderr)
            index += 1
            remaining = duration_seconds - (monotonic() - started)
            if remaining <= 0:
                break
            next_at = started + index * interval_seconds
            wait = next_at - monotonic()
            if wait <= 0:
                wait = min(remaining, interval_seconds)
            sleep(max(0.0, min(remaining, wait)))
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True, help="Telemachus host log path")
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    if arguments.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    try:
        written = collect(
            arguments.log,
            arguments.output_jsonl,
            duration_seconds=arguments.duration_seconds,
            interval_seconds=arguments.interval_seconds,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"records_written": written}, sort_keys=True))
    return 0 if written > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
