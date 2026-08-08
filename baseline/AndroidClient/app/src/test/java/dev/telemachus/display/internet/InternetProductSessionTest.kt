package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DeviceRevoked
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.ResourceLimits
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import java.security.SecureRandom

class InternetProductSessionTest {
    private val localIdentity =
        publicPoint(generateEphemeral(SecureRandom())).let { publicKey ->
            InternetPairingIdentity(
                deviceId = "device-1",
                keyId = pairingSha256(publicKey).toPairingHex(),
                keyEpoch = 1,
                signingPublicKey = publicKey,
            )
        }
    private val signaling =
        SignalingConfiguration(
            baseUrl = "https://signal.example.test",
            bearerToken = "device-role-token-with-at-least-32-characters",
            role = PeerRole.DEVICE,
        )
    private val lease =
        InternetProductSessionLease(
            pairingIdentifier = "pair-1",
            signalingSessionId = "session-1",
            authoritativeSessionEpoch = 7,
            identityEpoch = 1,
            localIdentity = localIdentity,
            transcriptContext = ByteArray(32),
            iceServers = listOf(IceServer(listOf("stun:stun.example.test:3478"))),
            signaling = signaling,
            pinnedHostId = "host-1",
        )
    private val codec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.HEVC)) { 1 }

    @Test
    fun boundTranscriptContextMatchesSwiftKnownAnswer() {
        val context =
            InternetProductSessionLease(
                pairingIdentifier = "pair-1",
                signalingSessionId = "session-1",
                authoritativeSessionEpoch = 7,
                identityEpoch = 1,
                localIdentity = localIdentity,
                transcriptContext = ByteArray(32) { it.toByte() },
                iceServers = listOf(IceServer(listOf("stun:stun.example.test:3478"))),
                signaling = SignalingConfiguration("https://signal.example.test", "x".repeat(32), PeerRole.DEVICE),
                pinnedHostId = "host-1",
            ).use { it.boundTranscriptContext("device-1") }

        assertArrayEquals(
            "dd7e26a6d119e9d8d62e3f967d311c7c0ef78357a985947e33083b8c2c683735".hex(),
            context,
        )
    }

    @Test
    fun negotiatesVideoDeliversKeyframeAndRequestsFreshSessionOnHandoff() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, Envelope.parseFrom(peer.control.single()).payloadCase)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)

        peer.receive(
            controlEnvelope(3)
                .setVideoConfig(
                    VideoConfig
                        .newBuilder()
                        .setConfigEpoch(3)
                        .setCodec(Codec.CODEC_HEVC)
                        .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                        .setFramesPerSecond(60)
                        .setBitrateKbps(12_000)
                        .setStreamId(5)
                        .setRotationDegrees(90),
                ).build(),
        )
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, Envelope.parseFrom(peer.control.last()).payloadCase)

        peer.media(media(frameId = 1, keyframe = false, payload = "delta".toByteArray()))
        assertEquals(0, callbacks.frames.size)
        assertEquals(Envelope.PayloadCase.REQUEST_KEYFRAME, Envelope.parseFrom(peer.control.last()).payloadCase)
        peer.media(media(frameId = 2, keyframe = true, payload = "key".toByteArray()))
        assertEquals("key", callbacks.frames.single().payload.toString(Charsets.UTF_8))
        assertTrue(session.sendTouch(ProductTouchEvent(1, 0, ProductInputPhase.BEGAN, 0.5, 0.5)))
        assertEquals(listOf(90), callbacks.configurations.map { it.rotationDegrees })

        peer.receive(
            controlEnvelope(4)
                .setVideoConfig(
                    VideoConfig
                        .newBuilder()
                        .setConfigEpoch(4)
                        .setCodec(Codec.CODEC_HEVC)
                        .setEncodedSize(Dimensions.newBuilder().setWidth(1080).setHeight(1920))
                        .setFramesPerSecond(60)
                        .setBitrateKbps(12_000)
                        .setStreamId(5)
                        .setRotationDegrees(270),
                ).build(),
        )
        assertEquals(listOf(90, 270), callbacks.configurations.map { it.rotationDegrees })

        monitor.available("cellular")
        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertEquals(1, callbacks.freshReasons.size)
        assertEquals(1, callbacks.states.count { it == InternetProductSessionState.RECOVERING })
        assertEquals(0, peer.restartCalls)
        assertFalse(session.sendTouch(ProductTouchEvent(2, 0, ProductInputPhase.ENDED, 0.5, 0.5)))
        session.close()
        session.close()
        assertEquals(1, peer.closeCalls)
        assertEquals(1, monitor.closeCalls)
    }

    @Test
    fun rejectsWrongPinnedHostAndNonMonotonicControlIds() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)

        peer.receive(controlEnvelope(2).setHostHello(hostHello().setHostId("attacker")).build())
        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)

        val secondPeer = ProductFakePeerEngine()
        val secondCallbacks = ProductCallbacks()
        val second = session(secondPeer, ProductFakeNetworkMonitor().also { }, secondCallbacks)
        second.start()
        secondPeer.observer.onConnected(PeerRoute.DIRECT)
        secondPeer.receive(controlEnvelope(2).setHostHello(hostHello()).build())
        secondPeer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.FAILED, second.state)
        assertEquals(1, secondCallbacks.failures.size)
    }

    @Test
    fun rejectsLegacyHostWithoutMediaFragmentationDuringHandshake() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        peer.receive(
            controlEnvelope(1)
                .setHostHello(
                    hostHello()
                        .clearCapabilities()
                        .addAllCapabilities(
                            ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES.filterNot {
                                it == Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION
                            },
                        ),
                ).build(),
        )

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
    }

    @Test
    fun rejectsSessionAcceptanceCapabilitiesThatDifferFromTheExactHelloIntersection() {
        val requiredCapabilities = ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES
        val invalidHandshakes =
            listOf(
                hostHello() to
                    sessionAccepted()
                        .clearNegotiatedCapabilities()
                        .addAllNegotiatedCapabilities(
                            requiredCapabilities.filterNot {
                                it == Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION
                            },
                        ),
                hostHello() to sessionAccepted().addNegotiatedCapabilities(Capability.CAPABILITY_AUDIO),
                hostHello().addCapabilities(Capability.CAPABILITY_AUDIO) to
                    sessionAccepted().addNegotiatedCapabilities(Capability.CAPABILITY_AUDIO),
            )

        invalidHandshakes.forEach { (advertisedHostHello, invalidAcceptance) ->
            val peer = ProductFakePeerEngine()
            val callbacks = ProductCallbacks()
            val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
            session.start()
            peer.observer.onConnected(PeerRoute.DIRECT)
            peer.receive(controlEnvelope(1).setHostHello(advertisedHostHello).build())
            peer.receive(controlEnvelope(2).setSessionAccepted(invalidAcceptance).build())

            assertEquals(InternetProductSessionState.FAILED, session.state)
            assertEquals(1, callbacks.failures.size)
            assertTrue(callbacks.configurations.isEmpty())
        }
    }

    @Test
    fun acceptsHostOnlyFutureCapabilityWhenSessionAcceptanceUsesTheExactIntersection() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(
            controlEnvelope(1)
                .setHostHello(hostHello().addCapabilities(Capability.CAPABILITY_AUDIO))
                .build(),
        )
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun acceptsFutureLargerUnsignedHostLimitsAndClampsNegotiationToTheLocalMaximum() {
        val futureHostLimits =
            listOf(
                InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES * 2,
                -1,
            )

        futureHostLimits.forEach { advertisedLimit ->
            val peer = ProductFakePeerEngine()
            val callbacks = ProductCallbacks()
            val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
            session.start()
            peer.observer.onConnected(PeerRoute.DIRECT)
            peer.receive(
                controlEnvelope(1)
                    .setHostHello(hostHello().setResourceLimits(mediaRecordLimits(advertisedLimit)))
                    .build(),
            )
            peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

            assertEquals(InternetProductSessionState.ACTIVE, session.state)
            assertTrue(callbacks.failures.isEmpty())
        }
    }

    @Test
    fun rejectsFutureHostLimitWhenSessionAcceptanceDoesNotClampToTheLocalMaximum() {
        val advertisedLimit = InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES * 2
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(
            controlEnvelope(1)
                .setHostHello(hostHello().setResourceLimits(mediaRecordLimits(advertisedLimit)))
                .build(),
        )
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(
                    sessionAccepted().setNegotiatedResourceLimits(mediaRecordLimits(advertisedLimit)),
                ).build(),
        )

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
    }

    @Test
    fun rejectsMissingHostMediaRecordLimitDuringHandshake() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello().clearResourceLimits()).build())

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
    }

    @Test
    fun rejectsMissingOrMismatchedNegotiatedMediaRecordLimitBeforeVideo() {
        for (acceptedLimit in listOf(0, InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES - 1)) {
            val peer = ProductFakePeerEngine()
            val callbacks = ProductCallbacks()
            val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
            session.start()
            peer.observer.onConnected(PeerRoute.DIRECT)
            peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
            peer.receive(
                controlEnvelope(2)
                    .setSessionAccepted(
                        sessionAccepted().setNegotiatedResourceLimits(
                            mediaRecordLimits(acceptedLimit),
                        ),
                    ).build(),
            )

            assertEquals(InternetProductSessionState.FAILED, session.state)
            assertEquals(1, callbacks.failures.size)
        }
    }

    @Test
    fun rejectsPlaintextMediaRecordAboveNegotiatedLimit() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        val negotiatedLimit = InternetMediaRecordContract.MINIMUM_NEGOTIATED_ENCRYPTED_RECORD_BYTES
        peer.receive(
            controlEnvelope(1)
                .setHostHello(
                    hostHello().setResourceLimits(mediaRecordLimits(negotiatedLimit)),
                ).build(),
        )
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(
                    sessionAccepted().setNegotiatedResourceLimits(mediaRecordLimits(negotiatedLimit)),
                ).build(),
        )
        peer.receive(videoConfigurationEnvelope(3))
        val negotiatedPlaintextLimit = negotiatedLimit - InternetMediaRecordContract.APPLICATION_AEAD_RECORD_OVERHEAD_BYTES
        val oversizedRecord = mediaRecordWithExactSize(negotiatedPlaintextLimit + 1)

        assertEquals(negotiatedPlaintextLimit + 1, oversizedRecord.size)
        assertTrue(codec.decodeMediaFragment(oversizedRecord).payload.isNotEmpty())
        peer.media(oversizedRecord)

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
        assertEquals(
            "Protocol v1 media record exceeds the negotiated session limit",
            callbacks.failures.single().cause?.message,
        )
        assertEquals(0, callbacks.frames.size)
    }

    @Test
    fun tickExpiresIncompleteMediaAssemblyAndRequestsOneKeyframe() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val clock = ProductFakeClock(0)
        val session = session(peer, monitor, callbacks, clock)
        activateWithVideo(session, peer, monitor)
        peer.media(
            media(
                frameId = 5,
                keyframe = true,
                payload = "partial".toByteArray(),
                fragmentIndex = 0,
                fragmentCount = 2,
            ),
        )
        val requestsBeforeDeadline = peer.keyframeRequests().size

        clock.now = ProductMediaFrameAssembler.DEFAULT_ASSEMBLY_DEADLINE_MS
        session.tick()

        val requestsAfterDeadline = peer.keyframeRequests()
        assertEquals(requestsBeforeDeadline + 1, requestsAfterDeadline.size)
        assertEquals(
            ProductMediaFrameAssembler.REASON_ASSEMBLY_TIMEOUT,
            requestsAfterDeadline.last().requestKeyframe.reasonCode,
        )
        session.tick()
        assertEquals(requestsAfterDeadline.size, peer.keyframeRequests().size)

        peer.media(media(frameId = 6, keyframe = true, payload = "fresh".toByteArray()))
        assertEquals("fresh", callbacks.frames.single().payload.toString(Charsets.UTF_8))
    }

    @Test
    fun routeChangesAndConcurrentConnectedCallbacksSendOneClientHello() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        val executor = Executors.newFixedThreadPool(16)
        val ready = CountDownLatch(16)
        val start = CountDownLatch(1)
        repeat(16) { index ->
            executor.execute {
                ready.countDown()
                start.await()
                peer.observer.onConnected(if (index % 2 == 0) PeerRoute.DIRECT else PeerRoute.RELAY)
            }
        }
        assertTrue(ready.await(2, TimeUnit.SECONDS))
        start.countDown()
        executor.shutdown()
        assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS))
        peer.observer.onRouteChanged(PeerRoute.DIRECT)
        peer.observer.onRouteChanged(PeerRoute.RELAY)

        assertEquals(1, peer.control.size)
        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, Envelope.parseFrom(peer.control.single()).payloadCase)
        assertTrue(callbacks.routes.isNotEmpty())
    }

    @Test
    fun shortDisconnectRouteInterleavingResumesActiveTouchAndHeartbeatWithoutSecondHello() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val clock = ProductFakeClock(0)
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, clock = clock)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)

        peer.observer.onDisconnected()
        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        peer.observer.onRouteChanged(PeerRoute.RELAY)
        peer.observer.onConnected(PeerRoute.DIRECT)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(session.sendTouch(ProductTouchEvent(9, 0, ProductInputPhase.BEGAN, 0.25, 0.75)))

        clock.now = 1_000
        session.tick()
        val payloads = peer.control.map { Envelope.parseFrom(it).payloadCase }
        assertEquals(1, payloads.count { it == Envelope.PayloadCase.CLIENT_HELLO })
        assertTrue(payloads.contains(Envelope.PayloadCase.TOUCH_EVENT))
        assertTrue(payloads.contains(Envelope.PayloadCase.PING))
        assertTrue(callbacks.routes.contains(PeerRoute.RELAY))
        assertTrue(callbacks.routes.contains(PeerRoute.DIRECT))
    }

    @Test
    fun freshSessionRequestInvalidatesOwnerAndLateCallbacksCannotReactivateOldEpoch() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val clock = ProductFakeClock(0)
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, clock = clock)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)

        monitor.available("cellular")
        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertEquals(1, callbacks.freshReasons.size)
        peer.observer.onConnected(PeerRoute.RELAY)
        peer.observer.onRouteChanged(PeerRoute.DIRECT)
        peer.observer.onFailure(IllegalStateException("late owner failure"))
        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertFalse(session.sendTouch(ProductTouchEvent(10, 0, ProductInputPhase.BEGAN, 0.1, 0.2)))

        clock.now = 10_000
        session.tick()
        val payloads = peer.control.map { Envelope.parseFrom(it).payloadCase }
        assertEquals(1, payloads.count { it == Envelope.PayloadCase.CLIENT_HELLO })
        assertFalse(payloads.contains(Envelope.PayloadCase.TOUCH_EVENT))
        assertFalse(payloads.contains(Envelope.PayloadCase.PING))
    }

    @Test
    fun freshInvalidationAfterControlDecodePreventsLateSessionAcceptanceCommit() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val shouldBlock = AtomicBoolean(false)
        val decoded = CountDownLatch(1)
        val release = CountDownLatch(1)
        val session =
            session(
                peer,
                monitor,
                callbacks,
                testHooks =
                    InternetProductSessionTestHooks(
                        afterControlDecodeBeforeCommit = {
                            if (shouldBlock.get()) {
                                decoded.countDown()
                                assertTrue(release.await(2, TimeUnit.SECONDS))
                            }
                        },
                    ),
            )
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())

        shouldBlock.set(true)
        val executor = Executors.newSingleThreadExecutor()
        val acceptance = executor.submit { peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build()) }
        assertTrue(decoded.await(2, TimeUnit.SECONDS))
        monitor.available("cellular")
        release.countDown()
        acceptance.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertEquals(1, callbacks.freshReasons.size)
        assertEquals(1, peer.control.size)
        assertFalse(session.sendTouch(ProductTouchEvent(12, 0, ProductInputPhase.BEGAN, 0.2, 0.3)))
    }

    @Test
    fun videoConfigurationCallbackCanCloseWithoutDeadlockOrLateSend() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val sessionReference = AtomicReference<InternetProductSession>()
        val installs = AtomicInteger(0)
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    sessionReference.get().close()
                    completion(
                        effect.commit {
                            installs.incrementAndGet()
                            ProductVideoDecision.ACCEPT
                        },
                    )
                }
            }
        val session = session(peer, monitor, callbacks)
        sessionReference.set(session)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        val executor = Executors.newSingleThreadExecutor()
        val delivery = executor.submit { peer.receive(videoConfigurationEnvelope(3)) }
        delivery.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(0, installs.get())
        assertEquals(1, peer.control.size)
    }

    @Test
    fun concurrentVideoConfigurationsFailClosedBeforeSecondDecoderInstall() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val configurationCallbacks = AtomicInteger(0)
        val pendingEffect = AtomicReference<ProductVideoConfigurationEffect>()
        val pendingCompletion = AtomicReference<(ProductVideoDecision) -> Unit>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    pendingEffect.set(effect)
                    pendingCompletion.set(completion)
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(videoConfigurationEnvelope(3))
        peer.receive(videoConfigurationEnvelope(4))
        pendingCompletion.get().invoke(
            pendingEffect.get().commit {
                configurationCallbacks.incrementAndGet()
                ProductVideoDecision.ACCEPT
            },
        )

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(0, configurationCallbacks.get())
        assertEquals(1, peer.control.size)
    }

    @Test
    fun freshCancelsPendingVideoEffectBeforeDecoderOrUiSideEffects() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val installs = AtomicInteger(0)
        val pendingEffect = AtomicReference<ProductVideoConfigurationEffect>()
        val pendingCompletion = AtomicReference<(ProductVideoDecision) -> Unit>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    pendingEffect.set(effect)
                    pendingCompletion.set(completion)
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        peer.receive(videoConfigurationEnvelope(3))

        monitor.available("cellular")
        pendingCompletion.get().invoke(
            pendingEffect.get().commit {
                installs.incrementAndGet()
                ProductVideoDecision.ACCEPT
            },
        )

        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertEquals(0, installs.get())
        assertEquals(1, peer.control.size)
    }

    @Test
    fun videoEffectIsOneShotAndAcceptedCompletionAcksOnce() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val installs = AtomicInteger(0)
        val pendingEffect = AtomicReference<ProductVideoConfigurationEffect>()
        val pendingCompletion = AtomicReference<(ProductVideoDecision) -> Unit>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    pendingEffect.set(effect)
                    pendingCompletion.set(completion)
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        peer.receive(videoConfigurationEnvelope(3))

        val first =
            pendingEffect.get().commit {
                installs.incrementAndGet()
                ProductVideoDecision.ACCEPT
            }
        val second =
            pendingEffect.get().commit {
                installs.incrementAndGet()
                ProductVideoDecision.ACCEPT
            }
        pendingCompletion.get().invoke(first)

        assertTrue(first.accepted)
        assertFalse(second.accepted)
        assertEquals(1, installs.get())
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, Envelope.parseFrom(peer.control.last()).payloadCase)
    }

    @Test
    fun committedVideoEffectWithoutCompletionTimesOutFailClosed() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val clock = ProductFakeClock(0)
        val installs = AtomicInteger(0)
        val pendingEffect = AtomicReference<ProductVideoConfigurationEffect>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    pendingEffect.set(effect)
                }
            }
        val session = session(peer, monitor, callbacks, clock = clock)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        peer.receive(videoConfigurationEnvelope(3))
        pendingEffect.get().commit {
            installs.incrementAndGet()
            ProductVideoDecision.ACCEPT
        }

        clock.now = 5_000
        session.tick()

        assertEquals(1, installs.get())
        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.control.size)
    }

    @Test
    fun closeFromRecoveringStateCallbackSuppressesFreshCallback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val sessionReference = AtomicReference<InternetProductSession>()
        val freshCallbacks = AtomicInteger(0)
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (state == InternetProductSessionState.RECOVERING) sessionReference.get().close()
                }

                override fun onFreshSessionRequired(reason: String) {
                    freshCallbacks.incrementAndGet()
                }
            }
        val session = session(peer, monitor, callbacks)
        sessionReference.set(session)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        monitor.available("cellular")

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(0, freshCallbacks.get())
    }

    @Test
    fun closeWaitsForAtomicStartTransactionThenReleasesResources() {
        val startEntered = CountDownLatch(1)
        val releaseStart = CountDownLatch(1)
        val peer =
            ProductFakePeerEngine(
                startHook = {
                    startEntered.countDown()
                    assertTrue(releaseStart.await(2, TimeUnit.SECONDS))
                },
            )
        val monitor = ProductFakeNetworkMonitor()
        val states = mutableListOf<InternetProductSessionState>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    states += state
                }
            }
        val session = session(peer, monitor, callbacks)

        val executor = Executors.newFixedThreadPool(2)
        val start = executor.submit { session.start() }
        assertTrue(startEntered.await(2, TimeUnit.SECONDS))
        val close = executor.submit { session.close() }
        assertFalse(close.isDone)
        releaseStart.countDown()
        start.get(2, TimeUnit.SECONDS)
        close.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(listOf(InternetProductSessionState.CONNECTING, InternetProductSessionState.CLOSED), states)
        assertEquals(1, peer.startCalls)
        assertEquals(1, peer.closeCalls)
        assertEquals(1, monitor.closeCalls)
    }

    @Test
    fun concurrentStartReservesIdleOnceAndDoesNotFailSuccessfulSession() {
        val startEntered = CountDownLatch(1)
        val releaseStart = CountDownLatch(1)
        val peer =
            ProductFakePeerEngine(
                startHook = {
                    startEntered.countDown()
                    assertTrue(releaseStart.await(2, TimeUnit.SECONDS))
                },
            )
        val session = session(peer, ProductFakeNetworkMonitor(), ProductCallbacks())
        val executor = Executors.newFixedThreadPool(2)
        val ready = CountDownLatch(2)
        val begin = CountDownLatch(1)
        val starts =
            List(2) {
                executor.submit {
                    ready.countDown()
                    begin.await()
                    session.start()
                }
            }
        assertTrue(ready.await(2, TimeUnit.SECONDS))
        begin.countDown()
        assertTrue(startEntered.await(2, TimeUnit.SECONDS))
        releaseStart.countDown()
        val failures =
            starts.mapNotNull { future ->
                try {
                    future.get(2, TimeUnit.SECONDS)
                    null
                } catch (failure: ExecutionException) {
                    failure.cause
                }
            }
        executor.shutdown()

        assertEquals(1, peer.startCalls)
        assertEquals(1, failures.size)
        assertTrue(failures.single() is IllegalStateException)
        assertEquals("Product session has already started", failures.single().message)
        assertEquals(InternetProductSessionState.CONNECTING, session.state)
    }

    @Test
    fun connectingCallbackCanCloseBeforeTransportStart() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val sessionReference = AtomicReference<InternetProductSession>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (state == InternetProductSessionState.CONNECTING) sessionReference.get().close()
                }
            }
        val session = session(peer, monitor, callbacks)
        sessionReference.set(session)

        session.start()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(0, peer.startCalls)
        assertEquals(1, peer.closeCalls)
        assertEquals(1, monitor.closeCalls)
    }

    @Test
    fun freshInvalidationAfterMediaDecodePreventsLateFrameDispatch() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val shouldBlock = AtomicBoolean(false)
        val decoded = CountDownLatch(1)
        val release = CountDownLatch(1)
        val session =
            session(
                peer,
                monitor,
                callbacks,
                testHooks =
                    InternetProductSessionTestHooks(
                        afterMediaDecodeBeforeCommit = {
                            if (shouldBlock.get()) {
                                decoded.countDown()
                                assertTrue(release.await(2, TimeUnit.SECONDS))
                            }
                        },
                    ),
            )
        activateWithVideo(session, peer, monitor)

        shouldBlock.set(true)
        val executor = Executors.newSingleThreadExecutor()
        val delivery = executor.submit { peer.media(media(frameId = 20, keyframe = true, payload = "late".toByteArray())) }
        assertTrue(decoded.await(2, TimeUnit.SECONDS))
        monitor.available("cellular")
        release.countDown()
        delivery.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertTrue(callbacks.frames.isEmpty())
    }

    @Test
    fun freshInvalidationBetweenMediaCommitAndDispatchGateDropsFrame() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val committed = CountDownLatch(1)
        val release = CountDownLatch(1)
        val session =
            session(
                peer,
                monitor,
                callbacks,
                testHooks =
                    InternetProductSessionTestHooks(
                        beforeMediaDispatchGate = {
                            committed.countDown()
                            assertTrue(release.await(2, TimeUnit.SECONDS))
                        },
                    ),
            )
        activateWithVideo(session, peer, monitor)

        val executor = Executors.newSingleThreadExecutor()
        val delivery = executor.submit { peer.media(media(frameId = 22, keyframe = true, payload = "late".toByteArray())) }
        assertTrue(committed.await(2, TimeUnit.SECONDS))
        monitor.available("cellular")
        release.countDown()
        delivery.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertTrue(callbacks.frames.isEmpty())
    }

    @Test
    fun failedAndClosedSessionsDropLateControlAndMediaWithoutSending() {
        listOf(InternetProductSessionState.FAILED, InternetProductSessionState.CLOSED).forEach { terminalState ->
            val peer = ProductFakePeerEngine()
            val monitor = ProductFakeNetworkMonitor()
            val callbacks = ProductCallbacks()
            val session = session(peer, monitor, callbacks)
            activateWithVideo(session, peer, monitor)
            val sentBeforeTerminal = peer.control.size

            if (terminalState == InternetProductSessionState.FAILED) {
                peer.observer.onFailure(IllegalStateException("transport failed"))
            } else {
                session.close()
            }
            peer.receive(controlEnvelope(4).setPing(Ping.newBuilder().setSequence(99)).build())
            peer.receive(controlEnvelope(5).setSessionAccepted(sessionAccepted()).build())
            peer.media(media(frameId = 21, keyframe = true, payload = "late".toByteArray()))

            assertEquals(terminalState, session.state)
            assertEquals(sentBeforeTerminal, peer.control.size)
            assertTrue(callbacks.frames.isEmpty())
        }
    }

    @Test
    fun failureThenLateConnectedAndRouteCallbacksCannotReviveNegotiation() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val clock = ProductFakeClock(0)
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, clock = clock)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)

        peer.observer.onFailure(IllegalStateException("candidate resolution failed"))
        peer.observer.onDisconnected()
        peer.observer.onConnected(PeerRoute.RELAY)
        peer.observer.onRouteChanged(PeerRoute.DIRECT)

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertFalse(session.sendTouch(ProductTouchEvent(11, 0, ProductInputPhase.BEGAN, 0.1, 0.2)))
        clock.now = 10_000
        session.tick()
        val payloads = peer.control.map { Envelope.parseFrom(it).payloadCase }
        assertEquals(1, payloads.count { it == Envelope.PayloadCase.CLIENT_HELLO })
        assertFalse(payloads.contains(Envelope.PayloadCase.TOUCH_EVENT))
        assertFalse(payloads.contains(Envelope.PayloadCase.PING))
    }

    @Test
    fun durablePendingRevocationAllowsCloseWhileTombstonePersistIsInFlight() {
        val persistEntered = CountDownLatch(1)
        val releasePersist = CountDownLatch(1)
        val store =
            ProductRevocationStore {
                persistEntered.countDown()
                assertTrue(releasePersist.await(2, TimeUnit.SECONDS))
            }
        val coordinator = InternetProductRevocationCoordinator()
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session =
            session(
                peer,
                monitor,
                callbacks,
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        activateWithVideo(session, peer, monitor)
        val sentBeforeRevocation = peer.control.size

        val executor = Executors.newFixedThreadPool(3)
        val revoke = executor.submit { peer.receive(revocationEnvelope(4)) }
        assertTrue(persistEntered.await(2, TimeUnit.SECONDS))
        assertFalse(store.revoked.get())
        assertFalse(session.sendTouch(ProductTouchEvent(30, 0, ProductInputPhase.BEGAN, 0.2, 0.3)))
        peer.receive(controlEnvelope(5).setPing(Ping.newBuilder().setSequence(30)).build())
        peer.media(media(frameId = 30, keyframe = true, payload = "revoked".toByteArray()))
        assertEquals(sentBeforeRevocation, peer.control.size)
        assertTrue(callbacks.frames.isEmpty())
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        }
        val close = executor.submit { session.close() }
        close.get(2, TimeUnit.SECONDS)
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        val fresh = executor.submit { monitor.available("cellular") }
        fresh.get(2, TimeUnit.SECONDS)
        assertTrue(callbacks.freshReasons.isEmpty())
        releasePersist.countDown()
        revoke.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertTrue(store.revoked.get())
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertTrue(callbacks.freshReasons.isEmpty())
        assertEquals(0, callbacks.states.count { it == InternetProductSessionState.FAILED })
    }

    @Test
    fun pendingRevocationPersistenceFailureRefusesTransportCloseFailClosed() {
        val store =
            ProductRevocationStore(
                beforePending = { throw IllegalStateException("pending storage unavailable") },
            )
        val coordinator = InternetProductRevocationCoordinator()
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                callbacks,
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(revocationEnvelope(3))

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
        assertThrows(PendingRevocationBarrierException::class.java) { session.close() }
        assertEquals(0, peer.closeCalls)
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        }
    }

    @Test
    fun pendingBarrierFailureSurvivesOwnerRecreationAndCanRetryToClose() {
        val storageAvailable = AtomicBoolean(false)
        val store =
            ProductRevocationStore(
                beforePending = {
                    check(storageAvailable.get()) { "pending storage unavailable" }
                },
            )
        val processCoordinator = InternetProductRevocationCoordinator()
        val peer = ProductFakePeerEngine()
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = processCoordinator,
                revocationStore = store,
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(revocationEnvelope(3))

        assertTrue(processCoordinator.hasActiveReservation())
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = processCoordinator,
                revocationStore = store,
            )
        }
        storageAvailable.set(true)
        assertEquals("user_revoked", session.retryPendingRevocationBarrier())
        assertFalse(processCoordinator.hasActiveReservation())
        assertTrue(store.revoked.get())
        assertFalse(store.pending.get())
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(1, peer.closeCalls)
    }

    @Test
    fun durableRevocationCommitWinsConcurrentCloseAndRemainsGloballyBlocked() {
        val persisted = CountDownLatch(1)
        val releaseCommit = CountDownLatch(1)
        val store = ProductRevocationStore()
        val coordinator = InternetProductRevocationCoordinator()
        val peer = ProductFakePeerEngine()
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                testHooks =
                    InternetProductSessionTestHooks(
                        afterRevocationPersistBeforeCommit = {
                            persisted.countDown()
                            assertTrue(releaseCommit.await(2, TimeUnit.SECONDS))
                        },
                    ),
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        val executor = Executors.newFixedThreadPool(2)
        val revoke = executor.submit { peer.receive(revocationEnvelope(3)) }
        assertTrue(persisted.await(2, TimeUnit.SECONDS))
        assertTrue(store.revoked.get())
        val close = executor.submit { session.close() }
        close.get(2, TimeUnit.SECONDS)
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        releaseCommit.countDown()
        revoke.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        }
    }

    @Test
    fun closeAfterRevocationStateCommitSuppressesLateFailedAndRevokedCallbacks() {
        val stateCommitted = CountDownLatch(1)
        val releaseCallback = CountDownLatch(1)
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val revocationEvents = mutableListOf<String>()
        callbacks.revocationEvents = revocationEvents
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                callbacks,
                testHooks =
                    InternetProductSessionTestHooks(
                        afterRevocationStateCommitBeforeCallback = {
                            stateCommitted.countDown()
                            assertTrue(releaseCallback.await(2, TimeUnit.SECONDS))
                        },
                    ),
                revocationStore = ProductRevocationStore(),
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        val executor = Executors.newSingleThreadExecutor()
        val revoke = executor.submit { peer.receive(revocationEnvelope(3)) }
        assertTrue(stateCommitted.await(2, TimeUnit.SECONDS))
        session.close()
        releaseCallback.countDown()
        revoke.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(0, callbacks.states.count { it == InternetProductSessionState.FAILED })
        assertTrue(revocationEvents.isEmpty())
    }

    @Test
    fun revocationStateCallbackFailureStillClosesTransportExactlyOnce() {
        val peer = ProductFakePeerEngine()
        val revokedCallbacks = AtomicInteger(0)
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (state == InternetProductSessionState.FAILED) throw IllegalStateException("state callback failed")
                }

                override fun onRevoked(reason: String) {
                    revokedCallbacks.incrementAndGet()
                }
            }
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                callbacks,
                revocationStore = ProductRevocationStore(),
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        val thrown = assertThrows(IllegalStateException::class.java) { peer.receive(revocationEnvelope(3)) }

        assertEquals("state callback failed", thrown.message)
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(0, revokedCallbacks.get())
        assertEquals(1, peer.closeCalls)
    }

    @Test
    fun persistsAuthenticatedRevocationBeforeCallbackAndClose() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val events = mutableListOf<String>()
        callbacks.revocationEvents = events
        val store =
            ProductRevocationStore {
                events += "persisted"
            }
        val session =
            session(peer, ProductFakeNetworkMonitor(), callbacks, revocationStore = store)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(
            controlEnvelope(3)
                .setDeviceRevoked(DeviceRevoked.newBuilder().setDeviceId("device-1").setReasonCode("user_revoked"))
                .build(),
        )

        assertEquals(listOf("persisted", "callback"), events)
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(1, peer.closeCalls)
    }

    @Test
    fun tombstoneFailureSurvivesRestartBlocksAdmissionAndRetriesSuccessfully() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val store = ProductRevocationStore().apply { failCompletionWith(IllegalStateException("disk unavailable")) }
        val coordinator = InternetProductRevocationCoordinator()
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                callbacks,
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(
            controlEnvelope(3)
                .setDeviceRevoked(DeviceRevoked.newBuilder().setDeviceId("device-1").setReasonCode("user_revoked"))
                .build(),
        )

        assertTrue(callbacks.revocationEvents.isNullOrEmpty())
        assertEquals(1, callbacks.failures.size)
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(1, peer.closeCalls)
        assertTrue(store.pending.get())
        assertFalse(store.revoked.get())
        assertFalse(coordinator.hasActiveReservation())
        assertTrue(coordinator.isCredentialMutationBlocked { store.isAdmissionBlocked("pair-1") })
        assertThrows(IllegalStateException::class.java) {
            coordinator.withCredentialMutationAdmission(
                durableBlock = { store.isAdmissionBlocked("different-pairing") },
            ) { error("A durable pending revocation must block pairing metadata replacement") }
        }

        val restartedStore = store.restarted()
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationStore = restartedStore,
            )
        }
        restartedStore.retryPending("pair-1", "user_revoked")
        assertFalse(restartedStore.pending.get())
        assertTrue(restartedStore.revoked.get())
        assertThrows(IllegalStateException::class.java) {
            session(
                ProductFakePeerEngine(),
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationStore = restartedStore,
            )
        }
    }

    @Test
    fun dialogOpenedBeforeDurableRevocationCannotCommitPairingAfterPendingAppears() {
        val coordinator = InternetProductRevocationCoordinator()
        val store = ProductRevocationStore().apply { failCompletionWith(IllegalStateException("disk unavailable")) }
        assertFalse(coordinator.isCredentialMutationBlocked { store.isAdmissionBlocked("pair-2") })
        val peer = ProductFakePeerEngine()
        val session =
            session(
                peer,
                ProductFakeNetworkMonitor(),
                ProductCallbacks(),
                revocationCoordinator = coordinator,
                revocationStore = store,
            )
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(revocationEnvelope(3))

        val pairingCommitted = AtomicBoolean(false)
        assertThrows(IllegalStateException::class.java) {
            coordinator.withCredentialMutationAdmission(
                durableBlock = { store.isAdmissionBlocked("pair-2") },
            ) {
                pairingCommitted.set(true)
            }
        }
        assertFalse(pairingCommitted.get())
        assertTrue(store.pending.get())
    }

    @Test
    fun pairingCommitAndRevocationReservationShareOneLinearizationGate() {
        val coordinator = InternetProductRevocationCoordinator()
        val commitEntered = CountDownLatch(1)
        val releaseCommit = CountDownLatch(1)
        val events = java.util.Collections.synchronizedList(mutableListOf<String>())
        val issuedPermit = AtomicReference<InternetProductCredentialMutationPermit?>()
        val executor = Executors.newFixedThreadPool(2)
        val commit =
            executor.submit {
                coordinator.withCredentialMutationAdmission(durableBlock = { false }) { permit ->
                    issuedPermit.set(permit)
                    permit.requireActive()
                    events += "commit-start"
                    commitEntered.countDown()
                    assertTrue(releaseCommit.await(2, TimeUnit.SECONDS))
                    events += "commit-end"
                }
            }
        assertTrue(commitEntered.await(2, TimeUnit.SECONDS))
        val reserve =
            executor.submit {
                coordinator.reserve("pair-linearized").also { events += "reserve" }
            }
        assertFalse(reserve.isDone)
        releaseCommit.countDown()
        commit.get(2, TimeUnit.SECONDS)
        reserve.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(listOf("commit-start", "commit-end", "reserve"), events)
        assertTrue(coordinator.hasActiveReservation())
        assertThrows(IllegalStateException::class.java) { requireNotNull(issuedPermit.get()).requireActive() }
    }

    @Test
    fun closeReleasesAllOwnersTransitionsClosedAndAggregatesFailures() {
        val monitorFailure = IllegalStateException("monitor close failed")
        val peerFailure = IllegalArgumentException("peer close failed")
        val peer = ProductFakePeerEngine(closeFailure = peerFailure)
        val monitor = ProductFakeNetworkMonitor(closeFailure = monitorFailure)
        val session = session(peer, monitor, ProductCallbacks())

        val thrown = assertThrows(IllegalStateException::class.java) { session.close() }
        session.close()

        assertEquals(monitorFailure, thrown)
        assertEquals(listOf(peerFailure), thrown.suppressed.toList())
        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(1, monitor.closeCalls)
        assertEquals(1, peer.closeCalls)
    }

    private fun session(
        peer: ProductFakePeerEngine,
        monitor: ProductFakeNetworkMonitor,
        callbacks: InternetProductSessionCallbacks,
        clock: ProductFakeClock = ProductFakeClock(0),
        testHooks: InternetProductSessionTestHooks = InternetProductSessionTestHooks(),
        revocationCoordinator: InternetProductRevocationCoordinator = InternetProductRevocationCoordinator(),
        revocationStore: InternetProductRevocationStore = ProductRevocationStore(),
    ) = InternetProductSession(
        lease = lease,
        configuration =
            PeerConfiguration(
                iceServers = lease.iceServers,
                sessionId = lease.signalingSessionId,
                sessionEpoch = lease.authoritativeSessionEpoch,
            ),
        peerEngine = peer,
        networkMonitor = monitor,
        clock = clock,
        codec = codec,
        callbacks = callbacks,
        revocationStore = revocationStore,
        revocationCoordinator = revocationCoordinator,
        testHooks = testHooks,
    )

    private fun activateWithVideo(
        session: InternetProductSession,
        peer: ProductFakePeerEngine,
        monitor: ProductFakeNetworkMonitor,
    ) {
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        peer.receive(videoConfigurationEnvelope(3))
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    private fun videoConfigurationEnvelope(messageId: Long): Envelope =
        controlEnvelope(messageId)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(3)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(5),
            ).build()

    private fun revocationEnvelope(messageId: Long): Envelope =
        controlEnvelope(messageId)
            .setDeviceRevoked(DeviceRevoked.newBuilder().setDeviceId("device-1").setReasonCode("user_revoked"))
            .build()

    private fun controlEnvelope(messageId: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(messageId)
            .setSessionId(ByteString.copyFrom(lease.protocolSessionId))
            .setSessionEpoch(lease.authoritativeSessionEpoch)

    private fun hostHello(): HostHello.Builder =
        HostHello
            .newBuilder()
            .setSelectedProtocol(1)
            .setHostId("host-1")
            .setHostName("Mac")
            .addAllCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
            .setResourceLimits(mediaRecordLimits())

    private fun sessionAccepted(): SessionAccepted.Builder =
        SessionAccepted
            .newBuilder()
            .setSessionId(ByteString.copyFrom(lease.protocolSessionId))
            .setSessionEpoch(lease.authoritativeSessionEpoch)
            .setHeartbeatIntervalMs(1_000)
            .addAllNegotiatedCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)
            .setNegotiatedResourceLimits(mediaRecordLimits())

    private fun mediaRecordLimits(
        maximumEncryptedMediaRecordBytes: Int = InternetMediaRecordContract.MAXIMUM_ENCRYPTED_RECORD_BYTES,
    ): ResourceLimits.Builder =
        ResourceLimits
            .newBuilder()
            .setMaximumEncryptedMediaRecordBytes(maximumEncryptedMediaRecordBytes)

    private fun media(
        frameId: Long,
        keyframe: Boolean,
        payload: ByteArray,
        fragmentIndex: Int = 0,
        fragmentCount: Int = 1,
    ): ByteArray =
        ProtobufProtocolV1ProductCodec.encodeMediaFragment(
            MediaPacketHeader
                .newBuilder()
                .setStreamId(5)
                .setSessionEpoch(7)
                .setConfigEpoch(3)
                .setFrameId(frameId)
                .setFragmentIndex(fragmentIndex)
                .setFragmentCount(fragmentCount)
                .setCaptureTimestampNs(frameId * 100)
                .setKeyframe(keyframe)
                .setCodec(Codec.CODEC_HEVC)
                .setPayloadLength(payload.size)
                .build(),
            payload,
        )

    private fun mediaRecordWithExactSize(targetBytes: Int): ByteArray {
        require(targetBytes in 2..InternetMediaRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES)
        var payloadBytes = targetBytes
        repeat(8) {
            val record = media(frameId = 1, keyframe = true, payload = ByteArray(payloadBytes))
            if (record.size == targetBytes) return record
            payloadBytes += targetBytes - record.size
            require(payloadBytes > 0) { "Target media record size cannot contain a valid payload" }
        }
        error("Could not construct a media record with exactly $targetBytes bytes")
    }
}

