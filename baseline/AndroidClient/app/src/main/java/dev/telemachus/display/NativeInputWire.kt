package dev.telemachus.display

import android.view.MotionEvent

/**
 * Shared native-input wire encoding for Protocol v1 pointer/keyboard.
 *
 * These bit conventions are owned end to end with the macOS host
 * (StreamInputWire): the host decodes the same PointerEvent.button_mask and
 * KeyEvent.modifier_mask bits into CGEvent buttons and modifier flags.
 */
internal object NativeInputWire {
    // PointerEvent.button_mask bits.
    const val BUTTON_PRIMARY = 1 shl 0
    const val BUTTON_SECONDARY = 1 shl 1

    // KeyEvent.modifier_mask bits.
    const val MODIFIER_SHIFT = 1 shl 0
    const val MODIFIER_CONTROL = 1 shl 1
    const val MODIFIER_OPTION = 1 shl 2
    const val MODIFIER_COMMAND = 1 shl 3

    /** Translates Android MotionEvent button state into wire button bits. */
    fun buttonMask(androidButtonState: Int): Int {
        var mask = 0
        if (androidButtonState and MotionEvent.BUTTON_PRIMARY != 0) mask = mask or BUTTON_PRIMARY
        if (androidButtonState and MotionEvent.BUTTON_SECONDARY != 0) mask = mask or BUTTON_SECONDARY
        return mask
    }

    /** Translates protocol-neutral key modifiers into wire modifier bits. */
    fun modifierMask(modifiers: Set<ClientKeyModifier>): Int {
        var mask = 0
        if (ClientKeyModifier.SHIFT in modifiers) mask = mask or MODIFIER_SHIFT
        if (ClientKeyModifier.CONTROL in modifiers) mask = mask or MODIFIER_CONTROL
        if (ClientKeyModifier.ALT in modifiers) mask = mask or MODIFIER_OPTION
        if (ClientKeyModifier.META in modifiers) mask = mask or MODIFIER_COMMAND
        return mask
    }
}
