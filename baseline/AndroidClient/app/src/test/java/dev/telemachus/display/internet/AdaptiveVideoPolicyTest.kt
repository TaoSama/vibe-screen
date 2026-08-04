package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AdaptiveVideoPolicyTest {
    @Test
    fun downgradesAfterTwoPoorSamples() {
        val policy = AdaptiveVideoPolicy()
        val poor = WebRtcStats(availableBitrateKbps = 3_000, packetLossPercent = 8.0, roundTripTimeMs = 300, jitterMs = 50)

        assertNull(policy.update(poor))
        assertEquals(VideoProfile(1600, 900, 45, 7_000), policy.update(poor))
    }

    @Test
    fun upgradesOnlyAfterFiveGoodSamples() {
        val policy = AdaptiveVideoPolicy(poorSamplesToDowngrade = 1, goodSamplesToUpgrade = 5)
        policy.update(WebRtcStats(1_000, 10.0, 400, 80))
        val good = WebRtcStats(availableBitrateKbps = 20_000, packetLossPercent = 0.0, roundTripTimeMs = 50, jitterMs = 5)

        repeat(4) { assertNull(policy.update(good)) }
        assertEquals(VideoProfile(1920, 1080, 60, 12_000), policy.update(good))
    }

    @Test
    fun neutralSampleResetsHysteresisCounters() {
        val policy = AdaptiveVideoPolicy()
        val poor = WebRtcStats(3_000, 8.0, 300, 50)
        val neutral = WebRtcStats(20_000, 2.0, 150, 20)

        assertNull(policy.update(poor))
        assertNull(policy.update(neutral))
        assertNull(policy.update(poor))
    }
}
