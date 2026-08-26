import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
ANDROID_GATE = ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/internet/security/AdvancedChannelSecurityGate.kt"
SWIFT_GATE = ROOT / "baseline/MacHost/Sources/Phase3/Security/AdvancedChannelSecurityGate.swift"
FIXTURE_GENERATOR = ROOT / "contracts/fixtures/channel-security/v1/generate.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(source: str) -> str:
    return re.sub(r"[\s_]", "", source)


class AdvancedChannelSecurityGateStaticTests(unittest.TestCase):
    def test_advanced_channel_gate_exists_on_android_and_macos(self) -> None:
        android = _read(ANDROID_GATE)
        swift = _read(SWIFT_GATE)

        for source in (android, swift):
            self.assertIn("AdvancedChannelOwner", source)
            self.assertIn("AdvancedChannelBinding", source)
            self.assertIn("AdvancedChannelAdmission", source)
            self.assertIn("AdvancedChannelSecurityGate", source)
            self.assertIn("sessionEpoch > 0", source)
            self.assertIn("generation > 0", source)
            self.assertIn("replaceOwner", source)
            self.assertTrue("admissions.clear" in source or "admissions.removeAll" in source)

    def test_advanced_channel_gate_is_limited_to_audio_and_bulk_channels(self) -> None:
        android = _read(ANDROID_GATE)
        swift = _read(SWIFT_GATE)

        self.assertIn("override val channel = SecurityChannel.AUDIO", android)
        self.assertIn("override val channel = SecurityChannel.BULK", android)
        self.assertIn("case .audio: return .audio", swift)
        self.assertIn("case .bulk: return .bulk", swift)
        self.assertNotIn("SecurityChannel.CONTROL", android)
        self.assertNotIn("SecurityChannel.MEDIA", android)
        self.assertNotIn("case .control", swift)
        self.assertNotIn("case .media", swift)

    def test_advanced_channel_gate_limits_match_record_contracts(self) -> None:
        android_gate = _read(ANDROID_GATE)
        swift_gate = _read(SWIFT_GATE)

        self.assertIn("InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES", android_gate)
        self.assertIn("InternetBulkRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES", android_gate)
        self.assertIn("InternetAudioRecordContract.maximumPlaintextRecordBytes", swift_gate)
        self.assertIn("InternetBulkRecordContract.maximumPlaintextRecordBytes", swift_gate)
        self.assertIn("maximumAudioBacklogBytes = 1024 * 1024", android_gate)
        self.assertIn("maximumBulkBacklogBytes = 4 * 1024 * 1024", android_gate)
        normalized_swift = _normalized(swift_gate)
        self.assertIn("maximumAudioBacklogBytes:1024*1024", normalized_swift)
        self.assertIn("maximumBulkBacklogBytes:4*1024*1024", normalized_swift)

    def test_channel_security_fixture_generator_uses_unoptimized_self_check(self) -> None:
        generator = _read(FIXTURE_GENERATOR)

        self.assertNotIn("assert known.hex()", generator)
        self.assertIn("AES-GCM known-vector mismatch", generator)


if __name__ == "__main__":
    unittest.main()
