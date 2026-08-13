from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


CONTRACT_ROOT = Path(__file__).parents[1]
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures" / "messages" / "v1"
MANIFEST = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
BUF_VERSION = MANIFEST["bufVersion"]
BUF_COMMAND = ["go", "run", f"github.com/bufbuild/buf/cmd/buf@{BUF_VERSION}"]
FRAME_HEADER_LENGTH = 5


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


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift <= 28:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, offset
        shift += 7
    raise ValueError("invalid protobuf varint")


def convert(
    message_type: str,
    source: Path,
    source_format: str,
    destination: Path,
    destination_format: str,
) -> None:
    subprocess.run(
        [
            *BUF_COMMAND,
            "convert",
            str(CONTRACT_ROOT),
            f"--type={message_type}",
            f"--from={source}#format={source_format}",
            f"--to={destination}#format={destination_format}",
        ],
        check=True,
        cwd=CONTRACT_ROOT,
        capture_output=True,
        text=True,
    )


def frame(channel: int, payload: bytes) -> bytes:
    maximum = MANIFEST["transport"]["maximumPayloadBytes"]
    if channel not in {
        MANIFEST["transport"]["controlChannel"],
        MANIFEST["transport"]["videoChannel"],
    }:
        raise ValueError("unsupported channel")
    if len(payload) > maximum:
        raise ValueError("payload exceeds transport limit")
    return bytes([channel]) + struct.pack(">I", len(payload)) + payload


