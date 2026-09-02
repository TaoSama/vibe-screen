package dev.telemachus.display

import android.media.MediaCodecList
import android.media.MediaFormat

/**
 * One-shot decoder capability probe. AVC-only devices drive the H.264
 * wire-protocol negotiation (the Mac encodes H.264 instead of HEVC).
 *
 * "Has HEVC" means the device has a *usable hardware* HEVC decoder — not merely
 * any decoder that advertises the type. Two classes of device are deliberately
 * routed to H.264 instead:
 *
 *  - **Software-only HEVC** (e.g. Onyx Boox Nova Air C, whose vendor
 *    media_codecs.xml disables HW HEVC): the Google software decoder
 *    (c2.android.hevc / OMX.google.hevc) is far too slow for real-time mirroring.
 *
 *  - **Broken vendor HW HEVC**: Spreadtrum/Unisoc (OMX.sprd.hevc, c2.sprd.*)
 *    advertise a HW HEVC decoder that configures and starts successfully but
 *    never renders decoded frames to the output Surface — the SurfaceView stays
 *    empty and the user sees a black screen (e.g. Yuho Tab 10, SC9863A + PowerVR).
 *
 * Both classes have a working hardware H.264 decoder, so H.264 is the reliable
 * path for them.
 */
object CodecCapabilities {
    private fun hasUsableDecoder(mime: String): Boolean =
        try {
            MediaCodecList(MediaCodecList.ALL_CODECS).codecInfos.any { info ->
                if (info.isEncoder) return@any false
                val handlesMime =
                    info.supportedTypes.any { it.equals(mime, ignoreCase = true) }
                if (!handlesMime) return@any false

                DecoderNameRules.isUsableForMime(info.name, mime)
            }
        } catch (_: Exception) {
            mime == MediaFormat.MIMETYPE_VIDEO_HEVC // preserve legacy HEVC fail-open behavior only
        }

    val hasHevcDecoder: Boolean by lazy {
        hasUsableDecoder(MediaFormat.MIMETYPE_VIDEO_HEVC)
    }

    /** Diagnostic-only until AV1 frame admission is explicitly enabled. */
    val hasAv1Decoder: Boolean by lazy {
        hasUsableDecoder(MediaFormat.MIMETYPE_VIDEO_AV1)
    }

    val runtimeAdmissionSnapshot: CodecRuntimeAdmissionSnapshot
        get() = CodecRuntimeAdmissionSnapshot(
            hasUsableHevcDecoder = hasHevcDecoder,
            hasUsableAv1Decoder = hasAv1Decoder,
            av1FrameAdmissionEnabled = false,
        )

    /** True when the next connection must explicitly negotiate H.264. */
    val shouldAdvertiseAvcOnly: Boolean
        get() = CodecFallbackPolicy.shouldUseH264(hasHevcDecoder)

    /** Snapshot used when constructing a new connection's wire offer. */
    val advertisedStreamCodecs: List<StreamCodec>
        get() = CodecFallbackPolicy.candidates(runtimeAdmissionSnapshot)
}

internal fun StreamCodec.toProtocolCodecOrNull(): dev.vibescreen.protocol.v1.Codec? =
    when (this) {
        StreamCodec.HEVC -> dev.vibescreen.protocol.v1.Codec.CODEC_HEVC
        StreamCodec.H264 -> dev.vibescreen.protocol.v1.Codec.CODEC_H264
        StreamCodec.AV1 -> null
    }

internal fun StreamCodec.toProductVideoCodecOrNull(): dev.telemachus.display.internet.ProductVideoCodec? =
    when (this) {
        StreamCodec.HEVC -> dev.telemachus.display.internet.ProductVideoCodec.HEVC
        StreamCodec.H264 -> dev.telemachus.display.internet.ProductVideoCodec.H264
        StreamCodec.AV1 -> null
    }

internal fun String.toStreamCodec(): StreamCodec =
    when (this) {
        MediaFormat.MIMETYPE_VIDEO_HEVC -> StreamCodec.HEVC
        MediaFormat.MIMETYPE_VIDEO_AV1 -> StreamCodec.AV1
        else -> StreamCodec.H264
    }
