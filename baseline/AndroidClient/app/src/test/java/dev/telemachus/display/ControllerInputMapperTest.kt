package dev.telemachus.display

import android.view.InputDevice
import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerInputMapperTest {
    @Test
    fun stableControllerIdHashesDescriptorAndTruncates() {
        val id = ControllerInputMapper.stableControllerId("descriptor-1")
        assertTrue(id.startsWith("android-"))
        // 12 bytes = 24 hex chars after the "android-" prefix
        assertEquals(8 + 24, id.length)
        val second = ControllerInputMapper.stableControllerId("descriptor-1")
        assertEquals(id, second)
        val third = ControllerInputMapper.stableControllerId("descriptor-2")
        assertFalse(id == third)
    }

    @Test
    fun stableControllerIdRejectsBlank() {
        assertThrows(IllegalArgumentException::class.java) {
            ControllerInputMapper.stableControllerId("")
        }
    }

    @Test
    fun normalizeStickAppliesDeadzoneAndRange() {
        val calibration = ControllerAxisCalibration(minimum = -1f, maximum = 1f, flat = 0.1f)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(0f, calibration), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(0.05f, calibration), 0.0)
        assertEquals(1.0, ControllerInputMapper.normalizeStick(1f, calibration), 1e-9)
        assertEquals(-1.0, ControllerInputMapper.normalizeStick(-1f, calibration), 1e-9)
        val mid = ControllerInputMapper.normalizeStick(0.5f, calibration)
        assertTrue(mid > 0.0 && mid < 1.0)
    }

    @Test
    fun normalizeStickSupportsZeroFlatAndSaturatingFlat() {
        val zeroFlat = ControllerAxisCalibration(minimum = -1f, maximum = 1f, flat = 0f)
        assertEquals(0.5, ControllerInputMapper.normalizeStick(0.5f, zeroFlat), 1e-9)
        assertEquals(-0.5, ControllerInputMapper.normalizeStick(-0.5f, zeroFlat), 1e-9)

        val saturatingFlat = ControllerAxisCalibration(minimum = -1f, maximum = 1f, flat = 2f)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(1f, saturatingFlat), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(-1f, saturatingFlat), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeTrigger(1f, saturatingFlat), 0.0)
    }

    @Test
    fun normalizeStickPreservesReportedFlatAcrossAsymmetricRange() {
        val calibration = ControllerAxisCalibration(minimum = -0.5f, maximum = 1f, flat = 0.6f)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(-0.5f, calibration), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(0.6f, calibration), 0.0)
        assertEquals(0.25, ControllerInputMapper.normalizeStick(0.7f, calibration), 1e-6)
        assertEquals(1.0, ControllerInputMapper.normalizeStick(1f, calibration), 1e-9)
    }

    @Test
    fun normalizeStickReturnsZeroWithoutCalibration() {
        assertEquals(0.0, ControllerInputMapper.normalizeStick(0.5f, null), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeStick(Float.NaN, null), 0.0)
    }

    @Test
    fun deviceCalibrationRejectsUnusableRanges() {
        assertNull(ControllerAxisCalibration.fromDeviceRange(0f, 0f, 0f))
        assertNull(ControllerAxisCalibration.fromDeviceRange(Float.NaN, 1f, 0f))
        assertNull(ControllerAxisCalibration.fromDeviceRange(-1f, 1f, -0.1f))
        assertEquals(
            ControllerAxisCalibration(-1f, 1f, 0.1f),
            ControllerAxisCalibration.fromDeviceRange(-1f, 1f, 0.1f),
        )
    }

    @Test
    fun fallbackDescriptorIncludesAndroidDeviceIdentity() {
        val first = ControllerInputMapper.fallbackDescriptor(1, 2, "Pad", InputDevice.SOURCE_GAMEPAD, 7)
        val second = ControllerInputMapper.fallbackDescriptor(1, 2, "Pad", InputDevice.SOURCE_GAMEPAD, 8)

        assertFalse(first == second)
        assertFalse(ControllerInputMapper.stableControllerId(first) == ControllerInputMapper.stableControllerId(second))
    }

    @Test
    fun normalizeTriggerMapsFromMinToMax() {
        val calibration = ControllerAxisCalibration(minimum = 0f, maximum = 255f, flat = 10f)
        assertEquals(0.0, ControllerInputMapper.normalizeTrigger(0f, calibration), 0.0)
        assertEquals(0.0, ControllerInputMapper.normalizeTrigger(10f, calibration), 0.0)
        assertEquals(1.0, ControllerInputMapper.normalizeTrigger(255f, calibration), 1e-9)
    }

    @Test
    fun normalizeHatReturnsDirectionalInt() {
        val calibration = ControllerAxisCalibration(minimum = -1f, maximum = 1f, flat = 0.1f)
        assertEquals(0, ControllerInputMapper.normalizeHat(0f, calibration))
        assertEquals(1, ControllerInputMapper.normalizeHat(1f, calibration))
        assertEquals(-1, ControllerInputMapper.normalizeHat(-1f, calibration))
    }

    @Test
    fun isControllerSourceRecognizesGamepadAndJoystick() {
        assertTrue(ControllerInputMapper.isControllerSource(InputDevice.SOURCE_GAMEPAD))
        assertTrue(ControllerInputMapper.isControllerSource(InputDevice.SOURCE_JOYSTICK))
        assertFalse(ControllerInputMapper.isControllerSource(InputDevice.SOURCE_TOUCHSCREEN))
        assertFalse(ControllerInputMapper.isControllerSource(InputDevice.SOURCE_KEYBOARD))
    }

    @Test
    fun keyToButtonMapsKnownGamepadButtons() {
        assertEquals(ControllerButton.A, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_A))
        assertEquals(ControllerButton.B, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_B))
        assertEquals(ControllerButton.START, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_START))
        assertNull(ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_A))
    }

    @Test
    fun keyToHatMapsDpadKeys() {
        assertEquals(ControllerHatButton.UP, ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_DPAD_UP))
        assertEquals(ControllerHatButton.DOWN, ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_DPAD_DOWN))
        assertEquals(ControllerHatButton.LEFT, ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_DPAD_LEFT))
        assertEquals(ControllerHatButton.RIGHT, ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_DPAD_RIGHT))
        assertNull(ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_A))
    }

    @Test
    fun connectEmitsConnectedAndFullState() {
        val state = ControllerSessionState()
        val dispatch = state.connectDispatch("c1")
        assertEquals(ControllerDelivery.STRUCTURAL, dispatch.delivery)
        val kinds = dispatch.samples.map { it.kind }
        assertTrue(kinds.contains(ControllerEventKind.CONNECTED))
        assertTrue(kinds.contains(ControllerEventKind.STATE))
        assertEquals(1L, dispatch.samples.first { it.kind == ControllerEventKind.CONNECTED }.controllerEpoch)
    }

    @Test
    fun fullStateSnapshotsUseStableControllerIdOrder() {
        val state = ControllerSessionState()
        state.connectDispatch("controller-z")
        val second = state.connectDispatch("controller-a")

        assertEquals(
            listOf("controller-a", "controller-z"),
            second.samples
                .filter { it.kind == ControllerEventKind.STATE }
                .map { it.controllerId },
        )
    }

    @Test
    fun connectDistinguishesAlreadyActiveFromLimitReached() {
        val state = ControllerSessionState()
        assertTrue(state.connect("c1") is ControllerConnectResult.Connected)
        assertEquals(ControllerConnectResult.AlreadyActive, state.connect("c1"))
        (2..MAXIMUM_ACTIVE_CONTROLLERS).forEach { index ->
            assertTrue(state.connect("c$index") is ControllerConnectResult.Connected)
        }
        assertEquals(ControllerConnectResult.LimitReached, state.connect("c5"))
    }

    @Test
    fun applyMotionForUnknownControllerAutoConnects() {
        val state = ControllerSessionState()
        val snapshot = ControllerMotionSnapshot("c1", listOf(ControllerAxes(leftX = 0.5)))
        val dispatch = checkNotNull(state.applyMotion(snapshot))
        val kinds = dispatch.samples.map { it.kind }
        assertTrue(kinds.contains(ControllerEventKind.CONNECTED))
        assertTrue(kinds.contains(ControllerEventKind.STATE))
    }

    @Test
    fun applyMotionWithOnlyAnalogAxesIsAnalogDelivery() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        val snapshot = ControllerMotionSnapshot("c1", listOf(ControllerAxes(leftX = 0.5)))
        val dispatch = checkNotNull(state.applyMotion(snapshot))
        assertEquals(ControllerDelivery.ANALOG, dispatch.delivery)
    }

    @Test
    fun applyMotionWithHatChangeIsStructural() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        val snapshot = ControllerMotionSnapshot("c1", listOf(ControllerAxes(hatX = 1)))
        val dispatch = checkNotNull(state.applyMotion(snapshot))
        assertEquals(ControllerDelivery.STRUCTURAL, dispatch.delivery)
    }

    @Test
    fun fifthControllerIsIgnoredUntilAnActiveSlotIsReleased() {
        val state = ControllerSessionState()
        (1..MAXIMUM_ACTIVE_CONTROLLERS).forEach { index ->
            assertTrue(state.connect("c$index") is ControllerConnectResult.Connected)
        }

        assertEquals(ControllerConnectResult.LimitReached, state.connect("c5"))
        assertNull(
            state.applyMotion(
                ControllerMotionSnapshot("c5", listOf(ControllerAxes(leftX = 0.5))),
            ),
        )
        assertNull(
            state.applyKey(
                ControllerKeyChange.Button("c5", pressed = true, ControllerButton.A),
            ),
        )
        assertEquals(
            listOf("c1", "c2", "c3", "c4"),
            state.activeSnapshots().map { it.controllerId },
        )

        assertNotNull(state.disconnect("c2"))
        val takeover = checkNotNull(
            state.applyMotion(
                ControllerMotionSnapshot("c5", listOf(ControllerAxes(leftX = 0.5))),
            ),
        )
        assertTrue(takeover.samples.any { it.controllerId == "c5" && it.kind == ControllerEventKind.CONNECTED })
        assertEquals(
            listOf("c1", "c3", "c4", "c5"),
            state.activeSnapshots().map { it.controllerId },
        )
    }

    @Test
    fun applyKeyButtonPressIsStructural() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        val change = ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A)
        val dispatch = state.applyKey(change)
        assertNotNull(dispatch)
        assertEquals(ControllerDelivery.STRUCTURAL, dispatch!!.delivery)
        val stateSample = dispatch.samples.last { it.kind == ControllerEventKind.STATE }
        assertEquals(1 shl ControllerButton.A.bit, stateSample.buttonMask)
    }

    @Test
    fun applyKeyHatCombinesOppositesAndRestoresMotionHat() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        state.applyMotion(ControllerMotionSnapshot("c1", listOf(ControllerAxes(hatX = 1))))

        val left = checkNotNull(
            state.applyKey(ControllerKeyChange.Hat("c1", pressed = true, ControllerHatButton.LEFT)),
        )
        assertEquals(-1, left.samples.last { it.controllerId == "c1" }.axes.hatX)

        val right = checkNotNull(
            state.applyKey(ControllerKeyChange.Hat("c1", pressed = true, ControllerHatButton.RIGHT)),
        )
        assertEquals(0, right.samples.last { it.controllerId == "c1" }.axes.hatX)

        val leftReleased = checkNotNull(
            state.applyKey(ControllerKeyChange.Hat("c1", pressed = false, ControllerHatButton.LEFT)),
        )
        assertEquals(1, leftReleased.samples.last { it.controllerId == "c1" }.axes.hatX)

        assertNull(
            state.applyKey(ControllerKeyChange.Hat("c1", pressed = false, ControllerHatButton.RIGHT)),
        )
        assertEquals(1, checkNotNull(state.resynchronize()).samples.single().axes.hatX)
    }

    @Test
    fun applyKeyUnchangedButtonReturnsNull() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        val press = ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A)
        state.applyKey(press)
        val pressAgain = ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A)
        assertNull(state.applyKey(pressAgain))
    }

    @Test
    fun disconnectEmitsNeutralStateAndDisconnected() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        state.applyKey(ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A))
        val dispatch = state.disconnect("c1")
        assertNotNull(dispatch)
        val samples = dispatch!!.samples
        val neutral = samples.first { it.kind == ControllerEventKind.STATE }
        assertEquals(0, neutral.buttonMask)
        assertEquals(ControllerAxes.NEUTRAL, neutral.axes)
        assertTrue(samples.any { it.kind == ControllerEventKind.DISCONNECTED })
    }

    @Test
    fun takeReleaseEmitsNeutralForAllActiveControllers() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        state.connectDispatch("c2")
        state.applyKey(ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A))
        val dispatch = state.takeRelease()
        assertNotNull(dispatch)
        val states = dispatch!!.samples.filter { it.kind == ControllerEventKind.STATE }
        assertEquals(2, states.size)
        states.forEach { assertEquals(0, it.buttonMask) }
        assertTrue(dispatch.samples.any { it.kind == ControllerEventKind.DISCONNECTED })
    }

    @Test
    fun takeReleaseOnEmptyReturnsNull() {
        val state = ControllerSessionState()
        assertNull(state.takeRelease())
    }

    @Test
    fun reconnectAfterDisconnectAdvancesEpoch() {
        val state = ControllerSessionState()
        val first = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(1L, first.controllerEpoch)
        state.disconnect("c1")
        val second = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(2L, second.controllerEpoch)
        state.disconnect("c1")
        val third = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(3L, third.controllerEpoch)
    }

    @Test
    fun rejectedConnectionRemovesOnlyExactEpochAndDoesNotRollBackHistory() {
        val state = ControllerSessionState()
        val first = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }

        assertFalse(state.rejectConnection("c1", first.controllerEpoch + 1))
        assertTrue(state.isActive("c1"))
        assertTrue(state.rejectConnection("c1", first.controllerEpoch))
        assertFalse(state.isActive("c1"))

        val retry = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(first.controllerEpoch + 1, retry.controllerEpoch)
    }

    @Test
    fun sameSessionResynchronizationRetainsActiveEpochAndState() {
        val state = ControllerSessionState()
        val first = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(1L, first.controllerEpoch)
        state.applyKey(ControllerKeyChange.Button("c1", pressed = true, ControllerButton.A))

        val resynchronized = checkNotNull(state.resynchronize())

        assertEquals(ControllerDelivery.STRUCTURAL, resynchronized.delivery)
        assertEquals(1, resynchronized.samples.size)
        assertEquals(1L, resynchronized.samples.single().controllerEpoch)
        assertEquals(1 shl ControllerButton.A.bit, resynchronized.samples.single().buttonMask)
    }

    @Test
    fun discardResetsEpochForNewNegotiatedSession() {
        val state = ControllerSessionState()
        // First connection in the initial session.
        assertEquals(1L, state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }.controllerEpoch)
        state.disconnect("c1")
        // Same session: reconnect keeps advancing the epoch.
        assertEquals(2L, state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }.controllerEpoch)
        state.disconnect("c1")

        // discard represents a newly negotiated session: it clears both the active
        // controllers and the remembered epoch map.
        state.resetForNewSession()

        // After discard the same controller id starts a fresh epoch at 1.
        val afterDiscard = state.connectDispatch("c1").samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(1L, afterDiscard.controllerEpoch)
    }

    @Test
    fun discardClearsActiveControllers() {
        val state = ControllerSessionState()
        state.connectDispatch("c1")
        state.resetForNewSession()
        assertNull(state.takeRelease())
    }

    @Test
    fun controllerStateSampleAccepts128MultiByteUtf8Bytes() {
        // 64 two-byte UTF-8 characters (U+00E9) occupy exactly 128 bytes.
        val id128 = "\u00E9".repeat(64)
        assertEquals(128, id128.toByteArray(Charsets.UTF_8).size)
        val sample = ControllerStateSample(id128, 1L, ControllerEventKind.STATE)
        assertEquals(id128, sample.controllerId)
    }

    @Test
    fun controllerStateSampleRejects129MultiByteUtf8Bytes() {
        // 43 three-byte UTF-8 characters (U+4E2D) occupy exactly 129 bytes.
        val id129 = "\u4E2D".repeat(43)
        assertEquals(129, id129.toByteArray(Charsets.UTF_8).size)
        assertThrows(IllegalArgumentException::class.java) {
            ControllerStateSample(id129, 1L, ControllerEventKind.STATE)
        }
    }

    private fun ControllerSessionState.connectDispatch(controllerId: String): ControllerDispatch {
        val result = connect(controllerId)
        check(result is ControllerConnectResult.Connected) {
            "Expected $controllerId to connect, but admission returned $result"
        }
        return result.dispatch
    }
}
