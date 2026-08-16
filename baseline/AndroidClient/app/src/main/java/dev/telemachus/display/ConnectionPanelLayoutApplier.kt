package dev.telemachus.display

import android.content.res.Resources
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

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
        // Stacked portrait keeps the original vertical centering inside the
        // scroll viewport; the two-column landscape split must top-align the
        // header and actions so their internal content starts at the same edge.
        views.content.gravity =
            when (layout.contentOrientation) {
                ConnectionPanelLayoutPolicy.Orientation.HORIZONTAL -> Gravity.TOP
                ConnectionPanelLayoutPolicy.Orientation.VERTICAL -> Gravity.CENTER_VERTICAL
            }
        views.subtitle.maxLines = layout.subtitleMaxLines
        views.subtitle.ellipsize = null
        applyColumn(views.header, layout.header, startGapPx = 0)
        applyColumn(views.actions, layout.actions, startGapPx = layout.columnGapPx)
        return layout
    }

    private fun applyConfigurationDimensions(
        resources: Resources,
        views: Views,
    ) {
        views.content.setPaddingRelative(
            views.content.paddingStart,
            resources.getDimensionPixelSize(R.dimen.connection_panel_padding_top),
            views.content.paddingEnd,
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
