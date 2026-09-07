"""Evaluate Android <-> macOS Protocol v1 single-file transfer evidence.

The gate is intentionally fail-closed. USB/LAN preflight, Android-local smoke
logs, JVM tests, protocol fixtures, and Host self-tests are useful readiness
evidence, but they cannot close the real file-transfer smoke gate without
retained product evidence for both transfer directions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION


KIND = "android_macos_file_transfer_smoke"
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
SAFE_SERIAL_LABEL = "REDACTED_P0110_USB_SERIAL"
TCC_PATH_COMPONENT = "Application" + r"\s+" + "Support/com" + r"\.apple\." + "TCC"
TCC_BUNDLE_COMPONENT = "com" + r"\.apple\." + "TCC"
TCC_DATABASE_COMPONENT = "TCC" + r"\.db"
SENSITIVE_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"EP[0-9A-Z]{14,}", re.IGNORECASE), SAFE_SERIAL_LABEL),
    (re.compile(TCC_PATH_COMPONENT, re.IGNORECASE), "<redacted-tcc-reference>"),
    (re.compile(TCC_BUNDLE_COMPONENT, re.IGNORECASE), "<redacted-tcc-reference>"),
    (re.compile(TCC_DATABASE_COMPONENT, re.IGNORECASE), "<redacted-tcc-reference>"),
    (re.compile(r"/Users/[^\r\n<>\"']+"), "<redacted-local-path>"),
    (re.compile(r"/home/[^\r\n<>\"']+"), "<redacted-local-path>"),
)
RETAINED_ARTIFACTS_FIELD = "retained_artifacts"
REQUIRED_DIRECTION_ARTIFACT_ROLES = (
    "sender_action",
    "receiver_approval",
    "protocol_packets",
    "remote_file",
    "sha256_verification",
)
REQUIRED_CANCEL_ARTIFACT_ROLES = ("cancel_request", "cleanup_state")
EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_METHODS = (
    "fileTransferControlPreservesTouchTargetsWhenVisible",
    "productionApplierCoversStackedColumnAndHiddenSelectorBoundaries",
    "narrowAndLargeFontOfferDialogKeepsDecisionContentReadableAndScrollable",
    "offerLayoutKeepsDecisionCopyStructuredForDialogButtons",
    "outgoingConfirmationLayoutKeepsPreflightDetailsReadableAndScrollable",
)
EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_CLASSES = (
    "dev.telemachus.display.ControlBarLayoutInstrumentedTest",
    "dev.telemachus.display.FileTransferOfferDialogLayoutInstrumentedTest",
)
EXPECTED_DIRECTION_ENDPOINTS = {
    "android_to_macos_file_transfer": (
        "android_saf_selected_file",
        "macos_saved_file",
    ),
    "macos_to_android_file_transfer": (
        "macos_selected_file",
        "android_downloads_file",
    ),
}
HASH_CHUNK_BYTES = 1024 * 1024


class FileTransferAndroidSmokeGateError(ValueError):
    """Raised when evidence cannot be evaluated."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FileTransferAndroidSmokeGateError(f"cannot read {label}: {error}") from error
    if not isinstance(document, dict):
        raise FileTransferAndroidSmokeGateError(f"{label} must be a JSON object")
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
    for pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


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


