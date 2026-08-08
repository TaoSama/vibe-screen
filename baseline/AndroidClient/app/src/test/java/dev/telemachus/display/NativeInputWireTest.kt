package dev.telemachus.display

import android.view.MotionEvent
import org.junit.Assert.assertEquals
import org.junit.Test

/** Verifies the shared native-input wire encoding matches the host bits. */
class NativeInputWireTest {
    @Test
    fun buttonMaskMapsPrimaryAndSecondary() {
        assertEquals(NativeInputWire.BUTTON_PRIMARY, NativeInputWire.buttonMask(MotionEvent.BUTTON_PRIMARY))
        assertEquals(NativeInputWire.BUTTON_SECONDARY, NativeInputWire.buttonMask(MotionEvent.BUTTON_SECONDARY))
        assertEquals(
            NativeInputWire.BUTTON_PRIMARY or NativeInputWire.BUTTON_SECONDARY,
            NativeInputWire.buttonMask(MotionEvent.BUTTON_PRIMARY or MotionEvent.BUTTON_SECONDARY),
        )
        assertEquals(0, NativeInputWire.buttonMask(0))
    }

    @Test
    fun modifierMaskMapsEachModifierBit() {
        assertEquals(
            NativeInputWire.MODIFIER_SHIFT or NativeInputWire.MODIFIER_COMMAND,
            NativeInputWire.modifierMask(setOf(ClientKeyModifier.SHIFT, ClientKeyModifier.META)),
        )
        assertEquals(
            NativeInputWire.MODIFIER_CONTROL or NativeInputWire.MODIFIER_OPTION,
            NativeInputWire.modifierMask(setOf(ClientKeyModifier.CONTROL, ClientKeyModifier.ALT)),
        )
        assertEquals(0, NativeInputWire.modifierMask(emptySet()))
    }
}
