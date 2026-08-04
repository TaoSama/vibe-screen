import hashlib
import hmac
import struct
import os
from pathlib import Path
import tempfile
import unittest

import turn_allocation_helper as helper


class TurnAllocationHelperTests(unittest.TestCase):
    def test_authenticated_request_has_adjusted_length_and_valid_integrity(self) -> None:
        transaction_id = bytes.fromhex("00112233445566778899aabb")
        packet = helper.authenticated_request(
            helper.ALLOCATE_REQUEST,
            transaction_id,
            [helper.encode_attribute(helper.REQUESTED_TRANSPORT, bytes((17, 0, 0, 0)))],
            "1700000000:device",
            "relay.test",
            b"nonce",
            "password",
        )
        message_type, body, attributes = helper.parse_message(packet, transaction_id)
        self.assertEqual(message_type, helper.ALLOCATE_REQUEST)
        integrity = helper.first_attribute(attributes, helper.MESSAGE_INTEGRITY)
        integrity_offset = next(offset for kind, _, offset in attributes if kind == helper.MESSAGE_INTEGRITY)
        key = hashlib.md5(b"1700000000:device:relay.test:password", usedforsecurity=False).digest()
        expected = hmac.new(key, packet[: helper.HEADER.size + integrity_offset], hashlib.sha1).digest()
        self.assertEqual(integrity, expected)
        self.assertEqual(len(packet), helper.HEADER.size + len(body))

    def test_message_integrity_rejects_tampering_and_duplicates(self) -> None:
        transaction_id = b"t" * 12
        packet = helper.authenticated_request(
            helper.REFRESH_REQUEST,
            transaction_id,
            [helper.encode_attribute(helper.LIFETIME, struct.pack("!I", 0))],
            "1700000000:device",
            "relay.test",
            b"nonce",
            "password",
        )
        _, _, attributes = helper.parse_message(packet, transaction_id)
        key = helper.long_term_key("1700000000:device", "relay.test", "password")
        helper.verify_message_integrity(packet, attributes, key)
        tampered = bytearray(packet)
        tampered[-1] ^= 1
        _, _, tampered_attributes = helper.parse_message(bytes(tampered), transaction_id)
        with self.assertRaisesRegex(helper.TurnProtocolError, "mismatch"):
            helper.verify_message_integrity(bytes(tampered), tampered_attributes, key)
        duplicate = attributes + [(helper.MESSAGE_INTEGRITY, b"x" * 20, len(packet))]
        with self.assertRaisesRegex(helper.TurnProtocolError, "requires one"):
            helper.verify_message_integrity(packet, duplicate, key)

    def test_parse_attributes_rejects_truncation(self) -> None:
        with self.assertRaisesRegex(helper.TurnProtocolError, "truncated TURN attribute value"):
            helper.parse_attributes(struct.pack("!HH", helper.REALM, 4) + b"abc")

    def test_parse_message_rejects_transaction_and_length_mismatch(self) -> None:
        transaction_id = b"a" * 12
        packet = helper.HEADER.pack(helper.ALLOCATE_SUCCESS, 0, helper.MAGIC_COOKIE, b"b" * 12)
        with self.assertRaisesRegex(helper.TurnProtocolError, "transaction ID mismatch"):
            helper.parse_message(packet, transaction_id)
        malformed = helper.HEADER.pack(helper.ALLOCATE_SUCCESS, 4, helper.MAGIC_COOKIE, transaction_id)
        with self.assertRaisesRegex(helper.TurnProtocolError, "message length"):
            helper.parse_message(malformed, transaction_id)

    def test_error_code_requires_well_formed_attribute(self) -> None:
        attributes = [(helper.ERROR_CODE, bytes((0, 0, 4, 86)), 0)]
        self.assertEqual(helper.error_code(attributes), 486)
        with self.assertRaisesRegex(helper.TurnProtocolError, "ERROR-CODE"):
            helper.error_code([(helper.ERROR_CODE, b"\0\0\4", 0)])
        with self.assertRaisesRegex(helper.TurnProtocolError, "reserved"):
            helper.error_code([(helper.ERROR_CODE, bytes((1, 0, 4, 86)), 0)])

    def test_decode_xor_ipv4_address(self) -> None:
        transaction_id = b"z" * 12
        port = 54321
        address = bytes((203, 0, 113, 7))
        mask = struct.pack("!I", helper.MAGIC_COOKIE)
        value = bytes((0, 1)) + struct.pack("!H", port ^ (helper.MAGIC_COOKIE >> 16)) + bytes(
            left ^ right for left, right in zip(address, mask)
        )
        self.assertEqual(helper.decode_xor_address(value, transaction_id), "203.0.113.7:54321")

    def test_parse_message_rejects_non_stun_top_bits(self) -> None:
        transaction_id = b"a" * 12
        packet = helper.HEADER.pack(0xC103, 0, helper.MAGIC_COOKIE, transaction_id)
        with self.assertRaisesRegex(helper.TurnProtocolError, "top bits"):
            helper.parse_message(packet, transaction_id)

    def test_singleton_attribute_rejects_duplicates(self) -> None:
        attributes = [(helper.NONCE, b"one", 0), (helper.NONCE, b"two", 8)]
        with self.assertRaisesRegex(helper.TurnProtocolError, "duplicate"):
            helper.first_attribute(attributes, helper.NONCE)

    def test_password_file_requires_owner_only_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            path.write_text("secret\n", encoding="utf-8")
            os.chmod(path, 0o600)
            self.assertEqual(helper.read_password_file(path), "secret")
            os.chmod(path, 0o640)
            with self.assertRaisesRegex(helper.TurnProtocolError, "group or world"):
                helper.read_password_file(path)

    def test_wait_cli_requires_transient_code_and_deadline_pair(self) -> None:
        args = helper.parse_args(
            [
                "--server-host",
                "127.0.0.1",
                "--server-port",
                "3478",
                "--username",
                "user",
                "--password-file",
                "/tmp/password",
                "--transient-code",
                "486",
                "--wait-deadline-seconds",
                "3",
            ]
        )
        self.assertEqual(args.transient_code, 486)
        self.assertEqual(args.wait_deadline_seconds, 3)


if __name__ == "__main__":
    unittest.main()
