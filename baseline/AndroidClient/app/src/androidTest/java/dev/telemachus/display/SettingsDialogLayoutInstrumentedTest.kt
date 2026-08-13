package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.slider.Slider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class SettingsDialogLayoutInstrumentedTest {
    @Test
    fun narrowPhoneWindowsStackFourOptionGroupsWithoutClipping() {
        listOf(320, 360).forEach { screenWidthDp ->
            withLayout(screenWidthDp = screenWidthDp) { layout ->
                assertStackedAndReadable(layout, R.id.rotationGroup)
                assertStackedAndReadable(layout, R.id.videoQualityGroup)
                assertStackedAndReadable(layout, R.id.videoFrameRateGroup)
                assertReadable(layout, R.id.settingsResetActions)
            }
        }
    }

    @Test
    fun largeTextStacksFourOptionGroupsWithoutClipping() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    assertStackedAndReadable(layout, R.id.rotationGroup)
                    assertStackedAndReadable(layout, R.id.videoQualityGroup)
                    assertStackedAndReadable(layout, R.id.videoFrameRateGroup)
                    assertStackedAndReadable(layout, R.id.settingsResetActions)
                    assertAllTextButtonsReadable(layout)
                }
            }
        }
    }

    @Test
    fun wideWindowKeepsFourOptionGroupsHorizontal() {
        withLayout(screenWidthDp = 600) { layout ->
            listOf(
                R.id.rotationGroup,
                R.id.videoQualityGroup,
                R.id.videoFrameRateGroup,
                R.id.settingsResetActions,
            ).forEach { groupId ->
                val group = layout.root.findViewById<LinearLayout>(groupId)
                assertEquals(LinearLayout.HORIZONTAL, group.orientation)
                assertTrue((0 until group.childCount).all { index ->
                    val params = group.getChildAt(index).layoutParams as LinearLayout.LayoutParams
                    params.width == 0 && params.weight == 1f
                })
            }
        }
    }

    @Test
    fun positionTargetsAndOpacitySliderMeetAccessibilityContract() {
        withLayout(screenWidthDp = 320) { layout ->
            val minimumTarget = layout.dp(48)
            POSITION_BUTTON_IDS.forEach { buttonId ->
                assertTrue(layout.root.findViewById<View>(buttonId).measuredHeight >= minimumTarget)
            }
            val label = layout.root.findViewById<TextView>(R.id.opacityLabel)
            val slider = layout.root.findViewById<Slider>(R.id.opacitySlider)
            assertEquals(slider.id, label.labelFor)
            assertEquals(0, layout.rootParams.leftMargin)
            assertEquals(0, layout.rootParams.rightMargin)
            assertEquals(0, layout.rootParams.topMargin)
            assertEquals(0, layout.rootParams.bottomMargin)
        }
    }

    @Test
    fun repeatedResponsiveLayoutPreservesToggleSelectionAndSemantics() {
        withLayout(screenWidthDp = 600) { layout ->
            val group = layout.root.findViewById<MaterialButtonToggleGroup>(R.id.videoQualityGroup)
            group.check(R.id.videoQualityBalanced)
            var listenerCalls = 0
            group.addOnButtonCheckedListener { _, _, _ -> listenerCalls += 1 }

            SettingsDialogLayoutApplier.applyAfterNextLayout(layout.root)
            layout.measureAndLayout(layout.dp(320))
            assertEquals(LinearLayout.VERTICAL, group.orientation)
            SettingsDialogLayoutApplier.applyAfterNextLayout(layout.root)
            layout.measureAndLayout(layout.dp(600))
            assertEquals(LinearLayout.HORIZONTAL, group.orientation)

            assertEquals(R.id.videoQualityBalanced, group.checkedButtonId)
            assertEquals(1, group.checkedButtonIds.size)
            assertTrue(group.isSingleSelection)
            assertTrue(group.isSelectionRequired)
            assertEquals(0, listenerCalls)
        }
    }

    private fun assertAllTextButtonsReadable(layout: MeasuredLayout) {
        fun visit(view: View) {
            if (view is MaterialButton && view.text.isNotEmpty()) {
                assertButtonReadable(layout, view)
            }
            if (view is ViewGroup) {
                (0 until view.childCount).forEach { index -> visit(view.getChildAt(index)) }
            }
        }
        visit(layout.root)
    }

    private fun assertStackedAndReadable(
        layout: MeasuredLayout,
        groupId: Int,
    ) {
        val group = layout.root.findViewById<LinearLayout>(groupId)
        assertEquals(LinearLayout.VERTICAL, group.orientation)
        assertReadable(layout, groupId)
    }

    private fun assertReadable(
        layout: MeasuredLayout,
        groupId: Int,
    ) {
        val group = layout.root.findViewById<LinearLayout>(groupId)
        (0 until group.childCount).forEach { index ->
            val button = group.getChildAt(index) as MaterialButton
            val params = button.layoutParams as LinearLayout.LayoutParams
            if (group.orientation == LinearLayout.VERTICAL) {
                assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, params.width)
                assertEquals(0f, params.weight, 0f)
            }
            assertButtonReadable(layout, button)
        }
    }

    private fun assertButtonReadable(
        layout: MeasuredLayout,
        button: MaterialButton,
    ) {
        val label = "${button.resources.getResourceEntryName(button.id)} (${button.text})"
        assertTrue("$label width", button.measuredWidth >= layout.dp(48))
        assertTrue("$label height", button.measuredHeight >= layout.dp(48))
        val textLayout = button.layout
        assertTrue("$label has text layout", textLayout != null && textLayout.lineCount > 0)
        assertTrue(
            "$label is not ellipsized",
            (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
        )
        val contentWidth = button.width - button.compoundPaddingLeft - button.compoundPaddingRight
        val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
        assertTrue(
            "$label line width $maximumLineWidth fits content width $contentWidth",
            maximumLineWidth <= contentWidth,
        )
        assertTrue(
            "$label line fits height",
            textLayout.getLineBottom(textLayout.lineCount - 1) <= button.height - button.compoundPaddingBottom,
        )
    }

    private fun withLayout(
        screenWidthDp: Int,
        fontScale: Float = 1f,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = screenWidthDp
        configuration.fontScale = fontScale
        val configuredContext = applicationContext().createConfigurationContext(configuration)
        val themedContext = ContextThemeWrapper(configuredContext, R.style.AppTheme)
        val parent = FrameLayout(themedContext)
        val root =
            LayoutInflater.from(themedContext)
                .inflate(R.layout.dialog_settings, parent, false) as ViewGroup
        val dialogWidth = layoutWidth(themedContext, screenWidthDp)
        val measured = MeasuredLayout(themedContext, root, dialogWidth)
        measured.measureAndLayout()
        SettingsDialogLayoutApplier.apply(root)
        measured.measureAndLayout()
        assertion(measured)
    }

    private fun layoutWidth(
        context: Context,
        screenWidthDp: Int,
    ): Int {
        val availableWidthDp = screenWidthDp - SETTINGS_WINDOW_MARGIN_DP * 2
        return dp(context, minOf(SETTINGS_MAX_WIDTH_DP, availableWidthDp))
    }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(
        context: Context,
        value: Int,
    ): Int = (value * context.resources.displayMetrics.density).roundToInt()

    private class MeasuredLayout(
        val context: Context,
        val root: ViewGroup,
        private val widthPx: Int,
    ) {
        val rootParams: ViewGroup.MarginLayoutParams
            get() = root.layoutParams as ViewGroup.MarginLayoutParams

        fun measureAndLayout(widthPx: Int = this.widthPx) {
            root.measure(
                View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dp(4000), View.MeasureSpec.AT_MOST),
            )
            root.layout(0, 0, root.measuredWidth, root.measuredHeight)
            root.viewTreeObserver.dispatchOnGlobalLayout()
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private companion object {
        const val SETTINGS_WINDOW_MARGIN_DP = 24
        const val SETTINGS_MAX_WIDTH_DP = 680
        val POSITION_BUTTON_IDS =
            listOf(
                R.id.cornerTopLeft,
                R.id.positionTopCenter,
                R.id.cornerTopRight,
                R.id.positionCenterLeft,
                R.id.positionCenterRight,
                R.id.cornerBottomLeft,
                R.id.positionBottomCenter,
                R.id.cornerBottomRight,
            )
    }
}
