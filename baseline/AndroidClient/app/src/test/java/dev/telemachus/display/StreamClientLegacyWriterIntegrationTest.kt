package dev.telemachus.display

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class StreamClientLegacyWriterIntegrationTest {
    @Test
    fun consecutiveLegacyConfigurationsSupersedeSurfaceWaitAndRequestOneKeyframe() = runBlocking {
        ServerSocket(0).use { server ->
            val firstConfigurationObserved = CountDownLatch(1)
            val bothConfigurationsObserved = CountDownLatch(2)
            val surfaceReady = AtomicBoolean()
            val configurations = Collections.synchronizedList(mutableListOf<Pair<Int, Int>>())
            val lifecycle =
                MainSessionDisplayLifecycle(
                    isCurrentSession = { true },
                    postToUi = { it() },
                    updateVideoConfiguration = { configuration ->
                        configurations += configuration.encodedWidth to configuration.encodedHeight
                        bothConfigurationsObserved.countDown()
                        if (configurations.size == 1) firstConfigurationObserved.countDown()
                    },
                    releaseDecoder = {},
                    configureDecoder = { _, _, publish, completion ->
                        if (surfaceReady.get()) {
                            assertTrue(publish { true })
                            completion(MainSessionDecoderConfigurationResult.Configured)
                        } else {
                            completion(MainSessionDecoderConfigurationResult.RetryWhenSurfaceReady)
                        }
                    },
                    updateDisplayGeometry = {},
                )
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        val input = DataInputStream(peer.getInputStream())
                        val output = DataOutputStream(peer.getOutputStream())
                        assertEquals(PROTOCOL_UPGRADE_BYTE, input.readUnsignedByte())
                        output.writeDisplayConfiguration(1920, 1080, 0)
                        assertTrue(firstConfigurationObserved.await(3, TimeUnit.SECONDS))
                        output.writeDisplayConfiguration(1280, 720, 90)

                        var keyframeRequests = 0
                        while (keyframeRequests == 0) {
                            if (input.readUnsignedByte() == MESSAGE_KEYFRAME_REQUEST) {
                                input.readUnsignedByte()
                                keyframeRequests++
                            }
                        }
                        peer.soTimeout = 200
                        assertTrue(runCatching { input.readUnsignedByte() }.exceptionOrNull() is SocketTimeoutException)
                        assertEquals(1, keyframeRequests)
                        peer.getOutputStream().write(MESSAGE_SERVER_SHUTDOWN)
                        peer.getOutputStream().flush()
                    }
                }
            val client =
                StreamClient("127.0.0.1", server.localPort).apply {
                    onVideoConfiguration = lifecycle::onVideoConfiguration
                    onDisplayGeometry = lifecycle::onDisplayGeometry
                }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(bothConfigurationsObserved.await(3, TimeUnit.SECONDS))
            surfaceReady.set(true)
            lifecycle.onSurfaceReady()

            withTimeout(4_000) { serverJob.await() }
            withTimeout(4_000) { clientJob.await() }
            assertEquals(listOf(1920 to 1080, 1280 to 720), configurations)
        }
    }

    @Test
    fun serverShutdownInvalidatesPendingLegacyDecoderCommit() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val ended = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        DataOutputStream(peer.getOutputStream()).apply {
                            writeByte(MESSAGE_DISPLAY_CONFIG)
                            writeInt(1920)
                            writeInt(1080)
                            writeInt(0)
                            flush()
                        }
                        assertTrue(configurationRequested.await(3, TimeUnit.SECONDS))
                        peer.getOutputStream().write(MESSAGE_SERVER_SHUTDOWN)
                        peer.getOutputStream().flush()
                    }
                }
            val client =
                StreamClient("127.0.0.1", server.localPort).apply {
                    onVideoConfiguration = { _, pendingCommit ->
                        commit.set(pendingCommit)
                        configurationRequested.countDown()
                    }
                    onSessionEnded = { ended.countDown() }
                }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(ended.await(3, TimeUnit.SECONDS))
            var published = false
            assertFalse(
                checkNotNull(commit.get()).tryPublish {
                    published = true
                    true
                },
            )
            assertFalse(published)
            checkNotNull(commit.get()).complete(StreamVideoConfigurationDecision.ACCEPTED)

            withTimeout(4_000) { serverJob.await() }
            withTimeout(4_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun deviceInfoAndTouchRemainWholeOnTheSingleWriter() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val requestDeviceInfo = CountDownLatch(1)
            val ended = CountDownLatch(1)
            var terminal: SessionFailure? = null
            var writerFailure: String? = null
            val reconnect = CountDownLatch(1)
            val shutdownCallbacks = AtomicInteger()
            val retryCancellations = AtomicInteger()
            val shutdownActions = AtomicInteger()
            val retryCoordinator =
                SessionAutomaticRetryCoordinator(
                    postAutomaticRetry = {},
                    cancelPendingAutomaticRetry = { retryCancellations.incrementAndGet() },
                    handleServerShutdown = { shutdownActions.incrementAndGet() },
                )
            val receivedTypes = mutableListOf<Int>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        val input = DataInputStream(peer.getInputStream())
                        assertEquals(PROTOCOL_UPGRADE_BYTE, input.readUnsignedByte())
                        DataOutputStream(peer.getOutputStream()).apply {
                            writeByte(MESSAGE_DISPLAY_CONFIG)
                            writeInt(1920)
                            writeInt(1080)
                            writeInt(0)
                            flush()
                        }
                        assertTrue(requestDeviceInfo.await(3, TimeUnit.SECONDS))
                        peer.getOutputStream().write(MESSAGE_DEVICE_INFO_CAPABILITY)
                        peer.getOutputStream().flush()
                        while (!(receivedTypes.contains(MESSAGE_CLIENT_DEVICE_INFO) &&
                                    receivedTypes.contains(MESSAGE_TOUCH))) {
                            when (val type = input.readUnsignedByte()) {
                                MESSAGE_CLIENT_AVC_ONLY,
                                MESSAGE_FRAME_METADATA,
                                MESSAGE_DEVICE_INFO_CAPABILITY,
                                -> receivedTypes += type
                                MESSAGE_CLIENT_DEVICE_INFO -> {
                                    input.readNBytes(65)
                                    receivedTypes += type
                                }
                                MESSAGE_TOUCH -> {
                                    val pointers = input.readUnsignedByte()
                                    assertEquals(1, pointers)
                                    input.readNBytes(12)
                                    receivedTypes += type
                                }
                                else -> error("interleaved or unknown client byte: $type")
                            }
                        }
                        peer.getOutputStream().write(MESSAGE_SERVER_SHUTDOWN)
                        peer.getOutputStream().flush()
                    }
                }
            val client =
                StreamClient("127.0.0.1", server.localPort).apply {
                    onConnectionStatus = { connected -> if (connected) ready.countDown() }
                    onSessionEnded = {
                        retryCoordinator.onSessionEnded(it)
                        terminal = it
                        ended.countDown()
                    }
                    onServerShutdown = {
                        retryCoordinator.onServerShutdown()
                        shutdownCallbacks.incrementAndGet()
                    }
                    onReconnectSuggested = { reconnect.countDown() }
                    onWriteFailure = { writerFailure = it }
                }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            if (!ready.await(3, TimeUnit.SECONDS)) {
                assertTrue("session ended before ready: $terminal", ended.await(100, TimeUnit.MILLISECONDS))
                error("session ended before ready: $terminal, writer=$writerFailure")
            }
            requestDeviceInfo.countDown()
            client.sendTouch(0.25f, 0.75f, action = 1)

            withTimeout(4_000) { serverJob.await() }
            withTimeout(4_000) { clientJob.await() }
            assertEquals(1, receivedTypes.count { it == MESSAGE_CLIENT_DEVICE_INFO })
            assertEquals(1, receivedTypes.count { it == MESSAGE_TOUCH })
            assertEquals(SessionFailureKind.SERVER_SHUTDOWN, terminal?.kind)
            client.disconnect()
            assertEquals(1, shutdownCallbacks.get())
            assertEquals(1, retryCancellations.get())
            assertEquals(1, shutdownActions.get())
            assertFalse(reconnect.await(200, TimeUnit.MILLISECONDS))
        }
    }

    @Test
    fun deviceInfoWriteFailureFailsClosedWithTypedSessionFailure() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val requestDeviceInfo = CountDownLatch(1)
            val writerFailed = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        DataOutputStream(peer.getOutputStream()).apply {
                            writeByte(MESSAGE_DISPLAY_CONFIG)
                            writeInt(1920)
                            writeInt(1080)
                            writeInt(0)
                            flush()
                        }
                        assertTrue(requestDeviceInfo.await(3, TimeUnit.SECONDS))
                        peer.getOutputStream().write(MESSAGE_DEVICE_INFO_CAPABILITY)
                        peer.getOutputStream().flush()
                        assertTrue(writerFailed.await(3, TimeUnit.SECONDS))
                        // Keep the inbound direction open past one client read poll so
                        // pending WRITE_FAILED, rather than peer EOF, ends the session.
                        Thread.sleep(1_200)
                    }
                }
            val ended = CountDownLatch(1)
            var failure: SessionFailure? = null
            var writerFailure: String? = null
            val client =
                StreamClient(
                    "127.0.0.1",
                    server.localPort,
                    socketFactory = { FailOnDeviceInfoSocket() },
                ).apply {
                    onSessionEnded = {
                        failure = it
                        ended.countDown()
                    }
                    onWriteFailure = {
                        writerFailure = it
                        writerFailed.countDown()
                    }
                    onConnectionStatus = { connected -> if (connected) ready.countDown() }
                }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(ready.await(3, TimeUnit.SECONDS))
            requestDeviceInfo.countDown()
            assertTrue(ended.await(3, TimeUnit.SECONDS))
            withTimeout(4_000) { clientJob.await() }
            withTimeout(4_000) { serverJob.await() }
            assertEquals("writer=$writerFailure detail=${failure?.detail}", SessionFailureKind.WRITE_FAILED, failure?.kind)
            assertTrue(checkNotNull(failure).retryable)
        }
    }

    private class FailOnDeviceInfoSocket : Socket() {
        override fun getOutputStream(): OutputStream =
            object : OutputStream() {
                private val delegate = super@FailOnDeviceInfoSocket.getOutputStream()

                override fun write(value: Int) = delegate.write(value)

                override fun write(bytes: ByteArray, offset: Int, length: Int) {
                    if (length == 66 && bytes[offset].toInt() and 0xff == MESSAGE_CLIENT_DEVICE_INFO) {
                        throw IOException("injected device-info write failure")
                    }
                    delegate.write(bytes, offset, length)
                }

                override fun flush() = delegate.flush()
            }
    }

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
        private const val MESSAGE_DISPLAY_CONFIG = 1
        private const val MESSAGE_TOUCH = 2
        private const val MESSAGE_SERVER_SHUTDOWN = 3
        private const val MESSAGE_KEYFRAME_REQUEST = 7
        private const val MESSAGE_FRAME_METADATA = 8
        private const val MESSAGE_CLIENT_AVC_ONLY = 9
        private const val MESSAGE_CLIENT_DEVICE_INFO = 11
        private const val MESSAGE_DEVICE_INFO_CAPABILITY = 12
    }

    private fun DataOutputStream.writeDisplayConfiguration(
        width: Int,
        height: Int,
        rotation: Int,
    ) {
        writeByte(MESSAGE_DISPLAY_CONFIG)
        writeInt(width)
        writeInt(height)
        writeInt(rotation)
        flush()
    }
}
