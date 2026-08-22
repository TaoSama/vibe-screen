"""Evaluate the Phase 3 production end-to-end release evidence gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .phase3_production_e2e_manifest import (
    AGGREGATE_OWNER,
    KIND as MANIFEST_KIND,
    READINESS_GATES,
    REQUIRED_PRODUCTION_GATES,
    SCOPE_PRS,
    SOURCE_DOCS,
)

GATE_KIND = "phase3_production_e2e_gate"
PASS_STATUSES = {"pass", "passed"}
READINESS_STATUSES = {"readiness", "readiness-only", "passed-readiness"}
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MINIMUM_SOAK_SECONDS = 2 * 60 * 60
MAX_EVIDENCE_SCAN_BYTES = 1024 * 1024
PRODUCTION_EVIDENCE_REJECTION_MARKERS = (
    "local_loopback_only",
    "synthetic_protocol_v1_device",
    "synthetic_videotoolbox_input_frames",
    "no_android_device_or_ui",
    "no_real_screen_capture",
    "no_android_mediacodec_decode",
    "no_public_internet_path",
    b'"capture_or_stream_server_started": false',
    b'"synthetic_device": true',
    "synthetic Protocol v1 harness",
)

INTERPRETATION = (
    "A pass means the current-base Phase 3 release evidence contains a real "
    "public Internet and remote TURN run with ScreenCaptureKit/CGDisplayStream "
    "Host capture decoded by Android MediaCodec on a physical device, plus "
    "production revocation propagation, privacy scan, latency evidence, and a "
    "two-hour mixed direct/relay/network-change soak. Local loopback, forced "
    "local coturn, historical-source, emulator, simulator, or synthetic Protocol "
    "v1 evidence remains readiness only."
)


class Phase3ProductionE2EGateError(ValueError):
    """Raised when a Phase 3 production E2E manifest cannot be evaluated."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Phase3ProductionE2EGateError(
            f"cannot read Phase 3 production E2E manifest: {error}"
        ) from error
    if not isinstance(document, dict):
        raise Phase3ProductionE2EGateError(
            "Phase 3 production E2E manifest must be a JSON object"
        )
    return document


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Phase3ProductionE2EGateError(
            f"manifest schema violation: {name} must be an object"
        )
    return value


def _require_fields(record: dict[str, Any], fields: set[str], name: str) -> None:
    missing = sorted(field for field in fields if field not in record)
    if missing:
        raise Phase3ProductionE2EGateError(
            f"manifest schema violation: {name} missing required field(s): {', '.join(missing)}"
        )


def _check(
    passed: bool,
    expected: str,
    *,
    evidence: list[str] | None = None,
    blocking: bool = False,
    measured: Any = None,
) -> dict[str, Any]:
    result = {
        "passed": passed,
        "expected": expected,
        "evidence": evidence or [],
        "blocking": blocking,
    }
    if measured is not None:
        result["measured"] = measured
    return result


def _status_pass(value: Any) -> bool:
    return isinstance(value, str) and value in PASS_STATUSES


def _status_readiness(value: Any) -> bool:
    return isinstance(value, str) and value in READINESS_STATUSES


def _validate_manifest_contract(manifest: dict[str, Any]) -> None:
    _require_fields(
        manifest,
        {
            "schema_version",
            "kind",
            "run_id",
            "created_at",
            "command",
            "repository",
            "source_root",
            "owner",
            "scope_prs",
            "source_docs",
            "production_environment",
            "device",
            "host",
            "android_artifact",
            "claims",
            "gates",
            "required_artifacts",
            "limitations",
            "notes",
        },
        "manifest",
    )
    _require_object(manifest.get("repository"), "repository")
    _require_object(manifest.get("owner"), "owner")
    _require_object(manifest.get("production_environment"), "production_environment")
    _require_object(manifest.get("device"), "device")
    _require_object(manifest.get("host"), "host")
    _require_object(manifest.get("android_artifact"), "android_artifact")
    _require_object(manifest.get("claims"), "claims")
    gates = _require_object(manifest.get("gates"), "gates")
    for name in [*REQUIRED_PRODUCTION_GATES, *READINESS_GATES]:
        gate = _require_object(gates.get(name), f"gates.{name}")
        _require_fields(
            gate,
            {"status", "category", "requirement", "blocking", "evidence", "notes"},
            f"gates.{name}",
        )
        if not isinstance(gate.get("evidence"), list):
            raise Phase3ProductionE2EGateError(
                f"manifest schema violation: gates.{name}.evidence must be an array"
            )
        if not isinstance(gate.get("notes"), list):
            raise Phase3ProductionE2EGateError(
                f"manifest schema violation: gates.{name}.notes must be an array"
            )


