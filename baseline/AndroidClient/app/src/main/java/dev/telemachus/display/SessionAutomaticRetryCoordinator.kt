package dev.telemachus.display

/**
 * Coordinates terminal callbacks with connection-coroutine finally blocks.
 *
 * This is the single owner of the automatic-retry scheduling decision for a
 * session. Both the protocol-layer reconnect suggestion (which carries the
 * bounded backoff delay) and the connection-coroutine finally block feed into
 * this coordinator. The scheduled retry always uses the delay supplied by
 * [onReconnectSuggested] when it is available. If the finally block runs first
 * and the session is still eligible for automatic retry, the default initial
 * delay is posted and then replaced by the suggested delay once it arrives.
 * Terminal (non-retryable) failures never schedule a retry.
 */
internal class SessionAutomaticRetryCoordinator(
    private val postAutomaticRetry: (Long) -> Unit,
    private val cancelPendingAutomaticRetry: () -> Unit,
    private val handleServerShutdown: () -> Unit,
) {
    private var permanentlyStopped = false
    private var showTerminalGuidance = false
    private var serverShutdownHandled = false
    private var pendingRetryDelayMs: Long? = null
    private var finallyProcessed = false
    private var retryScheduled = false
    private var retryEligible = false

    @Synchronized
    fun onSessionEnded(failure: SessionFailure): Boolean {
        if (failure.retryable) return false
        if (!permanentlyStopped) {
            permanentlyStopped = true
            showTerminalGuidance = !failure.intentional
            cancelPendingAutomaticRetry()
        }
        return showTerminalGuidance
    }

    @Synchronized
    fun onReconnectSuggested(delayMs: Long) {
        if (permanentlyStopped) return
        pendingRetryDelayMs = delayMs
        if (finallyProcessed && retryEligible) {
            // finally already scheduled a retry (possibly with the default
            // delay); replace it with the correct bounded-backoff delay.
            retryScheduled = true
            postAutomaticRetry(delayMs)
        }
    }

    @Synchronized
    fun onServerShutdown() {
        if (serverShutdownHandled) return
        serverShutdownHandled = true
        handleServerShutdown()
    }

    @Synchronized
    fun onConnectionFinally(
        automaticRetryEnabled: Boolean,
        disconnected: Boolean,
    ) {
        finallyProcessed = true
        retryEligible = !permanentlyStopped && automaticRetryEnabled && disconnected
        if (!retryEligible) return
        if (retryScheduled) return
        retryScheduled = true
        val delayMs = pendingRetryDelayMs ?: ReconnectBackoff.INITIAL_DELAY_MS
        postAutomaticRetry(delayMs)
    }
}
