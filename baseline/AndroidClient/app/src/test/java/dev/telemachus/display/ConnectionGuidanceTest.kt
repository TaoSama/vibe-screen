package dev.telemachus.display

import java.io.IOException
import java.net.SocketTimeoutException
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionGuidanceTest {
    @Test
    fun `refused connection tells user to open Mac app`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("Connection refused"), 54321)

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertTrue(guidance.status.contains("Mac app"))
        assertTrue(guidance.message.contains("Open Vibe Screen"))
    }

    @Test
    fun `unreachable USB route includes exact reverse command`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("ENETUNREACH"), 60000)

        assertEquals(ConnectionFailureKind.NETWORK_UNREACHABLE, guidance.kind)
        assertTrue(guidance.message.contains("adb reverse tcp:60000 tcp:60000"))
    }

    @Test
    fun `timeout guidance names port and firewall`() {
        val guidance = ConnectionGuidanceFactory.from(SocketTimeoutException("connect timeout"), 54321)

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertTrue(guidance.message.contains("54321"))
        assertTrue(guidance.message.contains("firewall"))
    }

    @Test
    fun `protocol failure stops retry with upgrade guidance`() {
        val guidance =
            ConnectionGuidanceFactory.from(
                SessionFailure.protocol(SessionFailureKind.UNKNOWN_MESSAGE, "Unknown message type: 99"),
                54321,
            )

        assertEquals(ConnectionFailureKind.INCOMPATIBLE_SESSION, guidance.kind)
        assertTrue(guidance.message.contains("Update Vibe Screen"))
        assertTrue(guidance.message.contains("99"))
    }
}
