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

internal object MacServerChecklistStatusPolicy {
    fun waitingStatus(
        connectionGuidanceVisible: Boolean,
        connectionAttemptInProgress: Boolean,
    ): ChecklistStatus =
        if (connectionGuidanceVisible && !connectionAttemptInProgress) {
            ChecklistStatus.NOT_READY
        } else {
            ChecklistStatus.CHECKING
        }
}
