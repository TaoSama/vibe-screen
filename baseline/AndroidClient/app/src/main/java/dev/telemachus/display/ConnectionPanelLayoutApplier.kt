package dev.telemachus.display

import android.content.res.Resources
import android.content.res.Configuration
import android.text.TextUtils
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.constraintlayout.widget.ConstraintLayout
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import com.google.android.material.button.MaterialButtonToggleGroup
import kotlin.math.roundToInt

internal object ConnectionPanelLayoutApplier {
    data class Views(
        val panel: View,
        val content: LinearLayout,
        val header: View,
        val actions: View,
        val subtitle: TextView,
    )

    fun apply(
        resources: Resources,
        views: Views,
        connectionMode: ConnectionMode,
        subtitleExpanded: Boolean,
    ): ConnectionPanelLayoutPolicy.Layout {
        applyConfigurationDimensions(resources, views)
        val layout =
            ConnectionPanelLayoutPolicy.resolve(
                twoColumn = resources.getBoolean(R.bool.connection_panel_two_column),
                columnGapPx = resources.getDimensionPixelSize(R.dimen.connection_panel_column_gap),
            )
        views.content.orientation =
            when (layout.contentOrientation) {
                ConnectionPanelLayoutPolicy.Orientation.HORIZONTAL -> LinearLayout.HORIZONTAL
                ConnectionPanelLayoutPolicy.Orientation.VERTICAL -> LinearLayout.VERTICAL
            }
        views.content.gravity = layout.contentGravity
        val stackedContent = layout.contentOrientation == ConnectionPanelLayoutPolicy.Orientation.VERTICAL
        val actionsAvailableWidthPx = actionsAvailableWidthPx(resources, views, layout)
        applyModeToggleLayout(
            views = views,
            layout =
                ConnectionModeToggleLayoutPolicy.resolve(
                    stackedContent = stackedContent,
                    fontScale = resources.configuration.fontScale,
                    availableWidthPx = actionsAvailableWidthPx,
                    minimumHorizontalButtonWidthPx =
                        dp(resources, ConnectionModeToggleLayoutPolicy.MINIMUM_HORIZONTAL_BUTTON_WIDTH_DP),
                ),
        )
        applyInternetProfileActionsLayout(
            views = views,
            layout =
                InternetProfileActionsLayoutPolicy.resolve(
                    stackedContent = stackedContent,
                    fontScale = resources.configuration.fontScale,
                    availableWidthPx = actionsAvailableWidthPx,
                    gapPx = resources.getDimensionPixelSize(R.dimen.connection_profile_action_gap),
                    minimumHorizontalButtonWidthPx =
                        dp(resources, InternetProfileActionsLayoutPolicy.MINIMUM_HORIZONTAL_BUTTON_WIDTH_DP),
                ),
        )
        applyInternetSecondaryActionsLayout(
            views = views,
            layout =
                InternetSecondaryActionsLayoutPolicy.resolve(
                    stackedContent = stackedContent,
                    fontScale = resources.configuration.fontScale,
                    availableWidthPx = actionsAvailableWidthPx,
                    gapPx = resources.getDimensionPixelSize(R.dimen.connection_profile_action_gap),
                    minimumHorizontalButtonWidthPx =
                        dp(resources, InternetSecondaryActionsLayoutPolicy.MINIMUM_HORIZONTAL_BUTTON_WIDTH_DP),
                    layoutButtonCount = layoutPresentInternetSecondaryActionCount(views),
                ),
        )
        applyDiagnosticsLayout(
            views = views,
            layout =
                ConnectionDiagnosticsLayoutPolicy.resolve(
                    fontScale = resources.configuration.fontScale,
                    defaultPaddingPx = resources.getDimensionPixelSize(R.dimen.connection_diagnostics_padding),
                    largeFontPaddingPx =
                        resources.getDimensionPixelSize(R.dimen.connection_diagnostics_large_font_padding),
                    defaultTitleMarginBottomPx =
                        resources.getDimensionPixelSize(R.dimen.connection_diagnostics_title_margin_bottom),
                    largeFontTitleMarginBottomPx =
                        resources.getDimensionPixelSize(
                            R.dimen.connection_diagnostics_large_font_title_margin_bottom,
                        ),
                ),
        )
        applySubtitleDisclosure(
            resources = resources,
            subtitle = views.subtitle,
            presentation =
                ConnectionSubtitleDisclosurePolicy.resolve(
                    connectionMode = connectionMode,
                    stackedPortrait =
                        stackedContent && resources.configuration.orientation == Configuration.ORIENTATION_PORTRAIT,
                    requestedExpanded = subtitleExpanded,
                ),
        )
        applyColumn(views.header, layout.header, startGapPx = 0)
        applyColumn(views.actions, layout.actions, startGapPx = layout.columnGapPx)
        ConnectionStateAccessibilityApplier.apply(views.content)
        return layout
    }

