#!/usr/bin/env python3
"""Reproduce the conservative third-party notice bundle for WebRTC M150."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


WEBRTC_REVISION = "1f975dfd761af6e5d76d28333191973b258d82a8"
GENERATOR_SHA256 = "242497538da856ba1b7b50daedb59afb7f34a67439b94b69166bc8e9319e8604"
CHROMIUM_THIRD_PARTY = (
    "https://chromium.googlesource.com/chromium/src/third_party",
    "7c92732938de0ef7e28f5da231994723f938f407",
)
WEBRTC = ("https://webrtc.googlesource.com/src", WEBRTC_REVISION)
SOURCES = (
    ("abseil-cpp", *CHROMIUM_THIRD_PARTY, "abseil-cpp/LICENSE"),
    ("boringssl", "https://boringssl.googlesource.com/boringssl", "f91f1447397c6719f9774dfb8e67329378e1f3d3", "LICENSE"),
    ("boringssl-fiat", "https://boringssl.googlesource.com/boringssl", "f91f1447397c6719f9774dfb8e67329378e1f3d3", "third_party/fiat/LICENSE"),
    ("crc32c", "https://chromium.googlesource.com/external/github.com/google/crc32c", "d3d60ac6e0f16780bcfcc825385e1d338801a558", "LICENSE"),
    ("compiler-rt", "https://chromium.googlesource.com/external/github.com/llvm/llvm-project/compiler-rt", "b7f9fa6b211b362d3ca07ab2043419ebaf75d1d0", "LICENSE.TXT"),
    ("cpu_features", "https://chromium.googlesource.com/external/github.com/google/cpu_features", "d3b2440fcfc25fe8e6d0d4a85f06d68e98312f5b", "LICENSE"),
    ("dav1d", *CHROMIUM_THIRD_PARTY, "dav1d/LICENSE"),
    ("jsoncpp", *CHROMIUM_THIRD_PARTY, "jsoncpp/LICENSE"),
    ("libaom", "https://aomedia.googlesource.com/aom", "c213343c8d32bcae729fe09fcba16e1f371cb23b", "LICENSE"),
    ("libc++", "https://chromium.googlesource.com/external/github.com/llvm/llvm-project/libcxx", "5abc7f839700f0f17338434e1c1c6a8c87c00c11", "LICENSE.TXT"),
    ("libc++abi", "https://chromium.googlesource.com/external/github.com/llvm/llvm-project/libcxxabi", "8f11bb1d4438d0239d0dfc1bd9456a9f31629dda", "LICENSE.TXT"),
    ("libjpeg_turbo", "https://chromium.googlesource.com/chromium/deps/libjpeg_turbo", "640f254ad0fa03f6b1f29f89b7dd9366f2f6e533", "LICENSE.md"),
    ("libsrtp", "https://chromium.googlesource.com/chromium/deps/libsrtp", "cd5d177bf1fde755ddb4c7f0d9ff7693f8b49e5e", "LICENSE"),
    ("libunwind", "https://chromium.googlesource.com/external/github.com/llvm/llvm-project/libunwind", "d6c7a21e978f0adaa43accaad53bc64f0b64f6ec", "LICENSE.TXT"),
    ("libvpx", "https://chromium.googlesource.com/webm/libvpx", "31af37b1bd2774d11a932c1cd9a3849328375f64", "LICENSE"),
    ("libyuv", "https://chromium.googlesource.com/libyuv/libyuv", "de63bd90f4396313f864ad58b65279e7894451a9", "LICENSE"),
    ("llvm-libc", "https://chromium.googlesource.com/external/github.com/llvm/llvm-project/libc", "be95a36286a288c9437f5ed991720ccece1a6391", "LICENSE.TXT"),
    ("nasm", "https://chromium.googlesource.com/chromium/deps/nasm", "525a09a813be0f75b646ee93fc2a31c27b87d722", "LICENSE"),
    ("opus", *CHROMIUM_THIRD_PARTY, "opus/src/COPYING"),
    ("pffft", *CHROMIUM_THIRD_PARTY, "pffft/LICENSE"),
    ("protobuf", *CHROMIUM_THIRD_PARTY, "protobuf/LICENSE"),
    ("protobuf-javascript", *CHROMIUM_THIRD_PARTY, "protobuf-javascript/LICENSE"),
    ("rnnoise", *CHROMIUM_THIRD_PARTY, "rnnoise/COPYING"),
    ("zlib", *CHROMIUM_THIRD_PARTY, "zlib/LICENSE"),
    ("jni_zero", *CHROMIUM_THIRD_PARTY, "jni_zero/LICENSE"),
    ("perfetto", "https://chromium.googlesource.com/external/github.com/google/perfetto", "82ad4b69cbaf64e26c639061b1712756a9cc5e20", "LICENSE"),
    ("webrtc-portaudio", *WEBRTC, "modules/third_party/portaudio/LICENSE"),
    ("webrtc-fft", *WEBRTC, "modules/third_party/fft/LICENSE"),
    ("webrtc-g711", *WEBRTC, "modules/third_party/g711/LICENSE"),
    ("webrtc-g722", *WEBRTC, "modules/third_party/g722/LICENSE"),
    ("webrtc-ooura", *WEBRTC, "common_audio/third_party/ooura/LICENSE"),
    ("webrtc-spl_sqrt_floor", *WEBRTC, "common_audio/third_party/spl_sqrt_floor/LICENSE"),
)


def source_manifest_sha256() -> str:
    manifest = json.dumps(SOURCES, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(manifest).hexdigest()


def fetch_text(repository: str, revision: str, path: str) -> str:
    url = f"{repository}/+show/{revision}/{path}?format=TEXT"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return base64.b64decode(response.read()).decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def render() -> str:
    header = f"""# WebRTC M150 third-party license notices

This is an intentionally conservative license superset for the stasel WebRTC
150.0.0 binary. It covers every non-Android, non-empty license mapping with a
current source path in Google WebRTC's `tools_webrtc/libs/generate_licenses.py`
at source commit `{WEBRTC_REVISION}`, including mappings that may not be linked
into the macOS framework. Build-target-specific GN output was not published
with the binary, so this superset is used to avoid under-attribution. The
generator's obsolete `rtc_base/third_party/base64/LICENSE` mapping is absent
from that source revision; current `rtc_base/base64.*` is covered by WebRTC's
license. This bundle is independent of the Android M144 notice bundle.

The exact upstream generator SHA-256 is `{GENERATOR_SHA256}`. Exact source
repositories, revisions, paths, and source-text hashes are recorded before
each notice below. The ordered 32-component source manifest SHA-256 is
`{source_manifest_sha256()}`. Google WebRTC's own license is retained
separately in `WebRTC-LICENSE.md`. Displayed license text removes trailing
horizontal whitespace from each source line; the recorded source-text hashes
cover the unmodified upstream bytes after UTF-8 decoding.

"""
    sections = []
    for name, repository, revision, path in SOURCES:
        license_text = fetch_text(repository, revision, path)
        digest = hashlib.sha256(license_text.encode("utf-8")).hexdigest()
        normalized_license_text = "\n".join(line.rstrip() for line in license_text.splitlines())
        sections.append(
            f"## {name}\n\nSource: `{repository}` at `{revision}`, path `{path}`.\n"
            f"Source text SHA-256: `{digest}`.\n\n```text\n{normalized_license_text.rstrip()}\n```\n"
        )
    return header + "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
