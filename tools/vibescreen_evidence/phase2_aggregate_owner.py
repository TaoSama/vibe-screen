"""Aggregate Phase 2 tablet productization gate ownership and evidence status."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION


KIND = "phase2_aggregate_owner"
STATUS_CLOSED = "closed"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
STATUS_OPEN = "open"
VERDICT_PASS = "pass"
VERDICT_BLOCKED = "blocked"
VERDICT_INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class OwnerPr:
    number: int | None
    title: str
    branch: str
    head_sha: str | None
    merge_order: int
    note: str


@dataclass(frozen=True)
class SubGate:
    gate_id: str
    label: str
    owner_key: str
    input_key: str | None
    can_close_field: str | None
    requirement: str


OWNER_PRS: dict[str, OwnerPr] = {
    "tablet_ui": OwnerPr(
        234,
        "Improve Android tablet UI ergonomics",
        "codex/android-tablet-ui-optimization",
        "068d15e6cc161c3619fca171e454c167baa2f962",
        1,
        "Android UI-only owner; merge before evidence-doc branches when possible.",
    ),
    "soak": OwnerPr(
        174,
        "Add Phase 2 soak evidence runner",
        "codex/phase2-soak-evidence-runner",
        "e0607d4b7e961baa0e06b73aa1fb9526bafce0ea",
        2,
        "Owns the reusable eight-hour sampling runner and soak-readiness artifacts.",
    ),
    "tablet_preflight": OwnerPr(
        189,
        "Add Phase 2 tablet acceptance preflight",
        "codex/phase2-tablet-acceptance-verifier-20260821",
        "5b9424e3755b6c75ced1e33cb83a2af011fbd87d",
        3,
        "Owns physical tablet identity and pre-run acceptance metadata; aggregate closure is owned by this PR.",
    ),
    "device_memory": OwnerPr(
        213,
        "test: add phase2 device memory gate",
        "origin/main",
        "c8a2e771e3d89a785b4dc773185dc4b989add48d",
        4,
        "Already merged in current base; owns Android and Host memory trend closure inside the Phase 2 window.",
    ),
    "device_environment": OwnerPr(
        252,
        "Add Phase 2 device environment gate",
        "codex/phase2-device-environment-gates",
        "f4727a4ecac44881d3759a64ff4a4d92961661f8",
        5,
        "Owns device power, battery, thermal, and environment-readiness checks.",
    ),
    "hardware_keyboard": OwnerPr(
        240,
        "Document Phase 2 hardware keyboard blocked evidence",
        "codex/phase2-hardware-keyboard-gate",
        "4b0391c8628214721bb4e314da4b31e3bfb24041",
        6,
        "Owns physical Android-attached hardware-keyboard workflow evidence.",
    ),
    "stand_charging": OwnerPr(
        255,
        "Require Phase 2 charging gate owners",
        "codex/phase2-stand-charging-owner-gate",
        "1103cc89b10bd20caa04d7bdcb1578f2446a7b25",
        7,
        "Owns stand-mounted charging thresholds and gate ownership wiring.",
    ),
    "aggregate": OwnerPr(
        None,
        "Phase 2 current-base aggregate owner",
        "codex/phase2-aggregate-owner-20260822",
        None,
        8,
        "Owns the cross-PR owner matrix, merge order, and fail-closed aggregate report.",
    ),
}

PENDING_MERGE_OWNER_KEYS = (
    "tablet_ui",
    "soak",
    "tablet_preflight",
    "device_environment",
    "hardware_keyboard",
    "stand_charging",
    "aggregate",
)

PAIRWISE_OVERLAP_NOTES = [
    "#213 is already in current base; #274 references its device-memory gate output instead of duplicating that owner.",
    "#189/#255 overlap on Phase 2 manifest schema, tests, and README/runbook wording.",
    "#174/#189/#252/#255 overlap on Makefile and Phase 2 evidence-tool documentation.",
    "#240 overlaps with README/TEST/testing documentation but is semantically a blocked hardware-keyboard evidence refresh.",
    "#234 is Android UI scoped and has no direct evidence-tool file overlap, but still needs current-base rebase before merge.",
]


SUB_GATES: tuple[SubGate, ...] = (
    SubGate(
        "tablet_ui_ergonomics",
        "8-9 inch tablet UI ergonomics",
        "tablet_ui",
        "tablet_ui",
        "can_close_tablet_ui_gate",
        "Target-tablet or accepted instrumentation evidence for the tablet UI surface.",
    ),
    SubGate(
        "physical_8_9_inch_tablet",
        "Physical 8-9 inch tablet identity",
        "tablet_preflight",
        "tablet_gate",
        None,
        "Phase 2 tablet gate pass with manifest device.device_class=physical_8_9_inch_tablet.",
    ),
    SubGate(
        "eight_hour_sustained_stream",
        "Eight-hour sustained stream",
        "soak",
        "soak_readiness",
        "can_close_eight_hour_soak_gate",
        "Soak-readiness gate pass plus a Phase 2 tablet gate pass over an exact eight-hour evidence window.",
    ),
    SubGate(
        "device_memory",
        "Device and Host memory trend",
        "device_memory",
        "device_memory",
        "can_close_device_memory_gate",
        "Device-memory gate pass or explicit close boolean from the memory owner.",
    ),
    SubGate(
        "stand_mounted_charging",
        "Stand-mounted charging stability",
        "stand_charging",
        "stand_charging",
        "can_close_stand_charging_gate",
        "Stand-charging gate pass plus continuous charging/full status and plugged samples in the tablet gate.",
    ),
    SubGate(
        "thermal_power_sampling",
        "Thermal and power sampling",
        "device_environment",
        "device_environment",
        "can_close_device_environment_gate",
        "Device-environment gate pass or explicit close boolean from the environment owner.",
    ),
    SubGate(
        "foreground_background_transport_recovery",
        "Foreground/background and transport recovery",
        "aggregate",
        "recovery",
        "can_close_recovery_gate",
        "Live recovery evidence with fresh session epoch and no stale frame/input acceptance.",
    ),
    SubGate(
        "hardware_keyboard",
        "Hardware-keyboard workflow",
        "hardware_keyboard",
        "hardware_keyboard",
        "can_close_hardware_keyboard_gate",
        "Hardware-keyboard summary pass from a physical Android-attached keyboard run.",
    ),
    SubGate(
        "login_startup_headless",
        "Login startup or headless Mac mini recovery",
        "aggregate",
        "login_headless",
        "can_close_login_headless_gate",
        "Mac login-startup or headless recovery evidence with Host build and permission state.",
    ),
)


class AggregateOwnerError(ValueError):
    """Raised when aggregate-owner inputs are malformed."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AggregateOwnerError(f"failed to read {label} {path}: {error}") from error
    if not isinstance(document, dict):
        raise AggregateOwnerError(f"{label} must be a JSON object: {path}")
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _owner_document(owner: OwnerPr) -> dict[str, Any]:
    return {
        "pr_number": owner.number,
        "title": owner.title,
        "branch": owner.branch,
        "head_sha": owner.head_sha,
        "merge_order": owner.merge_order,
        "note": owner.note,
    }


