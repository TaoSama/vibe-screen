package dev.telemachus.display

import android.view.MotionEvent
import dev.vibescreen.protocol.v1.InputPhase
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

internal data class StylusPointerSnapshot(
    val pointerId: Int,
    val x: Double,
    val y: Double,
    val pressure: Double,
    val tiltRadians: Double,
    val orientationRadians: Double,
    val toolKind: StylusToolKind?,
    val buttonMask: Int = 0,
)

internal enum class StylusToolKind { PEN, ERASER }

internal enum class StylusContactState { CONTACT, PROXIMITY }

internal enum class StylusDelivery { MOTION, STRUCTURAL }

internal data class StylusMotionSnapshot(
    val actionMasked: Int,
    val actionIndex: Int,
    val pointers: List<StylusPointerSnapshot>,
    val historicalPointers: List<List<StylusPointerSnapshot>> = emptyList(),
    val buttonMask: Int = 0,
)

internal data class StylusSample(
    val pointerId: Int,
    val phase: InputPhase,
    val x: Double,
    val y: Double,
    val pressure: Double,
    val tiltXDegrees: Double,
    val tiltYDegrees: Double,
    val toolKind: StylusToolKind,
    val buttonMask: Int,
    val contactState: StylusContactState,
    val delivery: StylusDelivery,
) {
    init {
        require(pointerId >= 0)
        require(phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x.isFinite() && y.isFinite() && x in 0.0..1.0 && y in 0.0..1.0)
        require(pressure.isFinite() && pressure in 0.0..1.0)
        require(tiltXDegrees.isFinite() && tiltXDegrees in -90.0..90.0)
        require(tiltYDegrees.isFinite() && tiltYDegrees in -90.0..90.0)
        require(Math.hypot(tiltXDegrees, tiltYDegrees) <= MAX_TILT_DEGREES)
        require(buttonMask and STYLUS_BUTTON_MASK.inv() == 0)
        require(contactState != StylusContactState.PROXIMITY || pressure == 0.0)
    }
}

internal class StylusGestureRouter {
    private enum class Route { UNDECIDED, TOUCH, STYLUS }

    private var route = Route.UNDECIDED

    fun routesToStylus(
        snapshot: StylusMotionSnapshot,
        stylusNegotiated: Boolean,
    ): Boolean {
        if (snapshot.actionMasked == MotionEvent.ACTION_DOWN) {
            val firstPointer = snapshot.pointers.getOrNull(snapshot.actionIndex)
            route = if (stylusNegotiated && firstPointer?.toolKind != null) Route.STYLUS else Route.TOUCH
        } else if (route == Route.UNDECIDED) {
            route = Route.TOUCH
        }
        val routesToStylus = route == Route.STYLUS
        if (snapshot.actionMasked == MotionEvent.ACTION_UP || snapshot.actionMasked == MotionEvent.ACTION_CANCEL) reset()
        return routesToStylus
    }

    fun reset() {
        route = Route.UNDECIDED
    }
}

internal class StylusInputIdTracker(
    private val nextInputId: () -> Long,
) {
    private data class ActiveStylus(val inputId: Long, var sample: StylusSample)

    internal data class Cancellation(val inputId: Long, val sample: StylusSample)

    private val activeInputs = mutableMapOf<Int, ActiveStylus>()

    fun resolve(sample: StylusSample): Long? =
        if (sample.phase == InputPhase.INPUT_PHASE_BEGAN) {
            nextInputId().also { activeInputs[sample.pointerId] = ActiveStylus(it, sample) }
        } else {
            activeInputs[sample.pointerId]?.also { it.sample = sample }?.inputId
        }

    fun complete(sample: StylusSample) {
        if (sample.phase == InputPhase.INPUT_PHASE_ENDED || sample.phase == InputPhase.INPUT_PHASE_CANCELLED) {
            activeInputs.remove(sample.pointerId)
        }
    }

    fun takeCancellations(): List<Cancellation> =
        activeInputs.values
            .map { active ->
                Cancellation(
                    active.inputId,
                    active.sample.copy(
                        phase = InputPhase.INPUT_PHASE_CANCELLED,
                        pressure = 0.0,
                        buttonMask = 0,
                        delivery = StylusDelivery.STRUCTURAL,
                    ),
                )
            }.also { activeInputs.clear() }

    fun clear() = activeInputs.clear()

    internal val activeCount: Int
        get() = activeInputs.size
}

/** Resolves button and cancellation samples from explicit per-pointer proximity/contact state. */
internal class StylusContactRouter {
    private val states = mutableMapOf<Int, StylusContactState>()

