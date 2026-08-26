package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.slider.Slider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class SettingsDialogLayoutInstrumentedTest {
    @Test
    fun narrowPhoneWindowsStackOptionGroupsWithoutClipping() {
        listOf(320, 360).forEach { screenWidthDp ->
            withLayout(screenWidthDp = screenWidthDp) { layout ->
                assertStackedAndReadable(layout, R.id.rotationGroup)
                assertStackedAndReadable(layout, R.id.videoQualityGroup)
                assertStackedAndReadable(layout, R.id.videoFrameRateGroup)
                assertStackedAndReadable(layout, R.id.gestureSwipeUpGroup)
                assertStackedAndReadable(layout, R.id.gestureSwipeDownGroup)
                assertReadable(layout, R.id.settingsResetActions)
            }
        }
    }

    @Test
    fun largeTextStacksOptionGroupsWithoutClipping() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    assertStackedAndReadable(layout, R.id.rotationGroup)
                    assertStackedAndReadable(layout, R.id.videoQualityGroup)
                    assertStackedAndReadable(layout, R.id.videoFrameRateGroup)
                    assertStackedAndReadable(layout, R.id.gestureSwipeUpGroup)
                    assertStackedAndReadable(layout, R.id.gestureSwipeDownGroup)
                    assertStackedAndReadable(layout, R.id.settingsResetActions)
                    assertAllTextButtonsReadable(layout)
                }
            }
        }
    }

    @Test
    fun wideWindowKeepsOptionGroupsHorizontal() {
        withLayout(screenWidthDp = 600) { layout ->
            listOf(
                R.id.rotationGroup,
                R.id.videoQualityGroup,
                R.id.videoFrameRateGroup,
                R.id.gestureSwipeUpGroup,
                R.id.gestureSwipeDownGroup,
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
    fun smallTabletPortraitAndLandscapeKeepSustainedUseStatusReadable() {
        listOf(600 to 960, 960 to 600).forEach { (widthDp, heightDp) ->
            withLayout(screenWidthDp = widthDp, screenHeightDp = heightDp) { layout ->
                assertAdaptiveColumns(layout, twoColumns = widthDp > heightDp)
                val section = layout.root.findViewById<View>(R.id.deviceHealthSection)
                val status = layout.root.findViewById<TextView>(R.id.deviceHealthStatus)
                val summary = layout.root.findViewById<TextView>(R.id.deviceHealthSummary)

                assertTrue(section.measuredWidth > 0 && section.measuredHeight > 0)
                listOf(status, summary).forEach { text ->
                    assertTrue(text.layout != null && text.layout.lineCount > 0)
                    assertTrue(
                        (0 until text.layout.lineCount).all { line -> text.layout.getEllipsisCount(line) == 0 },
                    )
                }
                assertEquals(layout.dialogHeightPx, layout.viewport.measuredHeight)
                assertEquals(layout.dialogHeightPx, layout.root.measuredHeight)
                val scrollView = layout.root.getChildAt(0) as ScrollView
                assertEquals(layout.dialogHeightPx, scrollView.measuredHeight)
                assertVerticallyOrdered(layout.root.findViewById(R.id.settingsContent))
                assertAllTextReadable(layout.root)
                assertLastItemCanScrollIntoView(layout)
            }
        }
    }

    @Test
    fun smallTabletLandscapeUsesTwoSettingsColumnsWithoutLosingActions() {
        withLayout(screenWidthDp = 960, screenHeightDp = 600) { layout ->
            assertAdaptiveColumns(layout, twoColumns = true)
            assertAllTextReadable(layout.root)
            assertLastItemCanScrollIntoView(layout)

            val closeButton = layout.root.findViewById<View>(R.id.closeButton)
            val resetActions = layout.root.findViewById<LinearLayout>(R.id.settingsResetActions)
            assertTrue(closeButton.measuredHeight >= layout.dp(48))
            assertTrue(resetActions.measuredHeight >= layout.dp(48))
            assertEquals(LinearLayout.HORIZONTAL, resetActions.orientation)
            assertTrue(
                "reset actions should keep the full dialog row width outside the two-column body",
                resetActions.measuredWidth > layout.root.findViewById<View>(R.id.settingsControlsColumn).measuredWidth,
            )
            listOf(R.id.gestureSwipeUpGroup, R.id.gestureSwipeDownGroup).forEach { groupId ->
                assertGroupInsideControlsColumn(layout, groupId)
                assertReadable(layout, groupId)
            }
        }
    }

    @Test
    fun p0110LandscapeInitialSettingsViewportShowsSustainedUseAndVideoChoices() {
        withLayout(
            screenWidthDp = 1018,
            screenHeightDp = 459,
            dialogWidthDp = 880,
            dialogHeightDp = 390,
        ) { layout ->
            renderNominalDeviceHealth(layout)
            layout.measureAndLayout()

            assertAdaptiveColumns(layout, twoColumns = true)
            assertAllTextReadable(layout.root)
            assertFullyVisibleInInitialViewport(layout, R.id.deviceHealthSection)
            assertFullyVisibleInInitialViewport(layout, R.id.videoQualityGroup)
            assertFullyVisibleInInitialViewport(layout, R.id.videoFrameRateGroup)
        }
    }

    @Test
    fun sixHundredDpLandscapeWindowUsesTwoSettingsColumns() {
        withLayout(
            screenWidthDp = 600,
            screenHeightDp = 420,
            dialogWidthDp = 600,
            dialogHeightDp = 420,
        ) { layout ->
            assertAdaptiveColumns(layout, twoColumns = true)
            listOf(R.id.gestureSwipeUpGroup, R.id.gestureSwipeDownGroup).forEach { groupId ->
                assertGroupInsideControlsColumn(layout, groupId, expectedHorizontal = false)
                assertReadable(layout, groupId)
            }
        }
    }

    @Test
    fun sixHundredDpPortraitWindowKeepsOneSettingsColumn() {
        withLayout(screenWidthDp = 600, screenHeightDp = 800) { layout ->
            assertAdaptiveColumns(layout, twoColumns = false)
            assertAllTextReadable(layout.root)
        }
    }

    @Test
    fun smallTabletPortraitKeepsSettingsSingleColumnForReadableCards() {
        withLayout(screenWidthDp = 600, screenHeightDp = 960) { layout ->
            assertAdaptiveColumns(layout, twoColumns = false)
            assertAllTextReadable(layout.root)
            assertLastItemCanScrollIntoView(layout)
        }
    }

    @Test
    fun capturesSustainedUseStatusEvidenceImages() {
        listOf("portrait" to (600 to 960), "landscape" to (960 to 600)).forEach { (name, dimensions) ->
            val (widthDp, heightDp) = dimensions
            withLayout(screenWidthDp = widthDp, screenHeightDp = heightDp) { layout ->
                renderNominalDeviceHealth(layout)
                layout.measureAndLayout()
                assertAllTextReadable(layout.root)
                val screenshot = captureRoot(layout)
                assertTrue("$name screenshot exists", screenshot.isFile)
                assertTrue("$name screenshot is non-empty", screenshot.length() > 0L)
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

    private fun renderNominalDeviceHealth(layout: MeasuredLayout) {
        val resources = layout.context.resources
        layout.root.findViewById<TextView>(R.id.deviceHealthStatus).apply {
            setText(R.string.device_health_ready)
        }
        layout.root.findViewById<TextView>(R.id.deviceHealthSummary).apply {
            text =
                resources.getString(
                    R.string.device_health_summary,
                    resources.getString(R.string.device_health_battery, 100),
                    resources.getString(R.string.device_health_charging),
                    resources.getString(R.string.device_health_power_saver_off),
                    resources.getString(R.string.device_health_thermal_nominal),
                )
        }
    }

    private fun captureRoot(layout: MeasuredLayout): File {
        assertNotNull(layout.root.background)
        val bitmap = Bitmap.createBitmap(layout.root.width, layout.root.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        layout.root.draw(canvas)
        val externalFilesDir = layout.context.getExternalFilesDir(null)
        assertNotNull("external files directory is available", externalFilesDir)
        val output = File(externalFilesDir, "phase2-readiness")
        assertTrue("phase2 readiness directory exists", output.isDirectory || output.mkdirs())
        val orientation =
            if (layout.root.width > layout.root.height) {
                "landscape"
            } else {
                "portrait"
            }
        val screenshot = File(output, "sustained-use-$orientation.png")
        FileOutputStream(screenshot).use { stream ->
            assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream))
        }
        return screenshot
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

    private fun assertAdaptiveColumns(
        layout: MeasuredLayout,
        twoColumns: Boolean,
    ) {
        val columns = layout.root.findViewById<LinearLayout>(R.id.settingsAdaptiveColumns)
        val primary = layout.root.findViewById<LinearLayout>(R.id.settingsPrimaryColumn)
        val controls = layout.root.findViewById<LinearLayout>(R.id.settingsControlsColumn)
        val primaryParams = primary.layoutParams as LinearLayout.LayoutParams
        val controlsParams = controls.layoutParams as LinearLayout.LayoutParams
        if (twoColumns) {
            assertEquals(LinearLayout.HORIZONTAL, columns.orientation)
            assertEquals(0, primaryParams.width)
            assertEquals(1f, primaryParams.weight, 0f)
            assertEquals(0, controlsParams.width)
            assertEquals(1f, controlsParams.weight, 0f)
            assertTrue(controlsParams.marginStart > 0)
            assertTrue("secondary column starts after primary", controls.left >= primary.right)
            assertTrue("columns remain in settings width", controls.right <= columns.width)
        } else {
            assertEquals(LinearLayout.VERTICAL, columns.orientation)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, primaryParams.width)
            assertEquals(0f, primaryParams.weight, 0f)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, controlsParams.width)
            assertEquals(0f, controlsParams.weight, 0f)
            assertEquals(0, controlsParams.marginStart)
            assertTrue("secondary column is below primary", controls.top >= primary.bottom)
        }
    }

    private fun assertGroupInsideControlsColumn(
        layout: MeasuredLayout,
        groupId: Int,
        expectedHorizontal: Boolean = true,
    ) {
        val controls = layout.root.findViewById<LinearLayout>(R.id.settingsControlsColumn)
        val group = layout.root.findViewById<LinearLayout>(groupId)
        if (expectedHorizontal) {
            assertEquals(LinearLayout.HORIZONTAL, group.orientation)
        }
        assertTrue("group is nested in controls column", group.hasAncestor(controls))
        assertTrue("group fits controls column width", group.measuredWidth <= controls.measuredWidth)
    }

    private fun View.hasAncestor(ancestor: View): Boolean {
        var current = parent as? View
        while (current != null) {
            if (current === ancestor) return true
            current = current.parent as? View
        }
        return false
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
        screenHeightDp: Int = 800,
        fontScale: Float = 1f,
        dialogWidthDp: Int? = null,
        dialogHeightDp: Int? = null,
        assertion: (MeasuredLayout) -> Unit,
    ) {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = screenWidthDp
        configuration.screenHeightDp = screenHeightDp
        configuration.orientation =
            if (screenWidthDp > screenHeightDp) {
                Configuration.ORIENTATION_LANDSCAPE
            } else {
                Configuration.ORIENTATION_PORTRAIT
            }
        configuration.fontScale = fontScale
        val configuredContext = applicationContext().createConfigurationContext(configuration)
        val themedContext = ContextThemeWrapper(configuredContext, R.style.AppTheme)
        val parent = FrameLayout(themedContext)
        val root =
            LayoutInflater.from(themedContext)
                .inflate(R.layout.dialog_settings, parent, false) as ViewGroup
        val dialogWidth = dialogWidthDp?.let { dp(themedContext, it) } ?: layoutWidth(themedContext, screenWidthDp)
        val dialogHeight = dialogHeightDp?.let { dp(themedContext, it) } ?: layoutHeight(themedContext, screenHeightDp)
        parent.addView(root)
        val measured = MeasuredLayout(themedContext, parent, root, dialogWidth, dialogHeight)
        measured.measureAndLayout()
        SettingsDialogLayoutApplier.apply(root)
        measured.measureAndLayout()
        assertion(measured)
    }

    private fun layoutHeight(
        context: Context,
        screenHeightDp: Int,
    ): Int {
        val ratioHeightDp = (screenHeightDp * SETTINGS_MAX_HEIGHT_RATIO).roundToInt()
        val availableHeightDp = screenHeightDp - SETTINGS_WINDOW_MARGIN_DP * 2
        return dp(context, minOf(ratioHeightDp, availableHeightDp))
    }

    private fun assertVerticallyOrdered(content: ViewGroup) {
        var previousBottom = 0
        (0 until content.childCount).forEach { index ->
            val child = content.getChildAt(index)
            if (child.visibility != View.GONE) {
                assertTrue("${child.javaClass.simpleName} at $index overlaps its predecessor", child.top >= previousBottom)
                previousBottom = child.bottom
            }
        }
    }

    private fun assertAllTextReadable(root: View) {
        fun visit(view: View) {
            if (view is TextView && view.visibility == View.VISIBLE && view.text.isNotEmpty()) {
                val textLayout = view.layout
                val label =
                    if (view.id == View.NO_ID) {
                        view.text.toString()
                    } else {
                        view.resources.getResourceEntryName(view.id)
                    }
                assertTrue("$label has text layout", textLayout != null && textLayout.lineCount > 0)
                assertTrue(
                    "$label is not ellipsized",
                    (0 until textLayout.lineCount).all { line -> textLayout.getEllipsisCount(line) == 0 },
                )
                val contentWidth = view.width - view.compoundPaddingLeft - view.compoundPaddingRight
                val maximumLineWidth = (0 until textLayout.lineCount).maxOf(textLayout::getLineWidth)
                assertTrue(
                    "$label line width $maximumLineWidth fits content width $contentWidth",
                    maximumLineWidth <= contentWidth,
                )
                assertTrue(
                    "$label fits vertically",
                    textLayout.getLineBottom(textLayout.lineCount - 1) <= view.height - view.compoundPaddingBottom,
                )
            }
            if (view is ViewGroup) {
                (0 until view.childCount).forEach { index -> visit(view.getChildAt(index)) }
            }
        }
        visit(root)
    }

    private fun assertLastItemCanScrollIntoView(layout: MeasuredLayout) {
        val scrollView = layout.root.getChildAt(0) as ScrollView
        val lastItem = layout.root.findViewById<View>(R.id.closeButton)
        scrollView.scrollTo(0, lastItem.bottom)
        val visibleTop = scrollView.scrollY
        val visibleBottom = visibleTop + scrollView.height - scrollView.paddingBottom
        assertTrue("last item top is above the viewport", lastItem.top >= visibleTop)
        assertTrue("last item bottom is below the viewport", lastItem.bottom <= visibleBottom)
    }

    private fun assertFullyVisibleInInitialViewport(
        layout: MeasuredLayout,
        viewId: Int,
    ) {
        val scrollView = layout.root.getChildAt(0) as ScrollView
        val target = layout.root.findViewById<View>(viewId)
        assertEquals("initial scroll should be at top", 0, scrollView.scrollY)
        assertTrue("target $viewId starts above the initial viewport", target.top >= scrollView.scrollY)
        assertTrue(
            "target $viewId ends below the initial viewport",
            target.bottom <= scrollView.scrollY + scrollView.height - scrollView.paddingBottom,
        )
    }

    private fun layoutWidth(
        context: Context,
        screenWidthDp: Int,
    ): Int {
        val availableWidthDp = screenWidthDp - SETTINGS_WINDOW_MARGIN_DP * 2
        return minOf(
            context.resources.getDimensionPixelSize(R.dimen.settings_dialog_max_width),
            dp(context, availableWidthDp),
        )
    }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(
        context: Context,
        value: Int,
    ): Int = (value * context.resources.displayMetrics.density).roundToInt()

    private class MeasuredLayout(
        val context: Context,
        val viewport: FrameLayout,
        val root: ViewGroup,
        private val widthPx: Int,
        val dialogHeightPx: Int,
    ) {
        val rootParams: ViewGroup.MarginLayoutParams
            get() = root.layoutParams as ViewGroup.MarginLayoutParams

        fun measureAndLayout(widthPx: Int = this.widthPx) {
            viewport.measure(
                View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(dialogHeightPx, View.MeasureSpec.EXACTLY),
            )
            viewport.layout(0, 0, viewport.measuredWidth, viewport.measuredHeight)
            root.viewTreeObserver.dispatchOnGlobalLayout()
        }

        fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
    }

    private companion object {
        const val SETTINGS_WINDOW_MARGIN_DP = 24
        const val SETTINGS_MAX_HEIGHT_RATIO = 0.85f
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
