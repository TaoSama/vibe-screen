package dev.telemachus.display

internal object ChecklistProbeResultPolicy {
    fun shouldApply(
        connectionMode: ConnectionMode,
        detailsVisible: Boolean,
        connected: Boolean,
        connectionAttemptInProgress: Boolean,
        automaticUsbConnect: Boolean,
    ): Boolean =
        connectionMode == ConnectionMode.USB &&
            detailsVisible &&
            !connected &&
            !connectionAttemptInProgress &&
            !automaticUsbConnect
}
