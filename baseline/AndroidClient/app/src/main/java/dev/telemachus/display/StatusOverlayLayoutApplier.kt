package dev.telemachus.display

import android.content.res.Resources
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout

/** Views whose layout is controlled together by [StatusOverlayLayoutApplier]. */
internal data class StatusOverlayViews(
    val card: View,
    val content: LinearLayout,
)

internal object StatusOverlayLayoutPolicy {
    data class Geometry(
        val horizontalContentPaddingPx: Int,
        val itemGapPx: Int,
        val rowGapPx: Int,
        val columnMinimumWidthPx: Int,
    )

    enum class Mode {
        SINGLE_ROW,
        STACKED,
    }

    fun mode(
        availableWidthPx: Int,
        columnCount: Int,
        geometry: Geometry,
    ): Mode {
        val contentColumns = columnCount.coerceAtLeast(1)
        val singleRowWidth =
            geometry.horizontalContentPaddingPx +
                geometry.columnMinimumWidthPx * contentColumns +
                geometry.itemGapPx * (contentColumns - 1).coerceAtLeast(0)
        return if (availableWidthPx >= singleRowWidth) {
            Mode.SINGLE_ROW
        } else {
            Mode.STACKED
        }
    }

    fun maxWidthPx(
        windowWidthPx: Int,
        safeAreaInsets: SafeAreaGeometry.Insets,
        horizontalMarginsPx: Int,
    ): Int =
        (windowWidthPx.coerceAtLeast(0) - safeAreaInsets.left - safeAreaInsets.right - horizontalMarginsPx)
            .coerceAtLeast(0)
}

/** Keeps the draggable stats overlay readable within the current safe window. */
internal object StatusOverlayLayoutApplier {
    fun geometry(resources: Resources): StatusOverlayLayoutPolicy.Geometry =
        StatusOverlayLayoutPolicy.Geometry(
            horizontalContentPaddingPx =
                resources.getDimensionPixelSize(R.dimen.status_overlay_content_padding) * 2,
            itemGapPx = resources.getDimensionPixelSize(R.dimen.status_overlay_item_gap),
            rowGapPx = resources.getDimensionPixelSize(R.dimen.status_overlay_row_gap),
            columnMinimumWidthPx = resources.getDimensionPixelSize(R.dimen.status_overlay_column_min_width),
        )

    fun apply(
        views: StatusOverlayViews,
        resources: Resources,
        windowWidthPx: Int,
        safeAreaInsets: SafeAreaGeometry.Insets,
    ): StatusOverlayLayoutPolicy.Mode {
        val geometry = geometry(resources)
        val cardMargins = views.card.layoutParams as? ViewGroup.MarginLayoutParams
        val horizontalMarginsPx = (cardMargins?.marginStart ?: 0) + (cardMargins?.marginEnd ?: 0)
        val availableWidthPx =
            StatusOverlayLayoutPolicy.maxWidthPx(
                windowWidthPx = windowWidthPx,
                safeAreaInsets = safeAreaInsets,
                horizontalMarginsPx = horizontalMarginsPx,
            )
        val visibleItems = views.content.visibleChildren()
        val mode =
            StatusOverlayLayoutPolicy.mode(
                availableWidthPx = availableWidthPx,
                columnCount = visibleItems.size,
                geometry = geometry,
            )

        val cardParams = views.card.layoutParams
        val contentParams = views.content.layoutParams
        when (mode) {
            StatusOverlayLayoutPolicy.Mode.SINGLE_ROW -> {
                cardParams.width = availableWidthPx
                contentParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                views.content.orientation = LinearLayout.HORIZONTAL
                views.content.gravity = Gravity.CENTER_VERTICAL
            }
            StatusOverlayLayoutPolicy.Mode.STACKED -> {
                cardParams.width = availableWidthPx
                contentParams.width = ViewGroup.LayoutParams.MATCH_PARENT
                views.content.orientation = LinearLayout.VERTICAL
                views.content.gravity = Gravity.CENTER_VERTICAL
            }
        }
        views.card.layoutParams = cardParams
        views.content.layoutParams = contentParams
        applyItemLayout(visibleItems, mode, geometry)
        return mode
    }

    private fun applyItemLayout(
        items: List<View>,
        mode: StatusOverlayLayoutPolicy.Mode,
        geometry: StatusOverlayLayoutPolicy.Geometry,
    ) {
        items.forEachIndexed { index, item ->
            val params = item.layoutParams as LinearLayout.LayoutParams
            item.minimumWidth = geometry.columnMinimumWidthPx
            when (mode) {
                StatusOverlayLayoutPolicy.Mode.SINGLE_ROW -> {
                    params.width = 0
                    params.weight = 1f
                    params.marginEnd = if (index < items.lastIndex) geometry.itemGapPx else 0
                    params.topMargin = 0
                }
                StatusOverlayLayoutPolicy.Mode.STACKED -> {
                    params.width = ViewGroup.LayoutParams.MATCH_PARENT
                    params.weight = 0f
                    params.marginEnd = 0
                    params.topMargin = if (index == 0) 0 else geometry.rowGapPx
                }
            }
            item.layoutParams = params
        }
    }

    private fun LinearLayout.visibleChildren(): List<View> =
        (0 until childCount).mapNotNull { index ->
            getChildAt(index).takeUnless { child -> child.visibility == View.GONE }
        }
}
