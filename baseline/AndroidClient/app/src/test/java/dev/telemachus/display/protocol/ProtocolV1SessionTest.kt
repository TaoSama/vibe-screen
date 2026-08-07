package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisconnectNotice
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.DisplayChanged
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
    fun clientHelloPinsVersionAndExactProductionCapabilities() {
        val session = session()
        val hello = session.clientHello()

        assertEquals(1, hello.protocolVersion)
        assertEquals(1L, hello.messageId)
        assertEquals(1_000L, hello.sentAtMonotonicNs)
        assertEquals(1, hello.clientHello.supportedProtocols.minimum)
        assertEquals(1, hello.clientHello.supportedProtocols.maximum)
        assertEquals(listOf(Capability.CAPABILITY_TOUCH), hello.clientHello.capabilitiesList)
        assertEquals(emptyList<Capability>(), hello.clientHello.requiredCapabilitiesList)
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

        val requested = session.receive(videoConfig(6)).single() as ProtocolV1Session.Action.VideoConfigurationRequested
        assertEquals(1920, requested.width)
        assertEquals(1080, requested.height)
        assertEquals(90, requested.rotation)
        assertEquals(3L, requested.configEpoch)
        assertEquals(7L, requested.sessionEpoch)
        assertFalse(session.isStreaming)
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader()),
        )

        val actions =
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        val result = actions[0] as ProtocolV1Session.Action.Send
        val keyframe = actions[1] as ProtocolV1Session.Action.Send
        val committed = actions[2] as ProtocolV1Session.Action.VideoConfigurationCommitted
        val geometry = actions[3] as ProtocolV1Session.Action.DisplayGeometryChanged
        assertTrue(result.envelope.videoConfigResult.accepted)
        assertEquals(6L, result.envelope.correlationId)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, keyframe.envelope.payloadCase)
        assertEquals(3L, committed.configEpoch)
        assertEquals(1920, geometry.width)
        assertEquals(1080, geometry.height)
        assertEquals(90, geometry.rotation)
        assertTrue(session.isStreaming)
    }

    @Test
    fun runtimeDisplayChangeCarriesRotationWithoutReconfiguringMedia() {
        val session = streamingSession()
        val action =
            session.receive(
                base(7)
                    .setDisplayChanged(
                        DisplayChanged
                            .newBuilder()
                            .setDisplay(
                                DisplayDescriptor
                                    .newBuilder()
                                    .setDisplayId("display-main")
                                    .setLogicalSize(Dimensions.newBuilder().setWidth(1080).setHeight(1920)),
                            ).setRotationDegrees(270),
                    ).build(),
            ).single() as ProtocolV1Session.Action.DisplayGeometryChanged

        assertEquals(1080, action.width)
        assertEquals(1920, action.height)
        assertEquals(270, action.rotation)
        session.validateMedia(mediaHeader())
    }

    @Test
    fun staleVideoConfigEpochIsRejectedWithoutAReconfigurationAction() {
        val session = streamingSession()

        val actions = session.receive(videoConfig(id = 7, configEpoch = 3))
        val result = actions.single() as ProtocolV1Session.Action.Send

        assertFalse(result.envelope.videoConfigResult.accepted)
        assertEquals(3L, result.envelope.videoConfigResult.configEpoch)
    }

    @Test
    fun reconfigurationDropsPendingAndRetiredEpochsUntilNewKeyframe() {
        val session = streamingSession()
        assertEquals(
            ProtocolV1Session.MediaDisposition.ACCEPT,
            session.validateMedia(mediaHeader(frameId = 1)),
        )

        val requested =
            session.receive(videoConfig(id = 7, configEpoch = 4)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 3, frameId = 2)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_PENDING_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 1)),
        )

        session.completeVideoConfiguration(
            completedConfigEpoch = 4,
            configurationToken = requested.configurationToken,
            accepted = true,
            rejectionReason = "",
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_RETIRED_CONFIGURATION,
            session.validateMedia(mediaHeader(configEpoch = 3, frameId = 2)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.DROP_AWAITING_KEYFRAME,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 1, keyframe = false)),
        )
        assertEquals(
            ProtocolV1Session.MediaDisposition.ACCEPT,
            session.validateMedia(mediaHeader(configEpoch = 4, frameId = 2, keyframe = true)),
        )
    }

    @Test
    fun staleDecoderCompletionProducesNoAckAndLeavesPendingRequestIntact() {
        val session = sessionThroughDisplayStart()
        val requested =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 99,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken + 1,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertFalse(session.isStreaming)
        val completion =
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        assertTrue((completion.first() as ProtocolV1Session.Action.Send).envelope.videoConfigResult.accepted)
    }

    @Test
    fun disconnectNoticeInvalidatesPendingVideoConfigurationAndLateCompletion() {
        val session = sessionThroughDisplayStart()
        val requested =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested

        val disconnected =
            session.receive(
                base(7)
                    .setDisconnectNotice(
                        DisconnectNotice.newBuilder().setReasonCode("host_shutdown").setMayResume(false),
                    ).build(),
            ).single()
        assertTrue(disconnected is ProtocolV1Session.Action.Disconnected)
        assertTrue(
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            ).isEmpty(),
        )
        assertFalse(session.isStreaming)
        assertFalse(session.canSendTouch)
        assertInvalidMediaHeader { session.validateMedia(mediaHeader()) }
    }

    @Test
    fun displayChangeForAnotherDisplayIsRejected() {
        val session = streamingSession()
        val changed =
            DisplayChanged
                .newBuilder()
                .setDisplay(
                    DisplayDescriptor
                        .newBuilder()
                        .setDisplayId("stale-display")
                        .setLogicalSize(Dimensions.newBuilder().setWidth(1080).setHeight(1920)),
                ).setRotationDegrees(270)

        assertInvalidPeerMessage {
            session.receive(base(7).setDisplayChanged(changed).build())
        }
    }

    @Test
    fun rejectsVersionSessionEpochAndUnexpectedPayload() {
        val wrongVersion = session().also { it.clientHello() }
        assertInvalidPeerMessage {
            wrongVersion.receive(hostHello(2).toBuilder().setProtocolVersion(2).build())
        }

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

    @Test
    fun rejectsSessionAcceptedWithCapabilityClientDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities =
                    listOf(
                        Capability.CAPABILITY_TOUCH,
                        Capability.CAPABILITY_TELEMETRY,
                    ),
            ),
        )
        val acceptedMessage = sessionAccepted(3)
        val accepted =
            acceptedMessage.toBuilder()
                .setSessionAccepted(
                    acceptedMessage.sessionAccepted.toBuilder()
                        .addNegotiatedCapabilities(Capability.CAPABILITY_TELEMETRY),
                ).build()

        assertInvalidPeerMessage { session.receive(accepted) }
    }

    @Test
    fun acceptsExactIntersectionWhenHostAdvertisesAdditionalCapabilities() {
        val session = session()
        session.clientHello()
        session.receive(
            hostHello(
                id = 2,
                advertisedCapabilities =
                    listOf(
                        Capability.CAPABILITY_TOUCH,
                        Capability.CAPABILITY_TELEMETRY,
                    ),
            ),
        )

        val listRequest = session.receive(sessionAccepted(3)).single() as ProtocolV1Session.Action.Send

        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
    }

    @Test
    fun rejectsSessionAcceptedWithCapabilityHostDidNotAdvertise() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2, advertisedCapabilities = emptyList()))

        assertInvalidPeerMessage { session.receive(sessionAccepted(3)) }
    }

    @Test
    fun rejectsSessionAcceptedThatOmitsMutuallyAdvertisedTouch() {
        val session = session()
        session.clientHello()
        session.receive(hostHello(2))

        assertInvalidPeerMessage {
            session.receive(sessionAccepted(3, negotiatedCapabilities = emptyList()))
        }
    }

    @Test
    fun displayOnlyNegotiationStreamsButBlocksTouch() {
        val session = session()
        session.clientHello()
        assertTrue(session.receive(hostHello(2, advertisedCapabilities = emptyList())).isEmpty())
        val listRequest =
            session.receive(sessionAccepted(3, negotiatedCapabilities = emptyList())).single()
                as ProtocolV1Session.Action.Send
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, listRequest.envelope.payloadCase)
        session.receive(displayList(4))
        session.receive(startDisplay(5))
        val configured =
            session.receive(videoConfig(6)).single()
                as ProtocolV1Session.Action.VideoConfigurationRequested
        assertFalse(session.isStreaming)
        session.completeVideoConfiguration(
            completedConfigEpoch = 3,
            configurationToken = configured.configurationToken,
            accepted = true,
            rejectionReason = "",
        )

        assertTrue(session.isStreaming)
        assertFalse(session.canSendTouch)
        assertThrows(IllegalStateException::class.java) {
            session.touch(100, 1, InputPhase.INPUT_PHASE_BEGAN, 0.25, 0.75)
        }
    }

    private fun streamingSession(): ProtocolV1Session =
        sessionThroughDisplayStart().also {
            val requested =
                it.receive(videoConfig(6)).single()
                    as ProtocolV1Session.Action.VideoConfigurationRequested
            it.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

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
        advertisedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
    ): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .addAllCapabilities(advertisedCapabilities)
                    .addAllCodecs(advertisedCodecs),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
    ): Envelope =
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
                    .addAllNegotiatedCapabilities(negotiatedCapabilities),
            ).build()

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

    private fun videoConfig(
        id: Long,
        configEpoch: Long = 3,
    ): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(configEpoch)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(42)
                    .setRotationDegrees(90),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    private fun mediaHeader(
        configEpoch: Long = 3,
        frameId: Long = 1,
        keyframe: Boolean = true,
    ): MediaPacketHeader =
        MediaPacketHeader
            .newBuilder()
            .setStreamId(42)
            .setSessionEpoch(7)
            .setConfigEpoch(configEpoch)
            .setFrameId(frameId)
            .setFragmentIndex(0)
            .setFragmentCount(1)
            .setKeyframe(keyframe)
            .setCodec(Codec.CODEC_HEVC)
            .setPayloadLength(4)
            .build()

    companion object {
        private val SESSION_ID = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
    }
}
