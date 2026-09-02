package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class MainActivityLaunchIntentPolicyTest {
    @Test
    fun `explicit auto_connect true enables automatic USB regardless of saved state`() {
        assertEquals(
            AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = true,
                autoConnectExtra = true,
                hasSavedAutomaticUsbConnectState = true,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.INTERNET,
                allowImplicitUsbFallback = false,
            ),
        )
    }

    @Test
    fun `explicit auto_connect false shows USB without automatic connect`() {
        assertEquals(
            AutomaticUsbLaunchDecision.SHOW_USB_WITHOUT_AUTOMATIC_CONNECT,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = true,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = true,
                savedAutomaticUsbConnect = true,
                savedConnectionMode = ConnectionMode.USB,
                allowImplicitUsbFallback = true,
            ),
        )
    }

    @Test
    fun `no extra and saved automatic USB true enables automatic USB`() {
        assertEquals(
            AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = true,
                savedAutomaticUsbConnect = true,
                savedConnectionMode = ConnectionMode.WIRELESS,
                allowImplicitUsbFallback = false,
            ),
        )
    }

    @Test
    fun `no extra and saved automatic USB false keeps saved mode`() {
        assertEquals(
            AutomaticUsbLaunchDecision.KEEP_SAVED_MODE,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = true,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.USB,
                allowImplicitUsbFallback = true,
            ),
        )
    }

    @Test
    fun `no extra no saved state with implicit USB fallback and USB mode enables automatic USB`() {
        assertEquals(
            AutomaticUsbLaunchDecision.ENABLE_AUTOMATIC_USB,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = false,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.USB,
                allowImplicitUsbFallback = true,
            ),
        )
    }

    @Test
    fun `no extra no saved state without implicit fallback keeps saved mode even in USB`() {
        assertEquals(
            AutomaticUsbLaunchDecision.KEEP_SAVED_MODE,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = false,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.USB,
                allowImplicitUsbFallback = false,
            ),
        )
    }

    @Test
    fun `no extra no saved state with implicit fallback but non-USB mode keeps saved mode`() {
        assertEquals(
            AutomaticUsbLaunchDecision.KEEP_SAVED_MODE,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = false,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.WIRELESS,
                allowImplicitUsbFallback = true,
            ),
        )
    }

    @Test
    fun `onNewIntent with auto_connect false shows USB without automatic connect`() {
        assertEquals(
            AutomaticUsbLaunchDecision.SHOW_USB_WITHOUT_AUTOMATIC_CONNECT,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = true,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = false,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.WIRELESS,
                allowImplicitUsbFallback = false,
            ),
        )
    }

    @Test
    fun `recreation after explicit auto_connect false keeps saved mode without auto-connect`() {
        assertEquals(
            AutomaticUsbLaunchDecision.KEEP_SAVED_MODE,
            MainActivityLaunchIntentPolicy.resolve(
                hasAutoConnectExtra = false,
                autoConnectExtra = false,
                hasSavedAutomaticUsbConnectState = true,
                savedAutomaticUsbConnect = false,
                savedConnectionMode = ConnectionMode.USB,
                allowImplicitUsbFallback = true,
            ),
        )
    }
}
