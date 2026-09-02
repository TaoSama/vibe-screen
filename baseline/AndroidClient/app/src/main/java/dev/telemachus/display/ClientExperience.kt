package dev.telemachus.display

import android.content.pm.ActivityInfo
import android.view.Gravity
import dev.vibescreen.protocol.v1.VideoQualityPreset

internal object ControlBarAccessibilityPolicy {
    const val STANDARD_AUTO_HIDE_MS = 5_000L
    const val SESSION_STARTED_AUTO_HIDE_MS = 7_000L

    enum class RevealReason {
        USER_REQUEST,
        SESSION_STARTED,
    }

    fun shouldAutoHide(touchExplorationEnabled: Boolean): Boolean = !touchExplorationEnabled

    fun autoHideDelayMs(
        touchExplorationEnabled: Boolean,
        revealReason: RevealReason,
    ): Long? =
        if (shouldAutoHide(touchExplorationEnabled)) {
            when (revealReason) {
                RevealReason.SESSION_STARTED -> SESSION_STARTED_AUTO_HIDE_MS
                RevealReason.USER_REQUEST -> STANDARD_AUTO_HIDE_MS
            }
        } else {
            null
        }

    fun shouldExposeRevealAction(
        connected: Boolean,
        controlBarVisible: Boolean,
    ): Boolean = connected && !controlBarVisible
}

internal enum class StreamTouchPhase {
    BEGIN,
    UPDATE,
    END,
    CANCEL,
    OTHER,
}

/**
 * Keeps the hidden control bar tap-to-reveal gesture from leaking through as an
 * accidental Mac click. Stylus and pointer input bypass this policy so a
 * drawing stroke or external pointer action is never consumed just because the
 * transient chrome was hidden.
 */
internal object ControlRevealGesturePolicy {
    fun shouldStartRevealOnlyGesture(
        connected: Boolean,
        controlBarVisible: Boolean,
        directTouch: Boolean,
        inRevealHotZone: Boolean,
        phase: StreamTouchPhase,
    ): Boolean = connected && !controlBarVisible && directTouch && inRevealHotZone && phase == StreamTouchPhase.BEGIN

    fun shouldConsumeActiveRevealOnlyGesture(
        revealOnlyGestureActive: Boolean,
        directTouch: Boolean,
        phase: StreamTouchPhase,
    ): Boolean = revealOnlyGestureActive && directTouch && phase != StreamTouchPhase.OTHER

    fun endsGesture(phase: StreamTouchPhase): Boolean = phase == StreamTouchPhase.END || phase == StreamTouchPhase.CANCEL
}

internal object DisplayMenuSelectionGuard {
    fun acceptsSelection(
        menuShownAtMs: Long,
        nowMs: Long,
        armDelayMs: Long,
    ): Boolean = menuShownAtMs >= 0L && nowMs - menuShownAtMs >= armDelayMs
}

internal object ConnectionSecurityPresentationPolicy {
    data class Presentation(
        val labelResource: Int,
        val detailResource: Int,
        val warning: Boolean,
    )

    fun presentation(
        mode: ConnectionMode,
        lanProtectionState: LanRecordProtectionState = LanRecordProtectionState.NOT_APPLICABLE,
    ): Presentation =
        when (mode) {
            ConnectionMode.USB ->
                Presentation(
                    labelResource = R.string.stream_status_usb_label,
                    detailResource = R.string.stream_status_usb_detail,
                    warning = false,
                )
            ConnectionMode.WIRELESS ->
                Presentation(
                    labelResource = R.string.stream_status_lan_label,
                    detailResource =
                        when (lanProtectionState) {
                            LanRecordProtectionState.ENCRYPTED -> R.string.stream_status_lan_encrypted_detail
                            LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK ->
                                R.string.stream_status_lan_legacy_plaintext_detail
                            LanRecordProtectionState.NEGOTIATING -> R.string.stream_status_lan_negotiating_detail
                            LanRecordProtectionState.NOT_APPLICABLE -> R.string.stream_status_lan_unknown_detail
                        },
                    warning = lanProtectionState != LanRecordProtectionState.ENCRYPTED,
                )
            ConnectionMode.INTERNET ->
                Presentation(
                    labelResource = R.string.stream_status_internet_label,
                    detailResource = R.string.stream_status_internet_detail,
                    warning = false,
                )
        }
}