def _retained_artifact_reasons(
    document: dict[str, Any],
    label: str,
    required_roles: Sequence[str],
    evidence_dir: Path | None,
    cross_product_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> list[str]:
    artifacts = document.get(RETAINED_ARTIFACTS_FIELD)
    if not isinstance(artifacts, list) or not artifacts:
        return [f"{label}.{RETAINED_ARTIFACTS_FIELD} must retain product evidence artifacts"]

    reasons: list[str] = []
    resolved_evidence_dir = evidence_dir.resolve() if evidence_dir is not None else None
    required_role_names = set(required_roles)
    seen_roles: set[str] = set()
    seen_artifact_paths: dict[Path | str, str] = {}
    for index, artifact in enumerate(artifacts):
        artifact_label = f"{label}.{RETAINED_ARTIFACTS_FIELD}[{index}]"
        if not isinstance(artifact, dict):
            reasons.append(f"{artifact_label} must be an object")
            continue
        role = artifact.get("role")
        if isinstance(role, str) and role.strip():
            role_name = role.strip()
            if role_name not in required_role_names:
                reasons.append(f"{artifact_label}.role must be one of {', '.join(required_roles)}")
                role_is_required = False
            elif role_name in seen_roles:
                reasons.append(f"{artifact_label}.role duplicates {role_name} artifact")
                role_is_required = True
            else:
                role_is_required = True
            seen_roles.add(role_name)
        else:
            role_name = f"entry {index}"
            role_is_required = False
            reasons.append(f"{artifact_label}.role must be present")

        path_value = artifact.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            reasons.append(f"{artifact_label}.path must be present")
            continue
        path = Path(path_value)
        if path.is_absolute():
            reasons.append(f"{artifact_label}.path must be evidence-relative")
            continue
        if (path.parts and path.parts[0] == "..") or ".." in path.parts:
            reasons.append(f"{artifact_label}.path must stay inside the evidence bundle")
            continue
        artifact_key: Path | str | None = path.as_posix() if evidence_dir is None else None
        if evidence_dir is not None and resolved_evidence_dir is not None:
            candidate = evidence_dir / path
            try:
                resolved_candidate = candidate.resolve(strict=True)
            except FileNotFoundError:
                reasons.append(f"{artifact_label}.path missing retained artifact {sanitize_text(path_value)}")
                continue
            except (OSError, RuntimeError, ValueError) as error:
                reasons.append(
                    f"{artifact_label}.path cannot access retained artifact "
                    f"{sanitize_text(path_value)}: {sanitize_text(error)}"
                )
                continue
            try:
                resolved_candidate.relative_to(resolved_evidence_dir)
            except ValueError:
                reasons.append(f"{artifact_label}.path must stay inside the evidence bundle")
                continue
            if not resolved_candidate.is_file():
                reasons.append(f"{artifact_label}.path missing retained artifact {sanitize_text(path_value)}")
            elif resolved_candidate.stat().st_size <= 0:
                reasons.append(f"{artifact_label}.path retained artifact {sanitize_text(path_value)} must be non-empty")
            else:
                artifact_key = resolved_candidate
        if artifact_key is not None:
            previous_role = seen_artifact_paths.get(artifact_key)
            if previous_role is not None:
                reasons.append(f"{artifact_label}.path must be distinct from {previous_role} artifact path")
            else:
                seen_artifact_paths[artifact_key] = role_name
            if cross_product_artifact_paths is not None and role_is_required:
                previous_artifact = cross_product_artifact_paths.get(artifact_key)
                if previous_artifact is not None and previous_artifact[0] != label:
                    previous_label, previous_role = previous_artifact
                    reasons.append(
                        f"{artifact_label}.path for {role_name} must be distinct from "
                        f"{previous_label} {previous_role} artifact path"
                    )
                elif previous_artifact is None:
                    cross_product_artifact_paths[artifact_key] = (label, role_name)

    missing_roles = [role for role in required_roles if role not in seen_roles]
    reasons.extend(
        f"{label}.{RETAINED_ARTIFACTS_FIELD} missing {role} artifact"
        for role in missing_roles
    )
    return reasons


def _retained_artifact_path_by_role(document: dict[str, Any], role: str) -> Path | None:
    artifacts = document.get(RETAINED_ARTIFACTS_FIELD)
    if not isinstance(artifacts, list):
        return None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("role") != role:
            continue
        path_value = artifact.get("path")
        if isinstance(path_value, str) and path_value.strip():
            return Path(path_value)
    return None


def _remote_file_artifact_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
) -> list[str]:
    if evidence_dir is None:
        return []
    remote_file_path = _retained_artifact_path_by_role(direction, "remote_file")
    if remote_file_path is None or remote_file_path.is_absolute() or ".." in remote_file_path.parts:
        return []

    candidate = evidence_dir / remote_file_path
    try:
        resolved_evidence_dir = evidence_dir.resolve()
        remote_file = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return []
    try:
        remote_file.relative_to(resolved_evidence_dir)
    except ValueError:
        return []
    if not remote_file.is_file():
        return []

    byte_length = direction.get("byte_length")
    expected_sha256 = direction.get("sha256")
    reasons: list[str] = []
    if isinstance(byte_length, int) and not isinstance(byte_length, bool) and byte_length > 0:
        try:
            actual_size = remote_file.stat().st_size
        except OSError as error:
            reasons.append(f"{label}.remote_file artifact size cannot be read: {sanitize_text(error)}")
        else:
            if actual_size != byte_length:
                reasons.append(
                    f"{label}.remote_file artifact size {actual_size} must equal byte_length {byte_length}"
                )
    if isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        try:
            digest = hashlib.sha256()
            with remote_file.open("rb") as file_handle:
                for chunk in iter(lambda: file_handle.read(HASH_CHUNK_BYTES), b""):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
        except OSError as error:
            reasons.append(f"{label}.remote_file artifact SHA-256 cannot be read: {sanitize_text(error)}")
        else:
            if actual_sha256 != expected_sha256.lower():
                reasons.append(f"{label}.remote_file artifact SHA-256 must equal direction.sha256")
    return reasons


