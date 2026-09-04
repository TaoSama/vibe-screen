package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChecklistProbeResultPolicyTest {
    @Test
    fun appliesOnlyToTheStillVisibleIdleUsbChecklist() {
        assertTrue(shouldApply())
        assertFalse(shouldApply(connectionMode = ConnectionMode.WIRELESS))
        assertFalse(shouldApply(detailsVisible = false))
        assertFalse(shouldApply(connected = true))
        assertFalse(shouldApply(connectionAttemptInProgress = true))
        assertFalse(shouldApply(automaticUsbConnect = true))
    }

    @Test
    fun macServerChecklistStopsShowingCheckingAfterTerminalUsbFailure() {
        assertEquals(
            ChecklistStatus.NOT_READY,
            MacServerChecklistStatusPolicy.waitingStatus(
                connectionGuidanceVisible = true,
                connectionAttemptInProgress = false,
            ),
        )
    }

    @Test
    fun macServerChecklistKeepsCheckingDuringActiveUsbAttempts() {
        assertEquals(
            ChecklistStatus.CHECKING,
            MacServerChecklistStatusPolicy.waitingStatus(
                connectionGuidanceVisible = true,
                connectionAttemptInProgress = true,
            ),
        )
    }

    private fun shouldApply(
        connectionMode: ConnectionMode = ConnectionMode.USB,
        detailsVisible: Boolean = true,
        connected: Boolean = false,
        connectionAttemptInProgress: Boolean = false,
        automaticUsbConnect: Boolean = false,
    ): Boolean =
        ChecklistProbeResultPolicy.shouldApply(
            connectionMode = connectionMode,
            detailsVisible = detailsVisible,
            connected = connected,
            connectionAttemptInProgress = connectionAttemptInProgress,
            automaticUsbConnect = automaticUsbConnect,
        )
}