internal object LanClipboardProtectionMessagePolicy {
    fun sendMessage(state: LanRecordProtectionState): Int =
        when (state) {
            LanRecordProtectionState.ENCRYPTED -> R.string.clipboard_lan_confirm_message
            LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK -> R.string.clipboard_lan_legacy_confirm_message
            LanRecordProtectionState.NEGOTIATING,
            LanRecordProtectionState.NOT_APPLICABLE,
            -> R.string.clipboard_lan_unknown_confirm_message
        }

    fun receiveMessage(state: LanRecordProtectionState): Int =
        when (state) {
            LanRecordProtectionState.ENCRYPTED -> R.string.clipboard_lan_receive_confirm_message
            LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK -> R.string.clipboard_lan_legacy_receive_confirm_message
            LanRecordProtectionState.NEGOTIATING,
            LanRecordProtectionState.NOT_APPLICABLE,
            -> R.string.clipboard_lan_unknown_receive_confirm_message
        }

    fun directReceiveMessage(state: LanRecordProtectionState): Int =
        when (state) {
            LanRecordProtectionState.ENCRYPTED -> R.string.clipboard_lan_direct_receive_confirm_message
            LanRecordProtectionState.EXPLICIT_LEGACY_FALLBACK -> R.string.clipboard_lan_legacy_direct_receive_confirm_message
            LanRecordProtectionState.NEGOTIATING,
            LanRecordProtectionState.NOT_APPLICABLE,
            -> R.string.clipboard_lan_unknown_direct_receive_confirm_message
        }
}

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
    const val KBPS_PER_MBPS = 1_000
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
                ?.let { (it + ClientVideoBounds.KBPS_PER_MBPS / 2) / ClientVideoBounds.KBPS_PER_MBPS }
                ?.coerceIn(ClientVideoBounds.MIN_BITRATE_MBPS, ClientVideoBounds.MAX_BITRATE_MBPS)
        val supportedFrameRate = framesPerSecond.takeIf(ClientVideoBounds.FRAME_RATE_CHOICES::contains)
        return AppliedVideoPreferenceProjection(bitrateMbps, supportedFrameRate)
    }
}

internal data class SavedVideoPreferenceReplay(
    val bitrateKbps: Int,
    val framesPerSecond: Int,
    val qualityPreset: VideoQualityPreset,
    val resetQualityToAuto: Boolean = false,
)

internal object SavedVideoPreferenceReplayPolicy {
    fun fromSavedPreferences(
        quality: VideoQualityChoice,
        bitrateMbps: Int,
        framesPerSecond: Int,
    ): SavedVideoPreferenceReplay? {
        val explicitBitrate =
            bitrateMbps
                .takeIf { it != ClientVideoBounds.DEFAULT_BITRATE_MBPS }
                ?.coerceIn(ClientVideoBounds.MIN_BITRATE_MBPS, ClientVideoBounds.MAX_BITRATE_MBPS)
                ?.times(ClientVideoBounds.KBPS_PER_MBPS)
                ?: 0
        val explicitFrameRate =
            framesPerSecond.takeIf {
                it != ClientVideoBounds.DEFAULT_FRAME_RATE && it in ClientVideoBounds.FRAME_RATE_CHOICES
            } ?: 0
        return when {
            quality == VideoQualityChoice.AUTO && explicitBitrate == 0 && explicitFrameRate == 0 -> null
            quality == VideoQualityChoice.AUTO ->
                SavedVideoPreferenceReplay(
                    bitrateKbps = explicitBitrate,
                    framesPerSecond = explicitFrameRate,
                    qualityPreset = VideoQualityPreset.VIDEO_QUALITY_PRESET_UNSPECIFIED,
                    resetQualityToAuto = true,
                )
            else ->
                SavedVideoPreferenceReplay(
                    bitrateKbps = explicitBitrate,
                    framesPerSecond = explicitFrameRate,
                    qualityPreset = quality.preset,
                )
        }
    }
}

internal object SavedVideoPreferenceReplayer {
    fun replayIfAvailable(
        clientVideoControlAvailable: Boolean,
        quality: VideoQualityChoice,
        bitrateMbps: Int,
        framesPerSecond: Int,
        send: (SavedVideoPreferenceReplay) -> Unit,
    ): Boolean {
        if (!clientVideoControlAvailable) return false
        val replay =
            SavedVideoPreferenceReplayPolicy.fromSavedPreferences(
                quality = quality,
                bitrateMbps = bitrateMbps,
                framesPerSecond = framesPerSecond,
            ) ?: return false
        send(replay)
        return true
    }
}

