package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionPanelLayoutPolicyTest {
    @Test
    fun `stacked layout keeps a single full-width column`() {
        val layout = ConnectionPanelLayoutPolicy.resolve(twoColumn = false, columnGapPx = 28)

        assertEquals(ConnectionPanelLayoutPolicy.Orientation.VERTICAL, layout.contentOrientation)
        assertTrue(layout.header.widthMatchParent)
        assertTrue(layout.actions.widthMatchParent)
        assertEquals(0f, layout.header.weight, 0f)
        assertEquals(0f, layout.actions.weight, 0f)
        // The stacked layout must not reserve any inter-column gap.
        assertEquals(0, layout.columnGapPx)
    }

    @Test
    fun `two-column layout splits into weighted columns with a gap`() {
        val layout = ConnectionPanelLayoutPolicy.resolve(twoColumn = true, columnGapPx = 28)

        assertEquals(ConnectionPanelLayoutPolicy.Orientation.HORIZONTAL, layout.contentOrientation)
        assertFalse(layout.header.widthMatchParent)
        assertFalse(layout.actions.widthMatchParent)
        assertEquals(ConnectionPanelLayoutPolicy.HEADER_WEIGHT, layout.header.weight, 0f)
        assertEquals(ConnectionPanelLayoutPolicy.ACTIONS_WEIGHT, layout.actions.weight, 0f)
        assertEquals(28, layout.columnGapPx)
    }

    @Test
    fun `actions column gets the larger share so tall content is not cramped`() {
        val layout = ConnectionPanelLayoutPolicy.resolve(twoColumn = true, columnGapPx = 0)

        assertTrue(layout.actions.weight > layout.header.weight)
    }

    @Test
    fun `negative gap is clamped to zero`() {
        val layout = ConnectionPanelLayoutPolicy.resolve(twoColumn = true, columnGapPx = -10)

        assertEquals(0, layout.columnGapPx)
    }
}
