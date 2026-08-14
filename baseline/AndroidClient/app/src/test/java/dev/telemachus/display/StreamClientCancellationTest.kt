package dev.telemachus.display

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.asCoroutineDispatcher
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
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.SocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class StreamClientCancellationTest {
    @Test
    fun invalidLocalWirelessCredentialsNeverOpenSocket() =
        runBlocking {
            ServerSocket(0).use { server ->
                server.soTimeout = 250
                val failures = mutableListOf<SessionFailure>()
                val client =
                    StreamClient("127.0.0.1", server.localPort).apply {
                        onSessionEnded = { failures += it }
                    }

                try {
                    client.connectWireless(ByteArray(31), "test-device")
                    fail("Expected invalid local credentials")
                } catch (expected: StreamClient.WirelessConnectError.ProtocolError) {
                    Unit
                }

                val accepted = runCatching { server.accept().use { } }.isSuccess
                assertFalse("invalid local credentials opened a socket", accepted)
                assertTrue(failures.isEmpty())
            }
        }

    @Test
    fun wirelessOkStartupFailureClosesSocketAndEndsGenerationOnce() =
        runBlocking {
            val deviceName = "test-device"
            val requestSize = 37 + deviceName.toByteArray().size
            ServerSocket(0).use { server ->
                val serverObservedEof = CountDownLatch(1)
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { socket ->
                            val request = socket.getInputStream().readNBytes(requestSize)
                            assertEquals(requestSize, request.size)
                            socket.getOutputStream().apply {
                                write(byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00))
                                flush()
                            }
                            while (socket.getInputStream().read() >= 0) {
                                // Wait until the client-owned termination path closes the socket.
                            }
                            serverObservedEof.countDown()
                        }
                    }
                val failures = mutableListOf<SessionFailure>()
                val retries = mutableListOf<Long>()
                val statuses = mutableListOf<Boolean>()
                val client =
                    StreamClient(
                        host = "127.0.0.1",
                        port = server.localPort,
                        socketFactory = { FailAfterBytesSocket(requestSize) },
                    ).apply {
                        onSessionEnded = { failures += it }
                        onReconnectSuggested = { retries += it }
                        onConnectionStatus = { statuses += it }
                    }

                client.connectWireless(ByteArray(32), deviceName)

                assertTrue(serverObservedEof.await(1, TimeUnit.SECONDS))
                serverJob.await()
                assertEquals(SessionFailureKind.WRITE_FAILED, failures.single().kind)
                assertTrue(failures.single().retryable)
                assertEquals(1, retries.size)
                assertEquals(listOf(false), statuses)
                client.disconnect()
                assertEquals(1, failures.size)
                assertEquals(1, retries.size)
            }
        }

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
        runWithServerDispatcher { serverDispatcher ->
            repeat(25) { iteration ->
                ServerSocket(0).use { server ->
                    val serverReady = CountDownLatch(1)
                    val serverJob =
                        async(serverDispatcher) {
                            serverReady.countDown()
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
                    val client =
                        StreamClient("127.0.0.1", server.localPort).apply {
                            onSessionEnded = { failures += it }
                            onReconnectSuggested = { retries += it }
                        }

                    assertTrue(
                        "iteration $iteration fake server did not start",
                        serverReady.await(1, TimeUnit.SECONDS),
                    )
                    val connectResult = runCatching { client.connect() }
                    withTimeout(2_000) { serverJob.await() }
                    connectResult.getOrThrow()
                    assertEquals("iteration $iteration", SessionFailureKind.INVALID_DISPLAY, failures.single().kind)
                    assertFalse("iteration $iteration", failures.single().retryable)
                    assertTrue("iteration $iteration", retries.isEmpty())
                }
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
                            repeat(3) { socket.getInputStream().read() }
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
                server.soTimeout = FAKE_SERVER_SYNC_TIMEOUT_MILLIS
                repeat(25) { iteration ->
                    val writerFailureObserved = CountDownLatch(1)
                    val displayReadyObserved = CountDownLatch(1)
                    val failureInjectionArmed = CountDownLatch(1)
                    val clientSocket =
                        FailAfterBytesSocket(
                            allowedBytes = 1,
                            failureInjectionArmed = failureInjectionArmed,
                        )
                    clientSocket.connectForTest(InetSocketAddress("127.0.0.1", server.localPort))
                    val failures = mutableListOf<SessionFailure>()
                    val retries = mutableListOf<Long>()
                    val client =
                        StreamClient(
                            "127.0.0.1",
                            server.localPort,
                            socketFactory = { clientSocket },
                        ).apply {
                            onWriteFailure = { writerFailureObserved.countDown() }
                            onConnectionStatus = { connected ->
                                if (connected) displayReadyObserved.countDown()
                            }
                            onSessionEnded = { failures += it }
                            onReconnectSuggested = { retries += it }
                        }

                    val socket = server.accept()
                    val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
                    socket.use {
                        assertEquals(0x0d, socket.getInputStream().read())
                        DataOutputStream(socket.getOutputStream()).apply {
                            writeDisplay(1920, 1080, 0)
                            flush()
                        }
                        failureInjectionArmed.countDown()
                        assertTrue(
                            "iteration $iteration did not inject the concurrent writer failure",
                            writerFailureObserved.await(FAKE_SERVER_SYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS),
                        )
                        assertTrue(
                            "iteration $iteration closed before the display became ready",
                            displayReadyObserved.await(FAKE_SERVER_SYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS),
                        )
                    }
                    val connectResult =
                        withTimeout(FAKE_SERVER_SYNC_TIMEOUT_MILLIS.toLong()) {
                            clientJob.await()
                        }
                    connectResult.getOrThrow()
                    assertEquals(
                        "iteration $iteration",
                        SessionFailureKind.TRANSPORT_CLOSED,
                        failures.single().kind,
                    )
                    assertTrue("iteration $iteration", failures.single().retryable)
                    assertTrue("iteration $iteration", failures.single().detail.isNotBlank())
                    assertEquals("iteration $iteration", 1, retries.size)
                }
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

    @Test
    fun disconnectClosesUsbFreshFallbackCandidateExactlyOnce() = runBlocking {
        ServerSocket(0).use { server ->
            val fresh = BlockingConnectSocket()
            val sockets = AtomicInteger()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { probe ->
                        assertEquals(0x0d, probe.getInputStream().read())
                        Thread.sleep(400)
                    }
                }
            val client =
                StreamClient(
                    "127.0.0.1",
                    server.localPort,
                    socketFactory = { if (sockets.getAndIncrement() == 0) Socket() else fresh },
                )
            val connectJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            assertTrue(fresh.connectEntered.await(2, TimeUnit.SECONDS))

            client.disconnect()
            withTimeout(2_000) { connectJob.await() }
            withTimeout(2_000) { serverJob.await() }
            assertEquals(1, fresh.closeCalls.get())
            assertEquals(2, sockets.get())
        }
    }

    @Test
    fun supersedingGenerationRejectsAndClosesUsbFreshFallbackCandidate() = runBlocking {
        ServerSocket(0).use { firstServer ->
            ServerSocket(0).use { secondServer ->
                val fresh = BlockingConnectSocket()
                val sockets = AtomicInteger()
                val firstServerJob =
                    async(Dispatchers.IO) {
                        firstServer.accept().use { probe ->
                            assertEquals(0x0d, probe.getInputStream().read())
                            Thread.sleep(400)
                        }
                    }
                val secondServerJob =
                    async(Dispatchers.IO) {
                        secondServer.accept().use { peer ->
                            assertEquals(0x0d, peer.getInputStream().read())
                            DataOutputStream(peer.getOutputStream()).apply {
                                writeDisplay(1920, 1080, 0)
                                flush()
                            }
                        }
                    }
                val first =
                    StreamClient(
                        "127.0.0.1",
                        firstServer.localPort,
                        socketFactory = { if (sockets.getAndIncrement() == 0) Socket() else fresh },
                    )
                val firstJob = async(Dispatchers.IO) { runCatching { first.connect() } }
                assertTrue(fresh.connectEntered.await(2, TimeUnit.SECONDS))

                runCatching { StreamClient("127.0.0.1", secondServer.localPort).connect() }
                fresh.allowConnectReturn()

                withTimeout(2_000) { firstJob.await() }
                withTimeout(2_000) { firstServerJob.await() }
                withTimeout(2_000) { secondServerJob.await() }
                assertEquals(1, fresh.closeCalls.get())
            }
        }
    }

    @Test
    fun disconnectDuringFreshWirelessAuthClosesCandidateExactlyOnce() = runBlocking {
        val deviceName = "fallback-auth"
        val requestSize = 37 + deviceName.toByteArray().size
        ServerSocket(0).use { server ->
            val fresh = BlockingAuthSocket()
            val sockets = AtomicInteger()
            val routedConnections = AtomicInteger()
            val connector =
                WirelessSocketConnector { socket, host, port, timeoutMs ->
                    routedConnections.incrementAndGet()
                    socket.connect(InetSocketAddress(host, port), timeoutMs)
                }
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { probe ->
                        assertEquals(requestSize, probe.getInputStream().readNBytes(requestSize).size)
                        probe.getOutputStream().apply {
                            write(byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00))
                            flush()
                        }
                        assertEquals(0x0d, probe.getInputStream().read())
                        Thread.sleep(400)
                    }
                }
            val client =
                StreamClient(
                    "127.0.0.1",
                    server.localPort,
                    socketFactory = { if (sockets.getAndIncrement() == 0) Socket() else fresh },
                    wirelessSocketConnector = connector,
                )
            val connectJob =
                async(Dispatchers.IO) {
                    runCatching { client.connectWireless(ByteArray(32), deviceName) }
                }
            assertTrue(fresh.authPaused.await(2, TimeUnit.SECONDS))

            client.disconnect()
            withTimeout(2_000) { connectJob.await() }
            withTimeout(2_000) { serverJob.await() }
            assertEquals(1, fresh.closeCalls.get())
            assertEquals(2, sockets.get())
            assertEquals(2, routedConnections.get())
        }
    }

    private fun runWithServerDispatcher(block: suspend CoroutineScope.(CoroutineDispatcher) -> Unit) =
        runBlocking {
            Executors
                .newSingleThreadExecutor { runnable ->
                    Thread(runnable, "StreamClientCancellationTestServer").apply { isDaemon = true }
                }.asCoroutineDispatcher()
                .use { serverDispatcher -> block(serverDispatcher) }
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

    private class FailAfterBytesSocket(
        private val allowedBytes: Int,
        private val failureInjectionArmed: CountDownLatch? = null,
    ) : Socket() {
        fun connectForTest(endpoint: SocketAddress) {
            super.connect(endpoint, FAKE_SERVER_SYNC_TIMEOUT_MILLIS)
        }

        override fun connect(
            endpoint: SocketAddress?,
            timeout: Int,
        ) {
            // This fake is single-use: preconnection removes listener-port churn
            // while the test exercises the later writer/EOF ordering.
            if (!isConnected) super.connect(endpoint, timeout)
        }

        override fun getOutputStream(): OutputStream =
            FailAfterBytesOutputStream(super.getOutputStream(), allowedBytes, failureInjectionArmed)

        override fun setSoTimeout(timeout: Int) {
            // This test exercises writer/EOF ordering, not the 250 ms upgrade
            // timeout. Keep CI scheduling stalls out of the fallback branch.
            super.setSoTimeout(maxOf(timeout, 2_000))
        }
    }

    private class FailAfterBytesOutputStream(
        private val delegate: OutputStream,
        private val allowedBytes: Int,
        private val failureInjectionArmed: CountDownLatch? = null,
    ) : OutputStream() {
        private var written = 0

        override fun write(value: Int) {
            if (written >= allowedBytes) throwInjectedFailure()
            delegate.write(value)
            written++
        }

        override fun write(
            bytes: ByteArray,
            offset: Int,
            length: Int,
        ) {
            if (written + length > allowedBytes) throwInjectedFailure()
            delegate.write(bytes, offset, length)
            written += length
        }

        private fun throwInjectedFailure(): Nothing {
            val armed = failureInjectionArmed
            if (armed != null && !armed.await(FAKE_SERVER_SYNC_TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
                throw IOException("fake server did not arm the writer failure")
            }
            throw IOException("injected capability failure")
        }

        override fun flush() = delegate.flush()
    }

    private class BlockingConnectSocket : Socket() {
        val connectEntered = CountDownLatch(1)
        val closeCalls = AtomicInteger()
        private val released = CountDownLatch(1)

        override fun connect(endpoint: SocketAddress?, timeout: Int) {
            connectEntered.countDown()
            released.await()
        }

        override fun close() {
            if (closeCalls.incrementAndGet() == 1) released.countDown()
        }

        fun allowConnectReturn() = released.countDown()

        override fun setTcpNoDelay(on: Boolean) = Unit

        override fun setSoTimeout(timeout: Int) = Unit
    }

    private class BlockingAuthSocket : Socket() {
        val authPaused = CountDownLatch(1)
        val closeCalls = AtomicInteger()
        private val released = CountDownLatch(1)
        private val output = ByteArrayOutputStream()
        private val response = byteArrayOf(0x53, 0x53, 0x57, 0x52, 0x00)
        private val input =
            object : InputStream() {
                private var offset = 0

                override fun read(): Int {
                    val target = ByteArray(1)
                    return if (read(target, 0, 1) < 0) -1 else target[0].toInt() and 0xff
                }

                override fun read(target: ByteArray, targetOffset: Int, length: Int): Int {
                    if (offset >= response.size) return -1
                    if (offset == response.lastIndex) {
                        authPaused.countDown()
                        released.await()
                    }
                    val count = minOf(length, if (offset == 0) response.size - 1 else 1)
                    response.copyInto(target, targetOffset, offset, offset + count)
                    offset += count
                    return count
                }
            }

        override fun connect(endpoint: SocketAddress?, timeout: Int) = Unit

        override fun getOutputStream(): OutputStream = output

        override fun getInputStream(): InputStream = input

        override fun close() {
            if (closeCalls.incrementAndGet() == 1) released.countDown()
        }

        override fun setTcpNoDelay(on: Boolean) = Unit

        override fun setSoTimeout(timeout: Int) = Unit
    }

    private companion object {
        const val FAKE_SERVER_SYNC_TIMEOUT_SECONDS = 5L
        const val FAKE_SERVER_SYNC_TIMEOUT_MILLIS = 5_000
    }
}