internal enum class VideoPreferenceFeedbackKind {
    QUALITY,
    FRAME_RATE,
    BITRATE,
}

internal object VideoPreferenceFeedbackPolicy {
    fun shouldAnnounceRequest(clientAvailable: Boolean): Boolean = clientAvailable

    fun shouldAnnounceApplied(
        appliesClientVideoPreferences: Boolean,
        configEpoch: Long,
        lastAnnouncedConfigEpoch: Long,
    ): Boolean = appliesClientVideoPreferences && configEpoch > lastAnnouncedConfigEpoch
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

    fun screenOrientationFor(effectiveRotation: Int): Int =
        when (normalizeRotation(effectiveRotation)) {
            90 -> ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            180 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE
            270 -> ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT
            else -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        }

    fun surfaceTransformRotation(clientRotation: ClientRotation): Int = clientRotation.degrees

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
    val controller: Boolean,
    val customGestures: Boolean,
    val hostActions: Boolean,
    val clipboard: Boolean,
    val fileTransfer: Boolean,
    val peripheralInputFramework: Boolean = false,
) {
    companion object {
        val LEGACY_TOUCH_ONLY =
            ClientSessionCapabilities(
                touch = true,
                displaySelection = false,
                keyboard = false,
                nativePointer = false,
                controller = false,
                customGestures = false,
                hostActions = false,
                clipboard = false,
                fileTransfer = false,
                peripheralInputFramework = false,
            )
    }
}

internal enum class ClientControl {
    DISPLAY_SELECTION,
    KEYBOARD,
    NATIVE_POINTER,
    HOST_ACTIONS,
    CUSTOM_GESTURES,
    CLIPBOARD,
    FILE_TRANSFER,
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
    enum class DisplayKind {
        PRIMARY,
        VIRTUAL,
        BUILT_IN,
        EXTERNAL,
    }

    /** Display selection is offered only when negotiated and there is a choice. */
    fun isSelectable(
        displaySelection: Boolean,
        displays: List<StreamDisplayOption>,
    ): Boolean = displaySelection && displays.size > 1

    /** Disable the selector while a host-side display switch is still settling. */
    fun isEnabled(
        displaySelection: Boolean,
        displays: List<StreamDisplayOption>,
        pendingDisplayId: String?,
    ): Boolean = isSelectable(displaySelection, displays) && pendingDisplayId == null

    /** Resolve the option currently marked active, if any. */
    fun activeOption(
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ): StreamDisplayOption? = displays.firstOrNull { it.id == selectedId }

    fun pendingOption(
        displays: List<StreamDisplayOption>,
        pendingId: String?,
    ): StreamDisplayOption? = pendingId?.let { id -> displays.firstOrNull { it.id == id } }

    /**
     * Label shown on the capsule. Falls back to the primary/first display when
     * the selected id is unknown so the capsule never reads as empty. The view
     * owns visual ellipsizing because its width depends on safe-area and window
     * constraints; retaining the full name also keeps accessibility intact.
     */
    fun capsuleLabel(
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ): String {
        val active =
            activeOption(displays, selectedId)
                ?: displays.firstOrNull { it.isPrimary }
                ?: displays.firstOrNull()
                ?: return ""
        return active.name.trim()
    }

    fun displayKind(option: StreamDisplayOption): DisplayKind =
        when {
            option.isVirtual -> DisplayKind.VIRTUAL
            option.isPrimary -> DisplayKind.PRIMARY
            option.name.contains("built", ignoreCase = true) -> DisplayKind.BUILT_IN
            option.name.contains("internal", ignoreCase = true) -> DisplayKind.BUILT_IN
            else -> DisplayKind.EXTERNAL
        }
}

internal object ControlBarLayoutPolicy {
    enum class Mode { COMPACT, INLINE, STACKED, COLUMN }
    enum class Action { HOST, CLIPBOARD, FILE_TRANSFER, SETTINGS, DISCONNECT }

