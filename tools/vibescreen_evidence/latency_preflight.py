#!/usr/bin/env python3
"""Preflight external-camera latency gate readiness without side effects.

This check records whether a run is ready to attempt the formal latency gates.
It never converts synthetic samples, telemetry, or partial setup notes into a
performance pass. Missing evidence defaults to blocked with actionable
requirements for the USB glass-to-glass, LAN glass-to-glass, and input P95
profiles.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .latency import (
    GATE_INPUT_P95_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_PROFILES,
    GATE_USB_GLASS_TO_GLASS_SUB50,
)

KIND = "latency_gate_preflight"
STATUS_READY = "ready"
STATUS_BLOCKED = "blocked"

FORMAL_LATENCY_PROFILES = (
    GATE_USB_GLASS_TO_GLASS_SUB50,
    GATE_LAN_GLASS_TO_GLASS_SUB80,
    GATE_INPUT_P95_SUB50,
)

COMMON_REQUIREMENTS = (
    (
        "external_camera_timebase_ready",
        "capture Mac stimulus/result and Android display/input in one 120 FPS or higher external-camera timebase",
    ),
    (
        "raw_camera_recording_retained",
        "retain the raw high-frame-rate camera recording in the evidence directory",
    ),
    (
        "sample_annotations_retained",
        "retain latency samples derived from the same camera timebase",
    ),
    (
        "minimum_sample_count_ready",
        "annotate at least five valid samples for the selected profile",
    ),
    (
        "formal_manifest_retained",
        "write a formal latency manifest bound to the raw recording, samples, device, host, and build",
    ),
    (
        "device_identity_recorded",
        "record manufacturer, model, codename, Android version, and serial for the measured Android device",
    ),
    (
        "host_build_identity_recorded",
        "record the measured Mac host identity and Host binary/build identity",
    ),
)

PROFILE_REQUIREMENTS = {
    GATE_USB_GLASS_TO_GLASS_SUB50: (
        (
            "usb_transport_ready",
            "record ADB reverse/USB connection setup and active USB stream proof for the run",
        ),
    ),
    GATE_LAN_GLASS_TO_GLASS_SUB80: (
        (
            "lan_transport_ready",
            "record LAN network preflight plus active trusted-LAN stream proof for the run",
        ),
    ),
    GATE_INPUT_P95_SUB50: (
        (
            "physical_input_actuation_ready",
            "use real physical Android input actuation visible to the measurement timebase",
        ),
        (
            "visible_mac_input_result_ready",
            "record the first visible Mac-side result for each physical input sample",
        ),
    ),
}

DEFAULT_PROFILES = FORMAL_LATENCY_PROFILES


class LatencyPreflightError(ValueError):
    """Raised when latency preflight input is malformed."""


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_non_finite_json_constant,
        )
    except OSError as error:
        raise LatencyPreflightError(f"cannot read {label} {path}: {error}") from error
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise LatencyPreflightError(f"invalid JSON in {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise LatencyPreflightError(f"{label} must be a JSON object")
    return document


def _run(command: Sequence[str], cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LatencyPreflightError(f"failed to run {' '.join(command)}: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise LatencyPreflightError(
            f"{' '.join(command)} exited with {completed.returncode}: {detail}"
        )
    return completed.stdout.strip()


def _repository_revision(repo: Path | None) -> str | None:
    if repo is None:
        return None
    return _run(("git", "rev-parse", "HEAD"), repo)


def _is_non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _device_from_device_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    document = _load_json(path, "Android device info")
    device = document.get("device")
    if not isinstance(device, dict):
        raise LatencyPreflightError("Android device info must contain a device object")
    return device


def _device_identity_complete(device: Any) -> bool:
    if not isinstance(device, dict):
        return False
    os_version = device.get("os_version", device.get("android_release"))
    serial = device.get("adb_serial", device.get("device_serial", device.get("serial")))
    return all(
        _is_non_empty_text(value)
        for value in (
            device.get("manufacturer"),
            device.get("model"),
            device.get("codename", device.get("device")),
            os_version,
            serial,
        )
    )


def _profile_records(
    document: dict[str, Any], profiles: Sequence[str]
) -> dict[str, dict[str, Any]]:
    raw_profiles = document.get("gate_profiles", document.get("profiles", []))
    if raw_profiles is None:
        raw_profiles = []
    if not isinstance(raw_profiles, list):
        raise LatencyPreflightError("gate_profiles must be an array")

    records: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_profiles):
        if not isinstance(item, dict):
            raise LatencyPreflightError(f"gate_profiles[{index}] must be an object")
        profile = item.get("profile")
        if profile not in FORMAL_LATENCY_PROFILES:
            allowed = ", ".join(FORMAL_LATENCY_PROFILES)
            raise LatencyPreflightError(
                f"gate_profiles[{index}].profile must be one of: {allowed}"
            )
        records[str(profile)] = item

    return {profile: records.get(profile, {"profile": profile}) for profile in profiles}


def _boolean_checks(
    record: dict[str, Any], profile: str
) -> tuple[dict[str, bool], list[str]]:
    raw_checks = record.get("checks", {})
    if raw_checks is None:
        raw_checks = {}
    if not isinstance(raw_checks, dict):
        raise LatencyPreflightError(f"{profile}.checks must be an object")

    checks: dict[str, bool] = {}
    errors: list[str] = []
    for field, _requirement in (*COMMON_REQUIREMENTS, *PROFILE_REQUIREMENTS[profile]):
        value = raw_checks.get(field, False)
        if isinstance(value, bool):
            checks[field] = value
        else:
            errors.append(f"{profile}.checks.{field} must be true or false")
            checks[field] = False
    return checks, errors


def _artifact_paths(record: dict[str, Any]) -> list[str]:
    raw_artifacts = record.get("artifact_paths", [])
    if raw_artifacts is None:
        return []
    if not isinstance(raw_artifacts, list) or not all(
        isinstance(item, str) for item in raw_artifacts
    ):
        raise LatencyPreflightError("artifact_paths must be a list of strings")
    return list(raw_artifacts)


def _notes(document: dict[str, Any], explicit_notes: Sequence[str]) -> list[str]:
    if explicit_notes:
        return list(explicit_notes)
    raw_notes = document.get("notes", [])
    if raw_notes is None:
        return []
    if not isinstance(raw_notes, list) or not all(
        isinstance(item, str) for item in raw_notes
    ):
        raise LatencyPreflightError("notes must be a list of strings")
    return list(raw_notes)


def evaluate(
    document: dict[str, Any],
    *,
    profiles: Sequence[str] = DEFAULT_PROFILES,
    device: dict[str, Any] | None = None,
    run_id: str | None = None,
    repository_revision: str | None = None,
    checked_at: str | None = None,
    notes: Sequence[str] = (),
) -> dict[str, Any]:
    requested_profiles = tuple(profiles)
    for profile in requested_profiles:
        if profile not in FORMAL_LATENCY_PROFILES:
            allowed = ", ".join(FORMAL_LATENCY_PROFILES)
            raise LatencyPreflightError(f"profile must be one of: {allowed}")

    merged_device = device if device is not None else document.get("device")
    device_recorded = _device_identity_complete(merged_device)
    profile_documents = _profile_records(document, requested_profiles)
    gate_reports: list[dict[str, Any]] = []

    for profile, record in profile_documents.items():
        checks, type_errors = _boolean_checks(record, profile)
        checks["device_identity_recorded"] = device_recorded

        missing = [
            {"field": field, "requirement": requirement}
            for field, requirement in (*COMMON_REQUIREMENTS, *PROFILE_REQUIREMENTS[profile])
            if not checks[field]
        ]
        for error in type_errors:
            missing.append({"field": "input", "requirement": error})

        profile_definition = GATE_PROFILES[profile]
        gate_reports.append(
            {
                "profile": profile,
                "latency_kind": profile_definition["kind"],
                "transport": profile_definition["transport"],
                "status": STATUS_READY if not missing else STATUS_BLOCKED,
                "can_attempt_formal_gate": not missing,
                "can_close_performance_gate": False,
                "checks": checks,
                "missing_requirements": missing,
                "artifact_paths": _artifact_paths(record),
            }
        )

    status = (
        STATUS_READY
        if all(report["status"] == STATUS_READY for report in gate_reports)
        else STATUS_BLOCKED
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or str(document.get("run_id") or uuid.uuid4()),
        "kind": KIND,
        "status": status,
        "checked_at": checked_at
        or str(document.get("checked_at") or datetime.now(timezone.utc).isoformat()),
        "repository_revision": repository_revision or document.get("repository_revision"),
        "device": merged_device,
        "gate_profiles": gate_reports,
        "notes": _notes(document, notes),
        "claim_boundary": (
            "This preflight is readiness evidence only. It cannot close USB, LAN, "
            "or input latency gates; only a passing formal latency evidence report "
            "with retained real measurement artifacts can do that."
        ),
    }


def _write_json(path: Path | None, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="optional latency preflight readiness JSON; missing checks default to blocked",
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=FORMAL_LATENCY_PROFILES,
        help="gate profile to include; repeatable. Defaults to all formal latency profiles",
    )
    parser.add_argument("--device-info", type=Path, help="Android device-info JSON to embed")
    parser.add_argument("--repo", type=Path, help="Git repository used to record HEAD")
    parser.add_argument("--repository-revision", help="repository revision to record")
    parser.add_argument("--run-id", help="stable run identifier")
    parser.add_argument("--checked-at", help="ISO timestamp/date for deterministic reports")
    parser.add_argument("--note", action="append", default=[], help="note to include; repeatable")
    parser.add_argument("--output", type=Path, help="write preflight report JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = _load_json(args.input, "latency preflight input") if args.input else {}
        device = _device_from_device_info(args.device_info) if args.device_info else None
        repository_revision = args.repository_revision or _repository_revision(args.repo)
        result = evaluate(
            document,
            profiles=args.profile or DEFAULT_PROFILES,
            device=device,
            run_id=args.run_id,
            repository_revision=repository_revision,
            checked_at=args.checked_at,
            notes=args.note,
        )
        _write_json(args.output, result)
    except (LatencyPreflightError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0 if result["status"] == STATUS_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
