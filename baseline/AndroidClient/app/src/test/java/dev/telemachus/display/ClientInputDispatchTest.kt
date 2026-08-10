package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ClientInputDispatchTest {
    @Test
    fun `legacy binding keeps key and native pointer explicitly unsupported`() {
        val dispatch = ClientInputDispatch(ClientSessionBinding.LEGACY_TOUCH_ONLY)

        assertEquals(ClientInputDispatchResult.UNSUPPORTED, dispatch.sendKey(key(pressed = true)))
        assertEquals(ClientInputDispatchResult.UNSUPPORTED, dispatch.sendPointer(pointer(ClientPointerAction.SCROLL)))
    }

    @Test
    fun `negotiated sink receives physical key and pointer sequence in order`() {
        val received = mutableListOf<String>()
        val sink =
            object : ClientSessionInputSink {
                override fun sendKey(input: ClientKeyInput): Boolean {
                    received += if (input.pressed) "key-down" else "key-up"
                    return true
                }

                override fun sendPointer(input: ClientPointerInput): Boolean {
                    received += input.action.name
                    return true
                }
            }
        val dispatch = ClientInputDispatch(ClientSessionBinding(NEGOTIATED_INPUT, sink))

        dispatch.sendKey(key(pressed = true))
        dispatch.sendKey(key(pressed = false))
        dispatch.sendPointer(pointer(ClientPointerAction.BUTTON_PRESS))
        dispatch.sendPointer(pointer(ClientPointerAction.BUTTON_RELEASE))
        dispatch.sendPointer(pointer(ClientPointerAction.SCROLL))

        assertEquals(
            listOf("key-down", "key-up", "BUTTON_PRESS", "BUTTON_RELEASE", "SCROLL"),
            received,
        )
    }

    @Test
    fun `capability cannot be enabled without matching sender`() {
        assertThrows(IllegalArgumentException::class.java) {
            ClientSessionBinding(NEGOTIATED_INPUT)
        }
    }

    private fun key(pressed: Boolean) = ClientKeyInput(usbHidUsage = 0x04, pressed, emptySet(), 0)

    private fun pointer(action: ClientPointerAction) = ClientPointerInput(action, 0.5f, 0.5f)

    private companion object {
        val NEGOTIATED_INPUT =
           ClientSessionCapabilities(
               touch = true,
               displaySelection = false,
               keyboard = true,
               nativePointer = true,
                hostActions = false,
           )
    }
}