    data class Geometry(
        val horizontalContentPaddingPx: Int,
        val selectorMinimumWidthPx: Int,
        val buttonSizePx: Int,
        val actionMarginPx: Int,
        val disconnectSeparationPx: Int,
        val columnActionSpacingPx: Int,
        val statusMinimumWidthPx: Int,
        val statusGapPx: Int,
    ) {
        init {
            require(horizontalContentPaddingPx >= 0)
            require(selectorMinimumWidthPx > 0)
            require(buttonSizePx > 0)
            require(actionMarginPx >= 0)
            require(disconnectSeparationPx >= 0)
            require(columnActionSpacingPx >= 0)
            require(statusMinimumWidthPx > 0)
            require(statusGapPx >= 0)
        }

        fun horizontalActionsWidthPx(
            hostActionsVisible: Boolean,
            clipboardVisible: Boolean,
            fileTransferVisible: Boolean = false,
        ): Int {
            val settingsWidth = buttonSizePx + actionMarginPx * 2
            val disconnectWidth = buttonSizePx + disconnectSeparationPx
            val hostWidth = if (hostActionsVisible) buttonSizePx + actionMarginPx * 2 else 0
            val clipboardWidth = if (clipboardVisible) buttonSizePx + actionMarginPx * 2 else 0
            val fileTransferWidth = if (fileTransferVisible) buttonSizePx + actionMarginPx * 2 else 0
            return hostWidth + clipboardWidth + fileTransferWidth + settingsWidth + disconnectWidth
        }
    }

    data class Margins(
        val startPx: Int,
        val topPx: Int,
        val endPx: Int,
        val bottomPx: Int = 0,
    )

    fun mode(
        availableWidthPx: Int,
        displaySelectorVisible: Boolean,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
        geometry: Geometry,
        fileTransferVisible: Boolean = false,
    ): Mode {
        val actionWidthPx = geometry.horizontalActionsWidthPx(hostActionsVisible, clipboardVisible, fileTransferVisible)
        val statusWidthPx = geometry.statusMinimumWidthPx + geometry.statusGapPx
        if (!displaySelectorVisible) {
            val compactMinimumPx = geometry.horizontalContentPaddingPx + statusWidthPx + actionWidthPx
            return if (availableWidthPx >= compactMinimumPx) Mode.COMPACT else Mode.COLUMN
        }
        val inlineMinimumPx =
            geometry.horizontalContentPaddingPx +
                statusWidthPx +
                geometry.selectorMinimumWidthPx +
                actionWidthPx
        val stackedMinimumPx =
            geometry.horizontalContentPaddingPx +
                maxOf(geometry.statusMinimumWidthPx, geometry.selectorMinimumWidthPx, actionWidthPx)
        return when {
            availableWidthPx >= inlineMinimumPx -> Mode.INLINE
            availableWidthPx >= stackedMinimumPx -> Mode.STACKED
            else -> Mode.COLUMN
        }
    }

    fun statusMargins(
        mode: Mode,
        geometry: Geometry,
    ): Margins =
        when (mode) {
            Mode.COMPACT, Mode.INLINE -> Margins(0, 0, geometry.statusGapPx)
            Mode.STACKED, Mode.COLUMN -> Margins(0, 0, 0, geometry.statusGapPx)
        }

