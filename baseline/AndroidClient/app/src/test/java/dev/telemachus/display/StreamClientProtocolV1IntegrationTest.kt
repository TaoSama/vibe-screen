package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.audio.AudioOutputFailureReason
import dev.telemachus.display.audio.AudioOutputException
import dev.telemachus.display.audio.PcmAudioOutput
import dev.telemachus.display.audio.PcmAudioOutputFactory
import dev.telemachus.display.audio.PcmAudioStreamFormat
import dev.telemachus.display.audio.PcmAudioWriteResult
import dev.telemachus.display.audio.ProtocolPcmAudioPlayer
import dev.telemachus.display.audio.encodePacket
import dev.telemachus.display.audio.loadUsbLanPcmAudioFixture
import dev.telemachus.display.audio.pcmPayload
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolFrame
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.TouchSample
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.ClipboardRequest
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DisconnectNotice
import dev.vibescreen.protocol.v1.DisplayChanged
import dev.vibescreen.protocol.v1.DisplayDescriptor
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.HostActionCatalog
import dev.vibescreen.protocol.v1.HostActionDescriptor
import dev.vibescreen.protocol.v1.HostActionResult
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.VideoConfig
import dev.vibescreen.protocol.v1.WakeHostRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.io.OutputStream
import java.io.File
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class StreamClientProtocolV1IntegrationTest {
    @Test
    fun negotiatedAudioConfigEnablesPcmPlaybackAndStopsOnDisconnect() = runBlocking {
        ServerSocket(0).use { server ->
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val audioFrameWritten = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            audioOutputFactory.onWrite = { audioFrameWritten.countDown() }
            val configurationRequested = CountDownLatch(1)
            val audioConfig = audioConfig()
            val audioPayload = pcmPayload(PcmAudioStreamFormat.from(audioConfig), seed = 30)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(audioConfig).build())
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.AUDIO_CONFIG_RESULT, result.payloadCase)
                        assertTrue(result.audioConfigResult.accepted)
                        assertEquals(audioConfig.streamId, result.audioConfigResult.streamId)
                        assertEquals(audioConfig.configEpoch, result.audioConfigResult.configEpoch)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            encodePacket(
                                AudioPacketHeader.newBuilder()
                                    .setStreamId(audioConfig.streamId)
                                    .setSessionEpoch(7)
                                    .setConfigEpoch(audioConfig.configEpoch)
                                    .setSequence(0)
                                    .setFrameCount(audioConfig.framesPerPacket)
                                    .setPayloadLength(audioPayload.size)
                                    .build(),
                                audioPayload,
                            ),
                        )
                        assertTrue(audioFrameWritten.await(8, TimeUnit.SECONDS))
                        write(peer, disconnect(id = 7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = { sessionEnded.countDown() }
            client.onVideoConfiguration = { _, commit ->
                commit.accept()
                configurationRequested.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(listOf("start", "write", "stop", "close"), audioOutputFactory.created.single().events)
            assertEquals(listOf(audioPayload.toList()), audioOutputFactory.created.single().writes.map { it.toList() })
        }
    }

    @Test
    fun usbLanPcmFixtureNegotiatesWritesAndCleansUpOnDisconnect() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val writtenPackets = CountDownLatch(fixture.packets.size)
            val sessionEnded = CountDownLatch(1)
            audioOutputFactory.onWrite = { writtenPackets.countDown() }
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(fixture.audioConfig()).build())
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.AUDIO_CONFIG_RESULT, result.payloadCase)
                        assertArrayEquals(fixture.acceptedConfigResult.serializedBytes, result.audioConfigResult.toByteArray())

                        fixture.packets.forEach { packet ->
                            ProtocolV1Framing.write(
                                peer.getOutputStream(),
                                ProtocolChannel.AUDIO,
                                packet.serializedFrameBytes,
                            )
                        }
                        assertTrue(writtenPackets.await(8, TimeUnit.SECONDS))
                        write(peer, disconnect(id = 7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = { sessionEnded.countDown() }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(
                fixture.cleanupExpectations.outputEventsAfterConfigPacketDisconnect,
                audioOutputFactory.created.single().events,
            )
            assertEquals(
                fixture.packets.map { it.payloadBytes.toList() },
                audioOutputFactory.created.single().writes.map { it.toList() },
            )
        }
    }

    @Test
    fun rejectedAudioReconfigurationStopsExistingPlayback() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val sessionEnded = CountDownLatch(1)
            val acceptedConfig = audioConfig()
            val rejectedConfig = audioConfig(codec = AudioCodec.AUDIO_CODEC_OPUS, configEpoch = 2)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(acceptedConfig).build())
                        val accepted = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.AUDIO_CONFIG_RESULT, accepted.payloadCase)
                        assertTrue(accepted.audioConfigResult.accepted)

                        write(peer, base(7).setAudioConfig(rejectedConfig).build())
                        val rejected = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.AUDIO_CONFIG_RESULT, rejected.payloadCase)
                        assertFalse(rejected.audioConfigResult.accepted)
                        assertEquals("unsupported_codec", rejected.audioConfigResult.rejectionReason)
                        write(peer, disconnect(id = 8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = { sessionEnded.countDown() }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(fixture.cleanupExpectations.outputEventsAfterConfigReject, audioOutputFactory.created.single().events)
        }
    }

    @Test
    fun malformedAudioPacketAfterAcceptedConfigFailsSessionAndReleasesOutput() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(fixture.audioConfig()).build())
                        assertTrue(readEnvelope(peer).audioConfigResult.accepted)
                        val firstPacket = fixture.packets.first().serializedFrameBytes
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            firstPacket.copyOfRange(0, firstPacket.size - 1),
                        )
                    }
                }
            var failure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = {
                failure = it
                sessionEnded.countDown()
            }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_MEDIA_PAYLOAD, checkNotNull(failure).kind)
            assertEquals(fixture.cleanupExpectations.outputEventsAfterPacketError, audioOutputFactory.created.single().events)
        }
    }

    @Test
    fun audioPacketOnChannelThreeWithoutNegotiatedCapabilityFailsClosed() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH),
                        )
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            fixture.packets.first().serializedFrameBytes,
                        )
                    }
                }
            var failure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = {
                failure = it
                sessionEnded.countDown()
            }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_MEDIA_PAYLOAD, checkNotNull(failure).kind)
            assertTrue(checkNotNull(failure).detail.contains("Audio packet received before AudioConfig acceptance"))
            assertEquals(0, audioOutputFactory.created.size)
        }
    }

    @Test
    fun staleAudioEpochOnProductChannelFailsSessionAndReleasesOutput() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(fixture.audioConfig()).build())
                        val configResult = readEnvelope(peer)
                        assertEquals(
                            configResult.protocolError.message,
                            Envelope.PayloadCase.AUDIO_CONFIG_RESULT,
                            configResult.payloadCase,
                        )
                        assertTrue(configResult.audioConfigResult.rejectionReason, configResult.audioConfigResult.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            encodePacket(
                                AudioPacketHeader.newBuilder()
                                    .setStreamId(fixture.config.streamId)
                                    .setSessionEpoch(fixture.sessionEpoch - 1)
                                    .setConfigEpoch(fixture.config.configEpoch)
                                    .setSequence(0)
                                    .setFrameCount(fixture.config.framesPerPacket)
                                    .setPayloadLength(fixture.packets.first().payloadBytes.size)
                                    .build(),
                                fixture.packets.first().payloadBytes,
                            ),
                        )
                    }
                }
            var failure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = {
                failure = it
                sessionEnded.countDown()
            }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_MEDIA_PAYLOAD, checkNotNull(failure).kind)
            assertTrue(checkNotNull(failure).detail.contains("stale_session_epoch"))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(fixture.cleanupExpectations.outputEventsAfterPacketError, audioOutputFactory.created.single().events)
        }
    }

    @Test
    fun audioTrackWriteFailureOnProductChannelFailsSessionAndCleansUp() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory().apply {
                writeFailures += AudioOutputFailureReason.WRITE_DEAD_OBJECT
            }
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_AUDIO),
                        )
                        write(peer, base(6).setAudioConfig(fixture.audioConfig()).build())
                        val configResult = readEnvelope(peer)
                        assertEquals(
                            configResult.protocolError.message,
                            Envelope.PayloadCase.AUDIO_CONFIG_RESULT,
                            configResult.payloadCase,
                        )
                        assertTrue(configResult.audioConfigResult.rejectionReason, configResult.audioConfigResult.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            fixture.packets.first().serializedFrameBytes,
                        )
                    }
                }
            var failure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = {
                failure = it
                sessionEnded.countDown()
            }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.CODEC_CONFIGURATION, checkNotNull(failure).kind)
            assertTrue(checkNotNull(failure).detail.contains("audio_playback_failed: audio_track_write_dead_object"))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(listOf("start", "stop", "close"), audioOutputFactory.created.single().events)
            assertTrue(audioOutputFactory.created.single().writes.isEmpty())
        }
    }

    @Test
    fun managedPolicyAudioDenyStopsPlaybackAndRejectsFurtherAudioPackets() = runBlocking {
        ServerSocket(0).use { server ->
            val fixture = loadUsbLanPcmAudioFixture()
            val audioOutputFactory = TestPcmAudioOutputFactory()
            val firstWrite = CountDownLatch(1)
            audioOutputFactory.onWrite = { firstWrite.countDown() }
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        val caps = listOf(
                            Capability.CAPABILITY_TOUCH,
                            Capability.CAPABILITY_AUDIO,
                            Capability.CAPABILITY_MANAGED_CONFIGURATION,
                        )
                        completeManagedPolicyHandshake(
                            peer = peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            hostManagedStatus = ProtocolV1Session.ManagedPolicy.UNMANAGED.toStatus(),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES,
                        )
                        write(peer, base(7).setAudioConfig(fixture.audioConfig()).build())
                        val configResult = readEnvelope(peer)
                        assertEquals(
                            configResult.protocolError.message,
                            Envelope.PayloadCase.AUDIO_CONFIG_RESULT,
                            configResult.payloadCase,
                        )
                        assertTrue(configResult.audioConfigResult.rejectionReason, configResult.audioConfigResult.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            fixture.packets.first().serializedFrameBytes,
                        )
                        assertTrue(firstWrite.await(8, TimeUnit.SECONDS))
                        write(peer, managedPolicyStatus(8, managedPolicy(audioAllowed = false).toStatus()))
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.AUDIO,
                            fixture.packets.last().serializedFrameBytes,
                        )
                    }
                }
            var failure: SessionFailure? = null
            val client = StreamClient("127.0.0.1", server.localPort)
            client.audioPlayer = ProtocolPcmAudioPlayer(audioOutputFactory)
            client.onSessionEnded = {
                failure = it
                sessionEnded.countDown()
            }
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_MEDIA_PAYLOAD, checkNotNull(failure).kind)
            assertTrue(checkNotNull(failure).detail.contains("Audio packet received before AudioConfig acceptance"))
            assertEquals(1, audioOutputFactory.created.size)
            assertEquals(listOf("start", "write", "stop", "close"), audioOutputFactory.created.single().events)
            assertEquals(listOf(fixture.packets.first().payloadBytes.toList()), audioOutputFactory.created.single().writes.map { it.toList() })
        }
    }

    @Test
    fun decoderCommitWithholdsAckDropsPrematureMediaThenRequestsKeyframeAndDeliversNewEpoch() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val prematureMediaSent = CountDownLatch(1)
            val frameDelivered = CountDownLatch(1)
            val configurationApplied = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val appliedConfiguration = AtomicReference<StreamVideoConfiguration?>()
            val deliveredEpochs = Collections.synchronizedList(mutableListOf<Long>())
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        peer.soTimeout = 250
                        assertNull(readEnvelopeOrNull(peer))
                        writeVideo(peer, configEpoch = 3, frameId = 1, keyframe = true)
                        prematureMediaSent.countDown()

                        peer.soTimeout = 3_000
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
                        assertTrue(result.videoConfigResult.accepted)
                        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
                        peer.soTimeout = 200
                        assertNull(readEnvelopeOrNull(peer))

                        writeVideo(peer, configEpoch = 3, frameId = 2, keyframe = true)
                        write(peer, disconnect(id = 6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, pendingCommit ->
                commit.set(pendingCommit)
                configurationRequested.countDown()
            }
            client.onVideoConfigurationApplied = {
                appliedConfiguration.set(it)
                configurationApplied.countDown()
            }
            client.onFrameReceived = { buffer, _, _, _, _, configEpoch ->
                deliveredEpochs += configEpoch
                client.releaseBuffer(buffer)
                frameDelivered.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
            assertTrue(prematureMediaSent.await(8, TimeUnit.SECONDS))
            assertFalse(frameDelivered.await(250, TimeUnit.MILLISECONDS))
            assertFalse(configurationApplied.await(250, TimeUnit.MILLISECONDS))
            checkNotNull(commit.get()).accept()
            assertTrue(configurationApplied.await(8, TimeUnit.SECONDS))
            assertFalse(checkNotNull(appliedConfiguration.get()).appliesClientVideoPreferences)

            assertTrue(configurationApplied.await(8, TimeUnit.SECONDS))
            assertTrue(frameDelivered.await(8, TimeUnit.SECONDS))
            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(listOf(3L), deliveredEpochs)
            assertEquals(12_000, checkNotNull(appliedConfiguration.get()).bitrateKbps)
            assertEquals(60, checkNotNull(appliedConfiguration.get()).framesPerSecond)
        }
    }

    @Test
    fun staleProtocolV1FrameAfterNewSessionIsDropped() {
        runBlocking {
            ServerSocket(0).use { oldServer ->
                ServerSocket(0).use { newServer ->
                    val oldReadyForFrame = CountDownLatch(1)
                    val sendOldFrame = CountDownLatch(1)
                    val oldFrameDelivered = CountDownLatch(1)
                    val newStreaming = CountDownLatch(1)
                    val oldServerJob =
                        async(Dispatchers.IO) {
                            oldServer.accept().use { peer ->
                                completeHandshake(peer, initialRotation = 0, videoConfigEpoch = 3)
                                oldReadyForFrame.countDown()
                                assertTrue(sendOldFrame.await(8, TimeUnit.SECONDS))
                                writeVideo(peer, configEpoch = 3, frameId = 1, keyframe = true)
                                peer.soTimeout = 300
                                readEnvelopeOrNull(peer)
                            }
                        }
                    val newServerJob =
                        async(Dispatchers.IO) {
                            newServer.accept().use { peer ->
                                completeHandshake(peer, initialRotation = 0, videoConfigEpoch = 4)
                                newStreaming.countDown()
                                write(peer, disconnect(6))
                            }
                        }
                    val oldClient = StreamClient("127.0.0.1", oldServer.localPort)
                    oldClient.onVideoConfiguration = { _, commit -> commit.accept() }
                    oldClient.onFrameReceived = { buffer, _, _, _, _, _ ->
                        oldClient.releaseBuffer(buffer)
                        oldFrameDelivered.countDown()
                    }
                    val oldClientJob = async(Dispatchers.IO) { runCatching { oldClient.connect() } }

                    assertTrue(oldReadyForFrame.await(8, TimeUnit.SECONDS))
                    val newClient = StreamClient("127.0.0.1", newServer.localPort)
                    newClient.acceptVideoConfigurations()
                    val newClientJob = async(Dispatchers.IO) { runCatching { newClient.connect() } }
                    assertTrue(newStreaming.await(8, TimeUnit.SECONDS))

                    sendOldFrame.countDown()
                    withTimeout(8_000) { oldServerJob.await() }
                    assertFalse(oldFrameDelivered.await(250, TimeUnit.MILLISECONDS))

                    oldClient.disconnect()
                    newClient.disconnect()
                    withTimeout(8_000) { newServerJob.await() }
                    withTimeout(8_000) { oldClientJob.await() }
                    withTimeout(8_000) { newClientJob.await() }
                    Unit
                }
            }
        }
    }

    @Test
    fun disconnectBeforeDecoderCompletionSendsNoAck() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val serverResult =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        configurationRequested.await(8, TimeUnit.SECONDS)
                        Thread.sleep(300)
                        peer.soTimeout = 200
                        readEnvelopeOrNull(peer)
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, pendingCommit ->
                commit.set(pendingCommit)
                configurationRequested.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
            client.disconnect()
            assertFalse(checkNotNull(commit.get()).tryPublish { true })
            checkNotNull(commit.get()).complete(StreamVideoConfigurationDecision.ACCEPTED)

            assertNull(withTimeout(8_000) { serverResult.await() })
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun disconnectDrainsAlreadyQueuedProtocolBatchBeforeClearingSession() = runBlocking {
        ServerSocket(0).use { server ->
            val gatedFlushSocket = AtomicReference<GateableFlushSocket?>()
            val clientConnected = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD),
                        )
                        peer.soTimeout = 500
                        var observedClipboardOffer = false
                        repeat(8) {
                            if (!observedClipboardOffer) {
                                observedClipboardOffer = readEnvelopeOrNull(peer)?.payloadCase == Envelope.PayloadCase.CLIPBOARD_OFFER
                            }
                        }
                        assertTrue(observedClipboardOffer)
                    }
                }
            val writeFailure = AtomicReference<String?>()
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    socketFactory = {
                        GateableFlushSocket().also(gatedFlushSocket::set)
                    },
                )
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { isConnected ->
                if (isConnected) clientConnected.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            client.onWriteFailure = { writeFailure.set(it) }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(clientConnected.await(8, TimeUnit.SECONDS))
            val gate = checkNotNull(gatedFlushSocket.get())
            gate.armNextFlush()
            client.sendPing()
            assertTrue(gate.flushEntered.await(8, TimeUnit.SECONDS))
            assertTrue(client.offerClipboard("queued-before-disconnect"))
            val disconnectJob = async(Dispatchers.IO) { client.disconnect() }
            try {
                gate.releaseFlush.countDown()

                withTimeout(8_000) { disconnectJob.await() }
                withTimeout(8_000) { serverJob.await() }
                withTimeout(8_000) { clientJob.await() }
            } finally {
                gate.releaseFlush.countDown()
            }

            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertNull(writeFailure.get())
            Unit
        }
    }

    @Test
    fun disconnectDrainsAlreadyQueuedFileOfferBeforeCleanupCancelsTransferWithReason() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val source = File.createTempFile("vibescreen-drain-offer", ".txt")
            source.writeText("queued-offer-before-disconnect")
            val gatedFlushSocket = AtomicReference<GateableFlushSocket?>()
            val clientConnected = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val resultCount = AtomicInteger()
            val acceptedResult = AtomicBoolean(true)
            val rejectionReason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            maxFileBytes = 1024,
                            maxFileChunkBytes = 64 * 1024,
                        )
                        val offer = checkNotNull(readEnvelopeUntil(peer) { it.payloadCase == Envelope.PayloadCase.FILE_OFFER })
                        assertEquals(source.name, offer.fileOffer.fileName)
                        assertEquals(source.length(), offer.fileOffer.byteLength)
                    }
                }
            val writeFailure = AtomicReference<String?>()
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    socketFactory = {
                        GateableFlushSocket().also(gatedFlushSocket::set)
                    },
                )
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { isConnected ->
                if (isConnected) clientConnected.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            client.onWriteFailure = { writeFailure.set(it) }
            client.onFileTransferResult = { accepted, reason ->
                resultCount.incrementAndGet()
                acceptedResult.set(accepted)
                rejectionReason.set(reason)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(clientConnected.await(8, TimeUnit.SECONDS))
            val gate = checkNotNull(gatedFlushSocket.get())
            gate.armNextFlush()
            client.sendPing()
            assertTrue(gate.flushEntered.await(8, TimeUnit.SECONDS))
            assertTrue(client.offerFile(source, "text/plain"))
            val disconnectJob = async(Dispatchers.IO) { client.disconnect() }
            try {
                gate.releaseFlush.countDown()

                withTimeout(8_000) { disconnectJob.await() }
                withTimeout(8_000) { serverJob.await() }
                withTimeout(8_000) { clientJob.await() }
            } finally {
                gate.releaseFlush.countDown()
                source.delete()
            }

            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
            assertEquals(1, resultCount.get())
            assertFalse(acceptedResult.get())
            assertEquals("connection_cleanup", rejectionReason.get())
            assertNull(writeFailure.get())
            Unit
        }
    }

    @Test
    fun disconnectDrainsAlreadyQueuedFileOfferDecisionBeforeClearingSession() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "host-offer-before-disconnect".toByteArray(Charsets.UTF_8)
            val transferId = ByteString.copyFrom(byteArrayOf(0x61))
            val capturedOffer = AtomicReference<FileOffer>()
            val offerSeen = CountDownLatch(1)
            val offerCallbackCount = AtomicInteger()
            val serverMayRead = CountDownLatch(1)
            val fileAcceptCount = AtomicInteger()
            val gatedFlushSocket = AtomicReference<GateableFlushSocket?>()
            val clientConnected = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            maxFileBytes = 1024,
                            maxFileChunkBytes = 64 * 1024,
                        )
                        write(peer, fileOffer(6, transferId, "host-offer.txt", content))
                        assertTrue(serverMayRead.await(8, TimeUnit.SECONDS))
                        val accept = checkNotNull(readEnvelopeUntil(peer) { envelope ->
                            if (envelope.payloadCase == Envelope.PayloadCase.FILE_ACCEPT) {
                                fileAcceptCount.incrementAndGet()
                                true
                            } else {
                                false
                            }
                        })
                        assertEquals(transferId, accept.fileAccept.transferId)
                        assertTrue(accept.fileAccept.accepted)
                        peer.soTimeout = 300
                        repeat(3) {
                            readEnvelopeOrNull(peer)?.let { envelope ->
                                if (envelope.payloadCase == Envelope.PayloadCase.FILE_ACCEPT) {
                                    fileAcceptCount.incrementAndGet()
                                }
                            }
                        }
                    }
                }
            val writeFailure = AtomicReference<String?>()
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    socketFactory = {
                        GateableFlushSocket().also(gatedFlushSocket::set)
                    },
                )
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { isConnected ->
                if (isConnected) clientConnected.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            client.onWriteFailure = { writeFailure.set(it) }
            client.onFileOffer = { offer ->
                offerCallbackCount.incrementAndGet()
                capturedOffer.set(offer)
                offerSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(clientConnected.await(8, TimeUnit.SECONDS))
            assertTrue(offerSeen.await(8, TimeUnit.SECONDS))
            val gate = checkNotNull(gatedFlushSocket.get())
            gate.armNextFlush()
            client.sendPing()
            assertTrue(gate.flushEntered.await(8, TimeUnit.SECONDS))
            assertTrue(client.respondToFileOffer(checkNotNull(capturedOffer.get()), accepted = true))
            val disconnectJob = async(Dispatchers.IO) { client.disconnect() }
            try {
                serverMayRead.countDown()
                gate.releaseFlush.countDown()

                withTimeout(8_000) { disconnectJob.await() }
                withTimeout(8_000) { serverJob.await() }
                withTimeout(8_000) { clientJob.await() }
            } finally {
                serverMayRead.countDown()
                gate.releaseFlush.countDown()
            }

            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(1, offerCallbackCount.get())
            assertEquals(1, fileAcceptCount.get())
            assertNull(writeFailure.get())
            Unit
        }
    }

    @Test
    fun disconnectDrainsAlreadyQueuedWakeHostCompletionBeforeClearingSession() = runBlocking {
        ServerSocket(0).use { server ->
            val secret = ByteArray(32) { it.toByte() }
            val requestId = ByteString.copyFrom(byteArrayOf(0x62))
            val targetMac = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
            val sentPackets = Collections.synchronizedList(mutableListOf<ByteArray>())
            val queuedWakeHost = AtomicReference<Runnable?>()
            val wakeHostQueued = CountDownLatch(1)
            val wakeCompletionQueued = CountDownLatch(1)
            val wakeCompletionCount = AtomicInteger()
            val serverMayRead = CountDownLatch(1)
            val wakeResultCount = AtomicInteger()
            val gatedFlushSocket = AtomicReference<GateableFlushSocket?>()
            val clientConnected = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        var clientDeviceId = ""
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES + Capability.CAPABILITY_WAKE_HOST,
                            onClientHello = { clientDeviceId = it.deviceId },
                        )
                        write(
                            peer,
                            signedWakeHostRequest(
                                id = 6,
                                requestId = requestId,
                                targetMac = targetMac,
                                clientDeviceId = clientDeviceId,
                                secret = secret,
                            ),
                        )
                        assertTrue(serverMayRead.await(8, TimeUnit.SECONDS))
                        val result = checkNotNull(readEnvelopeUntil(peer) { envelope ->
                            if (envelope.payloadCase == Envelope.PayloadCase.WAKE_HOST_RESULT) {
                                wakeResultCount.incrementAndGet()
                                true
                            } else {
                                false
                            }
                        })
                        assertEquals(requestId, result.wakeHostResult.requestId)
                        assertTrue(result.wakeHostResult.accepted)
                        assertEquals("", result.wakeHostResult.rejectionReason)
                        peer.soTimeout = 300
                        repeat(3) {
                            readEnvelopeOrNull(peer)?.let { envelope ->
                                if (envelope.payloadCase == Envelope.PayloadCase.WAKE_HOST_RESULT) {
                                    wakeResultCount.incrementAndGet()
                                }
                            }
                        }
                    }
                }
            val writeFailure = AtomicReference<String?>()
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    socketFactory = {
                        GateableFlushSocket().also(gatedFlushSocket::set)
                    },
                    wakeHostPolicy = SharedSecretWakeHostPolicy(secret.copyOf(), nowUnixSeconds = { 1_010L }),
                    wakeHostPacketSender = WakeHostPacketSender { packet -> sentPackets += packet },
                    wakeHostExecutor = Executor { command ->
                        queuedWakeHost.set {
                            command.run()
                            wakeCompletionCount.incrementAndGet()
                            wakeCompletionQueued.countDown()
                        }
                        wakeHostQueued.countDown()
                    },
                )
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { isConnected ->
                if (isConnected) clientConnected.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            client.onWriteFailure = { writeFailure.set(it) }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(clientConnected.await(8, TimeUnit.SECONDS))
            assertTrue(wakeHostQueued.await(8, TimeUnit.SECONDS))
            val gate = checkNotNull(gatedFlushSocket.get())
            gate.armNextFlush()
            client.sendPing()
            assertTrue(gate.flushEntered.await(8, TimeUnit.SECONDS))
            queuedWakeHost.get()?.run()
            assertTrue(wakeCompletionQueued.await(8, TimeUnit.SECONDS))
            val disconnectJob = async(Dispatchers.IO) { client.disconnect() }
            try {
                serverMayRead.countDown()
                gate.releaseFlush.countDown()

                withTimeout(8_000) { disconnectJob.await() }
                withTimeout(8_000) { serverJob.await() }
                withTimeout(8_000) { clientJob.await() }
            } finally {
                serverMayRead.countDown()
                gate.releaseFlush.countDown()
            }

            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(1, wakeCompletionCount.get())
            assertEquals(1, wakeResultCount.get())
            assertEquals(1, sentPackets.size)
            assertArrayEquals(WakeHostMagicPacket.build(targetMac), sentPackets.single())
            assertNull(writeFailure.get())
            Unit
        }
    }

    @Test
    fun savedVideoPreferencesReplayAfterClientVideoControlNegotiation() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val connectedLatch = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(
                                Capability.CAPABILITY_TOUCH,
                                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                            ),
                            negotiatedCapabilities = listOf(
                                Capability.CAPABILITY_TOUCH,
                                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                            ),
                        )
                        configurationRequested.await(8, TimeUnit.SECONDS)
                        val replay = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.SET_VIDEO_PREFERENCES, replay.payloadCase)
                        assertEquals(50_000, replay.setVideoPreferences.bitrateKbps)
                        assertEquals(30, replay.setVideoPreferences.framesPerSecond)
                        assertEquals(
                            dev.vibescreen.protocol.v1.VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                            replay.setVideoPreferences.qualityPreset,
                        )
                        assertTrue(replay.setVideoPreferences.resetQualityToAuto)
                        write(peer, disconnect(id = 6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, commit ->
                commit.accept()
                configurationRequested.countDown()
            }
            client.onConnectionStatus = { connected ->
                if (connected) {
                    connectedLatch.countDown()
                }
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(connectedLatch.await(8, TimeUnit.SECONDS))
            assertTrue(Capability.CAPABILITY_CLIENT_VIDEO_CONTROL in client.negotiatedCapabilities())
            SavedVideoPreferenceReplayer.replayIfAvailable(
                clientVideoControlAvailable = true,
                quality = VideoQualityChoice.AUTO,
                bitrateMbps = 50,
                framesPerSecond = 30,
            ) { replay ->
                client.setVideoPreferences(
                    bitrateKbps = replay.bitrateKbps,
                    framesPerSecond = replay.framesPerSecond,
                    qualityPreset = replay.qualityPreset,
                    resetQualityToAuto = replay.resetQualityToAuto,
                )
            }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
        }
        Unit
    }

    @Test
    fun controllerForwardingWaitsForConnectedAckBeforeStateResync() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val configurationApplied = CountDownLatch(1)
            val controllerAcked = CountDownLatch(1)
            val client = StreamClient("127.0.0.1", server.localPort, advertiseController = true)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities =
                                listOf(
                                    Capability.CAPABILITY_TOUCH,
                                    Capability.CAPABILITY_COLOR_MANAGEMENT,
                                    Capability.CAPABILITY_CONTROLLER,
                                ),
                            negotiatedCapabilities =
                                listOf(
                                    Capability.CAPABILITY_TOUCH,
                                    Capability.CAPABILITY_COLOR_MANAGEMENT,
                                    Capability.CAPABILITY_CONTROLLER,
                                ),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES + Capability.CAPABILITY_CONTROLLER,
                        )
                        assertTrue(configurationApplied.await(8, TimeUnit.SECONDS))
                        val connected = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CONTROLLER_EVENT, connected.payloadCase)
                        assertEquals(
                            dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                            connected.controllerEvent.kind,
                        )
                        peer.soTimeout = 250
                        assertNull(readEnvelopeOrNull(peer))
                        peer.soTimeout = 3_000
                        write(
                            peer,
                            base(6)
                                .setInputAck(
                                    InputAck
                                        .newBuilder()
                                        .setInputId(connected.controllerEvent.inputId)
                                        .setAccepted(true),
                                ).build(),
                        )
                        controllerAcked.await(8, TimeUnit.SECONDS)
                        val state = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CONTROLLER_EVENT, state.payloadCase)
                        assertEquals(
                            dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE,
                            state.controllerEvent.kind,
                        )
                        write(peer, disconnect(id = 7))
                    }
            }
            client.onVideoConfiguration = { _, commit ->
                commit.accept()
                configurationRequested.countDown()
            }
            client.onVideoConfigurationApplied = {
                configurationApplied.countDown()
            }
            client.onControllerInputAck = { _, accepted, _ ->
                if (accepted) {
                    controllerAcked.countDown()
                    client.sendController(
                        ControllerDispatch(
                            samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1)),
                            delivery = ControllerDelivery.STRUCTURAL,
                        ),
                    )
                }
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
            assertTrue(configurationApplied.await(8, TimeUnit.SECONDS))
            val admitted =
                client.sendController(
                    ControllerDispatch(
                        samples =
                            listOf(
                                ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED),
                                ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1),
                            ),
                        delivery = ControllerDelivery.STRUCTURAL,
                    ),
                )
            assertTrue(admitted)
            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun hostDisconnectNoticeInvalidatesLateDecoderCompletionWithoutAck() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val disconnectSent = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val serverResult =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
                        write(peer, disconnect(id = 6))
                        disconnectSent.countDown()
                        peer.soTimeout = 500
                        readEnvelopeOrNull(peer)
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, pendingCommit ->
                commit.set(pendingCommit)
                configurationRequested.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(disconnectSent.await(8, TimeUnit.SECONDS))
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertFalse(checkNotNull(commit.get()).tryPublish { true })
            checkNotNull(commit.get()).complete(StreamVideoConfigurationDecision.ACCEPTED)

            assertNull(withTimeout(8_000) { serverResult.await() })
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun hostProtocolErrorCancelsPendingDecoderCommitBeforeSessionCleanup() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val protocolErrorSent = CountDownLatch(1)
            val sessionEnded = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val serverResult =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
                        write(peer, hostProtocolError(id = 6))
                        protocolErrorSent.countDown()
                        peer.soTimeout = 500
                        readEnvelopeOrNull(peer)
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, pendingCommit ->
                commit.set(pendingCommit)
                configurationRequested.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(protocolErrorSent.await(8, TimeUnit.SECONDS))
            withTimeout(8_000) {
                while (checkNotNull(commit.get()).isPending()) kotlinx.coroutines.delay(5)
            }
            assertFalse(checkNotNull(commit.get()).tryPublish { true })
            checkNotNull(commit.get()).complete(StreamVideoConfigurationDecision.ACCEPTED)

            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertNull(withTimeout(8_000) { serverResult.await() })
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun malformedControlFrameCancelsPendingDecoderCommitBeforeSessionCleanup() = runBlocking {
        ServerSocket(0).use { server ->
            val configurationRequested = CountDownLatch(1)
            val malformedFrameSent = CountDownLatch(1)
            val commit = AtomicReference<StreamVideoConfigurationCommit?>()
            val serverResult =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        assertTrue(configurationRequested.await(8, TimeUnit.SECONDS))
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.CONTROL,
                            byteArrayOf(0x0A),
                        )
                        malformedFrameSent.countDown()
                        peer.soTimeout = 500
                        readEnvelopeOrNull(peer)
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.onVideoConfiguration = { _, pendingCommit ->
                commit.set(pendingCommit)
                configurationRequested.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(malformedFrameSent.await(8, TimeUnit.SECONDS))
            withTimeout(8_000) {
                while (checkNotNull(commit.get()).isPending()) kotlinx.coroutines.delay(5)
            }
            var published = false
            assertFalse(
                checkNotNull(commit.get()).tryPublish {
                    published = true
                    true
                },
            )
            assertFalse(published)
            checkNotNull(commit.get()).complete(StreamVideoConfigurationDecision.ACCEPTED)

            assertNull(withTimeout(8_000) { serverResult.await() })
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun decoderConfigurationFailureRejectsAndFailsClosed() = runBlocking {
        assertRejectedDecoderConfiguration(
            clientFactory = { port -> StreamClient("127.0.0.1", port) },
            configure = { commit ->
                commit.complete(StreamVideoConfigurationDecision.reject("decoder_configuration_failure"))
            },
            expectedReason = "decoder_configuration_failure",
        )
    }

    @Test
    fun decoderConfigurationTimeoutRejectsAndFailsClosed() = runBlocking {
        assertRejectedDecoderConfiguration(
            clientFactory = { port ->
                StreamClient(
                    host = "127.0.0.1",
                    port = port,
                    videoConfigurationCommitTimeoutMs = 100,
                )
            },
            configure = {},
            expectedReason = "decoder_configuration_timeout",
        )
    }

    @Test
    fun failedPublishRejectsAndFailsClosed() = runBlocking {
        assertRejectedDecoderConfiguration(
            clientFactory = { port -> StreamClient("127.0.0.1", port) },
            configure = { commit ->
                assertFalse(commit.tryPublish { false })
            },
            expectedReason = "decoder_configuration_not_published",
        )
    }

    @Test
    fun throwingPublishRejectsAndFailsClosed() = runBlocking {
        assertRejectedDecoderConfiguration(
            clientFactory = { port -> StreamClient("127.0.0.1", port) },
            configure = { commit ->
                // A publish() that throws after the commit is reserved must not
                // strand the state machine: the commit rejects and stops being
                // pending, and the throwable still surfaces to the caller.
                assertThrows(IllegalStateException::class.java) {
                    commit.tryPublish { throw IllegalStateException("publish blew up") }
                }
                assertFalse(commit.isPending())
            },
            expectedReason = "decoder_configuration_publish_failed",
        )
    }

    @Test
    fun slowPublishDoesNotBlockOtherClientTimeout() = runBlocking {
        val timeoutExecutor = GatedFirstScheduledExecutor()
        val terminationExecutor =
            Executors.newCachedThreadPool { runnable ->
                Thread(runnable, "StreamClientTerminationTest").apply { isDaemon = true }
            }
        val releasePublish = CountDownLatch(1)
        val closeFirstPeer = CountDownLatch(1)

        try {
            ServerSocket(0).use { firstServer ->
                ServerSocket(0).use { secondServer ->
                    val firstConfigured = CountDownLatch(1)
                    val firstCommit = AtomicReference<StreamVideoConfigurationCommit?>()
                    val firstServerJob =
                        async(Dispatchers.IO) {
                            firstServer.accept().use { peer ->
                                beginHandshake(peer, initialRotation = 0)
                                assertTrue(closeFirstPeer.await(8, TimeUnit.SECONDS))
                            }
                        }
                    val firstClient =
                        StreamClient(
                            host = "127.0.0.1",
                            port = firstServer.localPort,
                            videoConfigurationCommitTimeoutMs = 1,
                            videoConfigurationTimeoutExecutor = timeoutExecutor,
                            terminationExecutor = terminationExecutor,
                        )
                    firstClient.onVideoConfiguration = { _, commit ->
                        firstCommit.set(commit)
                        firstConfigured.countDown()
                    }
                    val firstClientJob = async(Dispatchers.IO) { runCatching { firstClient.connect() } }

                    assertTrue(firstConfigured.await(8, TimeUnit.SECONDS))
                    assertTrue(timeoutExecutor.firstTaskStarted.await(8, TimeUnit.SECONDS))
                    val publishStarted = CountDownLatch(1)
                    val publishJob =
                        async(Dispatchers.Default) {
                            checkNotNull(firstCommit.get()).tryPublish {
                                publishStarted.countDown()
                                assertTrue(releasePublish.await(8, TimeUnit.SECONDS))
                                true
                            }
                        }
                    assertTrue(publishStarted.await(8, TimeUnit.SECONDS))
                    timeoutExecutor.releaseFirstTask.countDown()

                    val secondConfigured = CountDownLatch(1)
                    val secondServerJob =
                        async(Dispatchers.IO) {
                            secondServer.accept().use { peer ->
                                beginHandshake(peer, initialRotation = 0)
                                val result = readEnvelope(peer)
                                assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
                                assertFalse(result.videoConfigResult.accepted)
                                result.videoConfigResult.rejectionReason
                            }
                        }
                    val secondClient =
                        StreamClient(
                            host = "127.0.0.1",
                            port = secondServer.localPort,
                            videoConfigurationCommitTimeoutMs = 1,
                            videoConfigurationTimeoutExecutor = timeoutExecutor,
                            terminationExecutor = terminationExecutor,
                        )
                    secondClient.onVideoConfiguration = { _, _ -> secondConfigured.countDown() }
                    val secondClientJob = async(Dispatchers.IO) { runCatching { secondClient.connect() } }

                    try {
                        assertTrue(secondConfigured.await(8, TimeUnit.SECONDS))
                        assertEquals(
                            "decoder_configuration_timeout",
                            withTimeout(8_000) { secondServerJob.await() },
                        )
                    } finally {
                        releasePublish.countDown()
                        closeFirstPeer.countDown()
                        firstClient.disconnect()
                        secondClient.disconnect()
                    }

                    assertTrue(withTimeout(8_000) { publishJob.await() })
                    withTimeout(8_000) { firstServerJob.await() }
                    withTimeout(8_000) { firstClientJob.await() }
                    withTimeout(8_000) { secondClientJob.await() }
                }
            }
        } finally {
            releasePublish.countDown()
            closeFirstPeer.countDown()
            timeoutExecutor.releaseFirstTask.countDown()
            timeoutExecutor.shutdownNow()
            terminationExecutor.shutdownNow()
        }
        Unit
    }

    @Test
    fun decoderRejectionFlushesBeforeTermination() = runBlocking {
        val flushCount = AtomicInteger()
        val flushCountBeforeRejection = AtomicInteger(-1)
        val flushedBeforeTermination = AtomicBoolean(false)
        val releasePeer = CountDownLatch(1)
        val terminationExecutor =
            ManualExecutor {
                val baseline = flushCountBeforeRejection.get()
                flushedBeforeTermination.set(baseline >= 0 && flushCount.get() > baseline)
            }
        val timeoutExecutor = Executors.newSingleThreadScheduledExecutor()
        try {
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            beginHandshake(peer, initialRotation = 0)
                            readEnvelope(peer).also { releasePeer.await() }
                        }
                    }
                val client =
                    StreamClient(
                        host = "127.0.0.1",
                        port = server.localPort,
                        socketFactory = { FlushTrackingSocket(flushCount) },
                        videoConfigurationTimeoutExecutor = timeoutExecutor,
                        terminationExecutor = terminationExecutor,
                    )
                client.onVideoConfiguration = { _, commit ->
                    flushCountBeforeRejection.set(flushCount.get())
                    commit.complete(StreamVideoConfigurationDecision.reject("decoder_configuration_failure"))
                }
                val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

                try {
                    assertTrue(terminationExecutor.submitted.await(8, TimeUnit.SECONDS))
                    assertTrue(flushedBeforeTermination.get())
                    releasePeer.countDown()
                    val result = withTimeout(8_000) { serverJob.await() }
                    assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
                    assertFalse(result.videoConfigResult.accepted)
                    assertEquals("decoder_configuration_failure", result.videoConfigResult.rejectionReason)
                } finally {
                    terminationExecutor.runSubmittedIfPresent()
                    releasePeer.countDown()
                }

                withTimeout(8_000) { clientJob.await() }
            }
        } finally {
            releasePeer.countDown()
            terminationExecutor.runSubmittedIfPresent()
            timeoutExecutor.shutdownNow()
        }
        Unit
    }

    @Test
    fun videoReconfigurationAndRuntimeDisplayChangeStaySeparated() = runBlocking {
        ServerSocket(0).use { server ->
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(peer, initialRotation = 90)
                        write(
                            peer,
                            videoConfig(
                                id = 6,
                                rotation = 90,
                                configEpoch = 4,
                                encodedWidth = 1280,
                                encodedHeight = 720,
                            ),
                        )
                        assertTrue(readEnvelope(peer).videoConfigResult.accepted)
                        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
                        write(peer, displayChanged(id = 7, rotation = 270, logicalWidth = 1080, logicalHeight = 1920))
                        write(peer, disconnect(id = 8))
                    }
                }
            val videoConfigurations = Collections.synchronizedList(mutableListOf<StreamVideoConfiguration>())
            val displayGeometries = Collections.synchronizedList(mutableListOf<StreamDisplayGeometry>())
            val ended = CountDownLatch(1)
            var failure: SessionFailure? = null
            val reconnect = CountDownLatch(1)
            val shutdownObserved = CountDownLatch(1)
            val shutdownCallbacks = AtomicInteger()
            val retryCancellations = AtomicInteger()
            val shutdownActions = AtomicInteger()
            val terminationOrder = Collections.synchronizedList(mutableListOf<String>())
            val retryCoordinator =
                SessionAutomaticRetryCoordinator(
                    postAutomaticRetry = {},
                    cancelPendingAutomaticRetry = { retryCancellations.incrementAndGet() },
                    handleServerShutdown = { shutdownActions.incrementAndGet() },
                )
            val client = StreamClient("127.0.0.1", server.localPort)
            client.apply {
                onVideoConfiguration = { configuration, commit ->
                    videoConfigurations += configuration
                    commit.accept()
                }
                onDisplayGeometry = { displayGeometries += it }
                onSessionEnded = {
                    retryCoordinator.onSessionEnded(it)
                    failure = it
                    terminationOrder += "session_ended"
                    ended.countDown()
                }
                onServerShutdown = {
                    retryCoordinator.onServerShutdown()
                    terminationOrder += "server_shutdown"
                    shutdownCallbacks.incrementAndGet()
                    client.disconnect()
                    shutdownObserved.countDown()
                }
                onReconnectSuggested = { reconnect.countDown() }
            }

            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            withTimeout(8_000) { serverJob.await() }
            assertTrue(ended.await(8, TimeUnit.SECONDS))
            withTimeout(8_000) { clientJob.await() }

            assertEquals(listOf(3L, 4L), videoConfigurations.map { it.configEpoch })
            assertEquals(listOf(1920 to 1080, 1280 to 720), videoConfigurations.map { it.encodedWidth to it.encodedHeight })
            assertEquals(listOf(90, 90), videoConfigurations.map { it.rotation })
            assertEquals(listOf(90, 270), displayGeometries.map { it.rotation })
            assertEquals(1080 to 1920, displayGeometries.last().logicalWidth to displayGeometries.last().logicalHeight)
            assertEquals(SessionFailureKind.SERVER_SHUTDOWN, failure?.kind)
            assertFalse(checkNotNull(failure).retryable)
            assertTrue(checkNotNull(failure).intentional)
            client.disconnect()
            assertTrue(shutdownObserved.await(8, TimeUnit.SECONDS))
            assertEquals(listOf("session_ended", "server_shutdown"), terminationOrder)
            assertEquals(1, shutdownCallbacks.get())
            assertEquals(1, retryCancellations.get())
            assertEquals(1, shutdownActions.get())
            assertFalse(reconnect.await(200, TimeUnit.MILLISECONDS))
        }
    }

    @Test
    fun runtimeDisplaySelectionPublishesConfirmedDisplayAfterDecoderCommit() = runBlocking {
        ServerSocket(0).use { server ->
            val displaysSeen = Collections.synchronizedList(mutableListOf<String>())
            val connected = CountDownLatch(1)
            val confirmedDisplay = CountDownLatch(1)
            val initialConfigurationApplied = CountDownLatch(1)
            val switchedConfigurationApplied = CountDownLatch(1)
            val appliedConfigurations = AtomicInteger()
            val ended = CountDownLatch(1)
            val failure = AtomicReference<SessionFailure?>()
            val secondDisplay = display(id = "display-2", logicalWidth = 2560, logicalHeight = 1440)
            val capabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MULTI_DISPLAY)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = capabilities,
                            negotiatedCapabilities = capabilities,
                            displays = listOf(display(), secondDisplay),
                        )
                        peer.soTimeout = 3_000
                        val request = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.START_DISPLAY_REQUEST, request.payloadCase)
                        assertEquals("display-2", request.startDisplayRequest.sourceDisplayId)
                        write(peer, startDisplay(id = 6, display = secondDisplay))
                        write(
                            peer,
                            videoConfig(
                                id = 7,
                                rotation = 0,
                                configEpoch = 4,
                                encodedWidth = 2560,
                                encodedHeight = 1440,
                            ),
                        )
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
                        assertTrue(result.videoConfigResult.accepted)
                        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
                        assertTrue(confirmedDisplay.await(8, TimeUnit.SECONDS))
                        write(peer, disconnect(id = 8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.apply {
                acceptVideoConfigurations()
                onConnectionStatus = { isConnected ->
                    if (isConnected) connected.countDown()
                }
                onVideoConfigurationApplied = {
                    when (appliedConfigurations.incrementAndGet()) {
                        1 -> initialConfigurationApplied.countDown()
                        2 -> switchedConfigurationApplied.countDown()
                    }
                }
                onDisplaysAvailable = { _, selectedId ->
                    displaysSeen += selectedId
                    if (selectedId == "display-2") confirmedDisplay.countDown()
                }
                onSessionEnded = {
                    failure.set(it)
                    ended.countDown()
                }
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(connected.await(8, TimeUnit.SECONDS))
            assertTrue(initialConfigurationApplied.await(8, TimeUnit.SECONDS))
            client.selectDisplay("display-2")
            assertTrue(switchedConfigurationApplied.await(8, TimeUnit.SECONDS))
            assertTrue(confirmedDisplay.await(8, TimeUnit.SECONDS))
            assertEquals(listOf("display-main", "display-2"), displaysSeen)
            assertTrue(ended.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.SERVER_SHUTDOWN, checkNotNull(failure.get()).kind)
            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun twoPointerMoveIsAnAtomicSchedulerBatchOnWire() = runBlocking {
        ServerSocket(0).use { server ->
            val ready = CountDownLatch(1)
            val samples = mutableListOf<Envelope>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(peer, initialRotation = 0)
                        ready.countDown()
                        repeat(2) {
                            samples += readEnvelope(peer)
                        }
                        write(peer, disconnect(id = 6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            assertTrue(ready.await(8, TimeUnit.SECONDS))

            client.sendMotionTouch(
                v1Samples =
                    listOf(
                        TouchSample(7, InputPhase.INPUT_PHASE_CHANGED, 0.2, 0.3),
                        TouchSample(9, InputPhase.INPUT_PHASE_CHANGED, 0.8, 0.7),
                    ),
                legacyAction = 1,
                legacyPointers = emptyList(),
            )

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(listOf(7, 9), samples.map { it.touchEvent.pointerId })
            assertTrue(samples.all { it.touchEvent.phase == InputPhase.INPUT_PHASE_CHANGED })
            assertEquals(samples[0].messageId + 1, samples[1].messageId)
            assertEquals(samples[0].touchEvent.inputId + 1, samples[1].touchEvent.inputId)
        }
    }

    @Test
    fun displayOnlyHostCompletesStreamingAndTouchStaysOffWire() = runBlocking {
        ServerSocket(0).use { server ->
            val streaming = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = emptyList(),
                            negotiatedCapabilities = emptyList(),
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        val unexpected =
                            try {
                                readEnvelope(peer)
                            } catch (_: SocketTimeoutException) {
                                null
                            }
                        write(peer, disconnect(id = 6))
                        unexpected
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            assertTrue(streaming.await(8, TimeUnit.SECONDS))

            client.sendMotionTouch(
                v1Samples = listOf(TouchSample(7, InputPhase.INPUT_PHASE_BEGAN, 0.2, 0.3)),
                legacyAction = 0,
                legacyPointers = emptyList(),
            )

            assertEquals(null, withTimeout(8_000) { serverJob.await() })
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun hostActionCatalogSurfacesActionsAndInvokeReceivesResult() =
        runBlocking {
            ServerSocket(0).use { server ->
                val caps =
                    listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_HOST_ACTIONS)
                val invokeEnvelope = AtomicReference<Envelope?>(null)
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            completeHandshake(
                                peer,
                                initialRotation = 0,
                                hostCapabilities = caps,
                                negotiatedCapabilities = caps,
                            )
                            write(peer, hostActionCatalog(6))
                            val invoke = readEnvelope(peer)
                            invokeEnvelope.set(invoke)
                            write(
                                peer,
                                hostActionResult(
                                    id = 7,
                                    invocationId = invoke.hostActionInvoke.invocationId,
                                    accepted = true,
                                ),
                            )
                            write(peer, disconnect(8))
                        }
                    }
                val ended = CountDownLatch(1)
                val actionsSeen = CountDownLatch(1)
                val resultSeen = CountDownLatch(1)
                val advertised = Collections.synchronizedList(mutableListOf<String>())
                val acceptedResult = AtomicBoolean(false)
                val client = StreamClient("127.0.0.1", server.localPort)
                client.apply {
                    acceptVideoConfigurations()
                    onHostActionsAvailable = {
                        advertised += it.map { option -> option.id }
                        actionsSeen.countDown()
                    }
                    onHostActionResult = { accepted, _ ->
                        acceptedResult.set(accepted)
                        resultSeen.countDown()
                    }
                    onSessionEnded = { ended.countDown() }
                }
                val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
                try {
                    assertTrue(actionsSeen.await(8, TimeUnit.SECONDS))
                    assertEquals(listOf("move-window", "return-windows"), advertised)
                    client.invokeHostAction("move-window")
                    assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                    assertTrue(acceptedResult.get())
                    assertTrue(ended.await(8, TimeUnit.SECONDS))
                    assertEquals(Unit, withTimeout(8_000) { serverJob.await() })
                    assertEquals(
                        "move-window",
                        checkNotNull(invokeEnvelope.get()).hostActionInvoke.actionId,
                    )
                } finally {
                    client.disconnect()
                }
                withTimeout(8_000) { clientJob.await() }
                Unit
            }
        }

    @Test
    fun signedWakeHostRequestSendsMagicPacketAndRejectsReplay() = runBlocking {
        ServerSocket(0).use { server ->
            val secret = ByteArray(32) { it.toByte() }
            val requestId = ByteString.copyFrom(byteArrayOf(0x51))
            val targetMac = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
            val sentPackets = Collections.synchronizedList(mutableListOf<ByteArray>())
            val sender = WakeHostPacketSender { packet -> sentPackets += packet }
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        var clientDeviceId = ""
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES + Capability.CAPABILITY_WAKE_HOST,
                            onClientHello = { clientDeviceId = it.deviceId },
                        )
                        val wakeRequest = signedWakeHostRequest(
                            id = 6,
                            requestId = requestId,
                            targetMac = targetMac,
                            clientDeviceId = clientDeviceId,
                            secret = secret,
                        )
                        write(peer, wakeRequest)
                        val accepted = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, accepted.payloadCase)
                        assertEquals(requestId, accepted.wakeHostResult.requestId)
                        assertTrue(accepted.wakeHostResult.accepted)
                        assertEquals("", accepted.wakeHostResult.rejectionReason)

                        write(peer, wakeRequest.toBuilder().setMessageId(7).build())
                        val replay = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, replay.payloadCase)
                        assertEquals(requestId, replay.wakeHostResult.requestId)
                        assertFalse(replay.wakeHostResult.accepted)
                        assertEquals("wake_host_replay", replay.wakeHostResult.rejectionReason)
                        write(peer, disconnect(8))
                    }
                }
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    wakeHostPolicy = SharedSecretWakeHostPolicy(secret.copyOf(), nowUnixSeconds = { 1_010L }),
                    wakeHostPacketSender = sender,
                    wakeHostExecutor = Executor { it.run() },
                )
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(1, sentPackets.size)
            assertArrayEquals(WakeHostMagicPacket.build(targetMac), sentPackets.single())
        }
    }

    @Test
    fun queuedWakeHostRequestAfterDisconnectDoesNotSendPacketOrResult() = runBlocking {
        ServerSocket(0).use { server ->
            val secret = ByteArray(32) { it.toByte() }
            val requestId = ByteString.copyFrom(byteArrayOf(0x53))
            val targetMac = ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6))
            val sentPackets = Collections.synchronizedList(mutableListOf<ByteArray>())
            val queuedWakeHost = AtomicReference<Runnable?>()
            val wakeHostQueued = CountDownLatch(1)
            val serverMayFinish = CountDownLatch(1)
            val wakeResultCount = AtomicInteger()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        var clientDeviceId = ""
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES + Capability.CAPABILITY_WAKE_HOST,
                            onClientHello = { clientDeviceId = it.deviceId },
                        )
                        write(
                            peer,
                            signedWakeHostRequest(
                                id = 6,
                                requestId = requestId,
                                targetMac = targetMac,
                                clientDeviceId = clientDeviceId,
                                secret = secret,
                            ),
                        )
                        assertTrue(wakeHostQueued.await(8, TimeUnit.SECONDS))
                        serverMayFinish.await(8, TimeUnit.SECONDS)
                        peer.soTimeout = 300
                        repeat(3) {
                            readEnvelopeOrNull(peer)?.let { envelope ->
                                if (envelope.payloadCase == Envelope.PayloadCase.WAKE_HOST_RESULT) {
                                    wakeResultCount.incrementAndGet()
                                }
                            }
                        }
                    }
                }
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    wakeHostPolicy = SharedSecretWakeHostPolicy(secret.copyOf(), nowUnixSeconds = { 1_010L }),
                    wakeHostPacketSender = WakeHostPacketSender { packet -> sentPackets += packet },
                    wakeHostExecutor = Executor { command ->
                        queuedWakeHost.set(command)
                        wakeHostQueued.countDown()
                    },
                )
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(wakeHostQueued.await(8, TimeUnit.SECONDS))
            client.disconnect()
            queuedWakeHost.get()?.run()
            serverMayFinish.countDown()

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(0, wakeResultCount.get())
            assertTrue(sentPackets.isEmpty())
        }
    }

    @Test
    fun unsignedWakeHostRequestFailsClosedWithoutSendingPacket() = runBlocking {
        ServerSocket(0).use { server ->
            val sentPackets = Collections.synchronizedList(mutableListOf<ByteArray>())
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        var clientDeviceId = ""
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_WAKE_HOST),
                            expectedClientCapabilities = DEFAULT_CLIENT_CAPABILITIES + Capability.CAPABILITY_WAKE_HOST,
                            onClientHello = { clientDeviceId = it.deviceId },
                        )
                        write(
                            peer,
                            base(6)
                                .setWakeHostRequest(
                                    WakeHostRequest.newBuilder()
                                        .setRequestId(ByteString.copyFrom(byteArrayOf(0x52)))
                                        .setTargetMacAddress(ByteString.copyFrom(byteArrayOf(1, 2, 3, 4, 5, 6)))
                                        .setHostId(TEST_HOST_ID)
                                        .setDeviceId(clientDeviceId),
                                ).build(),
                        )
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.WAKE_HOST_RESULT, result.payloadCase)
                        assertFalse(result.wakeHostResult.accepted)
                        assertEquals("wake_host_unauthorized", result.wakeHostResult.rejectionReason)
                        write(peer, disconnect(7))
                    }
                }
            val client =
                StreamClient(
                    host = "127.0.0.1",
                    port = server.localPort,
                    wakeHostPolicy = SharedSecretWakeHostPolicy(ByteArray(32) { it.toByte() }, nowUnixSeconds = { 1_010L }),
                    wakeHostPacketSender = WakeHostPacketSender { packet -> sentPackets += packet },
                    wakeHostExecutor = Executor { it.run() },
                )
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sentPackets.isEmpty())
        }
    }


    @Test
    fun clipboardOfferFromClientIsRequestedAndContentServed() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
            val clientDeviceId = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            onClientHello = { clientDeviceId.set(it.deviceId) },
                        )
                        val offerEnv = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIPBOARD_OFFER, offerEnv.payloadCase)
                        val offer = offerEnv.clipboardOffer
                        assertEquals(clientDeviceId.get(), offer.originDeviceId)
                        assertEquals("text/plain", offer.mimeType)
                        assertEquals("hello world".length.toLong(), offer.byteLength)
                        assertEquals(32, offer.sha256.size())

                        write(peer, clipboardRequest(6, offer.changeId))

                        val contentEnv = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIPBOARD_CONTENT, contentEnv.payloadCase)
                        val content = contentEnv.clipboardContent
                        assertEquals(offer.changeId, content.changeId)
                        assertEquals("hello world", content.content.toStringUtf8())
                        assertEquals(offer.sha256, content.sha256)
                        write(peer, disconnect(7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                withTimeout(8_000) {
                    while (!client.canSendClipboard) kotlinx.coroutines.delay(5)
                }
                assertTrue(client.offerClipboard("hello world"))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clipboardOfferFromHostRequiresExplicitClientRequestBeforeContent() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
            val offerSeen = CountDownLatch(1)
            val noAutomaticRequestVerified = CountDownLatch(1)
            val contentSeen = CountDownLatch(1)
            val offeredChangeId = AtomicReference<ByteArray?>()
            val receivedContent = AtomicReference<ClipboardContentData?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        val text = "from-host"
                        val textBytes = text.toByteArray(Charsets.UTF_8)
                        val changeId = ByteString.copyFrom(ByteArray(16) { (it + 1).toByte() })
                        val sha256 = ByteString.copyFrom(sha256(textBytes))
                        write(
                            peer,
                            clipboardOffer(
                                id = 6,
                                changeId = changeId,
                                originDeviceId = TEST_HOST_ID,
                                byteLength = textBytes.size.toLong(),
                                sha256 = sha256,
                            ),
                        )

                        // The client must not auto-request the content.
                        peer.soTimeout = 500
                        val unexpected =
                            try {
                                readEnvelope(peer)
                            } catch (_: SocketTimeoutException) {
                                null
                            }
                        assertNull(unexpected)
                        noAutomaticRequestVerified.countDown()

                        peer.soTimeout = 8_000
                        val requestEnv = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIPBOARD_REQUEST, requestEnv.payloadCase)
                        assertEquals(changeId, requestEnv.clipboardRequest.changeId)

                        write(
                            peer,
                            clipboardContent(
                                id = 7,
                                changeId = changeId,
                                originDeviceId = TEST_HOST_ID,
                                content = textBytes,
                                sha256 = sha256,
                            ),
                        )
                        write(peer, disconnect(8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onClipboardOffered = { offer ->
                offeredChangeId.set(offer.changeId)
                offerSeen.countDown()
            }
            client.onClipboardContentReceived = { content ->
                receivedContent.set(content)
                contentSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(offerSeen.await(8, TimeUnit.SECONDS))
                assertTrue(noAutomaticRequestVerified.await(8, TimeUnit.SECONDS))
                assertTrue(client.requestClipboard(checkNotNull(offeredChangeId.get())))
                assertTrue(contentSeen.await(8, TimeUnit.SECONDS))
                val content = checkNotNull(receivedContent.get())
                assertFalse(content.pending)
                assertEquals("from-host", String(content.content, Charsets.UTF_8))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clipboardRequestReturnsFalseForUnknownOfferWithoutWireMessage() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
            val streaming = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(streaming.await(8, TimeUnit.SECONDS))
                assertTrue(client.canSendClipboard)
                assertFalse(client.requestClipboard(ByteArray(16) { 0x7F.toByte() }))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clipboardOfferReturnsFalseWhenTextExceedsNegotiatedLimitWithoutWireMessage() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
            val streaming = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            maxClipboardBytes = 4L,
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(streaming.await(8, TimeUnit.SECONDS))
                assertTrue(client.canSendClipboard)
                assertEquals(4L, client.negotiatedMaxClipboardBytes)
                assertFalse(client.offerClipboard("12345"))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clipboardTimeoutDoesNotCancelApprovalAfterContentWasConsumed() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_CLIPBOARD)
            val offerSeen = CountDownLatch(1)
            val contentCallbackEntered = CountDownLatch(1)
            val releaseContentCallback = CountDownLatch(1)
            val expiryCompleted = CountDownLatch(1)
            val allowDisconnect = CountDownLatch(1)
            val offeredChangeId = AtomicReference<ByteArray?>()
            val receivedContent = AtomicReference<ClipboardContentData?>()
            val expired = AtomicReference<Boolean?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        val textBytes = "already-consumed".toByteArray(Charsets.UTF_8)
                        val changeId = ByteString.copyFrom(ByteArray(16) { (it + 9).toByte() })
                        val digest = ByteString.copyFrom(sha256(textBytes))
                        write(
                            peer,
                            clipboardOffer(
                                id = 6,
                                changeId = changeId,
                                originDeviceId = TEST_HOST_ID,
                                byteLength = textBytes.size.toLong(),
                                sha256 = digest,
                            ),
                        )
                        peer.soTimeout = 8_000
                        val request = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIPBOARD_REQUEST, request.payloadCase)
                        assertEquals(changeId, request.clipboardRequest.changeId)
                        write(
                            peer,
                            clipboardContent(
                                id = 7,
                                changeId = changeId,
                                originDeviceId = TEST_HOST_ID,
                                content = textBytes,
                                sha256 = digest,
                            ),
                        )
                        assertTrue(allowDisconnect.await(8, TimeUnit.SECONDS))
                        write(peer, disconnect(8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onClipboardOffered = { offer ->
                offeredChangeId.set(offer.changeId)
                offerSeen.countDown()
            }
            client.onClipboardContentReceived = { content ->
                receivedContent.set(content)
                contentCallbackEntered.countDown()
                assertTrue(releaseContentCallback.await(8, TimeUnit.SECONDS))
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(offerSeen.await(8, TimeUnit.SECONDS))
                val changeId = checkNotNull(offeredChangeId.get())
                assertTrue(client.requestClipboard(changeId))
                assertTrue(contentCallbackEntered.await(8, TimeUnit.SECONDS))

                assertTrue(
                    client.expireClipboardRequest(changeId) { didExpire ->
                        expired.set(didExpire)
                        expiryCompleted.countDown()
                    },
                )
                releaseContentCallback.countDown()
                assertTrue(expiryCompleted.await(8, TimeUnit.SECONDS))
                assertFalse(checkNotNull(expired.get()))
                val content = checkNotNull(receivedContent.get())
                assertFalse(content.pending)
                assertEquals("already-consumed", String(content.content, Charsets.UTF_8))
                allowDisconnect.countDown()
                withTimeout(8_000) { serverJob.await() }
            } finally {
                releaseContentCallback.countDown()
                allowDisconnect.countDown()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clipboardApisReturnFalseWhenCapabilityNotNegotiated() = runBlocking {
        ServerSocket(0).use { server ->
            val streaming = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = emptyList(),
                            negotiatedCapabilities = emptyList(),
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        readEnvelopeOrNull(peer)
                        write(peer, disconnect(6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(streaming.await(8, TimeUnit.SECONDS))
                assertFalse(client.canSendClipboard)
                assertFalse(client.offerClipboard("hello"))
                assertFalse(client.requestClipboard(ByteArray(16)))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun hostFileOfferAcceptsBulkChunksAndCompletesStagedFile() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 3).toByte() })
            val content = "from-host-file".toByteArray(Charsets.UTF_8)
            val completed = AtomicReference<dev.telemachus.display.protocol.CompletedIncomingFile?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "hello.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertTrue(accept.fileAccept.accepted)
                        assertEquals(transferId, accept.fileAccept.transferId)

                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.BULK,
                            fileChunk(transferId = transferId, offset = 0, payload = content, final = true),
                        )
                        val progress = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_PROGRESS, progress.payloadCase)
                        assertEquals(content.size.toLong(), progress.fileTransferProgress.receivedBytes)
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_COMPLETE, result.payloadCase)
                        assertTrue(result.fileTransferComplete.accepted)
                        assertEquals(ByteString.copyFrom(sha256(content)), result.fileTransferComplete.sha256)
                        write(peer, disconnect(7))
                    }
            }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer -> client.respondToFileOffer(offer, accepted = true) }
            client.onIncomingFileCompleted = { completed.set(it) }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            val received = checkNotNull(completed.get())
            assertEquals("hello.txt", received.fileName)
            assertEquals(content.toList(), received.stagingFile.readBytes().toList())
            assertEquals(ByteString.copyFrom(sha256(content)), received.sha256)
            received.stagingFile.delete()
            Unit
        }
    }

    @Test
    fun hostFileOfferDefaultsToReceiverDeniedWithoutApprovalCallback() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 43).toByte() })
            val content = "receiver-default-denied".toByteArray(Charsets.UTF_8)
            val completed = AtomicReference<dev.telemachus.display.protocol.CompletedIncomingFile?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "default-denied.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertEquals(transferId, accept.fileAccept.transferId)
                        assertFalse(accept.fileAccept.accepted)
                        assertEquals("user_denied", accept.fileAccept.rejectionReason)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onIncomingFileCompleted = { completed.set(it) }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertNull(completed.get())
            Unit
        }
    }

    @Test
    fun hostFileOfferRejectsUnsafeBasenameBeforeReceiverApprovalCallback() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 53).toByte() })
            val content = "unsafe-name".toByteArray(Charsets.UTF_8)
            val approvalCallbacks = AtomicInteger()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "../escape.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertEquals(transferId, accept.fileAccept.transferId)
                        assertFalse(accept.fileAccept.accepted)
                        assertEquals("invalid_file_name", accept.fileAccept.rejectionReason)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { approvalCallbacks.incrementAndGet() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(0, approvalCallbacks.get())
            Unit
        }
    }

    @Test
    fun hostFileOfferLargerThanNegotiatedLimitRejectsBeforeReceiverApprovalCallback() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 57).toByte() })
            val content = "larger-than-peer-limit".toByteArray(Charsets.UTF_8)
            val approvalCallbacks = AtomicInteger()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            maxFileBytes = 4,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "too-large.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertEquals(transferId, accept.fileAccept.transferId)
                        assertFalse(accept.fileAccept.accepted)
                        assertEquals("file_too_large", accept.fileAccept.rejectionReason)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { approvalCallbacks.incrementAndGet() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(0, approvalCallbacks.get())
            Unit
        }
    }

    @Test
    fun hostManagedPolicyDenialRejectsIncomingFileOfferAndEndsSession() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 58).toByte() })
            val content = "managed-denied-file".toByteArray(Charsets.UTF_8)
            val approvalCallbacks = AtomicInteger()
            val sessionEnded = CountDownLatch(1)
            val sessionFailure = AtomicReference<SessionFailure?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeManagedPolicyHandshake(
                            peer = peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            hostManagedStatus = managedPolicyStatus(fileTransferAllowed = false),
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 7,
                                transferId = transferId,
                                fileName = "managed-denied.txt",
                                content = content,
                            ),
                        )
                        val error = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.PROTOCOL_ERROR, error.payloadCase)
                        assertEquals(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE, error.protocolError.code)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { approvalCallbacks.incrementAndGet() }
            client.onSessionEnded = { failure ->
                sessionFailure.set(failure)
                sessionEnded.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_PEER_MESSAGE, checkNotNull(sessionFailure.get()).kind)
            assertEquals(0, approvalCallbacks.get())
            assertFalse(client.canTransferFiles)
            Unit
        }
    }

    @Test
    fun localManagedConfigurationParseErrorIsInjectedIntoProtocolHandshake() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
            val providerCalls = AtomicInteger()
            val malformedRestrictions = mapOf(ManagedConfigurationKeys.MAXIMUM_FILE_BYTES to -1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                        peer.getOutputStream().flush()
                        val clientHello = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, clientHello.payloadCase)
                        assertEquals(
                            clientCapabilitiesWithout(
                                setOf(
                                    Capability.CAPABILITY_HOST_ACTIONS,
                                    Capability.CAPABILITY_CLIPBOARD,
                                    Capability.CAPABILITY_AUDIO,
                                    Capability.CAPABILITY_FILE_TRANSFER,
                                ),
                            ).toSet(),
                            clientHello.clientHello.capabilitiesList.toSet(),
                        )
                        assertEquals(0L, clientHello.clientHello.resourceLimits.maximumFileBytes)

                        write(peer, hostHello(1, caps))
                        write(peer, sessionAccepted(2, caps))
                        val clientPolicy = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, clientPolicy.payloadCase)
                        assertTrue(clientPolicy.managedPolicyStatus.managed)
                        assertFalse(clientPolicy.managedPolicyStatus.fileTransferAllowed)
                        assertEquals(0L, clientPolicy.managedPolicyStatus.maximumFileBytes)
                        assertTrue(clientPolicy.managedPolicyStatus.allowedHostsRestricted)
                        assertTrue(clientPolicy.managedPolicyStatus.restrictionResultsList.all { it.source == "local_parse_error" })
                        assertEquals(1, providerCalls.get())
                        write(peer, disconnect(3))
                    }
                }
            val client =
                StreamClient("127.0.0.1", server.localPort, managedPolicyProvider = {
                    providerCalls.incrementAndGet()
                    ManagedConfigurationProvider { malformedRestrictions }.loadPolicy()
                })
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(1, providerCalls.get())
            Unit
        }
    }

    @Test
    fun localManagedPolicyProviderIsCapturedOnceForProtocolSession() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
            val providerCalls = AtomicInteger()
            val localPolicy = managedPolicy(fileTransferAllowed = false, maximumFileBytes = 0)
            val laterPolicy = managedPolicy(fileTransferAllowed = true, maximumFileBytes = 8_192)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
                        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
                        peer.getOutputStream().flush()
                        val clientHello = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, clientHello.payloadCase)
                        assertEquals(
                            clientCapabilitiesWithout(setOf(Capability.CAPABILITY_FILE_TRANSFER)).toSet(),
                            clientHello.clientHello.capabilitiesList.toSet(),
                        )
                        assertEquals(0L, clientHello.clientHello.resourceLimits.maximumFileBytes)

                        write(peer, hostHello(1, caps, maxFileBytes = 8_192, maxFileChunkBytes = 1_024))
                        write(peer, sessionAccepted(2, listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION)))
                        val clientPolicy = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, clientPolicy.payloadCase)
                        assertEquals(localPolicy.toStatus(), clientPolicy.managedPolicyStatus)
                        assertEquals(1, providerCalls.get())

                        write(peer, managedPolicyStatus(3, laterPolicy.toStatus()))
                        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, readEnvelope(peer).payloadCase)
                        assertEquals(1, providerCalls.get())
                        write(peer, disconnect(4))
                    }
                }
            val client =
                StreamClient("127.0.0.1", server.localPort, managedPolicyProvider = {
                    providerCalls.incrementAndGet()
                    if (providerCalls.get() == 1) localPolicy else laterPolicy
                })
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertEquals(1, providerCalls.get())
            assertFalse(client.canTransferFiles)
            Unit
        }
    }

    @Test
    fun localManagedPolicyProviderIsReadForEachNewProtocolSession() = runBlocking {
        val policies = listOf(
            managedPolicy(fileTransferAllowed = false, maximumFileBytes = 0),
            managedPolicy(fileTransferAllowed = true, maximumFileBytes = 8_192),
        )
        val observedClientPolicies = Collections.synchronizedList(mutableListOf<ManagedPolicyStatus>())
        val providerCalls = AtomicInteger()

        repeat(2) { index ->
            ServerSocket(0).use { server ->
                val serverJob =
                    async(Dispatchers.IO) {
                        server.accept().use { peer ->
                            completeManagedPolicyHandshake(
                                peer = peer,
                                initialRotation = 0,
                                hostCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION),
                                negotiatedCapabilities = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_MANAGED_CONFIGURATION),
                                hostManagedStatus = managedPolicy(fileTransferAllowed = true, maximumFileBytes = 8_192).toStatus(),
                                expectedClientCapabilities =
                                    if (index == 0) {
                                        clientCapabilitiesWithout(setOf(Capability.CAPABILITY_FILE_TRANSFER))
                                    } else {
                                        DEFAULT_CLIENT_CAPABILITIES
                                    },
                                onClientPolicy = { observedClientPolicies += it },
                            )
                            write(peer, disconnect(7))
                        }
                }
                val client =
                    StreamClient("127.0.0.1", server.localPort, managedPolicyProvider = {
                        policies[providerCalls.getAndIncrement()]
                    })
                client.acceptVideoConfigurations()
                val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

                withTimeout(8_000) { serverJob.await() }
                withTimeout(8_000) { clientJob.await() }
            }
        }

        assertEquals(2, providerCalls.get())
        assertEquals(policies.map { it.toStatus() }, observedClientPolicies.toList())
    }

    @Test
    fun hostFileOfferRejectsStaleSessionEpochChunkAndCleansTransfer() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 63).toByte() })
            val content = "stale-epoch-file".toByteArray(Charsets.UTF_8)
            val completed = AtomicReference<dev.telemachus.display.protocol.CompletedIncomingFile?>()
            val sessionEnded = CountDownLatch(1)
            val sessionFailure = AtomicReference<SessionFailure?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "stale-epoch.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertTrue(accept.fileAccept.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.BULK,
                            fileChunk(
                                transferId = transferId,
                                offset = 0,
                                payload = content,
                                final = true,
                                sessionEpoch = 6,
                            ),
                        )
                        val cancel = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, cancel.payloadCase)
                        assertEquals(transferId, cancel.fileTransferCancel.transferId)
                        assertEquals("stale_session_epoch", cancel.fileTransferCancel.reasonCode)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer -> client.respondToFileOffer(offer, accepted = true) }
            client.onIncomingFileCompleted = { completed.set(it) }
            client.onSessionEnded = { failure ->
                sessionFailure.set(failure)
                sessionEnded.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.TRANSPORT_CLOSED, checkNotNull(sessionFailure.get()).kind)
            assertNull(completed.get())
            Unit
        }
    }

    @Test
    fun hostFileOfferRejectsChunkWithUnexpectedOffset() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 64).toByte() })
            val content = "unexpected-offset-file".toByteArray(Charsets.UTF_8)
            val completed = AtomicReference<dev.telemachus.display.protocol.CompletedIncomingFile?>()
            val sessionEnded = CountDownLatch(1)
            val sessionFailure = AtomicReference<SessionFailure?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "unexpected-offset.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertTrue(accept.fileAccept.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.BULK,
                            fileChunk(
                                transferId = transferId,
                                offset = 1,
                                payload = content,
                                final = true,
                            ),
                        )
                        val cancel = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, cancel.payloadCase)
                        assertEquals(transferId, cancel.fileTransferCancel.transferId)
                        assertEquals("unexpected_offset", cancel.fileTransferCancel.reasonCode)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer -> client.respondToFileOffer(offer, accepted = true) }
            client.onIncomingFileCompleted = { completed.set(it) }
            client.onSessionEnded = { failure ->
                sessionFailure.set(failure)
                sessionEnded.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.TRANSPORT_CLOSED, checkNotNull(sessionFailure.get()).kind)
            assertNull(completed.get())
            Unit
        }
    }

    @Test
    fun hostFileOfferRejectsChunkWithMismatchedDigest() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 65).toByte() })
            val content = "digest-mismatch-file".toByteArray(Charsets.UTF_8)
            val completed = AtomicReference<dev.telemachus.display.protocol.CompletedIncomingFile?>()
            val sessionEnded = CountDownLatch(1)
            val sessionFailure = AtomicReference<SessionFailure?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "digest-mismatch.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertTrue(accept.fileAccept.accepted)
                        ProtocolV1Framing.write(
                            peer.getOutputStream(),
                            ProtocolChannel.BULK,
                            corruptedFileChunk(
                                transferId = transferId,
                                offset = 0,
                                payload = content,
                                final = true,
                            ),
                        )
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer -> client.respondToFileOffer(offer, accepted = true) }
            client.onIncomingFileCompleted = { completed.set(it) }
            client.onSessionEnded = { failure ->
                sessionFailure.set(failure)
                sessionEnded.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            assertEquals(SessionFailureKind.INVALID_MEDIA_PAYLOAD, checkNotNull(sessionFailure.get()).kind)
            assertNull(completed.get())
            Unit
        }
    }

    @Test
    fun hostFileCancelCancelsIncomingTransferAndNotifiesResult() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 66).toByte() })
            val content = "host-cancel-file".toByteArray(Charsets.UTF_8)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(true)
            val resultReason = AtomicReference<String>()
            val sessionEnded = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "host-cancel.txt",
                                content = content,
                            ),
                        )
                        val accept = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_ACCEPT, accept.payloadCase)
                        assertTrue(accept.fileAccept.accepted)
                        write(peer, fileCancel(7, transferId, "peer_cancelled"))
                        assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                        assertFalse(sessionEnded.await(250, TimeUnit.MILLISECONDS))
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer -> client.respondToFileOffer(offer, accepted = true) }
            client.onFileTransferResult = { accepted, reason ->
                acceptedResult.set(accepted)
                resultReason.set(reason)
                resultSeen.countDown()
            }
            client.onSessionEnded = { sessionEnded.countDown() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            assertFalse(acceptedResult.get())
            assertEquals("peer_cancelled", resultReason.get())
            assertTrue(sessionEnded.await(8, TimeUnit.SECONDS))
            Unit
        }
    }

    @Test
    fun hostFileOfferDoesNotBlockOutboundCommandsWhileAwaitingUserDecision() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 23).toByte() })
            val content = "pending-host-file".toByteArray(Charsets.UTF_8)
            val offered = CountDownLatch(1)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "pending.txt",
                                content = content,
                            ),
                        )
                        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(7))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offered.countDown() }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(offered.await(8, TimeUnit.SECONDS))
                client.requestKeyframe(force = true, reason = "file_offer_pending_test")
                withTimeout(8_000) { serverJob.await() }
            } finally {
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun staleHostFileOfferDecisionAfterDisconnectSendsNoAccept() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val transferId = ByteString.copyFrom(ByteArray(16) { (it + 33).toByte() })
            val content = "stale-host-file".toByteArray(Charsets.UTF_8)
            val offered = CountDownLatch(1)
            val serverMayFinish = CountDownLatch(1)
            val capturedOffer = AtomicReference<FileOffer?>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        write(
                            peer,
                            fileOffer(
                                id = 6,
                                transferId = transferId,
                                fileName = "stale.txt",
                                content = content,
                            ),
                        )
                        assertTrue(offered.await(8, TimeUnit.SECONDS))
                        serverMayFinish.await(8, TimeUnit.SECONDS)
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onFileOffer = { offer ->
                capturedOffer.set(offer)
                offered.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            assertTrue(offered.await(8, TimeUnit.SECONDS))
            client.disconnect()
            assertFalse(client.respondToFileOffer(checkNotNull(capturedOffer.get()), accepted = true))
            serverMayFinish.countDown()

            withTimeout(8_000) { serverJob.await() }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferSendsBulkChunksAndReportsCompletion() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "from-client-file".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-client-offer", ".txt")
            source.writeBytes(content)
            val connected = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(false)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_OFFER, offerEnvelope.payloadCase)
                        val offer = offerEnvelope.fileOffer
                        assertEquals(source.name, offer.fileName)
                        assertEquals(content.size.toLong(), offer.byteLength)
                        assertEquals(ByteString.copyFrom(sha256(content)), offer.sha256)
                        write(peer, fileAccept(6, offer.transferId, accepted = true))
                        val chunkFrame = ProtocolV1Framing.read(peer.getInputStream())
                        assertEquals(ProtocolChannel.BULK, chunkFrame.channel)
                        val decoded = ProtocolV1Framing.decodeFileChunk(chunkFrame.payload)
                        assertEquals(offer.transferId, decoded.header.transferId)
                        assertEquals(0L, decoded.header.offset)
                        assertTrue(decoded.header.final)
                        assertEquals(content.toList(), decoded.payload.toList())
                        assertEquals(ByteString.copyFrom(sha256(content)), decoded.header.chunkSha256)
                        write(peer, fileProgress(7, offer.transferId, content.size.toLong()))
                        write(
                            peer,
                            fileComplete(
                                id = 8,
                                transferId = offer.transferId,
                                accepted = true,
                                sha256 = offer.sha256,
                            ),
                        )
                        write(peer, disconnect(9))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, _ ->
                acceptedResult.set(accepted)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertTrue(acceptedResult.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferSendsNextChunkOnlyAfterPeerProgress() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "progress-gated-file".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-progress-gated", ".txt")
            source.writeBytes(content)
            val connected = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(false)
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_OFFER, offerEnvelope.payloadCase)
                        val offer = offerEnvelope.fileOffer
                        write(peer, fileAccept(6, offer.transferId, accepted = true, maximumChunkBytes = 8))

                        val firstFrame = ProtocolV1Framing.read(peer.getInputStream())
                        assertEquals(ProtocolChannel.BULK, firstFrame.channel)
                        val firstChunk = ProtocolV1Framing.decodeFileChunk(firstFrame.payload)
                        assertEquals(offer.transferId, firstChunk.header.transferId)
                        assertEquals(0L, firstChunk.header.offset)
                        assertEquals(8, firstChunk.payload.size)
                        assertFalse(firstChunk.header.final)
                        peer.soTimeout = 300
                        assertNull(readProtocolFrameOrNull(peer))

                        peer.soTimeout = 3_000
                        write(peer, fileProgress(7, offer.transferId, firstChunk.header.payloadLength.toLong()))
                        val secondFrame = ProtocolV1Framing.read(peer.getInputStream())
                        assertEquals(ProtocolChannel.BULK, secondFrame.channel)
                        val secondChunk = ProtocolV1Framing.decodeFileChunk(secondFrame.payload)
                        assertEquals(8L, secondChunk.header.offset)
                        assertFalse(secondChunk.header.final)
                        write(peer, fileProgress(8, offer.transferId, secondChunk.header.offset + secondChunk.header.payloadLength))

                        val thirdFrame = ProtocolV1Framing.read(peer.getInputStream())
                        assertEquals(ProtocolChannel.BULK, thirdFrame.channel)
                        val thirdChunk = ProtocolV1Framing.decodeFileChunk(thirdFrame.payload)
                        assertEquals(16L, thirdChunk.header.offset)
                        assertTrue(thirdChunk.header.final)
                        assertEquals(content.toList(), (firstChunk.payload + secondChunk.payload + thirdChunk.payload).toList())
                        write(peer, fileProgress(9, offer.transferId, content.size.toLong()))
                        write(
                            peer,
                            fileComplete(
                                id = 10,
                                transferId = offer.transferId,
                                accepted = true,
                                sha256 = offer.sha256,
                            ),
                        )
                        write(peer, disconnect(11))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, _ ->
                acceptedResult.set(accepted)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertTrue(acceptedResult.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferCancelsWhenPeerReportsUnexpectedProgress() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "unexpected-progress-client-file".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-unexpected-progress", ".txt")
            source.writeBytes(content)
            val connected = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(true)
            val reason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_OFFER, offerEnvelope.payloadCase)
                        val offer = offerEnvelope.fileOffer
                        write(peer, fileAccept(6, offer.transferId, accepted = true, maximumChunkBytes = 8))
                        val firstFrame = ProtocolV1Framing.read(peer.getInputStream())
                        val firstChunk = ProtocolV1Framing.decodeFileChunk(firstFrame.payload)
                        assertEquals(8, firstChunk.header.payloadLength)

                        write(peer, fileProgress(7, offer.transferId, 1))
                        val cancel = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, cancel.payloadCase)
                        assertEquals(offer.transferId, cancel.fileTransferCancel.transferId)
                        assertEquals("unexpected_progress", cancel.fileTransferCancel.reasonCode)
                        peer.soTimeout = 300
                        assertNull(readProtocolFrameOrNull(peer))
                        write(peer, disconnect(8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, rejectionReason ->
                acceptedResult.set(accepted)
                reason.set(rejectionReason)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertFalse(acceptedResult.get())
                assertEquals("unexpected_progress", reason.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferRejectsSecondConcurrentOfferBeforeWireMessage() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val first = File.createTempFile("vibescreen-client-first", ".txt")
            val second = File.createTempFile("vibescreen-client-second", ".txt")
            first.writeText("first-file")
            second.writeText("second-file")
            val connected = CountDownLatch(1)
            val firstOfferSeen = CountDownLatch(1)
            val rejectedResultSeen = CountDownLatch(1)
            val rejectedReason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_OFFER, offerEnvelope.payloadCase)
                        assertEquals(first.name, offerEnvelope.fileOffer.fileName)
                        firstOfferSeen.countDown()
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(9))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, reason ->
                if (!accepted && reason == "concurrent_limit") {
                    rejectedReason.set(reason)
                    rejectedResultSeen.countDown()
                }
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(first, "text/plain"))
                assertFalse(client.offerFile(second, "text/plain"))
                assertTrue(rejectedResultSeen.await(8, TimeUnit.SECONDS))
                assertEquals("concurrent_limit", rejectedReason.get())
                assertTrue(firstOfferSeen.await(8, TimeUnit.SECONDS))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                first.delete()
                second.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun legacyFallbackCancelsPendingOutgoingFileTransfers() {
        val source = File.createTempFile("vibescreen-fallback-offer", ".txt")
        source.writeText("fallback-file")
        val client = StreamClient("127.0.0.1", 1)
        val fileTransferProductOwner = client.fileTransferProductOwnerForTest()
        fileTransferProductOwner.activateSession()
        val prepared = fileTransferProductOwner.prepareOutgoingFile(
            file = source,
            mimeType = "text/plain",
            negotiatedPolicy = FileTransferPolicy(),
        ) as FileTransferProductOwner.PrepareOutgoingResult.Prepared
        assertTrue(
            fileTransferProductOwner.startPreparedOutgoing(prepared.transfer, canTransferFiles = true)
                is FileTransferProductOwner.StartOutgoingResult.Started,
        )
        val resultSeen = CountDownLatch(1)
        val rejectionReason = AtomicReference<String>()
        client.onFileTransferResult = { accepted, reason ->
            if (!accepted && reason == "session_deactivated") {
                rejectionReason.set(reason)
                resultSeen.countDown()
            }
        }
        try {
            client.forceLegacyFallbackForTest()

            assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
            assertEquals("session_deactivated", rejectionReason.get())
            assertEquals(0, fileTransferProductOwner.activeOutgoingTransferCount())
        } finally {
            source.delete()
        }
    }

    @Test
    fun clientFileOfferRejectsFileLargerThanNegotiatedPeerLimitWithoutWireMessage() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "too-large-for-peer".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-peer-limit", ".txt")
            source.writeBytes(content)
            val streaming = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(true)
            val reason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                            maxFileBytes = content.size.toLong() - 1,
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(8))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) streaming.countDown() }
            client.onFileTransferResult = { accepted, rejectionReason ->
                acceptedResult.set(accepted)
                reason.set(rejectionReason)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(streaming.await(8, TimeUnit.SECONDS))
                assertFalse(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertFalse(acceptedResult.get())
                assertEquals("file_too_large", reason.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferRejectsCompletionWithMismatchedSha256() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "from-client-file".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-client-offer", ".txt")
            source.writeBytes(content)
            val connected = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(true)
            val reason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        val offer = offerEnvelope.fileOffer
                        write(peer, fileAccept(6, offer.transferId, accepted = true))
                        ProtocolV1Framing.read(peer.getInputStream())
                        write(peer, fileProgress(7, offer.transferId, content.size.toLong()))
                        write(
                            peer,
                            fileComplete(
                                id = 8,
                                transferId = offer.transferId,
                                accepted = true,
                                sha256 = ByteString.copyFrom(ByteArray(32) { 7 }),
                            ),
                        )
                        val cancel = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, cancel.payloadCase)
                        assertEquals(offer.transferId, cancel.fileTransferCancel.transferId)
                        assertEquals("digest_mismatch", cancel.fileTransferCancel.reasonCode)
                        write(peer, disconnect(9))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, rejectionReason ->
                acceptedResult.set(accepted)
                reason.set(rejectionReason)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertFalse(acceptedResult.get())
                assertEquals("digest_mismatch", reason.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun clientFileOfferRejectsCompletionBeforeAllBytesAreAcknowledged() = runBlocking {
        ServerSocket(0).use { server ->
            val caps = listOf(Capability.CAPABILITY_TOUCH, Capability.CAPABILITY_FILE_TRANSFER)
            val content = "multi-chunk-client-file".toByteArray(Charsets.UTF_8)
            val source = File.createTempFile("vibescreen-early-complete", ".txt")
            source.writeBytes(content)
            val connected = CountDownLatch(1)
            val resultSeen = CountDownLatch(1)
            val acceptedResult = AtomicBoolean(true)
            val reason = AtomicReference<String>()
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = caps,
                            negotiatedCapabilities = caps,
                        )
                        connected.countDown()
                        val offerEnvelope = readEnvelope(peer)
                        val offer = offerEnvelope.fileOffer
                        write(peer, fileAccept(6, offer.transferId, accepted = true, maximumChunkBytes = 5))
                        val firstFrame = ProtocolV1Framing.read(peer.getInputStream())
                        val firstChunk = ProtocolV1Framing.decodeFileChunk(firstFrame.payload)
                        assertEquals(offer.transferId, firstChunk.header.transferId)
                        assertFalse(firstChunk.header.final)
                        write(peer, fileProgress(7, offer.transferId, firstChunk.header.offset + firstChunk.header.payloadLength))
                        val secondFrame = ProtocolV1Framing.read(peer.getInputStream())
                        val secondChunk = ProtocolV1Framing.decodeFileChunk(secondFrame.payload)
                        assertEquals(offer.transferId, secondChunk.header.transferId)
                        assertFalse(secondChunk.header.final)
                        write(
                            peer,
                            fileComplete(
                                id = 8,
                                transferId = offer.transferId,
                                accepted = true,
                                sha256 = offer.sha256,
                            ),
                        )
                        val cancel = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.FILE_TRANSFER_CANCEL, cancel.payloadCase)
                        assertEquals(offer.transferId, cancel.fileTransferCancel.transferId)
                        assertEquals("incomplete_file", cancel.fileTransferCancel.reasonCode)
                        write(peer, disconnect(9))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            client.onConnectionStatus = { connectedStatus -> if (connectedStatus) connected.countDown() }
            client.onFileTransferResult = { accepted, rejectionReason ->
                acceptedResult.set(accepted)
                reason.set(rejectionReason)
                resultSeen.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(connected.await(8, TimeUnit.SECONDS))
                assertTrue(client.offerFile(source, "text/plain"))
                assertTrue(resultSeen.await(8, TimeUnit.SECONDS))
                assertFalse(acceptedResult.get())
                assertEquals("incomplete_file", reason.get())
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    @Test
    fun fileOfferReturnsFalseWhenCapabilityNotNegotiatedWithoutWireMessage() = runBlocking {
        ServerSocket(0).use { server ->
            val streaming = CountDownLatch(1)
            val source = File.createTempFile("vibescreen-no-file-capability", ".txt")
            source.writeText("blocked")
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        completeHandshake(
                            peer,
                            initialRotation = 0,
                            hostCapabilities = emptyList(),
                            negotiatedCapabilities = emptyList(),
                        )
                        streaming.countDown()
                        peer.soTimeout = 300
                        assertNull(readEnvelopeOrNull(peer))
                        write(peer, disconnect(6))
                    }
                }
            val client = StreamClient("127.0.0.1", server.localPort)
            client.acceptVideoConfigurations()
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }
            try {
                assertTrue(streaming.await(8, TimeUnit.SECONDS))
                assertFalse(client.offerFile(source))
                withTimeout(8_000) { serverJob.await() }
            } finally {
                source.delete()
                client.disconnect()
            }
            withTimeout(8_000) { clientJob.await() }
            Unit
        }
    }

    private fun completeHandshake(
        peer: Socket,
        initialRotation: Int,
        hostCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        expectedClientCapabilities: List<Capability> = DEFAULT_CLIENT_CAPABILITIES,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
        maxFileBytes: Long = 0L,
        maxFileChunkBytes: Int = 0,
        displays: List<DisplayDescriptor> = listOf(display()),
        videoConfigEpoch: Long = 3,
        onClientHello: (dev.vibescreen.protocol.v1.ClientHello) -> Unit = {},
    ) {
        beginHandshake(
            peer,
            initialRotation,
            hostCapabilities,
            negotiatedCapabilities,
            expectedClientCapabilities,
            maxClipboardBytes,
            maxFileBytes,
            maxFileChunkBytes,
            displays,
            videoConfigEpoch,
            onClientHello,
        )
        val result = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
        assertTrue(result.videoConfigResult.accepted)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
    }

    private fun completeManagedPolicyHandshake(
        peer: Socket,
        initialRotation: Int,
        hostCapabilities: List<Capability>,
        negotiatedCapabilities: List<Capability>,
        hostManagedStatus: ManagedPolicyStatus,
        expectedClientCapabilities: List<Capability> = DEFAULT_CLIENT_CAPABILITIES,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
        maxFileBytes: Long = 0L,
        maxFileChunkBytes: Int = 0,
        displays: List<DisplayDescriptor> = listOf(display()),
        videoConfigEpoch: Long = 3,
        onClientPolicy: (ManagedPolicyStatus) -> Unit = {},
    ) {
        assertTrue(Capability.CAPABILITY_MANAGED_CONFIGURATION in negotiatedCapabilities)
        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
        peer.getOutputStream().flush()
        val clientHello = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, clientHello.payloadCase)
        assertEquals(expectedClientCapabilities.toSet(), clientHello.clientHello.capabilitiesList.toSet())
        assertEquals(emptyList<Capability>(), clientHello.clientHello.requiredCapabilitiesList)
        write(
            peer,
            hostHello(
                1,
                hostCapabilities,
                maxClipboardBytes = maxClipboardBytes,
                maxFileBytes = maxFileBytes,
                maxFileChunkBytes = maxFileChunkBytes,
            ),
        )
        write(
            peer,
            sessionAccepted(
                2,
                negotiatedCapabilities,
                maxClipboardBytes = maxClipboardBytes,
                maxFileBytes = maxFileBytes,
                maxFileChunkBytes = maxFileChunkBytes,
            ),
        )
        assertEquals(2, clientHello.clientHello.videoDecodeCapabilitiesCount)
        val clientPolicy = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.MANAGED_POLICY_STATUS, clientPolicy.payloadCase)
        onClientPolicy(clientPolicy.managedPolicyStatus)
        write(peer, managedPolicyStatus(3, hostManagedStatus))
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, displayList(4, displays))
        assertEquals(Envelope.PayloadCase.START_DISPLAY_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, startDisplay(5, displays.first()))
        write(peer, videoConfig(6, initialRotation, configEpoch = videoConfigEpoch))
        val result = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
        assertTrue(result.videoConfigResult.accepted)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
    }

    private fun StreamClient.forceLegacyFallbackForTest() {
        val method = javaClass.getDeclaredMethod("configureLegacyMode", Integer::class.java)
        method.isAccessible = true
        method.invoke(this, null)
    }

    private fun StreamClient.fileTransferProductOwnerForTest(): FileTransferProductOwner {
        val field = javaClass.getDeclaredField("fileTransferProductOwner")
        field.isAccessible = true
        return field.get(this) as FileTransferProductOwner
    }

    private fun beginHandshake(
        peer: Socket,
        initialRotation: Int,
        hostCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        expectedClientCapabilities: List<Capability> = DEFAULT_CLIENT_CAPABILITIES,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
        maxFileBytes: Long = 0L,
        maxFileChunkBytes: Int = 0,
        displays: List<DisplayDescriptor> = listOf(display()),
        videoConfigEpoch: Long = 3,
        onClientHello: (dev.vibescreen.protocol.v1.ClientHello) -> Unit = {},
    ) {
        assertEquals(PROTOCOL_UPGRADE_BYTE, peer.getInputStream().read())
        peer.getOutputStream().write(byteArrayOf(PROTOCOL_UPGRADE_BYTE.toByte(), 1))
        peer.getOutputStream().flush()
        val clientHello = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, clientHello.payloadCase)
        onClientHello(clientHello.clientHello)
        assertEquals(expectedClientCapabilities.toSet(), clientHello.clientHello.capabilitiesList.toSet())
        assertEquals(emptyList<Capability>(), clientHello.clientHello.requiredCapabilitiesList)
        write(
            peer,
            hostHello(
                1,
                hostCapabilities,
                maxClipboardBytes = maxClipboardBytes,
                maxFileBytes = maxFileBytes,
                maxFileChunkBytes = maxFileChunkBytes,
            ),
        )
        write(
            peer,
            sessionAccepted(
                2,
                negotiatedCapabilities,
                maxClipboardBytes = maxClipboardBytes,
                maxFileBytes = maxFileBytes,
                maxFileChunkBytes = maxFileChunkBytes,
            ),
        )
        assertEquals(2, clientHello.clientHello.videoDecodeCapabilitiesCount)
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, displayList(3, displays))
        assertEquals(Envelope.PayloadCase.START_DISPLAY_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, startDisplay(4, displays.first()))
        write(peer, videoConfig(5, initialRotation, configEpoch = videoConfigEpoch))
    }

    private suspend fun assertRejectedDecoderConfiguration(
        clientFactory: (Int) -> StreamClient,
        configure: (StreamVideoConfigurationCommit) -> Unit,
        expectedReason: String,
    ) = kotlinx.coroutines.coroutineScope {
        ServerSocket(0).use { server ->
            val ended = CountDownLatch(1)
            val configurationApplied = AtomicBoolean(false)
            var failure: SessionFailure? = null
            val serverJob =
                async(Dispatchers.IO) {
                    server.accept().use { peer ->
                        beginHandshake(peer, initialRotation = 0)
                        val result = readEnvelope(peer)
                        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
                        assertFalse(result.videoConfigResult.accepted)
                        assertEquals(expectedReason, result.videoConfigResult.rejectionReason)
                    }
                }
            val client = clientFactory(server.localPort)
            client.onVideoConfiguration = { _, commit -> configure(commit) }
            client.onVideoConfigurationApplied = { configurationApplied.set(true) }
            client.onSessionEnded = {
                failure = it
                ended.countDown()
            }
            val clientJob = async(Dispatchers.IO) { runCatching { client.connect() } }

            withTimeout(REJECTED_CONFIG_AWAIT_MS) { serverJob.await() }
            assertTrue(ended.await(REJECTED_CONFIG_AWAIT_MS, TimeUnit.MILLISECONDS))
            withTimeout(REJECTED_CONFIG_AWAIT_MS) { clientJob.await() }
            assertEquals(SessionFailureKind.CODEC_CONFIGURATION, checkNotNull(failure).kind)
            assertFalse(configurationApplied.get())
        }
    }

    private fun StreamClient.acceptVideoConfigurations() {
        onVideoConfiguration = { _, commit ->
            commit.accept()
        }
    }

    private fun StreamVideoConfigurationCommit.accept() {
        assertTrue(tryPublish { true })
        complete(StreamVideoConfigurationDecision.ACCEPTED)
    }

    private fun readEnvelope(peer: Socket): Envelope {
        val frame = ProtocolV1Framing.read(peer.getInputStream())
        assertEquals(ProtocolChannel.CONTROL, frame.channel)
        return Envelope.parseFrom(frame.payload)
    }

    private fun readEnvelopeOrNull(peer: Socket): Envelope? =
        try {
            readEnvelope(peer)
        } catch (_: SocketTimeoutException) {
            null
        } catch (_: IOException) {
            null
        }

    private fun readProtocolFrameOrNull(peer: Socket): ProtocolFrame? =
        try {
            ProtocolV1Framing.read(peer.getInputStream())
        } catch (_: SocketTimeoutException) {
            null
        } catch (_: IOException) {
            null
        }

    private fun readEnvelopeUntil(
        peer: Socket,
        attempts: Int = 8,
        predicate: (Envelope) -> Boolean,
    ): Envelope? {
        peer.soTimeout = 500
        repeat(attempts) {
            val envelope = readEnvelopeOrNull(peer) ?: return@repeat
            if (predicate(envelope)) return envelope
        }
        return null
    }

    private fun write(peer: Socket, envelope: Envelope) =
        ProtocolV1Framing.write(peer.getOutputStream(), ProtocolChannel.CONTROL, envelope.toByteArray())

    private fun writeVideo(
        peer: Socket,
        configEpoch: Long,
        frameId: Long,
        keyframe: Boolean,
    ) {
        val payload = byteArrayOf(0, 0, 0, 1, 0x26)
        val header =
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
                .setPayloadLength(payload.size)
                .build()
        ProtocolV1Framing.write(
            peer.getOutputStream(),
            ProtocolChannel.VIDEO,
            ProtocolV1Framing.encodeVideo(header, payload),
        )
    }

    private fun audioConfig(
        codec: AudioCodec = AudioCodec.AUDIO_CODEC_PCM_S16LE,
        configEpoch: Long = 1,
    ): AudioConfig =
        AudioConfig.newBuilder()
            .setStreamId(2)
            .setConfigEpoch(configEpoch)
            .setCodec(codec)
            .setSampleRateHz(48_000)
            .setChannelCount(2)
            .setFramesPerPacket(2)
            .build()

    private class TestPcmAudioOutputFactory : PcmAudioOutputFactory {
        val created = Collections.synchronizedList(mutableListOf<TestPcmAudioOutput>())
        val writeFailures = Collections.synchronizedList(mutableListOf<AudioOutputFailureReason>())
        var onWrite: () -> Unit = {}

        override fun create(format: PcmAudioStreamFormat): PcmAudioOutput =
            TestPcmAudioOutput(onWrite, writeFailures).also { created += it }
    }

    private class TestPcmAudioOutput(
        private val onWrite: () -> Unit,
        private val writeFailures: MutableList<AudioOutputFailureReason>,
    ) : PcmAudioOutput {
        val events = Collections.synchronizedList(mutableListOf<String>())
        val writes = Collections.synchronizedList(mutableListOf<ByteArray>())

        override fun start() {
            events += "start"
        }

        override fun writePcm(payload: ByteArray): PcmAudioWriteResult {
            synchronized(writeFailures) {
                if (writeFailures.isNotEmpty()) {
                    return PcmAudioWriteResult.Failed(writeFailures.removeAt(0))
                }
            }
            events += "write"
            writes += payload.copyOf()
            onWrite()
            return PcmAudioWriteResult.Written
        }

        override fun stop() {
            events += "stop"
        }

        override fun close() {
            try {
                stop()
            } catch (failure: RuntimeException) {
                throw AudioOutputException(AudioOutputFailureReason.STOP_FAILED, failure)
            }
            events += "close"
        }
    }

    private class ManualExecutor(
        private val onSubmit: () -> Unit,
    ) : Executor {
        val submitted = CountDownLatch(1)
        private val command = AtomicReference<Runnable?>()

        override fun execute(command: Runnable) {
            onSubmit()
            check(this.command.compareAndSet(null, command)) { "termination command already submitted" }
            submitted.countDown()
        }

        fun runSubmittedIfPresent() {
            command.getAndSet(null)?.run()
        }
    }

    private class GatedFirstScheduledExecutor :
        ScheduledThreadPoolExecutor(
            1,
            { runnable -> Thread(runnable, "StreamClientTimeoutTest").apply { isDaemon = true } },
        ) {
        val firstTaskStarted = CountDownLatch(1)
        val releaseFirstTask = CountDownLatch(1)
        private val scheduledTaskCount = AtomicInteger()

        override fun schedule(
            command: Runnable,
            delay: Long,
            unit: TimeUnit,
        ): ScheduledFuture<*> {
            val taskIndex = scheduledTaskCount.getAndIncrement()
            return super.schedule(
                {
                    if (taskIndex == 0) {
                        firstTaskStarted.countDown()
                        releaseFirstTask.await()
                    }
                    command.run()
                },
                delay,
                unit,
            )
        }
    }

    private class FlushTrackingSocket(
        private val flushCount: AtomicInteger,
    ) : Socket() {
        override fun getOutputStream(): OutputStream {
            val delegate = super.getOutputStream()
            return object : OutputStream() {
                override fun write(value: Int) = delegate.write(value)

                override fun write(
                    bytes: ByteArray,
                    offset: Int,
                    length: Int,
                ) = delegate.write(bytes, offset, length)

                override fun flush() {
                    delegate.flush()
                    flushCount.incrementAndGet()
                }

                override fun close() = delegate.close()
            }
        }
    }

    private class GateableFlushSocket : Socket() {
        val flushEntered = CountDownLatch(1)
        val releaseFlush = CountDownLatch(1)
        private val armed = AtomicBoolean(false)
        private val blocked = AtomicBoolean(false)

        fun armNextFlush() {
            armed.set(true)
        }

        override fun getOutputStream(): OutputStream {
            val delegate = super.getOutputStream()
            return object : OutputStream() {
                override fun write(value: Int) = delegate.write(value)

                override fun write(
                    bytes: ByteArray,
                    offset: Int,
                    length: Int,
                ) = delegate.write(bytes, offset, length)

                override fun flush() {
                    if (armed.compareAndSet(true, false) && blocked.compareAndSet(false, true)) {
                        flushEntered.countDown()
                        try {
                            releaseFlush.await()
                        } catch (error: InterruptedException) {
                            Thread.currentThread().interrupt()
                            throw IOException("flush gate interrupted", error)
                        }
                    }
                    delegate.flush()
                }

                override fun close() = delegate.close()
            }
        }
    }

    private fun hostHello(
        id: Long,
        advertisedCapabilities: List<Capability>,
        hostId: String = TEST_HOST_ID,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
        maxFileBytes: Long = 0L,
        maxFileChunkBytes: Int = 0,
    ): Envelope =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello.newBuilder()
                    .setSelectedProtocol(1)
                    .setHostId(hostId)
                    .addAllCapabilities(advertisedCapabilities)
                    .addCodecs(Codec.CODEC_HEVC)
                    .setResourceLimits(
                        ResourceLimits.newBuilder()
                            .setMaximumClipboardBytes(maxClipboardBytes)
                            .setMaximumFileBytes(maxFileBytes)
                            .setMaximumFileChunkBytes(maxFileChunkBytes),
                    ),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability>,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
        maxFileBytes: Long = 0L,
        maxFileChunkBytes: Int = 0,
    ): Envelope =
        base(id)
            .setSessionAccepted(
                SessionAccepted.newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .addAllNegotiatedCapabilities(negotiatedCapabilities)
                    .setNegotiatedResourceLimits(
                        ResourceLimits.newBuilder()
                            .setMaximumClipboardBytes(maxClipboardBytes)
                            .setMaximumFileBytes(maxFileBytes)
                            .setMaximumFileChunkBytes(maxFileChunkBytes),
                    ),
            ).build()

    private fun displayList(
        id: Long,
        displays: List<DisplayDescriptor> = listOf(display()),
    ): Envelope =
        base(id).setListDisplaysResponse(
            ListDisplaysResponse.newBuilder().addAllDisplays(displays),
        ).build()

    private fun startDisplay(
        id: Long,
        display: DisplayDescriptor = display(),
    ): Envelope =
        base(id).setStartDisplayResponse(
            StartDisplayResponse.newBuilder().setAccepted(true).setDisplay(display).setStreamId(42),
        ).build()

    private fun videoConfig(
        id: Long,
        rotation: Int,
        configEpoch: Long = 3,
        encodedWidth: Int = 1920,
        encodedHeight: Int = 1080,
    ): Envelope =
        base(id).setVideoConfig(
            VideoConfig.newBuilder()
                .setConfigEpoch(configEpoch)
                .setCodec(Codec.CODEC_HEVC)
                .setEncodedSize(Dimensions.newBuilder().setWidth(encodedWidth).setHeight(encodedHeight))
                .setFramesPerSecond(60)
                .setBitrateKbps(12_000)
                .setStreamId(42)
                .setRotationDegrees(rotation),
        ).build()

    private fun displayChanged(
        id: Long,
        rotation: Int,
        logicalWidth: Int = 1920,
        logicalHeight: Int = 1080,
    ): Envelope =
        base(id).setDisplayChanged(
            DisplayChanged
                .newBuilder()
                .setDisplay(display(logicalWidth, logicalHeight))
                .setRotationDegrees(rotation),
        ).build()

    private fun disconnect(id: Long): Envelope =
        base(id).setDisconnectNotice(
            DisconnectNotice.newBuilder().setReasonCode("host_shutdown").setMayResume(false),
        ).build()

    private fun hostActionCatalog(id: Long): Envelope =
        base(id).setHostActionCatalog(
            HostActionCatalog.newBuilder()
                .addActions(
                    HostActionDescriptor.newBuilder().setActionId("move-window").setLocalizedName("Move"),
                ).addActions(
                    HostActionDescriptor.newBuilder().setActionId("return-windows").setLocalizedName("Return"),
                ),
        ).build()

    private fun hostActionResult(
        id: Long,
        invocationId: ByteString,
        accepted: Boolean,
    ): Envelope =
        base(id).setHostActionResult(
            HostActionResult.newBuilder().setInvocationId(invocationId).setAccepted(accepted),
        ).build()

    private fun signedWakeHostRequest(
        id: Long,
        requestId: ByteString,
        targetMac: ByteString,
        clientDeviceId: String,
        secret: ByteArray,
    ): Envelope {
        val keyId = WakeHostProof.keyId(secret)
        val nonce = ByteString.copyFrom(ByteArray(WakeHostProof.MINIMUM_NONCE_BYTES) { (0xa0 + it).toByte() })
        val issuedAt = 1_000L
        val expiresAt = 1_060L
        val signature =
            WakeHostProof.signature(
                requestId = requestId,
                targetMacAddress = targetMac,
                secureOnPassword = ByteString.EMPTY,
                hostId = TEST_HOST_ID,
                deviceId = clientDeviceId,
                keyId = keyId,
                issuedAtUnixSeconds = issuedAt,
                expiresAtUnixSeconds = expiresAt,
                nonce = nonce,
                secret = secret,
            )
        return base(id)
            .setWakeHostRequest(
                WakeHostRequest.newBuilder()
                    .setRequestId(requestId)
                    .setTargetMacAddress(targetMac)
                    .setHostId(TEST_HOST_ID)
                    .setDeviceId(clientDeviceId)
                    .setKeyId(keyId)
                    .setIssuedAtUnixSeconds(issuedAt)
                    .setExpiresAtUnixSeconds(expiresAt)
                    .setNonce(nonce)
                    .setSignature(signature),
            ).build()
    }

    private fun clipboardOffer(
        id: Long,
        changeId: ByteString,
        originDeviceId: String,
        byteLength: Long,
        sha256: ByteString,
    ): Envelope =
        base(id).setClipboardOffer(
            ClipboardOffer.newBuilder()
                .setChangeId(changeId)
                .setOriginDeviceId(originDeviceId)
                .setMimeType("text/plain")
                .setByteLength(byteLength)
                .setSha256(sha256),
        ).build()

    private fun clipboardRequest(
        id: Long,
        changeId: ByteString,
    ): Envelope =
        base(id).setClipboardRequest(
            ClipboardRequest.newBuilder().setChangeId(changeId),
        ).build()

    private fun clipboardContent(
        id: Long,
        changeId: ByteString,
        originDeviceId: String,
        content: ByteArray,
        sha256: ByteString,
    ): Envelope =
        base(id).setClipboardContent(
            ClipboardContent.newBuilder()
                .setChangeId(changeId)
                .setOriginDeviceId(originDeviceId)
                .setMimeType("text/plain")
                .setContent(ByteString.copyFrom(content))
                .setSha256(sha256),
        ).build()

    private fun fileOffer(
        id: Long,
        transferId: ByteString,
        fileName: String,
        content: ByteArray,
    ): Envelope =
        base(id).setFileOffer(
            FileOffer.newBuilder()
                .setTransferId(transferId)
                .setFileName(fileName)
                .setMimeType("text/plain")
                .setByteLength(content.size.toLong())
                .setSha256(ByteString.copyFrom(sha256(content))),
        ).build()

    private fun fileAccept(
        id: Long,
        transferId: ByteString,
        accepted: Boolean,
        reason: String = "",
        maximumChunkBytes: Int = 64 * 1024,
    ): Envelope =
        base(id).setFileAccept(
            FileAccept.newBuilder()
                .setTransferId(transferId)
                .setAccepted(accepted)
                .setMaximumChunkBytes(maximumChunkBytes)
                .setRejectionReason(reason),
        ).build()

    private fun fileProgress(
        id: Long,
        transferId: ByteString,
        receivedBytes: Long,
    ): Envelope =
        base(id).setFileTransferProgress(
            FileTransferProgress.newBuilder()
                .setTransferId(transferId)
                .setReceivedBytes(receivedBytes),
        ).build()

    private fun fileComplete(
        id: Long,
        transferId: ByteString,
        accepted: Boolean,
        sha256: ByteString,
    ): Envelope =
        base(id).setFileTransferComplete(
            FileTransferComplete.newBuilder()
                .setTransferId(transferId)
                .setAccepted(accepted)
                .setSha256(sha256),
        ).build()

    private fun fileCancel(
        id: Long,
        transferId: ByteString,
        reasonCode: String,
    ): Envelope =
        base(id).setFileTransferCancel(
            FileTransferCancel.newBuilder()
                .setTransferId(transferId)
                .setReasonCode(reasonCode),
        ).build()

    private fun managedPolicyStatus(
        id: Long,
        status: ManagedPolicyStatus,
    ): Envelope = base(id).setManagedPolicyStatus(status).build()

    private fun managedPolicy(
        fileTransferAllowed: Boolean = true,
        audioAllowed: Boolean = true,
        maximumFileBytes: Long = ProtocolV1Session.ManagedPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
    ): ProtocolV1Session.ManagedPolicy =
        ProtocolV1Session.ManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            fileTransferAllowed = fileTransferAllowed,
            audioAllowed = audioAllowed,
            maximumFileBytes = maximumFileBytes,
            allowedHosts = setOf(TEST_HOST_ID),
            allowedHostsRestricted = true,
        )

    private fun managedPolicyStatus(
        fileTransferAllowed: Boolean = true,
        maximumFileBytes: Long = ProtocolV1Session.ManagedPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
    ): ManagedPolicyStatus =
        managedPolicy(fileTransferAllowed = fileTransferAllowed, maximumFileBytes = maximumFileBytes).toStatus()

    private fun clientCapabilitiesWithout(capabilities: Set<Capability>): List<Capability> =
        DEFAULT_CLIENT_CAPABILITIES.filterNot { it in capabilities }

    private fun fileChunk(
        transferId: ByteString,
        offset: Long,
        payload: ByteArray,
        final: Boolean,
        sessionEpoch: Long = 7,
    ): ByteArray =
        ProtocolV1Framing.encodeFileChunk(
            FileChunkHeader.newBuilder()
                .setTransferId(transferId)
                .setOffset(offset)
                .setPayloadLength(payload.size)
                .setSessionEpoch(sessionEpoch)
                .setChunkSha256(ByteString.copyFrom(sha256(payload)))
                .setFinal(final)
                .build(),
            payload,
        )

    private fun corruptedFileChunk(
        transferId: ByteString,
        offset: Long,
        payload: ByteArray,
        final: Boolean,
        sessionEpoch: Long = 7,
    ): ByteArray =
        ProtocolV1Framing.encodeFileChunk(
            FileChunkHeader.newBuilder()
                .setTransferId(transferId)
                .setOffset(offset)
                .setPayloadLength(payload.size)
                .setSessionEpoch(sessionEpoch)
                .setChunkSha256(ByteString.copyFrom(ByteArray(32) { 0x7f }))
                .setFinal(final)
                .build(),
            payload,
        )

    private fun sha256(bytes: ByteArray): ByteArray =
        java.security.MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun hostProtocolError(id: Long): Envelope =
        base(id).setProtocolError(
            ProtocolError
                .newBuilder()
                .setCode(ProtocolErrorCode.PROTOCOL_ERROR_CODE_INVALID_STATE)
                .setMessage("host terminated the session")
                .setRetryable(false),
        ).build()

    private fun display(
        logicalWidth: Int = 1920,
        logicalHeight: Int = 1080,
        id: String = "display-main",
    ): DisplayDescriptor =
        DisplayDescriptor.newBuilder()
            .setDisplayId(id)
            .setLogicalSize(Dimensions.newBuilder().setWidth(logicalWidth).setHeight(logicalHeight))
            .build()

    private fun base(id: Long): Envelope.Builder =
        Envelope.newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    companion object {
        private const val PROTOCOL_UPGRADE_BYTE = 0x0d
        private const val TEST_HOST_ID = "host-test-device"
        private const val TEST_MAX_CLIPBOARD_BYTES = 1024L * 1024L
        // Generous await ceiling for the rejected-decoder-configuration path.
        // These integration tests drive a real loopback socket plus coroutine
        // handoffs, whose scheduling is far slower on a shared CI runner than
        // locally; a tight ceiling makes the reject assertions flaky there.
        private const val REJECTED_CONFIG_AWAIT_MS = 8_000L
        private val SESSION_ID = ByteString.copyFrom(ByteArray(16) { 1 })
        private val DEFAULT_CLIENT_CAPABILITIES =
            listOf(
                Capability.CAPABILITY_TOUCH,
                Capability.CAPABILITY_KEYBOARD,
                Capability.CAPABILITY_POINTER,
                Capability.CAPABILITY_STYLUS,
                Capability.CAPABILITY_STYLUS_EXTENDED,
                Capability.CAPABILITY_COLOR_MANAGEMENT,
                Capability.CAPABILITY_MULTI_DISPLAY,
                Capability.CAPABILITY_CLIENT_VIDEO_CONTROL,
                Capability.CAPABILITY_HOST_ACTIONS,
                Capability.CAPABILITY_USB_HID_MODIFIER_BYTE,
                Capability.CAPABILITY_CLIPBOARD,
                Capability.CAPABILITY_AUDIO,
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
    }
}