def _source_root(manifest: dict[str, Any], manifest_path: Path) -> Path:
    value = manifest.get("source_root")
    if not _non_empty_string(value):
        raise Phase3ProductionE2EGateError(
            "manifest schema violation: source_root must be a non-empty string"
        )
    root = Path(str(value)).expanduser()
    if not root.is_absolute():
        root = manifest_path.parent / root
    return root


def _path_exists(path: str, source_root: Path, manifest_path: Path) -> bool:
    return _resolve_existing_path(path, source_root, manifest_path) is not None


def _resolve_existing_path(
    path: str, source_root: Path, manifest_path: Path
) -> Path | None:
    candidate = Path(path)
    roots = [source_root, manifest_path.parent]
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    for root in roots:
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return None


def _marker_bytes(marker: str | bytes) -> bytes:
    if isinstance(marker, bytes):
        return marker.lower()
    return marker.encode("utf-8").lower()


def _json_contains_pair(value: Any, key: str, expected: Any) -> bool:
    if isinstance(value, dict):
        if value.get(key) == expected:
            return True
        return any(_json_contains_pair(item, key, expected) for item in value.values())
    if isinstance(value, list):
        return any(_json_contains_pair(item, key, expected) for item in value)
    return False


def _evidence_rejection_hits(
    evidence: list[str], source_root: Path, manifest_path: Path
) -> list[str]:
    hits: list[str] = []
    marker_bytes = {marker: _marker_bytes(marker) for marker in PRODUCTION_EVIDENCE_REJECTION_MARKERS}
    for evidence_path in evidence:
        path_bytes = evidence_path.encode("utf-8", errors="ignore").lower()
        for marker, encoded_marker in marker_bytes.items():
            if encoded_marker in path_bytes:
                hits.append(f"{evidence_path}: {marker!s}")

        resolved = _resolve_existing_path(evidence_path, source_root, manifest_path)
        if resolved is None or not resolved.is_file():
            continue
        try:
            with resolved.open("rb") as evidence_file:
                raw_sample = evidence_file.read(MAX_EVIDENCE_SCAN_BYTES)
        except OSError:
            continue
        sample = raw_sample.lower()
        for marker, encoded_marker in marker_bytes.items():
            if encoded_marker in sample:
                hits.append(f"{evidence_path}: {marker!s}")
        try:
            decoded = json.loads(raw_sample.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _json_contains_pair(decoded, "capture_or_stream_server_started", False):
            hits.append(f"{evidence_path}: capture_or_stream_server_started=false")
        if _json_contains_pair(decoded, "synthetic_device", True):
            hits.append(f"{evidence_path}: synthetic_device=true")
    return sorted(set(hits))


def _metadata_checks(
    manifest: dict[str, Any], manifest_path: Path
) -> dict[str, dict[str, Any]]:
    owner = manifest.get("owner") if isinstance(manifest.get("owner"), dict) else {}
    repository = manifest.get("repository") if isinstance(manifest.get("repository"), dict) else {}
    source_root = _source_root(manifest, manifest_path)
    source_docs = set(_string_list(manifest.get("source_docs")))
    source_doc_exists = [
        (source_root / path).is_file() if not Path(path).is_absolute() else Path(path).is_file()
        for path in SOURCE_DOCS
    ]
    scope_prs = set(_string_list(manifest.get("scope_prs")))
    return {
        "schema_version": _check(manifest.get("schema_version") == SCHEMA_VERSION, SCHEMA_VERSION),
        "kind": _check(manifest.get("kind") == MANIFEST_KIND, MANIFEST_KIND),
        "aggregate_owner": _check(
            owner.get("aggregate") == AGGREGATE_OWNER,
            AGGREGATE_OWNER,
            evidence=[str(owner.get("aggregate"))] if owner.get("aggregate") else [],
        ),
        "scope_prs": _check(
            set(SCOPE_PRS).issubset(scope_prs),
            "all Phase 3 current-base PRs are listed in scope",
            evidence=sorted(scope_prs),
        ),
        "source_docs": _check(
            set(SOURCE_DOCS).issubset(source_docs) and all(source_doc_exists),
            "README and Phase 3 PRD/TECH/TEST/OPERATIONS are referenced and present",
            evidence=sorted(source_docs),
        ),
        "clean_repository": _check(
            repository.get("dirty") is False,
            "production evidence is bound to a clean source tree",
            evidence=_string_list(repository.get("status_porcelain")),
            blocking=True,
        ),
    }


def _environment_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    environment = manifest.get("production_environment")
    if not isinstance(environment, dict):
        environment = {}
    expectations = {
        "public_internet_path": "genuine public Internet/NAT path observed",
        "remote_turn": "remote TURN allocation observed",
        "production_authority": "production Authority admission used",
        "managed_postgresql": "managed PostgreSQL or production-equivalent durable database recorded",
        "tls_public_ingress": "public TLS/private ingress layer recorded",
        "ntp_monitoring": "NTP or clock-skew monitoring evidence retained",
    }
    return {
        key: _check(environment.get(key) is True, expected, blocking=True)
        for key, expected in expectations.items()
    }


def _device_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    device = manifest.get("device") if isinstance(manifest.get("device"), dict) else {}
    identity = {
        key: device.get(key)
        for key in ("manufacturer", "model", "codename", "android_release", "sdk")
    }
    evidence = _string_list(device.get("evidence"))
    label = str(device.get("identity_label") or "")
    normalized = {key: str(value or "").strip().lower() for key, value in identity.items()}
    is_p0110 = (
        normalized.get("manufacturer") == "nubia"
        and normalized.get("model") == "p0110"
        and normalized.get("codename") == "pacific"
    )
    mislabeled_p0110 = is_p0110 and any(term in label.lower() for term in ("xiaomi", "fuxi"))
    return {
        "physical_android_device": _check(
            device.get("runtime_class") == "physical_android_device",
            "physical Android device recorded",
            evidence=[str(device.get("runtime_class"))] if device.get("runtime_class") else evidence,
            blocking=True,
        ),
        "android_identity": _check(
            all(_non_empty_string(value) for value in identity.values()),
            "manufacturer, model, codename, Android release, and SDK are recorded",
            evidence=[f"{key}={value}" for key, value in identity.items() if value],
            blocking=True,
        ),
        "nubia_identity_guard": _check(
            not mislabeled_p0110,
            "Nubia P0110/pacific evidence is not relabeled as Xiaomi/fuxi",
            evidence=[label] if label else [],
            blocking=True,
        ),
        "device_evidence": _check(
            bool(evidence),
            "device identity and UI evidence paths are retained",
            evidence=evidence,
            blocking=True,
        ),
    }


def _host_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    host = manifest.get("host") if isinstance(manifest.get("host"), dict) else {}
    evidence = _string_list(host.get("evidence"))
    capture_api = host.get("capture_api")
    return {
        "real_capture_api": _check(
            capture_api in {"ScreenCaptureKit", "CGDisplayStream"},
            "Host capture API is ScreenCaptureKit or CGDisplayStream",
            evidence=[str(capture_api)] if capture_api else evidence,
            blocking=True,
        ),
        "real_capture_source": _check(
            host.get("capture_source") == "real_display",
            "Host capture source is a real display, not synthetic pixels",
            evidence=[str(host.get("capture_source"))] if host.get("capture_source") else evidence,
            blocking=True,
        ),
        "host_build_identity": _check(
            _non_empty_string(host.get("build_identity")),
            "Host build identity or hash is recorded",
            evidence=[str(host.get("build_identity"))] if host.get("build_identity") else [],
            blocking=True,
        ),
        "screen_recording_permission": _check(
            host.get("screen_recording_permission") == "granted",
            "Screen Recording permission was granted for the recorded run",
            evidence=[str(host.get("screen_recording_permission"))]
            if host.get("screen_recording_permission")
            else [],
            blocking=True,
        ),
        "host_evidence": _check(
            bool(evidence),
            "Host logs/version/capture evidence paths are retained",
            evidence=evidence,
            blocking=True,
        ),
    }


def _artifact_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifact = manifest.get("android_artifact") if isinstance(manifest.get("android_artifact"), dict) else {}
    apk_sha = artifact.get("apk_sha256")
    evidence = _string_list(artifact.get("evidence"))
    return {
        "apk_sha256": _check(
            isinstance(apk_sha, str) and HASH_RE.fullmatch(apk_sha) is not None,
            "Android APK SHA-256 is a 64-character hex digest",
            evidence=[apk_sha] if isinstance(apk_sha, str) else [],
            blocking=True,
        ),
        "apk_evidence": _check(
            bool(evidence),
            "APK version/install evidence paths are retained",
            evidence=evidence,
            blocking=True,
        ),
    }


def _gate_checks(
    manifest: dict[str, Any], manifest_path: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    source_root = _source_root(manifest, manifest_path)
    production: dict[str, dict[str, Any]] = {}
    readiness: dict[str, dict[str, Any]] = {}
    for name, requirement in REQUIRED_PRODUCTION_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        evidence = _string_list(record.get("evidence"))
        existing = [path for path in evidence if _path_exists(path, source_root, manifest_path)]
        production[name] = _check(
            _status_pass(record.get("status")) and bool(evidence) and len(existing) == len(evidence),
            requirement,
            evidence=evidence,
            blocking=True,
            measured=record.get("status"),
        )
        if evidence and len(existing) != len(evidence):
            production[name]["missing_artifacts"] = [
                path for path in evidence if path not in existing
            ]
    for name, requirement in READINESS_GATES.items():
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        evidence = _string_list(record.get("evidence"))
        readiness[name] = _check(
            _status_pass(record.get("status")) or _status_readiness(record.get("status")),
            requirement,
            evidence=evidence,
            blocking=False,
            measured=record.get("status"),
        )
    return production, readiness


def _production_evidence_substitution_checks(
    manifest: dict[str, Any], manifest_path: Path
) -> dict[str, dict[str, Any]]:
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    source_root = _source_root(manifest, manifest_path)
    checks: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_PRODUCTION_GATES:
        record = gates.get(name) if isinstance(gates.get(name), dict) else {}
        evidence = _string_list(record.get("evidence"))
        hits = _evidence_rejection_hits(evidence, source_root, manifest_path)
        checks[name] = _check(
            not hits,
            "production evidence must not contain local/synthetic/readiness limitation markers",
            evidence=hits,
            blocking=True,
        )
    return checks


def _claim_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims = manifest.get("claims") if isinstance(manifest.get("claims"), dict) else {}
    expectations = {
        "local_loopback_used_for_production": "local loopback is not used for production gate closure",
        "synthetic_protocol_v1_used_for_production": "synthetic Protocol v1 harness is not used for production gate closure",
        "simulator_or_emulator_used_for_production": "simulator or emulator evidence is not used for production gate closure",
        "legacy_plaintext_fallback_used": "legacy plaintext fallback is not used for Phase 3 production evidence",
        "historical_or_stale_source_used_for_current_gate": "historical or stale-source evidence is not used for current-base gate closure",
    }
    return {
        key: _check(
            claims.get(key) is not True,
            expected,
            blocking=True,
            measured=claims.get(key),
        )
        for key, expected in expectations.items()
    }


def _soak_seconds(manifest: dict[str, Any]) -> float | None:
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    soak = gates.get("mixed_route_soak") if isinstance(gates.get("mixed_route_soak"), dict) else {}
    metrics = soak.get("metrics") if isinstance(soak.get("metrics"), dict) else {}
    value = metrics.get("duration_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _duration_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    duration = _soak_seconds(manifest)
    return {
        "mixed_route_soak_duration": _check(
            duration is not None and duration >= MINIMUM_SOAK_SECONDS,
            "mixed-route soak duration is at least two hours",
            blocking=True,
            measured=duration,
        )
    }


def derive_gate(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = _load_json(manifest_path)
        _validate_manifest_contract(manifest)
    except Phase3ProductionE2EGateError as error:
        return _failure_report(manifest_path, str(error))

    metadata = _metadata_checks(manifest, manifest_path)
    environment = _environment_checks(manifest)
    device = _device_checks(manifest)
    host = _host_checks(manifest)
    artifact = _artifact_checks(manifest)
    production_gates, readiness_gates = _gate_checks(manifest, manifest_path)
    evidence_substitutions = _production_evidence_substitution_checks(
        manifest, manifest_path
    )
    claims = _claim_checks(manifest)
    duration = _duration_checks(manifest)

    required_groups = {
        **metadata,
        **environment,
        **device,
        **host,
        **artifact,
        **production_gates,
        **claims,
        **duration,
    }
    blocking_missing = [name for name, item in required_groups.items() if not item["passed"]]
    readiness_present = [
        name
        for name, item in readiness_gates.items()
        if item["passed"] and item.get("evidence")
    ]
    readiness_statuses = [
        name
        for name, item in production_gates.items()
        if _status_readiness(item.get("measured"))
    ]
    substitution_failures = [
        name for name, item in claims.items() if item.get("measured") is True
    ]
    substitution_failures.extend(
        f"production_evidence_substitution:{name}"
        for name, item in evidence_substitutions.items()
        if not item["passed"]
    )

    if substitution_failures:
        verdict = "fail"
    elif blocking_missing:
        verdict = "insufficient" if readiness_present or readiness_statuses else "blocked"
    else:
        verdict = "pass"

    reasons: list[str] = []
    reasons.extend(f"fail: {name}" for name in substitution_failures)
    reasons.extend(f"blocked: {name}" for name in blocking_missing)
    reasons.extend(f"readiness-only: {name}" for name in readiness_present)
    reasons.extend(f"readiness-only: {name}" for name in readiness_statuses)

    can_close = verdict == "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "complete",
        "verdict": verdict,
        "run_id": manifest.get("run_id"),
        "owner": manifest.get("owner"),
        "source": {"manifest": str(manifest_path)},
        "can_close_phase3_production_e2e": can_close,
        "can_claim_public_internet_release": can_close,
        "can_claim_real_screen_capture_android_decode": can_close,
        "can_claim_revocation_soak_enforcement": can_close,
        "checks": {
            "metadata": metadata,
            "production_environment": environment,
            "device": device,
            "host": host,
            "android_artifact": artifact,
            "production_gates": production_gates,
            "readiness_gates": readiness_gates,
            "evidence_substitutions": evidence_substitutions,
            "claims": claims,
            "duration": duration,
        },
        "reasons": reasons,
        "interpretation": INTERPRETATION,
    }


def _failure_report(manifest_path: Path, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": GATE_KIND,
        "derivation_status": "failed",
        "verdict": "blocked",
        "run_id": None,
        "owner": None,
        "source": {"manifest": str(manifest_path)},
        "can_close_phase3_production_e2e": False,
        "can_claim_public_internet_release": False,
        "can_claim_real_screen_capture_android_decode": False,
        "can_claim_revocation_soak_enforcement": False,
        "checks": {},
        "reasons": [reason],
        "interpretation": INTERPRETATION,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = derive_gate(args.manifest)
    except (Phase3ProductionE2EGateError, OSError, TypeError, ValueError) as error:
        report = _failure_report(args.manifest, str(error))
    try:
        write_json(args.output, report)
    except (OSError, TypeError, ValueError):
        print("error: Phase 3 production E2E gate output could not be written", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("verdict") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
