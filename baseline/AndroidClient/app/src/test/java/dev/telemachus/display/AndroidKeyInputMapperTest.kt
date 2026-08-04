package dev.telemachus.display

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidKeyInputMapperTest {
    @Test
    fun `maps letter shortcut and modifiers to protocol neutral event`() {
        val input =
            requireNotNull(
                AndroidKeyInputMapper.map(
                    keyCode = KeyEvent.KEYCODE_C,
                    action = KeyEvent.ACTION_DOWN,
                    metaState = KeyEvent.META_META_ON or KeyEvent.META_SHIFT_ON,
                    repeatCount = 0,
                ),
            )

        assertEquals(0x06, input.usbHidUsage)
        assertTrue(input.pressed)
        assertEquals(setOf(ClientKeyModifier.META, ClientKeyModifier.SHIFT), input.modifiers)
    }

    @Test
    fun `maps release arrows enter and backspace`() {
        val left = requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.ACTION_UP, 0, 2))

        assertEquals(0x50, left.usbHidUsage)
        assertFalse(left.pressed)
        assertEquals(2, left.repeatCount)
        assertEquals(0x28, requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_ENTER, 0, 0, 0)).usbHidUsage)
        assertEquals(0x2A, requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_DEL, 0, 0, 0)).usbHidUsage)
    }

    @Test
    fun `rejects unknown keys and non key actions`() {
        assertNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_UNKNOWN, KeyEvent.ACTION_DOWN, 0, 0))
        assertNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_A, 99, 0, 0))
    }

    @Test
    fun `physical shortcut press and release preserve usage and modifiers`() {
        val metaState = KeyEvent.META_CTRL_ON or KeyEvent.META_ALT_ON
        val down =
            requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_F5, KeyEvent.ACTION_DOWN, metaState, 0))
        val up =
            requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_F5, KeyEvent.ACTION_UP, metaState, 0))

        assertEquals(0x3E, down.usbHidUsage)
        assertEquals(down.usbHidUsage, up.usbHidUsage)
        assertTrue(down.pressed)
        assertFalse(up.pressed)
        assertEquals(setOf(ClientKeyModifier.CONTROL, ClientKeyModifier.ALT), down.modifiers)
        assertEquals(down.modifiers, up.modifiers)
    }
}