    fun actionMargins(
        mode: Mode,
        action: Action,
        hostActionsVisible: Boolean,
        clipboardVisible: Boolean,
        geometry: Geometry,
        fileTransferVisible: Boolean = false,
    ): Margins =
        if (mode == Mode.COLUMN) {
            when (action) {
                Action.HOST -> Margins(0, 0, 0)
                Action.CLIPBOARD ->
                    Margins(0, if (hostActionsVisible) geometry.columnActionSpacingPx else 0, 0)
                Action.FILE_TRANSFER ->
                    Margins(
                        0,
                        if (hostActionsVisible || clipboardVisible) geometry.columnActionSpacingPx else 0,
                        0,
                    )
                Action.SETTINGS ->
                    Margins(
                        0,
                        if (hostActionsVisible || clipboardVisible || fileTransferVisible) {
                            geometry.columnActionSpacingPx
                        } else {
                            0
                        },
                        0,
                    )
                Action.DISCONNECT -> Margins(0, geometry.disconnectSeparationPx, 0)
            }
        } else {
            when (action) {
                Action.HOST, Action.CLIPBOARD, Action.FILE_TRANSFER, Action.SETTINGS ->
                    Margins(geometry.actionMarginPx, 0, geometry.actionMarginPx)
                Action.DISCONNECT -> Margins(geometry.disconnectSeparationPx, 0, 0)
            }
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
            ClientControl.CUSTOM_GESTURES -> capabilities.customGestures
            ClientControl.CLIPBOARD -> capabilities.clipboard
            ClientControl.FILE_TRANSFER -> capabilities.fileTransfer
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

enum class HostActionSelectionMode {
    INVOKE,
    CONFIRM,
}

internal enum class GestureHostActionTrigger {
    THREE_FINGER_SWIPE_UP,
    THREE_FINGER_SWIPE_DOWN,
}

internal sealed class GestureHostActionMappingAction {
    data object Default : GestureHostActionMappingAction()
    data object Deny : GestureHostActionMappingAction()
    data class InvokeHostAction(val actionId: String) : GestureHostActionMappingAction()
}

enum class GestureHostActionChoice {
    DEFAULT,
    MOVE_WINDOW,
    RETURN_WINDOWS,
    ;

    internal fun toMappingAction(): GestureHostActionMappingAction =
        when (this) {
            DEFAULT -> GestureHostActionMappingAction.Default
            MOVE_WINDOW -> GestureHostActionMappingAction.InvokeHostAction(HostActionMenuPolicy.ACTION_MOVE_WINDOW)
            RETURN_WINDOWS -> GestureHostActionMappingAction.InvokeHostAction(HostActionMenuPolicy.ACTION_RETURN_WINDOWS)
        }

    companion object {
        fun fromName(value: String?): GestureHostActionChoice = entries.firstOrNull { it.name == value } ?: DEFAULT
    }
}

internal fun GestureHostActionChoice.isSupportedByHostActions(availableHostActions: Iterable<HostActionOption>): Boolean =
    when (val action = toMappingAction()) {
        GestureHostActionMappingAction.Default -> true
        GestureHostActionMappingAction.Deny -> false
        is GestureHostActionMappingAction.InvokeHostAction -> availableHostActions.any { it.id == action.actionId }
    }

internal fun GestureHostActionChoice.effectiveForHostActions(availableHostActions: Iterable<HostActionOption>): GestureHostActionChoice =
    if (isSupportedByHostActions(availableHostActions)) this else GestureHostActionChoice.DEFAULT

internal data class GestureHostActionMapping(
    val trigger: GestureHostActionTrigger,
    val action: GestureHostActionMappingAction,
)

internal data class GestureHostActionProfile(
    val mappings: List<GestureHostActionMapping> = emptyList(),
) {
    companion object {
        val DEFAULT = GestureHostActionProfile()

        fun fromChoices(
            swipeUp: GestureHostActionChoice,
            swipeDown: GestureHostActionChoice,
        ): GestureHostActionProfile =
            GestureHostActionProfile(
                mappings =
                    listOf(
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_UP,
                            action = swipeUp.toMappingAction(),
                        ),
                        GestureHostActionMapping(
                            trigger = GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN,
                            action = swipeDown.toMappingAction(),
                        ),
                    ),
            )
    }
}

internal data class GestureHostActionPolicyContext(
    val customGesturesAllowed: Boolean,
    val hostActionsAllowed: Boolean,
    val hostActionsNegotiated: Boolean,
    val availableHostActionIds: Set<String>,
)

internal sealed class GestureHostActionDecision {
    data object Default : GestureHostActionDecision()
    data object Denied : GestureHostActionDecision()
    data class InvokeHostAction(val actionId: String) : GestureHostActionDecision()
}

internal object GestureHostActionPolicy {
    fun knownActionIds(): Set<String> = HostActionMenuPolicy.KNOWN_ACTION_IDS

    fun shouldInterceptThreeFingerGestures(profile: GestureHostActionProfile): Boolean =
        profile.mappings.any { mapping ->
            when (mapping.action) {
                GestureHostActionMappingAction.Default -> false
                GestureHostActionMappingAction.Deny,
                is GestureHostActionMappingAction.InvokeHostAction,
                -> true
            }
        }

