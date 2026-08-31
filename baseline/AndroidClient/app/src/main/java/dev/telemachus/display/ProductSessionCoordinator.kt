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
    private var displayState = DisplayState()
    private var hostActions = emptyList<HostActionOption>()
    private var clipboardRuntimeAvailable = false
    private var fileTransferRuntimeAvailable = false
    private var hostActionsRuntimeAvailable = false

    fun activate(client: ClientIdentity): Long {
        val generation = sessionState.activate(client)
        activeClient = client
        activeGeneration = generation
        connected = false
        clearUiState()
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
    ): Boolean = sessionState.updateNegotiatedSession(client, generation, binding)

    fun onConnectionStatus(
        client: ClientIdentity,
        generation: Long,
        isConnected: Boolean,
    ): Boolean {
        if (!accepts(client, generation)) return false
        connected = isConnected
        if (!isConnected) clearUiState()
        return true
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
        return true
    }

    fun requestHostAction(actionId: String): Command {
        val state = renderState()
        if (!state.hostActionsEnabled || state.hostActions.none { it.id == actionId }) return Command.None
        return Command.InvokeHostAction(actionId)
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
        clearUiState()
    }

    private fun clearUiState() {
        displayState = DisplayState()
        hostActions = emptyList()
        clipboardRuntimeAvailable = false
        fileTransferRuntimeAvailable = false
        hostActionsRuntimeAvailable = false
    }

    data class RenderState(
        val connected: Boolean,
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

    private companion object {
        const val NO_GENERATION = 0L
    }
}
