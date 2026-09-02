package dev.telemachus.display

/**
 * Coordinates UI-facing product-session state without owning transport, protocol,
 * renderer, decoder, or platform side effects. The view layer executes returned
 * commands; this class owns session freshness and control availability decisions.
 */
internal class ProductSessionCoordinator<ClientIdentity : Any>(
    private val sessionState: SessionState<ClientIdentity> = SessionState(),
) {
    private var activeClient: ClientIdentity? = null
    private var activeGeneration = NO_GENERATION
    private var connected = false
    private var transportConnected = false
    private var connectionAttemptInProgress = false
    private var displayState = DisplayState()
    private var hostActions = emptyList<HostActionOption>()
    private var clipboardRuntimeAvailable = false
    private var fileTransferRuntimeAvailable = false
    private var hostActionsRuntimeAvailable = false
    private val clipboardApprovalState = ClipboardApprovalState<ClientIdentity>()
    private var pendingOutgoingFileTransfer: PendingOutgoingFileTransfer<ClientIdentity>? = null
    private var pendingIncomingFileOffer: PendingIncomingFileOffer<ClientIdentity>? = null
    @Volatile private var internetSessionToken: Any? = null
    @Volatile private var internetGeneration = NO_GENERATION
    @Volatile private var internetSessionEpoch = NO_GENERATION
    private var requiredFreshInternetEpoch = NO_GENERATION

    fun activate(client: ClientIdentity): Long {
        val generation = sessionState.activate(client)
        activeClient = client
        activeGeneration = generation
        connected = false
        transportConnected = false
        clearUiState()
        clipboardApprovalState.activate(client, generation)
        return generation
    }

    fun invalidate(
        client: ClientIdentity,
        generation: Long,
    ): Boolean {
        if (!sessionState.invalidate(client, generation)) return false
        if (activeClient === client && activeGeneration == generation) {
            activeClient = null
            activeGeneration = NO_GENERATION
            connected = false
            transportConnected = false
            connectionAttemptInProgress = false
            clearUiState()
        }
        return true
    }

    fun accepts(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = sessionState.accepts(client, generation)

    fun currentGeneration(): Long = activeGeneration

    fun currentBinding(): ClientSessionBinding {
        val client = activeClient ?: return ClientSessionBinding.LEGACY_TOUCH_ONLY
        return sessionState.binding(client, activeGeneration) ?: ClientSessionBinding.LEGACY_TOUCH_ONLY
    }

    fun updateNegotiatedSession(
        client: ClientIdentity,
        generation: Long,
        binding: ClientSessionBinding,
    ): Boolean {
        if (!sessionState.updateNegotiatedSession(client, generation, binding)) return false
        if (!binding.capabilities.clipboard) resetClipboardWorkflow()
        if (!binding.capabilities.fileTransfer) clearFileTransferWorkflow()
        return true
    }

    fun onConnectionStatus(
        client: ClientIdentity,
        generation: Long,
        isConnected: Boolean,
    ): Boolean {
        if (!accepts(client, generation)) return false
        connected = isConnected
        transportConnected = isConnected
        if (!isConnected) clearUiState()
        return true
    }

    fun beginConnectionAttempt(): Boolean {
        if (transportConnected || connectionAttemptInProgress) return false
        connectionAttemptInProgress = true
        return true
    }

    fun endConnectionAttempt() {
        connectionAttemptInProgress = false
    }

    fun setTransportConnected(isConnected: Boolean) {
        transportConnected = isConnected
        if (!isConnected) {
            connected = false
            clearUiState()
        }
    }

    fun onDisplaysAvailable(
        client: ClientIdentity,
        generation: Long,
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ): Boolean {
        if (!accepts(client, generation)) return false
        displayState =
            DisplayState(
                displays = displays.toList(),
                selectedId = selectedId,
                pendingDisplayId = null,
            )
        return true
    }

    fun onDisplaySelectionPending(
        client: ClientIdentity,
        generation: Long,
        selectedId: String,
        pendingId: String,
    ): Boolean {
        if (!accepts(client, generation)) return false
        if (pendingId == selectedId || displayState.displays.none { it.id == pendingId }) return false
        displayState = displayState.copy(selectedId = selectedId, pendingDisplayId = pendingId)
        return true
    }

    fun onDisplaySelectionConfirmed(
        client: ClientIdentity,
        generation: Long,
        selectedId: String,
    ): Boolean {
        if (!accepts(client, generation)) return false
        displayState = displayState.copy(selectedId = selectedId, pendingDisplayId = null)
        return true
    }

    fun onDisplaySelectionRejected(
        client: ClientIdentity,
        generation: Long,
        selectedId: String,
    ): Boolean {
        if (!accepts(client, generation)) return false
        displayState = displayState.copy(selectedId = selectedId, pendingDisplayId = null)
        return true
    }

    fun requestDisplaySelection(displayId: String): Command {
        val state = renderState()
        if (!DisplayCapsulePolicy.isEnabled(
                displaySelection = state.capabilities.displaySelection,
                displays = state.displays,
                pendingDisplayId = state.pendingDisplayId,
            ) || displayId == state.selectedDisplayId || state.displays.none { it.id == displayId }
        ) {
            return Command.None
        }
        return Command.SelectDisplay(displayId, previousDisplayId = state.selectedDisplayId)
    }

    fun onHostActionsAvailable(
        client: ClientIdentity,
        generation: Long,
        actions: List<HostActionOption>,
    ): Boolean {
        if (!accepts(client, generation)) return false
        hostActions = HostActionMenuPolicy.supportedActions(actions)
        return true
    }

    fun setRuntimeAvailability(
        client: ClientIdentity,
        generation: Long,
        clipboard: Boolean = clipboardRuntimeAvailable,
        fileTransfer: Boolean = fileTransferRuntimeAvailable,
        hostActions: Boolean = hostActionsRuntimeAvailable,
    ): Boolean {
        if (!accepts(client, generation)) return false
        clipboardRuntimeAvailable = clipboard
        fileTransferRuntimeAvailable = fileTransfer
        hostActionsRuntimeAvailable = hostActions
        if (!clipboardRuntimeAvailable) resetClipboardWorkflow()
        if (!fileTransferRuntimeAvailable) clearFileTransferWorkflow()
        return true
    }

    fun requestHostAction(actionId: String): Command {
        val state = renderState()
        if (!state.hostActionsEnabled || state.hostActions.none { it.id == actionId }) return Command.None
        return Command.InvokeHostAction(actionId)
    }

    fun beginInternetSession(sessionEpoch: Long): Long {
        internetGeneration += 1
        internetSessionToken = null
        internetSessionEpoch = sessionEpoch
        return internetGeneration
    }

    fun attachInternetSession(
        generation: Long,
        sessionToken: Any,
    ): Boolean {
        if (!isInternetGenerationCurrent(generation)) return false
        internetSessionToken = sessionToken
        return true
    }

    fun acceptsInternetSession(
        generation: Long,
        sessionToken: Any?,
    ): Boolean =
        sessionToken != null &&
            internetGeneration == generation &&
            internetSessionToken === sessionToken

    fun isInternetGenerationCurrent(generation: Long): Boolean = internetGeneration == generation

    fun currentInternetGeneration(): Long = internetGeneration

    fun currentInternetSessionEpoch(): Long = internetSessionEpoch

    fun requiredFreshInternetEpoch(): Long = requiredFreshInternetEpoch

    fun requiresFreshInternetLease(sessionEpoch: Long): Boolean = sessionEpoch <= requiredFreshInternetEpoch

    fun clearInternetFreshnessRequirement() {
        requiredFreshInternetEpoch = NO_GENERATION
    }

    fun markFreshInternetSessionRequired(
        generation: Long,
        sessionToken: Any?,
    ): Boolean {
        if (!acceptsInternetSession(generation, sessionToken)) return false
        requiredFreshInternetEpoch = maxOf(requiredFreshInternetEpoch, internetSessionEpoch)
        return true
    }

    fun markInternetSessionStartFailed(
        generation: Long,
        sessionEpoch: Long,
    ): Boolean {
        if (!isInternetGenerationCurrent(generation)) return false
        requiredFreshInternetEpoch = maxOf(requiredFreshInternetEpoch, sessionEpoch)
        return true
    }

    fun invalidateInternetSession() {
        internetGeneration += 1
        internetSessionToken = null
        internetSessionEpoch = NO_GENERATION
    }

    fun revokeInternetPairing() {
        requiredFreshInternetEpoch = Long.MAX_VALUE
        invalidateInternetSession()
    }

    fun hasPendingClipboardReceive(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = clipboardControlsEnabled(client, generation) && clipboardApprovalState.hasPendingReceive(client, generation)

    fun stageClipboardOffer(
        client: ClientIdentity,
        generation: Long,
        offer: PendingClipboardOffer,
    ): Boolean = clipboardControlsEnabled(client, generation) && clipboardApprovalState.stageOffer(client, generation, offer)

    fun stageDirectClipboardContent(
        client: ClientIdentity,
        generation: Long,
        content: ClipboardContentData,
    ): Boolean = clipboardControlsEnabled(client, generation) && clipboardApprovalState.stageDirectContent(client, generation, content)

    fun clipboardOfferForRequest(
        client: ClientIdentity,
        generation: Long,
    ): PendingClipboardOffer? =
        if (clipboardControlsEnabled(client, generation)) clipboardApprovalState.offerForRequest(client, generation) else null

    fun directClipboardContentForConfirmation(
        client: ClientIdentity,
        generation: Long,
    ): ClipboardContentData? =
        if (clipboardControlsEnabled(client, generation)) clipboardApprovalState.directContentForConfirmation(client, generation) else null

    fun approveClipboardOffer(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): Boolean = clipboardControlsEnabled(client, generation) && clipboardApprovalState.approveOffer(client, generation, changeId)

    fun cancelClipboardOfferApproval(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): Boolean = clipboardApprovalState.cancelOfferApproval(client, generation, changeId)

    fun consumeSolicitedClipboardContent(
        client: ClientIdentity,
        generation: Long,
        content: ClipboardContentData,
    ): ClipboardContentData? =
        if (clipboardControlsEnabled(client, generation)) {
            clipboardApprovalState.consumeSolicitedContent(client, generation, content)
        } else {
            null
        }

    fun consumeDirectClipboardContent(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ): ClipboardContentData? =
        if (clipboardControlsEnabled(client, generation)) {
            clipboardApprovalState.consumeDirectContent(client, generation, changeId)
        } else {
            null
        }

    fun discardDirectClipboardContent(
        client: ClientIdentity,
        generation: Long,
        changeId: ByteArray,
    ) {
        clipboardApprovalState.discardDirectContent(client, generation, changeId)
    }

    fun clearClipboardWorkflow() {
        resetClipboardWorkflow()
    }

    fun requestOutgoingFileTransfer(
        client: ClientIdentity,
        generation: Long,
    ): Boolean = fileTransferControlsEnabled(client, generation)

    fun stageOutgoingFileTransfer(
        client: ClientIdentity,
        generation: Long,
        fileToken: Any,
    ): Boolean {
        if (!fileTransferControlsEnabled(client, generation)) return false
        pendingOutgoingFileTransfer = PendingOutgoingFileTransfer(client, generation, fileToken)
        return true
    }

    fun takePendingOutgoingFileTransfer(): Any? {
        val pending = pendingOutgoingFileTransfer ?: return null
        pendingOutgoingFileTransfer = null
        return pending.fileToken
    }

    fun beginIncomingFileOffer(
        client: ClientIdentity,
        generation: Long,
        offerToken: Any,
    ): Boolean {
        if (!fileTransferControlsEnabled(client, generation) || pendingIncomingFileOffer != null) return false
        pendingIncomingFileOffer = PendingIncomingFileOffer(client, generation, offerToken)
        return true
    }

    fun acceptsIncomingFileOffer(
        client: ClientIdentity,
        generation: Long,
        offerToken: Any,
    ): Boolean =
        pendingIncomingFileOffer?.let {
            it.client === client && it.generation == generation && it.offerToken === offerToken
        } == true

    fun finishIncomingFileOffer(
        client: ClientIdentity,
        generation: Long,
        offerToken: Any,
    ): Boolean {
        if (!acceptsIncomingFileOffer(client, generation, offerToken)) return false
        pendingIncomingFileOffer = null
        return true
    }

    fun clearIncomingFileOffer() {
        pendingIncomingFileOffer = null
    }

    fun clearFileTransferWorkflow(): Any? {
        val outgoing = pendingOutgoingFileTransfer?.fileToken
        pendingOutgoingFileTransfer = null
        pendingIncomingFileOffer = null
        return outgoing
    }

    fun renderState(): RenderState {
        val binding = currentBinding()
        val capabilities = binding.capabilities
        val sessionControlsActive = activeClient != null && connected
        val hostActionsAvailable =
            sessionControlsActive && HostActionMenuPolicy.isAvailable(capabilities.hostActions, hostActions)
        val clipboardAvailable = sessionControlsActive && ClipboardMenuPolicy.isAvailable(capabilities.clipboard)
        val fileTransferAvailable =
            sessionControlsActive &&
                ClientControlAvailability.isSupported(ClientControl.FILE_TRANSFER, capabilities) &&
                fileTransferRuntimeAvailable
        return RenderState(
            connected = connected,
            transportConnected = transportConnected,
            connectionAttemptInProgress = connectionAttemptInProgress,
            generation = activeGeneration,
            binding = binding,
            capabilities = capabilities,
            displays = displayState.displays,
            selectedDisplayId = displayState.selectedId,
            pendingDisplayId = displayState.pendingDisplayId,
            hostActions = hostActions,
            hostActionsVisible = hostActionsAvailable,
            hostActionsEnabled = hostActionsAvailable && hostActionsRuntimeAvailable,
            clipboardVisible = clipboardAvailable,
            clipboardEnabled = clipboardAvailable && clipboardRuntimeAvailable,
            fileTransferVisible = fileTransferAvailable,
            fileTransferEnabled = fileTransferAvailable,
        )
    }

    fun clearDisconnectedUiState() {
        connected = false
        transportConnected = false
        clearUiState()
    }

    private fun clearUiState(): Any? {
        displayState = DisplayState()
        hostActions = emptyList()
        clipboardRuntimeAvailable = false
        fileTransferRuntimeAvailable = false
        hostActionsRuntimeAvailable = false
        clipboardApprovalState.clear()
        return clearFileTransferWorkflow()
    }

    private fun resetClipboardWorkflow() {
        clipboardApprovalState.clear()
        val client = activeClient ?: return
        if (activeGeneration != NO_GENERATION) {
            clipboardApprovalState.activate(client, activeGeneration)
        }
    }

    private fun fileTransferControlsEnabled(
        client: ClientIdentity,
        generation: Long,
    ): Boolean =
        accepts(client, generation) &&
            connected &&
            ClientControlAvailability.isSupported(ClientControl.FILE_TRANSFER, currentBinding().capabilities) &&
            fileTransferRuntimeAvailable

    private fun clipboardControlsEnabled(
        client: ClientIdentity,
        generation: Long,
    ): Boolean =
        accepts(client, generation) &&
            connected &&
            ClipboardMenuPolicy.isAvailable(currentBinding().capabilities.clipboard) &&
            clipboardRuntimeAvailable

    data class RenderState(
        val connected: Boolean,
        val transportConnected: Boolean,
        val connectionAttemptInProgress: Boolean,
        val generation: Long,
        val binding: ClientSessionBinding,
        val capabilities: ClientSessionCapabilities,
        val displays: List<StreamDisplayOption>,
        val selectedDisplayId: String,
        val pendingDisplayId: String?,
        val hostActions: List<HostActionOption>,
        val hostActionsVisible: Boolean,
        val hostActionsEnabled: Boolean,
        val clipboardVisible: Boolean,
        val clipboardEnabled: Boolean,
        val fileTransferVisible: Boolean,
        val fileTransferEnabled: Boolean,
    )

    sealed interface Command {
        data object None : Command

        data class SelectDisplay(
            val displayId: String,
            val previousDisplayId: String,
        ) : Command

        data class InvokeHostAction(
            val actionId: String,
        ) : Command
    }

    private data class DisplayState(
        val displays: List<StreamDisplayOption> = emptyList(),
        val selectedId: String = "",
        val pendingDisplayId: String? = null,
    )

    private data class PendingOutgoingFileTransfer<ClientIdentity : Any>(
        val client: ClientIdentity,
        val generation: Long,
        val fileToken: Any,
    )

    private data class PendingIncomingFileOffer<ClientIdentity : Any>(
        val client: ClientIdentity,
        val generation: Long,
        val offerToken: Any,
    )

    private companion object {
        const val NO_GENERATION = 0L
    }
}
