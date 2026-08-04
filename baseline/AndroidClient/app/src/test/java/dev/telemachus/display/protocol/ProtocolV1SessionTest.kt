package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.SessionRejected
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolV1SessionTest {
    @Test
    fun clientHelloPinsVersionRequiredCapabilityAndDeterministicGoldenFields() {
        val session = session()
        val hello = session.clientHello()

        assertEquals(1, hello.protocolVersion)
        assertEquals(1L, hello.messageId)
        assertEquals(1_000L, hello.sentAtMonotonicNs)
        assertEquals(1, hello.clientHello.supportedProtocols.minimum)
        assertEquals(1, hello.clientHello.supportedProtocols.maximum)
        assertEquals(listOf(Capability.CAPABILITY_TOUCH), hello.clientHello.requiredCapabilitiesList)
        assertEquals(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264), hello.clientHello.codecsList)
    }

    @Test
    fun handshakeDisplayAndVideoReachStreamingWithHostEpoch() {
        val session = session()
        session.clientHello()
        assertTrue(session.receive(hostHello(2)).isEmpty())
        val listRequest = session.receive(sessionAccepted(3)).single() as ProtocolV1Session.Action.Send
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        assertEquals(SESSION_ID, listRequest.envelope.sessionId)
        assertEquals(7L, listRequest.envelope.sessionEpoch)

        val start = session.receive(displayList(4)).single() as ProtocolV1Session.Action.Send
        assertEquals("display-main", start.envelope.startDisplayRequest.sourceDisplayId)
        assertTrue(session.receive(startDisplay(5)).isEmpty())

        val actions = session.receive(videoConfig(6))
        val result = actions[0] as ProtocolV1Session.Action.Send
        val configured = actions[1] as ProtocolV1Session.Action.VideoConfigured
        assertTrue(result.envelope.videoConfigResult.accepted)
        assertEquals(6L, result.envelope.correlationId)
        assertEquals(1920, configured.width)
        assertEquals(1080, configured.height)
        assertEquals(7L, configured.sessionEpoch)
        assertTrue(session.isStreaming)
    }

    @Test
    fun rejectsVersionCapabilitySessionEpochAndUnexpectedPayload() {
        val wrongVersion = session().also { it.clientHello() }
        assertInvalidPeerMessage {
            wrongVersion.receive(hostHello(2).toBuilder().setProtocolVersion(2).build())
        }

        val missingRequired = session().also { it.clientHello() }
        val hello = hostHello(2).toBuilder().setHostHello(HostHello.newBuilder().setSelectedProtocol(1)).build()
        assertInvalidPeerMessage { missingRequired.receive(hello) }

        val active = streamingSession()
        assertInvalidPeerMessage {
            active.receive(
                Envelope.newBuilder(videoConfig(7)).setSessionEpoch(6).build(),
            )
        }

        val missingPayload = session().also { it.clientHello() }
        assertInvalidPeerMessage {
            missingPayload.receive(
                Envelope.newBuilder().setProtocolVersion(1).setMessageId(2).build(),
            )
        }
    }

    @Test
    fun validatesMediaHeaderAndRejectsFragmentOrStaleEpoch() {
        val session = streamingSession()
        session.validateMedia(mediaHeader())
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setFragmentCount(2).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setSessionEpoch(6).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader().toBuilder().setPayloadLength(0).build()) }
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
        assertInvalidMediaHeader {
            streamingSession().validateMedia(mediaHeader().toBuilder().setCodec(Codec.CODEC_H264).build())
        }
    }

    @Test
    fun touchHeartbeatKeyframeAndProtocolErrorUseControlEnvelope() {
        val session = streamingSession()
        val touch = session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        assertEquals(Envelope.PayloadCase.TOUCH_EVENT, touch.payloadCase)
        assertEquals("display-main", touch.touchEvent.target.displayId)
        assertEquals(42L, touch.touchEvent.target.streamId)

        val pong = session.receive(
            base(7).setPing(Ping.newBuilder().setSequence(99)).build(),
        ).single() as ProtocolV1Session.Action.Send
        assertEquals(99L, pong.envelope.pong.sequence)
        assertEquals(7L, pong.envelope.correlationId)
        assertEquals(42L, session.requestKeyframe("decoder").requestKeyframe.streamId)

        val error =
            base(8)
                .setProtocolError(
                    ProtocolError
                        .newBuilder()
                        .setCode(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE)
                        .setMessage("bad state"),
                ).build()
        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(error) }
        assertEquals(ProtocolV1Failure.Source.HOST_PROTOCOL_ERROR, failure.source)
        assertEquals(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE.name, failure.reason)
        assertFalse(failure.retryable)
    }

    @Test
    fun sessionRejectionPreservesReasonAndRetryability() {
        val session = session().also { it.clientHello() }
        session.receive(hostHello(2))
        val rejected =
            Envelope
                .newBuilder()
                .setProtocolVersion(1)
                .setMessageId(3)
                .setSessionRejected(
                    SessionRejected
                        .newBuilder()
                        .setReasonCode("host_busy")
                        .setMessage("Try another host")
                        .setRetryable(true),
                ).build()

        val failure = assertThrows(ProtocolV1Failure::class.java) { session.receive(rejected) }

        assertEquals(ProtocolV1Failure.Source.SESSION_REJECTED, failure.source)
        assertEquals("host_busy", failure.reason)
        assertEquals("Try another host", failure.message)
        assertTrue(failure.retryable)
    }

    @Test
    fun rejectedVideoConfigIsAcknowledgedButNeverEnablesMedia() {
        val session = sessionThroughDisplayStart()
        val actions = session.receive(videoConfig(6).toBuilder().setVideoConfig(videoConfig(6).videoConfig.toBuilder().setStreamId(99)).build())
        val result = actions.single() as ProtocolV1Session.Action.Send
        assertFalse(result.envelope.videoConfigResult.accepted)
        assertFalse(session.isStreaming)
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
    }

    @Test
    fun rejectsCodecThatHostDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, listOf(Codec.CODEC_H264)))
        session.receive(sessionAccepted(3))
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val result = session.receive(videoConfig(6)).single() as ProtocolV1Session.Action.Send
        assertFalse(result.envelope.videoConfigResult.accepted)
        assertFalse(session.isStreaming)
    }

    private fun streamingSession(): ProtocolV1Session =
        sessionThroughDisplayStart().also { it.receive(videoConfig(6)) }

    private fun sessionThroughDisplayStart(): ProtocolV1Session =
        session().also {
            it.clientHello()
            it.receive(hostHello(2))
            it.receive(sessionAccepted(3))
            it.receive(displayList(4))
            it.receive(startDisplay(5))
        }

    private fun session(): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            nowNs = { 1_000L },
        )

    private fun assertInvalidPeerMessage(block: () -> Unit) {
        val failure = assertThrows(ProtocolV1Failure::class.java, block)
        assertEquals("invalid_peer_message", failure.reason)
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
        assertFalse(failure.retryable)
    }

    private fun assertInvalidMediaHeader(block: () -> Unit) {
        val failure = assertThrows(ProtocolV1Failure::class.java, block)
        assertEquals("invalid_media_header", failure.reason)
        assertEquals(ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION, failure.source)
        assertFalse(failure.retryable)
    }

    private fun hostHello(
        id: Long,
        advertisedCodecs: List<Codec> = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .addCapabilities(Capability.CAPABILITY_TOUCH)
                    .addCapabilities(Capability.CAPABILITY_TELEMETRY)
                    .addAllCodecs(advertisedCodecs),
            ).build()

    private fun sessionAccepted(id: Long): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted
                    .newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .setHeartbeatIntervalMs(1_000)
                    .addCapabilitiesCompat(),
            ).build()

    private fun SessionAccepted.Builder.addCapabilitiesCompat(): SessionAccepted.Builder =
        addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH)
            .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY)

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(42),
            ).build()

    private fun videoConfig(id: Long): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(3)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(42),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    private fun mediaHeader(): MediaPacketHeader =
        MediaPacketHeader
            .newBuilder()
            .setStreamId(42)
            .setSessionEpoch(7)
            .setConfigEpoch(3)
            .setFrameId(1)
            .setFragmentIndex(0)
            .setFragmentCount(1)
            .setKeyframe(true)
            .setCodec(Codec.CODEC_HEVC)
            .setPayloadLength(4)
            .build()

    companion object {
        private val SESSION_ID = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
    }
}