def _gate(
    name: str, status: str, reasons: Sequence[str], evidence: Sequence[str] = ()
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reasons": [sanitize_text(reason) for reason in reasons],
        "evidence": list(evidence),
    }


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
        failures.append("file-transfer evidence for this run must identify nubia P0110 / pacific")
    if manufacturer not in {"nubia", "zte"}:
        failures.append("P0110 evidence must not be relabeled as Xiaomi/fuxi or any other device")
    if android_release != "16":
        failures.append("P0110 file-transfer evidence must record Android 16")
    if sdk not in (36, "36"):
        failures.append("P0110 file-transfer evidence must record SDK 36")
    return failures


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
    return _gate(
        "host_readiness",
        PASS if not reasons else BLOCKED,
        reasons,
        ["host-readiness.json"] if host else [],
    )


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
        "at least one real Protocol v1 USB or trusted-LAN path must be ready before file-transfer smoke can pass"
    ]
    reasons.extend(f"usb: {reason}" for reason in usb_gate["reasons"])
    reasons.extend(f"trusted_lan: {reason}" for reason in lan_gate["reasons"])
    return _gate("real_transport_ready", BLOCKED, reasons, [])


def _android_file_transfer_gate(log_path: Path | None) -> dict[str, Any]:
    if log_path is None or not log_path.is_file():
        return _gate(
            "android_file_transfer_smoke",
            BLOCKED,
            ["current-run Android file-transfer instrumentation log is missing"],
        )
    raw_text = log_path.read_text(encoding="utf-8", errors="replace")
    executed_tests = _android_file_transfer_test_count(raw_text)
    passed_methods = _android_file_transfer_passed_methods(raw_text)
    class_executed_tests = _android_file_transfer_class_test_count(raw_text)
    has_failure_signal = (
        "FAILURES!!!" in raw_text
        or "BUILD FAILED" in raw_text
        or _android_file_transfer_has_junit_failures(raw_text)
    )
    has_success_summary = _android_file_transfer_has_success_summary(raw_text)
    has_method_rejection = _android_file_transfer_has_method_rejection(raw_text)
    expected_file_transfer_coverage = bool(passed_methods) or class_executed_tests >= 2
    passed = (
        executed_tests > 0
        and expected_file_transfer_coverage
        and has_success_summary
        and not has_failure_signal
        and not has_method_rejection
    )
    reasons = []
    if executed_tests <= 0:
        reasons.append("Android file-transfer instrumentation log does not show any executed tests")
    if not expected_file_transfer_coverage:
        reasons.append(
            "Android file-transfer instrumentation log must name a file-transfer UI smoke class "
            "and either list an expected file-transfer method or show at least 2 executed tests"
        )
    if has_failure_signal:
        reasons.append("Android file-transfer instrumentation log contains a failure result")
    if has_method_rejection:
        reasons.append("Android file-transfer instrumentation log contains a skipped or failed file-transfer smoke method")
    if not has_success_summary:
        reasons.append("Android file-transfer instrumentation log does not show an OK result")
    return _gate("android_file_transfer_smoke", PASS if passed else BLOCKED, reasons, [log_path.name])


