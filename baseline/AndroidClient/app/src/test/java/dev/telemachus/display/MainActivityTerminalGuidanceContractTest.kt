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
    fun modeVisibilityAppliesSubtitleLayoutFromItsExplicitMode() {
        val source = mainActivitySource()
        val applyModeVisibility = extractMethod(source, "private fun applyModeVisibility")
        val applyConnectionPanelLayout = extractMethod(source, "private fun applyConnectionPanelLayout")
        val compactModeVisibility = applyModeVisibility.replace(Regex("\\s+"), "")
        val compactLayout = applyConnectionPanelLayout.replace(Regex("\\s+"), "")

        assertTrue(
            "Mode visibility must render disclosure state from the requested mode",
            compactModeVisibility.contains("applyConnectionPanelLayout(mode)"),
        )
        assertTrue(
            "Configuration-driven callers may still use the current persisted mode by default",
            compactLayout.contains("connectionMode:ConnectionMode=prefs.connectionMode"),
        )
        assertTrue(
            "The explicit layout mode must reach the disclosure applier",
            compactLayout.contains("connectionMode=connectionMode"),
        )
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
        // Imported, pairing, session, failure, idle, and revoked states all announce through the helper.
        assertUsesLiveRegion(source, "internetStateText", "MainActivity", minimumCalls = 6)
    }

    @Test
    fun internetErrorVisibilityUsesAnnouncementAwareHelpers() {
        val compactSource = mainActivitySource().replace(Regex("\\s+"), "")
        val showInvocation = "LiveRegionTextApplier.show(binding.internetErrorText,"
        val hideInvocation = "LiveRegionTextApplier.hide(binding.internetErrorText)"
        val showCount = countOccurrences(compactSource, showInvocation)
        val hideCount = countOccurrences(compactSource, hideInvocation)

        assertFalse(compactSource.contains("internetErrorText.visibility=View.VISIBLE"))
        assertFalse(compactSource.contains("internetErrorText.visibility=View.GONE"))
        // Cleanup, fresh-session, session failure, quarantine, and revocation paths show errors.
        assertTrue("Expected at least 5 error show calls; found $showCount", showCount >= 5)
        // Import success, session creation, and idle disconnect hide stale errors.
        assertTrue("Expected at least 3 error hide calls; found $hideCount", hideCount >= 3)
    }

    @Test
    fun methodExtractionIgnoresBracesOutsideTheMethodStructure() {
        val source =
            """
            // private fun target() { declaration decoy }
            private fun target() {
                val ordinary = "{ string brace }"
                val raw = """ + "\"\"\"{ raw brace }\"\"\"" + """
                val character = '}'
                // { line-comment brace }
                /* outer { /* nested } */ block } */
                LiveRegionTextApplier.apply(binding.connectionTitle, ordinary + raw + character)
            }
            private fun next() {
                error("must not be included")
            }
            """.trimIndent()

        val extracted = extractMethod(source, "private fun target")

        assertTrue(extracted.contains("LiveRegionTextApplier.apply"))
        assertFalse(extracted.contains("private fun next"))
        assertFalse(extracted.contains("declaration decoy"))
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
        val callCount = countOccurrences(compactBlock, invocation)
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
        val declaration =
            Regex("(?m)^[\\t ]*" + Regex.escape(signature) + "(?=\\s|\\()")
                .find(source)
                ?: error("Method not found: $signature")
        val start = declaration.range.first
        var braceDepth = 0
        var methodStarted = false
        var lineComment = false
        var blockCommentDepth = 0
        var quotedCharacter: Char? = null
        var tripleQuotedString = false
        var escaped = false
        var i = start
        while (i < source.length) {
            val current = source[i]
            val next = source.getOrNull(i + 1)
            if (lineComment) {
                lineComment = current != '\n'
                i++
                continue
            }
            if (blockCommentDepth > 0) {
                when {
                    current == '/' && next == '*' -> {
                        blockCommentDepth++
                        i += 2
                    }
                    current == '*' && next == '/' -> {
                        blockCommentDepth--
                        i += 2
                    }
                    else -> i++
                }
                continue
            }
            if (tripleQuotedString) {
                if (source.startsWith("\"\"\"", i)) {
                    tripleQuotedString = false
                    i += 3
                } else {
                    i++
                }
                continue
            }
            val quote = quotedCharacter
            if (quote != null) {
                when {
                    escaped -> escaped = false
                    current == '\\' -> escaped = true
                    current == quote -> quotedCharacter = null
                }
                i++
                continue
            }
            when {
                current == '/' && next == '/' -> {
                    lineComment = true
                    i += 2
                }
                current == '/' && next == '*' -> {
                    blockCommentDepth = 1
                    i += 2
                }
                source.startsWith("\"\"\"", i) -> {
                    tripleQuotedString = true
                    i += 3
                }
                current == '"' || current == '\'' -> {
                    quotedCharacter = current
                    escaped = false
                    i++
                }
                current == '{' -> {
                    methodStarted = true
                    braceDepth++
                    i++
                }
                current == '}' -> {
                    braceDepth--
                    if (methodStarted && braceDepth == 0) return source.substring(start, i + 1)
                    i++
                }
                else -> i++
            }
        }
        error("Closing brace not found for $signature")
    }

    private fun countOccurrences(
        source: String,
        target: String,
    ): Int {
        require(target.isNotEmpty())
        var count = 0
        var offset = 0
        while (true) {
            val match = source.indexOf(target, offset)
            if (match < 0) return count
            count++
            offset = match + target.length
        }
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
