"""Validate trusted-LAN smoke evidence packages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import SCHEMA_VERSION


STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_INSUFFICIENT = "insufficient"
GATE_PROFILE = "trusted-lan-current-worktree-smoke"
TEXT_SUFFIXES = {".err", ".exit", ".json", ".jsonl", ".log", ".md", ".txt", ".xml"}
DERIVED_OUTPUT_FILES = {"trusted-lan-smoke-verdict.json"}
EXPECTED_DEVICE_MARKERS = ("nubia", "p0110", "pacific", "android 16")
FORBIDDEN_DEVICE_CLAIM_RE = re.compile(r"\b(xiaomi\s*13|fuxi)\b", re.IGNORECASE)
DEVICE_LABEL_RE = re.compile(r"^(?:device|target device|observed device)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
SENSITIVE_PAIRING_RE = re.compile(
    r"(telemachus://[^\s]+|vibescreen://[^\s]+|\btoken\s*[=:]\s*[A-Za-z0-9+/=_-]{32,})",
    re.IGNORECASE,
)
BLOCKED_NETWORK_MARKERS = (
    "wifi is not connected",
    "no-carrier",
    "state down",
    "no route",
    "network is unreachable",
)
BLOCKED_SIGNING_MARKERS = (
    "0 valid identities found",
    "codesign identity",
    "signing identity",
    "vibe screen dev",
)
PASS_MARKERS = {
    "host_secure_records": "trusted lan secure records negotiated",
    "android_secure_records": "trusted lan encrypted records",
    "protocol_lan": "transport_kind_lan",
    "decoder": "hevc",
    "first_output_frame": "first output frame",
    "continuing_frames": "continuing frame",
    "host_pid": "host pid",
}
RECONNECT_PASS_MARKERS = (
    "reconnect succeeded",
    "reconnected with host pid preserved",
    "host pid preserved",
)
LOCK_MARKERS = (
    "/tmp/vibe-screen-device-android.lock",
    "android_device_lock_acquired",
)
TELEMETRY_ENCRYPTED_RE = re.compile(r'"?trusted_lan_encrypted"?\s*(?:=|:|to)\s*(?:true|True)')
TELEMETRY_NOT_LEGACY_RE = re.compile(r'"?trusted_lan_legacy_plaintext"?\s*(?:=|:|to)\s*(?:false|False)')


class TrustedLANSmokeEvidenceError(ValueError):
    """Raised when a trusted-LAN smoke evidence record is malformed."""


def read_text_files(evidence_dir: Path) -> dict[str, str]:
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"evidence directory not found: {evidence_dir}")
    result: dict[str, str] = {}
    for path in sorted(evidence_dir.iterdir()):
        if (
            path.is_file()
            and path.name not in DERIVED_OUTPUT_FILES
            and path.suffix.lower() in TEXT_SUFFIXES
        ):
            result[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return result


def _joined_text(files: dict[str, str]) -> str:
    return "\n".join(files[name] for name in sorted(files))


def _contains_any(haystack: str, markers: Iterable[str]) -> bool:
    return any(marker in haystack for marker in markers)


def _missing_pass_markers(lowered: str) -> list[str]:
    missing = [name for name, marker in PASS_MARKERS.items() if marker not in lowered]
    if TELEMETRY_ENCRYPTED_RE.search(lowered) is None:
        missing.append("telemetry_encrypted")
    if TELEMETRY_NOT_LEGACY_RE.search(lowered) is None:
        missing.append("telemetry_not_legacy_false")
    if not _contains_any(lowered, RECONNECT_PASS_MARKERS):
        missing.append("reconnect_success")
    return missing


def _blocked_state(readme_lower: str, lowered: str) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    if not _contains_any(lowered, BLOCKED_NETWORK_MARKERS):
        missing.append("concrete Wi-Fi/route blocker")
    if not _contains_any(lowered, BLOCKED_SIGNING_MARKERS):
        missing.append("concrete Host signing/preflight blocker")
    if (
        "no real trusted-lan stream" not in readme_lower
        and "observed no real trusted-lan" not in readme_lower
    ):
        missing.append("explicit no-real-stream statement")
    return missing, _missing_pass_markers(lowered)


def evaluate_evidence_dir(evidence_dir: Path) -> dict[str, Any]:
    files = read_text_files(evidence_dir)
    text = _joined_text(files)
    lowered = text.lower()
    readme = files.get("README.md", "")
    readme_lower = readme.lower()
    errors: list[str] = []
    warnings: list[str] = []

    if not readme:
        errors.append("README.md is required")

    missing_device = [marker for marker in EXPECTED_DEVICE_MARKERS if marker not in lowered]
    if missing_device:
        errors.append(
            "missing Nubia P0110/pacific/Android 16 identity markers: "
            + ", ".join(missing_device)
        )
    if not _contains_any(lowered, LOCK_MARKERS):
        errors.append("evidence must record /tmp/vibe-screen-device-android.lock acquisition or equivalent lock observation")

    device_labels = DEVICE_LABEL_RE.findall(readme)
    if any(FORBIDDEN_DEVICE_CLAIM_RE.search(label) for label in device_labels):
        errors.append("README.md must not label Nubia P0110/pacific evidence as Xiaomi 13/fuxi")

    missing_pass = _missing_pass_markers(lowered)
    has_pass_signals = not missing_pass
    is_blocked = "blocked" in readme_lower

    if is_blocked:
        missing_blocked, _ = _blocked_state(readme_lower, lowered)
        if has_pass_signals:
            errors.append("blocked evidence also contains complete pass markers")
        for missing in missing_blocked:
            errors.append(f"blocked evidence must include {missing}")
        verdict = STATUS_BLOCKED if not errors else STATUS_INSUFFICIENT
    elif has_pass_signals:
        if "trusted_lan_legacy_plaintext=true" in lowered:
            errors.append("pass evidence must not include trusted_lan_legacy_plaintext=true")
        verdict = STATUS_PASS if not errors else STATUS_INSUFFICIENT
    else:
        errors.append(
            "evidence is neither blocked nor complete pass; missing pass markers: "
            + ", ".join(missing_pass)
        )
        verdict = STATUS_INSUFFICIENT

    if SENSITIVE_PAIRING_RE.search(text):
        warnings.append("review retained files for accidental QR payload or pairing token disclosure")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "trusted_lan_smoke_evidence",
        "profile": GATE_PROFILE,
        "evidence_dir": str(evidence_dir),
        "files_checked": sorted(files),
        "verdict": verdict,
        "can_close_trusted_lan_stream_gate": verdict == STATUS_PASS,
        "can_close_trusted_lan_reconnect_gate": verdict == STATUS_PASS,
        "device_identity_requirement": (
            "Nubia P0110/pacific/Android 16 evidence must remain labeled as "
            "Nubia P0110/pacific and must not be relabeled as Xiaomi 13/fuxi."
        ),
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--expect",
        choices=("auto", STATUS_PASS, STATUS_BLOCKED),
        default="auto",
        help="Expected verdict. auto accepts pass or blocked but rejects insufficient evidence.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_evidence_dir(args.evidence_dir)
    except (OSError, TrustedLANSmokeEvidenceError, ValueError) as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "kind": "trusted_lan_smoke_evidence",
            "profile": GATE_PROFILE,
            "evidence_dir": str(args.evidence_dir),
            "files_checked": [],
            "verdict": STATUS_INSUFFICIENT,
            "can_close_trusted_lan_stream_gate": False,
            "can_close_trusted_lan_reconnect_gate": False,
            "device_identity_requirement": (
                "Nubia P0110/pacific/Android 16 evidence must remain labeled as "
                "Nubia P0110/pacific and must not be relabeled as Xiaomi 13/fuxi."
            ),
            "errors": [str(error)],
            "warnings": [],
        }
    if args.expect != "auto" and report["verdict"] != args.expect:
        report["errors"].append(f"expected {args.expect}, got {report['verdict']}")
        report["verdict"] = STATUS_INSUFFICIENT
        report["can_close_trusted_lan_stream_gate"] = False
        report["can_close_trusted_lan_reconnect_gate"] = False

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0 if report["verdict"] in {STATUS_PASS, STATUS_BLOCKED} else 1


if __name__ == "__main__":
    raise SystemExit(main())
