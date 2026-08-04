package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionStateTest {
    @Test
    fun `activation assigns a new generation and legacy capabilities`() {
        val state = SessionState<TestClient>()
        val client = TestClient("current")

        val firstGeneration = state.activate(client)
        val secondGeneration = state.activate(client)

        assertTrue(secondGeneration > firstGeneration)
        assertFalse(state.accepts(client, firstGeneration))
        assertTrue(state.accepts(client, secondGeneration))
        assertEquals(
            ClientSessionCapabilities.LEGACY_TOUCH_ONLY,
            state.capabilities(client, secondGeneration),
        )
    }

    @Test
    fun `equal clients do not share identity`() {
        val state = SessionState<TestClient>()
        val activeClient = TestClient("same-value")
        val equalButDifferentClient = TestClient("same-value")
        val generation = state.activate(activeClient)

        assertFalse(state.accepts(equalButDifferentClient, generation))
        assertNull(state.capabilities(equalButDifferentClient, generation))
    }

    @Test
    fun `stale invalidation cannot clear replacement session`() {
        val state = SessionState<TestClient>()
        val oldClient = TestClient("old")
        val oldGeneration = state.activate(oldClient)
        val currentClient = TestClient("current")
        val currentGeneration = state.activate(currentClient)

        assertFalse(state.invalidate(oldClient, oldGeneration))
        assertTrue(state.accepts(currentClient, currentGeneration))
        assertTrue(state.invalidate(currentClient, currentGeneration))
        assertFalse(state.accepts(currentClient, currentGeneration))
    }

    @Test
    fun `only current generation can update negotiated capabilities`() {
        val state = SessionState<TestClient>()
        val client = TestClient("reused")
        val staleGeneration = state.activate(client)
        val currentGeneration = state.activate(client)
        val negotiated =
            ClientSessionBinding(
                capabilities =
                    ClientSessionCapabilities(
                        touch = true,
                        displaySelection = true,
                        keyboard = true,
                        nativePointer = true,
                    ),
                inputSink = AcceptingInputSink,
            )

        assertFalse(state.updateNegotiatedSession(client, staleGeneration, negotiated))
        assertEquals(
            ClientSessionCapabilities.LEGACY_TOUCH_ONLY,
            state.capabilities(client, currentGeneration),
        )
        assertTrue(state.updateNegotiatedSession(client, currentGeneration, negotiated))
        assertEquals(negotiated, state.binding(client, currentGeneration))
    }

    @Test
    fun `queued callback is rejected when generation changes before execution`() {
        val state = SessionState<TestClient>()
        val oldClient = TestClient("old")
        val oldGeneration = state.activate(oldClient)
        val queuedCallback = { state.accepts(oldClient, oldGeneration) }

        assertTrue(queuedCallback())
        val replacement = TestClient("replacement")
        val replacementGeneration = state.activate(replacement)

        assertFalse(queuedCallback())
        assertTrue(state.accepts(replacement, replacementGeneration))
    }

    private data class TestClient(
        val value: String,
    )

    private object AcceptingInputSink : ClientSessionInputSink {
        override fun sendKey(input: ClientKeyInput) = true

        override fun sendPointer(input: ClientPointerInput) = true
    }
}
