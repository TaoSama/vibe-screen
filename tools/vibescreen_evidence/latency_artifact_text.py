"""Shared text checks for retained latency gate artifacts."""

from __future__ import annotations

import re
from pathlib import Path


ARTIFACT_BLOCKING_PATTERNS = (
    (re.compile(r"\bno-host\b"), "no-Host diagnostic evidence"),
    (re.compile(r"\bdiagnostic(?:s)?\s+only\b"), "diagnostic-only evidence"),
    (re.compile(r"\binformational\s+only\b"), "informational-only evidence"),
    (re.compile(r"\bsummary[- ]only\b"), "summary-only evidence"),
    (re.compile(r"\bpreflight\s+only\b"), "preflight-only evidence"),
    (
        re.compile(r"\bread[- ]only\s+(?:usb\s+)?(?:transport\s+)?observation\b"),
        "read-only observation",
    ),
    (
        re.compile(
            r"\b(?:cannot|can\s*not|must\s+not|does\s+not|do\s+not)\s+"
            r"(?:close|replace|prove)\b"
        ),
        "explicit non-closing evidence",
    ),
    (
        re.compile(r"\bno\s+(?:retained\s+)?synchronized[- ]clock\b"),
        "missing synchronized-clock evidence",
    ),
    (
        re.compile(r"\bno\s+(?:real\s+)?physical[- ]input\b"),
        "missing physical-input evidence",
    ),
)


def latency_artifact_blocking_reason(text: str) -> str | None:
    normalized = text.lower()
    for pattern, reason in ARTIFACT_BLOCKING_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None


def read_latency_artifact_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
