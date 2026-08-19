package dev.telemachus.display.audio

import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import java.util.TreeMap

internal data class PcmAudioStreamFormat(
    val streamId: Long,
    val configEpoch: Long,
    val sampleRateHz: Int,
    val channelCount: Int,
    val framesPerPacket: Int,
) {
    val bytesPerPacket: Int = checkedBytesPerPacket(channelCount, framesPerPacket)

    companion object {
        fun from(config: AudioConfig): PcmAudioStreamFormat {
            if (config.streamId <= 0) throw ProtocolAudioException(AudioRejectReason.INVALID_STREAM_ID)
            if (config.configEpoch <= 0) throw ProtocolAudioException(AudioRejectReason.INVALID_CONFIG_EPOCH)
            if (config.codec != AudioCodec.AUDIO_CODEC_PCM_S16LE) {
                throw ProtocolAudioException(AudioRejectReason.UNSUPPORTED_CODEC)
            }
            if (config.sampleRateHz !in MIN_SAMPLE_RATE_HZ..MAX_SAMPLE_RATE_HZ) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_SAMPLE_RATE)
            }
            if (config.channelCount !in MIN_CHANNEL_COUNT..MAX_CHANNEL_COUNT) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_CHANNEL_COUNT)
            }
            if (config.framesPerPacket <= 0) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_FRAMES_PER_PACKET)
            }
            return PcmAudioStreamFormat(
                streamId = config.streamId,
                configEpoch = config.configEpoch,
                sampleRateHz = config.sampleRateHz,
                channelCount = config.channelCount,
                framesPerPacket = config.framesPerPacket,
            )
        }

        private fun checkedBytesPerPacket(
            channelCount: Int,
            framesPerPacket: Int,
        ): Int {
            val bytes = framesPerPacket.toLong() * channelCount.toLong() * PCM_S16LE_BYTES_PER_SAMPLE
            if (bytes !in 1..MAX_PCM_PACKET_BYTES.toLong()) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_PCM_BYTE_COUNT)
            }
            return bytes.toInt()
        }
    }
}

internal data class ProtocolAudioPacket(
    val header: AudioPacketHeader,
    val payload: ByteArray,
) {
    init {
        require(payload.size == header.payloadLength) { "Audio payload length must match its header" }
    }

    override fun equals(other: Any?): Boolean =
        other is ProtocolAudioPacket && header == other.header && payload.contentEquals(other.payload)

    override fun hashCode(): Int = 31 * header.hashCode() + payload.contentHashCode()

    companion object {
        fun parse(serializedFrame: ByteArray): ProtocolAudioPacket {
            val headerBoundary = DelimitedAudioPayload.readHeaderBoundary(serializedFrame)
            val headerLength = headerBoundary.headerLength
            if (headerLength > MAX_AUDIO_HEADER_BYTES) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_HEADER)
            }
            if (headerLength > serializedFrame.size - headerBoundary.payloadOffset) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_HEADER)
            }
            val header =
                try {
                    AudioPacketHeader.parseFrom(
                        serializedFrame.copyOfRange(
                            headerBoundary.payloadOffset,
                            headerBoundary.payloadOffset + headerLength,
                        ),
                    )
                } catch (failure: RuntimeException) {
                    throw ProtocolAudioException(AudioRejectReason.INVALID_HEADER, failure)
                }
            if (header.payloadLength > MAX_PCM_PACKET_BYTES) {
                throw ProtocolAudioException(AudioRejectReason.INVALID_PCM_BYTE_COUNT)
            }
            val payloadOffset = headerBoundary.payloadOffset + headerLength
            val payloadLength = serializedFrame.size - payloadOffset
            if (payloadLength != header.payloadLength) {
                throw ProtocolAudioException(AudioRejectReason.PAYLOAD_LENGTH_MISMATCH)
            }
            return ProtocolAudioPacket(
                header = header,
                payload = serializedFrame.copyOfRange(payloadOffset, serializedFrame.size),
            )
        }
    }
}

internal sealed interface AudioEnqueueResult {
    data object Queued : AudioEnqueueResult

    data object Duplicate : AudioEnqueueResult

    data object Stale : AudioEnqueueResult

    data class AdvancedPastGap(val droppedPackets: Long) : AudioEnqueueResult

    data class QueueFullDropped(val sequence: Long) : AudioEnqueueResult
}

internal class AudioJitterBuffer(
    firstSequence: Long,
    maximumPackets: Int = DEFAULT_JITTER_BUFFER_PACKETS,
) {
    private val packets = TreeMap<Long, ProtocolAudioPacket>()
    private var expectedSequence = firstSequence
    val maximumPackets = maximumPackets.coerceAtLeast(MINIMUM_JITTER_BUFFER_PACKETS)

    init {
        require(firstSequence >= 0) { "Audio sequence must start at a non-negative value" }
    }

    fun enqueue(
        packet: ProtocolAudioPacket,
        sessionEpoch: Long,
        format: PcmAudioStreamFormat,
    ): AudioEnqueueResult {
        packet.validate(sessionEpoch, format)
        val sequence = packet.header.sequence
        if (sequence < expectedSequence) return AudioEnqueueResult.Stale
        if (packets.containsKey(sequence)) return AudioEnqueueResult.Duplicate
        packets[sequence] = packet
        if (packets.size <= maximumPackets) return AudioEnqueueResult.Queued

        val earliest = packets.firstKey()
        return if (earliest > expectedSequence) {
            val droppedPackets = earliest - expectedSequence
            expectedSequence = earliest
            while (packets.size > maximumPackets) {
                packets.remove(packets.lastKey())
            }
            AudioEnqueueResult.AdvancedPastGap(droppedPackets)
        } else {
            val droppedSequence = packets.lastKey()
            packets.remove(droppedSequence)
            AudioEnqueueResult.QueueFullDropped(droppedSequence)
        }
    }

    fun drainReady(): List<ProtocolAudioPacket> {
        val ready = mutableListOf<ProtocolAudioPacket>()
        while (true) {
            val packet = packets.remove(expectedSequence) ?: break
            ready += packet
            expectedSequence++
        }
        return ready
    }

    fun reset(firstSequence: Long) {
        require(firstSequence >= 0) { "Audio sequence must start at a non-negative value" }
        packets.clear()
        expectedSequence = firstSequence
    }

    fun queuedPacketCount(): Int = packets.size
}

