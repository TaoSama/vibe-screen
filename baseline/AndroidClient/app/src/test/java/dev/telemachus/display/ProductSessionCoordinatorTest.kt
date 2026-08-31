package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
