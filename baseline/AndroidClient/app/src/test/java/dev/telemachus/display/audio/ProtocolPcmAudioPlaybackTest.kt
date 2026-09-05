package dev.telemachus.display.audio

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ProtocolPcmAudioPlaybackTest {
    @Test
    fun noConfigurationDiagnosticMatchesProductProtocolCode() {
        assertEquals("no_audio_configuration", AUDIO_PACKET_NO_CONFIGURATION_CODE)
    }

    @Test
    fun configureStartsOutputAndStopClosesIt() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        assertEquals(1, factory.created.size)
        assertEquals(listOf("start"), factory.created.single().events)
        assertEquals(testFormat(), player.activeFormat())

        player.stop()

        assertNull(player.activeFormat())
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
    }

    @Test
    fun configureRejectsInvalidConfigWithoutCreatingOutput() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(
            ProtocolAudioConfigureResult.Rejected(AudioRejectReason.UNSUPPORTED_CODEC),
            player.configure(audioConfig(codec = dev.vibescreen.protocol.v1.AudioCodec.AUDIO_CODEC_OPUS), sessionEpoch = 5),
        )

        assertEquals(0, factory.created.size)
        assertNull(player.activeFormat())
    }

    @Test
    fun configureRejectsInvalidSessionEpochWithoutCreatingOutput() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(
            ProtocolAudioConfigureResult.Rejected(AudioRejectReason.INVALID_SESSION_EPOCH),
            player.configure(audioConfig(), sessionEpoch = 0),
        )

        assertEquals(0, factory.created.size)
        assertNull(player.activeFormat())
    }

    @Test
    fun configureRejectsNegativeSessionEpochWithoutCreatingOutput() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(
            ProtocolAudioConfigureResult.Rejected(AudioRejectReason.INVALID_SESSION_EPOCH),
            player.configure(audioConfig(), sessionEpoch = -1),
        )

        assertEquals(0, factory.created.size)
        assertNull(player.activeFormat())
    }

    @Test
    fun invalidReconfigureStopsOldOutputAndLeavesPlayerUnconfigured() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))

        assertEquals(
            ProtocolAudioConfigureResult.Rejected(AudioRejectReason.UNSUPPORTED_CODEC),
            player.configure(audioConfig(codec = dev.vibescreen.protocol.v1.AudioCodec.AUDIO_CODEC_OPUS), sessionEpoch = 6),
        )

        assertNull(player.activeFormat())
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
    }

    @Test
    fun invalidSessionEpochReconfigureStopsOldOutputWithoutCreatingNewOutput() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))

        assertEquals(
            ProtocolAudioConfigureResult.Rejected(AudioRejectReason.INVALID_SESSION_EPOCH),
            player.configure(audioConfig(streamId = 9, configEpoch = 4), sessionEpoch = 0),
        )

        assertNull(player.activeFormat())
        assertEquals(1, factory.created.size)
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
    }

    @Test
    fun configureReportsOutputCreateAndStartFailures() {
        val createFailure = FakePcmAudioOutputFactory(createFailure = AudioOutputFailureReason.CREATE_FAILED)
        assertEquals(
            ProtocolAudioConfigureResult.PlaybackFailed(AudioOutputFailureReason.CREATE_FAILED),
            ProtocolPcmAudioPlayer(createFailure).configure(audioConfig(), sessionEpoch = 5),
        )

        val startFailure = FakePcmAudioOutputFactory(startFailure = AudioOutputFailureReason.START_FAILED)
        assertEquals(
            ProtocolAudioConfigureResult.PlaybackFailed(AudioOutputFailureReason.START_FAILED),
            ProtocolPcmAudioPlayer(startFailure).configure(audioConfig(), sessionEpoch = 5),
        )
        assertEquals(listOf("start", "stop", "close"), startFailure.created.single().events)
    }

    @Test
    fun submitRejectsWithoutConfigurationAndRejectsMalformedPacketBytes() {
        val player = ProtocolPcmAudioPlayer(FakePcmAudioOutputFactory())

        assertEquals(
            ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.NO_CONFIGURATION),
            player.submit(audioPacket()),
        )
        assertEquals(
            ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.ProtocolRejected(AudioRejectReason.INVALID_HEADER)),
            player.submit(byteArrayOf(0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x01)),
        )
    }

    @Test
    fun writesReadyPacketsInSequenceOrderAfterOutOfOrderSubmit() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        val format = checkNotNull(player.activeFormat())
        val second = audioPacket(sequence = 1, payload = pcmPayload(format, seed = 20))
        val first = audioPacket(sequence = 0, payload = pcmPayload(format, seed = 10))

        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 0),
            player.submit(second),
        )
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 2),
            player.submit(first),
        )

        val output = factory.created.single()
        assertEquals(2, output.writes.size)
        assertArrayEquals(first.payload, output.writes[0])
        assertArrayEquals(second.payload, output.writes[1])
    }

    @Test
    fun usbLanPcmProductFlowFixtureWritesAudioTrackPayloadsAndStops() {
        val fixture = loadUsbLanPcmAudioFixture()
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(
            ProtocolAudioConfigureResult.Accepted(fixture.config.streamId, fixture.config.configEpoch),
            player.configure(fixture.audioConfig(), sessionEpoch = fixture.sessionEpoch),
        )
        assertEquals(
            fixture.packets.map { ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 1) },
            fixture.packets.map { packet -> player.submit(packet.serializedFrameBytes) },
        )

        player.stop()

        assertEquals(1, factory.created.size)
        assertEquals(fixture.cleanupExpectations.outputEventsAfterConfigPacketDisconnect, factory.created.single().events)
        assertEquals(fixture.packets.map { it.payloadBytes.toList() }, factory.created.single().writes.map { it.toList() })
    }

    @Test
    fun submitRejectsScopeMismatchWithoutWriting() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))

        assertEquals(
            ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.ProtocolRejected(AudioRejectReason.FUTURE_CONFIG_EPOCH)),
            player.submit(audioPacket(configEpoch = 4)),
        )

        assertEquals(0, factory.created.single().writes.size)
    }

    @Test
    fun threeChannelPcmConfigurationCreatesOutputWithExpectedPacketSize() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(
            ProtocolAudioConfigureResult.Accepted(7, 3),
            player.configure(audioConfig(channelCount = 3, framesPerPacket = 4), sessionEpoch = 5),
        )

        assertEquals(1, factory.created.size)
        assertEquals(3, factory.created.single().format.channelCount)
        assertEquals(24, factory.created.single().format.bytesPerPacket)
    }

    @Test
    fun backpressureDropResultsStayAcceptedAndPlaybackContinues() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory, maximumBufferedPackets = 2)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        val format = checkNotNull(player.activeFormat())

        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 0),
            player.submit(audioPacket(sequence = 1, payload = pcmPayload(format, seed = 20))),
        )
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 0),
            player.submit(audioPacket(sequence = 2, payload = pcmPayload(format, seed = 30))),
        )
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.QueueFullDropped(2), writtenPackets = 2),
            player.submit(audioPacket(sequence = 0, payload = pcmPayload(format, seed = 10))),
        )
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 1),
            player.submit(audioPacket(sequence = 2, payload = pcmPayload(format, seed = 30))),
        )

        assertEquals(3, factory.created.single().writes.size)
        assertEquals(
            listOf(
                pcmPayload(format, seed = 10).toList(),
                pcmPayload(format, seed = 20).toList(),
                pcmPayload(format, seed = 30).toList(),
            ),
            factory.created.single().writes.map { it.toList() },
        )
    }

    @Test
    fun writeFailureStopsActiveOutputAndRejectsFurtherPacketsUntilReconfigured() {
        val factory = FakePcmAudioOutputFactory(writeFailures = mutableListOf(AudioOutputFailureReason.WRITE_DEAD_OBJECT))
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        val format = checkNotNull(player.activeFormat())

        assertEquals(
            ProtocolAudioPacketResult.PlaybackFailed(AudioOutputFailureReason.WRITE_DEAD_OBJECT),
            player.submit(audioPacket(sequence = 0, payload = pcmPayload(format))),
        )

        assertNull(player.activeFormat())
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
        assertEquals(
            ProtocolAudioPacketResult.Rejected(AudioPacketRejectReason.NO_CONFIGURATION),
            player.submit(audioPacket(sequence = 1, payload = pcmPayload(format))),
        )
    }

    @Test
    fun reconfigureClosesOldOutputAndStartsFreshSequence() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)

        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        val firstFormat = checkNotNull(player.activeFormat())
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 1),
            player.submit(audioPacket(sequence = 0, payload = pcmPayload(firstFormat))),
        )
        assertEquals(
            ProtocolAudioConfigureResult.Accepted(9, 4),
            player.configure(audioConfig(streamId = 9, configEpoch = 4, channelCount = 1, framesPerPacket = 3), sessionEpoch = 6),
        )

        assertEquals(listOf("start", "write", "stop", "close"), factory.created[0].events)
        assertEquals(listOf("start"), factory.created[1].events)
        assertEquals(
            ProtocolAudioPacketResult.Accepted(AudioEnqueueResult.Queued, writtenPackets = 1),
            player.submit(
                audioPacket(
                    streamId = 9,
                    sessionEpoch = 6,
                    configEpoch = 4,
                    sequence = 0,
                    frameCount = 3,
                    payload = pcmBytes(6),
                ),
            ),
        )
        assertEquals(1, factory.created[1].writes.size)
    }

    @Test
    fun reconfigureCreateFailureStopsOldOutputAndLeavesPlayerUnconfigured() {
        val factory = FakePcmAudioOutputFactory()
        val player = ProtocolPcmAudioPlayer(factory)
        assertEquals(ProtocolAudioConfigureResult.Accepted(7, 3), player.configure(audioConfig(), sessionEpoch = 5))
        factory.createFailure = AudioOutputFailureReason.CREATE_FAILED

        assertEquals(
            ProtocolAudioConfigureResult.PlaybackFailed(AudioOutputFailureReason.CREATE_FAILED),
            player.configure(audioConfig(streamId = 9, configEpoch = 4), sessionEpoch = 6),
        )

        assertNull(player.activeFormat())
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
    }
}

