package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class ReconnectBackoffTest {
    @Test
    fun growsExponentiallyAndCaps() {
        val backoff = ReconnectBackoff(initialDelayMs = 250L, maximumDelayMs = 1_000L, jitterRatio = 0.0)

        assertEquals(250L, backoff.nextDelayMs())
        assertEquals(500L, backoff.nextDelayMs())
        assertEquals(1_000L, backoff.nextDelayMs())
        assertEquals(1_000L, backoff.nextDelayMs())
        backoff.reset()
        assertEquals(250L, backoff.nextDelayMs())
    }
}
