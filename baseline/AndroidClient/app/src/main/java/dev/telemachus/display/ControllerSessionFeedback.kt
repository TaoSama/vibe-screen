package dev.telemachus.display

internal const val MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON =
    "maximum_active_controllers_exceeded"

internal data class ControllerConnection(
    val controllerId: String,
    val controllerEpoch: Long,
) {
    init {
        require(controllerId.isNotBlank())
        require(controllerEpoch > 0)
    }
}

/** Correlates optional host InputAck messages with active controller lifecycles. */
internal class ControllerConnectionAckTracker {
    private val lock = Any()
    private val connectionsByInputId = linkedMapOf<Long, ControllerConnection>()
    private val inputIdsByConnection = mutableMapOf<ControllerConnection, Long>()
    private val pendingDisconnectsByConnection = mutableMapOf<ControllerConnection, Long>()
    private val readyDisconnectsByConnection = linkedMapOf<ControllerConnection, Long>()

    fun recordConnected(
        inputId: Long,
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        require(inputId > 0)
        val connection = ControllerConnection(controllerId, controllerEpoch)
        val existingConnection = connectionsByInputId[inputId]
        val existingInputId = inputIdsByConnection[connection]
        if (existingConnection != null || existingInputId != null) {
            return@synchronized existingConnection == connection && existingInputId == inputId
        }
        connectionsByInputId[inputId] = connection
        inputIdsByConnection[connection] = inputId
        true
    }

    fun deferDisconnected(
        inputId: Long,
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        require(inputId > 0)
        val connection = ControllerConnection(controllerId, controllerEpoch)
        if (connection !in inputIdsByConnection) return@synchronized false
        pendingDisconnectsByConnection.putIfAbsent(connection, inputId) == null
    }

    fun hasDeferredDisconnectBefore(
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        pendingDisconnectsByConnection.keys.any { connection ->
            connection.controllerId == controllerId && connection.controllerEpoch < controllerEpoch
        } ||
            readyDisconnectsByConnection.keys.any { connection ->
                connection.controllerId == controllerId && connection.controllerEpoch < controllerEpoch
            }
    }

    fun markDisconnectReady(
        connection: ControllerConnection,
        inputId: Long,
    ): Unit = synchronized(lock) {
        require(inputId > 0)
        readyDisconnectsByConnection.putIfAbsent(connection, inputId)
    }

    fun nextReadyDisconnect(): DeferredControllerDisconnect? = synchronized(lock) {
        val first = readyDisconnectsByConnection.entries.firstOrNull() ?: return@synchronized null
        DeferredControllerDisconnect(first.value, first.key)
    }

    fun recordDisconnected(
        controllerId: String,
        controllerEpoch: Long,
    ) = synchronized(lock) {
        val connection = ControllerConnection(controllerId, controllerEpoch)
        inputIdsByConnection.remove(connection)?.let(connectionsByInputId::remove)
        pendingDisconnectsByConnection.remove(connection)
        readyDisconnectsByConnection.remove(connection)
    }

    fun acknowledge(inputId: Long): ControllerConnectionAcknowledgement? = synchronized(lock) {
        val connection = connectionsByInputId.remove(inputId) ?: return@synchronized null
        inputIdsByConnection.remove(connection, inputId)
        val deferredDisconnectInputId = pendingDisconnectsByConnection.remove(connection)
        ControllerConnectionAcknowledgement(connection, deferredDisconnectInputId)
    }

    fun isPending(
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        inputIdsByConnection.containsKey(ControllerConnection(controllerId, controllerEpoch))
    }

    fun reset() = synchronized(lock) {
        connectionsByInputId.clear()
        inputIdsByConnection.clear()
        pendingDisconnectsByConnection.clear()
        readyDisconnectsByConnection.clear()
    }

    internal fun pendingCount(): Int = synchronized(lock) { connectionsByInputId.size }
}

internal data class ControllerConnectionAcknowledgement(
    val connection: ControllerConnection,
    val deferredDisconnectInputId: Long?,
)

internal data class DeferredControllerDisconnect(
    val inputId: Long,
    val connection: ControllerConnection,
)

internal data class RejectedControllerConnection(
    val controllerId: String,
    val controllerEpoch: Long,
) {
    init {
        require(controllerId.isNotBlank())
        require(controllerEpoch > 0)
    }
}

internal object ControllerInputAckPolicy {
    fun rejectedConnection(
        controllerId: String?,
        controllerEpoch: Long?,
        accepted: Boolean,
    ): RejectedControllerConnection? {
        if (accepted) return null
        if (controllerId.isNullOrBlank() || controllerEpoch == null || controllerEpoch <= 0L) return null
        return RejectedControllerConnection(controllerId, controllerEpoch)
    }

    fun isMaximumActiveControllersRejection(rejectionReason: String): Boolean =
        rejectionReason == MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON
}

internal object ControllerNoticePolicy {
    fun shouldShowUnsupported(
        isConnected: Boolean,
        hasNegotiatedControllerCapability: Boolean,
    ): Boolean = isConnected && !hasNegotiatedControllerCapability
}

internal object ControllerInputConsumptionPolicy {
    fun shouldConsume(
        isConnected: Boolean,
        isSystemKey: Boolean,
    ): Boolean = isConnected && !isSystemKey
}

internal class ControllerNoticeState {
    private val lock = Any()
    private var unsupportedShown = false
    private var limitShown = false
    private var rejectedShown = false

    fun shouldShowUnsupported(): Boolean = synchronized(lock) {
        if (unsupportedShown) return false
        unsupportedShown = true
        true
    }

    fun shouldShowLimit(): Boolean = synchronized(lock) {
        if (limitShown) return false
        limitShown = true
        true
    }

    fun shouldShowRejected(): Boolean = synchronized(lock) {
        if (rejectedShown) return false
        rejectedShown = true
        true
    }

    /** Capacity can recover within a session; unsupported/rejected notices reset only with the session. */
    fun resetLimit() = synchronized(lock) {
        limitShown = false
    }

    fun resetForNewSession() = synchronized(lock) {
        unsupportedShown = false
        limitShown = false
        rejectedShown = false
    }
}
