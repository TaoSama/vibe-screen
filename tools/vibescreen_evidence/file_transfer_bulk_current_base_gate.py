"""Evaluate the file-transfer/WebRTC bulk current-base aggregate gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .file_transfer_bulk_current_base_manifest import (
    AGGREGATE_OWNER,
    ANDROID_CHILD_ID,
    KIND as MANIFEST_KIND,
    READINESS_BASELINE_PR,
    REPOSITORY_FULL_NAME,
    SOURCE_DOCS,
    WEBRTC_CHILD_ID,
)

KIND = "file_transfer_bulk_current_base_readiness_gate"
PASS = "pass"
BLOCKED = "blocked"
INSUFFICIENT = "insufficient"
FAIL = "fail"

INTERPRETATION = (
    "A pass means both existing child gates have retained pass evidence: Android "
    "USB/LAN Protocol v1 file transfer and public Internet WebRTC bulk "
    "product-flow. This aggregate never closes the clipboard gate and never turns "
    "USB/LAN evidence into WebRTC Internet evidence."
)


class FileTransferBulkCurrentBaseGateError(ValueError):
    """Raised when an aggregate manifest cannot be evaluated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FileTransferBulkCurrentBaseGateError(f"cannot read aggregate manifest: {error}") from error
    if not isinstance(document, dict):
        raise FileTransferBulkCurrentBaseGateError("aggregate manifest must be a JSON object")
    return document


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _check(passed: bool, expected: str, *, evidence: Sequence[str] = (), blocking: bool = True) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "evidence": list(evidence),
        "blocking": blocking,
    }


def _validate_manifest_contract(manifest: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "kind",
        "run_id",
        "created_at",
        "command",
        "repository",
        "source_root",
        "owner",
        "source_docs",
        "evidence_boundary",
        "child_gates",
        "limitations",
        "notes",
    }
    missing = sorted(field for field in required if field not in manifest)
    if missing:
        raise FileTransferBulkCurrentBaseGateError(
            "manifest schema violation: missing required field(s): " + ", ".join(missing)
        )
    if not isinstance(manifest.get("child_gates"), dict):
        raise FileTransferBulkCurrentBaseGateError("manifest schema violation: child_gates must be an object")
    for child_id in (ANDROID_CHILD_ID, WEBRTC_CHILD_ID):
        if not isinstance(manifest["child_gates"].get(child_id), dict):
            raise FileTransferBulkCurrentBaseGateError(
                f"manifest schema violation: child_gates.{child_id} must be an object"
            )


def _metadata_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    owner = _dict(manifest.get("owner"))
    repository = _dict(manifest.get("repository"))
    source_docs = _dict(manifest.get("source_docs"))
    return {
        "schema_version": _check(manifest.get("schema_version") == SCHEMA_VERSION, SCHEMA_VERSION),
        "kind": _check(manifest.get("kind") == MANIFEST_KIND, MANIFEST_KIND),
        "aggregate_owner": _check(owner.get("aggregate") == AGGREGATE_OWNER, AGGREGATE_OWNER),
        "readiness_baseline": _check(
            owner.get("readiness_baseline_pr") == READINESS_BASELINE_PR,
            f"merged readiness baseline {READINESS_BASELINE_PR}",
        ),
        "repository": _check(owner.get("repository") == REPOSITORY_FULL_NAME, REPOSITORY_FULL_NAME),
        "repository_clean": _check(
            repository.get("dirty") is False,
            "manifest was collected from a clean worktree",
            evidence=_string_list(repository.get("status_porcelain")),
        ),
        "source_docs": _check(
            set(SOURCE_DOCS).issubset(set(_string_list(source_docs.get("paths"))))
            and _string_list(source_docs.get("missing")) == [],
            "all aggregate source documents are present",
            evidence=_string_list(source_docs.get("missing")),
        ),
    }


