from pathlib import Path
import json
import re
import subprocess
import unittest


PROTO_ROOT = Path(__file__).parents[1] / "proto" / "vibescreen" / "protocol" / "v1"
CHANNEL_RECORD_FIXTURE = Path(__file__).parents[1] / "fixtures" / "security" / "v1" / "channel-records.json"
CHANNEL_RECORD_VERIFIER = Path(__file__).with_name("channel_security_fixture_verifier.go")


def message_fields(source: str, message_name: str) -> dict[str, int]:
    match = re.search(rf"message\s+{message_name}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    if not match:
        raise AssertionError(f"message {message_name} not found")
    return {
        name: int(number)
        for name, number in re.findall(
            r"(?:(?:repeated|optional)\s+)?[.\w]+\s+(\w+)\s*=\s*(\d+)\s*;", match.group(1)
        )
    }


def enum_values(source: str, enum_name: str) -> dict[str, int]:
    match = re.search(rf"enum\s+{enum_name}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    if not match:
        raise AssertionError(f"enum {enum_name} not found")
    return {
        name: int(number)
        for name, number in re.findall(r"(\w+)\s*=\s*(\d+)\s*;", match.group(1))
    }


class SecurityContractTest(unittest.TestCase):
    def test_usb_hid_modifier_byte_capability_is_additive_value_27(self) -> None:
        session_source = (PROTO_ROOT / "session.proto").read_text()
        input_source = (PROTO_ROOT / "input.proto").read_text()
        capabilities = enum_values(session_source, "Capability")
        self.assertEqual(27, capabilities["CAPABILITY_USB_HID_MODIFIER_BYTE"])
        self.assertEqual(len(capabilities), len(set(capabilities.values())))
        self.assertEqual(
            {
                "input_id": 1,
                "usb_hid_usage": 2,
                "pressed": 3,
                "modifier_mask": 4,
                "text": 5,
                "target": 6,
            },
            message_fields(input_source, "KeyEvent"),
        )

    def test_client_required_capabilities_is_additive_field_nine(self) -> None:
        source = (PROTO_ROOT / "session.proto").read_text()
        self.assertEqual(9, message_fields(source, "ClientHello")["required_capabilities"])

    def test_media_record_fragmentation_negotiation_is_additive(self) -> None:
        session_source = (PROTO_ROOT / "session.proto").read_text()
        advanced_source = (PROTO_ROOT / "advanced.proto").read_text()
        capability = re.search(
            r"CAPABILITY_MEDIA_RECORD_FRAGMENTATION\s*=\s*(\d+)\s*;",
            session_source,
        )
        self.assertIsNotNone(capability)
        self.assertEqual(23, int(capability.group(1)))
        self.assertEqual(
            8,
            message_fields(advanced_source, "ResourceLimits")["maximum_encrypted_media_record_bytes"],
        )

    def test_legacy_pairing_field_numbers_remain_stable(self) -> None:
        source = (PROTO_ROOT / "pairing.proto").read_text()
        self.assertEqual(
            {"offer_id": 1, "one_time_credential": 2, "expires_at_unix_seconds": 3, "host_public_key": 4},
            {name: number for name, number in message_fields(source, "PairingOffer").items() if number <= 4},
        )
        self.assertEqual(
            {"offer_id": 1, "device_id": 2, "device_name": 3, "device_public_key": 4},
            {name: number for name, number in message_fields(source, "PairingRequest").items() if number <= 4},
        )

    def test_secure_packet_header_has_unique_stable_fields(self) -> None:
        source = (PROTO_ROOT / "security.proto").read_text()
        fields = message_fields(source, "SecurePacketHeader")
        self.assertEqual(len(fields), len(set(fields.values())))
        self.assertEqual(
            {
                "protocol_version": 1,
                "session_id": 2,
                "session_epoch": 3,
                "key_id": 4,
                "key_epoch": 5,
                "channel": 6,
                "sequence": 7,
                "aead_algorithm": 8,
                "nonce": 9,
                "sender_role": 10,
            },
            fields,
        )

    def test_secure_channels_and_shared_record_fixtures_are_stable(self) -> None:
        source = (PROTO_ROOT / "security.proto").read_text()
        self.assertEqual(
            {
                "SECURE_CHANNEL_UNSPECIFIED": 0,
                "SECURE_CHANNEL_CONTROL": 1,
                "SECURE_CHANNEL_MEDIA": 2,
                "SECURE_CHANNEL_AUDIO": 3,
                "SECURE_CHANNEL_BULK": 4,
            },
            enum_values(source, "SecureChannel"),
        )

        fixture = json.loads(CHANNEL_RECORD_FIXTURE.read_text())
        expected_records = {
            "host_control": (1, 1),
            "device_media": (2, 2),
            "host_audio": (1, 3),
            "device_bulk": (2, 4),
        }
        self.assertEqual(set(expected_records), set(fixture["records"]))
        for name, (sender, channel) in expected_records.items():
            payload = bytes.fromhex(fixture["records"][name]["payload"])
            record = bytes.fromhex(fixture["records"][name]["record"])
            self.assertEqual(b"VSCR", record[:4])
            self.assertEqual(1, record[4])
            self.assertEqual(fixture["session"]["epoch"], int.from_bytes(record[21:29], "big"))
            self.assertEqual(1, int.from_bytes(record[29:37], "big"))
            self.assertEqual(sender, record[37])
            self.assertEqual(channel, record[38])
            self.assertEqual(channel, int.from_bytes(record[39:43], "big"))
            self.assertEqual(1, int.from_bytes(record[43:51], "big"))
            self.assertEqual(51 + len(payload) + 16, len(record))

    def test_channel_security_fixture_cryptography_is_independently_reproducible(self) -> None:
        result = subprocess.run(
            [
                "go",
                "run",
                str(CHANNEL_RECORD_VERIFIER),
                "--fixture",
                str(CHANNEL_RECORD_FIXTURE),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_control_and_media_ciphertexts_are_distinct_messages(self) -> None:
        source = (PROTO_ROOT / "security.proto").read_text()
        self.assertEqual({"header": 1, "ciphertext": 2}, message_fields(source, "EncryptedControlPacket"))
        self.assertEqual({"header": 1, "ciphertext": 2}, message_fields(source, "EncryptedMediaPacket"))

    def test_stylus_event_is_an_additive_input_payload(self) -> None:
        input_source = (PROTO_ROOT / "input.proto").read_text()
        envelope_source = (PROTO_ROOT / "envelope.proto").read_text()
        stylus_declaration = input_source[:input_source.index("message StylusEvent")]
        stylus_documentation = " ".join(
            line.removeprefix("// ")
            for line in stylus_declaration.splitlines()[-6:]
            if line.startswith("// ")
        )
        self.assertIn("Phase must be BEGAN, CHANGED, ENDED, or CANCELLED.", stylus_documentation)
        self.assertIn("Position coordinates must be finite and normalized to [0, 1].", stylus_documentation)
        self.assertEqual(
            {
                "input_id": 1,
                "pointer_id": 2,
                "phase": 3,
                "position": 4,
                "pressure": 5,
                "tilt_x_degrees": 6,
                "tilt_y_degrees": 7,
                "target": 8,
                "tool_kind": 9,
                "button_mask": 10,
                "contact_state": 11,
            },
            message_fields(input_source, "StylusEvent"),
        )
        self.assertRegex(input_source, r"optional\s+StylusToolKind\s+tool_kind\s*=\s*9\s*;")
        self.assertRegex(input_source, r"optional\s+StylusContactState\s+contact_state\s*=\s*11\s*;")
        self.assertEqual(65, message_fields(envelope_source, "Envelope")["stylus_event"])

    def test_extended_stylus_enum_and_capability_values_are_stable(self) -> None:
        input_source = (PROTO_ROOT / "input.proto").read_text()
        session_source = (PROTO_ROOT / "session.proto").read_text()
        expected_values = {
            "STYLUS_TOOL_KIND_UNSPECIFIED": 0,
            "STYLUS_TOOL_KIND_PEN": 1,
            "STYLUS_TOOL_KIND_ERASER": 2,
            "STYLUS_CONTACT_STATE_UNSPECIFIED": 0,
            "STYLUS_CONTACT_STATE_CONTACT": 1,
            "STYLUS_CONTACT_STATE_PROXIMITY": 2,
        }
        for name, raw_value in expected_values.items():
            self.assertRegex(input_source, rf"{name}\s*=\s*{raw_value}\s*;")
        self.assertRegex(session_source, r"CAPABILITY_STYLUS\s*=\s*6\s*;")
        self.assertRegex(session_source, r"CAPABILITY_STYLUS_EXTENDED\s*=\s*25\s*;")


    def test_controller_event_is_additive_and_lifecycle_scoped(self) -> None:
        input_source = (PROTO_ROOT / "input.proto").read_text()
        envelope_source = (PROTO_ROOT / "envelope.proto").read_text()
        session_source = (PROTO_ROOT / "session.proto").read_text()
        self.assertEqual(
            {
                "input_id": 1,
                "controller_id": 2,
                "controller_epoch": 3,
                "kind": 4,
                "button_mask": 5,
                "left_stick_x": 6,
                "left_stick_y": 7,
                "right_stick_x": 8,
                "right_stick_y": 9,
                "left_trigger": 10,
                "right_trigger": 11,
                "hat_x": 12,
                "hat_y": 13,
                "target": 14,
            },
            message_fields(input_source, "ControllerEvent"),
        )
        for name, raw_value in {
            "CONTROLLER_EVENT_KIND_UNSPECIFIED": 0,
            "CONTROLLER_EVENT_KIND_CONNECTED": 1,
            "CONTROLLER_EVENT_KIND_STATE": 2,
            "CONTROLLER_EVENT_KIND_DISCONNECTED": 3,
        }.items():
            self.assertRegex(input_source, rf"{name}\s*=\s*{raw_value}\s*;")
        declaration = input_source[input_source.index("// Controller input"):input_source.index("message ControllerEvent")]
        self.assertIn("strictly increase within the ControllerEvent subsequence", declaration)
        self.assertIn("controller_id must encode to 1-128 UTF-8 bytes", declaration)
        self.assertIn("must not contain a raw serial", declaration)
        self.assertIn("controller_epoch must be non-zero and", declaration)
        self.assertIn("strictly increase for the same controller_id", declaration)
        self.assertIn("A new negotiated session resets both monotonic sequences.", declaration)
        self.assertIn("CONNECTED starts a lifecycle", declaration)
        self.assertIn("At most four controller lifecycles may be active concurrently", declaration)
        self.assertIn("maximum_active_controllers_exceeded", declaration)
        self.assertIn("without closing", declaration)
        self.assertIn("or changing any admitted controller lifecycle", declaration)
        self.assertIn("CONNECTED and DISCONNECTED are neutral lifecycle markers", declaration)
        self.assertIn("transport loss", declaration)
        controller_message = input_source[input_source.index("message ControllerEvent"):input_source.index("message PointerEvent")]
        self.assertIn(
            "Bits 0-12 are south, east, west, north, L1, R1, L2 digital, R2 digital,",
            controller_message,
        )
        self.assertIn("select, start, guide/mode, L3, and R3", controller_message)
        self.assertEqual(66, message_fields(envelope_source, "Envelope")["controller_event"])
        self.assertRegex(session_source, r"CAPABILITY_CONTROLLER\s*=\s*26\s*;")

    def test_envelope_security_payloads_do_not_reuse_existing_numbers(self) -> None:
        source = (PROTO_ROOT / "envelope.proto").read_text()
        fields = message_fields(source, "Envelope")
        self.assertEqual(len(fields), len(set(fields.values())))
        self.assertEqual(34, fields["key_rotation_request"])
        self.assertEqual(35, fields["key_rotation_result"])
        self.assertEqual(36, fields["device_revocation"])
        self.assertEqual(37, fields["traffic_key_update"])
        self.assertEqual(38, fields["traffic_key_ack"])
        self.assertEqual(90, fields["encrypted_control_packet"])


if __name__ == "__main__":
    unittest.main()
