"""Evaluate Android ClipboardManager <-> macOS NSPasteboard E2E evidence.

The gate is intentionally fail-closed. USB/LAN preflight, Android-local
ClipboardManager instrumentation, JVM tests, protocol fixtures, and Host
self-tests are useful readiness evidence, but they cannot close the real
system-clipboard E2E gate without retained product evidence for both transfer
directions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


KIND = "android_macos_clipboard_e2e_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"
DEFAULT_DEVICE_IDENTITY = {
    "manufacturer": "nubia",
    "model": "P0110",
    "codename": "pacific",
    "android_release": "16",
    "sdk": 36,
}
LOCAL_MAXIMUM_CLIPBOARD_BYTES = 1_048_576
REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS = 8
REQUIRED_ANDROID_CLIPBOARD_SMOKE_METHODS = (
    "foregroundActivityCanUseAndroidSystemClipboardLocally",
    "foregroundActivityCanRoundTripUnicodeAndLargePlainTextLocally",
    "foregroundActivityHandlesNonTextClipboardItemSafely",
    "foregroundActivitySeesEmptyClipboardAsNoPrimaryClip",
    "foregroundActivityDoesNotTreatLaterTextItemAsFirstClipboardText",
    "foregroundActivityCanRoundTripExpandedLargePlainTextLocally",
    "setForegroundClipboardFromInstrumentationArgument",
    "assertForegroundClipboardMatchesInstrumentationArgument",
)
ANDROID_CLIPBOARD_SMOKE_CLASS = "dev.telemachus.display.ClipboardManagerInstrumentedTest"
SAFE_SERIAL_LABEL = "REDACTED_P0110_USB_SERIAL"
RETAINED_ARTIFACTS_FIELD = "retained_artifacts"
HOST_READINESS_REQUIRED_PERMISSION_FIELDS = (
    "screen_recording_granted",
    "accessibility_granted",
    "microphone_granted",
    "screen_recording_identity_bound",
    "accessibility_identity_bound",
    "microphone_identity_bound",
)
REQUIRED_DIRECTION_ARTIFACT_ROLES = (
    "source_clipboard_read",
    "sender_action",
    "receiver_approval",
    "protocol_packets",
    "destination_clipboard_write",
    "final_verification",
    "negative_boundary_verification",
)
SESSION_ID_HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
HASH_CHUNK_BYTES = 1024 * 1024
TCC_PATH_COMPONENT = "Application" + r"\s+" + "Support/com" + r"\.apple\." + "TCC"
TCC_BUNDLE_COMPONENT = "com" + r"\.apple\." + "TCC"
TCC_DATABASE_COMPONENT = "TCC" + r"\.db"
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"\bEP[0-9A-Z]{14,}\b"),
    re.compile(TCC_PATH_COMPONENT, re.IGNORECASE),
    re.compile(TCC_BUNDLE_COMPONENT, re.IGNORECASE),
    re.compile(TCC_DATABASE_COMPONENT, re.IGNORECASE),
    re.compile(r"/Users/[^\r\n<>\"']+"),
    re.compile(r"/home/[^\r\n<>\"']+"),
)


class ClipboardE2EGateError(ValueError):
    """Raised when evidence cannot be evaluated."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ClipboardE2EGateError(f"cannot read {label}: {error}") from error
    if not isinstance(document, dict):
        raise ClipboardE2EGateError(f"{label} must be a JSON object")
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sanitize_text(value: Any) -> str:
    text = str(value)
    for pattern in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(_replacement_for_pattern(pattern), text)
    return text


def _replacement_for_pattern(pattern: re.Pattern[str]) -> str:
    pattern_text = pattern.pattern.lower()
    if "ep[0-9a-z]" in pattern_text:
        return SAFE_SERIAL_LABEL
    if "users" in pattern_text or "home" in pattern_text:
        return "<redacted-local-path>"
    return "<redacted-tcc-reference>"


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_text(key): sanitize_value(item) for key, item in value.items()}
    return value


def _list_value(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key)
    return value if isinstance(value, list) else []


def _gate(
    name: str, status: str, reasons: Sequence[str], evidence: Sequence[str] = ()
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reasons": [sanitize_text(reason) for reason in reasons],
        "evidence": list(evidence),
    }


