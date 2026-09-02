package dev.telemachus.display

/**
 * Maps visible viewport coordinates into the encoded video orientation.
 *
 * MediaCodec's SCALE_TO_FIT mode letterboxes when the stream and tablet have
 * different aspect ratios. Normalizing against the whole SurfaceView would
 * offset every touch on the mirrored Mac display.
 */
internal object TouchMapper {
    data class Point(
        val x: Float,
        val y: Float,
    )

    fun map(
        x: Float,
        y: Float,
        viewWidth: Int,
        viewHeight: Int,
        videoWidth: Int,
        videoHeight: Int,
        scaleMode: VideoScaleMode = VideoScaleMode.FIT,
        renderRotation: Int = 0,
    ): Point {
        if (viewWidth <= 0 || viewHeight <= 0 || videoWidth <= 0 || videoHeight <= 0) {
            return Point(0f, 0f)
        }

        val surfaceWidth = viewWidth.toFloat()
        val surfaceHeight = viewHeight.toFloat()
        val normalizedRotation = ViewportPolicy.normalizeRotation(renderRotation)
        val quarterTurn = normalizedRotation == 90 || normalizedRotation == 270
        val rotatedVideoWidth = if (quarterTurn) videoHeight else videoWidth
        val rotatedVideoHeight = if (quarterTurn) videoWidth else videoHeight
        val videoAspect = rotatedVideoWidth.toFloat() / rotatedVideoHeight.toFloat()
        val surfaceAspect = surfaceWidth / surfaceHeight

        val contentWidth: Float
        val contentHeight: Float
        val offsetX: Float
        val offsetY: Float

        val fitByHeight = surfaceAspect > videoAspect
        if ((scaleMode == VideoScaleMode.FIT && fitByHeight) ||
            (scaleMode == VideoScaleMode.FILL && !fitByHeight)
        ) {
            contentHeight = surfaceHeight
            contentWidth = contentHeight * videoAspect
            offsetX = (surfaceWidth - contentWidth) / 2f
            offsetY = 0f
        } else {
            contentWidth = surfaceWidth
            contentHeight = contentWidth / videoAspect
            offsetX = 0f
            offsetY = (surfaceHeight - contentHeight) / 2f
        }

        val rotatedX = ((x - offsetX) / contentWidth).coerceIn(0f, 1f)
        val rotatedY = ((y - offsetY) / contentHeight).coerceIn(0f, 1f)
        return when (normalizedRotation) {
            90 -> Point(rotatedY, 1f - rotatedX)
            180 -> Point(1f - rotatedX, 1f - rotatedY)
            270 -> Point(1f - rotatedY, rotatedX)
            else -> Point(rotatedX, rotatedY)
        }
    }
}
