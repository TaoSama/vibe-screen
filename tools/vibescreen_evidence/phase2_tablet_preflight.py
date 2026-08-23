"""Preflight a Phase 2 physical tablet evidence bundle.

This checker sits above the eight-hour soak gate. The soak gate evaluates the
continuous telemetry window; this preflight verifies that the evidence bundle is
for a real 8-9 inch tablet and that the hardware/UI acceptance artifacts needed
by the Phase 2 runbook are present before anyone treats the bundle as a
tablet-productization result.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION

PREFLIGHT_KIND = "phase2_tablet_acceptance_preflight"
TABLET_DEVICE_CLASS = "physical_8_9_inch_tablet"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"
MISSING = "missing"

DEFAULT_PORTRAIT_SCREENSHOTS = (
    "screenshots/sustained-use-portrait.png",
    "screenshots/portrait.png",
)
DEFAULT_LANDSCAPE_SCREENSHOTS = (
    "screenshots/sustained-use-landscape.png",
    "screenshots/landscape.png",
)
DEFAULT_STYLUS_EVIDENCE = (
    "stylus-evidence.json",
    "stylus/stylus-evidence.json",
)
DEFAULT_KEYBOARD_EVIDENCE = (
    "hardware-keyboard-summary.json",
    "hardware-keyboard-evidence.json",
    "keyboard/hardware-keyboard-summary.json",
    "keyboard/hardware-keyboard-evidence.json",
    "keyboard-evidence.json",
)
DEFAULT_RECOVERY_EVIDENCE = (
    "recovery-evidence.json",
    "recovery/recovery-evidence.json",
)
DEFAULT_ORIENTATION_EVIDENCE = (
    "orientation-evidence.json",
    "screenshots/orientation-evidence.json",
)

REQUIRED_RAW_ARTIFACTS = (
    "README.md",
    "phase2-tablet-manifest.json",
    "device-info.json",
    "device.txt",
    "host.txt",
    "build.txt",
    "apk-sha256.txt",
    "adb-battery-before.txt",
    "adb-battery-after.txt",
    "adb-power-before.txt",
    "adb-power-after.txt",
    "thermal-before.txt",
    "thermal-after.txt",
    "thermal-before.err",
    "thermal-after.err",
    "raw-logcat.txt",
    "host.log",
    "reconnects.log",
    "frame-drops.log",
    "decoder-telemetry.jsonl",
)

REQUIRED_RAW_ARTIFACT_GROUPS = {
    "soak-8h/samples.jsonl": ("soak-8h/samples.jsonl", "samples.jsonl"),
    "soak-8h/summary.json": ("soak-8h/summary.json", "summary.json"),
    "soak-8h/host-telemetry.jsonl": ("soak-8h/host-telemetry.jsonl", "host-telemetry.jsonl"),
}

EMPTY_ALLOWED_ARTIFACTS = {
    "thermal-before.err",
    "thermal-after.err",
}

REQUIRED_RECOVERY_SCENARIOS = (
    "foreground_background",
    "transport_reconnect",
    "login_startup_or_headless",
)

KEYBOARD_SUMMARY_PASS_FIELDS = (
    "physical_keyboard_attached",
    "android_keyboard_source_observed",
    "protocol_keyboard_capability_negotiated",
    "protocol_usb_hid_modifier_capability_negotiated",
    "android_production_forwarding_observed",
    "host_key_injection_observed",
    "key_press_release_observed",
    "shortcut_combo_observed",
    "modifier_release_no_leak_observed",
    "visible_mac_result_observed",
    "host_logs_retained",
    "android_logs_retained",
)


class PreflightError(RuntimeError):
    """Raised when the preflight cannot read or write its own artifacts."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"failed to read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must be a JSON object: {path}")
    return value


def _read_optional_json(path: Path | None, label: str) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, f"missing {label}"
    try:
        return _read_json(path, label), None
    except PreflightError as error:
        return None, str(error)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _existing_path(root: Path, candidates: Sequence[str]) -> Path | None:
    for relative in candidates:
        path = root / relative
        if path.exists():
            return path
    return None


