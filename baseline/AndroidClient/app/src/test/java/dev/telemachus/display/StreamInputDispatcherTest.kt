package dev.telemachus.display

import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.TouchSample
import dev.vibescreen.protocol.v1.Capability
import dev.vibescreen.protocol.v1.Codec
import dev.vibescreen.protocol.v1.Dimensions
import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.HostHello
import dev.vibescreen.protocol.v1.InputPhase
import dev.vibescreen.protocol.v1.ListDisplaysResponse
import dev.vibescreen.protocol.v1.SessionAccepted
import dev.vibescreen.protocol.v1.StartDisplayResponse
import dev.vibescreen.protocol.v1.TransportKind
import dev.vibescreen.protocol.v1.VideoConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicLong

class StreamInputDispatcherTest {
    @Test
    fun legacyTouchUsesLegacyWireCommandAndCapsTwoPointers() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = StreamInputSessionState(connected = true, protocolV1 = false),
            recorder = recorder,
        )

        dispatcher.sendTouch(0.2f, 0.3f, action = 1, pointerCount = 3, x2 = 0.7f, y2 = 0.8f)

        val submission = recorder.single()
        assertEquals(OutboundCommandScheduler.Kind.MOVE, submission.kind)
        val touch = submission.command as StreamOutboundCommand.Touch
        assertEquals(0.2f, touch.x)
        assertEquals(0.3f, touch.y)
        assertEquals(1, touch.action)
        assertEquals(2, touch.pointerCount)
        assertEquals(0.7f, touch.x2)
        assertEquals(0.8f, touch.y2)
    }

    @Test
    fun disconnectedSessionRejectsAllInputRoutes() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = StreamInputSessionState(connected = false, protocolV1 = true),
            recorder = recorder,
        )

        dispatcher.sendTouch(0.2f, 0.3f, action = 0)
        assertFalse(dispatcher.sendMotionStylus(listOf(stylusSample())))
        assertFalse(dispatcher.sendPointer(InputPhase.INPUT_PHASE_BEGAN, 0.2f, 0.3f, NativeInputWire.BUTTON_PRIMARY))
        assertFalse(dispatcher.sendScroll(1.0, -1.0))
        assertFalse(dispatcher.sendKey(0x04, pressed = true, modifierMask = 0))
        assertFalse(dispatcher.sendController(controllerDispatch()))

        assertTrue(recorder.submissions.isEmpty())
    }

    @Test
    fun unnegotiatedProtocolV1InputStaysOffWire() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = StreamInputSessionState(connected = true, protocolV1 = true),
            recorder = recorder,
        )

        dispatcher.sendMotionTouch(
            v1Samples = listOf(TouchSample(1, InputPhase.INPUT_PHASE_BEGAN, 0.2, 0.3)),
            legacyAction = 0,
            legacyPointers = emptyList(),
        )
        assertFalse(dispatcher.sendMotionStylus(listOf(stylusSample())))
        assertFalse(dispatcher.sendPointer(InputPhase.INPUT_PHASE_BEGAN, 0.2f, 0.3f, NativeInputWire.BUTTON_PRIMARY))
        assertFalse(dispatcher.sendKey(0x04, pressed = true, modifierMask = 0))
        assertFalse(dispatcher.sendController(controllerDispatch()))

        assertTrue(recorder.submissions.isEmpty())
    }

    @Test
    fun negotiatedTouchBatchPreservesAtomicMoveRoutingAndInputIds() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(touch = true),
            recorder = recorder,
            firstInputId = 10,
        )

        dispatcher.sendMotionTouch(
            v1Samples =
                listOf(
                    TouchSample(7, InputPhase.INPUT_PHASE_CHANGED, 0.2, 0.3),
                    TouchSample(9, InputPhase.INPUT_PHASE_CHANGED, 0.8, 0.7),
                ),
            legacyAction = 1,
            legacyPointers = emptyList(),
        )

        val submission = recorder.single()
        assertEquals(OutboundCommandScheduler.Kind.MOVE, submission.kind)
        val envelopes = submission.protocolEnvelopes(streamingSession(Capability.CAPABILITY_TOUCH))
        assertEquals(listOf(7, 9), envelopes.map { it.touchEvent.pointerId })
        assertEquals(listOf(10L, 11L), envelopes.map { it.touchEvent.inputId })
    }

    @Test
    fun stylusExtendedFieldsAreSuppressedUnlessActiveSessionAllowsThem() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(stylus = true, extendedStylus = true),
            recorder = recorder,
        )

        assertTrue(dispatcher.sendMotionStylus(listOf(stylusSample())))

        val basic = recorder.single().protocolEnvelopes(streamingSession(Capability.CAPABILITY_STYLUS)).single()
        assertEquals(dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_UNSPECIFIED, basic.stylusEvent.toolKind)
        assertEquals(0, basic.stylusEvent.buttonMask)

        val extended =
            recorder.single().protocolEnvelopes(
                streamingSession(Capability.CAPABILITY_STYLUS, Capability.CAPABILITY_STYLUS_EXTENDED),
            ).single()
        assertEquals(dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_PEN, extended.stylusEvent.toolKind)
        assertEquals(STYLUS_PRIMARY_BUTTON, extended.stylusEvent.buttonMask)
        assertEquals(
            dev.vibescreen.protocol.v1.StylusContactState.STYLUS_CONTACT_STATE_CONTACT,
            extended.stylusEvent.contactState,
        )
    }

    @Test
    fun pointerKeyboardAndReleaseRoutesUseStructuralProtocolBatches() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(pointer = true, keyboard = true),
            recorder = recorder,
            firstInputId = 20,
        )

        assertTrue(dispatcher.sendPointer(InputPhase.INPUT_PHASE_BEGAN, 0.2f, 0.3f, NativeInputWire.BUTTON_PRIMARY))
        assertTrue(dispatcher.sendScroll(deltaX = 1.5, deltaY = -2.0))
        assertTrue(dispatcher.sendKey(0x04, pressed = true, modifierMask = NativeInputWire.MODIFIER_SHIFT))
        assertTrue(
            dispatcher.sendNativeInputRelease(
                NativeInputReleasePlan(
                    pressedKeyUsages = listOf(0x04),
                    pointer = NativePointerSnapshot(0.2f, 0.3f),
                ),
                InputPhase.INPUT_PHASE_CANCELLED,
            ),
        )

        assertEquals(
            listOf(
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            ),
            recorder.submissions.map { it.kind },
        )
        val session = streamingSession(Capability.CAPABILITY_POINTER, Capability.CAPABILITY_KEYBOARD)
        assertEquals(20L, recorder.submissions[0].protocolEnvelopes(session).single().pointerEvent.inputId)
        assertEquals(21L, recorder.submissions[1].protocolEnvelopes(session).single().scrollEvent.inputId)
        assertEquals(22L, recorder.submissions[2].protocolEnvelopes(session).single().keyEvent.inputId)
        val release = recorder.submissions[3].protocolEnvelopes(session)
        assertEquals(23L, release[0].keyEvent.inputId)
        assertEquals(false, release[0].keyEvent.pressed)
        assertEquals(24L, release[1].pointerEvent.inputId)
        assertEquals(InputPhase.INPUT_PHASE_CANCELLED, release[1].pointerEvent.phase)
    }

    @Test
    fun nativePointerMoveUsesMoveBatchAndPreservesButtonMask() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(pointer = true),
            recorder = recorder,
            firstInputId = 40,
        )

        assertTrue(dispatcher.sendPointer(InputPhase.INPUT_PHASE_CHANGED, 0.6f, 0.4f, NativeInputWire.BUTTON_PRIMARY))

        val submission = recorder.single()
        assertEquals(OutboundCommandScheduler.Kind.MOVE, submission.kind)
        val pointer = submission.protocolEnvelopes(streamingSession(Capability.CAPABILITY_POINTER)).single().pointerEvent
        assertEquals(40L, pointer.inputId)
        assertEquals(InputPhase.INPUT_PHASE_CHANGED, pointer.phase)
        assertEquals(0.6, pointer.position.x, 0.000001)
        assertEquals(0.4, pointer.position.y, 0.000001)
        assertEquals(NativeInputWire.BUTTON_PRIMARY, pointer.buttonMask)
    }

    @Test
    fun controllerConnectWaitsForAckBeforeStateResync() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        val connectedOnly = recorder.single().protocolEnvelopes(controllerSession)
        assertEquals(listOf(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED), connectedOnly.map { it.controllerEvent.kind })
        assertTrue(tracker.isPending("pad-1", 1))

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertTrue(recorder.submissions[1].protocolEnvelopes(controllerSession).isEmpty())
        assertEquals(ControllerConnection("pad-1", 1), tracker.acknowledge(30))
        assertFalse(tracker.isPending("pad-1", 1))

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        val state = recorder.submissions[2].protocolEnvelopes(controllerSession).single()
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, state.controllerEvent.kind)
        assertEquals(1, state.controllerEvent.buttonMask)
    }

    @Test
    fun rejectedSubmissionPropagatesFalseForStatefulNativeInput() {
        val recorder = RecordingSubmitter(result = OutboundCommandScheduler.Submission.CLOSED)
        val dispatcher = dispatcher(
            state = negotiatedState(pointer = true, keyboard = true, controller = true),
            recorder = recorder,
        )

        assertFalse(dispatcher.sendPointer(InputPhase.INPUT_PHASE_BEGAN, 0.2f, 0.3f, 1))
        assertFalse(dispatcher.sendKey(0x04, pressed = true, modifierMask = 0))
        assertFalse(dispatcher.sendController(controllerDispatch()))
        assertFalse(
            dispatcher.sendNativeInputRelease(
                NativeInputReleasePlan(listOf(0x04), NativePointerSnapshot(0.2f, 0.3f)),
                InputPhase.INPUT_PHASE_ENDED,
            ),
        )
    }

    private fun dispatcher(
        state: StreamInputSessionState,
        recorder: RecordingSubmitter,
        tracker: ControllerConnectionAckTracker = ControllerConnectionAckTracker(),
        firstInputId: Long = 1,
    ) = StreamInputDispatcher(
        state = { state },
        nextInputId = AtomicLong(firstInputId),
        submitOutbound = recorder::submit,
        controllerConnectionAcks = tracker,
    )

    private fun negotiatedState(
        touch: Boolean = false,
        pointer: Boolean = false,
        keyboard: Boolean = false,
        stylus: Boolean = false,
        extendedStylus: Boolean = false,
        controller: Boolean = false,
    ) = StreamInputSessionState(
        connected = true,
        protocolV1 = true,
        canSendTouch = touch,
        canSendPointer = pointer,
        canSendKeyboard = keyboard,
        canSendStylus = stylus,
        canSendExtendedStylus = extendedStylus,
        canSendController = controller,
    )

    private fun stylusSample() =
        StylusSample(
            pointerId = 4,
            phase = InputPhase.INPUT_PHASE_BEGAN,
            x = 0.25,
            y = 0.75,
            pressure = 0.5,
            tiltXDegrees = 10.0,
            tiltYDegrees = -5.0,
            toolKind = StylusToolKind.PEN,
            buttonMask = STYLUS_PRIMARY_BUTTON,
            contactState = StylusContactState.CONTACT,
            delivery = StylusDelivery.STRUCTURAL,
        )

    private fun controllerDispatch() =
        ControllerDispatch(
            samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.STATE)),
            delivery = ControllerDelivery.STRUCTURAL,
        )

    private class RecordingSubmitter(
        private val result: OutboundCommandScheduler.Submission = OutboundCommandScheduler.Submission.ACCEPTED,
    ) {
        data class Submission(
            val kind: OutboundCommandScheduler.Kind,
            val command: StreamOutboundCommand,
            val timeoutMillis: Long,
        ) {
            fun protocolEnvelopes(session: ProtocolV1Session): List<Envelope> =
                (command as StreamOutboundCommand.ProtocolBatch).build(session)
        }

        val submissions = mutableListOf<Submission>()

        fun submit(
            kind: OutboundCommandScheduler.Kind,
            command: StreamOutboundCommand,
            timeoutMillis: Long,
        ): OutboundCommandScheduler.Submission {
            submissions += Submission(kind, command, timeoutMillis)
            return result
        }

        fun single(): Submission {
            assertEquals(1, submissions.size)
            return submissions.single()
        }
    }

    private fun streamingSession(vararg capabilities: Capability): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertiseController = Capability.CAPABILITY_CONTROLLER in capabilities,
            nowNs = { 1_000L },
        ).also { session ->
            session.clientHello()
            session.receive(hostHello(2, capabilities.toList()))
            session.receive(sessionAccepted(3, capabilities.toList()))
            session.receive(displayList(4))
            session.receive(startDisplay(5))
            val requested = session.receive(videoConfig(6)).single() as ProtocolV1Session.Action.VideoConfigurationRequested
            session.completeVideoConfiguration(
                completedConfigEpoch = 3,
                configurationToken = requested.configurationToken,
                accepted = true,
                rejectionReason = "",
            )
        }

    private fun hostHello(id: Long, capabilities: List<Capability>): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setHostHello(
                HostHello
                    .newBuilder()
                    .setSelectedProtocol(1)
                    .addAllCapabilities(capabilities)
                    .addAllCodecs(listOf(Codec.CODEC_HEVC, Codec.CODEC_H264)),
            ).build()

    private fun sessionAccepted(id: Long, capabilities: List<Capability>): Envelope =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionAccepted(
                SessionAccepted
                    .newBuilder()
                    .setSessionId(SESSION_ID)
                    .setSessionEpoch(7)
                    .setHeartbeatIntervalMs(1_000)
                    .addAllNegotiatedCapabilities(capabilities),
            ).build()

    private fun displayList(id: Long): Envelope =
        base(id)
            .setListDisplaysResponse(
                ListDisplaysResponse
                    .newBuilder()
                    .addDisplays(
                        dev.vibescreen.protocol.v1.DisplayDescriptor
                            .newBuilder()
                            .setDisplayId("display-main")
                            .setLogicalSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080)),
                    ),
            ).build()

    private fun startDisplay(id: Long): Envelope =
        base(id)
            .setStartDisplayResponse(
                StartDisplayResponse
                    .newBuilder()
                    .setAccepted(true)
                    .setStreamId(42),
            ).build()

    private fun videoConfig(id: Long): Envelope =
        base(id)
            .setVideoConfig(
                VideoConfig
                    .newBuilder()
                    .setConfigEpoch(3)
                    .setCodec(Codec.CODEC_HEVC)
                    .setEncodedSize(Dimensions.newBuilder().setWidth(1920).setHeight(1080))
                    .setFramesPerSecond(60)
                    .setBitrateKbps(12_000)
                    .setStreamId(42)
                    .setRotationDegrees(90),
            ).build()

    private fun base(id: Long): Envelope.Builder =
        Envelope
            .newBuilder()
            .setProtocolVersion(1)
            .setMessageId(id)
            .setSessionId(SESSION_ID)
            .setSessionEpoch(7)

    private companion object {
        val SESSION_ID = com.google.protobuf.ByteString.copyFrom(byteArrayOf(1, 2, 3, 4))
    }
}
