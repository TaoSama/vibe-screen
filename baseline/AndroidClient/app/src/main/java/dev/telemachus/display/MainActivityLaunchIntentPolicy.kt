package dev.telemachus.display

internal enum class AutomaticUsbLaunchDecision {
    ENABLE_AUTOMATIC_USB,
    SHOW_USB_WITHOUT_AUTOMATIC_CONNECT,
    KEEP_SAVED_MODE,
}

internal object MainActivityLaunchIntentPolicy {
    fun resolve(
        hasAutoConnectExtra: Boolean,
        autoConnectExtra: Boolean,
        hasSavedAutomaticUsbConnectState: Boolean,
        savedAutomaticUsbConnect: Boolean,
        savedConnectionMode: ConnectionMode,
        allowImplicitUsbFallback: Boolean,
    ): AutomaticUsbLaunchDecision =
        when {
            hasAutoConnectExtra && autoConnectExtra -> AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB
            hasAutoConnectExtra -> AutomaticUsbLaunchDecision.SHOW_USB_WITHOUT_AUTOMATIC_CONNECT
            hasSavedAutomaticUsbConnectState && savedAutomaticUsbConnect -> AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB
            hasSavedAutomaticUsbConnectState -> AutomaticUsbLaunchDecision.KEEP_SAVED_MODE
            allowImplicitUsbFallback && savedConnectionMode == ConnectionMode.USB ->
                AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB
            else -> AutomaticUsbLaunchDecision.KEEP_SAVED_MODE
        }
}
