package dev.telemachus.display

import android.content.Intent
import android.os.SystemClock
import android.util.Log
import android.view.InputDevice
import android.view.KeyCharacterMap
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import dev.vibescreen.protocol.v1.InputPhase
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
            arguments.getString(OPT_IN_ARGUMENT, "false").toBoolean(),
        )

        val scenario = ActivityScenario.launch<MainActivity>(autoConnectIntent())
        try {
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
        } finally {
            closeScenarioBestEffort(scenario)
        }
    }

    @Test
    fun drivesNativeKeyboardScrollAndTouchWhileProtocolV1Ready() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Pass -e $NATIVE_OPT_IN_ARGUMENT true only when a disposable Mac test surface is ready",
            arguments.getString(NATIVE_OPT_IN_ARGUMENT, "false").toBoolean(),
        )

        val scenario = ActivityScenario.launch<MainActivity>(autoConnectIntent())
        try {
            val inputView = waitForProtocolV1Input(scenario)
            val centerX = inputView.width * 0.50f
            val centerY = inputView.height * 0.55f

            Log.d(LOG_TAG, "native_sequence_begin center=$centerX,$centerY")
            Log.d(LOG_TAG, "native_key_sequence keycodes=A,B,C")
            dispatchKeyStroke(scenario, KeyEvent.KEYCODE_A)
            dispatchKeyStroke(scenario, KeyEvent.KEYCODE_B)
            dispatchKeyStroke(scenario, KeyEvent.KEYCODE_C)
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            Log.d(LOG_TAG, "native_scroll vertical=-3.0")
            dispatchGeneric(inputView, scrollEvent(centerX, centerY, verticalScroll = -3f))
            SystemClock.sleep(BETWEEN_GESTURES_MS)

            Log.d(LOG_TAG, "native_touch tap")
            dispatchSinglePointer(inputView, centerX, centerY, holdMillis = TAP_HOLD_MS)
            SystemClock.sleep(BETWEEN_GESTURES_MS)
            Log.d(LOG_TAG, "native_touch long_press")
            dispatchSinglePointer(inputView, centerX, centerY, holdMillis = LONG_PRESS_HOLD_MS)
            SystemClock.sleep(HOST_FLUSH_MS)
            Log.d(LOG_TAG, "native_sequence_end")
        } finally {
            closeScenarioBestEffort(scenario)
        }
    }

    @Test
    fun directProtocolV1InputSendIsAdmittedWhileStreaming() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Pass -e $DIRECT_OPT_IN_ARGUMENT true only when a disposable Mac test surface is ready",
            arguments.getString(DIRECT_OPT_IN_ARGUMENT, "false").toBoolean(),
        )

        val scenario = ActivityScenario.launch<MainActivity>(autoConnectIntent())
        try {
            waitForProtocolV1Input(scenario)
            SystemClock.sleep(POST_PROTOCOL_READY_SETTLE_MS)
            scenario.onActivity { activity ->
                val client = currentStreamClient(activity)
                val before = currentInputState(activity)
                logCurrentProtocolSessionSnapshot(client)
                val keyDown = client.sendKey(USB_HID_A, pressed = true, modifierMask = 0)
                val keyUp = client.sendKey(USB_HID_A, pressed = false, modifierMask = 0)
                val keyBDown = client.sendKey(USB_HID_B, pressed = true, modifierMask = 0)
                val keyBUp = client.sendKey(USB_HID_B, pressed = false, modifierMask = 0)
                val keyCDown = client.sendKey(USB_HID_C, pressed = true, modifierMask = 0)
                val keyCUp = client.sendKey(USB_HID_C, pressed = false, modifierMask = 0)
                val scroll = client.sendScroll(deltaX = 0.0, deltaY = -3.0)
                val pointerMove =
                    client.sendPointer(
                        phase = InputPhase.INPUT_PHASE_CHANGED,
                        x = 0.50f,
                        y = 0.55f,
                        buttonMask = 0,
                    )
                client.sendTouch(0.50f, 0.55f, LEGACY_TOUCH_DOWN)
                client.sendTouch(0.50f, 0.55f, LEGACY_TOUCH_UP)
                Log.d(
                    LOG_TAG,
                    "direct_send keyDown=$keyDown keyUp=$keyUp keyBDown=$keyBDown " +
                        "keyBUp=$keyBUp keyCDown=$keyCDown keyCUp=$keyCUp " +
                        "scroll=$scroll pointerMove=$pointerMove touchSent=true " +
                        "state=${before.description}",
                )
                assertTrue("Direct Protocol v1 key down was not admitted: ${before.description}", keyDown)
                assertTrue("Direct Protocol v1 key up was not admitted: ${before.description}", keyUp)
                assertTrue("Direct Protocol v1 key B down was not admitted: ${before.description}", keyBDown)
                assertTrue("Direct Protocol v1 key B up was not admitted: ${before.description}", keyBUp)
                assertTrue("Direct Protocol v1 key C down was not admitted: ${before.description}", keyCDown)
                assertTrue("Direct Protocol v1 key C up was not admitted: ${before.description}", keyCUp)
                assertTrue("Direct Protocol v1 scroll was not admitted: ${before.description}", scroll)
                assertTrue("Direct Protocol v1 pointer move was not admitted: ${before.description}", pointerMove)
            }
            SystemClock.sleep(DIRECT_SEND_OBSERVE_MS)
        } finally {
            closeScenarioBestEffort(scenario)
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

    private fun waitForProtocolV1Input(scenario: ActivityScenario<MainActivity>): View {
        val deadline = SystemClock.elapsedRealtime() + STREAM_WAIT_MS
        var inputView: View? = null
        var ready = false
        var lastState = "not_checked"
        while (SystemClock.elapsedRealtime() < deadline && !ready) {
            scenario.onActivity { activity ->
                val candidate = activity.findViewById<View>(R.id.inputViewport)
                inputView = candidate
                val streamingUi =
                    candidate.width > 0 &&
                        candidate.height > 0 &&
                        activity.findViewById<View>(R.id.disconnectedBackdrop).visibility == View.GONE
                val state = currentInputState(activity)
                lastState = state.description
                ready = streamingUi && state.isProtocolV1InputReady
            }
            if (!ready) SystemClock.sleep(STREAM_POLL_MS)
        }
        Log.d(LOG_TAG, "protocol_v1_input_ready=$ready state=$lastState")
        assertTrue("The real MainActivity did not reach Protocol v1 input-ready state: $lastState", ready)
        return requireNotNull(inputView)
    }

    private fun currentInputState(activity: MainActivity): ReflectedInputState {
        val client = currentStreamClientOrNull(activity) ?: return ReflectedInputState(rawDescription = "streamClient=null")
        val method = client.javaClass.getDeclaredMethod(INPUT_STATE_METHOD_NAME).apply { isAccessible = true }
        val state = method.invoke(client) ?: return ReflectedInputState(rawDescription = "inputState=null")
        fun booleanField(name: String): Boolean {
            val field = state.javaClass.getDeclaredField(name).apply { isAccessible = true }
            return field.getBoolean(state)
        }
        return ReflectedInputState(
            connected = booleanField("connected"),
            protocolV1 = booleanField("protocolV1"),
            canSendTouch = booleanField("canSendTouch"),
            canSendPointer = booleanField("canSendPointer"),
            canSendKeyboard = booleanField("canSendKeyboard"),
        )
    }

    private fun closeScenarioBestEffort(scenario: ActivityScenario<MainActivity>) {
        scenario.onActivity { activity -> activity.finishAndRemoveTask() }
    }

    private fun currentStreamClient(activity: MainActivity): StreamClient =
        requireNotNull(currentStreamClientOrNull(activity)) { "streamClient=null" }

    private fun currentStreamClientOrNull(activity: MainActivity): StreamClient? {
        val clientField = MainActivity::class.java.getDeclaredField(STREAM_CLIENT_FIELD_NAME).apply { isAccessible = true }
        return clientField.get(activity) as? StreamClient
    }

    private fun logCurrentProtocolSessionSnapshot(client: StreamClient) {
        val sessionField = StreamClient::class.java.getDeclaredField(PROTOCOL_SESSION_FIELD_NAME).apply { isAccessible = true }
        val session = sessionField.get(client)
        if (session == null) {
            Log.d(LOG_TAG, "direct_session protocolSession=null")
            return
        }
        val sessionEpoch = session.longField("sessionEpoch")
        val displayId = session.stringField("displayId")
        val streamId = session.longField("streamId")
        val nextMessageId = session.longField("nextMessageId")
        Log.d(
            LOG_TAG,
            "direct_session protocolSession=true next_message_id=$nextMessageId " +
                "session_epoch=$sessionEpoch target_display=${displayId.ifBlank { "<empty>" }} " +
                "target_stream=$streamId",
        )
    }

    private fun Any.longField(name: String): Long {
        val field = javaClass.getDeclaredField(name).apply { isAccessible = true }
        return field.getLong(this)
    }

    private fun Any.stringField(name: String): String {
        val field = javaClass.getDeclaredField(name).apply { isAccessible = true }
        return field.get(this) as? String ?: ""
    }

    private fun autoConnectIntent(): Intent =
        Intent(ApplicationProvider.getApplicationContext(), MainActivity::class.java).apply {
            putExtra(AUTO_CONNECT_EXTRA, true)
        }

    private fun dispatchKeyStroke(
        scenario: ActivityScenario<MainActivity>,
        keyCode: Int,
    ) {
        val downTime = SystemClock.uptimeMillis()
        dispatchKey(scenario, keyEvent(downTime, downTime, KeyEvent.ACTION_DOWN, keyCode))
        dispatchKey(scenario, keyEvent(downTime, SystemClock.uptimeMillis(), KeyEvent.ACTION_UP, keyCode))
    }

    private fun dispatchKey(
        scenario: ActivityScenario<MainActivity>,
        event: KeyEvent,
    ) {
        scenario.onActivity { activity ->
            assertTrue("Activity rejected key ${event.keyCode} action ${event.action}", activity.dispatchKeyEvent(event))
        }
    }

    private fun keyEvent(
        downTime: Long,
        eventTime: Long,
        action: Int,
        keyCode: Int,
    ): KeyEvent =
        KeyEvent(
            downTime,
            eventTime,
            action,
            keyCode,
            0,
            0,
            KeyCharacterMap.VIRTUAL_KEYBOARD,
            0,
            0,
            InputDevice.SOURCE_KEYBOARD,
        )

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

    private fun dispatchGeneric(view: View, event: MotionEvent) {
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                assertTrue("Input view rejected generic action ${event.actionMasked}", view.dispatchGenericMotionEvent(event))
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

    private fun scrollEvent(
        x: Float,
        y: Float,
        verticalScroll: Float,
    ): MotionEvent {
        val eventTime = SystemClock.uptimeMillis()
        val properties =
            arrayOf(
                MotionEvent.PointerProperties().apply {
                    id = 0
                    toolType = MotionEvent.TOOL_TYPE_MOUSE
                },
            )
        val coordinates =
            arrayOf(
                MotionEvent.PointerCoords().apply {
                    this.x = x
                    this.y = y
                    setAxisValue(MotionEvent.AXIS_VSCROLL, verticalScroll)
                },
            )
        return MotionEvent.obtain(
            eventTime,
            eventTime,
            MotionEvent.ACTION_SCROLL,
            1,
            properties,
            coordinates,
            0,
            0,
            1f,
            1f,
            0,
            0,
            InputDevice.SOURCE_MOUSE,
            0,
        )
    }

    private data class Point(val x: Float, val y: Float)

    private data class ReflectedInputState(
        val connected: Boolean = false,
        val protocolV1: Boolean = false,
        val canSendTouch: Boolean = false,
        val canSendPointer: Boolean = false,
        val canSendKeyboard: Boolean = false,
        private val rawDescription: String? = null,
    ) {
        val isProtocolV1InputReady: Boolean
            get() = connected && protocolV1 && canSendTouch && canSendPointer && canSendKeyboard

        val description: String
            get() =
                rawDescription ?: "connected=$connected protocolV1=$protocolV1 " +
                    "canSendTouch=$canSendTouch canSendPointer=$canSendPointer canSendKeyboard=$canSendKeyboard"
    }

    private companion object {
        const val AUTO_CONNECT_EXTRA = "auto_connect"
        const val OPT_IN_ARGUMENT = "vibeScreenTouchE2E"
        const val NATIVE_OPT_IN_ARGUMENT = "vibeScreenNativeInputE2E"
        const val DIRECT_OPT_IN_ARGUMENT = "vibeScreenDirectInputE2E"
        const val LOG_TAG = "P0110InputE2E"
        const val USB_HID_A = 0x04
        const val USB_HID_B = 0x05
        const val USB_HID_C = 0x06
        const val LEGACY_TOUCH_DOWN = 0
        const val LEGACY_TOUCH_UP = 2
        const val STREAM_CLIENT_FIELD_NAME = "streamClient"
        const val PROTOCOL_SESSION_FIELD_NAME = "protocolSession"
        const val INPUT_STATE_METHOD_NAME = "currentInputSessionState"
        const val STREAM_WAIT_MS = 15_000L
        const val STREAM_POLL_MS = 250L
        const val TAP_HOLD_MS = 80L
        const val LONG_PRESS_HOLD_MS = 650L
        const val MOVE_SETTLE_MS = 120L
        const val BETWEEN_GESTURES_MS = 400L
        const val HOST_FLUSH_MS = 1_000L
        const val POST_PROTOCOL_READY_SETTLE_MS = 1_500L
        const val DIRECT_SEND_OBSERVE_MS = 5_000L
    }
}
