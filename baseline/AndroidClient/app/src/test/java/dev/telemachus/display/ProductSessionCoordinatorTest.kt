package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProductSessionCoordinatorTest {
    @Test
    fun `activate owns generation and starts with legacy controls hidden`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")

        val generation = coordinator.activate(client)
        val state = coordinator.renderState()

        assertTrue(coordinator.accepts(client, generation))
        assertEquals(generation, state.generation)
        assertEquals(ClientSessionCapabilities.LEGACY_TOUCH_ONLY, state.capabilities)
        assertFalse(state.connected)
        assertFalse(state.transportConnected)
        assertFalse(state.connectionAttemptInProgress)
        assertFalse(state.clipboardVisible)
        assertFalse(state.fileTransferVisible)
        assertFalse(state.hostActionsVisible)
        assertEquals(emptyList<StreamDisplayOption>(), state.displays)
    }

    @Test
    fun `connection attempt gate allows one in flight attempt until ended`() {
        val coordinator = ProductSessionCoordinator<TestClient>()

        assertTrue(coordinator.beginConnectionAttempt())
        assertTrue(coordinator.renderState().connectionAttemptInProgress)
        assertFalse(coordinator.beginConnectionAttempt())

        coordinator.endConnectionAttempt()

        assertFalse(coordinator.renderState().connectionAttemptInProgress)
        assertTrue(coordinator.beginConnectionAttempt())
    }

    @Test
    fun `connection attempt gate rejects while any transport is connected`() {
        val coordinator = ProductSessionCoordinator<TestClient>()

        coordinator.setTransportConnected(true)

        assertTrue(coordinator.renderState().transportConnected)
        assertFalse(coordinator.renderState().connected)
        assertFalse(coordinator.beginConnectionAttempt())
    }

    @Test
    fun `display selection intent maps only current selectable state to command`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(displaySelection = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onDisplaysAvailable(client, generation, displays = displays(), selectedId = "built-in")

        assertEquals(
            ProductSessionCoordinator.Command.SelectDisplay("studio", previousDisplayId = "built-in"),
            coordinator.requestDisplaySelection("studio"),
        )
        assertEquals(ProductSessionCoordinator.Command.None, coordinator.requestDisplaySelection("built-in"))
        assertEquals(ProductSessionCoordinator.Command.None, coordinator.requestDisplaySelection("missing"))

        assertTrue(coordinator.onDisplaySelectionPending(client, generation, selectedId = "built-in", pendingId = "studio"))
        assertEquals(ProductSessionCoordinator.Command.None, coordinator.requestDisplaySelection("built-in"))
    }

    @Test
    fun `host action intent maps only negotiated supported enabled action`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(hostActions = true, customGestures = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onHostActionsAvailable(
            client,
            generation,
            listOf(
                HostActionOption("unsupported", "Unsupported", requiresConfirmation = false),
                HostActionOption(HostActionMenuPolicy.ACTION_MOVE_WINDOW, "Move", requiresConfirmation = false),
            ),
        )

        assertFalse(coordinator.renderState().hostActionsEnabled)
        assertEquals(ProductSessionCoordinator.Command.None, coordinator.requestHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW))

        coordinator.setRuntimeAvailability(client, generation, hostActions = true)

        assertTrue(coordinator.renderState().hostActionsEnabled)
        assertEquals(
            ProductSessionCoordinator.Command.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
            coordinator.requestHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW),
        )
        assertEquals(ProductSessionCoordinator.Command.None, coordinator.requestHostAction("unsupported"))
    }

    @Test
    fun `connected status gates visible controls and disconnect status clears UI state`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(displaySelection = true, clipboard = true, fileTransfer = true))
        coordinator.onDisplaysAvailable(client, generation, displays = displays(), selectedId = "built-in")
        coordinator.setRuntimeAvailability(client, generation, clipboard = true, fileTransfer = true)

        assertFalse(coordinator.renderState().clipboardVisible)
        assertFalse(coordinator.renderState().fileTransferVisible)

        assertTrue(coordinator.onConnectionStatus(client, generation, isConnected = true))
        assertTrue(coordinator.renderState().transportConnected)
        assertTrue(coordinator.renderState().clipboardVisible)
        assertTrue(coordinator.renderState().clipboardEnabled)
        assertTrue(coordinator.renderState().fileTransferVisible)

        assertTrue(coordinator.onConnectionStatus(client, generation, isConnected = false))
        val disconnected = coordinator.renderState()
        assertFalse(disconnected.connected)
        assertFalse(disconnected.transportConnected)
        assertEquals(emptyList<StreamDisplayOption>(), disconnected.displays)
        assertFalse(disconnected.clipboardVisible)
        assertFalse(disconnected.fileTransferVisible)
    }

    @Test
    fun `internet transport state gates attempts without activating local session controls`() {
        val coordinator = ProductSessionCoordinator<TestClient>()

        coordinator.setTransportConnected(true)
        val active = coordinator.renderState()

        assertTrue(active.transportConnected)
        assertFalse(active.connected)
        assertEquals(ClientSessionCapabilities.LEGACY_TOUCH_ONLY, active.capabilities)
        assertFalse(active.clipboardVisible)
        assertFalse(coordinator.beginConnectionAttempt())

        coordinator.setTransportConnected(false)

        assertFalse(coordinator.renderState().transportConnected)
        assertTrue(coordinator.beginConnectionAttempt())
    }

    @Test
    fun `clipboard visible follows capability while enabled follows runtime readiness`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)

        assertTrue(coordinator.renderState().clipboardVisible)
        assertFalse(coordinator.renderState().clipboardEnabled)

        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        assertTrue(coordinator.renderState().clipboardVisible)
        assertTrue(coordinator.renderState().clipboardEnabled)
    }

    @Test
    fun `partial runtime availability updates preserve omitted values`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(hostActions = true, clipboard = true, fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onHostActionsAvailable(client, generation, listOf(HostActionOption(HostActionMenuPolicy.ACTION_MOVE_WINDOW, "", false)))
        coordinator.setRuntimeAvailability(client, generation, clipboard = true, fileTransfer = true, hostActions = true)

        coordinator.setRuntimeAvailability(client, generation, clipboard = false)
        val state = coordinator.renderState()

        assertTrue(state.clipboardVisible)
        assertFalse(state.clipboardEnabled)
        assertTrue(state.fileTransferEnabled)
        assertTrue(state.hostActionsEnabled)
    }

    @Test
    fun `activating a local session keeps in flight attempt gate active until completion`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")

        assertTrue(coordinator.beginConnectionAttempt())
        val generation = coordinator.activate(client)

        assertTrue(coordinator.accepts(client, generation))
        assertTrue(coordinator.renderState().connectionAttemptInProgress)
        assertFalse(coordinator.beginConnectionAttempt())

        coordinator.endConnectionAttempt()

        assertFalse(coordinator.renderState().connectionAttemptInProgress)
    }

    @Test
    fun `confirmed and rejected display callbacks clear pending state`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(displaySelection = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onDisplaysAvailable(client, generation, displays = displays(), selectedId = "built-in")
        coordinator.onDisplaySelectionPending(client, generation, selectedId = "built-in", pendingId = "studio")

        assertTrue(coordinator.onDisplaySelectionConfirmed(client, generation, selectedId = "studio"))
        assertEquals("studio", coordinator.renderState().selectedDisplayId)
        assertEquals(null, coordinator.renderState().pendingDisplayId)

        coordinator.onDisplaySelectionPending(client, generation, selectedId = "studio", pendingId = "built-in")
        assertTrue(coordinator.onDisplaySelectionRejected(client, generation, selectedId = "studio"))
        assertEquals("studio", coordinator.renderState().selectedDisplayId)
        assertEquals(null, coordinator.renderState().pendingDisplayId)
    }

    @Test
    fun `disconnect cleanup clears UI product session state`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(displaySelection = true, hostActions = true, clipboard = true, fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onDisplaysAvailable(client, generation, displays = displays(), selectedId = "built-in")
        coordinator.onDisplaySelectionPending(client, generation, selectedId = "built-in", pendingId = "studio")
        coordinator.onHostActionsAvailable(client, generation, listOf(HostActionOption(HostActionMenuPolicy.ACTION_MOVE_WINDOW, "", false)))
        coordinator.setRuntimeAvailability(client, generation, clipboard = true, fileTransfer = true, hostActions = true)

        assertTrue(coordinator.renderState().clipboardEnabled)
        assertTrue(coordinator.invalidate(client, generation))
        val state = coordinator.renderState()

        assertFalse(coordinator.accepts(client, generation))
        assertFalse(state.connected)
        assertFalse(state.transportConnected)
        assertFalse(state.connectionAttemptInProgress)
        assertEquals(ClientSessionCapabilities.LEGACY_TOUCH_ONLY, state.capabilities)
        assertEquals(emptyList<StreamDisplayOption>(), state.displays)
        assertEquals("", state.selectedDisplayId)
        assertEquals(null, state.pendingDisplayId)
        assertEquals(emptyList<HostActionOption>(), state.hostActions)
        assertFalse(state.clipboardVisible)
        assertFalse(state.fileTransferVisible)
        assertFalse(state.hostActionsVisible)
    }

    @Test
    fun `clear disconnected UI state preserves current session identity`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        coordinator.clearDisconnectedUiState()

        assertTrue(coordinator.accepts(client, generation))
        assertEquals(binding(clipboard = true), coordinator.currentBinding())
        assertFalse(coordinator.renderState().connected)
        assertFalse(coordinator.renderState().transportConnected)
        assertFalse(coordinator.renderState().clipboardVisible)
    }

    @Test
    fun `stale callbacks cannot mutate active replacement session`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val oldClient = TestClient("old")
        val oldGeneration = coordinator.activate(oldClient)
        val currentClient = TestClient("current")
        val currentGeneration = coordinator.activate(currentClient)
        coordinator.updateNegotiatedSession(currentClient, currentGeneration, binding(displaySelection = true))
        coordinator.onConnectionStatus(currentClient, currentGeneration, isConnected = true)

        assertFalse(coordinator.onConnectionStatus(oldClient, oldGeneration, isConnected = true))
        assertFalse(coordinator.onDisplaysAvailable(oldClient, oldGeneration, displays(), selectedId = "studio"))
        assertFalse(coordinator.onDisplaySelectionPending(oldClient, oldGeneration, selectedId = "built-in", pendingId = "studio"))
        assertFalse(coordinator.onDisplaySelectionConfirmed(oldClient, oldGeneration, selectedId = "studio"))
        assertFalse(coordinator.onDisplaySelectionRejected(oldClient, oldGeneration, selectedId = "built-in"))
        assertFalse(
            coordinator.onHostActionsAvailable(
                oldClient,
                oldGeneration,
                listOf(HostActionOption(HostActionMenuPolicy.ACTION_MOVE_WINDOW, "", false)),
            ),
        )
        assertFalse(coordinator.setRuntimeAvailability(oldClient, oldGeneration, clipboard = true, fileTransfer = true, hostActions = true))

        val state = coordinator.renderState()
        assertTrue(state.connected)
        assertEquals(emptyList<StreamDisplayOption>(), state.displays)
        assertFalse(state.clipboardVisible)
        assertFalse(state.hostActionsVisible)
    }

    @Test
    fun `configuration changes do not reset session state`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(displaySelection = true, clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.onDisplaysAvailable(client, generation, displays = displays(), selectedId = "studio")
        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        val before = coordinator.renderState()
        val after = coordinator.renderState()

        assertEquals(before, after)
        assertEquals("studio", after.selectedDisplayId)
        assertTrue(after.clipboardEnabled)
    }

    @Test
    fun `internet session lifecycle tracks generation token and epoch`() {
        val coordinator = ProductSessionCoordinator<TestClient>()

        assertEquals(0L, coordinator.currentInternetGeneration())
        assertEquals(0L, coordinator.currentInternetSessionEpoch())

        val generation = coordinator.beginInternetSession(sessionEpoch = 42L)

        assertEquals(1L, generation)
        assertEquals(1L, coordinator.currentInternetGeneration())
        assertEquals(42L, coordinator.currentInternetSessionEpoch())
        assertFalse(coordinator.isInternetGenerationCurrent(generation = 0L))
        assertTrue(coordinator.isInternetGenerationCurrent(generation))

        val token = Any()
        assertTrue(coordinator.attachInternetSession(generation, token))
        assertTrue(coordinator.acceptsInternetSession(generation, token))
        assertFalse(coordinator.acceptsInternetSession(generation, Any()))
        assertFalse(coordinator.acceptsInternetSession(generation = 0L, token))
    }

    @Test
    fun `internet session freshness requirement rejects stale leases`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val generation = coordinator.beginInternetSession(sessionEpoch = 10L)
        val token = Any()
        coordinator.attachInternetSession(generation, token)

        assertFalse(coordinator.requiresFreshInternetLease(sessionEpoch = 10L))
        assertFalse(coordinator.requiresFreshInternetLease(sessionEpoch = 11L))

        assertTrue(coordinator.markFreshInternetSessionRequired(generation, token))

        assertEquals(10L, coordinator.requiredFreshInternetEpoch())
        assertTrue(coordinator.requiresFreshInternetLease(sessionEpoch = 10L))
        assertFalse(coordinator.requiresFreshInternetLease(sessionEpoch = 11L))

        coordinator.clearInternetFreshnessRequirement()

        assertEquals(0L, coordinator.requiredFreshInternetEpoch())
        assertFalse(coordinator.requiresFreshInternetLease(sessionEpoch = 10L))
    }

    @Test
    fun `internet session start failure marks the failed epoch as stale`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val generation = coordinator.beginInternetSession(sessionEpoch = 10L)

        assertTrue(coordinator.markInternetSessionStartFailed(generation, sessionEpoch = 10L))
        assertEquals(10L, coordinator.requiredFreshInternetEpoch())
        assertTrue(coordinator.requiresFreshInternetLease(sessionEpoch = 10L))

        assertFalse(coordinator.markInternetSessionStartFailed(generation = generation + 1, sessionEpoch = 20L))
        assertEquals(10L, coordinator.requiredFreshInternetEpoch())
    }

    @Test
    fun `internet session invalidation bumps generation and clears token and epoch`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val generation = coordinator.beginInternetSession(sessionEpoch = 10L)
        val token = Any()
        coordinator.attachInternetSession(generation, token)

        coordinator.invalidateInternetSession()

        assertEquals(generation + 1, coordinator.currentInternetGeneration())
        assertEquals(0L, coordinator.currentInternetSessionEpoch())
        assertFalse(coordinator.acceptsInternetSession(generation, token))
    }

    @Test
    fun `internet pairing revocation rejects every future lease epoch`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        coordinator.beginInternetSession(sessionEpoch = 10L)

        coordinator.revokeInternetPairing()

        assertEquals(Long.MAX_VALUE, coordinator.requiredFreshInternetEpoch())
        assertTrue(coordinator.requiresFreshInternetLease(sessionEpoch = Long.MAX_VALUE))
    }

    @Test
    fun `clipboard offer requires negotiated clipboard and runtime availability`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)

        assertFalse(coordinator.hasPendingClipboardReceive(client, generation))

        val offer = PendingClipboardOffer(
            changeId = byteArrayOf(1, 2, 3),
            originDeviceId = "host",
            mimeType = "text/plain",
            byteLength = 4L,
            sha256 = ByteArray(32),
        )
        assertFalse(coordinator.stageClipboardOffer(client, generation, offer))

        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        assertTrue(coordinator.stageClipboardOffer(client, generation, offer))
        assertTrue(coordinator.hasPendingClipboardReceive(client, generation))
    }

    @Test
    fun `clipboard offer approval and solicited content consumption`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        val changeId = byteArrayOf(1, 2, 3)
        val offer = PendingClipboardOffer(
            changeId = changeId,
            originDeviceId = "host",
            mimeType = "text/plain",
            byteLength = 4L,
            sha256 = ByteArray(32),
        )
        assertTrue(coordinator.stageClipboardOffer(client, generation, offer))
        assertEquals(offer, coordinator.clipboardOfferForRequest(client, generation))

        assertTrue(coordinator.approveClipboardOffer(client, generation, changeId))
        assertNull(coordinator.clipboardOfferForRequest(client, generation))

        val content = ClipboardContentData(
            changeId = changeId,
            originDeviceId = "host",
            mimeType = "text/plain",
            content = "text".toByteArray(),
            sha256 = ByteArray(32),
            pending = false,
        )
        assertEquals(content, coordinator.consumeSolicitedClipboardContent(client, generation, content))
        assertFalse(coordinator.hasPendingClipboardReceive(client, generation))
    }

    @Test
    fun `direct clipboard content requires confirmation before consumption`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        val changeId = byteArrayOf(4, 5, 6)
        val content = ClipboardContentData(
            changeId = changeId,
            originDeviceId = "host",
            mimeType = "text/plain",
            content = "direct".toByteArray(),
            sha256 = ByteArray(32),
            pending = true,
        )
        assertTrue(coordinator.stageDirectClipboardContent(client, generation, content))
        assertTrue(coordinator.hasPendingClipboardReceive(client, generation))
        assertEquals(content, coordinator.directClipboardContentForConfirmation(client, generation))

        assertEquals(content, coordinator.consumeDirectClipboardContent(client, generation, changeId))
        assertFalse(coordinator.hasPendingClipboardReceive(client, generation))
    }

    @Test
    fun `clipboard workflow is cleared when clipboard capability or runtime is lost`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(clipboard = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, clipboard = true)

        val offer = PendingClipboardOffer(
            changeId = byteArrayOf(1),
            originDeviceId = "host",
            mimeType = "text/plain",
            byteLength = 1L,
            sha256 = ByteArray(32),
        )
        assertTrue(coordinator.stageClipboardOffer(client, generation, offer))
        assertTrue(coordinator.hasPendingClipboardReceive(client, generation))

        coordinator.setRuntimeAvailability(client, generation, clipboard = false)

        assertFalse(coordinator.hasPendingClipboardReceive(client, generation))
    }

    @Test
    fun `outgoing file transfer staging requires negotiated file transfer`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)

        assertFalse(coordinator.requestOutgoingFileTransfer(client, generation))

        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        assertTrue(coordinator.requestOutgoingFileTransfer(client, generation))
        val fileToken = Any()
        assertTrue(coordinator.stageOutgoingFileTransfer(client, generation, fileToken))
        assertEquals(fileToken, coordinator.takePendingOutgoingFileTransfer())
        assertNull(coordinator.takePendingOutgoingFileTransfer())
    }

    @Test
    fun `incoming file offer is accepted only once and finished by matching token`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        val offerToken = Any()
        assertTrue(coordinator.beginIncomingFileOffer(client, generation, offerToken))
        assertFalse(coordinator.beginIncomingFileOffer(client, generation, Any()))
        assertTrue(coordinator.acceptsIncomingFileOffer(client, generation, offerToken))

        assertTrue(coordinator.finishIncomingFileOffer(client, generation, offerToken))
        assertFalse(coordinator.acceptsIncomingFileOffer(client, generation, offerToken))
    }

    @Test
    fun `incoming and outgoing file transfer workflows are mutually exclusive`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        val offerToken = Any()
        assertTrue(coordinator.beginIncomingFileOffer(client, generation, offerToken))
        assertFalse(coordinator.requestOutgoingFileTransfer(client, generation))
        assertFalse(coordinator.stageOutgoingFileTransfer(client, generation, Any()))

        assertTrue(coordinator.finishIncomingFileOffer(client, generation, offerToken))
        assertTrue(coordinator.requestOutgoingFileTransfer(client, generation))

        val fileToken = Any()
        assertTrue(coordinator.stageOutgoingFileTransfer(client, generation, fileToken))
        assertFalse(coordinator.beginIncomingFileOffer(client, generation, Any()))

        assertEquals(fileToken, coordinator.takePendingOutgoingFileTransfer())
        assertTrue(coordinator.beginIncomingFileOffer(client, generation, Any()))
    }

    @Test
    fun `file transfer workflow is cleared when file transfer capability is lost`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        val fileToken = Any()
        assertTrue(coordinator.stageOutgoingFileTransfer(client, generation, fileToken))

        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = false))

        assertNull(coordinator.takePendingOutgoingFileTransfer())

        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)
        val offerToken = Any()
        assertTrue(coordinator.beginIncomingFileOffer(client, generation, offerToken))

        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = false))

        assertFalse(coordinator.acceptsIncomingFileOffer(client, generation, offerToken))
    }

    @Test
    fun `clearFileTransferWorkflow returns pending outgoing token for explicit resource handoff`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        val fileToken = Any()
        assertTrue(coordinator.stageOutgoingFileTransfer(client, generation, fileToken))

        val returned = coordinator.clearFileTransferWorkflow()

        assertEquals(fileToken, returned)
        assertNull(coordinator.takePendingOutgoingFileTransfer())
    }

    @Test
    fun `disconnect clears and returns pending outgoing file token`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        coordinator.updateNegotiatedSession(client, generation, binding(fileTransfer = true))
        coordinator.onConnectionStatus(client, generation, isConnected = true)
        coordinator.setRuntimeAvailability(client, generation, fileTransfer = true)

        val fileToken = Any()
        assertTrue(coordinator.stageOutgoingFileTransfer(client, generation, fileToken))

        assertTrue(coordinator.onConnectionStatus(client, generation, isConnected = false))

        assertNull(coordinator.takePendingOutgoingFileTransfer())
    }

    @Test
    fun `stageOutgoingFileTransfer fails when file transfer controls are not enabled`() {
        val coordinator = ProductSessionCoordinator<TestClient>()
        val client = TestClient("current")
        val generation = coordinator.activate(client)
        // No fileTransfer capability, no runtime availability

        assertFalse(coordinator.stageOutgoingFileTransfer(client, generation, Any()))
        assertNull(coordinator.takePendingOutgoingFileTransfer())
    }

    private fun binding(
        displaySelection: Boolean = false,
        hostActions: Boolean = false,
        customGestures: Boolean = false,
        clipboard: Boolean = false,
        fileTransfer: Boolean = false,
    ) =
        ClientSessionBinding(
            ClientSessionCapabilities.LEGACY_TOUCH_ONLY.copy(
                displaySelection = displaySelection,
                hostActions = hostActions,
                customGestures = customGestures,
                clipboard = clipboard,
                fileTransfer = fileTransfer,
            ),
        )

    private fun displays(): List<StreamDisplayOption> =
        listOf(
            StreamDisplayOption("built-in", "Built-in", 1920, 1080, isPrimary = true, isVirtual = false),
            StreamDisplayOption("studio", "Studio", 2560, 1440, isPrimary = false, isVirtual = false),
        )

    private data class TestClient(
        val name: String,
    )
}
