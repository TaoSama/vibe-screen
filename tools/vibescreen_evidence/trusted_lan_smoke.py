"""Validate trusted-LAN smoke evidence packages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence


TEXT_SUFFIXES = {".err", ".exit", ".json", ".jsonl", ".log", ".md", ".txt", ".xml"}
EXPECTED_DEVICE_MARKERS = ("nubia", "p0110", "pacific", "android 16")
FORBIDDEN_DEVICE_CLAIM_RE = re.compile(r"\b(xiaomi\s*13|fuxi)\b", re.IGNORECASE)
SENSITIVE_PAIRING_RE = re.compile(
    r"(telemachus://[^\s`]+|vibescreen://[^\s`]+|\btoken\s*[=:]\s*[A-Za-z0-9+/=_-]{32,})",
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
    "telemetry_encrypted": "trusted_lan_encrypted",
    "telemetry_not_legacy": "trusted_lan_legacy_plaintext",
    "protocol_lan": "transport_kind_lan",
    "decoder": "hevc",
}
RECONNECT_PASS_MARKERS = ("reconnect succeeded", "reconnected", "host pid preserved")


def read_text_files(evidence_dir: Path) -> dict[str, str]:
    if not evidence_dir.is_dir():
        raise FileNotFoundError(f"evidence directory not found: {evidence_dir}")
    result: dict[str, str] = {}
    for path in sorted(evidence_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            result[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return result


def joined_text(files: dict[str, str]) -> str:
    return "\n".join(files[name] for name in sorted(files))


def _contains_any(haystack: str, markers: Iterable[str]) -> bool:
    return any(marker in haystack for marker in markers)


def _telemetry_marks_non_legacy(text: str) -> bool:
    encrypted = re.search(r'"?trusted_lan_encrypted"?\s*(?:=|:|to)\s*(?:true|True)', text)
    legacy_false = re.search(r'"?trusted_lan_legacy_plaintext"?\s*(?:=|:|to)\s*(?:false|False)', text)
    return bool(encrypted and legacy_false)


def evaluate_evidence_dir(evidence_dir: Path) -> dict[str, object]:
    files = read_text_files(evidence_dir)
    text = joined_text(files)
    lowered = text.lower()
    readme = files.get("README.md", "")
    readme_lower = readme.lower()
    errors: list[str] = []
    warnings: list[str] = []

    if not readme:
        errors.append("README.md is required")

    missing_device = [marker for marker in EXPECTED_DEVICE_MARKERS if marker not in lowered]
    if missing_device:
        errors.append("missing Nubia P0110/pacific/Android 16 identity markers: " + ", ".join(missing_device))

    if FORBIDDEN_DEVICE_CLAIM_RE.search(readme):
        errors.append("README.md must not label Nubia P0110/pacific evidence as Xiaomi 13/fuxi")

    is_blocked = "blocked" in readme_lower
    has_pass_signals = all(
        marker in lowered
        for key, marker in PASS_MARKERS.items()
        if key not in {"telemetry_encrypted", "telemetry_not_legacy"}
    ) and _telemetry_marks_non_legacy(text) and _contains_any(lowered, RECONNECT_PASS_MARKERS)

    if is_blocked:
        if has_pass_signals:
            errors.append("blocked evidence also contains complete pass markers")
        if not _contains_any(lowered, BLOCKED_NETWORK_MARKERS):
            errors.append("blocked evidence must include a concrete Wi-Fi/route blocker")
        if not _contains_any(lowered, BLOCKED_SIGNING_MARKERS):
            errors.append("blocked evidence must include a concrete Host signing/preflight blocker")
        if "no real trusted-lan stream" not in readme_lower and "observed no real trusted-lan" not in readme_lower:
            errors.append("blocked README must explicitly say no real trusted-LAN stream was observed")
        verdict = "blocked" if not errors else "insufficient"
    elif has_pass_signals:
        if "trusted_lan_legacy_plaintext=true" in lowered or '"trusted_lan_legacy_plaintext": true' in lowered:
            errors.append("pass evidence must not include trusted_lan_legacy_plaintext=true")
        verdict = "pass" if not errors else "insufficient"
    else:
        missing_pass = [
            name
            for name, marker in PASS_MARKERS.items()
            if marker not in lowered and name not in {"telemetry_encrypted", "telemetry_not_legacy"}
        ]
        if not _telemetry_marks_non_legacy(text):
            missing_pass.extend(["telemetry_encrypted", "telemetry_not_legacy_false"])
        if not _contains_any(lowered, RECONNECT_PASS_MARKERS):
            missing_pass.append("reconnect_success")
        errors.append("evidence is neither blocked nor complete pass; missing pass markers: " + ", ".join(missing_pass))
        verdict = "insufficient"

    if SENSITIVE_PAIRING_RE.search(text):
        warnings.append("review retained files for accidental QR payload or pairing token disclosure")

    return {
        "evidence_dir": str(evidence_dir),
        "files_checked": sorted(files),
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate trusted-LAN smoke evidence.")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--expect",
        choices=("auto", "pass", "blocked"),
        default="auto",
        help="Expected verdict. auto accepts pass or blocked but still rejects insufficient evidence.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_evidence_dir(args.evidence_dir)
    except (OSError, FileNotFoundError) as error:
        report = {
            "evidence_dir": str(args.evidence_dir),
            "files_checked": [],
            "verdict": "insufficient",
            "errors": [str(error)],
            "warnings": [],
        }
    if args.expect != "auto" and report["verdict"] != args.expect:
        report["errors"].append(f"expected {args.expect}, got {report['verdict']}")
        report["verdict"] = "insufficient"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0 if report["verdict"] in {"pass", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
