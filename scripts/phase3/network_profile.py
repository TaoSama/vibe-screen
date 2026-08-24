#!/usr/bin/env python3
"""Run deterministic transport impairment profiles without requiring root.

This simulator models the observable contract needed by the Internet transport:
control is reliable and ordered, while media is lossy and bounded in favour of
new packets. It is deliberately not presented as an OS-level network test.
"""

from __future__ import annotations

import argparse
import heapq
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


class ProfileError(ValueError):
    """Raised for an invalid profile."""


@dataclass(frozen=True)
class Segment:
    name: str
    duration_ms: int
    latency_ms: int
    jitter_ms: int
    loss_percent: float
    bandwidth_kbps: int
    network_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Segment":
        required = {
            "name",
            "duration_ms",
            "latency_ms",
            "jitter_ms",
            "loss_percent",
            "bandwidth_kbps",
            "network_id",
        }
        missing = required.difference(value)
        if missing:
            raise ProfileError(f"profile segment is missing: {', '.join(sorted(missing))}")
        try:
            segment = cls(**{key: value[key] for key in required})
        except TypeError as error:
            raise ProfileError(f"profile segment has invalid field types: {error}") from error
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in (segment.duration_ms, segment.latency_ms, segment.jitter_ms, segment.bandwidth_kbps)):
            raise ProfileError("duration, latency, jitter, and bandwidth must be integers")
        if not isinstance(segment.loss_percent, (int, float)) or isinstance(segment.loss_percent, bool):
            raise ProfileError("loss_percent must be numeric")
        if not isinstance(segment.name, str) or not isinstance(segment.network_id, str):
            raise ProfileError("name and network_id must be strings")
        if segment.duration_ms <= 0 or segment.latency_ms < 0 or segment.jitter_ms < 0:
            raise ProfileError("duration must be positive; latency and jitter cannot be negative")
        if not 0 <= segment.loss_percent <= 100:
            raise ProfileError("loss_percent must be between 0 and 100")
        if segment.bandwidth_kbps <= 0 or not segment.name or not segment.network_id:
            raise ProfileError("bandwidth must be positive; names cannot be blank")
        return segment


@dataclass(frozen=True)
class Packet:
    channel: str
    sequence: int
    created_ms: int
    size_bytes: int
    keyframe: bool = False


@dataclass
class SimulationResult:
    evidence_scope: str
    evidence_limitations: list[str]
    segments: list[dict[str, Any]]
    route_sequence: list[str]
    seed: int
    duration_ms: int
    control_sent: int
    control_delivered: int
    control_retransmissions: int
    control_ordered: bool
    media_sent: int
    media_delivered: int
    media_network_drops: int
    media_queue_drops: int
    max_media_queue_depth: int
    handoffs: int
    final_network_id: str
    delivered_control_sequences: list[int]
    delivered_media_sequences: list[int]


DEFAULT_PROFILES: dict[str, list[Segment]] = {
    "healthy": [Segment("healthy", 10_000, 35, 5, 0.2, 20_000, "wifi")],
    "moderate": [Segment("moderate", 10_000, 100, 25, 2.0, 10_000, "wifi")],
    "weak": [Segment("weak", 10_000, 160, 60, 12.0, 2_000, "wifi")],
    "bandwidth-step": [
        Segment("wifi-high", 3_000, 35, 5, 0.5, 20_000, "wifi"),
        Segment("wifi-constrained", 3_000, 100, 35, 4.0, 3_000, "wifi"),
        Segment("wifi-recovered", 4_000, 70, 15, 1.0, 12_000, "wifi"),
    ],
    "handoff": [
        Segment("wifi", 3_000, 40, 8, 0.5, 15_000, "wifi"),
        Segment("handoff-gap", 1_000, 350, 150, 45.0, 500, "transition"),
        Segment("cellular", 6_000, 95, 25, 3.0, 6_000, "cellular"),
    ],
    "relay-loss": [
        Segment("relay-healthy", 3_000, 80, 15, 0.5, 12_000, "relay"),
        Segment("relay-loss", 2_000, 450, 200, 70.0, 500, "relay-outage"),
        Segment("relay-recovered", 5_000, 120, 30, 2.0, 8_000, "relay"),
    ],
}


