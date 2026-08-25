#!/usr/bin/env python3
"""Fail-closed verifier for Phase 3 automatic session-authority issuance evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, NoReturn, Sequence

SCHEMA = "dev.vibescreen.phase3-session-authority-readiness/v1"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"

COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
SECRET_FIELD_NAMES = frozenset(
    {
        "admin_token",
        "api_key",
        "authorization",
        "bearer",
        "credential",
        "device_token",
        "host_token",
        "password",
        "private_key",
        "raw_credential",
        "secret",
        "shared_secret",
        "signaling_token",
        "token",
        "turn_password",
    }
)
SECRET_FIELD_SUFFIXES = ("token", "password", "secret", "credential", "private_key")
SECRET_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "observed_at",
        "source",
        "product_flow",
        "account_device",
        "authority",
        "mac_signer",
        "android_import",
        "signaling",
        "turn",
        "privacy",
        "notes",
    }
)
SOURCE_FIELDS = frozenset({"commit", "tree_status", "deployment_id", "profile_endpoint"})
PRODUCT_FIELDS = frozenset(
    {
        "authority_profile_endpoint_called_by_product_flow",
        "operator_manual_profile_copy",
        "manual_unsigned_lease_file_transfer",
        "user_visible_pairing_or_session_flow",
        "product_flow_artifact_hash",
    }
)
ACCOUNT_FIELDS = frozenset(
    {
        "account_registered_by_product_flow",
        "device_registered_by_product_flow",
        "account_device_binding_observed",
        "authority_audit_event_observed",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "profile_created_or_replayed",
        "request_digest_bound",
        "strict_replay_rejected",
        "session_epoch_monotonic",
        "session_ttl_seconds",
        "unsigned_lease_returned_to_product_flow",
    }
)
MAC_FIELDS = frozenset(
    {
        "signed_authority_supplied_epoch",
        "local_high_water_mark_reserved",
        "mismatched_epoch_rejected",
        "host_identity_bound",
        "signature_observed_by_product_flow",
    }
)
ANDROID_FIELDS = frozenset(
    {
        "signed_lease_imported_by_product_flow",
        "host_signature_verified",
        "session_epoch_accepted",
        "manual_import_ui_used",
    }
)
SIGNALING_FIELDS = frozenset(
    {
        "host_role_authorized",
        "client_role_authorized",
        "cross_role_token_rejected",
        "expired_session_rejected",
    }
)
TURN_FIELDS = frozenset(
    {
        "present",
        "authority_or_relay_issued_short_lived",
        "static_turn_password_in_product",
        "credential_ttl_seconds",
        "rotation_or_expiry_observed",
    }
)
PRIVACY_FIELDS = frozenset(
    {
        "raw_tokens_recorded",
        "raw_credentials_recorded",
        "raw_device_identifiers_recorded",
        "operator_paths_recorded",
    }
)
MAX_SESSION_TTL_SECONDS = 1800
MAX_TURN_TTL_SECONDS = 1800


class VerificationError(RuntimeError):
    """Raised when an evidence report is malformed or unsafe to evaluate."""


@dataclass(frozen=True)
class VerificationResult:
    status: str
    missing: tuple[str, ...]
    blockers: tuple[str, ...]
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": self.status,
            "missing": list(self.missing),
            "blockers": list(self.blockers),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


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


def _read_report(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read report: {type(exc).__name__}") from exc
    if not isinstance(raw, dict):
        _fail("report must be a JSON object")
    _reject_secrets(raw)
    return raw


def _object(value: Any, field: str, allowed_fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    extra = set(value) - allowed_fields
    if extra:
        _fail(f"{field} contains unknown fields: {', '.join(sorted(extra))}")
    return value


def _timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be an RFC3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise VerificationError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include a timezone")


def _identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be a bounded ASCII identifier")


def _required_bool(
    section: dict[str, Any],
    key: str,
    expected: bool,
    label: str,
    missing: list[str],
    blockers: list[str],
    failures: list[str],
    *,
    unsafe: bool = False,
) -> None:
    value = section.get(key)
    if value is expected:
        return
    if isinstance(value, bool):
        if unsafe:
            failures.append(label)
        else:
            blockers.append(label)
        return
    missing.append(label)


def _required_positive_int(
    section: dict[str, Any], key: str, label: str, missing: list[str], maximum: int | None = None
) -> None:
    value = section.get(key)
    if value is None:
        missing.append(label)
        return
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail(f"{label} must be a positive integer")
    if maximum is not None and value > maximum:
        _fail(f"{label} exceeds the accepted maximum")


def _git_head(repo: Path) -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _tree_status(repo: Path) -> str:
    completed = subprocess.run(["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True)
    return "clean" if not completed.stdout.strip() else "dirty"


def verify_report(report: dict[str, Any], *, repo: Path | None = None, require_current_head: bool = False) -> VerificationResult:
    _reject_secrets(report)
    _object(report, "$", TOP_LEVEL_FIELDS)
    if report.get("schema") != SCHEMA:
        _fail("schema mismatch")
    _timestamp(report.get("observed_at"), "observed_at")

    missing: list[str] = []
    blockers: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []

    source = _object(report.get("source"), "source", SOURCE_FIELDS)
    commit = source.get("commit")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        _fail("source.commit must be a git commit hash")
    tree_status = source.get("tree_status")
    if tree_status not in {"clean", "dirty"}:
        _fail("source.tree_status must be clean or dirty")
    if tree_status != "clean":
        blockers.append("source tree must be clean for current-base pass evidence")
    if "deployment_id" in source:
        _identifier(source["deployment_id"], "source.deployment_id")
    if "profile_endpoint" in source and source["profile_endpoint"] not in {"authority_admin", "product_authority"}:
        _fail("source.profile_endpoint must be authority_admin or product_authority")
    if require_current_head:
        if repo is None:
            _fail("repo is required when --require-current-head is set")
        if commit != _git_head(repo):
            blockers.append("source commit does not match current HEAD")
        if _tree_status(repo) != "clean":
            blockers.append("repository worktree is dirty")

    product = _object(report.get("product_flow"), "product_flow", PRODUCT_FIELDS)
    _required_bool(product, "authority_profile_endpoint_called_by_product_flow", True, "product flow did not call Authority profile issuance", missing, blockers, failures)
    _required_bool(product, "operator_manual_profile_copy", False, "operator manual profile copy is still required", missing, blockers, failures)
    _required_bool(product, "manual_unsigned_lease_file_transfer", False, "manual unsigned lease transfer is still required", missing, blockers, failures)
    _required_bool(product, "user_visible_pairing_or_session_flow", True, "product pairing/session UI flow was not observed", missing, blockers, failures)
    artifact_hash = product.get("product_flow_artifact_hash")
    if not isinstance(artifact_hash, str) or not HASH.fullmatch(artifact_hash):
        missing.append("product flow artifact hash")

    account = _object(report.get("account_device"), "account_device", ACCOUNT_FIELDS)
    for key, label in (
        ("account_registered_by_product_flow", "account registration was not product-driven"),
        ("device_registered_by_product_flow", "device registration was not product-driven"),
        ("account_device_binding_observed", "account/device binding was not observed"),
        ("authority_audit_event_observed", "Authority audit event was not observed"),
    ):
        _required_bool(account, key, True, label, missing, blockers, failures)

    authority = _object(report.get("authority"), "authority", AUTHORITY_FIELDS)
    for key, label in (
        ("profile_created_or_replayed", "Authority did not create or replay a profile"),
        ("request_digest_bound", "Authority request digest binding was not observed"),
        ("strict_replay_rejected", "Authority strict replay rejection was not observed"),
        ("session_epoch_monotonic", "Authority session epoch monotonicity was not observed"),
        ("unsigned_lease_returned_to_product_flow", "unsigned lease did not stay in product flow"),
    ):
        _required_bool(authority, key, True, label, missing, blockers, failures)
    _required_positive_int(authority, "session_ttl_seconds", "authority session TTL", missing, MAX_SESSION_TTL_SECONDS)

    mac = _object(report.get("mac_signer"), "mac_signer", MAC_FIELDS)
    for key, label in (
        ("signed_authority_supplied_epoch", "Mac did not sign the exact Authority epoch"),
        ("local_high_water_mark_reserved", "Mac high-water mark reservation was not observed"),
        ("mismatched_epoch_rejected", "Mac mismatched epoch rejection was not observed"),
        ("host_identity_bound", "Mac host identity binding was not observed"),
        ("signature_observed_by_product_flow", "Mac signature was not observed in product flow"),
    ):
        _required_bool(mac, key, True, label, missing, blockers, failures)

    android = _object(report.get("android_import"), "android_import", ANDROID_FIELDS)
    for key, label in (
        ("signed_lease_imported_by_product_flow", "Android did not import the signed lease through product flow"),
        ("host_signature_verified", "Android host signature verification was not observed"),
        ("session_epoch_accepted", "Android session epoch acceptance was not observed"),
    ):
        _required_bool(android, key, True, label, missing, blockers, failures)
    _required_bool(android, "manual_import_ui_used", False, "manual Android import UI was still used", missing, blockers, failures)

    signaling = _object(report.get("signaling"), "signaling", SIGNALING_FIELDS)
    for key, label in (
        ("host_role_authorized", "host signaling role authorization was not observed"),
        ("client_role_authorized", "client signaling role authorization was not observed"),
        ("cross_role_token_rejected", "cross-role token rejection was not observed"),
        ("expired_session_rejected", "expired session rejection was not observed"),
    ):
        _required_bool(signaling, key, True, label, missing, blockers, failures)

    turn = _object(report.get("turn", {}), "turn", TURN_FIELDS)
    turn_present = turn.get("present")
    if turn_present is True:
        _required_bool(turn, "authority_or_relay_issued_short_lived", True, "TURN credential was not Authority/relay-issued and short-lived", missing, blockers, failures)
        _required_bool(turn, "static_turn_password_in_product", False, "static TURN password is present in product flow", missing, blockers, failures, unsafe=True)
        _required_bool(turn, "rotation_or_expiry_observed", True, "TURN rotation or expiry was not observed", missing, blockers, failures)
        _required_positive_int(turn, "credential_ttl_seconds", "TURN credential TTL", missing, MAX_TURN_TTL_SECONDS)
    elif turn_present is False:
        warnings.append("TURN credential path was not part of this evidence report")
    else:
        missing.append("TURN presence declaration")

    privacy = _object(report.get("privacy"), "privacy", PRIVACY_FIELDS)
    for key, label in (
        ("raw_tokens_recorded", "raw tokens were recorded"),
        ("raw_credentials_recorded", "raw credentials were recorded"),
        ("raw_device_identifiers_recorded", "raw device identifiers were recorded"),
        ("operator_paths_recorded", "operator paths were recorded"),
    ):
        _required_bool(privacy, key, False, label, missing, blockers, failures, unsafe=True)

    if failures:
        status = FAIL
    elif missing or blockers:
        status = BLOCKED
    else:
        status = PASS
    return VerificationResult(
        status=status,
        missing=tuple(sorted(set(missing))),
        blockers=tuple(sorted(set(blockers))),
        failures=tuple(sorted(set(failures))),
        warnings=tuple(sorted(set(warnings))),
    )


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            output.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--write-summary", type=Path)
    parser.add_argument("--require-current-head", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        report = _read_report(args.report)
        result = verify_report(report, repo=args.repo, require_current_head=args.require_current_head)
        if args.write_summary:
            write_json(args.write_summary, result.as_dict())
    except VerificationError as error:
        print(f"Phase 3 session-authority readiness: ERROR ({error})", file=sys.stderr)
        return 2
    if result.status == PASS:
        print("Phase 3 session-authority readiness: PASS", file=sys.stderr)
        return 0
    if result.status == FAIL:
        print("Phase 3 session-authority readiness: FAIL", file=sys.stderr)
        return 1
    print("Phase 3 session-authority readiness: BLOCKED", file=sys.stderr)
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
