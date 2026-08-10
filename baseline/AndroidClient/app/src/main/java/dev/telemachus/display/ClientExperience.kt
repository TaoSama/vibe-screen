package dev.telemachus.display

import dev.vibescreen.protocol.v1.VideoQualityPreset

/** Client-local viewport choices that do not require a wire-protocol change. */
enum class VideoScaleMode {
    FIT,
    FILL,
    ;

    companion object {
        fun fromName(value: String?): VideoScaleMode = entries.firstOrNull { it.name == value } ?: FIT
    }
}

/**
 * Coarse video-quality intent surfaced in settings. Each choice maps to a wire
 * [VideoQualityPreset]; the host clamps and applies it, honoring the preset
 * only when no explicit bitrate is requested. AUTO defers entirely to the host
 * default and sends no preset.
 */
enum class VideoQualityChoice(
    val preset: VideoQualityPreset,
) {
    AUTO(VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED),
    SMOOTH(VideoQualityPreset.VIDEO_QUALITY_PRESET_SMOOTH),
    BALANCED(VideoQualityPreset.VIDEO_QUALITY_PRESET_BALANCED),
    SHARP(VideoQualityPreset.VIDEO_QUALITY_PRESET_SHARP),
    ;

    companion object {
        fun fromName(value: String?): VideoQualityChoice = entries.firstOrNull { it.name == value } ?: AUTO
    }
}

/** Client video-tuning bounds mirrored from the host's accepted range. */
object ClientVideoBounds {
    const val MIN_BITRATE_MBPS = 1
    const val MAX_BITRATE_MBPS = 100
    const val DEFAULT_BITRATE_MBPS = 20
    val FRAME_RATE_CHOICES = listOf(30, 60, 120)
    const val DEFAULT_FRAME_RATE = 60
}

internal data class AppliedVideoPreferenceProjection(
    val bitrateMbps: Int?,
    val framesPerSecond: Int?,
)

internal object AppliedVideoPreferenceProjector {
    fun shouldPersist(
        appliesClientVideoPreferences: Boolean,
        configEpoch: Long,
        lastAppliedConfigEpoch: Long,
    ): Boolean = appliesClientVideoPreferences && configEpoch > lastAppliedConfigEpoch

    fun project(
        bitrateKbps: Int,
        framesPerSecond: Int,
    ): AppliedVideoPreferenceProjection {
        val bitrateMbps =
            bitrateKbps
                .takeIf { it > 0 }
                ?.let { (it + 500) / 1_000 }
                ?.coerceIn(ClientVideoBounds.MIN_BITRATE_MBPS, ClientVideoBounds.MAX_BITRATE_MBPS)
        val supportedFrameRate = framesPerSecond.takeIf(ClientVideoBounds.FRAME_RATE_CHOICES::contains)
        return AppliedVideoPreferenceProjection(bitrateMbps, supportedFrameRate)
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
    val hostActions: Boolean,
) {
    companion object {
        val LEGACY_TOUCH_ONLY =
            ClientSessionCapabilities(
                touch = true,
                displaySelection = false,
                keyboard = false,
                nativePointer = false,
                hostActions = false,
            )
    }
}

internal enum class ClientControl {
    DISPLAY_SELECTION,
    KEYBOARD,
    NATIVE_POINTER,
    HOST_ACTIONS,
}

/** A host display the client can select, surfaced to the UI without protocol imports. */
data class StreamDisplayOption(
    val id: String,
    val name: String,
    val width: Int,
    val height: Int,
    val isPrimary: Boolean,
    val isVirtual: Boolean,
)

/**
 * Pure, testable logic for the display-selection capsule shown in the control
 * bar. The capsule reads as a dropdown selector: it shows the active display
 * name and only becomes selectable when display selection was negotiated and
 * more than one display exists. Keeping this UI-free lets the label and
 * selectability be unit-tested without inflating any Android view.
 */
internal object DisplayCapsulePolicy {
    /** Display selection is offered only when negotiated and there is a choice. */
    fun isSelectable(
        displaySelection: Boolean,
        displays: List<StreamDisplayOption>,
    ): Boolean = displaySelection && displays.size > 1

    /** Resolve the option currently marked active, if any. */
    fun activeOption(
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ): StreamDisplayOption? = displays.firstOrNull { it.id == selectedId }

    /**
     * Label shown on the capsule. Falls back to the primary/first display when
     * the selected id is unknown so the capsule never reads as empty, and
     * truncates long host names with an ellipsis so the compact, centered
     * capsule cannot be pushed off-screen.
     */
    fun capsuleLabel(
        displays: List<StreamDisplayOption>,
        selectedId: String,
        maxNameLength: Int,
    ): String {
        val active =
            activeOption(displays, selectedId)
                ?: displays.firstOrNull { it.isPrimary }
                ?: displays.firstOrNull()
                ?: return ""
        return truncateName(active.name, maxNameLength)
    }