private class ProductFakeClock(var now: Long) : MonotonicClock {
    override fun nowMillis(): Long = now
}

private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

private class ProductRevocationStore(
    private val backing: ProductRevocationBacking = ProductRevocationBacking(),
    private val beforePending: () -> Unit = {},
    private val beforeComplete: () -> Unit = {},
) : InternetProductRevocationStore {
    private val completionFailure = AtomicReference<Throwable?>()
    val revoked: AtomicBoolean get() = backing.revoked
    val pending: AtomicBoolean get() = backing.pending

    override fun persistPendingAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
        beforePending()
        backing.pending.set(true)
    }

    override fun persistAuthenticatedRevocation(pairingIdentifier: String, reason: String) {
        beforeComplete()
        completionFailure.get()?.let { throw it }
        check(backing.pending.get()) { "pending revocation is required" }
        backing.revoked.set(true)
        backing.pending.set(false)
    }

    override fun isAdmissionBlocked(pairingIdentifier: String): Boolean = backing.pending.get() || backing.revoked.get()

    fun failCompletionWith(failure: Throwable) {
        completionFailure.set(failure)
    }

    fun allowCompletion() {
        completionFailure.set(null)
    }

    fun restarted(): ProductRevocationStore = ProductRevocationStore(backing = backing)

    fun retryPending(pairingIdentifier: String, reason: String) {
        persistAuthenticatedRevocation(pairingIdentifier, reason)
    }
}

