package dev.telemachus.display

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamClientLegacyWriterIntegrationTest {
    @Test
    fun deviceInfoAndTouchRemainWholeOnTheSingleWriter() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val requestDeviceInfo = CountDownLatch(1)
            val ended = CountDownLatch(1)
            var terminal: SessionFailure? = null
            var writerFailure: String? = null
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
                        terminal = it
                        ended.countDown()
                    }
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
        }
    }

    @Test
    fun deviceInfoWriteFailureFailsClosedWithTypedSessionFailure() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val requestDeviceInfo = CountDownLatch(1)
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
                        while (peer.getInputStream().read() >= 0) {
                            // Wait for the typed writer-failure cleanup to close the socket.
                        }
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
                    onWriteFailure = { writerFailure = it }
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
        private const val MESSAGE_FRAME_METADATA = 8
        private const val MESSAGE_CLIENT_AVC_ONLY = 9
        private const val MESSAGE_CLIENT_DEVICE_INFO = 11
        private const val MESSAGE_DEVICE_INFO_CAPABILITY = 12
    }
}