    private fun truncateName(
        name: String,
        maxNameLength: Int,
    ): String {
        val trimmed = name.trim()
        if (maxNameLength <= 1 || trimmed.length <= maxNameLength) return trimmed
        return trimmed.take(maxNameLength - 1).trimEnd() + "\u2026"
    }
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
            ClientControl.HOST_ACTIONS -> capabilities.hostActions
        }
}

/**
 * A host action the client can invoke, surfaced to the UI without protocol
 * imports.
 */
data class HostActionOption(
    val id: String,
    val name: String,
    val requiresConfirmation: Boolean,
)

/**
 * Pure, testable logic for the host-action control shown in the control bar.
 * The control is a single compact icon button that opens a dropdown of window
 * actions (move the focused window to the client, return moved windows). It is
 * offered only when host actions were negotiated and the host advertised at
 * least one action this client understands; otherwise the button collapses so
 * it never adds a dead tap target to the compact capsule.
 */
internal object HostActionMenuPolicy {
    fun isAvailable(
        hostActions: Boolean,
        actions: List<HostActionOption>,
    ): Boolean = hostActions && actions.isNotEmpty()

    /**
     * Menu label for an action. Prefers the host's localized name and falls
     * back to a stable per-id default so the menu never renders an empty row
     * even if the host omits a name.
     */
    fun menuLabel(
        option: HostActionOption,
        moveDefault: String,
        returnDefault: String,
    ): String {
        val trimmed = option.name.trim()
        if (trimmed.isNotEmpty()) return trimmed
        return when (option.id) {
            ACTION_MOVE_WINDOW -> moveDefault
            ACTION_RETURN_WINDOWS -> returnDefault
            else -> option.id
        }
    }

    const val ACTION_MOVE_WINDOW = "move-window"
    const val ACTION_RETURN_WINDOWS = "return-windows"
}

/**
 * Pure layout policy for the connection panel's header/actions split. The
* panel stacks the brand/title header above the connection actions in a single
* column by default; when there is enough horizontal room (landscape) it places
 * the header beside the actions in two weighted columns. Keeping the geometry
 * here lets the orientation, sizing, and weight decisions be unit-tested
 * without inflating any Android view.
 */
internal object ConnectionPanelLayoutPolicy {
    /** LinearLayout.VERTICAL / LinearLayout.HORIZONTAL mirrored as data. */
    enum class Orientation {
        VERTICAL,
        HORIZONTAL,
    }

    /**
     * Resolved geometry for one child column. [widthMatchParent] maps to
     * MATCH_PARENT when true and 0dp (weighted) when false; [weight] is the
     * LinearLayout weight to assign.
     */
    data class Column(
        val widthMatchParent: Boolean,
        val weight: Float,
    )

    data class Layout(
        val contentOrientation: Orientation,
        val header: Column,
        val actions: Column,
        /** Gap placed between the two columns; zero in the stacked layout. */
        val columnGapPx: Int,
        val subtitleMaxLines: Int,
    )

    // Landscape splits roughly 40/60 so the actions column, which carries the
    // mode switch and the tallest per-mode content, gets the extra room.
    const val HEADER_WEIGHT = 40f
    const val ACTIONS_WEIGHT = 60f
    const val LANDSCAPE_SUBTITLE_MAX_LINES = 3

    /**
     * @param twoColumn whether the current configuration opts into the
     *   side-by-side layout (typically true in landscape).
     * @param columnGapPx spacing to insert between the columns when they sit
     *   side by side; ignored in the stacked layout.
     */
    fun resolve(
        twoColumn: Boolean,
        columnGapPx: Int,
    ): Layout =
        if (twoColumn) {
            Layout(
                contentOrientation = Orientation.HORIZONTAL,
                header = Column(widthMatchParent = false, weight = HEADER_WEIGHT),
                actions = Column(widthMatchParent = false, weight = ACTIONS_WEIGHT),
                columnGapPx = columnGapPx.coerceAtLeast(0),
                subtitleMaxLines = LANDSCAPE_SUBTITLE_MAX_LINES,
            )
        } else {
            // Stacked: both children keep their original full-width, unweighted
            // visual so portrait renders exactly as before.
            Layout(
                contentOrientation = Orientation.VERTICAL,
                header = Column(widthMatchParent = true, weight = 0f),
                actions = Column(widthMatchParent = true, weight = 0f),
                columnGapPx = 0,
                subtitleMaxLines = Int.MAX_VALUE,
            )
        }
}

internal object UsbConnectActionPolicy {
    enum class Action {
        CONNECT,
        CONNECTING,
        TRY_AGAIN,
    }

    fun resolve(
        connectionAttemptInProgress: Boolean,
        hasAttemptedConnection: Boolean,
    ): Action =
        when {
            connectionAttemptInProgress -> Action.CONNECTING
            hasAttemptedConnection -> Action.TRY_AGAIN
            else -> Action.CONNECT
        }
}
