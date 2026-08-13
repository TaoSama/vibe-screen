package dev.telemachus.display

import android.view.InputDevice
import android.view.MotionEvent
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.vibescreen.protocol.v1.InputPhase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.PI

@RunWith(AndroidJUnit4::class)
class StylusInputMapperInstrumentedTest {
    @Test
    fun frameworkMotionEventAxesReachProductionMapper() {
        val properties =
            MotionEvent.PointerProperties().apply {
                id = 9
                toolType = MotionEvent.TOOL_TYPE_STYLUS
            }
        fun coords(xValue: Float, pressureValue: Float) =
            MotionEvent.PointerCoords().apply {
                x = xValue
                y = 75f
                pressure = pressureValue
                setAxisValue(MotionEvent.AXIS_TILT, (PI / 4.0).toFloat())
                setAxisValue(MotionEvent.AXIS_ORIENTATION, (PI / 2.0).toFloat())
            }
        val event =
            MotionEvent.obtain(
                1L,
                1L,
                MotionEvent.ACTION_MOVE,
                1,
                arrayOf(properties),
                arrayOf(coords(10f, 0.25f)),
                0,
                0,
                1f,
                1f,
                0,
                0,
                InputDevice.SOURCE_STYLUS,
                0,
            )
        try {
            event.addBatch(2L, arrayOf(coords(20f, 0.45f)), 0)
            event.addBatch(3L, arrayOf(coords(30f, 0.65f)), 0)
            val snapshot = StylusInputMapper.snapshot(event) { x, y -> TouchMapper.Point(x / 100f, y / 100f) }
            val samples = StylusInputMapper.map(snapshot)
            assertEquals(3, samples.size)
            listOf(0.1, 0.2, 0.3).forEachIndexed { index, expected ->
                assertEquals(expected, samples[index].x, 1e-6)
            }
            listOf(0.25, 0.45, 0.65).forEachIndexed { index, expected ->
                assertEquals(expected, samples[index].pressure, 1e-6)
            }
            val sample = samples.last()
            assertEquals(InputPhase.INPUT_PHASE_CHANGED, sample.phase)
            assertEquals(9, sample.pointerId)
            assertEquals(0.3, sample.x, 1e-6)
            assertEquals(0.75, sample.y, 1e-6)
            assertEquals(0.65, sample.pressure, 1e-6)
            assertEquals(45.0, sample.tiltXDegrees, 1e-4)
            assertEquals(0.0, sample.tiltYDegrees, 1e-4)
            assertTrue(Math.hypot(sample.tiltXDegrees, sample.tiltYDegrees) <= 90.0)
        } finally {
            event.recycle()
        }
    }

    @Test
    fun mixedStylusAndFingerBoundariesStayOnStylusRoute() {
        val tracker = StylusInputIdTracker(generateSequence(200L) { it + 1 }.iterator()::next)
        val router = StylusGestureRouter()
        val beganEvent = mixedEvent(MotionEvent.ACTION_DOWN, actionIndex = 0, includeFinger = false)
        val began = map(beganEvent).single()
        assertTrue(router.routesToStylus(snapshot(beganEvent), stylusNegotiated = true))
        tracker.resolve(began)
        beganEvent.recycle()

        val cases =
            listOf(
                mixedEvent(MotionEvent.ACTION_POINTER_DOWN, actionIndex = 1) to emptyList(),
                mixedEvent(MotionEvent.ACTION_MOVE, actionIndex = 0) to listOf(InputPhase.INPUT_PHASE_CHANGED),
                mixedEvent(MotionEvent.ACTION_POINTER_UP, actionIndex = 1) to emptyList(),
                mixedEvent(MotionEvent.ACTION_CANCEL, actionIndex = 0) to listOf(InputPhase.INPUT_PHASE_CANCELLED),
            )
        try {
            cases.forEach { (event, expectedPhases) ->
                val snapshot = snapshot(event)
                assertTrue(router.routesToStylus(snapshot, stylusNegotiated = true))
                val samples = StylusInputMapper.map(snapshot)
                assertEquals(expectedPhases, samples.map { it.phase })
                assertTrue(samples.none { it.pointerId == 8 })
                samples.forEach { sample ->
                    assertEquals(200L, tracker.resolve(sample))
                    tracker.complete(sample)
                }
            }
            assertEquals(0, tracker.activeCount)
        } finally {
            cases.forEach { it.first.recycle() }
        }
    }

    private fun snapshot(event: MotionEvent) =
        StylusInputMapper.snapshot(event) { x, y -> TouchMapper.Point(x / 100f, y / 100f) }

    private fun map(event: MotionEvent) = StylusInputMapper.map(snapshot(event))

    private fun mixedEvent(
        actionMasked: Int,
        actionIndex: Int,
        includeFinger: Boolean = true,
    ): MotionEvent {
        val properties =
            buildList {
                add(
                    MotionEvent.PointerProperties().apply {
                        id = 7
                        toolType = MotionEvent.TOOL_TYPE_STYLUS
                    },
                )
                if (includeFinger) {
                    add(
                        MotionEvent.PointerProperties().apply {
                            id = 8
                            toolType = MotionEvent.TOOL_TYPE_FINGER
                        },
                    )
                }
            }.toTypedArray()
        val coordinates =
            properties.mapIndexed { index, _ ->
                MotionEvent.PointerCoords().apply {
                    x = 20f + index * 20f
                    y = 50f
                    pressure = 0.5f
                }
            }.toTypedArray()
        val action = actionMasked or (actionIndex shl MotionEvent.ACTION_POINTER_INDEX_SHIFT)
        return MotionEvent.obtain(
            1L,
            2L,
            action,
            properties.size,
            properties,
            coordinates,
            0,
            0,
            1f,
            1f,
            0,
            0,
            InputDevice.SOURCE_TOUCHSCREEN or InputDevice.SOURCE_STYLUS,
            0,
        )
    }
}
