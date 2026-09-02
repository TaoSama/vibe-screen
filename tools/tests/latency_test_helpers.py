from __future__ import annotations

from pathlib import Path


def minimal_mov(payload: bytes = b"retained-device-video-fragment") -> bytes:
    def box(name: bytes, contents: bytes) -> bytes:
        return (len(contents) + 8).to_bytes(4, "big") + name + contents

    sample_description = box(
        b"stsd",
        b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + box(b"avc1", b"\x00" * 16),
    )
    sample_table = box(b"stbl", sample_description)
    media_info = box(b"minf", sample_table)
    handler = box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 8)
    media = box(b"mdia", handler + media_info)
    track = box(b"trak", box(b"tkhd", b"\x00" * 16) + media)
    movie = box(b"moov", box(b"mvhd", b"\x00" * 16) + track)
    run = box(b"trun", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big"))
    fragment = box(b"moof", box(b"traf", run))
    file_type = box(b"ftyp", b"qt  \x00\x00\x00\x00qt  ")
    return file_type + movie + fragment + box(b"mdat", payload)


def write_minimal_mov(path: Path, payload: bytes = b"retained-device-video-fragment") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(minimal_mov(payload))
