package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DeviceRevoked
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.MediaPacketHeader
import dev.vibescreen.protocol.v1.Ping
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class InternetProductSessionTest {
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
            transcriptContext = ByteArray(32),
            iceServers = listOf(IceServer(listOf("stun:stun.example.test:3478"))),
            signaling = signaling,
            pinnedHostId = "host-1",
        )
    private val codec = ProtobufProtocolV1ProductCodec("device-1", "Android", setOf(ProductVideoCodec.HEVC)) { 1 }

    @Test
    fun boundTranscriptContextMatchesSwiftKnownAnswer() {
        val context =
            lease
                .copy(
                    signalingSessionId = "session-1",
                    authoritativeSessionEpoch = 7,
                    pinnedHostId = "host-1",
                    transcriptContext = ByteArray(32) { it.toByte() },
                ).boundTranscriptContext("device-1")

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
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(configuration: ProductVideoConfiguration): ProductVideoDecision {
                    sessionReference.get().close()
                    return ProductVideoDecision.ACCEPT
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
        assertEquals(1, peer.control.size)
    }

    @Test
    fun concurrentVideoConfigurationsFailClosedBeforeSecondDecoderInstall() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbackEntered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val configurationCallbacks = AtomicInteger(0)
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onVideoConfiguration(configuration: ProductVideoConfiguration): ProductVideoDecision {
                    configurationCallbacks.incrementAndGet()
                    callbackEntered.countDown()
                    assertTrue(release.await(2, TimeUnit.SECONDS))
                    return ProductVideoDecision.ACCEPT
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        val executor = Executors.newSingleThreadExecutor()
        val first = executor.submit { peer.receive(videoConfigurationEnvelope(3)) }
        assertTrue(callbackEntered.await(2, TimeUnit.SECONDS))
        peer.receive(videoConfigurationEnvelope(4))
        release.countDown()
        first.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, configurationCallbacks.get())
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
    fun closeBetweenStateCommitAndDispatchGateSuppressesConnectingAndStart() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val committed = CountDownLatch(1)
        val release = CountDownLatch(1)
        val states = mutableListOf<InternetProductSessionState>()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    states += state
                }
            }
        val session =
            session(
                peer,
                monitor,
                callbacks,
                testHooks =
                    InternetProductSessionTestHooks(
                        afterStateCommitBeforeDispatchGate = { state ->
                            if (state == InternetProductSessionState.CONNECTING) {
                                committed.countDown()
                                assertTrue(release.await(2, TimeUnit.SECONDS))
                            }
                        },
                    ),
            )

        val executor = Executors.newSingleThreadExecutor()
        val start = executor.submit { session.start() }
        assertTrue(committed.await(2, TimeUnit.SECONDS))
        session.close()
        release.countDown()
        start.get(2, TimeUnit.SECONDS)
        executor.shutdown()

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertFalse(states.contains(InternetProductSessionState.CONNECTING))
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
    fun persistsAuthenticatedRevocationBeforeCallbackAndClose() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val events = mutableListOf<String>()
        callbacks.revocationEvents = events
        val session =
            session(peer, ProductFakeNetworkMonitor(), callbacks) { pairingIdentifier, reason ->
                assertEquals("pair-1", pairingIdentifier)
                assertEquals("user_revoked", reason)
                events += "persisted"
            }
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
    fun closesWithoutRevocationCallbackWhenTombstonePersistenceFails() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session =
            session(peer, ProductFakeNetworkMonitor(), callbacks) { _, _ ->
                throw IllegalStateException("disk unavailable")
            }
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
        revocationStore: InternetProductRevocationStore = InternetProductRevocationStore { _, _ -> },
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

    private fun sessionAccepted(): SessionAccepted.Builder =
        SessionAccepted
            .newBuilder()
            .setSessionId(ByteString.copyFrom(lease.protocolSessionId))
            .setSessionEpoch(lease.authoritativeSessionEpoch)
            .setHeartbeatIntervalMs(1_000)
            .addAllNegotiatedCapabilities(ProtobufProtocolV1ProductCodec.REQUIRED_CLIENT_CAPABILITIES)

    private fun media(frameId: Long, keyframe: Boolean, payload: ByteArray): ByteArray =
        ProtobufProtocolV1ProductCodec.encodeMediaFragment(
            MediaPacketHeader
                .newBuilder()
                .setStreamId(5)
                .setSessionEpoch(7)
                .setConfigEpoch(3)
                .setFrameId(frameId)
                .setFragmentCount(1)
                .setCaptureTimestampNs(frameId * 100)
                .setKeyframe(keyframe)
                .setCodec(Codec.CODEC_HEVC)
                .setPayloadLength(payload.size)
                .build(),
            payload,
        )
}

private class ProductFakeClock(var now: Long) : MonotonicClock {
    override fun nowMillis(): Long = now
}

private fun String.hex(): ByteArray = chunked(2).map { it.toInt(16).toByte() }.toByteArray()

private class ProductCallbacks : InternetProductSessionCallbacks {
    val frames = mutableListOf<ProductVideoFrame>()
    val configurations = mutableListOf<ProductVideoConfiguration>()
    val freshReasons = mutableListOf<String>()
    val failures = mutableListOf<Throwable>()
    val routes = java.util.concurrent.CopyOnWriteArrayList<PeerRoute>()
    var revocationEvents: MutableList<String>? = null
    override fun onVideoConfiguration(configuration: ProductVideoConfiguration): ProductVideoDecision {
        configurations += configuration
        return ProductVideoDecision.ACCEPT
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
) : WebRtcPeerEngine {
    override val controlSemantics = DataChannelSemantics.RELIABLE_CONTROL
    override val mediaSemantics = DataChannelSemantics.LATEST_MEDIA
    lateinit var observer: WebRtcPeerEngine.Observer
    val control = mutableListOf<ByteArray>()
    var restartCalls = 0
    var closeCalls = 0
    override fun start(configuration: PeerConfiguration, observer: WebRtcPeerEngine.Observer) { this.observer = observer }
    override fun sendControl(payload: ByteArray): Boolean = control.add(payload)
    override fun sendMedia(payload: ByteArray): Boolean = true
    override fun restartIce() { restartCalls++ }
    override fun applyVideoProfile(profile: VideoProfile) = Unit
    override fun close() {
        closeCalls++
        closeFailure?.let { throw it }
    }
    fun receive(envelope: Envelope) = observer.onControlMessage(7, envelope.toByteArray())
    fun media(payload: ByteArray) = observer.onMediaPacket(7, payload)
}
