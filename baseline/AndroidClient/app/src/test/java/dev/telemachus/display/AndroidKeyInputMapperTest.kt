package dev.telemachus.display

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidKeyInputMapperTest {
    @Test
    fun `maps letter digit function navigation and punctuation HID usages`() {
        val cases =
            listOf(
                KeyEvent.KEYCODE_A to 0x04,
                KeyEvent.KEYCODE_Z to 0x1D,
                KeyEvent.KEYCODE_1 to 0x1E,
                KeyEvent.KEYCODE_9 to 0x26,
                KeyEvent.KEYCODE_0 to 0x27,
                KeyEvent.KEYCODE_TAB to 0x2B,
                KeyEvent.KEYCODE_SPACE to 0x2C,
                KeyEvent.KEYCODE_MINUS to 0x2D,
                KeyEvent.KEYCODE_EQUALS to 0x2E,
                KeyEvent.KEYCODE_LEFT_BRACKET to 0x2F,
                KeyEvent.KEYCODE_RIGHT_BRACKET to 0x30,
                KeyEvent.KEYCODE_BACKSLASH to 0x31,
                KeyEvent.KEYCODE_SEMICOLON to 0x33,
                KeyEvent.KEYCODE_APOSTROPHE to 0x34,
                KeyEvent.KEYCODE_GRAVE to 0x35,
                KeyEvent.KEYCODE_COMMA to 0x36,
                KeyEvent.KEYCODE_PERIOD to 0x37,
                KeyEvent.KEYCODE_SLASH to 0x38,
                KeyEvent.KEYCODE_F1 to 0x3A,
                KeyEvent.KEYCODE_F12 to 0x45,
                KeyEvent.KEYCODE_MOVE_HOME to 0x4A,
                KeyEvent.KEYCODE_MOVE_END to 0x4D,
                KeyEvent.KEYCODE_DPAD_RIGHT to 0x4F,
                KeyEvent.KEYCODE_DPAD_LEFT to 0x50,
                KeyEvent.KEYCODE_DPAD_DOWN to 0x51,
                KeyEvent.KEYCODE_DPAD_UP to 0x52,
                KeyEvent.KEYCODE_ESCAPE to 0x29,
            )

        cases.forEach { (keyCode, expectedUsage) ->
            assertEquals(
                "Unexpected HID usage for keyCode=$keyCode",
                expectedUsage,
                requireNotNull(AndroidKeyInputMapper.map(keyCode, KeyEvent.ACTION_DOWN, 0, 0)).usbHidUsage,
            )
        }
    }

    @Test
    fun `maps editing page navigation and numeric keypad HID usages`() {
        val cases =
            listOf(
                KeyEvent.KEYCODE_INSERT to 0x49,
                KeyEvent.KEYCODE_PAGE_UP to 0x4B,
                KeyEvent.KEYCODE_FORWARD_DEL to 0x4C,
                KeyEvent.KEYCODE_PAGE_DOWN to 0x4E,
                KeyEvent.KEYCODE_NUM_LOCK to 0x53,
                KeyEvent.KEYCODE_NUMPAD_DIVIDE to 0x54,
                KeyEvent.KEYCODE_NUMPAD_MULTIPLY to 0x55,
                KeyEvent.KEYCODE_NUMPAD_SUBTRACT to 0x56,
                KeyEvent.KEYCODE_NUMPAD_ADD to 0x57,
                KeyEvent.KEYCODE_NUMPAD_ENTER to 0x58,
                KeyEvent.KEYCODE_NUMPAD_1 to 0x59,
                KeyEvent.KEYCODE_NUMPAD_2 to 0x5A,
                KeyEvent.KEYCODE_NUMPAD_3 to 0x5B,
                KeyEvent.KEYCODE_NUMPAD_4 to 0x5C,
                KeyEvent.KEYCODE_NUMPAD_5 to 0x5D,
                KeyEvent.KEYCODE_NUMPAD_6 to 0x5E,
                KeyEvent.KEYCODE_NUMPAD_7 to 0x5F,
                KeyEvent.KEYCODE_NUMPAD_8 to 0x60,
                KeyEvent.KEYCODE_NUMPAD_9 to 0x61,
                KeyEvent.KEYCODE_NUMPAD_0 to 0x62,
                KeyEvent.KEYCODE_NUMPAD_DOT to 0x63,
                KeyEvent.KEYCODE_NUMPAD_EQUALS to 0x67,
            )

        cases.forEach { (keyCode, expectedUsage) ->
            assertEquals(
                "Unexpected HID usage for keyCode=$keyCode",
                expectedUsage,
                requireNotNull(AndroidKeyInputMapper.map(keyCode, KeyEvent.ACTION_DOWN, 0, 0)).usbHidUsage,
            )
        }
    }

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
    fun `maps normalized aggregate modifier state and clamps negative repeat counts`() {
        val input =
            requireNotNull(
                AndroidKeyInputMapper.map(
                    keyCode = KeyEvent.KEYCODE_SLASH,
                    action = KeyEvent.ACTION_DOWN,
                    metaState =
                        KeyEvent.META_SHIFT_LEFT_ON or
                            KeyEvent.META_CTRL_RIGHT_ON or
                            KeyEvent.META_ALT_LEFT_ON or
                            KeyEvent.META_META_RIGHT_ON,
                    repeatCount = -7,
                ),
            )

        assertEquals(0x38, input.usbHidUsage)
        assertEquals(
            setOf(
                ClientKeyModifier.SHIFT,
                ClientKeyModifier.CONTROL,
                ClientKeyModifier.ALT,
                ClientKeyModifier.META,
            ),
            input.modifiers,
        )
        assertEquals(0, input.repeatCount)
    }

    @Test
    fun `maps release arrows enter and backspace`() {
        val left = requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.ACTION_UP, 0, 2))

        assertEquals(0x50, left.usbHidUsage)
        assertFalse(left.pressed)
        assertEquals(2, left.repeatCount)
        assertEquals(0x28, requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_ENTER, 0, 0, 0)).usbHidUsage)
        assertEquals(
            0x58,
            requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_NUMPAD_ENTER, 0, 0, 0)).usbHidUsage,
        )
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

    @Test
    fun `shortcut release sequence preserves usage and only reports currently active modifiers`() {
        val commandShift = KeyEvent.META_META_LEFT_ON or KeyEvent.META_SHIFT_LEFT_ON
        val keyDown = requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_P, KeyEvent.ACTION_DOWN, commandShift, 0))
        val keyUp = requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_P, KeyEvent.ACTION_UP, commandShift, 0))
        val laterPlain = requireNotNull(AndroidKeyInputMapper.map(KeyEvent.KEYCODE_P, KeyEvent.ACTION_DOWN, 0, 0))

        assertEquals(listOf(0x13, 0x13, 0x13), listOf(keyDown.usbHidUsage, keyUp.usbHidUsage, laterPlain.usbHidUsage))
        assertEquals(listOf(true, false, true), listOf(keyDown.pressed, keyUp.pressed, laterPlain.pressed))
        assertEquals(setOf(ClientKeyModifier.META, ClientKeyModifier.SHIFT), keyDown.modifiers)
        assertEquals(keyDown.modifiers, keyUp.modifiers)
        assertEquals(emptySet<ClientKeyModifier>(), laterPlain.modifiers)
    }

    @Test
    fun `modifier only caps lock function media and unknown keys fail closed`() {
        listOf(
            KeyEvent.KEYCODE_SHIFT_LEFT,
            KeyEvent.KEYCODE_SHIFT_RIGHT,
            KeyEvent.KEYCODE_CTRL_LEFT,
            KeyEvent.KEYCODE_CTRL_RIGHT,
            KeyEvent.KEYCODE_ALT_LEFT,
            KeyEvent.KEYCODE_ALT_RIGHT,
            KeyEvent.KEYCODE_META_LEFT,
            KeyEvent.KEYCODE_META_RIGHT,
            KeyEvent.KEYCODE_CAPS_LOCK,
            KeyEvent.KEYCODE_FUNCTION,
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
            KeyEvent.KEYCODE_MEDIA_NEXT,
            KeyEvent.KEYCODE_UNKNOWN,
        ).forEach { keyCode ->
            assertNull(
                "keyCode=$keyCode",
                AndroidKeyInputMapper.map(
                    keyCode = keyCode,
                    action = KeyEvent.ACTION_DOWN,
                    metaState = KeyEvent.META_SHIFT_ON or KeyEvent.META_CTRL_ON,
                    repeatCount = 0,
                ),
            )
            assertNull(
                "keyCode=$keyCode",
                AndroidKeyInputMapper.map(
                    keyCode = keyCode,
                    action = KeyEvent.ACTION_UP,
                    metaState = 0,
                    repeatCount = 0,
                ),
            )
        }
    }
}
