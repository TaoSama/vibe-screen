package dev.telemachus.display

import dev.telemachus.display.protocol.MotionPointer
import dev.telemachus.display.protocol.TouchSample
import dev.vibescreen.protocol.v1.InputPhase
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
) {
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
        return true
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
        val submission =
            submitOutbound(
                when (dispatch.delivery) {
                    ControllerDelivery.ANALOG -> OutboundCommandScheduler.Kind.CONTROLLER_MOVE
                    ControllerDelivery.STRUCTURAL -> OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL
                },
                StreamOutboundCommand.ProtocolBatch { activeSession ->
                    val pendingConnections =
                        dispatch.samples
                            .filter { it.kind == ControllerEventKind.CONNECTED }
                            .map { ControllerConnection(it.controllerId, it.controllerEpoch) }
                            .toMutableSet()
                    dispatch.samples.mapNotNull { sample ->
                        val connection = ControllerConnection(sample.controllerId, sample.controllerEpoch)
                        if (sample.kind != ControllerEventKind.CONNECTED &&
                            (connection in pendingConnections ||
                                controllerConnectionAcks.isPending(sample.controllerId, sample.controllerEpoch))
                        ) {
                            return@mapNotNull null
                        }
                        val inputId = nextInputId.getAndIncrement()
                        if (sample.kind == ControllerEventKind.CONNECTED) {
                            check(controllerConnectionAcks.recordConnected(inputId, sample.controllerId, sample.controllerEpoch)) {
                                "duplicate controller CONNECTED input id"
                            }
                        } else if (sample.kind == ControllerEventKind.DISCONNECTED) {
                            controllerConnectionAcks.recordDisconnected(sample.controllerId, sample.controllerEpoch)
                        }
                        activeSession.controller(inputId = inputId, sample = sample)
                    }
                },
                0,
            )
        return submission.wasAdmitted()
    }

    fun sendPeripheral(
        peripheralKind: String,
        payload: ByteArray,
    ): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendPeripheral) return false
        if (peripheralKind.isBlank()) return false
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
