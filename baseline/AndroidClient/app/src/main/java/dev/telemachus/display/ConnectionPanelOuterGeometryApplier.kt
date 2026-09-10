package dev.telemachus.display

import android.content.res.Resources
import android.view.View
import androidx.constraintlayout.widget.ConstraintLayout

internal object ConnectionPanelOuterGeometryApplier {
    data class AppliedGeometry(val horizontalMarginsPx: Int)

    fun apply(
        resources: Resources,
        panel: View,
        baseChromeMargins: MutableMap<Int, SafeAreaGeometry.Insets>,
        safeAreaInsets: SafeAreaGeometry.Insets,
    ): AppliedGeometry {
        val params =
            panel.layoutParams as? ConstraintLayout.LayoutParams
                ?: return AppliedGeometry(
                    horizontalMarginsPx = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal) * 2,
                )
        val baseMargins = baseMargins(resources)
        val maxWidth = resources.getDimensionPixelSize(R.dimen.connection_panel_max_width)
        if (params.matchConstraintMaxWidth != maxWidth ||
            params.marginStart != baseMargins.left ||
            params.topMargin != baseMargins.top ||
            params.marginEnd != baseMargins.right ||
            params.bottomMargin != baseMargins.bottom
        ) {
            params.matchConstraintMaxWidth = maxWidth
            params.marginStart = baseMargins.left
            params.topMargin = baseMargins.top
            params.marginEnd = baseMargins.right
            params.bottomMargin = baseMargins.bottom
            panel.layoutParams = params
        }
        baseChromeMargins[panel.id] = baseMargins
        ChromeSafeAreaApplier.applyMargins(panel, baseMargins, safeAreaInsets)
        val appliedParams = panel.layoutParams as ConstraintLayout.LayoutParams
        return AppliedGeometry(
            horizontalMarginsPx = (appliedParams.marginStart + appliedParams.marginEnd).coerceAtLeast(0),
        )
    }

    private fun baseMargins(resources: Resources): SafeAreaGeometry.Insets =
        SafeAreaGeometry.Insets.of(
            left = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal),
            top = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_vertical),
            right = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_horizontal),
            bottom = resources.getDimensionPixelSize(R.dimen.connection_panel_margin_vertical),
        )
}
