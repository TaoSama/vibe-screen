from pathlib import Path
import re
import unittest


PROTO_ROOT = Path(__file__).parents[1] / "proto" / "vibescreen" / "protocol" / "v1"


def message_fields(source: str, message_name: str) -> dict[str, int]:
    match = re.search(rf"message\s+{message_name}\s*\{{(.*?)\n\}}", source, re.DOTALL)
    if not match:
        raise AssertionError(f"message {message_name} not found")
    return {
        name: int(number)
        for name, number in re.findall(
            r"(?:repeated\s+)?[.\w]+\s+(\w+)\s*=\s*(\d+)\s*;", match.group(1)
        )
    }


class SecurityContractTest(unittest.TestCase):
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

    def test_control_and_media_ciphertexts_are_distinct_messages(self) -> None:
        source = (PROTO_ROOT / "security.proto").read_text()
        self.assertEqual({"header": 1, "ciphertext": 2}, message_fields(source, "EncryptedControlPacket"))
        self.assertEqual({"header": 1, "ciphertext": 2}, message_fields(source, "EncryptedMediaPacket"))

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
