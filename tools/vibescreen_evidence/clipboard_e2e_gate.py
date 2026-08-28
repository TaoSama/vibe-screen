"""Evaluate Android ClipboardManager <-> macOS NSPasteboard E2E evidence.

The gate is intentionally fail-closed. USB/LAN preflight, Android-local
ClipboardManager instrumentation, JVM tests, protocol fixtures, and Host
self-tests are useful readiness evidence, but they cannot close the real
system-clipboard E2E gate without retained product evidence for both transfer
directions.
"""

from __future__ import annotations

import argparse
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
SAFE_SERIAL_LABEL = "REDACTED_P0110_USB_SERIAL"
TCC_PATH_COMPONENT = "Application" + r"\s+" + "Support/com" + r"\.apple\." + "TCC"
TCC_BUNDLE_COMPONENT = "com" + r"\.apple\." + "TCC"
TCC_DATABASE_COMPONENT = "TCC" + r"\.db"
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"EP[0-9A-Z]{14,}", re.IGNORECASE),
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
    if pattern_text.startswith("ep"):
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
        if usb.get("result") != "pass" or claims.get("can_start_usb_smoke") is not True:
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
        if lan.get("result") != "pass":
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
    text = sanitize_text(log_path.read_text(encoding="utf-8", errors="replace"))
    passed = (
        ("OK (" in text or ("Finished " in text and " tests on " in text and "BUILD SUCCESSFUL" in text))
        and "FAILURES!!!" not in text
        and "BUILD FAILED" not in text
        and "Tests run:" not in text
    )
    reasons = [] if passed else ["Android ClipboardManager instrumentation log does not show an OK result"]
    return _gate("android_clipboardmanager_smoke", PASS if passed else BLOCKED, reasons, [log_path.name])


def _direction_reasons(direction: dict[str, Any], label: str) -> list[str]:
    required_true = (
        "protocol_v1_session",
        "system_source_clipboard_read",
        "explicit_user_action",
        "remote_system_clipboard_write",
        "final_marker_match",
    )
    reasons = [
        f"{label}.{field} must be true"
        for field in required_true
        if direction.get(field) is not True
    ]
    marker = direction.get("marker")
    if not isinstance(marker, str) or len(marker.strip()) < 8:
        reasons.append(f"{label}.marker must identify the transferred text marker")
    transport = direction.get("transport")
    if transport not in {"usb", "trusted_lan"}:
        reasons.append(f"{label}.transport must be usb or trusted_lan")
    return reasons


def _product_e2e_gate(
    product: dict[str, Any] | None,
    missing: Sequence[str],
    available_transports: set[str],
) -> dict[str, Any]:
    reasons = list(missing)
    evidence = ["product-e2e.json"] if product is not None else []
    if product is not None:
        if product.get("kind") != "android_macos_clipboard_product_e2e":
            reasons.append("product evidence kind must be android_macos_clipboard_product_e2e")
        if product.get("synthetic") is True or product.get("offline_only") is True:
            reasons.append("synthetic or offline-only clipboard evidence cannot close this gate")
        directions = product.get("directions") if isinstance(product.get("directions"), dict) else {}
        android_to_macos = directions.get("android_clipboardmanager_to_macos_nspasteboard")
        macos_to_android = directions.get("macos_nspasteboard_to_android_clipboardmanager")
        if isinstance(android_to_macos, dict):
            reasons.extend(_direction_reasons(android_to_macos, "android_clipboardmanager_to_macos_nspasteboard"))
            transport = android_to_macos.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"android_clipboardmanager_to_macos_nspasteboard.transport {transport} is not ready")
        else:
            reasons.append("missing android_clipboardmanager_to_macos_nspasteboard direction evidence")
        if isinstance(macos_to_android, dict):
            reasons.extend(_direction_reasons(macos_to_android, "macos_nspasteboard_to_android_clipboardmanager"))
            transport = macos_to_android.get("transport")
            if transport in {"usb", "trusted_lan"} and transport not in available_transports:
                reasons.append(f"macos_nspasteboard_to_android_clipboardmanager.transport {transport} is not ready")
        else:
            reasons.append("missing macos_nspasteboard_to_android_clipboardmanager direction evidence")
    return _gate("bidirectional_product_e2e", PASS if not reasons else BLOCKED, reasons, evidence)


def _device_gate(usb: dict[str, Any] | None, lan: dict[str, Any] | None, product: dict[str, Any] | None) -> dict[str, Any]:
    if product and isinstance(product.get("device"), dict):
        identity = _device_identity(product.get("device"))
    elif usb and isinstance(usb.get("device"), dict):
        identity = _device_identity(usb.get("device"))
    elif lan and isinstance(lan.get("android_device"), dict):
        identity = _device_identity(lan.get("android_device"))
    else:
        identity = dict(DEFAULT_DEVICE_IDENTITY)
    reasons = _device_identity_failures(identity)
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
    serial_label: str = SAFE_SERIAL_LABEL,
) -> dict[str, Any]:
    host, host_missing = _load_optional(host_readiness, "host readiness")
    usb, usb_missing = _load_optional(usb_preflight, "USB preflight")
    lan, lan_missing = _load_optional(trusted_lan_preflight, "trusted-LAN preflight")
    product, product_missing = _load_optional(product_e2e, "product E2E evidence")

    usb_gate = _usb_gate(usb, usb_missing)
    lan_gate = _lan_gate(lan, lan_missing)
    available_transports = {
        transport
        for transport, gate in (("usb", usb_gate), ("trusted_lan", lan_gate))
        if gate["status"] == PASS
    }
    gates = [
        _device_gate(usb, lan, product),
        _host_gate(host, host_missing),
        usb_gate,
        lan_gate,
        _transport_gate(usb_gate, lan_gate),
        _android_clipboard_gate(android_clipboard_instrumentation_log),
        _product_e2e_gate(product, product_missing, available_transports),
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
            "Protocol v1 session ownership, and final marker match. Offline or synthetic coverage alone remains readiness evidence."
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
