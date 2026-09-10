package dev.telemachus.display

import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Rect
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CompoundButton
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class SettingsDialogLayoutInstrumentedTest {
    @Test
    fun showStatsRowStaysReadableAndReachableOnNarrowLargeText() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    assertShowStatsRowState(layout, LinearLayout.VERTICAL)
                }
            }
        }
    }

    @Test
    fun showStatsRowKeepsHorizontalLayoutWhenContentFits() {
        withLayout(screenWidthDp = 600) { layout ->
            assertShowStatsRowState(layout, LinearLayout.HORIZONTAL)
        }
    }

    @Test
    fun showStatsRowRestoresLayoutAcrossNarrowWideReflow() {
        withLayout(screenWidthDp = 600, fontScale = 2f) { layout ->
            val sameRow = layout.root.findViewById<LinearLayout>(R.id.showStatsRow)
            val statsSwitch = layout.root.findViewById<CompoundButton>(R.id.showStatsSwitch)
            statsSwitch.isChecked = true

            assertShowStatsRowState(layout, LinearLayout.HORIZONTAL)
            val firstHorizontal = layout.captureShowStatsState()
            layout.applySettingsDialogLayoutForWidth(600)
            assertSame(sameRow, layout.root.findViewById<LinearLayout>(R.id.showStatsRow))
            assertEquals(firstHorizontal, layout.captureShowStatsState())

            listOf(320, 360).forEach { narrowWidthDp ->
                layout.applySettingsDialogLayoutForWidth(narrowWidthDp)
                assertSame(sameRow, layout.root.findViewById<LinearLayout>(R.id.showStatsRow))
                assertShowStatsRowState(layout, LinearLayout.VERTICAL)
                val firstStacked = layout.captureShowStatsState()
                layout.applySettingsDialogLayoutForWidth(narrowWidthDp)
                assertSame(sameRow, layout.root.findViewById<LinearLayout>(R.id.showStatsRow))
                assertEquals(firstStacked, layout.captureShowStatsState())

                layout.applySettingsDialogLayoutForWidth(600)
                assertSame(sameRow, layout.root.findViewById<LinearLayout>(R.id.showStatsRow))
                assertShowStatsRowState(layout, LinearLayout.HORIZONTAL)
                assertEquals(firstHorizontal, layout.captureShowStatsState())

                layout.applySettingsDialogLayoutForWidth(narrowWidthDp)
                assertSame(sameRow, layout.root.findViewById<LinearLayout>(R.id.showStatsRow))
                assertShowStatsRowState(layout, LinearLayout.VERTICAL)
                assertEquals(firstStacked, layout.captureShowStatsState())
            }
        }
    }

    @Test
    fun narrowPhoneWindowsStackOptionGroupsWithoutClipping() {
        listOf(320, 360).forEach { screenWidthDp ->
            withLayout(screenWidthDp = screenWidthDp) { layout ->
                assertReadable(layout, R.id.scaleModeGroup)
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
                    assertStackedAndReadable(layout, R.id.scaleModeGroup)
                    assertStackedAndReadable(layout, R.id.rotationGroup)
                    assertStackedAndReadable(layout, R.id.videoQualityGroup)
                    assertStackedAndReadable(layout, R.id.videoFrameRateGroup)
                    assertStackedAndReadable(layout, R.id.gestureSwipeUpGroup)
                    assertStackedAndReadable(layout, R.id.gestureSwipeDownGroup)
                    assertReadable(layout, R.id.settingsResetActions)
                    assertAllTextButtonsReadable(layout)
                }
            }
        }
    }

    @Test
    fun videoGroupsStayReadableOnNarrowLargeTextAndShortLandscape() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1f, 1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    assertVideoGroupsReadable(layout)
                    assertVerticallyOrdered(layout.root.findViewById(R.id.videoSection))
                }
            }
        }

        listOf(1f, 1.5f, 2f).forEach { fontScale ->
            withLayout(
                screenWidthDp = 640,
                screenHeightDp = 320,
                fontScale = fontScale,
                dialogWidthDp = 640,
                dialogHeightDp = 320,
            ) { layout ->
                assertAdaptiveColumns(layout, twoColumns = false)
                assertVideoGroupsReadable(layout)
                assertVerticallyOrdered(layout.root.findViewById(R.id.videoSection))
            }
        }
    }

    @Test
    fun scaleModeGroupStacksInResponsiveProductionLayoutOnNarrowLargeText() {
        withLayout(screenWidthDp = 320, fontScale = 2f) { layout ->
            val group = layout.root.findViewById<MaterialButtonToggleGroup>(R.id.scaleModeGroup)
            val modes = SettingsDialogLayoutApplier.apply(layout.root)
            layout.measureAndLayout()
            val mode = modes[R.id.scaleModeGroup]

            assertTrue("scale mode group participates in responsive layout", modes.containsKey(R.id.scaleModeGroup))
            assertEquals(SettingsDialogLayoutApplier.Mode.STACKED, mode)
            assertEquals(LinearLayout.VERTICAL, group.orientation)
            assertTrue(group.isSingleSelection)
            assertTrue(group.isSelectionRequired)
            assertEquals(layout.context.getString(R.string.display_selection_host_only), group.contentDescription)
            assertReadable(layout, R.id.scaleModeGroup)
            assertAllTextReadable(group)
        }
    }

    @Test
    fun capabilityCopyStaysReadableScrollableAndRestoresAfterResponsiveReflow() {
        listOf(320, 360).forEach { screenWidthDp ->
            withLayout(screenWidthDp = screenWidthDp, fontScale = 2f) { layout ->
                renderLongRuntimeCapabilityCopy(layout)
                layout.measureAndLayout()
                val displayCapability = layout.root.findViewById<TextView>(R.id.displayCapability)
                val inputCapability = layout.root.findViewById<TextView>(R.id.inputCapability)
                val scaleModeGroup = layout.root.findViewById<MaterialButtonToggleGroup>(R.id.scaleModeGroup)

                assertEquals(layout.context.getString(R.string.display_selection_available), displayCapability.text.toString())
                assertEquals(layout.context.getString(R.string.input_capability_touch_only), inputCapability.text.toString())
                assertEquals(displayCapability.text.toString(), scaleModeGroup.contentDescription.toString())
                assertCapabilityCopyReadableAndReachable(layout, displayCapability)
                assertCapabilityCopyReadableAndReachable(layout, inputCapability)
                assertVerticallyOrdered(layout.root.findViewById(R.id.viewportSection))

                val firstNarrowState = layout.captureCapabilityCopyState()
                layout.applySettingsDialogLayoutForWidth(600)
                renderLongRuntimeCapabilityCopy(layout)
                layout.measureAndLayout()
                assertCapabilityCopyReadableAndReachable(layout, displayCapability)
                assertCapabilityCopyReadableAndReachable(layout, inputCapability)
                val firstWideState = layout.captureCapabilityCopyState()

                layout.applySettingsDialogLayoutForWidth(screenWidthDp)
                renderLongRuntimeCapabilityCopy(layout)
                layout.measureAndLayout()
                assertEquals(firstNarrowState, layout.captureCapabilityCopyState())
                assertCapabilityCopyReadableAndReachable(layout, displayCapability)
                assertCapabilityCopyReadableAndReachable(layout, inputCapability)

                layout.applySettingsDialogLayoutForWidth(600)
                renderLongRuntimeCapabilityCopy(layout)
                layout.measureAndLayout()
                assertEquals(firstWideState, layout.captureCapabilityCopyState())
            }
        }
    }

    @Test
    fun wideWindowKeepsOptionGroupsHorizontal() {
        withLayout(screenWidthDp = 600) { layout ->
            listOf(
                R.id.scaleModeGroup,
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
            assertGroupInsidePrimaryColumn(layout, R.id.scaleModeGroup)
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
    fun transferReadinessUsesSinglePoliteLiveRegion() {
        withLayout(screenWidthDp = 360) { layout ->
            val status = layout.root.findViewById<View>(R.id.transferReadinessStatus)
            val summary = layout.root.findViewById<View>(R.id.transferReadinessSummary)

            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, status.accessibilityLiveRegion)
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_NONE, summary.accessibilityLiveRegion)
        }
    }

    @Test
    fun audioReadinessCardStaysReadableAndUsesSinglePoliteLiveRegion() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1f, 1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    val section = layout.root.findViewById<View>(R.id.audioReadinessSection)
                    val status = layout.root.findViewById<View>(R.id.audioReadinessStatus)
                    val summary = layout.root.findViewById<View>(R.id.audioReadinessSummary)
                    val counters = layout.root.findViewById<View>(R.id.audioReadinessCounters)

                    assertTrue(section.measuredWidth > 0 && section.measuredHeight > 0)
                    assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, status.accessibilityLiveRegion)
                    assertEquals(View.ACCESSIBILITY_LIVE_REGION_NONE, summary.accessibilityLiveRegion)
                    assertEquals(View.ACCESSIBILITY_LIVE_REGION_NONE, counters.accessibilityLiveRegion)
                    assertAllTextReadable(section)
                }
            }
        }
    }

    @Test
    fun videoBitrateSliderKeepsVisibleLabelSemanticsOnNarrowLargeText() {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1.5f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale) { layout ->
                    val section = layout.root.findViewById<View>(R.id.videoSection)
                    val label = layout.root.findViewById<TextView>(R.id.videoBitrateLabel)
                    val value = layout.root.findViewById<TextView>(R.id.videoBitrateValue)
                    val slider = layout.root.findViewById<Slider>(R.id.videoBitrateSlider)
                    value.text = layout.context.getString(R.string.video_bitrate_value, 100)
                    layout.measureAndLayout()

                    assertEquals(slider.id, label.labelFor)
                    assertTrue(label.isAccessibilityHeading)
                    assertNull(slider.contentDescription)
                    assertEquals(layout.context.getString(R.string.video_bitrate_label), label.text.toString())
                    assertTrue(slider.measuredWidth >= layout.dp(48))
                    assertTrue(slider.measuredHeight >= layout.dp(48))
                    assertAllTextReadable(section)
                    assertFullyReachableByScroll(layout, label)
                    assertFullyReachableByScroll(layout, value)
                    assertFullyReachableByScroll(layout, slider)
                    assertVerticallyOrdered(section as ViewGroup)
                }
            }
        }
    }

    @Test
    fun unavailableVideoControlsExposeNoteInsteadOfDeadControls() {
        unavailableNoteLayouts { layout ->
            val note = layout.root.findViewById<TextView>(R.id.videoControlUnavailable)
            val controls =
                listOf(
                    layout.root.findViewById<View>(R.id.videoQualityLabel),
                    layout.root.findViewById<View>(R.id.videoQualityGroup),
                    layout.root.findViewById<View>(R.id.videoFrameRateLabel),
                    layout.root.findViewById<View>(R.id.videoFrameRateGroup),
                    layout.root.findViewById<View>(R.id.videoBitrateLabel),
                    layout.root.findViewById<View>(R.id.videoBitrateValue),
                    layout.root.findViewById<View>(R.id.videoBitrateSlider),
                )

            SettingsUnavailableControlsAccessibilityApplier.apply(
                available = false,
                unavailableNote = note,
                unavailableContent = controls,
            )

            assertUnavailableNoteOwnsAccessibility(note)
            assertUnavailableNoteTouchTarget(layout, note)
            controls.forEach(::assertUnavailableControlHiddenFromAccessibility)

            SettingsUnavailableControlsAccessibilityApplier.apply(
                available = true,
                unavailableNote = note,
                unavailableContent = controls,
            )

            assertAvailableControlsRestoreDefaultAccessibility(note, controls)
        }
    }

    @Test
    fun unavailableGestureShortcutControlsExposeNoteInsteadOfDeadControls() {
        unavailableNoteLayouts { layout ->
            val note = layout.root.findViewById<TextView>(R.id.gestureShortcutUnavailable)
            val description = layout.root.findViewById<TextView>(R.id.gestureShortcutsDescription)
            val swipeUpLabel = layout.root.findViewById<TextView>(R.id.gestureSwipeUpLabel)
            val swipeDownLabel = layout.root.findViewById<TextView>(R.id.gestureSwipeDownLabel)
            val controls =
                listOf(
                    description,
                    swipeUpLabel,
                    layout.root.findViewById<View>(R.id.gestureSwipeUpGroup),
                    swipeDownLabel,
                    layout.root.findViewById<View>(R.id.gestureSwipeDownGroup),
                )
            assertEquals(layout.context.getString(R.string.gesture_shortcuts_description), description.text.toString())
            assertEquals(layout.context.getString(R.string.gesture_swipe_up_label), swipeUpLabel.text.toString())
            assertEquals(layout.context.getString(R.string.gesture_swipe_down_label), swipeDownLabel.text.toString())

            SettingsUnavailableControlsAccessibilityApplier.apply(
                available = false,
                unavailableNote = note,
                unavailableContent = controls,
            )

            assertUnavailableNoteOwnsAccessibility(note)
            assertUnavailableNoteTouchTarget(layout, note)
            controls.forEach(::assertUnavailableControlHiddenFromAccessibility)

            SettingsUnavailableControlsAccessibilityApplier.apply(
                available = true,
                unavailableNote = note,
                unavailableContent = controls,
            )

            assertAvailableControlsRestoreDefaultAccessibility(note, controls)
        }
    }

    private fun unavailableNoteLayouts(assertion: (MeasuredLayout) -> Unit) {
        listOf(320, 360).forEach { screenWidthDp ->
            listOf(1f, 2f).forEach { fontScale ->
                withLayout(screenWidthDp = screenWidthDp, fontScale = fontScale, assertion = assertion)
            }
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
    fun opacitySliderKeepsAccessibilityContract() {
        withLayout(screenWidthDp = 320) { layout ->
            val label = layout.root.findViewById<TextView>(R.id.opacityLabel)
            val slider = layout.root.findViewById<Slider>(R.id.opacitySlider)
            assertEquals(slider.id, label.labelFor)
            assertTrue(label.isAccessibilityHeading)
            assertEquals(0, layout.rootParams.leftMargin)
            assertEquals(0, layout.rootParams.rightMargin)
            assertEquals(0, layout.rootParams.topMargin)
            assertEquals(0, layout.rootParams.bottomMargin)
        }
    }

    @Test
    fun settingsSectionsExposeScreenReaderHeadings() {
        withLayout(screenWidthDp = 360) { layout ->
            listOf(
                R.id.settingsDialogTitle,
                R.id.deviceHealthTitle,
                R.id.transferReadinessTitle,
                R.id.audioReadinessTitle,
                R.id.viewportTitle,
                R.id.videoSectionTitle,
                R.id.gestureShortcutsTitle,
                R.id.opacityLabel,
            ).forEach { viewId ->
                val heading = layout.root.findViewById<TextView>(viewId)
                assertTrue(
                    "${heading.resources.getResourceEntryName(viewId)} is an accessibility heading",
                    heading.isAccessibilityHeading,
                )
            }
        }
    }

    @Test
    fun repeatedResponsiveLayoutPreservesToggleSelectionAndSemantics() {
        withLayout(screenWidthDp = 600) { layout ->
            assertResponsiveLayoutPreservesToggleSelection(
                layout = layout,
                groupId = R.id.videoQualityGroup,
                selectedButtonId = R.id.videoQualityBalanced,
                narrowWidthPx = layout.dp(320),
                expectedNarrowOrientation = LinearLayout.VERTICAL,
                requireReadableControls = true,
            )
            assertResponsiveLayoutPreservesToggleSelection(
                layout = layout,
                groupId = R.id.videoFrameRateGroup,
                selectedButtonId = R.id.videoFps120,
                narrowWidthPx = layout.dp(320),
                expectedNarrowOrientation = LinearLayout.VERTICAL,
                requireReadableControls = true,
            )
            assertResponsiveLayoutPreservesToggleSelection(
                layout = layout,
                groupId = R.id.scaleModeGroup,
                selectedButtonId = R.id.scaleFillButton,
                narrowWidthPx = layout.dp(120),
                expectedNarrowOrientation = LinearLayout.VERTICAL,
            )
        }
    }

    private fun assertResponsiveLayoutPreservesToggleSelection(
        layout: MeasuredLayout,
        groupId: Int,
        selectedButtonId: Int,
        narrowWidthPx: Int,
        expectedNarrowOrientation: Int,
        requireReadableControls: Boolean = false,
    ) {
        val group = layout.root.findViewById<MaterialButtonToggleGroup>(groupId)
        group.check(selectedButtonId)
        var listenerCalls = 0
        group.addOnButtonCheckedListener { _, _, _ -> listenerCalls += 1 }

        layout.applySettingsDialogLayoutForExactWidth(narrowWidthPx)
        assertEquals(expectedNarrowOrientation, group.orientation)
        if (requireReadableControls) {
            assertReadable(layout, groupId)
            assertNoSubstantialButtonOverlap(layout, group)
        }
        layout.applySettingsDialogLayoutForExactWidth(layout.dp(600))
        assertEquals(LinearLayout.HORIZONTAL, group.orientation)
        if (requireReadableControls) {
            assertReadable(layout, groupId)
            assertNoSubstantialButtonOverlap(layout, group)
        }

        assertEquals(selectedButtonId, group.checkedButtonId)
        assertEquals(1, group.checkedButtonIds.size)
        assertTrue(group.isSingleSelection)
        assertTrue(group.isSelectionRequired)
        assertEquals(0, listenerCalls)
    }

    private fun assertUnavailableNoteOwnsAccessibility(note: TextView) {
        assertEquals(View.VISIBLE, note.visibility)
        assertTrue(note.isFocusable)
        assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_YES, note.importantForAccessibility)
        assertEquals(null, note.contentDescription)
        assertNotNull(note.background)
    }

    private fun assertUnavailableNoteTouchTarget(
        layout: MeasuredLayout,
        note: TextView,
    ) {
        layout.measureAndLayout()
        assertTrue(note.measuredWidth > 0)
        assertTrue(note.measuredHeight >= layout.dp(48))
        assertAllTextReadable(note)
    }

    private fun assertAvailableControlsRestoreDefaultAccessibility(
        note: TextView,
        controls: List<View>,
    ) {
        assertEquals(View.GONE, note.visibility)
        assertFalse(note.isFocusable)
        assertEquals(null, note.contentDescription)
        assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO, note.importantForAccessibility)
        assertNotNull(note.background)
        controls.forEach { control ->
            assertEquals(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO, control.importantForAccessibility)
        }
    }

    private fun assertUnavailableControlHiddenFromAccessibility(control: View) {
        val expectedImportance =
            if (control is ViewGroup) {
                View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
            } else {
                View.IMPORTANT_FOR_ACCESSIBILITY_NO
            }
        assertEquals(expectedImportance, control.importantForAccessibility)
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

    private fun renderLongRuntimeCapabilityCopy(layout: MeasuredLayout) {
        val displayCapability = layout.root.findViewById<TextView>(R.id.displayCapability)
        val inputCapability = layout.root.findViewById<TextView>(R.id.inputCapability)
        val scaleModeGroup = layout.root.findViewById<MaterialButtonToggleGroup>(R.id.scaleModeGroup)
        displayCapability.setText(R.string.display_selection_available)
        inputCapability.setText(R.string.input_capability_touch_only)
        scaleModeGroup.contentDescription = displayCapability.text
    }

    private fun assertCapabilityCopyReadableAndReachable(
        layout: MeasuredLayout,
        textView: TextView,
    ) {
        assertTrue("${textView.resources.getResourceEntryName(textView.id)} is selectable", textView.isTextSelectable)
        assertAllTextReadable(textView)
        assertFullyReachableByScroll(layout, textView)
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

    private fun assertGroupInsidePrimaryColumn(
        layout: MeasuredLayout,
        groupId: Int,
    ) {
        val primary = layout.root.findViewById<LinearLayout>(R.id.settingsPrimaryColumn)
        val group = layout.root.findViewById<LinearLayout>(groupId)
        assertTrue("group is nested in primary column", group.hasAncestor(primary))
        assertTrue("group fits primary column width", group.measuredWidth <= primary.measuredWidth)
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

    private fun assertVideoGroupsReadable(layout: MeasuredLayout) {
        listOf(R.id.videoQualityGroup, R.id.videoFrameRateGroup).forEach { groupId ->
            val group = layout.root.findViewById<LinearLayout>(groupId)
            assertReadable(layout, groupId)
            assertNoSubstantialButtonOverlap(layout, group)
            (0 until group.childCount).forEach { index ->
                assertFullyReachableByScroll(layout, group.getChildAt(index))
            }
        }
    }

    private fun assertNoSubstantialButtonOverlap(
        layout: MeasuredLayout,
        group: LinearLayout,
    ) {
        val toleratedStrokeOverlap = layout.dp(2)
        var previous: View? = null
        (0 until group.childCount).forEach { index ->
            val current = group.getChildAt(index)
            val prior = previous
            if (prior != null) {
                if (group.orientation == LinearLayout.VERTICAL) {
                    assertTrue(
                        "${prior.resources.getResourceEntryName(prior.id)} overlaps ${current.resources.getResourceEntryName(current.id)} vertically",
                        current.top >= prior.bottom - toleratedStrokeOverlap,
                    )
                } else {
                    assertTrue(
                        "${prior.resources.getResourceEntryName(prior.id)} overlaps ${current.resources.getResourceEntryName(current.id)} horizontally",
                        current.left >= prior.right - toleratedStrokeOverlap,
                    )
                }
            }
            previous = current
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

    private fun assertShowStatsRowState(
        layout: MeasuredLayout,
        expectedOrientation: Int,
    ) {
        val row = layout.root.findViewById<LinearLayout>(R.id.showStatsRow)
        val textGroup = layout.root.findViewById<LinearLayout>(R.id.showStatsTextGroup)
        val title = layout.root.findViewById<TextView>(R.id.showStatsTitle)
        val description = layout.root.findViewById<TextView>(R.id.showStatsDescription)
        val statsSwitch = layout.root.findViewById<CompoundButton>(R.id.showStatsSwitch)
        val textParams = textGroup.layoutParams as LinearLayout.LayoutParams
        val switchParams = statsSwitch.layoutParams as LinearLayout.LayoutParams

        assertEquals(expectedOrientation, row.orientation)
        assertEquals(statsSwitch.id, title.labelFor)
        assertEquals(layout.context.getString(R.string.stats_description), description.text.toString())
        assertNull(row.contentDescription)
        assertNull(textGroup.contentDescription)
        assertNull(title.contentDescription)
        assertNull(description.contentDescription)
        assertNull(statsSwitch.contentDescription)
        assertTrue("show stats switch width", statsSwitch.measuredWidth >= layout.dp(48))
        assertTrue("show stats switch height", statsSwitch.measuredHeight >= layout.dp(48))
        assertAllTextReadable(row)
        assertNoOverlapInShowStatsRow(row, textGroup, statsSwitch)
        assertFullyReachableByScroll(layout, row)

        if (expectedOrientation == LinearLayout.VERTICAL) {
            assertEquals(Gravity.START or Gravity.TOP, row.gravity)
            assertEquals(ViewGroup.LayoutParams.MATCH_PARENT, textParams.width)
            assertEquals(0f, textParams.weight, 0f)
            assertEquals(0, switchParams.marginStart)
            assertEquals(layout.context.resources.getDimensionPixelSize(R.dimen.settings_show_stats_switch_gap), switchParams.topMargin)
            assertEquals(Gravity.END, switchParams.gravity)
        } else {
            assertEquals(Gravity.START or Gravity.CENTER_VERTICAL, row.gravity)
            assertEquals(0, textParams.width)
            assertEquals(1f, textParams.weight, 0f)
            assertEquals(layout.context.resources.getDimensionPixelSize(R.dimen.settings_show_stats_switch_gap), switchParams.marginStart)
            assertEquals(0, switchParams.topMargin)
            assertEquals(Gravity.NO_GRAVITY, switchParams.gravity)
            assertTrue("horizontal show stats text and switch fit row width", textGroup.right <= statsSwitch.left)
            assertTrue("horizontal show stats switch stays inside row", statsSwitch.right <= row.width - row.paddingEnd)
        }
    }

    private fun MeasuredLayout.captureShowStatsState(): ShowStatsRowState {
        val row = root.findViewById<LinearLayout>(R.id.showStatsRow)
        val textGroup = root.findViewById<LinearLayout>(R.id.showStatsTextGroup)
        val statsSwitch = root.findViewById<CompoundButton>(R.id.showStatsSwitch)
        val textParams = textGroup.layoutParams as LinearLayout.LayoutParams
        val switchParams = statsSwitch.layoutParams as LinearLayout.LayoutParams
        return ShowStatsRowState(
            rowOrientation = row.orientation,
            rowGravity = row.gravity,
            textWidth = textParams.width,
            textWeight = textParams.weight,
            switchMarginStart = switchParams.marginStart,
            switchTopMargin = switchParams.topMargin,
            switchGravity = switchParams.gravity,
            switchChecked = statsSwitch.isChecked,
        )
    }

    private fun MeasuredLayout.captureCapabilityCopyState(): CapabilityCopyState {
        val displayCapability = root.findViewById<TextView>(R.id.displayCapability)
        val inputCapability = root.findViewById<TextView>(R.id.inputCapability)
        val scaleModeGroup = root.findViewById<MaterialButtonToggleGroup>(R.id.scaleModeGroup)
        return CapabilityCopyState(
            displayLineCount = requireNotNull(displayCapability.layout).lineCount,
            displayWidth = displayCapability.measuredWidth,
            displayHeight = displayCapability.measuredHeight,
            inputLineCount = requireNotNull(inputCapability.layout).lineCount,
            inputWidth = inputCapability.measuredWidth,
            inputHeight = inputCapability.measuredHeight,
            scaleModeDescription = scaleModeGroup.contentDescription.toString(),
        )
    }

    private fun MeasuredLayout.applySettingsDialogLayoutForWidth(widthDp: Int) {
        applySettingsDialogLayoutForExactWidth(dp(widthDp))
    }

    private fun MeasuredLayout.applySettingsDialogLayoutForExactWidth(widthPx: Int) {
        measureAndLayout(widthPx)
        SettingsDialogLayoutApplier.apply(root)
        measureAndLayout(widthPx)
    }

    private fun assertFullyReachableByScroll(
        layout: MeasuredLayout,
        target: View,
    ) {
        val scrollView = layout.root.getChildAt(0) as ScrollView
        val targetBounds = Rect(0, 0, target.width, target.height)
        val content = scrollView.getChildAt(0) as ViewGroup
        content.offsetDescendantRectToMyCoords(target, targetBounds)
        scrollView.scrollTo(0, targetBounds.top)
        val visibleTop = scrollView.scrollY
        val visibleBottom = visibleTop + scrollView.height - scrollView.paddingBottom
        assertTrue("target top is above the viewport", targetBounds.top >= visibleTop)
        assertTrue("target bottom is below the viewport", targetBounds.bottom <= visibleBottom)
    }

    private fun assertNoOverlapInShowStatsRow(
        row: LinearLayout,
        textGroup: View,
        statsSwitch: View,
    ) {
        val textBounds = Rect(textGroup.left, textGroup.top, textGroup.right, textGroup.bottom)
        val switchBounds = Rect(statsSwitch.left, statsSwitch.top, statsSwitch.right, statsSwitch.bottom)
        assertFalse(
            "show stats text and switch overlap in ${if (row.orientation == LinearLayout.VERTICAL) "stacked" else "horizontal"} layout",
            Rect.intersects(textBounds, switchBounds),
        )
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

    private data class ShowStatsRowState(
        val rowOrientation: Int,
        val rowGravity: Int,
        val textWidth: Int,
        val textWeight: Float,
        val switchMarginStart: Int,
        val switchTopMargin: Int,
        val switchGravity: Int,
        val switchChecked: Boolean,
    )

    private data class CapabilityCopyState(
        val displayLineCount: Int,
        val displayWidth: Int,
        val displayHeight: Int,
        val inputLineCount: Int,
        val inputWidth: Int,
        val inputHeight: Int,
        val scaleModeDescription: String,
    )

    private companion object {
        const val SETTINGS_WINDOW_MARGIN_DP = 24
        const val SETTINGS_MAX_HEIGHT_RATIO = 0.85f
    }
}
