package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Test

class SafeAreaGeometryTest {
    private val margin = 24

    @Test
    fun `landscape left cutout keeps controls off the notched short edge`() {
        // Xiaomi 13 landscape: 2400x1080 with a 104px cutout on the leading edge.
        val insets = SafeAreaGeometry.Insets.of(left = 104, top = 0, right = 0, bottom = 0)
        val safe = SafeAreaGeometry.safeRect(2400, 1080, insets, marginPx = margin)

        assertEquals(104f + margin, safe.left, 0f)
        assertEquals(margin.toFloat(), safe.top, 0f)
        assertEquals(2400f - margin, safe.right, 0f)
        assertEquals(1080f - margin, safe.bottom, 0f)

        // A control pinned to the visual left must clear the cutout.
        val (x, _) = SafeAreaGeometry.clampToSafeRect(0f, 0f, viewWidth = 200, viewHeight = 120, safe = safe)
        assertEquals(104f + margin, x, 0f)
    }

    @Test
    fun `portrait top and bottom insets bound the vertical range`() {
        val insets = SafeAreaGeometry.Insets.of(left = 0, top = 96, right = 0, bottom = 132)
        val safe = SafeAreaGeometry.safeRect(1080, 2400, insets, marginPx = margin)

        // Below the bottom system bar: clamp pulls it up so it stays visible.
        val (_, low) = SafeAreaGeometry.clampToSafeRect(0f, 5000f, viewWidth = 300, viewHeight = 150, safe = safe)
        assertEquals(2400f - 132f - margin - 150f, low, 0f)

        // Above the top inset: clamp pushes it down below the status bar.
        val (_, high) = SafeAreaGeometry.clampToSafeRect(0f, -400f, viewWidth = 300, viewHeight = 150, safe = safe)
        assertEquals(96f + margin, high, 0f)
    }

    @Test
    fun `stale position from another orientation is pulled back in bounds`() {
        // Saved while landscape (x far right), now applied in portrait.
        val portraitInsets = SafeAreaGeometry.Insets.of(left = 0, top = 96, right = 0, bottom = 132)
        val safe = SafeAreaGeometry.safeRect(1080, 2400, portraitInsets, marginPx = margin)

        val staleX = 2200f
        val staleY = 40f
        val (x, y) =
            SafeAreaGeometry.clampToSafeRect(staleX, staleY, viewWidth = 400, viewHeight = 180, safe = safe)

        assertEquals(1080f - margin - 400f, x, 0f)
        assertEquals(96f + margin, y, 0f)
    }

    @Test
    fun `view wider than safe span pins to the safe start instead of leaving bounds`() {
        val insets = SafeAreaGeometry.Insets.of(left = 104, top = 0, right = 40, bottom = 0)
        val safe = SafeAreaGeometry.safeRect(600, 400, insets, marginPx = margin)

        val (x, _) = SafeAreaGeometry.clampToSafeRect(999f, 0f, viewWidth = 5000, viewHeight = 50, safe = safe)
        assertEquals(safe.left, x, 0f)
    }

    @Test
    fun `negative reported insets are treated as zero`() {
        val insets = SafeAreaGeometry.Insets.of(left = -10, top = -5, right = -1, bottom = -2)
        assertEquals(SafeAreaGeometry.Insets.NONE, insets)
    }

    @Test
    fun `extreme insets collapse toward center without inverting`() {
        val insets = SafeAreaGeometry.Insets.of(left = 500, top = 0, right = 500, bottom = 0)
        val safe = SafeAreaGeometry.safeRect(400, 400, insets, marginPx = 0)
        assertEquals(safe.left, safe.right, 0f)
        assertEquals(0f, safe.width, 0f)
        assertEquals(200f, safe.left, 0f)
    }

    @Test
    fun `asymmetric extreme inset still collapses inside the parent`() {
        val insets = SafeAreaGeometry.Insets.of(left = 900, top = 700, right = 0, bottom = 0)
        val safe = SafeAreaGeometry.safeRect(400, 300, insets, marginPx = 0)

        assertEquals(400f, safe.left, 0f)
        assertEquals(400f, safe.right, 0f)
        assertEquals(300f, safe.top, 0f)
        assertEquals(300f, safe.bottom, 0f)
    }
}
