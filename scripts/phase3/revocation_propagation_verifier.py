#!/usr/bin/env python3
"""Verify Phase 3 cross-service revocation propagation evidence.

This verifier consumes a curated JSON report from an Authority/signaling/relay/
coturn run. It is intentionally a fail-closed contract checker, not a coturn log
parser and not a deployment driver. A report passes only when it proves that a
revocation reached the active signaling session, future and already-issued TURN
credential paths, the active coturn allocation, and post-revocation data-plane
traffic. Missing live deployment proof is reported as blocked instead of passed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, NoReturn, Sequence

SCHEMA = "dev.vibescreen.phase3-revocation-propagation/v1"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"

ALLOWED_REJECTION_STATUS = frozenset({401, 403, 404, 438, 486})
ALLOWED_REVOCATION_STATUS = frozenset({200, 202, 204})
LIVE_PRODUCTION_EVIDENCE_KIND = "live_production"
RECOGNIZED_EVIDENCE_KINDS = frozenset(
    {"blocked", "local_control_plane", "offline_fixture", LIVE_PRODUCTION_EVIDENCE_KIND}
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
SUMMARY_RESERVED_KEYS = frozenset({"schema", "status", "missing", "failures", "warnings"})
SECRET_FIELD_NAMES = frozenset(
    {
        "admin_token",
        "api_key",
        "authorization",
        "bearer",
        "credential_password",
        "password",
        "private_key",
        "raw_credential",
        "secret",
        "shared_secret",
        "token",
        "turn_password",
    }
)
SECRET_FIELD_SUFFIXES = ("_token", "_password", "_secret", "_private_key")
SECRET_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "observed_at",
        "source",
        "authority_revocation",
        "signaling",
        "relay_admission",
        "coturn_allocation",
        "data_plane",
        "notes",
    }
)
SOURCE_FIELDS = frozenset(
    {
        "commit",
        "topology",
        "authority_url_kind",
        "coturn_source_id",
        "deployment_id",
        "evidence_kind",
        "public_internet_path",
        "remote_turn_deployment",
        "synthetic_fixture",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "device_revoked",
        "session_revoked",
        "revocation_status",
        "audit_event_observed",
        "chain_id",
        "tombstone_id",
        "tombstone_persisted",
        "tombstone_persisted_at",
    }
)
SIGNALING_FIELDS = frozenset(
    {
        "active_session_rejected",
        "rejection_status",
        "long_poll_woke_fail_closed",
        "chain_id",
        "rejected_tombstone_id",
        "rejection_observed_at",
    }
)
RELAY_ADMISSION_FIELDS = frozenset(
    {
        "new_grant_rejected",
        "new_grant_status",
        "same_allocation_retry_rejected",
        "same_allocation_retry_status",
        "stale_grant_reuse_rejected",
        "stale_grant_status",
        "grant_ttl_seconds",
        "chain_id",
        "rejected_tombstone_id",
        "credential_allocation_id",
        "rejection_observed_at",
    }
)
COTURN_FIELDS = frozenset(
    {
        "active_before_revocation",
        "allocation_id",
        "disconnect_observed",
        "disconnect_method",
        "disconnect_observed_at",
        "chain_id",
        "revoked_tombstone_id",
    }
)
DATA_PLANE_FIELDS = frozenset(
    {
        "traffic_established_before_revocation",
        "post_revocation_traffic_denied",
        "relayed_packets_after_revocation",
        "denial_observed_at",
        "chain_id",
        "rejected_tombstone_id",
        "allocation_id",
        "rejected_after_disconnect",
    }
)


class VerificationError(RuntimeError):
    """Raised when an evidence report is malformed or unsafe to evaluate."""


@dataclass(frozen=True)
class VerificationResult:
    status: str
    missing: tuple[str, ...]
    failures: tuple[str, ...]
    warnings: tuple[str, ...]
    observations: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        collisions = SUMMARY_RESERVED_KEYS & set(self.observations)
        if collisions:
            raise VerificationError(
                f"summary observations collide with reserved keys: {', '.join(sorted(collisions))}"
            )
        output = {
            "schema": SCHEMA,
            "status": self.status,
            "missing": list(self.missing),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }
        output.update(self.observations)
        return output


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _read_report(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read report: {exc}") from exc
    if not isinstance(raw, dict):
        _fail("report must be a JSON object")
    _reject_secrets(raw)
    return raw


def _reject_secrets(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(f"{path} contains a non-string key")
            normalized = key.lower().replace("-", "_")
            if normalized in SECRET_FIELD_NAMES or normalized.endswith(SECRET_FIELD_SUFFIXES):
                _fail(f"{path}.{key} must not contain secret material")
            _reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                _fail(f"{path} appears to contain secret material")


def _object(value: Any, field: str, allowed_fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    extra = set(value) - allowed_fields
    if extra:
        _fail(f"{field} contains unknown fields: {', '.join(sorted(extra))}")
    return value


def _required_bool(
    section: dict[str, Any], key: str, label: str, missing: list[str], failures: list[str]
) -> bool | None:
    value = section.get(key)
    if value is True:
        return True
    if value is False:
        failures.append(label)
        return False
    missing.append(label)
    return None


def _optional_status(
    section: dict[str, Any], key: str, label: str, allowed: frozenset[int], warnings: list[str]
) -> None:
    if key not in section:
        warnings.append(f"{label} status not recorded")
        return
    value = section[key]
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(f"{label} must be an integer HTTP/TURN status code")
    if value not in allowed:
        _fail(f"{label} status {value} is outside the accepted fail-closed set")


def _optional_positive_int(section: dict[str, Any], key: str, label: str) -> int | None:
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _fail(f"{label} must be a non-negative integer")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise VerificationError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include a timezone")
    return parsed


def _identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be a bounded ASCII identifier")


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        _fail(f"{field} must be a boolean")
    return value


def _required_identifier(
    section: dict[str, Any], key: str, field: str, label: str, missing: list[str]
) -> str | None:
    if key not in section:
        missing.append(label)
        return None
    value = section[key]
    _identifier(value, field)
    return value


def _optional_identifier(section: dict[str, Any], key: str, field: str) -> str | None:
    if key not in section:
        return None
    value = section[key]
    _identifier(value, field)
    return value


def _required_timestamp(
    section: dict[str, Any], key: str, field: str, label: str, missing: list[str]
) -> datetime | None:
    if key not in section:
        missing.append(label)
        return None
    return _timestamp(section[key], field)


def _validate_source_evidence_boundary(
    source: dict[str, Any], missing: list[str], failures: list[str]
) -> None:
    evidence_kind = source.get("evidence_kind")
    if evidence_kind is None:
        missing.append("live production evidence classification")
    elif evidence_kind not in RECOGNIZED_EVIDENCE_KINDS:
        _fail(
            "source.evidence_kind must be one of "
            f"{', '.join(sorted(RECOGNIZED_EVIDENCE_KINDS))}"
        )
    elif evidence_kind != LIVE_PRODUCTION_EVIDENCE_KIND:
        missing.append("live production evidence classification")

    if source.get("topology") != "production":
        if evidence_kind == LIVE_PRODUCTION_EVIDENCE_KIND:
            failures.append("live production evidence cannot use non-production topology")
        else:
            missing.append("production topology")

    for key, label in (
        ("public_internet_path", "public Internet path evidence"),
        ("remote_turn_deployment", "remote TURN deployment evidence"),
    ):
        observed = _optional_bool(source.get(key), f"source.{key}")
        if observed is not True:
            missing.append(label)

    synthetic = _optional_bool(source.get("synthetic_fixture"), "source.synthetic_fixture")
    if synthetic is None:
        missing.append("non-synthetic evidence boundary")
    elif synthetic is True:
        if evidence_kind == LIVE_PRODUCTION_EVIDENCE_KIND:
            failures.append("synthetic fixture cannot claim live production evidence")
        else:
            missing.append("non-synthetic evidence boundary")


def _validate_chain_binding(
    authority: dict[str, Any],
    signaling: dict[str, Any],
    relay_admission: dict[str, Any],
    coturn: dict[str, Any],
    data_plane: dict[str, Any],
    missing: list[str],
    failures: list[str],
) -> bool:
    chain_missing: list[str] = []
    chain_failures: list[str] = []
    authority_chain = _required_identifier(
        authority,
        "chain_id",
        "authority_revocation.chain_id",
        "authority revocation chain id",
        chain_missing,
    )
    tombstone_id = _required_identifier(
        authority,
        "tombstone_id",
        "authority_revocation.tombstone_id",
        "authority tombstone identity",
        chain_missing,
    )
    authority_at = _required_timestamp(
        authority,
        "tombstone_persisted_at",
        "authority_revocation.tombstone_persisted_at",
        "authority tombstone timestamp",
        chain_missing,
    )

    chain_sections = (
        (signaling, "signaling", "signaling revocation chain id"),
        (relay_admission, "relay_admission", "TURN credential rejection chain id"),
        (coturn, "coturn_allocation", "coturn allocation disconnect chain id"),
        (data_plane, "data_plane", "post-revocation traffic rejection chain id"),
    )
    for section, field, label in chain_sections:
        chain_id = _required_identifier(section, "chain_id", f"{field}.chain_id", label, chain_missing)
        if authority_chain is not None and chain_id is not None and chain_id != authority_chain:
            chain_failures.append(f"{field}.chain_id must match authority_revocation.chain_id")

    tombstone_refs = (
        (signaling, "signaling", "rejected_tombstone_id", "signaling rejected tombstone identity"),
        (relay_admission, "relay_admission", "rejected_tombstone_id", "TURN credential rejected tombstone identity"),
        (coturn, "coturn_allocation", "revoked_tombstone_id", "coturn disconnect tombstone identity"),
        (data_plane, "data_plane", "rejected_tombstone_id", "traffic rejection tombstone identity"),
    )
    for section, field, key, label in tombstone_refs:
        ref = _required_identifier(section, key, f"{field}.{key}", label, chain_missing)
        if tombstone_id is not None and ref is not None and ref != tombstone_id:
            chain_failures.append(f"{field}.{key} must match authority_revocation.tombstone_id")

    allocation_id = _optional_identifier(
        coturn, "allocation_id", "coturn_allocation.allocation_id"
    )
    relay_allocation = _required_identifier(
        relay_admission,
        "credential_allocation_id",
        "relay_admission.credential_allocation_id",
        "TURN credential allocation identity",
        chain_missing,
    )
    data_allocation = _required_identifier(
        data_plane,
        "allocation_id",
        "data_plane.allocation_id",
        "traffic rejection allocation identity",
        chain_missing,
    )
    for field, observed in (
        ("relay_admission.credential_allocation_id", relay_allocation),
        ("data_plane.allocation_id", data_allocation),
    ):
        if allocation_id is not None and observed is not None and observed != allocation_id:
            chain_failures.append(f"{field} must match coturn_allocation.allocation_id")

    signaling_at = _required_timestamp(
        signaling,
        "rejection_observed_at",
        "signaling.rejection_observed_at",
        "signaling rejection timestamp",
        chain_missing,
    )
    relay_at = _required_timestamp(
        relay_admission,
        "rejection_observed_at",
        "relay_admission.rejection_observed_at",
        "TURN credential rejection timestamp",
        chain_missing,
    )
    coturn_at = _required_timestamp(
        coturn,
        "disconnect_observed_at",
        "coturn_allocation.disconnect_observed_at",
        "coturn allocation disconnect timestamp",
        chain_missing,
    )
    data_at = _required_timestamp(
        data_plane,
        "denial_observed_at",
        "data_plane.denial_observed_at",
        "traffic rejection timestamp",
        chain_missing,
    )
    ordered = (
        (authority_at, "authority tombstone"),
        (signaling_at, "signaling rejection"),
        (relay_at, "TURN credential rejection"),
        (coturn_at, "coturn allocation disconnect"),
        (data_at, "post-revocation traffic rejection"),
    )
    previous: tuple[datetime, str] | None = None
    for current, label in ordered:
        if current is None:
            continue
        if previous is not None and current < previous[0]:
            chain_failures.append(
                f"{label} timestamp must be at or after {previous[1]} timestamp"
            )
        previous = (current, label)

    missing.extend(chain_missing)
    failures.extend(chain_failures)
    return not chain_missing and not chain_failures


def verify_report(report: dict[str, Any]) -> VerificationResult:
    extra = set(report) - TOP_LEVEL_FIELDS
    if extra:
        _fail(f"report contains unknown fields: {', '.join(sorted(extra))}")
    if report.get("schema") != SCHEMA:
        _fail(f"schema must be {SCHEMA}")
    _timestamp(report.get("observed_at"), "observed_at")

    source = _object(report.get("source"), "source", SOURCE_FIELDS)
    commit = source.get("commit")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        _fail("source.commit must be a 7-40 character lowercase git SHA")
    topology = source.get("topology")
    if topology not in {"local", "staging", "production", "blocked"}:
        _fail("source.topology must be local, staging, production, or blocked")
    if "coturn_source_id" in source:
        _identifier(source["coturn_source_id"], "source.coturn_source_id")

    authority = _object(report.get("authority_revocation"), "authority_revocation", AUTHORITY_FIELDS)
    signaling = _object(report.get("signaling"), "signaling", SIGNALING_FIELDS)
    relay_admission = _object(
        report.get("relay_admission"), "relay_admission", RELAY_ADMISSION_FIELDS
    )
    coturn = _object(report.get("coturn_allocation"), "coturn_allocation", COTURN_FIELDS)
    data_plane = _object(report.get("data_plane"), "data_plane", DATA_PLANE_FIELDS)

    missing: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []

    _validate_source_evidence_boundary(source, missing, failures)

    device_revoked = _required_bool(
        authority, "device_revoked", "authority device revoke", missing, failures
    )
    session_revoked = _required_bool(
        authority, "session_revoked", "authority session revoke", missing, failures
    )
    tombstone_persisted = _required_bool(
        authority,
        "tombstone_persisted",
        "authority tombstone persistence",
        missing,
        failures,
    )
    audit_event_observed = _required_bool(
        authority,
        "audit_event_observed",
        "authority revocation audit event",
        missing,
        failures,
    )
    _optional_status(
        authority, "revocation_status", "authority revocation", ALLOWED_REVOCATION_STATUS, warnings
    )

    active_session_rejected = _required_bool(
        signaling, "active_session_rejected", "active signaling session rejection", missing, failures
    )
    long_poll_woke_fail_closed = _required_bool(
        signaling,
        "long_poll_woke_fail_closed",
        "signaling long-poll wakeup fail-closed",
        missing,
        failures,
    )
    _optional_status(
        signaling, "rejection_status", "signaling rejection", ALLOWED_REJECTION_STATUS, warnings
    )

    new_grant_rejected = _required_bool(
        relay_admission,
        "new_grant_rejected",
        "future relay credential rejection",
        missing,
        failures,
    )
    _optional_status(
        relay_admission,
        "new_grant_status",
        "future relay credential rejection",
        ALLOWED_REJECTION_STATUS,
        warnings,
    )
    same_allocation_retry_rejected = _required_bool(
        relay_admission,
        "same_allocation_retry_rejected",
        "post-revocation same allocation credential retry rejection",
        missing,
        failures,
    )
    _optional_status(
        relay_admission,
        "same_allocation_retry_status",
        "post-revocation same allocation credential retry rejection",
        ALLOWED_REJECTION_STATUS,
        warnings,
    )
    stale_grant_reuse_rejected = _required_bool(
        relay_admission,
        "stale_grant_reuse_rejected",
        "stale TURN credential reuse rejection",
        missing,
        failures,
    )
    _optional_status(
        relay_admission,
        "stale_grant_status",
        "stale TURN credential rejection",
        ALLOWED_REJECTION_STATUS,
        warnings,
    )
    ttl = _optional_positive_int(
        relay_admission, "grant_ttl_seconds", "relay_admission.grant_ttl_seconds"
    )
    if ttl is not None and ttl > 60:
        warnings.append("TURN credential TTL exceeds the current short-lived exposure target")

    active_before_revocation = _required_bool(
        coturn, "active_before_revocation", "active coturn allocation before revoke", missing, failures
    )
    if "allocation_id" in coturn:
        _identifier(coturn["allocation_id"], "coturn_allocation.allocation_id")
    else:
        missing.append("active coturn allocation identity")
    disconnect_observed = _required_bool(
        coturn, "disconnect_observed", "active coturn allocation disconnect", missing, failures
    )
    if coturn.get("disconnect_observed") is True:
        if not isinstance(coturn.get("disconnect_method"), str) or not coturn["disconnect_method"]:
            missing.append("active coturn allocation disconnect method")

    traffic_established_before_revocation = _required_bool(
        data_plane,
        "traffic_established_before_revocation",
        "pre-revocation data-plane traffic",
        missing,
        failures,
    )
    post_revocation_traffic_denied = _required_bool(
        data_plane,
        "post_revocation_traffic_denied",
        "post-revocation data-plane traffic denial",
        missing,
        failures,
    )
    packets = _optional_positive_int(
        data_plane, "relayed_packets_after_revocation", "data_plane.relayed_packets_after_revocation"
    )
    if packets is None:
        missing.append("post-revocation relayed packet count")
    elif packets != 0:
        failures.append("post-revocation relayed packet count must be zero")
    rejected_after_disconnect = _required_bool(
        data_plane,
        "rejected_after_disconnect",
        "post-revocation traffic rejection after coturn disconnect",
        missing,
        failures,
    )

    chain_consistent = _validate_chain_binding(
        authority, signaling, relay_admission, coturn, data_plane, missing, failures
    )

    if failures:
        status = FAIL
    elif missing:
        status = BLOCKED
    else:
        status = PASS
    chain_id = _optional_identifier(authority, "chain_id", "authority_revocation.chain_id")
    tombstone_id = _optional_identifier(authority, "tombstone_id", "authority_revocation.tombstone_id")
    allocation_id = _optional_identifier(coturn, "allocation_id", "coturn_allocation.allocation_id")
    observations = {
        "evidence_kind": source.get("evidence_kind"),
        "public_internet_path": source.get("public_internet_path"),
        "remote_turn_deployment": source.get("remote_turn_deployment"),
        "synthetic_fixture": source.get("synthetic_fixture"),
        "chain_id": chain_id,
        "tombstone_id": tombstone_id,
        "allocation_id": allocation_id,
        "device_revoked": device_revoked is True,
        "session_revoked": session_revoked is True,
        "authority_tombstone_observed": tombstone_persisted is True
        and audit_event_observed is True,
        "signaling_rejection_observed": active_session_rejected is True
        and long_poll_woke_fail_closed is True,
        "future_turn_credential_rejected": new_grant_rejected is True,
        "same_allocation_turn_credential_rejected": same_allocation_retry_rejected is True,
        "stale_credential_reuse_rejected": stale_grant_reuse_rejected is True,
        "active_allocation_before_revocation": active_before_revocation is True,
        "active_allocation_disconnected": disconnect_observed is True,
        "pre_revocation_traffic_established": traffic_established_before_revocation is True,
        "post_revocation_traffic_denied": post_revocation_traffic_denied is True,
        "post_revocation_traffic_denied_after_disconnect": rejected_after_disconnect is True,
        "post_revocation_packet_count_zero": None if packets is None else packets == 0,
        "relayed_packets_after_revocation": packets,
        "revocation_chain_consistent": chain_consistent,
    }
    return VerificationResult(status, tuple(missing), tuple(failures), tuple(warnings), observations)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="revocation propagation report JSON")
    parser.add_argument("--write-summary", type=Path, help="optional JSON summary output path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = verify_report(_read_report(args.report))
        output = result.as_dict()
        print(json.dumps(output, sort_keys=True), flush=True)
        if args.write_summary is not None:
            args.write_summary.write_text(
                json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if result.status == PASS:
            return 0
        if result.status == BLOCKED:
            return 4
        return 1
    except VerificationError as exc:
        print(f"revocation-propagation-verifier: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
