package dev.telemachus.display

import android.view.Gravity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionPanelLayoutPolicyTest {
    @Test
    fun `stacked layout keeps a single full-width column`() {
        val layout = ConnectionPanelLayoutPolicy.resolve(twoColumn = false, columnGapPx = 28)

        assertEquals(ConnectionPanelLayoutPolicy.Orientation.VERTICAL, layout.contentOrientation)
        assertEquals(Gravity.TOP, layout.contentGravity)
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
        assertEquals(Gravity.TOP, layout.contentGravity)
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

    @Test
    fun `narrow landscape falling back to single column matches the stacked contract`() {
        // A landscape window that is too narrow for the side-by-side split (for
        // example a split-screen or narrow freeform window below the width
        // qualifier threshold) resolves twoColumn=false and must render as the
        // full-width stacked column, identical to portrait.
        val narrowLandscape = ConnectionPanelLayoutPolicy.resolve(twoColumn = false, columnGapPx = 28)
        val portrait = ConnectionPanelLayoutPolicy.resolve(twoColumn = false, columnGapPx = 0)

        assertEquals(ConnectionPanelLayoutPolicy.Orientation.VERTICAL, narrowLandscape.contentOrientation)
        assertTrue(narrowLandscape.header.widthMatchParent)
        assertTrue(narrowLandscape.actions.widthMatchParent)
        assertEquals(0f, narrowLandscape.header.weight, 0f)
        assertEquals(0f, narrowLandscape.actions.weight, 0f)
        // No inter-column gap is reserved even if a landscape gap dimension is
        // supplied, so the fallback is visually identical to portrait.
        assertEquals(0, narrowLandscape.columnGapPx)
        assertEquals(portrait.contentOrientation, narrowLandscape.contentOrientation)
        assertEquals(portrait.columnGapPx, narrowLandscape.columnGapPx)
    }

    @Test
    fun `mode toggle stacks only for large-font stacked portrait`() {
        val layout = ConnectionModeToggleLayoutPolicy.resolve(stackedPortrait = true, fontScale = 1.3f)

        assertEquals(ConnectionModeToggleLayoutPolicy.Orientation.VERTICAL, layout.orientation)
        assertTrue(layout.buttonWidthMatchParent)
        assertEquals(0f, layout.buttonWeight, 0f)
    }

    @Test
    fun `mode toggle stays segmented for default font stacked portrait`() {
        val layout = ConnectionModeToggleLayoutPolicy.resolve(stackedPortrait = true, fontScale = 1.0f)

        assertEquals(ConnectionModeToggleLayoutPolicy.Orientation.HORIZONTAL, layout.orientation)
        assertFalse(layout.buttonWidthMatchParent)
        assertEquals(1f, layout.buttonWeight, 0f)
    }

    @Test
    fun `mode toggle stays segmented outside stacked portrait`() {
        val layout = ConnectionModeToggleLayoutPolicy.resolve(stackedPortrait = false, fontScale = 1.3f)

        assertEquals(ConnectionModeToggleLayoutPolicy.Orientation.HORIZONTAL, layout.orientation)
        assertFalse(layout.buttonWidthMatchParent)
        assertEquals(1f, layout.buttonWeight, 0f)
    }
}
