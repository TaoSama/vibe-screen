package dev.telemachus.display

import android.content.res.Resources
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/** Views whose layout is controlled together by [ControlBarLayoutApplier]. */
internal data class ControlBarViews(
    val card: View,
    val content: LinearLayout,
    val connectionStatus: View,
    val displaySelector: View,
    val actions: LinearLayout,
    val hostAction: View,
    val clipboard: View,
    val settings: View,
    val disconnect: View,
)

/** Keeps the full-screen reveal action out of the accessibility tree while chrome is visible. */
internal object ControlBarAccessibilityApplier {
    fun applyRevealAction(
        inputViewport: View,
        connected: Boolean,
        controlBarVisible: Boolean,
    ) {
        inputViewport.importantForAccessibility =
            if (ControlBarAccessibilityPolicy.shouldExposeRevealAction(connected, controlBarVisible)) {
                View.IMPORTANT_FOR_ACCESSIBILITY_YES
            } else {
                View.IMPORTANT_FOR_ACCESSIBILITY_NO
            }
    }
}

/** Applies physical window insets to start/end-aware chrome margins. */
internal object ChromeSafeAreaApplier {
    fun captureBaseMargins(view: View): SafeAreaGeometry.Insets {
        val params = view.layoutParams as? ViewGroup.MarginLayoutParams
            ?: return SafeAreaGeometry.Insets.NONE
        return SafeAreaGeometry.Insets.of(
            left = params.marginStart,
            top = params.topMargin,
            right = params.marginEnd,
            bottom = params.bottomMargin,
        )
    }

    fun applyMargins(
        view: View,
        baseMargins: SafeAreaGeometry.Insets,
        safeAreaInsets: SafeAreaGeometry.Insets,
    ) {
        val params = view.layoutParams as? ViewGroup.MarginLayoutParams ?: return
        val isRtl = view.layoutDirection == View.LAYOUT_DIRECTION_RTL
        val safeStart = if (isRtl) safeAreaInsets.right else safeAreaInsets.left
        val safeEnd = if (isRtl) safeAreaInsets.left else safeAreaInsets.right
        val newStart = safeStart + baseMargins.left
        val newTop = safeAreaInsets.top + baseMargins.top
        val newEnd = safeEnd + baseMargins.right
        val newBottom = safeAreaInsets.bottom + baseMargins.bottom
        if (params.marginStart != newStart ||
            params.topMargin != newTop ||
            params.marginEnd != newEnd ||
            params.bottomMargin != newBottom
        ) {
            params.marginStart = newStart
            params.topMargin = newTop
            params.marginEnd = newEnd
            params.bottomMargin = newBottom
            view.layoutParams = params
        }
    }
}

/**
 * Production adapter from resource pixels and current window geometry to the
 * control-bar views. Keeping this outside the Activity lets device tests run
 * the same resource mapping and mutations that ship in the app.
 */
internal object ControlBarLayoutApplier {
    fun geometry(resources: Resources): ControlBarLayoutPolicy.Geometry =
        ControlBarLayoutPolicy.Geometry(
            horizontalContentPaddingPx =
                resources.getDimensionPixelSize(R.dimen.control_bar_content_padding) * 2,
            selectorMinimumWidthPx = resources.getDimensionPixelSize(R.dimen.display_capsule_min_width),
            buttonSizePx = resources.getDimensionPixelSize(R.dimen.control_bar_button_size),
            actionMarginPx = resources.getDimensionPixelSize(R.dimen.control_bar_button_margin),
            disconnectSeparationPx =
                resources.getDimensionPixelSize(R.dimen.control_bar_disconnect_margin_start),
            columnActionSpacingPx =
                resources.getDimensionPixelSize(R.dimen.control_bar_column_button_margin),
            statusMinimumWidthPx = resources.getDimensionPixelSize(R.dimen.connection_status_min_width),
            statusGapPx = resources.getDimensionPixelSize(R.dimen.connection_status_gap),
        )

