#!/usr/bin/env python3
"""Generate the cross-platform AUDIO/BULK channel-security fixture.

The fixture pins the session key-derivation inputs (shared secret, bootstrap
secret, transcript context), session epoch, key epoch, channel, sender,
sequence, and plaintext. Both Swift and Android derive the same directional
traffic keys via HKDF-SHA256 and then seal the same plaintext with AES-256-GCM,
producing byte-for-byte identical records.

Expected records are computed with OpenSSL's EVP_aes_256_gcm and validated
against the project's known empty-plaintext vector
(530f8afbc74536b9a963b4f1c4cb738b) before emission.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import struct
from pathlib import Path

# --- OpenSSL AES-256-GCM ---------------------------------------------------

_libcrypto = ctypes.CDLL("/opt/homebrew/lib/libcrypto.dylib")
_libcrypto.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
_libcrypto.EVP_aes_256_gcm.restype = ctypes.c_void_p
_libcrypto.EVP_EncryptInit_ex.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
]
_libcrypto.EVP_EncryptInit_ex.restype = ctypes.c_int
_libcrypto.EVP_CIPHER_CTX_ctrl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_libcrypto.EVP_CIPHER_CTX_ctrl.restype = ctypes.c_int
_libcrypto.EVP_EncryptUpdate.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_int,
]
_libcrypto.EVP_EncryptUpdate.restype = ctypes.c_int
_libcrypto.EVP_EncryptFinal_ex.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
_libcrypto.EVP_EncryptFinal_ex.restype = ctypes.c_int
_libcrypto.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]

_EVP_CTRL_GCM_SET_IVLEN = 0x9
_EVP_CTRL_GCM_GET_TAG = 0x10


def aes_gcm_seal(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("AES-256-GCM requires a 32-byte key and 12-byte nonce")
    ctx = _libcrypto.EVP_CIPHER_CTX_new()
    try:
        cipher = _libcrypto.EVP_aes_256_gcm()
        if _libcrypto.EVP_EncryptInit_ex(ctx, cipher, None, None, None) != 1:
            raise RuntimeError("EVP_EncryptInit_ex(cipher) failed")
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_SET_IVLEN, len(nonce), None) != 1:
            raise RuntimeError("EVP_CTRL_GCM_SET_IVLEN failed")
        if _libcrypto.EVP_EncryptInit_ex(ctx, None, None, key, nonce) != 1:
            raise RuntimeError("EVP_EncryptInit_ex(key,iv) failed")

        outlen = ctypes.c_int(0)
        if aad:
            if _libcrypto.EVP_EncryptUpdate(ctx, None, ctypes.byref(outlen), aad, len(aad)) != 1:
                raise RuntimeError("EVP_EncryptUpdate(aad) failed")

        cipherbuf = ctypes.create_string_buffer(len(plaintext) + 16)
        if _libcrypto.EVP_EncryptUpdate(ctx, cipherbuf, ctypes.byref(outlen), plaintext, len(plaintext)) != 1:
            raise RuntimeError("EVP_EncryptUpdate(plaintext) failed")
        ciphertext = cipherbuf.raw[: outlen.value]

        finalbuf = ctypes.create_string_buffer(16)
        finallen = ctypes.c_int(0)
        if _libcrypto.EVP_EncryptFinal_ex(ctx, finalbuf, ctypes.byref(finallen)) != 1:
            raise RuntimeError("EVP_EncryptFinal_ex failed")
        ciphertext += finalbuf.raw[: finallen.value]

        tag = ctypes.create_string_buffer(16)
        if _libcrypto.EVP_CIPHER_CTX_ctrl(ctx, _EVP_CTRL_GCM_GET_TAG, 16, tag) != 1:
            raise RuntimeError("EVP_CTRL_GCM_GET_TAG failed")
        return ciphertext + tag.raw
    finally:
        _libcrypto.EVP_CIPHER_CTX_free(ctx)


# --- HKDF-SHA256 -----------------------------------------------------------


def hkdf_sha256(input_key_material: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, input_key_material, hashlib.sha256).digest()
    output = b""
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(prk, previous + info + bytes([counter]), hashlib.sha256).digest()
        output += previous
        counter += 1
    return output[:length]


# --- Record construction ---------------------------------------------------

MAGIC = 0x56534352  # "VSCR"
VERSION = 1
SESSION_ID_HASH_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
HEADER_BYTES = 4 + 1 + SESSION_ID_HASH_BYTES + 8 + 8 + 1 + 1 + NONCE_BYTES

CHANNEL_AUDIO = 3
CHANNEL_BULK = 4
SENDER_HOST = 1
SENDER_DEVICE = 2


def session_id_hash(session_identifier: str) -> bytes:
    return hashlib.sha256(session_identifier.encode("utf-8")).digest()[:SESSION_ID_HASH_BYTES]


def make_nonce(channel: int, sequence: int) -> bytes:
    return struct.pack(">I", channel) + struct.pack(">Q", sequence)


def make_header(
    session_hash: bytes,
    session_epoch: int,
    key_epoch: int,
    sender: int,
    channel: int,
    nonce: bytes,
) -> bytes:
    return (
        struct.pack(">I", MAGIC)
        + bytes([VERSION])
        + session_hash
        + struct.pack(">Q", session_epoch)
        + struct.pack(">Q", key_epoch)
        + bytes([sender])
        + bytes([channel])
        + nonce
    )


def derive_keys(shared_secret: bytes, bootstrap_secret: bytes, context: bytes) -> dict[str, bytes]:
    material = hkdf_sha256(shared_secret, bootstrap_secret, context, 256)
    return {
        "host_control": material[0:32],
        "device_control": material[32:64],
        "host_media": material[64:96],
        "device_media": material[96:128],
        "host_audio": material[128:160],
        "device_audio": material[160:192],
        "host_bulk": material[192:224],
        "device_bulk": material[224:256],
    }


def directional_key(keys: dict, channel: int, sender: int) -> bytes:
    if channel == CHANNEL_AUDIO:
        return keys["host_audio"] if sender == SENDER_HOST else keys["device_audio"]
    if channel == CHANNEL_BULK:
        return keys["host_bulk"] if sender == SENDER_HOST else keys["device_bulk"]
    raise ValueError(f"unsupported channel {channel}")


def seal_record(
    session_hash: bytes,
    session_epoch: int,
    key_epoch: int,
    channel: int,
    sender: int,
    sequence: int,
    plaintext: bytes,
    keys: dict,
) -> dict:
    nonce = make_nonce(channel, sequence)
    header = make_header(session_hash, session_epoch, key_epoch, sender, channel, nonce)
    key = directional_key(keys, channel, sender)
    ciphertext_and_tag = aes_gcm_seal(key, nonce, plaintext, header)
    record = header + ciphertext_and_tag
    return {
        "nonce": nonce.hex(),
        "header": header.hex(),
        "ciphertext_and_tag": ciphertext_and_tag.hex(),
        "record": record.hex(),
    }


def main() -> None:
    # Sanity-check against the project's known AES-GCM vector.
    known = aes_gcm_seal(bytes(32), bytes(12), b"", b"")
    assert known.hex() == "530f8afbc74536b9a963b4f1c4cb738b", known.hex()

    session_identifier = "vibescreen-channel-security-fixture-v1"
    session_epoch = 7
    key_epoch = 1
    key_id = "fixture-channel-security-key-v1"

    # Fixed key-derivation inputs. Both platforms derive identical keys.
    shared_secret = bytes(range(0x01, 0x21))
    bootstrap_secret = bytes(range(0x21, 0x41))
    context = bytes(range(0x41, 0x61))

    keys = derive_keys(shared_secret, bootstrap_secret, context)
    sess_hash = session_id_hash(session_identifier)

    cases = [
        ("host_audio_seq1", CHANNEL_AUDIO, SENDER_HOST, 1, bytes([0xAA, 0xBB, 0xCC, 0xDD])),
        ("device_audio_seq1", CHANNEL_AUDIO, SENDER_DEVICE, 1, bytes([0x11, 0x22, 0x33, 0x44, 0x55])),
        ("host_bulk_seq1", CHANNEL_BULK, SENDER_HOST, 1, bytes(range(0x10))),
        ("device_bulk_seq1", CHANNEL_BULK, SENDER_DEVICE, 1, bytes(range(0x20, 0x30))),
    ]

    records = []
    for name, channel, sender, sequence, plaintext in cases:
        sealed = seal_record(
            sess_hash, session_epoch, key_epoch, channel, sender, sequence, plaintext, keys,
        )
        records.append(
            {
                "name": name,
                "channel": "AUDIO" if channel == CHANNEL_AUDIO else "BULK",
                "sender": "HOST" if sender == SENDER_HOST else "DEVICE",
                "sequence": sequence,
                "plaintext": plaintext.hex(),
                **sealed,
            }
        )

    fixture = {
        "schema": "vibescreen.channel-security-fixture.v1",
        "fixture_scope": "TEST_ONLY_SYNTHETIC_MATERIAL_DO_NOT_USE_IN_PRODUCTION",
        "session": {
            "session_identifier": session_identifier,
            "session_epoch": session_epoch,
            "key_epoch": key_epoch,
            "key_id": key_id,
            "session_id_hash": sess_hash.hex(),
            "key_derivation": {
                "shared_secret": shared_secret.hex(),
                "bootstrap_secret": bootstrap_secret.hex(),
                "context": context.hex(),
            },
            "keys": {name: value.hex() for name, value in keys.items()},
        },
        "record_format": {
            "magic": f"0x{MAGIC:08x}",
            "version": VERSION,
            "header_bytes": HEADER_BYTES,
            "nonce_bytes": NONCE_BYTES,
            "tag_bytes": TAG_BYTES,
            "nonce_layout": "uint32_be(channel) || uint64_be(sequence)",
            "header_layout": (
                "uint32_be(magic) || uint8(version) || bytes16(session_id_hash) || "
                "uint64_be(session_epoch) || uint64_be(key_epoch) || uint8(sender) || "
                "uint8(channel) || bytes12(nonce)"
            ),
            "aead": "AES-256-GCM",
            "record_layout": "header || ciphertext || tag(16)",
        },
        "records": records,
    }

    out = Path(__file__).with_name("audio-bulk-records.json")
    out.write_text(json.dumps(fixture, indent=2) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    for rec in records:
        print(f"  {rec['name']}: record={len(bytes.fromhex(rec['record']))} bytes")


if __name__ == "__main__":
    main()