private class ProductRevocationBacking {
    val pending = AtomicBoolean(false)
    val revoked = AtomicBoolean(false)
}

private class ProductCallbacks : InternetProductSessionCallbacks {
    val states = java.util.concurrent.CopyOnWriteArrayList<InternetProductSessionState>()
    val frames = mutableListOf<ProductVideoFrame>()
    val configurations = mutableListOf<ProductVideoConfiguration>()
    val freshReasons = mutableListOf<String>()
    val failures = mutableListOf<Throwable>()
    val routes = java.util.concurrent.CopyOnWriteArrayList<PeerRoute>()
    var revocationEvents: MutableList<String>? = null
    override fun onStateChanged(state: InternetProductSessionState) { states += state }
    override fun onVideoConfiguration(
        configuration: ProductVideoConfiguration,
        effect: ProductVideoConfigurationEffect,
        completion: (ProductVideoDecision) -> Unit,
    ) {
        completion(
            effect.commit {
                configurations += configuration
                ProductVideoDecision.ACCEPT
            },
        )
    }
    override fun onVideoFrame(frame: ProductVideoFrame) { frames += frame }
    override fun onFreshSessionRequired(reason: String) { freshReasons += reason }
    override fun onFailure(error: Throwable) { failures += error }
    override fun onRouteSelected(route: PeerRoute) { routes += route }
    override fun onRevoked(reason: String) { revocationEvents?.add("callback") }
}

