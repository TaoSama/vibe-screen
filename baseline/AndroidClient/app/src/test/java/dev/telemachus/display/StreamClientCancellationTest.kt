package dev.telemachus.display

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.DataOutputStream
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamClientCancellationTest {
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
}
