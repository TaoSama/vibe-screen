package dev.telemachus.display

import java.io.IOException
import java.net.SocketTimeoutException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionGuidanceTest {
    @Test
    fun `usb refused connection includes Mac app and exact ADB recovery steps`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("Connection refused"), 54321, ConnectionMode.USB)

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertTrue(guidance.status.contains("Mac app"))
        assertTrue(guidance.message.contains("Open Vibe Screen"))
        assertTrue(guidance.message.contains("adb connect <device-ip>:<wireless-adb-port>"))
        assertTrue(guidance.message.contains("adb reverse tcp:54321 tcp:54321"))
    }

    @Test
    fun `usb unreachable ADB route includes connect and exact reverse guidance`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("ENETUNREACH"), 60000, ConnectionMode.USB)

        assertEquals(ConnectionFailureKind.NETWORK_UNREACHABLE, guidance.kind)
        assertEquals("ADB route unavailable", guidance.status)
        assertTrue(guidance.message.contains("wireless debugging"))
        assertTrue(guidance.message.contains("adb connect <device-ip>:<wireless-adb-port>"))
        assertTrue(guidance.message.contains("adb reverse tcp:60000 tcp:60000"))
    }

    @Test
    fun `usb timeout guidance names port and firewall`() {
        val guidance = ConnectionGuidanceFactory.from(SocketTimeoutException("connect timeout"), 54321, ConnectionMode.USB)

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertTrue(guidance.message.contains("54321"))
        assertTrue(guidance.message.contains("firewall"))
        assertTrue(guidance.message.contains("adb reverse tcp:54321 tcp:54321"))
    }

    @Test
    fun `usb unknown failure mentions debugging and both ADB setup steps`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("something broke"), 54321, ConnectionMode.USB)

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertTrue(guidance.message.contains("USB or wireless debugging"))
        assertTrue(guidance.message.contains("adb connect"))
        assertTrue(guidance.message.contains("adb reverse"))
        assertTrue(guidance.message.contains("54321"))
    }

    @Test
    fun `wireless refused connection omits ADB and suggests network check`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("Connection refused"), 54321, ConnectionMode.WIRELESS)

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("same"))
        assertTrue(guidance.message.contains("network"))
        assertTrue(guidance.message.contains("54321"))
    }

    @Test
    fun `wireless unreachable omits ADB and suggests same Wi-Fi`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("ENETUNREACH"), 54321, ConnectionMode.WIRELESS)

        assertEquals(ConnectionFailureKind.NETWORK_UNREACHABLE, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("Wi-Fi"))
        assertTrue(guidance.message.contains("54321"))
    }

    @Test
    fun `wireless timeout omits ADB and suggests network and firewall`() {
        val guidance = ConnectionGuidanceFactory.from(SocketTimeoutException("connect timeout"), 54321, ConnectionMode.WIRELESS)

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("firewall"))
        assertTrue(guidance.message.contains("54321"))
    }

    @Test
    fun `wireless unknown failure omits ADB and suggests network check`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("something broke"), 54321, ConnectionMode.WIRELESS)

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("network"))
        assertTrue(guidance.message.contains("54321"))
    }

    @Test
    fun `internet refused connection omits ADB and suggests a fresh session profile`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("Connection refused"), 54321, ConnectionMode.INTERNET)

        assertEquals(ConnectionFailureKind.HOST_NOT_RUNNING, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("session profile"))
    }

    @Test
    fun `internet unreachable omits ADB and suggests internet check`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("ENETUNREACH"), 54321, ConnectionMode.INTERNET)

        assertEquals(ConnectionFailureKind.NETWORK_UNREACHABLE, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("internet"))
        assertTrue(guidance.message.contains("session profile"))
    }

    @Test
    fun `internet timeout omits ADB and suggests a fresh session profile`() {
        val guidance = ConnectionGuidanceFactory.from(SocketTimeoutException("connect timeout"), 54321, ConnectionMode.INTERNET)

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("internet"))
        assertTrue(guidance.message.contains("session profile"))
    }

    @Test
    fun `internet unknown failure omits ADB and suggests a fresh session profile`() {
        val guidance = ConnectionGuidanceFactory.from(IOException("something broke"), 54321, ConnectionMode.INTERNET)

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("session profile"))
    }

    @Test
    fun `protocol failure stops retry with upgrade guidance regardless of mode`() {
        val failure = SessionFailure.protocol(SessionFailureKind.UNKNOWN_MESSAGE, "Unknown message type: 99")
        val guidanceByMode =
            ConnectionMode.entries.map { mode ->
                ConnectionGuidanceFactory.from(failure, 54321, mode)
            }

        assertTrue(guidanceByMode.all { it == guidanceByMode.first() })
        assertEquals(ConnectionFailureKind.INCOMPATIBLE_SESSION, guidanceByMode.first().kind)
        assertTrue(guidanceByMode.first().message.contains("Update Vibe Screen"))
        assertTrue(guidanceByMode.first().message.contains("99"))
    }

    @Test
    fun `wireless heartbeat failure delegates to timeout guidance without ADB`() {
        val guidance =
            ConnectionGuidanceFactory.from(
                SessionFailure.heartbeat("heartbeat timeout"),
                54321,
                ConnectionMode.WIRELESS,
            )

        assertEquals(ConnectionFailureKind.TIMEOUT, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("firewall"))
    }

    @Test
    fun `wireless transport failure delegates to unknown guidance without ADB`() {
        val guidance =
            ConnectionGuidanceFactory.from(
                SessionFailure.transport("eof"),
                54321,
                ConnectionMode.WIRELESS,
            )

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("network"))
    }

    @Test
    fun `wireless write failure delegates to unknown guidance without ADB`() {
        val guidance =
            ConnectionGuidanceFactory.from(
                SessionFailure.write("broken pipe"),
                54321,
                ConnectionMode.WIRELESS,
            )

        assertEquals(ConnectionFailureKind.UNKNOWN, guidance.kind)
        assertNoAdbReferences(guidance.message)
        assertTrue(guidance.message.contains("network"))
    }

    private fun assertNoAdbReferences(message: String) {
        assertFalse("message must not mention adb: $message", message.contains("adb", ignoreCase = true))
        assertFalse("message must not mention USB: $message", message.contains("USB", ignoreCase = true))
        assertFalse("message must not mention reverse: $message", message.contains("reverse", ignoreCase = true))
    }
}
