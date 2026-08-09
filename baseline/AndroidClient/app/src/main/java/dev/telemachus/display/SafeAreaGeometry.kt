package dev.telemachus.display

/**
 * Pure geometry for keeping floating chrome (status overlay, control bar,
 * settings button, settings panel) inside a safe, interactive region while the
 * video SurfaceView stays edge-to-edge.
 *
 * The view hierarchy draws behind the system bars and the display cutout so the
 * stream fills the panel. These helpers translate the reported insets into a
 * safe rectangle within the parent and clamp a draggable view into it, so a
 * control never lands under a notch, a rounded corner, or a gesture bar. All
 * math is in device pixels and free of Android view state so it is unit
 * testable off-device.
 */
internal object SafeAreaGeometry {
    /**
     * Non-interactive edge insets in pixels, already unioned across the desired
     * inset types (typically system bars + display cutout). Values are clamped
     * to be non-negative by [of].
     */
    data class Insets(
        val left: Int,
        val top: Int,
        val right: Int,
        val bottom: Int,
    ) {
        companion object {
            val NONE = Insets(0, 0, 0, 0)

            fun of(
                left: Int,
                top: Int,
                right: Int,
                bottom: Int,
            ): Insets =
                Insets(
                    left = left.coerceAtLeast(0),
                    top = top.coerceAtLeast(0),
                    right = right.coerceAtLeast(0),
                    bottom = bottom.coerceAtLeast(0),
                )
        }
    }

    /** A rectangle in parent-local pixels. */
    data class Rect(
        val left: Float,
        val top: Float,
        val right: Float,
        val bottom: Float,
    ) {
        val width: Float get() = (right - left).coerceAtLeast(0f)
        val height: Float get() = (bottom - top).coerceAtLeast(0f)
    }

    /**
     * The safe rectangle inside a [parentWidth] x [parentHeight] container after
     * subtracting [insets] and an optional uniform [marginPx] breathing gap.
     *
     * If the insets and margins overflow the parent (extreme cutouts on a tiny
     * surface) the rectangle collapses toward the parent center instead of
     * inverting, so callers still get a well-formed, in-bounds anchor.
     */
    fun safeRect(
        parentWidth: Int,
        parentHeight: Int,
        insets: Insets,
        marginPx: Int = 0,
    ): Rect {
        val margin = marginPx.coerceAtLeast(0).toFloat()
        val w = parentWidth.coerceAtLeast(0).toFloat()
        val h = parentHeight.coerceAtLeast(0).toFloat()

        var left = insets.left + margin
        var top = insets.top + margin
        var right = w - insets.right - margin
        var bottom = h - insets.bottom - margin

        if (left > right) {
            val mid = ((insets.left + (w - insets.right)) / 2f).coerceIn(0f, w)
            left = mid
            right = mid
        }
        if (top > bottom) {
            val mid = ((insets.top + (h - insets.bottom)) / 2f).coerceIn(0f, h)
            top = mid
            bottom = mid
        }
        return Rect(left, top, right, bottom)
    }

    /**
     * Clamp a [viewWidth] x [viewHeight] view whose desired top-left is
     * ([x], [y]) so it stays fully within [safe]. When the view is larger than
     * the safe span on an axis it is pinned to the safe start on that axis
     * rather than pushed off-screen.
     */
    fun clampToSafeRect(
        x: Float,
        y: Float,
        viewWidth: Int,
        viewHeight: Int,
        safe: Rect,
    ): Pair<Float, Float> {
        val clampedX = clampAxis(x, viewWidth.toFloat(), safe.left, safe.right)
        val clampedY = clampAxis(y, viewHeight.toFloat(), safe.top, safe.bottom)
        return clampedX to clampedY
    }

    private fun clampAxis(
        value: Float,
        size: Float,
        min: Float,
        max: Float,
    ): Float {
        val upper = max - size
        if (upper <= min) {
            // The view cannot fit; pin to the safe start so it never leaves the
            // safe region on the leading edge.
            return min
        }
        return value.coerceIn(min, upper)
    }
}
