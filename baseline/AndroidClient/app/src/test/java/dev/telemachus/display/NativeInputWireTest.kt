package dev.telemachus.display

import android.view.MotionEvent
import dev.vibescreen.protocol.v1.InputPhase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
    fun buttonMaskFiltersUnsupportedTertiaryBackAndForwardButtons() {
        assertEquals(0, NativeInputWire.buttonMask(MotionEvent.BUTTON_TERTIARY))
        assertEquals(0, NativeInputWire.buttonMask(MotionEvent.BUTTON_BACK))
        assertEquals(0, NativeInputWire.buttonMask(MotionEvent.BUTTON_FORWARD))
        assertEquals(
            NativeInputWire.BUTTON_PRIMARY,
            NativeInputWire.buttonMask(MotionEvent.BUTTON_PRIMARY or MotionEvent.BUTTON_TERTIARY),
        )
        assertEquals(
            NativeInputWire.BUTTON_SECONDARY,
            NativeInputWire.buttonMask(MotionEvent.BUTTON_SECONDARY or MotionEvent.BUTTON_BACK or MotionEvent.BUTTON_FORWARD),
        )
    }

    @Test
    fun pointerActionMapsHoverBoundariesToExplicitNativePointerActions() {
        assertEquals(ClientPointerAction.HOVER_ENTER, NativeInputWire.pointerAction(MotionEvent.ACTION_HOVER_ENTER))
        assertEquals(ClientPointerAction.MOVE, NativeInputWire.pointerAction(MotionEvent.ACTION_HOVER_MOVE))
        assertEquals(ClientPointerAction.HOVER_EXIT, NativeInputWire.pointerAction(MotionEvent.ACTION_HOVER_EXIT))
        assertEquals(ClientPointerAction.MOVE, NativeInputWire.pointerAction(MotionEvent.ACTION_MOVE))
        assertEquals(ClientPointerAction.BUTTON_PRESS, NativeInputWire.pointerAction(MotionEvent.ACTION_BUTTON_PRESS))
        assertEquals(ClientPointerAction.BUTTON_RELEASE, NativeInputWire.pointerAction(MotionEvent.ACTION_BUTTON_RELEASE))
        assertEquals(ClientPointerAction.SCROLL, NativeInputWire.pointerAction(MotionEvent.ACTION_SCROLL))
        assertNull(NativeInputWire.pointerAction(MotionEvent.ACTION_CANCEL))
    }

    @Test
    fun outboundButtonMaskClearsHoverBoundariesAndPreservesOrdinaryPointerButtons() {
        val heldButtons = MotionEvent.BUTTON_PRIMARY or MotionEvent.BUTTON_SECONDARY

        assertEquals(0, NativeInputWire.outboundButtonMask(ClientPointerAction.HOVER_ENTER, heldButtons))
        assertEquals(0, NativeInputWire.outboundButtonMask(ClientPointerAction.HOVER_EXIT, heldButtons))
        assertEquals(
            NativeInputWire.BUTTON_PRIMARY or NativeInputWire.BUTTON_SECONDARY,
            NativeInputWire.outboundButtonMask(ClientPointerAction.MOVE, heldButtons),
        )
        assertEquals(
            NativeInputWire.BUTTON_PRIMARY,
            NativeInputWire.outboundButtonMask(ClientPointerAction.BUTTON_PRESS, MotionEvent.BUTTON_PRIMARY),
        )
    }

    @Test
    fun mouseLikeSourceNamesMatchPhysicalPointerGateSources() {
        assertEquals(listOf("MOUSE"), NativeInputWire.mouseLikeSourceNames(android.view.InputDevice.SOURCE_MOUSE))
        assertEquals(
            listOf("MOUSE_RELATIVE"),
            NativeInputWire.mouseLikeSourceNames(android.view.InputDevice.SOURCE_MOUSE_RELATIVE),
        )
        assertEquals(listOf("TOUCHPAD"), NativeInputWire.mouseLikeSourceNames(android.view.InputDevice.SOURCE_TOUCHPAD))
        assertEquals(listOf("TRACKBALL"), NativeInputWire.mouseLikeSourceNames(android.view.InputDevice.SOURCE_TRACKBALL))
        assertEquals(
            listOf("MOUSE", "TOUCHPAD"),
            NativeInputWire.mouseLikeSourceNames(
                android.view.InputDevice.SOURCE_MOUSE or android.view.InputDevice.SOURCE_TOUCHPAD,
            ),
        )
        assertEquals(emptyList<String>(), NativeInputWire.mouseLikeSourceNames(android.view.InputDevice.SOURCE_TOUCHSCREEN))
    }

    @Test
    fun mouseLikeSourceNamesPreferInputDeviceSourceMaskWhenAvailable() {
        assertEquals(
            listOf("MOUSE", "TOUCHPAD"),
            NativeInputWire.mouseLikeSourceNames(
                eventSource = android.view.InputDevice.SOURCE_MOUSE,
                inputDeviceSources = android.view.InputDevice.SOURCE_MOUSE or android.view.InputDevice.SOURCE_TOUCHPAD,
            ),
        )
        assertEquals(
            listOf("MOUSE"),
            NativeInputWire.mouseLikeSourceNames(
                eventSource = android.view.InputDevice.SOURCE_MOUSE,
                inputDeviceSources = null,
            ),
        )
    }

    @Test
    fun pointerPhasePreservesRemainingButtonsOnPartialRelease() {
        assertEquals(
            InputPhase.INPUT_PHASE_BEGAN,
            NativeInputWire.pointerPhase(
                ClientPointerAction.BUTTON_PRESS,
                NativeInputWire.BUTTON_PRIMARY,
                NativeInputWire.BUTTON_PRIMARY,
            ),
        )
        assertEquals(
            InputPhase.INPUT_PHASE_CHANGED,
            NativeInputWire.pointerPhase(
                ClientPointerAction.BUTTON_RELEASE,
                NativeInputWire.BUTTON_SECONDARY,
                NativeInputWire.BUTTON_PRIMARY,
            ),
        )
        assertEquals(
            InputPhase.INPUT_PHASE_ENDED,
            NativeInputWire.pointerPhase(
                ClientPointerAction.BUTTON_RELEASE,
                0,
                NativeInputWire.BUTTON_PRIMARY,
            ),
        )
    }

    @Test
    fun pointerPhaseDropsUnsupportedButtonPresses() {
        assertEquals(InputPhase.INPUT_PHASE_CHANGED, NativeInputWire.pointerPhase(ClientPointerAction.MOVE, 0, 0))
        assertEquals(InputPhase.INPUT_PHASE_CHANGED, NativeInputWire.pointerPhase(ClientPointerAction.HOVER_ENTER, 0, 0))
        assertEquals(InputPhase.INPUT_PHASE_ENDED, NativeInputWire.pointerPhase(ClientPointerAction.HOVER_EXIT, 0, 0))
        assertEquals(
            InputPhase.INPUT_PHASE_CANCELLED,
            NativeInputWire.pointerPhase(
                ClientPointerAction.HOVER_EXIT,
                NativeInputWire.BUTTON_PRIMARY,
                0,
            ),
        )
        assertNull(NativeInputWire.pointerPhase(ClientPointerAction.BUTTON_PRESS, 0, 0))
        assertNull(NativeInputWire.pointerPhase(ClientPointerAction.SCROLL, NativeInputWire.BUTTON_PRIMARY, 0))
    }

    @Test
    fun pointerPhaseDropsUnsupportedButtonTransitionEvenWithSupportedButtonHeld() {
        val heldButtonMask = NativeInputWire.BUTTON_PRIMARY

        assertNull(
            NativeInputWire.pointerPhase(
                ClientPointerAction.BUTTON_PRESS,
                heldButtonMask,
                changedButtonMask = 0,
            ),
        )
        assertNull(
            NativeInputWire.pointerPhase(
                ClientPointerAction.BUTTON_RELEASE,
                heldButtonMask,
                changedButtonMask = 0,
            ),
        )
    }

    @Test
    fun pointerPhaseDropsUnsupportedTertiaryBackAndForwardTransitions() {
        listOf(MotionEvent.BUTTON_TERTIARY, MotionEvent.BUTTON_BACK, MotionEvent.BUTTON_FORWARD).forEach { button ->
            val changedButtonMask = NativeInputWire.buttonMask(button)
            assertEquals(0, changedButtonMask)
            assertNull(NativeInputWire.pointerPhase(ClientPointerAction.BUTTON_PRESS, 0, changedButtonMask))
            assertNull(NativeInputWire.pointerPhase(ClientPointerAction.BUTTON_RELEASE, 0, changedButtonMask))
            assertNull(
                NativeInputWire.pointerPhase(
                    ClientPointerAction.BUTTON_PRESS,
                    NativeInputWire.BUTTON_PRIMARY,
                    changedButtonMask,
                ),
            )
        }
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

    @Test
    fun negotiatedStandardAndLegacyFallbackDistinguishControlAndShift() {
        assertEquals(0x01, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_CONTROL, true))
        assertEquals(0x02, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_SHIFT, true))
        assertEquals(0x02, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_CONTROL, false))
        assertEquals(0x01, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_SHIFT, false))
    }

    @Test
    fun legacyFallbackCollapsesRightModifiersAndRejectsReservedBits() {
        assertEquals(0x02, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_RIGHT_CONTROL, false))
        assertEquals(0x01, NativeInputWire.wireModifierMask(NativeInputWire.MODIFIER_RIGHT_SHIFT, false))
        assertEquals(
            0x0C,
            NativeInputWire.wireModifierMask(
                NativeInputWire.MODIFIER_RIGHT_OPTION or NativeInputWire.MODIFIER_RIGHT_COMMAND,
                false,
            ),
        )
        org.junit.Assert.assertThrows(IllegalArgumentException::class.java) {
            NativeInputWire.wireModifierMask(0x100, true)
        }
    }
}
