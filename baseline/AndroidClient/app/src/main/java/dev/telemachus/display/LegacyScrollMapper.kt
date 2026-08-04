package dev.telemachus.display

/** Maps a mouse wheel event onto the legacy host's two-finger scroll gesture. */
internal object LegacyScrollMapper {
    data class Gesture(
        val startFirst: TouchMapper.Point,
        val startSecond: TouchMapper.Point,
        val endFirst: TouchMapper.Point,
        val endSecond: TouchMapper.Point,
    )

    fun map(
        anchor: TouchMapper.Point,
        horizontalAxis: Float,
        verticalAxis: Float,
    ): Gesture? {
        if (horizontalAxis == 0f && verticalAxis == 0f) return null

        val offsetX = effectiveDelta(horizontalAxis)
        val offsetY = -effectiveDelta(verticalAxis)
        val startX = anchor.x.coerceIn((-offsetX).coerceAtLeast(0f), (1f - offsetX).coerceAtMost(1f))
        val startY = anchor.y.coerceIn((-offsetY).coerceAtLeast(0f), (1f - offsetY).coerceAtMost(1f))
        val secondStartX = (startX + POINTER_SPACING).coerceIn(0f, 1f)
        val endFirst =
            TouchMapper.Point(
                (startX + offsetX).coerceIn(0f, 1f),
                (startY + offsetY).coerceIn(0f, 1f),
            )
        val endSecond =
            TouchMapper.Point(
                (secondStartX + offsetX).coerceIn(0f, 1f),
                (startY + offsetY).coerceIn(0f, 1f),
            )
        return Gesture(
            startFirst = TouchMapper.Point(startX, startY),
            startSecond = TouchMapper.Point(secondStartX, startY),
            endFirst = endFirst,
            endSecond = endSecond,
        )
    }

    private fun effectiveDelta(axis: Float): Float {
        if (axis == 0f) return 0f
        val scaled = (axis * AXIS_SCALE).coerceIn(-MAX_EFFECTIVE_DELTA, MAX_EFFECTIVE_DELTA)
        return if (kotlin.math.abs(scaled) >= MIN_EFFECTIVE_DELTA) {
            scaled
        } else {
            kotlin.math.sign(axis) * MIN_EFFECTIVE_DELTA
        }
    }

    private const val AXIS_SCALE = 0.025f
    private const val MIN_EFFECTIVE_DELTA = 0.02f
    private const val MAX_EFFECTIVE_DELTA = 0.25f
    private const val POINTER_SPACING = 0.04f
}
