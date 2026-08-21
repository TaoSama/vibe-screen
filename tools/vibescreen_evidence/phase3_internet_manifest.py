"""Create a Phase 3 public Internet evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

try:
    from scripts.phase3.public_internet_evidence import (
        REQUIRED_DEPLOYMENT_PREREQUISITES,
        parse_turn_uri,
        require_public_remote_host,
    )
except ModuleNotFoundError:  # pragma: no cover - only used outside repository root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.phase3.public_internet_evidence import (  # type: ignore[no-redef]
        REQUIRED_DEPLOYMENT_PREREQUISITES,
        parse_turn_uri,
        require_public_remote_host,
    )


KIND = "phase3_public_internet_manifest"
MINIMUM_DURATION_SECONDS = 2 * 60 * 60
REQUIRED_GATES = [
    "public_signaling_tls_readiness",
    "remote_turn_tls_readiness",
    "authority_backed_relay_admission",
    "remote_turn_allocation",
    "relayed_packet_exchange",
    "real_screen_capture_to_android_decoder",
    "touch_keyboard_input_over_internet",
    "wifi_cellular_or_independent_network_handoff",
    "cross_service_revocation",
    "internet_soak_2h",
    "nonce_reuse_absence",
]
REQUIRED_ARTIFACTS = [
    "README.md",
    "phase3-internet-manifest.json",
    "preflight.json",
    "remote-turn-verifier.json",
    "soak-summary.json",
    "soak-samples.jsonl",
    "host-telemetry.jsonl",
    "relay-usage.jsonl",
    "network-handoff-notes.md",
    "privacy-scan.json",
    "SHA256SUMS",
]
REQUIRED_BOUNDARIES = [
    "not_local_loopback",
    "not_forced_local_coturn",
    "not_synthetic_protocol_v1_device",
    "real_remote_turn",
    "public_internet_path",
    "real_screen_capture",
    "physical_android_device",
]


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"failed to read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object: {path}")
    return value


def _sha256(path: Path, label: str) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ManifestError(f"failed to read {label}: {error}") from error
    return hashlib.sha256(content).hexdigest()


def _require_text(value: str | None, option: str) -> str:
    if value is None or not value.strip():
        raise ManifestError(f"{option} is required")
    return value.strip()


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_turn_uris(turn_uris: Sequence[str]) -> list[dict[str, Any]]:
    if not turn_uris:
        raise ManifestError("at least one --turn-uri is required")
    parsed = []
    turns_count = 0
    for uri_text in turn_uris:
        try:
            uri = parse_turn_uri(uri_text)
            addresses = require_public_remote_host(uri.host)
        except Exception as error:
            raise ManifestError(f"invalid public TURN URI: {error}") from error
        if uri.scheme == "turns":
            turns_count += 1
        parsed.append(
            {
                "scheme": uri.scheme,
                "host_hash": hashlib.sha256(uri.host.encode("utf-8")).hexdigest(),
                "resolved_address_hashes": [
                    hashlib.sha256(address.encode("utf-8")).hexdigest()
                    for address in addresses
                ],
                "port": uri.port,
                "transport": uri.transport,
            }
        )
    if turns_count == 0:
        raise ManifestError("at least one turns: URI is required")
    return parsed


def _validate_public_https_origin(value: str, option: str) -> str:
    origin = _require_text(value, option)
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise ManifestError(f"{option} must be an HTTPS origin without path, query, fragment, or userinfo")
    try:
        require_public_remote_host(parsed.hostname)
    except Exception as error:
        raise ManifestError(f"{option} must use a public host: {error}") from error
    return origin


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    turn_realm: str,
    turn_uris: Sequence[str],
    authority_source_id: str,
    tls_certificate: Path,
    signaling_origin: str,
    relay_origin: str,
    duration_seconds: int,
    planned_network_handoffs: Sequence[str],
    notes: str | None,
) -> dict[str, Any]:
    if duration_seconds < MINIMUM_DURATION_SECONDS:
        raise ManifestError("--duration-seconds must be at least 7200 for a Phase 3 Internet soak")
    if not planned_network_handoffs:
        raise ManifestError("--planned-network-handoffs is required")
    realm = _require_text(turn_realm, "--turn-realm")
    source_id = _require_text(authority_source_id, "--authority-source-id")
    signaling = _validate_public_https_origin(signaling_origin, "--signaling-origin")
    relay = _validate_public_https_origin(relay_origin, "--relay-origin")
    try:
        require_public_remote_host(realm)
    except Exception as error:
        raise ManifestError(f"--turn-realm must be public DNS: {error}") from error
    parsed_uris = _validate_turn_uris(turn_uris)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": list(command),
        "repository": repository_state(repo.resolve()),
        "deployment": {
            "turn_realm_hash": hashlib.sha256(realm.encode("utf-8")).hexdigest(),
            "turn_uris": parsed_uris,
            "authority_source_id_hash": hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            "tls_certificate_sha256": _sha256(tls_certificate, "TLS certificate"),
            "signaling_origin_hash": hashlib.sha256(signaling.encode("utf-8")).hexdigest(),
            "relay_origin_hash": hashlib.sha256(relay.encode("utf-8")).hexdigest(),
        },
        "session": {
            "transport": "internet",
            "duration_seconds": duration_seconds,
            "planned_network_handoffs": list(planned_network_handoffs),
        },
        "deployment_prerequisites": list(REQUIRED_DEPLOYMENT_PREREQUISITES),
        "evidence_boundaries": list(REQUIRED_BOUNDARIES),
        "required_gates": list(REQUIRED_GATES),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "privacy": {
            "raw_endpoints_recorded": False,
            "sensitive_values_recorded": False,
            "raw_device_identifiers_recorded": False,
        },
        "notes": notes,
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--turn-realm", required=True)
    parser.add_argument("--turn-uri", action="append", default=[])
    parser.add_argument("--authority-source-id", required=True)
    parser.add_argument("--tls-certificate", type=Path, required=True)
    parser.add_argument("--signaling-origin", required=True)
    parser.add_argument("--relay-origin", required=True)
    parser.add_argument("--duration-seconds", type=int, default=MINIMUM_DURATION_SECONDS)
    parser.add_argument("--planned-network-handoffs", required=True)
    parser.add_argument("--notes")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        manifest = build_manifest(
            command=command,
            repo=args.repo,
            turn_realm=args.turn_realm,
            turn_uris=args.turn_uri,
            authority_source_id=args.authority_source_id,
            tls_certificate=args.tls_certificate,
            signaling_origin=args.signaling_origin,
            relay_origin=args.relay_origin,
            duration_seconds=args.duration_seconds,
            planned_network_handoffs=_split_csv(args.planned_network_handoffs),
            notes=args.notes,
        )
        _write_json(args.output, manifest)
    except (ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