def _retained_artifact_reasons(
    document: dict[str, Any],
    label: str,
    required_roles: Sequence[str],
    evidence_dir: Path | None,
    cross_direction_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> list[str]:
    artifacts = document.get(RETAINED_ARTIFACTS_FIELD)
    if not isinstance(artifacts, list) or not artifacts:
        return [f"{label}.{RETAINED_ARTIFACTS_FIELD} must retain product evidence artifacts"]

    reasons: list[str] = []
    required_role_names = set(required_roles)
    seen_roles: set[str] = set()
    seen_artifact_paths: dict[Path | str, str] = {}
    for index, artifact in enumerate(artifacts):
        artifact_label = f"{label}.{RETAINED_ARTIFACTS_FIELD}[{index}]"
        if not isinstance(artifact, dict):
            reasons.append(f"{artifact_label} must be an object")
            continue
        role = artifact.get("role")
        direction_matches = artifact.get("direction") == label
        if not direction_matches:
            reasons.append(f"{artifact_label}.direction must be {label}")
        if isinstance(role, str) and role.strip():
            role_name = role.strip()
            if role_name not in required_role_names:
                reasons.append(f"{artifact_label}.role must be one of {', '.join(required_roles)}")
                role_is_required = False
            elif not direction_matches:
                role_is_required = False
            elif role_name in seen_roles:
                reasons.append(f"{artifact_label}.role duplicates {role_name} artifact")
                role_is_required = True
            else:
                role_is_required = True
            if direction_matches:
                seen_roles.add(role_name)
        else:
            role_name = f"entry {index}"
            role_is_required = False
            reasons.append(f"{artifact_label}.role must be present")

        path_value = artifact.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            reasons.append(f"{artifact_label}.path must be present")
            continue
        artifact_key, path_reasons = _retained_artifact_key(artifact_label, path_value, evidence_dir)
        reasons.extend(path_reasons)
        reasons.extend(_retained_artifact_digest_reasons(artifact_label, artifact, artifact_key))
        if artifact_key is not None:
            previous_role = seen_artifact_paths.get(artifact_key)
            if previous_role is not None:
                reasons.append(f"{artifact_label}.path must be distinct from {previous_role} artifact path")
            else:
                seen_artifact_paths[artifact_key] = role_name
            if cross_direction_artifact_paths is not None and role_is_required:
                previous_artifact = cross_direction_artifact_paths.get(artifact_key)
                if previous_artifact is not None and previous_artifact[0] != label:
                    previous_label, previous_role = previous_artifact
                    reasons.append(
                        f"{artifact_label}.path for {role_name} must be distinct from "
                        f"{previous_label} {previous_role} artifact path"
                    )
                elif previous_artifact is None:
                    cross_direction_artifact_paths[artifact_key] = (label, role_name)

    missing_roles = [role for role in required_roles if role not in seen_roles]
    reasons.extend(
        f"{label}.{RETAINED_ARTIFACTS_FIELD} missing {role} artifact"
        for role in missing_roles
    )
    return reasons


def _retained_artifact_key(
    artifact_label: str,
    path_value: str,
    evidence_dir: Path | None,
) -> tuple[Path | str | None, list[str]]:
    path = Path(path_value)
    if path.is_absolute():
        return None, [f"{artifact_label}.path must be evidence-relative"]
    if (path.parts and path.parts[0] == "..") or ".." in path.parts:
        return None, [f"{artifact_label}.path must stay inside the evidence bundle"]
    if evidence_dir is None:
        return path.as_posix(), []

    resolved_evidence_dir = evidence_dir.resolve()
    candidate = evidence_dir / path
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None, [f"{artifact_label}.path missing retained artifact {sanitize_text(path_value)}"]
    except (OSError, RuntimeError, ValueError) as error:
        return None, [
            f"{artifact_label}.path cannot access retained artifact "
            f"{sanitize_text(path_value)}: {sanitize_text(error)}"
        ]
    try:
        resolved_candidate.relative_to(resolved_evidence_dir)
    except ValueError:
        return None, [f"{artifact_label}.path must stay inside the evidence bundle"]
    if not resolved_candidate.is_file():
        return None, [f"{artifact_label}.path missing retained artifact {sanitize_text(path_value)}"]
    if resolved_candidate.stat().st_size <= 0:
        return None, [f"{artifact_label}.path retained artifact {sanitize_text(path_value)} must be non-empty"]
    return resolved_candidate, []


def _retained_artifact_digest_reasons(
    artifact_label: str,
    artifact: dict[str, Any],
    artifact_key: Path | str | None,
) -> list[str]:
    reasons: list[str] = []
    expected_byte_length = artifact.get("byte_length")
    if (
        not isinstance(expected_byte_length, int)
        or isinstance(expected_byte_length, bool)
        or expected_byte_length <= 0
    ):
        reasons.append(f"{artifact_label}.byte_length must record the retained artifact byte length")
    expected_sha256 = artifact.get("sha256")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        reasons.append(f"{artifact_label}.sha256 must record the retained artifact SHA-256 digest")

    if not isinstance(artifact_key, Path):
        return reasons

    try:
        actual_byte_length = artifact_key.stat().st_size
    except OSError as error:
        reasons.append(f"{artifact_label}.byte_length cannot be verified: {sanitize_text(error)}")
    else:
        if isinstance(expected_byte_length, int) and not isinstance(expected_byte_length, bool):
            if actual_byte_length != expected_byte_length:
                reasons.append(
                    f"{artifact_label}.byte_length {expected_byte_length} must equal retained artifact size {actual_byte_length}"
                )

    if isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        try:
            digest = hashlib.sha256()
            with artifact_key.open("rb") as file_handle:
                for chunk in iter(lambda: file_handle.read(HASH_CHUNK_BYTES), b""):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
        except OSError as error:
            reasons.append(f"{artifact_label}.sha256 cannot be verified: {sanitize_text(error)}")
        else:
            if actual_sha256 != expected_sha256.lower():
                reasons.append(f"{artifact_label}.sha256 must equal retained artifact SHA-256")
    return reasons


def _retained_artifact_path_by_role(direction: dict[str, Any], role: str) -> Path | None:
    artifacts = direction.get(RETAINED_ARTIFACTS_FIELD)
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("role") != role:
            continue
        path_value = artifact.get("path")
        if isinstance(path_value, str) and path_value.strip():
            return Path(path_value)
    return None


def _resolved_retained_artifact_path(direction: dict[str, Any], role: str, evidence_dir: Path | None) -> Path | None:
    if evidence_dir is None:
        return None
    path = _retained_artifact_path_by_role(direction, role)
    if path is None or path.is_absolute() or ".." in path.parts:
        return None
    try:
        resolved_evidence_dir = evidence_dir.resolve()
        resolved_candidate = (evidence_dir / path).resolve(strict=True)
        resolved_candidate.relative_to(resolved_evidence_dir)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    if not resolved_candidate.is_file():
        return None
    return resolved_candidate


def _artifact_payload_reasons(
    path: Path,
    label: str,
    expected_byte_length: Any,
    expected_sha256: Any,
) -> list[str]:
    reasons: list[str] = []
    try:
        actual_byte_length = path.stat().st_size
    except OSError as error:
        reasons.append(f"{label} artifact byte length cannot be read: {sanitize_text(error)}")
    else:
        if isinstance(expected_byte_length, int) and not isinstance(expected_byte_length, bool):
            if actual_byte_length != expected_byte_length:
                reasons.append(f"{label} artifact size {actual_byte_length} must equal direction.byte_length {expected_byte_length}")

    if isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        try:
            digest = hashlib.sha256()
            with path.open("rb") as file_handle:
                for chunk in iter(lambda: file_handle.read(HASH_CHUNK_BYTES), b""):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
        except OSError as error:
            reasons.append(f"{label} artifact SHA-256 cannot be read: {sanitize_text(error)}")
        else:
            if actual_sha256 != expected_sha256.lower():
                reasons.append(f"{label} artifact SHA-256 must equal direction.sha256")
    return reasons


def _destination_clipboard_artifact_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
) -> list[str]:
    destination_artifact = _resolved_retained_artifact_path(
        direction,
        "destination_clipboard_write",
        evidence_dir,
    )
    if destination_artifact is None:
        return []
    return _artifact_payload_reasons(
        destination_artifact,
        f"{label}.destination_clipboard_write",
        direction.get("byte_length"),
        direction.get("sha256"),
    )


