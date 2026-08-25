#!/usr/bin/env python3
"""Fail-closed gate for current-base Phase 3 Android Internet evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


COMBINED_SCHEMA = "dev.vibescreen.phase3-android-product-interop-combined/v1"
ROUTE_SCHEMA = "dev.vibescreen.phase3-android-product-interop/v1"
WITHDRAWN_SCHEMA = "dev.vibescreen.phase3-android-interop/v1"
LOCAL_WEBRTC_SCHEMA = "dev.vibescreen.phase3-webrtc-e2e/v1"
GATE_SCHEMA = "dev.vibescreen.phase3-android-current-base-interop-gate/v1"

EXPECTED_DEVICE = {
    "manufacturer": "nubia",
    "model": "P0110",
    "codename": "pacific",
    "android_version": "16",
    "sdk": 36,
}

BASE_PRODUCT_ASSERTIONS = {
    "real_android_app_and_instrumentation": "pass",
    "real_local_signaling_process": "pass",
    "selected_route": "pass",
    "protocol_v1": "pass",
    "aes_256_gcm_control": "pass",
    "aes_256_gcm_media": "pass",
    "authenticated_touch": "pass",
    "internet_ui_pairing_and_strict_signed_lease_import": "pass",
}

PRODUCT_INTEROP_ASSERTIONS = {
    **BASE_PRODUCT_ASSERTIONS,
    "synthetic_video_config_keyframe_delta": "pass",
}

REAL_CAPTURE_ASSERTIONS = {
    "real_screen_capture": "pass",
    "screen_capture_kit": "pass",
    "videotoolbox_output": "pass",
    "android_mediacodec_decode": "pass",
    "mediacodec_first_output_frame": "pass",
    "continuous_fps_and_decode_latency": "pass",
    "disconnect_reconnect": "pass",
}

PUBLIC_ASSERTIONS = {
    "public_internet_path": "pass",
    "public_nat_or_remote_turn": "pass",
}

LOCAL_PRODUCT_PASS_ASSERTIONS = {
    *PRODUCT_INTEROP_ASSERTIONS.keys(),
    "local_revoke_and_repair",
    "secure_credential_dialogs",
}

PROFILE_PASS_ASSERTIONS = {
    "product-interop": LOCAL_PRODUCT_PASS_ASSERTIONS,
    "real-capture": LOCAL_PRODUCT_PASS_ASSERTIONS | set(REAL_CAPTURE_ASSERTIONS),
    "public-internet": LOCAL_PRODUCT_PASS_ASSERTIONS
    | set(REAL_CAPTURE_ASSERTIONS)
    | set(PUBLIC_ASSERTIONS),
}

PRODUCT_BOUNDARY_EXPECTATIONS = {
    "ui": "pairing_strict_signed_lease_import_local_revoke_repair_only_no_negative_lease_ui_case",
    "screen_capture_kit": "not_claimed",
    "real_display_content": "not_claimed",
    "android_mediacodec_decode": "not_claimed",
    "rotation": "open_harness_has_no_rotation_assertion",
    "disconnect_reconnect": "not_claimed",
    "revocation_repair": "local_android_keystore_and_profile_store_only",
    "soak": "not_claimed",
}

REAL_CAPTURE_BOUNDARY_ASSERTIONS = {
    "real_screen_capture",
    "screen_capture_kit",
    "real_display_content",
    "videotoolbox_output",
    "android_mediacodec_decode",
    "mediacodec_first_output_frame",
    "continuous_fps_and_decode_latency",
    "disconnect_reconnect",
}

PUBLIC_BOUNDARY_ASSERTIONS = {
    "public_internet_path",
    "public_nat_or_remote_turn",
}

NON_RELEASE_BOUNDARY_EXPECTATIONS = {
    "ui": "pairing_strict_signed_lease_import_local_revoke_repair_only_no_negative_lease_ui_case",
    "rotation": "open_harness_has_no_rotation_assertion",
    "revocation_repair": "local_android_keystore_and_profile_store_only",
    "soak": "not_claimed",
}

LEASE_IDENTITY_FIELDS = (
    "pid",
    "task",
    "commit",
    "filesystem_device",
    "inode",
    "content_bytes",
    "lease_comparison_tag",
)

class GateError(RuntimeError):
    """Evidence is absent or below the requested proof boundary."""


@dataclass(frozen=True)
class GateResult:
    result: str
    profile: str
    evidence: Path
    checked_at_utc: str
    reasons: list[str]
    accepted_commit: str | None = None

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": GATE_SCHEMA,
            "result": self.result,
            "profile": self.profile,
            "evidence": str(self.evidence),
            "checked_at_utc": self.checked_at_utc,
            "reasons": self.reasons,
        }
        if self.accepted_commit is not None:
            body["accepted_commit"] = self.accepted_commit
        return body


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GateError("cannot determine repository source state")
    return result.stdout.strip()


def current_commit(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def require_clean_worktree(root: Path) -> None:
    if _git(root, "status", "--porcelain"):
        raise GateError("repository worktree is not clean; current-base evidence must bind to a clean HEAD")


def load_json(path: Path) -> dict[str, Any]:
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("evidence JSON is unavailable or invalid") from error
    if not isinstance(root, dict):
        raise GateError("evidence JSON root must be an object")
    return root


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise GateError(f"{label} must be a list")
    return value


def _normalized_sdk(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    manufacturer = str(device.get("manufacturer") or "").lower()
    model = str(device.get("model") or device.get("product") or "")
    codename = str(device.get("codename") or "")
    android_version = str(device.get("android_version") or device.get("operating_system") or "")
    android_version = android_version.removeprefix("Android ")
    return {
        "manufacturer": manufacturer,
        "model": model,
        "codename": codename,
        "android_version": android_version,
        "sdk": _normalized_sdk(device.get("sdk")),
    }


def require_current_source(report: dict[str, Any], expected_commit: str) -> str:
    source = _require_mapping(report.get("source"), "source")
    commit = source.get("commit")
    if commit != expected_commit:
        raise GateError("evidence source commit is not the current-base commit")
    return str(commit)


def require_nubia_p0110(report: dict[str, Any]) -> None:
    device = _normalize_device(_require_mapping(report.get("device"), "device"))
    if device != EXPECTED_DEVICE:
        raise GateError(
            "evidence device must be nubia P0110 / pacific / Android 16 / SDK 36"
        )


def _require_assertions(assertions: dict[str, Any], expected: dict[str, str]) -> None:
    missing = [key for key, value in expected.items() if assertions.get(key) != value]
    if missing:
        raise GateError("evidence omitted required assertions: " + ", ".join(missing))


def _reject_unpermitted_pass_assertions(
    assertions: dict[str, Any], *, profile: str, route: str
) -> None:
    allowed = set(PROFILE_PASS_ASSERTIONS[profile])
    if route == "relay":
        allowed.add("caller_managed_reachable_coturn_route")
    unexpected = sorted(
        key for key, value in assertions.items() if value == "pass" and key not in allowed
    )
    if unexpected:
        raise GateError(
            f"{profile} evidence must not claim pass for: " + ", ".join(unexpected)
        )


def _require_boundaries(report: dict[str, Any], *, profile: str) -> None:
    boundaries = _require_mapping(report.get("evidence_boundaries", {}), "evidence_boundaries")
    if profile == "product-interop":
        missing_or_changed = [
            key for key, expected in PRODUCT_BOUNDARY_EXPECTATIONS.items()
            if boundaries.get(key) != expected
        ]
        if missing_or_changed:
            raise GateError(
                "product-interop boundary must keep non-product proof open: "
                + ", ".join(missing_or_changed)
            )
        pass_claims = sorted(key for key, value in boundaries.items() if value == "pass")
        if pass_claims:
            raise GateError(
                "product-interop boundary must not claim pass for: "
                + ", ".join(pass_claims)
            )
        return

    for key, expected in NON_RELEASE_BOUNDARY_EXPECTATIONS.items():
        if boundaries.get(key) != expected:
            raise GateError(f"{profile} profile requires {key}={expected}")

    required_pass = set(REAL_CAPTURE_BOUNDARY_ASSERTIONS)
    if profile == "public-internet":
        required_pass |= PUBLIC_BOUNDARY_ASSERTIONS
    for key in sorted(required_pass):
        if boundaries.get(key) != "pass":
            raise GateError(f"{profile} profile requires {key}=pass")

    allowed_pass = required_pass
    pass_claims = sorted(
        key for key, value in boundaries.items() if value == "pass" and key not in allowed_pass
    )
    if pass_claims:
        raise GateError(
            f"{profile} boundary must not claim pass for: " + ", ".join(pass_claims)
        )


def _require_adb_gate(report: dict[str, Any]) -> dict[str, Any]:
    adb_gate = _require_mapping(report.get("adb_gate"), "adb_gate")
    if adb_gate.get("schema") != "dev.vibescreen.adb-lease-gate/v1":
        raise GateError("adb_gate schema is invalid")
    if adb_gate.get("owner_matches_initial") is not True:
        raise GateError("adb_gate owner must match the initial lease holder")
    if adb_gate.get("content_matches_initial") is not True:
        raise GateError("adb_gate content must match the initial lease")
    missing = [field for field in LEASE_IDENTITY_FIELDS if field not in adb_gate]
    if missing:
        raise GateError("adb_gate omitted lease identity fields: " + ", ".join(missing))
    return adb_gate


def _require_same_lease(route_gates: list[dict[str, Any]]) -> None:
    baseline = route_gates[0]
    for adb_gate in route_gates[1:]:
        if any(adb_gate[field] != baseline[field] for field in LEASE_IDENTITY_FIELDS):
            raise GateError("direct and relay route reports must use the same adb lease identity")


def _route_reports(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") == ROUTE_SCHEMA:
        raise GateError("current-base replacement evidence must be a combined direct and relay report")
    runs = _require_list(report.get("runs"), "runs")
    route_reports = []
    for index, item in enumerate(runs):
        route_reports.append(_require_mapping(item, f"runs[{index}]"))
    return route_reports


def validate_report(report: dict[str, Any], *, expected_commit: str, profile: str) -> str:
    schema = report.get("schema")
    if schema == WITHDRAWN_SCHEMA or report.get("result") == "withdrawn":
        raise GateError("withdrawn Android interop records are not current evidence")
    if schema == LOCAL_WEBRTC_SCHEMA:
        raise GateError("local WebRTC loopback evidence is not Android interop evidence")
    if schema not in {COMBINED_SCHEMA, ROUTE_SCHEMA}:
        raise GateError("unsupported Phase 3 Android interop evidence schema")
    if report.get("result") != "pass":
        raise GateError("evidence result is not pass")
    accepted_commit = require_current_source(report, expected_commit)
    require_nubia_p0110(report)

    if schema != COMBINED_SCHEMA:
        raise GateError("current-base replacement evidence must be a combined direct and relay report")
    if report.get("routes") != ["direct", "relay"]:
        raise GateError("combined evidence must contain direct and relay routes")
    if report.get("same_device_lease_holder") is not True:
        raise GateError("combined evidence must use one stable device lease holder")

    route_reports = _route_reports(report)
    if len(route_reports) != 2:
        raise GateError("combined evidence must contain exactly two route reports")
    seen_routes: set[str] = set()
    adb_gates: list[dict[str, Any]] = []
    for route_report in route_reports:
        if route_report.get("schema") != ROUTE_SCHEMA:
            raise GateError("route evidence schema is invalid")
        if route_report.get("result") != "pass":
            raise GateError("route evidence result is not pass")
        require_current_source(route_report, expected_commit)
        require_nubia_p0110(route_report)
        route = route_report.get("route")
        if route not in {"direct", "relay"}:
            raise GateError("route evidence must be direct or relay")
        if route in seen_routes:
            raise GateError("combined evidence must not duplicate route reports")
        seen_routes.add(str(route))
        adb_gates.append(_require_adb_gate(route_report))
        assertions = _require_mapping(route_report.get("assertions"), "assertions")
        _require_assertions(assertions, BASE_PRODUCT_ASSERTIONS)
        if route == "relay":
            if assertions.get("caller_managed_reachable_coturn_route") != "pass":
                raise GateError("relay route must prove caller-managed reachable coturn")
        elif assertions.get("caller_managed_reachable_coturn_route") != "not_exercised":
            raise GateError("direct route must not claim caller-managed reachable coturn")
        _reject_unpermitted_pass_assertions(assertions, profile=profile, route=str(route))
        _require_boundaries(route_report, profile=profile)
        if profile == "product-interop":
            _require_assertions(assertions, PRODUCT_INTEROP_ASSERTIONS)
        if profile == "real-capture":
            _require_assertions(assertions, REAL_CAPTURE_ASSERTIONS)
        if profile == "public-internet":
            _require_assertions(assertions, {**REAL_CAPTURE_ASSERTIONS, **PUBLIC_ASSERTIONS})

    _require_boundaries(report, profile=profile)
    _require_same_lease(adb_gates)
    if seen_routes != {"direct", "relay"}:
        raise GateError("combined evidence must include both direct and relay route reports")
    return accepted_commit


def evaluate(path: Path, *, expected_commit: str, profile: str) -> GateResult:
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        accepted_commit = validate_report(load_json(path), expected_commit=expected_commit, profile=profile)
    except GateError as error:
        return GateResult("blocked", profile, path, checked_at, [str(error)])
    return GateResult(
        "pass",
        profile,
        path,
        checked_at,
        ["current-base Phase 3 Android interop evidence satisfies the requested profile"],
        accepted_commit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--profile",
        choices=("product-interop", "real-capture", "public-internet"),
        default="real-capture",
        help=(
            "product-interop accepts the local direct/forced-coturn Android product-session subset; "
            "real-capture additionally requires ScreenCaptureKit/VideoToolbox to Android MediaCodec proof; "
            "public-internet also requires a public NAT/remote TURN path."
        ),
    )
    parser.add_argument("--expected-commit", help="override the repository HEAD expected in evidence")
    parser.add_argument("--output", type=Path, help="optional gate-result JSON path")
    return parser


def write_output(path: Path, result: GateResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result.to_json(), indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expected_commit: str | None = None
    try:
        repo = args.repo.resolve()
        expected_commit = args.expected_commit or current_commit(repo)
        if args.expected_commit is None:
            require_clean_worktree(repo)
        result = evaluate(args.evidence.resolve(), expected_commit=expected_commit, profile=args.profile)
    except GateError as error:
        if args.output is not None:
            result = GateResult(
                "blocked",
                args.profile,
                args.evidence.resolve(),
                datetime.now(timezone.utc).isoformat(),
                [str(error)],
                expected_commit,
            )
            write_output(args.output, result)
        print(f"Phase 3 Android current-base interop gate: BLOCKED ({error})", file=sys.stderr)
        return 1
    if args.output is not None:
        write_output(args.output, result)
    if result.result != "pass":
        print(
            "Phase 3 Android current-base interop gate: BLOCKED ("
            + "; ".join(result.reasons)
            + ")",
            file=sys.stderr,
        )
        return 1
    print(f"Phase 3 Android current-base interop gate: PASS ({result.accepted_commit})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
