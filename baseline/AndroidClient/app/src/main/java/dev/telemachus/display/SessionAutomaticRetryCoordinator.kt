package dev.telemachus.display

/** Coordinates terminal callbacks with connection-coroutine finally blocks. */
internal class SessionAutomaticRetryCoordinator(
    private val postAutomaticRetry: () -> Unit,
    private val cancelPendingAutomaticRetry: () -> Unit,
    private val handleServerShutdown: () -> Unit,
) {
    private var permanentlyStopped = false
    private var showTerminalGuidance = false
    private var serverShutdownHandled = false

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
        if (automaticRetryEnabled && disconnected && !permanentlyStopped) {
            postAutomaticRetry()
        }
    }
}
