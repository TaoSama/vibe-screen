package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import com.google.protobuf.InvalidProtocolBufferException
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClientHello
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.NormalizedPoint
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.ProtocolRange
import dev.vibescreen.protocol.v1.Pong
import dev.vibescreen.protocol.v1.RequestKeyframe
import dev.vibescreen.protocol.v1.TouchEvent
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfigResult

enum class ProductVideoCodec {
    H264,
    HEVC,
    AV1,
}

enum class ProductInputPhase {
    BEGAN,
    CHANGED,
    ENDED,
    CANCELLED,
}

data class ProductTouchEvent(
    val inputId: Long,
    val pointerId: Int,
    val phase: ProductInputPhase,
    val normalizedX: Double,
    val normalizedY: Double,
    val pressure: Double = 0.0,
) {
    init {
        require(inputId > 0 && pointerId >= 0) { "Input identifiers must be positive" }
        require(normalizedX in 0.0..1.0 && normalizedY in 0.0..1.0) { "Touch coordinates must be normalized" }
        require(pressure in 0.0..1.0) { "Touch pressure must be normalized" }
    }
}

data class ProductVideoConfiguration(
    val configEpoch: Long,
    val codec: ProductVideoCodec,
    val width: Int,
    val height: Int,
    val framesPerSecond: Int,
    val bitrateKbps: Int,
    val streamId: Long,
    val rotationDegrees: Int = 0,
) {
    init {
        require(configEpoch > 0 && streamId > 0) { "Video epochs and stream identifiers must be positive" }
        require(width in 16..MAX_VIDEO_DIMENSION && height in 16..MAX_VIDEO_DIMENSION) { "Video dimensions are invalid" }
        require(framesPerSecond in 1..MAX_VIDEO_FPS && bitrateKbps > 0) { "Video rate is invalid" }
        require(rotationDegrees in setOf(0, 90, 180, 270)) { "Video rotation is invalid" }
    }

    companion object {
        private const val MAX_VIDEO_DIMENSION = 8_192
        private const val MAX_VIDEO_FPS = 240
    }
}

data class ProductMediaFragment(
    val streamId: Long,
    val sessionEpoch: Long,
    val configEpoch: Long,
    val frameId: Long,
    val fragmentIndex: Int,
    val fragmentCount: Int,
    val captureTimestampNs: Long,
    val keyframe: Boolean,
    val codec: ProductVideoCodec,
    val payload: ByteArray,
)

sealed class ProductControlMessage {
    data class HostHello(
        val selectedProtocol: Int,
        val hostId: String,
        val hostName: String,
        val capabilities: Set<Capability>,
    ) : ProductControlMessage()

    data class SessionAccepted(
        val sessionId: ByteArray,
        val sessionEpoch: Long,
        val capabilities: Set<Capability>,
        val heartbeatIntervalMillis: Long,
    ) : ProductControlMessage()

    data class SessionRejected(
        val reasonCode: String,
        val message: String,
        val retryable: Boolean,
    ) : ProductControlMessage()

    data class VideoConfiguration(val value: ProductVideoConfiguration) : ProductControlMessage()

    data class Pong(val sequence: Long) : ProductControlMessage()

    data class Ping(val sequence: Long) : ProductControlMessage()

    data class Disconnect(val reasonCode: String, val mayResume: Boolean) : ProductControlMessage()

    data class Revoked(val reasonCode: String) : ProductControlMessage()

    data class ProtocolFailure(val code: String, val message: String, val retryable: Boolean) : ProductControlMessage()

    data object Ignored : ProductControlMessage()
}

data class DecodedProductControl(
    val messageId: Long,
    val sessionId: ByteArray,
    val sessionEpoch: Long,
    val message: ProductControlMessage,
)

interface ProtocolV1ProductCodec {
    val localDeviceId: String

    fun encodeClientHello(messageId: Long, sessionId: ByteArray, sessionEpoch: Long): ByteArray

    fun encodeTouch(messageId: Long, sessionId: ByteArray, sessionEpoch: Long, event: ProductTouchEvent): ByteArray

    fun encodeKeyframeRequest(messageId: Long, sessionId: ByteArray, sessionEpoch: Long, streamId: Long, reason: String): ByteArray

    fun encodePing(messageId: Long, sessionId: ByteArray, sessionEpoch: Long, sequence: Long): ByteArray