def _non_empty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted):
            return converted
    return None


def _gate(name: str, status: str, *, evidence: Sequence[str] = (), reasons: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "evidence": list(evidence),
        "reasons": list(reasons),
    }


def _status_from_json(document: dict[str, Any]) -> str | None:
    value = document.get("status", document.get("verdict"))
    return value if isinstance(value, str) else None


def _scenario_status(document: dict[str, Any], scenario: str) -> str | None:
    scenarios = document.get("scenarios")
    if isinstance(scenarios, dict):
        value = scenarios.get(scenario)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return _status_from_json(value)
    if isinstance(scenarios, list):
        for item in scenarios:
            if not isinstance(item, dict):
                continue
            if item.get("name") == scenario or item.get("scenario") == scenario:
                return _status_from_json(item)
    value = document.get(scenario)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _status_from_json(value)
    return None


def _device_identity(document: dict[str, Any]) -> dict[str, Any]:
    device = document.get("device")
    if not isinstance(device, dict):
        return {}
    identity = dict(device)
    if identity.get("codename") in (None, "") and identity.get("device") is not None:
        identity["codename"] = identity["device"]
    return identity


def _manifest_identity(document: dict[str, Any]) -> dict[str, Any]:
    device = document.get("device")
    if not isinstance(device, dict):
        return {}
    identity = device.get("identity")
    return identity if isinstance(identity, dict) else {}


def _identity_mismatches(manifest: dict[str, Any], device_info: dict[str, Any]) -> list[str]:
    manifest_identity = _manifest_identity(manifest)
    device_identity = _device_identity(device_info)
    checks = {
        "manufacturer": "manufacturer",
        "model": "model",
        "codename": "codename",
        "android_release": "android_release",
        "adb_serial": "adb_serial",
    }
    mismatches: list[str] = []
    for manifest_key, device_key in checks.items():
        manifest_value = manifest_identity.get(manifest_key)
        device_value = device_identity.get(device_key)
        if manifest_value is not None and device_value is not None and str(manifest_value) != str(device_value):
            mismatches.append(
                f"manifest {manifest_key}={manifest_value!r} does not match device-info {device_key}={device_value!r}"
            )
    return mismatches


def _physical_tablet_gate(
    manifest: dict[str, Any] | None,
    device_info: dict[str, Any] | None,
    *,
    min_inches: float,
    max_inches: float,
) -> dict[str, Any]:
    evidence = ["phase2-tablet-manifest.json"]
    if device_info is not None:
        evidence.append("device-info.json")
    if manifest is None:
        return _gate("physical_8_9_inch_tablet", MISSING, reasons=["phase2-tablet-manifest.json is missing or unreadable"])
    device = manifest.get("device") if isinstance(manifest.get("device"), dict) else {}
    device_class = device.get("device_class")
    size = _finite_float(device.get("tablet_size_inches"))
    reasons: list[str] = []
    if device_class != TABLET_DEVICE_CLASS:
        reasons.append(
            f"device_class is {device_class!r}; Phase 2 tablet acceptance requires {TABLET_DEVICE_CLASS!r}"
        )
        return _gate("physical_8_9_inch_tablet", BLOCKED, evidence=evidence, reasons=reasons)
    if size is None:
        reasons.append("tablet_size_inches is required for a physical tablet run")
    elif not (min_inches <= size <= max_inches):
        reasons.append(f"tablet_size_inches={size:g} is outside the accepted {min_inches:g}-{max_inches:g} inch range")
    if device_info is None:
        reasons.append("device-info.json is missing or unreadable")
    else:
        reasons.extend(_identity_mismatches(manifest, device_info))
    return _gate("physical_8_9_inch_tablet", PASS if not reasons else INSUFFICIENT, evidence=evidence, reasons=reasons)


