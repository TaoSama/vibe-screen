package dev.telemachus.display.internet

import com.google.protobuf.ByteString
import com.google.protobuf.CodedOutputStream
import dev.telemachus.display.ClipboardContentData
import dev.telemachus.display.ClipboardOfferData
import dev.telemachus.display.ControllerAxes
import dev.telemachus.display.CONTROLLER_CONNECTION_ACK_TIMEOUT_MS
import dev.telemachus.display.ControllerEventKind
import dev.telemachus.display.ControllerStateSample
import dev.telemachus.display.STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.sha256
import dev.telemachus.display.internet.security.InternetPairingIdentity
import dev.telemachus.display.internet.security.generateEphemeral
import dev.telemachus.display.internet.security.pairingSha256
import dev.telemachus.display.internet.security.publicPoint
import dev.telemachus.display.internet.security.toPairingHex
import dev.vibescreen.protocol.v1.AudioCodec
import dev.vibescreen.protocol.v1.AudioConfig
import dev.vibescreen.protocol.v1.AudioPacketHeader
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.ClipboardContent
import dev.vibescreen.protocol.v1.ClipboardOffer
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.DeviceRevoked
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputAck
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
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
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import java.security.SecureRandom

class InternetProductSessionTest {
    @Test
    fun inputAckWithoutNegotiatedControllerFailsClosed() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(
            controlEnvelope(3)
                .setInputAck(InputAck.newBuilder().setInputId(1).setAccepted(true))
                .build(),
        )

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.closeCalls)
        assertEquals(
            "Controller input acknowledgement arrived without a negotiated controller session",
            callbacks.failures.single().message,
        )
    }

    @Test
    fun negotiatedControllerInputAckWithoutSenderIsNoOp() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val controllerCodec =
            ProtobufProtocolV1ProductCodec(
                localDeviceId = "device-1",
                deviceName = "Android",
                supportedCodecs = setOf(ProductVideoCodec.HEVC),
                advertiseController = true,
                monotonicNanos = { 1 },
            )
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks, codec = controllerCodec)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(
            controlEnvelope(1)
                .setHostHello(hostHello().addCapabilities(Capability.CAPABILITY_CONTROLLER))
                .build(),
        )
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(
                    sessionAccepted().addNegotiatedCapabilities(Capability.CAPABILITY_CONTROLLER),
                ).build(),
        )
        val sentBeforeAck = peer.control.size

        peer.receive(
            controlEnvelope(3)
                .setInputAck(InputAck.newBuilder().setInputId(1).setAccepted(true))
                .build(),
        )
        peer.receive(controlEnvelope(4).setPing(Ping.newBuilder().setSequence(99)).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(0, peer.closeCalls)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(sentBeforeAck + 1, peer.control.size)
        val pong = Envelope.parseFrom(peer.control.last())
        assertEquals(Envelope.PayloadCase.PONG, pong.payloadCase)
        assertEquals(4L, pong.correlationId)
        assertEquals(99L, pong.pong.sequence)
    }

    @Test
    fun structuralHevcRejectionIsSentBeforeOwnerFailsAndCloses() {
        val events = mutableListOf<String>()
        val peer =
            ProductFakePeerEngine(
                sendControlHook = { payload ->
                    val envelope = Envelope.parseFrom(payload)
                    if (envelope.payloadCase == Envelope.PayloadCase.VIDEO_CONFIG_RESULT) {
                        events += "rejection_sent"
                    }
                },
            )
        val monitor = ProductFakeNetworkMonitor()
        val callbacks =
            object : InternetProductSessionCallbacks {
                override fun onStateChanged(state: InternetProductSessionState) {
                    if (state == InternetProductSessionState.FAILED) events += "session_failed"
                }

                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    completion(ProductVideoDecision.reject(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON))
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(videoConfigurationEnvelope(3))

        val result = Envelope.parseFrom(peer.control.last()).videoConfigResult
        assertFalse(result.accepted)
        assertEquals(STRUCTURAL_HEVC_TARGET_UNSUPPORTED_REASON, result.rejectionReason)
        assertEquals(listOf("rejection_sent", "session_failed"), events)
        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.closeCalls)
    }

    @Test
    fun hostWithoutInputCapabilitiesStillNegotiatesVideo() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertFalse(session.canSendStylus())
        assertFalse(session.canSendTouch())
        val controlCount = peer.control.size
        assertFalse(session.sendTouch(ProductTouchEvent(1, 0, ProductInputPhase.BEGAN, 0.5, 0.5)))
        assertEquals(controlCount, peer.control.size)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        peer.receive(
            controlEnvelope(3)
                .setVideoConfig(
                    VideoConfig.newBuilder()
                        .setConfigEpoch(3)
                        .setCodec(Codec.CODEC_HEVC)
                        .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                        .setFramesPerSecond(60)
                        .setBitrateKbps(12_000)
                        .setStreamId(5),
                ).build(),
        )
        assertEquals(Envelope.PayloadCase.VIDEO_CONFIG_RESULT, Envelope.parseFrom(peer.control.last()).payloadCase)
        assertEquals(1, callbacks.configurations.size)
    }

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
    private val controllerCodec =
        ProtobufProtocolV1ProductCodec(
            localDeviceId = "device-1",
            deviceName = "Android",
            supportedCodecs = setOf(ProductVideoCodec.HEVC),
            advertiseController = true,
            monotonicNanos = { 1 },
        )
    private val audioCodec =
        ProtobufProtocolV1ProductCodec(
            localDeviceId = "device-1",
            deviceName = "Android",
            supportedCodecs = setOf(ProductVideoCodec.HEVC),
            advertiseAudio = true,
            monotonicNanos = { 1 },
        )

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
    fun negotiatesVideoDeliversKeyframeAndRequestsFreshSessionOnNetworkHandoff() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)

        assertEquals(Envelope.PayloadCase.CLIENT_HELLO, Envelope.parseFrom(peer.control.single()).payloadCase)
        peer.receive(
            controlEnvelope(1)
                .setHostHello(
                    hostHello()
                        .addCapabilities(Capability.CAPABILITY_TOUCH)
                        .addCapabilities(Capability.CAPABILITY_STYLUS),
                ).build(),
        )
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(
                    sessionAccepted()
                        .addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH)
                        .addNegotiatedCapabilities(Capability.CAPABILITY_STYLUS),
                )
                .build(),
        )
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertFalse(session.canSendStylus())
        assertTrue(session.canSendTouch())

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
        assertTrue(session.canSendStylus())
        assertTrue(
            session.sendStylus(
                ProductStylusEvent(2, 7, ProductInputPhase.CHANGED, 0.25, 0.75, 0.6, 30.0, -40.0),
            ),
        )
        val stylusEnvelope = Envelope.parseFrom(peer.control.last())
        assertEquals(Envelope.PayloadCase.STYLUS_EVENT, stylusEnvelope.payloadCase)
        assertEquals(5L, stylusEnvelope.stylusEvent.target.streamId)
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
    fun internetMediaAssemblerPreservesAnnexBHevcFramesForDecoderCallback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)

        val keyframePayload = byteArrayOf(0, 0, 0, 1, 0x40, 0, 0, 0, 1, 0x26, 0x01)
        val deltaPayload = byteArrayOf(0, 0, 0, 1, 0x02, 0x7f, 0x55)

        peer.media(media(frameId = 100, keyframe = true, payload = keyframePayload))
        peer.media(media(frameId = 101, keyframe = false, payload = deltaPayload))

        assertEquals(2, callbacks.frames.size)
        callbacks.frames[0].also { frame ->
            assertTrue(frame.keyframe)
            assertEquals(ProductVideoCodec.HEVC, frame.codec)
            assertEquals(7L, frame.sessionEpoch)
            assertEquals(3L, frame.configEpoch)
            assertEquals(5L, frame.streamId)
            assertEquals(10_000L, frame.captureTimestampNs)
            assertArrayEquals(keyframePayload, frame.payload)
        }
        callbacks.frames[1].also { frame ->
            assertFalse(frame.keyframe)
            assertEquals(ProductVideoCodec.HEVC, frame.codec)
            assertEquals(7L, frame.sessionEpoch)
            assertEquals(3L, frame.configEpoch)
            assertEquals(5L, frame.streamId)
            assertEquals(10_100L, frame.captureTimestampNs)
            assertArrayEquals(deltaPayload, frame.payload)
        }
    }

    @Test
    fun controllerOptInNegotiatesTheCapabilityAdvertisedByThisCodecInstance() {
        val peer = ProductFakePeerEngine()
        val callbacks = ProductCallbacks()
        val session = session(peer, ProductFakeNetworkMonitor(), callbacks, codec = controllerCodec)
        session.start()
        peer.observer.onConnected(PeerRoute.DIRECT)

        val clientHello = Envelope.parseFrom(peer.control.single()).clientHello
        assertTrue(clientHello.capabilitiesList.contains(Capability.CAPABILITY_CONTROLLER))
        peer.receive(
            controlEnvelope(1)
                .setHostHello(hostHello().addCapabilities(Capability.CAPABILITY_CONTROLLER))
                .build(),
        )
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(
                    sessionAccepted().addNegotiatedCapabilities(Capability.CAPABILITY_CONTROLLER),
                ).build(),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun controllerEventsSendAfterNegotiatedControllerAndVideoConfiguration() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        val accepted =
            session.sendController(
                listOf(
                    ProductControllerEvent(
                        inputId = 11,
                        sample =
                            controllerSample(
                                kind = ControllerEventKind.STATE,
                                buttonMask = 0b101,
                                axes = ControllerAxes(leftX = 0.25, rightTrigger = 0.75),
                            ),
                    ),
                ),
                InternetControllerSendQueue.Delivery.ANALOG,
            )

        val controller = peer.controllerEvents().single().controllerEvent
        assertTrue(accepted)
        assertTrue(session.hasNegotiatedControllerCapability())
        assertTrue(session.canSendController())
        assertEquals(11L, controller.inputId)
        assertEquals(5L, controller.target.streamId)
        assertEquals("pad-1", controller.controllerId)
        assertEquals(3L, controller.controllerEpoch)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, controller.kind)
        assertEquals(0b101, controller.buttonMask)
        assertEquals(0.25, controller.leftStickX, 0.0)
        assertEquals(0.75, controller.rightTrigger, 0.0)
        assertEquals(callbacks.configurations, callbacks.appliedConfigurations)
    }

    @Test
    fun controllerConnectSkipsStateForPendingConnectionUntilHostAccepts() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED)),
                    ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 1)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val beforeAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, beforeAck.size)
        assertEquals(21L, beforeAck.single().inputId)
        assertEquals(
            dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            beforeAck.single().kind,
        )

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(1, peer.controllerEvents().size)
        assertEquals(listOf(ProductInputAckCallback(21, "pad-1", 3, accepted = true, "")), callbacks.inputAcks)
    }

    @Test
    fun controllerDisconnectDuringPendingConnectionWaitsForAcceptedAckThenSendsOneCleanup() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val nextControllerInputId = monotonicControllerInputIds(24)
        val session = session(peer, monitor, callbacks, codec = controllerCodec, nextControllerInputId = nextControllerInputId)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.STATE)),
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.DISCONNECTED)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val beforeAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, beforeAck.size)
        assertEquals(21L, beforeAck.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, beforeAck.single().kind)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        val afterAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(2, afterAck.size)
        assertEquals(21L, afterAck[0].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, afterAck[0].kind)
        assertEquals(24L, afterAck[1].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, afterAck[1].kind)
        assertEquals("pad-1", afterAck[1].controllerId)
        assertEquals(3L, afterAck[1].controllerEpoch)
        assertEquals(listOf(ProductInputAckCallback(21, "pad-1", 3, accepted = true, "")), callbacks.inputAcks)

        peer.receive(
            controlEnvelope(5)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )
        assertEquals(2, peer.controllerEvents().size)
    }

    @Test
    fun controllerDisconnectDuringRejectedPendingConnectionDoesNotSendCleanup() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.DISCONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertEquals(1, peer.controllerEvents().size)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(21)
                        .setAccepted(false)
                        .setRejectionReason("maximum_active_controllers_exceeded"),
                ).build(),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(1, peer.controllerEvents().size)
        assertEquals(
            listOf(ProductInputAckCallback(21, "pad-1", 3, accepted = false, "maximum_active_controllers_exceeded")),
            callbacks.inputAcks,
        )
    }

    @Test
    fun reconnectedControllerEpochWaitsForPendingDisconnectCleanup() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val nextControllerInputId = monotonicControllerInputIds(22)
        val session = session(peer, monitor, callbacks, codec = controllerCodec, nextControllerInputId = nextControllerInputId)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 3))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.DISCONNECTED, controllerEpoch = 3)),
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 4)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertEquals(1, peer.controllerEvents().size)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        val controllers = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(3, controllers.size)
        assertEquals(21L, controllers[0].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, controllers[0].kind)
        assertEquals(3L, controllers[0].controllerEpoch)
        assertEquals(22L, controllers[1].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, controllers[1].kind)
        assertEquals(3L, controllers[1].controllerEpoch)
        assertEquals(23L, controllers[2].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, controllers[2].kind)
        assertEquals(4L, controllers[2].controllerEpoch)
        assertEquals(listOf(ProductInputAckCallback(21, "pad-1", 3, accepted = true, "")), callbacks.inputAcks)
    }

    @Test
    fun sameBatchReconnectBeforeOlderDisconnectIsRepairedAfterInputIdsAreAssigned() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val nextControllerInputId = monotonicControllerInputIds(22)
        val session = session(peer, monitor, callbacks, codec = controllerCodec, nextControllerInputId = nextControllerInputId)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 3))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 4)),
                    ProductControllerEvent(controllerSample(kind = ControllerEventKind.DISCONNECTED, controllerEpoch = 3)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val beforeAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, beforeAck.size)
        assertEquals(21L, beforeAck.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, beforeAck.single().kind)
        assertEquals(3L, beforeAck.single().controllerEpoch)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        val afterAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(3, afterAck.size)
        assertEquals(listOf(21L, 22L, 23L), afterAck.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            afterAck.map { it.kind },
        )
        assertEquals(listOf(3L, 3L, 4L), afterAck.map { it.controllerEpoch })
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun sameBatchReconnectAfterAcknowledgedDisconnectReordersEventsWithoutSwappingExplicitInputIds() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 3))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )
        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(23, controllerSample(kind = ControllerEventKind.CONNECTED, controllerEpoch = 4)),
                    ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.DISCONNECTED, controllerEpoch = 3)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val controllers = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(3, controllers.size)
        assertEquals(listOf(21L, 22L, 23L), controllers.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            controllers.map { it.kind },
        )
        assertEquals(listOf(3L, 3L, 4L), controllers.map { it.controllerEpoch })
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun sameBatchStateBeforeSameEpochConnectedWaitsForAckResync() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 9)),
                    ProductControllerEvent(32, controllerSample(kind = ControllerEventKind.CONNECTED)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val connectedOnly = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, connectedOnly.size)
        assertEquals(32L, connectedOnly.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, connectedOnly.single().kind)
        assertEquals(0, connectedOnly.single().buttonMask)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(32).setAccepted(true))
                .build(),
        )
        assertEquals(listOf(ProductInputAckCallback(32, "pad-1", 3, accepted = true, "")), callbacks.inputAcks)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(33, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 9))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        val afterResync = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(listOf(32L, 33L), afterResync.map { it.inputId })
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, afterResync.last().kind)
        assertEquals(9, afterResync.last().buttonMask)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun sameBatchDisconnectBeforeSameEpochConnectedWaitsForAcceptedConnection() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val nextControllerInputId = monotonicControllerInputIds(33)
        val session = session(peer, monitor, callbacks, codec = controllerCodec, nextControllerInputId = nextControllerInputId)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.DISCONNECTED)),
                    ProductControllerEvent(32, controllerSample(kind = ControllerEventKind.CONNECTED)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val connectedOnly = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, connectedOnly.size)
        assertEquals(32L, connectedOnly.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, connectedOnly.single().kind)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(32).setAccepted(true))
                .build(),
        )

        val afterAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(listOf(32L, 33L), afterAck.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
            ),
            afterAck.map { it.kind },
        )
        assertEquals(listOf(3L, 3L), afterAck.map { it.controllerEpoch })
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun duplicateConnectedInSameBatchIsConsumedWhilePending() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.CONNECTED)),
                    ProductControllerEvent(32, controllerSample(kind = ControllerEventKind.CONNECTED)),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val sent = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, sent.size)
        assertEquals(31L, sent.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, sent.single().kind)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun duplicateConnectedInLaterPendingBatchIsConsumedEvenWhenInputIdIsReused() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val sent = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, sent.size)
        assertEquals(31L, sent.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, sent.single().kind)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun deferredDisconnectDoesNotBlockOtherControllerAndUsesActualSendOrderInputIds() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val nextControllerInputId = monotonicControllerInputIds(24)
        val session = session(peer, monitor, callbacks, codec = controllerCodec, nextControllerInputId = nextControllerInputId)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED, controllerId = "pad-1"))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(controllerSample(kind = ControllerEventKind.DISCONNECTED, controllerId = "pad-1"))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(23, controllerSample(kind = ControllerEventKind.CONNECTED, controllerId = "pad-2"))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        val beforeAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(2, beforeAck.size)
        assertEquals(listOf(21L, 23L), beforeAck.map { it.inputId })
        assertEquals(listOf("pad-1", "pad-2"), beforeAck.map { it.controllerId })

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        val controllers = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(3, controllers.size)
        assertEquals(listOf(21L, 23L, 24L), controllers.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
            ),
            controllers.map { it.kind },
        )
        assertEquals(listOf("pad-1", "pad-2", "pad-1"), controllers.map { it.controllerId })
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun tickExpiresPendingControllerConnectionWithoutNewInputAndLateAckIsNoOp() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val clock = ProductFakeClock(0)
        val nextControllerInputId = monotonicControllerInputIds(22)
        val session = session(
            peer,
            monitor,
            callbacks,
            clock = clock,
            codec = controllerCodec,
            nextControllerInputId = nextControllerInputId,
        )
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(controllerSample(kind = ControllerEventKind.DISCONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertEquals(1, peer.controllerEvents().size)

        clock.now = CONTROLLER_CONNECTION_ACK_TIMEOUT_MS - 1
        session.tick()
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(0, peer.closeCalls)
        assertEquals(1, peer.controllerEvents().size)

        clock.now = CONTROLLER_CONNECTION_ACK_TIMEOUT_MS
        session.tick()
        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.closeCalls)
        assertEquals("Controller input acknowledgement timed out", callbacks.failures.single().message)
        assertEquals(1, peer.controllerEvents().size)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )
        assertTrue(callbacks.inputAcks.isEmpty())
        assertEquals(1, peer.controllerEvents().size)
    }

    @Test
    fun staleControllerAckDoesNotFlushPendingDisconnectCleanup() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.DISCONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertEquals(1, peer.controllerEvents().size)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(99).setAccepted(true))
                .build(),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(1, peer.controllerEvents().size)
        assertEquals(listOf(ProductInputAckCallback(99, null, null, accepted = true, "")), callbacks.inputAcks)
    }

    @Test
    fun controllerDisconnectCleanupIsClearedWhenSessionClosesBeforeAck() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.DISCONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        session.close()
        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )

        assertEquals(InternetProductSessionState.CLOSED, session.state)
        assertEquals(1, peer.controllerEvents().size)
        assertTrue(callbacks.inputAcks.isEmpty())
    }

    @Test
    fun pendingConnectionDoesNotBlockStateForAcceptedController() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED, controllerId = "pad-1"))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(21).setAccepted(true))
                .build(),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(22, controllerSample(kind = ControllerEventKind.CONNECTED, controllerId = "pad-2"))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(
                    ProductControllerEvent(23, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 1, controllerId = "pad-2")),
                    ProductControllerEvent(24, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 2, controllerId = "pad-1")),
                ),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        val controllers = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(3, controllers.size)
        assertEquals(21L, controllers[0].inputId)
        assertEquals(22L, controllers[1].inputId)
        assertEquals(24L, controllers[2].inputId)
        assertEquals("pad-1", controllers[2].controllerId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, controllers[2].kind)
        assertEquals(2, controllers[2].buttonMask)
    }

    @Test
    fun controllerInputAckReportsRejectedConnectedSampleWithoutClosingSession() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(21, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        peer.receive(
            controlEnvelope(4)
                .setInputAck(
                    InputAck
                        .newBuilder()
                        .setInputId(21)
                        .setAccepted(false)
                        .setRejectionReason("maximum_active_controllers_exceeded"),
                ).build(),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(
            listOf(ProductInputAckCallback(21, "pad-1", 3, accepted = false, "maximum_active_controllers_exceeded")),
            callbacks.inputAcks,
        )
    }

    @Test
    fun controllerStructuralQueuesDuringRecoveringAndDrainsAfterTransportResumes() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)
        val controlCountBeforeRecovery = peer.control.size

        peer.observer.onDisconnected()
        assertEquals(InternetProductSessionState.RECOVERING, session.state)

        assertFalse(
            session.sendController(
                listOf(ProductControllerEvent(31, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 1))),
                InternetControllerSendQueue.Delivery.ANALOG,
            ),
        )
        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(32, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )
        assertEquals(controlCountBeforeRecovery, peer.control.size)

        peer.observer.onConnected(PeerRoute.DIRECT)

        val controller = peer.controllerEvents().single().controllerEvent
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(32L, controller.inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, controller.kind)
    }

    @Test
    fun controllerBackpressureTracksConnectionOnlyAfterSendSucceeds() {
        var rejectNextController = true
        val peer =
            ProductFakePeerEngine(
                sendControlResult = { payload ->
                    val envelope = Envelope.parseFrom(payload)
                    if (envelope.payloadCase == Envelope.PayloadCase.CONTROLLER_EVENT && rejectNextController) {
                        rejectNextController = false
                        false
                    } else {
                        true
                    }
                },
            )
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = controllerCodec)
        activateWithVideo(session, peer, monitor, controller = true)
        val controlCountBeforeController = peer.control.size

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(41, controllerSample(kind = ControllerEventKind.CONNECTED))),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
            ),
        )

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(controlCountBeforeController, peer.control.size)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(42, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 1))),
                InternetControllerSendQueue.Delivery.ANALOG,
            ),
        )

        val controllers = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(1, controllers.size)
        assertEquals(41L, controllers.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, controllers.single().kind)

        peer.receive(
            controlEnvelope(4)
                .setInputAck(InputAck.newBuilder().setInputId(41).setAccepted(true))
                .build(),
        )
        assertEquals(listOf(ProductInputAckCallback(41, "pad-1", 3, accepted = true, "")), callbacks.inputAcks)

        assertTrue(
            session.sendController(
                listOf(ProductControllerEvent(43, controllerSample(kind = ControllerEventKind.STATE, buttonMask = 1))),
                InternetControllerSendQueue.Delivery.ANALOG,
            ),
        )
        val afterAck = peer.controllerEvents().map { it.controllerEvent }
        assertEquals(2, afterAck.size)
        assertEquals(43L, afterAck[1].inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, afterAck[1].kind)
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
    fun localManagedPolicyHostDenyFailsInternetHandshakeClosed() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val managedCodec =
            ProtobufProtocolV1ProductCodec(
                localDeviceId = "device-1",
                deviceName = "Android",
                supportedCodecs = setOf(ProductVideoCodec.HEVC),
                localManagedPolicy =
                    InternetManagedPolicy.UNMANAGED.copy(
                        isManaged = true,
                        allowedHosts = setOf("other-host"),
                        allowedHostsRestricted = true,
                    ),
            ) { 1 }
        val session = session(peer, monitor, callbacks, codec = managedCodec)

        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.closeCalls)
        assertEquals("Managed policy does not allow this host", callbacks.failures.single().message)
    }

    @Test
    fun rejectsLegacyHostMissingRequiredTransportBoundaryDuringHandshake() {
        val removedCapabilities =
            listOf(
                Capability.CAPABILITY_MEDIA_RECORD_FRAGMENTATION,
                Capability.CAPABILITY_AUDIO_DATA_CHANNEL,
                Capability.CAPABILITY_BULK_DATA_CHANNEL,
            )

        removedCapabilities.forEach { removed ->
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
                                    it == removed
                                },
                            ),
                    ).build(),
            )

            assertEquals(InternetProductSessionState.FAILED, session.state)
            assertEquals(1, callbacks.failures.size)
        }
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
    fun activeSessionSendsAndReceivesAudioAndBulkRecords() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)

        assertTrue(session.sendAudioRecord(byteArrayOf(0x11, 0x12)))
        assertTrue(session.sendBulkRecord(byteArrayOf(0x21, 0x22), ByteArray(16) { 0x33 }))
        assertArrayEquals(byteArrayOf(0x11, 0x12), peer.audio.single())
        assertArrayEquals(byteArrayOf(0x21, 0x22), peer.bulk.single())

        peer.audio(byteArrayOf(0xA1.toByte(), 0xA2.toByte()))
        peer.bulk(byteArrayOf(0xB1.toByte(), 0xB2.toByte(), 0xB3.toByte()))

        assertArrayEquals(byteArrayOf(0xA1.toByte(), 0xA2.toByte()), callbacks.audio.single())
        assertArrayEquals(byteArrayOf(0xB1.toByte(), 0xB2.toByte(), 0xB3.toByte()), callbacks.bulk.single())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun clipboardNegotiatesAndTransfersContentOverInternetControlChannel() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, clipboard = true)

        assertTrue(session.canSendClipboard())
        assertEquals(InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES, session.negotiatedMaxClipboardBytes())
        assertTrue(session.offerClipboard("from android"))
        val offer = peer.clipboardOffers().single().clipboardOffer
        assertEquals("device-1", offer.originDeviceId)
        assertEquals(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN, offer.mimeType)
        assertEquals("from android".toByteArray(Charsets.UTF_8).size.toLong(), offer.byteLength)

        peer.receive(controlEnvelope(4).setClipboardRequest(
            dev.vibescreen.protocol.v1.ClipboardRequest.newBuilder().setChangeId(offer.changeId),
        ).build())
        val outgoingContent = peer.clipboardContents().single().clipboardContent
        assertEquals(offer.changeId, outgoingContent.changeId)
        assertEquals("device-1", outgoingContent.originDeviceId)
        assertArrayEquals("from android".toByteArray(Charsets.UTF_8), outgoingContent.content.toByteArray())

        val hostText = "from host".toByteArray(Charsets.UTF_8)
        val hostOffer = clipboardOffer(hostText)
        peer.receive(controlEnvelope(5).setClipboardOffer(hostOffer).build())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(1, callbacks.clipboardOffers.size)
        assertArrayEquals(hostOffer.changeId.toByteArray(), callbacks.clipboardOffers.single().changeId)

        assertTrue(session.requestClipboard(hostOffer.changeId.toByteArray()))
        assertEquals(hostOffer.changeId, peer.clipboardRequests().single().clipboardRequest.changeId)
        peer.receive(controlEnvelope(6).setClipboardContent(clipboardContent(hostOffer.changeId, hostText)).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        val received = callbacks.clipboardContents.single()
        assertFalse(received.pending)
        assertArrayEquals(hostText, received.content)
        assertArrayEquals(hostOffer.changeId.toByteArray(), received.changeId)
    }

    @Test
    fun clipboardUnavailableUntilVideoConfigurationIsAccepted() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        val hello = hostHello()
            .addCapabilities(Capability.CAPABILITY_CLIPBOARD)
            .addCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
            .setResourceLimits(mediaRecordLimits(maximumClipboardBytes = InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES))
        val accepted = sessionAccepted()
            .addNegotiatedCapabilities(Capability.CAPABILITY_CLIPBOARD)
            .addNegotiatedCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
            .setNegotiatedResourceLimits(mediaRecordLimits(maximumClipboardBytes = InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES))

        peer.receive(controlEnvelope(1).setHostHello(hello).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(accepted).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertFalse(session.canSendClipboard())
        assertFalse(session.offerClipboard("too early"))
        peer.receive(controlEnvelope(3).setClipboardContent(
            clipboardContent(
                ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { 0x44 }),
                "too early".toByteArray(Charsets.UTF_8),
            ),
        ).build())

        assertEquals(InternetProductSessionState.FAILED, session.state)
    }

    @Test
    fun clipboardContentSupportsOneMiBTextPlusControlEnvelopeOverhead() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, clipboard = true)
        val text = "a".repeat(InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES.toInt())

        assertTrue(session.offerClipboard(text))
        val offer = peer.clipboardOffers().single().clipboardOffer
        peer.receive(controlEnvelope(4).setClipboardRequest(
            dev.vibescreen.protocol.v1.ClipboardRequest.newBuilder().setChangeId(offer.changeId),
        ).build())

        val contentEnvelope = Envelope.parseFrom(peer.control.last())
        assertEquals(Envelope.PayloadCase.CLIPBOARD_CONTENT, contentEnvelope.payloadCase)
        assertEquals(InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES.toInt(), contentEnvelope.clipboardContent.content.size())
        assertTrue(peer.control.last().size > InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES)
    }

    @Test
    fun negotiatedInternetFileTransferAcceptsBulkChunkAndCompletesStagedFile() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x21, 0x22, 0x23)
        val transferId = transferId(0x10)
        val offer = fileOffer(transferId, "incoming.bin", payload)

        peer.receive(controlEnvelope(4).setFileOffer(offer).build())

        assertEquals(offer, callbacks.fileOffers.single())
        assertTrue(session.respondToFileOffer(offer, accepted = true))
        val accepted = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_ACCEPT }.fileAccept
        assertTrue(accepted.accepted)
        assertEquals(transferId, accepted.transferId)
        assertEquals(FileTransferPolicy.DEFAULT_MAXIMUM_CHUNK_BYTES, accepted.maximumChunkBytes)

        peer.bulk(fileChunk(transferId, offset = 0, payload = payload, final = true).toFrame())

        val progress = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_PROGRESS }.fileTransferProgress
        assertEquals(transferId, progress.transferId)
        assertEquals(payload.size.toLong(), progress.receivedBytes)
        val complete = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_COMPLETE }.fileTransferComplete
        assertTrue(complete.accepted)
        assertEquals(transferId, complete.transferId)
        assertEquals(sha256(payload), complete.sha256)
        val completed = callbacks.incomingFiles.single()
        assertEquals(transferId, completed.transferId)
        assertEquals("incoming.bin", completed.fileName)
        assertArrayEquals(payload, completed.stagingFile.readBytes())
        assertTrue(completed.stagingFile.delete())
        assertTrue(callbacks.bulk.isEmpty())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun directClipboardContentIsPendingAndInvalidDigestFailsClosed() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, clipboard = true)

        val directChangeId = ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { (0x40 + it).toByte() })
        val directText = "direct host content".toByteArray(Charsets.UTF_8)
        peer.receive(controlEnvelope(4).setClipboardContent(clipboardContent(directChangeId, directText)).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        val direct = callbacks.clipboardContents.single()
        assertTrue(direct.pending)
        assertArrayEquals(directText, direct.content)

        val badDigestChangeId = ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { (0x60 + it).toByte() })
        peer.receive(
            controlEnvelope(5)
                .setClipboardContent(
                    clipboardContent(badDigestChangeId, "bad".toByteArray(Charsets.UTF_8))
                        .toBuilder()
                        .setSha256(ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_SHA256_BYTES) { 0x7f }))
                        .build(),
                ).build(),
        )

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, peer.closeCalls)
        assertEquals(1, callbacks.failures.size)
    }

    @Test
    fun remoteManagedPolicyDenyDisablesClipboardWithoutClosingActiveVideoSession() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, clipboard = true)
        val beforePolicy = peer.control.size

        peer.receive(controlEnvelope(4).setManagedPolicyStatus(
            managedPolicyStatus(clipboardAllowed = false, allowedHosts = setOf("host-1")),
        ).build())

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertFalse(session.canSendClipboard())
        assertFalse(session.offerClipboard("blocked"))
        assertEquals(beforePolicy, peer.control.size)
        assertEquals(1, callbacks.managedPolicies.size)
        assertFalse(callbacks.managedPolicies.single().clipboardAllowed)
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(0, peer.closeCalls)

        peer.receive(controlEnvelope(5).setPing(Ping.newBuilder().setSequence(77)).build())
        assertEquals(77L, peer.pongs().single().pong.sequence)
    }

    @Test
    fun activeFileTransferDemultiplexesFileChunksFromRawBulkRecords() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x41, 0x42)
        val transferId = transferId(0x20)
        val offer = fileOffer(transferId, "demux.bin", payload)

        peer.receive(controlEnvelope(4).setFileOffer(offer).build())
        assertTrue(session.respondToFileOffer(offer, accepted = true))
        peer.bulk(fileChunk(transferId, offset = 0, payload = payload, final = true).toFrame())

        assertTrue(peer.controlEnvelopes().any { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_COMPLETE })
        assertTrue(callbacks.bulk.isEmpty())

        val rawBulk = byteArrayOf(0x7F, 0x7E)
        peer.bulk(rawBulk)

        assertArrayEquals(rawBulk, callbacks.bulk.single())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun activeFileTransferRejectsChunkLengthMismatchWithTypedReason() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val transferId = transferId(0x24)
        val payload = byteArrayOf(0x51, 0x52)
        val offer = fileOffer(transferId, "mismatch.bin", payload)

        peer.receive(controlEnvelope(4).setFileOffer(offer).build())
        assertTrue(session.respondToFileOffer(offer, accepted = true))

        peer.bulk(fileChunkFrameWithDeclaredLength(transferId, payload, declaredPayloadLength = payload.size + 1))

        val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
        assertEquals(transferId, cancel.transferId)
        assertEquals("chunk_length_mismatch", cancel.reasonCode)
        assertEquals(false to "chunk_length_mismatch", callbacks.fileResults.single())
        assertTrue(callbacks.bulk.isEmpty())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun clientFileOfferStreamsChunksOverInternetBulkDataChannel() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x31, 0x32, 0x33, 0x34, 0x35)
        val file = java.io.File.createTempFile("vibe-internet-outgoing", ".bin")
        file.writeBytes(payload)

        try {
            assertTrue(session.offerFile(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            assertEquals(file.name, offer.fileName)
            assertEquals(payload.size.toLong(), offer.byteLength)
            assertEquals(sha256(payload), offer.sha256)

            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(2),
                    ).build(),
            )
            assertFileChunk(peer.bulk.single(), offer.transferId, offset = 0, payload = payload.copyOfRange(0, 2), final = false)

            peer.receive(controlEnvelope(5).setFileTransferProgress(fileProgress(offer.transferId, 2)).build())
            assertEquals(2, peer.bulk.size)
            assertFileChunk(peer.bulk[1], offer.transferId, offset = 2, payload = payload.copyOfRange(2, 4), final = false)

            peer.receive(controlEnvelope(6).setFileTransferProgress(fileProgress(offer.transferId, 4)).build())
            assertEquals(3, peer.bulk.size)
            assertFileChunk(peer.bulk[2], offer.transferId, offset = 4, payload = payload.copyOfRange(4, 5), final = true)

            peer.receive(controlEnvelope(7).setFileTransferProgress(fileProgress(offer.transferId, 5)).build())
            peer.receive(controlEnvelope(8).setFileTransferComplete(fileComplete(offer.transferId, sha256(payload))).build())

            assertEquals(
                listOf(
                    Triple(offer.transferId, 0L, payload.size.toLong()),
                    Triple(offer.transferId, 2L, payload.size.toLong()),
                    Triple(offer.transferId, 4L, payload.size.toLong()),
                    Triple(offer.transferId, 5L, payload.size.toLong()),
                ),
                callbacks.outgoingProgress,
            )
            assertEquals(listOf(offer.transferId), callbacks.outgoingFinished)
            assertEquals(true to "", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileTransferCanBeCancelledByUser() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x51, 0x52, 0x53, 0x54)
        val file = java.io.File.createTempFile("vibe-internet-outgoing-cancel", ".bin")
        file.writeBytes(payload)

        try {
            val handle = requireNotNull(session.offerFileWithHandle(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            assertEquals(offer.transferId, handle.transferId)
            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(2),
                    ).build(),
            )
            assertFileChunk(peer.bulk.single(), offer.transferId, offset = 0, payload = payload.copyOfRange(0, 2), final = false)

            assertTrue(session.cancelOutgoingFileTransfer(handle.transferId, "user_cancelled"))

            val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
            assertEquals(handle.transferId, cancel.transferId)
            assertEquals("user_cancelled", cancel.reasonCode)
            assertEquals(listOf(Triple(handle.transferId, 0L, payload.size.toLong())), callbacks.outgoingProgress)
            assertEquals(listOf(handle.transferId), callbacks.outgoingFinished)
            assertEquals(false to "user_cancelled", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileCancelReportsLocalSuccessWhenControlSendFails() {
        val peer =
            ProductFakePeerEngine(
                sendControlResult = { payload ->
                    Envelope.parseFrom(payload).payloadCase != Envelope.PayloadCase.FILE_TRANSFER_CANCEL
                },
            )
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x51, 0x52, 0x53, 0x54)
        val file = java.io.File.createTempFile("vibe-internet-outgoing-cancel-send-fail", ".bin")
        file.writeBytes(payload)

        try {
            val handle = requireNotNull(session.offerFileWithHandle(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(2),
                    ).build(),
            )

            assertTrue(session.cancelOutgoingFileTransfer(handle.transferId, "user_cancelled"))

            assertTrue(peer.controlEnvelopes().none { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL })
            assertEquals(listOf(handle.transferId), callbacks.outgoingFinished)
            assertEquals(false to "user_cancelled", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.FAILED, session.state)
            assertEquals("Reliable control channel backlog rejected a state-changing message", callbacks.failures.single().message)
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileOfferTimeoutCancelsTransferAndFreesSlot() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val clock = ProductFakeClock(0)
        val session = session(peer, monitor, callbacks, clock = clock)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val file = java.io.File.createTempFile("vibe-internet-offer-timeout", ".bin")
        file.writeBytes(byteArrayOf(0x41, 0x42))

        try {
            assertTrue(session.offerFile(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer

            clock.now = InternetProductSession.FILE_TRANSFER_PROGRESS_TIMEOUT_MS - 1
            session.tick()
            assertTrue(peer.controlEnvelopes().none { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL })

            clock.now = InternetProductSession.FILE_TRANSFER_PROGRESS_TIMEOUT_MS
            session.tick()

            val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
            assertEquals(offer.transferId, cancel.transferId)
            assertEquals("transfer_timeout", cancel.reasonCode)
            assertEquals(false to "transfer_timeout", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)
            assertEquals(0, peer.closeCalls)

            val nextFile = java.io.File.createTempFile("vibe-internet-after-offer-timeout", ".bin")
            nextFile.writeBytes(byteArrayOf(0x43))
            try {
                assertTrue(session.offerFile(nextFile, "application/octet-stream"))
                assertEquals(2, peer.controlEnvelopes().count { it.payloadCase == Envelope.PayloadCase.FILE_OFFER })
            } finally {
                nextFile.delete()
            }
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileProgressTimeoutCancelsTransferAndFreesSlot() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val clock = ProductFakeClock(0)
        val session = session(peer, monitor, callbacks, clock = clock)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x51, 0x52, 0x53)
        val file = java.io.File.createTempFile("vibe-internet-progress-timeout", ".bin")
        file.writeBytes(payload)

        try {
            assertTrue(session.offerFile(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(2),
                    ).build(),
            )
            assertEquals(1, peer.bulk.size)
            assertFileChunk(peer.bulk.single(), offer.transferId, offset = 0, payload = payload.copyOfRange(0, 2), final = false)

            clock.now = InternetProductSession.FILE_TRANSFER_PROGRESS_TIMEOUT_MS
            session.tick()

            val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
            assertEquals(offer.transferId, cancel.transferId)
            assertEquals("transfer_timeout", cancel.reasonCode)
            assertEquals(false to "transfer_timeout", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)
            assertEquals(0, peer.closeCalls)

            val nextFile = java.io.File.createTempFile("vibe-internet-after-progress-timeout", ".bin")
            nextFile.writeBytes(byteArrayOf(0x54))
            try {
                assertTrue(session.offerFile(nextFile, "application/octet-stream"))
                assertEquals(2, peer.controlEnvelopes().count { it.payloadCase == Envelope.PayloadCase.FILE_OFFER })
            } finally {
                nextFile.delete()
            }
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileCompleteTimeoutCancelsTransferAndFreesSlot() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val clock = ProductFakeClock(0)
        val session = session(peer, monitor, callbacks, clock = clock)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x71, 0x72, 0x73)
        val file = java.io.File.createTempFile("vibe-internet-complete-timeout", ".bin")
        file.writeBytes(payload)

        try {
            assertTrue(session.offerFile(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(2),
                    ).build(),
            )
            assertEquals(1, peer.bulk.size)
            peer.receive(controlEnvelope(5).setFileTransferProgress(fileProgress(offer.transferId, 2)).build())
            assertEquals(2, peer.bulk.size)
            assertFileChunk(peer.bulk[1], offer.transferId, offset = 2, payload = payload.copyOfRange(2, 3), final = true)
            peer.receive(controlEnvelope(6).setFileTransferProgress(fileProgress(offer.transferId, 3)).build())

            clock.now = InternetProductSession.FILE_TRANSFER_PROGRESS_TIMEOUT_MS
            session.tick()

            val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
            assertEquals(offer.transferId, cancel.transferId)
            assertEquals("transfer_timeout", cancel.reasonCode)
            assertEquals(false to "transfer_timeout", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)

            val nextFile = java.io.File.createTempFile("vibe-internet-after-complete-timeout", ".bin")
            nextFile.writeBytes(byteArrayOf(0x74))
            try {
                assertTrue(session.offerFile(nextFile, "application/octet-stream"))
                assertEquals(2, peer.controlEnvelopes().count { it.payloadCase == Envelope.PayloadCase.FILE_OFFER })
            } finally {
                nextFile.delete()
            }
        } finally {
            file.delete()
        }
    }

    @Test
    fun outgoingInternetFileBulkBackpressureCancelsTransferWithoutFailingSession() {
        val peer = ProductFakePeerEngine(acceptBulkRecords = false)
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true)
        val payload = byteArrayOf(0x61, 0x62, 0x63)
        val file = java.io.File.createTempFile("vibe-internet-backpressure", ".bin")
        file.writeBytes(payload)

        try {
            assertTrue(session.offerFile(file, "application/octet-stream"))
            val offer = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_OFFER }.fileOffer
            peer.receive(
                controlEnvelope(4)
                    .setFileAccept(
                        FileAccept
                            .newBuilder()
                            .setTransferId(offer.transferId)
                            .setAccepted(true)
                            .setMaximumChunkBytes(payload.size),
                    ).build(),
            )

            val cancel = peer.controlEnvelopes().single { it.payloadCase == Envelope.PayloadCase.FILE_TRANSFER_CANCEL }.fileTransferCancel
            assertEquals(offer.transferId, cancel.transferId)
            assertEquals("bulk_send_failed", cancel.reasonCode)
            assertEquals(false to "bulk_send_failed", callbacks.fileResults.single())
            assertEquals(InternetProductSessionState.ACTIVE, session.state)
            assertEquals(0, peer.closeCalls)
            assertTrue(callbacks.failures.isEmpty())
        } finally {
            file.delete()
        }
    }

    @Test
    fun managedPolicyDenyDisablesInternetFileTransferWithoutAffectingRawBulkCallback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor, fileTransfer = true, managedConfiguration = true)
        assertTrue(session.canTransferFiles)

        peer.receive(
            controlEnvelope(4)
                .setManagedPolicyStatus(managedPolicyStatus(fileTransferAllowed = false, maximumFileBytes = 0))
                .build(),
        )
        peer.bulk(byteArrayOf(0x7F))

        assertFalse(session.canTransferFiles)
        assertArrayEquals(byteArrayOf(0x7F), callbacks.bulk.single())
        assertTrue(callbacks.failures.isEmpty())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun negotiatedInternetAudioConfiguresPlaybackAfterVideoConfiguration() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)

        val clientHello = Envelope.parseFrom(peer.control.first()).clientHello
        assertTrue(clientHello.capabilitiesList.contains(Capability.CAPABILITY_AUDIO))

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())

        val result = Envelope.parseFrom(peer.control.last()).audioConfigResult
        assertTrue(result.accepted)
        assertEquals(2L, result.streamId)
        assertEquals(1L, result.configEpoch)
        assertEquals(listOf(audioConfig() to 7L), playback.configured)
        assertTrue(playback.stops.isEmpty())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun acceptedInternetAudioPacketsSubmitToPlaybackAndSuppressRawCallback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)
        val config = audioConfig()
        peer.receive(controlEnvelope(4).setAudioConfig(config).build())
        val packet = audioPacket(config)

        peer.audio(packet)

        assertEquals(1, playback.submitted.size)
        assertArrayEquals(packet, playback.submitted.single())
        assertTrue(callbacks.audio.isEmpty())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun managedPolicyAudioDenyStopsPlaybackAndRemovesCapability() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true, managedConfiguration = true)
        val config = audioConfig()
        peer.receive(controlEnvelope(4).setAudioConfig(config).build())
        val packet = audioPacket(config)
        peer.audio(packet)
        assertEquals(1, playback.submitted.size)

        peer.receive(
            controlEnvelope(5)
                .setManagedPolicyStatus(managedPolicyStatus(audioAllowed = false))
                .build(),
        )
        assertEquals(listOf("managed_policy_audio_denied"), playback.stops)

        peer.audio(packet)

        assertEquals(1, playback.submitted.size)
        assertTrue(callbacks.audio.isEmpty())

        peer.receive(controlEnvelope(6).setAudioConfig(audioConfig(configEpoch = 2)).build())

        assertEquals(listOf("managed_policy_audio_denied", "session_failure"), playback.stops)
        assertEquals(1, playback.submitted.size)
        assertTrue(callbacks.audio.isEmpty())
        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals("Audio configuration arrived without a negotiated audio session", callbacks.failures.single().message)
    }

    @Test
    fun audioConfigurationWithoutNegotiatedAudioFailsClosed() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, audioPlayback = playback)
        activateWithVideo(session, peer, monitor)

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertTrue(playback.configured.isEmpty())
        assertEquals(1, callbacks.failures.size)
        assertEquals(
            "Audio configuration arrived without a negotiated audio session",
            callbacks.failures.single().message,
        )
    }

    @Test
    fun rejectedInternetAudioConfigurationRespondsWithoutStartingPlayback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback(configureDecision = InternetAudioDecision.reject("audio_track_start_failed"))
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())

        val result = Envelope.parseFrom(peer.control.last()).audioConfigResult
        assertFalse(result.accepted)
        assertEquals("audio_track_start_failed", result.rejectionReason)
        assertEquals(listOf(audioConfig() to 7L), playback.configured)
        assertEquals(listOf("audio_configuration_rejected"), playback.stops)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun repeatedAcceptedInternetAudioConfigurationIsIdempotent() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())
        peer.receive(controlEnvelope(5).setAudioConfig(audioConfig()).build())

        val result = Envelope.parseFrom(peer.control.last()).audioConfigResult
        assertTrue(result.accepted)
        assertEquals("", result.rejectionReason)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(1, playback.configured.size)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun staleInternetAudioConfigurationIsRejectedWithoutFailingSession() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())
        peer.receive(controlEnvelope(5).setAudioConfig(audioConfig(streamId = 3)).build())

        val result = Envelope.parseFrom(peer.control.last()).audioConfigResult
        assertFalse(result.accepted)
        assertEquals("invalid_audio_config_epoch", result.rejectionReason)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(1, playback.configured.size)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun negotiatedInternetAudioWithoutPlaybackAdapterFailsClosed() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks, codec = audioCodec)
        activateWithVideo(session, peer, monitor, audio = true)

        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.failures.size)
        assertEquals(
            "Audio playback is unavailable for a negotiated audio session",
            callbacks.failures.single().message,
        )
    }

    @Test
    fun rejectedInternetAudioPacketFailsClosedAndStopsPlayback() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val playback = ProductFakeAudioPlayback()
        val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
        activateWithVideo(session, peer, monitor, audio = true)
        peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())
        playback.submitDecision = InternetAudioDecision.reject("invalid_audio_header")

        peer.audio(byteArrayOf(0x01))

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(listOf("invalid_audio_header", "session_failure"), playback.stops)
        assertEquals(1, callbacks.failures.size)
        assertEquals(
            "Protocol v1 audio record was rejected: invalid_audio_header",
            callbacks.failures.single().message,
        )
    }

    @Test
    fun configuredInternetAudioStopsOnCloseFreshSessionAndRevocation() {
        listOf("close", "fresh", "revocation").forEach { terminal ->
            val peer = ProductFakePeerEngine()
            val monitor = ProductFakeNetworkMonitor()
            val callbacks = ProductCallbacks()
            val playback = ProductFakeAudioPlayback()
            val session = session(peer, monitor, callbacks, codec = audioCodec, audioPlayback = playback)
            activateWithVideo(session, peer, monitor, audio = true)
            peer.receive(controlEnvelope(4).setAudioConfig(audioConfig()).build())

            when (terminal) {
                "close" -> session.close()
                "fresh" -> monitor.available("cellular")
                "revocation" -> peer.receive(revocationEnvelope(5))
            }

            assertTrue(playback.stops.isNotEmpty())
            assertEquals(
                when (terminal) {
                    "close" -> "session_close"
                    "fresh" -> "fresh_session_required"
                    else -> "session_revoked"
                },
                playback.stops.first(),
            )
        }
    }

    @Test
    fun audioRecordBeforeVideoConfigurationIsDroppedWithoutFailingSession() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.audio(byteArrayOf(0x01))

        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertEquals(0, peer.closeCalls)
        assertTrue(callbacks.audio.isEmpty())
        assertTrue(callbacks.failures.isEmpty())

        peer.receive(videoConfigurationEnvelope(3))
        peer.audio(byteArrayOf(0x02))

        assertArrayEquals(byteArrayOf(0x02), callbacks.audio.single())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    @Test
    fun audioRecordWithoutNegotiatedAudioUsesRawCallbackOnlyAfterVideoConfiguration() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)

        peer.audio(byteArrayOf(0x03))

        assertArrayEquals(byteArrayOf(0x03), callbacks.audio.single())
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun overlappingAudioRecordAdmissionsDoNotFailActiveSession() {
        val firstSendEntered = CountDownLatch(1)
        val releaseFirstSend = CountDownLatch(1)
        val audioSendCalls = AtomicInteger(0)
        val peer =
            ProductFakePeerEngine(
                sendAudioHook = {
                    if (audioSendCalls.incrementAndGet() == 1) {
                        firstSendEntered.countDown()
                        assertTrue(releaseFirstSend.await(2, TimeUnit.SECONDS))
                    }
                },
            )
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)
        val payload = ByteArray(InternetAudioRecordContract.MAXIMUM_PLAINTEXT_RECORD_BYTES) { 0x11 }
        val executor = Executors.newFixedThreadPool(2)

        val first = executor.submit<Boolean> { session.sendAudioRecord(payload) }
        assertTrue(firstSendEntered.await(2, TimeUnit.SECONDS))
        val second = executor.submit<Boolean> { session.sendAudioRecord(payload) }
        assertTrue(second.get(2, TimeUnit.SECONDS))
        releaseFirstSend.countDown()

        assertTrue(first.get(2, TimeUnit.SECONDS))
        executor.shutdown()
        assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS))
        assertEquals(2, peer.audio.size)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.failures.isEmpty())
    }

    @Test
    fun advancedChannelRecordsAreRejectedOutsideActiveSessionAndFailClosedOnBacklogFailure() {
        val inactive = session(ProductFakePeerEngine(), ProductFakeNetworkMonitor(), ProductCallbacks())
        assertFalse(inactive.sendAudioRecord(byteArrayOf(1)))
        assertFalse(inactive.sendBulkRecord(byteArrayOf(2), ByteArray(16)))

        val peer = ProductFakePeerEngine(acceptBulkRecords = false)
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)

        assertFalse(session.sendBulkRecord(byteArrayOf(3), ByteArray(16)))

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals("Protocol v1 advanced channel backlog rejected a product-session record", callbacks.failures.single().message)
        assertEquals(1, peer.closeCalls)
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
        peer.receive(controlEnvelope(1).setHostHello(hostHello().addCapabilities(Capability.CAPABILITY_TOUCH)).build())
        peer.receive(
            controlEnvelope(2)
                .setSessionAccepted(sessionAccepted().addNegotiatedCapabilities(Capability.CAPABILITY_TOUCH))
                .build(),
        )
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
    fun av1VideoConfigurationRejectionIsReportedBeforeMediaActivation() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks =
            object : InternetProductSessionCallbacks {
                val configurations = mutableListOf<ProductVideoConfiguration>()

                override fun onVideoConfiguration(
                    configuration: ProductVideoConfiguration,
                    effect: ProductVideoConfigurationEffect,
                    completion: (ProductVideoDecision) -> Unit,
                ) {
                    if (configuration.codec == ProductVideoCodec.AV1) {
                        completion(ProductVideoDecision.reject("av1_decoder_unavailable"))
                        return
                    }
                    completion(
                        effect.commit {
                            configurations += configuration
                            ProductVideoDecision.ACCEPT
                        },
                    )
                }
            }
        val session = session(peer, monitor, callbacks)
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        peer.receive(controlEnvelope(1).setHostHello(hostHello()).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(sessionAccepted()).build())

        peer.receive(videoConfigurationEnvelope(3, codec = Codec.CODEC_AV1))

        val result = Envelope.parseFrom(peer.control.last()).videoConfigResult
        assertFalse(result.accepted)
        assertEquals("av1_decoder_unavailable", result.rejectionReason)
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
        assertTrue(callbacks.configurations.isEmpty())
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
    fun nonIncreasingVideoConfigurationEpochFailsClosedBeforeDecoderInstall() {
        val peer = ProductFakePeerEngine()
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)

        activateWithVideo(session, peer, monitor)
        assertEquals(1, callbacks.configurations.size)

        // Epoch 3 is already committed by activateWithVideo. A repeated epoch
        // must fail before a second decoder configuration is installed.
        peer.receive(videoConfigurationEnvelope(4))

        assertEquals(InternetProductSessionState.FAILED, session.state)
        assertEquals(1, callbacks.configurations.size)
        assertEquals(1, callbacks.failures.size)
        assertEquals(1, peer.closeCalls)
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
    fun freshSessionRecoveryClosesOldTransportBeforeCallback() {
        val peer = ProductFakePeerEngine(
            restartResult = WebRtcIceRestartResult.RequiresFreshSession("fresh lease required"),
        )
        val monitor = ProductFakeNetworkMonitor()
        val callbacks = ProductCallbacks()
        val session = session(peer, monitor, callbacks)
        activateWithVideo(session, peer, monitor)

        peer.observer.onConnectionFailed("ICE failed")

        assertEquals(InternetProductSessionState.RECOVERING, session.state)
        assertEquals(listOf("fresh lease required"), callbacks.freshReasons)
        assertEquals(1, peer.restartCalls)
        assertEquals(1, peer.closeCalls)
        peer.media(media(frameId = 20, keyframe = true, payload = "stale".toByteArray()))
        assertTrue(callbacks.frames.isEmpty())
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
        codec: ProtocolV1ProductCodec = this.codec,
        nextControllerInputId: () -> Long = { error("Unexpected controller input id allocation") },
        audioPlayback: InternetAudioPlayback? = null,
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
        audioPlayback = audioPlayback,
        callbacks = callbacks,
        revocationStore = revocationStore,
        revocationCoordinator = revocationCoordinator,
        nextControllerInputId = nextControllerInputId,
        testHooks = testHooks,
    )

    private fun monotonicControllerInputIds(first: Long): () -> Long {
        val next = AtomicLong(first)
        return { next.getAndIncrement() }
    }

    private fun activateWithVideo(
        session: InternetProductSession,
        peer: ProductFakePeerEngine,
        monitor: ProductFakeNetworkMonitor,
        controller: Boolean = false,
        clipboard: Boolean = false,
        fileTransfer: Boolean = false,
        managedConfiguration: Boolean = false,
        audio: Boolean = false,
    ) {
        session.start()
        monitor.available("wifi")
        peer.observer.onConnected(PeerRoute.DIRECT)
        val hello = hostHello()
        val accepted = sessionAccepted()
        if (controller) {
            hello.addCapabilities(Capability.CAPABILITY_CONTROLLER)
            accepted.addNegotiatedCapabilities(Capability.CAPABILITY_CONTROLLER)
        }
        if (clipboard) {
            hello
                .addCapabilities(Capability.CAPABILITY_CLIPBOARD)
                .addCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
                .setResourceLimits(mediaRecordLimits(maximumClipboardBytes = InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES))
            accepted
                .addNegotiatedCapabilities(Capability.CAPABILITY_CLIPBOARD)
                .addNegotiatedCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
                .setNegotiatedResourceLimits(mediaRecordLimits(maximumClipboardBytes = InternetClipboard.LOCAL_MAX_CLIPBOARD_BYTES))
        }
        if (fileTransfer) {
            hello.addCapabilities(Capability.CAPABILITY_FILE_TRANSFER)
            accepted.addNegotiatedCapabilities(Capability.CAPABILITY_FILE_TRANSFER)
        }
        if (managedConfiguration) {
            hello.addCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
            accepted.addNegotiatedCapabilities(Capability.CAPABILITY_MANAGED_CONFIGURATION)
        }
        if (audio) {
            hello.addCapabilities(Capability.CAPABILITY_AUDIO)
            accepted.addNegotiatedCapabilities(Capability.CAPABILITY_AUDIO)
        }
        peer.receive(controlEnvelope(1).setHostHello(hello).build())
        peer.receive(controlEnvelope(2).setSessionAccepted(accepted).build())
        peer.receive(videoConfigurationEnvelope(3))
        assertEquals(InternetProductSessionState.ACTIVE, session.state)
    }

    private fun controllerSample(
        kind: ControllerEventKind,
        buttonMask: Int = 0,
        axes: ControllerAxes = ControllerAxes.NEUTRAL,
        controllerId: String = "pad-1",
        controllerEpoch: Long = 3,
    ): ControllerStateSample =
        ControllerStateSample(
            controllerId = controllerId,
            controllerEpoch = controllerEpoch,
            kind = kind,
            buttonMask = buttonMask,
            axes = axes,
        )

    private fun videoConfigurationEnvelope(
        messageId: Long,
        codec: Codec = Codec.CODEC_HEVC,
    ): Envelope =
        controlEnvelope(messageId)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(3)
                    .setCodec(codec)
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
        maximumClipboardBytes: Long = 0L,
    ): ResourceLimits.Builder =
        ResourceLimits
            .newBuilder()
            .setMaximumEncryptedMediaRecordBytes(maximumEncryptedMediaRecordBytes)
            .setMaximumClipboardBytes(maximumClipboardBytes)
            .setMaximumFileBytes(FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES)
            .setMaximumFileChunkBytes(FileTransferPolicy.DEFAULT_MAXIMUM_CHUNK_BYTES)

    private fun clipboardOffer(
        content: ByteArray,
        changeId: ByteString = ByteString.copyFrom(ByteArray(InternetClipboard.CLIPBOARD_CHANGE_ID_BYTES) { (0x20 + it).toByte() }),
    ): ClipboardOffer =
        ClipboardOffer
            .newBuilder()
            .setChangeId(changeId)
            .setOriginDeviceId("host-1")
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setByteLength(content.size.toLong())
            .setSha256(ByteString.copyFrom(InternetClipboard.sha256(content)))
            .build()

    private fun clipboardContent(
        changeId: ByteString,
        content: ByteArray,
    ): ClipboardContent =
        ClipboardContent
            .newBuilder()
            .setChangeId(changeId)
            .setOriginDeviceId("host-1")
            .setMimeType(InternetClipboard.CLIPBOARD_MIME_TEXT_PLAIN)
            .setContent(ByteString.copyFrom(content))
            .setSha256(ByteString.copyFrom(InternetClipboard.sha256(content)))
            .build()

    private fun transferId(seed: Int): ByteString = ByteString.copyFrom(ByteArray(16) { (seed + it).toByte() })

    private fun fileOffer(
        transferId: ByteString,
        fileName: String,
        payload: ByteArray,
        mimeType: String = "application/octet-stream",
    ): FileOffer =
        FileOffer
            .newBuilder()
            .setTransferId(transferId)
            .setFileName(fileName)
            .setMimeType(mimeType)
            .setByteLength(payload.size.toLong())
            .setSha256(sha256(payload))
            .build()

    private fun fileChunk(
        transferId: ByteString,
        offset: Long,
        payload: ByteArray,
        final: Boolean,
    ): FileChunk =
        FileChunk(
            FileChunkHeader
                .newBuilder()
                .setTransferId(transferId)
                .setOffset(offset)
                .setPayloadLength(payload.size)
                .setSessionEpoch(lease.authoritativeSessionEpoch)
                .setChunkSha256(sha256(payload))
                .setFinal(final)
                .build(),
            payload,
        )

    private fun fileChunkFrameWithDeclaredLength(
        transferId: ByteString,
        payload: ByteArray,
        declaredPayloadLength: Int,
    ): ByteArray {
        val header =
            FileChunkHeader
                .newBuilder()
                .setTransferId(transferId)
                .setOffset(0)
                .setPayloadLength(declaredPayloadLength)
                .setSessionEpoch(lease.authoritativeSessionEpoch)
                .setChunkSha256(sha256(payload))
                .setFinal(true)
                .build()
        val headerBytes = header.toByteArray()
        val prefixBytes = CodedOutputStream.computeUInt32SizeNoTag(headerBytes.size)
        return ByteArray(prefixBytes + headerBytes.size + payload.size).also { output ->
            val coded = CodedOutputStream.newInstance(output)
            coded.writeUInt32NoTag(headerBytes.size)
            coded.writeRawBytes(headerBytes)
            coded.writeRawBytes(payload)
            coded.flush()
        }
    }

    private fun fileProgress(transferId: ByteString, receivedBytes: Long): FileTransferProgress =
        FileTransferProgress
            .newBuilder()
            .setTransferId(transferId)
            .setReceivedBytes(receivedBytes)
            .build()

    private fun fileComplete(transferId: ByteString, digest: ByteString): FileTransferComplete =
        FileTransferComplete
            .newBuilder()
            .setTransferId(transferId)
            .setAccepted(true)
            .setSha256(digest)
            .build()

    private fun managedPolicyStatus(
        clipboardAllowed: Boolean = true,
        fileTransferAllowed: Boolean = true,
        audioAllowed: Boolean = true,
        maximumFileBytes: Long = FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
        allowedHosts: Set<String> = setOf("host-1"),
    ): ManagedPolicyStatus =
        InternetManagedPolicy.UNMANAGED.copy(
            isManaged = true,
            clipboardAllowed = clipboardAllowed,
            fileTransferAllowed = fileTransferAllowed,
            audioAllowed = audioAllowed,
            maximumFileBytes = maximumFileBytes,
            allowedHosts = allowedHosts,
            allowedHostsRestricted = allowedHosts.isNotEmpty(),
        ).toStatus()

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

    private fun audioConfig(
        streamId: Long = 2,
        configEpoch: Long = 1,
    ): AudioConfig =
        AudioConfig
            .newBuilder()
            .setStreamId(streamId)
            .setConfigEpoch(configEpoch)
            .setCodec(AudioCodec.AUDIO_CODEC_PCM_S16LE)
            .setSampleRateHz(48_000)
            .setChannelCount(2)
            .setFramesPerPacket(480)
            .build()

    private fun audioPacket(
        config: AudioConfig,
        sequence: Long = 0,
    ): ByteArray {
        val payload = ByteArray(config.framesPerPacket * config.channelCount * 2) { 0x55 }
        val header =
            AudioPacketHeader
                .newBuilder()
                .setStreamId(config.streamId)
                .setSessionEpoch(lease.authoritativeSessionEpoch)
                .setConfigEpoch(config.configEpoch)
                .setSequence(sequence)
                .setFrameCount(config.framesPerPacket)
                .setPayloadLength(payload.size)
                .build()
        val headerBytes = header.toByteArray()
        return audioVarint(headerBytes.size) + headerBytes + payload
    }

    private fun audioVarint(value: Int): ByteArray {
        var remaining = value
        val output = mutableListOf<Byte>()
        do {
            var next = remaining and 0x7f
            remaining = remaining ushr 7
            if (remaining > 0) next = next or 0x80
            output += next.toByte()
        } while (remaining > 0)
        return output.toByteArray()
    }

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