    fun encodePong(
        messageId: Long,
        correlationId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        sequence: Long,
    ): ByteArray

    fun encodeVideoConfigResult(
        messageId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        configuration: ProductVideoConfiguration,
        accepted: Boolean,
        rejectionReason: String,
    ): ByteArray

    fun decodeControl(payload: ByteArray): DecodedProductControl

    fun decodeMediaFragment(payload: ByteArray): ProductMediaFragment
}

/** Generated-lite Protocol v1 adapter; schemas are consumed directly from contracts/proto at build time. */
class ProtobufProtocolV1ProductCodec(
    override val localDeviceId: String,
    private val deviceName: String,
    private val supportedCodecs: Set<ProductVideoCodec>,
    private val monotonicNanos: () -> Long = System::nanoTime,
) : ProtocolV1ProductCodec {
    init {
        require(localDeviceId.isNotBlank() && deviceName.isNotBlank()) { "Device identity is required" }
        require(supportedCodecs.isNotEmpty()) { "At least one decoder codec is required" }
    }

    override fun encodeClientHello(messageId: Long, sessionId: ByteArray, sessionEpoch: Long): ByteArray {
        val hello =
            ClientHello
                .newBuilder()
                .setSupportedProtocols(ProtocolRange.newBuilder().setMinimum(PROTOCOL_VERSION).setMaximum(PROTOCOL_VERSION))
                .setDeviceId(localDeviceId)
                .setDeviceName(deviceName)
                .addAllCapabilities(REQUIRED_CLIENT_CAPABILITIES)
                .addAllCodecs(supportedCodecs.map { it.toProto() })
                .addTransports(TransportKind.TRANSPORT_KIND_INTERNET)
                .build()
        return envelope(messageId, sessionId, sessionEpoch).setClientHello(hello).build().toByteArray()
    }

    override fun encodeTouch(
        messageId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        event: ProductTouchEvent,
    ): ByteArray {
        val touch =
            TouchEvent
                .newBuilder()
                .setInputId(event.inputId)
                .setPointerId(event.pointerId)
                .setPhase(event.phase.toProto())
                .setPosition(NormalizedPoint.newBuilder().setX(event.normalizedX).setY(event.normalizedY))
                .setPressure(event.pressure)
                .build()
        return envelope(messageId, sessionId, sessionEpoch).setTouchEvent(touch).build().toByteArray()
    }

    override fun encodeKeyframeRequest(
        messageId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        streamId: Long,
        reason: String,
    ): ByteArray {
        require(streamId > 0 && reason.isNotBlank()) { "Keyframe request is incomplete" }
        val request = RequestKeyframe.newBuilder().setStreamId(streamId).setReasonCode(reason.take(MAX_REASON_BYTES)).build()
        return envelope(messageId, sessionId, sessionEpoch).setRequestKeyframe(request).build().toByteArray()
    }

    override fun encodePing(
        messageId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        sequence: Long,
    ): ByteArray {
        require(sequence > 0) { "Ping sequence must be positive" }
        return envelope(messageId, sessionId, sessionEpoch)
            .setPing(Ping.newBuilder().setSequence(sequence))
            .build()
            .toByteArray()
    }

    override fun encodePong(
        messageId: Long,
        correlationId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        sequence: Long,
    ): ByteArray {
        require(sequence > 0 && correlationId > 0) { "Pong sequence and correlation identifier must be positive" }
        return envelope(messageId, sessionId, sessionEpoch)
            .setCorrelationId(correlationId)
            .setPong(Pong.newBuilder().setSequence(sequence))
            .build()
            .toByteArray()
    }

    override fun encodeVideoConfigResult(
        messageId: Long,
        sessionId: ByteArray,
        sessionEpoch: Long,
        configuration: ProductVideoConfiguration,
        accepted: Boolean,
        rejectionReason: String,
    ): ByteArray {
        require(accepted || rejectionReason.isNotBlank()) { "Rejected video configuration requires a reason" }
        val result =
            VideoConfigResult
                .newBuilder()
                .setConfigEpoch(configuration.configEpoch)
                .setAccepted(accepted)
                .setRejectionReason(rejectionReason.take(MAX_REASON_BYTES))
                .setStreamId(configuration.streamId)
                .build()
        return envelope(messageId, sessionId, sessionEpoch).setVideoConfigResult(result).build().toByteArray()
    }

    override fun decodeControl(payload: ByteArray): DecodedProductControl {
        require(payload.size in 1..MAX_CONTROL_BYTES) { "Control envelope size is invalid" }
        val envelope = parseEnvelope(payload)
        require(envelope.protocolVersion == PROTOCOL_VERSION) { "Unsupported Protocol v1 envelope version" }
        val message =
            when (envelope.payloadCase) {
                Envelope.PayloadCase.HOST_HELLO -> {
                    val value = envelope.hostHello
                    ProductControlMessage.HostHello(
                        value.selectedProtocol,
                        value.hostId,
                        value.hostName,
                        value.capabilitiesList.toSet(),
                    )
                }
                Envelope.PayloadCase.SESSION_ACCEPTED -> {
                    val value = envelope.sessionAccepted
                    ProductControlMessage.SessionAccepted(
                        value.sessionId.toByteArray(),
                        value.sessionEpoch,
                        value.negotiatedCapabilitiesList.toSet(),
                        value.heartbeatIntervalMs.toLong(),
                    )
                }
                Envelope.PayloadCase.SESSION_REJECTED -> {
                    val value = envelope.sessionRejected
                    ProductControlMessage.SessionRejected(value.reasonCode, value.message, value.retryable)
                }
                Envelope.PayloadCase.VIDEO_CONFIG -> ProductControlMessage.VideoConfiguration(envelope.videoConfig.toProduct())
                Envelope.PayloadCase.PONG -> ProductControlMessage.Pong(envelope.pong.sequence)
                Envelope.PayloadCase.PING -> ProductControlMessage.Ping(envelope.ping.sequence)
                Envelope.PayloadCase.DISCONNECT_NOTICE -> {
                    val value = envelope.disconnectNotice
                    ProductControlMessage.Disconnect(value.reasonCode, value.mayResume)
                }
                Envelope.PayloadCase.DEVICE_REVOKED -> ProductControlMessage.Revoked(envelope.deviceRevoked.reasonCode)
                Envelope.PayloadCase.PROTOCOL_ERROR -> {
                    val value = envelope.protocolError
                    ProductControlMessage.ProtocolFailure(value.code.name, value.message, value.retryable)
                }
                Envelope.PayloadCase.ERROR_REPORT -> {
                    val value = envelope.errorReport
                    ProductControlMessage.ProtocolFailure(value.code, value.message, value.retryable)
                }
                else -> ProductControlMessage.Ignored
            }
        return DecodedProductControl(
            messageId = envelope.messageId,
            sessionId = envelope.sessionId.toByteArray(),
            sessionEpoch = envelope.sessionEpoch,
            message = message,
        )
    }

    override fun decodeMediaFragment(payload: ByteArray): ProductMediaFragment {
        require(payload.size in 2..MAX_MEDIA_PACKET_BYTES) { "Media packet size is invalid" }
        val (headerLength, prefixBytes) = decodeBoundedVarint(payload)
        require(headerLength in 1..MAX_MEDIA_HEADER_BYTES && headerLength <= payload.size - prefixBytes) {
            "Media header length is invalid"
        }
        val headerBytes = payload.copyOfRange(prefixBytes, prefixBytes + headerLength)
        val header =
            try {
                MediaPacketHeader.parseFrom(headerBytes)
            } catch (failure: InvalidProtocolBufferException) {
                throw IllegalArgumentException("Media header is malformed", failure)
            }
        val body = payload.copyOfRange(prefixBytes + headerLength, payload.size)
        require(header.payloadLength == body.size) { "Media payload length does not match its authenticated header" }
        require(header.fragmentCount in 1..MAX_MEDIA_FRAGMENTS && header.fragmentIndex < header.fragmentCount) {
            "Media fragment coordinates are invalid"
        }
        return ProductMediaFragment(
            streamId = header.streamId,
            sessionEpoch = header.sessionEpoch,
            configEpoch = header.configEpoch,
            frameId = header.frameId,
            fragmentIndex = header.fragmentIndex,
            fragmentCount = header.fragmentCount,
            captureTimestampNs = header.captureTimestampNs,
            keyframe = header.keyframe,
            codec = header.codec.toProduct(),
            payload = body,
        )
    }

    private fun envelope(messageId: Long, sessionId: ByteArray, sessionEpoch: Long): Envelope.Builder {
        require(messageId > 0 && sessionId.isNotEmpty() && sessionEpoch > 0) { "Envelope routing metadata is invalid" }
        return Envelope
            .newBuilder()
            .setProtocolVersion(PROTOCOL_VERSION)
            .setMessageId(messageId)
            .setSessionId(ByteString.copyFrom(sessionId))
            .setSessionEpoch(sessionEpoch)
            .setSentAtMonotonicNs(monotonicNanos())
    }

    private fun parseEnvelope(payload: ByteArray): Envelope =
        try {
            Envelope.parseFrom(payload)
        } catch (failure: InvalidProtocolBufferException) {
            throw IllegalArgumentException("Control envelope is malformed", failure)
        }

    private fun decodeBoundedVarint(payload: ByteArray): Pair<Int, Int> {
        var value = 0
        var shift = 0
        for (index in 0 until minOf(payload.size, MAX_VARINT_BYTES)) {
            val byte = payload[index].toInt() and 0xff
            value = value or ((byte and 0x7f) shl shift)
            if (byte and 0x80 == 0) return value to (index + 1)
            shift += 7
        }
        throw IllegalArgumentException("Media header length varint is invalid")
    }

    private fun dev.vibescreen.protocol.v1.VideoConfig.toProduct(): ProductVideoConfiguration =
        ProductVideoConfiguration(
            configEpoch = configEpoch,
            codec = codec.toProduct(),
            width = encodedSize.width,
            height = encodedSize.height,
            framesPerSecond = framesPerSecond,
            bitrateKbps = bitrateKbps,
            streamId = streamId,
            rotationDegrees = rotationDegrees,
        )

    private fun ProductVideoCodec.toProto(): Codec =
        when (this) {
            ProductVideoCodec.H264 -> Codec.CODEC_H264
            ProductVideoCodec.HEVC -> Codec.CODEC_HEVC
            ProductVideoCodec.AV1 -> Codec.CODEC_AV1
        }

    private fun Codec.toProduct(): ProductVideoCodec =
        when (this) {
            Codec.CODEC_H264 -> ProductVideoCodec.H264
            Codec.CODEC_HEVC -> ProductVideoCodec.HEVC
            Codec.CODEC_AV1 -> ProductVideoCodec.AV1
            else -> throw IllegalArgumentException("Unsupported video codec: $this")
        }

    private fun ProductInputPhase.toProto(): InputPhase =
        when (this) {
            ProductInputPhase.BEGAN -> InputPhase.INPUT_PHASE_BEGAN
            ProductInputPhase.CHANGED -> InputPhase.INPUT_PHASE_CHANGED
            ProductInputPhase.ENDED -> InputPhase.INPUT_PHASE_ENDED
            ProductInputPhase.CANCELLED -> InputPhase.INPUT_PHASE_CANCELLED
        }

    companion object {
        const val PROTOCOL_VERSION = 1
        private const val MAX_CONTROL_BYTES = 1_048_576
        private const val MAX_MEDIA_PACKET_BYTES = 4_194_304
        private const val MAX_MEDIA_HEADER_BYTES = 64 * 1024
        private const val MAX_MEDIA_FRAGMENTS = 256
        private const val MAX_VARINT_BYTES = 5
        private const val MAX_REASON_BYTES = 256
        val REQUIRED_CLIENT_CAPABILITIES =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_DEVICE_IDENTITY,
                Capability.CAPABILITY_END_TO_END_ENCRYPTION,
                Capability.CAPABILITY_REPLAY_PROTECTION,
            )

        /** Test/host helper for the Protocol v1 `uint32 header length | header | payload` media-channel framing. */
        fun encodeMediaFragment(header: MediaPacketHeader, payload: ByteArray): ByteArray {
            require(header.payloadLength == payload.size) { "Media payload length does not match its header" }
            val encodedHeader = header.toByteArray()
            require(encodedHeader.size <= MAX_MEDIA_HEADER_BYTES) { "Media header is too large" }
            val prefix = encodeVarint(encodedHeader.size)
            return prefix + encodedHeader + payload
        }

        private fun encodeVarint(value: Int): ByteArray {
            require(value >= 0) { "Varint value cannot be negative" }
            var remaining = value
            val result = ArrayList<Byte>(MAX_VARINT_BYTES)
            do {
                var next = remaining and 0x7f
                remaining = remaining ushr 7
                if (remaining != 0) next = next or 0x80
                result += next.toByte()
            } while (remaining != 0)
            return result.toByteArray()
        }
    }
}
