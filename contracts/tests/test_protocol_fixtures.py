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
STYLUS_VALIDATION = json.loads((FIXTURE_ROOT / "stylus_validation.json").read_text())
CONTROLLER_VALIDATION = json.loads((FIXTURE_ROOT / "controller_validation.json").read_text())
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

    def test_modifier_fixtures_cover_standard_and_legacy_layouts(self) -> None:
        fixtures = {entry["name"]: entry for entry in MANIFEST["controlFixtures"]}
        expected = {
            "key_usb_hid_control": 0x01,
            "key_usb_hid_shift": 0x02,
            "key_legacy_control": 0x02,
            "key_legacy_shift": 0x01,
        }
        with tempfile.TemporaryDirectory(prefix="vibescreen-modifier-fixtures-") as temporary:
            for name, mask in expected.items():
                entry = fixtures[name]
                output = Path(temporary) / f"{name}.json"
                convert(entry["messageType"], FIXTURE_ROOT / entry["binary"], "binpb", output, "json")
                event = json.loads(output.read_text())["keyEvent"]
                self.assertEqual(mask, event["modifierMask"], name)


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
        self.assertNotIn("toolKind", event)
        self.assertNotIn("buttonMask", event)
        self.assertNotIn("contactState", event)
        self.assertEqual(
            {
                "toolKind": "STYLUS_TOOL_KIND_PEN",
                "buttonMask": 0,
                "contactState": "STYLUS_CONTACT_STATE_CONTACT",
            },
            STYLUS_VALIDATION["legacyDefaults"],
        )

    def test_extended_stylus_fixture_covers_eraser_buttons_and_proximity(self) -> None:
        fixtures = {entry["name"]: entry for entry in MANIFEST["controlFixtures"]}
        stylus = fixtures["stylus_extended"]
        with tempfile.TemporaryDirectory(prefix="vibescreen-stylus-extended-fixture-") as temporary:
            decoded_path = Path(temporary) / "stylus_extended.json"
            convert(stylus["messageType"], FIXTURE_ROOT / stylus["binary"], "binpb", decoded_path, "json")
            event = json.loads(decoded_path.read_text())["stylusEvent"]

        self.assertEqual("STYLUS_TOOL_KIND_ERASER", event["toolKind"])
        self.assertEqual(3, event["buttonMask"])
        self.assertEqual("STYLUS_CONTACT_STATE_PROXIMITY", event["contactState"])
        self.assertEqual(0, event.get("pressure", 0))

    def test_extended_stylus_validation_fixture_covers_invalid_values(self) -> None:
        self.assertEqual(
            "vibescreen.protocol.v1.StylusEvent.validation/v1",
            STYLUS_VALIDATION["schema"],
        )
        cases = {case["name"]: case for case in STYLUS_VALIDATION["negativeCases"]}
        self.assertEqual(
            {
                "unknown_tool_kind",
                "reserved_button_bit",
                "unknown_contact_state",
                "proximity_with_pressure",
            },
            set(cases),
        )
        for case in cases.values():
            event = case["event"]
            valid = (
                event["toolKindRawValue"] in {1, 2}
                and event["buttonMask"] & ~0b11 == 0
                and event["contactStateRawValue"] in {1, 2}
                and not (event["contactStateRawValue"] == 2 and event["pressure"] != 0)
            )
            self.assertFalse(valid, case["name"])
            self.assertTrue(case["reason"])


    def test_controller_fixtures_cover_neutral_lifecycle_and_full_state(self) -> None:
        fixtures = {entry["name"]: entry for entry in MANIFEST["controlFixtures"]}
        decoded_events: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(prefix="vibescreen-controller-fixtures-") as temporary:
            temporary_root = Path(temporary)
            for name in ("controller_connected", "controller_state", "controller_disconnected"):
                fixture = fixtures[name]
                decoded_path = temporary_root / f"{name}.json"
                convert(fixture["messageType"], FIXTURE_ROOT / fixture["binary"], "binpb", decoded_path, "json")
                decoded_events[name] = json.loads(decoded_path.read_text())["controllerEvent"]

        connected = decoded_events["controller_connected"]
        state = decoded_events["controller_state"]
        disconnected = decoded_events["controller_disconnected"]
        self.assertEqual("CONTROLLER_EVENT_KIND_CONNECTED", connected["kind"])
        self.assertEqual("CONTROLLER_EVENT_KIND_STATE", state["kind"])
        self.assertEqual("CONTROLLER_EVENT_KIND_DISCONNECTED", disconnected["kind"])
        self.assertEqual("controller-xbox-1", state["controllerId"])
        self.assertEqual("1", state["controllerEpoch"])
        self.assertEqual(4101, state["buttonMask"])
        pressed_buttons = {
            name
            for name, bit in CONTROLLER_VALIDATION["buttonBits"].items()
            if state["buttonMask"] & (1 << bit)
        }
        self.assertEqual({"south", "west", "r3"}, pressed_buttons)
        self.assertEqual([-0.75, 0.5, 0.25, -0.125], [state[key] for key in ("leftStickX", "leftStickY", "rightStickX", "rightStickY")])
        self.assertEqual([0.375, 0.875], [state[key] for key in ("leftTrigger", "rightTrigger")])
        self.assertEqual([1, -1], [state["hatX"], state["hatY"]])
        self.assertEqual({"displayId": "display-main", "streamId": "42"}, state["target"])
        state_fields = {"buttonMask", "leftStickX", "leftStickY", "rightStickX", "rightStickY", "leftTrigger", "rightTrigger", "hatX", "hatY"}
        self.assertTrue(state_fields.isdisjoint(connected))
        self.assertTrue(state_fields.isdisjoint(disconnected))

    def test_controller_validation_fixture_covers_invalid_values(self) -> None:
        self.assertEqual(
            "vibescreen.protocol.v1.ControllerEvent.validation/v1",
            CONTROLLER_VALIDATION["schema"],
        )
        self.assertEqual(0b1_1111_1111_1111, CONTROLLER_VALIDATION["buttonMaskDefinedBits"])
        self.assertEqual(
            {
                "south": 0,
                "east": 1,
                "west": 2,
                "north": 3,
                "l1": 4,
                "r1": 5,
                "l2Digital": 6,
                "r2Digital": 7,
                "select": 8,
                "start": 9,
                "guideMode": 10,
                "l3": 11,
                "r3": 12,
            },
            CONTROLLER_VALIDATION["buttonBits"],
        )
        cases = {case["name"]: case for case in CONTROLLER_VALIDATION["negativeCases"]}
        self.assertEqual(
            {
                "zero_input_id",
                "empty_controller_id",
                "overlong_controller_id",
                "overlong_controller_id_multibyte_utf8",
                "zero_controller_epoch",
                "unknown_kind",
                "unspecified_kind",
                "reserved_button_bit",
                "stick_axis_out_of_range",
                "stick_axis_non_finite",
                "trigger_out_of_range",
                "trigger_non_finite",
                "invalid_hat_axis",
                "connected_non_neutral",
                "disconnected_non_neutral",
            },
            set(cases),
        )
        for case in cases.values():
            event = case["event"]
            analog = [event.get(key, 0) for key in ("leftStickX", "leftStickY", "rightStickX", "rightStickY", "leftTrigger", "rightTrigger")]
            lifecycle_neutral = event["kindRawValue"] == 2 or (
                event.get("buttonMask", 0) == 0
                and all(value == 0 for value in analog)
                and event.get("hatX", 0) == 0
                and event.get("hatY", 0) == 0
            )
            valid = (
                event["inputId"] > 0
                and 1 <= len(event["controllerId"].encode("utf-8")) <= 128
                and event["controllerEpoch"] > 0
                and event["kindRawValue"] in {1, 2, 3}
                and event.get("buttonMask", 0) & ~CONTROLLER_VALIDATION["buttonMaskDefinedBits"] == 0
                and all(math.isfinite(value) for value in analog)
                and all(-1 <= event.get(key, 0) <= 1 for key in ("leftStickX", "leftStickY", "rightStickX", "rightStickY"))
                and all(0 <= event.get(key, 0) <= 1 for key in ("leftTrigger", "rightTrigger"))
                and event.get("hatX", 0) in {-1, 0, 1}
                and event.get("hatY", 0) in {-1, 0, 1}
                and lifecycle_neutral
            )
            self.assertFalse(valid, case["name"])
            self.assertTrue(case["reason"])

        lifecycle_cases = {
            case["name"]: case for case in CONTROLLER_VALIDATION["lifecycleNegativeCases"]
        }
        self.assertEqual(
            {
                "duplicate_connected",
                "state_before_connected",
                "state_after_disconnected",
                "reused_controller_epoch",
                "decreasing_controller_epoch",
                "duplicate_input_id",
                "non_monotonic_input_id",
            },
            set(lifecycle_cases),
        )
        for case in lifecycle_cases.values():
            active_epochs: dict[str, int] = {}
            last_epochs: dict[str, int] = {}
            last_input_id = 0
            valid_sequence = True
            for event in case["sequence"]:
                input_id = event["inputId"]
                if input_id <= last_input_id:
                    valid_sequence = False
                    break
                last_input_id = input_id
                controller_id = event["controllerId"]
                controller_epoch = event["controllerEpoch"]
                kind = event["kindRawValue"]
                active_epoch = active_epochs.get(controller_id)
                if kind == 1:
                    if active_epoch is not None or controller_epoch <= last_epochs.get(controller_id, 0):
                        valid_sequence = False
                        break
                    active_epochs[controller_id] = controller_epoch
                    last_epochs[controller_id] = controller_epoch
                elif kind == 2:
                    if active_epoch != controller_epoch:
                        valid_sequence = False
                        break
                elif kind == 3:
                    if active_epoch != controller_epoch:
                        valid_sequence = False
                        break
                    del active_epochs[controller_id]
                else:
                    valid_sequence = False
                    break
            self.assertFalse(valid_sequence, case["name"])
            self.assertTrue(case["reason"])

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
