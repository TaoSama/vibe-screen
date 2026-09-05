package dev.telemachus.display

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityFileTransferSystemBoundaryContractTest {
    @Test
    fun incomingFileTransferExposesProgressAndUserCancelThroughProductState() {
        val source = mainActivitySource()
        val strings = stringsSource()
        val begin = extractMethod(source, "private fun beginIncomingFileTransferState")
        val progress = extractMethod(source, "private fun updateIncomingFileTransferProgress")
        val refreshControl = extractMethod(source, "private fun refreshFileTransferControl")
        val clickHandler = extractMethod(source, "private fun handleFileTransferControlClick")
        val cancel = extractMethod(source, "private fun cancelIncomingFileTransfer")
        val finish = extractMethod(source, "private fun finishIncomingFileTransferState")
        val cleanup = extractMethod(source, "private fun clearActiveIncomingFileTransfer")
        val handlePicker = extractMethod(source, "private fun handleFileTransferPickerResult")
        val promptOffer = extractMethod(source, "private fun promptIncomingFileOffer(\n        offer: dev.vibescreen.protocol.v1.FileOffer")
        val callback = extractCallback(source, "callbackClient.onIncomingFileProgress = fileProgress@")
        val cancelledCallback = extractCallback(source, "callbackClient.onIncomingFileCancelled = fileCancelled@")
        val completedCallback = extractCallback(source, "callbackClient.onIncomingFileCompleted = incomingFile@")
        val internetProgress = extractCallback(source, "override fun onIncomingFileProgress(")
        val internetCancelled = extractCallback(source, "override fun onIncomingFileCancelled(")
        val internetCompleted = extractCallback(source, "override fun onIncomingFileCompleted(")
        val acceptDecision = extractCallback(source, ".setPositiveButton(R.string.file_transfer_accept)")

        assertTrue(
            "Accepting an incoming offer should register active receive state after the protocol response is admitted",
            source.contains("""if (respond(true, ""))""") && source.contains("beginTransfer()"),
        )
        assertTrue(
            "Incoming offer acceptance must re-check session validity and transfer mutual exclusion before starting the receive",
            acceptDecision.contains("val rejectionReason =") &&
                acceptDecision.contains("!isCurrentAndAllowed() -> \"user_denied\"") &&
                acceptDecision.contains("hasActiveFileTransfer() -> \"concurrent_limit\"") &&
                acceptDecision.contains("if (rejectionReason != null)") &&
                acceptDecision.contains("respond(false, rejectionReason)") &&
                acceptDecision.contains("return@setPositiveButton") &&
                acceptDecision.contains("""if (respond(true, ""))""") &&
                assertBeforeValue(acceptDecision, "val rejectionReason =", "if (!finishDecision()) return@setPositiveButton") &&
                assertBeforeValue(acceptDecision, "if (rejectionReason != null)", """if (respond(true, ""))"""),
        )
        assertTrue(
            "Active receive state should retain transfer id, display name, byte length, and cancel command",
            begin.contains("ActiveIncomingFileTransfer(transferId, displayName, byteLength, cancel)"),
        )
        assertTrue(
            "Accepted incoming transfers should use the non-modal control bar, not a blocking receive dialog",
            begin.contains("revealControlBar(ControlBarAccessibilityPolicy.RevealReason.ACTIVE_TRANSFER)") &&
                begin.contains("refreshFileTransferControl()") &&
                !source.contains("showIncomingFileProgressDialog") &&
                !source.contains("updateIncomingFileProgressMessage") &&
                !source.contains("cancelIncomingFileTransferFromDialog") &&
                !strings.contains("file_transfer_receiving_title") &&
                !strings.contains("file_transfer_receiving_message"),
        )
        assertTrue(
            "Incoming progress callback should update the active receive control only on the current session",
            callback.contains("updateIncomingFileTransferProgress(transferId, receivedBytes)"),
        )
        assertTrue(
            "Incoming Internet progress callback should share the same active receive control",
            internetProgress.contains("updateIncomingFileTransferProgress(transferId, receivedBytes)"),
        )
        assertTrue(
            "Progress updates must be transfer-id scoped",
            progress.contains("if (active.transferId != transferId) return") &&
                progress.contains("val previousLabel = incomingFileProgressLabel(active)") &&
                progress.contains("activeIncomingFileTransfer = updated") &&
                progress.contains("if (incomingFileProgressLabel(updated) != previousLabel) refreshFileTransferControl()"),
        )
        assertTrue(
            "The shared file-transfer button should cancel an active incoming receive before opening the picker",
            clickHandler.contains("val activeIncoming = activeIncomingFileTransfer") &&
                clickHandler.contains("cancelIncomingFileTransfer(activeIncoming.transferId)") &&
                assertBeforeValue(clickHandler, "cancelIncomingFileTransfer(activeIncoming.transferId)", "beginChooseFileForTransfer()"),
        )
        assertTrue(
            "The control bar should render incoming receive progress through the same text and cancel affordance as outgoing sends",
            refreshControl.contains("val activeIncoming = activeIncomingFileTransfer") &&
                refreshControl.contains("val transferAvailable = state.fileTransferVisible || internetFileTransfer") &&
                refreshControl.contains("if (!transferAvailable)") &&
                assertBeforeValue(refreshControl, "if (!transferAvailable)", "val activeIncoming = activeIncomingFileTransfer") &&
                refreshControl.contains("val activeTransferVisible = activeIncoming != null || activeOutgoing != null") &&
                refreshControl.contains("val fileTransferControlVisible = transferAvailable || activeTransferVisible") &&
                refreshControl.contains("activeIncoming?.let(::incomingFileProgressLabel) ?: activeOutgoing?.let(::outgoingFileProgressLabel)") &&
                refreshControl.contains("val cancelling = activeIncoming?.cancelling ?: activeOutgoing?.cancelling ?: false") &&
                refreshControl.contains("R.drawable.ic_cancel_transfer") &&
                refreshControl.contains("if (activeTransferVisible)") &&
                refreshControl.contains("binding.controlFileTransferProgressText.visibility = View.VISIBLE") &&
                refreshControl.contains("refreshClipboardStatusText(client, activeSessionGeneration)"),
        )
        assertTrue(
            "Internet file-transfer capability loss must clear active receive state before rendering active-transfer controls",
            refreshControl.contains("if (prefs.connectionMode == ConnectionMode.INTERNET && !internetFileTransfer)") &&
                refreshControl.contains("rejectPendingIncomingFileOffer()") &&
                refreshControl.contains("clearActiveIncomingFileTransfer(refreshControl = false)") &&
                assertBeforeValue(refreshControl, "if (prefs.connectionMode == ConnectionMode.INTERNET && !internetFileTransfer)", "val activeIncoming = activeIncomingFileTransfer"),
        )
        assertTrue(
            "Incoming/outgoing transfers should be mutually exclusive at both approval and staging boundaries",
            promptOffer.contains("if (hasActiveFileTransfer())") &&
                promptOffer.contains("respond(false, \"concurrent_limit\")") &&
                promptOffer.contains("val rejectionReason =") &&
                promptOffer.contains("hasActiveFileTransfer() -> \"concurrent_limit\"") &&
                promptOffer.contains("if (rejectionReason != null)") &&
                assertBeforeValue(promptOffer, "if (rejectionReason != null)", "respond(true, \"\")") &&
                handlePicker.contains("session.isCurrentAndAllowed() && !hasActiveFileTransfer()"),
        )
        assertTrue(
            "User cancellation must call the active transfer cancellation boundary",
            cancel.contains("active.cancel(transferId)"),
        )
        assertTrue(
            "User cancellation should keep incoming UI in cancelling state until a matching callback closes it",
            cancel.contains("if (active.cancelling) return") &&
                cancel.contains("activeIncomingFileTransfer = active.copy(cancelling = true)") &&
                !cancel.contains("activeIncomingFileTransfer = null"),
        )
        assertTrue(
            "If the incoming cancel command cannot be submitted, the UI should not claim it was cancelled",
            cancel.contains("if (cancelled)") &&
                cancel.contains("} else {") &&
                cancel.contains("showDedupedToast(R.string.file_transfer_cancel_failed)"),
        )
        assertTrue(
            "Incoming cancellation should clear only the matching active receive state and restart ordinary control-bar timing",
            cancelledCallback.contains("if (finishIncomingFileTransferState(transferId)) revealControlBar()") &&
                internetCancelled.contains("if (finishIncomingFileTransferState(transferId)) revealControlBar()"),
        )
        assertTrue(
            "Incoming completion should clear only the matching active receive state and restart ordinary control-bar timing",
            completedCallback.contains("if (finishIncomingFileTransferState(completed.transferId)) revealControlBar()") &&
                internetCompleted.contains("if (finishIncomingFileTransferState(completed.transferId)) revealControlBar()"),
        )
        assertTrue(
            "Incoming finish should clear receive state through the shared cleanup path",
            finish.contains("activeIncomingFileTransfer?.transferId != transferId") &&
                finish.contains("return false") &&
                finish.contains("clearActiveIncomingFileTransfer(refreshControl = true)") &&
                finish.contains("return true"),
        )
        assertTrue(
            "Shared incoming cleanup should clear the active receive state and refresh only when requested",
            cleanup.contains("activeIncomingFileTransfer = null") &&
                cleanup.contains("if (refreshControl) refreshFileTransferControl()"),
        )
    }

    @Test
    fun outgoingFileTransferExposesProgressAndUserCancelThroughProductState() {
        val source = mainActivitySource()
        val handlePicker = extractMethod(source, "private fun handleFileTransferPickerResult")
        val refreshControl = extractMethod(source, "private fun refreshFileTransferControl")
        val clickHandler = extractMethod(source, "private fun handleFileTransferControlClick")
        val begin = extractMethod(source, "private fun beginOutgoingFileTransferState")
        val progress = extractMethod(source, "private fun updateOutgoingFileTransferProgress")
        val finish = extractMethod(source, "private fun finishOutgoingFileTransferState")
        val cancel = extractMethod(source, "private fun cancelOutgoingFileTransfer")
        val discard = extractMethod(source, "private fun discardPendingOutgoingFileTransfer")
        val failureMessage = extractMethod(source, "private fun fileTransferFailureMessageId")
        val callback = extractCallback(source, "callbackClient.onOutgoingFileProgress = outgoingProgress@")
        val finishedCallback = extractCallback(source, "callbackClient.onOutgoingFileFinished = outgoingFinished@")
        val resultCallback = extractCallback(source, "callbackClient.onFileTransferResult = fileResult@")
        val internetProgress = extractCallback(source, "override fun onOutgoingFileProgress(")
        val internetFinished = extractCallback(source, "override fun onOutgoingFileFinished(transferId: ByteString)")
        val internetResult = extractCallback(source, "override fun onFileTransferResult(")

        assertTrue(
            "Starting an outgoing offer should register active sending state from the returned transfer handle",
            handlePicker.contains("val outgoingValue =") &&
                handlePicker.contains("beginOutgoingFileTransferState(") &&
                handlePicker.contains("transferId = outgoingValue.transferId"),
        )
        assertTrue(
            "Picker completion must not show a dialog after the Activity is destroyed",
            handlePicker.contains("if (isFinishing || isDestroyed || !session.isCurrent()) return@withContext"),
        )
        assertTrue(
            "Started toast should only show when the outgoing progress state is actually displayed",
            handlePicker.contains("val started =") &&
                handlePicker.contains("if (started)") &&
                handlePicker.contains("showDedupedToast(R.string.file_transfer_sent_to_mac)"),
        )
        assertTrue(
            "A finished-before-begin transfer should still clean up staged outgoing files",
            handlePicker.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false, refreshControl = true)"),
        )
        assertTrue(
            "Active send state should retain transfer id, display name, byte length, and cancel command",
            begin.contains("ActiveOutgoingFileTransfer(transferId, displayName, byteLength, cancel)"),
        )
        assertTrue(
            "Outgoing progress should stay on the non-modal control bar so the cancel action remains reachable",
            begin.contains("revealControlBar(ControlBarAccessibilityPolicy.RevealReason.ACTIVE_TRANSFER)") &&
                !source.contains("showOutgoingFileProgressDialog") &&
                !source.contains("pendingOutgoingFileDialog"),
        )
        assertTrue(
            "The file-transfer button should switch between picker and cancellation behavior",
            source.contains("binding.controlFileTransferButton.setOnClickListener") &&
                source.contains("handleFileTransferControlClick()") &&
                clickHandler.contains("if (activeOutgoing == null)") &&
                clickHandler.contains("beginChooseFileForTransfer()") &&
                clickHandler.contains("cancelOutgoingFileTransfer(activeOutgoing.transferId)"),
        )
        assertTrue(
            "The control bar should show progress text and expose cancellation state to accessibility",
            refreshControl.contains("R.string.control_file_transfer_cancel_with_progress") &&
                refreshControl.contains("R.string.control_file_transfer_cancelling_with_progress") &&
                refreshControl.contains("val cancelling = activeIncoming?.cancelling ?: activeOutgoing?.cancelling ?: false") &&
                refreshControl.contains("R.drawable.ic_cancel_transfer") &&
                refreshControl.contains("R.color.danger") &&
                refreshControl.contains("if (activeTransferVisible)") &&
                refreshControl.contains("binding.controlFileTransferProgressText.visibility = View.VISIBLE") &&
                refreshControl.contains("refreshClipboardStatusText(client, activeSessionGeneration)") &&
                refreshControl.contains("binding.controlFileTransferProgressText.contentDescription = progressLabel ?: \"\""),
        )
        assertTrue(
            "A finish callback that arrives before UI state begins must suppress the late outgoing dialog, and incoming receives must reject late outgoing offers",
            begin.contains("if (hasOutgoingFileTransferAlreadyFinished(transferId)) return false") &&
                begin.contains("if (activeIncomingFileTransfer != null) {") &&
                begin.contains("cancel(transferId)") &&
                begin.contains("return false") &&
                finish.contains("transferId?.let(::markOutgoingFileTransferFinished)") &&
                source.contains("private fun hasOutgoingFileTransferAlreadyFinished(transferId: ByteString): Boolean"),
        )
        assertTrue(
            "Outgoing progress callback should update the active send dialog only on the current stream session",
            callback.contains("updateOutgoingFileTransferProgress(transferId, acknowledgedBytes, totalBytes)"),
        )
        assertTrue(
            "Outgoing Internet progress callback should share the same active send dialog",
            internetProgress.contains("updateOutgoingFileTransferProgress(transferId, acknowledgedBytes, totalBytes)"),
        )
        assertTrue(
            "Outgoing progress updates must be transfer-id scoped",
            progress.contains("if (active.transferId != transferId) return"),
        )
        assertTrue(
            "Progress should update layout only when the visible label changes",
            progress.contains("val previousLabel = outgoingFileProgressLabel(active)") &&
                progress.contains("activeOutgoingFileTransfer = updated") &&
                progress.contains("if (outgoingFileProgressLabel(updated) != previousLabel) refreshFileTransferControl()"),
        )
        assertTrue(
            "User cancellation must call the active outgoing transfer cancellation boundary",
            cancel.contains("active.cancel(transferId)"),
        )
        assertTrue(
            "User cancellation should keep active UI in cancelling state until a matching finished callback closes it",
            cancel.contains("if (active.cancelling) return") &&
                cancel.contains("activeOutgoingFileTransfer = active.copy(cancelling = true)") &&
                !cancel.contains("activeOutgoingFileTransfer = null") &&
                !cancel.contains("discardPendingOutgoingFileTransfer(refreshControl = true)"),
        )
        assertTrue(
            "User cancellation success should map to cancelled copy, not generic failure",
            failureMessage.contains("\"user_cancelled\"") &&
                failureMessage.contains("R.string.file_transfer_failed_cancelled"),
        )
        assertTrue(
            "If the cancel command cannot be submitted, the UI should not claim it was cancelled",
            cancel.contains("if (cancelled)") &&
                cancel.contains("} else {") &&
                cancel.contains("showDedupedToast(R.string.file_transfer_cancel_failed)"),
        )
        assertTrue(
            "Outgoing completion should clear only the matching active send state",
            finishedCallback.contains("finishOutgoingFileTransferState(transferId)") &&
                finishedCallback.contains("val finishingActiveTransfer = activeOutgoingFileTransfer?.transferId == transferId") &&
                finishedCallback.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false, clearActiveTransfer = false)") &&
                finishedCallback.contains("refreshFileTransferControl()") &&
                finishedCallback.contains("revealControlBar()") &&
                internetFinished.contains("finishOutgoingFileTransferState(transferId)") &&
                internetFinished.contains("val finishingActiveTransfer = activeOutgoingFileTransfer?.transferId == transferId") &&
                internetFinished.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false, clearActiveTransfer = false)") &&
                internetFinished.contains("refreshFileTransferControl()") &&
                internetFinished.contains("revealControlBar()") &&
                finish.contains("activeOutgoingFileTransfer?.transferId == transferId"),
        )
        assertTrue(
            "Generic outgoing cleanup should dismiss active send state and delete staged files",
            discard.contains("finishOutgoingFileTransferState(null)") &&
                discard.contains("clearActiveTransfer: Boolean = true") &&
                discard.contains("if (clearActiveTransfer) finishOutgoingFileTransferState(null)") &&
                discard.contains("if (clearFinishedTransferMarkers) recentlyFinishedOutgoingTransferIds.clear()") &&
                discard.contains("takePendingOutgoingFileTransfer()") &&
                discard.contains("if (refreshControl) refreshFileTransferControl()"),
        )
        assertTrue(
            "Picker cleanup should explicitly refresh the non-modal transfer control after cleanup",
            handlePicker.contains("discardPendingOutgoingFileTransfer(refreshControl = true)") &&
                handlePicker.contains("discardPendingOutgoingFileTransfer(clearFinishedTransferMarkers = false, refreshControl = true)"),
        )
        assertTrue(
            "File-transfer result callbacks have no transfer id and must not clear active send UI",
            !resultCallback.contains("discardPendingOutgoingFileTransfer") &&
                !internetResult.contains("discardPendingOutgoingFileTransfer") &&
                resultCallback.contains("refreshFileTransferControl()") &&
                internetResult.contains("refreshFileTransferControl()"),
        )
    }

    @Test
    fun disconnectedSessionUiHidesFileTransferControlsFailClosed() {
        val source = mainActivitySource()
        val activateSession = extractMethod(source, "private fun activateSession")
        val showDisconnected = extractMethod(source, "private fun showDisconnectedStreamUi")
        val disconnectedUi = extractMethod(source, "private fun applyDisconnectedSessionUi")
        val connectionStatus = extractCallback(source, "callbackClient.onConnectionStatus = connectionStatus@")
        val managedPolicy = extractCallback(source, "callbackClient.onManagedPolicyReceived = managedPolicy@")
        val updateInternetState = extractMethod(source, "private fun updateInternetState")
        val disconnectInternet = extractMethod(source, "private fun disconnectInternet")
        val quarantineInternetSession = extractMethod(source, "private fun quarantineInternetSession")

        assertTrue(
            "Session activation and disconnected stream UI must reject pending incoming offers with outgoing and active receive cleanup",
            activateSession.contains("rejectPendingIncomingFileOffer()") &&
                activateSession.contains("discardPendingOutgoingFileTransfer()") &&
                activateSession.contains("clearActiveIncomingFileTransfer()") &&
                showDisconnected.contains("rejectPendingIncomingFileOffer()") &&
                showDisconnected.contains("discardPendingOutgoingFileTransfer()") &&
                showDisconnected.contains("clearActiveIncomingFileTransfer()") &&
                disconnectedUi.contains("rejectPendingIncomingFileOffer()") &&
                disconnectedUi.contains("discardPendingOutgoingFileTransfer()") &&
                disconnectedUi.contains("clearActiveIncomingFileTransfer()"),
        )
        assertTrue(
            "Disconnected UI must hide and disable the file-transfer action, not rely only on the parent bar",
            disconnectedUi.contains("binding.controlFileTransferButton.visibility = View.GONE") &&
                disconnectedUi.contains("binding.controlFileTransferButton.isEnabled = false"),
        )
        assertTrue(
            "Disconnected UI must restore the neutral file-transfer accessibility label and tooltip",
            disconnectedUi.contains("binding.controlFileTransferButton.contentDescription = getString(R.string.control_file_transfer)") &&
                disconnectedUi.contains("TooltipCompat.setTooltipText(binding.controlFileTransferButton, getText(R.string.control_file_transfer))"),
        )
        assertTrue(
            "Disconnected UI must restore the neutral file-transfer icon and color",
            disconnectedUi.contains("binding.controlFileTransferButton.setImageResource(R.drawable.ic_file_transfer)") &&
                disconnectedUi.contains("binding.controlFileTransferButton.setColorFilter(ContextCompat.getColor(this, R.color.on_surface))"),
        )
        assertTrue(
            "Disconnected UI must clear progress text so a prior transfer cannot leak into a later disconnected screen",
            disconnectedUi.contains("binding.controlFileTransferProgressText.visibility = View.GONE") &&
                disconnectedUi.contains("binding.controlFileTransferProgressText.text = \"\"") &&
                disconnectedUi.contains("binding.controlFileTransferProgressText.contentDescription = \"\""),
        )
        assertTrue(
            "Transport disconnect and Internet terminal states must also clear a still-pending incoming offer dialog",
                connectionStatus.contains("if (!connected)") &&
                connectionStatus.contains("rejectPendingIncomingFileOffer()") &&
                managedPolicy.contains("if (!callbackClient.canTransferFiles)") &&
                managedPolicy.contains("rejectPendingIncomingFileOffer()") &&
                managedPolicy.contains("discardPendingOutgoingFileTransfer()") &&
                assertBeforeValue(managedPolicy, "if (!callbackClient.canTransferFiles)", "discardPendingOutgoingFileTransfer()") &&
                assertBeforeValue(managedPolicy, "if (!callbackClient.canTransferFiles)", "refreshFileTransferControl()") &&
                updateInternetState.contains("state == InternetProductSessionState.CLOSED || state == InternetProductSessionState.FAILED") &&
                updateInternetState.contains("rejectPendingIncomingFileOffer()") &&
                disconnectInternet.contains("rejectPendingIncomingFileOffer()") &&
                quarantineInternetSession.contains("rejectPendingIncomingFileOffer()"),
        )
        assertTrue(
            "Internet closed or failed state must clear active receive UI with outgoing cleanup",
            updateInternetState.contains("state == InternetProductSessionState.CLOSED || state == InternetProductSessionState.FAILED") &&
                updateInternetState.contains("rejectPendingIncomingFileOffer()") &&
                updateInternetState.contains("discardPendingOutgoingFileTransfer()") &&
                updateInternetState.contains("clearActiveIncomingFileTransfer()"),
        )
        assertTrue(
            "Explicit Internet disconnect must clear active receive UI with outgoing cleanup",
            disconnectInternet.contains("rejectPendingIncomingFileOffer()") &&
                disconnectInternet.contains("discardPendingOutgoingFileTransfer()") &&
                disconnectInternet.contains("clearActiveIncomingFileTransfer()"),
        )
        assertTrue(
            "Internet quarantine must clear active receive UI with outgoing cleanup",
            quarantineInternetSession.contains("rejectPendingIncomingFileOffer()") &&
                quarantineInternetSession.contains("discardPendingOutgoingFileTransfer()") &&
                quarantineInternetSession.contains("clearActiveIncomingFileTransfer()"),
        )
    }

    @Test
    fun internetFileTransferBlocksOutgoingWhileIncomingOfferIsPending() {
        val source = mainActivitySource()
        val internetSession = extractMethod(source, "private fun activeInternetFileTransferSession")
        val internetOffer = extractCallback(source, "override fun onFileOffer(offer: dev.vibescreen.protocol.v1.FileOffer)")

        assertTrue(
            "Internet outgoing selection should be unavailable while an incoming offer dialog is pending",
            internetSession.contains("pendingIncomingFileDialog == null") &&
                internetSession.contains("if (generation <= 0L || session.state != InternetProductSessionState.ACTIVE || !isCurrentAndAllowed())") &&
                assertBeforeValue(internetSession, "pendingIncomingFileDialog == null", "return ActiveFileTransferSession") &&
                assertBeforeValue(internetSession, "if (isCurrentAndAllowed())", "pendingInternetOutgoingFileTransfer = file"),
        )
        assertTrue(
            "Internet outgoing selection should be unavailable while another file transfer is pending or active",
            internetSession.contains("pendingInternetOutgoingFileTransfer == null") &&
                internetSession.contains("!hasActiveFileTransfer()") &&
                assertBeforeValue(internetSession, "pendingInternetOutgoingFileTransfer == null", "return ActiveFileTransferSession"),
        )
        assertTrue(
            "Internet should reject a second incoming offer while an offer dialog or transfer is already active",
            internetOffer.contains("pendingIncomingFileDialog != null || pendingInternetOutgoingFileTransfer != null || hasActiveFileTransfer()") &&
                internetOffer.contains("session.respondToFileOffer(offer, accepted = false, rejectionReason = \"concurrent_limit\")") &&
                assertBeforeValue(internetOffer, "pendingIncomingFileDialog != null", "promptIncomingFileOffer("),
        )
    }

    @Test
    fun activeFileTransferSuppressesControlBarAutoHide() {
        val source = mainActivitySource()
        val hideRunnable = extractProperty(source, "private val controlBarHideRunnable")
        val reconcileTouchExplorationState = extractMethod(source, "private fun reconcileTouchExplorationState")
        val revealControlBar = extractMethod(source, "private fun revealControlBar")
        val currentRevealReason = extractMethod(source, "private fun currentControlBarRevealReason")
        val hasActiveFileTransfer = extractMethod(source, "private fun hasActiveFileTransfer")

        assertTrue(
            "The delayed hide runnable must not hide progress/cancel UI while any file transfer is active",
            hideRunnable.contains("!hasActiveFileTransfer()") &&
                assertBeforeValue(hideRunnable, "!hasActiveFileTransfer()", "hideControlBar()"),
        )
        assertTrue(
            "Ordinary reveal calls during an active transfer should be treated as ACTIVE_TRANSFER",
            revealControlBar.contains("currentControlBarRevealReason(revealReason)"),
        )
        assertTrue(
            "Touch-exploration changes should preserve the active-transfer no-autohide reason",
            reconcileTouchExplorationState.contains("currentControlBarRevealReason(") &&
                reconcileTouchExplorationState.contains("ControlBarAccessibilityPolicy.RevealReason.USER_REQUEST"),
        )
        assertTrue(
            "Active incoming or outgoing transfer is the single source that upgrades reveal reason to no-autohide",
            currentRevealReason.contains("hasActiveFileTransfer()") &&
                currentRevealReason.contains("ControlBarAccessibilityPolicy.RevealReason.ACTIVE_TRANSFER") &&
                currentRevealReason.contains("requested") &&
                hasActiveFileTransfer.contains("activeIncomingFileTransfer != null || activeOutgoingFileTransfer != null"),
        )
    }

    @Test
    fun outgoingFileTransferCancelCopyHasDedicatedFailureMessage() {
        val strings = stringsSource()

        assertTrue(strings.contains("file_transfer_failed_cancelled"))
        assertTrue(strings.contains("File transfer request was cancelled."))
        assertTrue(strings.contains("file_transfer_cancel_failed"))
        assertTrue(strings.contains("File transfer could not be cancelled."))
        assertTrue(strings.contains("control_file_transfer_cancel_with_progress"))
        assertTrue(strings.contains("control_file_transfer_cancelling_with_progress"))
    }

    private fun mainActivitySource(): String {
        return sourceFile(MAIN_ACTIVITY_PATHS).readText()
    }

    private fun stringsSource(): String {
        return sourceFile(STRINGS_PATHS).readText()
    }

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

    private fun extractProperty(
        source: String,
        signature: String,
    ): String {
        val start = source.indexOf(signature)
        require(start >= 0) { "Property not found: $signature" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Property body not found: $signature" }
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

    private fun assertBeforeValue(
        source: String,
        first: String,
        second: String,
    ): Boolean {
        val firstIndex = source.indexOf(first)
        val secondIndex = source.indexOf(second)
        return firstIndex >= 0 && secondIndex >= 0 && firstIndex < secondIndex
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

    private companion object {
        val MAIN_ACTIVITY_PATHS =
            listOf(
                "app/src/main/java/dev/telemachus/display/MainActivity.kt",
                "baseline/AndroidClient/app/src/main/java/dev/telemachus/display/MainActivity.kt",
            )
        val STRINGS_PATHS =
            listOf(
                "app/src/main/res/values/strings.xml",
                "baseline/AndroidClient/app/src/main/res/values/strings.xml",
            )
    }
}
