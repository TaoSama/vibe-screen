package dev.telemachus.display

import android.view.KeyEvent

internal enum class ClientKeyModifier {
    SHIFT,
    CONTROL,
    ALT,
    META,
}

internal data class ClientKeyInput(
    val usbHidUsage: Int,
    val pressed: Boolean,
    val modifiers: Set<ClientKeyModifier>,
    val repeatCount: Int,
)

/** Converts Android physical-key events into protocol-neutral USB HID usages. */
internal object AndroidKeyInputMapper {
    fun map(
        keyCode: Int,
        action: Int,
        metaState: Int,
        repeatCount: Int,
    ): ClientKeyInput? {
        val usage = keyCode.toUsbHidUsage() ?: return null
        if (action != KeyEvent.ACTION_DOWN && action != KeyEvent.ACTION_UP) return null
        return ClientKeyInput(
            usbHidUsage = usage,
            pressed = action == KeyEvent.ACTION_DOWN,
            modifiers =
                buildSet {
                    if (metaState and KeyEvent.META_SHIFT_ON != 0) add(ClientKeyModifier.SHIFT)
                    if (metaState and KeyEvent.META_CTRL_ON != 0) add(ClientKeyModifier.CONTROL)
                    if (metaState and KeyEvent.META_ALT_ON != 0) add(ClientKeyModifier.ALT)
                    if (metaState and KeyEvent.META_META_ON != 0) add(ClientKeyModifier.META)
                },
            repeatCount = repeatCount.coerceAtLeast(0),
        )
    }

    private fun Int.toUsbHidUsage(): Int? =
        when (this) {
            in KeyEvent.KEYCODE_A..KeyEvent.KEYCODE_Z -> HID_A + (this - KeyEvent.KEYCODE_A)
            in KeyEvent.KEYCODE_1..KeyEvent.KEYCODE_9 -> HID_1 + (this - KeyEvent.KEYCODE_1)
            KeyEvent.KEYCODE_0 -> HID_0
            KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> 0x28
            KeyEvent.KEYCODE_ESCAPE -> 0x29
            KeyEvent.KEYCODE_DEL -> 0x2A
            KeyEvent.KEYCODE_TAB -> 0x2B
            KeyEvent.KEYCODE_SPACE -> 0x2C
            KeyEvent.KEYCODE_MINUS -> 0x2D
            KeyEvent.KEYCODE_EQUALS -> 0x2E
            KeyEvent.KEYCODE_LEFT_BRACKET -> 0x2F
            KeyEvent.KEYCODE_RIGHT_BRACKET -> 0x30
            KeyEvent.KEYCODE_BACKSLASH -> 0x31
            KeyEvent.KEYCODE_SEMICOLON -> 0x33
            KeyEvent.KEYCODE_APOSTROPHE -> 0x34
            KeyEvent.KEYCODE_GRAVE -> 0x35
            KeyEvent.KEYCODE_COMMA -> 0x36
            KeyEvent.KEYCODE_PERIOD -> 0x37
            KeyEvent.KEYCODE_SLASH -> 0x38
            in KeyEvent.KEYCODE_F1..KeyEvent.KEYCODE_F12 -> 0x3A + (this - KeyEvent.KEYCODE_F1)
            KeyEvent.KEYCODE_MOVE_HOME -> 0x4A
            KeyEvent.KEYCODE_MOVE_END -> 0x4D
            KeyEvent.KEYCODE_DPAD_RIGHT -> 0x4F
            KeyEvent.KEYCODE_DPAD_LEFT -> 0x50
            KeyEvent.KEYCODE_DPAD_DOWN -> 0x51
            KeyEvent.KEYCODE_DPAD_UP -> 0x52
            else -> null
        }

    private const val HID_A = 0x04
    private const val HID_1 = 0x1E
    private const val HID_0 = 0x27
}
