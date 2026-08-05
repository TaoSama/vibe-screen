package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionAutomaticRetryCleanupAdapterTest {
    @Test
    fun `terminal failure disables USB and clears both pending retry paths exactly once`() {
        val usb = FakeUsbAutomaticRetry(enabled = true, hasPendingRunnable = true)
        val wireless = FakeWirelessAutomaticRetry(hasPendingRunnable = true)
        val adapter = adapter(isCurrentGeneration = { true }, usb = usb, wireless = wireless)
        val coordinator = coordinator(adapter)

        coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onSessionEnded(SessionFailure.serverShutdown())

        assertFalse(usb.enabled)
        assertFalse(usb.hasPendingRunnable)
        assertFalse(wireless.hasPendingRunnable)
        assertEquals(1, usb.disableCount)
        assertEquals(1, usb.removeRunnableCount)
        assertEquals(1, wireless.cancelCount)
    }

    @Test
    fun `stale generation leaves USB and wireless retry state untouched`() {
        val usb = FakeUsbAutomaticRetry(enabled = true, hasPendingRunnable = true)
        val wireless = FakeWirelessAutomaticRetry(hasPendingRunnable = true)
        val adapter = adapter(isCurrentGeneration = { false }, usb = usb, wireless = wireless)

        coordinator(adapter).onSessionEnded(SessionFailure.serverShutdown())

        assertTrue(usb.enabled)
        assertTrue(usb.hasPendingRunnable)
        assertTrue(wireless.hasPendingRunnable)
        assertEquals(0, usb.disableCount)
        assertEquals(0, usb.removeRunnableCount)
        assertEquals(0, wireless.cancelCount)
    }

    private fun adapter(
        isCurrentGeneration: () -> Boolean,
        usb: FakeUsbAutomaticRetry,
        wireless: FakeWirelessAutomaticRetry,
    ) = SessionAutomaticRetryCleanupAdapter(
        isCurrentGeneration = isCurrentGeneration,
        disableAutomaticUsbConnect = usb::disable,
        cancelWirelessReconnect = wireless::cancel,
        removeAutomaticUsbRunnable = usb::removePendingRunnable,
    )

    private fun coordinator(adapter: SessionAutomaticRetryCleanupAdapter) =
        SessionAutomaticRetryCoordinator(
            postAutomaticRetry = {},
            cancelPendingAutomaticRetry = adapter::cleanup,
            handleServerShutdown = {},
        )

    private class FakeUsbAutomaticRetry(
        var enabled: Boolean,
        var hasPendingRunnable: Boolean,
    ) {
        var disableCount = 0
            private set
        var removeRunnableCount = 0
            private set

        fun disable() {
            disableCount++
            enabled = false
        }

        fun removePendingRunnable() {
            removeRunnableCount++
            hasPendingRunnable = false
        }
    }

    private class FakeWirelessAutomaticRetry(
        var hasPendingRunnable: Boolean,
    ) {
        var cancelCount = 0
            private set

        fun cancel() {
            cancelCount++
            hasPendingRunnable = false
        }
    }
}
