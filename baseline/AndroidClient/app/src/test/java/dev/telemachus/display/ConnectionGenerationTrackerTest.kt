package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionGenerationTrackerTest {
    @Test
    fun preAcceptFailureFinishesAttemptAndAllowsReconnect() {
        val tracker = ConnectionGenerationTracker()
        val failedAttempt = tracker.beginAttempt()

        assertTrue(tracker.finishCurrent(failedAttempt))
        assertFalse(tracker.isCurrent(failedAttempt))
        assertFalse(tracker.finishCurrent(failedAttempt))

        val reconnectAttempt = tracker.beginAttempt()
        assertTrue(reconnectAttempt > failedAttempt)
        assertTrue(tracker.isCurrent(reconnectAttempt))
    }

    @Test
    fun staleTeardownCannotFinishNewAttempt() {
        val tracker = ConnectionGenerationTracker()
        val firstAttempt = tracker.beginAttempt()
        val replacementAttempt = tracker.beginAttempt()

        assertFalse(tracker.finishCurrent(firstAttempt))
        assertTrue(tracker.isCurrent(replacementAttempt))
        assertTrue(tracker.finishCurrent(replacementAttempt))
    }

    @Test
    fun hostWireEpochRestartDoesNotResetLocalGeneration() {
        val tracker = ConnectionGenerationTracker()
        val firstWireEpoch = 9L
        val firstGeneration = tracker.beginAttempt()
        assertTrue(tracker.finishCurrent(firstGeneration))

        val restartedHostWireEpoch = 1L
        val secondGeneration = tracker.beginAttempt()

        assertTrue(restartedHostWireEpoch < firstWireEpoch)
        assertTrue(secondGeneration > firstGeneration)
        assertTrue(tracker.isCurrent(secondGeneration))
    }
}
