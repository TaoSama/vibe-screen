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
AV1_CURRENT_BASE_BLOCKED_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "docs/changes/2026-08-21-av1-codec-capability/evidence"
    / "2026-08-27-av1-current-base-blocked/README.md"
)
AV1_P0110_CAPABILITY_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "docs/changes/2026-08-21-av1-codec-capability/evidence"
    / "2026-08-28-nubia-p0110-av1-capability-probe/README.md"
)
MAC_CODEC_LIMITS_PATH = REPOSITORY_ROOT / "baseline/MacHost/Sources/CodecLimits.swift"
MAC_VIDEO_ENCODER_PATH = REPOSITORY_ROOT / "baseline/MacHost/Sources/VideoEncoder.swift"
MAC_STREAMING_SERVER_PATH = REPOSITORY_ROOT / "baseline/MacHost/Sources/StreamingServer.swift"
ANDROID_CODEC_CAPABILITIES_PATH = (
    REPOSITORY_ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/CodecCapabilities.kt"
)
ANDROID_RELIABILITY_PATH = (
    REPOSITORY_ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/ReliabilityPrimitives.kt"
)
ANDROID_MAIN_ACTIVITY_PATH = (
    REPOSITORY_ROOT / "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt"
)
IOS_VIDEO_CONFIG_VALIDATOR_PATH = (
    REPOSITORY_ROOT / "apps/ios/Sources/VibeScreenCore/VideoConfigValidator.swift"
)
IOS_VIDEO_DECODER_PATH = REPOSITORY_ROOT / "apps/ios/Sources/VibeScreenVideo/VideoDecoder.swift"
MAC_CODEC_LIMITS_TESTS_PATH = (
    REPOSITORY_ROOT / "baseline/MacHost/Tests/TelemachusTests/CodecLimitsTests.swift"
)
MAC_PROTOCOL_SESSION_TESTS_PATH = (
    REPOSITORY_ROOT / "baseline/MacHost/Tests/TelemachusTests/ProtocolV1SessionTests.swift"
)
MAC_INTERNET_CODEC_TESTS_PATH = (
    REPOSITORY_ROOT
    / "baseline/MacHost/Tests/TelemachusTests/InternetProductProtocolCodecTests.swift"
)
ANDROID_DECODER_SELECTION_TESTS_PATH = (
    REPOSITORY_ROOT
    / "baseline/AndroidClient/app/src/test/java/dev/telemachus/display/DecoderSelectionTest.kt"
)
ANDROID_INTERNET_SESSION_TESTS_PATH = (
    REPOSITORY_ROOT
    / "baseline/AndroidClient/app/src/test/java/dev/telemachus/display/internet/InternetProductSessionTest.kt"
)
IOS_MEDIA_GATE_SELF_TEST_PATH = (
    REPOSITORY_ROOT / "apps/ios/Sources/VibeScreenCore/VideoMediaGateSelfTest.swift"
)
IOS_SELF_TEST_PATH = REPOSITORY_ROOT / "apps/ios/Sources/VibeScreenIOSSelfTest/main.swift"


