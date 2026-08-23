"""Aggregate Phase 2 tablet productization owner and evidence status."""

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
VERDICT_PASS = "pass"
VERDICT_BLOCKED = "blocked"
VERDICT_INSUFFICIENT = "insufficient"
CURRENT_BASE = "origin/main 781992d7dc6e99d62ddd5326853f689c30c53d67"


@dataclass(frozen=True)
class OwnerPr:
    number: int | None
    title: str
    branch: str
    head_sha: str | None
    state: str
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


@dataclass(frozen=True)
class InputOption:
    cli_name: str
    dest: str
    label: str


OWNER_PRS: dict[str, OwnerPr] = {
    "tablet_ui": OwnerPr(
        234,
        "Improve Android tablet UI ergonomics",
        "codex/android-tablet-ui-optimization",
        "068d15e6cc161c3619fca171e454c167baa2f962",
        "active_child_draft_behind",
        1,
        "Owns Android tablet UI ergonomics only; it does not provide physical-tablet soak evidence.",
    ),
    "soak": OwnerPr(
        174,
        "Add Phase 2 soak evidence runner",
        "codex/phase2-soak-evidence-runner",
        "a7bfecf89b16df7354ae93f3a3f04c3b5c160425",
        "active_child_current_base",
        2,
        "Owns the reusable eight-hour soak runner and soak-readiness evidence path.",
    ),
    "tablet_preflight": OwnerPr(
        189,
        "Add Phase 2 tablet acceptance preflight",
        "origin/main",
        "5b9424e3755b6c75ced1e33cb83a2af011fbd87d",
        "merged_baseline",
        3,
        "Merged baseline for physical tablet identity and final preflight bundle checks.",
    ),
    "device_memory": OwnerPr(
        213,
        "test: add phase2 device memory gate",
        "origin/main",
        "c8a2e771e3d89a785b4dc773185dc4b989add48d",
        "merged_baseline",
        4,
        "Merged baseline for Android PSS, Host RSS, charging/full-state, and thermal sample sufficiency.",
    ),
    "device_environment": OwnerPr(
        285,
        "Add Phase 2 device environment owner gate",
        "codex/phase2-device-environment-owner-gate",
        "5198f06ebbca185ec33f9ed03f8a10cb0edf7050",
        "active_child_draft_conflicting",
        5,
        "Current device-environment child owner for stand charging, controlled thermal load, and power stability; supersedes #252 and folds in #255's owner mapping direction.",
    ),
    "hardware_keyboard": OwnerPr(
        240,
        "Document Phase 2 hardware keyboard blocked evidence",
        "codex/phase2-hardware-keyboard-gate",
        "4b0391c8628214721bb4e314da4b31e3bfb24041",
        "active_child_draft_conflicting",
        6,
        "Owns physical Android-attached hardware-keyboard workflow evidence.",
    ),
    "aggregate": OwnerPr(
        None,
        "Phase 2 current-base aggregate owner",
        "codex/phase2-current-base-aggregate-owner",
        None,
        "this_current_base_pr",
        7,
        "Owns the cross-PR owner matrix, stale/duplicate classification, merge order, and fail-closed aggregate report.",
    ),
}

STALE_PRS: tuple[dict[str, Any], ...] = (
    {
        "pr_number": 274,
        "title": "Add Phase 2 aggregate owner gate",
        "status": "stale_source_superseded",
        "replacement": "this current-base aggregate-owner branch",
        "reason": "The old aggregate branch was draft/conflicting and based on 660dae52; this branch replays only the aggregate semantics on current base.",
    },
    {
        "pr_number": 252,
        "title": "Add Phase 2 device environment gate",
        "status": "stale_duplicate",
        "replacement": "#285",
        "reason": "The newer #285 device-environment child owner carries the current stand/thermal/power direction and supersedes the older implementation.",
    },
    {
        "pr_number": 255,
        "title": "Require Phase 2 charging gate owners",
        "status": "partially_superseded",
        "replacement": "#285 plus this aggregate owner matrix",
        "reason": "Its stand-charging owner-map direction is represented by #285 and this aggregate report; the old branch should not be merged as-is.",
    },
)

