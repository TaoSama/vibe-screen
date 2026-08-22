package dev.telemachus.display

/**
 * Owns product-session lifecycle state for the USB/LAN StreamClient.
 *
 * The transport owner decides which socket is active. This state keeps local
 * session intent, readiness, epoch ownership, and reconnect backoff together so
 * StreamClient does not spread product-session decisions across transport, media,
 * and protocol handling paths.
 */
internal class StreamClientLocalSessionState(
    private val epochGate: SessionEpochGate = SessionEpochGate(),
    private val reconnectBackoff: ReconnectBackoff = ReconnectBackoff(),
) {
    @Volatile var isConnected = false
        private set
    @Volatile var isReady = false
        private set
    @Volatile var stopRequested = false
        private set
    @Volatile var connectionEpoch = 0L
        private set
    @Volatile var lastTerminationFailure: SessionFailure? = null
        private set

    fun prepareConnectionStart() {
        resetReadiness()
        allowResumeAfterFailure()
    }

    fun resetReadiness() {
        isReady = false
    }

    fun beginSession(): Long {
        connectionEpoch = epochGate.beginSession()
        return connectionEpoch
    }

    fun markConnected() {
        isConnected = true
    }

    fun markDisconnected() {
        isConnected = false
    }

    fun requestStop() {
        stopRequested = true
    }

    fun allowResumeAfterFailure() {
        stopRequested = false
    }

    fun markTerminationClaimed(failure: SessionFailure) {
        lastTerminationFailure = failure
        markDisconnected()
    }

    fun markReady(): Boolean {
        if (isReady) return false
        isReady = true
        reconnectBackoff.reset()
        return true
    }

    fun acceptsEpoch(epoch: Long): Boolean = epochGate.accepts(epoch)

    fun currentEpoch(): Long = epochGate.currentEpoch()

    fun ownsAttempt(attemptGeneration: Long): Boolean =
        connectionEpoch == attemptGeneration && acceptsEpoch(attemptGeneration)

    fun ownsCurrentEpoch(): Boolean = connectionEpoch == 0L || acceptsEpoch(connectionEpoch)

    fun nextReconnectDelayMs(): Long = reconnectBackoff.nextDelayMs()
}
