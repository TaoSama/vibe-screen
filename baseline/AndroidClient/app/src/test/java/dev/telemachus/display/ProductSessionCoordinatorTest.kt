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
        assertFalse(state.clipboardVisible)
        assertFalse(state.fileTransferVisible)
        assertFalse(state.hostActionsVisible)
        assertEquals(emptyList<StreamDisplayOption>(), state.displays)
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
