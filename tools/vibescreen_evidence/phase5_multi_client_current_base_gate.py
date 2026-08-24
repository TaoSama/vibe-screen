"""Evaluate Phase 5 multi-client/display current-base readiness evidence.

This gate is intentionally fail-closed. It distinguishes one client switching
between multiple displays from simultaneous multi-client display streaming, and
it never treats single-client display-selection evidence as a Phase 5
multi-client pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from . import SCHEMA_VERSION


KIND = "phase5_multi_client_current_base_gate"
PASS = "pass"
BLOCKED = "blocked"
FAIL = "fail"
INSUFFICIENT = "insufficient"

REQUIRED_ARTIFACTS = (
    "host-routing.json",
    "transport-ownership.json",
    "display-identity.json",
    "macos-host.json",
    "android-client-1.json",
    "android-client-2.json",
)

REQUIRED_ARTIFACT_KINDS = {
    "host-routing.json": "phase5_multi_client_host_routing_evidence",
    "transport-ownership.json": "phase5_multi_client_transport_ownership_evidence",
    "display-identity.json": "phase5_multi_client_display_identity_evidence",
    "macos-host.json": "phase5_multi_client_macos_host_evidence",
    "android-client-1.json": "phase5_multi_client_android_client_evidence",
    "android-client-2.json": "phase5_multi_client_android_client_evidence",
}

REQUIRED_ARTIFACT_OBSERVATIONS = {
    "host-routing.json": (
        "simultaneous_clients",
        "distinct_session_ids",
        "per_client_route_binding",
        "old_connection_retained",
    ),
    "transport-ownership.json": (
        "independent_transport_connections",
        "distinct_session_epochs",
    ),
    "display-identity.json": (
        "distinct_display_streams",
        "no_single_client_display_switch_substitution",
    ),
    "macos-host.json": (
        "host_does_not_replace_old_connection",
        "host_advertises_multi_client",
        "parallel_or_broadcast_capture_defined",
    ),
    "android-client-1.json": (
        "visible_distinct_stream",
        "session_bound_to_display",
    ),
    "android-client-2.json": (
        "visible_distinct_stream",
        "session_bound_to_display",
    ),
}

REQUIRED_TRUE_FIELDS = (
    "simultaneous_clients",
    "distinct_session_ids",
    "distinct_session_epochs",
    "independent_transport_connections",
    "per_client_route_binding",
    "per_client_frame_queue_or_broadcast_owner",
    "per_client_input_target_validation",
    "parallel_or_broadcast_capture_defined",
    "no_single_client_display_switch_substitution",
    "host_does_not_replace_old_connection",
    "host_advertises_multi_client",
    "android_clients_visible_distinct_streams",
)

OPTIONAL_PLATFORM_FIELDS = (
    "ios_owner_status_recorded",
    "harmony_owner_status_recorded",
)


class Phase5MultiClientGateError(ValueError):
    """Raised when an evidence package cannot be evaluated."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Phase5MultiClientGateError(f"cannot read {label}: {error}") from error
    if not isinstance(document, dict):
        raise Phase5MultiClientGateError(f"{label} must be a JSON object")
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _bool_value(document: dict[str, Any], key: str) -> bool:
    return document.get(key) is True


def _string_value(document: dict[str, Any], key: str) -> str | None:
    value = document.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _list_value(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key)
    return value if isinstance(value, list) else []


def _gate(name: str, status: str, reasons: Sequence[str], evidence: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reasons": list(reasons),
        "evidence": list(evidence),
    }


def _read_optional_manifest(evidence_dir: Path) -> tuple[dict[str, Any], list[str]]:
    manifest_path = evidence_dir / "multi-client-concurrency.json"
    if not manifest_path.is_file():
        return {}, ["missing multi-client-concurrency.json"]
    return _read_json(manifest_path, "multi-client concurrency manifest"), []


def _artifact_failures(evidence_dir: Path, manifest: dict[str, Any]) -> list[str]:
    declared = _list_value(manifest, "artifacts")
    declared_names = {item for item in declared if isinstance(item, str) and item}
    source_revision = _string_value(manifest, "source_revision")
    failures: list[str] = []
    for artifact in REQUIRED_ARTIFACTS:
        path = evidence_dir / artifact
        if artifact not in declared_names:
            failures.append(f"required artifact not declared: {artifact}")
        if not path.is_file():
            failures.append(f"missing required artifact: {artifact}")
            continue
        try:
            artifact_document = _read_json(path, artifact)
        except Phase5MultiClientGateError as error:
            failures.append(str(error))
            continue
        if artifact_document.get("schema_version") != SCHEMA_VERSION:
            failures.append(f"{artifact}: schema_version must be {SCHEMA_VERSION}")
        expected_kind = REQUIRED_ARTIFACT_KINDS[artifact]
        if artifact_document.get("kind") != expected_kind:
            failures.append(f"{artifact}: kind must be {expected_kind}")
        if source_revision and artifact_document.get("source_revision") != source_revision:
            failures.append(f"{artifact}: source_revision must match multi-client-concurrency.json")
        for field in REQUIRED_ARTIFACT_OBSERVATIONS[artifact]:
            if not _bool_value(artifact_document, field):
                failures.append(f"{artifact}: {field} must be true")
        if artifact.startswith("android-client-"):
            device = artifact_document.get("device")
            device_failures = _device_identity_failures({"devices": [device]}) if isinstance(device, dict) else [
                "device must record manufacturer, model, codename, Android release, and SDK"
            ]
            failures.extend(f"{artifact}: {failure}" for failure in device_failures)
    return failures