def _boundary_checks(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    boundary = _dict(manifest.get("evidence_boundary"))
    return {
        "p0110_usb_lan_only": _check(
            boundary.get("p0110_can_close_usb_lan_file_transfer") is True,
            "P0110 can contribute only to Android USB/LAN file-transfer evidence",
        ),
        "p0110_not_webrtc_bulk": _check(
            boundary.get("p0110_can_close_webrtc_bulk_public_internet") is False,
            "P0110-only evidence cannot close WebRTC bulk public-Internet evidence",
        ),
        "clipboard_separate": _check(
            boundary.get("clipboard_is_separate_gate") is True
            and boundary.get("aggregate_claims_clipboard_gate") is False,
            "clipboard remains a separate gate and is not claimed here",
        ),
        "no_external_collectors": _check(
            boundary.get("aggregate_runs_external_collectors") is False,
            "aggregate evaluation is read-only and does not run ADB, Host, TCC, or Keychain collectors",
        ),
    }


def _child_check(child: dict[str, Any], *, required_kind: str, required_flag: str) -> dict[str, Any]:
    expected = f"{required_kind} report has verdict=pass, gate_closed=true, and {required_flag}=true"
    evidence: list[str] = []
    path = child.get("path")
    if isinstance(path, str) and path.strip():
        evidence.append(path)
    blockers = _string_list(child.get("blockers"))
    if blockers:
        evidence.extend(blockers[:6])
    passed = (
        child.get("present") is True
        and child.get("kind") == required_kind
        and child.get("verdict") == PASS
        and child.get("gate_closed") is True
        and child.get("can_close") is True
    )
    return _check(passed, expected, evidence=evidence)


def _child_identity_invalid(child: dict[str, Any], *, required_kind: str) -> bool:
    return child.get("present") is True and child.get("kind") != required_kind


def derive_gate(manifest: dict[str, Any] | Path) -> dict[str, Any]:
    manifest_path: Path | None = manifest if isinstance(manifest, Path) else None
    try:
        if isinstance(manifest, Path):
            manifest = _load_json(manifest)
        _validate_manifest_contract(manifest)

        child_gates = _dict(manifest.get("child_gates"))
        checks: dict[str, dict[str, Any]] = {}
        checks.update({f"metadata.{name}": value for name, value in _metadata_checks(manifest).items()})
        checks.update({f"boundary.{name}": value for name, value in _boundary_checks(manifest).items()})
        checks[f"child.{ANDROID_CHILD_ID}"] = _child_check(
            _dict(child_gates.get(ANDROID_CHILD_ID)),
            required_kind="android_macos_file_transfer_smoke",
            required_flag="can_close_file_transfer_android_smoke_gate",
        )
        checks[f"child.{WEBRTC_CHILD_ID}"] = _child_check(
            _dict(child_gates.get(WEBRTC_CHILD_ID)),
            required_kind="phase3_webrtc_bulk_product_flow_gate",
            required_flag="can_close_public_internet_bulk_product_flow_gate",
        )

        invalid_child_identity = _child_identity_invalid(
            _dict(child_gates.get(ANDROID_CHILD_ID)),
            required_kind="android_macos_file_transfer_smoke",
        ) or _child_identity_invalid(
            _dict(child_gates.get(WEBRTC_CHILD_ID)),
            required_kind="phase3_webrtc_bulk_product_flow_gate",
        )

        android_passed = checks[f"child.{ANDROID_CHILD_ID}"]["passed"]
        webrtc_passed = checks[f"child.{WEBRTC_CHILD_ID}"]["passed"]
        required_context_passed = all(
            check["passed"]
            for name, check in checks.items()
            if name.startswith("metadata.") or name.startswith("boundary.")
        )
        failed = any(
            child_gates.get(child_id, {}).get("verdict") == FAIL
            for child_id in (ANDROID_CHILD_ID, WEBRTC_CHILD_ID)
            if isinstance(child_gates.get(child_id), dict)
        )

        blockers = [
            f"blocked: {name}"
            for name, check in checks.items()
            if not check["passed"] and check.get("blocking") is not False
        ]
        if failed:
            verdict = FAIL
        elif invalid_child_identity:
            verdict = BLOCKED
        elif required_context_passed and android_passed and webrtc_passed:
            verdict = PASS
        elif required_context_passed and (android_passed or webrtc_passed):
            verdict = INSUFFICIENT
        else:
            verdict = BLOCKED

        return {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "generated_at": _utc_now(),
            "derivation_status": "complete",
            "verdict": verdict,
            "gate_closed": verdict == PASS,
            "can_close_android_usb_lan_file_transfer": bool(android_passed and required_context_passed),
            "can_close_webrtc_bulk_product_flow": bool(webrtc_passed and required_context_passed),
            "can_close_current_base_aggregate": verdict == PASS,
            "can_claim_clipboard_gate": False,
            "run_id": manifest.get("run_id"),
            "owner": manifest.get("owner"),
            "source": {"manifest": str(manifest_path) if manifest_path is not None else None},
            "checks": checks,
            "blockers": blockers if verdict != PASS else [],
            "not_proven": [
                item
                for item in (
                    "Android USB/LAN file-transfer child gate pass" if not android_passed else "",
                    "public Internet WebRTC bulk product-flow child gate pass" if not webrtc_passed else "",
                    "clean current-base aggregate source context" if not required_context_passed else "",
                )
                if item
            ],
            "safety": {
                "aggregate_does_not_run_adb": True,
                "aggregate_does_not_launch_host": True,
                "aggregate_does_not_probe_tcc_or_keychain": True,
                "usb_lan_evidence_does_not_close_webrtc_bulk": True,
                "clipboard_evidence_does_not_close_file_transfer_bulk": True,
            },
            "interpretation": INTERPRETATION,
        }
    except FileTransferBulkCurrentBaseGateError as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "generated_at": _utc_now(),
            "derivation_status": "failed",
            "verdict": BLOCKED,
            "gate_closed": False,
            "can_close_android_usb_lan_file_transfer": False,
            "can_close_webrtc_bulk_product_flow": False,
            "can_close_current_base_aggregate": False,
            "can_claim_clipboard_gate": False,
            "run_id": None,
            "owner": None,
            "source": {"manifest": str(manifest_path) if manifest_path is not None else None},
            "checks": {},
            "blockers": [str(error)],
            "not_proven": ["aggregate manifest could not be evaluated"],
            "safety": {
                "aggregate_does_not_run_adb": True,
                "aggregate_does_not_launch_host": True,
                "aggregate_does_not_probe_tcc_or_keychain": True,
            },
            "interpretation": INTERPRETATION,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = derive_gate(args.manifest)
    try:
        _write_json(args.output, report)
    except OSError as error:
        print(f"error: file-transfer bulk current-base gate output could not be written: {error}", file=sys.stderr)
        return 3
    for blocker in report.get("blockers", []):
        print(blocker, file=sys.stderr)
    if report.get("verdict") == PASS:
        return 0
    return 2 if report.get("verdict") == FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
