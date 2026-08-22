"""Build and validate the allowlist-only Phase 3 CI artifact tree."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from scripts.phase3_webrtc.model import (
    E2EFailure,
    EVIDENCE_SCHEMA,
    PUBLIC_DIAGNOSTIC_SCHEMA,
    PUBLIC_EVIDENCE_SCHEMA,
    PUBLIC_GATE_FAILURE_SCHEMA,
    SUPPORTED_CANDIDATE_PROTOCOLS,
    SUPPORTED_CANDIDATE_TYPES,
    SUPPORTED_COTURN_VERSIONS,
)
from scripts.phase3_webrtc.privacy import write_private_text
from scripts.phase3_webrtc.public_schema import (
    DIAGNOSTIC_INPUTS,
    PUBLIC_LIMITATIONS,
    PUBLIC_PATHS,
    REVISION_PATTERN,
    expect_bool as _expect_bool,
    expect_exact_keys as _expect_exact_keys,
    expect_hash as _expect_hash,
    expect_mapping as _expect_mapping,
    expect_nonnegative_int as _expect_nonnegative_int,
    expect_string as _expect_string,
    read_json_file as _read_json_file,
    validate_public_artifact_tree,
)

CANDIDATE_PAIR_PATTERN = re.compile(
    r"^(direct|relay)\(local=([a-z0-9_-]+),remote=([a-z0-9_-]+),"
    r"protocol=([a-z0-9_-]+)\)$"
)
APPLICATION_E2EE_PROOF = "AES-256-GCM Protocol v1 record layer pass"
PRODUCT_SESSION_HOST = "InternetProductSession"
PRODUCTION_WEBRTC_IMPLEMENTATION = "stasel/WebRTC 150.0.0 production adapter"
CONTROL_CHANNEL_PROOF = "ordered/reliable; bidirectional payload pass"
MEDIA_CHANNEL_PROOF = "unordered/maxRetransmits=0; bidirectional payload pass"
PRODUCT_MEDIA_PROOF = (
    "real VideoToolbox HEVC keyframe and delta over WebRTC media DataChannel pass"
)
PRODUCT_MEDIA_SOURCE = "videotoolbox-hevc"
GATE_FAILURE_PATH = "gate-failure.json"


def _project_pass_evidence(
    evidence: dict[str, Any], expected_mode: str
) -> dict[str, Any]:
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        raise E2EFailure("private evidence has an unsupported schema")
    if evidence.get("result") != "pass" or evidence.get("mode") != expected_mode:
        raise E2EFailure(f"{expected_mode} private evidence is not a passing run")
    slice_name = evidence.get("slice")
    if slice_name not in {"transport", "product"}:
        raise E2EFailure("private evidence has an unsupported slice")

    environment = _expect_mapping(evidence.get("environment"), "environment")
    repository_source = _expect_mapping(
        environment.get("repository_source"), "environment.repository_source"
    )
    repository_commit = _expect_string(
        environment.get("repository_commit"), "environment.repository_commit"
    )
    if REVISION_PATTERN.fullmatch(repository_commit) is None:
        raise E2EFailure("environment.repository_commit is not a Git revision")
    if repository_source.get("repository_commit") != repository_commit:
        raise E2EFailure("repository commit fields disagree")
    source_fingerprint = _expect_hash(
        repository_source.get("source_fingerprint"),
        "environment.repository_source.source_fingerprint",
    )
    source_dirty = _expect_bool(
        repository_source.get("dirty"), "environment.repository_source.dirty"
    )

    artifacts = _expect_mapping(evidence.get("artifacts"), "artifacts")
    _expect_exact_keys(
        artifacts,
        required={
            "signaling_sha256",
            "mac_host_sha256",
            "webrtc_framework_sha256",
            "turnserver_sha256",
        },
        label="artifacts",
    )
    public_artifacts = {
        "signaling_sha256": _expect_hash(
            artifacts["signaling_sha256"], "artifacts.signaling_sha256"
        ),
        "mac_host_sha256": _expect_hash(
            artifacts["mac_host_sha256"], "artifacts.mac_host_sha256"
        ),
        "webrtc_framework_sha256": _expect_hash(
            artifacts["webrtc_framework_sha256"],
            "artifacts.webrtc_framework_sha256",
        ),
    }
    turnserver_hash = artifacts["turnserver_sha256"]
    if expected_mode == "direct":
        if turnserver_hash != "not_used":
            raise E2EFailure("direct evidence unexpectedly used turnserver")
        public_artifacts["turnserver_sha256"] = "not_used"
    else:
        public_artifacts["turnserver_sha256"] = _expect_hash(
            turnserver_hash, "artifacts.turnserver_sha256"
        )

    signaling = _expect_mapping(evidence.get("signaling"), "signaling")
    for field, expected in {
        "real_process": True,
        "health": "pass",
        "ready": "pass",
        "authenticated_session": "pass",
        "secret_log_scan": "pass",
    }.items():
        if signaling.get(field) != expected:
            raise E2EFailure(f"signaling evidence does not prove {field}")
    accepted_messages = _expect_nonnegative_int(
        signaling.get("accepted_messages"), "signaling.accepted_messages"
    )
    if accepted_messages < 4:
        raise E2EFailure("signaling evidence does not contain a complete exchange")

    webrtc = _expect_mapping(evidence.get("webrtc"), "webrtc")
    if webrtc.get("implementation") != PRODUCTION_WEBRTC_IMPLEMENTATION:
        raise E2EFailure("private WebRTC evidence is not bound to the production adapter")
    if webrtc.get("real_peer_connections") != 2:
        raise E2EFailure("private WebRTC evidence does not prove two real peer connections")
    if webrtc.get("offer_answer_via_http_signaling") != "pass":
        raise E2EFailure("private WebRTC evidence does not prove offer/answer signaling")
    if webrtc.get("ice_candidate_exchange") != "pass":
        raise E2EFailure("private WebRTC evidence does not prove ICE exchange")
    data_channels = _expect_mapping(webrtc.get("data_channels"), "webrtc.data_channels")
    if data_channels.get("control") != CONTROL_CHANNEL_PROOF:
        raise E2EFailure("private WebRTC evidence does not prove the control DataChannel")
    if data_channels.get("media") != MEDIA_CHANNEL_PROOF:
        raise E2EFailure("private WebRTC evidence does not prove the media DataChannel")
    application_e2ee = _expect_string(
        webrtc.get("application_e2ee"), "webrtc.application_e2ee"
    )
    if application_e2ee != APPLICATION_E2EE_PROOF:
        raise E2EFailure("private WebRTC evidence does not prove application E2EE")
    if webrtc.get("selected_route") != expected_mode:
        raise E2EFailure("selected WebRTC route does not match the evidence mode")
    candidate_pair = _expect_string(
        webrtc.get("selected_candidate_pair"), "webrtc.selected_candidate_pair"
    )
    candidate_match = CANDIDATE_PAIR_PATTERN.fullmatch(candidate_pair)
    if candidate_match is None or candidate_match.group(1) != expected_mode:
        raise E2EFailure("selected candidate pair has an invalid route summary")
    local_candidate, remote_candidate = candidate_match.group(2), candidate_match.group(3)
    candidate_protocol = candidate_match.group(4)
    if candidate_protocol not in SUPPORTED_CANDIDATE_PROTOCOLS:
        raise E2EFailure("selected candidate pair has an unsupported protocol")
    if any(
        candidate not in SUPPORTED_CANDIDATE_TYPES
        for candidate in (local_candidate, remote_candidate)
    ):
        raise E2EFailure("selected candidate pair has an unsupported candidate type")
    if expected_mode == "relay" and (local_candidate, remote_candidate) != (
        "relay",
        "relay",
    ):
        raise E2EFailure("relay evidence did not prove relay candidate types")
    if expected_mode == "direct" and "relay" in (local_candidate, remote_candidate):
        raise E2EFailure("direct evidence unexpectedly selected a relay candidate")

    public: dict[str, Any] = {
        "schema": PUBLIC_EVIDENCE_SCHEMA,
        "result": "pass",
        "mode": expected_mode,
        "slice": slice_name,
        "source": {
            "repository_commit": repository_commit,
            "source_fingerprint": source_fingerprint,
            "dirty": source_dirty,
        },
        "artifacts": public_artifacts,
        "signaling": {"accepted_messages": accepted_messages},
        "webrtc": {
            "selected_route": expected_mode,
            "candidate_pair_kind": candidate_match.group(1),
            "candidate_transport": candidate_protocol,
            "application_e2ee": True,
        },
        "limitations": list(PUBLIC_LIMITATIONS),
    }
    if slice_name == "product":
        product = _expect_mapping(evidence.get("product_session"), "product_session")
        product_host = _expect_string(
            product.get("host"), "product_session.host"
        )
        if product_host != PRODUCT_SESSION_HOST:
            raise E2EFailure("product evidence has an unsupported host session")
        if product.get("device") != "synthetic Protocol v1 harness":
            raise E2EFailure("product evidence is not bound to the synthetic harness")
        if product.get("capture_or_stream_server_started") is not False:
            raise E2EFailure("product evidence unexpectedly started a capture server")
        expected_product_proof = {
            "client_hello": "pass",
            "session_accepted_epoch": 1,
            "initial_video_config_ack_epoch": 1,
            "runtime_video_config_ack_epoch": 2,
            "runtime_rotation_degrees": 90,
            "media": PRODUCT_MEDIA_PROOF,
            "media_source": PRODUCT_MEDIA_SOURCE,
            "touch_input": "pass",
            "seeded_plaintext_log_scan": "pass",
        }
        for field, expected in expected_product_proof.items():
            if product.get(field) != expected:
                raise E2EFailure(f"product evidence does not prove {field}")
        public["product_session"] = {
            "host": product_host,
            "synthetic_device": True,
            "media_source": PRODUCT_MEDIA_SOURCE,
            "capture_or_stream_server_started": False,
        }
    if expected_mode == "relay":
        coturn = _expect_mapping(evidence.get("coturn"), "coturn")
        version = _expect_string(coturn.get("version"), "coturn.version")
        if version not in SUPPORTED_COTURN_VERSIONS:
            raise E2EFailure("relay evidence used an unsupported coturn version")
        if coturn.get("forced_libwebrtc_relay") != "pass":
            raise E2EFailure("relay evidence did not prove forced libwebrtc relay")
        if coturn.get("real_process") is not True:
            raise E2EFailure("relay evidence did not prove a real coturn process")
        executable_hash = _expect_hash(
            coturn.get("executable_sha256"), "coturn.executable_sha256"
        )
        if executable_hash != public_artifacts["turnserver_sha256"]:
            raise E2EFailure("coturn executable hash disagrees with relay artifacts")
        public["coturn"] = {
            "version": version,
            "forced_libwebrtc_relay": True,
            "executable_sha256": executable_hash,
        }
    return public


def _project_diagnostic(
    diagnostic: dict[str, Any], *, component: str, mode: str
) -> dict[str, Any]:
    _expect_exact_keys(
        diagnostic,
        required={
            "schema",
            "component",
            "status",
            "raw_bytes",
            "raw_lines",
            "raw_sha256",
            "raw_uploaded",
            "privacy_projection",
            "markers",
        },
        optional={"metadata"},
        label=f"{mode} {component} diagnostic",
    )
    if diagnostic["schema"] != PUBLIC_DIAGNOSTIC_SCHEMA:
        raise E2EFailure("diagnostic summary has an unsupported schema")
    if diagnostic["component"] != component or diagnostic["status"] != "captured":
        raise E2EFailure("diagnostic summary identity or status is invalid")
    if diagnostic["raw_uploaded"] is not False:
        raise E2EFailure("diagnostic summary must state that raw output is not uploaded")
    if diagnostic["privacy_projection"] != "allowlist-summary-only":
        raise E2EFailure("diagnostic summary has an unsupported privacy projection")
    markers = _expect_mapping(diagnostic["markers"], "diagnostic markers")
    _expect_exact_keys(
        markers,
        required={"pass", "fail", "timeout"},
        label="diagnostic markers",
    )
    projected: dict[str, Any] = {
        "schema": PUBLIC_DIAGNOSTIC_SCHEMA,
        "mode": mode,
        "component": component,
        "status": "captured",
        "raw_bytes": _expect_nonnegative_int(
            diagnostic["raw_bytes"], "diagnostic raw_bytes"
        ),
        "raw_lines": _expect_nonnegative_int(
            diagnostic["raw_lines"], "diagnostic raw_lines"
        ),
        "raw_sha256": _expect_hash(diagnostic["raw_sha256"], "diagnostic raw_sha256"),
        "raw_uploaded": False,
        "markers": {
            name: _expect_bool(markers[name], f"diagnostic markers.{name}")
            for name in ("pass", "fail", "timeout")
        },
    }
    metadata = diagnostic.get("metadata")
    if component == "turnserver":
        metadata = _expect_mapping(metadata, "turnserver diagnostic metadata")
        _expect_exact_keys(metadata, required={"version"}, label="turnserver metadata")
        version = _expect_string(metadata["version"], "turnserver metadata.version")
        if version not in SUPPORTED_COTURN_VERSIONS:
            raise E2EFailure("turnserver diagnostic used an unsupported coturn version")
        projected["coturn_version"] = version
    elif metadata is not None:
        raise E2EFailure("non-coturn diagnostic contains unexpected metadata")
    return projected


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    write_private_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def build_gate_failure_diagnostic(source_root: Path, output_root: Path) -> int:
    """Write a fixed failure marker without projecting private or passing evidence."""
    source_root = source_root.absolute()
    output_root = output_root.absolute()
    if output_root != source_root / "public-failure":
        raise E2EFailure(
            "failure diagnostic output must be exactly <private-root>/public-failure"
        )
    if source_root.is_symlink():
        raise E2EFailure("private Phase 3 artifact root must be a real directory")
    if source_root.exists() and not source_root.is_dir():
        raise E2EFailure("private Phase 3 artifact root must be a real directory")
    if output_root.is_symlink():
        output_root.unlink()
        raise E2EFailure("failure diagnostic output must not be a symlink")
    _remove_tree(output_root)
    source_root.mkdir(parents=True, exist_ok=True)
    source_root.chmod(0o700)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    temporary_root.chmod(0o700)
    try:
        diagnostic = {
            "schema": PUBLIC_GATE_FAILURE_SCHEMA,
            "status": "failed",
            "gate": "direct-and-relay-product-e2e",
            "successful_evidence_uploaded": False,
            "private_runner_output_uploaded": False,
        }
        rendered = json.dumps(diagnostic, indent=2, sort_keys=True) + "\n"
        if "pass" in rendered.lower():
            raise E2EFailure("failure diagnostic must not contain pass markers")
        _write_json(temporary_root / GATE_FAILURE_PATH, diagnostic)
        os.replace(temporary_root, output_root)
        return 1
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def build_public_artifact_tree(
    source_root: Path,
    output_root: Path,
    *,
    allow_missing: bool = False,
) -> int:
    """Create a fail-closed public projection without copying private evidence."""
    source_root = source_root.absolute()
    output_root = output_root.absolute()
    if output_root != source_root / "public":
        raise E2EFailure(
            "public artifact output must be exactly <private-root>/public"
        )
    if source_root.is_symlink():
        raise E2EFailure("private Phase 3 artifact root must be a real directory")
    if output_root.is_symlink():
        output_root.unlink()
        raise E2EFailure("public artifact output must not be a symlink")
    _remove_tree(output_root)
    if not source_root.exists():
        if allow_missing:
            return 0
        raise E2EFailure("private Phase 3 artifact directory is missing")
    if not source_root.is_dir():
        raise E2EFailure("private Phase 3 artifact root must be a real directory")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    temporary_root.chmod(0o700)
    written = 0
    try:
        projected_evidence: dict[str, dict[str, Any]] = {}
        for mode in ("direct", "relay"):
            source = source_root / f"{mode}.json"
            if source.exists() or source.is_symlink():
                projected = _project_pass_evidence(
                    _read_json_file(source, f"{mode} private evidence"), mode
                )
                projected_evidence[mode] = projected
                _write_json(temporary_root / f"{mode}.json", projected)
                written += 1
            elif not allow_missing:
                raise E2EFailure(f"{mode} private evidence is missing")
        if set(projected_evidence) == {"direct", "relay"}:
            direct = projected_evidence["direct"]
            relay = projected_evidence["relay"]
            if direct["source"] != relay["source"]:
                raise E2EFailure("direct and relay evidence have different source identity")
            for artifact in (
                "signaling_sha256",
                "mac_host_sha256",
                "webrtc_framework_sha256",
            ):
                if direct["artifacts"][artifact] != relay["artifacts"][artifact]:
                    raise E2EFailure(
                        "direct and relay evidence have different artifact hashes"
                    )
        for source_relative, output_relative in DIAGNOSTIC_INPUTS.items():
            source = source_root / source_relative
            if source.exists() or source.is_symlink():
                input_component = source.stem
                mode = source_relative.split("-logs/", 1)[0]
                _write_json(
                    temporary_root / output_relative,
                    _project_diagnostic(
                        _read_json_file(source, source_relative),
                        component=input_component,
                        mode=mode,
                    ),
                )
                written += 1
            elif not allow_missing:
                raise E2EFailure(f"diagnostic summary is missing: {source_relative}")
        if written == 0 and allow_missing:
            return 0
        validate_public_artifact_tree(
            temporary_root, require_complete=not allow_missing
        )
        os.replace(temporary_root, output_root)
        return written
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
