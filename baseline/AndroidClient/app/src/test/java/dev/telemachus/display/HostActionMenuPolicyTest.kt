package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostActionMenuPolicyTest {
    private fun option(
        id: String,
        name: String = "",
        requiresConfirmation: Boolean = false,
    ) = HostActionOption(id = id, name = name, requiresConfirmation = requiresConfirmation)

    @Test
    fun `button stays collapsed unless negotiated and at least one action`() {
        val actions = listOf(option("move-window"))
        assertFalse(HostActionMenuPolicy.isAvailable(hostActions = false, actions = actions))
        assertFalse(HostActionMenuPolicy.isAvailable(hostActions = true, actions = emptyList()))
        assertTrue(HostActionMenuPolicy.isAvailable(hostActions = true, actions = actions))
    }

    @Test
    fun `menu label prefers the host localized name`() {
        val label =
            HostActionMenuPolicy.menuLabel(
                option("move-window", name = "Move to iPad"),
                moveDefault = "Move window here",
                returnDefault = "Return windows to Mac",
            )
        assertEquals("Move to iPad", label)
    }

    @Test
    fun `menu label falls back to per-id default when name is blank`() {
        assertEquals(
            "Move window here",
            HostActionMenuPolicy.menuLabel(
                option("move-window", name = "   "),
                moveDefault = "Move window here",
                returnDefault = "Return windows to Mac",
            ),
        )
        assertEquals(
            "Return windows to Mac",
            HostActionMenuPolicy.menuLabel(
                option("return-windows"),
                moveDefault = "Move window here",
                returnDefault = "Return windows to Mac",
            ),
        )
    }

    @Test
    fun `menu label falls back to the id for an unknown blank action`() {
        assertEquals(
            "custom-action",
            HostActionMenuPolicy.menuLabel(
                option("custom-action"),
                moveDefault = "Move window here",
                returnDefault = "Return windows to Mac",
            ),
        )
    }

    @Test
    fun `availability check gates on the negotiated host-actions capability`() {
        val capabilities =
            ClientSessionCapabilities.LEGACY_TOUCH_ONLY.copy(hostActions = true)
        assertTrue(ClientControlAvailability.isSupported(ClientControl.HOST_ACTIONS, capabilities))
        assertFalse(
            ClientControlAvailability.isSupported(
                ClientControl.HOST_ACTIONS,
                ClientSessionCapabilities.LEGACY_TOUCH_ONLY,
            ),
        )
    }
}
