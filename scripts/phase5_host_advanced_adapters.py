#!/usr/bin/env python3
"""Validate the Phase 5 host-side advanced adapter readiness contract.

This is a source/readiness gate, not device acceptance. It records the minimum
adapter matrix that the iOS client expects from an advanced MacHost while
checking that the current production Host does not advertise unsupported
advanced adapters as shipped capabilities.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
KIND = "phase5_host_advanced_adapters_readiness"
SCHEMA = "dev.vibescreen.phase5-host-advanced-adapters-readiness/v1"
PROTOCOL_SESSION = Path("baseline/MacHost/Sources/ProtocolV1Session.swift")
PHASE5_TECH = Path("docs/changes/2026-08-04-phase-5-ios-advanced/TECH.md")
PHASE5_TEST = Path("docs/changes/2026-08-04-phase-5-ios-advanced/TEST.md")
README = Path("README.md")
IOS_README = Path("apps/ios/README.md")


@dataclass(frozen=True)
class AdapterContract:
    adapter_id: str
    owner: str
    capabilities: list[str]
    minimum_interface: list[str]
    shipped_surface: str
    fail_closed_contract: list[str]
    open_gates: list[str]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


ADAPTER_MATRIX: list[AdapterContract] = [
    AdapterContract(
        adapter_id="multi-client-display",
        owner="MacHost ProtocolV1Session advanced resource adapter",
        capabilities=["CAPABILITY_MULTI_DISPLAY", "CAPABILITY_MULTI_CLIENT"],
        minimum_interface=[
            "per-client session_id plus session_epoch ownership",
            "unique display_id and stream_id allocation per admitted stream",
            "targeted input routing by display_id and stream_id",
            "bounded maximum_clients, maximum_displays, and maximum_video_streams",
        ],
        shipped_surface=(
            "single-client multi-display Protocol v1 host path is offline/self-test covered; "
            "multi-client host allocation is not shipped"
        ),
        fail_closed_contract=[
            "do not advertise CAPABILITY_MULTI_CLIENT until allocation is implemented",
            "reject duplicate or over-limit display/stream bindings before capture allocation",
            "reject stale session_epoch targets without mutating the active stream",
        ],
        open_gates=[
            "iPhone/iPad multi-display device run",
            "concurrent-client MacHost allocation run",
        ],
    ),
    AdapterContract(
        adapter_id="audio-capture-playback",
        owner="MacHost AVAudioEngine capture adapter and iOS AVAudioEngine playback adapter",
        capabilities=["CAPABILITY_AUDIO", "CAPABILITY_AUDIO_DATA_CHANNEL"],
        minimum_interface=[
            "AudioConfig/AudioConfigResult control handshake",
            "PCM S16LE packet headers on logical audio channel 3 or negotiated audio DataChannel",
            "current session_epoch and config_epoch validation",
            "bounded jitter/backlog so audio cannot block control or video",
        ],
        shipped_surface=(
            "MacHost capture and iOS playback cores are offline-tested; audible device playback "
            "and host/iOS product flow are not accepted"
        ),
        fail_closed_contract=[
            "do not advertise audio capabilities from productionHostCapabilities by default",
            "reject unsupported codecs and malformed byte counts before scheduling playback",
            "require platform audio permission before native capture starts",
        ],
        open_gates=[
            "AVAudioEngine audible iOS device output",
            "MacHost microphone/system audio capture acceptance",
            "audio product flow over Internet DataChannel",
        ],
    ),
    AdapterContract(
        adapter_id="clipboard",
        owner="MacHost clipboard adapter and iOS explicit UIPasteboard adapter",
        capabilities=["CAPABILITY_CLIPBOARD"],
        minimum_interface=[
            "ClipboardOffer/ClipboardRequest/ClipboardContent control messages",
            "origin device and change ID loop suppression",
            "MIME, byte-limit, and SHA-256 validation before native pasteboard writes",
            "explicit user action for every local read or write",
        ],
        shipped_surface=(
            "protocol and local adapters are self-tested; iOS prompt/write behavior and "
            "host/iOS product flow are not device-accepted"
        ),
        fail_closed_contract=[
            "managed policy deny removes clipboard from the negotiated surface",
            "content without matching request stays staged or rejected",
            "oversize or digest-mismatched content never reaches native pasteboard",
        ],
        open_gates=[
            "UIPasteboard prompt/write iOS device acceptance",
            "host/iOS clipboard product flow",
        ],
    ),
    AdapterContract(
        adapter_id="file-transfer",
        owner="MacHost bounded file-transfer domain and iOS security-scoped file adapter",
        capabilities=["CAPABILITY_FILE_TRANSFER", "CAPABILITY_BULK_DATA_CHANNEL"],
        minimum_interface=[
            "FileOffer/FileAccept/FileTransferProgress/FileTransferCancel/FileTransferComplete control flow",
            "bulk chunks with transfer_id, ordered offsets, final flag, and per-chunk SHA-256",
            "safe basename staging and final SHA-256 verification before reveal/export",
            "resource limits for aggregate bytes, chunk bytes, and concurrency",
        ],
        shipped_surface=(
            "MacHost/Android USB/LAN single-file domain is offline-tested; host/iOS and "
            "Internet bulk product flows are not accepted"
        ),
        fail_closed_contract=[
            "productionHostCapabilities advertises file transfer only behind fileTransferAllowed and policy",
            "receivers default to reject until an explicit application approval callback grants a transfer",
            "policy, digest, disk, backpressure, disconnect, or peer cancel cleans staging state",
        ],
        open_gates=[
            "iOS security-scoped import/export device acceptance",
            "host/iOS file-transfer product flow",
            "bulk WebRTC DataChannel product flow",
        ],
    ),
    AdapterContract(
        adapter_id="hdr-color",
        owner="MacHost color retry adapter and iOS VideoToolbox/CoreVideo renderer",
        capabilities=["CAPABILITY_HDR_VIDEO", "CAPABILITY_COLOR_MANAGEMENT"],
        minimum_interface=[
            "VideoConfig color description with bit depth, primaries, transfer, matrix, and range",
            "new config_epoch for every fallback or retry",
            "explicit SDR fallback or structured rejection for unsupported Main10/PQ/HLG",
        ],
        shipped_surface=(
            "8-bit SDR color management/fallback is offline-tested; HDR/EDR output is not shipped"
        ),
        fail_closed_contract=[
            "do not advertise CAPABILITY_HDR_VIDEO until a real HDR output path is accepted",
            "fallback must select 8-bit BT.709 at a newer config_epoch",
            "unsupported color must not silently mutate an existing stream",
        ],
        open_gates=[
            "HDR/EDR iOS display output evidence",
            "hardware VideoToolbox Main10 behavior",
        ],
    ),
    AdapterContract(
        adapter_id="host-actions-and-gestures",
        owner="MacHost finite host-action catalog and iOS local gesture mapper",
        capabilities=["CAPABILITY_HOST_ACTIONS"],
        minimum_interface=[
            "finite HostActionCatalog with stable action IDs",
            "HostActionInvoke correlation and session target validation",
            "gesture definitions remain local to the client and invoke only catalogued IDs",
        ],
        shipped_surface=(
            "MacHost action catalog and iOS gesture persistence are offline-tested; "
            "advanced gesture device behavior remains open"
        ),
        fail_closed_contract=[
            "host actions require negotiated capability and deny-wins managed policy",
            "unknown, over-limit, pre-stream, or foreign-target actions return structured failure",
            "gesture UI must not inject uncatalogued protocol action IDs",
        ],
        open_gates=[
            "iOS gesture-to-action device acceptance",
            "host action behavior across iPhone and iPad targets",
        ],
    ),
    AdapterContract(
        adapter_id="wake-host",
        owner="MacHost authenticated wake helper and iOS Wake-on-LAN adapter",
        capabilities=["CAPABILITY_WAKE_HOST"],
        minimum_interface=[
            "WakeHostRequest/WakeHostResult with paired-device authorization",
            "replay-safe proof tied to the authorized host identity",
            "local policy check before emitting a Magic Packet",
        ],
        shipped_surface="WOL packet construction is self-tested; authenticated wake helper acceptance is open",
        fail_closed_contract=[
            "productionHostCapabilities advertises wake only when wakeHostAvailable and policy allow it",
            "default wake authorizer denies requests",
            "host ID mismatch or missing identity returns a protocol error",
        ],
        open_gates=[
            "paired-device wake helper acceptance",
            "sleeping Mac wake and reconnect run",
        ],
    ),
    AdapterContract(
        adapter_id="managed-policy",
        owner="MacHost deny-wins effective policy and iOS managed App Configuration adapter",
        capabilities=["CAPABILITY_MANAGED_CONFIGURATION"],
        minimum_interface=[
            "ManagedPolicyStatus exchange on the control channel",
            "deny-wins merge for clipboard, files, audio, wake, gestures, and host actions",
            "allowed-host restriction with normalized host IDs",
        ],
        shipped_surface="local and remote policy merge semantics are offline-tested; MDM injection remains open",
        fail_closed_contract=[
            "unset managed fields default to denied",
            "disjoint allowed-host sets deny all hosts",
            "policy denial removes or disables the affected adapter before native side effects",
        ],
        open_gates=[
            "managed App Configuration injection on iOS device",
            "host/iOS policy propagation with native adapter UI",
        ],
    ),
]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_text(repo: Path, relative: Path) -> str:
    try:
        return (repo / relative).read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"failed to read {relative}: {error}") from error


def production_host_capabilities_body(source: str) -> str:
    start = source.find("static func productionHostCapabilities")
    if start < 0:
        raise RuntimeError("productionHostCapabilities was not found")
    end = source.find("return capabilities", start)
    if end < 0:
        raise RuntimeError("productionHostCapabilities return was not found")
    return source[start:end]


def check_required_text(name: str, text: str, needles: Sequence[str]) -> CheckResult:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        return CheckResult(name=name, status="fail", detail=f"missing: {', '.join(missing)}")
    return CheckResult(name=name, status="pass", detail="all required contract text is present")


def validate_contracts(repo: Path = REPO_ROOT) -> tuple[list[CheckResult], list[str]]:
    protocol_session = read_text(repo, PROTOCOL_SESSION)
    phase5_tech = read_text(repo, PHASE5_TECH)
    phase5_test = read_text(repo, PHASE5_TEST)
    readme = read_text(repo, README)
    ios_readme = read_text(repo, IOS_README)
    capability_body = production_host_capabilities_body(protocol_session)

    checks = [
        CheckResult(
            name="matrix-has-minimum-adapter-coverage",
            status="pass" if {row.adapter_id for row in ADAPTER_MATRIX} == {
                "multi-client-display",
                "audio-capture-playback",
                "clipboard",
                "file-transfer",
                "hdr-color",
                "host-actions-and-gestures",
                "wake-host",
                "managed-policy",
            } else "fail",
            detail="matrix covers Phase 5 advanced host adapter families",
        ),
        check_required_text(
            "production-host-defaults-omit-unaccepted-adapters",
            capability_body,
            ["touchEnabled", ".colorManagement", ".multiDisplay", ".clientVideoControl"],
        ),
        CheckResult(
            name="production-host-defaults-do-not-advertise-hdr-audio-multiclient",
            status="pass" if (
                all(needle not in capability_body for needle in (".audioDataChannel", ".bulkDataChannel"))
                and "maximumClients: Int = 1" in capability_body
                and "if maximumClients > 1 { capabilities.insert(.multiClient) }" in capability_body
            ) else "fail",
            detail="audio/bulk DataChannel stay out of production defaults; multi-client requires maximumClients > 1 opt-in",
        ),
        check_required_text(
            "hdr-and-audio-are-explicitly-availability-gated",
            capability_body,
            ["hdrVideoAvailable", "if hdrVideoAvailable", "audioCaptureAvailable", "audioCaptureAvailable && managedPolicy.audioAllowed"],
        ),
        check_required_text(
            "file-transfer-and-wake-are-explicitly-gated",
            capability_body,
            ["fileTransferAllowed && managedPolicy.fileTransferAllowed", "wakeHostAvailable && managedPolicy.wakeAllowed"],
        ),
        check_required_text(
            "host-actions-and-clipboard-are-policy-gated",
            capability_body,
            ["managedPolicy.clipboardAllowed", "touchEnabled && managedPolicy.hostActionsAllowed"],
        ),
        check_required_text(
            "tech-doc-names-readiness-owner",
            phase5_tech,
            ["Host-side advanced adapter readiness owner", "phase5-host-advanced-adapters-gate"],
        ),
        check_required_text(
            "test-doc-keeps-device-gates-open",
            phase5_test,
            ["Host-side advanced adapter readiness gate", "does not close", "host-side multi-client/display"],
        ),
        check_required_text(
            "readme-points-to-readiness-owner",
            readme,
            ["host-side advanced adapter readiness owner", "phase5-host-advanced-adapters-gate"],
        ),
        check_required_text(
            "ios-readme-points-to-readiness-owner",
            ios_readme,
            ["phase5-host-advanced-adapters-gate readiness contract", "Advanced host integrations"],
        ),
    ]
    blocking = [check.detail for check in checks if check.status != "pass"]
    return checks, blocking


def build_report(repo: Path = REPO_ROOT) -> dict[str, object]:
    checks, blocking = validate_contracts(repo)
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "generated_at": utc_timestamp(),
        "verdict": "pass" if not blocking else "fail",
        "device_evidence": "not_collected",
        "device_gates_closed": [],
        "scope": (
            "readiness contract for iOS client and MacHost host-side advanced adapters; "
            "not iOS installation, hardware decode, AVAudioEngine audible output, HDR/EDR, "
            "clipboard/file product flow, Internet DataChannel product flow, or native input device evidence"
        ),
        "matrix": [asdict(row) for row in ADAPTER_MATRIX],
        "checks": [asdict(check) for check in checks],
        "blocking_reasons": blocking,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help="repository root to inspect",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON report path",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.repo.resolve())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
