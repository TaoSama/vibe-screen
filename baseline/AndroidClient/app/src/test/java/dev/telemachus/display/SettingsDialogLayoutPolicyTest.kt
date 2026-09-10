package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsDialogLayoutPolicyTest {
    @Test
    fun `options stack when their required widths exceed the group`() {
        assertTrue(
            SettingsDialogLayoutPolicy.shouldStack(
                availableWidthPx = 351,
                requiredButtonWidthsPx = listOf(88, 88, 88, 88),
            ),
        )
    }

    @Test
    fun `options stay horizontal when every option fits`() {
        assertFalse(
            SettingsDialogLayoutPolicy.shouldStack(
                availableWidthPx = 352,
                requiredButtonWidthsPx = listOf(88, 88, 88, 88),
            ),
        )
    }

    @Test
    fun `unmeasured groups use the safe stacked layout`() {
        assertTrue(
            SettingsDialogLayoutPolicy.shouldStack(
                availableWidthPx = 0,
                requiredButtonWidthsPx = listOf(88, 88),
            ),
        )
    }

    @Test
    fun `tablet landscape can use two settings columns`() {
        assertTrue(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 600,
                availableHeightPx = 420,
                minimumWidthPx = 600,
            ),
        )
    }

    @Test
    fun `dialog width can select two columns while content width sizes columns`() {
        val columns =
            SettingsDialogLayoutPolicy.columns(
                availableWidthPx = 552,
                availableHeightPx = 420,
                minimumWidthPx = 600,
                gapPx = 20,
                decisionWidthPx = 600,
            )

        assertTrue(columns.twoColumns)
        assertEquals(266, columns.primaryWidthPx)
        assertEquals(266, columns.controlsWidthPx)
        assertEquals(552, columns.fullWidthPx)
    }

    @Test
    fun `short landscape video choices stack inside constrained column width`() {
        val controlsColumnContentWidth =
            SettingsDialogLayoutPolicy.constrainedGroupWidth(
                columnWidthPx = 278,
                groupWidthPx = 576,
                groupMeasuredWidthPx = 576,
                parentHorizontalPaddingPx = 24,
            )

        assertEquals(254, controlsColumnContentWidth)
        assertTrue(
            SettingsDialogLayoutPolicy.shouldStack(
                availableWidthPx = controlsColumnContentWidth,
                requiredButtonWidthsPx = listOf(132, 132, 132),
            ),
        )
    }

    @Test
    fun `short landscape stays single column when split columns are too narrow`() {
        val columns =
            SettingsDialogLayoutPolicy.columns(
                availableWidthPx = 592,
                availableHeightPx = 272,
                minimumWidthPx = 600,
                gapPx = 0,
                decisionWidthPx = 640,
                minimumColumnContentWidthPx = 352,
            )

        assertFalse(columns.twoColumns)
        assertEquals(592, columns.primaryWidthPx)
        assertEquals(592, columns.controlsWidthPx)
        assertEquals(592, columns.fullWidthPx)
    }

    @Test
    fun `tablet portrait and narrow landscape keep one settings column`() {
        assertFalse(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 600,
                availableHeightPx = 960,
                minimumWidthPx = 600,
            ),
        )
        assertFalse(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 599,
                availableHeightPx = 360,
                minimumWidthPx = 600,
            ),
        )
    }

    @Test
    fun `option groups use the constrained rendered content width`() {
        assertEquals(
            272,
            SettingsDialogLayoutPolicy.constrainedGroupWidth(
                columnWidthPx = 312,
                groupWidthPx = 320,
                groupMeasuredWidthPx = 320,
                parentHorizontalPaddingPx = 40,
            ),
        )
    }

    @Test
    fun `option groups recover to the expanded column content width after reflow`() {
        assertEquals(
            448,
            SettingsDialogLayoutPolicy.constrainedGroupWidth(
                columnWidthPx = 480,
                groupWidthPx = 280,
                groupMeasuredWidthPx = 280,
                parentHorizontalPaddingPx = 32,
            ),
        )
    }

    @Test
    fun `option groups fall back to column content width before first layout`() {
        assertEquals(
            280,
            SettingsDialogLayoutPolicy.constrainedGroupWidth(
                columnWidthPx = 312,
                groupWidthPx = 0,
                groupMeasuredWidthPx = 0,
                parentHorizontalPaddingPx = 32,
            ),
        )
    }
}
