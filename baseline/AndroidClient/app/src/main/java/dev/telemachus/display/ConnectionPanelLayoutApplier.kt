package dev.telemachus.display

import android.content.res.Resources
import android.content.res.Configuration
import android.text.TextUtils
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import com.google.android.material.button.MaterialButtonToggleGroup

internal object ConnectionPanelLayoutApplier {
    data class Views(
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
        applyModeToggleLayout(
            views = views,
            layout =
                ConnectionModeToggleLayoutPolicy.resolve(
                    stackedContent = stackedContent,
                    fontScale = resources.configuration.fontScale,
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
