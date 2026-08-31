package dev.telemachus.display

/**
 * Owns the renderer-facing viewport state that the UI layer turns into actual
 * Android layout mutations.
 *
 * The class deliberately has no Android, transport, decoder, or protocol
 * dependency: it computes the visible video viewport and decoder surface
 * bounds from display geometry, client-local scale/rotation choices, and the
 * parent size. UI code should only map these values onto Android views.
 */
internal class RendererViewportState(
    private val scaleMode: () -> VideoScaleMode = { VideoScaleMode.FIT },
    private val renderRotation: () -> ClientRotation = { ClientRotation.FOLLOW_HOST },
    private val viewportLayout: (Int, Int, Int, Int, VideoScaleMode, ClientRotation) -> ViewportPolicy.Layout =
        { parentWidth, parentHeight, videoWidth, videoHeight, mode, rotation ->
            ViewportPolicy.layout(
                parentWidth = parentWidth,
                parentHeight = parentHeight,
                videoWidth = videoWidth,
                videoHeight = videoHeight,
                scaleMode = mode,
                renderRotation = ViewportPolicy.surfaceTransformRotation(rotation),
            )
        },
) {
    private var displayWidth = 0
    private var displayHeight = 0
    private var parentWidth = 0
    private var parentHeight = 0
    private var latestLayout: ViewportPolicy.Layout? = null

    val isReady: Boolean
        get() = displayWidth > 0 && displayHeight > 0 && parentWidth > 0 && parentHeight > 0

    val currentLayout: ViewportPolicy.Layout?
        get() = latestLayout

    fun updateDisplaySize(
        width: Int,
        height: Int,
    ) {
        displayWidth = width
        displayHeight = height
        recalculate()
    }

    fun updateParentSize(
        width: Int,
        height: Int,
    ) {
        parentWidth = width
        parentHeight = height
        recalculate()
    }

    fun updateScaleMode() {
        recalculate()
    }

    fun updateRenderRotation() {
        recalculate()
    }

    fun clear() {
        displayWidth = 0
        displayHeight = 0
        parentWidth = 0
        parentHeight = 0
        latestLayout = null
    }

    private fun recalculate() {
        latestLayout =
            if (isReady) {
                viewportLayout(
                    parentWidth,
                    parentHeight,
                    displayWidth,
                    displayHeight,
                    scaleMode(),
                    renderRotation(),
                )
            } else {
                null
            }
    }
}
