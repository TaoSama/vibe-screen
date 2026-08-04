package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.SessionRejected
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamClientProtocolFailureTest {
    @Test
    fun permanentRejectionReachesUiCallbackAndStopsReconnect() = runRejectedSession(retryable = false) { result ->
        assertEquals("device_revoked", result.reason)
        assertFalse(result.retryable)
        assertFalse(result.reconnectSuggested.await(200, TimeUnit.MILLISECONDS))
    }

    @Test
    fun retryableRejectionReachesUiCallbackAndSchedulesReconnect() = runRejectedSession(retryable = true) { result ->
        assertEquals("device_revoked", result.reason)
        assertTrue(result.retryable)
        assertTrue(result.reconnectSuggested.await(1, TimeUnit.SECONDS))
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
            var reason = ""
            var callbackRetryable = !retryable
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onProtocolFailure = { reportedReason, reportedRetryable, _ ->
                reason = reportedReason
                callbackRetryable = reportedRetryable
                protocolFailure.countDown()
            }
            client.onReconnectSuggested = { reconnect.countDown() }

            withTimeout(3_000) { client.connect() }
            withTimeout(3_000) { serverJob.await() }
            assertTrue(protocolFailure.await(1, TimeUnit.SECONDS))
            assertions(Result(reason, callbackRetryable, reconnect))
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
        val reason: String,
        val retryable: Boolean,
        val reconnectSuggested: CountDownLatch,
    )

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
    }
}
