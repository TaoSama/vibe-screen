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
import dev.vibescreen.protocol.v1.AudioCodec
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
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
        assertEquals(format, playback.readinessSnapshot().activeFormat)
        assertEquals(1L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(1L, playback.readinessSnapshot().writtenPacketCount)
    }

    @Test
    fun stopClearsReadinessSnapshot() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1, framesPerPacket = 2)
        val format = PcmAudioStreamFormat.from(config)
        val packet =
            audioPacket(
                streamId = config.streamId,
                sessionEpoch = 7,
                configEpoch = config.configEpoch,
                sequence = 0,
                frameCount = config.framesPerPacket,
                payload = pcmPayload(format),
            )
        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)
        assertTrue(playback.submit(encodePacket(packet.header, packet.payload)).accepted)

        playback.stop("test_disconnect")

        assertEquals(null, playback.readinessSnapshot().activeFormat)
        assertEquals(0L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(0L, playback.readinessSnapshot().writtenPacketCount)
    }

    @Test
    fun concurrentStopCannotLeaveInactiveSnapshotWithStaleCounters() {
        val writeGate = BlockingWriteGate()
        val factory = FakePcmAudioOutputFactory(writeGate = writeGate)
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1, framesPerPacket = 2)
        val format = PcmAudioStreamFormat.from(config)
        val packet =
            audioPacket(
                streamId = config.streamId,
                sessionEpoch = 7,
                configEpoch = config.configEpoch,
                sequence = 0,
                frameCount = config.framesPerPacket,
                payload = pcmPayload(format),
            )
        val submitDecision = AtomicReference<InternetAudioDecision>()
        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)

        val submitThread = Thread { submitDecision.set(playback.submit(encodePacket(packet.header, packet.payload))) }
        submitThread.start()
        assertTrue("submit should reach the blocking write", writeGate.entered.await(2, TimeUnit.SECONDS))

        val stopCompleted = CountDownLatch(1)
        val stopThread =
            Thread {
                playback.stop("concurrent_stop")
                stopCompleted.countDown()
            }
        stopThread.start()
        assertFalse("stop must wait for submit to leave the wrapper critical section", stopCompleted.await(100, TimeUnit.MILLISECONDS))

        writeGate.release.countDown()
        submitThread.join(2_000)
        stopThread.join(2_000)

        assertFalse("submit thread should finish", submitThread.isAlive)
        assertFalse("stop thread should finish", stopThread.isAlive)
        assertTrue(checkNotNull(submitDecision.get()).accepted)
        assertEquals(null, playback.readinessSnapshot().activeFormat)
        assertEquals(0L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(0L, playback.readinessSnapshot().writtenPacketCount)
    }

    @Test
    fun rejectedReconfigureClearsReadinessSnapshot() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1, framesPerPacket = 2)
        val format = PcmAudioStreamFormat.from(config)
        val packet =
            audioPacket(
                streamId = config.streamId,
                sessionEpoch = 7,
                configEpoch = config.configEpoch,
                sequence = 0,
                frameCount = config.framesPerPacket,
                payload = pcmPayload(format),
            )
        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)
        assertTrue(playback.submit(encodePacket(packet.header, packet.payload)).accepted)

        val decision = playback.configure(audioConfig(codec = AudioCodec.AUDIO_CODEC_OPUS), sessionEpoch = 8)

        assertFalse(decision.accepted)
        assertEquals(null, playback.readinessSnapshot().activeFormat)
        assertEquals(0L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(0L, playback.readinessSnapshot().writtenPacketCount)
    }

    @Test
    fun playbackFailedConfigureClearsReadinessSnapshot() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        assertTrue(playback.configure(audioConfig(streamId = 2, configEpoch = 1), sessionEpoch = 7).accepted)
        factory.startFailures += AudioOutputFailureReason.START_FAILED

        val decision = playback.configure(audioConfig(streamId = 3, configEpoch = 2), sessionEpoch = 8)

        assertFalse(decision.accepted)
        assertEquals("audio_track_start_failed", decision.rejectionReason)
        assertEquals(null, playback.readinessSnapshot().activeFormat)
        assertEquals(0L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(0L, playback.readinessSnapshot().writtenPacketCount)
    }

    @Test
    fun rejectedSubmitDoesNotIncrementAcceptedCounters() {
        val factory = FakePcmAudioOutputFactory()
        val playback = ProtocolInternetAudioPlayback(ProtocolPcmAudioPlayer(factory))
        val config = audioConfig(streamId = 2, configEpoch = 1)
        val format = PcmAudioStreamFormat.from(config)
        val valid =
            audioPacket(
                streamId = config.streamId,
                sessionEpoch = 7,
                configEpoch = config.configEpoch,
                sequence = 0,
                frameCount = config.framesPerPacket,
                payload = pcmPayload(format),
            )
        assertTrue(playback.configure(config, sessionEpoch = 7).accepted)
        assertTrue(playback.submit(encodePacket(valid.header, valid.payload)).accepted)

        val decision = playback.submit(byteArrayOf(0x80.toByte(), 0x80.toByte(), 0x01))

        assertFalse(decision.accepted)
        assertEquals(1L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(1L, playback.readinessSnapshot().writtenPacketCount)
        assertEquals(format, playback.readinessSnapshot().activeFormat)
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
        assertEquals(null, playback.readinessSnapshot().activeFormat)
        assertEquals(0L, playback.readinessSnapshot().acceptedPacketCount)
        assertEquals(0L, playback.readinessSnapshot().writtenPacketCount)
    }
}

private class FakePcmAudioOutputFactory(
    val startFailures: MutableList<AudioOutputFailureReason> = mutableListOf(),
    private val writeFailures: MutableList<AudioOutputFailureReason> = mutableListOf(),
    private val writeGate: BlockingWriteGate? = null,
) : PcmAudioOutputFactory {
    val created = mutableListOf<FakePcmAudioOutput>()

    override fun create(format: PcmAudioStreamFormat): PcmAudioOutput =
        FakePcmAudioOutput(startFailures, writeFailures, writeGate, format).also { created += it }
}

private class BlockingWriteGate {
    val entered = CountDownLatch(1)
    val release = CountDownLatch(1)
}

private class FakePcmAudioOutput(
    private val startFailures: MutableList<AudioOutputFailureReason>,
    private val writeFailures: MutableList<AudioOutputFailureReason>,
    private val writeGate: BlockingWriteGate?,
    val format: PcmAudioStreamFormat,
) : PcmAudioOutput {
    val events = mutableListOf<String>()
    val writes = mutableListOf<ByteArray>()
    private var closed = false

    override fun start() {
        events += "start"
        if (startFailures.isNotEmpty()) {
            throw dev.telemachus.display.audio.AudioOutputException(startFailures.removeAt(0))
        }
    }

    override fun writePcm(payload: ByteArray): PcmAudioWriteResult {
        if (writeFailures.isNotEmpty()) {
            return PcmAudioWriteResult.Failed(writeFailures.removeAt(0))
        }
        writeGate?.let { gate ->
            gate.entered.countDown()
            check(gate.release.await(2, TimeUnit.SECONDS)) { "Timed out waiting to release blocked audio write" }
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
