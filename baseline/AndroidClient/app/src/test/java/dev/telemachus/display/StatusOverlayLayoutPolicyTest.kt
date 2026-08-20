package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class StatusOverlayLayoutPolicyTest {
    private val geometry =
        StatusOverlayLayoutPolicy.Geometry(
            horizontalContentPaddingPx = 24,
            itemGapPx = 16,
            rowGapPx = 8,
            columnMinimumWidthPx = 96,
        )

    @Test
    fun `wide windows keep stats in a single row`() {
        val requiredWidth = 24 + 96 * 5 + 16 * 4

        assertEquals(
            StatusOverlayLayoutPolicy.Mode.SINGLE_ROW,
            StatusOverlayLayoutPolicy.mode(
                availableWidthPx = requiredWidth,
                columnCount = 5,
                geometry = geometry,
            ),
        )
    }

    @Test
    fun `narrow windows stack stats instead of exceeding the safe width`() {
        val requiredWidth = 24 + 96 * 5 + 16 * 4

        assertEquals(
            StatusOverlayLayoutPolicy.Mode.STACKED,
            StatusOverlayLayoutPolicy.mode(
                availableWidthPx = requiredWidth - 1,
                columnCount = 5,
                geometry = geometry,
            ),
        )
    }

    @Test
    fun `safe insets and margins shrink overlay maximum width`() {
        assertEquals(
            260,
            StatusOverlayLayoutPolicy.maxWidthPx(
                windowWidthPx = 320,
                safeAreaInsets = SafeAreaGeometry.Insets.of(left = 12, top = 0, right = 16, bottom = 0),
                horizontalMarginsPx = 32,
            ),
        )
    }

    @Test
    fun `invalid widths clamp to zero`() {
        assertEquals(
            0,
            StatusOverlayLayoutPolicy.maxWidthPx(
                windowWidthPx = 40,
                safeAreaInsets = SafeAreaGeometry.Insets.of(left = 30, top = 0, right = 30, bottom = 0),
                horizontalMarginsPx = 32,
            ),
        )
    }
}
