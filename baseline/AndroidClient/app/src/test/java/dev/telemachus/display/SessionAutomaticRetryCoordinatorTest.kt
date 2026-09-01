package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionAutomaticRetryCoordinatorTest {
    @Test
    fun `host shutdown callback before finally cancels and prevents USB post`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)

        val showGuidance = coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onServerShutdown()
        coordinator.onServerShutdown()
        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertFalse(showGuidance)
        assertEquals(0, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
        assertEquals(1, scheduler.shutdownCount)
        assertFalse(scheduler.hasPendingWork)
    }

    @Test
    fun `host shutdown callback before finally cancels and prevents wireless post`() {
        val scheduler = FakeWirelessScheduler()
        val coordinator = coordinator(scheduler)

        val showGuidance = coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onServerShutdown()
        coordinator.onServerShutdown()
        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertFalse(showGuidance)
        assertEquals(0, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
        assertEquals(1, scheduler.shutdownCount)
        assertFalse(scheduler.hasPendingWork)
    }

    @Test
    fun `host shutdown callback cancels USB work already posted by finally exactly once`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)

        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)
        assertTrue(scheduler.hasPendingWork)
        coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onSessionEnded(SessionFailure.serverShutdown())

        assertEquals(1, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
        assertFalse(scheduler.hasPendingWork)
    }

    @Test
    fun `host shutdown callback cancels wireless work already posted by finally exactly once`() {
        val scheduler = FakeWirelessScheduler()
        val coordinator = coordinator(scheduler)

        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)
        assertTrue(scheduler.hasPendingWork)
        coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onSessionEnded(SessionFailure.serverShutdown())

        assertEquals(1, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
        assertFalse(scheduler.hasPendingWork)
    }

    @Test
    fun `retryable failure posts without cancelling both schedulers`() {
        val usb = FakeUsbScheduler()
        val wireless = FakeWirelessScheduler()
        val usbCoordinator = coordinator(usb)
        val wirelessCoordinator = coordinator(wireless)

        assertFalse(usbCoordinator.onSessionEnded(SessionFailure.transport("usb eof")))
        assertFalse(wirelessCoordinator.onSessionEnded(SessionFailure.transport("wireless eof")))
        usbCoordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)
        wirelessCoordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertEquals(1, usb.postCount)
        assertEquals(0, usb.cancelCount)
        assertTrue(usb.hasPendingWork)
        assertEquals(1, wireless.postCount)
        assertEquals(0, wireless.cancelCount)
        assertTrue(wireless.hasPendingWork)
    }

    @Test
    fun `disabled retry and active sessions never post`() {
        val usb = FakeUsbScheduler()
        val wireless = FakeWirelessScheduler()

        coordinator(usb).onConnectionFinally(automaticRetryEnabled = false, disconnected = true)
        coordinator(wireless).onConnectionFinally(automaticRetryEnabled = true, disconnected = false)

        assertEquals(0, usb.postCount)
        assertEquals(0, wireless.postCount)
    }

    @Test
    fun `intentional only controls guidance while both terminal failures cancel`() {
        val intentionalScheduler = FakeUsbScheduler()
        val unintentionalScheduler = FakeWirelessScheduler()

        val intentional = coordinator(intentionalScheduler).onSessionEnded(SessionFailure.serverShutdown())
        val unintentional =
            coordinator(unintentionalScheduler).onSessionEnded(
                SessionFailure.protocol(SessionFailureKind.INVALID_DISPLAY, "bad rotation"),
            )

        assertFalse(intentional)
        assertTrue(unintentional)
        assertEquals(1, intentionalScheduler.cancelCount)
        assertEquals(1, unintentionalScheduler.cancelCount)
    }

    @Test
    fun `reconnect suggestion before finally schedules exactly once with the suggested delay`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)
        val suggestedDelay = 487L

        coordinator.onReconnectSuggested(suggestedDelay)
        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertEquals(1, scheduler.postCount)
        assertEquals(suggestedDelay, scheduler.lastPostedDelayMs)
        assertTrue(scheduler.hasPendingWork)
    }

    @Test
    fun `finally before reconnect suggestion replaces the active retry with the suggested delay`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)
        val suggestedDelay = 512L

        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)
        val defaultDelay = scheduler.lastPostedDelayMs
        coordinator.onReconnectSuggested(suggestedDelay)

        assertEquals(2, scheduler.postCount)
        assertEquals(suggestedDelay, scheduler.lastPostedDelayMs)
        assertTrue(defaultDelay in 1L..ReconnectBackoff.MAXIMUM_DELAY_MS)
        assertTrue(scheduler.hasPendingWork)
    }

    @Test
    fun `late reconnect suggestion does not schedule after finally found no retry work`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)
        val connectedScheduler = FakeUsbScheduler()
        val connectedCoordinator = coordinator(connectedScheduler)

        coordinator.onConnectionFinally(automaticRetryEnabled = false, disconnected = true)
        coordinator.onReconnectSuggested(512L)
        connectedCoordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = false)
        connectedCoordinator.onReconnectSuggested(512L)

        assertEquals(0, scheduler.postCount)
        assertFalse(scheduler.hasPendingWork)
        assertEquals(0, connectedScheduler.postCount)
        assertFalse(connectedScheduler.hasPendingWork)
    }

    @Test
    fun `non-retryable terminal failure prevents later reconnect suggestion from scheduling`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)

        coordinator.onSessionEnded(SessionFailure.protocol(SessionFailureKind.INVALID_DISPLAY, "bad"))
        coordinator.onReconnectSuggested(500L)
        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertEquals(0, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
        assertFalse(scheduler.hasPendingWork)
    }

    @Test
    fun `cancel pending retry clears scheduled work and prevents further posts`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)

        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)
        assertTrue(scheduler.hasPendingWork)
        coordinator.onSessionEnded(SessionFailure.serverShutdown())
        coordinator.onReconnectSuggested(500L)

        assertFalse(scheduler.hasPendingWork)
        assertEquals(1, scheduler.postCount)
        assertEquals(1, scheduler.cancelCount)
    }

    @Test
    fun `finally uses bounded default delay when no suggestion has arrived`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)

        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertEquals(1, scheduler.postCount)
        val delay = checkNotNull(scheduler.lastPostedDelayMs)
        assertTrue(
            "default delay $delay must be within [1, ${ReconnectBackoff.MAXIMUM_DELAY_MS}]",
            delay in 1L..ReconnectBackoff.MAXIMUM_DELAY_MS,
        )
    }

    @Test
    fun `reconnect suggestion delay is passed through unchanged`() {
        val scheduler = FakeUsbScheduler()
        val coordinator = coordinator(scheduler)
        val delay = 1_234L

        coordinator.onReconnectSuggested(delay)
        coordinator.onConnectionFinally(automaticRetryEnabled = true, disconnected = true)

        assertEquals(delay, scheduler.lastPostedDelayMs)
    }

    private fun coordinator(scheduler: FakeRetryScheduler) =
        SessionAutomaticRetryCoordinator(
            postAutomaticRetry = scheduler::post,
            cancelPendingAutomaticRetry = scheduler::cancel,
            handleServerShutdown = scheduler::shutdown,
        )

    private interface FakeRetryScheduler {
        val postCount: Int
        val cancelCount: Int
        val shutdownCount: Int
        val hasPendingWork: Boolean
        val lastPostedDelayMs: Long?

        fun post(delayMs: Long)

        fun cancel()

        fun shutdown()
    }

    private class FakeUsbScheduler : RecordingFakeScheduler()

    private class FakeWirelessScheduler : RecordingFakeScheduler()

    private open class RecordingFakeScheduler : FakeRetryScheduler {
        private var posts = 0
        private var cancels = 0
        private var shutdowns = 0
        private var pending = false
        private var lastDelay: Long? = null

        final override val postCount: Int
            get() = posts
        final override val cancelCount: Int
            get() = cancels
        final override val shutdownCount: Int
            get() = shutdowns
        final override val hasPendingWork: Boolean
            get() = pending
        final override val lastPostedDelayMs: Long?
            get() = lastDelay

        override fun post(delayMs: Long) {
            posts++
            pending = true
            lastDelay = delayMs
        }

        override fun cancel() {
            cancels++
            pending = false
        }

        override fun shutdown() {
            shutdowns++
        }
    }
}
