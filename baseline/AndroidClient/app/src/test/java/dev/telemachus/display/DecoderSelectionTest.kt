package dev.telemachus.display

import android.media.MediaFormat
import dev.telemachus.display.internet.ProductVideoCodec
import dev.vibescreen.protocol.v1.Codec
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderSelectionTest {
    @After
    fun resetFallbackPolicy() {
        CodecFallbackPolicy.resetForTest()
    }

    @Test
    fun hevcSelectsHardwareForSupportedSizeEvenWhenTargetRateIsUnsupported() {
        val result =
            DecoderSelector.select(
                MediaFormat.MIMETYPE_VIDEO_HEVC,
                DecoderCatalogSnapshot(
                    probes =
                        listOf(
                            DecoderProbe("c2.android.hevc.decoder", true, true),
                            DecoderProbe("c2.vendor.hevc.decoder", true, false),
                        ),
                ),
            )

        assertEquals(
            DecoderSelectionResult.Selected("c2.vendor.hevc.decoder", supportsTargetRate = false),
            result,
        )
    }

    @Test
    fun softwareOnlyAndBlacklistedHevcAreStructurallyUnsupported() {
        listOf("c2.android.hevc.decoder", "OMX.google.hevc.decoder", "C2.SPRD.HEVC.decoder").forEach { name ->
            val result =
                DecoderSelector.select(
                    MediaFormat.MIMETYPE_VIDEO_HEVC,
                    DecoderCatalogSnapshot(listOf(DecoderProbe(name, true, true))),
                )

            assertEquals(name, DecoderSelectionResult.UnsupportedTarget, result)
        }
    }

    @Test
    fun incompleteCapabilityProbeDoesNotClaimStructuralUnsupported() {
        val result =
            DecoderSelector.select(
                MediaFormat.MIMETYPE_VIDEO_HEVC,
                DecoderCatalogSnapshot(
                    probes = listOf(DecoderProbe("c2.vendor.hevc.decoder", false, false)),
                    capabilityProbeFailures = 1,
                ),
            )

        assertEquals(DecoderSelectionResult.ProbeFailed, result)
    }

    @Test
    fun completeProbeWithNoSizeMatchIsStructurallyUnsupported() {
        val result =
            DecoderSelector.select(
                MediaFormat.MIMETYPE_VIDEO_HEVC,
                DecoderCatalogSnapshot(listOf(DecoderProbe("c2.vendor.hevc.decoder", false, false))),
            )

        assertEquals(DecoderSelectionResult.UnsupportedTarget, result)
    }

    @Test
    fun fallbackCommitRecordsBeforeConfigurationCompletionWithoutClosing() {
        val events = mutableListOf<String>()
        val recorded =
            CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                codec = StreamCodec.HEVC,
                failure = structuralFailure(),
                isCurrentConfiguration = { events += "current_gate"; true },
            )
        events += "configuration_completion"

        assertTrue(recorded)
        assertEquals(listOf("current_gate", "configuration_completion"), events)
        assertEquals(listOf(StreamCodec.H264), CodecFallbackPolicy.candidates(true))
    }

    @Test
    fun av1ProbeDoesNotEnterAdvertisedCandidatesBeforeAdmissionIsEnabled() {
        assertEquals(
            listOf(StreamCodec.HEVC, StreamCodec.H264),
            CodecFallbackPolicy.candidates(hasUsableHevcDecoder = true, hasUsableAv1Decoder = true),
        )
        assertEquals(StreamCodec.AV1, MediaFormat.MIMETYPE_VIDEO_AV1.toStreamCodec())
        assertEquals(Codec.CODEC_HEVC, StreamCodec.HEVC.toProtocolCodecOrNull())
        assertEquals(ProductVideoCodec.HEVC, StreamCodec.HEVC.toProductVideoCodecOrNull())
        assertEquals(null, StreamCodec.AV1.toProtocolCodecOrNull())
        assertEquals(null, StreamCodec.AV1.toProductVideoCodecOrNull())
    }

    @Test
    fun staleTransientAndH264FailuresNeverPoisonNextOffer() {
        val cases =
            listOf(
                Triple(StreamCodec.HEVC, structuralFailure(), false),
                Triple(StreamCodec.HEVC, runtimeFailure(), true),
                Triple(StreamCodec.H264, structuralFailure(), true),
            )

        cases.forEach { (codec, failure, current) ->
            CodecFallbackPolicy.resetForTest()
            val recorded =
                CodecFallbackCommitGate.recordCurrentStructuralHevcFailure(
                    codec = codec,
                    failure = failure,
                    isCurrentConfiguration = { current },
                )

            assertFalse(recorded)
            assertFalse(CodecFallbackPolicy.shouldUseH264(hasUsableHevcDecoder = true))
        }
    }

    private fun structuralFailure() =
        DecoderFailure(
            DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED,
            STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON,
        )

    private fun runtimeFailure() =
        DecoderFailure(
            DecoderFailureKind.SESSION_RUNTIME_FAILURE,
            "codec_runtime_failure",
        )
}
