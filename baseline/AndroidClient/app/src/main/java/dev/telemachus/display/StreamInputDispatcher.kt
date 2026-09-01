package dev.telemachus.display

import dev.telemachus.display.protocol.MotionPointer
import dev.telemachus.display.protocol.ProtocolV1Session
import dev.telemachus.display.protocol.TouchSample
import dev.vibescreen.protocol.v1.InputPhase
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicLong

internal data class StreamInputSessionState(
    val connected: Boolean,
    val protocolV1: Boolean,
    val canSendTouch: Boolean = false,
    val canSendPointer: Boolean = false,
    val canSendKeyboard: Boolean = false,
    val canSendStylus: Boolean = false,
    val canSendExtendedStylus: Boolean = false,
    val canSendController: Boolean = false,
    val canSendPeripheral: Boolean = false,
)

internal class StreamInputDispatcher(
    private val state: () -> StreamInputSessionState,
    private val nextInputId: AtomicLong,
    private val submitOutbound:
        (OutboundCommandScheduler.Kind, StreamOutboundCommand, Long) -> OutboundCommandScheduler.Submission,
    private val controllerConnectionAcks: ControllerConnectionAckTracker,
    private val maximumDeferredControllerDispatches: Int = MAXIMUM_CONTROLLER_STRUCTURAL_BATCHES,
    private val onControllerDeferredOverflow: () -> Unit = {},
) {
    init {
        require(maximumDeferredControllerDispatches > 0) { "maximumDeferredControllerDispatches must be positive" }
    }

    private val controllerDispatchLock = Any()
    private val deferredControllerDispatches = ArrayDeque<ControllerDispatch>()
    private var controllerDeferredOverflowed = false

    fun sendTouch(
        x: Float,
        y: Float,
        action: Int,
        pointerCount: Int = 1,
        x2: Float = 0f,
        y2: Float = 0f,
    ) {
        val phase =
            when (action) {
                0 -> InputPhase.INPUT_PHASE_BEGAN
                1 -> InputPhase.INPUT_PHASE_CHANGED
                2 -> InputPhase.INPUT_PHASE_ENDED
                else -> InputPhase.INPUT_PHASE_CANCELLED
            }
        val legacyPointers =
            buildList {
                add(MotionPointer(0, x.toDouble(), y.toDouble()))
                if (pointerCount.coerceIn(1, MAX_FORWARDED_POINTERS) == MAX_FORWARDED_POINTERS) {
                    add(MotionPointer(1, x2.toDouble(), y2.toDouble()))
                }
            }
        sendMotionTouch(
            v1Samples = legacyPointers.map { TouchSample(it.pointerId, phase, it.x, it.y) },
            legacyAction = action,
            legacyPointers = legacyPointers,
        )
    }

    fun sendMotionTouch(
        v1Samples: List<TouchSample>,
        legacyAction: Int,
        legacyPointers: List<MotionPointer>,
    ) {
        val current = state()
        if (!current.connected) return
        if (current.protocolV1) {
            if (!current.canSendTouch) return
            val samples = v1Samples.toList()
            if (samples.isEmpty()) return
            submitOutbound(
                if (samples.all { it.phase == InputPhase.INPUT_PHASE_CHANGED }) {
                    OutboundCommandScheduler.Kind.MOVE
                } else {
                    OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
                },
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    samples.map { sample ->
                        activeSession.touch(
                            inputId = nextInputId.getAndIncrement(),
                            pointerId = sample.pointerId,
                            phase = sample.phase,
                            x = sample.x,
                            y = sample.y,
                        )
                    }
                },
                0,
            )
            return
        }

        val points = legacyPointers.take(MAX_FORWARDED_POINTERS)
        if (points.isEmpty()) return
        val first = points.first()
        val second = points.getOrNull(1)
        submitOutbound(
            if (legacyAction == TOUCH_ACTION_MOVE) {
                OutboundCommandScheduler.Kind.MOVE
            } else {
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
            },
            StreamOutboundCommand.Touch(
                first.x.toFloat(),
                first.y.toFloat(),
                legacyAction,
                points.size,
                second?.x?.toFloat() ?: 0f,
                second?.y?.toFloat() ?: 0f,
            ),
            0,
        )
    }

    fun canSendStylus(): Boolean = state().let { it.connected && it.protocolV1 && it.canSendStylus }

    fun canSendExtendedStylus(): Boolean = state().let { it.connected && it.protocolV1 && it.canSendExtendedStylus }

    fun sendMotionStylus(samples: List<StylusSample>): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendStylus) return false
        val copied = samples.toList()
        if (copied.isEmpty()) return false
        val submission =
            submitOutbound(
                if (copied.all { it.delivery == StylusDelivery.MOTION }) {
                    OutboundCommandScheduler.Kind.MOVE
                } else {
                    OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
                },
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    copied.map { sample ->
                        activeSession.stylus(
                            inputId = nextInputId.getAndIncrement(),
                            pointerId = sample.pointerId,
                            phase = sample.phase,
                            x = sample.x,
                            y = sample.y,
                            pressure = sample.pressure,
                            tiltXDegrees = sample.tiltXDegrees,
                            tiltYDegrees = sample.tiltYDegrees,
                            toolKind =
                                if (activeSession.canSendExtendedStylus) {
                                    sample.toolKind.toProtocol()
                                } else {
                                    null
                                },
                            buttonMask = if (activeSession.canSendExtendedStylus) sample.buttonMask else 0,
                            contactState =
                                if (activeSession.canSendExtendedStylus) {
                                    sample.contactState.toProtocol()
                                } else {
                                    null
                                },
                        )
                    }
                },
                0,
            )
        val admitted = submission.wasAdmitted()
        return admitted
    }

    fun sendPointer(
        phase: InputPhase,
        x: Float,
        y: Float,
        buttonMask: Int,
    ): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendPointer) return false
        val submission =
            submitOutbound(
                if (phase == InputPhase.INPUT_PHASE_CHANGED) {
                    OutboundCommandScheduler.Kind.MOVE
                } else {
                    OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
                },
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    listOf(
                        activeSession.pointer(
                            inputId = nextInputId.getAndIncrement(),
                            phase = phase,
                            x = x.toDouble(),
                            y = y.toDouble(),
                            buttonMask = buttonMask,
                        ),
                    )
                },
                0,
            )
        return submission.wasAdmitted()
    }

    fun sendScroll(
        deltaX: Double,
        deltaY: Double,
    ): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendPointer) return false
        submitOutbound(
            // Scroll deltas are incremental and must not be coalesced with pointer moves.
            OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
            StreamOutboundCommand.ProtocolBatch { activeSession ->
                listOf(
                    activeSession.scroll(
                        inputId = nextInputId.getAndIncrement(),
                        deltaX = deltaX,
                        deltaY = deltaY,
                    ),
                )
            },
            0,
        )
        return true
    }

    fun sendKey(
        usbHidUsage: Int,
        pressed: Boolean,
        modifierMask: Int,
    ): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendKeyboard) return false
        val submission =
            submitOutbound(
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    listOf(
                        activeSession.key(
                            inputId = nextInputId.getAndIncrement(),
                            usbHidUsage = usbHidUsage,
                            pressed = pressed,
                            modifierMask = modifierMask,
                        ),
                    )
                },
                0,
            )
        return submission.wasAdmitted()
    }

    fun sendNativeInputRelease(
        release: NativeInputReleasePlan,
        pointerPhase: InputPhase,
    ): Boolean {
        require(pointerPhase == InputPhase.INPUT_PHASE_ENDED || pointerPhase == InputPhase.INPUT_PHASE_CANCELLED)
        if (release.isEmpty) return true
        val current = state()
        if (!current.connected || !current.protocolV1) return false
        if (release.pressedKeyUsages.isNotEmpty() && !current.canSendKeyboard) return false
        if (release.pointer != null && !current.canSendPointer) return false
        val submission =
            submitOutbound(
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    NativeInputReleaseBatch.build(
                        release = release,
                        keyUp = { usage ->
                            activeSession.key(
                                inputId = nextInputId.getAndIncrement(),
                                usbHidUsage = usage,
                                pressed = false,
                                modifierMask = 0,
                            )
                        },
                        pointerTerminal = { pointer ->
                            activeSession.pointer(
                                inputId = nextInputId.getAndIncrement(),
                                phase = pointerPhase,
                                x = pointer.x.toDouble(),
                                y = pointer.y.toDouble(),
                                buttonMask = 0,
                            )
                        },
                    )
                },
                0,
            )
        return submission.wasAdmitted()
    }

    fun sendController(dispatch: ControllerDispatch): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendController) return false
        if (hasControllerDeferredOverflowed()) return false
        if (shouldDeferControllerDispatch(dispatch)) {
            if (!enqueueDeferredControllerDispatch(dispatch)) return failControllerDeferredOverflow()
            flushControllerDisconnectCleanup()
            return true
        }
        val submission = submitControllerDispatch(dispatch)
        return submission.wasAdmitted() && !hasControllerDeferredOverflowed()
    }

    private fun submitControllerDispatch(dispatch: ControllerDispatch): OutboundCommandScheduler.Submission {
        val submission =
            submitOutbound(
                when (dispatch.delivery) {
                    ControllerDelivery.ANALOG -> OutboundCommandScheduler.Kind.CONTROLLER_MOVE
                    ControllerDelivery.STRUCTURAL -> OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL
                },
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    if (hasControllerDeferredOverflowed()) {
                        emptyList()
                    } else if (shouldDeferControllerDispatch(dispatch)) {
                        if (!enqueueDeferredControllerDispatch(dispatch)) failControllerDeferredOverflow()
                        emptyList()
                    } else {
                        buildControllerEnvelopes(activeSession, dispatch)
                    }
                },
                0,
            )
        return submission
    }

    fun flushControllerDisconnectCleanup(): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendController) return false
        if (hasControllerDeferredOverflowed()) return false
        if (!hasFlushableControllerWork()) return true
        val submission =
            submitOutbound(
                OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL,
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    buildControllerDisconnectCleanupEnvelopes(activeSession)
                },
                0,
            )
        return submission.wasAdmitted()
    }

    fun resetControllerState() {
        synchronized(controllerDispatchLock) {
            deferredControllerDispatches.clear()
            controllerDeferredOverflowed = false
        }
    }

    internal fun deferredControllerDispatchCount(): Int =
        synchronized(controllerDispatchLock) { deferredControllerDispatches.size }

    private fun buildControllerEnvelopes(
        activeSession: ProtocolV1Session,
        dispatch: ControllerDispatch,
    ): List<dev.vibescreen.protocol.v1.Envelope> {
        val connectedInBatch =
            dispatch.samples
                .filter { it.kind == ControllerEventKind.CONNECTED }
                .map { ControllerConnection(it.controllerId, it.controllerEpoch) }
                .toSet()
        val seenConnectedInBatch = mutableSetOf<ControllerConnection>()
        val envelopes = mutableListOf<dev.vibescreen.protocol.v1.Envelope>()
        val deferredSamples = mutableListOf<ControllerStateSample>()
        var deferringRemainder = false
        for ((index, sample) in dispatch.samples.withIndex()) {
            val connection = ControllerConnection(sample.controllerId, sample.controllerEpoch)
            val hasDeferredDisconnects = controllerConnectionAcks.hasDeferredDisconnects()
            if (deferringRemainder || hasDeferredDisconnects) {
                if (sample.kind != ControllerEventKind.CONNECTED && controllerConnectionAcks.isPending(sample.controllerId, sample.controllerEpoch)) {
                    if (!deferPendingControllerDisconnect(sample)) {
                        // STATE is recovered by an ACK-triggered full-state resync.
                    }
                } else {
                    deferredSamples += sample
                }
                continue
            }
            if (controllerConnectionAcks.hasDeferredDisconnectBefore(sample.controllerId, sample.controllerEpoch)) {
                deferringRemainder = true
                deferredSamples += sample
                continue
            }
            if (ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(dispatch.samples, index, sample)) {
                deferredSamples += sample
                continue
            }
            val isPendingConnection =
                connection in seenConnectedInBatch ||
                    controllerConnectionAcks.isPending(sample.controllerId, sample.controllerEpoch)
            if (sample.kind != ControllerEventKind.CONNECTED && isPendingConnection) {
                if (!deferPendingControllerDisconnect(sample)) {
                    // STATE is recovered by an ACK-triggered full-state resync.
                } else {
                    deferringRemainder = true
                }
                continue
            }
            if (sample.kind != ControllerEventKind.CONNECTED && connection in connectedInBatch && connection !in seenConnectedInBatch) {
                continue
            }
            val inputId = nextInputId.getAndIncrement()
            if (sample.kind == ControllerEventKind.CONNECTED) {
                check(controllerConnectionAcks.recordConnected(inputId, sample.controllerId, sample.controllerEpoch)) {
                    "duplicate controller CONNECTED input id"
                }
                seenConnectedInBatch += connection
            } else if (sample.kind == ControllerEventKind.DISCONNECTED) {
                controllerConnectionAcks.recordDisconnected(sample.controllerId, sample.controllerEpoch)
            }
            envelopes += activeSession.controller(inputId = inputId, sample = sample)
        }
        if (deferredSamples.isNotEmpty()) {
            val deferredDispatch = dispatch.copy(samples = deferredSamples)
            if (controllerConnectionAcks.hasDeferredDisconnects() || isBlockedByDeferredDisconnect(deferredDispatch)) {
                if (!enqueueDeferredControllerDispatch(deferredDispatch)) {
                    failControllerDeferredOverflow()
                    return emptyList()
                }
            } else {
                envelopes += buildControllerEnvelopes(activeSession, deferredDispatch)
            }
        }
        return envelopes
    }

    private fun deferPendingControllerDisconnect(sample: ControllerStateSample): Boolean {
        if (sample.kind != ControllerEventKind.DISCONNECTED) return false
        if (!controllerConnectionAcks.isPending(sample.controllerId, sample.controllerEpoch)) return false
        controllerConnectionAcks.deferDisconnected(
            nextInputId.getAndIncrement(),
            sample.controllerId,
            sample.controllerEpoch,
        )
        return true
    }

    private fun buildControllerDisconnectCleanupEnvelopes(
        activeSession: ProtocolV1Session,
    ): List<dev.vibescreen.protocol.v1.Envelope> {
        val envelopes = mutableListOf<dev.vibescreen.protocol.v1.Envelope>()
        while (true) {
            val disconnect = controllerConnectionAcks.nextReadyDisconnect() ?: break
            val sample =
                ControllerStateSample(
                    controllerId = disconnect.connection.controllerId,
                    controllerEpoch = disconnect.connection.controllerEpoch,
                    kind = ControllerEventKind.DISCONNECTED,
                )
            envelopes += activeSession.controller(inputId = disconnect.inputId, sample = sample)
            controllerConnectionAcks.recordDisconnected(sample.controllerId, sample.controllerEpoch)
        }
        while (true) {
            val dispatch = pollUnblockedDeferredControllerDispatch() ?: break
            envelopes += buildControllerEnvelopes(activeSession, dispatch)
        }
        return envelopes
    }

    private fun shouldDeferControllerDispatch(dispatch: ControllerDispatch): Boolean =
        hasDeferredControllerDispatches() || dispatch.samples.any { sample ->
            controllerConnectionAcks.hasDeferredDisconnectBefore(sample.controllerId, sample.controllerEpoch)
        }

    private fun hasFlushableControllerWork(): Boolean =
        controllerConnectionAcks.nextReadyDisconnect() != null ||
            synchronized(controllerDispatchLock) {
                deferredControllerDispatches.firstOrNull()?.let { !isBlockedByDeferredDisconnect(it) } == true
            }

    private fun hasDeferredControllerDispatches(): Boolean =
        synchronized(controllerDispatchLock) { deferredControllerDispatches.isNotEmpty() }

    private fun hasControllerDeferredOverflowed(): Boolean =
        synchronized(controllerDispatchLock) { controllerDeferredOverflowed }

    private fun enqueueDeferredControllerDispatch(dispatch: ControllerDispatch): Boolean =
        synchronized(controllerDispatchLock) {
            if (tryReplaceTrailingDeferredAnalogDispatch(dispatch)) return@synchronized true
            if (deferredControllerDispatches.size >= maximumDeferredControllerDispatches) return@synchronized false
            deferredControllerDispatches.addLast(dispatch)
            true
        }

    private fun tryReplaceTrailingDeferredAnalogDispatch(dispatch: ControllerDispatch): Boolean {
        if (dispatch.delivery != ControllerDelivery.ANALOG || dispatch.samples.isEmpty()) return false
        val trailing = deferredControllerDispatches.lastOrNull() ?: return false
        if (trailing.delivery != ControllerDelivery.ANALOG) return false
        if (trailing.samples.isEmpty()) return false
        val trailingConnections = trailing.samples.map { ControllerConnection(it.controllerId, it.controllerEpoch) }.toSet()
        val replacementConnections = dispatch.samples.map { ControllerConnection(it.controllerId, it.controllerEpoch) }.toSet()
        if (trailingConnections != replacementConnections) return false
        deferredControllerDispatches.removeLast()
        deferredControllerDispatches.addLast(dispatch)
        return true
    }

    private fun failControllerDeferredOverflow(): Boolean {
        synchronized(controllerDispatchLock) {
            deferredControllerDispatches.clear()
            controllerDeferredOverflowed = true
        }
        controllerConnectionAcks.reset()
        onControllerDeferredOverflow()
        return false
    }

    private fun pollUnblockedDeferredControllerDispatch(): ControllerDispatch? =
        synchronized(controllerDispatchLock) {
            val dispatch = deferredControllerDispatches.firstOrNull() ?: return@synchronized null
            if (isBlockedByDeferredDisconnect(dispatch)) return@synchronized null
            deferredControllerDispatches.removeFirst()
        }

    private fun isBlockedByDeferredDisconnect(dispatch: ControllerDispatch): Boolean =
        dispatch.samples.any { sample ->
            controllerConnectionAcks.hasDeferredDisconnectBefore(sample.controllerId, sample.controllerEpoch)
        }

    fun sendPeripheral(
        peripheralKind: String,
        payload: ByteArray,
    ): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendPeripheral) return false
        val kindBytes = peripheralKind.toByteArray(StandardCharsets.UTF_8)
        if (peripheralKind.isBlank() || kindBytes.size > ProtocolV1Session.MAX_PERIPHERAL_KIND_BYTES) return false
        if (payload.size > ProtocolV1Session.MAX_PERIPHERAL_PAYLOAD_BYTES) return false
        val submission =
            submitOutbound(
                OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH,
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    listOf(
                        activeSession.peripheral(
                            inputId = nextInputId.getAndIncrement(),
                            peripheralKind = peripheralKind,
                            payload = payload,
                        ),
                    )
                },
                0,
            )
        return submission.wasAdmitted()
    }

    private fun StylusToolKind.toProtocol(): dev.vibescreen.protocol.v1.StylusToolKind =
        when (this) {
            StylusToolKind.PEN -> dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_PEN
            StylusToolKind.ERASER -> dev.vibescreen.protocol.v1.StylusToolKind.STYLUS_TOOL_KIND_ERASER
        }

    private fun StylusContactState.toProtocol(): dev.vibescreen.protocol.v1.StylusContactState =
        when (this) {
            StylusContactState.CONTACT -> dev.vibescreen.protocol.v1.StylusContactState.STYLUS_CONTACT_STATE_CONTACT
            StylusContactState.PROXIMITY -> dev.vibescreen.protocol.v1.StylusContactState.STYLUS_CONTACT_STATE_PROXIMITY
        }

    private fun OutboundCommandScheduler.Submission.wasAdmitted(): Boolean =
        this != OutboundCommandScheduler.Submission.TIMED_OUT &&
            this != OutboundCommandScheduler.Submission.CLOSED

    private companion object {
        const val MAX_FORWARDED_POINTERS = 2
        const val TOUCH_ACTION_MOVE = 1
    }
}
