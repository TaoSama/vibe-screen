"""Validate macOS login-startup, headless, and recovery evidence.

The checker is intentionally passive. It consumes a retained evidence JSON
document from a real macOS Host run and returns blocked until the integration
artifacts prove login launch, automatic startup, capturable headless display
state, unattended recovery, window restoration, and the operator remote-access
boundary. It does not reboot the Mac, alter Login Items, grant TCC, start the
Host, or touch Android devices.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from . import SCHEMA_VERSION

KIND = "macos_startup_recovery_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"

REQUIRED_RETRY_DELAYS = [1, 2, 4, 8, 16, 30, 30, 30]
SUPPORTED_DISPLAY_TOPOLOGIES = {
    "physical",
    "dummy_or_headless",
    "screen_sharing",
}
SUPPORTED_REMOTE_ACCESS = {
    "physical_console",
    "screen_sharing",
    "remote_management",
    "mdm",
}
P0110_IDENTITY_MARKERS = {"nubia", "p0110", "pacific"}


class StartupRecoveryGateError(ValueError):
    """Raised when the evidence document cannot be evaluated."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StartupRecoveryGateError(f"failed to read evidence {path}: {error}") from error
    if not isinstance(document, dict):
        raise StartupRecoveryGateError(f"evidence must be a JSON object: {path}")
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _artifact(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _gate(name: str, status: str, *, evidence: Sequence[str] = (), reasons: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "passed": status == PASS,
        "evidence": list(evidence),
        "reasons": list(reasons),
    }


def _require_true(value: Any, field: str, reasons: list[str]) -> None:
    observed = _bool(value)
    if observed is not True:
        reasons.append(f"{field} must be true")


def _require_false(value: Any, field: str, reasons: list[str]) -> None:
    observed = _bool(value)
    if observed is not False:
        reasons.append(f"{field} must be false")


def _artifact_evidence(section: Mapping[str, Any], *fields: str) -> list[str]:
    evidence: list[str] = []
    for field in fields:
        value = section.get(field)
        if _artifact(value):
            evidence.append(str(value))
    return evidence


def _artifact_path(root: Path, relative_path: str) -> Path | None:
    path = Path(relative_path)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    resolved_root = root.resolve()
    resolved_path = (resolved_root / path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_path


def _artifact_is_non_empty(root: Path, relative_path: str) -> bool:
    path = _artifact_path(root, relative_path)
    if path is None:
        return False
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _validate_gate_artifacts(gate: dict[str, Any], root: Path | None) -> dict[str, Any]:
    if root is None:
        return gate
    reasons = list(gate["reasons"])
    for relative in gate["evidence"]:
        if not _artifact_is_non_empty(root, relative):
            reasons.append(f"evidence artifact {relative!r} must exist under the evidence root and be non-empty")
    if reasons and gate["status"] == PASS:
        status = BLOCKED
    else:
        status = gate["status"]
    return {**gate, "status": status, "passed": status == PASS, "reasons": reasons}


def _status_for_missing_or_failed(reasons: Sequence[str], *, failed: bool = False) -> str:
    if not reasons:
        return PASS
    return FAIL if failed else BLOCKED


def _host_identity_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    host = _mapping(document.get("mac_host"))
    reasons: list[str] = []
    for field in ("model", "architecture", "macos_version", "macos_build", "host_bundle_identifier"):
        if _string(host.get(field)) is None:
            reasons.append(f"mac_host.{field} is required")
    signing = _string(host.get("host_signing"))
    if signing != "identity_signed":
        reasons.append("mac_host.host_signing must be identity_signed")
    if _string(host.get("host_cdhash")) is None:
        reasons.append("mac_host.host_cdhash is required")
    if _string(host.get("host_binary_sha256")) is None:
        reasons.append("mac_host.host_binary_sha256 is required")
    if _string(host.get("screen_recording_permission")) != "granted":
        reasons.append("mac_host.screen_recording_permission must be granted")
    if _string(host.get("accessibility_permission")) != "granted":
        reasons.append("mac_host.accessibility_permission must be granted for window recovery")
    return _gate(
        "host_identity_permissions",
        _status_for_missing_or_failed(reasons),
        evidence=_artifact_evidence(host, "signing_report", "permission_report", "host_log"),
        reasons=reasons,
    )


def _login_item_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    login = _mapping(document.get("login_item"))
    reasons: list[str] = []
    status = _string(login.get("status"))
    if status != "enabled":
        reasons.append("login_item.status must be enabled")
    _require_false(login.get("requires_approval"), "login_item.requires_approval", reasons)
    _require_true(login.get("reboot_or_logout_login_performed"), "login_item.reboot_or_logout_login_performed", reasons)
    _require_true(login.get("login_launch_observed"), "login_item.login_launch_observed", reasons)
    if login.get("manual_launch_used") is True:
        reasons.append("manual Finder/Dock launch cannot be counted as login-startup evidence")
    failed = login.get("manual_launch_used") is True
    return _gate(
        "login_item_registration_and_launch",
        _status_for_missing_or_failed(reasons, failed=failed),
        evidence=_artifact_evidence(login, "system_settings_artifact", "launch_log"),
        reasons=reasons,
    )


def _automatic_startup_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    startup = _mapping(document.get("automatic_startup"))
    reasons: list[str] = []
    _require_true(startup.get("auto_start_enabled"), "automatic_startup.auto_start_enabled", reasons)
    if _string(startup.get("startup_mode")) not in {"usb", "wireless", "lan"}:
        reasons.append("automatic_startup.startup_mode must be usb, wireless, or lan")
    _require_true(startup.get("onboarding_completed"), "automatic_startup.onboarding_completed", reasons)
    _require_true(startup.get("first_server_start_observed"), "automatic_startup.first_server_start_observed", reasons)
    _require_true(startup.get("client_render_observed"), "automatic_startup.client_render_observed", reasons)
    return _gate(
        "automatic_startup_streaming",
        _status_for_missing_or_failed(reasons),
        evidence=_artifact_evidence(startup, "startup_log", "client_render_artifact"),
        reasons=reasons,
    )


def _display_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    display = _mapping(document.get("display"))
    reasons: list[str] = []
    topology = _string(display.get("topology"))
    if topology not in SUPPORTED_DISPLAY_TOPOLOGIES:
        reasons.append(
            "display.topology must be physical, dummy_or_headless, or screen_sharing"
        )
    _require_true(display.get("capturable_display_observed"), "display.capturable_display_observed", reasons)
    _require_true(display.get("first_frame_observed"), "display.first_frame_observed", reasons)
    if _string(display.get("display_uuid")) is None:
        reasons.append("display.display_uuid is required")
    dimensions = _mapping(display.get("dimensions"))
    for field in ("logical_width", "logical_height", "physical_width", "physical_height"):
        value = dimensions.get(field)
        if not isinstance(value, int) or value <= 0:
            reasons.append(f"display.dimensions.{field} must be a positive integer")
    headless_topology = topology in {"dummy_or_headless", "screen_sharing"}
    if headless_topology and display.get("claims_headless_from_attached_monitor") is True:
        reasons.append("an attached monitor cannot be relabeled as dummy/headless evidence")
    failed = display.get("claims_headless_from_attached_monitor") is True
    return _gate(
        "headless_or_dummy_display_capture",
        _status_for_missing_or_failed(reasons, failed=failed),
        evidence=_artifact_evidence(display, "display_report", "first_frame_artifact"),
        reasons=reasons,
    )


def _unattended_recovery_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    recovery = _mapping(document.get("unattended_recovery"))
    reasons: list[str] = []
    if _string(recovery.get("trigger")) is None:
        reasons.append("unattended_recovery.trigger is required")
    _require_true(recovery.get("observed"), "unattended_recovery.observed", reasons)
    delays = recovery.get("retry_delays_seconds")
    if delays != REQUIRED_RETRY_DELAYS:
        reasons.append("unattended_recovery.retry_delays_seconds must match the bounded 1,2,4,8,16,30,30,30 policy")
    _require_false(recovery.get("full_speed_loop_observed"), "unattended_recovery.full_speed_loop_observed", reasons)
    if recovery.get("restart_succeeded") is not True and recovery.get("bounded_exhaustion_observed") is not True:
        reasons.append("unattended_recovery must record restart_succeeded or bounded_exhaustion_observed")
    _require_true(recovery.get("logs_retained"), "unattended_recovery.logs_retained", reasons)
    failed = recovery.get("full_speed_loop_observed") is True
    return _gate(
        "unattended_listener_recovery",
        _status_for_missing_or_failed(reasons, failed=failed),
        evidence=_artifact_evidence(recovery, "recovery_log"),
        reasons=reasons,
    )


def _window_recovery_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    window = _mapping(document.get("window_recovery"))
    reasons: list[str] = []
    _require_true(window.get("move_observed"), "window_recovery.move_observed", reasons)
    _require_true(window.get("disconnect_or_failure_trigger_observed"), "window_recovery.disconnect_or_failure_trigger_observed", reasons)
    _require_true(window.get("restored_observed"), "window_recovery.restored_observed", reasons)
    if _mapping(window.get("original_frame")) == {}:
        reasons.append("window_recovery.original_frame is required")
    if _mapping(window.get("restored_frame")) == {}:
        reasons.append("window_recovery.restored_frame is required")
    if window.get("accessibility_error_observed") is True:
        reasons.append("window recovery cannot pass with Accessibility errors")
    failed = window.get("accessibility_error_observed") is True
    return _gate(
        "window_restore_on_disconnect_or_failure",
        _status_for_missing_or_failed(reasons, failed=failed),
        evidence=_artifact_evidence(window, "window_log", "before_artifact", "after_artifact"),
        reasons=reasons,
    )


def _remote_access_gate(document: Mapping[str, Any]) -> dict[str, Any]:
    remote = _mapping(document.get("remote_access"))
    reasons: list[str] = []
    if _string(remote.get("method")) not in SUPPORTED_REMOTE_ACCESS:
        reasons.append("remote_access.method must describe physical console, Screen Sharing, Remote Management, or MDM access")
    _require_true(remote.get("operator_intervention_path_verified"), "remote_access.operator_intervention_path_verified", reasons)
    _require_true(remote.get("filevault_or_first_login_blocker_absent"), "remote_access.filevault_or_first_login_blocker_absent", reasons)
    _require_false(remote.get("requires_unavailable_local_intervention"), "remote_access.requires_unavailable_local_intervention", reasons)
    return _gate(
        "remote_admin_access_boundary",
        _status_for_missing_or_failed(reasons),
        evidence=_artifact_evidence(remote, "access_artifact"),
        reasons=reasons,
    )


def _android_identity_gate(document: Mapping[str, Any]) -> dict[str, Any] | None:
    android = document.get("android_device")
    if android is None:
        return None
    android = _mapping(android)
    evidence = _artifact_evidence(android, "device_info")
    reasons: list[str] = []
    labels = {str(android.get(field, "")).lower() for field in ("manufacturer", "model", "codename")}
    has_p0110_identity = bool(labels & P0110_IDENTITY_MARKERS)
    if has_p0110_identity:
        expected = {
            "manufacturer": "nubia",
            "model": "P0110",
            "codename": "pacific",
            "android_release": "16",
            "sdk": "36",
        }
        for field, expected_value in expected.items():
            if str(android.get(field, "")) != expected_value:
                reasons.append(f"android_device.{field} must be {expected_value!r} for Nubia P0110/pacific evidence")
    if has_p0110_identity and ({"xiaomi", "fuxi"} & labels):
        reasons.append("Nubia P0110 evidence must not be relabeled as Xiaomi/fuxi")
    return _gate(
        "android_identity_label_guard",
        FAIL if reasons else PASS,
        evidence=evidence,
        reasons=reasons,
    )


def derive_gate(evidence: Mapping[str, Any], *, evidence_root: Path | None = None) -> dict[str, Any]:
    gates = [
        _host_identity_gate(evidence),
        _login_item_gate(evidence),
        _automatic_startup_gate(evidence),
        _display_gate(evidence),
        _unattended_recovery_gate(evidence),
        _window_recovery_gate(evidence),
        _remote_access_gate(evidence),
    ]
    android_gate = _android_identity_gate(evidence)
    if android_gate is not None:
        gates.append(android_gate)
    gates = [_validate_gate_artifacts(gate, evidence_root) for gate in gates]

    statuses = {gate["status"] for gate in gates}
    if FAIL in statuses:
        verdict = FAIL
    elif BLOCKED in statuses:
        verdict = BLOCKED
    elif INSUFFICIENT in statuses:
        verdict = INSUFFICIENT
    else:
        verdict = PASS

    open_reasons = [
        f"{gate['name']}: {reason}"
        for gate in gates
        if gate["status"] != PASS
        for reason in gate["reasons"]
    ]
    display_topology = _string(_mapping(evidence.get("display")).get("topology"))
    headless_topology = display_topology in {"dummy_or_headless", "screen_sharing"}
    mac_host = _mapping(evidence.get("mac_host"))
    is_mac_mini = _string(mac_host.get("model")) == "Mac mini"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "can_close_login_headless_gate": verdict == PASS,
        "can_claim_headless_mac_mini_operation": verdict == PASS and headless_topology and is_mac_mini,
        "source_evidence": {
            "kind": evidence.get("kind"),
            "run_id": evidence.get("run_id"),
            "source_commit": evidence.get("source_commit"),
        },
        "required_boundaries": [
            "identity-signed Host with current Screen Recording and Accessibility grants",
            "macOS login item enabled and not awaiting System Settings approval",
            "reboot or logout/login launch, not manual Finder or Dock launch",
            "automatic startup produces a real client-rendered stream",
            "capturable physical, dummy/headless, or Screen Sharing display with first frame",
            "bounded unattended recovery logs for the declared failure trigger",
            "real window move and restore after disconnect or failure",
            "remote or local administrator path for FileVault, first-login, TCC, and display intervention",
        ],
        "checks": gates,
        "open_reasons": open_reasons,
        "interpretation": (
            "This report is a passive Phase 2 login-startup/headless Mac mini owner gate. "
            "A pass requires retained real-macOS integration evidence for every boundary; "
            "blocked readiness or offline policy tests must keep can_close_login_headless_gate=false."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        evidence = _read_json(arguments.evidence)
        report = derive_gate(evidence, evidence_root=arguments.evidence_root or arguments.evidence.parent)
        _write_json(arguments.output, report)
    except (OSError, StartupRecoveryGateError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["verdict"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
