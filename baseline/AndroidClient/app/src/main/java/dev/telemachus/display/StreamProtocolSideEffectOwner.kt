package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session

/**
 * Owns Protocol v1 session/generation gates for side effects that outlive one
 * inbound envelope dispatch. File-transfer decisions and WakeHost work must pass
 * through this owner before touching files, UI callbacks, or network packet senders.
 */
internal class StreamProtocolSideEffectOwner(
    private val isConnected: () -> Boolean,
    private val acceptsConnectionGeneration: (Long) -> Boolean,
    private val maximumPendingWakeHostRequests: Int = DEFAULT_MAXIMUM_PENDING_WAKE_HOST_REQUESTS,
    private val maximumPendingFileOffers: Int = DEFAULT_MAXIMUM_PENDING_FILE_OFFERS,
) {
    private var activeOwner: ProtocolOwner? = null
    private val pendingWakeHostRequests = LinkedHashMap<ByteString, ProtocolOwner>()
    private val pendingFileOffers = LinkedHashMap<ByteString, ProtocolOwner>()

    init {
        require(maximumPendingWakeHostRequests > 0) { "maximumPendingWakeHostRequests must be positive" }
        require(maximumPendingFileOffers > 0) { "maximumPendingFileOffers must be positive" }
    }

    data class ProtocolOwner(
        val session: ProtocolV1Session,
        val connectionGeneration: Long,
    )

    @Synchronized
    fun activate(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ) {
        activeOwner = ProtocolOwner(session, connectionGeneration)
        pendingWakeHostRequests.clear()
        pendingFileOffers.clear()
    }

    @Synchronized
    fun isCurrent(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean {
        val owner = activeOwner ?: return false
        return isConnected() &&
            owner.session === session &&
            owner.connectionGeneration == connectionGeneration &&
            acceptsConnectionGeneration(connectionGeneration)
    }

    fun <T> runIfCurrent(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        block: () -> T,
    ): T? {
        val current = synchronized(this) {
            val owner = activeOwner
            owner != null &&
                isConnected() &&
                owner.session === session &&
                owner.connectionGeneration == connectionGeneration &&
                acceptsConnectionGeneration(connectionGeneration)
        }
        return if (current) block() else null
    }

    @Synchronized
    fun trackFileOffer(
        transferId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean {
        if (!isCurrent(session, connectionGeneration)) return false
        if (pendingFileOffers.containsKey(transferId)) return false
        if (pendingFileOffers.size >= maximumPendingFileOffers) return false
        pendingFileOffers[transferId] = ProtocolOwner(session, connectionGeneration)
        return true
    }

    @Synchronized
    fun claimFileOffer(transferId: ByteString): ProtocolOwner? {
        val owner = pendingFileOffers.remove(transferId) ?: return null
        return if (isCurrent(owner.session, owner.connectionGeneration)) owner else null
    }

    @Synchronized
    fun releaseFileOffer(transferId: ByteString) {
        pendingFileOffers.remove(transferId)
    }

    @Synchronized
    fun clearFileOffers() {
        pendingFileOffers.clear()
    }

    @Synchronized
    fun trackWakeHostRequest(
        requestId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean {
        if (!isCurrent(session, connectionGeneration)) return false
        if (pendingWakeHostRequests.contains(requestId)) return false
        if (pendingWakeHostRequests.size >= maximumPendingWakeHostRequests) return false
        pendingWakeHostRequests[requestId] = ProtocolOwner(session, connectionGeneration)
        return true
    }

    @Synchronized
    fun releaseWakeHostRequest(
        requestId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean {
        val owner = pendingWakeHostRequests[requestId] ?: return false
        if (owner.session !== session || owner.connectionGeneration != connectionGeneration) return false
        pendingWakeHostRequests.remove(requestId)
        return true
    }

    @Synchronized
    fun closeAdmission() {
        activeOwner = null
    }

    @Synchronized
    fun clear() {
        activeOwner = null
        pendingWakeHostRequests.clear()
        pendingFileOffers.clear()
    }

    companion object {
        const val DEFAULT_MAXIMUM_PENDING_WAKE_HOST_REQUESTS = 16
        const val DEFAULT_MAXIMUM_PENDING_FILE_OFFERS = 16
    }
}
