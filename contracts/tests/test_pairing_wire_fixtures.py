from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import unittest
from urllib.parse import parse_qsl, urlsplit


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "pairing" / "v1" / "wire.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())

P256_PRIME = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
P256_A = P256_PRIME - 3
P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
P256_GENERATOR = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)
REQUIRED_CAPABILITIES = [
    "application_e2ee",
    "audio_data_channel",
    "bulk_data_channel",
    "control_data_channel",
    "media_data_channel",
    "peer_identity",
]
IDENTITY_KEYS = {
    "device_id",
    "key_id",
    "key_epoch",
    "signature_algorithm",
    "signing_public_key",
}


def decode_base64url(value: str) -> bytes:
    if not value or "=" in value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("non-canonical base64url")
    decoded = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != value:
        raise ValueError("non-canonical base64url")
    return decoded


def uint64(value: int) -> bytes:
    return value.to_bytes(8, "big")


def length_prefixed(value: bytes) -> bytes:
    return uint64(len(value)) + value


def canonical_list(values: list[str]) -> bytes:
    return uint64(len(values)) + b"".join(length_prefixed(value.encode()) for value in values)


def transcript_digest(domain: str, parts: list[bytes]) -> bytes:
    encoded = length_prefixed(b"vibescreen/identity/v1")
    encoded += length_prefixed(domain.encode())
    encoded += b"".join(length_prefixed(part) for part in parts)
    return hashlib.sha256(encoded).digest()


def identity_parts(identity: dict[str, object]) -> list[bytes]:
    return [
        str(identity["device_id"]).encode(),
        str(identity["key_id"]).encode(),
        uint64(int(identity["key_epoch"])),
        str(identity["signature_algorithm"]).encode(),
        decode_base64url(str(identity["signing_public_key"])),
    ]


def canonical_parts(offer: dict[str, object], request: dict[str, object]) -> list[bytes]:
    host_identity = offer["host_identity"]
    device_identity = request["device_identity"]
    assert isinstance(host_identity, dict) and isinstance(device_identity, dict)
    return [
        uint64(int(offer["protocol_min"])),
        uint64(int(offer["protocol_max"])),
        str(offer["host_role"]).encode(),
        str(offer["device_role"]).encode(),
        canonical_list(list(offer["signature_algorithms"])),
        canonical_list(list(offer["key_agreement_algorithms"])),
        canonical_list(list(offer["aead_algorithms"])),
        canonical_list(list(offer["required_capabilities"])),
        decode_base64url(str(offer["offer_id"])),
        decode_base64url(str(offer["challenge"])),
        uint64(int(offer["expires_at_unix_seconds"])),
        *identity_parts(host_identity),
        decode_base64url(str(offer["ephemeral_public_key"])),
        *identity_parts(device_identity),
        str(request["device_name"]).encode(),
        decode_base64url(str(request["ephemeral_public_key"])),
    ]


