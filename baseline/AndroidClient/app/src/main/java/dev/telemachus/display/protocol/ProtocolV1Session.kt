package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClientHello
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.InputTarget
import dev.vibescreen.protocol.v1.ListDisplaysRequest
import dev.vibescreen.protocol.v1.NormalizedPoint
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.Pong
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.ProtocolRange
import dev.vibescreen.protocol.v1.RequestKeyframe
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.StartDisplayRequest
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.TouchEvent
import dev.vibescreen.protocol.v1.VideoConfigResult
import java.io.IOException

internal class ProtocolV1Failure(
    val reason: String,
    val retryable: Boolean,
    val source: Source,
    message: String,
) : IOException(message) {
    enum class Source {
        SESSION_REJECTED,
        HOST_PROTOCOL_ERROR,
        PEER_PROTOCOL_VIOLATION,
        FRAME,
        ENVELOPE,
        MEDIA_PAYLOAD,
    }
}

/** Product-session state machine. It intentionally has no Android, UI, codec, or transport imports. */
internal class ProtocolV1Session(
    private val deviceId: String,
    private val deviceName: String,
    private val transport: TransportKind,
    private val codecs: List<Codec>,
    private val nowNs: () -> Long = System::nanoTime,
) {
    sealed class Action {
        data class Send(val envelope: Envelope) : Action()

        data class VideoConfigured(
            val width: Int,
            val height: Int,
            val codec: Codec,
            val sessionEpoch: Long,
        ) : Action()

        data class PongReceived(val sequence: Long) : Action()

        data class Disconnected(val mayResume: Boolean) : Action()
    }

    private enum class State { AWAITING_HOST_HELLO, AWAITING_SESSION, ACTIVE, DISPLAY_REQUESTED, STREAMING, CLOSED }

    private var state = State.AWAITING_HOST_HELLO
    private var nextMessageId = 1L
    private var lastInboundMessageId = 0L
    private var sessionId = ByteString.EMPTY
    private var sessionEpoch = 0L
    private var streamId = 0L
    private var configEpoch = 0L
    private var configuredCodec = Codec.CODEC_UNSPECIFIED
    private var lastFrameId = 0L
    private var displayId = ""
    private var negotiatedCapabilities = emptySet<Capability>()
    private var hostCapabilities = emptySet<Capability>()
    private var hostCodecs = emptySet<Codec>()

    private val advertisedCapabilities = setOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_TELEMETRY)
    private val requiredCapabilities = setOf(Capability.CAPABILITY_TOUCH)

    val activeSessionEpoch: Long
        @Synchronized
        get() = sessionEpoch

    val isStreaming: Boolean
        @Synchronized
        get() = state == State.STREAMING

    init {
        require(deviceId.isNotBlank()) { "deviceId must not be blank" }
        require(deviceName.isNotBlank()) { "deviceName must not be blank" }
        require(codecs.isNotEmpty() && codecs.none { it == Codec.CODEC_UNSPECIFIED }) { "At least one codec is required" }
    }

    @Synchronized
    fun clientHello(): Envelope {
        check(state == State.AWAITING_HOST_HELLO)
        val hello =
            ClientHello
                .newBuilder()
                .setSupportedProtocols(ProtocolRange.newBuilder().setMinimum(VERSION).setMaximum(VERSION))
                .setDeviceId(deviceId)
                .setDeviceName(deviceName)
                .addAllCapabilities(advertisedCapabilities)
                .addAllRequiredCapabilities(requiredCapabilities)
                .addAllCodecs(codecs)
                .addTransports(transport)
                .setResourceLimits(
                    ResourceLimits
                        .newBuilder()
                        .setMaximumClients(1)
                        .setMaximumDisplays(1)
                        .setMaximumVideoStreams(1),
                ).build()
        return envelope().setClientHello(hello).build()
    }

    @Synchronized
    fun receive(envelope: Envelope): List<Action> {
        validateEnvelope(envelope)
        return when (envelope.payloadCase) {
            Envelope.PayloadCase.HOST_HELLO -> onHostHello(envelope)
            Envelope.PayloadCase.SESSION_ACCEPTED -> onSessionAccepted(envelope)
            Envelope.PayloadCase.SESSION_REJECTED -> {
                val rejected = envelope.sessionRejected
                throw ProtocolV1Failure(
                    reason = rejected.reasonCode.ifBlank { "session_rejected" },
                    retryable = rejected.retryable,
                    source = ProtocolV1Failure.Source.SESSION_REJECTED,
                    message = rejected.message.ifBlank { "Session rejected: ${rejected.reasonCode}" },
                )
            }
            Envelope.PayloadCase.LIST_DISPLAYS_RESPONSE -> onDisplays(envelope)
            Envelope.PayloadCase.START_DISPLAY_RESPONSE -> onStartDisplay(envelope)
            Envelope.PayloadCase.VIDEO_CONFIG -> onVideoConfig(envelope)
            Envelope.PayloadCase.PING ->
                listOf(
                    Action.Send(
                        envelope(correlationId = envelope.messageId)
                            .setPong(Pong.newBuilder().setSequence(envelope.ping.sequence))
                            .build(),
                    ),
                )
            Envelope.PayloadCase.PONG -> listOf(Action.PongReceived(envelope.pong.sequence))
            Envelope.PayloadCase.DISCONNECT_NOTICE -> {
                state = State.CLOSED
                listOf(Action.Disconnected(envelope.disconnectNotice.mayResume))
            }
            Envelope.PayloadCase.PROTOCOL_ERROR -> {
                val error = envelope.protocolError
                throw ProtocolV1Failure(
                    reason = error.code.name,
                    retryable = error.retryable,
                    source = ProtocolV1Failure.Source.HOST_PROTOCOL_ERROR,
                    message = "Host protocol error ${error.code}: ${error.message}",
                )
            }
            else -> throw protocolFailure("Unexpected ${envelope.payloadCase} in state $state")
        }
    }

    @Synchronized
    fun ping(sequence: Long): Envelope {
        require(sequence > 0)
        check(state >= State.ACTIVE && state != State.CLOSED)
        return envelope().setPing(Ping.newBuilder().setSequence(sequence)).build()
    }

    @Synchronized
    fun requestKeyframe(reason: String): Envelope {
        check(state == State.STREAMING)
        return envelope()
            .setRequestKeyframe(RequestKeyframe.newBuilder().setStreamId(streamId).setReasonCode(reason.take(128)))
            .build()
    }

    @Synchronized
    fun touch(
        inputId: Long,
        pointerId: Int,
        phase: InputPhase,
        x: Double,
        y: Double,
    ): Envelope {
        check(state == State.STREAMING)
        require(inputId > 0 && pointerId >= 0 && phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x in 0.0..1.0 && y in 0.0..1.0)
        val event =
            TouchEvent
                .newBuilder()
                .setInputId(inputId)
                .setPointerId(pointerId)
                .setPhase(phase)
                .setPosition(NormalizedPoint.newBuilder().setX(x).setY(y))
                .setTarget(InputTarget.newBuilder().setDisplayId(displayId).setStreamId(streamId))
                .build()
        return envelope().setTouchEvent(event).build()
    }

    @Synchronized
    fun validateMedia(header: dev.vibescreen.protocol.v1.MediaPacketHeader) {
        if (state != State.STREAMING) throw mediaFailure("Media received before VideoConfig acceptance")
        if (header.sessionEpoch != sessionEpoch || header.streamId != streamId || header.configEpoch != configEpoch) {
            throw mediaFailure("Stale or cross-stream media header")
        }
        if (header.codec != configuredCodec) throw mediaFailure("Media codec differs from accepted VideoConfig")
        if (header.fragmentCount != 1 || header.fragmentIndex != 0) {
            throw mediaFailure("Fragmented Protocol v1 media is unsupported")
        }
        if (header.frameId <= lastFrameId) throw mediaFailure("Non-monotonic media frame_id")
        if (header.payloadLength <= 0) throw mediaFailure("Media payload must not be empty")
        lastFrameId = header.frameId
    }

    @Synchronized
    fun protocolError(
        message: String,
        correlationId: Long = 0,
    ): Envelope =
        envelope(correlationId)
            .setProtocolError(
                ProtocolError
                    .newBuilder()
                    .setCode(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE)
                    .setMessage(message.take(256))
                    .setComponent("android-session")
                    .setRetryable(false),
            ).build()

    private fun onHostHello(envelope: Envelope): List<Action> {
        if (state != State.AWAITING_HOST_HELLO) throw protocolFailure("Duplicate HostHello")
        val hello = envelope.hostHello
        if (hello.selectedProtocol != VERSION) throw protocolFailure("Unsupported selected protocol ${hello.selectedProtocol}")
        hostCapabilities = hello.capabilitiesList.toSet()
        hostCodecs = hello.codecsList.toSet()
        val missing = requiredCapabilities - hostCapabilities
        if (missing.isNotEmpty()) {
            throw protocolFailure("Host lacks required capabilities: $missing")
        }
        if (hostCodecs.intersect(codecs.toSet()).isEmpty()) throw protocolFailure("Host and device share no codec")
        state = State.AWAITING_SESSION
        return emptyList()
    }

    private fun onSessionAccepted(envelope: Envelope): List<Action> {
        if (state != State.AWAITING_SESSION) throw protocolFailure("SessionAccepted before HostHello")
        val accepted = envelope.sessionAccepted
        if (accepted.sessionId.isEmpty || accepted.sessionEpoch <= 0) throw protocolFailure("Invalid accepted session identity")
        if ((!envelope.sessionId.isEmpty && envelope.sessionId != accepted.sessionId) ||
            (envelope.sessionEpoch != 0L && envelope.sessionEpoch != accepted.sessionEpoch)
        ) {
            throw protocolFailure("Outer and accepted session identity differ")
        }
        val negotiated = accepted.negotiatedCapabilitiesList.toSet()
        if (!negotiated.containsAll(requiredCapabilities)) {
            throw protocolFailure("Required capabilities were not negotiated")
        }
        if (!advertisedCapabilities.containsAll(negotiated) || !hostCapabilities.containsAll(negotiated)) {
            throw protocolFailure("Negotiated capabilities are not the peer intersection")
        }
        sessionId = accepted.sessionId
        sessionEpoch = accepted.sessionEpoch
        negotiatedCapabilities = negotiated
        state = State.ACTIVE
        return listOf(Action.Send(envelope().setListDisplaysRequest(ListDisplaysRequest.getDefaultInstance()).build()))
    }

    private fun onDisplays(envelope: Envelope): List<Action> {
        if (state != State.ACTIVE) throw protocolFailure("Display list in state $state")
        val display = envelope.listDisplaysResponse.displaysList.firstOrNull()
            ?: throw protocolFailure("Host reported no displays")
        displayId = display.displayId
        state = State.DISPLAY_REQUESTED
        val request =
            StartDisplayRequest
                .newBuilder()
                .setMode(dev.vibescreen.protocol.v1.DisplayMode.DISPLAY_MODE_EXISTING)
                .setSourceDisplayId(displayId)
                .build()
        return listOf(Action.Send(envelope().setStartDisplayRequest(request).build()))
    }

    private fun onStartDisplay(envelope: Envelope): List<Action> {
        if (state != State.DISPLAY_REQUESTED) throw protocolFailure("StartDisplayResponse in state $state")
        val response = envelope.startDisplayResponse
        if (!response.accepted || response.streamId <= 0) {
            throw protocolFailure("Display start rejected: ${response.rejectionReason}")
        }
        streamId = response.streamId
        if (response.hasDisplay() && response.display.displayId.isNotBlank()) displayId = response.display.displayId
        return emptyList()
    }

    private fun onVideoConfig(envelope: Envelope): List<Action> {
        if (state != State.DISPLAY_REQUESTED && state != State.STREAMING) throw protocolFailure("VideoConfig in state $state")
        val config = envelope.videoConfig
        val accepted =
            config.streamId == streamId &&
                config.configEpoch > configEpoch &&
                config.encodedSize.width in 16..8192 &&
                config.encodedSize.height in 16..8192 &&
                config.codec in codecs &&
                config.codec in hostCodecs
        val result =
            VideoConfigResult
                .newBuilder()
                .setConfigEpoch(config.configEpoch)
                .setStreamId(config.streamId)
                .setAccepted(accepted)
                .setRejectionReason(if (accepted) "" else "unsupported_video_config")
                .build()
        val actions =
            mutableListOf<Action>(
                Action.Send(
                    envelope(correlationId = envelope.messageId)
                        .setVideoConfigResult(result)
                        .build(),
                ),
            )
        if (!accepted) return actions
        configEpoch = config.configEpoch
        configuredCodec = config.codec
        lastFrameId = 0L
        state = State.STREAMING
        actions +=
            Action.VideoConfigured(
                config.encodedSize.width,
                config.encodedSize.height,
                config.codec,
                sessionEpoch,
            )
        return actions
    }

    private fun validateEnvelope(envelope: Envelope) {
        if (envelope.protocolVersion != VERSION) throw protocolFailure("Unsupported envelope version ${envelope.protocolVersion}")
        if (envelope.messageId <= lastInboundMessageId) throw protocolFailure("Non-monotonic message_id")
        if (state >= State.ACTIVE && state != State.CLOSED) {
            if (envelope.sessionId != sessionId || envelope.sessionEpoch != sessionEpoch) {
                throw protocolFailure("Wrong session_id or session_epoch")
            }
        } else if (envelope.payloadCase == Envelope.PayloadCase.HOST_HELLO &&
            (!envelope.sessionId.isEmpty || envelope.sessionEpoch != 0L)
        ) {
            throw protocolFailure("HostHello unexpectedly carries session identity")
        }
        if (envelope.payloadCase == Envelope.PayloadCase.PAYLOAD_NOT_SET) throw protocolFailure("Envelope payload is missing")
        lastInboundMessageId = envelope.messageId
    }

    private fun envelope(correlationId: Long = 0): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(VERSION)
            .setMessageId(nextMessageId++)
            .setCorrelationId(correlationId)
            .setSessionId(sessionId)
            .setSessionEpoch(sessionEpoch)
            .setSentAtMonotonicNs(nowNs())

    private fun protocolFailure(message: String): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = "invalid_peer_message",
            retryable = false,
            source = ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION,
            message = "Protocol v1: $message",
        )

    private fun mediaFailure(message: String): ProtocolV1Failure =
        ProtocolV1Failure(
            reason = "invalid_media_header",
            retryable = false,
            source = ProtocolV1Failure.Source.PEER_PROTOCOL_VIOLATION,
            message = "Protocol v1: $message",
        )

    companion object {
        const val VERSION = 1
    }
}
