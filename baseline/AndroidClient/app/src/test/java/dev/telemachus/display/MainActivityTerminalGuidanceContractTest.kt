package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityTerminalGuidanceContractTest {
    @Test
    fun onSessionEndedUsesRetainedSessionPortInsteadOfCurrentUiPort() {
        val callback = onSessionEndedCallback(mainActivitySource())
        val compactCallback = callback.replace(Regex("\\s+"), " ")

        assertTrue(
            "onSessionEnded must build guidance from the immutable session context",
            compactCallback.contains("guidanceContext.withPort(callbackClient.actualPort)"),
        )
        assertFalse(
            "onSessionEnded must not read the current UI port",
            callback.contains("currentUsbPort()"),
        )
        assertFalse(
            "onSessionEnded must not read view binding on the termination thread",
            callback.contains("binding."),
        )
        assertFalse(
            "onSessionEnded diagnostics must not persist raw failure details",
            callback.contains("failure.detail"),
        )
    }

    @Test
    fun setupCallersCaptureUsbAndLanOwnershipBeforeCallbacks() {
        val source = mainActivitySource().replace(Regex("\\s+"), " ")

        assertTrue(
            "USB connections must capture their ADB transport before callback delivery",
            source.contains("ConnectionGuidanceContext.adb(port, currentUsbTransportSnapshot().adbTransport)"),
        )
        assertTrue(
            "LAN connections must capture trusted-LAN ownership",
            source.contains("ConnectionGuidanceContext.trustedLan(port)"),
        )
        assertTrue(
            "Internet failures must use Internet-owned guidance",
            source.contains("ConnectionGuidanceContext.internet()"),
        )
    }

    private fun onSessionEndedCallback(source: String): String {
        val startMarker = "callbackClient.onSessionEnded = sessionEnded@{ failure ->"
        val endMarker = "callbackClient.onConnectionStatus = connectionStatus@{ connected ->"
        val start = source.indexOf(startMarker)
        require(start >= 0) { "MainActivity onSessionEnded callback not found" }
        val end = source.indexOf(endMarker, start)
        require(end > start) { "MainActivity onSessionEnded callback boundary not found" }
        return source.substring(start, end)
    }

    private fun mainActivitySource(): String {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            MAIN_ACTIVITY_PATHS
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it.readText() }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("MainActivity.kt not found from " + System.getProperty("user.dir"))
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
    }
}