    private fun actionsAvailableWidthPx(
        resources: Resources,
        views: Views,
        layout: ConnectionPanelLayoutPolicy.Layout,
    ): Int {
        val contentWidthPx = connectionContentWidthPx(resources, views)
        if (layout.contentOrientation == ConnectionPanelLayoutPolicy.Orientation.VERTICAL) {
            return contentWidthPx
        }
        val columnsWidthPx = (contentWidthPx - layout.columnGapPx).coerceAtLeast(0)
        val totalWeight = ConnectionPanelLayoutPolicy.HEADER_WEIGHT + ConnectionPanelLayoutPolicy.ACTIONS_WEIGHT
        return (columnsWidthPx * ConnectionPanelLayoutPolicy.ACTIONS_WEIGHT / totalWeight).roundToInt()
    }

    private fun connectionContentWidthPx(
        resources: Resources,
        views: Views,
    ): Int {
        val measuredContentWidthPx = views.content.width - views.content.paddingStart - views.content.paddingEnd
        val measuredActionsWidthPx = views.actions.width
        val measuredWidthPx = maxOf(measuredContentWidthPx, measuredActionsWidthPx).takeIf { it > 0 }
        val screenWidthPx =
            if (resources.configuration.screenWidthDp > 0) {
                dp(resources, resources.configuration.screenWidthDp.toFloat())
            } else {
                resources.displayMetrics.widthPixels
            }
        val panelWidthPx =
            (screenWidthPx - connectionPanelHorizontalMarginsPx(resources, views))
                .coerceAtLeast(0)
                .coerceAtMost(resources.getDimensionPixelSize(R.dimen.connection_panel_max_width))
        val configuredContentWidthPx =
            (panelWidthPx - resources.getDimensionPixelSize(R.dimen.connection_panel_horizontal_padding) * 2)
                .coerceAtLeast(0)
        return measuredWidthPx?.coerceAtMost(configuredContentWidthPx) ?: configuredContentWidthPx
    }

    private fun dp(
        resources: Resources,
        value: Float,
    ): Int = (value * resources.displayMetrics.density).roundToInt()

