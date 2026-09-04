package dev.telemachus.display

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionFailureTest {
    @Test
    fun `transport and heartbeat failures remain retryable`() {
        assertTrue(SessionFailure.transport("eof").retryable)
        assertTrue(SessionFailure.heartbeat("timeout").retryable)
        assertTrue(SessionFailure.write("broken pipe").retryable)
        assertTrue(SessionFailure.hostNotRunning().retryable)
    }

    @Test
    fun `protocol and backpressure failures stop reconnect loops`() {
        assertFalse(
            SessionFailure.protocol(SessionFailureKind.INVALID_DISPLAY, "bad rotation").retryable,
        )
        assertFalse(
            SessionFailure.protocol(SessionFailureKind.OUTBOUND_BACKPRESSURE, "queue full").retryable,
        )
    }
}
