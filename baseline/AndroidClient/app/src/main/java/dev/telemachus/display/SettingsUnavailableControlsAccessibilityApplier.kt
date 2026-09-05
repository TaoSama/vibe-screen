package dev.telemachus.display

import android.view.View
import android.view.ViewGroup
import android.widget.TextView

internal object SettingsUnavailableControlsAccessibilityApplier {
    fun apply(
        available: Boolean,
        unavailableNote: TextView,
        unavailableContent: List<View>,
    ) {
        unavailableNote.visibility = if (available) View.GONE else View.VISIBLE
        unavailableNote.isFocusable = !available
        unavailableNote.importantForAccessibility =
            if (available) {
                View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
            } else {
                View.IMPORTANT_FOR_ACCESSIBILITY_YES
            }

        unavailableContent.forEach { view ->
            view.importantForAccessibility =
                when {
                    available -> View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
                    view is ViewGroup -> View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
                    else -> View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }
        }
    }
}