def _android_file_transfer_test_count(text: str) -> int:
    counts = [
        int(match.group(1))
        for match in re.finditer(r"^OK \((\d+) tests?\)\r?$", text, re.MULTILINE)
    ]
    counts.extend(int(match.group(1)) for match in re.finditer(r"Tests run:\s*(\d+)", text))
    counts.extend(
        int(match.group(1)) for match in re.finditer(r"Finished\s+(\d+)\s+tests?\s+on\s+", text)
    )
    return max(counts, default=0)


def _android_file_transfer_has_junit_failures(text: str) -> bool:
    for match in re.finditer(r"Tests run:\s*\d+,\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)", text):
        if int(match.group(1)) > 0 or int(match.group(2)) > 0:
            return True
    for class_name in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_CLASSES:
        pattern = re.compile(rf"^{re.escape(class_name)}:[.FEIS]*[FE][.FEIS]*\r?$", re.MULTILINE)
        if pattern.search(text):
            return True
    return False


def _android_file_transfer_passed_methods(text: str) -> set[str]:
    passed_methods: set[str] = set()
    for class_name in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_CLASSES:
        escaped_class = re.escape(class_name)
        for method in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_METHODS:
            escaped_method = re.escape(method)
            if re.search(rf"{escaped_class}#{escaped_method}:\s*PASSED\b", text):
                passed_methods.add(method)
            if re.search(rf"finished:\s*{escaped_method}\({escaped_class}\)", text):
                passed_methods.add(method)
    return passed_methods


def _android_file_transfer_class_test_count(text: str) -> int:
    max_count = 0
    for class_name in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_CLASSES:
        compact_pattern = re.compile(rf"^{re.escape(class_name)}:(?P<markers>[.FEIS]+)\r?$", re.MULTILINE)
        for match in compact_pattern.finditer(text):
            max_count = max(max_count, match.group("markers").count("."))
        finished_pattern = re.compile(rf"finished:\s*[^\r\n()]+\({re.escape(class_name)}\)")
        max_count = max(max_count, len(finished_pattern.findall(text)))
    return max_count


def _android_file_transfer_has_method_rejection(text: str) -> bool:
    for class_name in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_CLASSES:
        escaped_class = re.escape(class_name)
        for method in EXPECTED_ANDROID_FILE_TRANSFER_SMOKE_METHODS:
            escaped_method = re.escape(method)
            if re.search(rf"{escaped_class}#{escaped_method}:\s*(SKIPPED|IGNORED|FAILED|ERROR)\b", text):
                return True
            if re.search(rf"(skipped|ignored|failed|error):\s*{escaped_method}\({escaped_class}\)", text, re.IGNORECASE):
                return True
    return False


def _android_file_transfer_has_success_summary(text: str) -> bool:
    ok_match = re.search(r"^OK \((\d+) tests?\)\r?$", text, re.MULTILINE)
    if ok_match and int(ok_match.group(1)) > 0:
        return True
    finished_match = re.search(r"Finished\s+(\d+)\s+tests?\s+on\s+", text)
    return bool(finished_match and int(finished_match.group(1)) > 0 and "BUILD SUCCESSFUL" in text)