internal enum class AudioRejectReason(val code: String) {
    INVALID_STREAM_ID("invalid_stream_id"),
    INVALID_CONFIG_EPOCH("invalid_config_epoch"),
    INVALID_SESSION_EPOCH("invalid_session_epoch"),
    UNSUPPORTED_CODEC("unsupported_codec"),
    INVALID_SAMPLE_RATE("invalid_sample_rate"),
    INVALID_CHANNEL_COUNT("invalid_channel_count"),
    INVALID_FRAMES_PER_PACKET("invalid_frames_per_packet"),
    INVALID_HEADER("invalid_audio_header"),
    PAYLOAD_LENGTH_MISMATCH("audio_payload_length_mismatch"),
    STALE_SESSION_EPOCH("stale_session_epoch"),
    STALE_CONFIG_EPOCH("stale_config_epoch"),
    STREAM_MISMATCH("audio_stream_mismatch"),
    FUTURE_SESSION_EPOCH("future_session_epoch"),
    FUTURE_CONFIG_EPOCH("future_config_epoch"),
    INVALID_SEQUENCE("invalid_audio_sequence"),
    INVALID_PCM_BYTE_COUNT("invalid_pcm_byte_count"),
}

internal class ProtocolAudioException(
    val reason: AudioRejectReason,
    cause: Throwable? = null,
) : IllegalArgumentException(reason.code, cause)

private data class HeaderBoundary(
    val headerLength: Int,
    val payloadOffset: Int,
)

private object DelimitedAudioPayload {
    fun readHeaderBoundary(data: ByteArray): HeaderBoundary {
        var value = 0
        var shift = 0
        var cursor = 0
        while (cursor < data.size && shift <= MAX_VARINT_SHIFT) {
            val byte = data[cursor].toInt() and BYTE_MASK
            cursor++
            value = value or ((byte and VARINT_VALUE_MASK) shl shift)
            if ((byte and VARINT_CONTINUATION_BIT) == 0) {
                return HeaderBoundary(value, cursor)
            }
            shift += VARINT_GROUP_BITS
        }
        throw ProtocolAudioException(AudioRejectReason.INVALID_HEADER)
    }
}

private fun ProtocolAudioPacket.validate(
    sessionEpoch: Long,
    format: PcmAudioStreamFormat,
) {
    if (sessionEpoch <= 0) throw ProtocolAudioException(AudioRejectReason.INVALID_SESSION_EPOCH)
    when {
        header.sessionEpoch < sessionEpoch -> throw ProtocolAudioException(AudioRejectReason.STALE_SESSION_EPOCH)
        header.sessionEpoch > sessionEpoch -> throw ProtocolAudioException(AudioRejectReason.FUTURE_SESSION_EPOCH)
        header.configEpoch < format.configEpoch -> throw ProtocolAudioException(AudioRejectReason.STALE_CONFIG_EPOCH)
        header.configEpoch > format.configEpoch -> throw ProtocolAudioException(AudioRejectReason.FUTURE_CONFIG_EPOCH)
        header.streamId != format.streamId -> throw ProtocolAudioException(AudioRejectReason.STREAM_MISMATCH)
        header.sequence < 0 -> throw ProtocolAudioException(AudioRejectReason.INVALID_SEQUENCE)
        header.frameCount != format.framesPerPacket -> throw ProtocolAudioException(AudioRejectReason.INVALID_PCM_BYTE_COUNT)
        payload.size != format.bytesPerPacket -> throw ProtocolAudioException(AudioRejectReason.INVALID_PCM_BYTE_COUNT)
    }
}

private const val MIN_SAMPLE_RATE_HZ = 8_000
private const val MAX_SAMPLE_RATE_HZ = 192_000
private const val MIN_CHANNEL_COUNT = 1
private const val MAX_CHANNEL_COUNT = 8
private const val PCM_S16LE_BYTES_PER_SAMPLE = 2
private const val MAX_PCM_PACKET_BYTES = 256 * 1024
private const val MAX_AUDIO_HEADER_BYTES = 64 * 1024
private const val DEFAULT_JITTER_BUFFER_PACKETS = 8
private const val MINIMUM_JITTER_BUFFER_PACKETS = 2
private const val BYTE_MASK = 0xff
private const val VARINT_VALUE_MASK = 0x7f
private const val VARINT_CONTINUATION_BIT = 0x80
private const val VARINT_GROUP_BITS = 7
private const val MAX_VARINT_SHIFT = 28
