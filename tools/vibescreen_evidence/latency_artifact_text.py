"""Shared text checks for retained latency gate artifacts."""

from __future__ import annotations

import re
from pathlib import Path


ARTIFACT_STATE_SUBJECT_PATTERN = (
    r"(?:usb|lan|public|remote|turn\s+endpoint|turns?|stream(?:ing)?|route|"
    r"routed|routing|peer|input|result|proof|evidence|measurement|clock|"
    r"connection|record|synchronization)"
)
ARTIFACT_NEGATED_STATE_PATTERN = (
    r"(?:active|visible|established|connected|measured|available|present|observed|retained)"
)
ARTIFACT_FAILED_STATE_PATTERN = (
    r"(?:failed|inactive|disconnected|absent|unavailable|unobserved)"
)
ARTIFACT_ABSENT_EVIDENCE_SUBJECT_PATTERN = r"(?:evidence|proof|record|measurement)"
LATENCY_ARTIFACT_TERM_PATTERNS = {
    "stream": re.compile(r"(?<![a-z0-9])stream(?:s|ing)?(?![a-z0-9])"),
    "route": re.compile(r"(?<![a-z0-9])rout(?:e|ed|es|ing)(?![a-z0-9])"),
    "turn": re.compile(r"(?<![a-z0-9])turns?(?![a-z0-9])"),
    "physical": re.compile(r"(?<![a-z0-9])physical(?:ly)?(?![a-z0-9])"),
    "visible": re.compile(r"(?<![a-z0-9])visib(?:le|ility)(?![a-z0-9])"),
}


ARTIFACT_BLOCKING_PATTERNS = (
    (re.compile(r"\bno[- ]host\b(?!\s+restart\b)"), "no-Host diagnostic evidence"),
    (re.compile(r"\bdiagnostic(?:s)?[-\s]+only\b"), "diagnostic-only evidence"),
    (re.compile(r"\binformational[-\s]+only\b"), "informational-only evidence"),
    (re.compile(r"\bsummary[- ]only\b"), "summary-only evidence"),
    (re.compile(r"\bpreflight[-\s]+only\b"), "preflight-only evidence"),
    (
        re.compile(r"\bread[- ]only\s+(?:usb\s+)?(?:transport\s+)?observation\b"),
        "read-only observation",
    ),
    (
        re.compile(
            r"\b(?:cannot|can\s*not|must\s+not|does\s+not|do\s+not)\s+"
            r"(?:close|replace|prove)\s+(?:the\s+)?(?:latency\s+|performance\s+)?"
            r"(?:gate|evidence|closure|proof)\b"
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
    (
        re.compile(
            rf"\b{ARTIFACT_STATE_SUBJECT_PATTERN}\b"
            rf"(?:\s+(?:was|is|were|are|became|remained))?\s+"
            rf"(?:not|never)\s+{ARTIFACT_NEGATED_STATE_PATTERN}\b"
        ),
        "negated required-state evidence",
    ),
    (
        re.compile(
            rf"\b{ARTIFACT_STATE_SUBJECT_PATTERN}\b"
            rf"(?:\s+(?:was|is|were|are|became|remained))?\s+"
            rf"{ARTIFACT_FAILED_STATE_PATTERN}\b"
            rf"|\b(?:failed|inactive|disconnected|unavailable|unobserved)\s+"
            rf"{ARTIFACT_STATE_SUBJECT_PATTERN}\b"
            rf"|\babsent\s+{ARTIFACT_ABSENT_EVIDENCE_SUBJECT_PATTERN}\b"
        ),
        "failed or absent evidence state",
    ),
)

LATENCY_ARTIFACT_CONTENT_REQUIREMENTS = {
    "usb_connection": ("usb", "stream"),
    "lan_network_preflight": ("lan", "stream"),
    "internet_public_route_record": ("public", "route", "remote", "turn", "stream"),
    "input_actuation_record": ("physical", "input", "visible"),
    "synchronization_record": ("skew", "drift", "uncertainty", "budget"),
}


def latency_artifact_blocking_reason(text: str) -> str | None:
    normalized = text.lower()
    for pattern, reason in ARTIFACT_BLOCKING_PATTERNS:
        if pattern.search(normalized):
            return reason
    return None


def missing_latency_artifact_terms(text: str, required_terms: tuple[str, ...]) -> list[str]:
    normalized = text.lower()
    missing: list[str] = []
    for term in required_terms:
        pattern = LATENCY_ARTIFACT_TERM_PATTERNS.get(term.lower()) or re.compile(
            rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
        )
        if pattern.search(normalized) is None:
            missing.append(term)
    return missing


def read_latency_artifact_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
