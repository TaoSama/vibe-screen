from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY = ROOT / "contracts/proto/vibescreen/protocol/v1/security.proto"
ENVELOPE = ROOT / "contracts/proto/vibescreen/protocol/v1/envelope.proto"


def message_fields(source: str, message: str) -> dict[str, int]:
    match = re.search(rf"message\s+{re.escape(message)}\s*\{{(?P<body>.*?)\n\}}", source, re.DOTALL)
    if match is None:
        raise AssertionError(f"missing message {message}")
    return {
        name: int(number)
        for _, name, number in re.findall(
            r"^\s*(?:repeated\s+)?([.\w]+)\s+(\w+)\s*=\s*(\d+)\s*;",
            match.group("body"),
            re.MULTILINE,
        )
    }


class Phase3ProtocolCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.security = SECURITY.read_text(encoding="utf-8")
        cls.envelope = ENVELOPE.read_text(encoding="utf-8")

    def test_secure_header_keeps_replay_and_key_epoch_fields(self) -> None:
        fields = message_fields(self.security, "SecurePacketHeader")
        required_fields = {
                "protocol_version": 1,
                "session_id": 2,
                "session_epoch": 3,
                "key_id": 4,
                "key_epoch": 5,
                "channel": 6,
                "sequence": 7,
                "aead_algorithm": 8,
                "nonce": 9,
        }
        self.assertEqual({name: fields.get(name) for name in required_fields}, required_fields)
        self.assertEqual(len(fields.values()), len(set(fields.values())), "field numbers must remain unique")

    def test_rotation_and_revocation_field_numbers_are_pinned(self) -> None:
        self.assertEqual(message_fields(self.security, "KeyRotationRequest")["current_key_signature"], 5)
        self.assertEqual(message_fields(self.security, "KeyRotationRequest")["next_key_signature"], 6)
        self.assertEqual(message_fields(self.security, "DeviceRevocation")["authority_signature"], 8)
        self.assertEqual(message_fields(self.security, "DeviceRevocation")["revocation_sequence"], 3)
        self.assertEqual(message_fields(self.security, "SecurePacketHeader")["sender_role"], 10)

    def test_encrypted_control_keeps_extension_number(self) -> None:
        fields = message_fields(self.envelope, "Envelope")
        self.assertEqual(fields["encrypted_control_packet"], 90)

    def test_media_ciphertext_is_a_separate_message(self) -> None:
        self.assertIn("message EncryptedControlPacket", self.security)
        self.assertIn("message EncryptedMediaPacket", self.security)
        self.assertEqual(message_fields(self.security, "EncryptedMediaPacket"), {"header": 1, "ciphertext": 2})


if __name__ == "__main__":
    unittest.main()
