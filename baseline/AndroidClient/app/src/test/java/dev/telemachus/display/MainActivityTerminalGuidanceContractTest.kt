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

    @Test
    fun onConfigurationChangedConnectionTitleUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val onConfigurationChanged = extractMethod(source, "override fun onConfigurationChanged")

        assertFalse(
            "onConfigurationChanged must not set connectionTitle via setText (bypasses live-region deduplication)",
            onConfigurationChanged.contains("connectionTitle.setText"),
        )
        assertUsesLiveRegion(onConfigurationChanged, "connectionTitle", "onConfigurationChanged")
    }

    @Test
    fun updateDisconnectedHeaderUsesLiveRegionApplierForTitleAndSubtitle() {
        val source = mainActivitySource()
        val updateHeader = extractMethod(source, "private fun updateDisconnectedHeader")

        assertFalse(
            "updateDisconnectedHeader must not set connectionTitle via setText",
            updateHeader.contains("connectionTitle.setText"),
        )
        assertFalse(
            "updateDisconnectedHeader must not set connectionSubtitle via setText",
            updateHeader.contains("connectionSubtitle.setText"),
        )
        assertUsesLiveRegion(updateHeader, "connectionTitle", "updateDisconnectedHeader")
        assertUsesLiveRegion(updateHeader, "connectionSubtitle", "updateDisconnectedHeader")
    }

    @Test
    fun updateUsbTransportSubtitleUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val updateSubtitle = extractMethod(source, "private fun updateUsbTransportSubtitle")

        assertFalse(
            "updateUsbTransportSubtitle must not set connectionSubtitle via direct .text assignment",
            updateSubtitle.contains("connectionSubtitle.text ="),
        )
        assertUsesLiveRegion(updateSubtitle, "connectionSubtitle", "updateUsbTransportSubtitle")
    }

    @Test
    fun revocationQuarantineInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val allowMutation = extractMethod(source, "private fun allowInternetCredentialMutation")

        assertNoDirectInternetErrorTextAssignment(allowMutation, "revocation quarantine")
        assertUsesLiveRegionShow(allowMutation, "internetErrorText", "revocation quarantine")
    }

    @Test
    fun revokeInternetPairingInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val revoke = extractMethod(source, "private fun revokeInternetPairing")

        assertNoDirectInternetErrorTextAssignment(revoke, "revokeInternetPairing")
        assertUsesLiveRegionShow(revoke, "internetErrorText", "revokeInternetPairing")
    }

    @Test
    fun setupInternetUiPendingRevocationCleanupInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val setup = extractMethod(source, "private fun setupInternetUi")

        assertNoDirectInternetErrorTextAssignment(setup, "setupInternetUi")
        assertUsesLiveRegionShow(setup, "internetErrorText", "setupInternetUi")
    }

    @Test
    fun onFreshSessionRequiredInternetErrorTextUsesLiveRegionApplier() {
        val source = mainActivitySource()
        val callback = extractMethod(source, "override fun onFreshSessionRequired")

        assertNoDirectInternetErrorTextAssignment(callback, "onFreshSessionRequired")
        assertUsesLiveRegionShow(callback, "internetErrorText", "onFreshSessionRequired")
    }

    @Test
    fun internetStateTextAlwaysUsesLiveRegionApplier() {
        val source = mainActivitySource()

        assertFalse(source.contains("internetStateText.setText"))
        assertFalse(source.contains("internetStateText.text ="))
        assertUsesLiveRegion(source, "internetStateText", "MainActivity", minimumCalls = 6)
    }

    @Test
    fun internetErrorVisibilityUsesAnnouncementAwareHelpers() {
        val compactSource = mainActivitySource().replace(Regex("\\s+"), "")

        assertFalse(compactSource.contains("internetErrorText.visibility=View.VISIBLE"))
        assertFalse(compactSource.contains("internetErrorText.visibility=View.GONE"))
        assertTrue(compactSource.windowed("LiveRegionTextApplier.show(binding.internetErrorText,".length)
            .count { it == "LiveRegionTextApplier.show(binding.internetErrorText," } >= 5)
        assertTrue(compactSource.windowed("LiveRegionTextApplier.hide(binding.internetErrorText)".length)
            .count { it == "LiveRegionTextApplier.hide(binding.internetErrorText)" } >= 3)
    }

    private fun assertNoDirectInternetErrorTextAssignment(block: String, owner: String) {
        assertFalse(
            "$owner must not set internetErrorText via setText (bypasses live-region deduplication)",
            block.contains("internetErrorText.setText"),
        )
        assertFalse(
            "$owner must not set internetErrorText via direct .text assignment (bypasses live-region deduplication)",
            block.contains("internetErrorText.text ="),
        )
    }

    private fun assertUsesLiveRegion(
        block: String,
        viewName: String,
        owner: String,
        minimumCalls: Int = 1,
    ) {
        val compactBlock = block.replace(Regex("\\s+"), "")
        val invocation = "LiveRegionTextApplier.apply(binding.$viewName,"
        val callCount = compactBlock.windowed(invocation.length).count { it == invocation }
        assertTrue(
            "$owner must route $viewName through LiveRegionTextApplier at least $minimumCalls time(s); found $callCount",
            callCount >= minimumCalls,
        )
    }

    private fun assertUsesLiveRegionShow(
        block: String,
        viewName: String,
        owner: String,
    ) {
        val compactBlock = block.replace(Regex("\\s+"), "")
        assertTrue(
            "$owner must make $viewName visible before changing its live-region text",
            compactBlock.contains("LiveRegionTextApplier.show(binding.$viewName,"),
        )
    }

    private fun extractMethod(source: String, signature: String): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        var braceDepth = 0
        var i = source.indexOf('{', start)
        require(i >= 0) { "Opening brace not found for $signature" }
        while (i < source.length) {
            when (source[i]) {
                '{' -> braceDepth++
                '}' -> {
                    braceDepth--
                    if (braceDepth == 0) return source.substring(start, i + 1)
                }
            }
            i++
        }
        error("Closing brace not found for $signature")
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