PAIRWISE_OVERLAP_NOTES = [
    "#252 and #285 both own device-environment style checks; #285 is the current child owner and #252 is stale.",
    "#255 overlaps #285 on stand-charging owner mapping and tablet gate wiring; keep #255 as stale/partially superseded unless rebased deliberately.",
    "#174 owns the eight-hour runner and remains separate from the aggregate verdict layer.",
    "#189 and #213 are already merged into current base and are consumed as baseline gates, not reimplemented here.",
    "#234 and #240 remain independent child slices for tablet UI and hardware keyboard evidence.",
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
        "Soak-readiness pass plus a Phase 2 tablet gate pass over an exact eight-hour evidence window.",
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
        "device_environment",
        "device_environment",
        "can_close_stand_charging_gate",
        "Device-environment pass or explicit stand-charging close signal with continuous charging/full status.",
    ),
    SubGate(
        "thermal_power_sampling",
        "Thermal and power sampling",
        "device_environment",
        "device_environment",
        "can_close_device_environment_gate",
        "Device-environment pass or explicit close signal for thermal-load and power stability.",
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

INPUT_OPTIONS: tuple[InputOption, ...] = (
    InputOption("tablet-gate", "tablet_gate", "Phase 2 tablet gate"),
    InputOption("tablet-manifest", "tablet_manifest", "Phase 2 tablet manifest"),
    InputOption("hardware-keyboard", "hardware_keyboard", "hardware-keyboard summary"),
    InputOption("device-memory", "device_memory", "device-memory summary"),
    InputOption("device-environment", "device_environment", "device-environment summary"),
    InputOption("soak-readiness", "soak_readiness", "soak-readiness summary"),
    InputOption("tablet-ui", "tablet_ui", "tablet UI summary"),
    InputOption("recovery", "recovery", "recovery summary"),
    InputOption("login-headless", "login_headless", "login/headless summary"),
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


def _owner_document(owner: OwnerPr) -> dict[str, Any]:
    return {
        "pr_number": owner.number,
        "title": owner.title,
        "branch": owner.branch,
        "head_sha": owner.head_sha,
        "state": owner.state,
        "merge_order": owner.merge_order,
        "note": owner.note,
    }


def _source_status(document: dict[str, Any] | None) -> str | None:
    if document is None:
        return None
    for field in ("verdict", "status", "derivation_status"):
        value = document.get(field)
        if isinstance(value, str) and value:
            return value
    return None


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
    if verdict == VERDICT_PASS:
        return True, None
    if isinstance(verdict, str) and verdict:
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


def _tablet_gate_has_package(tablet_gate: dict[str, Any] | None) -> bool:
    if tablet_gate is None:
        return False
    package = tablet_gate.get("evidence_package")
    return isinstance(package, dict) and package.get("passed") is True


def _known_phone_substitute(identity: dict[str, Any] | None) -> bool:
    if identity is None:
        return False
    model = str(identity.get("model", "")).lower()
    codename = str(identity.get("codename", "")).lower()
    return model == "p0110" or codename == "pacific"


def _substitute_notes(manifest: dict[str, Any] | None) -> list[str]:
    notes: list[str] = []
    device_class = _manifest_device_class(manifest)
    identity = _manifest_identity(manifest)
    if device_class == "android_substitute":
        notes.append(
            "manifest records android_substitute; this is substitute readiness only and cannot close the physical tablet gate"
        )
    if _known_phone_substitute(identity):
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
    if spec.gate_id == "physical_8_9_inch_tablet" and _known_phone_substitute(_manifest_identity(manifest)):
        can_close = False
        reasons.append("known phone substitute cannot close the physical 8-9 inch tablet gate")
    if spec.input_key == "tablet_gate" and not _tablet_gate_has_package(document):
        can_close = False
        reasons.append("tablet gate is not package-aware or evidence_package did not pass")
    if spec.gate_id in {"eight_hour_sustained_stream", "stand_mounted_charging"}:
        tablet_gate = inputs.get("tablet_gate")
        if not _tablet_gate_has_package(tablet_gate):
            can_close = False
            reasons.append("tablet gate is not package-aware or evidence_package did not pass")

    if can_close:
        status = STATUS_CLOSED
    elif document is None or _source_status(document) == STATUS_BLOCKED:
        status = STATUS_BLOCKED
    else:
        status = STATUS_INSUFFICIENT

    return {
        "gate_id": spec.gate_id,
        "label": spec.label,
        "status": status,
        "can_close": can_close,
        "owner": _owner_document(OWNER_PRS[spec.owner_key]),
        "input_key": spec.input_key,
        "requirement": spec.requirement,
        "reasons": reasons,
    }


def derive_report(
    *,
    tablet_gate: dict[str, Any] | None = None,
    tablet_manifest: dict[str, Any] | None = None,
    hardware_keyboard: dict[str, Any] | None = None,
    device_memory: dict[str, Any] | None = None,
    device_environment: dict[str, Any] | None = None,
    soak_readiness: dict[str, Any] | None = None,
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
        "tablet_ui": tablet_ui,
        "recovery": recovery,
        "login_headless": login_headless,
    }
    owner_matrix = [
        _gate_status(spec, inputs=inputs, manifest=tablet_manifest)
        for spec in SUB_GATES
    ]
    open_reasons = [
        f"{gate['gate_id']}: {reason}"
        for gate in owner_matrix
        if not gate["can_close"]
        for reason in gate["reasons"]
    ]
    if not _tablet_gate_has_package(tablet_gate):
        open_reasons.append(
            "aggregate: no passing package-aware Phase 2 tablet gate output was supplied"
        )

    can_close = all(gate["can_close"] for gate in owner_matrix) and _tablet_gate_has_package(tablet_gate)
    blocked = any(gate["status"] == STATUS_BLOCKED for gate in owner_matrix)
    verdict = VERDICT_PASS if can_close else (VERDICT_BLOCKED if blocked else VERDICT_INSUFFICIENT)
    merge_plan = [
        _owner_document(OWNER_PRS[key])
        for key in ("tablet_ui", "soak", "device_environment", "hardware_keyboard", "aggregate")
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "verdict": verdict,
        "can_close_readme_phase2_gates": can_close,
        "source_baseline": CURRENT_BASE,
        "audit_summary": {
            "single_prs_against_origin_main": (
                "#189 and #213 are merged into current base. #174 is the current-base soak child owner. "
                "#285 should carry the device-environment child gate; #252 and #255 are stale/duplicate inputs."
            ),
            "pairwise_overlap": PAIRWISE_OVERLAP_NOTES,
            "recommendation": (
                "Use this aggregate owner layer to keep README Phase 2 gate status fail-closed while child PRs are rebased or merged in the recorded order."
            ),
        },
        "input_summaries": {
            key: {"provided": value is not None, "status": _source_status(value)}
            for key, value in inputs.items()
        },
        "owner_matrix": owner_matrix,
        "merge_plan": merge_plan,
        "stale_prs": list(STALE_PRS),
        "substitute_readiness": {
            "device_class": _manifest_device_class(tablet_manifest),
            "device_identity": _manifest_identity(tablet_manifest),
            "notes": _substitute_notes(tablet_manifest),
        },
        "open_reasons": open_reasons,
        "interpretation": (
            "This aggregate report establishes one current-base owner per Phase 2 tablet productization sub-gate. "
            "It does not close any child gate unless that child gate supplies an explicit pass/close signal; phone substitute readiness remains separate from physical 8-9 inch tablet evidence."
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
    for option in INPUT_OPTIONS:
        parser.add_argument(f"--{option.cli_name}", dest=option.dest, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        inputs = {
            option.dest: _optional_document(getattr(arguments, option.dest), option.label)
            for option in INPUT_OPTIONS
        }
        report = derive_report(**inputs)
        _write_json(arguments.output, report)
    except (AggregateOwnerError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
