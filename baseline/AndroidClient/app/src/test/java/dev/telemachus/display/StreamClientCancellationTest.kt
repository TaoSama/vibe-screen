package dev.telemachus.display

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.DataOutputStream
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamClientCancellationTest {
    @Test
    fun disconnectBeforeConnectPreventsSocketCreation() =
        runBlocking {
            ServerSocket(0).use { server ->
                server.soTimeout = 250
                val client = StreamClient("127.0.0.1", server.localPort)
                val statuses = mutableListOf<Boolean>()
                client.onConnectionStatus = { statuses += it }

                client.disconnect()
                client.connect()

                assertTrue(statuses.isEmpty())
                val accepted = runCatching { server.accept().use { } }.isSuccess
                assertFalse("pre-cancelled client opened a socket", accepted)
            }
        }

    @Test
    fun readySessionRejectsMalformedDisplayWithoutReconnectLoop() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                            DataOutputStream(socket.getOutputStream()).apply {
                                writeDisplay(1920, 1080, 0)
                                writeDisplay(1920, 1080, 45)
                                flush()
                            }
                        }
                    }
                val failures = mutableListOf<SessionFailure>()
                val retries = mutableListOf<Long>()
                StreamClient("127.0.0.1", server.localPort)
                    .apply {
                        onSessionEnded = { failures += it }
                        onReconnectSuggested = { retries += it }
                    }.connect()

                serverJob.await()
                assertEquals(SessionFailureKind.INVALID_DISPLAY, failures.single().kind)
                assertFalse(failures.single().retryable)
                assertTrue(retries.isEmpty())
            }
        }

    @Test
    fun unknownMessageIsNonRetryableAndPreservesType() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                            DataOutputStream(socket.getOutputStream()).apply {
                                writeDisplay(1920, 1080, 0)
                                writeByte(99)
                                flush()
                            }
                        }
                    }
                val failures = mutableListOf<SessionFailure>()
                StreamClient("127.0.0.1", server.localPort)
                    .apply { onSessionEnded = { failures += it } }
                    .connect()

                serverJob.await()
                assertEquals(SessionFailureKind.UNKNOWN_MESSAGE, failures.single().kind)
                assertTrue(failures.single().detail.contains("99"))
                assertFalse(failures.single().retryable)
            }
        }

    @Test
    fun readySessionEofRemainsRetryableWithSpecificReason() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                            DataOutputStream(socket.getOutputStream()).apply {
                                writeDisplay(1920, 1080, 0)
                                flush()
                            }
                        }
                    }
                val failures = mutableListOf<SessionFailure>()
                val retries = mutableListOf<Long>()
                StreamClient("127.0.0.1", server.localPort)
                    .apply {
                        onSessionEnded = { failures += it }
                        onReconnectSuggested = { retries += it }
                    }.connect()

                serverJob.await()
                assertEquals(SessionFailureKind.TRANSPORT_CLOSED, failures.single().kind)
                assertTrue(failures.single().retryable)
                assertTrue(failures.single().detail.isNotBlank())
                assertEquals(1, retries.size)
            }
        }

    @Test
    fun malformedDisplayConfigurationNeverMarksSessionReady() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                            DataOutputStream(socket.getOutputStream()).apply {
                                writeByte(1)
                                writeInt(0)
                                writeInt(1080)
                                writeInt(45)
                                flush()
                            }
                        }
                    }
                val statuses = mutableListOf<Boolean>()
                try {
                    StreamClient("127.0.0.1", server.localPort)
                        .apply { onConnectionStatus = { connected -> statuses += connected } }
                        .connect()
                    fail("Expected malformed display configuration to fail")
                } catch (expected: Exception) {
                    assertTrue(expected.message.orEmpty().contains("display configuration"))
                }

                serverJob.await()
                assertFalse(statuses.contains(true))
            }
        }

    @Test
    fun connectRejectsSocketThatClosesBeforeDisplayConfiguration() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                        }
                    }
                try {
                    StreamClient("127.0.0.1", server.localPort).connect()
                    fail("Expected a pre-display EOF to be propagated")
                } catch (expected: Exception) {
                    assertTrue(expected.message.orEmpty().contains("display configuration"))
                }
                serverJob.await()
                Unit
            }
        }

    @Test
    fun connectionBecomesReadyOnlyAfterDisplayConfiguration() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            socket.getInputStream().read()
                            DataOutputStream(socket.getOutputStream()).apply {
                                writeByte(1)
                                writeInt(1920)
                                writeInt(1080)
                                writeInt(0)
                                flush()
                            }
                        }
                    }
                val statuses = mutableListOf<Boolean>()
                StreamClient("127.0.0.1", server.localPort)
                    .apply { onConnectionStatus = { connected -> statuses += connected } }
                    .connect()

                serverJob.await()
                assertTrue(statuses.first())
                assertTrue(statuses.last().not())
            }
        }

    @Test
    fun connectPropagatesInitialFailureForActionableUi() =
        runBlocking {
            val unusedPort = ServerSocket(0).use { it.localPort }
            try {
                StreamClient("127.0.0.1", unusedPort).connect()
                fail("Expected the refused connection to be propagated")
            } catch (expected: Exception) {
                assertTrue(expected.message.orEmpty().isNotBlank())
            }
        }

    @Test
    fun disconnectCancelsPendingWirelessHandshake() =
        runBlocking {
            ServerSocket(0).use { server ->
                val accepted = CountDownLatch(1)
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use {
                            accepted.countDown()
                            it.getInputStream().read(ByteArray(256))
                            Thread.sleep(2_000)
                        }
                    }
                val client = StreamClient("127.0.0.1", server.localPort)
                val connectJob =
                    async(Dispatchers.IO) {
                        runCatching {
                            client.connectWireless(ByteArray(32), "test-device")
                        }
                    }

                assertTrue(withContext(Dispatchers.IO) { accepted.await(1, TimeUnit.SECONDS) })
                client.disconnect()
                withTimeout(1_000) {
                    connectJob.await()
                }
                serverJob.cancel()
            }
        }

    private fun DataOutputStream.writeDisplay(
        width: Int,
        height: Int,
        rotation: Int,
    ) {
        writeByte(1)
        writeInt(width)
        writeInt(height)
        writeInt(rotation)
    }
}
