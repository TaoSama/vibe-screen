package dev.telemachus.display

import android.content.res.Configuration
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
    data class Columns(
        val twoColumns: Boolean,
        val primaryWidthPx: Int,
        val controlsWidthPx: Int,
        val fullWidthPx: Int,
    )

    fun shouldStack(
        availableWidthPx: Int,
        requiredButtonWidthsPx: List<Int>,
    ): Boolean = availableWidthPx <= 0 || requiredButtonWidthsPx.sum() > availableWidthPx

    fun shouldUseTwoColumns(
        availableWidthPx: Int,
        availableHeightPx: Int,
        minimumWidthPx: Int,
    ): Boolean =
        availableWidthPx >= minimumWidthPx &&
            availableWidthPx > availableHeightPx

    fun columns(
        availableWidthPx: Int,
        availableHeightPx: Int,
        minimumWidthPx: Int,
        gapPx: Int,
    ): Columns {
        val twoColumns = shouldUseTwoColumns(availableWidthPx, availableHeightPx, minimumWidthPx)
        val width = availableWidthPx.coerceAtLeast(0)
        return if (twoColumns) {
            val columnWidth = ((width - gapPx.coerceAtLeast(0)) / 2).coerceAtLeast(0)
            Columns(
                twoColumns = true,
                primaryWidthPx = columnWidth,
                controlsWidthPx = columnWidth,
                fullWidthPx = width,
            )
        } else {
            Columns(twoColumns = false, primaryWidthPx = width, controlsWidthPx = width, fullWidthPx = width)
        }
    }
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

    fun apply(root: View): Map<Int, Mode> {
        val columns = applyAdaptiveColumns(root)
        return mapOf(
            R.id.rotationGroup to columns.primaryWidthPx,
            R.id.videoQualityGroup to columns.controlsWidthPx,
            R.id.videoFrameRateGroup to columns.controlsWidthPx,
            R.id.settingsResetActions to columns.fullWidthPx,
        ).mapValues { (groupId, availableWidthPx) ->
            val group = root.findViewById<LinearLayout>(groupId)
            apply(
                group = group,
                separateStackedButtons = groupId == R.id.settingsResetActions,
                availableWidthPx = groupAvailableWidth(group, columns.twoColumns, availableWidthPx),
            )
        }
    }

    fun applyAdaptiveColumns(root: View): SettingsDialogLayoutPolicy.Columns {
        val fallbackWidth = measuredWidth(root)
        val fallbackColumns = SettingsDialogLayoutPolicy.Columns(false, fallbackWidth, fallbackWidth, fallbackWidth)
        val container = root.findViewById<LinearLayout>(R.id.settingsAdaptiveColumns) ?: return fallbackColumns
        val primary = root.findViewById<LinearLayout>(R.id.settingsPrimaryColumn) ?: return fallbackColumns
        val controls = root.findViewById<LinearLayout>(R.id.settingsControlsColumn) ?: return fallbackColumns
        val availableWidth = measuredWidth(container)
        val availableHeight = measuredHeight(root)
        val gap = root.resources.getDimensionPixelSize(R.dimen.settings_column_gap)
        val columns =
            SettingsDialogLayoutPolicy.columns(
                availableWidthPx = availableWidth,
                availableHeightPx = availableHeight,
                minimumWidthPx = root.resources.getDimensionPixelSize(R.dimen.settings_two_column_min_width),
                gapPx = gap,
            )
        container.orientation = if (columns.twoColumns) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
        applyColumnLayout(primary, columns.twoColumns, marginStart = 0)
        applyColumnLayout(controls, columns.twoColumns, marginStart = if (columns.twoColumns) gap else 0)
        return columns
    }

    fun apply(
        group: LinearLayout,
        separateStackedButtons: Boolean = false,
        availableWidthPx: Int = group.width,
    ): Mode {
        val buttons =
            (0 until group.childCount).mapNotNull { index ->
                group.getChildAt(index) as? MaterialButton
            }
        val requiredWidths = buttons.map(::requiredButtonWidth)
        val mode =
            if (SettingsDialogLayoutPolicy.shouldStack(availableWidthPx, requiredWidths)) {
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

    private fun measuredWidth(view: View): Int =
        view.width.takeIf { it > 0 }
            ?: view.measuredWidth.takeIf { it > 0 }
            ?: view.resources.displayMetrics.widthPixels

    private fun measuredHeight(view: View): Int {
        view.height.takeIf { it > 0 }?.let { return it }
        view.measuredHeight.takeIf { it > 0 }?.let { return it }
        val metrics = view.resources.displayMetrics
        return if (view.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE) {
            minOf(metrics.widthPixels, metrics.heightPixels)
        } else {
            maxOf(metrics.widthPixels, metrics.heightPixels)
        }
    }

    private fun applyColumnLayout(
        column: LinearLayout,
        twoColumns: Boolean,
        marginStart: Int,
    ) {
        val params = column.layoutParams as LinearLayout.LayoutParams
        params.width = if (twoColumns) 0 else ViewGroup.LayoutParams.MATCH_PARENT
        params.weight = if (twoColumns) 1f else 0f
        params.marginStart = marginStart
        column.layoutParams = params
    }

    private fun groupAvailableWidth(
        group: LinearLayout,
        twoColumns: Boolean,
        columnWidthPx: Int,
    ): Int {
        if (!twoColumns) return group.width
        val parent = group.parent as? ViewGroup
        val parentHorizontalPadding = (parent?.paddingStart ?: 0) + (parent?.paddingEnd ?: 0)
        return (columnWidthPx - parentHorizontalPadding).coerceAtLeast(0)
    }

    private const val MINIMUM_OPTION_WIDTH_DP = 88f
    private const val MINIMUM_HORIZONTAL_PADDING_DP = 32f
    private const val MAX_OPTION_LINES = 2

    private data class PendingLayoutListener(
        val observer: ViewTreeObserver,
        val listener: ViewTreeObserver.OnGlobalLayoutListener,
    )

    private val pendingLayoutListeners = WeakHashMap<View, PendingLayoutListener>()
}
