"""Strict schema validation for public Phase 3 CI artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from scripts.phase3_webrtc.model import (
    E2EFailure,
    PUBLIC_DIAGNOSTIC_SCHEMA,
    PUBLIC_EVIDENCE_SCHEMA,
    SUPPORTED_CANDIDATE_PROTOCOLS,
    SUPPORTED_COTURN_VERSIONS,
)
from scripts.phase3_webrtc.privacy import public_diagnostic_findings

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REVISION_PATTERN = re.compile(r"[0-9a-f]{40,64}")
PUBLIC_LIMITATIONS = (
    "local_loopback_only",
    "synthetic_protocol_v1_device",
    "synthetic_videotoolbox_input_frames",
    "no_android_device_or_ui",
    "no_real_screen_capture",
    "no_android_mediacodec_decode",
    "no_public_internet_path",
)
DIAGNOSTIC_INPUTS = {
    "direct-logs/peer.json": "diagnostics/direct-peer.json",
    "direct-logs/signaling.json": "diagnostics/direct-signaling.json",
    "relay-logs/peer.json": "diagnostics/relay-peer.json",
    "relay-logs/signaling.json": "diagnostics/relay-signaling.json",
    "relay-logs/turnserver.json": "diagnostics/relay-turnserver.json",
}
PUBLIC_PATHS = {"direct.json", "relay.json", *DIAGNOSTIC_INPUTS.values()}
PUBLIC_DIAGNOSTIC_IDENTITIES = {
    output: (source.split("-logs/", 1)[0], Path(source).stem)
    for source, output in DIAGNOSTIC_INPUTS.items()
}


def expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise E2EFailure(f"{label} must be a JSON object")
    return value


def expect_exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    label: str,
) -> None:
    missing = sorted(required - value.keys())
    unexpected = sorted(value.keys() - required - optional)
    if missing or unexpected:
        raise E2EFailure(
            f"{label} has invalid keys; missing={missing}, unexpected={unexpected}"
        )


def expect_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise E2EFailure(f"{label} must be a non-empty string")
    return value


def expect_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise E2EFailure(f"{label} must be a boolean")
    return value


def expect_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise E2EFailure(f"{label} must be a non-negative integer")
    return value


def expect_hash(value: Any, label: str) -> str:
    rendered = expect_string(value, label)
    if SHA256_PATTERN.fullmatch(rendered) is None:
        raise E2EFailure(f"{label} must be a lowercase SHA-256 digest")
    return rendered


def read_json_file(path: Path, label: str) -> dict[str, Any]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise E2EFailure(f"{label} must be a regular file")
        if before.st_size > 1024 * 1024:
            raise E2EFailure(f"{label} is unexpectedly large")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        identity_before = (
            before.st_dev, before.st_ino, before.st_mode, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_mode, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        identity_current = (
            current.st_dev, current.st_ino, current.st_mode, current.st_size,
            current.st_mtime_ns, current.st_ctime_ns,
        )
        if identity_before != identity_after or identity_after != identity_current:
            raise E2EFailure(f"{label} changed while it was being read")
        text = b"".join(chunks).decode("utf-8")
        value = json.loads(text)
    except OSError as exception:
        raise E2EFailure(f"{label} must be a safely readable regular file") from exception
    except (UnicodeError, json.JSONDecodeError) as exception:
        raise E2EFailure(f"{label} is not strict UTF-8 JSON") from exception
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return expect_mapping(value, label)


def _validate_public_evidence(value: dict[str, Any], expected_mode: str) -> None:
    expect_exact_keys(
        value,
        required={
            "schema", "result", "mode", "slice", "source", "artifacts",
            "signaling", "webrtc", "limitations",
        },
        optional={"product_session", "coturn"},
        label="public evidence",
    )
    if value["schema"] != PUBLIC_EVIDENCE_SCHEMA:
        raise E2EFailure("public evidence has an unsupported schema")
    if value["mode"] != expected_mode or value["result"] != "pass":
        raise E2EFailure("public evidence identity or result is invalid")
    if value["slice"] not in {"transport", "product"}:
        raise E2EFailure("public evidence has an unsupported slice")
    source = expect_mapping(value["source"], "public source")
    expect_exact_keys(
        source,
        required={"repository_commit", "source_fingerprint", "dirty"},
        label="public source",
    )
    commit = expect_string(source["repository_commit"], "public source commit")
    if REVISION_PATTERN.fullmatch(commit) is None:
        raise E2EFailure("public source commit is invalid")
    expect_hash(source["source_fingerprint"], "public source fingerprint")
    expect_bool(source["dirty"], "public source dirty")
    artifacts = expect_mapping(value["artifacts"], "public artifacts")
    expect_exact_keys(
        artifacts,
        required={
            "signaling_sha256",
            "mac_host_sha256",
            "webrtc_framework_sha256",
            "turnserver_sha256",
        },
        label="public artifacts",
    )
    for name in (
        "signaling_sha256",
        "mac_host_sha256",
        "webrtc_framework_sha256",
    ):
        expect_hash(artifacts[name], f"public artifacts.{name}")
    if expected_mode == "direct":
        if artifacts["turnserver_sha256"] != "not_used":
            raise E2EFailure("public direct evidence unexpectedly used turnserver")
    else:
        expect_hash(
            artifacts["turnserver_sha256"],
            "public artifacts.turnserver_sha256",
        )
    signaling = expect_mapping(value["signaling"], "public signaling")
    expect_exact_keys(signaling, required={"accepted_messages"}, label="public signaling")
    if expect_nonnegative_int(signaling["accepted_messages"], "accepted messages") < 4:
        raise E2EFailure("public signaling exchange is incomplete")
    webrtc = expect_mapping(value["webrtc"], "public webrtc")
    expect_exact_keys(
        webrtc,
        required={
            "selected_route", "candidate_pair_kind", "candidate_transport",
            "application_e2ee",
        },
        label="public webrtc",
    )
    if webrtc["selected_route"] != expected_mode or webrtc["candidate_pair_kind"] != expected_mode:
        raise E2EFailure("public WebRTC route is invalid")
    candidate_transport = expect_string(
        webrtc["candidate_transport"], "candidate transport"
    )
    if candidate_transport not in SUPPORTED_CANDIDATE_PROTOCOLS:
        raise E2EFailure("public candidate transport is unsupported")
    if webrtc["application_e2ee"] is not True:
        raise E2EFailure("public WebRTC evidence does not prove application E2EE")
    if value["limitations"] != list(PUBLIC_LIMITATIONS):
        raise E2EFailure("public limitations are not the fixed allowlist")
    product = value.get("product_session")
    if value["slice"] == "product":
        product = expect_mapping(product, "public product session")
        expect_exact_keys(
            product,
            required={
                "host",
                "synthetic_device",
                "media_source",
                "capture_or_stream_server_started",
            },
            label="public product session",
        )
        if product != {
            "host": "InternetProductSession",
            "synthetic_device": True,
            "media_source": "videotoolbox-hevc",
            "capture_or_stream_server_started": False,
        }:
            raise E2EFailure("public product session boundary is invalid")
    elif product is not None:
        raise E2EFailure("transport evidence contains an unexpected product session")
    coturn = value.get("coturn")
    if expected_mode == "relay":
        coturn = expect_mapping(coturn, "public coturn")
        expect_exact_keys(
            coturn,
            required={
                "version",
                "forced_libwebrtc_relay",
                "executable_sha256",
            },
            label="public coturn",
        )
        if coturn["version"] not in SUPPORTED_COTURN_VERSIONS:
            raise E2EFailure("public coturn version is unsupported")
        if coturn["forced_libwebrtc_relay"] is not True:
            raise E2EFailure("public relay evidence is not forced")
        executable_hash = expect_hash(
            coturn["executable_sha256"], "public coturn executable hash"
        )
        if executable_hash != artifacts["turnserver_sha256"]:
            raise E2EFailure("public coturn executable hash disagrees with artifacts")
    elif coturn is not None:
        raise E2EFailure("direct evidence contains unexpected coturn state")


def _validate_public_diagnostic(
    value: dict[str, Any], *, mode: str, component: str
) -> None:
    expect_exact_keys(
        value,
        required={
            "schema", "mode", "component", "status", "raw_bytes", "raw_lines",
            "raw_sha256", "raw_uploaded", "markers",
        },
        optional={"coturn_version"},
        label="public diagnostic",
    )
    if value["schema"] != PUBLIC_DIAGNOSTIC_SCHEMA:
        raise E2EFailure("public diagnostic has an unsupported schema")
    if value["mode"] != mode or value["component"] != component:
        raise E2EFailure("public diagnostic identity is invalid")
    if value["status"] != "captured" or value["raw_uploaded"] is not False:
        raise E2EFailure("public diagnostic status is invalid")
    expect_nonnegative_int(value["raw_bytes"], "public diagnostic raw_bytes")
    expect_nonnegative_int(value["raw_lines"], "public diagnostic raw_lines")
    expect_hash(value["raw_sha256"], "public diagnostic raw_sha256")
    markers = expect_mapping(value["markers"], "public diagnostic markers")
    expect_exact_keys(
        markers, required={"pass", "fail", "timeout"}, label="public diagnostic markers"
    )
    for name in markers:
        expect_bool(markers[name], f"public diagnostic markers.{name}")
    if component == "turnserver":
        if value.get("coturn_version") not in SUPPORTED_COTURN_VERSIONS:
            raise E2EFailure("public turnserver diagnostic version is unsupported")
    elif "coturn_version" in value:
        raise E2EFailure("non-coturn public diagnostic contains a coturn version")


def validate_public_artifact_tree(
    root: Path, *, require_complete: bool = False
) -> int:
    if root.is_symlink() or not root.is_dir():
        raise E2EFailure("public artifact root must be a real directory")
    if root.stat().st_mode & 0o077:
        raise E2EFailure("public artifact root permissions are too broad")
    found: set[str] = set()
    evidence_identities: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise E2EFailure("public artifact directories must be private real directories")
            continue
        relative_path = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            raise E2EFailure(f"public artifact is not a regular file: {relative_path}")
        if relative_path not in PUBLIC_PATHS:
            raise E2EFailure(f"unexpected public artifact path: {relative_path}")
        if path.stat().st_mode & 0o077:
            raise E2EFailure(f"public artifact permissions are too broad: {relative_path}")
        value = read_json_file(path, f"public artifact {relative_path}")
        if relative_path in {"direct.json", "relay.json"}:
            _validate_public_evidence(value, Path(relative_path).stem)
            evidence_identities[Path(relative_path).stem] = (
                expect_mapping(value["source"], "public source"),
                expect_mapping(value["artifacts"], "public artifacts"),
            )
        else:
            mode, component = PUBLIC_DIAGNOSTIC_IDENTITIES[relative_path]
            _validate_public_diagnostic(value, mode=mode, component=component)
        rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
        findings = public_diagnostic_findings(rendered)
        if findings:
            raise E2EFailure(
                f"public artifact privacy scan failed for {relative_path}: "
                f"{','.join(findings)}"
            )
        found.add(relative_path)
    if set(evidence_identities) == {"direct", "relay"}:
        direct_source, direct_artifacts = evidence_identities["direct"]
        relay_source, relay_artifacts = evidence_identities["relay"]
        if direct_source != relay_source:
            raise E2EFailure(
                "public direct and relay evidence have different source or artifacts"
            )
        for artifact in (
            "signaling_sha256",
            "mac_host_sha256",
            "webrtc_framework_sha256",
        ):
            if direct_artifacts[artifact] != relay_artifacts[artifact]:
                raise E2EFailure(
                    "public direct and relay evidence have different source or artifacts"
                )
    if require_complete and found != PUBLIC_PATHS:
        raise E2EFailure(
            f"public artifact tree is incomplete; missing={sorted(PUBLIC_PATHS - found)}"
        )
    return len(found)