    fun resolve(
        trigger: GestureHostActionTrigger,
        profile: GestureHostActionProfile,
        context: GestureHostActionPolicyContext,
    ): GestureHostActionDecision {
        val matches = profile.mappings.filter { it.trigger == trigger }
        if (matches.size > 1) return GestureHostActionDecision.Denied
        val mapping = matches.firstOrNull() ?: return GestureHostActionDecision.Default
        return when (val action = mapping.action) {
            GestureHostActionMappingAction.Default -> GestureHostActionDecision.Default
            GestureHostActionMappingAction.Deny -> GestureHostActionDecision.Denied
            is GestureHostActionMappingAction.InvokeHostAction -> {
                if (context.customGesturesAllowed &&
                    context.hostActionsAllowed &&
                    context.hostActionsNegotiated &&
                    action.actionId in knownActionIds() &&
                    action.actionId in context.availableHostActionIds
                ) {
                    GestureHostActionDecision.InvokeHostAction(action.actionId)
                } else {
                    GestureHostActionDecision.Denied
                }
            }
        }
    }
}

internal enum class ThreeFingerGesturePhase {
    BEGIN,
    MOVE,
    END,
    CANCEL,
    OTHER,
}

internal data class ThreeFingerGestureSample(
    val pointerCount: Int,
    val phase: ThreeFingerGesturePhase,
    val centroidY: Float,
    val viewportHeight: Int,
)

internal class ThreeFingerGestureClassifier(
    private val minimumSwipeFraction: Float = 0.12f,
) {
    private var startCentroidY: Float? = null

    fun consume(sample: ThreeFingerGestureSample): GestureHostActionTrigger? {
        if (sample.viewportHeight <= 0) {
            reset()
            return null
        }
        if (sample.pointerCount < THREE_FINGER_COUNT) {
            if (sample.phase == ThreeFingerGesturePhase.END) reset()
            return null
        }

        return when (sample.phase) {
            ThreeFingerGesturePhase.BEGIN -> {
                startCentroidY = sample.centroidY
                null
            }
            ThreeFingerGesturePhase.MOVE -> {
                val startY = startCentroidY
                if (startY == null) {
                    startCentroidY = sample.centroidY
                    null
                } else {
                    resolveCompletedSwipe(sample, startY, resetAfterMatch = true)
                }
            }
            ThreeFingerGesturePhase.END -> {
                val startY = startCentroidY ?: sample.centroidY
                reset()
                resolveCompletedSwipe(sample, startY, resetAfterMatch = false)
            }
            ThreeFingerGesturePhase.CANCEL,
            ThreeFingerGesturePhase.OTHER,
            -> {
                reset()
                null
            }
        }
    }

    fun reset() {
        startCentroidY = null
    }

    private fun resolveCompletedSwipe(
        sample: ThreeFingerGestureSample,
        startY: Float,
        resetAfterMatch: Boolean,
    ): GestureHostActionTrigger? {
        val deltaY = sample.centroidY - startY
        val threshold = sample.viewportHeight * minimumSwipeFraction
        val trigger =
            when {
                deltaY <= -threshold -> GestureHostActionTrigger.THREE_FINGER_SWIPE_UP
                deltaY >= threshold -> GestureHostActionTrigger.THREE_FINGER_SWIPE_DOWN
                else -> null
            }
        if (trigger != null && resetAfterMatch) reset()
        return trigger
    }

    private companion object {
        const val THREE_FINGER_COUNT = 3
    }
}

/**
 * Pure, testable logic for the host-action control shown in the control bar.
 * The control is a single compact icon button that opens a dropdown of window
 * actions (move the focused window to the client, return moved windows). It is
 * offered only when host actions were negotiated and the host advertised at
 * least one action this client understands; otherwise the button collapses so
 * it never adds a dead tap target to the compact capsule.
 */
internal object HostActionMenuPolicy {
    fun supportedActions(actions: List<HostActionOption>): List<HostActionOption> {
        val seen = mutableSetOf<String>()
        return actions.filter { option ->
            option.id in KNOWN_ACTION_IDS && seen.add(option.id)
        }
    }

    fun isAvailable(
        hostActions: Boolean,
        actions: List<HostActionOption>,
    ): Boolean = hostActions && supportedActions(actions).isNotEmpty()

