package dev.telemachus.display.protocol

import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.ColorDescription
import dev.vibescreen.protocol.v1.ColorPrimaries
import dev.vibescreen.protocol.v1.MatrixCoefficients
import dev.vibescreen.protocol.v1.TransferFunction
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VideoColorNegotiationTest {
    @Test
    fun sdrCapabilitiesAdvertiseOnlyBt709EightBitProfiles() {
        val capabilities = VideoColorNegotiation.sdrDecodeCapabilities(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264))

        assertEquals(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264), capabilities.map { it.codec })
        assertTrue(capabilities.all { capability ->
            capability.bitDepthsList == listOf(8) &&
                capability.transferFunctionsList ==
                listOf(TransferFunction.TRANSFER_FUNCTION_BT709, TransferFunction.TRANSFER_FUNCTION_SRGB)
        })
    }

    @Test
    fun hdrRequestWithoutNegotiatedHdrReturnsSdrFallback() {
        val decision =
            VideoColorNegotiation.evaluate(
                requestedColor = hdrColor(),
                negotiatedHdr = false,
                decodeCapabilities = VideoColorNegotiation.sdrDecodeCapabilities(listOf(Codec.CODEC_HEVC)),
                codec = Codec.CODEC_HEVC,
                width = 1920,
                height = 1080,
                framesPerSecond = 60,
            )

        assertTrue(decision is VideoColorDecision.Fallback)
        val fallback = decision as VideoColorDecision.Fallback
        assertEquals(VideoColorNegotiation.UNSUPPORTED_COLOR_OR_DECODE_PROFILE, fallback.reason)
        assertEquals(VideoColorNegotiation.legacySdrColor, fallback.selectedColor)
    }

    private fun hdrColor(): ColorDescription =
        ColorDescription
            .newBuilder()
            .setPrimaries(ColorPrimaries.COLOR_PRIMARIES_BT2020)
            .setTransferFunction(TransferFunction.TRANSFER_FUNCTION_PQ)
            .setMatrixCoefficients(MatrixCoefficients.MATRIX_COEFFICIENTS_BT2020_NON_CONSTANT)
            .setBitDepth(10)
            .build()
}
