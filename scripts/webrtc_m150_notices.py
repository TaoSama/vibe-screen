"""Fail-closed validation for the reviewed WebRTC M150 notice bundle."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import generate_webrtc_m150_notices


NOTICE_RELATIVE_PATH = Path(
    "baseline/MacHost/Sources/Phase3/InternetTransport/ThirdParty/"
    "WebRTC-M150-THIRD-PARTY-NOTICES.md"
)
NOTICE_SHA256 = "896890245459abac28f8b7223f6c68090ffe3447ec95fa8ef99045e88737d3b7"
SOURCE_COUNT = 32
SOURCE_MANIFEST_SHA256 = "8c6c2a3dc7a68fc1f86c768afa14641e71a0d279bfe9bad582a564af6560e75a"


def validate_notice_bundle(repository_root: Path) -> Path:
    sources = generate_webrtc_m150_notices.SOURCES
    if len(sources) != SOURCE_COUNT:
        raise ValueError(f"WebRTC M150 source manifest must contain exactly {SOURCE_COUNT} components")
    source_manifest = json.dumps(sources, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    actual_manifest_sha256 = hashlib.sha256(source_manifest).hexdigest()
    if actual_manifest_sha256 != SOURCE_MANIFEST_SHA256:
        raise ValueError(
            "WebRTC M150 source manifest SHA-256 mismatch: "
            f"expected {SOURCE_MANIFEST_SHA256}, found {actual_manifest_sha256}"
        )
    notice_path = repository_root / NOTICE_RELATIVE_PATH
    if not notice_path.is_file():
        raise FileNotFoundError(f"required WebRTC M150 notice bundle is missing: {NOTICE_RELATIVE_PATH}")
    actual_sha256 = hashlib.sha256(notice_path.read_bytes()).hexdigest()
    if actual_sha256 != NOTICE_SHA256:
        raise ValueError(
            "WebRTC M150 notice bundle SHA-256 mismatch: "
            f"expected {NOTICE_SHA256}, found {actual_sha256}"
        )
    notice_text = notice_path.read_text(encoding="utf-8")
    section_names = re.findall(r"^## (.+)$", notice_text, flags=re.MULTILINE)
    expected_names = [source[0] for source in sources]
    if section_names != expected_names:
        raise ValueError("WebRTC M150 notice sections do not match the reviewed source manifest")
    for name, repository, revision, source_path in sources:
        source_marker = f"Source: `{repository}` at `{revision}`, path `{source_path}`."
        if notice_text.count(source_marker) != 1:
            raise ValueError(f"WebRTC M150 notice source metadata mismatch for {name}")
    return notice_path
