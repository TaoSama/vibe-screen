package dev.telemachus.display

import android.content.pm.ActivityInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClientExperienceTest {
    @Test
    fun `client rotation composes with normalized host rotation`() {
        val rotations = listOf(0, 90, 180, 270)
        val clientRotations = ClientRotation.entries

        rotations.forEach { hostRotation ->
            clientRotations.forEach { clientRotation ->
                assertEquals(
                    "host=$hostRotation client=$clientRotation",
                    (hostRotation + clientRotation.degrees) % 360,
                    ViewportPolicy.effectiveRotation(hostRotation, clientRotation),
                )
            }
        }

        assertEquals(0, ViewportPolicy.effectiveRotation(450, ClientRotation.COUNTER_CLOCKWISE_90))
    }

    @Test
    fun `normalizes arbitrary rotation to the nearest display quadrant`() {
        assertEquals(0, ViewportPolicy.normalizeRotation(0))
        assertEquals(90, ViewportPolicy.normalizeRotation(90))
        assertEquals(180, ViewportPolicy.normalizeRotation(180))
        assertEquals(270, ViewportPolicy.normalizeRotation(270))
        assertEquals(0, ViewportPolicy.normalizeRotation(360))
        assertEquals(180, ViewportPolicy.normalizeRotation(-180))
        assertEquals(270, ViewportPolicy.normalizeRotation(-90))
        assertEquals(0, ViewportPolicy.normalizeRotation(45))
        assertEquals(0, ViewportPolicy.normalizeRotation(315))
    }

    @Test
    fun `effective host rotation maps only to Android screen orientation`() {
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE, ViewportPolicy.screenOrientationFor(0))
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT, ViewportPolicy.screenOrientationFor(90))
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE, ViewportPolicy.screenOrientationFor(180))
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT, ViewportPolicy.screenOrientationFor(270))
        assertEquals(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT, ViewportPolicy.screenOrientationFor(450))
    }

    @Test
    fun `surface transform stays client local when host rotation changes`() {
        ClientRotation.entries.forEach { clientRotation ->
            assertEquals(clientRotation.degrees, ViewportPolicy.surfaceTransformRotation(clientRotation))
        }
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
        val lan =
            ConnectionSecurityPresentationPolicy.presentation(
                ConnectionMode.WIRELESS,
                LanRecordProtectionState.ENCRYPTED,
            )
        val internet = ConnectionSecurityPresentationPolicy.presentation(ConnectionMode.INTERNET)

        assertEquals(R.string.stream_status_usb_label, usb.labelResource)
        assertFalse(usb.warning)
        assertEquals(R.string.stream_status_lan_label, lan.labelResource)
        assertEquals(R.string.stream_status_lan_encrypted_detail, lan.detailResource)
        assertFalse(lan.warning)
        assertEquals(R.string.stream_status_internet_label, internet.labelResource)
        assertEquals(R.string.stream_status_internet_detail, internet.detailResource)
        assertFalse(internet.warning)
    }

    @Test
    fun `lan streaming status does not report legacy or unknown protection as encrypted`() {
        val legacy =
            ConnectionSecurityPresentationPolicy.presentation(
                ConnectionMode.WIRELESS,
                LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK,
            )
        val unknown =
            ConnectionSecurityPresentationPolicy.presentation(
                ConnectionMode.WIRELESS,
                LanRecordProtectionState.NOT_APPLICABLE,
            )

        assertEquals(R.string.stream_status_lan_legacy_plaintext_detail, legacy.detailResource)
        assertTrue(legacy.warning)
        assertEquals(R.string.stream_status_lan_unknown_detail, unknown.detailResource)
        assertTrue(unknown.warning)
    }

    @Test
    fun `lan clipboard confirmation mirrors negotiated protection state`() {
        assertEquals(
            R.string.clipboard_lan_confirm_message,
            LanClipboardProtectionMessagePolicy.sendMessage(LanRecordProtectionState.ENCRYPTED),
        )
        assertEquals(
            R.string.clipboard_lan_legacy_confirm_message,
            LanClipboardProtectionMessagePolicy.sendMessage(LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK),
        )
        assertEquals(
            R.string.clipboard_lan_unknown_confirm_message,
            LanClipboardProtectionMessagePolicy.sendMessage(LanRecordProtectionState.NOT_APPLICABLE),
        )
        assertEquals(
            R.string.clipboard_lan_legacy_receive_confirm_message,
            LanClipboardProtectionMessagePolicy.receiveMessage(LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK),
        )
        assertEquals(
            R.string.clipboard_lan_unknown_direct_receive_confirm_message,
            LanClipboardProtectionMessagePolicy.directReceiveMessage(LanRecordProtectionState.NEGOTIATING),
        )
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
