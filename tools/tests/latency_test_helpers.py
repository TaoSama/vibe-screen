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


def sampled_mov(frame_count: int, payload: bytes = b"retained-device-video-fragment") -> bytes:
    if frame_count < 1:
        raise ValueError("frame_count must be positive")
    sample = payload or b"x"
    sample_payload = sample * frame_count
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isommp42")
    mdat_content_offset = len(ftyp) + 8
    mdat = _box(b"mdat", sample_payload)
    moov = _box(
        b"moov",
        _box(b"mvhd", b"\x00" * 16)
        + _sampled_track(b"vide", b"avc1", frame_count, mdat_content_offset, len(sample)),
    )
    return ftyp + mdat + moov


def sampled_mov_with_audio_track(
    video_frame_count: int,
    audio_sample_count: int,
    video_payload: bytes = b"retained-device-video-fragment",
    audio_payload: bytes = b"retained-device-audio-fragment",
) -> bytes:
    if video_frame_count < 1 or audio_sample_count < 1:
        raise ValueError("sample counts must be positive")
    video_sample = video_payload or b"x"
    audio_sample = audio_payload or b"a"
    sample_payload = (video_sample * video_frame_count) + (audio_sample * audio_sample_count)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isommp42")
    mdat_content_offset = len(ftyp) + 8
    mdat = _box(b"mdat", sample_payload)
    moov = _box(
        b"moov",
        _box(b"mvhd", b"\x00" * 16)
        + _sampled_track(b"vide", b"avc1", video_frame_count, mdat_content_offset, len(video_sample))
        + _sampled_track(b"soun", b"mp4a", audio_sample_count, mdat_content_offset, len(audio_sample)),
    )
    return ftyp + mdat + moov


def sampled_mov_with_two_video_tracks(
    first_video_frame_count: int,
    second_video_frame_count: int,
    first_video_payload: bytes = b"retained-device-first-video-fragment",
    second_video_payload: bytes = b"retained-device-second-video-fragment",
) -> bytes:
    if first_video_frame_count < 1 or second_video_frame_count < 1:
        raise ValueError("sample counts must be positive")
    first_sample = first_video_payload or b"x"
    second_sample = second_video_payload or b"y"
    sample_payload = (first_sample * first_video_frame_count) + (second_sample * second_video_frame_count)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isommp42")
    mdat_content_offset = len(ftyp) + 8
    mdat = _box(b"mdat", sample_payload)
    moov = _box(
        b"moov",
        _box(b"mvhd", b"\x00" * 16)
        + _sampled_track(b"vide", b"avc1", first_video_frame_count, mdat_content_offset, len(first_sample))
        + _sampled_track(b"vide", b"hvc1", second_video_frame_count, mdat_content_offset, len(second_sample)),
    )
    return ftyp + mdat + moov


def _sampled_track(
    handler_type: bytes,
    sample_entry_type: bytes,
    sample_count: int,
    mdat_content_offset: int,
    sample_size: int,
) -> bytes:
    stsd = _box(
        b"stsd",
        b"\x00\x00\x00\x00"
        + (1).to_bytes(4, "big")
        + _box(sample_entry_type, b"\x00" * 16),
    )
    stsz = _box(
        b"stsz",
        b"\x00\x00\x00\x00"
        + sample_size.to_bytes(4, "big")
        + sample_count.to_bytes(4, "big"),
    )
    stco = _box(
        b"stco",
        b"\x00\x00\x00\x00"
        + (1).to_bytes(4, "big")
        + mdat_content_offset.to_bytes(4, "big"),
    )
    stbl = _box(b"stbl", stsd + stsz + stco)
    minf = _box(b"minf", stbl)
    hdlr = _box(b"hdlr", b"\x00" * 8 + handler_type + b"\x00" * 8)
    mdia = _box(b"mdia", hdlr + minf)
    return _box(b"trak", _box(b"tkhd", b"\x00" * 16) + mdia)


def write_minimal_mov(path: Path, payload: bytes = b"retained-device-video-fragment") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(minimal_mov(payload))
