package dev.telemachus.display

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
}
