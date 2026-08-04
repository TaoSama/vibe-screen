#!/usr/bin/env python3
"""Execute Phase 3 replay, rotation, and revocation attack vectors.

With no --sut command this validates the vectors against a small policy model;
that mode never claims product cryptography coverage. With --sut, each vector
is sent as one JSON line to the implementation under test, which must return
one JSON line containing boolean ``accepted`` and string ``reason`` fields.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

MEDIA_REPLAY_WINDOW = 64
ORACLE_FIELDS = frozenset({"expect", "name"})
ROLES = frozenset({"host", "device"})


class VectorError(RuntimeError):
    """Raised for invalid vectors or SUT protocol failures."""


@dataclass
class KeyState:
    key_id: str
    key_epoch: int
    revoked: bool = False


class ReferencePolicy:
    """Stateful acceptance policy only; not a cryptographic implementation."""

    def __init__(self) -> None:
        self.keys: dict[str, KeyState] = {}
        self.devices: dict[str, str] = {}
        self.highest_sequence: dict[tuple[str, int, str, str, str], int] = {}
        self.seen_sequences: dict[tuple[str, int, str, str, str], set[int]] = {}
        self.revocation_sequence = 0
        self.highest_session_epoch: dict[str, int] = {}

    def execute(self, vector: dict[str, Any]) -> dict[str, Any]:
        action = vector.get("action")
        if action == "enroll":
            device = self._text(vector, "device_id")
            key_id = self._text(vector, "key_id")
            epoch = self._positive_int(vector, "key_epoch")
            if device in self.devices or key_id in self.keys:
                return self._result(False, "identity_already_exists")
            self.devices[device] = key_id
            self.keys[key_id] = KeyState(key_id, epoch)
            return self._result(True, "enrolled")
        if action == "packet":
            return self._packet(vector)
        if action == "rotate":
            return self._rotate(vector)
        if action == "revoke":
            return self._revoke(vector)
        raise VectorError(f"unsupported action: {action!r}")

    def _packet(self, vector: dict[str, Any]) -> dict[str, Any]:
        key_id = self._text(vector, "key_id")
        state = self.keys.get(key_id)
        if state is None:
            return self._result(False, "unknown_key")
        if state.revoked:
            return self._result(False, "revoked_key")
        key_epoch = self._positive_int(vector, "key_epoch")
        if key_epoch != state.key_epoch:
            return self._result(False, "stale_key_epoch")
        session_id = self._text(vector, "session_id")
        session_epoch = self._positive_int(vector, "session_epoch")
        if session_epoch < self.highest_session_epoch.get(session_id, 0):
            return self._result(False, "stale_session_epoch")
        channel = self._text(vector, "channel")
        if channel not in {"control", "media"}:
            raise VectorError("channel must be control or media")
        sender_role = self._role(vector, "sender_role")
        receiver_role = self._role(vector, "receiver_role")
        if sender_role == receiver_role:
            return self._result(False, "reflected_sender_role")
        sequence = self._positive_int(vector, "sequence", allow_zero=True)
        window = (session_id, session_epoch, key_id, channel, sender_role)
        previous = self.highest_sequence.get(window, -1)
        seen = self.seen_sequences.setdefault(window, set())
        if sequence in seen or (channel == "control" and sequence <= previous):
            return self._result(False, "replayed_sequence")
        if channel == "media" and previous >= 0 and sequence <= previous - MEDIA_REPLAY_WINDOW:
            return self._result(False, "outside_replay_window")
        self.highest_sequence[window] = max(previous, sequence)
        self.highest_session_epoch[session_id] = max(self.highest_session_epoch.get(session_id, 0), session_epoch)
        seen.add(sequence)
        floor = self.highest_sequence[window] - MEDIA_REPLAY_WINDOW
        self.seen_sequences[window] = {item for item in seen if item > floor}
        return self._result(True, "packet_accepted")

    def _rotate(self, vector: dict[str, Any]) -> dict[str, Any]:
        device = self._text(vector, "device_id")
        old_key = self._text(vector, "current_key_id")
        new_key = self._text(vector, "next_key_id")
        next_epoch = self._positive_int(vector, "next_key_epoch")
        current = self.keys.get(old_key)
        if self.devices.get(device) != old_key or current is None or current.revoked:
            return self._result(False, "current_key_not_active")
        if next_epoch != current.key_epoch + 1:
            return self._result(False, "non_monotonic_key_epoch")
        if new_key in self.keys:
            return self._result(False, "next_key_already_exists")
        if not vector.get("current_signature_valid", False):
            return self._result(False, "invalid_rotation_signature")
        if not vector.get("next_signature_valid", False):
            return self._result(False, "invalid_next_key_signature")
        current.revoked = True
        self.keys[new_key] = KeyState(new_key, next_epoch)
        self.devices[device] = new_key
        return self._result(True, "key_rotated")

    def _revoke(self, vector: dict[str, Any]) -> dict[str, Any]:
        device = self._text(vector, "device_id")
        key_id = self._text(vector, "key_id")
        sequence = self._positive_int(vector, "revocation_sequence")
        if not vector.get("authority_signature_valid", False):
            return self._result(False, "invalid_revocation_signature")
        if sequence <= self.revocation_sequence:
            return self._result(False, "stale_revocation_sequence")
        state = self.keys.get(key_id)
        if state is None:
            return self._result(False, "unknown_key")
        if self.devices.get(device) != key_id:
            return self._result(False, "key_not_active_for_device")
        state.revoked = True
        self.revocation_sequence = sequence
        return self._result(True, "key_revoked")

    @staticmethod
    def _result(accepted: bool, reason: str) -> dict[str, Any]:
        return {"accepted": accepted, "reason": reason}

    @staticmethod
    def _text(vector: dict[str, Any], key: str) -> str:
        value = vector.get(key)
        if not isinstance(value, str) or not value:
            raise VectorError(f"{key} must be a non-empty string")
        return value

    @classmethod
    def _role(cls, vector: dict[str, Any], key: str) -> str:
        value = cls._text(vector, key)
        if value not in ROLES:
            raise VectorError(f"{key} must be host or device")
        return value

    @staticmethod
    def _positive_int(vector: dict[str, Any], key: str, allow_zero: bool = False) -> int:
        value = vector.get(key)
        minimum = 0 if allow_zero else 1
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise VectorError(f"{key} must be an integer >= {minimum}")
        return value


def load_vectors(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VectorError(f"cannot read {path}: {error}") from error
    if not isinstance(raw, list) or not raw or not all(isinstance(item, dict) for item in raw):
        raise VectorError("vector file must be a non-empty JSON array of objects")
    names: set[str] = set()
    for vector in raw:
        name = vector.get("name")
        expected = vector.get("expect")
        if not isinstance(name, str) or not name or name in names:
            raise VectorError("every vector needs a unique non-empty name")
        if not isinstance(expected, dict) or not isinstance(expected.get("accepted"), bool) or not isinstance(expected.get("reason"), str):
            raise VectorError(f"{name}: expect must contain accepted and reason")
        names.add(name)
    return raw


def _execute_external(command: Sequence[str], vectors: list[dict[str, Any]], timeout: float) -> list[dict[str, Any]]:
    if not command:
        raise VectorError("--sut requires a command after --")
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError as error:
        raise VectorError(f"cannot start SUT: {error}") from error
    requests = ({key: value for key, value in vector.items() if key not in ORACLE_FIELDS} for vector in vectors)
    request = "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in requests)
    try:
        stdout, stderr = process.communicate(request, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate()
        raise VectorError(f"SUT timed out after {timeout:g}s") from error
    if process.returncode != 0:
        raise VectorError(f"SUT exited {process.returncode}: {stderr.strip() or 'no stderr'}")
    lines = stdout.splitlines()
    if len(lines) != len(vectors):
        raise VectorError(f"SUT returned {len(lines)} responses for {len(vectors)} vectors")
    responses: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            raise VectorError(f"SUT response {index + 1} is not JSON: {error}") from error
        if not isinstance(response, dict):
            raise VectorError(f"SUT response {index + 1} is not an object")
        if not isinstance(response.get("accepted"), bool) or not isinstance(response.get("reason"), str):
            raise VectorError(f"SUT response {index + 1} must contain boolean accepted and string reason")
        responses.append(response)
    return responses


def run_vectors(vectors: list[dict[str, Any]], sut_command: Sequence[str] | None = None, timeout: float = 30) -> dict[str, Any]:
    if timeout <= 0:
        raise VectorError("timeout must be positive")
    if sut_command is None:
        policy = ReferencePolicy()
        responses = [policy.execute(vector) for vector in vectors]
        mode = "reference-policy-model"
    else:
        responses = _execute_external(sut_command, vectors, timeout)
        mode = "external-sut"
    cases = []
    for vector, response in zip(vectors, responses):
        expected = vector["expect"]
        passed = response.get("accepted") == expected["accepted"] and response.get("reason") == expected["reason"]
        cases.append({"name": vector["name"], "passed": passed, "expected": expected, "actual": response})
    return {"mode": mode, "passed": all(case["passed"] for case in cases), "cases": cases}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, default=Path(__file__).resolve().parents[2] / "tests/phase3/vectors/security.json")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sut", nargs=argparse.REMAINDER, help="external JSON-lines SUT command; put after all other options")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.sut
    if command and command[0] == "--":
        command = command[1:]
    try:
        report = run_vectors(load_vectors(args.vectors), command, args.timeout)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(args.output)
        else:
            print(rendered, end="")
        return 0 if report["passed"] else 1
    except (OSError, VectorError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
