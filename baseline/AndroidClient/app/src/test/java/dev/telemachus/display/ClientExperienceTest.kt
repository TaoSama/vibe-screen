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
    fun `transfer readiness stays waiting before a compatible Mac session`() {
        val presentation =
            TransferReadinessPresentationPolicy.presentation(
                connected = false,
                clipboardReady = false,
                fileTransferReady = false,
            )

        assertEquals(R.string.transfer_readiness_waiting_status, presentation.statusResource)
        assertEquals(R.string.transfer_readiness_waiting_summary, presentation.summaryResource)
        assertEquals(R.color.on_surface_muted, presentation.statusColorResource)
    }

    @Test
    fun `transfer readiness reports unnegotiated controls without claiming support`() {
        val presentation =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = false,
            )

        assertEquals(R.string.transfer_readiness_unavailable_status, presentation.statusResource)
        assertEquals(R.string.transfer_readiness_unavailable_summary, presentation.summaryResource)
        assertEquals(R.color.warning, presentation.statusColorResource)
    }

    @Test
    fun `transfer readiness distinguishes partial and full negotiated controls`() {
        val clipboardOnly =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = true,
                fileTransferReady = false,
            )
        val filesOnly =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = true,
            )
        val ready =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = true,
                fileTransferReady = true,
            )

        assertEquals(R.string.transfer_readiness_clipboard_only_status, clipboardOnly.statusResource)
        assertEquals(R.color.warning, clipboardOnly.statusColorResource)
        assertEquals(R.string.transfer_readiness_files_only_status, filesOnly.statusResource)
        assertEquals(R.color.warning, filesOnly.statusColorResource)
        assertEquals(R.string.transfer_readiness_ready_status, ready.statusResource)
        assertEquals(R.string.transfer_readiness_ready_summary, ready.summaryResource)
        assertEquals(R.color.accent, ready.statusColorResource)
    }

    @Test
    fun `transfer readiness reports managed policy blocks before compatibility fallback`() {
        val bothBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = false,
                fileTransferPolicyAllowed = false,
            )
        val clipboardBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = true,
                clipboardPolicyAllowed = false,
                fileTransferPolicyAllowed = true,
            )
        val fileTransferBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = true,
                fileTransferReady = false,
                clipboardPolicyAllowed = true,
                fileTransferPolicyAllowed = false,
            )
        val clipboardBlockedBeforeFilesReady =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = false,
                fileTransferPolicyAllowed = true,
            )
        val filesBlockedBeforeClipboardReady =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = true,
                fileTransferPolicyAllowed = false,
            )

        assertEquals(R.string.transfer_readiness_policy_blocked_status, bothBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_policy_blocked_summary, bothBlocked.summaryResource)
        assertEquals(R.color.warning, bothBlocked.statusColorResource)
        assertEquals(R.string.transfer_readiness_files_only_status, clipboardBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_clipboard_policy_blocked_summary, clipboardBlocked.summaryResource)
        assertEquals(R.string.transfer_readiness_clipboard_only_status, fileTransferBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_file_policy_blocked_summary, fileTransferBlocked.summaryResource)
        assertEquals(R.string.transfer_readiness_policy_blocked_status, clipboardBlockedBeforeFilesReady.statusResource)
        assertEquals(R.string.transfer_readiness_clipboard_policy_waiting_summary, clipboardBlockedBeforeFilesReady.summaryResource)
        assertEquals(R.string.transfer_readiness_policy_blocked_status, filesBlockedBeforeClipboardReady.statusResource)
        assertEquals(R.string.transfer_readiness_file_policy_waiting_summary, filesBlockedBeforeClipboardReady.summaryResource)
    }

    @Test
    fun `transfer readiness reports local managed policy blocks while disconnected`() {
        val clipboardBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = false,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = false,
                fileTransferPolicyAllowed = true,
            )
        val fileTransferBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = false,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = true,
                fileTransferPolicyAllowed = false,
            )

        assertEquals(R.string.transfer_readiness_policy_blocked_status, clipboardBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_clipboard_policy_waiting_summary, clipboardBlocked.summaryResource)
        assertEquals(R.color.warning, clipboardBlocked.statusColorResource)
        assertEquals(R.string.transfer_readiness_policy_blocked_status, fileTransferBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_file_policy_waiting_summary, fileTransferBlocked.summaryResource)
        assertEquals(R.color.warning, fileTransferBlocked.statusColorResource)
    }

    @Test
    fun `transfer readiness reports wake and fixed host policy blocks while disconnected`() {
        val fixedHostBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = false,
                clipboardReady = false,
                fileTransferReady = false,
                clipboardPolicyAllowed = false,
                fileTransferPolicyAllowed = false,
                wakeHostPolicyAllowed = false,
                fixedHostPolicyAllowed = false,
            )
        val wakeBlocked =
            TransferReadinessPresentationPolicy.presentation(
                connected = false,
                clipboardReady = false,
                fileTransferReady = false,
                wakeHostPolicyAllowed = false,
            )

        assertEquals(R.string.transfer_readiness_policy_blocked_status, fixedHostBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_fixed_host_policy_blocked_summary, fixedHostBlocked.summaryResource)
        assertEquals(R.color.warning, fixedHostBlocked.statusColorResource)
        assertEquals(R.string.transfer_readiness_policy_blocked_status, wakeBlocked.statusResource)
        assertEquals(R.string.transfer_readiness_wake_policy_blocked_summary, wakeBlocked.summaryResource)
        assertEquals(R.color.warning, wakeBlocked.statusColorResource)
    }

    @Test
    fun `transfer readiness keeps negotiated transfer state ahead of wake and fixed host policy hints`() {
        val ready =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = true,
                fileTransferReady = true,
                wakeHostPolicyAllowed = false,
                fixedHostPolicyAllowed = false,
            )
        val clipboardOnly =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = true,
                fileTransferReady = false,
                wakeHostPolicyAllowed = false,
                fixedHostPolicyAllowed = false,
            )
        val filesOnly =
            TransferReadinessPresentationPolicy.presentation(
                connected = true,
                clipboardReady = false,
                fileTransferReady = true,
                wakeHostPolicyAllowed = false,
                fixedHostPolicyAllowed = false,
            )

        assertEquals(R.string.transfer_readiness_ready_status, ready.statusResource)
        assertEquals(R.string.transfer_readiness_ready_summary, ready.summaryResource)
        assertEquals(R.color.accent, ready.statusColorResource)
        assertEquals(R.string.transfer_readiness_clipboard_only_status, clipboardOnly.statusResource)
        assertEquals(R.string.transfer_readiness_clipboard_only_summary, clipboardOnly.summaryResource)
        assertEquals(R.string.transfer_readiness_files_only_status, filesOnly.statusResource)
        assertEquals(R.string.transfer_readiness_files_only_summary, filesOnly.summaryResource)
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
