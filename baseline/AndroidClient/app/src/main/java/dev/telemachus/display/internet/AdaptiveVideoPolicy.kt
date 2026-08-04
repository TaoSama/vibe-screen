package dev.telemachus.display.internet

/** Hysteretic adaptation policy: react quickly to congestion and recover conservatively. */
class AdaptiveVideoPolicy(
    private val profiles: List<VideoProfile> = DEFAULT_PROFILES,
    private val poorSamplesToDowngrade: Int = 2,
    private val goodSamplesToUpgrade: Int = 5,
) {
    init {
        require(profiles.isNotEmpty()) { "At least one video profile is required" }
        require(poorSamplesToDowngrade > 0 && goodSamplesToUpgrade > 0)
    }

    private var profileIndex = 0
    private var consecutivePoorSamples = 0
    private var consecutiveGoodSamples = 0

    val currentProfile: VideoProfile
        get() = profiles[profileIndex]

    /** Returns a new profile only when encoder settings should change. */
    fun update(stats: WebRtcStats): VideoProfile? {
        val isPoor =
            stats.packetLossPercent >= POOR_LOSS_PERCENT ||
                stats.roundTripTimeMs >= POOR_RTT_MS ||
                stats.availableBitrateKbps < (currentProfile.bitrateKbps * BITRATE_HEADROOM)
        val isGood =
            stats.packetLossPercent <= GOOD_LOSS_PERCENT &&
                stats.roundTripTimeMs <= GOOD_RTT_MS &&
                stats.jitterMs <= GOOD_JITTER_MS &&
                profileIndex > 0 &&
                stats.availableBitrateKbps >= (profiles[profileIndex - 1].bitrateKbps * BITRATE_HEADROOM)

        when {
            isPoor -> {
                consecutivePoorSamples++
                consecutiveGoodSamples = 0
            }
            isGood -> {
                consecutiveGoodSamples++
                consecutivePoorSamples = 0
            }
            else -> {
                consecutivePoorSamples = 0
                consecutiveGoodSamples = 0
            }
        }

        val nextIndex =
            when {
                consecutivePoorSamples >= poorSamplesToDowngrade && profileIndex < profiles.lastIndex -> profileIndex + 1
                consecutiveGoodSamples >= goodSamplesToUpgrade && profileIndex > 0 -> profileIndex - 1
                else -> return null
            }
        profileIndex = nextIndex
        consecutivePoorSamples = 0
        consecutiveGoodSamples = 0
        return currentProfile
    }

    companion object {
        private const val POOR_LOSS_PERCENT = 5.0
        private const val GOOD_LOSS_PERCENT = 1.0
        private const val POOR_RTT_MS = 250
        private const val GOOD_RTT_MS = 120
        private const val GOOD_JITTER_MS = 30
        private const val BITRATE_HEADROOM = 1.2

        val DEFAULT_PROFILES =
            listOf(
                VideoProfile(width = 1920, height = 1080, framesPerSecond = 60, bitrateKbps = 12_000),
                VideoProfile(width = 1600, height = 900, framesPerSecond = 45, bitrateKbps = 7_000),
                VideoProfile(width = 1280, height = 720, framesPerSecond = 30, bitrateKbps = 4_000),
                VideoProfile(width = 960, height = 540, framesPerSecond = 24, bitrateKbps = 2_000),
            )
    }
}
