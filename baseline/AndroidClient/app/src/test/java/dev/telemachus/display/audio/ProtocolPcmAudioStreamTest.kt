package dev.telemachus.display.audio

import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ProtocolPcmAudioStreamTest {
    @Test
    fun validatesPcmConfigAndDerivesPacketByteCount() {
        val format = PcmAudioStreamFormat.from(audioConfig(sampleRateHz = 48_000, channelCount = 2, framesPerPacket = 480))

        assertEquals(7L, format.streamId)
        assertEquals(3L, format.configEpoch)
        assertEquals(48_000, format.sampleRateHz)
        assertEquals(2, format.channelCount)
        assertEquals(480, format.framesPerPacket)
        assertEquals(1_920, format.bytesPerPacket)
    }

    @Test
    fun rejectsUnsupportedConfigValues() {
        assertRejects(AudioRejectReason.INVALID_STREAM_ID, audioConfig(streamId = 0))
        assertRejects(AudioRejectReason.INVALID_CONFIG_EPOCH, audioConfig(configEpoch = 0))
        assertRejects(AudioRejectReason.UNSUPPORTED_CODEC, audioConfig(codec = AudioCodec.AUDIO_CODEC_OPUS))
        assertRejects(AudioRejectReason.INVALID_SAMPLE_RATE, audioConfig(sampleRateHz = 7_999))
        assertRejects(AudioRejectReason.INVALID_SAMPLE_RATE, audioConfig(sampleRateHz = 192_001))
        assertRejects(AudioRejectReason.INVALID_CHANNEL_COUNT, audioConfig(channelCount = 0))
        assertRejects(AudioRejectReason.INVALID_CHANNEL_COUNT, audioConfig(channelCount = 9))
        assertRejects(AudioRejectReason.INVALID_FRAMES_PER_PACKET, audioConfig(framesPerPacket = 0))
        assertRejects(AudioRejectReason.INVALID_PCM_BYTE_COUNT, audioConfig(channelCount = 8, framesPerPacket = 16_385))
    }

    @Test
    fun parsesDelimitedAudioPacketAndRejectsPayloadMismatch() {
        val packet = audioPacket(sequence = 5, payload = byteArrayOf(1, 2, 3, 4))
        val serialized = encodePacket(packet.header, packet.payload)

        val parsed = ProtocolAudioPacket.parse(serialized)

        assertEquals(packet.header, parsed.header)
        assertArrayEquals(byteArrayOf(1, 2, 3, 4), parsed.payload)
        assertProtocolThrows(AudioRejectReason.PAYLOAD_LENGTH_MISMATCH) {
            ProtocolAudioPacket.parse(encodePacket(packet.header.toBuilder().setPayloadLength(5).build(), packet.payload))
        }
        assertProtocolThrows(AudioRejectReason.INVALID_HEADER) {
            ProtocolAudioPacket.parse(byteArrayOf(0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x01))
        }
    }

    @Test
    fun drainsContiguousPacketsAfterOutOfOrderArrival() {
        val buffer = AudioJitterBuffer(firstSequence = 1, maximumPackets = 4)
        val format = testFormat(framesPerPacket = 2)

        assertEquals(AudioEnqueueResult.Queued, buffer.enqueue(audioPacket(sequence = 2, payload = pcmPayload(format)), 5, format))
        assertEquals(emptyList<ProtocolAudioPacket>(), buffer.drainReady())
        assertEquals(AudioEnqueueResult.Queued, buffer.enqueue(audioPacket(sequence = 1, payload = pcmPayload(format, seed = 10)), 5, format))

        val ready = buffer.drainReady()
        assertEquals(listOf(1L, 2L), ready.map { it.header.sequence })
        assertEquals(0, buffer.queuedPacketCount())
    }

    @Test
    fun rejectsDuplicateStaleAndScopeMismatchedPackets() {
        val buffer = AudioJitterBuffer(firstSequence = 1, maximumPackets = 4)
        val format = testFormat(framesPerPacket = 2)

        val first = audioPacket(sequence = 1, payload = pcmPayload(format))
        assertEquals(AudioEnqueueResult.Queued, buffer.enqueue(first, 5, format))
        assertEquals(AudioEnqueueResult.Duplicate, buffer.enqueue(first, 5, format))
        assertEquals(listOf(1L), buffer.drainReady().map { it.header.sequence })
        assertEquals(AudioEnqueueResult.Stale, buffer.enqueue(first, 5, format))
        buffer.reset(firstSequence = 0)
        assertEquals(AudioEnqueueResult.Queued, buffer.enqueue(audioPacket(sequence = 0, payload = pcmPayload(format)), 5, format))
        assertEquals(listOf(0L), buffer.drainReady().map { it.header.sequence })

        assertProtocolThrows(AudioRejectReason.STALE_SESSION_EPOCH) {
            buffer.enqueue(audioPacket(sequence = 2, sessionEpoch = 4, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.FUTURE_SESSION_EPOCH) {
            buffer.enqueue(audioPacket(sequence = 2, sessionEpoch = 6, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.STALE_CONFIG_EPOCH) {
            buffer.enqueue(audioPacket(sequence = 2, configEpoch = 2, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.FUTURE_CONFIG_EPOCH) {
            buffer.enqueue(audioPacket(sequence = 2, configEpoch = 4, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.STREAM_MISMATCH) {
            buffer.enqueue(audioPacket(sequence = 2, streamId = 8, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.INVALID_SEQUENCE) {
            buffer.enqueue(audioPacket(sequence = -1, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.INVALID_PCM_BYTE_COUNT) {
            buffer.enqueue(audioPacket(sequence = 2, frameCount = 1, payload = pcmPayload(format)), 5, format)
        }
        assertProtocolThrows(AudioRejectReason.INVALID_PCM_BYTE_COUNT) {
            buffer.enqueue(audioPacket(sequence = 2, payload = pcmBytes(2)), 5, format)
        }
    }

    @Test
    fun boundedBufferAdvancesPastGapOrDropsNewest() {
        val gapBuffer = AudioJitterBuffer(firstSequence = 1, maximumPackets = 2)
        val format = testFormat(framesPerPacket = 2)

        assertEquals(AudioEnqueueResult.Queued, gapBuffer.enqueue(audioPacket(sequence = 3, payload = pcmPayload(format)), 5, format))
        assertEquals(AudioEnqueueResult.Queued, gapBuffer.enqueue(audioPacket(sequence = 4, payload = pcmPayload(format)), 5, format))
        assertEquals(AudioEnqueueResult.AdvancedPastGap(2), gapBuffer.enqueue(audioPacket(sequence = 5, payload = pcmPayload(format)), 5, format))
        assertEquals(listOf(3L, 4L), gapBuffer.drainReady().map { it.header.sequence })

        val newestDropBuffer = AudioJitterBuffer(firstSequence = 1, maximumPackets = 2)
        assertEquals(AudioEnqueueResult.Queued, newestDropBuffer.enqueue(audioPacket(sequence = 1, payload = pcmPayload(format)), 5, format))
        assertEquals(AudioEnqueueResult.Queued, newestDropBuffer.enqueue(audioPacket(sequence = 3, payload = pcmPayload(format)), 5, format))
        assertEquals(AudioEnqueueResult.QueueFullDropped(4), newestDropBuffer.enqueue(audioPacket(sequence = 4, payload = pcmPayload(format)), 5, format))
        assertEquals(listOf(1L), newestDropBuffer.drainReady().map { it.header.sequence })
        assertEquals(1, newestDropBuffer.queuedPacketCount())
    }

    private fun assertRejects(
        expected: AudioRejectReason,
        config: AudioConfig,
    ) {
        assertProtocolThrows(expected) { PcmAudioStreamFormat.from(config) }
    }
}

internal fun audioConfig(
    streamId: Long = 7,
    configEpoch: Long = 3,
    codec: AudioCodec = AudioCodec.AUDIO_CODEC_PCM_S16LE,
    sampleRateHz: Int = 48_000,
    channelCount: Int = 2,
    framesPerPacket: Int = 2,
): AudioConfig =
    AudioConfig
        .newBuilder()
        .setStreamId(streamId)
        .setConfigEpoch(configEpoch)
        .setCodec(codec)
        .setSampleRateHz(sampleRateHz)
        .setChannelCount(channelCount)
        .setFramesPerPacket(framesPerPacket)
        .build()

internal fun testFormat(
    streamId: Long = 7,
    configEpoch: Long = 3,
    sampleRateHz: Int = 48_000,
    channelCount: Int = 2,
    framesPerPacket: Int = 2,
): PcmAudioStreamFormat =
    PcmAudioStreamFormat.from(
        audioConfig(
            streamId = streamId,
            configEpoch = configEpoch,
            sampleRateHz = sampleRateHz,
            channelCount = channelCount,
            framesPerPacket = framesPerPacket,
        ),
    )

internal fun audioPacket(
    streamId: Long = 7,
    sessionEpoch: Long = 5,
    configEpoch: Long = 3,
    sequence: Long = 1,
    frameCount: Int = 2,
    payload: ByteArray = pcmBytes(8),
): ProtocolAudioPacket =
    ProtocolAudioPacket(
        AudioPacketHeader
            .newBuilder()
            .setStreamId(streamId)
            .setSessionEpoch(sessionEpoch)
            .setConfigEpoch(configEpoch)
            .setSequence(sequence)
            .setFrameCount(frameCount)
            .setPayloadLength(payload.size)
            .build(),
        payload,
    )

internal fun encodePacket(
    header: AudioPacketHeader,
    payload: ByteArray,
): ByteArray {
    val headerBytes = header.toByteArray()
    return encodeVarint(headerBytes.size) + headerBytes + payload
}

internal fun encodeVarint(value: Int): ByteArray {
    var remaining = value
    val output = mutableListOf<Byte>()
    do {
        var byte = remaining and 0x7f
        remaining = remaining ushr 7
        if (remaining > 0) byte = byte or 0x80
        output += byte.toByte()
    } while (remaining > 0)
    return output.toByteArray()
}

internal fun pcmBytes(
    size: Int,
    seed: Int = 0,
): ByteArray = ByteArray(size) { index -> (seed + index).toByte() }

internal fun pcmPayload(
    format: PcmAudioStreamFormat,
    seed: Int = 0,
): ByteArray = pcmBytes(format.bytesPerPacket, seed)

internal fun assertProtocolThrows(
    expected: AudioRejectReason,
    block: () -> Unit,
) {
    val failure = assertThrows(ProtocolAudioException::class.java, block)
    assertEquals(expected, failure.reason)
}
