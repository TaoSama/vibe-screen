from __future__ import annotations

from pathlib import Path


_READABLE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "latency"
    / "external-camera-valid"
    / "raw-camera-fixture.mov"
)


def _box(name: bytes, contents: bytes) -> bytes:
    return (len(contents) + 8).to_bytes(4, "big") + name + contents


def minimal_mov(payload: bytes = b"retained-device-video-fragment") -> bytes:
    return _READABLE_FIXTURE.read_bytes() + _box(b"free", payload)


def write_minimal_mov(path: Path, payload: bytes = b"retained-device-video-fragment") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(minimal_mov(payload))
