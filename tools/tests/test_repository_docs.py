from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPOSITORY_ROOT / "README.md"
AV1_GATE_PATH = (
    REPOSITORY_ROOT / "docs/changes/2026-08-21-av1-codec-capability/TEST.md"
)
AV1_BLOCKED_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "docs/changes/2026-08-21-av1-codec-capability/evidence"
    / "2026-08-21-av1-offline-blocked/README.md"
)


class RepositoryDocsTests(unittest.TestCase):
    def test_readme_current_video_status_does_not_claim_shipped_av1(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        video_rows = [line for line in readme.splitlines() if line.startswith("| Video |")]

        self.assertEqual(len(video_rows), 1)
        row = video_rows[0]
        self.assertIn("VideoToolbox HEVC/H.264 encoding", row)
        self.assertIn("Android MediaCodec HEVC/H.264 decode", row)
        self.assertIn("AV1 is not a current Host/device stream codec", row)
        self.assertIn("Protocol v1 only reserves CODEC_AV1", row)
        self.assertIn("the current Host does not advertise AV1", row)
        self.assertIn("no AV1 real-stream Host/device acceptance is recorded", row)
        self.assertIn("docs/changes/2026-08-21-av1-codec-capability/TEST.md", row)
        self.assertNotIn("AV1 when supported", row)
        self.assertNotIn("real AV1 support", row)

    def test_readme_macos_and_ios_av1_status_remains_future_or_rejected(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        normalized_readme = " ".join(readme.split())

        self.assertIn("reserves CODEC_AV1 for a future AV1-capable Host", readme)
        self.assertIn("Host has no AV1 encoder/packaging path", readme)
        self.assertIn("never advertises AV1", readme)
        self.assertIn(
            "AV1 protocol-enum recognition with explicit rejection because no AV1 decoder is implemented",
            normalized_readme,
        )
        self.assertNotIn("unless both peers expose real AV1 support", readme)

    def test_av1_gate_records_current_base_as_blocked_not_shipped(self) -> None:
        gate = AV1_GATE_PATH.read_text(encoding="utf-8")
        blocked_evidence = AV1_BLOCKED_EVIDENCE_PATH.read_text(encoding="utf-8")

        self.assertIn("real AV1 stream blocked", gate)
        self.assertIn("No AV1-capable macOS Host stream", gate)
        self.assertIn("current Host does not advertise AV1", gate)
        self.assertIn("AV1 real-stream acceptance is still blocked", blocked_evidence)
        self.assertIn("must not be cited as AV1 Host/device streaming evidence", blocked_evidence)


if __name__ == "__main__":
    unittest.main()
