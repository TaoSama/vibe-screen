package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeInputSessionStateTest {
    @Test
    fun `release is ordered and idempotently clears admitted input`() {
        val state = NativeInputSessionState<TestClient>()
        val client = TestClient("current")
        state.admit(client, 7)

        assertTrue(state.recordKey(client, 7, usbHidUsage = 0x1d, pressed = true))
        assertTrue(state.recordKey(client, 7, usbHidUsage = 0x04, pressed = true))
        assertTrue(state.recordPointer(client, 7, x = 0.7f, y = 0.2f, buttonMask = 1))

        assertEquals(
            NativeInputReleasePlan(
                pressedKeyUsages = listOf(0x04, 0x1d),
                pointer = NativePointerSnapshot(0.7f, 0.2f),
            ),
            state.takeRelease(client, 7),
        )
        assertTrue(state.takeRelease(client, 7)?.isEmpty == true)
    }

    @Test
    fun `ordinary up and zero button mask leave nothing to synthesize`() {
        val state = NativeInputSessionState<TestClient>()
        val client = TestClient("current")
        state.admit(client, 3)

        state.recordKey(client, 3, usbHidUsage = 0x04, pressed = true)
        state.recordKey(client, 3, usbHidUsage = 0x04, pressed = false)
        state.recordPointer(client, 3, x = 0.4f, y = 0.6f, buttonMask = 1)
        state.recordPointer(client, 3, x = 0.5f, y = 0.7f, buttonMask = 0)

        assertTrue(state.takeRelease(client, 3)?.isEmpty == true)
    }

    @Test
    fun `stale owner cannot mutate drain or discard replacement`() {
        val state = NativeInputSessionState<TestClient>()
        val reusedClient = TestClient("reused")
        state.admit(reusedClient, 1)
        state.recordKey(reusedClient, 1, usbHidUsage = 0x04, pressed = true)
        state.admit(reusedClient, 2)
        state.recordKey(reusedClient, 2, usbHidUsage = 0x05, pressed = true)

        assertFalse(state.recordKey(reusedClient, 1, usbHidUsage = 0x06, pressed = true))
        assertNull(state.takeRelease(reusedClient, 1))
        assertFalse(state.discard(reusedClient, 1))
        assertEquals(listOf(0x05), state.takeRelease(reusedClient, 2)?.pressedKeyUsages)
    }

    @Test
    fun `passive disconnect discards without producing a later release`() {
        val state = NativeInputSessionState<TestClient>()
        val client = TestClient("current")
        state.admit(client, 4)
        state.recordKey(client, 4, usbHidUsage = 0x04, pressed = true)

        assertTrue(state.discard(client, 4))
        assertNull(state.takeRelease(client, 4))
    }

    @Test
    fun `coordinator submits release before disconnect action`() {
        val state = NativeInputSessionState<TestClient>()
        val coordinator = NativeInputReleaseCoordinator(state)
        val client = TestClient("current")
        val events = mutableListOf<String>()
        state.admit(client, 5)
        state.recordKey(client, 5, usbHidUsage = 0x04, pressed = true)

        val result =
            coordinator.completeBoundary(
                client = client,
                generation = 5,
                submitRelease = {
                    events += "release:${it.pressedKeyUsages.single()}"
                    true
                },
                afterRelease = { events += "disconnect" },
            )

        assertEquals(NativeInputReleaseSubmission.ACCEPTED, result)
        assertEquals(listOf("release:4", "disconnect"), events)
    }

    @Test
    fun `coordinator skips empty and stale release but still finishes boundary`() {
        val state = NativeInputSessionState<TestClient>()
        val coordinator = NativeInputReleaseCoordinator(state)
        val client = TestClient("current")
        val events = mutableListOf<String>()
        state.admit(client, 6)

        assertEquals(
            NativeInputReleaseSubmission.NOT_NEEDED,
            coordinator.completeBoundary(client, 6, { events += "submit-empty"; true }) { events += "empty-done" },
        )
        assertEquals(
            NativeInputReleaseSubmission.NOT_NEEDED,
            coordinator.completeBoundary(client, 5, { events += "submit-stale"; true }) { events += "stale-done" },
        )
        assertEquals(listOf("empty-done", "stale-done"), events)
    }

    @Test
    fun `rejected release still performs disconnect action`() {
        val state = NativeInputSessionState<TestClient>()
        val coordinator = NativeInputReleaseCoordinator(state)
        val client = TestClient("current")
        val events = mutableListOf<String>()
        state.admit(client, 8)
        state.recordKey(client, 8, usbHidUsage = 0x04, pressed = true)

        val result =
            coordinator.completeBoundary(
                client,
                8,
                submitRelease = { events += "release-rejected"; false },
                afterRelease = { events += "disconnect" },
            )

        assertEquals(NativeInputReleaseSubmission.REJECTED, result)
        assertEquals(listOf("release-rejected", "disconnect"), events)
    }

    @Test
    fun `release batch contains sorted key ups then one pointer terminal`() {
        var keyBuilds = 0
        var pointerBuilds = 0
        val events =
            NativeInputReleaseBatch.build(
                release =
                    NativeInputReleasePlan(
                        pressedKeyUsages = listOf(0x04, 0x1d),
                        pointer = NativePointerSnapshot(0.7f, 0.2f),
                    ),
                keyUp = { usage -> "key-up:${usage.also { keyBuilds++ }}" },
                pointerTerminal = { pointer ->
                    pointerBuilds++
                    "pointer-terminal:${pointer.x},${pointer.y}:mask=0"
                },
            )

        assertEquals(
            listOf("key-up:4", "key-up:29", "pointer-terminal:0.7,0.2:mask=0"),
            events,
        )
        assertEquals(2, keyBuilds)
        assertEquals(1, pointerBuilds)
    }

    private data class TestClient(
        val value: String,
    )
}
