package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.ProtocolChannel
import dev.telemachus.display.protocol.ProtocolV1Framing
import dev.telemachus.display.protocol.TouchSample
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
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.HostActionCatalog
import dev.vibescreen.protocol.v1.HostActionDescriptor
import dev.vibescreen.protocol.v1.HostActionResult
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.ProtocolError
import dev.vibescreen.protocol.v1.ProtocolErrorCode
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.VideoConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
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
            client.onFileOffer = { true }
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
                        write(
                            peer,
                            fileComplete(
                                id = 7,
                                transferId = offer.transferId,
                                accepted = true,
                                sha256 = offer.sha256,
                            ),
                        )
                        write(peer, disconnect(8))
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
        onClientHello: (dev.vibescreen.protocol.v1.ClientHello) -> Unit = {},
    ) {
        beginHandshake(
            peer,
            initialRotation,
            hostCapabilities,
            negotiatedCapabilities,
            expectedClientCapabilities,
            maxClipboardBytes,
            onClientHello,
        )
        val result = readEnvelope(peer)
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, result.payloadCase)
        assertTrue(result.videoConfigResult.accepted)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, readEnvelope(peer).payloadCase)
    }

    private fun beginHandshake(
        peer: Socket,
        initialRotation: Int,
        hostCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        negotiatedCapabilities: List<Capability> = listOf(Capability.CAPABILITY_TOUCH),
        expectedClientCapabilities: List<Capability> = DEFAULT_CLIENT_CAPABILITIES,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
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
        write(peer, hostHello(1, hostCapabilities, maxClipboardBytes = maxClipboardBytes))
        write(peer, sessionAccepted(2, negotiatedCapabilities, maxClipboardBytes = maxClipboardBytes))
        assertEquals(2, clientHello.clientHello.videoDecodeCapabilitiesCount)
        assertEquals(Envelope.PayloadCase.LIST_DISPLAYS_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, displayList(3))
        assertEquals(Envelope.PayloadCase.START_DISPLAY_REQUEST, readEnvelope(peer).payloadCase)
        write(peer, startDisplay(4))
        write(peer, videoConfig(5, initialRotation))
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

    private fun hostHello(
        id: Long,
        advertisedCapabilities: List<Capability>,
        hostId: String = TEST_HOST_ID,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
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
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(maxClipboardBytes),
                    ),
            ).build()

    private fun sessionAccepted(
        id: Long,
        negotiatedCapabilities: List<Capability>,
        maxClipboardBytes: Long = TEST_MAX_CLIPBOARD_BYTES,
    ): Envelope =
        base(id)
            .setSessionAccepted(
                SessionAccepted.newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .addAllNegotiatedCapabilities(negotiatedCapabilities)
                    .setNegotiatedResourceLimits(
                        ResourceLimits.newBuilder().setMaximumClipboardBytes(maxClipboardBytes),
                    ),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id).setListDisplaysResponse(
            ListDisplaysResponse.newBuilder().addDisplays(display()),
        ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id).setStartDisplayResponse(
            StartDisplayResponse.newBuilder().setAccepted(true).setDisplay(display()).setStreamId(42),
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
    ): Envelope =
        base(id).setFileAccept(
            FileAccept.newBuilder()
                .setTransferId(transferId)
                .setAccepted(accepted)
                .setMaximumChunkBytes(64 * 1024)
                .setRejectionReason(reason),
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

    private fun fileChunk(
        transferId: ByteString,
        offset: Long,
        payload: ByteArray,
        final: Boolean,
    ): ByteArray =
        ProtocolV1Framing.encodeFileChunk(
            FileChunkHeader.newBuilder()
                .setTransferId(transferId)
                .setOffset(offset)
                .setPayloadLength(payload.size)
                .setSessionEpoch(7)
                .setChunkSha256(ByteString.copyFrom(sha256(payload)))
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
    ): DisplayDescriptor =
        DisplayDescriptor.newBuilder()
            .setDisplayId("display-main")
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
                Capability.CAPABILITY_FILE_TRANSFER,
                Capability.CAPABILITY_MANAGED_CONFIGURATION,
            )
    }
}
