package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityTransferReadinessContractTest {
    @Test
    fun settingsDialogBindsTransferReadinessWithoutTransferSideEffects() {
        val source = mainActivitySource()
        val showSettingsDialog = extractMethod(source, "private fun showSettingsDialog")
        val renderTransferReadiness = extractMethod(source, "private fun renderTransferReadiness")
        val refreshTransferReadiness = extractMethod(source, "private fun refreshTransferReadinessInSettings")

        assertTrue(
            "Settings should bind the transfer-readiness status view",
            showSettingsDialog.contains("R.id.transferReadinessStatus"),
        )
        assertTrue(
            "Settings should bind the transfer-readiness summary view",
            showSettingsDialog.contains("R.id.transferReadinessSummary"),
        )
        assertTrue(
            "Settings should render transfer readiness from the shared presentation policy",
            showSettingsDialog.contains("renderTransferReadiness("),
        )
        assertTrue(
            "Readiness should use existing coordinator render state instead of probing system services",
            renderTransferReadiness.contains("productSessionCoordinator.renderState()"),
        )
        assertTrue(
            "Open Settings refreshes should read the active dialog instead of keeping the opening snapshot",
            refreshTransferReadiness.contains("activeSettingsDialog ?: return"),
        )
        assertTrue(
            "Open Settings refreshes should rebind the status view",
            refreshTransferReadiness.contains("R.id.transferReadinessStatus"),
        )
        assertTrue(
            "Open Settings refreshes should rebind the summary view",
            refreshTransferReadiness.contains("R.id.transferReadinessSummary"),
        )
        assertTrue(
            "Open Settings refreshes should rerender through the same presentation path",
            refreshTransferReadiness.contains("renderTransferReadiness(status, summary)"),
        )
        assertTrue(
            "Readiness should include active Internet file-transfer capability without claiming clipboard support",
            renderTransferReadiness.contains("internetSession?.canTransferFiles == true"),
        )
        assertTrue(
            "Readiness should be presented by the pure policy",
            renderTransferReadiness.contains("TransferReadinessPresentationPolicy.presentation("),
        )
        assertFalse(
            "Opening Settings must not read Android ClipboardManager",
            renderTransferReadiness.contains("ClipboardManager") ||
                renderTransferReadiness.contains("primaryClip"),
        )
        assertFalse(
            "Opening Settings must not launch the Android file picker",
            renderTransferReadiness.contains("ACTION_OPEN_DOCUMENT") ||
                renderTransferReadiness.contains("startActivityForResult"),
        )
    }

    @Test
    fun openSettingsTransferReadinessRefreshesAfterTransferStateChanges() {
        val source = mainActivitySource()
        val refreshClipboardControl = extractMethod(source, "private fun refreshClipboardControl")
        val refreshFileTransferControl = extractMethod(source, "private fun refreshFileTransferControl")
        val applyNegotiatedSession = extractMethod(source, "private fun applyNegotiatedSession")
        val updateInternetState = extractMethod(source, "private fun updateInternetState")

        assertTrue(
            "Clipboard runtime availability changes should refresh an already-open Settings dialog",
            refreshClipboardControl.contains("clipboard = client.canSendClipboard") &&
                refreshClipboardControl.contains("refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "File-transfer runtime availability changes should refresh an already-open Settings dialog",
            refreshFileTransferControl.contains("fileTransfer = client.canTransferFiles") &&
                refreshFileTransferControl.contains("refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "Negotiated-session capability changes should refresh an already-open Settings dialog",
            applyNegotiatedSession.contains("productSessionCoordinator.updateNegotiatedSession") &&
                applyNegotiatedSession.contains("if (updated) refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "Managed-policy commits should refresh through negotiated-session and runtime-control paths",
            source.contains("callbackClient.onManagedPolicyReceived = managedPolicy@") &&
                source.contains("applyNegotiatedSession(") &&
                source.contains("fileTransfer = callbackClient.canTransferFiles") &&
                source.contains("refreshClipboardControl()"),
        )
        assertTrue(
            "Connection status commits should refresh after the coordinator state changes",
            source.contains(
                "productSessionCoordinator.onConnectionStatus(callbackClient, callbackGeneration, connected)" +
                    "\n                refreshTransferReadinessInSettings()",
            ),
        )
        assertTrue(
            "Internet session state changes should refresh an already-open Settings dialog",
            updateInternetState.contains("LiveRegionTextApplier.apply(") &&
                updateInternetState.contains("refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "Internet route changes should refresh through the shared Internet state renderer",
            source.contains("override fun onRouteSelected(route: PeerRoute)") &&
                source.contains("updateInternetState(sessionReference.get()?.state ?: InternetProductSessionState.CONNECTING)"),
        )
        assertTrue(
            "Attaching an Internet session should refresh an already-open Settings dialog",
            source.contains(
                "productSessionCoordinator.attachInternetSession(generation, created)" +
                    "\n            internetNetworkMonitor = monitor" +
                    "\n            internetSession = created" +
                    "\n            refreshTransferReadinessInSettings()",
            ),
        )
    }

    @Test
    fun settingsLayoutExposesCompactTransferReadinessCopy() {
        val layout = settingsLayoutSource()
        val strings = stringsSource()

        assertTrue(layout.contains("@+id/transferReadinessSection"))
        assertTrue(layout.contains("@+id/transferReadinessStatus"))
        assertTrue(layout.contains("@+id/transferReadinessSummary"))
        assertTrue(layout.contains("@string/transfer_readiness_title"))
        assertBefore(layout, "@+id/deviceHealthSection", "@+id/transferReadinessSection")
        assertBefore(layout, "@+id/transferReadinessSection", "@+id/viewportSection")
        assertTrue(strings.contains("transfer_readiness_waiting_status"))
        assertTrue(strings.contains("Waiting for a compatible Mac session"))
        assertTrue(strings.contains("Clipboard and file controls require Protocol v1"))
        assertFalse(
            "Readiness copy must not close the runtime E2E gate by calling the feature stable or accepted",
            Regex("transfer_readiness_[^>]+>(?:(?!</string>).)*(stable|accepted|E2E passed|verified end to end)", RegexOption.IGNORE_CASE)
                .containsMatchIn(strings),
        )
    }

    private fun mainActivitySource(): String = sourceFile(MAIN_ACTIVITY_PATHS).readText()

    private fun settingsLayoutSource(): String = sourceFile(SETTINGS_LAYOUT_PATHS).readText()

    private fun stringsSource(): String = sourceFile(STRINGS_PATHS).readText()

    private fun sourceFile(paths: List<String>): File {
        var current = File(requireNotNull(System.getProperty("user.dir"))).canonicalFile
        repeat(8) {
            paths
                .map(current::resolve)
                .firstOrNull(File::isFile)
                ?.let { return it }
            current = current.parentFile?.canonicalFile ?: current
        }
        error("Source file not found from " + System.getProperty("user.dir"))
    }

    private fun extractMethod(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Method not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Method body not found: $signature" }
        return extractBraceBlock(source, start, bodyStart, signature)
    }

    private fun extractBraceBlock(
        source: String,
        start: Int,
        bodyStart: Int,
        label: String,
    ): String {
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Closing brace not found: $label")
    }

    private fun assertBefore(
        source: String,
        first: String,
        second: String,
    ) {
        val firstIndex = source.indexOf(first)
        val secondIndex = source.indexOf(second)
        assertTrue("Missing first marker: $first", firstIndex >= 0)
        assertTrue("Missing second marker: $second", secondIndex >= 0)
        assertTrue("Expected '$first' before '$second'", firstIndex < secondIndex)
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val SETTINGS_LAYOUT_PATHS =
            listOf(
                "app/src/main/res/layout/dialog_settings.xml",
                "baseline/AndroidClient/app/src/main/res/layout/dialog_settings.xml",
            )
        val STRINGS_PATHS =
            listOf(
                "app/src/main/res/values/strings.xml",
                "baseline/AndroidClient/app/src/main/res/values/strings.xml",
            )
    }
}
