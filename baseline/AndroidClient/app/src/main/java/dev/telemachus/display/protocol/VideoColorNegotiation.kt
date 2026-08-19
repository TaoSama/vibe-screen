package dev.telemachus.display.protocol

import dev.vibescreen.protocol.v1.ColorDescription
import dev.vibescreen.protocol.v1.ColorPrimaries
import dev.vibescreen.protocol.v1.MatrixCoefficients
import dev.vibescreen.protocol.v1.TransferFunction
import dev.vibescreen.protocol.v1.VideoDecodeCapability

internal sealed class VideoColorDecision {
    object Accepted : VideoColorDecision()

    data class Fallback(
        val selectedColor: ColorDescription,
        val reason: String,
    ) : VideoColorDecision()

    data class Rejected(
        val reason: String,
    ) : VideoColorDecision()
}

internal object VideoColorNegotiation {
    const val UNSUPPORTED_COLOR_OR_DECODE_PROFILE = "unsupported_color_or_decode_profile"

    val legacySdrColor: ColorDescription =
        ColorDescription
            .newBuilder()
            .setPrimaries(ColorPrimaries.COLOR_PRIMARIES_BT709)
            .setTransferFunction(TransferFunction.TRANSFER_FUNCTION_BT709)
            .setMatrixCoefficients(MatrixCoefficients.MATRIX_COEFFICIENTS_BT709)
            .setFullRange(false)
            .setBitDepth(8)
            .build()

    fun sdrDecodeCapabilities(codecs: Iterable<dev.vibescreen.protocol.v1.Codec>): List<VideoDecodeCapability> =
        codecs.map { codec ->
            VideoDecodeCapability
                .newBuilder()
                .setCodec(codec)
                .setMaximumWidth(MAXIMUM_SDR_WIDTH)
                .setMaximumHeight(MAXIMUM_SDR_HEIGHT)
                .setMaximumFramesPerSecond(MAXIMUM_SDR_FRAMES_PER_SECOND)
                .addBitDepths(8)
                .addTransferFunctions(TransferFunction.TRANSFER_FUNCTION_BT709)
                .addTransferFunctions(TransferFunction.TRANSFER_FUNCTION_SRGB)
                .build()
        }

    fun evaluate(
        requestedColor: ColorDescription?,
        negotiatedHdr: Boolean,
        decodeCapabilities: Iterable<VideoDecodeCapability>,
        codec: dev.vibescreen.protocol.v1.Codec,
        width: Int,
        height: Int,
        framesPerSecond: Int,
    ): VideoColorDecision {
        val color = normalize(requestedColor ?: legacySdrColor)
        val supportsLegacySdr = supports(decodeCapabilities, legacySdrColor, codec, width, height, framesPerSecond)
        if (isHdr(color) && !negotiatedHdr) {
            return unsupportedDecision(supportsLegacySdr)
        }
        val supported = supports(decodeCapabilities, color, codec, width, height, framesPerSecond)
        return if (supported) {
            VideoColorDecision.Accepted
        } else {
            unsupportedDecision(supportsLegacySdr)
        }
    }

    fun normalize(color: ColorDescription): ColorDescription {
        val builder = color.toBuilder()
        if (builder.primaries == ColorPrimaries.COLOR_PRIMARIES_UNSPECIFIED) {
            builder.primaries = ColorPrimaries.COLOR_PRIMARIES_BT709
        }
        if (builder.transferFunction == TransferFunction.TRANSFER_FUNCTION_UNSPECIFIED) {
            builder.transferFunction = TransferFunction.TRANSFER_FUNCTION_BT709
        }
        if (builder.matrixCoefficients == MatrixCoefficients.MATRIX_COEFFICIENTS_UNSPECIFIED) {
            builder.matrixCoefficients = MatrixCoefficients.MATRIX_COEFFICIENTS_BT709
        }
        if (builder.bitDepth == 0) {
            builder.bitDepth = 8
        }
        return builder.build()
    }

    private fun isHdr(color: ColorDescription): Boolean =
        color.bitDepth > 8 ||
            color.transferFunction == TransferFunction.TRANSFER_FUNCTION_PQ ||
            color.transferFunction == TransferFunction.TRANSFER_FUNCTION_HLG ||
            color.primaries == ColorPrimaries.COLOR_PRIMARIES_BT2020 ||
            color.matrixCoefficients == MatrixCoefficients.MATRIX_COEFFICIENTS_BT2020_NON_CONSTANT

    private fun unsupportedDecision(supportsLegacySdr: Boolean): VideoColorDecision =
        if (supportsLegacySdr) {
            VideoColorDecision.Fallback(legacySdrColor, UNSUPPORTED_COLOR_OR_DECODE_PROFILE)
        } else {
            VideoColorDecision.Rejected(UNSUPPORTED_COLOR_OR_DECODE_PROFILE)
        }

    private fun supports(
        decodeCapabilities: Iterable<VideoDecodeCapability>,
        color: ColorDescription,
        codec: dev.vibescreen.protocol.v1.Codec,
        width: Int,
        height: Int,
        framesPerSecond: Int,
    ): Boolean =
        decodeCapabilities.any { capability ->
            capability.codec == codec &&
                width <= capability.maximumWidth &&
                height <= capability.maximumHeight &&
                framesPerSecond <= capability.maximumFramesPerSecond &&
                capability.bitDepthsList.contains(color.bitDepth) &&
                capability.transferFunctionsList.contains(color.transferFunction)
        }

    private const val MAXIMUM_SDR_WIDTH = 3840
    private const val MAXIMUM_SDR_HEIGHT = 2160
    private const val MAXIMUM_SDR_FRAMES_PER_SECOND = 120
}
