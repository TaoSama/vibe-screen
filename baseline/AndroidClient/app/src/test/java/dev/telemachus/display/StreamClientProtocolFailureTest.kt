package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.SessionRejected
import dev.vibescreen.protocol.v1.SessionAccepted
import com.google.protobuf.ByteString
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamClientProtocolFailureTest {
    @Test
    fun permanentRejectionReachesUiCallbackAndStopsReconnect() = runRejectedSession(retryable = false) { result ->
        assertEquals(SessionFailureKind.SESSION_REJECTED, result.failure.kind)
        assertTrue(result.failure.detail.startsWith("device_revoked:"))
        assertFalse(result.failure.retryable)
        assertFalse(result.reconnectSuggested.await(200, TimeUnit.MILLISECONDS))
    }

    @Test
    fun retryableRejectionReachesUiCallbackAndSchedulesReconnect() = runRejectedSession(retryable = true) { result ->
        assertEquals(SessionFailureKind.SESSION_REJECTED, result.failure.kind)
        assertTrue(result.failure.detail.startsWith("device_revoked:"))
        assertTrue(result.failure.retryable)
        assertTrue(result.reconnectSuggested.await(1, TimeUnit.SECONDS))
    }

    @Test
    fun malformedEnvelopeReachesUiAndStopsReconnect() =
        runMalformedPeerFrame(
            payload = byteArrayOf(0x80.toByte()),
            expectedReason = "invalid_envelope",
        )

    @Test
    fun malformedMediaReachesUiAndStopsReconnect() =
        runMalformedPeerFrame(
            payload = byteArrayOf(0),
            channel = ProtocolChannel.VIDEO,
            expectedReason = "invalid_media_payload",
        )

    @Test
    fun invalidMediaHeaderReachesUiAndStopsReconnect() =
        runBlocking {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                            peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                            peer.getOutputStream().flush()
                            ProtocolV1Framing.read(peer.getInputStream())
                            write(peer, hostHello())
                            write(
                                peer,
                                Envelope.newBuilder()
                                    .setProtocolVersion(1)
                                    .setMessageId(2)
                                    .setSessionAccepted(
                                        SessionAccepted.newBuilder()
                                            .setSessionId(ByteString.copyFrom(ByteArray(16) { 1 }))
                                            .setSessionEpoch(1)
                                            .addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH)
                                            .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY),
                                    ).build(),
                            )
                            ProtocolV1Framing.read(peer.getInputStream())
                            val media =
                                ProtocolV1Framing.encodeVideo(
                                    MediaPacketHeader.newBuilder().setPayloadLength(1).build(),
                                    byteArrayOf(1),
                                )
                            ProtocolV1Framing.write(peer.getOutputStream(), ProtocolChannel.VIDEO, media)
                        }
                    }
                val callback = CountDownLatch(1)
                val reconnect = CountDownLatch(1)
                var reportedFailure: SessionFailure? = null
                val client = StreamClient("127.0.0.1", server.localPort)
                client.onSessionEnded = { failure ->
                    reportedFailure = failure
                    callback.countDown()
                }
                client.onReconnectSuggested = { reconnect.countDown() }

                runCatching { withTimeout(3_000) { client.connect() } }
                withTimeout(3_000) { serverJob.await() }
                assertTrue(callback.await(1, TimeUnit.SECONDS))
                val failure = checkNotNull(reportedFailure)
                assertEquals(SessionFailureKind.INVALID_MEDIA_HEADER, failure.kind)
                assertTrue(failure.detail.startsWith("invalid_media_header:"))
                assertFalse(failure.retryable)
                assertFalse(reconnect.await(200, TimeUnit.MILLISECONDS))
            }
        }

    @Test
    fun invalidFrameChannelReachesUiAndStopsReconnect() =
        runMalformedPeerFrame(
            rawFrame = byteArrayOf(99, 0, 0, 0, 0),
            expectedReason = "invalid_frame",
        )

    @Test
    fun truncatedFrameReachesUiAndStopsReconnect() =
        runMalformedPeerFrame(
            rawFrame = byteArrayOf(ProtocolChannel.CONTROL.wireValue.toByte(), 0, 0),
            expectedReason = "invalid_frame",
        )

    private fun runMalformedPeerFrame(
        payload: ByteArray? = null,
        rawFrame: ByteArray? = null,
        channel: ProtocolChannel = ProtocolChannel.CONTROL,
        expectedReason: String,
    ) = runBlocking {
        ServerSocket(0).use { server ->
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                        peer.getOutputStream().flush()
                        ProtocolV1Framing.read(peer.getInputStream())
                        val malformed =
                            rawFrame ?: ByteBuffer
                                .allocate(5 + checkNotNull(payload).size)
                                .order(ByteOrder.BIG_ENDIAN)
                                .put(channel.wireValue.toByte())
                                .putInt(payload.size)
                                .put(payload)
                                .array()
                        peer.getOutputStream().write(malformed)
                        peer.getOutputStream().flush()
                    }
                }
            val callback = CountDownLatch(1)
            val reconnect = CountDownLatch(1)
            var reportedFailure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onSessionEnded = { failure ->
                reportedFailure = failure
                callback.countDown()
            }
            client.onReconnectSuggested = { reconnect.countDown() }

            runCatching { withTimeout(3_000) { client.connect() } }
            withTimeout(3_000) { serverJob.await() }
            assertTrue(callback.await(1, TimeUnit.SECONDS))
            val failure = checkNotNull(reportedFailure)
            assertEquals(expectedKind(expectedReason), failure.kind)
            assertTrue(failure.detail.startsWith("$expectedReason:"))
            assertFalse(failure.retryable)
            assertFalse(reconnect.await(200, TimeUnit.MILLISECONDS))
        }
    }

    private fun runRejectedSession(
        retryable: Boolean,
        assertions: (Result) -> Unit,
    ) = runBlocking {
        ServerSocket(0).use { server ->
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                        peer.getOutputStream().flush()
                        val hello = ProtocolV1Framing.read(peer.getInputStream())
                        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, Envelope.parseFrom(hello.payload).payloadCase)
                        write(peer, hostHello())
                        write(peer, rejection(retryable))
                    }
                }
            val protocolFailure = CountDownLatch(1)
            val reconnect = CountDownLatch(1)
            var reportedFailure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onSessionEnded = { failure ->
                reportedFailure = failure
                protocolFailure.countDown()
            }
            client.onReconnectSuggested = { reconnect.countDown() }

            runCatching { withTimeout(3_000) { client.connect() } }
            withTimeout(3_000) { serverJob.await() }
            assertTrue(protocolFailure.await(1, TimeUnit.SECONDS))
            assertions(Result(checkNotNull(reportedFailure), reconnect))
        }
    }

    private fun write(
        peer: java.net.Socket,
        envelope: Envelope,
    ) = ProtocolV1Framing.write(peer.getOutputStream(), ProtocolChannel.CONTROL, envelope.toByteArray())

    private fun hostHello(): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(1)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .addCapabilities(Capability.CAPABILITY_TOUCH)
                    .addCapabilities(Capability.CAPABILITY_TELEMETRY)
                    .addCodecs(Codec.CODEC_HEVC),
            ).build()

    private fun rejection(retryable: Boolean): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(2)
            .setSessionRejected(
                SessionRejected
                    .newBuilder()
                    .setReasonCode("device_revoked")
                    .setMessage("Pair this device again")
                    .setRetryable(retryable),
            ).build()

    private data class Result(
        val failure: SessionFailure,
        val reconnectSuggested: CountDownLatch,
    )

    private fun expectedKind(reason: String): SessionFailureKind =
        when (reason) {
            "invalid_frame" -> SessionFailureKind.INVALID_FRAME
            "invalid_envelope" -> SessionFailureKind.INVALID_ENVELOPE
            "invalid_media_payload" -> SessionFailureKind.INVALID_MEDIA_PAYLOAD
            else -> error("Unexpected Protocol v1 failure reason: $reason")
        }

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
    }
}