def _raw_artifacts_gate(root: Path) -> dict[str, Any]:
    missing = [
        relative
        for relative in REQUIRED_RAW_ARTIFACTS
        if not (
            (root / relative).exists()
            if relative in EMPTY_ALLOWED_ARTIFACTS
            else _non_empty(root / relative)
        )
    ]
    evidence = [relative for relative in REQUIRED_RAW_ARTIFACTS if relative not in missing]
    for label, candidates in REQUIRED_RAW_ARTIFACT_GROUPS.items():
        matched = _existing_path(root, candidates)
        if matched is None or not _non_empty(matched):
            missing.append(label)
        else:
            relative = _relative(root, matched)
            if relative is not None:
                evidence.append(relative)
    status = PASS if not missing else MISSING
    reasons = ["missing or empty required artifact: " + relative for relative in missing]
    return _gate("raw_evidence_bundle", status, evidence=evidence, reasons=reasons)


def _orientation_gate(root: Path) -> dict[str, Any]:
    portrait = _existing_path(root, DEFAULT_PORTRAIT_SCREENSHOTS)
    landscape = _existing_path(root, DEFAULT_LANDSCAPE_SCREENSHOTS)
    orientation = _existing_path(root, DEFAULT_ORIENTATION_EVIDENCE)
    evidence = [
        item
        for item in (_relative(root, portrait), _relative(root, landscape), _relative(root, orientation))
        if item is not None
    ]
    reasons: list[str] = []
    if portrait is None or not _non_empty(portrait):
        reasons.append("missing non-empty portrait sustained-use/settings screenshot")
    if landscape is None or not _non_empty(landscape):
        reasons.append("missing non-empty landscape sustained-use/settings screenshot")
    if orientation is None:
        reasons.append("missing orientation-evidence.json for rotation and touch-mapping confirmation")
    else:
        document, error = _read_optional_json(orientation, "orientation evidence")
        if error is not None:
            reasons.append(error)
        elif _status_from_json(document or {}) != PASS:
            reasons.append("orientation-evidence.json does not report status/verdict pass")
    return _gate("portrait_landscape_ui", PASS if not reasons else MISSING, evidence=evidence, reasons=reasons)


def _stylus_gate(root: Path, explicit_path: Path | None) -> dict[str, Any]:
    path = explicit_path or _existing_path(root, DEFAULT_STYLUS_EVIDENCE)
    if path is None:
        matches = sorted(root.glob("**/stylus-evidence.json"))
        path = matches[0] if matches else None
    document, error = _read_optional_json(path, "stylus evidence")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("physical_stylus", MISSING, evidence=[item for item in evidence if item], reasons=[error])
    status = _status_from_json(document or {})
    observed = bool((document or {}).get("observed_physical_drawing"))
    if status == PASS and observed:
        return _gate("physical_stylus", PASS, evidence=[item for item in evidence if item])
    return _gate(
        "physical_stylus",
        BLOCKED if status and status.startswith("blocked") else INSUFFICIENT,
        evidence=[item for item in evidence if item],
        reasons=["stylus evidence must report pass with observed_physical_drawing=true"],
    )


def _keyboard_gate(root: Path, explicit_path: Path | None) -> dict[str, Any]:
    path = explicit_path or _existing_path(root, DEFAULT_KEYBOARD_EVIDENCE)
    document, error = _read_optional_json(path, "hardware keyboard evidence")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("hardware_keyboard", MISSING, evidence=[item for item in evidence if item], reasons=[error])
    status = _status_from_json(document or {})
    observations = (document or {}).get("observations")
    if not isinstance(observations, dict):
        observations = {}
    is_hardware_keyboard_summary = (document or {}).get("kind") == "phase2_hardware_keyboard_workflow"
    if is_hardware_keyboard_summary:
        observed = all(observations.get(field) is True for field in KEYBOARD_SUMMARY_PASS_FIELDS)
        host_confirmed = (document or {}).get("can_close_hardware_keyboard_gate") is True
    else:
        observed = bool((document or {}).get("observed_physical_keyboard"))
        host_confirmed = (document or {}).get("host_input_observed") is True
    if status == PASS and observed and host_confirmed:
        return _gate("hardware_keyboard", PASS, evidence=[item for item in evidence if item])
    return _gate(
        "hardware_keyboard",
        BLOCKED if status and status.startswith("blocked") else INSUFFICIENT,
        evidence=[item for item in evidence if item],
        reasons=[
            "hardware keyboard evidence must report pass with physical keyboard and Host key-injection evidence"
        ],
    )


