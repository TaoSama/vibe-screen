package dev.telemachus.display.audio

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path

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
    fun usbLanPcmProductFlowFixtureMatchesProtocolParser() {
        val fixture = loadUsbLanPcmAudioFixture()
        val config = fixture.audioConfig()
        val format = PcmAudioStreamFormat.from(config)

        assertEquals(listOf("usb", "lan"), fixture.transportModes)
        assertEquals("CAPABILITY_AUDIO", fixture.capability)
        assertEquals("AUDIO", fixture.protocolChannelName)
        assertEquals(3, fixture.protocolChannelId)
        assertEquals("connection_cleanup", fixture.cleanupExpectations.disconnectStopReason)
        assertEquals("audio_reconfigure", fixture.cleanupExpectations.hostStopReason)
        assertEquals(listOf("start", "write", "write", "stop", "close"), fixture.cleanupExpectations.outputEventsAfterConfigPacketDisconnect)
        assertEquals(listOf("start", "stop", "close"), fixture.cleanupExpectations.outputEventsAfterConfigReject)
        assertEquals(listOf("start", "stop", "close"), fixture.cleanupExpectations.outputEventsAfterPacketError)
        assertEquals(fixture.config.streamId, format.streamId)
        assertEquals(fixture.config.configEpoch, format.configEpoch)
        assertEquals(fixture.config.sampleRateHz, format.sampleRateHz)
        assertEquals(fixture.config.channelCount, format.channelCount)
        assertEquals(fixture.config.framesPerPacket, format.framesPerPacket)
        assertEquals(fixture.config.bytesPerPacket, format.bytesPerPacket)
        assertArrayEquals(fixture.config.serializedBytes, config.toByteArray())
        assertArrayEquals(fixture.acceptedConfigResult.serializedBytes, fixture.acceptedConfigResult.message().toByteArray())

        val buffer = AudioJitterBuffer(firstSequence = fixture.packets.first().sequence)
        fixture.packets.reversed().forEach { packetFixture ->
            val parsed = ProtocolAudioPacket.parse(packetFixture.serializedFrameBytes)
            assertEquals(fixture.config.streamId, parsed.header.streamId)
            assertEquals(fixture.sessionEpoch, parsed.header.sessionEpoch)
            assertEquals(fixture.config.configEpoch, parsed.header.configEpoch)
            assertEquals(packetFixture.sequence, parsed.header.sequence)
            assertEquals(packetFixture.frameCount, parsed.header.frameCount)
            assertEquals(packetFixture.payloadBytes.size, parsed.header.payloadLength)
            assertArrayEquals(packetFixture.headerBytes, parsed.header.toByteArray())
            assertArrayEquals(packetFixture.payloadBytes, parsed.payload)
            assertEquals(AudioEnqueueResult.Queued, buffer.enqueue(parsed, fixture.sessionEpoch, format))
        }

        val ready = buffer.drainReady()
        assertEquals(fixture.packets.map { it.sequence }, ready.map { it.header.sequence })
        fixture.packets.zip(ready).forEach { (expected, actual) ->
            assertArrayEquals(expected.payloadBytes, actual.payload)
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

internal data class UsbLanPcmAudioFixture(
    val transportModes: List<String>,
    val capability: String,
    val protocolChannelName: String,
    val protocolChannelId: Int,
    val sessionEpoch: Long,
    val config: FixtureAudioConfig,
    val acceptedConfigResult: FixtureAudioConfigResult,
    val capture: FixtureCapture,
    val packets: List<FixtureAudioPacket>,
    val cleanupExpectations: FixtureCleanupExpectations,
) {
    fun audioConfig(): AudioConfig =
        AudioConfig
            .newBuilder()
            .setStreamId(config.streamId)
            .setConfigEpoch(config.configEpoch)
            .setCodec(AudioCodec.valueOf(config.codec))
            .setSampleRateHz(config.sampleRateHz)
            .setChannelCount(config.channelCount)
            .setFramesPerPacket(config.framesPerPacket)
            .build()
}

internal data class FixtureAudioConfig(
    val streamId: Long,
    val configEpoch: Long,
    val codec: String,
    val sampleRateHz: Int,
    val channelCount: Int,
    val framesPerPacket: Int,
    val bytesPerPacket: Int,
    val serializedBytes: ByteArray,
)

internal data class FixtureAudioConfigResult(
    val streamId: Long,
    val configEpoch: Long,
    val accepted: Boolean,
    val rejectionReason: String,
    val serializedBytes: ByteArray,
) {
    fun message(): dev.vibescreen.protocol.v1.AudioConfigResult =
        dev.vibescreen.protocol.v1.AudioConfigResult
            .newBuilder()
            .setStreamId(streamId)
            .setConfigEpoch(configEpoch)
            .setAccepted(accepted)
            .setRejectionReason(rejectionReason)
            .build()
}

internal data class FixtureCapture(
    val frameCount: Int,
    val timestampMonotonicNs: Long,
    val pcmS16LEBytes: ByteArray,
)

internal data class FixtureAudioPacket(
    val sequence: Long,
    val frameCount: Int,
    val timestampMonotonicNs: Long,
    val payloadBytes: ByteArray,
    val headerBytes: ByteArray,
    val serializedFrameBytes: ByteArray,
)

internal data class FixtureCleanupExpectations(
    val disconnectStopReason: String,
    val hostStopReason: String,
    val outputEventsAfterConfigPacketDisconnect: List<String>,
    val outputEventsAfterConfigReject: List<String>,
    val outputEventsAfterPacketError: List<String>,
)

internal fun loadUsbLanPcmAudioFixture(): UsbLanPcmAudioFixture {
    val relative = Path.of("contracts", "fixtures", "audio", "v1", "usb-lan-pcm-s16le-product-flow.json")
    val fixturePath = generateSequence(Path.of(System.getProperty("user.dir")).toAbsolutePath()) { it.parent }
        .map { it.resolve(relative) }
        .firstOrNull(Files::isRegularFile)
        ?: error("Unable to locate USB/LAN PCM audio fixture from " + System.getProperty("user.dir"))
    val root = JsonParser.parseString(String(Files.readAllBytes(fixturePath), StandardCharsets.UTF_8)).asJsonObject
    val config = root.getAsJsonObject("config")
    val result = root.getAsJsonObject("accepted_config_result")
    val capture = root.getAsJsonObject("capture")
    val channel = root.getAsJsonObject("protocol_channel")
    val cleanup = root.getAsJsonObject("cleanup_expectations")
    val packets = root.getAsJsonArray("packets").map { item ->
        val packet = item.asJsonObject
        FixtureAudioPacket(
            sequence = packet.long("sequence"),
            frameCount = packet.int("frame_count"),
            timestampMonotonicNs = packet.long("timestamp_monotonic_ns"),
            payloadBytes = hexToBytes(packet.string("payload_hex")),
            headerBytes = hexToBytes(packet.string("header_hex")),
            serializedFrameBytes = hexToBytes(packet.string("serialized_frame_hex")),
        )
    }
    return UsbLanPcmAudioFixture(
        transportModes = root.getAsJsonArray("transport_modes").map { it.asString },
        capability = root.string("capability"),
        protocolChannelName = channel.string("name"),
        protocolChannelId = channel.int("id"),
        sessionEpoch = root.long("session_epoch"),
        config = FixtureAudioConfig(
            streamId = config.long("stream_id"),
            configEpoch = config.long("config_epoch"),
            codec = config.string("codec"),
            sampleRateHz = config.int("sample_rate_hz"),
            channelCount = config.int("channel_count"),
            framesPerPacket = config.int("frames_per_packet"),
            bytesPerPacket = config.int("bytes_per_packet"),
            serializedBytes = hexToBytes(config.string("serialized_hex")),
        ),
        acceptedConfigResult = FixtureAudioConfigResult(
            streamId = result.long("stream_id"),
            configEpoch = result.long("config_epoch"),
            accepted = result.get("accepted").asBoolean,
            rejectionReason = result.string("rejection_reason"),
            serializedBytes = hexToBytes(result.string("serialized_hex")),
        ),
        capture = FixtureCapture(
            frameCount = capture.int("frame_count"),
            timestampMonotonicNs = capture.long("timestamp_monotonic_ns"),
            pcmS16LEBytes = hexToBytes(capture.string("pcm_s16le_hex")),
        ),
        packets = packets,
        cleanupExpectations = FixtureCleanupExpectations(
            disconnectStopReason = cleanup.string("disconnect_stop_reason"),
            hostStopReason = cleanup.string("host_stop_reason"),
            outputEventsAfterConfigPacketDisconnect = cleanup.stringList("output_events_after_config_packet_disconnect"),
            outputEventsAfterConfigReject = cleanup.stringList("output_events_after_config_reject"),
            outputEventsAfterPacketError = cleanup.stringList("output_events_after_packet_error"),
        ),
    )
}

private fun JsonObject.string(name: String): String = get(name).asString

private fun JsonObject.long(name: String): Long = get(name).asLong

private fun JsonObject.int(name: String): Int = get(name).asInt

private fun JsonObject.stringList(name: String): List<String> = getAsJsonArray(name).map { it.asString }

internal fun hexToBytes(value: String): ByteArray {
    require(value.length % 2 == 0) { "hex string must have even length" }
    return ByteArray(value.length / 2) { index ->
        value.substring(index * 2, index * 2 + 2).toInt(16).toByte()
    }
}
