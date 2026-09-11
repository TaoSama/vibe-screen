package dev.telemachus.display

import android.widget.Button
import androidx.appcompat.app.AlertDialog
import kotlin.math.max
import kotlin.math.roundToInt

internal object DialogActionButtonLayoutApplier {
    fun apply(dialog: AlertDialog) {
        listOf(
            AlertDialog.BUTTON_NEGATIVE,
            AlertDialog.BUTTON_POSITIVE,
            AlertDialog.BUTTON_NEUTRAL,
        ).forEach { buttonId ->
            dialog.getButton(buttonId)?.applyReadableActionButtonLayout()
        }
    }

    private fun Button.applyReadableActionButtonLayout() {
        isSingleLine = false
        setHorizontallyScrolling(false)
        ellipsize = null
        maxLines = MAX_ACTION_BUTTON_LINES
        val minimumTouchTarget = dp(MINIMUM_TOUCH_TARGET_DP)
        minWidth = max(minWidth, minimumTouchTarget)
        minHeight = max(minHeight, minimumTouchTarget)
    }

    private fun Button.dp(value: Int): Int =
        (value * resources.displayMetrics.density).roundToInt()

    private const val MAX_ACTION_BUTTON_LINES = 2
    private const val MINIMUM_TOUCH_TARGET_DP = 48
}
