package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DisplayCapsulePolicyTest {
    private fun option(
        id: String,
        name: String = id,
        primary: Boolean = false,
        virtual: Boolean = false,
    ) =
        StreamDisplayOption(
            id = id,
            name = name,
            width = 1920,
            height = 1080,
            isPrimary = primary,
            isVirtual = virtual,
        )

    @Test
    fun `capsule stays collapsed unless negotiated and more than one display`() {
        val two = listOf(option("a"), option("b"))
        assertFalse(DisplayCapsulePolicy.isSelectable(displaySelection = false, displays = two))
        assertFalse(
            DisplayCapsulePolicy.isSelectable(displaySelection = true, displays = listOf(option("a"))),
        )
        assertTrue(DisplayCapsulePolicy.isSelectable(displaySelection = true, displays = two))
    }

    @Test
    fun `active option resolves by selected id`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))
        assertEquals("Sidecar", DisplayCapsulePolicy.activeOption(displays, "b")?.name)
        assertNull(DisplayCapsulePolicy.activeOption(displays, "missing"))
    }

    @Test
    fun `label prefers selected display`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Sidecar"))
        assertEquals("Sidecar", DisplayCapsulePolicy.capsuleLabel(displays, "b"))
    }

    @Test
    fun `label falls back to primary then first when selection unknown`() {
        val displays = listOf(option("a", "Built-in"), option("b", "Main", primary = true))
        assertEquals("Main", DisplayCapsulePolicy.capsuleLabel(displays, "gone"))

        val noPrimary = listOf(option("a", "First"), option("b", "Second"))
        assertEquals("First", DisplayCapsulePolicy.capsuleLabel(noPrimary, "gone"))
    }

    @Test
    fun `label is empty when there are no displays`() {
        assertEquals("", DisplayCapsulePolicy.capsuleLabel(emptyList(), "a"))
    }

    @Test
    fun `label preserves the complete trimmed name for visual and accessibility consumers`() {
        val displays = listOf(option("a", "  Studio Display Ultra Wide 5K  "))
        assertEquals("Studio Display Ultra Wide 5K", DisplayCapsulePolicy.capsuleLabel(displays, "a"))
    }
}

class ControlBarLayoutPolicyTest {
    private val geometry =
        ControlBarLayoutPolicy.Geometry(
            horizontalContentPaddingPx = 12,
            selectorMinimumWidthPx = 88,
            buttonSizePx = 48,
            actionMarginPx = 4,
            disconnectSeparationPx = 12,
            columnActionSpacingPx = 8,
        )

    @Test
    fun `single display keeps a compact capsule`() {
        assertEquals(
            ControlBarLayoutPolicy.Mode.COMPACT,
            ControlBarLayoutPolicy.mode(360, false, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(160, false, true, geometry),
        )
    }

    @Test
    fun `common phone widths keep all negotiated controls inline`() {
        assertEquals(
            ControlBarLayoutPolicy.Mode.INLINE,
            ControlBarLayoutPolicy.mode(320, true, true, geometry),
        )
    }

    @Test
    fun `narrow windows stack and extreme windows use a column`() {
        assertEquals(
            ControlBarLayoutPolicy.Mode.STACKED,
            ControlBarLayoutPolicy.mode(240, true, true, geometry),
        )
        assertEquals(
            ControlBarLayoutPolicy.Mode.COLUMN,
            ControlBarLayoutPolicy.mode(160, true, true, geometry),
        )
    }

    @Test
    fun `column mode converts horizontal action spacing to vertical spacing`() {
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 8, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.COLUMN,
                ControlBarLayoutPolicy.Action.SETTINGS,
                hostActionsVisible = true,
                geometry = geometry,
            ),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(0, 12, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.COLUMN,
                ControlBarLayoutPolicy.Action.DISCONNECT,
                hostActionsVisible = true,
                geometry = geometry,
            ),
        )
        assertEquals(
            ControlBarLayoutPolicy.Margins(12, 0, 0),
            ControlBarLayoutPolicy.actionMargins(
                ControlBarLayoutPolicy.Mode.INLINE,
                ControlBarLayoutPolicy.Action.DISCONNECT,
                hostActionsVisible = true,
                geometry = geometry,
            ),
        )
    }
}
