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
    val displaySelector: View,
    val actions: LinearLayout,
    val hostAction: View,
    val settings: View,
    val disconnect: View,
)

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
        val mode =
            ControlBarLayoutPolicy.mode(
                availableWidthPx = availableWidthPx,
                displaySelectorVisible = views.displaySelector.visibility == View.VISIBLE,
                hostActionsVisible = hostActionsVisible,
                geometry = geometry,
            )
        val cardParams = views.card.layoutParams
        val selectorParams = views.displaySelector.layoutParams as LinearLayout.LayoutParams
        val actionsParams = views.actions.layoutParams as LinearLayout.LayoutParams
        when (mode) {
            ControlBarLayoutPolicy.Mode.COMPACT -> {
                cardParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.content.orientation = LinearLayout.HORIZONTAL
                selectorParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.INLINE -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.HORIZONTAL
                selectorParams.width = 0
                selectorParams.weight = 1f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.STACKED -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.VERTICAL
                selectorParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.HORIZONTAL
            }
            ControlBarLayoutPolicy.Mode.COLUMN -> {
                cardParams.width = 0
                views.content.orientation = LinearLayout.VERTICAL
                selectorParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                selectorParams.weight = 0f
                actionsParams.width = ViewGroup.LayoutParams.WRAP_CONTENT
                views.actions.orientation = LinearLayout.VERTICAL
            }
        }
        views.card.layoutParams = cardParams
        views.displaySelector.layoutParams = selectorParams
        views.actions.layoutParams = actionsParams
        listOf(
            views.hostAction to ControlBarLayoutPolicy.Action.HOST,
            views.settings to ControlBarLayoutPolicy.Action.SETTINGS,
            views.disconnect to ControlBarLayoutPolicy.Action.DISCONNECT,
        ).forEach { (view, action) ->
            val margins = ControlBarLayoutPolicy.actionMargins(mode, action, hostActionsVisible, geometry)
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
