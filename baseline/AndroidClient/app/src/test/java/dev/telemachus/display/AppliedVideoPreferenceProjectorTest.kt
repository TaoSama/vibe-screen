package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppliedVideoPreferenceProjectorTest {
    @Test
    fun `only client requested newer configurations may overwrite saved preferences`() {
        assertFalse(AppliedVideoPreferenceProjector.shouldPersist(false, 1, 0))
        assertFalse(AppliedVideoPreferenceProjector.shouldPersist(true, 4, 4))
        assertFalse(AppliedVideoPreferenceProjector.shouldPersist(true, 3, 4))
        assertTrue(AppliedVideoPreferenceProjector.shouldPersist(true, 5, 4))
    }

    @Test
    fun `projects authoritative whole-megabit config`() {
        assertEquals(
            AppliedVideoPreferenceProjection(bitrateMbps = 35, framesPerSecond = 60),
            AppliedVideoPreferenceProjector.project(
                bitrateKbps = 35_000,
                framesPerSecond = 60,
            ),
        )
    }

    @Test
    fun `rounds and clamps bitrate to the settings control range`() {
        assertEquals(
            ClientVideoBounds.MIN_BITRATE_MBPS,
            AppliedVideoPreferenceProjector.project(1, 60).bitrateMbps,
        )
        assertEquals(
            ClientVideoBounds.MAX_BITRATE_MBPS,
            AppliedVideoPreferenceProjector.project(250_000, 60).bitrateMbps,
        )
        assertEquals(36, AppliedVideoPreferenceProjector.project(35_500, 60).bitrateMbps)
    }

    @Test
    fun `unknown values do not overwrite saved controls`() {
        val projection = AppliedVideoPreferenceProjector.project(0, 45)

        assertNull(projection.bitrateMbps)
        assertNull(projection.framesPerSecond)
    }
}
