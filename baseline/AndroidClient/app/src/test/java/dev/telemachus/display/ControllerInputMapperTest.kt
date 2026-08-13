package dev.telemachus.display

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ControllerInputMapperTest {
    @Test
    fun `normalizes asymmetric sticks with flat deadzone`() {
        val calibration = ControllerAxisCalibration(-0.8f, 1.0f, 0.1f)

        assertEquals(0.0, ControllerInputMapper.normalizeStick(0.05f, calibration), 0.0)
        assertEquals(0.5, ControllerInputMapper.normalizeStick(0.55f, calibration), 1e-6)
        assertEquals(-0.5, ControllerInputMapper.normalizeStick(-0.45f, calibration), 1e-6)
        assertEquals(1.0, ControllerInputMapper.normalizeStick(5f, calibration), 0.0)
    }

    @Test
    fun `normalizes triggers and quantizes hats`() {
        val trigger = ControllerAxisCalibration(-1f, 1f, 0.2f)
        val hat = ControllerAxisCalibration(-1f, 1f, 0.0f)

        assertEquals(0.0, ControllerInputMapper.normalizeTrigger(-1f, trigger), 0.0)
        assertEquals(1.0, ControllerInputMapper.normalizeTrigger(1f, trigger), 0.0)
        assertEquals(-1, ControllerInputMapper.normalizeHat(-0.8f, hat))
        assertEquals(0, ControllerInputMapper.normalizeHat(0.2f, hat))
        assertEquals(1, ControllerInputMapper.normalizeHat(0.8f, hat))
    }

    @Test
    fun `stable identifiers neither expose descriptors nor alias devices`() {
        val first = ControllerInputMapper.stableControllerId("vendor-a/device-1")
        assertEquals(first, ControllerInputMapper.stableControllerId("vendor-a/device-1"))
        assertNotEquals(first, ControllerInputMapper.stableControllerId("vendor-a/device-2"))
        assertTrue(first.startsWith("android-"))
        assertTrue("vendor-a" !in first)
    }

    @Test
    fun `canonical buttons occupy exactly bits zero through twelve`() {
        assertEquals(
            listOf(
                ControllerButton.A to 0,
                ControllerButton.B to 1,
                ControllerButton.X to 2,
                ControllerButton.Y to 3,
                ControllerButton.LEFT_SHOULDER to 4,
                ControllerButton.RIGHT_SHOULDER to 5,
                ControllerButton.LEFT_TRIGGER to 6,
                ControllerButton.RIGHT_TRIGGER to 7,
                ControllerButton.SELECT to 8,
                ControllerButton.START to 9,
                ControllerButton.MODE to 10,
                ControllerButton.LEFT_STICK to 11,
                ControllerButton.RIGHT_STICK to 12,
            ),
            ControllerButton.entries.map { it to it.bit },
        )
        assertEquals(ControllerButton.A, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_A))
        assertEquals(ControllerButton.MODE, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_MODE))
        assertEquals(ControllerButton.LEFT_STICK, ControllerInputMapper.keyToButton(KeyEvent.KEYCODE_BUTTON_THUMBL))
        assertEquals(ControllerHatButton.LEFT, ControllerInputMapper.keyToHat(KeyEvent.KEYCODE_DPAD_LEFT))
    }

    @Test
    fun `motion keeps history order and every frame carries all active controllers`() {
        val state = ControllerSessionState()
        state.applyMotion(ControllerMotionSnapshot("first", listOf(axes(leftX = 0.2))))
        state.connect("second")

        val dispatch =
            state.applyMotion(
                ControllerMotionSnapshot(
                    "second",
                    listOf(axes(leftX = 0.3), axes(leftX = 0.6)),
                ),
            )

        assertEquals(ControllerDelivery.ANALOG, dispatch.delivery)
        assertEquals(listOf("first", "second", "first", "second"), dispatch.samples.map { it.controllerId })
        assertEquals(listOf(0.3, 0.6), dispatch.samples.filter { it.controllerId == "second" }.map { it.axes.leftX })
        assertTrue(dispatch.samples.all { it.kind == ControllerEventKind.STATE })
    }

    @Test
    fun `button and hat changes are structural full snapshots`() {
        val state = ControllerSessionState()
        state.connect("first")
        state.connect("second")

        val button = state.applyKey(ControllerKeyChange.Button("first", true, ControllerButton.RIGHT_TRIGGER))!!
        assertEquals(ControllerDelivery.STRUCTURAL, button.delivery)
        assertEquals(listOf("first", "second"), button.samples.map { it.controllerId })
        assertEquals(1 shl ControllerButton.RIGHT_TRIGGER.bit, button.samples.first().buttonMask)

        val hat = state.applyKey(ControllerKeyChange.Hat("second", true, ControllerHatButton.UP))!!
        assertEquals(-1, hat.samples.single { it.controllerId == "second" }.axes.hatY)
    }

    @Test
    fun `reconnect increments epoch and release neutralizes before disconnect`() {
        val state = ControllerSessionState()
        val connected = state.connect("pad")!!.samples.first { it.kind == ControllerEventKind.CONNECTED }
        state.applyKey(ControllerKeyChange.Button("pad", true, ControllerButton.A))
        val release = state.takeRelease()!!

        assertEquals(
            listOf(ControllerEventKind.STATE, ControllerEventKind.DISCONNECTED),
            release.samples.map { it.kind },
        )
        assertTrue(release.samples.all { it.buttonMask == 0 && it.axes == ControllerAxes.NEUTRAL })
        val reconnected = state.connect("pad")!!.samples.first { it.kind == ControllerEventKind.CONNECTED }
        assertEquals(connected.controllerEpoch + 1, reconnected.controllerEpoch)
    }

    @Test
    fun `physical hat is restored when dpad key is released`() {
        val state = ControllerSessionState()
        state.applyMotion(ControllerMotionSnapshot("pad", listOf(axes(hatX = -1))))
        state.applyKey(ControllerKeyChange.Hat("pad", true, ControllerHatButton.RIGHT))

        val released = state.applyKey(ControllerKeyChange.Hat("pad", false, ControllerHatButton.RIGHT))!!

        assertEquals(-1, released.samples.single().axes.hatX)
    }

    @Test
    fun `connect and disconnect structural batches carry every remaining controller state`() {
        val state = ControllerSessionState()
        state.applyMotion(ControllerMotionSnapshot("b", listOf(axes(leftX = 0.75))))

        val connectA = state.connect("a")!!
        assertEquals(
            listOf(
                "a" to ControllerEventKind.CONNECTED,
                "a" to ControllerEventKind.STATE,
                "b" to ControllerEventKind.STATE,
            ),
            connectA.samples.map { it.controllerId to it.kind },
        )
        assertEquals(0.75, connectA.samples.single { it.controllerId == "b" }.axes.leftX, 0.0)

        val disconnectA = state.disconnect("a")!!
        assertEquals(
            listOf(
                "a" to ControllerEventKind.STATE,
                "a" to ControllerEventKind.DISCONNECTED,
                "b" to ControllerEventKind.STATE,
            ),
            disconnectA.samples.map { it.controllerId to it.kind },
        )
        assertEquals(0.75, disconnectA.samples.single { it.controllerId == "b" }.axes.leftX, 0.0)
    }

    private fun axes(
        leftX: Double = 0.0,
        hatX: Int = 0,
    ) = ControllerAxes(leftX = leftX, hatX = hatX)
}
