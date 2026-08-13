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
    val isStylus: Boolean,
)

internal data class StylusMotionSnapshot(
    val actionMasked: Int,
    val actionIndex: Int,
    val pointers: List<StylusPointerSnapshot>,
    val historicalPointers: List<List<StylusPointerSnapshot>> = emptyList(),
)

internal data class StylusSample(
    val pointerId: Int,
    val phase: InputPhase,
    val x: Double,
    val y: Double,
    val pressure: Double,
    val tiltXDegrees: Double,
    val tiltYDegrees: Double,
) {
    init {
        require(pointerId >= 0)
        require(phase != InputPhase.INPUT_PHASE_UNSPECIFIED)
        require(x.isFinite() && y.isFinite() && x in 0.0..1.0 && y in 0.0..1.0)
        require(pressure.isFinite() && pressure in 0.0..1.0)
        require(tiltXDegrees.isFinite() && tiltXDegrees in -90.0..90.0)
        require(tiltYDegrees.isFinite() && tiltYDegrees in -90.0..90.0)
        require(Math.hypot(tiltXDegrees, tiltYDegrees) <= MAX_TILT_DEGREES)
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
            route = if (stylusNegotiated && firstPointer?.isStylus == true) Route.STYLUS else Route.TOUCH
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
    private val activeInputIds = mutableMapOf<Int, Long>()

    fun resolve(sample: StylusSample): Long? =
        if (sample.phase == InputPhase.INPUT_PHASE_BEGAN) {
            nextInputId().also { activeInputIds[sample.pointerId] = it }
        } else {
            activeInputIds[sample.pointerId]
        }

    fun complete(sample: StylusSample) {
        if (sample.phase == InputPhase.INPUT_PHASE_ENDED || sample.phase == InputPhase.INPUT_PHASE_CANCELLED) {
            activeInputIds.remove(sample.pointerId)
        }
    }

    fun clear() = activeInputIds.clear()

    internal val activeCount: Int
        get() = activeInputIds.size
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
                isStylus = event.getToolType(index) == MotionEvent.TOOL_TYPE_STYLUS,
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
        )
    }

    fun map(snapshot: StylusMotionSnapshot): List<StylusSample> =
        when (snapshot.actionMasked) {
            MotionEvent.ACTION_DOWN,
            MotionEvent.ACTION_POINTER_DOWN,
            -> snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_BEGAN)?.let(::listOf).orEmpty()

            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_POINTER_UP,
            -> snapshot.actionStylusOrNull(InputPhase.INPUT_PHASE_ENDED)?.let(::listOf).orEmpty()

            MotionEvent.ACTION_MOVE ->
                (snapshot.historicalPointers + listOf(snapshot.pointers)).flatMap { pointers ->
                    pointers.mapNotNull { it.toSampleOrNull(InputPhase.INPUT_PHASE_CHANGED) }
                }
            MotionEvent.ACTION_CANCEL -> snapshot.pointers.mapNotNull { it.toSampleOrNull(InputPhase.INPUT_PHASE_CANCELLED) }
            else -> emptyList()
        }

    private fun StylusMotionSnapshot.actionStylusOrNull(phase: InputPhase): StylusSample? =
        pointers.getOrNull(actionIndex)?.toSampleOrNull(phase)

    private fun StylusPointerSnapshot.toSampleOrNull(phase: InputPhase): StylusSample? {
        if (!isStylus || !x.isFinite() || !y.isFinite()) return null
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
                if (phase == InputPhase.INPUT_PHASE_ENDED || phase == InputPhase.INPUT_PHASE_CANCELLED) {
                    0.0
                } else {
                    pressure.takeIf(Double::isFinite)?.coerceIn(0.0, 1.0) ?: 0.0
                },
            tiltXDegrees = tiltX.coerceIn(-MAX_TILT_DEGREES, MAX_TILT_DEGREES),
            tiltYDegrees = tiltY.coerceIn(-MAX_TILT_DEGREES, MAX_TILT_DEGREES),
        )
    }
}

private const val MAX_TILT_DEGREES = 90.0
