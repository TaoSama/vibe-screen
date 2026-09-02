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
    private val onControllerAckTimeout: (List<ControllerConnection>) -> Unit = {},
    private val nowMillis: () -> Long = { System.nanoTime() / NANOS_PER_MILLISECOND },
    private val afterPendingNonConnectedDetected: (ControllerStateSample) -> Unit = {},
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
        if (expireControllerAckTimeouts()) return false
        if (hasControllerDeferredOverflowed()) return false
        val plan = prepareControllerDispatch(dispatch, queuedControllerIds())
        if (plan.deferredDispatch != null && !canAcceptDeferredControllerDispatch(plan.deferredDispatch)) {
            rollbackPreparedControllerConnections(plan.samples)
            failControllerDeferredOverflow()
            return false
        }
        if (plan.samples.isEmpty()) {
            plan.deferredDispatch?.let { deferred ->
                if (!enqueueDeferredControllerDispatch(deferred)) return failControllerDeferredOverflow()
            }
            return plan.consumedWithoutWire || plan.deferredDispatch != null
        }
        val submission = submitPreparedControllerDispatch(dispatch.delivery, plan.samples)
        if (!submission.wasAdmitted()) {
            rollbackPreparedControllerConnections(plan.samples)
        } else {
            plan.deferredDispatch?.let { deferred ->
                if (!enqueueDeferredControllerDispatch(deferred)) failControllerDeferredOverflow()
            }
        }
        return submission.wasAdmitted() && !hasControllerDeferredOverflowed()
    }

    private fun submitPreparedControllerDispatch(
        delivery: ControllerDelivery,
        samples: List<PreparedControllerSample>,
    ): OutboundCommandScheduler.Submission =
        submitOutbound(
            when (delivery) {
                ControllerDelivery.ANALOG -> OutboundCommandScheduler.Kind.CONTROLLER_MOVE
                ControllerDelivery.STRUCTURAL -> OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL
            },
            StreamOutboundCommand.ProtocolBatch { activeSession ->
                samples.map { planned -> activeSession.controller(inputId = planned.inputId, sample = planned.sample) }
            },
            0,
        )

    fun flushControllerDisconnectCleanup(): Boolean {
        val current = state()
        if (!current.connected || !current.protocolV1 || !current.canSendController) return false
        if (expireControllerAckTimeouts()) return false
        if (hasControllerDeferredOverflowed()) return false
        val plan = prepareControllerCleanup()
        if (plan.samples.isEmpty()) return true
        val submission = submitPreparedControllerDispatch(ControllerDelivery.STRUCTURAL, plan.samples)
        if (!submission.wasAdmitted()) {
            rollbackPreparedControllerConnections(plan.samples)
            plan.readyDisconnects.forEach(controllerConnectionAcks::markDisconnectReady)
        }
        return submission.wasAdmitted()
    }

    fun expireControllerAckTimeouts(): Boolean {
        val expired = controllerConnectionAcks.expirePendingConnections(nowMillis())
        if (expired.isEmpty()) return false
        synchronized(controllerDispatchLock) {
            deferredControllerDispatches.clear()
            controllerDeferredOverflowed = true
        }
        controllerConnectionAcks.reset()
        onControllerAckTimeout(expired)
        return true
    }

    fun resetControllerState() {
        synchronized(controllerDispatchLock) {
            deferredControllerDispatches.clear()
            controllerDeferredOverflowed = false
        }
    }

    internal fun deferredControllerDispatchCount(): Int =
        synchronized(controllerDispatchLock) { deferredControllerDispatches.size }

    private fun prepareControllerDispatch(
        dispatch: ControllerDispatch,
        blockedControllerIds: Set<String>,
        ignoredReadyDisconnects: Set<ControllerConnection> = emptySet(),
    ): PreparedControllerDispatch {
        val orderedDispatch = ControllerDispatchOrdering.disconnectsBeforeLaterEpochSamples(dispatch)
        val connectedInBatch =
            orderedDispatch.samples
                .filter { it.kind == ControllerEventKind.CONNECTED }
                .map { ControllerConnection(it.controllerId, it.controllerEpoch) }
                .toSet()
        val seenConnectedInBatch = mutableSetOf<ControllerConnection>()
        val samples = mutableListOf<PreparedControllerSample>()
        val deferredSamples = mutableListOf<ControllerStateSample>()
        val deferredControllersInBatch = mutableSetOf<String>()
        var consumedWithoutWire = false
        for ((index, sample) in orderedDispatch.samples.withIndex()) {
            val connection = ControllerConnection(sample.controllerId, sample.controllerEpoch)
            val isPendingConnection =
                connection in seenConnectedInBatch ||
                    controllerConnectionAcks.isPending(sample.controllerId, sample.controllerEpoch)
            if (sample.kind == ControllerEventKind.CONNECTED && isPendingConnection) {
                consumedWithoutWire = true
                continue
            }
            if (sample.kind != ControllerEventKind.CONNECTED && isPendingConnection) {
                afterPendingNonConnectedDetected(sample)
                val disposition = controllerConnectionAcks.consumePendingNonConnected(sample.controllerId, sample.controllerEpoch, sample.kind)
                if (disposition == PendingControllerInputDisposition.CONSUMED_PENDING_STATE) {
                    consumedWithoutWire = true
                    continue
                }
                if (
                    disposition == PendingControllerInputDisposition.DEFERRED_PENDING_DISCONNECT ||
                    disposition == PendingControllerInputDisposition.DUPLICATE_PENDING_DISCONNECT
                ) {
                    consumedWithoutWire = true
                    deferredControllersInBatch += sample.controllerId
                    continue
                }
            }
            if (controllerConnectionAcks.hasDeferredDisconnectFor(sample.controllerId, sample.controllerEpoch)) {
                consumedWithoutWire = true
                if (sample.kind == ControllerEventKind.DISCONNECTED) deferredControllersInBatch += sample.controllerId
                continue
            }
            if (sample.controllerId in blockedControllerIds) {
                deferredControllersInBatch += sample.controllerId
                deferredSamples += sample
                continue
            }
            if (sample.controllerId in deferredControllersInBatch) {
                deferredSamples += sample
                continue
            }
            if (controllerConnectionAcks.hasDeferredDisconnectBeforeExcept(sample.controllerId, sample.controllerEpoch, ignoredReadyDisconnects)) {
                deferredControllersInBatch += sample.controllerId
                deferredSamples += sample
                continue
            }
            if (ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(orderedDispatch.samples, index, sample)) {
                deferredControllersInBatch += sample.controllerId
                deferredSamples += sample
                continue
            }
            if (sample.kind != ControllerEventKind.CONNECTED && connection in connectedInBatch && connection !in seenConnectedInBatch) {
                if (sample.kind == ControllerEventKind.STATE) {
                    consumedWithoutWire = true
                } else {
                    deferredSamples += sample
                }
                continue
            }
            val inputId = nextInputId.getAndIncrement()
            if (sample.kind == ControllerEventKind.CONNECTED) {
                check(controllerConnectionAcks.recordConnected(inputId, sample.controllerId, sample.controllerEpoch, nowMillis())) {
                    "duplicate controller CONNECTED input id"
                }
                seenConnectedInBatch += connection
            } else if (sample.kind == ControllerEventKind.DISCONNECTED) {
                controllerConnectionAcks.recordDisconnected(sample.controllerId, sample.controllerEpoch)
            }
            samples += PreparedControllerSample(inputId, sample)
        }
        var deferredDispatch: ControllerDispatch? = null
        if (deferredSamples.isNotEmpty()) {
            deferredDispatch = orderedDispatch.copy(samples = deferredSamples)
        }
        return PreparedControllerDispatch(samples, deferredDispatch, consumedWithoutWire)
    }

    private fun prepareControllerCleanup(): PreparedControllerCleanup {
        val readyDisconnects = controllerConnectionAcks.readyDisconnects()
        val samples = readyDisconnects.map { connection ->
            controllerConnectionAcks.recordDisconnected(connection.controllerId, connection.controllerEpoch)
            ControllerStateSample(
                controllerId = connection.controllerId,
                controllerEpoch = connection.controllerEpoch,
                kind = ControllerEventKind.DISCONNECTED,
            )
        }.map { sample ->
            PreparedControllerSample(nextInputId.getAndIncrement(), sample)
        }.toMutableList()
        while (true) {
            val queued = pollDrainableDeferredControllerDispatch() ?: break
            val plan = prepareControllerDispatch(
                queued.dispatch,
                queued.blockedControllerIds,
                readyDisconnects.toSet(),
            )
            plan.deferredDispatch?.let { deferred ->
                reinsertDeferredControllerDispatch(queued.index, deferred)
            }
            samples += plan.samples
        }
        return PreparedControllerCleanup(samples, readyDisconnects)
    }

    private fun hasControllerDeferredOverflowed(): Boolean =
        synchronized(controllerDispatchLock) { controllerDeferredOverflowed }

    private fun enqueueDeferredControllerDispatch(dispatch: ControllerDispatch): Boolean =
        synchronized(controllerDispatchLock) {
            if (tryReplaceTrailingDeferredAnalogDispatch(dispatch)) return@synchronized true
            if (deferredControllerDispatches.size >= maximumDeferredControllerDispatches) return@synchronized false
            deferredControllerDispatches.addLast(dispatch)
            true
        }

    private fun canAcceptDeferredControllerDispatch(dispatch: ControllerDispatch): Boolean =
        synchronized(controllerDispatchLock) {
            canAcceptDeferredControllerDispatchLocked(dispatch)
        }

    private fun canAcceptDeferredControllerDispatchLocked(dispatch: ControllerDispatch): Boolean {
        if (dispatch.delivery == ControllerDelivery.ANALOG && dispatch.samples.isNotEmpty()) {
            val trailing = deferredControllerDispatches.lastOrNull()
            if (trailing?.delivery == ControllerDelivery.ANALOG && trailing.samples.isNotEmpty()) {
                val trailingConnections = trailing.samples.map { ControllerConnection(it.controllerId, it.controllerEpoch) }.toSet()
                val replacementConnections = dispatch.samples.map { ControllerConnection(it.controllerId, it.controllerEpoch) }.toSet()
                if (trailingConnections == replacementConnections) return true
            }
        }
        return deferredControllerDispatches.size < maximumDeferredControllerDispatches
    }

    private fun reinsertDeferredControllerDispatch(
        index: Int,
        dispatch: ControllerDispatch,
    ) = synchronized(controllerDispatchLock) {
        deferredControllerDispatches.add(index.coerceIn(0, deferredControllerDispatches.size), dispatch)
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

    private fun pollDrainableDeferredControllerDispatch(): QueuedControllerDispatch? =
        synchronized(controllerDispatchLock) {
            val index = firstDrainableDeferredControllerDispatchIndexLocked() ?: return@synchronized null
            val priorControllerIds =
                deferredControllerDispatches
                    .take(index)
                    .flatMap { dispatch -> dispatch.samples.map { it.controllerId } }
                    .toSet()
            QueuedControllerDispatch(index, deferredControllerDispatches.removeAt(index), priorControllerIds)
        }

    private fun firstDrainableDeferredControllerDispatchIndexLocked(): Int? {
        val priorControllerIds = mutableSetOf<String>()
        deferredControllerDispatches.forEachIndexed { index, dispatch ->
            if (!allSamplesBlockedByDeferredControllerWork(dispatch, priorControllerIds)) {
                return index
            }
            priorControllerIds += dispatch.samples.map { it.controllerId }
        }
        return null
    }

    private fun queuedControllerIds(): Set<String> =
        synchronized(controllerDispatchLock) {
            deferredControllerDispatches.flatMap { dispatch -> dispatch.samples.map { it.controllerId } }.toSet()
        }

    private fun allSamplesBlockedByDeferredControllerWork(
        dispatch: ControllerDispatch,
        priorControllerIds: Set<String>,
    ): Boolean {
        val blockedControllersInDispatch = mutableSetOf<String>()
        return dispatch.samples.withIndex().all { (index, sample) ->
            val blocked =
                sample.controllerId in priorControllerIds ||
                    sample.controllerId in blockedControllersInDispatch ||
                    controllerConnectionAcks.hasDeferredDisconnectBefore(sample.controllerId, sample.controllerEpoch) ||
                    ControllerDispatchOrdering.hasLaterLowerEpochDisconnect(dispatch.samples, index, sample)
            if (blocked) blockedControllersInDispatch += sample.controllerId
            blocked
        }
    }

    private fun rollbackPreparedControllerConnections(samples: List<PreparedControllerSample>) {
        samples.asReversed().forEach { planned ->
            if (planned.sample.kind == ControllerEventKind.CONNECTED) {
                controllerConnectionAcks.recordDisconnected(planned.sample.controllerId, planned.sample.controllerEpoch)
            }
        }
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

private const val NANOS_PER_MILLISECOND = 1_000_000L

private data class PreparedControllerSample(
    val inputId: Long,
    val sample: ControllerStateSample,
)

private data class PreparedControllerDispatch(
    val samples: List<PreparedControllerSample>,
    val deferredDispatch: ControllerDispatch?,
    val consumedWithoutWire: Boolean,
)

private data class PreparedControllerCleanup(
    val samples: List<PreparedControllerSample>,
    val readyDisconnects: List<ControllerConnection>,
)

private data class QueuedControllerDispatch(
    val index: Int,
    val dispatch: ControllerDispatch,
    val blockedControllerIds: Set<String>,
)