    fun selectionMode(option: HostActionOption): HostActionSelectionMode =
        if (option.requiresConfirmation) HostActionSelectionMode.CONFIRM else HostActionSelectionMode.INVOKE

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
    internal val KNOWN_ACTION_IDS = setOf(ACTION_MOVE_WINDOW, ACTION_RETURN_WINDOWS)
}

/**
 * A clipboard offer advertised by the Mac. Stored only as pending metadata; the
 * actual content is fetched only after the user explicitly approves it via the
 * "Get from Mac" menu action. This prevents the Mac from silently overwriting
 * the local clipboard.
 */
data class PendingClipboardOffer(
    val changeId: ByteArray,
    val originDeviceId: String,
    val mimeType: String,
    val byteLength: Long,
    val sha256: ByteArray,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is PendingClipboardOffer) return false
        return changeId.contentEquals(other.changeId) &&
            originDeviceId == other.originDeviceId &&
            mimeType == other.mimeType &&
            byteLength == other.byteLength &&
            sha256.contentEquals(other.sha256)
    }

    override fun hashCode(): Int {
        var result = changeId.contentHashCode()
        result = 31 * result + originDeviceId.hashCode()
        result = 31 * result + mimeType.hashCode()
        result = 31 * result + byteLength.hashCode()
        result = 31 * result + sha256.contentHashCode()
        return result
    }
}

/**
 * Pure, testable logic for the clipboard control shown in the control bar. The
 * control is a single compact icon button that opens a dropdown of two actions:
 * send the local clipboard to the Mac, or fetch the Mac's pending clipboard
 * offer. It is offered only when clipboard support was negotiated; otherwise
 * the button collapses so it never adds a dead tap target to the compact
 * capsule.
 */
internal object ClipboardMenuPolicy {
    /** Default clipboard byte limit when the peer does not advertise one. */
    const val DEFAULT_CLIPBOARD_BYTES: Long = 1024L * 1024L // 1 MiB

    /** The clipboard button is shown only when clipboard support was negotiated. */
    fun isAvailable(clipboard: Boolean): Boolean = clipboard

    /**
     * Whether the local clipboard text can be sent. Empty text is rejected so
     * the menu never sends a no-op offer to the Mac.
     */
    fun canSend(text: String?): Boolean = !text.isNullOrEmpty()

    /**
     * Whether the local clipboard text fits within the effective clipboard
     * byte limit. A non-positive limit falls back to [DEFAULT_CLIPBOARD_BYTES]
     * rather than being treated as unbounded.
     */
    fun isWithinSizeLimit(
        text: String,
        maximumClipboardBytes: Long,
    ): Boolean {
        val peerLimit =
            if (maximumClipboardBytes > 0L) maximumClipboardBytes else DEFAULT_CLIPBOARD_BYTES
        val limit = minOf(DEFAULT_CLIPBOARD_BYTES, peerLimit)
        return text.toByteArray(Charsets.UTF_8).size <= limit
    }

    /**
     * Whether a pending Mac clipboard offer can be fetched. The offer must be
     * present; an absent offer means the Mac has nothing to send.
     */
    fun canFetch(offer: PendingClipboardOffer?): Boolean = offer != null
}

/**
 * Pure layout policy for the connection panel's header/actions split. The
 * panel stacks the brand/title header above the connection actions in a single
 * column by default; when there is enough horizontal room it places the header
 * beside the actions in two weighted columns. Keeping the geometry
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
        val contentGravity: Int,
        val header: Column,
        val actions: Column,
        /** Gap placed between the two columns; zero in the stacked layout. */
        val columnGapPx: Int,
    )

    // Landscape splits roughly 40/60 so the actions column, which carries the
    // mode switch and the tallest per-mode content, gets the extra room.
    const val HEADER_WEIGHT = 40f
    const val ACTIONS_WEIGHT = 60f
    /**
     * @param twoColumn whether the current width-qualified configuration opts
     *   into the side-by-side layout.
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
                contentGravity = Gravity.TOP,
                header = Column(widthMatchParent = false, weight = HEADER_WEIGHT),
                actions = Column(widthMatchParent = false, weight = ACTIONS_WEIGHT),
                columnGapPx = columnGapPx.coerceAtLeast(0),
            )
        } else {
            // Stacked: both children keep their original full-width, unweighted
            // visual while staying anchored to the scroll origin.
            Layout(
                contentOrientation = Orientation.VERTICAL,
                contentGravity = Gravity.TOP,
                header = Column(widthMatchParent = true, weight = 0f),
                actions = Column(widthMatchParent = true, weight = 0f),
                columnGapPx = 0,
            )
        }
}

/**
 * Keeps the mode switch compact in normal layouts while giving each label a
 * full-width row in single-column large-text mode. The P0110 portrait and
 * narrow-landscape widths can fit three equal touch targets at the default
 * scale, but 1.3x text needs the extra horizontal room to keep labels readable.
 */
