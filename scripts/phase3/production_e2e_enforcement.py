#!/usr/bin/env python3
"""Verify Phase 3 production end-to-end enforcement evidence.

This checker is deliberately narrower than a deployment runner. It consumes a
reviewed manifest from a real production-shaped run and decides whether that
manifest can close the production enforcement gate. Missing deployment evidence
is reported as blocked; contradictory policy or local/synthetic evidence that is
presented as production is reported as failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase3.production_e2e_artifacts import (
    REQUIRED_ARTIFACT_TYPES,
    EnforcementError,
    Reason,
    is_public_host,
    reason as _reason,
    scan_artifact,
)


SCHEMA = "dev.vibescreen.phase3-production-e2e-enforcement/v1"
EXIT_FAIL = 2
EXIT_BLOCKED = 4
MAX_REASON_COUNT = 200
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/@+ -]{1,160}$")

REQUIRED_TOP_LEVEL = frozenset(
    {
        "schema",
        "run_id",
        "recorded_at_utc",
        "owners",
        "source",
        "production_config",
        "policy",
        "topology",
        "data_plane",
        "evidence",
    }
)

REQUIRED_OWNERS = frozenset(
    {
        "release_decision",
        "authority",
        "signaling",
        "coturn_data_plane",
        "evidence_review",
    }
)

REQUIRED_CONFIG_COMPONENTS = frozenset({"authority", "signaling", "coturn"})
REQUIRED_POLICY_FIELDS = frozenset(
    {
        "authority_source_id",
        "turn_realm",
        "maximum_session_ttl_seconds",
        "turn_credential_ttl_seconds",
        "maximum_allocations_per_device",
        "daily_bytes_per_device",
        "maximum_database_clock_skew_seconds",
    }
)


def _fail(message: str) -> NoReturn:
    raise EnforcementError(message)


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} must be a JSON object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    if not IDENTIFIER.fullmatch(value):
        _fail(f"{field} contains unsupported characters")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{field} must be boolean")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{field} must be a positive integer")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EnforcementError(f"cannot hash evidence artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _artifact_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        _fail(f"evidence artifact path must be relative and stay inside evidence root: {relative}")
    resolved_root = root.resolve()
    resolved_path = (resolved_root / path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise EnforcementError(f"evidence artifact escapes evidence root: {relative}") from exc
    return resolved_path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnforcementError(f"cannot read production enforcement manifest: {exc}") from exc
    return _object(raw, "manifest")


def _validate_shape(manifest: dict[str, Any], evidence_root: Path | None) -> list[Reason]:
    reasons: list[Reason] = []
    missing = REQUIRED_TOP_LEVEL - set(manifest)
    extra = set(manifest) - REQUIRED_TOP_LEVEL
    if missing:
        _fail(f"manifest missing required fields: {', '.join(sorted(missing))}")
    if extra:
        _fail(f"manifest contains unknown fields: {', '.join(sorted(extra))}")
    if manifest["schema"] != SCHEMA:
        _fail(f"schema must be {SCHEMA}")

    _string(manifest["run_id"], "run_id")
    _string(manifest["recorded_at_utc"], "recorded_at_utc")

    owners = _object(manifest["owners"], "owners")
    owner_missing = REQUIRED_OWNERS - set(owners)
    if owner_missing:
        reasons.append(
            _reason("blocked", "owners", f"missing owners: {', '.join(sorted(owner_missing))}")
        )
    for owner_name in REQUIRED_OWNERS & set(owners):
        owner = _object(owners[owner_name], f"owners.{owner_name}")
        _string(owner.get("team"), f"owners.{owner_name}.team")
        _string(owner.get("contact"), f"owners.{owner_name}.contact")

    source = _object(manifest["source"], "source")
    commit = _string(source.get("commit"), "source.commit")
    if not HEX_COMMIT.fullmatch(commit):
        reasons.append(_reason("blocked", "source.commit", "commit must be a 40-character hex SHA"))
    if _bool(source.get("dirty"), "source.dirty"):
        reasons.append(_reason("blocked", "source.dirty", "production gate requires clean committed source"))

    evidence = _object(manifest["evidence"], "evidence")
    commands = evidence.get("rerun_commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item for item in commands):
        reasons.append(_reason("blocked", "evidence.rerun_commands", "at least one rerun command is required"))
    artifacts = evidence.get("artifacts")
    artifact_types: set[str] = set()
    if not isinstance(artifacts, list) or not artifacts:
        reasons.append(_reason("blocked", "evidence.artifacts", "at least one reviewed artifact is required"))
    else:
        for index, artifact_value in enumerate(artifacts):
            artifact = _object(artifact_value, f"evidence.artifacts[{index}]")
            artifact_type = _string(artifact.get("type"), f"evidence.artifacts[{index}].type")
            if artifact_type not in REQUIRED_ARTIFACT_TYPES:
                reasons.append(
                    _reason("fail", f"evidence.artifacts[{index}].type", "unsupported artifact type")
                )
            if artifact_type in artifact_types:
                reasons.append(
                    _reason("fail", f"evidence.artifacts[{index}].type", "duplicate artifact type")
                )
            artifact_types.add(artifact_type)
            relative_path = _string(artifact.get("path"), f"evidence.artifacts[{index}].path")
            digest = _string(artifact.get("sha256"), f"evidence.artifacts[{index}].sha256")
            if not HEX_SHA256.fullmatch(digest):
                reasons.append(
                    _reason("blocked", f"evidence.artifacts[{index}].sha256", "artifact digest must be sha256 hex")
                )
            if evidence_root is not None:
                path = _artifact_path(evidence_root, relative_path)
                if not path.is_file():
                    reasons.append(
                        _reason("blocked", f"evidence.artifacts[{index}].path", "artifact file is missing")
                    )
                    continue
                actual_digest = _sha256(path)
                if HEX_SHA256.fullmatch(digest) and actual_digest != digest:
                    reasons.append(
                        _reason("fail", f"evidence.artifacts[{index}].sha256", "artifact digest does not match file")
                    )
                reasons.extend(scan_artifact(path, artifact_type, manifest))
    missing_artifact_types = REQUIRED_ARTIFACT_TYPES - artifact_types
    if missing_artifact_types:
        reasons.append(
            _reason(
                "blocked",
                "evidence.artifacts.type",
                f"missing production artifact types: {', '.join(sorted(missing_artifact_types))}",
            )
        )
    return reasons


def _config_present(component: dict[str, Any], name: str) -> list[Reason]:
    reasons: list[Reason] = []
    present = _bool(component.get("present"), f"production_config.{name}.present")
    if not present:
        reasons.append(_reason("blocked", f"production_config.{name}.present", "real deployed configuration is missing"))
    if component.get("source") != "deployed-secret-manager":
        reasons.append(
            _reason(
                "blocked",
                f"production_config.{name}.source",
                "configuration must come from reviewed deployed secret manager material",
            )
        )
    if not _bool(component.get("tls_verify_full"), f"production_config.{name}.tls_verify_full"):
        category = "fail" if present else "blocked"
        reasons.append(_reason(category, f"production_config.{name}.tls_verify_full", "TLS hostname/certificate verification is required"))
    return reasons


def _validate_config(manifest: dict[str, Any]) -> list[Reason]:
    config = _object(manifest["production_config"], "production_config")
    reasons: list[Reason] = []
    missing = REQUIRED_CONFIG_COMPONENTS - set(config)
    if missing:
        reasons.append(_reason("blocked", "production_config", f"missing components: {', '.join(sorted(missing))}"))
    for name in sorted(REQUIRED_CONFIG_COMPONENTS & set(config)):
        component = _object(config[name], f"production_config.{name}")
        reasons.extend(_config_present(component, name))

    authority = _object(config["authority"], "production_config.authority") if "authority" in config else None
    signaling = _object(config["signaling"], "production_config.signaling") if "signaling" in config else None
    coturn = _object(config["coturn"], "production_config.coturn") if "coturn" in config else None

    if authority is not None and authority.get("present") is True and authority.get("http_public_ingress") is not False:
        reasons.append(_reason("fail", "production_config.authority.http_public_ingress", "Authority HTTP must remain private/loopback only"))
    if signaling is not None and signaling.get("present") is True:
        if signaling.get("mode") != "production_authority":
            reasons.append(_reason("fail", "production_config.signaling.mode", "signaling must run in production_authority mode"))
        if signaling.get("storage_backend") != "postgres":
            reasons.append(_reason("fail", "production_config.signaling.storage_backend", "signaling production routing must use PostgreSQL"))
    if coturn is not None:
        coturn_category = "fail" if coturn.get("present") is True else "blocked"
        if coturn.get("exporter") != "deployed":
            reasons.append(_reason(coturn_category, "production_config.coturn.exporter", "trusted coturn allocation exporter is not deployed"))
        if coturn.get("disconnect_executor") != "deployed":
            reasons.append(_reason(coturn_category, "production_config.coturn.disconnect_executor", "active-allocation disconnect executor is not deployed"))
    return reasons


def _policy_components(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in ("authority", "signaling", "coturn"):
        component = _object(policy.get(name), f"policy.{name}")
        missing = REQUIRED_POLICY_FIELDS - set(component)
        extra = set(component) - REQUIRED_POLICY_FIELDS
        if missing:
            _fail(f"policy.{name} missing required fields: {', '.join(sorted(missing))}")
        if extra:
            _fail(f"policy.{name} contains unknown fields: {', '.join(sorted(extra))}")
        for field in ("authority_source_id", "turn_realm"):
            _string(component[field], f"policy.{name}.{field}")
        for field in REQUIRED_POLICY_FIELDS - {"authority_source_id", "turn_realm"}:
            _positive_int(component[field], f"policy.{name}.{field}")
        result[name] = component
    return result


def _validate_policy(manifest: dict[str, Any]) -> list[Reason]:
    policy = _object(manifest["policy"], "policy")
    components = _policy_components(policy)
    reasons: list[Reason] = []
    authority = components["authority"]
    for name in ("signaling", "coturn"):
        component = components[name]
        for field in REQUIRED_POLICY_FIELDS:
            if component[field] != authority[field]:
                reasons.append(
                    _reason(
                        "fail",
                        f"policy.{name}.{field}",
                        f"does not match authority policy value for {field}",
                    )
                )
    return reasons


def _validate_topology(manifest: dict[str, Any]) -> list[Reason]:
    topology = _object(manifest["topology"], "topology")
    reasons: list[Reason] = []
    if topology.get("classification") != "public_internet":
        reasons.append(_reason("fail", "topology.classification", "classification must be public_internet"))
    for field in ("local_loopback", "synthetic_peer", "public_route_observed", "remote_turn_observed"):
        value = _bool(topology.get(field), f"topology.{field}")
        expected = field in {"public_route_observed", "remote_turn_observed"}
        if value != expected:
            category = "fail" if field in {"local_loopback", "synthetic_peer"} else "blocked"
            reasons.append(_reason(category, f"topology.{field}", f"expected {expected}"))
    hosts = topology.get("public_endpoint_hosts")
    if not isinstance(hosts, list) or not hosts:
        reasons.append(_reason("blocked", "topology.public_endpoint_hosts", "public endpoint host observations are required"))
    else:
        for index, host_value in enumerate(hosts):
            host = _string(host_value, f"topology.public_endpoint_hosts[{index}]")
            if not is_public_host(host):
                reasons.append(_reason("fail", f"topology.public_endpoint_hosts[{index}]", "host is not public-routable evidence"))
    return reasons


def _validate_data_plane(manifest: dict[str, Any]) -> list[Reason]:
    data_plane = _object(manifest["data_plane"], "data_plane")
    reasons: list[Reason] = []
    required_true = (
        "real_screencapturekit_capture",
        "android_mediacodec_decode",
        "application_aead_verified",
        "coturn_allocation_observed",
        "coturn_disconnect_observed",
        "authority_admission_observed",
        "signaling_authorization_observed",
    )
    for field in required_true:
        if not _bool(data_plane.get(field), f"data_plane.{field}"):
            reasons.append(_reason("blocked", f"data_plane.{field}", "required production data-plane observation is missing"))
    soak_minutes = _positive_int(data_plane.get("mixed_route_soak_minutes"), "data_plane.mixed_route_soak_minutes")
    if soak_minutes < 120:
        reasons.append(_reason("blocked", "data_plane.mixed_route_soak_minutes", "mixed-route production soak must be at least 120 minutes"))
    return reasons


def evaluate_manifest(manifest: dict[str, Any], evidence_root: Path | None = None) -> dict[str, Any]:
    reasons: list[Reason] = []
    reasons.extend(_validate_shape(manifest, evidence_root))
    reasons.extend(_validate_config(manifest))
    reasons.extend(_validate_policy(manifest))
    reasons.extend(_validate_topology(manifest))
    reasons.extend(_validate_data_plane(manifest))
    if len(reasons) > MAX_REASON_COUNT:
        _fail(f"too many enforcement findings: {len(reasons)}")

    categories = {reason.category for reason in reasons}
    status = "fail" if "fail" in categories else "blocked" if "blocked" in categories else "pass"
    return {
        "schema": SCHEMA,
        "run_id": manifest["run_id"],
        "status": status,
        "owners": manifest["owners"],
        "reasons": [reason.as_dict() for reason in reasons],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Phase 3 production E2E enforcement evidence")
    parser.add_argument("--manifest", required=True, type=Path, help="production enforcement manifest JSON")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="directory containing referenced artifacts; defaults to the manifest directory",
    )
    parser.add_argument("--output", type=Path, help="optional normalized verification result JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_path = args.manifest.resolve()
        result = evaluate_manifest(
            _load_json(manifest_path),
            (args.evidence_root or manifest_path.parent).resolve(),
        )
    except EnforcementError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL
    if args.output is not None:
        write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "pass":
        return 0
    if result["status"] == "blocked":
        return EXIT_BLOCKED
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