def load_segments(profile: str, profile_file: Path | None) -> list[Segment]:
    if profile_file is None:
        try:
            return DEFAULT_PROFILES[profile]
        except KeyError as error:
            raise ProfileError(f"unknown built-in profile: {profile}") from error
    try:
        raw = json.loads(profile_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(f"cannot read {profile_file}: {error}") from error
    if not isinstance(raw, list) or not raw:
        raise ProfileError("profile file must contain a non-empty JSON array")
    if not all(isinstance(item, dict) for item in raw):
        raise ProfileError("every profile segment must be a JSON object")
    return [Segment.from_mapping(item) for item in raw]


def _segment_at(segments: list[Segment], now_ms: int) -> Segment:
    cursor = 0
    for segment in segments:
        cursor += segment.duration_ms
        if now_ms < cursor:
            return segment
    return segments[-1]


def simulate(
    segments: list[Segment],
    *,
    seed: int,
    media_fps: int = 60,
    control_interval_ms: int = 100,
    media_queue_capacity: int = 2,
    control_retry_ms: int = 120,
) -> SimulationResult:
    if not segments:
        raise ProfileError("at least one segment is required")
    if media_fps <= 0 or control_interval_ms <= 0 or media_queue_capacity <= 0 or control_retry_ms <= 0:
        raise ProfileError("rates, queue capacity, and retry delay must be positive")
    rng = random.Random(seed)
    duration_ms = sum(segment.duration_ms for segment in segments)
    media_interval_ms = max(1, round(1000 / media_fps))
    events: list[tuple[int, int, Packet]] = []
    event_counter = 0
    media_pending: list[tuple[int, int]] = []
    media_live: set[int] = set()
    control_deliveries: dict[int, int] = {}
    media_deliveries: list[tuple[int, int]] = []
    retransmissions = 0
    network_drops = 0
    queue_drops = 0
    max_depth = 0

    def schedule(packet: Packet, send_ms: int) -> None:
        nonlocal event_counter, retransmissions, network_drops
        attempt_ms = send_ms
        while True:
            segment = _segment_at(segments, min(attempt_ms, duration_ms - 1))
            dropped = rng.random() * 100 < segment.loss_percent
            if not dropped:
                break
            if packet.channel == "media":
                network_drops += 1
                media_live.discard(packet.sequence)
                return
            next_attempt = attempt_ms + control_retry_ms
            if next_attempt >= duration_ms:
                return
            retransmissions += 1
            attempt_ms = next_attempt
        jitter = rng.randint(-segment.jitter_ms, segment.jitter_ms) if segment.jitter_ms else 0
        serialization_ms = max(1, round(packet.size_bytes * 8 / segment.bandwidth_kbps))
        delivery_ms = attempt_ms + max(0, segment.latency_ms + jitter) + serialization_ms
        event_counter += 1
        heapq.heappush(events, (delivery_ms, event_counter, packet))

    control_packets = [Packet("control", seq, at, 128) for seq, at in enumerate(range(0, duration_ms, control_interval_ms))]
    media_packets = [Packet("media", seq, at, 24_000, seq % max(1, media_fps * 2) == 0) for seq, at in enumerate(range(0, duration_ms, media_interval_ms))]
    for packet in sorted(control_packets + media_packets, key=lambda item: (item.created_ms, item.channel)):
        while events and events[0][0] <= packet.created_ms:
            delivered_at, _, delivered = heapq.heappop(events)
            if delivered.channel == "control":
                control_deliveries.setdefault(delivered.sequence, delivered_at)
            elif delivered.sequence in media_live:
                media_live.remove(delivered.sequence)
                media_deliveries.append((delivered_at, delivered.sequence))
        if packet.channel == "control":
            schedule(packet, packet.created_ms)
            continue
        media_pending[:] = [(sequence, release) for sequence, release in media_pending if release > packet.created_ms]
        while len(media_pending) >= media_queue_capacity:
            stale, _ = media_pending.pop(0)
            if stale in media_live:
                media_live.discard(stale)
                queue_drops += 1
        segment = _segment_at(segments, packet.created_ms)
        serialization_ms = max(1, round(packet.size_bytes * 8 / segment.bandwidth_kbps))
        transmit_start_ms = max(packet.created_ms, media_pending[-1][1] if media_pending else packet.created_ms)
        media_pending.append((packet.sequence, transmit_start_ms + serialization_ms))
        media_live.add(packet.sequence)
        max_depth = max(max_depth, len(media_pending))
        schedule(packet, packet.created_ms)

    while events:
        delivered_at, _, delivered = heapq.heappop(events)
        if delivered.channel == "control":
            control_deliveries.setdefault(delivered.sequence, delivered_at)
        elif delivered.sequence in media_live:
            media_live.remove(delivered.sequence)
            media_deliveries.append((delivered_at, delivered.sequence))
    # A reliable ordered channel releases only the contiguous prefix; later
    # arrivals remain buffered when an earlier packet never arrives.
    ordered_control: list[int] = []
    while len(ordered_control) in control_deliveries:
        ordered_control.append(len(ordered_control))
    delivered_media = [sequence for _, sequence in sorted(media_deliveries)]
    route_sequence = [segments[0].network_id]
    for segment in segments[1:]:
        if segment.network_id != route_sequence[-1]:
            route_sequence.append(segment.network_id)
    return SimulationResult(
        evidence_scope="deterministic_contract_simulation_only",
        evidence_limitations=[
            "not_os_level_packet_impairment",
            "not_public_internet_path",
            "not_webrtc_ice_or_turn_evidence",
            "not_android_device_or_screen_capture_evidence",
            "not_soak_or_latency_gate_evidence",
        ],
        segments=[asdict(segment) for segment in segments],
        route_sequence=route_sequence,
        seed=seed,
        duration_ms=duration_ms,
        control_sent=len(control_packets),
        control_delivered=len(ordered_control),
        control_retransmissions=retransmissions,
        control_ordered=ordered_control == list(range(len(control_packets))),
        media_sent=len(media_packets),
        media_delivered=len(delivered_media),
        media_network_drops=network_drops,
        media_queue_drops=queue_drops,
        max_media_queue_depth=max_depth,
        handoffs=sum(1 for left, right in zip(segments, segments[1:]) if left.network_id != right.network_id),
        final_network_id=segments[-1].network_id,
        delivered_control_sequences=ordered_control,
        delivered_media_sequences=delivered_media,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(DEFAULT_PROFILES), default="healthy")
    parser.add_argument("--profile-file", type=Path, help="JSON array overriding --profile")
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--media-fps", type=int, default=60)
    parser.add_argument("--control-interval-ms", type=int, default=100)
    parser.add_argument("--media-queue-capacity", type=int, default=2)
    parser.add_argument("--output", type=Path, help="write JSON atomically instead of stdout")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = simulate(
            load_segments(args.profile, args.profile_file),
            seed=args.seed,
            media_fps=args.media_fps,
            control_interval_ms=args.control_interval_ms,
            media_queue_capacity=args.media_queue_capacity,
        )
        rendered = json.dumps(asdict(result), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(args.output)
        else:
            print(rendered, end="")
    except (OSError, ProfileError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
