package dev.telemachus.display

/** Client-local viewport choices that do not require a wire-protocol change. */
enum class VideoScaleMode {
    FIT,
    FILL,
    ;

    companion object {
        fun fromName(value: String?): VideoScaleMode = entries.firstOrNull { it.name == value } ?: FIT
    }
}

enum class ClientRotation(
    val degrees: Int,
) {
    FOLLOW_HOST(0),
    CLOCKWISE_90(90),
    UPSIDE_DOWN(180),
    COUNTER_CLOCKWISE_90(270),
    ;

    companion object {
        fun fromName(value: String?): ClientRotation = entries.firstOrNull { it.name == value } ?: FOLLOW_HOST
    }
}

internal object ViewportPolicy {
    data class Size(
        val width: Int,
        val height: Int,
    )

    /**
     * The viewport occupies the visible, rotated video bounds. The decoder
     * surface keeps the encoded orientation and is rotated inside it.
     */
    data class Layout(
        val viewport: Size,
        val surface: Size,
    )

    fun effectiveRotation(
        hostRotation: Int,
        clientRotation: ClientRotation,
    ): Int = (normalizeRotation(hostRotation) + clientRotation.degrees) % FULL_ROTATION_DEGREES

    fun normalizeRotation(rotation: Int): Int {
        val normalized = ((rotation % FULL_ROTATION_DEGREES) + FULL_ROTATION_DEGREES) % FULL_ROTATION_DEGREES
        return VALID_ROTATIONS.minBy { candidate ->
            val direct = kotlin.math.abs(candidate - normalized)
            minOf(direct, FULL_ROTATION_DEGREES - direct)
        }
    }

    fun surfaceSize(
        parentWidth: Int,
        parentHeight: Int,
        videoWidth: Int,
        videoHeight: Int,
        scaleMode: VideoScaleMode,
    ): Size {
        require(parentWidth > 0 && parentHeight > 0)
        require(videoWidth > 0 && videoHeight > 0)
        if (scaleMode == VideoScaleMode.FILL) return Size(0, 0)

        val videoAspect = videoWidth.toFloat() / videoHeight.toFloat()
        val parentAspect = parentWidth.toFloat() / parentHeight.toFloat()
        return if (parentAspect > videoAspect) {
            Size((parentHeight * videoAspect).toInt().coerceAtLeast(1), parentHeight)
        } else {
            Size(parentWidth, (parentWidth / videoAspect).toInt().coerceAtLeast(1))
        }
    }

    fun layout(
        parentWidth: Int,
        parentHeight: Int,
        videoWidth: Int,
        videoHeight: Int,
        scaleMode: VideoScaleMode,
        renderRotation: Int,
    ): Layout {
        require(parentWidth > 0 && parentHeight > 0)
        require(videoWidth > 0 && videoHeight > 0)

        val quarterTurn = normalizeRotation(renderRotation) % HALF_ROTATION_DEGREES != 0
        val rotatedVideoWidth = if (quarterTurn) videoHeight else videoWidth
        val rotatedVideoHeight = if (quarterTurn) videoWidth else videoHeight
        val viewport =
            if (scaleMode == VideoScaleMode.FILL) {
                Size(parentWidth, parentHeight)
            } else {
                fitSize(parentWidth, parentHeight, rotatedVideoWidth, rotatedVideoHeight)
            }
        val surface =
            if (quarterTurn) {
                Size(viewport.height, viewport.width)
            } else {
                viewport
            }
        return Layout(viewport = viewport, surface = surface)
    }

    private fun fitSize(
        parentWidth: Int,
        parentHeight: Int,
        contentWidth: Int,
        contentHeight: Int,
    ): Size {
        val contentAspect = contentWidth.toFloat() / contentHeight.toFloat()
        val parentAspect = parentWidth.toFloat() / parentHeight.toFloat()
        return if (parentAspect > contentAspect) {
            Size((parentHeight * contentAspect).toInt().coerceAtLeast(1), parentHeight)
        } else {
            Size(parentWidth, (parentWidth / contentAspect).toInt().coerceAtLeast(1))
        }
    }

    private const val FULL_ROTATION_DEGREES = 360
    private const val HALF_ROTATION_DEGREES = 180
    private val VALID_ROTATIONS = listOf(0, 90, 180, 270)
}

/**
 * Capabilities exposed by the currently connected application session.
 *
 * The runnable baseline is intentionally touch-only. Keeping unsupported
 * controls explicit prevents the UI from writing unnegotiated legacy bytes.
 */
data class ClientSessionCapabilities(
    val touch: Boolean,
    val displaySelection: Boolean,
    val keyboard: Boolean,
    val nativePointer: Boolean,
) {
    companion object {
        val LEGACY_TOUCH_ONLY =
            ClientSessionCapabilities(
                touch = true,
                displaySelection = false,
                keyboard = false,
                nativePointer = false,
            )
    }
}

internal enum class ClientControl {
    DISPLAY_SELECTION,
    KEYBOARD,
    NATIVE_POINTER,
}

internal object ClientControlAvailability {
    fun isSupported(
        control: ClientControl,
        capabilities: ClientSessionCapabilities,
    ): Boolean =
        when (control) {
            ClientControl.DISPLAY_SELECTION -> capabilities.displaySelection
            ClientControl.KEYBOARD -> capabilities.keyboard
            ClientControl.NATIVE_POINTER -> capabilities.nativePointer
        }
}
