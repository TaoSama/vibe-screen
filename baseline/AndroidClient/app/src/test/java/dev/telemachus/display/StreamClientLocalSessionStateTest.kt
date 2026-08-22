package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class StreamClientLocalSessionStateTest {
    @Test
    fun connectionStartClearsReadinessAndStopIntentWithoutChangingEpoch() {
        val state = StreamClientLocalSessionState()
        val epoch = state.beginSession()
        state.markReady()
        state.requestStop()

        state.prepareConnectionStart()

        assertEquals(epoch, state.connectionEpoch)
        assertFalse(state.isReady)
        assertFalse(state.stopRequested)
    }

    @Test
    fun beginSessionSupersedesStaleAttemptsThroughSharedEpochOwnership() {
        val state = StreamClientLocalSessionState()
        val staleEpoch = state.beginSession()
        val currentEpoch = state.beginSession()

        assertFalse(state.ownsAttempt(staleEpoch))
        assertFalse(state.acceptsEpoch(staleEpoch))
        assertTrue(state.ownsAttempt(currentEpoch))
        assertTrue(state.acceptsEpoch(currentEpoch))
        assertEquals(currentEpoch, state.currentEpoch())
    }

    @Test
    fun readyTransitionResetsReconnectBackoffOncePerDisplayConfiguration() {
        val reconnectBackoff = ReconnectBackoff(jitterRatio = 0.0)
        val state = StreamClientLocalSessionState(reconnectBackoff = reconnectBackoff)

        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS, reconnectBackoff.nextDelayMs(jitterUnit = 0.5))
        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS * 2, reconnectBackoff.nextDelayMs(jitterUnit = 0.5))

        assertTrue(state.markReady())
        assertFalse(state.markReady())
        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS, reconnectBackoff.nextDelayMs(jitterUnit = 0.5))
    }

    @Test
    fun readyTransitionIsClaimedByOnlyOneConcurrentCaller() {
        val state = StreamClientLocalSessionState()
        val start = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(16)

        try {
            val results = (0 until 64).map {
                executor.submit<Boolean> {
                    start.await()
                    state.markReady()
                }
            }

            start.countDown()

            val winners = results.count { it.get(5, TimeUnit.SECONDS) }
            assertEquals(1, winners)
            assertTrue(state.isReady)
        } finally {
            executor.shutdownNow()
        }
    }

    @Test
    fun terminationClaimRecordsFailureAndDropsActiveConnection() {
        val state = StreamClientLocalSessionState()
        val failure = SessionFailure.transport("socket closed")
        state.markConnected()

        state.markTerminationClaimed(failure)

        assertFalse(state.isConnected)
        assertEquals(failure, state.lastTerminationFailure)
    }

    @Test
    fun retryableReconnectDelayRemainsOwnedByLocalSessionState() {
        val state = StreamClientLocalSessionState(
            reconnectBackoff = ReconnectBackoff(jitterRatio = 0.0),
        )

        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS, state.nextReconnectDelayMs())
        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS * 2, state.nextReconnectDelayMs())
        state.markReady()
        assertEquals(ReconnectBackoff.INITIAL_DELAY_MS, state.nextReconnectDelayMs())
    }
}
