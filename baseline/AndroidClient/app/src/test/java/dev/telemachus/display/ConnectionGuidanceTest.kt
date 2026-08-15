package dev.telemachus.display

import java.io.IOException
import java.net.SocketTimeoutException
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionGuidanceTest {
    @Test
    fun `refused connection includes Mac app and exact ADB recovery steps`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("Connection refused"), 54321)

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertTrue(guidance.status.contains("Mac app"))
        assertTrue(guidance.message.contains("Open Vibe Screen"))
        assertTrue(guidance.message.contains("adb connect <device-ip>:<wireless-adb-port>"))
        assertTrue(guidance.message.contains("adb reverse tcp:54321 tcp:54321"))
    }

    @Test
    fun `unreachable ADB route includes connect and exact reverse guidance`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("ENETUNREACH"), 60000)

        assertEquals(ConnectionFailureKind.NETWORK_UNREACHABLE, guidance.kind)
        assertEquals("ADB route unavailable", guidance.status)
        assertTrue(guidance.message.contains("wireless debugging"))
        assertTrue(guidance.message.contains("adb connect <device-ip>:<wireless-adb-port>"))
        assertTrue(guidance.message.contains("adb reverse tcp:60000 tcp:60000"))
    }

    @Test
    fun `timeout guidance names port and firewall`() {
        val guidance = ConnectionGuidanceFactory.from(SocketTimeoutException("connect timeout"), 54321)

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertTrue(guidance.message.contains("54321"))
        assertTrue(guidance.message.contains("firewall"))
        assertTrue(guidance.message.contains("adb reverse tcp:54321 tcp:54321"))
    }

    @Test
    fun `unknown failure mentions debugging and both ADB setup steps`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("something broke"), 54321)

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertTrue(guidance.message.contains("USB or wireless debugging"))
        assertTrue(guidance.message.contains("adb connect"))
        assertTrue(guidance.message.contains("adb reverse"))
        assertTrue(guidance.message.contains("54321"))
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
