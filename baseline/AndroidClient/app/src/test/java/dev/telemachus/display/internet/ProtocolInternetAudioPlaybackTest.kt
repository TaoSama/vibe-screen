package dev.telemachus.display.internet

import dev.telemachus.display.audio.AUDIO_PACKET_NO_CONFIGURATION_CODE
import dev.telemachus.display.audio.AudioOutputFailureReason
import dev.telemachus.display.audio.PcmAudioOutput
import dev.telemachus.display.audio.PcmAudioOutputFactory
import dev.telemachus.display.audio.PcmAudioStreamFormat
import dev.telemachus.display.audio.PcmAudioWriteResult
import dev.telemachus.display.audio.ProtocolPcmAudioPlayer
import dev.telemachus.display.audio.audioConfig
import dev.telemachus.display.audio.audioPacket
import dev.telemachus.display.audio.encodePacket
import dev.telemachus.display.audio.pcmPayload
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolInternetAudioPlaybackTest {
    @Test
    fun submitBeforeConfigurationUsesSharedNoConfigurationDiagnostic() {
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(FakePcmAudioOutputFactory()))
        val packet = audioPacket()
        val decision = playback.submit(encodePacket(packet.header, packet.payload))

        assertFalse(decision.accepted)
        assertEquals(AUDIO_PACKET_NO_CONFIGURATION_CODE, decision.rejectionReason)
    }

    @Test
    fun configureAndSubmitWritePcmFramesThroughProtocolPlayer() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1, framesPerPacket = 2)
        val format = PcmAudioStreamFormat.from(config)
        val payload = pcmPayload(format, seed = 42)
        val packet = audioPacket(
            streamId = config.streamId,
            sessionEpoch = 7,
            configEpoch = config.configEpoch,
            sequence = 0,
            frameCount = config.framesPerPacket,
            payload = payload,
        )

        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)
        assertTrue(playback.submit(encodePacket(packet.header, packet.payload)).accepted)

        val output = factory.created.single()
        assertEquals(listOf("start", "write"), output.events)
        assertArrayEquals(payload, output.writes.single())
    }

    @Test
    fun malformedPacketPropagatesProtocolRejectReason() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        assertTrue(playback.configure(audioConfig(), sessionEpoch = 7).accepted)

        val decision = playback.submit(byteArrayOf(0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x80.toByte(), 0x01))

        assertFalse(decision.accepted)
        assertEquals("invalid_audio_header", decision.rejectionReason)
        assertEquals(0, factory.created.single().writes.size)
    }

    @Test
    fun playbackWriteFailureUsesAudioTrackDiagnostic() {
        val factory = FakePcmAudioOutputFactory(writeFailures = mutableListOf(AudioOutputFailureReason.WRITE_DEAD_OBJECT))
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1, framesPerPacket = 2)
        val format = PcmAudioStreamFormat.from(config)
        val packet = audioPacket(
            streamId = config.streamId,
            sessionEpoch = 7,
            configEpoch = config.configEpoch,
            sequence = 0,
            frameCount = config.framesPerPacket,
            payload = pcmPayload(format),
        )

        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)
        val decision = playback.submit(encodePacket(packet.header, packet.payload))

        assertFalse(decision.accepted)
        assertEquals("audio_track_write_dead_object", decision.rejectionReason)
        assertEquals(listOf("start", "stop", "close"), factory.created.single().events)
    }
}

private class FakePcmAudioOutputFactory(
    private val writeFailures: MutableList<AudioOutputFailureReason> = mutableListOf(),
) : PcmAudioOutputFactory {
    val created = mutableListOf<FakePcmAudioOutput>()

    override fun create(format: PcmAudioStreamFormat): PcmAudioOutput =
        FakePcmAudioOutput(writeFailures, format).also { created += it }
}

private class FakePcmAudioOutput(
    private val writeFailures: MutableList<AudioOutputFailureReason>,
    val format: PcmAudioStreamFormat,
) : PcmAudioOutput {
    val events = mutableListOf<String>()
    val writes = mutableListOf<ByteArray>()
    private var closed = false

    override fun start() {
        events += "start"
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
        if (closed) return
        closed = true
        stop()
        events += "close"
    }
}