def _direction_reasons(
    direction: dict[str, Any],
    label: str,
    evidence_dir: Path | None,
    cross_product_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> list[str]:
    required_true = (
        "protocol_v1_session",
        "file_offer_observed",
        "receiver_request_observed",
        "content_chunks_observed",
        "source_file_read",
        "explicit_user_action",
        "receiver_approved",
        "remote_file_written",
        "session_id_verified",
        "final_sha256_match",
        "session_epoch_verified",
        "transfer_id_verified",
        "progress_observed",
        "source_endpoint_verified",
        "destination_endpoint_verified",
    )
    reasons = [
        f"{label}.{field} must be true"
        for field in required_true
        if direction.get(field) is not True
    ]
    for field in ("file_name", "sha256"):
        value = direction.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{label}.{field} must be present")
    sha256 = direction.get("sha256")
    if isinstance(sha256, str) and not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        reasons.append(f"{label}.sha256 must be a 64-character hex SHA-256 digest")
    transfer_id = direction.get("transfer_id_hex")
    if not isinstance(transfer_id, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", transfer_id):
        reasons.append(f"{label}.transfer_id_hex must be a 32-character hex transfer ID")
    byte_length = direction.get("byte_length")
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length <= 0:
        reasons.append(f"{label}.byte_length must be a positive integer")
    session_epoch = direction.get("session_epoch")
    if not isinstance(session_epoch, int) or isinstance(session_epoch, bool) or session_epoch <= 0:
        reasons.append(f"{label}.session_epoch must be a positive integer")
    transport = direction.get("transport")
    if transport not in {"usb", "trusted_lan"}:
        reasons.append(f"{label}.transport must be usb or trusted_lan")
    source, destination = EXPECTED_DIRECTION_ENDPOINTS[label]
    if direction.get("source_endpoint") != source:
        reasons.append(f"{label}.source_endpoint must be {source}")
    if direction.get("destination_endpoint") != destination:
        reasons.append(f"{label}.destination_endpoint must be {destination}")
    reasons.extend(
        _retained_artifact_reasons(
            direction,
            label,
            REQUIRED_DIRECTION_ARTIFACT_ROLES,
            evidence_dir,
            cross_product_artifact_paths,
        )
    )
    reasons.extend(_remote_file_artifact_reasons(direction, label, evidence_dir))
    return reasons


def _product_e2e_gate(
    product: dict[str, Any] | None,
    missing: Sequence[str],
    available_transports: set[str],
    evidence_dir: Path | None,
    retained_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    reasons = list(missing)
    evidence = ["file-transfer-product-e2e.json"] if product is not None else []
    if product is not None:
        if product.get("kind") != "android_macos_file_transfer_product_e2e":
            reasons.append("product evidence kind must be android_macos_file_transfer_product_e2e")
        if product.get("synthetic") is True or product.get("offline_only") is True:
            reasons.append("synthetic or offline-only file-transfer evidence cannot close this gate")
        directions = product.get("directions") if isinstance(product.get("directions"), dict) else {}
        android_to_macos = directions.get("android_to_macos_file_transfer")
        macos_to_android = directions.get("macos_to_android_file_transfer")
        transfer_ids: dict[str, str] = {}
        digests: dict[str, str] = {}
        file_names: dict[str, str] = {}
        if retained_artifact_paths is None:
            retained_artifact_paths = {}
        if isinstance(android_to_macos, dict):
            reasons.extend(
                _direction_reasons(
                    android_to_macos,
                    "android_to_macos_file_transfer",
                    evidence_dir,
                    retained_artifact_paths,
                )
            )
            transport = android_to_macos.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"android_to_macos_file_transfer.transport {transport} is not ready")
            transfer_id = android_to_macos.get("transfer_id_hex")
            if isinstance(transfer_id, str) and re.fullmatch(r"[0-9a-fA-F]{32}", transfer_id):
                transfer_ids["android_to_macos_file_transfer"] = transfer_id.lower()
            digest = android_to_macos.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                digests["android_to_macos_file_transfer"] = digest.lower()
            file_name = android_to_macos.get("file_name")
            if isinstance(file_name, str) and file_name.strip():
                file_names["android_to_macos_file_transfer"] = file_name.strip()
        else:
            reasons.append("missing android_to_macos_file_transfer direction evidence")
        if isinstance(macos_to_android, dict):
            reasons.extend(
                _direction_reasons(
                    macos_to_android,
                    "macos_to_android_file_transfer",
                    evidence_dir,
                    retained_artifact_paths,
                )
            )
            transport = macos_to_android.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"macos_to_android_file_transfer.transport {transport} is not ready")
            transfer_id = macos_to_android.get("transfer_id_hex")
            if isinstance(transfer_id, str) and re.fullmatch(r"[0-9a-fA-F]{32}", transfer_id):
                transfer_ids["macos_to_android_file_transfer"] = transfer_id.lower()
            digest = macos_to_android.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                digests["macos_to_android_file_transfer"] = digest.lower()
            file_name = macos_to_android.get("file_name")
            if isinstance(file_name, str) and file_name.strip():
                file_names["macos_to_android_file_transfer"] = file_name.strip()
        else:
            reasons.append("missing macos_to_android_file_transfer direction evidence")
        if (
            transfer_ids.get("android_to_macos_file_transfer")
            and transfer_ids.get("android_to_macos_file_transfer")
            == transfer_ids.get("macos_to_android_file_transfer")
        ):
            reasons.append("direction transfer IDs must be distinct so one file exchange cannot satisfy both directions")
        if (
            digests.get("android_to_macos_file_transfer")
            and digests.get("android_to_macos_file_transfer")
            == digests.get("macos_to_android_file_transfer")
        ):
            reasons.append("direction SHA-256 digests must be distinct so one file payload cannot satisfy both directions")
        if (
            file_names.get("android_to_macos_file_transfer")
            and file_names.get("android_to_macos_file_transfer")
            == file_names.get("macos_to_android_file_transfer")
        ):
            reasons.append("direction file names must be distinct so one file exchange cannot satisfy both directions")
    return _gate("bidirectional_product_e2e", PASS if not reasons else BLOCKED, reasons, evidence)


def _cancel_cleanup_gate(
    product: dict[str, Any] | None,
    evidence_dir: Path | None,
    retained_artifact_paths: dict[Path | str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    evidence = ["file-transfer-product-e2e.json"] if product is not None else []
    if product is None:
        reasons.append("missing product E2E evidence: file-transfer-product-e2e.json")
    else:
        cancel_cleanup = product.get("cancel_cleanup")
        if not isinstance(cancel_cleanup, dict):
            reasons.append("missing cancel_cleanup evidence")
        else:
            required_true = (
                "cancel_requested",
                "cancel_acknowledged",
                "partial_file_removed_or_quarantined",
                "sender_state_cleared",
                "receiver_state_cleared",
            )
            reasons.extend(
                f"cancel_cleanup.{field} must be true"
                for field in required_true
                if cancel_cleanup.get(field) is not True
            )
            reasons.extend(
                _retained_artifact_reasons(
                    cancel_cleanup,
                    "cancel_cleanup",
                    REQUIRED_CANCEL_ARTIFACT_ROLES,
                    evidence_dir,
                    retained_artifact_paths,
                )
            )
    return _gate("cancel_cleanup", PASS if not reasons else BLOCKED, reasons, evidence)


def _device_gate(usb: dict[str, Any] | None, lan: dict[str, Any] | None, product: dict[str, Any] | None) -> dict[str, Any]:
    if product and isinstance(product.get("device"), dict):
        identity = _device_identity(product.get("device"))
        missing_identity = False
    elif usb and isinstance(usb.get("device"), dict):
        identity = _device_identity(usb.get("device"))
        missing_identity = False
    elif lan and isinstance(lan.get("android_device"), dict):
        identity = _device_identity(lan.get("android_device"))
        missing_identity = False
    else:
        identity = dict(DEFAULT_DEVICE_IDENTITY)
        missing_identity = True
    reasons = _device_identity_failures(identity)
    if missing_identity:
        reasons.append("missing real P0110 device identity evidence from USB, trusted-LAN, or product evidence")
    status = BLOCKED if missing_identity else (FAIL if reasons else PASS)
    return {
        "name": "device_identity",
        "status": status,
        "reasons": reasons,
        "evidence": [],
        "identity": sanitize_value(identity),
    }


def derive_gate(
    *,
    host_readiness: Path | None = None,
    usb_preflight: Path | None = None,
    trusted_lan_preflight: Path | None = None,
    android_file_transfer_instrumentation_log: Path | None = None,
    product_e2e: Path | None = None,
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
    retained_artifact_paths: dict[Path | str, tuple[str, str]] = {}
    gates = [
        _device_gate(usb, lan, product),
        _host_gate(host, host_missing),
        usb_gate,
        lan_gate,
        _transport_gate(usb_gate, lan_gate),
        _android_file_transfer_gate(android_file_transfer_instrumentation_log),
        _product_e2e_gate(product, product_missing, available_transports, evidence_dir, retained_artifact_paths),
        _cancel_cleanup_gate(product, evidence_dir, retained_artifact_paths),
    ]
    required_gate_names = {
        "device_identity",
        "host_readiness",
        "real_transport_ready",
        "android_file_transfer_smoke",
        "bidirectional_product_e2e",
        "cancel_cleanup",
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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "result": verdict,
        "gate_closed": verdict == PASS,
        "can_close_file_transfer_android_smoke_gate": verdict == PASS,
        "serial_label": sanitize_text(serial_label),
        "checks": sanitize_value(gates),
        "blockers": sanitize_value(blockers),
        "not_proven": [
            item
            for item in (
                "Android -> macOS single-file transfer over Protocol v1 USB/LAN" if verdict != PASS else "",
                "macOS -> Android single-file transfer over Protocol v1 USB/LAN" if verdict != PASS else "",
                "receiver approval, verified session ID and epoch, distinct verified 16-byte transfer IDs, "
                "observed progress, exact file endpoints, retained destination-file bytes that match the "
                "declared byte length and SHA-256, cancel cleanup, and end-to-end SHA-256 on retained "
                "product evidence" if verdict != PASS else "",
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
            "a current Android file-transfer smoke log, and retained bidirectional product E2E evidence "
            "showing file offer/request/content packets, source file read, explicit user action, receiver "
            "approval, remote file write, verified session ID and session epoch, distinct transfer IDs, "
            "distinct file names, distinct SHA-256 payload digests, observed progress, exact file endpoints, "
            "retained remote-file bytes whose size and SHA-256 match the direction manifest, "
            "retained non-empty product artifacts with exact required roles, no repeated roles, "
            "distinct files per role, and cancel/cleanup behavior. "
            "Offline or synthetic coverage alone remains readiness evidence."
        ),
    }


def _failure_report(error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verdict": BLOCKED,
        "result": BLOCKED,
        "gate_closed": False,
        "can_close_file_transfer_android_smoke_gate": False,
        "checks": [_gate("gate_input", BLOCKED, [error])],
        "blockers": [sanitize_text(error)],
        "not_proven": ["file-transfer smoke evidence could not be evaluated"],
        "safety": {
            "offline_tests_do_not_close_gate": True,
            "synthetic_evidence_do_not_close_gate": True,
            "public_output_sanitized": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-readiness", type=Path)
    parser.add_argument("--usb-preflight", type=Path)
    parser.add_argument("--trusted-lan-preflight", type=Path)
    parser.add_argument("--android-file-transfer-instrumentation-log", type=Path)
    parser.add_argument("--product-e2e", type=Path)
    parser.add_argument("--serial", help="Raw serial accepted for caller compatibility; never emitted")
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
            android_file_transfer_instrumentation_log=args.android_file_transfer_instrumentation_log,
            product_e2e=args.product_e2e,
            serial_label=args.serial_label,
        )
    except (FileTransferAndroidSmokeGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(str(error))
    _write_json(args.output, report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    if report.get("verdict") == PASS:
        return 0
    return 2 if not args.require_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
