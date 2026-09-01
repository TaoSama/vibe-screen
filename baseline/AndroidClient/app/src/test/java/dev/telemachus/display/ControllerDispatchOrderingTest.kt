package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerDispatchOrderingTest {
    @Test
    fun movesLowerEpochDisconnectBeforeLaterEpochSamplesForSameController() {
        val connectNew = sample("c1", 2, ControllerEventKind.CONNECTED)
        val disconnectOld = sample("c1", 1, ControllerEventKind.DISCONNECTED)
        val otherController = sample("c2", 1, ControllerEventKind.CONNECTED)
        val dispatch = ControllerDispatch(listOf(connectNew, otherController, disconnectOld), ControllerDelivery.STRUCTURAL)

        val ordered = ControllerDispatchOrdering.disconnectsBeforeLaterEpochSamples(dispatch)

        assertEquals(ControllerDelivery.STRUCTURAL, ordered.delivery)
        assertEquals(listOf(otherController, disconnectOld, connectNew), ordered.samples)
        assertFalse(ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(ordered.samples))
    }

    @Test
    fun keepsAlreadyOrderedBatchesStable() {
        val disconnectOld = sample("c1", 1, ControllerEventKind.DISCONNECTED)
        val connectNew = sample("c1", 2, ControllerEventKind.CONNECTED)
        val otherController = sample("c2", 1, ControllerEventKind.CONNECTED)
        val dispatch = ControllerDispatch(listOf(disconnectOld, connectNew, otherController), ControllerDelivery.STRUCTURAL)

        val ordered = ControllerDispatchOrdering.disconnectsBeforeLaterEpochSamples(dispatch)

        assertTrue(dispatch === ordered)
        assertEquals(listOf(disconnectOld, connectNew, otherController), ordered.samples)
        assertFalse(ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(ordered.samples))
    }

    @Test
    fun ordersMultipleLaterEpochSamplesWithoutMovingUnrelatedControllerDisconnectsAhead() {
        val c1Epoch2 = sample("c1", 2, ControllerEventKind.CONNECTED)
        val c2Disconnect = sample("c2", 1, ControllerEventKind.DISCONNECTED)
        val c1Epoch3 = sample("c1", 3, ControllerEventKind.STATE, buttonMask = 1)
        val c1Disconnect = sample("c1", 1, ControllerEventKind.DISCONNECTED)
        val dispatch =
            ControllerDispatch(
                listOf(c1Epoch2, c2Disconnect, c1Epoch3, c1Disconnect),
                ControllerDelivery.STRUCTURAL,
            )

        val ordered = ControllerDispatchOrdering.disconnectsBeforeLaterEpochSamples(dispatch)

        assertEquals(listOf(c2Disconnect, c1Disconnect, c1Epoch2, c1Epoch3), ordered.samples)
        assertFalse(ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(ordered.samples))
    }

    @Test
    fun doesNotReorderSameEpochConnectedAndDisconnected() {
        val connected = sample("c1", 1, ControllerEventKind.CONNECTED)
        val disconnected = sample("c1", 1, ControllerEventKind.DISCONNECTED)
        val dispatch = ControllerDispatch(listOf(connected, disconnected), ControllerDelivery.STRUCTURAL)

        val ordered = ControllerDispatchOrdering.disconnectsBeforeLaterEpochSamples(dispatch)

        assertTrue(dispatch === ordered)
        assertEquals(listOf(connected, disconnected), ordered.samples)
        assertFalse(ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(ordered.samples))
    }

    private fun sample(
        controllerId: String,
        controllerEpoch: Long,
        kind: ControllerEventKind,
        buttonMask: Int = 0,
    ): ControllerStateSample =
        ControllerStateSample(controllerId, controllerEpoch, kind, buttonMask = buttonMask)
}
