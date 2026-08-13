package dev.telemachus.display

import android.os.SystemClock
import android.view.InputDevice
import android.view.MotionEvent
import android.view.View
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Opt-in device-to-host gesture acceptance. This intentionally drives the real
 * input view and therefore must never run as part of an unattended CI suite.
 */
@RunWith(AndroidJUnit4::class)
class TouchGestureAcceptanceDriverInstrumentedTest {
    @Test
    fun drivesTouchGestureMatrixWhileConnected() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Pass -e $OPT_IN_ARGUMENT true only when a disposable Mac test surface is ready",
            arguments.getString(OPT_IN_ARGUMENT).toBoolean(),
        )

        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val inputView = waitForStreamingInput(scenario)
            val centerX = inputView.width * 0.50f
            val centerY = inputView.height * 0.55f

            dispatchSinglePointer(inputView, centerX, centerY, holdMillis = TAP_HOLD_MS)
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            dispatchSinglePointer(inputView, centerX, centerY, holdMillis = LONG_PRESS_HOLD_MS)
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            dispatchSinglePointer(
                inputView,
                centerX,
                centerY,
                holdMillis = LONG_PRESS_HOLD_MS,
                endX = centerX + inputView.width * 0.12f,
                endY = centerY,
            )
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            dispatchTwoPointers(
                inputView,
                firstStart = Point(centerX - 90f, centerY - 80f),
                secondStart = Point(centerX + 90f, centerY - 80f),
                firstEnd = Point(centerX - 90f, centerY + 100f),
                secondEnd = Point(centerX + 90f, centerY + 100f),
            )
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            dispatchTwoPointers(
                inputView,
                firstStart = Point(centerX - 70f, centerY),
                secondStart = Point(centerX + 70f, centerY),
                firstEnd = Point(centerX - 170f, centerY),
                secondEnd = Point(centerX + 170f, centerY),
            )
            SystemClock.sleep(HOST_FLUSH_MS)
        }
    }

    private fun waitForStreamingInput(scenario: ActivityScenario<MainActivity>): View {
        val deadline = SystemClock.elapsedRealtime() + STREAM_WAIT_MS
        var inputView: View? = null
        var streaming = false
        while (SystemClock.elapsedRealtime() < deadline && !streaming) {
            scenario.onActivity { activity ->
                val candidate = activity.findViewById<View>(R.id.inputViewport)
                inputView = candidate
                streaming =
                    candidate.width > 0 &&
                        candidate.height > 0 &&
                        activity.findViewById<View>(R.id.disconnectedBackdrop).visibility == View.GONE
            }
            if (!streaming) SystemClock.sleep(STREAM_POLL_MS)
        }
        assertTrue("The real MainActivity did not reach its connected streaming UI", streaming)
        return requireNotNull(inputView)
    }

    private fun dispatchSinglePointer(
        view: View,
        startX: Float,
        startY: Float,
        holdMillis: Long,
        endX: Float = startX,
        endY: Float = startY,
    ) {
        val downTime = SystemClock.uptimeMillis()
        dispatch(view, singlePointerEvent(downTime, downTime, MotionEvent.ACTION_DOWN, startX, startY))
        SystemClock.sleep(holdMillis)
        if (startX != endX || startY != endY) {
            dispatch(
                view,
                singlePointerEvent(
                    downTime,
                    SystemClock.uptimeMillis(),
                    MotionEvent.ACTION_MOVE,
                    endX,
                    endY,
                ),
            )
            SystemClock.sleep(MOVE_SETTLE_MS)
        }
        dispatch(
            view,
            singlePointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_UP,
                endX,
                endY,
            ),
        )
    }

    private fun dispatchTwoPointers(
        view: View,
        firstStart: Point,
        secondStart: Point,
        firstEnd: Point,
        secondEnd: Point,
    ) {
        val downTime = SystemClock.uptimeMillis()
        dispatch(view, singlePointerEvent(downTime, downTime, MotionEvent.ACTION_DOWN, firstStart.x, firstStart.y))
        dispatch(
            view,
            twoPointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_POINTER_DOWN or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                firstStart,
                secondStart,
            ),
        )
        SystemClock.sleep(MOVE_SETTLE_MS)
        dispatch(
            view,
            twoPointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_MOVE,
                firstEnd,
                secondEnd,
            ),
        )
        SystemClock.sleep(MOVE_SETTLE_MS)
        dispatch(
            view,
            twoPointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_POINTER_UP or (1 shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),
                firstEnd,
                secondEnd,
            ),
        )
        dispatch(
            view,
            singlePointerEvent(
                downTime,
                SystemClock.uptimeMillis(),
                MotionEvent.ACTION_UP,
                firstEnd.x,
                firstEnd.y,
            ),
        )
    }

    private fun dispatch(view: View, event: MotionEvent) {
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertTrue("Input view rejected action ${event.actionMasked}", view.dispatchTouchEvent(event))
            }
        } finally {
            event.recycle()
        }
    }

    private fun singlePointerEvent(
        downTime: Long,
        eventTime: Long,
        action: Int,
        x: Float,
        y: Float,
    ): MotionEvent =
        MotionEvent.obtain(
            downTime,
            eventTime,
            action,
            x,
            y,
            0,
        ).apply { source = InputDevice.SOURCE_TOUCHSCREEN }

    private fun twoPointerEvent(
        downTime: Long,
        eventTime: Long,
        action: Int,
        first: Point,
        second: Point,
    ): MotionEvent {
        val properties =
            arrayOf(
                MotionEvent.PointerProperties().apply {
                    id = 0
                    toolType = MotionEvent.TOOL_TYPE_FINGER
                },
                MotionEvent.PointerProperties().apply {
                    id = 1
                    toolType = MotionEvent.TOOL_TYPE_FINGER
                },
            )
        val coordinates =
            arrayOf(
                pointerCoordinates(first),
                pointerCoordinates(second),
            )
        return MotionEvent.obtain(
            downTime,
            eventTime,
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
            InputDevice.SOURCE_TOUCHSCREEN,
            0,
        )
    }

    private fun pointerCoordinates(point: Point) =
        MotionEvent.PointerCoords().apply {
            x = point.x
            y = point.y
            pressure = 1f
            size = 1f
        }

    private data class Point(val x: Float, val y: Float)

    private companion object {
        const val OPT_IN_ARGUMENT = "vibeScreenTouchE2E"
        const val STREAM_WAIT_MS = 15_000L
        const val STREAM_POLL_MS = 250L
        const val TAP_HOLD_MS = 80L
        const val LONG_PRESS_HOLD_MS = 650L
        const val MOVE_SETTLE_MS = 120L
        const val BETWEEN_GESTURES_MS = 400L
        const val HOST_FLUSH_MS = 1_000L
    }
}