    private fun connectionPanelHorizontalMarginsPx(
        resources: Resources,
        views: Views,
    ): Int {
        val margins = views.panel.layoutParams as? ViewGroup.MarginLayoutParams
        return if (margins != null) {
            (margins.marginStart + margins.marginEnd).coerceAtLeast(0)
        } else {
            resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal) * 2
        }
    }

    private fun layoutPresentInternetSecondaryActionCount(views: Views): Int {
        val actions = requiredView(views.actions, R.id.internetSecondaryActions) as? LinearLayout ?: return 0
        return listOf(
            R.id.internetConnectionSettingsButton,
            R.id.internetDisconnectButton,
            R.id.internetRevokeButton,
        ).count { id -> requiredView(actions, id).visibility != View.GONE }
    }

    private fun applySubtitleDisclosure(
        resources: Resources,
        subtitle: TextView,
        presentation: ConnectionSubtitleDisclosurePolicy.Presentation,
    ) {
        subtitle.maxLines = presentation.maxLines
        subtitle.ellipsize = if (presentation.ellipsizeEnd) TextUtils.TruncateAt.END else null
        subtitle.isClickable = presentation.expandable
        subtitle.isFocusable = presentation.expandable
        subtitle.minimumHeight =
            if (presentation.expandable) {
                resources.getDimensionPixelSize(R.dimen.connection_subtitle_touch_target_min_height)
            } else {
                0
            }
        subtitle.compoundDrawablePadding =
            if (presentation.expandable) {
                resources.getDimensionPixelSize(R.dimen.connection_subtitle_disclosure_icon_padding)
            } else {
                0
            }
        subtitle.setCompoundDrawablesRelativeWithIntrinsicBounds(
            0,
            0,
            when {
                !presentation.expandable -> 0
                presentation.expanded -> R.drawable.ic_collapse_chevron
                else -> R.drawable.ic_dropdown_chevron
            },
            0,
        )
        ViewCompat.setStateDescription(
            subtitle,
            if (presentation.expandable) {
                resources.getString(
                    if (presentation.expanded) {
                        R.string.internet_security_details_expanded
                    } else {
                        R.string.internet_security_details_collapsed
                    },
                )
            } else {
                null
            },
        )
        if (presentation.expandable) {
            ViewCompat.replaceAccessibilityAction(
                subtitle,
                AccessibilityNodeInfoCompat.AccessibilityActionCompat.ACTION_CLICK,
                resources.getString(
                    if (presentation.expanded) {
                        R.string.internet_security_details_collapse_action
                    } else {
                        R.string.internet_security_details_expand_action
                    },
                ),
            ) { view, _ ->
                view.performClick()
            }
        } else {
            ViewCompat.removeAccessibilityAction(
                subtitle,
                AccessibilityNodeInfoCompat.AccessibilityActionCompat.ACTION_CLICK.id,
            )
        }
    }

    private fun applyConfigurationDimensions(
        resources: Resources,
        views: Views,
    ) {
        applyPanelMaximumWidth(resources, views)
        val horizontalPadding = resources.getDimensionPixelSize(R.dimen.connection_panel_horizontal_padding)
        views.content.setPaddingRelative(
            horizontalPadding,
            resources.getDimensionPixelSize(R.dimen.connection_panel_padding_top),
            horizontalPadding,
            resources.getDimensionPixelSize(R.dimen.connection_panel_padding_bottom),
        )

        val icon = requiredView(views.header, R.id.connectionIcon)
        val iconSize = resources.getDimensionPixelSize(R.dimen.connection_icon_size)
        updateLayout(icon) { params ->
            params.width = iconSize
            params.height = iconSize
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_icon_margin_bottom)
        }
        updateLayout(requiredView(views.header, R.id.connectionWordmark)) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_wordmark_margin_bottom)
        }
        updateLayout(requiredView(views.header, R.id.connectionTitle)) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_title_margin_bottom)
        }
        updateLayout(views.subtitle) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_subtitle_margin_bottom)
        }
        updateLayout(requiredView(views.header, R.id.connectionProgress)) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_progress_margin_bottom)
        }
        updateLayout(requiredView(views.actions, R.id.modeToggleGroup)) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_mode_margin_bottom)
        }
        updateLayout(requiredView(views.actions, R.id.internetRouteLabel)) { params ->
            params.topMargin = resources.getDimensionPixelSize(R.dimen.connection_section_margin)
        }
        updateLayout(requiredView(views.actions, R.id.internetRouteToggleGroup)) { params ->
            params.bottomMargin = resources.getDimensionPixelSize(R.dimen.connection_section_margin)
        }
        updateLayout(requiredView(views.actions, R.id.internetConnectButton)) { params ->
            params.topMargin = resources.getDimensionPixelSize(R.dimen.connection_primary_action_margin_top)
        }
    }

    private fun applyPanelMaximumWidth(
        resources: Resources,
        views: Views,
    ) {
        val params = views.panel.layoutParams as? ConstraintLayout.LayoutParams ?: return
        val maxWidthPx = resources.getDimensionPixelSize(R.dimen.connection_panel_max_width)
        if (params.matchConstraintMaxWidth != maxWidthPx) {
            params.matchConstraintMaxWidth = maxWidthPx
            views.panel.layoutParams = params
        }
    }

    private fun applyModeToggleLayout(
        views: Views,
        layout: ConnectionModeToggleLayoutPolicy.Layout,
    ) {
        val group = requiredView(views.actions, R.id.modeToggleGroup) as? MaterialButtonToggleGroup ?: return
        group.orientation =
            when (layout.orientation) {
                ConnectionModeToggleLayoutPolicy.Orientation.HORIZONTAL -> LinearLayout.HORIZONTAL
                ConnectionModeToggleLayoutPolicy.Orientation.VERTICAL -> LinearLayout.VERTICAL
            }
        listOf(R.id.modeUSB, R.id.modeWireless, R.id.modeInternet).forEach { id ->
            updateModeButtonLayout(requiredView(group, id), layout)
        }
    }

    private fun applyInternetProfileActionsLayout(
        views: Views,
        layout: InternetProfileActionsLayoutPolicy.Layout,
    ) {
        val actions = requiredView(views.actions, R.id.internetProfileActions) as? LinearLayout ?: return
        actions.orientation =
            when (layout.orientation) {
                InternetProfileActionsLayoutPolicy.Orientation.HORIZONTAL -> LinearLayout.HORIZONTAL
                InternetProfileActionsLayoutPolicy.Orientation.VERTICAL -> LinearLayout.VERTICAL
            }
        updateInternetProfileActionButtonLayout(
            view = requiredView(actions, R.id.internetScanProfileButton),
            layout = layout,
            marginStartPx = 0,
            marginTopPx = 0,
        )
        updateInternetProfileActionButtonLayout(
            view = requiredView(actions, R.id.internetImportProfileButton),
            layout = layout,
            marginStartPx = layout.importMarginStartPx,
            marginTopPx = layout.importMarginTopPx,
        )
    }

    private fun updateInternetProfileActionButtonLayout(
        view: View,
        layout: InternetProfileActionsLayoutPolicy.Layout,
        marginStartPx: Int,
        marginTopPx: Int,
    ) {
        val params = view.layoutParams as? LinearLayout.LayoutParams ?: return
        params.width =
            if (layout.buttonWidthMatchParent) {
                ViewGroup.LayoutParams.MATCH_PARENT
            } else {
                0
            }
        params.weight = layout.buttonWeight
        params.marginStart = marginStartPx
        params.topMargin = marginTopPx
        view.layoutParams = params
    }

    private fun applyInternetSecondaryActionsLayout(
        views: Views,
        layout: InternetSecondaryActionsLayoutPolicy.Layout,
    ) {
        val actions = requiredView(views.actions, R.id.internetSecondaryActions) as? LinearLayout ?: return
        actions.orientation =
            when (layout.orientation) {
                InternetSecondaryActionsLayoutPolicy.Orientation.HORIZONTAL -> LinearLayout.HORIZONTAL
                InternetSecondaryActionsLayoutPolicy.Orientation.VERTICAL -> LinearLayout.VERTICAL
            }
        val buttons =
            listOf(
                requiredView(actions, R.id.internetConnectionSettingsButton),
                requiredView(actions, R.id.internetDisconnectButton),
                requiredView(actions, R.id.internetRevokeButton),
            )
        var visibleButtonIndex = 0
        buttons.forEach { button ->
            val visible = button.visibility != View.GONE
            val firstVisibleButton = visible && visibleButtonIndex == 0
            if (visible) visibleButtonIndex += 1
            updateInternetSecondaryActionButtonLayout(
                view = button,
                layout = layout,
                marginStartPx = if (!visible || firstVisibleButton) 0 else layout.interButtonMarginStartPx,
                marginTopPx = if (!visible || firstVisibleButton) 0 else layout.interButtonMarginTopPx,
            )
        }
    }

    private fun updateInternetSecondaryActionButtonLayout(
        view: View,
        layout: InternetSecondaryActionsLayoutPolicy.Layout,
        marginStartPx: Int,
        marginTopPx: Int,
    ) {
        val params = view.layoutParams as? LinearLayout.LayoutParams ?: return
        params.width =
            if (layout.buttonWidthMatchParent) {
                ViewGroup.LayoutParams.MATCH_PARENT
            } else {
                0
            }
        params.weight = layout.buttonWeight
        params.marginStart = marginStartPx
        params.topMargin = marginTopPx
        view.layoutParams = params
    }

    private fun updateModeButtonLayout(
        view: View,
        layout: ConnectionModeToggleLayoutPolicy.Layout,
    ) {
        val params = view.layoutParams as? LinearLayout.LayoutParams ?: return
        params.width =
            if (layout.buttonWidthMatchParent) {
                ViewGroup.LayoutParams.MATCH_PARENT
            } else {
                0
            }
        params.weight = layout.buttonWeight
        view.layoutParams = params
    }

    private fun requiredView(
        root: View,
        id: Int,
    ): View = root.findViewById<View>(id) ?: error("Connection panel view is missing: $id")

    private fun updateLayout(
        view: View,
        update: (ViewGroup.MarginLayoutParams) -> Unit,
    ) {
        val params = view.layoutParams as? ViewGroup.MarginLayoutParams ?: return
        update(params)
        view.layoutParams = params
    }

    private fun applyDiagnosticsLayout(
        views: Views,
        layout: ConnectionDiagnosticsLayoutPolicy.Layout,
    ) {
        val container = requiredView(views.actions, R.id.connectionErrorContainer)
        container.setPaddingRelative(
            layout.paddingPx,
            layout.paddingPx,
            layout.paddingPx,
            layout.paddingPx,
        )
        updateLayout(requiredView(container, R.id.connectionErrorTitle)) { params ->
            params.bottomMargin = layout.titleMarginBottomPx
        }
    }

    private fun applyColumn(
        view: View,
        column: ConnectionPanelLayoutPolicy.Column,
        startGapPx: Int,
    ) {
        val params = view.layoutParams as? LinearLayout.LayoutParams ?: return
        params.width =
            if (column.widthMatchParent) {
                ViewGroup.LayoutParams.MATCH_PARENT
            } else {
                0
            }
        params.weight = column.weight
        params.marginStart = startGapPx
        view.layoutParams = params
    }
}

internal object ConnectionStateAccessibilityApplier {
    private val groupedStatusRegionIds =
        listOf(
            R.id.connectionErrorContainer,
            R.id.wirelessConnecting,
            R.id.internetProfileSummary,
            R.id.internetStateText,
            R.id.internetErrorText,
        )
    private val interactiveStatusRegionIds =
        listOf(
            R.id.wirelessFirstTime,
            R.id.wirelessConnected,
            R.id.wirelessPairedIdle,
            R.id.wirelessTokenMismatch,
            R.id.wirelessPermDenied,
        )

    fun apply(root: View) {
        root.findViewById<View>(R.id.connectionTitle)?.let { title ->
            ViewCompat.setAccessibilityHeading(title, true)
        }
        groupedStatusRegionIds.forEach { id ->
            root.findViewById<View>(id)?.let { region ->
                ViewCompat.setScreenReaderFocusable(region, true)
            }
        }
        interactiveStatusRegionIds.forEach { id ->
            root.findViewById<View>(id)?.let { region ->
                ViewCompat.setScreenReaderFocusable(region, false)
            }
        }
    }
}