class FrameDecoder:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def append(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self.buffer.extend(chunk)
        decoded: list[tuple[int, bytes]] = []
        maximum = MANIFEST["transport"]["maximumPayloadBytes"]
        while len(self.buffer) >= FRAME_HEADER_LENGTH:
            channel = self.buffer[0]
            length = struct.unpack(">I", self.buffer[1:FRAME_HEADER_LENGTH])[0]
            if length > maximum:
                self.buffer.clear()
                raise ValueError("payload exceeds transport limit")
            frame_length = FRAME_HEADER_LENGTH + length
            if len(self.buffer) < frame_length:
                break
            decoded.append((channel, bytes(self.buffer[FRAME_HEADER_LENGTH:frame_length])))
            del self.buffer[:frame_length]
        return decoded


def parse_media_packet(packet: bytes) -> tuple[bytes, bytes]:
    header_length, payload_offset = decode_varint(packet)
    header_end = payload_offset + header_length
    if header_end > len(packet):
        raise ValueError("truncated media header")
    return packet[payload_offset:header_end], packet[header_end:]


class ProtocolFixtureTest(unittest.TestCase):
    def test_checked_fixtures_match_json_generation(self) -> None:
        subprocess.run(
            ["python3", str(FIXTURE_ROOT / "generate.py"), "--check"],
            check=True,
            cwd=CONTRACT_ROOT.parent,
            capture_output=True,
            text=True,
        )

    def test_control_fixtures_decode_and_exactly_reencode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vibescreen-fixture-test-") as temporary:
            temporary_root = Path(temporary)
            for fixture in MANIFEST["controlFixtures"]:
                with self.subTest(fixture=fixture["name"]):
                    binary = FIXTURE_ROOT / fixture["binary"]
                    self.assertEqual(fixture["byteLength"], binary.stat().st_size)
                    self.assertEqual(fixture["sha256"], hashlib.sha256(binary.read_bytes()).hexdigest())

                    decoded_path = temporary_root / f"{fixture['name']}.json"
                    convert(fixture["messageType"], binary, "binpb", decoded_path, "json")
                    decoded = json.loads(decoded_path.read_text())
                    expected = fixture["expected"]
                    self.assertEqual(expected["protocolVersion"], decoded["protocolVersion"])
                    self.assertEqual(expected["messageId"], decoded["messageId"])
                    self.assertEqual(expected["correlationId"], decoded.get("correlationId", "0"))
                    self.assertEqual(expected["sessionEpoch"], decoded.get("sessionEpoch", "0"))
                    self.assertEqual(expected["sentAtMonotonicNs"], decoded["sentAtMonotonicNs"])
                    self.assertIn(expected["payloadCase"], decoded)

                    reencoded_path = temporary_root / f"{fixture['name']}.binpb"
                    convert(fixture["messageType"], decoded_path, "json", reencoded_path, "binpb")
                    self.assertEqual(binary.read_bytes(), reencoded_path.read_bytes())

    def test_client_hello_fixture_declares_required_touch_capability(self) -> None:
        client_entry = MANIFEST["controlFixtures"][0]
        client_path = FIXTURE_ROOT / client_entry["binary"]
        with tempfile.TemporaryDirectory(prefix="vibescreen-required-capability-") as temporary:
            decoded_path = Path(temporary) / "decoded.json"
            convert(client_entry["messageType"], client_path, "binpb", decoded_path, "json")
            decoded = json.loads(decoded_path.read_text())
            self.assertEqual(["CAPABILITY_TOUCH"], decoded["clientHello"]["requiredCapabilities"])

    def test_rotation_fixtures_cover_initial_and_runtime_values(self) -> None:
        fixtures = {entry["name"]: entry for entry in MANIFEST["controlFixtures"]}
        with tempfile.TemporaryDirectory(prefix="vibescreen-rotation-fixtures-") as temporary:
            temporary_root = Path(temporary)
            decoded: dict[str, dict[str, object]] = {}
            for name in ("video_config", "display_changed"):
                entry = fixtures[name]
                output = temporary_root / f"{name}.json"
                convert(entry["messageType"], FIXTURE_ROOT / entry["binary"], "binpb", output, "json")
                decoded[name] = json.loads(output.read_text())
            self.assertEqual(90, decoded["video_config"]["videoConfig"]["rotationDegrees"])
            self.assertEqual(270, decoded["display_changed"]["displayChanged"]["rotationDegrees"])

    def test_stylus_fixture_covers_pressure_tilt_and_target(self) -> None:
        fixtures = {entry["name"]: entry for entry in MANIFEST["controlFixtures"]}
        stylus = fixtures["stylus"]
        with tempfile.TemporaryDirectory(prefix="vibescreen-stylus-fixture-") as temporary:
            decoded_path = Path(temporary) / "stylus.json"
            convert(stylus["messageType"], FIXTURE_ROOT / stylus["binary"], "binpb", decoded_path, "json")
            event = json.loads(decoded_path.read_text())["stylusEvent"]

        self.assertEqual("101", event["inputId"])
        self.assertEqual(7, event["pointerId"])
        self.assertEqual("INPUT_PHASE_CHANGED", event["phase"])
        self.assertIn(
            event["phase"],
            {
                "INPUT_PHASE_BEGAN",
                "INPUT_PHASE_CHANGED",
                "INPUT_PHASE_ENDED",
                "INPUT_PHASE_CANCELLED",
            },
        )
        self.assertEqual({"x": 0.125, "y": 0.875}, event["position"])
        self.assertTrue(all(math.isfinite(event["position"][axis]) for axis in ("x", "y")))
        self.assertTrue(all(0 <= event["position"][axis] <= 1 for axis in ("x", "y")))
        self.assertEqual(0.625, event["pressure"])
        self.assertEqual(-12.5, event["tiltXDegrees"])
        self.assertEqual(28.75, event["tiltYDegrees"])
        self.assertLessEqual(math.hypot(event["tiltXDegrees"], event["tiltYDegrees"]), 90)
        self.assertEqual({"displayId": "display-main", "streamId": "42"}, event["target"])

    def test_buf_json_projection_accepts_and_discards_unknown_binary_field(self) -> None:
        client_entry = MANIFEST["controlFixtures"][0]
        original = (FIXTURE_ROOT / client_entry["binary"]).read_bytes()
        unknown_field = encode_varint((500 << 3) | 0) + encode_varint(1)
        with tempfile.TemporaryDirectory(prefix="vibescreen-unknown-field-") as temporary:
            temporary_root = Path(temporary)
            extended_path = temporary_root / "extended.binpb"
            extended = original + unknown_field
            extended_path.write_bytes(extended)
            self.assertNotEqual(original, extended)

            decoded_path = temporary_root / "decoded.json"
            convert(client_entry["messageType"], extended_path, "binpb", decoded_path, "json")

            reencoded_path = temporary_root / "reencoded.binpb"
            convert(client_entry["messageType"], decoded_path, "json", reencoded_path, "binpb")
            self.assertEqual(original, reencoded_path.read_bytes())

    def test_tcp_framing_preserves_channel_and_split_coalesced_messages(self) -> None:
        client = (FIXTURE_ROOT / MANIFEST["controlFixtures"][0]["binary"]).read_bytes()
        media = (FIXTURE_ROOT / MANIFEST["mediaFixture"]["binary"]).read_bytes()
        control_frame = frame(MANIFEST["transport"]["controlChannel"], client)
        video_frame = frame(MANIFEST["transport"]["videoChannel"], media)
        self.assertEqual(1, control_frame[0])
        self.assertEqual(len(client), struct.unpack(">I", control_frame[1:5])[0])
        self.assertEqual(2, video_frame[0])

        decoder = FrameDecoder()
        self.assertEqual([], decoder.append(control_frame[:3]))
        self.assertEqual(
            [(1, client), (2, media)],
            decoder.append(control_frame[3:] + video_frame),
        )

    def test_media_header_and_annex_b_payload_lengths_match(self) -> None:
        fixture = MANIFEST["mediaFixture"]
        packet_path = FIXTURE_ROOT / fixture["binary"]
        packet = packet_path.read_bytes()
        self.assertEqual(fixture["sha256"], hashlib.sha256(packet).hexdigest())
        header, payload = parse_media_packet(packet)
        self.assertEqual(bytes.fromhex(fixture["annexBPayloadHex"]), payload)
        self.assertTrue(payload.startswith(bytes.fromhex("00000001")))

        with tempfile.TemporaryDirectory(prefix="vibescreen-media-header-") as temporary:
            temporary_root = Path(temporary)
            header_path = temporary_root / "header.binpb"
            header_path.write_bytes(header)
            decoded_path = temporary_root / "header.json"
            convert(fixture["headerMessageType"], header_path, "binpb", decoded_path, "json")
            decoded = json.loads(decoded_path.read_text())
            self.assertEqual(fixture["expectedHeader"], decoded)
            self.assertEqual(len(payload), decoded["payloadLength"])

        truncated_header = encode_varint(len(header) + 1) + header
        with self.assertRaisesRegex(ValueError, "truncated media header"):
            parse_media_packet(truncated_header)

    def test_upgrade_bytes_are_pinned(self) -> None:
        transport = MANIFEST["transport"]
        offer = (FIXTURE_ROOT / "bin" / "upgrade_offer.bin").read_bytes()
        acknowledgement = (FIXTURE_ROOT / "bin" / "upgrade_acknowledgement.bin").read_bytes()
        self.assertEqual(
            bytes.fromhex(transport["upgradeOfferHex"]),
            offer,
        )
        self.assertEqual(transport["upgradeOfferSha256"], hashlib.sha256(offer).hexdigest())
        self.assertEqual(
            bytes.fromhex(transport["upgradeAcknowledgementHex"]),
            acknowledgement,
        )
        self.assertEqual(
            transport["upgradeAcknowledgementSha256"],
            hashlib.sha256(acknowledgement).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