internal object ConnectionModeToggleLayoutPolicy {
    enum class Orientation {
        VERTICAL,
        HORIZONTAL,
    }

    data class Layout(
        val orientation: Orientation,
        val buttonWidthMatchParent: Boolean,
        val buttonWeight: Float,
    )

    const val STACKED_FONT_SCALE_THRESHOLD = 1.3f

    fun resolve(
        stackedContent: Boolean,
        fontScale: Float,
    ): Layout =
        if (stackedContent && fontScale >= STACKED_FONT_SCALE_THRESHOLD) {
            Layout(
                orientation = Orientation.VERTICAL,
                buttonWidthMatchParent = true,
                buttonWeight = 0f,
            )
        } else {
            Layout(
                orientation = Orientation.HORIZONTAL,
                buttonWidthMatchParent = false,
                buttonWeight = 1f,
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

internal object UsbTransportDisplayPolicy {
    data class Snapshot(
        val developerModeEnabled: Boolean,
        val usbDebuggingSettingEnabled: Boolean,
        val wirelessDebuggingEnabled: Boolean,
        val usbDataConnected: Boolean,
        val usbAdbFunctionEnabled: Boolean,
        val serverRunning: Boolean,
    ) {
        val adbTransport: AdbTransportKind
            get() =
                when {
                    usbDataConnected && usbAdbFunctionEnabled -> AdbTransportKind.USB
                    wirelessDebuggingEnabled -> AdbTransportKind.WIRELESS
                    else -> AdbTransportKind.UNAVAILABLE
                }
    }

    data class Projection(
        val subtitleResource: Int,
        val debuggingLabelResource: Int,
        val debuggingStatus: ChecklistStatus,
        val transportLabelResource: Int,
        val transportStatus: ChecklistStatus,
        val allReady: Boolean,
    )

    fun shouldRefreshSubtitle(connectionMode: ConnectionMode): Boolean =
        connectionMode == ConnectionMode.USB

    fun project(snapshot: Snapshot): Projection {
        val debuggingReady =
            snapshot.adbTransport != AdbTransportKind.UNAVAILABLE ||
                (snapshot.usbDebuggingSettingEnabled && !snapshot.usbDataConnected)
        val transportReady =
            snapshot.usbDataConnected || snapshot.adbTransport == AdbTransportKind.WIRELESS
        return Projection(
            subtitleResource =
                when (snapshot.adbTransport) {
                    AdbTransportKind.USB -> R.string.usb_waiting_description
                    AdbTransportKind.WIRELESS -> R.string.wireless_adb_waiting_description
                    AdbTransportKind.UNAVAILABLE -> R.string.adb_transport_waiting_description
                },
            debuggingLabelResource =
                when {
                    snapshot.adbTransport == AdbTransportKind.USB -> R.string.usb_debugging
                    snapshot.adbTransport == AdbTransportKind.WIRELESS -> R.string.wireless_debugging
                    snapshot.usbDebuggingSettingEnabled -> R.string.usb_debugging
                    else -> R.string.usb_or_wireless_debugging
                },
            debuggingStatus = if (debuggingReady) ChecklistStatus.READY else ChecklistStatus.NOT_READY,
            transportLabelResource =
                when {
                    snapshot.adbTransport == AdbTransportKind.USB -> R.string.usb_data_link
                    snapshot.adbTransport == AdbTransportKind.WIRELESS -> R.string.wireless_debugging_connection
                    snapshot.usbDataConnected -> R.string.usb_data_link
                    else -> R.string.usb_data_link_or_wireless_debugging
                },
            transportStatus = if (transportReady) ChecklistStatus.READY else ChecklistStatus.NOT_READY,
            allReady =
                snapshot.developerModeEnabled &&
                    snapshot.adbTransport != AdbTransportKind.UNAVAILABLE &&
                    snapshot.serverRunning,
        )
    }
}