def _soak_gate(root: Path, explicit_path: Path | None) -> dict[str, Any]:
    path = explicit_path or _existing_path(
        root,
        ("soak-8h/phase2-tablet-gate.json", "phase2-tablet-gate.json"),
    )
    document, error = _read_optional_json(path, "Phase 2 tablet soak gate")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("eight_hour_sustained_stream", MISSING, evidence=[item for item in evidence if item], reasons=[error])
    verdict = (document or {}).get("verdict")
    if verdict == PASS:
        return _gate("eight_hour_sustained_stream", PASS, evidence=[item for item in evidence if item])
    return _gate(
        "eight_hour_sustained_stream",
        FAIL if verdict == FAIL else INSUFFICIENT,
        evidence=[item for item in evidence if item],
        reasons=[f"phase2-tablet-gate verdict is {verdict!r}, not 'pass'"],
    )


def _thermal_power_gate(root: Path, soak_gate: dict[str, Any], soak_document: dict[str, Any] | None) -> dict[str, Any]:
    required = (
        "adb-battery-before.txt",
        "adb-battery-after.txt",
        "adb-power-before.txt",
        "adb-power-after.txt",
        "thermal-before.txt",
        "thermal-after.txt",
        "thermal-before.err",
        "thermal-after.err",
    )
    missing = [relative for relative in required if not (root / relative).exists()]
    evidence = [relative for relative in required if relative not in missing]
    reasons = ["missing required platform dump: " + relative for relative in missing]
    if soak_document is None or soak_document.get("verdict") != PASS:
        reasons.append("Phase 2 tablet soak gate must pass before thermal/power sampling can pass")
    else:
        criteria = soak_document.get("criteria") if isinstance(soak_document.get("criteria"), dict) else {}
        for name in ("thermal_status_max", "battery_temperature_celsius_max"):
            item = criteria.get(name)
            if not isinstance(item, dict) or item.get("passed") is not True:
                reasons.append(f"soak gate criterion did not pass: {name}")
    status = PASS if not reasons else (FAIL if soak_gate["status"] == FAIL else MISSING)
    return _gate("thermal_power_stand_charging", status, evidence=evidence, reasons=reasons)


def _recovery_gate(root: Path, explicit_path: Path | None) -> dict[str, Any]:
    path = explicit_path or _existing_path(root, DEFAULT_RECOVERY_EVIDENCE)
    document, error = _read_optional_json(path, "recovery evidence")
    evidence = [_relative(root, path)] if path is not None else []
    if error is not None:
        return _gate("recovery", MISSING, evidence=[item for item in evidence if item], reasons=[error])
    reasons: list[str] = []
    for scenario in REQUIRED_RECOVERY_SCENARIOS:
        if _scenario_status(document or {}, scenario) != PASS:
            reasons.append(f"recovery scenario {scenario!r} must report pass")
    stale = (document or {}).get("stale_frame_or_input_accepted")
    if stale is None:
        reasons.append("recovery evidence must record stale_frame_or_input_accepted")
    elif stale is not False:
        reasons.append("recovery evidence reports stale frame or input acceptance")
    return _gate("recovery", PASS if not reasons else INSUFFICIENT, evidence=[item for item in evidence if item], reasons=reasons)


def _report_evidence_dir(root: Path) -> str:
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return root.relative_to(candidate).as_posix()
    return str(root)