def _client_count(manifest: dict[str, Any]) -> int:
    value = manifest.get("client_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _stream_count(manifest: dict[str, Any]) -> int:
    value = manifest.get("stream_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _device_identity_failures(manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    devices = _list_value(manifest, "devices")
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            failures.append(f"devices[{index}] must be an object")
            continue
        manufacturer = str(device.get("manufacturer", "")).strip().lower()
        model = str(device.get("model", "")).strip().lower()
        codename = str(device.get("codename", "")).strip().lower()
        android_release = str(device.get("android_release", device.get("android_version", ""))).strip()
        sdk = device.get("sdk")
        if not manufacturer or not model or not codename:
            failures.append(f"devices[{index}] must record manufacturer, model, and codename")
        if model == "p0110" and codename != "pacific":
            failures.append("Nubia P0110 evidence must use codename pacific")
        if model == "p0110" and manufacturer not in {"nubia", "zte"}:
            failures.append("P0110 evidence must not be relabeled as another manufacturer")
        if manufacturer == "xiaomi" and codename != "fuxi":
            failures.append("Xiaomi evidence must identify codename fuxi")
        if model == "p0110" and android_release != "16":
            failures.append("current Nubia P0110 evidence must record Android 16 when used")
        if model == "p0110" and sdk not in (36, "36"):
            failures.append("current Nubia P0110 evidence must record SDK 36 when used")
    return failures


def derive_gate(evidence_dir: Path) -> dict[str, Any]:
    manifest, manifest_reasons = _read_optional_manifest(evidence_dir)
    if manifest_reasons:
        gates = [_gate("evidence_manifest", BLOCKED, manifest_reasons)]
        return _report(BLOCKED, gates, ["blocked: evidence_manifest"], evidence_dir)

    gates: list[dict[str, Any]] = []
    metadata_reasons: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        metadata_reasons.append(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("kind") != "phase5_multi_client_concurrency_evidence":
        metadata_reasons.append("kind must be phase5_multi_client_concurrency_evidence")
    if _string_value(manifest, "source_revision") is None:
        metadata_reasons.append("source_revision is required")
    gates.append(_gate("evidence_metadata", BLOCKED if metadata_reasons else PASS, metadata_reasons, ["multi-client-concurrency.json"]))

    artifact_reasons = _artifact_failures(evidence_dir, manifest)
    gates.append(_gate("retained_artifacts", BLOCKED if artifact_reasons else PASS, artifact_reasons, REQUIRED_ARTIFACTS))

    concurrency_reasons: list[str] = []
    if _client_count(manifest) < 2:
        concurrency_reasons.append("client_count must be at least 2 for multi-client evidence")
    if _stream_count(manifest) < 2:
        concurrency_reasons.append("stream_count must be at least 2 for multi-client/display evidence")
    for field in REQUIRED_TRUE_FIELDS:
        if not _bool_value(manifest, field):
            concurrency_reasons.append(f"{field} must be true")
    if _bool_value(manifest, "single_client_multiple_displays") and _client_count(manifest) < 2:
        concurrency_reasons.append("single-client multi-display evidence cannot close multi-client concurrency")
    concurrency_status = PASS if not concurrency_reasons else INSUFFICIENT
    gates.append(_gate("multi_client_concurrency", concurrency_status, concurrency_reasons, ["multi-client-concurrency.json"]))

    platform_reasons = [f"{field} must be true" for field in OPTIONAL_PLATFORM_FIELDS if not _bool_value(manifest, field)]
    gates.append(_gate("platform_owner_status", INSUFFICIENT if platform_reasons else PASS, platform_reasons, ["multi-client-concurrency.json"]))

    identity_reasons = _device_identity_failures(manifest)
    gates.append(_gate("device_identity", FAIL if identity_reasons else PASS, identity_reasons, ["multi-client-concurrency.json"]))

    if any(gate["status"] == FAIL for gate in gates):
        verdict = FAIL
    elif any(gate["status"] == BLOCKED for gate in gates):
        verdict = BLOCKED
    elif any(gate["status"] == INSUFFICIENT for gate in gates):
        verdict = INSUFFICIENT
    else:
        verdict = PASS
    reasons = [f"{gate['status']}: {gate['name']}" for gate in gates if gate["status"] != PASS]
    return _report(verdict, gates, reasons, evidence_dir)


def _report(verdict: str, gates: list[dict[str, Any]], reasons: list[str], evidence_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "verdict": verdict,
        "source": {"evidence_dir": str(evidence_dir)},
        "can_close_phase5_multi_client_display_gate": verdict == PASS,
        "can_claim_multi_client_concurrency": verdict == PASS,
        "can_use_single_client_display_evidence": False,
        "gates": gates,
        "reasons": reasons,
        "interpretation": (
            "A pass requires retained evidence for at least two simultaneous clients, "
            "distinct session/display stream ownership, transport isolation, Host route "
            "binding, input target isolation, and platform owner status. Single-client "
            "display switching remains separate evidence and cannot close this gate."
        ),
    }


def _failure_report(evidence_dir: Path, reason: str) -> dict[str, Any]:
    return _report(BLOCKED, [_gate("gate_input", BLOCKED, [reason])], [reason], evidence_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = derive_gate(args.evidence_dir)
    except (Phase5MultiClientGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.evidence_dir, str(error))
    try:
        _write_json(args.output, report)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: cannot write Phase 5 multi-client gate output: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
