package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClientExperienceTest {
    @Test
    fun `client rotation composes with normalized host rotation`() {
        assertEquals(180, ViewportPolicy.effectiveRotation(90, ClientRotation.CLOCKWISE_90))
        assertEquals(0, ViewportPolicy.effectiveRotation(450, ClientRotation.COUNTER_CLOCKWISE_90))
        assertEquals(270, ViewportPolicy.normalizeRotation(-90))
    }

    @Test
    fun `legacy session exposes touch without claiming unnegotiated controls`() {
        val capabilities = ClientSessionCapabilities.LEGACY_TOUCH_ONLY

        assertTrue(capabilities.touch)
        assertFalse(ClientControlAvailability.isSupported(ClientControl.DISPLAY_SELECTION, capabilities))
        assertFalse(ClientControlAvailability.isSupported(ClientControl.KEYBOARD, capabilities))
        assertFalse(ClientControlAvailability.isSupported(ClientControl.NATIVE_POINTER, capabilities))
    }

    @Test
    fun `saved enum parsing falls back safely`() {
        assertEquals(VideoScaleMode.FIT, VideoScaleMode.fromName("unknown"))
        assertEquals(ClientRotation.FOLLOW_HOST, ClientRotation.fromName(null))
        assertEquals(VideoScaleMode.FILL, VideoScaleMode.fromName("FILL"))
    }

    @Test
    fun `fit surface preserves non-square video aspect while fill matches constraints`() {
        assertEquals(
            ViewportPolicy.Size(1920, 1080),
            ViewportPolicy.surfaceSize(2400, 1080, 1920, 1080, VideoScaleMode.FIT),
        )
        assertEquals(
            ViewportPolicy.Size(0, 0),
            ViewportPolicy.surfaceSize(2400, 1080, 1920, 1080, VideoScaleMode.FILL),
        )
    }
}
