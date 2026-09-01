package dev.telemachus.display

internal const val MAXIMUM_ACTIVE_CONTROLLERS_REJECTION_REASON =
    "maximum_active_controllers_exceeded"

internal const val MAXIMUM_CONTROLLER_STRUCTURAL_BATCHES = 128

internal const val CONTROLLER_CONNECTION_ACK_TIMEOUT_MS = 2_000L

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
    private val connectionsByInputId = linkedMapOf<Long, PendingControllerConnection>()
    private val inputIdsByConnection = mutableMapOf<ControllerConnection, Long>()
    private val pendingDisconnectsByConnection = mutableSetOf<ControllerConnection>()
    private val readyDisconnectsByConnection = linkedSetOf<ControllerConnection>()

    fun recordConnected(
        inputId: Long,
        controllerId: String,
        controllerEpoch: Long,
        nowMillis: Long,
    ): Boolean = synchronized(lock) {
        require(inputId > 0)
        require(nowMillis >= 0)
        val connection = ControllerConnection(controllerId, controllerEpoch)
        val existingConnection = connectionsByInputId[inputId]
        val existingInputId = inputIdsByConnection[connection]
        if (existingConnection != null || existingInputId != null) {
            return@synchronized existingConnection?.connection == connection && existingInputId == inputId
        }
        connectionsByInputId[inputId] = PendingControllerConnection(connection, nowMillis)
        inputIdsByConnection[connection] = inputId
        true
    }

    fun deferDisconnected(
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        val connection = ControllerConnection(controllerId, controllerEpoch)
        if (connection !in inputIdsByConnection) return@synchronized false
        pendingDisconnectsByConnection.add(connection)
    }

    fun hasDeferredDisconnectBefore(
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        pendingDisconnectsByConnection.any { connection ->
            connection.controllerId == controllerId && connection.controllerEpoch < controllerEpoch
        } ||
            readyDisconnectsByConnection.any { connection ->
                connection.controllerId == controllerId && connection.controllerEpoch < controllerEpoch
            }
    }

    fun hasDeferredDisconnectBeforeExcept(
        controllerId: String,
        controllerEpoch: Long,
        ignoredConnections: Set<ControllerConnection>,
    ): Boolean = synchronized(lock) {
        pendingDisconnectsByConnection.any { connection ->
            connection !in ignoredConnections &&
                connection.controllerId == controllerId &&
                connection.controllerEpoch < controllerEpoch
        } ||
            readyDisconnectsByConnection.any { connection ->
                connection !in ignoredConnections &&
                    connection.controllerId == controllerId &&
                    connection.controllerEpoch < controllerEpoch
            }
    }

    fun hasDeferredDisconnectFor(
        controllerId: String,
        controllerEpoch: Long,
    ): Boolean = synchronized(lock) {
        val connection = ControllerConnection(controllerId, controllerEpoch)
        connection in pendingDisconnectsByConnection || connection in readyDisconnectsByConnection
    }

    fun markDisconnectReady(
        connection: ControllerConnection,
    ): Unit = synchronized(lock) {
        readyDisconnectsByConnection.add(connection)
    }

    fun nextReadyDisconnect(): DeferredControllerDisconnect? = synchronized(lock) {
        val first = readyDisconnectsByConnection.firstOrNull() ?: return@synchronized null
        DeferredControllerDisconnect(first)
    }

    fun readyDisconnects(): List<ControllerConnection> = synchronized(lock) {
        readyDisconnectsByConnection.toList()
    }

    fun expirePendingConnections(
        nowMillis: Long,
        timeoutMillis: Long = CONTROLLER_CONNECTION_ACK_TIMEOUT_MS,
    ): List<ControllerConnection> = synchronized(lock) {
        require(nowMillis >= 0)
        require(timeoutMillis > 0)
        val expired =
            connectionsByInputId
                .values
                .filter { pending ->
                    nowMillis >= pending.connectedAtMillis &&
                        nowMillis - pending.connectedAtMillis >= timeoutMillis
                }
                .map { it.connection }
        expired.forEach(::removeConnectionLocked)
        expired
    }

    fun recordDisconnected(
        controllerId: String,
        controllerEpoch: Long,
    ) = synchronized(lock) {
        val connection = ControllerConnection(controllerId, controllerEpoch)
        removeConnectionLocked(connection)
    }

    fun acknowledge(inputId: Long): ControllerConnectionAcknowledgement? = synchronized(lock) {
        val connection = connectionsByInputId.remove(inputId)?.connection ?: return@synchronized null
        inputIdsByConnection.remove(connection, inputId)
        val hasDeferredDisconnect = pendingDisconnectsByConnection.remove(connection)
        ControllerConnectionAcknowledgement(connection, hasDeferredDisconnect)
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

    private fun removeConnectionLocked(connection: ControllerConnection) {
        inputIdsByConnection.remove(connection)?.let(connectionsByInputId::remove)
        pendingDisconnectsByConnection.remove(connection)
        readyDisconnectsByConnection.remove(connection)
    }
}

private data class PendingControllerConnection(
    val connection: ControllerConnection,
    val connectedAtMillis: Long,
)

internal data class ControllerConnectionAcknowledgement(
    val connection: ControllerConnection,
    val hasDeferredDisconnect: Boolean,
)

internal data class DeferredControllerDisconnect(
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
