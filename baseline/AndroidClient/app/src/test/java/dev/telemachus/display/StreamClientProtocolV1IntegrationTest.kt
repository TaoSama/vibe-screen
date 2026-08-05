package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.TouchSample
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisconnectNotice
import dev.vibescreen.protocol.v1.DisplayChanged
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.VideoConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.net.Socket
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class StreamClientProtocolV1IntegrationTest {
    @Test
    fun initialAndRuntimeRotationThenShutdownStayFramedAndTyped() = runBlocking {
        ServerSocket(0).use { server ->
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(peer, initialRotation = 90)
                        write(peer, displayChanged(id = 6, rotation = 270))
                        write(peer, disconnect(id = 7))
                    }
                }
            val rotations = Collections.synchronizedList(mutableListOf<Int>())
            val ended = CountDownLatch(1)
            var failure: SessionFailure? = null
            val reconnect = CountDownLatch(1)
            val shutdownCallbacks = AtomicInteger()
            val retryCancellations = AtomicInteger()
            val shutdownActions = AtomicInteger()
            val terminationOrder = Collections.synchronizedList(mutableListOf<String>())
            val retryCoordinator =
                SessionAutomaticRetryCoordinator(
                    postAutomaticRetry = {},
                    cancelPendingAutomaticRetry = { retryCancellations.incrementAndGet() },
                    handleServerShutdown = { shutdownActions.incrementAndGet() },
                )
            val client = StreamClient("127.0.0.1", server.localPort)
            client.apply {
                onDisplaySize = { _, _, rotation -> rotations += rotation }
                onSessionEnded = {
                    retryCoordinator.onSessionEnded(it)
                    failure = it
                    terminationOrder += "session_ended"
                    ended.countDown()
                }
                onServerShutdown = {
                    retryCoordinator.onServerShutdown()
                    terminationOrder += "server_shutdown"
                    shutdownCallbacks.incrementAndGet()
                    client.disconnect()
                }
                onReconnectSuggested = { reconnect.countDown() }
            }

            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            withTimeout(4_000) { serverJob.await() }
            assertTrue(ended.await(2, TimeUnit.SECONDS))
            withTimeout(4_000) { clientJob.await() }

            assertEquals(listOf(90, 270), rotations)
            assertEquals(SessionFailureKind.SERVER_SHUTDOWN, failure?.kind)
            assertFalse(checkNotNull(failure).retryable)
            assertTrue(checkNotNull(failure).intentional)
            client.disconnect()
            assertEquals(listOf("session_ended", "server_shutdown"), terminationOrder)
            assertEquals(1, shutdownCallbacks.get())
            assertEquals(1, retryCancellations.get())
            assertEquals(1, shutdownActions.get())
            assertFalse(reconnect.await(200, TimeUnit.MILLISECONDS))
        }
    }

    @Test
    fun twoPointerMoveIsAnAtomicSchedulerBatchOnWire() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val samples = mutableListOf<Envelope>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(peer, initialRotation = 0)
                        ready.countDown()
                        repeat(2) {
                            samples += readEnvelope(peer)
                        }
                        write(peer, disconnect(id = 6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            assertTrue(ready.await(3, TimeUnit.SECONDS))

            client.sendMotionTouch(
                v1Samples =
                    listOf(
                        TouchSample(7, InputPhase.INPUT_PHASE_CHANGED, 0.2, 0.3),
                        TouchSample(9, InputPhase.INPUT_PHASE_CHANGED, 0.8, 0.7),
                    ),
                legacyAction = 1,
                legacyPointers = emptyList(),
            )

            withTimeout(4_000) { serverJob.await() }
            withTimeout(4_000) { clientJob.await() }
            assertEquals(listOf(7, 9), samples.map { it.touchEvent.pointerId })
            assertTrue(samples.all { it.touchEvent.phase == InputPhase.INPUT_PHASE_CHANGED })
            assertEquals(samples[0].messageId + 1, samples[1].messageId)
            assertEquals(samples[0].touchEvent.inputId + 1, samples[1].touchEvent.inputId)
        }
    }

    private fun completeHandshake(peer: Socket, initialRotation: Int) {
        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
        peer.getOutputStream().flush()
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, readEnvelope(peer).payloadCase)
        write(peer, hostHello(1))
        write(peer, sessionAccepted(2))
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, displayList(3))
        assertEquals(Envelope.PayloadCase.START_DISPLAY_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, startDisplay(4))
        write(peer, videoConfig(5, initialRotation))
        val result = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
        assertTrue(result.videoConfigResult.accepted)
    }

    private fun readEnvelope(peer: Socket): Envelope {
        val frame = ProtocolV1Framing.read(peer.getInputStream())
        assertEquals(ProtocolChannel.CONTROL, frame.channel)
        return Envelope.parseFrom(frame.payload)
    }

    private fun write(peer: Socket, envelope: Envelope) =
        ProtocolV1Framing.write(peer.getOutputStream(), ProtocolChannel.CONTROL, envelope.toByteArray())

    private fun hostHello(id: Long): Envelope =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello.newBuilder()
                    .setSelectedProtocol(1)
                    .addCapabilities(Capability.CAPABILITY_TOUCH)
                    .addCapabilities(Capability.CAPABILITY_TELEMETRY)
                    .addCodecs(Codec.CODEC_HEVC),
            ).build()

    private fun sessionAccepted(id: Long): Envelope =
        base(id)
            .setSessionAccepted(
                SessionAccepted.newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH)
                    .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id).setListDisplaysResponse(
            ListDisplaysResponse.newBuilder().addDisplays(display()),
        ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id).setStartDisplayResponse(
            StartDisplayResponse.newBuilder().setAccepted(true).setDisplay(display()).setStreamId(42),
        ).build()

    private fun videoConfig(id: Long, rotation: Int): Envelope =
        base(id).setVideoConfig(
            VideoConfig.newBuilder()
                .setConfigEpoch(3)
                .setCodec(Codec.CODEC_HEVC)
                .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                .setFramesPerSecond(60)
                .setBitrateKbps(12_000)
                .setStreamId(42)
                .setRotationDegrees(rotation),
        ).build()

    private fun displayChanged(id: Long, rotation: Int): Envelope =
        base(id).setDisplayChanged(
            DisplayChanged.newBuilder().setDisplay(display()).setRotationDegrees(rotation),
        ).build()

    private fun disconnect(id: Long): Envelope =
        base(id).setDisconnectNotice(
            DisconnectNotice.newBuilder().setReasonCode("host_shutdown").setMayResume(false),
        ).build()

    private fun display(): DisplayDescriptor =
        DisplayDescriptor.newBuilder()
            .setDisplayId("display-main")
            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
            .build()

    private fun base(id: Long): Envelope.Builder =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
        private val SESSION_ID = ByteString.copyFrom(ByteArray(16) { 1 })
    }
}