    fun apply(
        views: ControlBarViews,
        resources: Resources,
        windowWidthPx: Int,
        safeAreaInsets: SafeAreaGeometry.Insets,
    ): ControlBarLayoutPolicy.Mode {
        val geometry = geometry(resources)
        val availableWidthPx =
            (windowWidthPx.coerceAtLeast(0) - safeAreaInsets.left - safeAreaInsets.right)
                .coerceAtLeast(0)
        val hostActionsVisible = views.hostAction.visibility == View.VISIBLE
        val clipboardVisible = views.clipboard.visibility == View.VISIBLE
        val mode =
            ControlBarLayoutPolicy.mode(
                availableWidthPx = availableWidthPx,
                displaySelectorVisible = views.displaySelector.visibility == View.VISIBLE,
                hostActionsVisible = hostActionsVisible,
                clipboardVisible = clipboardVisible,
                geometry = geometry,
        )
        val cardParams = views.card.layoutParams
        val statusParams = views.connectionStatus.layoutParams as LinearLayout.LayoutParams
        val selectorParams = views.displaySelector.layoutParams as LinearLayout.LayoutParams
        val actionsParams = views.actions.layoutParams as LinearLayout.LayoutParams
        views.connectionStatus.minimumWidth = geometry.statusMinimumWidthPx
        views.displaySelector.minimumWidth = geometry.selectorMinimumWidthPx
        when (mode) {
            ControlBarLayoutPolicy.Mode.COMPACT -> {
                cardParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.content.orientation = LinearLayout.HORIZONTAL
                statusParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                statusParams.weight = 0f
                selectorParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.INLINE -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.HORIZONTAL
                statusParams.width = geometry.statusMinimumWidthPx
                statusParams.weight = 0f
                selectorParams.width = 0
                selectorParams.weight = 1f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.STACKED -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.VERTICAL
                statusParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                statusParams.weight = 0f
                selectorParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.COLUMN -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.VERTICAL
                statusParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                statusParams.weight = 0f
                selectorParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.VERTICAL
            }
        }
        views.card.layoutParams = cardParams
        views.connectionStatus.layoutParams = statusParams
        views.displaySelector.layoutParams = selectorParams
        views.actions.layoutParams = actionsParams
        val statusMargins = ControlBarLayoutPolicy.statusMargins(mode, geometry)
        (views.connectionStatus.layoutParams as LinearLayout.LayoutParams).also { params ->
            params.marginStart = statusMargins.startPx
            params.topMargin = statusMargins.topPx
            params.marginEnd = statusMargins.endPx
            params.bottomMargin = statusMargins.bottomPx
            views.connectionStatus.layoutParams = params
        }
        listOf(
            views.hostAction to ControlBarLayoutPolicy.Action.HOST,
            views.clipboard to ControlBarLayoutPolicy.Action.CLIPBOARD,
            views.settings to ControlBarLayoutPolicy.Action.SETTINGS,
            views.disconnect to ControlBarLayoutPolicy.Action.DISCONNECT,
        ).forEach { (view, action) ->
            val margins = ControlBarLayoutPolicy.actionMargins(mode, action, hostActionsVisible, clipboardVisible, geometry)
            val params = view.layoutParams as LinearLayout.LayoutParams
            params.marginStart = margins.startPx
            params.topMargin = margins.topPx
            params.marginEnd = margins.endPx
            params.bottomMargin = margins.bottomPx
            view.layoutParams = params
        }
        return mode
    }
}

/** Production binding for the visible and accessibility display names. */
internal object DisplayCapsuleViewBinder {
    fun bind(
        resources: Resources,
        selector: View,
        labelView: TextView,
        displaySelection: Boolean,
        displays: List<StreamDisplayOption>,
        selectedId: String,
    ): Boolean {
        val selectable = DisplayCapsulePolicy.isSelectable(displaySelection, displays)
        val label =
            DisplayCapsulePolicy.capsuleLabel(displays, selectedId)
                .ifEmpty { resources.getString(R.string.display_capsule_placeholder) }
        labelView.text = label
        selector.contentDescription = resources.getString(R.string.control_displays_current, label)
        selector.visibility = if (selectable) View.VISIBLE else View.GONE
        selector.isEnabled = selectable
        return selectable
    }
}
