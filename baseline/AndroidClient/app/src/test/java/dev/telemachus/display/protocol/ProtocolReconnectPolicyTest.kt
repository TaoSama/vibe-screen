package dev.telemachus.display.protocol

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class ProtocolReconnectPolicyTest {
    @Test
    fun retryableHostFailureSchedulesReconnect() {
        assertTrue(ProtocolReconnectPolicy.shouldReconnect(failure(retryable = true), stopRequested = false))
    }

    @Test
    fun permanentHostFailureAndUserStopNeverReconnect() {
        assertFalse(ProtocolReconnectPolicy.shouldReconnect(failure(retryable = false), stopRequested = false))
        assertFalse(ProtocolReconnectPolicy.shouldReconnect(IOException("network"), stopRequested = true))
    }

    private fun failure(retryable: Boolean) =
        ProtocolV1Failure(
            reason = "host_policy",
            retryable = retryable,
            source = ProtocolV1Failure.Source.SESSION_REJECTED,
            message = "host policy",
        )
}
