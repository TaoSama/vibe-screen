"""Validate the Phase 1 actionable-error state owner matrix.

This gate is intentionally offline. It validates that the documented Android
and macOS Host system states have stable ownership, user actions, retry policy,
and evidence boundaries. It does not start the Host, run ADB, inspect devices,
or close the README Phase 1 device acceptance gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from . import SCHEMA_VERSION


KIND = "phase1_actionable_error_state_matrix"
REPORT_KIND = "phase1_actionable_error_state_gate"
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
VALID_PLATFORMS = frozenset(("android", "macos_host"))
VALID_RETRY_BEHAVIORS = frozenset(
    ("bounded_auto_retry", "manual_retry", "terminal_no_retry", "not_applicable")
)
VALID_EVIDENCE_STATUSES = frozenset(
    ("device-covered", "offline-covered", "blocked", "open", "offline-only")
)
VALID_GATE_STATUSES = frozenset(("device-covered", "covered-offline", "blocked", "open"))
REQUIRED_OPEN_PRS = frozenset((242, 243, 272))
MIN_ANDROID_STATES = 8
MIN_HOST_STATES = 8
REMOTE_EVIDENCE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
SESSION_FAILURE_ENUM_RE = re.compile(r"\benum\s+class\s+SessionFailureKind\b")
REQUIRED_ACTIONABLE_CONTRACTS = {
    "host_screen_recording_denied": {
        "title": "Screen Recording permission denied",
        "body": (
            "The macOS Host cannot capture a display because Screen Recording permission "
            "is missing or stale for the installed app identity."
        ),
        "action": (
            "Grant Screen Recording to the installed Vibe Screen app in System Settings, "
            "quit, reopen, and rerun the Host preflight."
        ),
    },
    "accessibility_denied_or_limited": {
        "title": "Accessibility permission denied",
        "body": (
            "macOS input injection or window movement is unavailable because Accessibility "
            "is not granted to the stable signed Host app."
        ),
        "action": (
            "Grant Accessibility to the stable signed installed app, quit and reopen "
            "Vibe Screen, then retry input or window movement."
        ),
    },
    "adb_reverse_missing": {
        "title": "ADB reverse route missing",
        "body": (
            "USB mode cannot reach the Mac because the Android-to-Mac reverse route for "
            "TCP 54321 is missing, refused, or stale."
        ),
        "action": (
            "Reconnect or authorize the Android device, use the Mac app USB repair action "
            "to restore the reverse route, then retry."
        ),
    },
    "usb_disconnected": {
        "title": "USB device disconnected",
        "body": (
            "The Android device is no longer reachable over the authorized USB debugging "
            "transport, so the client cannot use the local stream route."
        ),
        "action": (
            "Reconnect the cable, unlock and authorize the phone, wait for the Mac app "
            "to repair USB routing, then retry."
        ),
    },
    "lan_route_unavailable": {
        "title": "LAN route unavailable",
        "body": (
            "Trusted LAN cannot route from the Android device to the saved Mac address "
            "and port on the same private network."
        ),
        "action": (
            "Reconnect both devices to the same trusted Wi-Fi, disable VPN or guest "
            "isolation, verify the saved Mac address and port, then reconnect."
        ),
    },
    "tcp_54321_unavailable": {
        "title": "TCP 54321 unavailable",
        "body": (
            "The Host is not reachable on TCP port 54321 because the listener is absent, "
            "failed to start, or the port is occupied."
        ),
        "action": (
            "Start or restart Vibe Screen on the Mac. If another process is listening "
            "on TCP 54321, stop it and restart Vibe Screen."
        ),
    },
    "stale_epoch_or_session_errors": {
        "title": "Stale session epoch",
        "body": (
            "The client rejected data from an older Protocol v1 session or configuration "
            "epoch to protect the current stream state."
        ),
        "action": (
            "Reconnect for a fresh session epoch; if it repeats, update both devices "
            "and collect logs instead of treating recovery as device-verified."
        ),
    },
}
REQUIRED_ACTIONABLE_CONTRACT_CODES = frozenset(REQUIRED_ACTIONABLE_CONTRACTS)
REQUIRED_CONTRACT_FIELDS = ("code", "title", "body", "action")
REQUIRED_ANDROID_GUIDANCE_CONTRACTS = {
    "adb_reverse_missing": {
        "context": "usb",
        "sample_failure": {
            "source": "throwable",
            "type": "ConnectException",
            "message": "ECONNREFUSED",
        },
        "kind": "USB_ROUTE_UNAVAILABLE",
        "status_resource": "connection_guidance_adb_route_unavailable_title",
        "message_resource": "connection_guidance_usb_recovery_usb",
        "message_prefix_resource": "connection_guidance_usb_route_unavailable_prefix",
        "recovery_button_action": "connectButton.try_again",
    },
    "usb_disconnected": {
        "context": "usb",
        "sample_failure": {
            "source": "throwable",
            "type": "NoRouteToHostException",
            "message": "ENETUNREACH",
        },
        "kind": "NETWORK_UNREACHABLE",
        "status_resource": "connection_guidance_adb_route_unavailable_title",
        "message_resource": "connection_guidance_usb_recovery_usb",
        "message_prefix_resource": "connection_guidance_usb_route_unavailable_prefix",
        "recovery_button_action": "connectButton.try_again",
    },
    "lan_route_unavailable": {
        "context": "lan",
        "sample_failure": {
            "source": "throwable",
            "type": "NoRouteToHostException",
            "message": "ENETUNREACH",
        },
        "kind": "NETWORK_UNREACHABLE",
        "status_resource": "connection_guidance_lan_route_unavailable_title",
        "message_resource": "connection_guidance_lan_network_unavailable_message",
        "recovery_button_action": "wirelessReconnectButton.reconnect",
    },
    "stale_epoch_or_session_errors": {
        "context": "internet",
        "sample_failure": {
            "source": "session_failure",
            "kind": "INVALID_MEDIA_PAYLOAD",
            "message": "stale_session_epoch",
        },
        "kind": "STALE_SESSION",
        "status_resource": "connection_guidance_stale_session_title",
        "message_resource": "connection_guidance_stale_session_message",
        "recovery_button_action": "internetConnectButton.fresh_session_retry",
    },
}
REQUIRED_ANDROID_GUIDANCE_CONTRACT_CODES = frozenset(REQUIRED_ANDROID_GUIDANCE_CONTRACTS)
VALID_ANDROID_GUIDANCE_CONTEXTS = frozenset(("usb", "lan", "internet"))
VALID_ANDROID_GUIDANCE_KINDS = frozenset(
    (
        "HOST_NOT_RUNNING",
        "USB_ROUTE_UNAVAILABLE",
        "NETWORK_UNREACHABLE",
        "TIMEOUT",
        "INCOMPATIBLE_SESSION",
        "STALE_SESSION",
        "INPUT_OVERLOADED",
        "UNKNOWN",
    )
)
VALID_ANDROID_GUIDANCE_SAMPLE_SOURCES = frozenset(("throwable", "session_failure"))
VALID_ANDROID_GUIDANCE_THROWABLE_TYPES = frozenset(
    ("ConnectException", "NoRouteToHostException", "SocketTimeoutException", "IOException")
)
VALID_ANDROID_GUIDANCE_RECOVERY_ACTIONS = frozenset(
    (
        "connectButton.try_again",
        "wirelessReconnectButton.reconnect",
        "internetConnectButton.fresh_session_retry",
    )
)
REQUIRED_HOST_CLI_CONTRACTS = {
    "host_screen_recording_denied": {
        "pre_gui_fail_closed": True,
        "exit_code": "EXIT_FAILURE",
        "stderr_error_messages": [
            "Unknown Vibe Screen Host CLI flag: --self-test",
            "Multiple Vibe Screen Host CLI commands are not supported.",
            "Unknown iOS loopback scenario.",
        ],
        "no_permission_prompt_on_parse_failure": True,
    },
    "accessibility_denied_or_limited": {
        "pre_gui_fail_closed": True,
        "exit_code": "EXIT_FAILURE",
        "stderr_error_messages": [
            "Unknown Vibe Screen Host CLI flag: --self-test",
            "Multiple Vibe Screen Host CLI commands are not supported.",
            "Unknown iOS loopback scenario.",
        ],
        "no_permission_prompt_on_parse_failure": True,
    },
    "tcp_54321_unavailable": {
        "pre_gui_fail_closed": True,
        "exit_code": "EXIT_FAILURE",
        "stderr_error_messages": [
            "Unknown Vibe Screen Host CLI flag: --self-test",
            "Multiple Vibe Screen Host CLI commands are not supported.",
            "Unknown iOS loopback scenario.",
        ],
        "no_permission_prompt_on_parse_failure": True,
    },
}
REQUIRED_HOST_CLI_CONTRACT_CODES = frozenset(REQUIRED_HOST_CLI_CONTRACTS)
REQUIRED_ACTIONABLE_STATE_ID_SEQUENCE = (
    "android-internet-webrtc-disconnected",
    "android-codec-negotiation-failed",
    "android-managed-policy-deny",
    "android-unsupported-peripheral-kind",
    "android-file-transfer-policy-deny",
    "android-clipboard-policy-deny",
)
REQUIRED_ACTIONABLE_STATE_IDS = frozenset(REQUIRED_ACTIONABLE_STATE_ID_SEQUENCE)

REQUIRED_STATE_FIELDS = (
    "id",
    "platform",
    "system_state",
    "failed_layer",
    "source_classifier",
    "ui_surface",
    "user_visible_copy",
    "user_action",
    "retry_behavior",
    "offline_evidence",
    "device_evidence_status",
    "gate_status",
    "readme_gate_closure",
)


class ActionableErrorStateError(ValueError):
    """Raised when the actionable-error matrix is malformed."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def load_matrix(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise ActionableErrorStateError(f"could not read {path}: {error}") from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ActionableErrorStateError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict):
        raise ActionableErrorStateError("top-level matrix must be an object")
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _integer_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]


