package dev.telemachus.display

import android.view.InputDevice
import android.view.MotionEvent
import dev.vibescreen.protocol.v1.InputPhase

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

    // Canonical standard USB HID modifier byte used inside the client.
    const val MODIFIER_CONTROL = 1 shl 0
    const val MODIFIER_SHIFT = 1 shl 1
    const val MODIFIER_OPTION = 1 shl 2
    const val MODIFIER_COMMAND = 1 shl 3
    const val MODIFIER_RIGHT_CONTROL = 1 shl 4
    const val MODIFIER_RIGHT_SHIFT = 1 shl 5
    const val MODIFIER_RIGHT_OPTION = 1 shl 6
    const val MODIFIER_RIGHT_COMMAND = 1 shl 7
    const val MODIFIER_BYTE_MASK = 0xFF

    /** Translates Android MotionEvent button state into wire button bits. */
    fun buttonMask(androidButtonState: Int): Int {
        var mask = 0
        if (androidButtonState and MotionEvent.BUTTON_PRIMARY != 0) mask = mask or BUTTON_PRIMARY
        if (androidButtonState and MotionEvent.BUTTON_SECONDARY != 0) mask = mask or BUTTON_SECONDARY
        return mask
    }

    fun mouseLikeSourceNames(androidSource: Int): List<String> =
        buildList {
            if (androidSource hasSource InputDevice.SOURCE_MOUSE) add("MOUSE")
            if (androidSource hasSource InputDevice.SOURCE_MOUSE_RELATIVE) add("MOUSE_RELATIVE")
            if (androidSource hasSource InputDevice.SOURCE_TOUCHPAD) add("TOUCHPAD")
            if (androidSource hasSource InputDevice.SOURCE_TRACKBALL) add("TRACKBALL")
        }

    fun isMouseLikeSource(androidSource: Int): Boolean = mouseLikeSourceNames(androidSource).isNotEmpty()

    /**
     * Maps Android button transitions onto the Host's absolute button-mask
     * contract. Android reports the absolute post-transition button state
     * separately from the button that changed; unsupported changed buttons must
     * not create or mutate a host pointer sequence.
     */
    fun pointerPhase(
        action: ClientPointerAction,
        wireButtonMask: Int,
        changedButtonMask: Int,
    ): InputPhase? =
        when (action) {
            ClientPointerAction.MOVE -> InputPhase.INPUT_PHASE_CHANGED
            ClientPointerAction.BUTTON_PRESS ->
                if (changedButtonMask == 0) null else InputPhase.INPUT_PHASE_BEGAN
            ClientPointerAction.BUTTON_RELEASE ->
                if (changedButtonMask == 0) {
                    null
                } else if (wireButtonMask == 0) {
                    InputPhase.INPUT_PHASE_ENDED
                } else {
                    InputPhase.INPUT_PHASE_CHANGED
                }
            ClientPointerAction.SCROLL -> null
        }

    private infix fun Int.hasSource(source: Int): Boolean = this and source == source

    /** Translates protocol-neutral key modifiers into wire modifier bits. */
    fun modifierMask(modifiers: Set<ClientKeyModifier>): Int {
        var mask = 0
        if (ClientKeyModifier.SHIFT in modifiers) mask = mask or MODIFIER_SHIFT
        if (ClientKeyModifier.CONTROL in modifiers) mask = mask or MODIFIER_CONTROL
        if (ClientKeyModifier.ALT in modifiers) mask = mask or MODIFIER_OPTION
        if (ClientKeyModifier.META in modifiers) mask = mask or MODIFIER_COMMAND
        return mask
    }

    /** Encodes the negotiated standard byte or the four-bit legacy fallback. */
    fun wireModifierMask(
        standardMask: Int,
        standardByteNegotiated: Boolean,
    ): Int {
        require(standardMask and MODIFIER_BYTE_MASK.inv() == 0)
        if (standardByteNegotiated) return standardMask

        // Legacy v1 is Shift, Control, Option, Command in bits 0..3.
        var legacyMask = 0
        if (standardMask and (MODIFIER_SHIFT or MODIFIER_RIGHT_SHIFT) != 0) legacyMask = legacyMask or 0x01
        if (standardMask and (MODIFIER_CONTROL or MODIFIER_RIGHT_CONTROL) != 0) legacyMask = legacyMask or 0x02
        if (standardMask and (MODIFIER_OPTION or MODIFIER_RIGHT_OPTION) != 0) legacyMask = legacyMask or 0x04
        if (standardMask and (MODIFIER_COMMAND or MODIFIER_RIGHT_COMMAND) != 0) legacyMask = legacyMask or 0x08
        return legacyMask
    }
}
