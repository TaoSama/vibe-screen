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
    fun `streaming status distinguishes transport security`() {
        val usb = ConnectionSecurityPresentationPolicy.presentation(ConnectionMode.USB)
        val lan = ConnectionSecurityPresentationPolicy.presentation(ConnectionMode.WIRELESS)
        val internet = ConnectionSecurityPresentationPolicy.presentation(ConnectionMode.INTERNET)

        assertEquals(R.string.stream_status_usb_label, usb.labelResource)
        assertFalse(usb.warning)
        assertEquals(R.string.stream_status_lan_label, lan.labelResource)
        assertEquals(R.string.stream_status_lan_detail, lan.detailResource)
        assertTrue(lan.warning)
        assertEquals(R.string.stream_status_internet_label, internet.labelResource)
        assertEquals(R.string.stream_status_internet_detail, internet.detailResource)
        assertFalse(internet.warning)
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

    @Test
    fun `quarter turns swap viewport aspect and preserve decoder surface orientation`() {
        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(600, 1200),
                surface = ViewportPolicy.Size(1200, 600),
            ),
            ViewportPolicy.layout(1200, 1200, 2000, 1000, VideoScaleMode.FIT, 90),
        )
        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(600, 1200),
                surface = ViewportPolicy.Size(1200, 600),
            ),
            ViewportPolicy.layout(1200, 1200, 2000, 1000, VideoScaleMode.FIT, 270),
        )
    }

    @Test
    fun `fill viewport covers parent while quarter turn swaps surface dimensions`() {
        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(1200, 800),
                surface = ViewportPolicy.Size(800, 1200),
            ),
            ViewportPolicy.layout(1200, 800, 2000, 1000, VideoScaleMode.FILL, 90),
        )
        assertEquals(
            ViewportPolicy.Layout(
                viewport = ViewportPolicy.Size(1200, 800),
                surface = ViewportPolicy.Size(1200, 800),
            ),
            ViewportPolicy.layout(1200, 800, 2000, 1000, VideoScaleMode.FILL, 180),
        )
    }
}
