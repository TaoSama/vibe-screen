package dev.telemachus.display

import android.media.MediaCodecList
import android.media.MediaFormat
import java.util.Locale

internal data class DecoderProbe(
    val name: String,
    val sizeSupported: Boolean,
    val targetRateSupported: Boolean,
)

internal data class DecoderCatalogSnapshot(
    val probes: List<DecoderProbe>,
    val capabilityProbeFailures: Int = 0,
)

internal sealed interface DecoderSelectionResult {
    data class Selected(
        val name: String,
        val supportsTargetRate: Boolean,
    ) : DecoderSelectionResult

    data object UnsupportedTarget : DecoderSelectionResult

    data object ProbeFailed : DecoderSelectionResult
}

internal object DecoderNameRules {
    private val BROKEN_HEVC_HARDWARE_PREFIXES = listOf("omx.sprd.", "c2.sprd.")

    fun isSoftware(name: String): Boolean {
        val normalized = name.lowercase(Locale.ROOT)
        return normalized.startsWith("c2.android.") || normalized.startsWith("omx.google.")
    }

    fun isUsableForMime(
        name: String,
        mime: String,
    ): Boolean {
        if (mime == MediaFormat.MIMETYPE_VIDEO_AV1) return !isSoftware(name)
        if (mime != MediaFormat.MIMETYPE_VIDEO_HEVC) return true
        val normalized = name.lowercase(Locale.ROOT)
        return !isSoftware(normalized) &&
            BROKEN_HEVC_HARDWARE_PREFIXES.none(normalized::startsWith)
    }
}

internal object DecoderSelector {
    fun select(
        mime: String,
        snapshot: DecoderCatalogSnapshot,
    ): DecoderSelectionResult {
        val supported =
            snapshot.probes.filter { probe ->
                probe.sizeSupported && DecoderNameRules.isUsableForMime(probe.name, mime)
            }
        if (supported.isEmpty()) {
            return if (snapshot.capabilityProbeFailures > 0) {
                DecoderSelectionResult.ProbeFailed
            } else {
                DecoderSelectionResult.UnsupportedTarget
            }
        }

        val chosen =
            supported.minWithOrNull(
                compareByDescending<DecoderProbe> { !DecoderNameRules.isSoftware(it.name) }
                    .thenByDescending { it.targetRateSupported },
            ) ?: error("supported decoder set unexpectedly empty")
        return DecoderSelectionResult.Selected(chosen.name, chosen.targetRateSupported)
    }
}

internal object AndroidDecoderCatalog {
    fun probe(
        mime: String,
        width: Int,
        height: Int,
        targetRate: Double,
    ): DecoderCatalogSnapshot? =
        try {
            val probes = mutableListOf<DecoderProbe>()
            var failures = 0
            MediaCodecList(MediaCodecList.ALL_CODECS).codecInfos.forEach { info ->
                if (info.isEncoder || info.supportedTypes.none { it.equals(mime, ignoreCase = true) }) {
                    return@forEach
                }
                val codecCapabilities =
                    try {
                        info.getCapabilitiesForType(mime)
                    } catch (_: Exception) {
                        failures++
                        null
                    } ?: return@forEach
                val videoCapabilities = codecCapabilities.videoCapabilities
                if (videoCapabilities == null) {
                    failures++
                    return@forEach
                }
                val sizeSupported =
                    try {
                        videoCapabilities.isSizeSupported(width, height)
                    } catch (_: Exception) {
                        failures++
                        false
                    }
                val rateSupported =
                    sizeSupported &&
                        try {
                            videoCapabilities.areSizeAndRateSupported(width, height, targetRate)
                        } catch (_: Exception) {
                            false
                        }
                probes += DecoderProbe(info.name, sizeSupported, rateSupported)
            }
            DecoderCatalogSnapshot(probes, failures)
        } catch (_: Exception) {
            null
        }
}