def point_add(
    left: tuple[int, int] | None,
    right: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if left is None:
        return right
    if right is None:
        return left
    left_x, left_y = left
    right_x, right_y = right
    if left_x == right_x and (left_y + right_y) % P256_PRIME == 0:
        return None
    if left == right:
        slope = (3 * left_x * left_x + P256_A) * pow(2 * left_y, -1, P256_PRIME)
    else:
        slope = (right_y - left_y) * pow(right_x - left_x, -1, P256_PRIME)
    slope %= P256_PRIME
    result_x = (slope * slope - left_x - right_x) % P256_PRIME
    result_y = (slope * (left_x - result_x) - left_y) % P256_PRIME
    return result_x, result_y


def point_multiply(
    scalar: int,
    point: tuple[int, int] = P256_GENERATOR,
) -> tuple[int, int] | None:
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def decode_public_key(encoded: bytes) -> tuple[int, int]:
    if len(encoded) != 65 or encoded[0] != 4:
        raise ValueError("invalid P-256 public key encoding")
    point = (int.from_bytes(encoded[1:33], "big"), int.from_bytes(encoded[33:], "big"))
    x, y = point
    if not (0 <= x < P256_PRIME and 0 <= y < P256_PRIME):
        raise ValueError("invalid P-256 coordinates")
    if (y * y - (x * x * x + P256_A * x + P256_B)) % P256_PRIME != 0:
        raise ValueError("P-256 point is not on the curve")
    return point


def encode_public_key(point: tuple[int, int] | None) -> bytes:
    if point is None:
        raise ValueError("point at infinity")
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def parse_der_signature(signature: bytes) -> tuple[int, int]:
    if len(signature) < 8 or len(signature) > 80 or signature[0] != 0x30:
        raise ValueError("invalid ECDSA DER signature")
    if signature[1] != len(signature) - 2:
        raise ValueError("invalid ECDSA DER sequence length")
    offset = 2
    values: list[int] = []
    for _ in range(2):
        if offset + 2 > len(signature) or signature[offset] != 0x02:
            raise ValueError("invalid ECDSA DER integer")
        length = signature[offset + 1]
        start = offset + 2
        end = start + length
        if length == 0 or end > len(signature):
            raise ValueError("invalid ECDSA DER integer length")
        encoded = signature[start:end]
        if encoded[0] & 0x80 or (len(encoded) > 1 and encoded[0] == 0 and encoded[1] & 0x80 == 0):
            raise ValueError("non-minimal ECDSA DER integer")
        values.append(int.from_bytes(encoded, "big"))
        offset = end
    if offset != len(signature) or not all(1 <= value < P256_ORDER for value in values):
        raise ValueError("invalid ECDSA signature values")
    return values[0], values[1]


def verify_signature(public_key: bytes, digest: bytes, signature: bytes) -> bool:
    try:
        point = decode_public_key(public_key)
        r, s = parse_der_signature(signature)
    except ValueError:
        return False
    inverse = pow(s, -1, P256_ORDER)
    candidate = point_add(
        point_multiply((int.from_bytes(digest, "big") * inverse) % P256_ORDER),
        point_multiply((r * inverse) % P256_ORDER, point),
    )
    return candidate is not None and candidate[0] % P256_ORDER == r


def hkdf_sha256(input_key: bytes, salt: bytes, info: bytes) -> bytes:
    extracted = hmac.new(salt, input_key, hashlib.sha256).digest()
    return hmac.new(extracted, info + b"\x01", hashlib.sha256).digest()


class PairingWireFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.offer_url = FIXTURE["wire"]["qr_offer"]["utf8"]
        cls.offer = json.loads(FIXTURE["wire"]["qr_offer"]["payload_utf8"])
        cls.request = json.loads(FIXTURE["wire"]["pairing_request"]["utf8"])
        cls.acceptance = json.loads(FIXTURE["wire"]["acceptance"]["utf8"])
        cls.parts = canonical_parts(cls.offer, cls.request)

    def test_schema_base64_and_wire_hashes(self) -> None:
        self.assertEqual(
            {"schema", "fixture_scope", "protocol_version", "test_material", "wire", "expected", "negative_cases"},
            set(FIXTURE),
        )
        self.assertEqual("vibescreen.pairing-wire-fixture.v1", FIXTURE["schema"])
        self.assertEqual(1, FIXTURE["protocol_version"])
        self.assertEqual(
            {
                "protocol_min", "protocol_max", "host_role", "device_role", "signature_algorithms",
                "key_agreement_algorithms", "aead_algorithms", "required_capabilities", "offer_id",
                "one_time_credential", "expires_at_unix_seconds", "host_identity", "challenge",
                "ephemeral_public_key",
            },
            set(self.offer),
        )
        self.assertEqual(IDENTITY_KEYS, set(self.offer["host_identity"]))
        self.assertEqual(IDENTITY_KEYS, set(self.request["device_identity"]))
        self.assertEqual(
            {"offer_id", "device_identity", "device_name", "ephemeral_public_key", "request_signature", "bootstrap_mac"},
            set(self.request),
        )
        self.assertEqual(
            {"accepted", "offer_id", "host_identity", "session_context", "session_key_id", "host_signature"},
            set(self.acceptance),
        )

        parsed_url = urlsplit(self.offer_url)
        self.assertEqual(("vibescreen", "pair", "", ""), (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.fragment))
        parameters = parse_qsl(parsed_url.query, keep_blank_values=True)
        self.assertEqual(["v", "o"], [name for name, _ in parameters])
        self.assertEqual("1", parameters[0][1])
        payload = decode_base64url(parameters[1][1])
        self.assertEqual(FIXTURE["wire"]["qr_offer"]["payload_utf8"].encode(), payload)

        for name, wire in FIXTURE["wire"].items():
            encoded = wire["utf8"].encode()
            self.assertEqual(wire["byte_length"], len(encoded), name)
            self.assertEqual(wire["sha256"], hashlib.sha256(encoded).hexdigest(), name)
        self.assertEqual(
            FIXTURE["wire"]["qr_offer"]["payload_sha256"],
            hashlib.sha256(payload).hexdigest(),
        )
        for case in FIXTURE["negative_cases"]:
            self.assertEqual(case["sha256"], hashlib.sha256(case["wire_utf8"].encode()).hexdigest(), case["name"])

        base64_values = [
            self.offer["offer_id"], self.offer["one_time_credential"], self.offer["challenge"],
            self.offer["ephemeral_public_key"], self.offer["host_identity"]["signing_public_key"],
            self.request["ephemeral_public_key"], self.request["request_signature"], self.request["bootstrap_mac"],
            self.request["device_identity"]["signing_public_key"], self.acceptance["session_context"],
            self.acceptance["host_signature"], *FIXTURE["expected"].values(),
            *[value for key, value in FIXTURE["test_material"].items() if key != "device_ephemeral_random_fill_byte"],
        ]
        for value in base64_values:
            if isinstance(value, str) and not re.fullmatch(r"[0-9a-f]{64}", value):
                decode_base64url(value)

    def test_canonical_digests_signatures_and_derived_identifiers(self) -> None:
        expected = FIXTURE["expected"]
        request_digest = transcript_digest("vibescreen/pairing-request/v1", self.parts)
        self.assertEqual(decode_base64url(expected["request_digest"]), request_digest)
        request_signature = decode_base64url(self.request["request_signature"])
        device_public_key = decode_base64url(self.request["device_identity"]["signing_public_key"])
        self.assertTrue(verify_signature(device_public_key, request_digest, request_signature))
        self.assertFalse(verify_signature(device_public_key, hashlib.sha256(request_digest).digest(), request_signature))

        bootstrap_digest = transcript_digest(
            "vibescreen/pairing-bootstrap/v1",
            self.parts + [request_signature],
        )
        self.assertEqual(decode_base64url(expected["bootstrap_digest"]), bootstrap_digest)
        credential = decode_base64url(self.offer["one_time_credential"])
        self.assertEqual(
            decode_base64url(self.request["bootstrap_mac"]),
            hmac.new(credential, bootstrap_digest, hashlib.sha256).digest(),
        )

        device_scalar = int.from_bytes(decode_base64url(FIXTURE["test_material"]["device_ephemeral_private_scalar"]), "big")
        host_ephemeral = decode_public_key(decode_base64url(self.offer["ephemeral_public_key"]))
        shared_point = point_multiply(device_scalar, host_ephemeral)
        self.assertIsNotNone(shared_point)
        ecdh_secret = shared_point[0].to_bytes(32, "big")
        shared_secret = hkdf_sha256(
            ecdh_secret,
            credential,
            transcript_digest("vibescreen/pairing-shared/v1", self.parts),
        )
        bootstrap_secret = hkdf_sha256(
            ecdh_secret,
            credential,
            transcript_digest("vibescreen/pairing-bootstrap-credential/v1", self.parts),
        )
        self.assertEqual(expected["session_key_id"], hashlib.sha256(shared_secret + bootstrap_secret).hexdigest())
        self.assertEqual(expected["pairing_identifier"], hashlib.sha256(decode_base64url(self.offer["offer_id"])).hexdigest())

        session_context = transcript_digest("vibescreen/pairing-session-context/v1", self.parts)
        self.assertEqual(decode_base64url(expected["session_context"]), session_context)
        result_digest = transcript_digest(
            "vibescreen/pairing-result/v1",
            self.parts + [
                request_signature,
                decode_base64url(self.request["bootstrap_mac"]),
                b"\x01",
                expected["session_key_id"].encode(),
            ],
        )
        self.assertEqual(decode_base64url(expected["pairing_result_digest"]), result_digest)
        self.assertTrue(
            verify_signature(
                decode_base64url(self.acceptance["host_identity"]["signing_public_key"]),
                result_digest,
                decode_base64url(self.acceptance["host_signature"]),
            )
        )

    def test_fixed_private_material_matches_public_keys_and_is_synthetic(self) -> None:
        material = FIXTURE["test_material"]
        for name in ("host_signing", "device_signing", "host_ephemeral", "device_ephemeral"):
            scalar = int.from_bytes(decode_base64url(material[f"{name}_private_scalar"]), "big")
            self.assertTrue(1 <= scalar < P256_ORDER)
            self.assertEqual(
                decode_base64url(material[f"{name}_public_key"]),
                encode_public_key(point_multiply(scalar)),
            )
        self.assertEqual(66, material["device_ephemeral_random_fill_byte"])
        self.assertEqual(bytes(range(0xA0, 0xC0)), decode_base64url(self.offer["one_time_credential"]))
        self.assertEqual("TEST_ONLY_SYNTHETIC_MATERIAL_DO_NOT_USE_IN_PRODUCTION", FIXTURE["fixture_scope"])

        serialized = FIXTURE_PATH.read_text().lower()
        for forbidden in ("-----begin", "/users/", "/home/", "https://", "http://", "@example."):
            self.assertNotIn(forbidden, serialized)
        self.assertIsNone(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", serialized))

    def test_negative_cases_cover_field_signature_size_and_order(self) -> None:
        cases = {case["name"]: case for case in FIXTURE["negative_cases"]}
        self.assertEqual({"field_tamper", "signature", "size", "order"}, {case["category"] for case in cases.values()})

        reordered_url = urlsplit(cases["reordered_required_capabilities"]["wire_utf8"])
        reordered_offer = json.loads(decode_base64url(parse_qsl(reordered_url.query)[1][1]))
        self.assertNotEqual(REQUIRED_CAPABILITIES, reordered_offer["required_capabilities"])

        changed_request = json.loads(cases["tampered_request_field"]["wire_utf8"])
        changed_digest = transcript_digest("vibescreen/pairing-request/v1", canonical_parts(self.offer, changed_request))
        self.assertFalse(
            verify_signature(
                decode_base64url(changed_request["device_identity"]["signing_public_key"]),
                changed_digest,
                decode_base64url(changed_request["request_signature"]),
            )
        )
        changed_signature = json.loads(cases["tampered_request_signature"]["wire_utf8"])
        self.assertFalse(
            verify_signature(
                decode_base64url(changed_signature["device_identity"]["signing_public_key"]),
                decode_base64url(FIXTURE["expected"]["request_digest"]),
                decode_base64url(changed_signature["request_signature"]),
            )
        )
        oversized = json.loads(cases["oversized_device_name"]["wire_utf8"])
        self.assertEqual(257, len(oversized["device_name"].encode()))

        changed_acceptance = json.loads(cases["tampered_acceptance_signature"]["wire_utf8"])
        self.assertFalse(
            verify_signature(
                decode_base64url(changed_acceptance["host_identity"]["signing_public_key"]),
                decode_base64url(FIXTURE["expected"]["pairing_result_digest"]),
                decode_base64url(changed_acceptance["host_signature"]),
            )
        )
        changed_context = json.loads(cases["tampered_session_context"]["wire_utf8"])
        self.assertNotEqual(self.acceptance["session_context"], changed_context["session_context"])


if __name__ == "__main__":
    unittest.main()
