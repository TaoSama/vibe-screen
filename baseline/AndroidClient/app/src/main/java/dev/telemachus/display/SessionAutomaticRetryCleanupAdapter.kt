package dev.telemachus.display

/** Applies automatic-retry cleanup only while its owning session generation is current. */
internal class SessionAutomaticRetryCleanupAdapter(
    private val isCurrentGeneration: () -> Boolean,
    private val disableAutomaticUsbConnect: () -> Unit,
    private val cancelWirelessReconnect: () -> Unit,
    private val removeAutomaticUsbRunnable: () -> Unit,
) {
    fun cleanup() {
        if (!isCurrentGeneration()) return
        disableAutomaticUsbConnect()
        cancelWirelessReconnect()
        removeAutomaticUsbRunnable()
    }
}