private data class ProductInputAckCallback(
    val inputId: Long,
    val controllerId: String?,
    val controllerEpoch: Long?,
    val accepted: Boolean,
    val rejectionReason: String,
)

private class ProductCallbacks : InternetProductSessionCallbacks {
    val states = java.util.concurrent.CopyOnWriteArrayList<InternetProductSessionState>()
    val frames = mutableListOf<ProductVideoFrame>()
    val audio = mutableListOf<ByteArray>()
    val bulk = mutableListOf<ByteArray>()
    val fileOffers = java.util.concurrent.CopyOnWriteArrayList<FileOffer>()
    val incomingFiles = java.util.concurrent.CopyOnWriteArrayList<CompletedIncomingFile>()
    val outgoingProgress = java.util.concurrent.CopyOnWriteArrayList<Triple<ByteString, Long, Long>>()
    val outgoingFinished = java.util.concurrent.CopyOnWriteArrayList<ByteString>()
    val fileResults = java.util.concurrent.CopyOnWriteArrayList<Pair<Boolean, String>>()
    val configurations = mutableListOf<ProductVideoConfiguration>()
    val appliedConfigurations = mutableListOf<ProductVideoConfiguration>()
    val inputAcks = java.util.concurrent.CopyOnWriteArrayList<ProductInputAckCallback>()
    val freshReasons = mutableListOf<String>()
    val failures = mutableListOf<Throwable>()
    val routes = java.util.concurrent.CopyOnWriteArrayList<PeerRoute>()
    val clipboardOffers = mutableListOf<ClipboardOfferData>()
    val clipboardContents = mutableListOf<ClipboardContentData>()
    val managedPolicies = mutableListOf<ManagedPolicyStatus>()
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
    override fun onVideoConfigurationApplied(configuration: ProductVideoConfiguration) {
        appliedConfigurations += configuration
    }
    override fun onInputAck(
        inputId: Long,
        controllerId: String?,
        controllerEpoch: Long?,
        accepted: Boolean,
        rejectionReason: String,
    ) {
        inputAcks += ProductInputAckCallback(inputId, controllerId, controllerEpoch, accepted, rejectionReason)
    }
    override fun onVideoFrame(frame: ProductVideoFrame) { frames += frame }
    override fun onAudioRecord(payload: ByteArray) { audio += payload }
    override fun onBulkRecord(payload: ByteArray) { bulk += payload }
    override fun onClipboardOffered(offer: ClipboardOfferData) { clipboardOffers += offer }
    override fun onClipboardContent(content: ClipboardContentData) { clipboardContents += content }
    override fun onManagedPolicyReceived(status: ManagedPolicyStatus) { managedPolicies += status }
    override fun onFileOffer(offer: FileOffer) { fileOffers += offer }
    override fun onIncomingFileCompleted(completed: CompletedIncomingFile) { incomingFiles += completed }
    override fun onOutgoingFileProgress(transferId: ByteString, acknowledgedBytes: Long, totalBytes: Long) {
        outgoingProgress += Triple(transferId, acknowledgedBytes, totalBytes)
    }
    override fun onOutgoingFileFinished(transferId: ByteString) { outgoingFinished += transferId }
    override fun onFileTransferResult(accepted: Boolean, reason: String) { fileResults += accepted to reason }
    override fun onFreshSessionRequired(reason: String) { freshReasons += reason }
    override fun onFailure(error: Throwable) { failures += error }
    override fun onRouteSelected(route: PeerRoute) { routes += route }
    override fun onRevoked(reason: String) { revocationEvents?.add("callback") }
}