def _load_soak_gate(root: Path, explicit_path: Path | None) -> tuple[Path | None, dict[str, Any] | None]:
    path = explicit_path or _existing_path(root, ("soak-8h/phase2-tablet-gate.json", "phase2-tablet-gate.json"))
    if path is None:
        return None, None
    try:
        return path, _read_json(path, "Phase 2 tablet soak gate")
    except PreflightError:
        return path, None


def derive_preflight(
    evidence_dir: Path,
    *,
    soak_gate_path: Path | None = None,
    stylus_evidence_path: Path | None = None,
    keyboard_evidence_path: Path | None = None,
    recovery_evidence_path: Path | None = None,
    min_inches: float = 8.0,
    max_inches: float = 9.0,
) -> dict[str, Any]:
    root = evidence_dir.resolve()
    manifest_path = root / "phase2-tablet-manifest.json"
    device_info_path = root / "device-info.json"
    manifest, manifest_error = _read_optional_json(manifest_path if manifest_path.exists() else None, "Phase 2 tablet manifest")
    device_info, device_info_error = _read_optional_json(device_info_path if device_info_path.exists() else None, "device info")
    loaded_soak_path, loaded_soak = _load_soak_gate(root, soak_gate_path)

    gates = [
        _physical_tablet_gate(manifest, device_info, min_inches=min_inches, max_inches=max_inches),
        _raw_artifacts_gate(root),
        _orientation_gate(root),
        _stylus_gate(root, stylus_evidence_path),
        _keyboard_gate(root, keyboard_evidence_path),
    ]
    soak_result = _soak_gate(root, loaded_soak_path)
    gates.append(soak_result)
    gates.append(_thermal_power_gate(root, soak_result, loaded_soak))
    gates.append(_recovery_gate(root, recovery_evidence_path))

    reasons: list[str] = []
    if manifest_error is not None:
        reasons.append(manifest_error)
    if device_info_error is not None:
        reasons.append(device_info_error)
    for gate in gates:
        reasons.extend(f"{gate['name']}: {reason}" for reason in gate["reasons"])

    statuses = {gate["status"] for gate in gates}
    if BLOCKED in statuses:
        verdict = BLOCKED
    elif FAIL in statuses:
        verdict = FAIL
    elif MISSING in statuses or INSUFFICIENT in statuses:
        verdict = INSUFFICIENT
    else:
        verdict = PASS

    device_class = None
    if isinstance(manifest, dict):
        manifest_device = manifest.get("device")
        if isinstance(manifest_device, dict):
            device_class = manifest_device.get("device_class")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": PREFLIGHT_KIND,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_dir": _report_evidence_dir(root),
        "device_class": device_class,
        "verdict": verdict,
        "gates": gates,
        "reasons": reasons,
        "interpretation": (
            "A pass means this evidence bundle contains the required physical 8-9 inch tablet, "
            "portrait/landscape UI, stylus, hardware keyboard, recovery, thermal/power, and "
            "eight-hour soak artifacts. A blocked verdict means the run cannot close Phase 2 "
            "because the available device or setup is not the required tablet hardware."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--soak-gate", type=Path)
    parser.add_argument("--stylus-evidence", type=Path)
    parser.add_argument("--keyboard-evidence", type=Path)
    parser.add_argument("--recovery-evidence", type=Path)
    parser.add_argument("--tablet-size-min", type=float, default=8.0)
    parser.add_argument("--tablet-size-max", type=float, default=9.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.tablet_size_min <= 0 or arguments.tablet_size_max < arguments.tablet_size_min:
        parser.error("tablet size bounds are invalid")
    output = arguments.output or (arguments.evidence_dir / "phase2-tablet-preflight.json")
    try:
        document = derive_preflight(
            arguments.evidence_dir,
            soak_gate_path=arguments.soak_gate,
            stylus_evidence_path=arguments.stylus_evidence,
            keyboard_evidence_path=arguments.keyboard_evidence,
            recovery_evidence_path=arguments.recovery_evidence,
            min_inches=arguments.tablet_size_min,
            max_inches=arguments.tablet_size_max,
        )
        _write_json(output, document)
    except (OSError, PreflightError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if document["verdict"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
