package dev.telemachus.display

import android.content.Context
import android.graphics.Typeface
import android.view.View
import android.widget.TextView
import androidx.core.content.ContextCompat

internal enum class ChecklistStatus {
    READY,
    NOT_READY,
    CHECKING,
}

internal object ChecklistStatusApplier {
    fun apply(
        context: Context,
        indicator: View,
        label: TextView,
        labelResource: Int,
        status: ChecklistStatus,
    ) {
        indicator.setBackgroundResource(
            when (status) {
                ChecklistStatus.READY -> R.drawable.status_indicator_green
                ChecklistStatus.NOT_READY -> R.drawable.status_indicator_red
                ChecklistStatus.CHECKING -> R.drawable.status_indicator_waiting
            },
        )
        val statusText =
            context.getString(
                when (status) {
                    ChecklistStatus.READY -> R.string.checklist_ready
                    ChecklistStatus.NOT_READY -> R.string.checklist_not_ready
                    ChecklistStatus.CHECKING -> R.string.checklist_checking
                },
            )
        val description =
            context.getString(
                R.string.checklist_item_status,
                context.getString(labelResource),
                statusText,
            )
        if (label.text.toString() != description) {
            label.text = description
        }
        label.setTextColor(
            ContextCompat.getColor(
                context,
                when (status) {
                    ChecklistStatus.NOT_READY -> R.color.warning
                    else -> R.color.on_surface_muted
                },
            ),
        )
        label.setTypeface(null, if (status == ChecklistStatus.NOT_READY) Typeface.BOLD else Typeface.NORMAL)
    }
}
