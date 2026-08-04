#!/usr/bin/env python3
"""Deterministic one-allocation TURN client for relay integration tests."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import struct
import sys
import time

MAGIC_COOKIE = 0x2112A442
HEADER = struct.Struct("!HHI12s")
ATTRIBUTE_HEADER = struct.Struct("!HH")
ALLOCATE_REQUEST = 0x0003
ALLOCATE_SUCCESS = 0x0103
ALLOCATE_ERROR = 0x0113
REFRESH_REQUEST = 0x0004
REFRESH_SUCCESS = 0x0104
REFRESH_ERROR = 0x0114
USERNAME = 0x0006
MESSAGE_INTEGRITY = 0x0008
ERROR_CODE = 0x0009
LIFETIME = 0x000D
XOR_RELAYED_ADDRESS = 0x0016
REALM = 0x0014
NONCE = 0x0015
REQUESTED_TRANSPORT = 0x0019


class TurnProtocolError(RuntimeError):
    pass


def encode_attribute(attribute_type: int, value: bytes) -> bytes:
    padding = (-len(value)) % 4
    return ATTRIBUTE_HEADER.pack(attribute_type, len(value)) + value + (b"\0" * padding)


def parse_attributes(body: bytes) -> list[tuple[int, bytes, int]]:
    attributes: list[tuple[int, bytes, int]] = []
    offset = 0
    while offset < len(body):
        if len(body) - offset < ATTRIBUTE_HEADER.size:
            raise TurnProtocolError("truncated TURN attribute header")
        attribute_type, length = ATTRIBUTE_HEADER.unpack_from(body, offset)
        value_start = offset + ATTRIBUTE_HEADER.size
        value_end = value_start + length
        padded_end = value_end + ((-length) % 4)
        if value_end > len(body) or padded_end > len(body):
            raise TurnProtocolError("truncated TURN attribute value")
        attributes.append((attribute_type, body[value_start:value_end], offset))
        offset = padded_end
    return attributes


def parse_message(packet: bytes, transaction_id: bytes) -> tuple[int, bytes, list[tuple[int, bytes, int]]]:
    if len(packet) < HEADER.size:
        raise TurnProtocolError("truncated TURN header")
    message_type, body_length, cookie, response_transaction = HEADER.unpack_from(packet)
    if message_type & 0xC000:
        raise TurnProtocolError("invalid TURN message type top bits")
    if cookie != MAGIC_COOKIE:
        raise TurnProtocolError("invalid TURN magic cookie")
    if response_transaction != transaction_id:
        raise TurnProtocolError("TURN transaction ID mismatch")
    if body_length % 4 != 0 or len(packet) != HEADER.size + body_length:
        raise TurnProtocolError("invalid TURN message length")
    body = packet[HEADER.size:]
    return message_type, body, parse_attributes(body)


def first_attribute(attributes: list[tuple[int, bytes, int]], attribute_type: int) -> bytes:
    values = [value for candidate_type, value, _ in attributes if candidate_type == attribute_type]
    if not values:
        raise TurnProtocolError(f"missing TURN attribute 0x{attribute_type:04x}")
    if len(values) != 1:
        raise TurnProtocolError(f"duplicate TURN attribute 0x{attribute_type:04x}")
    return values[0]


def error_code(attributes: list[tuple[int, bytes, int]]) -> int:
    value = first_attribute(attributes, ERROR_CODE)
    if len(value) < 4:
        raise TurnProtocolError("invalid TURN ERROR-CODE attribute")
    if value[:2] != b"\0\0" or value[2] & 0xF8:
        raise TurnProtocolError("invalid TURN ERROR-CODE reserved bits")
    code_class = value[2] & 0x07
    if code_class < 3 or code_class > 6 or value[3] > 99:
        raise TurnProtocolError("invalid TURN ERROR-CODE value")
    return code_class * 100 + value[3]


def long_term_key(username: str, realm: str, password: str) -> bytes:
    return hashlib.md5(f"{username}:{realm}:{password}".encode(), usedforsecurity=False).digest()


def authenticated_request(
    message_type: int,
    transaction_id: bytes,
    attributes: list[bytes],
    username: str,
    realm: str,
    nonce: bytes,
    password: str,
) -> bytes:
    before_integrity = b"".join(
        attributes
        + [
            encode_attribute(USERNAME, username.encode()),
            encode_attribute(REALM, realm.encode()),
            encode_attribute(NONCE, nonce),
        ]
    )
    integrity_length = len(before_integrity) + 24
    header = HEADER.pack(message_type, integrity_length, MAGIC_COOKIE, transaction_id)
    digest = hmac.new(long_term_key(username, realm, password), header + before_integrity, hashlib.sha1).digest()
    return header + before_integrity + encode_attribute(MESSAGE_INTEGRITY, digest)


def verify_message_integrity(packet: bytes, attributes: list[tuple[int, bytes, int]], key: bytes) -> None:
    integrity_entries = [(value, offset) for kind, value, offset in attributes if kind == MESSAGE_INTEGRITY]
    if len(integrity_entries) != 1:
        raise TurnProtocolError("authenticated TURN response requires one MESSAGE-INTEGRITY")
    integrity, offset = integrity_entries[0]
    if len(integrity) != hashlib.sha1().digest_size:
        raise TurnProtocolError("invalid MESSAGE-INTEGRITY length")
    message_type, _, cookie, transaction_id = HEADER.unpack_from(packet)
    adjusted_header = HEADER.pack(message_type, offset + 24, cookie, transaction_id)
    expected = hmac.new(key, adjusted_header + packet[HEADER.size : HEADER.size + offset], hashlib.sha1).digest()
    if not hmac.compare_digest(integrity, expected):
        raise TurnProtocolError("TURN response MESSAGE-INTEGRITY mismatch")


def unauthenticated_allocate(transaction_id: bytes) -> bytes:
    attributes = encode_attribute(REQUESTED_TRANSPORT, bytes((17, 0, 0, 0)))
    return HEADER.pack(ALLOCATE_REQUEST, len(attributes), MAGIC_COOKIE, transaction_id) + attributes


def decode_xor_address(value: bytes, transaction_id: bytes) -> str:
    if len(value) < 4:
        raise TurnProtocolError("invalid XOR-RELAYED-ADDRESS")
    family = value[1]
    port = struct.unpack_from("!H", value, 2)[0] ^ (MAGIC_COOKIE >> 16)
    mask = struct.pack("!I", MAGIC_COOKIE) + transaction_id
    if family == 0x01 and len(value) == 8:
        address = bytes(left ^ right for left, right in zip(value[4:], mask[:4]))
        return f"{socket.inet_ntop(socket.AF_INET, address)}:{port}"
    if family == 0x02 and len(value) == 20:
        address = bytes(left ^ right for left, right in zip(value[4:], mask))
        return f"[{socket.inet_ntop(socket.AF_INET6, address)}]:{port}"
    raise TurnProtocolError("unsupported XOR-RELAYED-ADDRESS family or length")


class TurnClient:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float) -> None:
        address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.connect(address)
        self.socket.settimeout(timeout)
        self.timeout = timeout
        self.username = username
        self.password = password
        self.realm = ""
        self.nonce = b""

    def close(self) -> None:
        self.socket.close()

    def transact(
        self, request: bytes, transaction_id: bytes, integrity_key: bytes | None = None
    ) -> tuple[int, list[tuple[int, bytes, int]]]:
        last_error: Exception | None = None
        deadline = time.monotonic() + self.timeout
        for attempt in range(2):
            self.socket.send(request)
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.socket.settimeout(remaining / (2 - attempt))
                packet = self.socket.recv(65535)
                message_type, _, attributes = parse_message(packet, transaction_id)
                if integrity_key is not None:
                    verify_message_integrity(packet, attributes, integrity_key)
                return message_type, attributes
            except socket.timeout as error:
                last_error = error
        raise TurnProtocolError("TURN response timed out at the bounded deadline") from last_error

    def allocate(self) -> tuple[int, str | None]:
        challenge_transaction = secrets.token_bytes(12)
        challenge_type, challenge_attributes = self.transact(
            unauthenticated_allocate(challenge_transaction), challenge_transaction
        )
        if challenge_type != ALLOCATE_ERROR or error_code(challenge_attributes) != 401:
            raise TurnProtocolError("TURN Allocate did not return the required 401 challenge")
        self.realm = first_attribute(challenge_attributes, REALM).decode()
        self.nonce = first_attribute(challenge_attributes, NONCE)

        transaction_id = secrets.token_bytes(12)
        request = authenticated_request(
            ALLOCATE_REQUEST,
            transaction_id,
            [encode_attribute(REQUESTED_TRANSPORT, bytes((17, 0, 0, 0)))],
            self.username,
            self.realm,
            self.nonce,
            self.password,
        )
        key = long_term_key(self.username, self.realm, self.password)
        response_type, attributes = self.transact(request, transaction_id, key)
        if response_type == ALLOCATE_SUCCESS:
            lifetime = first_attribute(attributes, LIFETIME)
            if len(lifetime) != 4 or struct.unpack("!I", lifetime)[0] == 0:
                raise TurnProtocolError("Allocate success has invalid LIFETIME")
            return 200, decode_xor_address(first_attribute(attributes, XOR_RELAYED_ADDRESS), transaction_id)
        if response_type == ALLOCATE_ERROR:
            return error_code(attributes), None
        raise TurnProtocolError(f"unexpected authenticated Allocate response 0x{response_type:04x}")

    def release(self) -> None:
        transaction_id = secrets.token_bytes(12)
        request = authenticated_request(
            REFRESH_REQUEST,
            transaction_id,
            [encode_attribute(LIFETIME, struct.pack("!I", 0))],
            self.username,
            self.realm,
            self.nonce,
            self.password,
        )
        key = long_term_key(self.username, self.realm, self.password)
        response_type, attributes = self.transact(request, transaction_id, key)
        if response_type == REFRESH_ERROR:
            raise TurnProtocolError(f"TURN release failed with {error_code(attributes)}")
        if response_type != REFRESH_SUCCESS:
            raise TurnProtocolError(f"unexpected Refresh response 0x{response_type:04x}")
        lifetime = first_attribute(attributes, LIFETIME)
        if len(lifetime) != 4 or struct.unpack("!I", lifetime)[0] != 0:
            raise TurnProtocolError("release Refresh did not confirm LIFETIME=0")


def read_password_file(path: Path) -> str:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise TurnProtocolError("password file must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TurnProtocolError("password file must not grant group or world permissions")
    password = path.read_text(encoding="utf-8").strip()
    if not password or "\n" in password or "\r" in password:
        raise TurnProtocolError("password file must contain exactly one non-empty line")
    return password


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-host", required=True)
    parser.add_argument("--server-port", required=True, type=int)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--expect-code", type=int, choices=(200, 486), default=200)
    parser.add_argument("--transient-code", type=int, choices=(486,))
    parser.add_argument("--wait-deadline-seconds", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--release-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if (
        args.server_port < 1
        or args.server_port > 65535
        or args.timeout <= 0
        or args.hold_seconds < 0
        or args.wait_deadline_seconds < 0
    ):
        raise TurnProtocolError("invalid port, timeout, or hold duration")
    if args.ready_file is not None and args.expect_code != 200:
        raise TurnProtocolError("ready-file requires a successful allocation")
    if (args.transient_code is None) != (args.wait_deadline_seconds == 0):
        raise TurnProtocolError("transient-code and a positive wait deadline must be used together")
    if args.transient_code == args.expect_code:
        raise TurnProtocolError("transient code must differ from the expected code")

    release_requested = False

    def request_release(_signum: int, _frame: object) -> None:
        nonlocal release_requested
        release_requested = True

    signal.signal(signal.SIGTERM, request_release)
    signal.signal(signal.SIGINT, request_release)
    password = read_password_file(args.password_file)
    client: TurnClient | None = None
    try:
        wait_deadline = time.monotonic() + args.wait_deadline_seconds
        attempt = 0
        while True:
            attempt += 1
            attempt_timeout = args.timeout
            if args.transient_code is not None:
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    raise TurnProtocolError(
                        f"TURN code stayed transient until the {args.wait_deadline_seconds:.3f}s deadline"
                    )
                attempt_timeout = min(attempt_timeout, remaining)
            client = TurnClient(args.server_host, args.server_port, args.username, password, attempt_timeout)
            code, relayed_address = client.allocate()
            result = {"attempt": attempt, "code": code, "relayed_address": relayed_address}
            print(json.dumps(result, sort_keys=True), flush=True)
            if code == args.expect_code:
                break
            if code != args.transient_code:
                raise TurnProtocolError(f"expected TURN code {args.expect_code}, received {code}")
            client.close()
            client = None
            if time.monotonic() >= wait_deadline:
                raise TurnProtocolError(
                    f"TURN code stayed {code} until the {args.wait_deadline_seconds:.3f}s deadline"
                )
            time.sleep(0.05)
        if code != 200:
            return 0
        if args.ready_file is not None:
            temporary = args.ready_file.with_suffix(args.ready_file.suffix + ".tmp")
            temporary.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
            os.replace(temporary, args.ready_file)
        deadline = time.monotonic() + args.hold_seconds
        while not release_requested and time.monotonic() < deadline:
            if args.release_file is not None and args.release_file.exists():
                break
            time.sleep(0.05)
        client.release()
        print(json.dumps({"code": 200, "released": True}, sort_keys=True), flush=True)
        return 0
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, UnicodeError, TurnProtocolError) as error:
        print(f"turn-allocation-helper: {error}", file=sys.stderr)
        raise SystemExit(1)