private class ProductFakeNetworkMonitor(
    private val closeFailure: Throwable? = null,
) : NetworkMonitor {
    lateinit var listener: NetworkMonitor.Listener
    var closeCalls = 0
    override fun start(listener: NetworkMonitor.Listener) { this.listener = listener }
    fun available(id: String) = listener.onAvailable(NetworkSnapshot(id, true, false, setOf(NetworkTransport.WIFI)))
    override fun close() {
        closeCalls++
        closeFailure?.let { throw it }
    }
}

private class ProductFakePeerEngine(
    private val closeFailure: Throwable? = null,
    private val startHook: () -> Unit = {},
) : WebRtcPeerEngine {
    override val controlSemantics = DataChannelSemantics.RELIABLE_CONTROL
    override val mediaSemantics = DataChannelSemantics.LATEST_MEDIA
    lateinit var observer: WebRtcPeerEngine.Observer
    val control = mutableListOf<ByteArray>()
    var startCalls = 0
    var restartCalls = 0
    var closeCalls = 0
    override fun start(configuration: PeerConfiguration, observer: WebRtcPeerEngine.Observer) {
        startCalls++
        this.observer = observer
        startHook()
    }
    override fun sendControl(payload: ByteArray): Boolean = control.add(payload)
    override fun sendMedia(frame: OutboundMediaFrame): Boolean = true
    override fun restartIce() { restartCalls++ }
    override fun applyVideoProfile(profile: VideoProfile) = Unit
    override fun close() {
        closeCalls++
        closeFailure?.let { throw it }
    }
    fun receive(envelope: Envelope) = observer.onControlMessage(7, envelope.toByteArray())
    fun media(payload: ByteArray) = observer.onMediaPacket(7, payload)

    fun keyframeRequests(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.REQUEST_KEYFRAME }
}
