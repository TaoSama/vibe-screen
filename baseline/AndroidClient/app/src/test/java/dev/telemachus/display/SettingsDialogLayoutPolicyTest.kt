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
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
            ),
        )
    }

    @Test
    fun `short landscape keeps one settings column`() {
        assertFalse(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 640,
                availableHeightPx = 320,
                minimumWidthPx = 600,
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
            ),
        )
    }

    @Test
    fun `columns stay single column when landscape height is too short`() {
        val columns =
            SettingsDialogLayoutPolicy.columns(
                availableWidthPx = 640,
                availableHeightPx = 320,
                minimumWidthPx = 600,
                gapPx = 0,
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
            )

        assertFalse(columns.twoColumns)
        assertEquals(640, columns.primaryWidthPx)
        assertEquals(640, columns.controlsWidthPx)
        assertEquals(640, columns.fullWidthPx)
    }

    @Test
    fun `dialog width can select two columns while content width sizes columns`() {
        val columns =
            SettingsDialogLayoutPolicy.columns(
                availableWidthPx = 552,
                availableHeightPx = 420,
                minimumWidthPx = 600,
                gapPx = 20,
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
                decisionWidthPx = 600,
            )

        assertTrue(columns.twoColumns)
        assertEquals(266, columns.primaryWidthPx)
        assertEquals(266, columns.controlsWidthPx)
        assertEquals(552, columns.fullWidthPx)
    }

    @Test
    fun `tablet portrait and narrow landscape keep one settings column`() {
        assertFalse(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 600,
                availableHeightPx = 960,
                minimumWidthPx = 600,
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
            ),
        )
        assertFalse(
            SettingsDialogLayoutPolicy.shouldUseTwoColumns(
                availableWidthPx = 599,
                availableHeightPx = 360,
                minimumWidthPx = 600,
                minimumHeightPx = SETTINGS_TWO_COLUMN_MIN_HEIGHT,
            ),
        )
    }

    private companion object {
        const val SETTINGS_TWO_COLUMN_MIN_HEIGHT = 336
    }
}
