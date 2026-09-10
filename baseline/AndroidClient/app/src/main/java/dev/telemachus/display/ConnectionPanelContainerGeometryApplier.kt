package dev.telemachus.display

import android.content.res.Resources
import android.view.View
import androidx.constraintlayout.widget.ConstraintLayout

/** Rebinds resource-qualified geometry for the connection panel's outer container. */
internal object ConnectionPanelContainerGeometryApplier {
    fun apply(
        resources: Resources,
        panel: View,
        safeAreaInsets: SafeAreaGeometry.Insets,
    ): SafeAreaGeometry.Insets {
        val horizontalMargin = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal)
        val verticalMargin = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_vertical)
        val baseMargins =
            SafeAreaGeometry.Insets.of(
                left = horizontalMargin,
                top = verticalMargin,
                right = horizontalMargin,
                bottom = verticalMargin,
            )

        val params = panel.layoutParams as? ConstraintLayout.LayoutParams ?: return baseMargins
        val maxWidthPx = resources.getDimensionPixelSize(R.dimen.connection_panel_max_width)
        val isRtl = panel.layoutDirection == View.LAYOUT_DIRECTION_RTL
        val safeStart = if (isRtl) safeAreaInsets.right else safeAreaInsets.left
        val safeEnd = if (isRtl) safeAreaInsets.left else safeAreaInsets.right
        val startMargin = baseMargins.left + safeStart
        val topMargin = baseMargins.top + safeAreaInsets.top
        val endMargin = baseMargins.right + safeEnd
        val bottomMargin = baseMargins.bottom + safeAreaInsets.bottom
        if (params.matchConstraintMaxWidth != maxWidthPx ||
            params.marginStart != startMargin ||
            params.topMargin != topMargin ||
            params.marginEnd != endMargin ||
            params.bottomMargin != bottomMargin
        ) {
            params.matchConstraintMaxWidth = maxWidthPx
            params.marginStart = startMargin
            params.topMargin = topMargin
            params.marginEnd = endMargin
            params.bottomMargin = bottomMargin
            panel.layoutParams = params
        }
        return baseMargins
    }
}
