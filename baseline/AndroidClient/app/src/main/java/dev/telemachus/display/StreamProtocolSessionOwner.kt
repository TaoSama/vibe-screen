package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolV1Session

/**
 * Owns the Protocol v1 product-session orchestration boundary for the USB/LAN
 * StreamClient.
 *
 * This owner composes the local connection epoch/readiness state, the
 * side-effect admission gate, and the active [ProtocolV1Session] reference so
 * StreamClient no longer spreads protocol-session lifecycle, epoch ownership,
 * cleanup, and retry-transition admission across transport, media, and protocol
 * handling paths.
 *
 * It intentionally has no Android UI, concrete socket, hardware decoder, file-transfer
 * side-effect, or WakeHost packet-sender dependencies.
 */
internal class StreamProtocolSessionOwner(
    epochGate: SessionEpochGate = SessionEpochGate(),
    reconnectBackoff: ReconnectBackoff = ReconnectBackoff(),
    maximumPendingWakeHostRequests: Int = StreamProtocolSideEffectOwner.DEFAULT_MAXIMUM_PENDING_WAKE_HOST_REQUESTS,
    maximumPendingFileOffers: Int = StreamProtocolSideEffectOwner.DEFAULT_MAXIMUM_PENDING_FILE_OFFERS,
) {
    private val localSessionState = StreamClientLocalSessionState(epochGate, reconnectBackoff)
    private val protocolSideEffectOwner =
        StreamProtocolSideEffectOwner(
            isConnected = { localSessionState.isConnected && !localSessionState.stopRequested },
            acceptsConnectionGeneration = localSessionState::acceptsEpoch,
            maximumPendingWakeHostRequests = maximumPendingWakeHostRequests,
            maximumPendingFileOffers = maximumPendingFileOffers,
        )

    @Volatile private var protocolSession: ProtocolV1Session? = null

    /** The currently active Protocol v1 session, or null when not negotiated. */
    val currentSession: ProtocolV1Session?
        get() = protocolSession

    /** The connection generation/epoch that owns the active session. */
    val connectionGeneration: Long
        get() = localSessionState.connectionEpoch

    // ---- Protocol v1 session lifecycle ----

    /**
     * Activates [session] as the current Protocol v1 session and binds the
     * side-effect admission gate to the current connection generation.
     */
    fun activate(session: ProtocolV1Session) {
        protocolSession = session
        protocolSideEffectOwner.activate(session, localSessionState.connectionEpoch)
    }

    /**
     * Deactivates the current Protocol v1 session and clears side-effect
     * admission state. Used when falling back to legacy mode.
     */
    fun deactivate() {
        protocolSession = null
        protocolSideEffectOwner.clear()
    }

    /**
     * Stops accepting delayed side effects while retaining the Protocol v1
     * session reference for already-admitted outbound drain work.
     */
    fun clearSideEffectAdmission() {
        protocolSideEffectOwner.closeAdmission()
    }

    /**
     * Full session cleanup after outbound drain has finished. Clears the session
     * reference and side-effect gates.
     */
    fun clear() {
        protocolSession = null
        protocolSideEffectOwner.clear()
    }

    // ---- Local session state (epochs, readiness, retry) ----

    fun prepareConnectionStart() = localSessionState.prepareConnectionStart()

    fun beginSession(): Long = localSessionState.beginSession()

    fun markConnected() = localSessionState.markConnected()

    fun markDisconnected() = localSessionState.markDisconnected()

    fun requestStop() = localSessionState.requestStop()

    fun allowResumeAfterFailure() = localSessionState.allowResumeAfterFailure()

    fun markReady(): Boolean = localSessionState.markReady()

    val isConnected: Boolean
        get() = localSessionState.isConnected

    val isReady: Boolean
        get() = localSessionState.isReady

    val stopRequested: Boolean
        get() = localSessionState.stopRequested

    val connectionEpoch: Long
        get() = localSessionState.connectionEpoch

    val lastTerminationFailure: SessionFailure?
        get() = localSessionState.lastTerminationFailure

    fun acceptsEpoch(epoch: Long): Boolean = localSessionState.acceptsEpoch(epoch)

    fun currentEpoch(): Long = localSessionState.currentEpoch()

    fun ownsAttempt(attemptGeneration: Long): Boolean =
        localSessionState.ownsAttempt(attemptGeneration)

    fun ownsCurrentEpoch(): Boolean = localSessionState.ownsCurrentEpoch()

    fun nextReconnectDelayMs(): Long = localSessionState.nextReconnectDelayMs()

    fun markTerminationClaimed(failure: SessionFailure) =
        localSessionState.markTerminationClaimed(failure)

    // ---- Side-effect admission gates ----

    fun isCurrent(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean = protocolSideEffectOwner.isCurrent(session, connectionGeneration)

    fun retainsSession(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean = currentSession === session && localSessionState.acceptsEpoch(connectionGeneration)

    fun <T> runIfCurrent(
        session: ProtocolV1Session,
        connectionGeneration: Long,
        block: () -> T,
    ): T? = protocolSideEffectOwner.runIfCurrent(session, connectionGeneration, block)

    fun trackFileOffer(
        transferId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean = protocolSideEffectOwner.trackFileOffer(transferId, session, connectionGeneration)

    fun claimFileOffer(transferId: ByteString): StreamProtocolSideEffectOwner.ProtocolOwner? =
        protocolSideEffectOwner.claimFileOffer(transferId)

    fun releaseFileOffer(transferId: ByteString) =
        protocolSideEffectOwner.releaseFileOffer(transferId)

    fun hasFileOffer(transferId: ByteString): Boolean =
        protocolSideEffectOwner.hasFileOffer(transferId)

    fun clearFileOffers() = protocolSideEffectOwner.clearFileOffers()

    fun trackWakeHostRequest(
        requestId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
        correlationId: Long = 0L,
    ): Boolean = protocolSideEffectOwner.trackWakeHostRequest(requestId, session, connectionGeneration, correlationId)

    fun releaseWakeHostRequest(
        requestId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean = protocolSideEffectOwner.releaseWakeHostRequest(requestId, session, connectionGeneration)

    fun hasWakeHostRequest(
        requestId: ByteString,
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): Boolean = protocolSideEffectOwner.hasWakeHostRequest(requestId, session, connectionGeneration)

    fun cancelWakeHostRequests(
        session: ProtocolV1Session,
        connectionGeneration: Long,
    ): List<StreamProtocolSideEffectOwner.PendingWakeHostRequest> =
        protocolSideEffectOwner.cancelWakeHostRequests(session, connectionGeneration)
}
