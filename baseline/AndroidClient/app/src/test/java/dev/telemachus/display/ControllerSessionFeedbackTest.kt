package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerSessionFeedbackTest {
    @Test
    fun connectionTrackerIsIdempotentAndRejectsConflictingMappings() {
        val tracker = ControllerConnectionAckTracker()

        assertTrue(tracker.recordConnected(7, "c1", 1, nowMillis = 100))
        assertTrue(tracker.recordConnected(7, "c1", 1, nowMillis = 100))
        assertFalse(tracker.recordConnected(7, "c2", 1, nowMillis = 100))
        assertFalse(tracker.recordConnected(8, "c1", 1, nowMillis = 100))
        assertEquals(1, tracker.pendingCount())
        assertTrue(tracker.isPending("c1", 1))
        assertFalse(tracker.isPending("c2", 1))

        assertEquals(ControllerConnection("c1", 1), tracker.acknowledge(7)?.connection)
        assertFalse(tracker.isPending("c1", 1))
        assertNull(tracker.acknowledge(7))
        assertEquals(0, tracker.pendingCount())
    }

    @Test
    fun deferredDisconnectIsReportedOnlyWhenPendingConnectionIsAcknowledged() {
        val tracker = ControllerConnectionAckTracker()

        assertTrue(tracker.recordConnected(7, "c1", 1, nowMillis = 100))
        assertTrue(tracker.deferDisconnected("c1", 1))
        assertFalse(tracker.deferDisconnected("c1", 1))
        assertTrue(tracker.hasDeferredDisconnectBefore("c1", 2))

        val acknowledged = tracker.acknowledge(7)

        assertEquals(ControllerConnection("c1", 1), acknowledged?.connection)
        assertEquals(true, acknowledged?.hasDeferredDisconnect)
        tracker.markDisconnectReady(requireNotNull(acknowledged).connection)
        assertTrue(tracker.hasDeferredDisconnectBefore("c1", 2))
        assertEquals(DeferredControllerDisconnect(ControllerConnection("c1", 1)), tracker.nextReadyDisconnect())
        tracker.recordDisconnected("c1", 1)
        assertNull(tracker.nextReadyDisconnect())
        assertFalse(tracker.hasDeferredDisconnectBefore("c1", 2))
        assertNull(tracker.acknowledge(7))
    }

    @Test
    fun disconnectAndResetRemovePendingConnections() {
        val tracker = ControllerConnectionAckTracker()
        tracker.recordConnected(7, "c1", 1, nowMillis = 100)
        tracker.recordConnected(8, "c2", 1, nowMillis = 100)

        tracker.deferDisconnected("c1", 1)
        tracker.recordDisconnected("c1", 1)
        assertFalse(tracker.isPending("c1", 1))
        assertFalse(tracker.hasDeferredDisconnectBefore("c1", 2))
        assertNull(tracker.nextReadyDisconnect())
        assertTrue(tracker.isPending("c2", 1))
        assertNull(tracker.acknowledge(7))
        assertEquals(1, tracker.pendingCount())

        val acknowledged = requireNotNull(tracker.acknowledge(8))
        tracker.markDisconnectReady(acknowledged.connection)

        tracker.reset()
        assertFalse(tracker.hasDeferredDisconnectBefore("c2", 2))
        assertNull(tracker.nextReadyDisconnect())
        assertEquals(0, tracker.pendingCount())
    }

    @Test
    fun pendingConnectionTimeoutUsesConnectedTimeBoundaryAndIgnoresClockRollback() {
        val tracker = ControllerConnectionAckTracker()
        assertTrue(tracker.recordConnected(7, "c1", 1, nowMillis = 100))
        assertTrue(tracker.recordConnected(8, "c2", 1, nowMillis = 200))

        assertTrue(tracker.expirePendingConnections(nowMillis = 99).isEmpty())
        assertTrue(tracker.expirePendingConnections(nowMillis = 2_099).isEmpty())
        assertEquals(listOf(ControllerConnection("c1", 1)), tracker.expirePendingConnections(nowMillis = 2_100))

        assertNull(tracker.acknowledge(7))
        assertTrue(tracker.isPending("c2", 1))
        assertEquals(listOf(ControllerConnection("c2", 1)), tracker.expirePendingConnections(nowMillis = 2_200))
        assertEquals(0, tracker.pendingCount())
    }

    @Test
    fun rejectionPolicyAcceptsOnlyExactMaximumControllerReason() {
        assertNull(
            ControllerInputAckPolicy.rejectedConnection(
                controllerId = "c1",
                controllerEpoch = 0,
                accepted = false,
            ),
        )
        assertNull(
            ControllerInputAckPolicy.rejectedConnection(
                controllerId = "  ",
                controllerEpoch = 3,
                accepted = false,
            ),
        )
        assertNull(
            ControllerInputAckPolicy.rejectedConnection(
                controllerId = "c1",
                controllerEpoch = 3,
                accepted = true,
            ),
        )
        assertEquals(
            RejectedControllerConnection("c1", 3),
            ControllerInputAckPolicy.rejectedConnection(
                controllerId = "c1",
                controllerEpoch = 3,
                accepted = false,
            ),
        )
        assertNull(
            ControllerInputAckPolicy.rejectedConnection(
                controllerId = null,
                controllerEpoch = null,
                accepted = false,
            ),
        )
        assertTrue(
            ControllerInputAckPolicy.isMaximumActiveControllersRejection(
                MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON,
            ),
        )
        assertFalse(
            ControllerInputAckPolicy.isMaximumActiveControllersRejection(
                "controller_temporarily_unavailable",
            ),
        )
    }

    @Test
    fun rejectedConnectionRequiresAValidLifecycleIdentity() {
        listOf(
            { RejectedControllerConnection("", 1) },
            { RejectedControllerConnection("c1", 0) },
        ).forEach { invalidConnection ->
            assertThrows(IllegalArgumentException::class.java) {
                invalidConnection()
            }
        }
    }

    @Test
    fun unsupportedNoticeWaitsForAConnectedNegotiatedSession() {
        assertFalse(
            ControllerNoticePolicy.shouldShowUnsupported(
                isConnected = false,
                hasNegotiatedControllerCapability = false,
            ),
        )
        assertFalse(
            ControllerNoticePolicy.shouldShowUnsupported(
                isConnected = true,
                hasNegotiatedControllerCapability = true,
            ),
        )
        assertTrue(
            ControllerNoticePolicy.shouldShowUnsupported(
                isConnected = true,
                hasNegotiatedControllerCapability = false,
            ),
        )
    }

    @Test
    fun controllerInputIsConsumedOnlyByAConnectedSessionAndNeverForSystemKeys() {
        assertFalse(
            ControllerInputConsumptionPolicy.shouldConsume(
                isConnected = false,
                isSystemKey = false,
            ),
        )
        assertFalse(
            ControllerInputConsumptionPolicy.shouldConsume(
                isConnected = true,
                isSystemKey = true,
            ),
        )
        assertTrue(
            ControllerInputConsumptionPolicy.shouldConsume(
                isConnected = true,
                isSystemKey = false,
            ),
        )
    }

    @Test
    fun noticesAreShownOnceUntilTheirDocumentedResetBoundary() {
        val notices = ControllerNoticeState()

        assertTrue(notices.shouldShowUnsupported())
        assertFalse(notices.shouldShowUnsupported())
        assertTrue(notices.shouldShowLimit())
        assertFalse(notices.shouldShowLimit())
        assertTrue(notices.shouldShowRejected())
        assertFalse(notices.shouldShowRejected())

        notices.resetLimit()
        assertTrue(notices.shouldShowLimit())
        assertFalse(notices.shouldShowUnsupported())
        assertFalse(notices.shouldShowRejected())

        notices.resetForNewSession()
        assertTrue(notices.shouldShowUnsupported())
        assertTrue(notices.shouldShowLimit())
        assertTrue(notices.shouldShowRejected())
    }
}