def _source_clipboard_artifact_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
) -> list[str]:
    source_artifact = _resolved_retained_artifact_path(
        direction,
        "source_clipboard_read",
        evidence_dir,
    )
    if source_artifact is None:
        return []
    return _artifact_payload_reasons(
        source_artifact,
        f"{label}.source_clipboard_read",
        direction.get("byte_length"),
        direction.get("sha256"),
    )


def _record_string_field_matches(record: dict[str, Any], key: str, expected: Any) -> bool:
    return (
        isinstance(expected, str)
        and bool(expected.strip())
        and record.get(key) == expected
    )


def _record_hex_field_matches(record: dict[str, Any], key: str, expected: Any, *, length: int) -> bool:
    return (
        isinstance(expected, str)
        and re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", expected) is not None
        and isinstance(record.get(key), str)
        and record[key].lower() == expected.lower()
    )


def _record_integer_field_matches(record: dict[str, Any], key: str, expected: Any) -> bool:
    return (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and isinstance(record.get(key), int)
        and not isinstance(record.get(key), bool)
        and record[key] == expected
    )


def _protocol_packets_artifact_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
) -> list[str]:
    protocol_artifact = _resolved_retained_artifact_path(direction, "protocol_packets", evidence_dir)
    if protocol_artifact is None:
        return []
    required_events = {"clipboard_offer", "clipboard_request", "clipboard_content"}
    observed_events: set[str] = set()
    observed_change_id = False
    observed_session_id = False
    observed_epoch = False
    observed_origin = False
    event_records_missing_metadata: list[str] = []
    event_records_wrong_direction: list[str] = []
    malformed_lines: list[int] = []
    change_id = direction.get("change_id_hex")
    session_id = direction.get("session_id_hex")
    session_epoch = direction.get("session_epoch")
    origin_device_id = direction.get("origin_device_id")
    mime_type = direction.get("mime_type")
    byte_length = direction.get("byte_length")
    sha256 = direction.get("sha256")
    try:
        lines = protocol_artifact.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return [f"{label}.protocol_packets artifact cannot be read: {sanitize_text(error)}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line_number)
            continue
        if not isinstance(record, dict):
            malformed_lines.append(line_number)
            continue
        event_names = {
            str(record.get(key, "")).strip().lower()
            for key in ("type", "event", "name", "message_type", "packet_type")
            if str(record.get(key, "")).strip()
        }
        matching_events = required_events & event_names
        observed_events.update(matching_events)
        event_has_change_id = _record_hex_field_matches(record, "change_id_hex", change_id, length=32)
        event_has_session_id = _record_hex_field_matches(record, "session_id_hex", session_id, length=32)
        event_has_epoch = _record_integer_field_matches(record, "session_epoch", session_epoch)
        event_has_origin = _record_string_field_matches(record, "origin_device_id", origin_device_id)
        event_has_payload_metadata = True
        payload_events = {"clipboard_offer", "clipboard_content"}
        if matching_events & payload_events:
            event_has_payload_metadata = (
                _record_string_field_matches(record, "mime_type", mime_type)
                and _record_integer_field_matches(record, "byte_length", byte_length)
                and _record_hex_field_matches(record, "sha256", sha256, length=64)
            )
        record_direction = record.get("direction")
        event_has_direction = record_direction == label
        observed_change_id = observed_change_id or event_has_change_id
        observed_session_id = observed_session_id or event_has_session_id
        observed_epoch = observed_epoch or event_has_epoch
        observed_origin = observed_origin or event_has_origin
        if matching_events and not (
            event_has_change_id
            and event_has_session_id
            and event_has_epoch
            and event_has_origin
            and event_has_payload_metadata
        ):
            event_records_missing_metadata.extend(sorted(matching_events))
        if matching_events and not event_has_direction:
            event_records_wrong_direction.extend(sorted(matching_events))

    reasons: list[str] = []
    if malformed_lines:
        reasons.append(f"{label}.protocol_packets artifact must be JSONL; malformed line(s): {malformed_lines[:5]}")
    missing_events = sorted(required_events - observed_events)
    if missing_events:
        reasons.append(f"{label}.protocol_packets artifact missing event(s): {', '.join(missing_events)}")
    if event_records_missing_metadata:
        missing_metadata_events = sorted(set(event_records_missing_metadata))
        reasons.append(
            f"{label}.protocol_packets event record(s) must include matching change_id_hex, "
            f"session_id_hex, session_epoch, origin_device_id, and offer/content payload metadata: "
            f"{', '.join(missing_metadata_events)}"
        )
    if event_records_wrong_direction:
        wrong_direction_events = sorted(set(event_records_wrong_direction))
        reasons.append(
            f"{label}.protocol_packets event record(s) must declare direction {label}: "
            f"{', '.join(wrong_direction_events)}"
        )
    if not observed_change_id:
        reasons.append(f"{label}.protocol_packets artifact must include change_id_hex {direction.get('change_id_hex')}")
    if not observed_session_id:
        reasons.append(f"{label}.protocol_packets artifact must include session_id_hex {direction.get('session_id_hex')}")
    if not observed_epoch:
        reasons.append(f"{label}.protocol_packets artifact must include session_epoch {direction.get('session_epoch')}")
    if not observed_origin:
        reasons.append(f"{label}.protocol_packets artifact must include origin_device_id {direction.get('origin_device_id')}")
    return reasons


def _flag_enabled(value: Any) -> bool:
    if isinstance(value, str) and value.strip().lower() in {"", "0", "false", "no", "n"}:
        return False
    return bool(value)


def _device_identity(document: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(document, dict):
        return dict(DEFAULT_DEVICE_IDENTITY)
    identity = document.get("identity") if isinstance(document.get("identity"), dict) else document
    return {
        "manufacturer": str(identity.get("manufacturer", "")).strip(),
        "model": str(identity.get("model", "")).strip(),
        "codename": str(identity.get("codename", identity.get("device", ""))).strip(),
        "android_release": str(identity.get("android_release", identity.get("android_version", ""))).strip(),
        "sdk": identity.get("sdk"),
    }


def _device_identity_failures(identity: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    manufacturer = str(identity.get("manufacturer", "")).lower()
    model = str(identity.get("model", "")).lower()
    codename = str(identity.get("codename", "")).lower()
    android_release = str(identity.get("android_release", ""))
    sdk = identity.get("sdk")
    if model != "p0110" or codename != "pacific":
        failures.append("clipboard E2E evidence for this run must identify nubia P0110 / pacific")
    if manufacturer not in {"nubia", "zte"}:
        failures.append("P0110 evidence must not be relabeled as Xiaomi/fuxi or any other device")
    if android_release != "16":
        failures.append("P0110 clipboard E2E evidence must record Android 16")
    if sdk not in (36, "36"):
        failures.append("P0110 clipboard E2E evidence must record SDK 36")
    return failures


def _identity_signature(identity: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(identity.get("manufacturer", "")).strip().lower(),
        str(identity.get("model", "")).strip().lower(),
        str(identity.get("codename", "")).strip().lower(),
        str(identity.get("android_release", "")).strip(),
        str(identity.get("sdk", "")).strip(),
    )


def _device_identity_consistency_failures(
    identities: Sequence[tuple[str, dict[str, Any]]]
) -> list[str]:
    if len(identities) < 2:
        return []
    baseline_label, baseline_identity = identities[0]
    baseline_signature = _identity_signature(baseline_identity)
    failures: list[str] = []
    for label, identity in identities[1:]:
        if _identity_signature(identity) != baseline_signature:
            failures.append(
                f"{label} device identity must match {baseline_label} device identity"
            )
    return failures


def _android_origin_device_id_failure(origin_device_id: Any, identity: dict[str, Any]) -> str | None:
    if not isinstance(origin_device_id, str) or not origin_device_id.strip():
        return None
    normalized_origin = origin_device_id.lower()
    if any(term in normalized_origin for term in ("xiaomi", "fuxi", "2211133c")):
        return "android_clipboardmanager_to_macos_nspasteboard.origin_device_id must not include a non-P0110 Android device identity"
    expected_terms = (
        str(identity.get("model", "")).strip().lower(),
        str(identity.get("codename", "")).strip().lower(),
    )
    if all(term and term in normalized_origin for term in expected_terms):
        return None
    return "android_clipboardmanager_to_macos_nspasteboard.origin_device_id must identify the P0110/pacific Android device"


def _load_optional(path: Path | None, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, [f"missing {label}"]
    if not path.is_file():
        return None, [f"missing {label}: {path.name}"]
    return _read_json(path, label), []


def _host_gate(host: dict[str, Any] | None, missing: Sequence[str]) -> dict[str, Any]:
    reasons = list(missing)
    if host is not None:
        if host.get("status") != "pass" or host.get("can_close_runtime_gates") is not True:
            blockers = [str(item) for item in _list_value(host, "blockers")]
            reasons.extend(blockers or ["Host readiness did not pass"])
        reasons.extend(_host_readiness_structural_reasons(host))
    return _gate(
        "host_readiness",
        PASS if not reasons else BLOCKED,
        reasons,
        ["host-readiness.json"] if host else [],
    )


def _host_readiness_structural_reasons(host: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if host.get("schema_version") != "vibescreen.host-readiness/v1":
        reasons.append("Host readiness schema_version must be vibescreen.host-readiness/v1")
    if host.get("kind") != "macos_host_shared_prerequisite_readiness":
        reasons.append("Host readiness kind must be macos_host_shared_prerequisite_readiness")
    if host.get("signing_tcc_status") != "ready":
        reasons.append(f"Host readiness signing_tcc_status must be ready, got {host.get('signing_tcc_status')!r}")
    listener = host.get("listener")
    if not isinstance(listener, dict):
        reasons.append("Host readiness listener must be present")
    elif listener.get("observed") is not True:
        reasons.append(f"Host readiness listener.observed must be true, got {listener.get('observed')!r}")
    permissions = host.get("permissions")
    if not isinstance(permissions, dict):
        reasons.append("Host readiness permissions must be present")
    else:
        if permissions.get("readable") is not True:
            reasons.append(f"Host readiness permissions.readable must be true, got {permissions.get('readable')!r}")
        for field in HOST_READINESS_REQUIRED_PERMISSION_FIELDS:
            if permissions.get(field) is not True:
                reasons.append(f"Host readiness permissions.{field} must be true, got {permissions.get(field)!r}")
    return reasons


def _usb_gate(usb: dict[str, Any] | None, missing: Sequence[str]) -> dict[str, Any]:
    reasons = list(missing)
    if usb is not None:
        claims = usb.get("claims") if isinstance(usb.get("claims"), dict) else {}
        if usb.get("result") not in {"pass", "ready"} or claims.get("can_start_usb_smoke") is not True:
            blockers = usb.get("blockers") if isinstance(usb.get("blockers"), list) else []
            for item in blockers:
                if isinstance(item, dict):
                    reasons.append(str(item.get("message", item)))
                else:
                    reasons.append(str(item))
            if not blockers:
                reasons.append("USB preflight did not pass")
    return _gate(
        "usb_preflight",
        PASS if not reasons else BLOCKED,
        reasons,
        ["usb-smoke-preflight.json"] if usb else [],
    )


def _lan_gate(lan: dict[str, Any] | None, missing: Sequence[str]) -> dict[str, Any]:
    reasons = list(missing)
    if lan is not None:
        if lan.get("result") not in {"pass", "ready"}:
            reasons.extend(str(item) for item in _list_value(lan, "blockers"))
            if not _list_value(lan, "blockers"):
                reasons.append("trusted-LAN preflight did not pass")
    return _gate(
        "trusted_lan_preflight",
        PASS if not reasons else BLOCKED,
        reasons,
        ["trusted-lan-preflight.json"] if lan else [],
    )


def _transport_gate(usb_gate: dict[str, Any], lan_gate: dict[str, Any]) -> dict[str, Any]:
    if usb_gate["status"] == PASS or lan_gate["status"] == PASS:
        return _gate("real_transport_ready", PASS, [], [])
    reasons = [
        "at least one real Protocol v1 USB or trusted-LAN path must be ready before clipboard E2E can pass"
    ]
    reasons.extend(f"usb: {reason}" for reason in usb_gate["reasons"])
    reasons.extend(f"trusted_lan: {reason}" for reason in lan_gate["reasons"])
    return _gate("real_transport_ready", BLOCKED, reasons, [])


def _android_clipboard_gate(log_path: Path | None) -> dict[str, Any]:
    if log_path is None or not log_path.is_file():
        return _gate(
            "android_clipboardmanager_smoke",
            BLOCKED,
            ["current-run Android ClipboardManager instrumentation log is missing"],
        )
    raw_text = log_path.read_text(encoding="utf-8", errors="replace")
    executed_tests = _android_clipboard_test_count(raw_text)
    passed_methods, failed_methods = _android_clipboard_method_results(raw_text)
    missing_methods = [
        method for method in REQUIRED_ANDROID_CLIPBOARD_SMOKE_METHODS if method not in passed_methods
    ]
    junit_summary = re.search(r"Tests run:\s*\d+,\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)", raw_text)
    has_junit_failures = bool(junit_summary and (int(junit_summary.group(1)) > 0 or int(junit_summary.group(2)) > 0))
    instrumentation_reasons = _android_instrumentation_reasons(raw_text, executed_tests)
    passed = (
        executed_tests >= REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS
        and not missing_methods
        and not failed_methods
        and not instrumentation_reasons
        and ("OK (" in raw_text or ("Finished " in raw_text and " tests on " in raw_text and "BUILD SUCCESSFUL" in raw_text))
        and "FAILURES!!!" not in raw_text
        and "BUILD FAILED" not in raw_text
        and not has_junit_failures
    )
    reasons = []
    if executed_tests < REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS:
        reasons.append(
            "Android ClipboardManager instrumentation log must show "
            f"at least {REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS} executed tests"
        )
    if missing_methods:
        reasons.append(
            "Android ClipboardManager instrumentation log must show passed expected test methods: "
            + ", ".join(missing_methods)
        )
    if failed_methods:
        reasons.append(
            "Android ClipboardManager instrumentation log must not show failed expected test methods: "
            + ", ".join(f"{method}={code}" for method, code in sorted(failed_methods.items()))
        )
    reasons.extend(instrumentation_reasons)
    if not passed:
        reasons.append("Android ClipboardManager instrumentation log does not show an OK result")
    return _gate("android_clipboardmanager_smoke", PASS if passed else BLOCKED, reasons, [log_path.name])


def _android_clipboard_method_results(text: str) -> tuple[set[str], dict[str, int]]:
    passed: set[str] = set()
    failed: dict[str, int] = {}
    for method in REQUIRED_ANDROID_CLIPBOARD_SMOKE_METHODS:
        escaped_class = re.escape(ANDROID_CLIPBOARD_SMOKE_CLASS)
        escaped_method = re.escape(method)
        if re.search(rf"{escaped_class}#{escaped_method}:\s*PASSED\b", text):
            passed.add(method)
        if re.search(rf"{escaped_class}#{escaped_method}:\s*(FAILED|ERROR)\b", text):
            failed[method] = -2

    current_class: str | None = None
    current_test: str | None = None
    for line in text.splitlines():
        class_match = re.fullmatch(r"INSTRUMENTATION_STATUS:\s+class=(.+)", line.strip())
        if class_match:
            current_class = class_match.group(1).strip()
            continue
        test_match = re.fullmatch(r"INSTRUMENTATION_STATUS:\s+test=(.+)", line.strip())
        if test_match:
            current_test = test_match.group(1).strip()
            continue
        code_match = re.fullmatch(r"INSTRUMENTATION_STATUS_CODE:\s+(-?\d+)", line.strip())
        if not code_match:
            continue
        code = int(code_match.group(1))
        if current_class != ANDROID_CLIPBOARD_SMOKE_CLASS or current_test not in REQUIRED_ANDROID_CLIPBOARD_SMOKE_METHODS:
            continue
        if code == 0:
            passed.add(current_test)
        elif code not in {1}:
            failed[current_test] = code
    return passed, failed


def _android_instrumentation_reasons(text: str, executed_tests: int) -> list[str]:
    reasons: list[str] = []
    if "INSTRUMENTATION_STATUS:" in text:
        instrumentation_code_match = re.search(r"INSTRUMENTATION_CODE:\s+(-?\d+)", text)
        if instrumentation_code_match is None:
            reasons.append("Android ClipboardManager instrumentation log must show final INSTRUMENTATION_CODE")
        elif int(instrumentation_code_match.group(1)) != -1:
            reasons.append("Android ClipboardManager instrumentation log must finish with INSTRUMENTATION_CODE -1")
        numtests = [int(match) for match in re.findall(r"INSTRUMENTATION_STATUS:\s+numtests=(\d+)", text)]
        if not numtests:
            reasons.append("Android ClipboardManager instrumentation log must report numtests for raw instrumentation output")
        elif any(count != executed_tests for count in numtests):
            reasons.append("Android ClipboardManager instrumentation numtests must match the executed test count")
        if numtests and any(count < REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS for count in numtests):
            reasons.append(
                "Android ClipboardManager instrumentation numtests must be at least "
                f"{REQUIRED_ANDROID_CLIPBOARD_SMOKE_TESTS}"
            )
    return reasons


def _android_clipboard_test_count(text: str) -> int:
    ok_match = re.search(r"OK \((\d+) tests?\)", text)
    if ok_match:
        return int(ok_match.group(1))
    tests_run_match = re.search(r"Tests run:\s*(\d+)", text)
    if tests_run_match:
        return int(tests_run_match.group(1))
    finished_match = re.search(r"Finished\s+(\d+)\s+tests?\s+on\s+", text)
    if finished_match:
        return int(finished_match.group(1))
    return 0


EXPECTED_DIRECTION_ENDPOINTS = {
    "android_clipboardmanager_to_macos_nspasteboard": (
        "android_clipboardmanager",
        "macos_nspasteboard",
    ),
    "macos_nspasteboard_to_android_clipboardmanager": (
        "macos_nspasteboard",
        "android_clipboardmanager",
    ),
}


def _direction_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
    cross_direction_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
    product_device_identity: dict[str, Any] | None = None,
) -> list[str]:
    required_true = (
        "protocol_v1_session",
        "system_source_clipboard_read",
        "explicit_user_action",
        "receiver_user_approval",
        "remote_system_clipboard_write",
        "final_marker_match",
        "session_id_verified",
        "session_epoch_verified",
        "final_sha256_match",
        "origin_device_id_verified",
        "send_failure_absent",
        "write_failure_absent",
        "cleanup_completed",
        "utf8_valid",
        "overwrite_confirmed",
        "cancel_does_not_write",
        "failure_does_not_write",
        "deny_wins_observed",
    )
    reasons = [
        f"{label}.{field} must be true"
        for field in required_true
        if direction.get(field) is not True
    ]
    marker = direction.get("marker")
    if not isinstance(marker, str) or len(marker.strip()) < 8:
        reasons.append(f"{label}.marker must identify the transferred text marker")
    change_id = direction.get("change_id_hex")
    if not isinstance(change_id, str) or not SESSION_ID_HEX_RE.fullmatch(change_id):
        reasons.append(f"{label}.change_id_hex must be a 32-character hex change ID")
    session_id = direction.get("session_id_hex")
    if not isinstance(session_id, str) or not SESSION_ID_HEX_RE.fullmatch(session_id):
        reasons.append(f"{label}.session_id_hex must be a 32-character hex session ID")
    sha256 = direction.get("sha256")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        reasons.append(f"{label}.sha256 must be a 64-character hex SHA-256 digest")
    origin_device_id = direction.get("origin_device_id")
    if not isinstance(origin_device_id, str) or not origin_device_id.strip():
        reasons.append(f"{label}.origin_device_id must record the verified Protocol v1 origin device ID")
    elif (
        label == "android_clipboardmanager_to_macos_nspasteboard"
        and product_device_identity is not None
    ):
        origin_failure = _android_origin_device_id_failure(origin_device_id, product_device_identity)
        if origin_failure is not None:
            reasons.append(origin_failure)
    byte_length = direction.get("byte_length")
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
        reasons.append(f"{label}.byte_length must be a positive integer")
    elif byte_length > LOCAL_MAXIMUM_CLIPBOARD_BYTES:
        reasons.append(f"{label}.byte_length must not exceed 1048576 bytes")
    mime_type = direction.get("mime_type")
    if mime_type != "text/plain":
        reasons.append(f"{label}.mime_type must be text/plain")
    session_epoch = direction.get("session_epoch")
    if not isinstance(session_epoch, int) or isinstance(session_epoch, bool) or session_epoch <= 0:
        reasons.append(f"{label}.session_epoch must be a positive integer")
    transport = direction.get("transport")
    if transport not in {"usb", "trusted_lan"}:
        reasons.append(f"{label}.transport must be usb or trusted_lan")
    source, destination = EXPECTED_DIRECTION_ENDPOINTS[label]
    if direction.get("source_system_clipboard") != source:
        reasons.append(f"{label}.source_system_clipboard must be {source}")
    if direction.get("destination_system_clipboard") != destination:
        reasons.append(f"{label}.destination_system_clipboard must be {destination}")
    final_marker = direction.get("final_marker")
    if not isinstance(final_marker, str) or final_marker != marker:
        reasons.append(f"{label}.final_marker must equal marker after the destination system clipboard write")
    overwrite_marker = direction.get("overwrite_marker")
    if not isinstance(overwrite_marker, str) or len(overwrite_marker.strip()) < 8:
        reasons.append(f"{label}.overwrite_marker must identify the explicit overwrite text marker")
    cancelled_marker = direction.get("cancelled_marker")
    if not isinstance(cancelled_marker, str) or len(cancelled_marker.strip()) < 8:
        reasons.append(f"{label}.cancelled_marker must identify the cancelled transfer marker")
    failed_marker = direction.get("failed_marker")
    if not isinstance(failed_marker, str) or len(failed_marker.strip()) < 8:
        reasons.append(f"{label}.failed_marker must identify the failed transfer marker")
    deny_marker = direction.get("deny_marker")
    if not isinstance(deny_marker, str) or len(deny_marker.strip()) < 8:
        reasons.append(f"{label}.deny_marker must identify the managed-policy denied marker")
    marker_fields = ("marker", "overwrite_marker", "cancelled_marker", "failed_marker", "deny_marker")
    seen_markers: dict[str, str] = {}
    for field in marker_fields:
        value = direction.get(field)
        if not isinstance(value, str) or len(value.strip()) < 8:
            continue
        normalized = value.strip()
        previous = seen_markers.get(normalized)
        if previous is not None:
            reasons.append(f"{label}.{field} must be distinct from {previous}")
        else:
            seen_markers[normalized] = field
    reasons.extend(
        _retained_artifact_reasons(
            direction,
            label,
            REQUIRED_DIRECTION_ARTIFACT_ROLES,
            evidence_dir,
            cross_direction_artifact_paths,
        )
    )
    reasons.extend(_source_clipboard_artifact_reasons(direction, label, evidence_dir))
    reasons.extend(_destination_clipboard_artifact_reasons(direction, label, evidence_dir))
    reasons.extend(_protocol_packets_artifact_reasons(direction, label, evidence_dir))
    return reasons


def _product_e2e_gate(
    product: dict[str, Any] | None,
    missing: Sequence[str],
    available_transports: set[str],
    evidence_dir: Path | None,
    verified_device_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    reasons = list(missing)
    evidence = ["product-e2e.json"] if product is not None else []
    if product is not None:
        if product.get("kind") != "android_macos_clipboard_product_e2e":
            reasons.append("product evidence kind must be android_macos_clipboard_product_e2e")
        if _flag_enabled(product.get("synthetic")) or _flag_enabled(product.get("offline_only")):
            reasons.append("synthetic or offline-only clipboard evidence cannot close this gate")
        directions = product.get("directions") if isinstance(product.get("directions"), dict) else {}
        android_to_macos = directions.get("android_clipboardmanager_to_macos_nspasteboard")
        macos_to_android = directions.get("macos_nspasteboard_to_android_clipboardmanager")
        markers: dict[str, str] = {}
        change_ids: dict[str, str] = {}
        digests: dict[str, str] = {}
        session_ids: dict[str, str] = {}
        transports: dict[str, str] = {}
        session_epochs: dict[str, int] = {}
        retained_artifact_paths: dict[Path | str, tuple[str, str]] = {}
        if isinstance(android_to_macos, dict):
            reasons.extend(
                _direction_reasons(
                    android_to_macos,
                    "android_clipboardmanager_to_macos_nspasteboard",
                    evidence_dir,
                    retained_artifact_paths,
                    verified_device_identity,
                )
            )
            transport = android_to_macos.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"android_clipboardmanager_to_macos_nspasteboard.transport {transport} is not ready")
            marker = android_to_macos.get("marker")
            if isinstance(marker, str):
                markers["android_clipboardmanager_to_macos_nspasteboard"] = marker.strip()
            change_id = android_to_macos.get("change_id_hex")
            if isinstance(change_id, str) and SESSION_ID_HEX_RE.fullmatch(change_id):
                change_ids["android_clipboardmanager_to_macos_nspasteboard"] = change_id.lower()
            session_id = android_to_macos.get("session_id_hex")
            if isinstance(session_id, str) and SESSION_ID_HEX_RE.fullmatch(session_id):
                session_ids["android_clipboardmanager_to_macos_nspasteboard"] = session_id.lower()
            digest = android_to_macos.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                digests["android_clipboardmanager_to_macos_nspasteboard"] = digest.lower()
            if transport in {"usb", "trusted_lan"}:
                transports["android_clipboardmanager_to_macos_nspasteboard"] = transport
            session_epoch = android_to_macos.get("session_epoch")
            if isinstance(session_epoch, int) and not isinstance(session_epoch, bool) and session_epoch > 0:
                session_epochs["android_clipboardmanager_to_macos_nspasteboard"] = session_epoch
        else:
            reasons.append("missing android_clipboardmanager_to_macos_nspasteboard direction evidence")
        if isinstance(macos_to_android, dict):
            reasons.extend(
                _direction_reasons(
                    macos_to_android,
                    "macos_nspasteboard_to_android_clipboardmanager",
                    evidence_dir,
                    retained_artifact_paths,
                )
            )
            transport = macos_to_android.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"macos_nspasteboard_to_android_clipboardmanager.transport {transport} is not ready")
            marker = macos_to_android.get("marker")
            if isinstance(marker, str):
                markers["macos_nspasteboard_to_android_clipboardmanager"] = marker.strip()
            change_id = macos_to_android.get("change_id_hex")
            if isinstance(change_id, str) and SESSION_ID_HEX_RE.fullmatch(change_id):
                change_ids["macos_nspasteboard_to_android_clipboardmanager"] = change_id.lower()
            session_id = macos_to_android.get("session_id_hex")
            if isinstance(session_id, str) and SESSION_ID_HEX_RE.fullmatch(session_id):
                session_ids["macos_nspasteboard_to_android_clipboardmanager"] = session_id.lower()
            digest = macos_to_android.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                digests["macos_nspasteboard_to_android_clipboardmanager"] = digest.lower()
            if transport in {"usb", "trusted_lan"}:
                transports["macos_nspasteboard_to_android_clipboardmanager"] = transport
            session_epoch = macos_to_android.get("session_epoch")
            if isinstance(session_epoch, int) and not isinstance(session_epoch, bool) and session_epoch > 0:
                session_epochs["macos_nspasteboard_to_android_clipboardmanager"] = session_epoch
        else:
            reasons.append("missing macos_nspasteboard_to_android_clipboardmanager direction evidence")
        if (
            markers.get("android_clipboardmanager_to_macos_nspasteboard")
            and markers.get("android_clipboardmanager_to_macos_nspasteboard")
            == markers.get("macos_nspasteboard_to_android_clipboardmanager")
        ):
            reasons.append("direction markers must be distinct so one transfer cannot satisfy both directions")
        if (
            change_ids.get("android_clipboardmanager_to_macos_nspasteboard")
            and change_ids.get("android_clipboardmanager_to_macos_nspasteboard")
            == change_ids.get("macos_nspasteboard_to_android_clipboardmanager")
        ):
            reasons.append("direction change IDs must be distinct so one transfer cannot satisfy both directions")
        if (
            digests.get("android_clipboardmanager_to_macos_nspasteboard")
            and digests.get("android_clipboardmanager_to_macos_nspasteboard")
            == digests.get("macos_nspasteboard_to_android_clipboardmanager")
        ):
            reasons.append("direction SHA-256 digests must be distinct so one payload cannot satisfy both directions")
        if (
            session_ids.get("android_clipboardmanager_to_macos_nspasteboard")
            and session_ids.get("macos_nspasteboard_to_android_clipboardmanager")
            and session_ids["android_clipboardmanager_to_macos_nspasteboard"]
            != session_ids["macos_nspasteboard_to_android_clipboardmanager"]
        ):
            reasons.append("direction session IDs must match for same-session bidirectional product evidence")
        if (
            transports.get("android_clipboardmanager_to_macos_nspasteboard")
            and transports.get("macos_nspasteboard_to_android_clipboardmanager")
            and transports["android_clipboardmanager_to_macos_nspasteboard"]
            != transports["macos_nspasteboard_to_android_clipboardmanager"]
        ):
            reasons.append("direction transports must match for same-session bidirectional product evidence")
        if (
            session_epochs.get("android_clipboardmanager_to_macos_nspasteboard")
            and session_epochs.get("macos_nspasteboard_to_android_clipboardmanager")
            and session_epochs["android_clipboardmanager_to_macos_nspasteboard"]
            != session_epochs["macos_nspasteboard_to_android_clipboardmanager"]
        ):
            reasons.append("direction session_epoch values must match for same-session bidirectional product evidence")
    return _gate("bidirectional_product_e2e", PASS if not reasons else BLOCKED, reasons, evidence)


def _source_path(path: Path | None, *, repo_root: Path | None) -> str | None:
    if path is None:
        return None
    if repo_root is None:
        return sanitize_text(path.name)
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return sanitize_text(path.name)


def _device_gate(usb: dict[str, Any] | None, lan: dict[str, Any] | None, product: dict[str, Any] | None) -> dict[str, Any]:
    identity_sources: list[tuple[str, dict[str, Any]]] = []
    if product and isinstance(product.get("device"), dict):
        identity_sources.append(("product", _device_identity(product.get("device"))))
    if usb and isinstance(usb.get("device"), dict):
        identity_sources.append(("usb", _device_identity(usb.get("device"))))
    if lan and isinstance(lan.get("android_device"), dict):
        identity_sources.append(("trusted_lan", _device_identity(lan.get("android_device"))))
    has_identity_evidence = True
    if identity_sources:
        identity = identity_sources[0][1]
    else:
        identity = dict(DEFAULT_DEVICE_IDENTITY)
        has_identity_evidence = False
    if not has_identity_evidence:
        return {
            "name": "device_identity",
            "status": BLOCKED,
            "reasons": ["missing real P0110 device identity evidence from USB, trusted-LAN, or product evidence"],
            "evidence": [],
            "identity": None,
            "expected_identity": sanitize_value(identity),
        }
    reasons = [
        reason
        for _, source_identity in identity_sources
        for reason in _device_identity_failures(source_identity)
    ]
    reasons.extend(_device_identity_consistency_failures(identity_sources))
    return {
        "name": "device_identity",
        "status": FAIL if reasons else PASS,
        "reasons": reasons,
        "evidence": [],
        "identity": sanitize_value(identity),
    }


def derive_gate(
    *,
    host_readiness: Path | None = None,
    usb_preflight: Path | None = None,
    trusted_lan_preflight: Path | None = None,
    android_clipboard_instrumentation_log: Path | None = None,
    product_e2e: Path | None = None,
    repo_root: Path | None = None,
    serial_label: str = SAFE_SERIAL_LABEL,
) -> dict[str, Any]:
    host, host_missing = _load_optional(host_readiness, "host readiness")
    usb, usb_missing = _load_optional(usb_preflight, "USB preflight")
    lan, lan_missing = _load_optional(trusted_lan_preflight, "trusted-LAN preflight")
    product, product_missing = _load_optional(product_e2e, "product E2E evidence")
    evidence_dir = product_e2e.parent if product_e2e is not None else None

    usb_gate = _usb_gate(usb, usb_missing)
    lan_gate = _lan_gate(lan, lan_missing)
    available_transports = {
        transport
        for transport, gate in (("usb", usb_gate), ("trusted_lan", lan_gate))
        if gate["status"] == PASS
    }
    device_gate = _device_gate(usb, lan, product)
    verified_device_identity = (
        device_gate.get("identity")
        if device_gate.get("status") == PASS and isinstance(device_gate.get("identity"), dict)
        else None
    )
    gates = [
        device_gate,
        _host_gate(host, host_missing),
        usb_gate,
        lan_gate,
        _transport_gate(usb_gate, lan_gate),
        _android_clipboard_gate(android_clipboard_instrumentation_log),
        _product_e2e_gate(
            product,
            product_missing,
            available_transports,
            evidence_dir,
            verified_device_identity,
        ),
    ]
    required_gate_names = {
        "device_identity",
        "host_readiness",
        "real_transport_ready",
        "android_clipboardmanager_smoke",
        "bidirectional_product_e2e",
    }
    required_gates = [gate for gate in gates if gate["name"] in required_gate_names]
    if any(gate["status"] == FAIL for gate in required_gates):
        verdict = FAIL
    elif any(gate["status"] == BLOCKED for gate in required_gates):
        verdict = BLOCKED
    elif any(gate["status"] == INSUFFICIENT for gate in required_gates):
        verdict = INSUFFICIENT
    else:
        verdict = PASS
    blockers = [
        f"{gate['name']}: {reason}"
        for gate in required_gates
        for reason in gate["reasons"]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "verdict": verdict,
        "result": verdict,
        "gate_closed": verdict == PASS,
        "can_close_android_macos_clipboard_e2e_gate": verdict == PASS,
        "serial_label": sanitize_text(serial_label),
        "checks": sanitize_value(gates),
        "blockers": sanitize_value(blockers),
        "source": {
            "product_e2e": _source_path(product_e2e, repo_root=repo_root),
        },
        "not_proven": [
            item
            for item in (
                "Android ClipboardManager -> macOS NSPasteboard over Protocol v1 USB/LAN" if verdict != PASS else "",
                "macOS NSPasteboard -> Android ClipboardManager over Protocol v1 USB/LAN" if verdict != PASS else "",
                "trusted-LAN clipboard warning and secure-record product behavior" if verdict != PASS else "",
            )
            if item
        ],
        "safety": {
            "offline_tests_do_not_close_gate": True,
            "synthetic_evidence_do_not_close_gate": True,
            "public_output_sanitized": True,
            "raw_serial_redacted": True,
        },
        "interpretation": (
            "A pass requires a current signed/TCC-ready Host, a ready USB or trusted-LAN real-device path, "
            "a current Android system ClipboardManager smoke, and retained bidirectional product E2E evidence "
            "showing explicit user action, source system clipboard read, remote system clipboard write, "
            "Protocol v1 session ownership, verified session ID and session epoch, verified origin device ID, change ID, "
            "SHA-256 digest, text/plain MIME, strict UTF-8 validation, bounded byte length, receiver approval, "
            "overwrite confirmation, cancel/no-write behavior, failure/no-write behavior, deny-wins managed-policy blocking, "
            "absence of send/write failures, cleanup completion, exact source/destination system clipboard endpoints, "
            "distinct final marker matches, distinct change IDs, distinct SHA-256 digests, and retained product "
            "artifacts for the source read, sender action, receiver approval, protocol packets, destination write, "
            "final verification, and negative boundary checks, with distinct non-empty artifact files per role, per "
            "direction, and across both directions. Every retained artifact must declare its parent direction, byte_length, and SHA-256 "
            "metadata that matches the retained file bytes, the destination_clipboard_write artifact must "
            "match the direction-level byte_length and SHA-256 payload, and protocol_packets JSONL must "
            "contain clipboard offer/request/content records for the matching transfer direction, change ID, "
            "session ID, session epoch, and origin, with offer/content records also matching text/plain, "
            "byte_length, and SHA-256 payload metadata. "
            "Offline or synthetic coverage alone remains readiness evidence."
        ),
    }


def _failure_report(error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "verdict": BLOCKED,
        "result": BLOCKED,
        "gate_closed": False,
        "can_close_android_macos_clipboard_e2e_gate": False,
        "checks": [_gate("gate_input", BLOCKED, [error])],
        "blockers": [sanitize_text(error)],
        "not_proven": ["clipboard E2E evidence could not be evaluated"],
        "safety": {"offline_tests_do_not_close_gate": True, "public_output_sanitized": True},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-readiness", type=Path)
    parser.add_argument("--usb-preflight", type=Path)
    parser.add_argument("--trusted-lan-preflight", type=Path)
    parser.add_argument("--android-clipboard-instrumentation-log", type=Path)
    parser.add_argument("--product-e2e", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--serial", help="Raw serial accepted for invocation auditing; never emitted")
    parser.add_argument("--serial-label", default=SAFE_SERIAL_LABEL)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = derive_gate(
            host_readiness=args.host_readiness,
            usb_preflight=args.usb_preflight,
            trusted_lan_preflight=args.trusted_lan_preflight,
            android_clipboard_instrumentation_log=args.android_clipboard_instrumentation_log,
            product_e2e=args.product_e2e,
            repo_root=args.repo_root,
            serial_label=args.serial_label,
        )
    except (ClipboardE2EGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(str(error))
    _write_json(args.output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    if report.get("verdict") == PASS:
        return 0
    return 2 if not args.require_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