def _input_close_signal(
    document: dict[str, Any] | None,
    *,
    can_close_field: str | None,
) -> tuple[bool, str | None]:
    if document is None:
        return False, "missing gate output"
    if can_close_field is not None:
        value = document.get(can_close_field)
        if isinstance(value, bool):
            return value, None if value else f"{can_close_field} is false"
    verdict = document.get("verdict")
    if verdict == "pass":
        return True, None
    if _non_empty_string(verdict):
        return False, f"verdict is {verdict}"
    return False, "gate output has no pass verdict or close boolean"


def _manifest_device_class(manifest: dict[str, Any] | None) -> str | None:
    if manifest is None:
        return None
    device = manifest.get("device")
    if not isinstance(device, dict):
        return None
    value = device.get("device_class")
    return value if isinstance(value, str) else None


def _manifest_identity(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    device = manifest.get("device")
    if not isinstance(device, dict):
        return None
    identity = device.get("identity")
    return identity if isinstance(identity, dict) else None


def _substitute_notes(manifest: dict[str, Any] | None) -> list[str]:
    device_class = _manifest_device_class(manifest)
    identity = _manifest_identity(manifest) or {}
    model = str(identity.get("model", "")).lower()
    codename = str(identity.get("codename", "")).lower()
    notes: list[str] = []
    if device_class == "android_substitute":
        notes.append(
            "manifest records android_substitute; this is substitute readiness only and cannot close the physical tablet gate"
        )
    if model == "p0110" or codename == "pacific":
        notes.append(
            "device identity is Nubia P0110/pacific/Android 16 when present; do not relabel it as Xiaomi/fuxi or 8-9 inch tablet evidence"
        )
    return notes


def _gate_status(
    spec: SubGate,
    *,
    inputs: dict[str, dict[str, Any] | None],
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    owner = OWNER_PRS[spec.owner_key]
    document = inputs.get(spec.input_key) if spec.input_key is not None else None
    can_close, input_reason = _input_close_signal(
        document,
        can_close_field=spec.can_close_field,
    )
    reasons: list[str] = []
    if input_reason is not None:
        reasons.append(input_reason)

    device_class = _manifest_device_class(manifest)
    if spec.gate_id == "physical_8_9_inch_tablet" and device_class != "physical_8_9_inch_tablet":
        can_close = False
        reasons.append("manifest device_class is not physical_8_9_inch_tablet")
    if spec.input_key == "tablet_gate" and not _tablet_gate_has_package(document):
        can_close = False
        reasons.append("tablet gate is not package-aware or evidence_package did not pass")
    if spec.gate_id in {"eight_hour_sustained_stream", "stand_mounted_charging"}:
        tablet_gate = inputs.get("tablet_gate")
        if not _tablet_gate_has_package(tablet_gate):
            can_close = False
            reasons.append("tablet gate is not package-aware or evidence_package did not pass")
    if spec.gate_id == "tablet_ui_ergonomics" and document is None:
        reasons.append("no current-base tablet UI gate output was supplied")

    if can_close:
        status = STATUS_CLOSED
    elif document is None:
        status = STATUS_BLOCKED
    elif document.get("verdict") == "blocked":
        status = STATUS_BLOCKED
    else:
        status = STATUS_INSUFFICIENT

    return {
        "gate_id": spec.gate_id,
        "label": spec.label,
        "status": status,
        "can_close": can_close,
        "owner": _owner_document(owner),
        "input_key": spec.input_key,
        "requirement": spec.requirement,
        "reasons": reasons,
    }


def _tablet_gate_has_package(tablet_gate: dict[str, Any] | None) -> bool:
    if tablet_gate is None:
        return False
    package = tablet_gate.get("evidence_package")
    return isinstance(package, dict) and package.get("passed") is True


def _source_status(document: dict[str, Any] | None) -> str | None:
    if document is None:
        return None
    value = document.get("verdict")
    if isinstance(value, str):
        return value
    value = document.get("status")
    if isinstance(value, str):
        return value
    return None


def derive_report(
    *,
    tablet_gate: dict[str, Any] | None = None,
    tablet_manifest: dict[str, Any] | None = None,
    hardware_keyboard: dict[str, Any] | None = None,
    device_memory: dict[str, Any] | None = None,
    device_environment: dict[str, Any] | None = None,
    soak_readiness: dict[str, Any] | None = None,
    stand_charging: dict[str, Any] | None = None,
    tablet_ui: dict[str, Any] | None = None,
    recovery: dict[str, Any] | None = None,
    login_headless: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = {
        "tablet_gate": tablet_gate,
        "tablet_manifest": tablet_manifest,
        "hardware_keyboard": hardware_keyboard,
        "device_memory": device_memory,
        "device_environment": device_environment,
        "soak_readiness": soak_readiness,
        "stand_charging": stand_charging,
        "tablet_ui": tablet_ui,
        "recovery": recovery,
        "login_headless": login_headless,
    }
    gates = [
        _gate_status(spec, inputs=inputs, manifest=tablet_manifest)
        for spec in SUB_GATES
    ]
    open_reasons = [
        f"{gate['gate_id']}: {reason}"
        for gate in gates
        if not gate["can_close"]
        for reason in gate["reasons"]
    ]
    if not _tablet_gate_has_package(tablet_gate):
        open_reasons.append(
            "aggregate: no passing package-aware Phase 2 tablet gate output was supplied"
        )
    merge_plan = [
        _owner_document(OWNER_PRS[key])
        for key in sorted(PENDING_MERGE_OWNER_KEYS, key=lambda item: OWNER_PRS[item].merge_order)
    ]
    closed = all(gate["can_close"] for gate in gates)
    if not _tablet_gate_has_package(tablet_gate):
        closed = False
    blocked = any(gate["status"] == STATUS_BLOCKED for gate in gates)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "verdict": VERDICT_PASS if closed else (VERDICT_BLOCKED if blocked else VERDICT_INSUFFICIENT),
        "can_close_readme_phase2_gates": closed,
        "source_baseline": "origin/main 660dae5231fb1ac4decf5088f911f22a9285abf8 current-base aggregate",
        "audit_summary": {
            "single_prs_against_origin_main": "Current base already includes #213. #274 now tracks the remaining Phase 2 child owners without duplicating #189 preflight or #213 device-memory implementation.",
            "pairwise_overlap": PAIRWISE_OVERLAP_NOTES,
            "recommendation": (
                "Use this aggregate owner layer to keep README Phase 2 gate status "
                "fail-closed while child PRs are rebased or merged in the recorded order."
            ),
        },
        "input_summaries": {
            key: {"provided": value is not None, "status": _source_status(value)}
            for key, value in inputs.items()
        },
        "owner_matrix": gates,
        "merge_plan": merge_plan,
        "substitute_readiness": {
            "device_class": _manifest_device_class(tablet_manifest),
            "device_identity": _manifest_identity(tablet_manifest),
            "notes": _substitute_notes(tablet_manifest),
        },
        "open_reasons": open_reasons,
        "interpretation": (
            "This aggregate report establishes one current-base owner per Phase 2 "
            "tablet productization sub-gate. It does not close any child gate "
            "unless that child gate supplies an explicit pass/close signal; phone "
            "substitute readiness remains separate from physical 8-9 inch tablet evidence."
        ),
    }


def _optional_document(path: Path | None, label: str) -> dict[str, Any] | None:
    if path is None:
        return None
    return _read_json(path, label)


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tablet-gate", type=Path)
    parser.add_argument("--tablet-manifest", type=Path)
    parser.add_argument("--hardware-keyboard", type=Path)
    parser.add_argument("--device-memory", type=Path)
    parser.add_argument("--device-environment", type=Path)
    parser.add_argument("--soak-readiness", type=Path)
    parser.add_argument("--stand-charging", type=Path)
    parser.add_argument("--tablet-ui", type=Path)
    parser.add_argument("--recovery", type=Path)
    parser.add_argument("--login-headless", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = derive_report(
            tablet_gate=_optional_document(arguments.tablet_gate, "Phase 2 tablet gate"),
            tablet_manifest=_optional_document(arguments.tablet_manifest, "Phase 2 tablet manifest"),
            hardware_keyboard=_optional_document(arguments.hardware_keyboard, "hardware-keyboard summary"),
            device_memory=_optional_document(arguments.device_memory, "device-memory summary"),
            device_environment=_optional_document(arguments.device_environment, "device-environment summary"),
            soak_readiness=_optional_document(arguments.soak_readiness, "soak-readiness summary"),
            stand_charging=_optional_document(arguments.stand_charging, "stand-charging summary"),
            tablet_ui=_optional_document(arguments.tablet_ui, "tablet UI summary"),
            recovery=_optional_document(arguments.recovery, "recovery summary"),
            login_headless=_optional_document(arguments.login_headless, "login/headless summary"),
        )
        _write_json(arguments.output, report)
    except (AggregateOwnerError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
