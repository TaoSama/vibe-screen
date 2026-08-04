#!/usr/bin/env python3
"""Generate deterministic Protocol v1 cross-platform golden fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


FIXTURE_ROOT = Path(__file__).resolve().parent
CONTRACT_ROOT = FIXTURE_ROOT.parents[2]
JSON_ROOT = FIXTURE_ROOT / "json"
OUTPUT_ROOT = FIXTURE_ROOT / "bin"
BUF_VERSION = "v1.72.0"
BUF_COMMAND = ["go", "run", f"github.com/bufbuild/buf/cmd/buf@{BUF_VERSION}"]
ENVELOPE_TYPE = "vibescreen.protocol.v1.Envelope"
MEDIA_HEADER_TYPE = "vibescreen.protocol.v1.MediaPacketHeader"
CONTROL_CHANNEL = 1
VIDEO_CHANNEL = 2
MAXIMUM_FRAME_PAYLOAD_BYTES = 16 * 1024 * 1024
UPGRADE_OFFER = bytes([0x0D])
UPGRADE_ACKNOWLEDGEMENT = bytes([0x0D, 0x01])
ANNEX_B_PAYLOAD = bytes.fromhex("0000000140010c01ff00aa55")

CONTROL_FIXTURES = (
    "client_hello",
    "host_hello",
    "session_accepted",
    "list_displays_request",
    "list_displays_response",
    "start_display_request",
    "start_display_response",
    "video_config",
    "video_config_result",
    "touch",
    "ping",
    "pong",
    "protocol_error",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in a temporary directory and fail if checked fixtures drift",
    )
    return parser.parse_args()


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint value must be non-negative")
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def convert_json(source: Path, message_type: str, destination: Path) -> None:
    command = [
        *BUF_COMMAND,
        "convert",
        str(CONTRACT_ROOT),
        f"--type={message_type}",
        f"--from={source}#format=json",
        f"--to={destination}#format=binpb",
    ]
    subprocess.run(command, check=True, cwd=CONTRACT_ROOT)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_metadata(source: dict[str, object]) -> dict[str, object]:
    payload_keys = [key for key in source if key not in {
        "protocolVersion",
        "messageId",
        "correlationId",
        "sessionId",
        "sessionEpoch",
        "sentAtMonotonicNs",
    }]
    if len(payload_keys) != 1:
        raise ValueError(f"Envelope JSON must have exactly one payload, found {payload_keys}")
    return {
        "protocolVersion": source["protocolVersion"],
        "messageId": source["messageId"],
        "correlationId": source.get("correlationId", "0"),
        "sessionEpoch": source.get("sessionEpoch", "0"),
        "sentAtMonotonicNs": source["sentAtMonotonicNs"],
        "payloadCase": payload_keys[0],
    }


def generate(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []

    for fixture_name in CONTROL_FIXTURES:
        source_path = JSON_ROOT / f"{fixture_name}.json"
        destination = output_root / f"{fixture_name}.binpb"
        convert_json(source_path, ENVELOPE_TYPE, destination)
        source = json.loads(source_path.read_text())
        manifest_entries.append({
            "name": fixture_name,
            "messageType": ENVELOPE_TYPE,
            "source": f"json/{fixture_name}.json",
            "binary": f"bin/{fixture_name}.binpb",
            "channel": CONTROL_CHANNEL,
            "byteLength": destination.stat().st_size,
            "sha256": sha256(destination),
            "expected": expected_metadata(source),
        })

    media_header_path = output_root / "media_packet_header.binpb"
    convert_json(JSON_ROOT / "media_packet_header.json", MEDIA_HEADER_TYPE, media_header_path)
    media_packet_path = output_root / "media_packet.bin"
    media_header = media_header_path.read_bytes()
    media_packet_path.write_bytes(encode_varint(len(media_header)) + media_header + ANNEX_B_PAYLOAD)

    offer_path = output_root / "upgrade_offer.bin"
    acknowledgement_path = output_root / "upgrade_acknowledgement.bin"
    offer_path.write_bytes(UPGRADE_OFFER)
    acknowledgement_path.write_bytes(UPGRADE_ACKNOWLEDGEMENT)

    media_source = json.loads((JSON_ROOT / "media_packet_header.json").read_text())
    manifest = {
        "protocolVersion": 1,
        "bufVersion": BUF_VERSION,
        "transport": {
            "header": "channel:uint8,payload_length:uint32-big-endian",
            "controlChannel": CONTROL_CHANNEL,
            "videoChannel": VIDEO_CHANNEL,
            "maximumPayloadBytes": MAXIMUM_FRAME_PAYLOAD_BYTES,
            "upgradeOfferHex": UPGRADE_OFFER.hex(),
            "upgradeOfferSha256": sha256(offer_path),
            "upgradeAcknowledgementHex": UPGRADE_ACKNOWLEDGEMENT.hex(),
            "upgradeAcknowledgementSha256": sha256(acknowledgement_path),
        },
        "controlFixtures": manifest_entries,
        "mediaFixture": {
            "name": "media_packet",
            "headerMessageType": MEDIA_HEADER_TYPE,
            "source": "json/media_packet_header.json",
            "headerBinary": "bin/media_packet_header.binpb",
            "binary": "bin/media_packet.bin",
            "channel": VIDEO_CHANNEL,
            "annexBPayloadHex": ANNEX_B_PAYLOAD.hex(),
            "byteLength": media_packet_path.stat().st_size,
            "sha256": sha256(media_packet_path),
            "headerSha256": sha256(media_header_path),
            "expectedHeader": media_source,
        },
    }
    (output_root.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def check_generated() -> None:
    with tempfile.TemporaryDirectory(prefix="vibescreen-protocol-fixtures-") as temporary:
        generated_root = Path(temporary) / "bin"
        generate(generated_root)
        expected_files = sorted(path.relative_to(FIXTURE_ROOT) for path in OUTPUT_ROOT.glob("*"))
        generated_files = sorted(path.relative_to(Path(temporary)) for path in generated_root.glob("*"))
        if expected_files != generated_files:
            raise RuntimeError(
                f"fixture file set drift: checked={expected_files}, generated={generated_files}"
            )
        for relative_path in expected_files:
            checked = FIXTURE_ROOT / relative_path
            regenerated = Path(temporary) / relative_path
            if checked.read_bytes() != regenerated.read_bytes():
                raise RuntimeError(f"fixture drift: {relative_path}")
        checked_manifest = FIXTURE_ROOT / "manifest.json"
        regenerated_manifest = Path(temporary) / "manifest.json"
        if checked_manifest.read_bytes() != regenerated_manifest.read_bytes():
            raise RuntimeError("fixture drift: manifest.json")


def main() -> None:
    arguments = parse_args()
    if arguments.check:
        check_generated()
    else:
        generate(OUTPUT_ROOT)


if __name__ == "__main__":
    main()
