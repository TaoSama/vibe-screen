package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityClipboardSystemBoundaryContractTest {
    @Test
    fun clipboardMenuDoesNotReadAndroidClipboardBeforeExplicitSendAction() {
        val showMenu = extractMethod(mainActivitySource(), "private fun showClipboardMenu")

        assertTrue(
            "Clipboard menu should expose an explicit Send to Mac command",
            showMenu.contains("CLIPBOARD_MENU_SEND -> beginSendLocalClipboard(client, generation)"),
        )
        assertTrue(
            "Clipboard menu should expose an explicit Get from Mac command",
            showMenu.contains("CLIPBOARD_MENU_RECEIVE -> beginReceiveRemoteClipboard(client, generation)"),
        )
        assertFalse(
            "Opening the menu must not inspect Android ClipboardManager",
            showMenu.contains("ClipboardManager") ||
                showMenu.contains("primaryClip") ||
                showMenu.contains("setPrimaryClip"),
        )
    }

    @Test
    fun sendToMacReadsClipboardOnlyAfterCurrentSessionAndCapabilityChecks() {
        val send = extractMethod(mainActivitySource(), "private fun sendLocalClipboard")
        assertTrue(
            "Send path should read the Android system clipboard through ClipboardManager",
            send.contains("getSystemService(ClipboardManager::class.java)") &&
                send.contains(".primaryClip"),
        )
        assertBefore(send, "isCurrentSession(client, generation)", "getSystemService(ClipboardManager::class.java)")
        assertBefore(send, "client.canSendClipboard", "getSystemService(ClipboardManager::class.java)")
        assertTrue(
            "Send path should read only the first ClipData item raw text after user approval",
            send.contains("?.takeIf { it.itemCount > 0 }") &&
                send.contains("?.getItemAt(0)") &&
                send.contains("?.text") &&
                send.contains("?.toString()"),
        )
        assertFalse(
            "Send path must not coerce non-text ClipData into text for transfer",
            send.contains("coerceToText"),
        )
        assertBefore(send, "ClipboardMenuPolicy.canSend(text)", "client.offerClipboard(clipboardText)")
        assertBefore(send, "ClipboardMenuPolicy.isWithinSizeLimit", "client.offerClipboard(clipboardText)")
        assertTrue(
            "A failed protocol send must surface a user-visible failure",
            send.contains("showDedupedToast(if (sent) R.string.clipboard_sent_to_mac else R.string.clipboard_send_failed)"),
        )
    }

    @Test
    fun receiveFromMacWritesClipboardOnlyAfterApprovalStateConsumptionAndOverwriteConfirmation() {
        val directConfirmation = extractMethod(mainActivitySource(), "private fun showDirectClipboardConfirmation")
        val overwriteConfirmation = extractMethod(mainActivitySource(), "private fun showClipboardOverwriteConfirmation")
        val receiveCallback = extractCallback(mainActivitySource(), "callbackClient.onClipboardContentReceived = clipboardContent@")

        assertTrue(
            "Direct content should route through the shared overwrite confirmation dialog",
            directConfirmation.contains("showClipboardOverwriteConfirmation("),
        )
        assertBefore(
            overwriteConfirmation,
            "val approved = approvedContent()",
            "writeRemoteClipboard(approved)",
        )
        assertTrue(
            "Direct content must be discarded when the user cancels overwrite confirmation",
            directConfirmation.contains("productSessionCoordinator.discardDirectClipboardContent("),
        )
        assertBefore(
            receiveCallback,
            "productSessionCoordinator.consumeSolicitedClipboardContent",
            "showClipboardOverwriteConfirmation(",
        )
        assertTrue(
            "Unsolicited direct content must be staged instead of immediately written",
            receiveCallback.contains("productSessionCoordinator.stageDirectClipboardContent") &&
                receiveCallback.contains("return@runOnUiThread"),
        )
    }

    @Test
    fun getFromMacRequestsClipboardOnlyAfterCurrentSessionAndCapabilityChecks() {
        val receive = extractMethod(mainActivitySource(), "private fun receiveRemoteClipboard")

        assertBefore(receive, "isCurrentSession(client, generation)", "productSessionCoordinator.directClipboardContentForConfirmation")
        assertBefore(receive, "client.canSendClipboard", "productSessionCoordinator.directClipboardContentForConfirmation")
        assertBefore(receive, "isCurrentSession(client, generation)", "client.requestClipboard(offer.changeId)")
        assertBefore(receive, "client.canSendClipboard", "client.requestClipboard(offer.changeId)")
        assertTrue(
            "A failed remote clipboard request must surface a user-visible failure",
            receive.contains("showDedupedToast(R.string.clipboard_receive_failed)"),
        )
    }

    @Test
    fun writeRemoteClipboardIsTheOnlyAndroidClipboardWriteBoundary() {
        val source = mainActivitySource()
        val write = extractMethod(source, "private fun writeRemoteClipboard")

        assertTrue(
            "Remote content must be written through Android ClipboardManager.setPrimaryClip",
            write.contains("getSystemService(ClipboardManager::class.java).setPrimaryClip") &&
                write.contains("ClipData.newPlainText"),
        )
        assertTrue(
            "Clipboard write failures must remain visible to the user and diagnostics",
            write.contains("showDedupedToast(if (result.isSuccess) R.string.clipboard_copied_from_mac else R.string.clipboard_write_failed)") &&
                write.contains("clipboard write failed"),
        )
        assertTrue(
            "MainActivity should keep exactly one Android system clipboard write boundary",
            countOccurrences(source, "setPrimaryClip") == 1,
        )
    }

    @Test
    fun managedPolicyDenyAndNewSessionsClearClipboardApprovalState() {
        val source = mainActivitySource()
        val activateSession = extractMethod(source, "private fun activateSession")
        val managedPolicyCallback = extractCallback(source, "callbackClient.onManagedPolicyReceived = managedPolicy@")

        assertTrue(
            "New sessions must bind approval state to the exact StreamClient generation",
            activateSession.contains("productSessionCoordinator.activate(client)"),
        )
        assertTrue(
            "New sessions must reset stale clipboard controls before any negotiation callback can republish them",
            activateSession.contains("resetClipboardControlToDefault()"),
        )
        assertTrue(
            "Remote managed-policy clipboard deny must clear pending approvals",
            managedPolicyCallback.contains("if (!clipboard) {") &&
                managedPolicyCallback.contains("cancelClipboardRequestTimeout()") &&
                managedPolicyCallback.contains("productSessionCoordinator.clearClipboardWorkflow()"),
        )
    }

    @Test
    fun pendingClipboardReceiveOwnsVisibleStatusUntilUserAction() {
        val source = mainActivitySource()
        val refreshClipboard = extractMethod(source, "private fun refreshClipboardControl")
        val updateClipboardLabel = extractMethod(source, "private fun updateClipboardAccessibilityLabel")
        val refreshClipboardStatus = extractMethod(source, "private fun refreshClipboardStatusText")
        val refreshFileTransfer = extractMethod(source, "private fun refreshFileTransferControl")
        val overwriteConfirmation = extractMethod(source, "private fun showClipboardOverwriteConfirmation")
        val timeout = extractMethod(source, "private fun scheduleClipboardRequestTimeout")
        val disconnectedUi = extractMethod(source, "private fun applyDisconnectedSessionUi")
        val resetClipboard = extractMethod(source, "private fun resetClipboardControlToDefault")
        val clipboardOfferCallback = extractCallback(source, "callbackClient.onClipboardOffered = clipboardOffer@")
        val clipboardContentCallback = extractCallback(source, "callbackClient.onClipboardContentReceived = clipboardContent@")

        assertTrue(
            "Refreshing clipboard controls should reconcile the shared visible status row",
            refreshClipboard.contains("refreshClipboardStatusText(client, activeSessionGeneration)"),
        )
        assertTrue(
            "Pending clipboard state should use a pending button label plus matching tooltip",
            updateClipboardLabel.contains("productSessionCoordinator.hasPendingClipboardReceive(client, generation)") &&
                updateClipboardLabel.contains("R.string.control_clipboard_pending") &&
                updateClipboardLabel.contains("R.string.control_clipboard") &&
                updateClipboardLabel.contains("TooltipCompat.setTooltipText(") &&
                updateClipboardLabel.contains("binding.controlClipboardButton.contentDescription"),
        )
        assertTrue(
            "Pending clipboard state should use a short visible row and a full accessibility instruction",
            refreshClipboardStatus.contains("activeIncomingFileTransfer != null || activeOutgoingFileTransfer != null") &&
                refreshClipboardStatus.contains("productSessionCoordinator.hasPendingClipboardReceive(client, generation)") &&
                refreshClipboardStatus.contains("R.string.clipboard_pending_status") &&
                refreshClipboardStatus.contains("R.string.clipboard_pending_from_mac") &&
                refreshClipboardStatus.contains("binding.controlFileTransferProgressText.visibility = if (pending) View.VISIBLE else View.GONE"),
        )
        assertTrue(
            "Remote clipboard offers should announce the actionable pending state after the button label is refreshed",
            clipboardOfferCallback.contains("productSessionCoordinator.stageClipboardOffer") &&
                clipboardOfferCallback.contains("R.string.clipboard_pending_from_mac"),
        )
        assertBefore(
            clipboardOfferCallback,
            "refreshClipboardControl()",
            "binding.controlClipboardButton.announceForAccessibility(",
        )
        assertTrue(
            "Direct clipboard content should announce the approval-required pending state after the button label is refreshed",
            clipboardContentCallback.contains("productSessionCoordinator.stageDirectClipboardContent") &&
                clipboardContentCallback.contains("R.string.clipboard_pending_confirmation"),
        )
        assertBefore(
            clipboardContentCallback,
            "refreshClipboardControl()",
            "binding.controlClipboardButton.announceForAccessibility(",
        )
        assertTrue(
            "Active file-transfer progress must retain precedence over clipboard status text",
            refreshFileTransfer.contains("if (activeTransferVisible)") &&
                refreshFileTransfer.contains("binding.controlFileTransferProgressText.text = progressLabel ?: \"\"") &&
                refreshFileTransfer.contains("refreshClipboardStatusText(client, activeSessionGeneration)"),
        )
        assertTrue(
            "Clipboard approve/cancel paths must clear the pending status row through full control refresh",
            overwriteConfirmation.contains("if (approved != null) writeRemoteClipboard(approved)") &&
                overwriteConfirmation.contains("refreshClipboardControl()") &&
                !overwriteConfirmation.contains("updateClipboardAccessibilityLabel(client, generation)"),
        )
        assertTrue(
            "Clipboard request timeout should clear approval state, refresh the row, and show a dedicated timeout toast",
            timeout.contains("CLIPBOARD_REQUEST_TIMEOUT_MS") &&
                timeout.contains("productSessionCoordinator.cancelClipboardOfferApproval(client, generation, exactChangeId)") &&
                timeout.contains("refreshClipboardControl()") &&
                timeout.contains("R.string.clipboard_request_timed_out"),
        )
        assertTrue(
            "Clipboard request timeout must surface the same timeout toast even when the expiry command cannot be submitted",
            timeout.contains("if (!submitted && productSessionCoordinator.cancelClipboardOfferApproval(client, generation, exactChangeId))") &&
                timeout.contains("showDedupedToast(R.string.clipboard_request_timed_out)"),
        )
        assertTrue(
            "Disconnected UI must fail closed by cancelling timers, clearing clipboard workflow, hiding the button, and restoring its default label",
            disconnectedUi.contains("resetClipboardControlToDefault()") &&
                resetClipboard.contains("cancelClipboardRequestTimeout()") &&
                resetClipboard.contains("productSessionCoordinator.clearClipboardWorkflow()") &&
                resetClipboard.contains("binding.controlClipboardButton.visibility = View.GONE") &&
                resetClipboard.contains("binding.controlClipboardButton.isEnabled = false") &&
                resetClipboard.contains("binding.controlClipboardButton.contentDescription = getString(R.string.control_clipboard)") &&
                resetClipboard.contains("TooltipCompat.setTooltipText(binding.controlClipboardButton, getText(R.string.control_clipboard))"),
        )
        assertTrue(
            "Disconnected UI must hide the shared transfer/clipboard status row so pending clipboard text cannot leak",
            disconnectedUi.contains("binding.controlFileTransferProgressText.visibility = View.GONE") &&
                disconnectedUi.contains("binding.controlFileTransferProgressText.text = \"\"") &&
                disconnectedUi.contains("binding.controlFileTransferProgressText.contentDescription = \"\""),
        )
    }

    @Test
    fun noHostClipboardControlSurfaceRefreshDoesNotTouchAndroidClipboardBoundary() {
        val source = mainActivitySource()
        val refreshClipboard = extractMethod(source, "private fun refreshClipboardControl")
        val updateClipboardLabel = extractMethod(source, "private fun updateClipboardAccessibilityLabel")
        val refreshClipboardStatus = extractMethod(source, "private fun refreshClipboardStatusText")
        val resetClipboard = extractMethod(source, "private fun resetClipboardControlToDefault")
        val disconnectedUi = extractMethod(source, "private fun applyDisconnectedSessionUi")

        val noHostControlSurfaceRefresh =
            listOf(
                refreshClipboard,
                updateClipboardLabel,
                refreshClipboardStatus,
                resetClipboard,
                disconnectedUi,
            ).joinToString("\n")

        assertFalse(
            "No-Host clipboard/control-surface refresh must not read or write Android ClipboardManager",
            noHostControlSurfaceRefresh.contains("ClipboardManager") ||
                noHostControlSurfaceRefresh.contains("primaryClip") ||
                noHostControlSurfaceRefresh.contains("setPrimaryClip") ||
                noHostControlSurfaceRefresh.contains("ClipData.newPlainText"),
        )
        assertTrue(
            "Clipboard system read remains isolated to the explicit Send to Mac path",
            extractMethod(source, "private fun sendLocalClipboard").contains("getSystemService(ClipboardManager::class.java)") &&
                extractMethod(source, "private fun sendLocalClipboard").contains(".primaryClip"),
        )
        assertTrue(
            "Clipboard system write remains isolated to the explicit approved receive path",
            extractMethod(source, "private fun writeRemoteClipboard").contains("setPrimaryClip"),
        )
    }

    @Test
    fun clipboardConfirmationDialogsApplyReadableActionButtonLayout() {
        val source = mainActivitySource()
        val send = extractMethod(source, "private fun beginSendLocalClipboard")
        val receive = extractMethod(source, "private fun beginReceiveRemoteClipboard")
        val overwrite = extractMethod(source, "private fun showClipboardOverwriteConfirmation")

        assertTrue(
            "LAN send clipboard dialog applies DialogActionButtonLayoutApplier",
            send.contains("showImmersiveDialog(") &&
                send.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
        assertTrue(
            "LAN receive clipboard dialog applies DialogActionButtonLayoutApplier",
            receive.contains("showImmersiveDialog(") &&
                receive.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
        assertTrue(
            "Direct overwrite clipboard dialog applies DialogActionButtonLayoutApplier",
            overwrite.contains("showImmersiveDialog(") &&
                overwrite.contains(".also(DialogActionButtonLayoutApplier::apply)"),
        )
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

    private fun extractCallback(
        source: String,
        marker: String,
    ): String {
        val start = source.indexOf(marker)
        require(start >= 0) { "Callback not found: $marker" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Callback body not found: $marker" }
        return extractBraceBlock(source, start, bodyStart, marker)
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

    private fun countOccurrences(
        source: String,
        target: String,
    ): Int {
        require(target.isNotEmpty())
        var count = 0
        var offset = 0
        while (true) {
            val index = source.indexOf(target, offset)
            if (index < 0) return count
            count++
            offset = index + target.length
        }
    }

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
    }
}
