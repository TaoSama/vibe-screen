"""Summarize macOS Host TCP file descriptors from lsof output.

This diagnostic is intentionally read-only. It can parse saved lsof snapshots
from a device run or sample one local Host PID/port pair without touching adb.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Sequence

from . import SCHEMA_VERSION


DEFAULT_PORT = 54321
DEFAULT_SAMPLES = 1
DEFAULT_INTERVAL_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 10.0
LSOF_ROW = re.compile(
    r"^(?P<command>\S+)\s+"
    r"(?P<pid>\d+)\s+"
    r"(?P<user>\S+)\s+"
    r"(?P<fd>\d+[A-Za-z]*)\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<device>\S+)\s+"
    r"(?P<sizeoff>\S+)\s+"
    r"(?P<node>\S+)\s+"
    r"(?P<name>.+?)"
    r"(?:\s+\((?P<state>[A-Z_]+)\))?$"
)


@dataclass(frozen=True)
class LsofEntry:
    command: str
    pid: int
    fd: str
    device: str
    name: str
    state: str


class SocketFDArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_lsof(text: str) -> list[LsofEntry]:
    entries: list[LsofEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("$") or line.startswith("COMMAND"):
            continue
        match = LSOF_ROW.match(line)
        if not match:
            continue
        entries.append(
            LsofEntry(
                command=match.group("command"),
                pid=int(match.group("pid")),
                fd=match.group("fd"),
                device=match.group("device"),
                name=match.group("name"),
                state=match.group("state") or "UNKNOWN",
            )
        )
    return entries


def summarize(entries: Sequence[LsofEntry]) -> dict[str, object]:
    states = Counter(entry.state for entry in entries)
    unique_devices = {entry.device for entry in entries}
    closed = [entry for entry in entries if entry.state == "CLOSED"]
    established = [entry for entry in entries if entry.state == "ESTABLISHED"]
    listening = [entry for entry in entries if entry.state == "LISTEN"]
    return {
        "entry_count": len(entries),
        "unique_socket_devices": len(unique_devices),
        "states": dict(sorted(states.items())),
        "closed_count": len(closed),
        "established_count": len(established),
        "listen_count": len(listening),
        "closed_fds": [entry.fd for entry in closed],
        "closed_devices": [entry.device for entry in closed],
    }


def verdict_for(samples: Sequence[dict[str, object]]) -> tuple[str, list[str]]:
    if not samples:
        return "insufficient", ["no lsof samples were provided"]
    empty_labels = [
        str(sample["label"])
        for sample in samples
        if int(sample["summary"]["entry_count"]) == 0
    ]
    if empty_labels:
        return (
            "insufficient",
            [
                "lsof produced no TCP entries for the requested Host PID/port: "
                + ", ".join(empty_labels)
            ],
        )
    closed_counts = [int(sample["summary"]["closed_count"]) for sample in samples]
    max_closed = max(closed_counts)
    reasons: list[str] = []
    if max_closed > 0:
        reasons.append(
            f"process still owns {max_closed} TCP socket FD(s) in CLOSED state"
        )
    if len(closed_counts) >= 2 and closed_counts[-1] > closed_counts[0]:
        reasons.append("CLOSED socket FD count increased during the sampling window")
    if reasons:
        return "fail", reasons
    return "pass", ["no CLOSED TCP socket FDs were observed"]


def run_lsof(pid: int, port: int) -> str:
    command = ["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"failed to run {' '.join(command)}: {error}") from error
    if completed.returncode not in (0, 1):
        raise RuntimeError(
            f"{' '.join(command)} exited with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def build_report(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    verdict, reasons = verdict_for(samples)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "host_socket_fd_diagnostic",
        "verdict": verdict,
        "reasons": reasons,
        "samples": list(samples),
        "gate": {
            "can_close_host_rss_no_growth_gate": False,
            "interpretation": (
                "This diagnostic only evaluates whether the Host process still "
                "owns TCP file descriptors after their TCP state has reached "
                "CLOSED. It is not a memory-growth or two-hour soak gate."
            ),
        },
    }


def sample_from_text(label: str, text: str) -> dict[str, object]:
    return {
        "label": label,
        "captured_at": utc_now(),
        "summary": summarize(parse_lsof(text)),
    }


def collect_samples(
    pid: int,
    port: int,
    count: int,
    interval_seconds: float,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for index in range(count):
        samples.append(sample_from_text(f"sample-{index}", run_lsof(pid, port)))
        if index + 1 < count:
            time.sleep(interval_seconds)
    return samples


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = SocketFDArgumentParser(
        description="Summarize Host TCP socket FD state from lsof output."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input",
        action="append",
        type=Path,
        help="Saved lsof snapshot. May be supplied more than once.",
    )
    source.add_argument("--pid", type=int, help="Host process ID to sample.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--output", type=Path, help="Path for the JSON report.")
    args = parser.parse_args(argv)
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.interval_seconds < 0:
        parser.error("--interval-seconds must be non-negative")
    if args.port < 1 or args.port > 65535:
        parser.error("--port must be in 1..65535")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.input:
            samples = [
                sample_from_text(str(path), path.read_text(encoding="utf-8"))
                for path in args.input
            ]
        else:
            samples = collect_samples(
                args.pid,
                args.port,
                args.samples,
                args.interval_seconds,
            )
        report = build_report(samples)
    except (OSError, RuntimeError) as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": "host_socket_fd_diagnostic",
            "verdict": "insufficient",
            "reasons": [str(error)],
            "samples": [],
            "gate": {"can_close_host_rss_no_growth_gate": False},
        }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return {"pass": 0, "insufficient": 1, "fail": 2}[str(report["verdict"])]


if __name__ == "__main__":
    raise SystemExit(main())