    fun map(snapshot: StylusMotionSnapshot, extendedNegotiated: Boolean): List<StylusSample> {
        val actionPointer = snapshot.pointers.getOrNull(snapshot.actionIndex)
        val explicitState =
            when (snapshot.actionMasked) {
                MotionEvent.ACTION_HOVER_ENTER, MotionEvent.ACTION_HOVER_MOVE -> StylusContactState.PROXIMITY
                MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN, MotionEvent.ACTION_MOVE,
                MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> StylusContactState.CONTACT
                MotionEvent.ACTION_BUTTON_PRESS, MotionEvent.ACTION_BUTTON_RELEASE ->
                    actionPointer?.let { states[it.pointerId] }
                MotionEvent.ACTION_CANCEL -> actionPointer?.let { states[it.pointerId] }
                else -> null
            }
        if (
            explicitState != null &&
            snapshot.actionMasked !in setOf(MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP, MotionEvent.ACTION_CANCEL)
        ) {
            snapshot.pointers.forEach { pointer ->
                if (pointer.toolKind != null) states[pointer.pointerId] = explicitState
            }
        }
        val samples = StylusInputMapper.map(snapshot, extendedNegotiated, explicitState)
        if (
            snapshot.actionMasked == MotionEvent.ACTION_HOVER_EXIT ||
            snapshot.actionMasked == MotionEvent.ACTION_UP ||
            snapshot.actionMasked == MotionEvent.ACTION_POINTER_UP
        ) {
            actionPointer?.let { states.remove(it.pointerId) }
        } else if (snapshot.actionMasked == MotionEvent.ACTION_CANCEL) {
            states.clear()
        }
        return samples
    }

    fun reset() = states.clear()
}

/** Drains both transport families before the shared native-input teardown boundary. */
internal class StylusReleaseCoordinator(
    private val streamTracker: StylusInputIdTracker,
    private val internetTracker: StylusInputIdTracker,
) {
    fun completeBoundary(
        submitStream: (List<StylusSample>) -> Unit,
        submitInternet: (List<StylusInputIdTracker.Cancellation>) -> Unit,
        afterRelease: () -> Unit,
    ) {
        try {
            val streamCancellations = streamTracker.takeCancellations().map { it.sample }
            if (streamCancellations.isNotEmpty()) submitStream(streamCancellations)
            val internetCancellations = internetTracker.takeCancellations()
            if (internetCancellations.isNotEmpty()) submitInternet(internetCancellations)
        } finally {
            afterRelease()
        }
    }
}

/** Converts Android stylus axes to protocol screen coordinates without owning gesture state. */
internal object StylusInputMapper {
    fun snapshot(
        event: MotionEvent,
        mapPoint: (Float, Float) -> TouchMapper.Point,
    ): StylusMotionSnapshot {
        fun pointer(index: Int, historyPosition: Int?): StylusPointerSnapshot {
            val rawX = historyPosition?.let { event.getHistoricalX(index, it) } ?: event.getX(index)
            val rawY = historyPosition?.let { event.getHistoricalY(index, it) } ?: event.getY(index)
            val point = mapPoint(rawX, rawY)
            return StylusPointerSnapshot(
                pointerId = event.getPointerId(index),
                x = point.x.toDouble(),
                y = point.y.toDouble(),
                pressure =
                    historyPosition?.let { event.getHistoricalPressure(index, it) }?.toDouble()
                        ?: event.getPressure(index).toDouble(),
                tiltRadians =
                    historyPosition?.let { event.getHistoricalAxisValue(MotionEvent.AXIS_TILT, index, it) }?.toDouble()
                        ?: event.getAxisValue(MotionEvent.AXIS_TILT, index).toDouble(),
                orientationRadians =
                    historyPosition?.let {
                        event.getHistoricalAxisValue(MotionEvent.AXIS_ORIENTATION, index, it)
                    }?.toDouble() ?: event.getAxisValue(MotionEvent.AXIS_ORIENTATION, index).toDouble(),
                toolKind =
                    when (event.getToolType(index)) {
                        MotionEvent.TOOL_TYPE_STYLUS -> StylusToolKind.PEN
                        MotionEvent.TOOL_TYPE_ERASER -> StylusToolKind.ERASER
                        else -> null
                    },
                buttonMask = event.buttonState.toStylusButtonMask(),
            )
        }
        return StylusMotionSnapshot(
            actionMasked = event.actionMasked,
            actionIndex = event.actionIndex,
            pointers = List(event.pointerCount) { pointer(it, null) },
            historicalPointers =
                List(event.historySize) { historyPosition ->
                    List(event.pointerCount) { index -> pointer(index, historyPosition) }
                },
            buttonMask = event.buttonState.toStylusButtonMask(),
        )
    }

