package dev.telemachus.display

import android.text.Layout
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.widget.LinearLayout
import com.google.android.material.button.MaterialButton
import java.lang.ref.WeakReference
import java.util.WeakHashMap
import kotlin.math.ceil
import kotlin.math.max

internal object SettingsDialogLayoutPolicy {
    fun shouldStack(
        availableWidthPx: Int,
        requiredButtonWidthsPx: List<Int>,
    ): Boolean = availableWidthPx <= 0 || requiredButtonWidthsPx.sum() > availableWidthPx
}

internal object SettingsDialogLayoutApplier {
    enum class Mode {
        HORIZONTAL,
        STACKED,
    }

    fun applyAfterNextLayout(root: View) {
        pendingLayoutListeners.remove(root)?.let { pending ->
            if (pending.observer.isAlive) {
                pending.observer.removeOnGlobalLayoutListener(pending.listener)
            }
        }
        val observer = root.viewTreeObserver
        val rootReference = WeakReference(root)
        lateinit var listener: ViewTreeObserver.OnGlobalLayoutListener
        listener =
            ViewTreeObserver.OnGlobalLayoutListener {
                val target = rootReference.get()
                if (observer.isAlive) {
                    observer.removeOnGlobalLayoutListener(listener)
                } else {
                    target?.viewTreeObserver?.removeOnGlobalLayoutListener(listener)
                }
                if (target != null && pendingLayoutListeners[target]?.listener === listener) {
                    pendingLayoutListeners.remove(target)
                    apply(target)
                }
            }
        pendingLayoutListeners[root] = PendingLayoutListener(observer, listener)
        observer.addOnGlobalLayoutListener(listener)
        root.requestLayout()
    }

    fun apply(root: View): Map<Int, Mode> =
        listOf(
            R.id.rotationGroup,
            R.id.videoQualityGroup,
            R.id.videoFrameRateGroup,
            R.id.settingsResetActions,
        ).associateWith { groupId ->
            apply(root.findViewById(groupId), groupId == R.id.settingsResetActions)
        }

    fun apply(
        group: LinearLayout,
        separateStackedButtons: Boolean = false,
    ): Mode {
        val buttons =
            (0 until group.childCount).mapNotNull { index ->
                group.getChildAt(index) as? MaterialButton
            }
        val requiredWidths = buttons.map(::requiredButtonWidth)
        val mode =
            if (SettingsDialogLayoutPolicy.shouldStack(group.width, requiredWidths)) {
                Mode.STACKED
            } else {
                Mode.HORIZONTAL
            }

        group.orientation =
            if (mode == Mode.STACKED) LinearLayout.VERTICAL else LinearLayout.HORIZONTAL
        buttons.forEach { button ->
            button.ellipsize = null
            button.maxLines = MAX_OPTION_LINES
            val params = button.layoutParams as LinearLayout.LayoutParams
            if (mode == Mode.STACKED) {
                params.width = ViewGroup.LayoutParams.MATCH_PARENT
                params.weight = 0f
            } else {
                params.width = 0
                params.weight = 1f
            }
            if (separateStackedButtons) {
                val isSecondButton = group.indexOfChild(button) > 0
                params.marginStart = if (mode == Mode.HORIZONTAL && isSecondButton) dp(button, 4f) else 0
                params.marginEnd = if (mode == Mode.HORIZONTAL && !isSecondButton) dp(button, 4f) else 0
                params.topMargin = if (mode == Mode.STACKED && isSecondButton) dp(button, 8f) else 0
            }
            button.layoutParams = params
        }
        return mode
    }

    private fun requiredButtonWidth(button: MaterialButton): Int {
        val density = button.resources.displayMetrics.density
        val minimumWidth = ceil(MINIMUM_OPTION_WIDTH_DP * density).toInt()
        val minimumHorizontalPadding = ceil(MINIMUM_HORIZONTAL_PADDING_DP * density).toInt()
        val displayedText =
            button.transformationMethod?.getTransformation(button.text, button) ?: button.text
        val textWidth = ceil(Layout.getDesiredWidth(displayedText, button.paint).toDouble()).toInt()
        val horizontalPadding =
            max(button.compoundPaddingLeft + button.compoundPaddingRight, minimumHorizontalPadding)
        return max(minimumWidth, textWidth + horizontalPadding)
    }

    private fun dp(
        view: View,
        value: Float,
    ): Int = ceil(value * view.resources.displayMetrics.density).toInt()

    private const val MINIMUM_OPTION_WIDTH_DP = 88f
    private const val MINIMUM_HORIZONTAL_PADDING_DP = 32f
    private const val MAX_OPTION_LINES = 2

    private data class PendingLayoutListener(
        val observer: ViewTreeObserver,
        val listener: ViewTreeObserver.OnGlobalLayoutListener,
    )

    private val pendingLayoutListeners = WeakHashMap<View, PendingLayoutListener>()
}
