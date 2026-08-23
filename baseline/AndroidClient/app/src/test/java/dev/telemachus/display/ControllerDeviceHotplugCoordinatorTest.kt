package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerDeviceHotplugCoordinatorTest {
    @Test
    fun addedDeviceConnectsControllerAndChangedDeviceResynchronizesState() {
        val coordinator = ControllerDeviceHotplugCoordinator()
        val state = ControllerSessionState()
        val sent = mutableListOf<ControllerDispatch>()

        val added = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(7, "controller-a")),
            sessionState = state,
            submit = sent::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 1, disconnected = 0, resynchronized = false, limitReached = 0), added)
        assertTrue(state.isActive("controller-a"))
        assertEquals(ControllerEventKind.CONNECTED, sent.single().samples.first().kind)

        sent.clear()
        state.applyKey(ControllerKeyChange.Button("controller-a", pressed = true, ControllerButton.A))

        val changed = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(7, "controller-a")),
            sessionState = state,
            submit = sent::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 0, disconnected = 0, resynchronized = true, limitReached = 0), changed)
        assertEquals(ControllerDelivery.STRUCTURAL, sent.single().delivery)
        assertEquals(1 shl ControllerButton.A.bit, sent.single().samples.single().buttonMask)
    }

    @Test
    fun removedDeviceReleasesControllerAndAvailableDeviceFillsSlot() {
        val coordinator = ControllerDeviceHotplugCoordinator()
        val state = ControllerSessionState()
        val sent = mutableListOf<ControllerDispatch>()

        coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(
                ControllerDeviceSnapshot(1, "controller-a"),
                ControllerDeviceSnapshot(2, "controller-b"),
            ),
            sessionState = state,
            submit = sent::add,
        )
        sent.clear()

        val removed = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(2, "controller-b")),
            sessionState = state,
            submit = sent::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 0, disconnected = 1, resynchronized = false, limitReached = 0), removed)
        assertFalse(state.isActive("controller-a"))
        assertTrue(state.isActive("controller-b"))
        assertTrue(sent.single().samples.any { it.controllerId == "controller-a" && it.kind == ControllerEventKind.DISCONNECTED })
    }

    @Test
    fun changedDeviceIdForSameControllerDoesNotEmitDisconnect() {
        val coordinator = ControllerDeviceHotplugCoordinator()
        val state = ControllerSessionState()
        val sent = mutableListOf<ControllerDispatch>()

        coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(1, "controller-a")),
            sessionState = state,
            submit = sent::add,
        )
        sent.clear()

        val changed = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(9, "controller-a")),
            sessionState = state,
            submit = sent::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 0, disconnected = 0, resynchronized = true, limitReached = 0), changed)
        assertTrue(state.isActive("controller-a"))
        assertTrue(sent.single().samples.all { it.kind == ControllerEventKind.STATE })
    }

    @Test
    fun fullSessionReportsUnsupportedHotplugWithoutMutatingActiveControllers() {
        val coordinator = ControllerDeviceHotplugCoordinator()
        val state = ControllerSessionState()
        val sent = mutableListOf<ControllerDispatch>()
        val initialDevices = (1..MAXIMUM_ACTIVE_CONTROLLERS).map { deviceId ->
            ControllerDeviceSnapshot(deviceId, "controller-$deviceId")
        }

        coordinator.synchronizeAvailableControllers(
            availableDevices = initialDevices,
            sessionState = state,
            submit = sent::add,
        )
        sent.clear()

        val full = coordinator.synchronizeAvailableControllers(
            availableDevices = initialDevices + ControllerDeviceSnapshot(99, "controller-extra"),
            sessionState = state,
            submit = sent::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 0, disconnected = 0, resynchronized = true, limitReached = 1), full)
        assertFalse(state.isActive("controller-extra"))
        assertEquals(initialDevices.map { it.controllerId }.toSet(), state.activeControllerIds())
    }

    @Test
    fun failedConnectSubmitRollsBackControllerSoNextHotplugRetriesConnect() {
        val coordinator = ControllerDeviceHotplugCoordinator()
        val state = ControllerSessionState()
        val retriedDispatches = mutableListOf<ControllerDispatch>()

        val failed = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(7, "controller-a")),
            sessionState = state,
            submit = { false },
        )

        assertEquals(ControllerHotplugSyncResult(connected = 0, disconnected = 0, resynchronized = false, limitReached = 0), failed)
        assertFalse(state.isActive("controller-a"))

        val retried = coordinator.synchronizeAvailableControllers(
            availableDevices = listOf(ControllerDeviceSnapshot(7, "controller-a")),
            sessionState = state,
            submit = retriedDispatches::add,
        )

        assertEquals(ControllerHotplugSyncResult(connected = 1, disconnected = 0, resynchronized = false, limitReached = 0), retried)
        assertEquals(ControllerEventKind.CONNECTED, retriedDispatches.single().samples.first().kind)
    }
}