    fun map(
        snapshot: StylusMotionSnapshot,
        extendedNegotiated: Boolean = false,
        explicitContactState: StylusContactState? = null,
    ): List<StylusSample> =
        when (snapshot.actionMasked) {
            MotionEvent.ACTION_DOWN,
            MotionEvent.ACTION_POINTER_DOWN,
            -> snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_BEGAN, StylusContactState.CONTACT)?.let(::listOf).orEmpty()

            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_POINTER_UP,
            -> snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_ENDED, StylusContactState.CONTACT)?.let(::listOf).orEmpty()

            MotionEvent.ACTION_MOVE ->
                (snapshot.historicalPointers + listOf(snapshot.pointers)).flatMap { pointers ->
                    pointers.mapNotNull { it.toSampleOrNull(InputPhase.INPUT_PHASE_CHANGED, StylusContactState.CONTACT) }
                }
            MotionEvent.ACTION_CANCEL ->
                snapshot.pointers.mapNotNull {
                    it.toSampleOrNull(
                        InputPhase.INPUT_PHASE_CANCELLED,
                        explicitContactState ?: StylusContactState.CONTACT,
                        StylusDelivery.STRUCTURAL,
                    )
                }
            MotionEvent.ACTION_HOVER_ENTER ->
                snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_BEGAN, StylusContactState.PROXIMITY)?.let(::listOf).orEmpty()
            MotionEvent.ACTION_HOVER_MOVE ->
                (snapshot.historicalPointers + listOf(snapshot.pointers)).flatMap { pointers ->
                    pointers.mapNotNull { it.toSampleOrNull(InputPhase.INPUT_PHASE_CHANGED, StylusContactState.PROXIMITY) }
                }
            MotionEvent.ACTION_HOVER_EXIT ->
                snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_ENDED, StylusContactState.PROXIMITY)?.let(::listOf).orEmpty()
            MotionEvent.ACTION_BUTTON_PRESS,
            MotionEvent.ACTION_BUTTON_RELEASE,
            -> explicitContactState
                ?.let { state ->
                    snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_CHANGED, state, StylusDelivery.STRUCTURAL)
                }?.let(::listOf).orEmpty()
            else -> emptyList()
        }.filter { sample ->
            extendedNegotiated ||
                (sample.toolKind == StylusToolKind.PEN && sample.contactState == StylusContactState.CONTACT)
        }.map { sample -> if (extendedNegotiated) sample else sample.copy(buttonMask = 0) }

    private fun StylusMotionSnapshot.actionStylusOrNull(
        phase: InputPhase,
        contactState: StylusContactState,
        delivery: StylusDelivery = StylusDelivery.STRUCTURAL,
    ): StylusSample? = pointers.getOrNull(actionIndex)?.toSampleOrNull(phase, contactState, delivery)

    private fun StylusPointerSnapshot.toSampleOrNull(
        phase: InputPhase,
        contactState: StylusContactState,
        delivery: StylusDelivery = StylusDelivery.MOTION,
    ): StylusSample? {
        val kind = toolKind ?: return null
        if (!x.isFinite() || !y.isFinite()) return null
        val magnitudeDegrees =
            tiltRadians
                .takeIf(Double::isFinite)
                ?.coerceIn(0.0, PI / 2.0)
                ?.let(Math::toDegrees)
                ?: 0.0
        val orientation = orientationRadians.takeIf(Double::isFinite) ?: 0.0
        var tiltX = sin(orientation) * magnitudeDegrees
        var tiltY = -cos(orientation) * magnitudeDegrees
        val vectorMagnitude = Math.hypot(tiltX, tiltY)
        if (vectorMagnitude > MAX_TILT_DEGREES) {
            val scale = MAX_TILT_DEGREES / vectorMagnitude
            tiltX *= scale
            tiltY *= scale
        }
        return StylusSample(
            pointerId = pointerId,
            phase = phase,
            x = x.coerceIn(0.0, 1.0),
            y = y.coerceIn(0.0, 1.0),
            pressure =
                if (contactState == StylusContactState.PROXIMITY ||
                    phase == InputPhase.INPUT_PHASE_ENDED || phase == InputPhase.INPUT_PHASE_CANCELLED
                ) {
                    0.0
                } else {
                    pressure.takeIf(Double::isFinite)?.coerceIn(0.0, 1.0) ?: 0.0
                },
            tiltXDegrees = tiltX.coerceIn(-MAX_TILT_DEGREES, MAX_TILT_DEGREES),
            tiltYDegrees = tiltY.coerceIn(-MAX_TILT_DEGREES, MAX_TILT_DEGREES),
            toolKind = kind,
            buttonMask = buttonMask and STYLUS_BUTTON_MASK,
            contactState = contactState,
            delivery = delivery,
        )
    }

    private fun Int.toStylusButtonMask(): Int =
        (if (this and MotionEvent.BUTTON_STYLUS_PRIMARY != 0) STYLUS_PRIMARY_BUTTON else 0) or
            (if (this and MotionEvent.BUTTON_STYLUS_SECONDARY != 0) STYLUS_SECONDARY_BUTTON else 0)
}

private const val MAX_TILT_DEGREES = 90.0
internal const val STYLUS_PRIMARY_BUTTON = 1 shl 0
internal const val STYLUS_SECONDARY_BUTTON = 1 shl 1
private const val STYLUS_BUTTON_MASK = STYLUS_PRIMARY_BUTTON or STYLUS_SECONDARY_BUTTON