private class FakePcmAudioOutputFactory(
    var createFailure: AudioOutputFailureReason? = null,
    private val startFailure: AudioOutputFailureReason? = null,
    private val writeFailures: MutableList<AudioOutputFailureReason> = mutableListOf(),
) : PcmAudioOutputFactory {
    val created = mutableListOf<FakePcmAudioOutput>()

    override fun create(format: PcmAudioStreamFormat): PcmAudioOutput {
        createFailure?.let { throw AudioOutputException(it) }
        return FakePcmAudioOutput(startFailure, writeFailures, format).also { created += it }
    }
}

private class FakePcmAudioOutput(
    private val startFailure: AudioOutputFailureReason?,
    private val writeFailures: MutableList<AudioOutputFailureReason>,
    val format: PcmAudioStreamFormat,
) : PcmAudioOutput {
    val events = mutableListOf<String>()
    val writes = mutableListOf<ByteArray>()

    override fun start() {
        events += "start"
        startFailure?.let { throw AudioOutputException(it) }
    }

    override fun writePcm(payload: ByteArray): PcmAudioWriteResult {
        if (writeFailures.isNotEmpty()) {
            return PcmAudioWriteResult.Failed(writeFailures.removeAt(0))
        }
        events += "write"
        writes += payload.copyOf()
        return PcmAudioWriteResult.Written
    }

    override fun stop() {
        events += "stop"
    }

    override fun close() {
        stop()
        events += "close"
    }
}