private class ProductFakeAudioPlayback(
    override val canAdvertiseAudio: Boolean = true,
    private val configureDecision: InternetAudioDecision = InternetAudioDecision.ACCEPT,
) : InternetAudioPlayback {
    val configured = mutableListOf<Pair<AudioConfig, Long>>()
    val submitted = mutableListOf<ByteArray>()
    val stops = mutableListOf<String>()
    var submitDecision: InternetAudioDecision = InternetAudioDecision.ACCEPT

    override fun configure(config: AudioConfig, sessionEpoch: Long): InternetAudioDecision {
        configured += config to sessionEpoch
        return configureDecision
    }

    override fun submit(serializedFrame: ByteArray): InternetAudioDecision {
        submitted += serializedFrame.copyOf()
        return submitDecision
    }

    override fun stop(reason: String) {
        stops += reason
    }
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
    private val sendControlHook: (ByteArray) -> Unit = {},
    private val sendControlResult: (ByteArray) -> Boolean = { true },
    private val sendAudioHook: (ByteArray) -> Unit = {},
    private val acceptBulkRecords: Boolean = true,
    private val restartResult: WebRtcIceRestartResult =
        WebRtcIceRestartResult.RequiresFreshSession("fresh signaling session required"),
) : WebRtcPeerEngine {
    override val controlSemantics = DataChannelSemantics.RELIABLE_CONTROL
    override val mediaSemantics = DataChannelSemantics.LATEST_MEDIA
    lateinit var observer: WebRtcPeerEngine.Observer
    val control = mutableListOf<ByteArray>()
    val audio = mutableListOf<ByteArray>()
    val bulk = mutableListOf<ByteArray>()
    var startCalls = 0
    var restartCalls = 0
    var closeCalls = 0
    override fun start(configuration: PeerConfiguration, observer: WebRtcPeerEngine.Observer) {
        startCalls++
        this.observer = observer
        startHook()
    }
    override fun sendControl(payload: ByteArray): Boolean {
        val accepted = sendControlResult(payload)
        if (accepted) control.add(payload)
        if (accepted) sendControlHook(payload)
        return accepted
    }
    override fun sendMedia(frame: OutboundMediaFrame): Boolean = true
    override fun sendAudioRecord(payload: ByteArray): Boolean {
        val accepted = synchronized(audio) { audio.add(payload) }
        if (accepted) sendAudioHook(payload)
        return accepted
    }
    override fun sendBulkRecord(payload: ByteArray): Boolean = acceptBulkRecords && bulk.add(payload)
    override fun restartIce(): WebRtcIceRestartResult {
        restartCalls++
        return restartResult
    }
    override fun applyVideoProfile(profile: VideoProfile) = Unit
    override fun close() {
        closeCalls++
        closeFailure?.let { throw it }
    }
    fun receive(envelope: Envelope) = observer.onControlMessage(7, envelope.toByteArray())
    fun media(payload: ByteArray) = observer.onMediaPacket(7, payload)
    fun audio(payload: ByteArray) = observer.onAudioRecord(7, payload)
    fun bulk(payload: ByteArray) = observer.onBulkRecord(7, payload)

    fun keyframeRequests(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.REQUEST_KEYFRAME }

    fun controllerEvents(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.CONTROLLER_EVENT }

    fun clipboardOffers(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.CLIPBOARD_OFFER }

    fun clipboardRequests(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.CLIPBOARD_REQUEST }

    fun clipboardContents(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.CLIPBOARD_CONTENT }

    fun pongs(): List<Envelope> =
        control
            .map(Envelope::parseFrom)
            .filter { it.payloadCase == Envelope.PayloadCase.PONG }
}

private fun ProductFakePeerEngine.controlEnvelopes(): List<Envelope> = control.map(Envelope::parseFrom)

private fun assertFileChunk(
    frame: ByteArray,
    transferId: ByteString,
    offset: Long,
    payload: ByteArray,
    final: Boolean,
) {
    val chunk = FileChunk.fromFrame(frame)
    assertEquals(transferId, chunk.header.transferId)
    assertEquals(offset, chunk.header.offset)
    assertEquals(payload.size, chunk.header.payloadLength)
    assertEquals(final, chunk.header.final)
    assertArrayEquals(payload, chunk.payload)
}
