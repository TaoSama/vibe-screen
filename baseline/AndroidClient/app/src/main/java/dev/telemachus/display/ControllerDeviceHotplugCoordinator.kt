package dev.telemachus.display

internal data class ControllerDeviceSnapshot(
    val deviceId: Int,
    val controllerId: String,
) {
    init {
        require(controllerId.isNotBlank())
    }
}

internal data class ControllerHotplugSyncResult(
    val connected: Int,
    val disconnected: Int,
    val resynchronized: Boolean,
    val limitReached: Int,
)

/** Tracks Android input-device identity and emits structural controller lifecycle changes. */
internal class ControllerDeviceHotplugCoordinator {
    private val controllerIdsByDeviceId = linkedMapOf<Int, String>()

    fun rememberObservedController(
        deviceId: Int,
        controllerId: String,
    ) {
        require(controllerId.isNotBlank())
        controllerIdsByDeviceId[deviceId] = controllerId
    }

    fun reset() {
        controllerIdsByDeviceId.clear()
    }

    fun synchronizeAvailableControllers(
        availableDevices: List<ControllerDeviceSnapshot>,
        sessionState: ControllerSessionState,
        submit: (ControllerDispatch) -> Boolean,
    ): ControllerHotplugSyncResult {
        val availableByDeviceId = linkedMapOf<Int, String>()
        availableDevices.forEach { device -> availableByDeviceId[device.deviceId] = device.controllerId }
        val availableControllerIds = availableByDeviceId.values.toCollection(linkedSetOf())

        var connected = 0
        var disconnected = 0
        var resynchronized = false
        var limitReached = 0
        var disconnectAttempted = false

        val missingKnownControllers =
            controllerIdsByDeviceId
                .filterKeys { deviceId -> deviceId !in availableByDeviceId }
                .values
                .filterNot(availableControllerIds::contains)
        val missingActiveControllers = sessionState.activeControllerIds().filterNot(availableControllerIds::contains)
        (missingKnownControllers + missingActiveControllers).distinct().forEach { controllerId ->
            sessionState.prepareDisconnect(controllerId)?.let { result ->
                disconnectAttempted = true
                if (submit(result.dispatch) && sessionState.completeDisconnect(result.controllerId, result.controllerEpoch)) {
                    disconnected++
                }
            }
        }

        controllerIdsByDeviceId.clear()
        controllerIdsByDeviceId.putAll(availableByDeviceId)

        availableControllerIds.forEach { controllerId ->
            if (!sessionState.isActive(controllerId)) {
                when (val result = sessionState.connect(controllerId)) {
                    ControllerConnectResult.AlreadyActive -> Unit
                    is ControllerConnectResult.Connected -> {
                        if (submit(result.dispatch)) {
                            connected++
                        } else {
                            result.dispatch.samples
                                .firstOrNull { it.kind == ControllerEventKind.CONNECTED }
                                ?.let { connectedSample ->
                                    sessionState.rejectConnection(
                                        connectedSample.controllerId,
                                        connectedSample.controllerEpoch,
                                    )
                                }
                        }
                    }
                    ControllerConnectResult.LimitReached -> limitReached++
                }
            }
        }

        if (connected == 0 && disconnected == 0 && !disconnectAttempted) {
            sessionState.resynchronize()?.let { dispatch ->
                if (submit(dispatch)) resynchronized = true
            }
        }

        return ControllerHotplugSyncResult(
            connected = connected,
            disconnected = disconnected,
            resynchronized = resynchronized,
            limitReached = limitReached,
        )
    }
}
