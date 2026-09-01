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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger
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
        assertFalse(dispatcher.sendPeripheral("vendor-device", byteArrayOf(0x01)))

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
        assertFalse(dispatcher.sendPeripheral("vendor-device", byteArrayOf(0x01)))

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
    fun rejectedStylusForwardingReportsNotAdmitted() {
        val recorder = RecordingSubmitter(OutboundCommandScheduler.Submission.CLOSED)
        val dispatcher = dispatcher(
            state = negotiatedState(stylus = true, extendedStylus = true),
            recorder = recorder,
        )

        assertFalse(dispatcher.sendMotionStylus(listOf(stylusSample())))

        assertEquals(1, recorder.submissions.size)
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
        assertEquals(1, recorder.submissions.size)
        assertEquals(ControllerConnection("pad-1", 1), tracker.acknowledge(30)?.connection)
        assertFalse(tracker.isPending("pad-1", 1))

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        val state = recorder.submissions[1].protocolEnvelopes(controllerSession).single()
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, state.controllerEvent.kind)
        assertEquals(1, state.controllerEvent.buttonMask)
    }

    @Test
    fun controllerDisconnectDuringPendingConnectionFlushesAfterAcceptedAck() {
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
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        val connectedOnly = recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 1),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        assertEquals(1, recorder.submissions.size)
        assertEquals(listOf(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED), connectedOnly.map { it.controllerEvent.kind })
        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)

        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val cleanup = recorder.submissions[1].protocolEnvelopes(controllerSession).single().controllerEvent
        assertEquals(31L, cleanup.inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, cleanup.kind)
        assertEquals("pad-1", cleanup.controllerId)
        assertEquals(1L, cleanup.controllerEpoch)
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(dispatcher.flushControllerDisconnectCleanup())
        assertEquals(2, recorder.submissions.size)
    }

    @Test
    fun controllerFlushSendsAllReadyDisconnectCleanups() {
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
                            ControllerStateSample("pad-2", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-2", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        val first = requireNotNull(tracker.acknowledge(30))
        val second = requireNotNull(tracker.acknowledge(31))
        tracker.markDisconnectReady(first.connection)
        tracker.markDisconnectReady(second.connection)

        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val cleanup = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(2, cleanup.size)
        assertEquals(listOf(32L, 33L), cleanup.map { it.inputId })
        assertEquals(listOf("pad-1", "pad-2"), cleanup.map { it.controllerId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
            ),
            cleanup.map { it.kind },
        )
        assertFalse(tracker.isPending("pad-1", 1))
        assertFalse(tracker.isPending("pad-2", 1))
    }

    @Test
    fun duplicateDisconnectDuringPendingConnectionKeepsFirstDeferredCleanup() {
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
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val cleanup = recorder.submissions[1].protocolEnvelopes(controllerSession).single().controllerEvent
        assertEquals(31L, cleanup.inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, cleanup.kind)
        assertEquals("pad-1", cleanup.controllerId)
        assertFalse(tracker.isPending("pad-1", 1))
    }

    @Test
    fun controllerAckTimeoutFailsClosedWithoutNewInputAndLateAckCannotFlushCleanup() {
        var now = 100L
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val timedOut = mutableListOf<ControllerConnection>()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            onControllerAckTimeout = { timedOut += it },
            nowMillis = { now },
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(1, recorder.submissions.size)

        now = 100 + CONTROLLER_CONNECTION_ACK_TIMEOUT_MS - 1
        assertFalse(dispatcher.expireControllerAckTimeouts())
        assertTrue(timedOut.isEmpty())
        assertEquals(1, recorder.submissions.size)

        now = 100 + CONTROLLER_CONNECTION_ACK_TIMEOUT_MS
        assertTrue(dispatcher.expireControllerAckTimeouts())
        assertEquals(listOf(ControllerConnection("pad-1", 1)), timedOut)
        assertNull(tracker.acknowledge(30))
        assertFalse(tracker.isPending("pad-1", 1))
        assertFalse(tracker.hasDeferredDisconnectFor("pad-1", 1))
        assertFalse(dispatcher.flushControllerDisconnectCleanup())
        assertEquals(1, recorder.submissions.size)
    }

    @Test
    fun reconnectedControllerEpochWaitsForPendingDisconnectCleanup() {
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
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.STATE),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 2, ControllerEventKind.STATE, buttonMask = 1),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(2, flushed.size)
        assertEquals(listOf(31L, 32L), flushed.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertEquals(listOf(1L, 2L), flushed.map { it.controllerEpoch })
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(tracker.isPending("pad-1", 2))
    }

    @Test
    fun mixedPendingDisconnectAndReconnectBatchDefersReconnectBehindCleanup() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 2, ControllerEventKind.STATE, buttonMask = 1),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        assertEquals(1, recorder.submissions.size)
        assertEquals(1, dispatcher.deferredControllerDispatchCount())

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(2, flushed.size)
        assertEquals(listOf(31L, 32L), flushed.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertEquals(listOf(1L, 2L), flushed.map { it.controllerEpoch })
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(tracker.isPending("pad-1", 2))
    }

    @Test
    fun mixedReconnectAndPendingDisconnectBatchDefersReconnectBehindCleanup() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        assertEquals(1, recorder.submissions.size)
        assertEquals(1, dispatcher.deferredControllerDispatchCount())

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(2, flushed.size)
        assertEquals(listOf(31L, 32L), flushed.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertEquals(listOf(1L, 2L), flushed.map { it.controllerEpoch })
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(tracker.isPending("pad-1", 2))
    }

    @Test
    fun mixedReconnectAndAcknowledgedDisconnectBatchStillSendsDisconnectFirst() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertEquals(ControllerConnection("pad-1", 1), tracker.acknowledge(30)?.connection)
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        val batch = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(2, batch.size)
        assertEquals(listOf(31L, 32L), batch.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            batch.map { it.kind },
        )
        assertEquals(listOf(1L, 2L), batch.map { it.controllerEpoch })
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(tracker.isPending("pad-1", 2))
    }

    @Test
    fun deferredControllerDispatchCapacityAllowsBoundaryAndFailsClosedOnOverflow() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val overflowCount = AtomicInteger()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            maximumDeferredControllerDispatches = 2,
            onControllerDeferredOverflow = { overflowCount.incrementAndGet() },
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(1, recorder.submissions.size)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 2)))
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 3)))
        assertEquals(2, dispatcher.deferredControllerDispatchCount())

        assertFalse(dispatcher.sendController(controllerConnected("pad-1", 4)))

        assertEquals(1, overflowCount.get())
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
        assertFalse(tracker.isPending("pad-1", 1))
        assertNull(tracker.acknowledge(30))
        assertNull(tracker.nextReadyDisconnect())
        assertFalse(tracker.hasDeferredDisconnectBefore("pad-1", 5))
        assertFalse(dispatcher.sendController(controllerConnected("pad-1", 5)))
        assertEquals(1, overflowCount.get())

        dispatcher.resetControllerState()
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 5)))
    }

    @Test
    fun deferredControllerDispatchesFlushRetainedItemsFifoAfterReadyDisconnects() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            maximumDeferredControllerDispatches = 2,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-2", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-2", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 2)))
        assertTrue(dispatcher.sendController(controllerConnected("pad-2", 2)))
        assertEquals(2, dispatcher.deferredControllerDispatchCount())

        val first = requireNotNull(tracker.acknowledge(30))
        val second = requireNotNull(tracker.acknowledge(31))
        tracker.markDisconnectReady(first.connection)
        tracker.markDisconnectReady(second.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(4, flushed.size)
        assertEquals(listOf(32L, 33L, 34L, 35L), flushed.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertEquals(listOf("pad-1", "pad-2", "pad-1", "pad-2"), flushed.map { it.controllerId })
        assertEquals(listOf(1L, 1L, 2L, 2L), flushed.map { it.controllerEpoch })
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
    }

    @Test
    fun deferredAnalogStateBehindReconnectWaitsForAckResync() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            maximumDeferredControllerDispatches = 2,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerConnected("pad-2", 1)))
        recorder.submissions[1].protocolEnvelopes(controllerSession)
        assertEquals(ControllerConnection("pad-2", 1), tracker.acknowledge(31)?.connection)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(2, recorder.submissions.size)
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 2)))
        assertTrue(dispatcher.sendController(controllerState("pad-1", 2, buttonMask = 1)))
        assertTrue(dispatcher.sendController(controllerState("pad-1", 2, buttonMask = 2)))
        recorder.materializeProtocolEnvelopes(controllerSession)
        assertEquals(2, dispatcher.deferredControllerDispatchCount())

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(2, flushed.size)
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertTrue(tracker.isPending("pad-1", 2))
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
    }

    @Test
    fun cleanupDoesNotSendStateBehindNewConnectedBeforeHostAck() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-1", 2, ControllerEventKind.STATE, buttonMask = 7),
                            ControllerStateSample("pad-2", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        val immediate = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(1, immediate.size)
        assertEquals("pad-2", immediate.single().controllerId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, immediate.single().kind)

        val firstAck = requireNotNull(tracker.acknowledge(30))
        assertTrue(firstAck.hasDeferredDisconnect)
        tracker.markDisconnectReady(firstAck.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val cleanup = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(2, cleanup.size)
        assertEquals(listOf("pad-1", "pad-1"), cleanup.map { it.controllerId })
        assertEquals(listOf(1L, 2L), cleanup.map { it.controllerEpoch })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            cleanup.map { it.kind },
        )
        assertTrue(tracker.isPending("pad-1", 2))

        assertEquals(ControllerConnection("pad-1", 2), tracker.acknowledge(cleanup[1].inputId)?.connection)
        assertTrue(dispatcher.sendController(controllerState("pad-1", 2, buttonMask = 7)))
        val resync = recorder.controllerEventBatches(controllerSession).last().single().controllerEvent
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, resync.kind)
        assertEquals(7, resync.buttonMask)
    }

    @Test
    fun stateBeforeSameBatchConnectedWaitsForAckResync() {
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
                            ControllerStateSample("pad-1", 1, ControllerEventKind.STATE, buttonMask = 9),
                            ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        val connectedOnly = recorder.submissions[0].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(1, connectedOnly.size)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, connectedOnly.single().kind)
        assertTrue(tracker.isPending("pad-1", 1))
        assertEquals(0, dispatcher.deferredControllerDispatchCount())

        assertEquals(ControllerConnection("pad-1", 1), tracker.acknowledge(30)?.connection)
        assertTrue(dispatcher.sendController(controllerState("pad-1", 1, buttonMask = 9)))
        val resync = recorder.controllerEventBatches(controllerSession).last().single().controllerEvent
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_STATE, resync.kind)
        assertEquals(9, resync.buttonMask)
    }

    @Test
    fun disconnectedAckRaceAfterPendingCheckStillSendsDisconnectOnWire() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        var acknowledgedDuringPendingCheck = false
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            afterPendingNonConnectedDetected = { sample ->
                if (sample.kind == ControllerEventKind.DISCONNECTED && !acknowledgedDuringPendingCheck) {
                    val acknowledgement = requireNotNull(tracker.acknowledge(30))
                    assertFalse(acknowledgement.hasDeferredDisconnect)
                    acknowledgedDuringPendingCheck = true
                }
            },
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)

        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))

        assertTrue(acknowledgedDuringPendingCheck)
        val disconnect = recorder.submissions[1].protocolEnvelopes(controllerSession).single().controllerEvent
        assertEquals(31L, disconnect.inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED, disconnect.kind)
        assertEquals("pad-1", disconnect.controllerId)
        assertEquals(1L, disconnect.controllerEpoch)
        assertFalse(tracker.isPending("pad-1", 1))
        assertFalse(tracker.hasDeferredDisconnectFor("pad-1", 1))
    }

    @Test
    fun deferredDisconnectDoesNotBlockOtherControllerAndUsesActualSendOrderInputIds() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(1, recorder.submissions.size)
        assertTrue(dispatcher.sendController(controllerConnected("pad-2", 1)))
        recorder.materializeProtocolEnvelopes(controllerSession)
        val immediate = recorder.controllerEventBatches(controllerSession)
        assertEquals(2, immediate.size)
        assertEquals(listOf("pad-1", "pad-2"), immediate.map { it.single().controllerEvent.controllerId })
        assertEquals(listOf(30L, 31L), immediate.map { it.single().controllerEvent.inputId })
        assertEquals(0, dispatcher.deferredControllerDispatchCount())

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        assertTrue(acknowledgement.hasDeferredDisconnect)
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(1, flushed.size)
        assertEquals(listOf(32L), flushed.map { it.inputId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
            ),
            flushed.map { it.kind },
        )
        assertEquals(listOf("pad-1"), flushed.map { it.controllerId })
    }

    @Test
    fun mixedDispatchSendsFreeControllerBeforeBlockedReconnect() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(1, recorder.submissions.size)

        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-2", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        val immediate = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(1, immediate.size)
        assertEquals("pad-2", immediate.single().controllerId)
        assertEquals(31L, immediate.single().inputId)
        assertEquals(1, dispatcher.deferredControllerDispatchCount())

        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        assertTrue(acknowledgement.hasDeferredDisconnect)
        tracker.markDisconnectReady(acknowledgement.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(2, flushed.size)
        assertEquals(listOf(32L, 33L), flushed.map { it.inputId })
        assertEquals(listOf("pad-1", "pad-1"), flushed.map { it.controllerId })
        assertEquals(
            listOf(
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_DISCONNECTED,
                dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED,
            ),
            flushed.map { it.kind },
        )
    }

    @Test
    fun partiallyUnblockedDeferredDispatchSendsReadyControllerAndLeavesBlockedPeerQueued() {
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
                            ControllerStateSample("pad-a", 1, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-b", 1, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-a", 1, ControllerEventKind.DISCONNECTED),
                            ControllerStateSample("pad-b", 1, ControllerEventKind.DISCONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples =
                        listOf(
                            ControllerStateSample("pad-a", 2, ControllerEventKind.CONNECTED),
                            ControllerStateSample("pad-b", 2, ControllerEventKind.CONNECTED),
                        ),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        assertEquals(1, dispatcher.deferredControllerDispatchCount())

        val firstAck = requireNotNull(tracker.acknowledge(30))
        assertTrue(firstAck.hasDeferredDisconnect)
        tracker.markDisconnectReady(firstAck.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val firstFlush = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(listOf("pad-a", "pad-a"), firstFlush.map { it.controllerId })
        assertEquals(listOf(1L, 2L), firstFlush.map { it.controllerEpoch })
        assertEquals(1, dispatcher.deferredControllerDispatchCount())
        assertTrue(tracker.isPending("pad-b", 1))
        assertTrue(tracker.isPending("pad-a", 2))

        val secondAck = requireNotNull(tracker.acknowledge(31))
        assertTrue(secondAck.hasDeferredDisconnect)
        tracker.markDisconnectReady(secondAck.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val secondFlush = recorder.controllerEventBatches(controllerSession).last().map { it.controllerEvent }
        assertEquals(listOf("pad-b", "pad-b"), secondFlush.map { it.controllerId })
        assertEquals(listOf(1L, 2L), secondFlush.map { it.controllerEpoch })
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
        assertTrue(tracker.isPending("pad-b", 2))
    }

    @Test
    fun deferredOverflowDuringPrepareReturnsFalseAndCleansState() {
        val tracker = ControllerConnectionAckTracker()
        val overflowCount = AtomicInteger()
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            maximumDeferredControllerDispatches = 1,
            onControllerDeferredOverflow = { overflowCount.incrementAndGet() },
        )
        assertTrue(tracker.recordConnected(20, "pad-1", 1, nowMillis = 100))
        assertTrue(tracker.deferDisconnected("pad-1", 1))
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 3)))
        assertEquals(1, dispatcher.deferredControllerDispatchCount())

        assertFalse(dispatcher.sendController(controllerConnected("pad-1", 2)))

        assertEquals(1, overflowCount.get())
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
        assertFalse(tracker.isPending("pad-1", 1))
        assertFalse(tracker.hasDeferredDisconnectBefore("pad-1", 2))
    }

    @Test
    fun deferredControllerOverflowClearsStaleEpochReplacementState() {
        val recorder = RecordingSubmitter()
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
            maximumDeferredControllerDispatches = 1,
        )
        val controllerSession = streamingSession(Capability.CAPABILITY_CONTROLLER)

        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 1)))
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(dispatcher.sendController(controllerDisconnected("pad-1", 1)))
        assertEquals(1, recorder.submissions.size)
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 2)))
        assertFalse(dispatcher.sendController(controllerConnected("pad-1", 3)))

        assertFalse(tracker.hasDeferredDisconnectBefore("pad-1", 4))
        assertFalse(tracker.isPending("pad-1", 1))
        assertEquals(0, dispatcher.deferredControllerDispatchCount())

        assertFalse(dispatcher.sendController(controllerConnected("pad-1", 4)))

        dispatcher.resetControllerState()
        assertTrue(dispatcher.sendController(controllerConnected("pad-1", 4)))

        val replacement = recorder.submissions[1].protocolEnvelopes(controllerSession).single().controllerEvent
        assertEquals(31L, replacement.inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, replacement.kind)
        assertEquals(4L, replacement.controllerEpoch)
        assertTrue(tracker.isPending("pad-1", 4))
    }

    @Test
    fun rejectedPendingConnectionAckReplaysDeferredReplacementWithoutCleanup() {
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
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)

        assertEquals(ControllerConnection("pad-1", 1), tracker.acknowledge(30)?.connection)
        assertTrue(dispatcher.flushControllerDisconnectCleanup())

        val flushed = recorder.submissions[1].protocolEnvelopes(controllerSession).map { it.controllerEvent }
        assertEquals(1, flushed.size)
        assertEquals(31L, flushed.single().inputId)
        assertEquals(dev.vibescreen.protocol.v1.ControllerEventKind.CONTROLLER_EVENT_KIND_CONNECTED, flushed.single().kind)
        assertEquals(2L, flushed.single().controllerEpoch)
        assertFalse(tracker.isPending("pad-1", 1))
        assertTrue(tracker.isPending("pad-1", 2))
    }

    @Test
    fun controllerResetClearsDeferredReplacementDispatches() {
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
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        recorder.submissions[0].protocolEnvelopes(controllerSession)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 1, ControllerEventKind.DISCONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )
        assertEquals(1, recorder.submissions.size)
        assertTrue(
            dispatcher.sendController(
                ControllerDispatch(
                    samples = listOf(ControllerStateSample("pad-1", 2, ControllerEventKind.CONNECTED)),
                    delivery = ControllerDelivery.STRUCTURAL,
                ),
            ),
        )

        tracker.reset()
        dispatcher.resetControllerState()

        assertTrue(dispatcher.flushControllerDisconnectCleanup())
        assertEquals(1, recorder.submissions.size)
        assertEquals(0, dispatcher.deferredControllerDispatchCount())
        assertFalse(tracker.isPending("pad-1", 1))
        assertFalse(tracker.isPending("pad-1", 2))
    }

    @Test
    fun controllerCleanupBackpressurePreservesReadyDisconnect() {
        val recorder = RecordingSubmitter(OutboundCommandScheduler.Submission.TIMED_OUT)
        val tracker = ControllerConnectionAckTracker()
        val dispatcher = dispatcher(
            state = negotiatedState(controller = true),
            recorder = recorder,
            tracker = tracker,
            firstInputId = 30,
        )

        assertTrue(tracker.recordConnected(30, "pad-1", 1, nowMillis = 100))
        assertTrue(tracker.deferDisconnected("pad-1", 1))
        val acknowledgement = requireNotNull(tracker.acknowledge(30))
        tracker.markDisconnectReady(acknowledgement.connection)

        assertFalse(dispatcher.flushControllerDisconnectCleanup())

        assertEquals(DeferredControllerDisconnect(ControllerConnection("pad-1", 1)), tracker.nextReadyDisconnect())
        assertTrue(recorder.submissions.isNotEmpty())
    }

    @Test
    fun peripheralInputUsesStructuralProtocolBatchOnlyAfterNegotiation() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(peripheral = true),
            recorder = recorder,
            firstInputId = 50,
        )

        assertTrue(dispatcher.sendPeripheral("vendor-device", byteArrayOf(0x01, 0x02)))

        val submission = recorder.single()
        assertEquals(OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH, submission.kind)
        val event = submission.protocolEnvelopes(
            streamingSession(Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK),
        ).single().peripheralEvent
        assertEquals(50L, event.inputId)
        assertEquals("vendor-device", event.peripheralKind)
        assertEquals(listOf(0x01.toByte(), 0x02.toByte()), event.payload.toByteArray().toList())
    }

    @Test
    fun peripheralInputRejectsInvalidEnvelopeBeforeWireSubmission() {
        val recorder = RecordingSubmitter()
        val dispatcher = dispatcher(
            state = negotiatedState(peripheral = true),
            recorder = recorder,
        )

        assertFalse(dispatcher.sendPeripheral(" ", byteArrayOf(0x01)))
        assertFalse(dispatcher.sendPeripheral(String(CharArray(129) { 'a' }), byteArrayOf(0x01)))
        assertFalse(dispatcher.sendPeripheral("vendor-device", ByteArray(64 * 1_024 + 1)))

        assertTrue(recorder.submissions.isEmpty())
    }

    @Test
    fun rejectedSubmissionPropagatesFalseForStatefulNativeInput() {
        val recorder = RecordingSubmitter(result = OutboundCommandScheduler.Submission.CLOSED)
        val dispatcher = dispatcher(
            state = negotiatedState(pointer = true, keyboard = true, controller = true, peripheral = true),
            recorder = recorder,
        )

        assertFalse(dispatcher.sendPointer(InputPhase.INPUT_PHASE_BEGAN, 0.2f, 0.3f, 1))
        assertFalse(dispatcher.sendKey(0x04, pressed = true, modifierMask = 0))
        assertFalse(dispatcher.sendController(controllerDispatch()))
        assertFalse(dispatcher.sendPeripheral("vendor-device", byteArrayOf(0x01)))
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
        maximumDeferredControllerDispatches: Int = MAXIMUM_CONTROLLER_STRUCTURAL_BATCHES,
        onControllerDeferredOverflow: () -> Unit = {},
        onControllerAckTimeout: (List<ControllerConnection>) -> Unit = {},
        nowMillis: () -> Long = { 100 },
        afterPendingNonConnectedDetected: (ControllerStateSample) -> Unit = {},
    ) = StreamInputDispatcher(
        state = { state },
        nextInputId = AtomicLong(firstInputId),
        submitOutbound = recorder::submit,
        controllerConnectionAcks = tracker,
        maximumDeferredControllerDispatches = maximumDeferredControllerDispatches,
        onControllerDeferredOverflow = onControllerDeferredOverflow,
        onControllerAckTimeout = onControllerAckTimeout,
        nowMillis = nowMillis,
        afterPendingNonConnectedDetected = afterPendingNonConnectedDetected,
    )

    private fun negotiatedState(
        touch: Boolean = false,
        pointer: Boolean = false,
        keyboard: Boolean = false,
        stylus: Boolean = false,
        extendedStylus: Boolean = false,
        controller: Boolean = false,
        peripheral: Boolean = false,
    ) = StreamInputSessionState(
        connected = true,
        protocolV1 = true,
        canSendTouch = touch,
        canSendPointer = pointer,
        canSendKeyboard = keyboard,
        canSendStylus = stylus,
        canSendExtendedStylus = extendedStylus,
        canSendController = controller,
        canSendPeripheral = peripheral,
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

    private fun controllerConnected(
        controllerId: String,
        epoch: Long,
    ) = ControllerDispatch(
        samples = listOf(ControllerStateSample(controllerId, epoch, ControllerEventKind.CONNECTED)),
        delivery = ControllerDelivery.STRUCTURAL,
    )

    private fun controllerDisconnected(
        controllerId: String,
        epoch: Long,
    ) = ControllerDispatch(
        samples = listOf(ControllerStateSample(controllerId, epoch, ControllerEventKind.DISCONNECTED)),
        delivery = ControllerDelivery.STRUCTURAL,
    )

    private fun controllerState(
        controllerId: String,
        epoch: Long,
        buttonMask: Int,
    ) = ControllerDispatch(
        samples = listOf(ControllerStateSample(controllerId, epoch, ControllerEventKind.STATE, buttonMask = buttonMask)),
        delivery = ControllerDelivery.ANALOG,
    )

    private class RecordingSubmitter(
        private val result: OutboundCommandScheduler.Submission = OutboundCommandScheduler.Submission.ACCEPTED,
        private val protocolBuildSession: ProtocolV1Session? = null,
        private val beforeProtocolBuild: () -> Unit = {},
    ) {
        data class Submission(
            val kind: OutboundCommandScheduler.Kind,
            val command: StreamOutboundCommand,
            val timeoutMillis: Long,
        ) {
            private val cachedEnvelopesBySession = mutableMapOf<ProtocolV1Session, List<Envelope>>()

            fun protocolEnvelopes(session: ProtocolV1Session): List<Envelope> =
                cachedEnvelopesBySession.getOrPut(session) {
                    (command as StreamOutboundCommand.ProtocolBatch).build(session)
                }
        }

        val submissions = mutableListOf<Submission>()

        fun submit(
            kind: OutboundCommandScheduler.Kind,
            command: StreamOutboundCommand,
            timeoutMillis: Long,
        ): OutboundCommandScheduler.Submission {
            submissions += Submission(kind, command, timeoutMillis)
            val session = protocolBuildSession
            if (session != null && command is StreamOutboundCommand.ProtocolBatch) {
                beforeProtocolBuild()
                submissions.last().protocolEnvelopes(session)
            }
            return result
        }

        fun single(): Submission {
            assertEquals(1, submissions.size)
            return submissions.single()
        }

        fun controllerEventBatches(session: ProtocolV1Session): List<List<Envelope>> =
            submissions
                .map { it.protocolEnvelopes(session) }
                .filter { envelopes -> envelopes.any { it.hasControllerEvent() } }

        fun materializeProtocolEnvelopes(session: ProtocolV1Session) {
            submissions.forEach { submission ->
                if (submission.command is StreamOutboundCommand.ProtocolBatch) {
                    submission.protocolEnvelopes(session)
                }
            }
        }
    }

    private fun streamingSession(vararg capabilities: Capability): ProtocolV1Session =
        ProtocolV1Session(
            deviceId = "android-test",
            deviceName = "Test Android",
            transport = TransportKind.TRANSPORT_KIND_USB,
            codecs = listOf(Codec.CODEC_HEVC, Codec.CODEC_H264),
            advertiseController = Capability.CAPABILITY_CONTROLLER in capabilities,
            advertisePeripheralInputFramework = Capability.CAPABILITY_PERIPHERAL_INPUT_FRAMEWORK in capabilities,
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