class AV1CurrentBaseGateTests(unittest.TestCase):
    def test_readme_keeps_av1_as_backlog_not_current_stream_support(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        video_rows = [line for line in readme.splitlines() if line.startswith("| Video |")]

        self.assertEqual(len(video_rows), 1)
        row = video_rows[0]
        self.assertIn("VideoToolbox HEVC/H.264 encoding", row)
        self.assertIn("Android MediaCodec HEVC/H.264 decode", row)
        self.assertIn("AV1 is a later-phase/backlog codec", row)
        self.assertIn("not a current Host/device stream codec", row)
        self.assertIn("Protocol v1 only reserves CODEC_AV1", row)
        self.assertIn("the current Host does not advertise AV1", row)
        self.assertIn("Android does not offer AV1 in product sessions", row)
        self.assertIn("no AV1 real-stream Host/device acceptance is recorded", row)
        self.assertIn("docs/changes/2026-08-21-av1-codec-capability/TEST.md", row)
        self.assertNotIn("AV1 when supported", row)
        self.assertNotIn("real AV1 support", row)

    def test_macos_source_keeps_av1_out_of_current_stream_admission(self) -> None:
        codec_limits = MAC_CODEC_LIMITS_PATH.read_text(encoding="utf-8")
        video_encoder = MAC_VIDEO_ENCODER_PATH.read_text(encoding="utf-8")
        streaming_server = MAC_STREAMING_SERVER_PATH.read_text(encoding="utf-8")

        self.assertRegex(codec_limits, r"enum\s+StreamCodec\s*\{[^}]*case\s+hevc[^}]*case\s+h264")
        self.assertNotRegex(codec_limits, r"enum\s+StreamCodec\s*\{[^}]*case\s+av1")
        self.assertIn("av1HardwareEncoderAvailable", codec_limits)
        self.assertIn("AV1 remains intentionally unadvertised", codec_limits)
        self.assertIn("case .av1, .unspecified, .UNRECOGNIZED: return nil", codec_limits)
        self.assertNotIn("codecs.append(.av1)", codec_limits)
        self.assertNotIn("kCMVideoCodecType_AV1", video_encoder)
        self.assertIn("supportedCodecs: [.hevc, .h264]", streaming_server)
        self.assertNotIn("supportedCodecs: [.av1", streaming_server)

    def test_android_source_keeps_av1_diagnostic_only_and_rejected(self) -> None:
        codec_capabilities = ANDROID_CODEC_CAPABILITIES_PATH.read_text(encoding="utf-8")
        reliability = ANDROID_RELIABILITY_PATH.read_text(encoding="utf-8")
        main_activity = ANDROID_MAIN_ACTIVITY_PATH.read_text(encoding="utf-8")

        self.assertIn("Diagnostic-only until AV1 frame admission is explicitly enabled", codec_capabilities)
        self.assertIn("MediaFormat.MIMETYPE_VIDEO_AV1 -> StreamCodec.AV1", codec_capabilities)
        self.assertIn("StreamCodec.AV1 -> null", codec_capabilities)
        self.assertIn(
            'ProductVideoCodec.AV1 -> return ProductVideoDecision.reject("av1_decoder_unavailable")',
            main_activity,
        )
        self.assertRegex(reliability, r"hasUsableAv1Decoder:[^=]+=[^)]*false")
        self.assertNotRegex(reliability, r"listOf\([^)]*StreamCodec\.AV1")

    def test_ios_source_knows_av1_protocol_enum_but_decoder_rejects_it(self) -> None:
        validator = IOS_VIDEO_CONFIG_VALIDATOR_PATH.read_text(encoding="utf-8")
        decoder = IOS_VIDEO_DECODER_PATH.read_text(encoding="utf-8")

        self.assertIn("case .h264, .hevc, .av1: true", validator)
        self.assertIn("throw VideoConfigValidationError.unsupportedDecodeProfile", validator)
        self.assertNotIn("kCMVideoCodecType_AV1", decoder)
        self.assertIn("throw VideoDecoderError.unsupportedCodec(codec)", decoder)

    def test_native_behavior_tests_cover_current_av1_admission_boundary(self) -> None:
        codec_limits_tests = MAC_CODEC_LIMITS_TESTS_PATH.read_text(encoding="utf-8")
        protocol_session_tests = MAC_PROTOCOL_SESSION_TESTS_PATH.read_text(encoding="utf-8")
        internet_codec_tests = MAC_INTERNET_CODEC_TESTS_PATH.read_text(encoding="utf-8")
        android_decoder_tests = ANDROID_DECODER_SELECTION_TESTS_PATH.read_text(encoding="utf-8")
        android_internet_tests = ANDROID_INTERNET_SESSION_TESTS_PATH.read_text(encoding="utf-8")
        ios_media_gate_self_test = IOS_MEDIA_GATE_SELF_TEST_PATH.read_text(encoding="utf-8")
        ios_self_test = IOS_SELF_TEST_PATH.read_text(encoding="utf-8")

        self.assertIn("testAV1CapabilityProbeDoesNotAdvertiseUnsupportedStreamCodec", codec_limits_tests)
        self.assertIn("testAV1OfferFallsBackToLocallyEncodableCodec", protocol_session_tests)
        self.assertIn("testAV1OnlyOfferFailsClosedUntilHostEncoderExists", protocol_session_tests)
        self.assertIn("testInternetProductVideoConfigurationRejectsAV1UntilEncoderExists", internet_codec_tests)
        self.assertIn("av1ProbeDoesNotEnterAdvertisedCandidatesBeforeAdmissionIsEnabled", android_decoder_tests)
        self.assertIn("av1VideoConfigurationRejectionIsReportedBeforeMediaActivation", android_internet_tests)
        self.assertIn("AV1 config was accepted without an AV1 decode capability", ios_media_gate_self_test)
        self.assertIn("AV1 decoder configuration was accepted without an implementation", ios_self_test)

    def test_gate_document_names_current_base_owner_and_blocked_evidence(self) -> None:
        gate = AV1_GATE_PATH.read_text(encoding="utf-8")
        normalized_gate = " ".join(gate.split())
        blocked_evidence = AV1_BLOCKED_EVIDENCE_PATH.read_text(encoding="utf-8")
        current_evidence = AV1_CURRENT_BASE_BLOCKED_EVIDENCE_PATH.read_text(encoding="utf-8")
        p0110_capability_evidence = AV1_P0110_CAPABILITY_EVIDENCE_PATH.read_text(encoding="utf-8")
        normalized_p0110_capability_evidence = " ".join(p0110_capability_evidence.split())

        self.assertIn("current-base closure owner", gate)
        self.assertIn("tools/tests/test_av1_current_base_gate.py", gate)
        self.assertIn("real AV1 stream blocked", gate)
        self.assertIn("current Host does not advertise AV1", gate)
        self.assertIn("Android does not offer AV1 in product sessions", gate)
        self.assertIn("iOS recognizes CODEC_AV1 but rejects it without local decoder support", normalized_gate)
        self.assertIn("AV1 real-stream acceptance is still blocked", blocked_evidence)
        self.assertIn("Nubia P0110", blocked_evidence)
        self.assertIn("pacific", blocked_evidence)
        self.assertIn("Android 16", blocked_evidence)
        self.assertIn("SDK 36", blocked_evidence)
        self.assertIn("<redacted-device-serial>", blocked_evidence)
        self.assertIn("adb -s <redacted-device-serial>", blocked_evidence)
        self.assertIn("c2.qti.av1.decoder", blocked_evidence)
        self.assertIn("Can't find service: media.codec", blocked_evidence)
        self.assertIn("diagnostic only", blocked_evidence)
        self.assertIn("must not be cited as AV1 Host/device streaming evidence", blocked_evidence)
        self.assertIn("current-base owner refresh", current_evidence)
        self.assertIn("nubia P0110", current_evidence)
        self.assertIn("pacific", current_evidence)
        self.assertIn("Android 16", current_evidence)
        self.assertIn("SDK: 36", current_evidence)
        self.assertIn("<redacted-device-serial>", current_evidence)
        self.assertIn("c2.qti.av1.decoder", current_evidence)
        self.assertIn("must not be cited as AV1 Host/device real-stream acceptance", current_evidence)
        self.assertIn("2026-08-28 Nubia P0110 Android decoder capability probe", gate)
        self.assertIn("capability/readiness snapshot", gate)
        self.assertIn("does not add AV1 Host/device real-stream evidence", normalized_gate)
        self.assertIn("Nubia P0110", p0110_capability_evidence)
        self.assertIn("pacific", p0110_capability_evidence)
        self.assertIn("Android: 16", p0110_capability_evidence)
        self.assertIn("SDK: 36", p0110_capability_evidence)
        self.assertIn("<redacted-device-serial>", p0110_capability_evidence)
        self.assertIn("/tmp/vibe-screen-android-<redacted-device-serial>.lock", p0110_capability_evidence)
        self.assertIn("pgrep -x sfltool || true", p0110_capability_evidence)
        self.assertIn("No /usr/bin/sfltool dumpbtm command was executed", normalized_p0110_capability_evidence)
        self.assertIn("dumpsys media.codec", p0110_capability_evidence)
        self.assertIn("'Can't find service: media.codec' with exit code 0", p0110_capability_evidence)
        self.assertIn("cmd: Can't find service: media.codec", p0110_capability_evidence)
        self.assertIn("'cmd: Can't find service: media.codec' with exit code 20", p0110_capability_evidence)
        self.assertIn("c2.qti.av1.decoder", p0110_capability_evidence)
        self.assertIn("c2.android.av1-dav1d.decoder", p0110_capability_evidence)
        self.assertIn("does not prove Vibe Screen AV1 negotiation", normalized_p0110_capability_evidence)

    def test_public_av1_gate_materials_do_not_expose_sensitive_local_values(self) -> None:
        public_paths = [
            README_PATH,
            AV1_GATE_PATH,
            AV1_BLOCKED_EVIDENCE_PATH,
            AV1_CURRENT_BASE_BLOCKED_EVIDENCE_PATH,
            AV1_P0110_CAPABILITY_EVIDENCE_PATH,
            Path(__file__),
        ]
        forbidden_values = [
            "EP" + "0110PZ0B9110300B",
            "/Users/" + "luwentao",
            "Application Support/" + "com.apple.TCC",
            "TCC" + ".db",
            "BEGIN " + "RSA PRIVATE KEY",
            "BEGIN " + "OPENSSH PRIVATE KEY",
            "BEGIN " + "EC PRIVATE KEY",
            "BEGIN " + "DSA PRIVATE KEY",
        ]

        for path in public_paths:
            content = path.read_text(encoding="utf-8")
            for forbidden in forbidden_values:
                self.assertNotIn(forbidden, content, str(path))



if __name__ == "__main__":
    unittest.main()
