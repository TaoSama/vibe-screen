"""Create the file-transfer/WebRTC bulk current-base aggregate manifest.

The manifest is intentionally read-only and fail-closed. It links the existing
Android USB/LAN file-transfer gate to the existing Phase 3 WebRTC bulk
product-flow gate without running ADB, launching the Host, or probing signing,
TCC, Keychain, or device state. Missing child gate reports are recorded as
blocked placeholders.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import SCHEMA_VERSION
from .manifest import ManifestError, repository_state

KIND = "file_transfer_bulk_current_base_readiness_manifest"
AGGREGATE_OWNER = "current-base-file-transfer-bulk"
REPOSITORY_FULL_NAME = "TaoSama/vibe-screen"
READINESS_BASELINE_PR = "#265"

ANDROID_CHILD_ID = "android_usb_lan_file_transfer"
WEBRTC_CHILD_ID = "webrtc_bulk_product_flow"
CLIPBOARD_BOUNDARY_ID = "clipboard_boundary"

SOURCE_DOCS = [
    "README.md",
    "tools/README.md",
    "docs/testing.md",
    "docs/changes/2026-08-16-android-macos-clipboard/TEST.md",
    "docs/changes/2026-08-21-file-transfer-e2e/TEST.md",
    "docs/changes/2026-08-04-phase-3-secure-internet/TEST.md",
    "docs/changes/2026-08-22-open-gates-coverage-audit/README.md",
    "docs/changes/2026-08-22-phase3-current-base-aggregation/README.md",
]

DEFAULT_LIMITATIONS = [
    "This aggregate does not create Android USB/LAN file-transfer pass evidence.",
    "This aggregate does not create public Internet WebRTC bulk product-flow pass evidence.",
    "Nubia P0110 evidence may contribute to the Android USB/LAN file-transfer child gate only when that child gate passes from retained product evidence.",
    "Nubia P0110-only USB/LAN evidence cannot close the public Internet WebRTC bulk child gate.",
    "Clipboard remains a separate Android ClipboardManager <-> macOS NSPasteboard gate and is never claimed by this aggregate.",
]

CHILD_GATE_DEFAULTS = {
    ANDROID_CHILD_ID: {
        "kind": "android_macos_file_transfer_smoke",
        "source_gate": "file-transfer-android-smoke",
        "required_flag": "can_close_file_transfer_android_smoke_gate",
        "requirement": (
            "Real Android USB or trusted-LAN Protocol v1 file transfer passes "
            "with signed/TCC-ready Host, bidirectional product evidence, retained "
            "artifacts, final SHA-256 equality, and cancel cleanup."
        ),
    },
    WEBRTC_CHILD_ID: {
        "kind": "phase3_webrtc_bulk_product_flow_gate",
        "source_gate": "phase3-webrtc-bulk-product-flow",
        "required_flag": "can_close_public_internet_bulk_product_flow_gate",
        "requirement": (
            "Real macOS and Android peers use public Internet WebRTC bulk "
            "DataChannel product-flow evidence with retained artifacts, route "
            "proof, bounded backlog, cleanup, and release prerequisite coverage."
        ),
    },
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read child gate {path}: {error}") from error
    if not isinstance(document, dict):
        raise ManifestError(f"child gate {path} must be a JSON object")
    return document


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return [item for item in value if item.strip()]


def _relative_path(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path)


def _child_gate_summary(
    *,
    child_id: str,
    path: Path | None,
    repo: Path,
) -> dict[str, Any]:
    defaults = CHILD_GATE_DEFAULTS[child_id]
    summary: dict[str, Any] = {
        "source_gate": defaults["source_gate"],
        "path": _relative_path(path, repo) if path is not None else None,
        "present": False,
        "kind": defaults["kind"],
        "verdict": "blocked",
        "gate_closed": False,
        "required_flag": defaults["required_flag"],
        "can_close": False,
        "requirement": defaults["requirement"],
        "blockers": [f"missing child gate report for {defaults['source_gate']}"],
        "not_proven": [],
    }
    if path is None or not path.is_file():
        return summary

    report = _load_json(path)
    verdict = report.get("verdict", report.get("result", "blocked"))
    summary.update(
        {
            "present": True,
            "kind": report.get("kind"),
            "verdict": verdict if isinstance(verdict, str) else "blocked",
            "gate_closed": report.get("gate_closed") is True,
            "can_close": report.get(str(defaults["required_flag"])) is True,
            "blockers": _string_list(report.get("blockers")) or _string_list(report.get("reasons")),
            "not_proven": _string_list(report.get("not_proven")),
        }
    )
    return summary


def _source_doc_status(repo: Path) -> dict[str, Any]:
    missing = [path for path in SOURCE_DOCS if not (repo / path).is_file()]
    return {"paths": list(SOURCE_DOCS), "missing": missing}


def build_manifest(
    *,
    command: Sequence[str],
    repo: Path,
    android_gate: Path | None = None,
    webrtc_gate: Path | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "run_id": str(uuid.uuid4()),
        "created_at": _utc_timestamp(),
        "command": list(command),
        "repository": repository_state(repo),
        "source_root": str(repo),
        "owner": {
            "aggregate": AGGREGATE_OWNER,
            "readiness_baseline_pr": READINESS_BASELINE_PR,
            "repository": REPOSITORY_FULL_NAME,
            "child_gates": [ANDROID_CHILD_ID, WEBRTC_CHILD_ID],
            "adjacent_gate_boundaries": [CLIPBOARD_BOUNDARY_ID],
        },
        "source_docs": _source_doc_status(repo),
        "evidence_boundary": {
            "p0110_can_close_usb_lan_file_transfer": True,
            "p0110_can_close_webrtc_bulk_public_internet": False,
            "clipboard_is_separate_gate": True,
            "aggregate_claims_clipboard_gate": False,
            "aggregate_runs_external_collectors": False,
        },
        "child_gates": {
            ANDROID_CHILD_ID: _child_gate_summary(child_id=ANDROID_CHILD_ID, path=android_gate, repo=repo),
            WEBRTC_CHILD_ID: _child_gate_summary(child_id=WEBRTC_CHILD_ID, path=webrtc_gate, repo=repo),
        },
        "limitations": list(DEFAULT_LIMITATIONS),
        "notes": notes,
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--file-transfer-android-smoke-gate", type=Path)
    parser.add_argument("--webrtc-bulk-product-flow-gate", type=Path)
    parser.add_argument("--notes")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Exact evidence command, placed after -- (optional)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    try:
        manifest = build_manifest(
            command=command,
            repo=args.repo,
            android_gate=args.file_transfer_android_smoke_gate,
            webrtc_gate=args.webrtc_bulk_product_flow_gate,
            notes=args.notes,
        )
        write_json(args.output, manifest)
    except (ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
