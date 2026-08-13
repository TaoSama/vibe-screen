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
    val hasHevcDecoder: Boolean by lazy {
        try {
            MediaCodecList(MediaCodecList.ALL_CODECS).codecInfos.any { info ->
                if (info.isEncoder) return@any false
                val handlesHevc =
                    info.supportedTypes.any { it.equals(MediaFormat.MIMETYPE_VIDEO_HEVC, ignoreCase = true) }
                if (!handlesHevc) return@any false

                DecoderNameRules.isUsableForMime(info.name, MediaFormat.MIMETYPE_VIDEO_HEVC)
            }
        } catch (_: Exception) {
            true // fail open: assume HEVC, preserving legacy behavior
        }
    }

    /** True when the next connection must explicitly negotiate H.264. */
    val shouldAdvertiseAvcOnly: Boolean
        get() = CodecFallbackPolicy.shouldUseH264(hasHevcDecoder)

    /** Snapshot used when constructing a new connection's wire offer. */
    val advertisedStreamCodecs: List<StreamCodec>
        get() = CodecFallbackPolicy.candidates(hasHevcDecoder)
}

internal fun String.toStreamCodec(): StreamCodec =
    if (this == MediaFormat.MIMETYPE_VIDEO_HEVC) StreamCodec.HEVC else StreamCodec.H264
