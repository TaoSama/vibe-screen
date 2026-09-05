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
            "Readiness should explain policy-disabled clipboard and file transfer separately from compatibility gaps",
            renderTransferReadiness.contains("clipboardPolicyAllowed = managedClipboardAllowed") &&
                renderTransferReadiness.contains("fileTransferPolicyAllowed = managedFileTransferAllowed"),
        )
        assertTrue(
            "Readiness should be presented by the pure policy",
            renderTransferReadiness.contains("TransferReadinessPresentationPolicy.presentation("),
        )
        assertTrue(
            "Readiness live-region updates should announce both status and the explanatory summary",
            renderTransferReadiness.contains("status.contentDescription =") &&
                renderTransferReadiness.contains("R.string.transfer_readiness_accessibility") &&
                renderTransferReadiness.contains("getString(presentation.statusResource)") &&
                renderTransferReadiness.contains("getString(presentation.summaryResource)"),
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
        val connectionStatusCallback = extractCallback(source, "callbackClient.onConnectionStatus = connectionStatus@")
        val updateInternetState = extractMethod(source, "private fun updateInternetState")
        val disconnectInternet = extractMethod(source, "private fun disconnectInternet")
        val quarantineInternetSession = extractMethod(source, "private fun quarantineInternetSession")
        val disconnectedSessionUi = extractMethod(source, "private fun applyDisconnectedSessionUi")

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
            assertBeforeValue(
                connectionStatusCallback,
                "productSessionCoordinator.onConnectionStatus(callbackClient, callbackGeneration, connected)",
                "refreshTransferReadinessInSettings()",
            ),
        )
        assertTrue(
            "Disconnected status commits should refresh through the disconnected UI path after state cleanup",
            connectionStatusCallback.contains("applyDisconnectedSessionUi()") &&
                assertBeforeValue(
                    disconnectedSessionUi,
                    "productSessionCoordinator.clearDisconnectedUiState()",
                    "refreshTransferReadinessInSettings()",
                ),
        )
        assertTrue(
            "Internet session state changes should refresh an already-open Settings dialog",
            updateInternetState.contains("LiveRegionTextApplier.apply(") &&
                updateInternetState.contains("refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "Terminal Internet states should reset stale remote policy before repainting transfer readiness",
            assertBeforeValue(updateInternetState, "refreshLocalManagedPolicySnapshot()", "refreshTransferReadinessInSettings()") &&
                assertBeforeValue(updateInternetState, "productSessionCoordinator.setTransportConnected(false)", "refreshLocalManagedPolicySnapshot()"),
        )
        assertTrue(
            "Manual Internet disconnect should reset stale remote policy before repainting transfer readiness",
            assertBeforeValue(disconnectInternet, "productSessionCoordinator.setTransportConnected(false)", "refreshLocalManagedPolicySnapshot()") &&
                assertBeforeValue(disconnectInternet, "refreshLocalManagedPolicySnapshot()", "refreshTransferReadinessInSettings()"),
        )
        assertTrue(
            "Quarantined Internet disconnect should reset stale remote policy before repainting transfer readiness",
            assertBeforeValue(quarantineInternetSession, "productSessionCoordinator.setTransportConnected(false)", "refreshLocalManagedPolicySnapshot()") &&
                assertBeforeValue(quarantineInternetSession, "refreshLocalManagedPolicySnapshot()", "refreshTransferReadinessInSettings()"),
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
        val status = extractXmlElement(layout, "android:id=\"@+id/transferReadinessStatus\"")
        assertTrue(status.contains("android:accessibilityLiveRegion=\"polite\""))
        assertBefore(layout, "@+id/deviceHealthSection", "@+id/transferReadinessSection")
        assertBefore(layout, "@+id/transferReadinessSection", "@+id/viewportSection")
        assertTrue(strings.contains("transfer_readiness_waiting_status"))
        assertTrue(strings.contains("Waiting for a compatible Mac session"))
        assertTrue(strings.contains("Clipboard and file controls require Protocol v1"))
        assertTrue(strings.contains("transfer_readiness_accessibility"))
        assertTrue(strings.contains("Clipboard &amp; files. %1\$s. %2\$s"))
        assertTrue(strings.contains("transfer_readiness_policy_blocked_status"))
        assertTrue(strings.contains("disabled by this device or Mac session policy"))
        assertFalse(
            "Readiness copy must not close the runtime E2E gate by calling the feature stable or accepted",
            Regex("transfer_readiness_[^>]+>(?:(?!</string>).)*(stable|accepted|E2E passed|verified end to end)", RegexOption.IGNORE_CASE)
                .containsMatchIn(strings),
        )
    }

    @Test
    fun localManagedPolicySnapshotFeedsNoHostTransferReadiness() {
        val source = mainActivitySource()
        val onCreate = extractMethod(source, "override fun onCreate")
        val applyLocalPolicy = extractMethod(source, "private fun applyLocalManagedPolicySnapshot")
        val refreshLocalPolicy = extractMethod(source, "private fun refreshLocalManagedPolicySnapshot")
        val disconnect = extractMethod(source, "private fun applyDisconnectedSessionUi")
        val streamManagedCallback = extractCallback(source, "callbackClient.onManagedPolicyReceived = managedPolicy@")
        val internetManagedCallback = extractCallback(source, "override fun onManagedPolicyReceived(status: ManagedPolicyStatus)")

        assertTrue(
            "The Activity should load local managed restrictions before first disconnected Settings render",
            onCreate.contains("refreshLocalManagedPolicySnapshot()") &&
                assertBeforeValue(onCreate, "refreshLocalManagedPolicySnapshot()", "setupUI()"),
        )
        assertTrue(
            "Local policy snapshots should retain clipboard and file-transfer denial state for no-host Settings",
            applyLocalPolicy.contains("localClipboardAllowed = policy.clipboardAllowed") &&
                applyLocalPolicy.contains("localFileTransferAllowed = policy.fileTransferAllowed") &&
                applyLocalPolicy.contains("managedClipboardAllowed = localClipboardAllowed") &&
                applyLocalPolicy.contains("managedFileTransferAllowed = localFileTransferAllowed"),
        )
        assertTrue(
            "Refreshing the local snapshot should read Android managed configuration through the existing provider",
            refreshLocalPolicy.contains("ManagedConfigurationProvider(applicationContext).loadPolicy()"),
        )
        assertTrue(
            "Disconnect should return to the latest local policy snapshot instead of showing false allowed state",
            disconnect.contains("refreshLocalManagedPolicySnapshot()") &&
                !disconnect.contains("managedClipboardAllowed = true") &&
                !disconnect.contains("managedFileTransferAllowed = true"),
        )
        assertTrue(
            "Stream managed-policy updates should propagate clipboard and file-transfer availability into Settings",
            streamManagedCallback.contains("localClipboardAllowed = localClipboardAllowed") &&
                streamManagedCallback.contains("localFileTransferAllowed = localFileTransferAllowed") &&
                streamManagedCallback.contains("managedClipboardAllowed = availability.clipboardAllowed") &&
                streamManagedCallback.contains("managedFileTransferAllowed = availability.fileTransferAllowed"),
        )
        assertTrue(
            "Internet managed-policy updates should use the same Settings availability source",
            internetManagedCallback.contains("localClipboardAllowed = localClipboardAllowed") &&
                internetManagedCallback.contains("localFileTransferAllowed = localFileTransferAllowed") &&
                internetManagedCallback.contains("managedClipboardAllowed = availability.clipboardAllowed") &&
                internetManagedCallback.contains("managedFileTransferAllowed = availability.fileTransferAllowed"),
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

    private fun extractCallback(
        source: String,
        startMarker: String,
    ): String {
        val start = source.indexOf(startMarker)
        require(start >= 0) { "Callback not found: $startMarker" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Callback body not found: $startMarker" }
        return extractBraceBlock(source, start, bodyStart, startMarker)
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

    private fun assertBeforeValue(
        source: String,
        first: String,
        second: String,
    ): Boolean {
        val firstIndex = source.indexOf(first)
        val secondIndex = source.indexOf(second)
        return firstIndex >= 0 && secondIndex >= 0 && firstIndex < secondIndex
    }

    private fun extractXmlElement(
        source: String,
        idAttribute: String,
    ): String {
        val idIndex = source.indexOf(idAttribute)
        require(idIndex >= 0) { "XML element not found: $idAttribute" }
        val openStart = source.lastIndexOf('<', idIndex)
        require(openStart >= 0) { "XML element start not found: $idAttribute" }
        val elementName =
            source.substring(openStart + 1)
                .takeWhile { !it.isWhitespace() && it != '>' }
        val selfClosingEnd = source.indexOf("/>", idIndex)
        val closeMarker = "</$elementName>"
        val closeEnd = source.indexOf(closeMarker, idIndex)
        val openTagEnd = source.indexOf('>', idIndex)
        require(openTagEnd >= 0) { "XML element open tag end not found: $idAttribute" }
        if (selfClosingEnd >= 0 && selfClosingEnd <= openTagEnd) {
            return source.substring(openStart, selfClosingEnd + 2)
        }
        require(closeEnd >= 0) { "XML element end not found: $idAttribute" }
        return source.substring(openStart, closeEnd + closeMarker.length)
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
