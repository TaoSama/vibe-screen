"""Summarize WakeHost current-base acceptance evidence.

This gate is intentionally evidence-only. It does not put a Mac to sleep, send
Wake-on-LAN packets, touch router configuration, or mutate pairing state. A
passing result requires retained proof that the current base woke a real sleeping
Mac through an authorized WakeHost request on a verified WOL-capable network.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION

GATE_PROFILE = "phase5-wake-host-current-base"
OWNER_PR = 199
BASELINE_PR = 225
STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_FAIL = "fail"
HASH_RE = re.compile(r"^[0-9a-fA-F]{40}$")

REQUIRED_FIELDS = (
    (
        "current_main_verified",
        "record the exact current origin/main commit used for the WakeHost current-base check",
    ),
    (
        "magic_packet_path_baseline_merged",
        "confirm PR #225's authenticated magic-packet path is present in the current base",
    ),
    (
        "paired_authorization_offline_passed",
        "run focused offline authorization/protocol tests for the current base",
    ),
    (
        "device_identity_recorded",
        "record the actual paired client device identity without relabeling substitute hardware",
    ),
    (
        "identity_signed_host_tcc_ready",
        "run an identity-signed installed Host with required TCC permissions before the sleep attempt",
    ),
    (
        "wake_for_network_access_enabled",
        "record macOS and NIC Wake for network access / Wake-on-LAN settings",
    ),
    (
        "host_sleep_state_recorded",
        "record the target Mac entering a real sleep state before the wake request",
    ),
    (
        "router_broadcast_or_directed_wol_verified",
        "record router, subnet broadcast, or directed WOL delivery support for the target network",
    ),
    (
        "magic_packet_emitted_after_authorization",
        "prove the WOL magic packet was emitted only after WakeHost authorization succeeded",
    ),
    (
        "network_packet_capture_retained",
        "retain packet capture or equivalent router log evidence for the WOL packet",
    ),
    (
        "mac_woke_from_sleep_observed",
        "record the Mac waking from the prior sleep state after the authorized request",
    ),
    ("post_wake_host_available_observed", "record Host or network availability after wake"),
    ("negative_unpaired_rejected", "retain a negative check showing an unpaired device is rejected"),
    ("negative_expired_authorization_rejected", "retain a negative check showing expired authorization is rejected"),
    ("negative_replayed_nonce_rejected", "retain a negative check showing nonce replay is rejected"),
    ("negative_wrong_key_or_signature_rejected", "retain a negative check showing a wrong key or signature is rejected"),
    ("host_logs_retained", "retain Host logs covering the authorized and negative WakeHost attempts"),
    ("client_logs_retained", "retain client logs covering the authorized and negative WakeHost attempts"),
)

BLOCKING_FIELDS = {
    "current_main_verified",
    "magic_packet_path_baseline_merged",
    "identity_signed_host_tcc_ready",
    "wake_for_network_access_enabled",
    "host_sleep_state_recorded",
    "router_broadcast_or_directed_wol_verified",
    "mac_woke_from_sleep_observed",
}

BOOLEAN_FIELDS = tuple(field for field, _ in REQUIRED_FIELDS)
FAILURE_FIELD = "wake_attempt_failed_observed"


class WakeHostCurrentBaseEvidenceError(ValueError):
    """Raised when a WakeHost current-base evidence record is malformed."""


def load_record(stream: TextIO) -> dict[str, Any]:
    try:
        record = json.load(stream)
    except json.JSONDecodeError as error:
        raise WakeHostCurrentBaseEvidenceError(f"invalid JSON: {error}") from error
    if not isinstance(record, dict):
        raise WakeHostCurrentBaseEvidenceError(
            "WakeHost current-base evidence must be a JSON object"
        )
    return record


def _bool_value(record: dict[str, Any], field: str) -> bool:
    value = record.get(field, False)
    if isinstance(value, bool):
        return value
    raise WakeHostCurrentBaseEvidenceError(f"{field} must be true or false")


def _string_list(record: dict[str, Any], field: str) -> list[str]:
    value = record.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WakeHostCurrentBaseEvidenceError(f"{field} must be a list of strings")
    if any(not item.strip() for item in value):
        raise WakeHostCurrentBaseEvidenceError(f"{field} must contain only non-empty strings")
    return value


def _string_value(record: dict[str, Any], field: str) -> str:
    value = record.get(field, "")
    if isinstance(value, str):
        return value
    raise WakeHostCurrentBaseEvidenceError(f"{field} must be a string")


def _current_main_sha(record: dict[str, Any], current_main_verified: bool) -> str | None:
    value = record.get("current_main_sha")
    if value is None:
        if current_main_verified:
            raise WakeHostCurrentBaseEvidenceError(
                "current_main_sha is required when current_main_verified is true"
            )
        return None
    if isinstance(value, str) and HASH_RE.fullmatch(value):
        return value.lower()
    raise WakeHostCurrentBaseEvidenceError("current_main_sha must be a 40-character Git SHA")


def _optional_run_id(record: dict[str, Any]) -> str | None:
    value = record.get("run_id")
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise WakeHostCurrentBaseEvidenceError("run_id must be a non-empty string")


def _explicit_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise WakeHostCurrentBaseEvidenceError("run_id must be a non-empty string")


def summarize(record: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    field_values = {field: _bool_value(record, field) for field in BOOLEAN_FIELDS}
    current_main_sha = _current_main_sha(record, field_values["current_main_verified"])
    failure_observed = _bool_value(record, FAILURE_FIELD)
    observations = {**field_values, FAILURE_FIELD: failure_observed}
    missing = [
        {"field": field, "requirement": requirement}
        for field, requirement in REQUIRED_FIELDS
        if not field_values[field]
    ]
    blocking_reasons = [
        item for item in missing if item["field"] in BLOCKING_FIELDS
    ]
    failure_reasons = _string_list(record, "failure_reasons")
    if failure_observed:
        verdict = STATUS_FAIL
        if not failure_reasons:
            failure_reasons = ["WakeHost attempt failed during a real or claimed hardware run"]
    elif not missing:
        verdict = STATUS_PASS
    elif blocking_reasons:
        verdict = STATUS_BLOCKED
    else:
        verdict = STATUS_INSUFFICIENT

    can_close = verdict == STATUS_PASS
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            _explicit_run_id(run_id) or _optional_run_id(record) or str(uuid.uuid4())
        ),
        "kind": "wake_host_current_base_gate",
        "profile": GATE_PROFILE,
        "owner_pr": OWNER_PR,
        "baseline_pr": BASELINE_PR,
        "current_main_sha": current_main_sha,
        "verdict": verdict,
        "can_close_wake_host_current_base_gate": can_close,
        "can_claim_sleeping_mac_wake": can_close,
        "requires_real_sleeping_mac": True,
        "requires_network_wol_delivery": True,
        "offline_baseline_only_is_not_acceptance": True,
        "observations": observations,
        "missing_requirements": missing,
        "blocking_reasons": blocking_reasons,
        "failure_reasons": failure_reasons,
        "artifact_paths": _string_list(record, "artifact_paths"),
        "blocking_notes": _string_list(record, "blocking_notes"),
        "notes": _string_value(record, "notes"),
    }


def _write_summary(summary: dict[str, Any], output: TextIO) -> None:
    json.dump(summary, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize Vibe Screen WakeHost current-base evidence.",
        epilog=(
            "Input is a JSON object with explicit boolean observations. Missing "
            "booleans default to false so absent sleeping-Mac, router/NIC, "
            "identity-signed Host, or negative security evidence cannot close the gate."
        ),
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="WakeHost current-base evidence .json file, or - for stdin; defaults to stdin",
    )
    parser.add_argument("--output", help="output summary JSON file (default: stdout)")
    parser.add_argument("--run-id", help="identifier shared with the evidence bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.input == "-":
            record = load_record(sys.stdin)
        else:
            with Path(args.input).open("r", encoding="utf-8") as stream:
                record = load_record(stream)
        summary = summarize(record, run_id=args.run_id)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_summary(summary, stream)
        else:
            _write_summary(summary, sys.stdout)
    except (WakeHostCurrentBaseEvidenceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 3
    return {
        STATUS_PASS: 0,
        STATUS_BLOCKED: 1,
        STATUS_FAIL: 2,
        STATUS_INSUFFICIENT: 3,
    }[str(summary["verdict"])]


if __name__ == "__main__":
    raise SystemExit(main())
