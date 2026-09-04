package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class ReconnectCountdownPresentationPolicyTest {
    @Test
    fun `remaining seconds rounds up partial seconds`() {
        assertEquals(3, ReconnectCountdownPresentationPolicy.remainingSeconds(nowMs = 1_000L, deadlineMs = 3_001L))
        assertEquals(2, ReconnectCountdownPresentationPolicy.remainingSeconds(nowMs = 1_000L, deadlineMs = 3_000L))
    }

    @Test
    fun `remaining seconds keeps an actionable final second visible`() {
        assertEquals(1, ReconnectCountdownPresentationPolicy.remainingSeconds(nowMs = 3_000L, deadlineMs = 3_000L))
        assertEquals(1, ReconnectCountdownPresentationPolicy.remainingSeconds(nowMs = 4_000L, deadlineMs = 3_000L))
    }
}
