package dev.telemachus.display.protocol

/** Keeps host-declared permanent failures from entering an automatic reconnect loop. */
internal object ProtocolReconnectPolicy {
    fun shouldReconnect(
        failure: Throwable,
        stopRequested: Boolean,
    ): Boolean {
        if (stopRequested) return false
        return (failure as? ProtocolV1Failure)?.retryable != false
    }
}