def _state_id_set(states: list[dict[str, Any]], platform: str) -> set[str]:
    return {
        state["id"]
        for state in states
        if state.get("platform") == platform and isinstance(state.get("id"), str)
    }


def _skip_quoted(source: str, start: int) -> int:
    if source.startswith('\"\"\"', start):
        end = source.find('\"\"\"', start + 3)
        if end == -1:
            return len(source)
        return end + 3

    quote = source[start]
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character == quote:
            return index + 1
        index += 1
    return len(source)


def _skip_comment(source: str, start: int) -> int | None:
    if source.startswith("//", start):
        end = source.find("\n", start + 2)
        return len(source) if end == -1 else end + 1
    if source.startswith("/*", start):
        end = source.find("*/", start + 2)
        return len(source) if end == -1 else end + 2
    return None


def _extract_balanced_brace_body(source: str, open_brace_index: int) -> str:
    depth = 0
    body_start = open_brace_index + 1
    index = open_brace_index
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[body_start:index]
            if depth < 0:
                break
        index += 1
    raise ActionableErrorStateError("SessionFailureKind enum body is not balanced")


def _find_next_open_brace(source: str, start: int) -> int:
    index = start
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        if character == "{":
            return index
        index += 1
    return -1


def _find_session_failure_enum_open_brace(source: str) -> int:
    index = 0
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = source[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(source, index)
            continue
        match = SESSION_FAILURE_ENUM_RE.match(source, index)
        if match:
            return _find_next_open_brace(source, match.end())
        index += 1
    return -1


def _parse_enum_constants(body: str) -> set[str]:
    kinds: set[str] = set()
    nesting = 0
    expecting_entry = True
    index = 0
    while index < len(body):
        comment_end = _skip_comment(body, index)
        if comment_end is not None:
            index = comment_end
            continue
        character = body[index]
        if character in {'\"', "'"}:
            index = _skip_quoted(body, index)
            continue
        if nesting == 0 and character == ";":
            break
        if character in "({[":
            nesting += 1
            index += 1
            continue
        if character in ")}]":
            nesting -= 1
            if nesting < 0:
                raise ActionableErrorStateError(
                    "SessionFailureKind enum constants are not balanced"
                )
            index += 1
            continue
        if nesting == 0 and character == ",":
            expecting_entry = True
            index += 1
            continue
        if nesting == 0 and expecting_entry:
            if character.isspace():
                index += 1
                continue
            match = re.match(r"[A-Z][A-Z0-9_]*\b", body[index:])
            if match:
                kinds.add(match.group(0))
                expecting_entry = False
                index += len(match.group(0))
                continue
        index += 1
    if nesting != 0:
        raise ActionableErrorStateError(
            "SessionFailureKind enum constants are not balanced"
        )
    return kinds


def parse_session_failure_kinds(source_path: Path) -> set[str]:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ActionableErrorStateError(
            f"could not read Android SessionFailure source: {error}"
        ) from error
    open_brace_index = _find_session_failure_enum_open_brace(source)
    if open_brace_index == -1:
        raise ActionableErrorStateError(
            "could not find enum class SessionFailureKind body in Android source"
        )
    kinds = _parse_enum_constants(
        _extract_balanced_brace_body(source, open_brace_index)
    )
    if not kinds:
        raise ActionableErrorStateError("SessionFailureKind enum contains no cases")
    return kinds


def _evidence_path(reference: str) -> str | None:
    stripped = reference.strip()
    if not stripped or REMOTE_EVIDENCE_RE.match(stripped):
        return None
    path = stripped.split("#", 1)[0]
    return path or None


def _evidence_anchor(reference: str) -> str | None:
    stripped = reference.strip()
    if "#" not in stripped or REMOTE_EVIDENCE_RE.match(stripped):
        return None
    anchor = stripped.split("#", 1)[1]
    return anchor or None


def _markdown_anchor_base(heading: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", heading.strip())
    text = re.sub(r"\s+#+\s*$", "", text).strip().lower()
    text = text.replace("`", "")
    characters: list[str] = []
    previous_hyphen = False
    for character in text:
        if character.isalnum() or character == "_":
            characters.append(character)
            previous_hyphen = False
        elif character.isspace() or character == "-":
            if not previous_hyphen:
                characters.append("-")
                previous_hyphen = True
    return "".join(characters).strip("-")


def _markdown_heading_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return anchors
    for line in lines:
        match = re.match(r"^ {0,3}#{1,6}\s+.+$", line)
        if match is None:
            continue
        base = _markdown_anchor_base(line)
        if not base:
            continue
        duplicate_index = counts.get(base, 0)
        anchor = base if duplicate_index == 0 else f"{base}-{duplicate_index}"
        counts[base] = duplicate_index + 1
        anchors.add(anchor)
    return anchors


def _has_markdown_anchor(path: Path, anchor: str) -> bool:
    if path.suffix.lower() not in {".md", ".markdown"}:
        return True
    return anchor in _markdown_heading_anchors(path)


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_top_level(matrix: dict[str, Any], errors: list[str]) -> None:
    if matrix.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    if matrix.get("kind") != KIND:
        errors.append(f"kind: must be {KIND}")
    if matrix.get("readme_gate_closure") is not False:
        errors.append("readme_gate_closure: must be false for this offline owner slice")
    if not _non_empty_string(matrix.get("owner")):
        errors.append("owner: must be a non-empty string")
    if not _non_empty_string(matrix.get("evidence_boundary")):
        errors.append("evidence_boundary: must be a non-empty string")

    reviewed = matrix.get("reviewed_open_prs")
    if not isinstance(reviewed, list) or not all(isinstance(item, int) for item in reviewed):
        errors.append("reviewed_open_prs: must be an array of PR numbers")
        return
    missing = sorted(REQUIRED_OPEN_PRS.difference(reviewed))
    if missing:
        errors.append(
            "reviewed_open_prs: missing required PR review(s) "
            + ", ".join(f"#{pr}" for pr in missing)
        )


def _validate_dict_matches(
    value: Any,
    expected: dict[str, Any],
    prefix: str,
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{prefix}: must be an object")
        return False
    is_valid = True
    for key, expected_value in expected.items():
        if key not in value:
            errors.append(f"{prefix}.{key}: is required")
            is_valid = False
            continue
        actual_value = value[key]
        if isinstance(expected_value, dict):
            is_valid = _validate_dict_matches(
                actual_value, expected_value, f"{prefix}.{key}", errors
            ) and is_valid
        elif actual_value != expected_value:
            errors.append(f"{prefix}.{key}: must match the stable value")
            is_valid = False
    return is_valid


def _validate_android_guidance_contract_shape(
    value: Any,
    prefix: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{prefix}: must be an object when present")
        return
    for field in (
        "context",
        "sample_failure",
        "kind",
        "status_resource",
        "message_resource",
        "recovery_button_action",
    ):
        if field not in value:
            errors.append(f"{prefix}.{field}: is required")
    if value.get("context") not in VALID_ANDROID_GUIDANCE_CONTEXTS:
        errors.append(
            f"{prefix}.context: must be one of "
            f"{', '.join(sorted(VALID_ANDROID_GUIDANCE_CONTEXTS))}"
        )
    if value.get("kind") not in VALID_ANDROID_GUIDANCE_KINDS:
        errors.append(
            f"{prefix}.kind: must be one of "
            f"{', '.join(sorted(VALID_ANDROID_GUIDANCE_KINDS))}"
        )
    for field in ("status_resource", "message_resource", "message_prefix_resource"):
        if field in value and not _non_empty_string(value.get(field)):
            errors.append(f"{prefix}.{field}: must be a non-empty string")
    if value.get("recovery_button_action") not in VALID_ANDROID_GUIDANCE_RECOVERY_ACTIONS:
        errors.append(
            f"{prefix}.recovery_button_action: must be one of "
            f"{', '.join(sorted(VALID_ANDROID_GUIDANCE_RECOVERY_ACTIONS))}"
        )

    sample = value.get("sample_failure")
    if not isinstance(sample, dict):
        errors.append(f"{prefix}.sample_failure: must be an object")
        return
    if sample.get("source") not in VALID_ANDROID_GUIDANCE_SAMPLE_SOURCES:
        errors.append(
            f"{prefix}.sample_failure.source: must be one of "
            f"{', '.join(sorted(VALID_ANDROID_GUIDANCE_SAMPLE_SOURCES))}"
        )
    if not _non_empty_string(sample.get("message")):
        errors.append(f"{prefix}.sample_failure.message: must be a non-empty string")
    if sample.get("source") == "throwable":
        if sample.get("type") not in VALID_ANDROID_GUIDANCE_THROWABLE_TYPES:
            errors.append(
                f"{prefix}.sample_failure.type: must be one of "
                f"{', '.join(sorted(VALID_ANDROID_GUIDANCE_THROWABLE_TYPES))}"
            )
    elif sample.get("source") == "session_failure":
        if not _non_empty_string(sample.get("kind")):
            errors.append(f"{prefix}.sample_failure.kind: must be a non-empty string")


def _validate_required_android_guidance_contract(
    contract_code: str,
    value: Any,
    prefix: str,
    errors: list[str],
) -> bool:
    expected = REQUIRED_ANDROID_GUIDANCE_CONTRACTS[contract_code]
    if value is None:
        errors.append(
            f"{prefix}: required Android guidance contract {contract_code} is missing"
        )
        return False
    _validate_android_guidance_contract_shape(value, prefix, errors)
    return _validate_dict_matches(value, expected, prefix, errors)


def _validate_host_cli_contract_shape(
    value: Any,
    prefix: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{prefix}: must be an object when present")
        return
    if value.get("pre_gui_fail_closed") is not True:
        errors.append(f"{prefix}.pre_gui_fail_closed: must be true")
    if value.get("exit_code") != "EXIT_FAILURE":
        errors.append(f"{prefix}.exit_code: must be EXIT_FAILURE")
    if value.get("no_permission_prompt_on_parse_failure") is not True:
        errors.append(f"{prefix}.no_permission_prompt_on_parse_failure: must be true")
    messages = value.get("stderr_error_messages")
    if not isinstance(messages, list) or not all(
        isinstance(item, str) and item.strip() for item in messages
    ):
        errors.append(f"{prefix}.stderr_error_messages: must be a list of non-empty strings")


def _validate_required_host_cli_contract(
    contract_code: str,
    value: Any,
    prefix: str,
    errors: list[str],
) -> bool:
    expected = REQUIRED_HOST_CLI_CONTRACTS[contract_code]
    if value is None:
        errors.append(f"{prefix}: required Host CLI contract {contract_code} is missing")
        return False
    _validate_host_cli_contract_shape(value, prefix, errors)
    return _validate_dict_matches(value, expected, prefix, errors)


def _validate_state(
    state: dict[str, Any],
    index: int,
    ids: set[str],
    contract_codes: dict[str, str],
    covered_contract_codes: set[str],
    covered_required_state_ids: set[str],
    errors: list[str],
    *,
    repository_root: Path | None = None,
) -> None:
    prefix = f"states[{index}]"
    for field in REQUIRED_STATE_FIELDS:
        if field not in state:
            errors.append(f"{prefix}.{field}: is required")

    state_id = state.get("id")
    if not _non_empty_string(state_id):
        errors.append(f"{prefix}.id: must be a non-empty string")
    elif state_id in ids:
        errors.append(f"{prefix}.id: duplicate state id {state_id}")
    else:
        ids.add(state_id)

    if state.get("platform") not in VALID_PLATFORMS:
        errors.append(f"{prefix}.platform: must be android or macos_host")

    for field in (
        "system_state",
        "failed_layer",
        "source_classifier",
        "ui_surface",
        "user_visible_copy",
        "user_action",
    ):
        if not _non_empty_string(state.get(field)):
            errors.append(f"{prefix}.{field}: must be a non-empty string")

    if state.get("retry_behavior") not in VALID_RETRY_BEHAVIORS:
        errors.append(
            f"{prefix}.retry_behavior: must be one of "
            f"{', '.join(sorted(VALID_RETRY_BEHAVIORS))}"
        )
    if state.get("device_evidence_status") not in VALID_EVIDENCE_STATUSES:
        errors.append(
            f"{prefix}.device_evidence_status: must be one of "
            f"{', '.join(sorted(VALID_EVIDENCE_STATUSES))}"
        )
    if state.get("gate_status") not in VALID_GATE_STATUSES:
        errors.append(
            f"{prefix}.gate_status: must be one of "
            f"{', '.join(sorted(VALID_GATE_STATUSES))}"
        )
    if state.get("readme_gate_closure") is not False:
        errors.append(f"{prefix}.readme_gate_closure: must be false")

    offline_evidence = _string_list(state.get("offline_evidence"))
    has_local_offline_evidence = False
    if not offline_evidence:
        errors.append(f"{prefix}.offline_evidence: must contain at least one reference")
    elif repository_root is not None:
        root = repository_root.resolve()
        for reference in offline_evidence:
            relative_path = _evidence_path(reference)
            if relative_path is None:
                continue
            evidence_path = (root / relative_path).resolve()
            if not _path_is_inside(evidence_path, root) or not evidence_path.exists():
                errors.append(
                    f"{prefix}.offline_evidence: missing repository path {relative_path}"
                )
            elif evidence_path.is_file():
                anchor = _evidence_anchor(reference)
                has_valid_anchor = anchor is None or _has_markdown_anchor(evidence_path, anchor)
                if not has_valid_anchor:
                    errors.append(
                        f"{prefix}.offline_evidence: missing markdown anchor "
                        f"{relative_path}#{anchor}"
                    )
                else:
                    has_local_offline_evidence = True
    if "localizedDescription" == str(state.get("user_visible_copy")).strip():
        errors.append(f"{prefix}.user_visible_copy: must not be a bare localizedDescription")

    contract = state.get("contract")
    contract_code: str | None = None
    if contract is not None:
        if not isinstance(contract, dict):
            errors.append(f"{prefix}.contract: must be an object when present")
        else:
            for field in REQUIRED_CONTRACT_FIELDS:
                if not _non_empty_string(contract.get(field)):
                    errors.append(f"{prefix}.contract.{field}: must be a non-empty string")
            code = contract.get("code")
            if _non_empty_string(code):
                raw_code = str(code)
                contract_code = raw_code
                normalized_code = raw_code.strip()
                if raw_code != normalized_code:
                    errors.append(
                        f"{prefix}.contract.code: must not contain surrounding whitespace"
                    )
                is_duplicate_contract_code = raw_code in contract_codes
                if raw_code in contract_codes:
                    errors.append(
                        f"{prefix}.contract.code: duplicate contract code {raw_code} "
                        f"already used by {contract_codes[raw_code]}"
                    )
                else:
                    contract_codes[raw_code] = str(state_id)
                if raw_code not in REQUIRED_ACTIONABLE_CONTRACT_CODES:
                    errors.append(f"{prefix}.contract.code: unsupported contract code {raw_code}")
                else:
                    expected_contract = REQUIRED_ACTIONABLE_CONTRACTS[raw_code]
                    has_required_contract_values = True
                    for field, expected_value in expected_contract.items():
                        if contract.get(field) != expected_value:
                            has_required_contract_values = False
                            errors.append(
                                f"{prefix}.contract.{field}: required contract {raw_code} "
                                "must match the stable value"
                            )
                    has_required_gate_status = state.get("gate_status") == "covered-offline"
                    has_required_evidence = has_local_offline_evidence
                    has_required_readme_boundary = state.get("readme_gate_closure") is False
                    if not has_required_gate_status:
                        errors.append(
                            f"{prefix}.gate_status: required contract {raw_code} "
                            "must be covered-offline"
                        )
                    if not has_required_evidence:
                        errors.append(
                            f"{prefix}.offline_evidence: required contract {raw_code} "
                            "must cite local offline evidence"
                        )
                    if not has_required_readme_boundary:
                        errors.append(
                            f"{prefix}.readme_gate_closure: required contract {raw_code} "
                            "must stay false for offline coverage"
                        )
                    if (
                        has_required_contract_values
                        and
                        has_required_gate_status
                        and has_required_evidence
                        and has_required_readme_boundary
                        and not is_duplicate_contract_code
                    ):
                        covered_contract_codes.add(raw_code)

    android_guidance_contract = state.get("android_guidance_contract")
    if contract_code in REQUIRED_ANDROID_GUIDANCE_CONTRACT_CODES:
        _validate_required_android_guidance_contract(
            contract_code,
            android_guidance_contract,
            f"{prefix}.android_guidance_contract",
            errors,
        )
    elif android_guidance_contract is not None:
        _validate_android_guidance_contract_shape(
            android_guidance_contract,
            f"{prefix}.android_guidance_contract",
            errors,
        )

    host_cli_contract = state.get("host_cli_contract")
    if contract_code in REQUIRED_HOST_CLI_CONTRACT_CODES:
        _validate_required_host_cli_contract(
            contract_code,
            host_cli_contract,
            f"{prefix}.host_cli_contract",
            errors,
        )
    elif host_cli_contract is not None:
        _validate_host_cli_contract_shape(
            host_cli_contract,
            f"{prefix}.host_cli_contract",
            errors,
        )

    is_required_actionable_state = (
        isinstance(state_id, str) and state_id in REQUIRED_ACTIONABLE_STATE_IDS
    )
    if is_required_actionable_state:
        has_required_state_gate_status = state.get("gate_status") == "covered-offline"
        has_required_state_readme_boundary = state.get("readme_gate_closure") is False
        has_required_state_fields = (
            _non_empty_string(state.get("failed_layer"))
            and _non_empty_string(state.get("ui_surface"))
            and _non_empty_string(state.get("user_action"))
            and state.get("retry_behavior") in VALID_RETRY_BEHAVIORS
        )
        if not has_required_state_gate_status:
            errors.append(
                f"{prefix}.gate_status: required actionable state {state_id} "
                "must be covered-offline"
            )
        if not has_local_offline_evidence:
            errors.append(
                f"{prefix}.offline_evidence: required actionable state {state_id} "
                "must cite local offline evidence"
            )
        if not has_required_state_readme_boundary:
            errors.append(
                f"{prefix}.readme_gate_closure: required actionable state {state_id} "
                "must stay false for offline coverage"
            )
        if (
            has_required_state_gate_status
            and has_local_offline_evidence
            and has_required_state_readme_boundary
            and has_required_state_fields
        ):
            covered_required_state_ids.add(str(state_id))

    android_failure_kinds = state.get("android_session_failure_kinds", [])
    if android_failure_kinds is None:
        android_failure_kinds = []
    if not isinstance(android_failure_kinds, list) or not all(
        isinstance(item, str) and item.strip() for item in android_failure_kinds
    ):
        errors.append(
            f"{prefix}.android_session_failure_kinds: must be a list of non-empty strings"
        )


def evaluate(
    matrix: dict[str, Any],
    *,
    android_session_failure_kinds: set[str] | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    _validate_top_level(matrix, errors)

    states_value = matrix.get("states")
    if not isinstance(states_value, list):
        errors.append("states: must be an array")
        states: list[dict[str, Any]] = []
    else:
        states = []
        for index, item in enumerate(states_value):
            if isinstance(item, dict):
                states.append(item)
            else:
                errors.append(f"states[{index}]: must be an object")

    ids: set[str] = set()
    contract_codes: dict[str, str] = {}
    covered_contract_codes: set[str] = set()
    covered_required_state_ids: set[str] = set()
    for index, state in enumerate(states):
        _validate_state(
            state,
            index,
            ids,
            contract_codes,
            covered_contract_codes,
            covered_required_state_ids,
            errors,
            repository_root=repository_root,
        )

    android_state_ids = _state_id_set(states, "android")
    host_state_ids = _state_id_set(states, "macos_host")
    if len(android_state_ids) < MIN_ANDROID_STATES:
        errors.append(f"states: must contain at least {MIN_ANDROID_STATES} Android states")
    if len(host_state_ids) < MIN_HOST_STATES:
        errors.append(f"states: must contain at least {MIN_HOST_STATES} macOS Host states")

    covered_session_failure_kinds: set[str] = set()
    for state in states:
        for kind in state.get("android_session_failure_kinds", []) or []:
            if isinstance(kind, str) and kind.strip():
                covered_session_failure_kinds.add(kind.strip())
    missing_session_failure_kinds: list[str] = []
    if android_session_failure_kinds is not None:
        missing_session_failure_kinds = sorted(
            android_session_failure_kinds.difference(covered_session_failure_kinds)
        )
        for kind in missing_session_failure_kinds:
            errors.append(f"android_session_failure_kinds: missing {kind}")
        unknown_session_failure_kinds = sorted(
            covered_session_failure_kinds.difference(android_session_failure_kinds)
        )
        for kind in unknown_session_failure_kinds:
            errors.append(f"android_session_failure_kinds: unknown {kind}")
    else:
        unknown_session_failure_kinds = []

    missing_contract_codes = sorted(
        REQUIRED_ACTIONABLE_CONTRACT_CODES.difference(contract_codes)
    )
    for code in missing_contract_codes:
        errors.append(f"required_actionable_contracts: missing {code}")

    missing_required_state_ids = sorted(REQUIRED_ACTIONABLE_STATE_IDS.difference(ids))
    for state_id in missing_required_state_ids:
        errors.append(f"required_actionable_states: missing {state_id}")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "verdict": STATUS_PASS if not errors else STATUS_FAIL,
        "can_close_readme_phase1_actionable_errors_gate": False,
        "matrix_kind": matrix.get("kind") if isinstance(matrix.get("kind"), str) else "",
        "owner": matrix.get("owner") if isinstance(matrix.get("owner"), str) else "",
        "state_count": len(states),
        "android_state_count": len(android_state_ids),
        "macos_host_state_count": len(host_state_ids),
        "reviewed_open_prs": _integer_list(matrix.get("reviewed_open_prs")),
        "required_actionable_state_ids": sorted(REQUIRED_ACTIONABLE_STATE_IDS),
        "covered_actionable_state_ids": sorted(covered_required_state_ids),
        "missing_actionable_state_ids": missing_required_state_ids,
        "required_actionable_contract_codes": sorted(REQUIRED_ACTIONABLE_CONTRACT_CODES),
        "covered_actionable_contract_codes": sorted(covered_contract_codes),
        "missing_actionable_contract_codes": missing_contract_codes,
        "covered_android_session_failure_kinds": sorted(covered_session_failure_kinds),
        "missing_android_session_failure_kinds": missing_session_failure_kinds,
        "unknown_android_session_failure_kinds": unknown_session_failure_kinds,
        "errors": errors,
        "interpretation": (
            "This offline gate validates matrix ownership and drift coverage only. "
            "It does not prove Android or macOS runtime acceptance and cannot close "
            "the README Phase 1 actionable-errors gate without retained device evidence."
        ),
    }


def _write_report(report: dict[str, Any], output: TextIO) -> None:
    json.dump(report, output, indent=2, sort_keys=True)
    output.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the Vibe Screen Phase 1 actionable-error state matrix."
    )
    parser.add_argument("matrix", help="actionable error state matrix JSON file")
    parser.add_argument(
        "--android-session-failure-source",
        help="optional SessionFailure.kt path for enum drift coverage",
    )
    parser.add_argument(
        "--repository-root",
        default=".",
        help=(
            "repository root for validating repository-relative offline evidence "
            "paths (default: current directory)"
        ),
    )
    parser.add_argument("--output", help="output gate JSON file (default: stdout)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        matrix = load_matrix(Path(args.matrix))
        session_failure_kinds = None
        if args.android_session_failure_source:
            session_failure_kinds = parse_session_failure_kinds(
                Path(args.android_session_failure_source)
            )
        report = evaluate(
            matrix,
            android_session_failure_kinds=session_failure_kinds,
            repository_root=Path(args.repository_root),
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as stream:
                _write_report(report, stream)
        else:
            _write_report(report, sys.stdout)
    except (ActionableErrorStateError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if report["verdict"] == STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
