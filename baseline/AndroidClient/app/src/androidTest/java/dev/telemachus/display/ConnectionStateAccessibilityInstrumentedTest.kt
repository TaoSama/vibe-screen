package dev.telemachus.display

import android.R.attr.state_checked
import android.R.attr.state_enabled
import android.content.Context
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.graphics.Typeface
import android.util.TypedValue
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.graphics.ColorUtils
import androidx.core.view.ViewCompat
import androidx.core.view.accessibility.AccessibilityNodeInfoCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class ConnectionStateAccessibilityInstrumentedTest {
    @Test
    fun productionConnectionStatesUsePoliteLiveRegions() {
        withProductionLayout { root ->
            listOf(
                R.id.connectionTitle,
                R.id.connectionSubtitle,
                R.id.connectionErrorTitle,
                R.id.connectionErrorMessage,
                R.id.statusText,
                R.id.internetProfileSummary,
                R.id.internetStateText,
                R.id.wirelessConnecting,
                R.id.wirelessFirstTime,
                R.id.wirelessConnected,
                R.id.wirelessPairedIdle,
                R.id.wirelessTokenMismatch,
                R.id.wirelessPermDenied,
            ).forEach { id ->
                assertEquals(
                    root.resources.getResourceEntryName(id),
                    View.ACCESSIBILITY_LIVE_REGION_POLITE,
                    root.findViewById<View>(id).accessibilityLiveRegion,
                )
            }
            assertEquals(
                View.ACCESSIBILITY_LIVE_REGION_ASSERTIVE,
                root.findViewById<View>(R.id.internetErrorText).accessibilityLiveRegion,
            )
        }
    }

    @Test
    fun productionLayoutDoesNotPreRenderModeSpecificGuidance() {
        withProductionLayout { root ->
            val title = root.findViewById<TextView>(R.id.connectionTitle)
            val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
            val status = root.findViewById<TextView>(R.id.statusText)

            assertEquals("", title.text.toString())
            assertEquals("", subtitle.text.toString())
            assertEquals(root.context.getString(R.string.looking_for_mac), status.text.toString())
        }
    }

    @Test
    fun liveRegionTextOnlyChangesForNewContent() {
        withProductionLayout { root ->
            val label = root.findViewById<TextView>(R.id.statusText)
            val original = label.text

            assertFalse(LiveRegionTextApplier.apply(label, original.toString()))
            assertTrue("Equivalent content should preserve the current text instance", original === label.text)

            val replacement = "Connection failed with actionable guidance"
            assertTrue(LiveRegionTextApplier.apply(label, replacement))
            assertEquals(replacement, label.text.toString())
            assertFalse(LiveRegionTextApplier.apply(label, replacement))
        }
    }

    @Test
    fun hiddenLiveRegionMessageReannouncesTheSameErrorWhenShownAgain() {
        withProductionLayout { root ->
            val error = root.findViewById<TextView>(R.id.internetErrorText)
            val message = "Pairing expired. Import a fresh profile."

            assertTrue(LiveRegionTextApplier.show(error, message))
            assertEquals(View.VISIBLE, error.visibility)
            assertEquals(message, error.text.toString())

            assertTrue(LiveRegionTextApplier.hide(error))
            assertEquals(View.GONE, error.visibility)
            assertEquals("", error.text.toString())

            assertTrue(LiveRegionTextApplier.show(error, message))
            assertEquals(View.VISIBLE, error.visibility)
            assertEquals(message, error.text.toString())
        }
    }

    @Test
    fun connectedStatusAnnouncementUsesVisibleStreamChromeAndDeduplicates() {
        withProductionLayout { root ->
            val settingsPanel = root.findViewById<View>(R.id.settingsPanel)
            val controlBar = root.findViewById<View>(R.id.controlBar)
            settingsPanel.visibility = View.GONE
            controlBar.visibility = View.VISIBLE

            val announcements = mutableListOf<String>()
            val coordinator = ConnectionStatusAnnouncementCoordinator()
            val connected = root.context.getString(R.string.connected_streaming)
            val announce = { text: CharSequence ->
                assertEquals(View.VISIBLE, controlBar.visibility)
                announcements += text.toString()
            }

            assertTrue(coordinator.announceIfChanged(connected, announce))
            assertFalse(coordinator.announceIfChanged(connected, announce))
            assertEquals(listOf(connected), announcements)

            coordinator.reset()
            assertTrue(coordinator.announceIfChanged(connected, announce))
            assertEquals(listOf(connected, connected), announcements)
        }
    }

    @Test
    fun connectionDetailsMeetsTouchTargetAndKeepsItsFullLabel() {
        listOf(1f, 2f).forEach { fontScale ->
            val configuration = Configuration(applicationContext().resources.configuration)
            configuration.screenWidthDp = 320
            configuration.fontScale = fontScale
            val configuredContext = applicationContext().createConfigurationContext(configuration)

            withProductionLayout(configuredContext) { root ->
                val action = root.findViewById<TextView>(R.id.showAdvanced)
                listOf(R.string.connection_details, R.string.hide_connection_details).forEach { label ->
                    action.setText(label)
                    measureAndLayout(root, configuredContext, widthDp = 320, heightDp = 800)

                    assertTrue(action.measuredHeight >= dp(configuredContext, 48))
                    val textLayout = checkNotNull(action.layout)
                    assertTrue((0 until textLayout.lineCount).all { textLayout.getEllipsisCount(it) == 0 })
                    assertEquals(action.text.length, textLayout.getLineEnd(textLayout.lineCount - 1))
                    assertTrue(
                        textLayout.getLineBottom(textLayout.lineCount - 1) <=
                            action.height - action.compoundPaddingBottom,
                    )
                }
            }
        }
    }

    @Test
    fun internetSecurityDescriptionStaysFullyVisibleWithoutDisclosureActions() {
        val context = configuredContext(widthDp = 361, heightDp = 800)
        withProductionLayout(context) { root ->
            val subtitle = root.findViewById<TextView>(R.id.connectionSubtitle)
            val views = connectionPanelViews(root)
            subtitle.setText(R.string.internet_waiting_description)

            ConnectionPanelLayoutApplier.apply(
                resources = context.resources,
                views = views,
                connectionMode = ConnectionMode.INTERNET,
                subtitleExpanded = false,
            )
            measureAndLayout(root, context, widthDp = 361, heightDp = 800)
            assertEquals(
                context.getString(R.string.internet_waiting_description),
                subtitle.text.toString(),
            )
            assertFalse(subtitle.isClickable)
            assertFalse(subtitle.isFocusable)
            assertTrue(subtitle.compoundDrawablesRelative[2] == null)
            assertEquals(Int.MAX_VALUE, subtitle.maxLines)
            assertTrue(ViewCompat.getStateDescription(subtitle) == null)
            val node = AccessibilityNodeInfoCompat.obtain()
            ViewCompat.onInitializeAccessibilityNodeInfo(subtitle, node)
            assertFalse(
                node.actionList.any {
                    it.label == context.getString(R.string.internet_security_details_expand_action) ||
                        it.label == context.getString(R.string.internet_security_details_collapse_action)
                },
            )
            val textLayout = checkNotNull(subtitle.layout)
            assertTrue((0 until textLayout.lineCount).all { textLayout.getEllipsisCount(it) == 0 })

            ConnectionPanelLayoutApplier.apply(
                resources = context.resources,
                views = views,
                connectionMode = ConnectionMode.USB,
                subtitleExpanded = false,
            )
            assertEquals(0, subtitle.minimumHeight)
            assertFalse(subtitle.isClickable)
            assertFalse(subtitle.isFocusable)
            assertTrue(subtitle.compoundDrawablesRelative[2] == null)
            assertEquals(Int.MAX_VALUE, subtitle.maxLines)
        }
    }

    @Test
    fun internetSecurityDescriptionStaysVisibleAfterModeAndConfigurationChanges() {
        val context = applicationContext()
        val preferences = PreferencesManager(context)
        val originalMode = preferences.connectionMode
        preferences.connectionMode = ConnectionMode.INTERNET
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                scenario.onActivity { activity ->
                    activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                }
                InstrumentationRegistry.getInstrumentation().waitForIdleSync()
                scenario.onActivity { activity ->
                    assertEquals(
                        Configuration.ORIENTATION_PORTRAIT,
                        activity.resources.configuration.orientation,
                    )
                    val subtitle = activity.findViewById<TextView>(R.id.connectionSubtitle)
                    assertEquals(Int.MAX_VALUE, subtitle.maxLines)
                    assertFalse(subtitle.isClickable)

                    val modeToggle = activity.findViewById<MaterialButtonToggleGroup>(R.id.modeToggleGroup)
                    modeToggle.check(R.id.modeWireless)
                    modeToggle.check(R.id.modeInternet)
                    assertEquals(Int.MAX_VALUE, subtitle.maxLines)
                    assertFalse(subtitle.isClickable)

                    activity.onConfigurationChanged(Configuration(activity.resources.configuration))
                    assertEquals(Int.MAX_VALUE, subtitle.maxLines)
                    assertFalse(subtitle.isClickable)
                }
            }
        } finally {
            preferences.connectionMode = originalMode
        }
    }

    @Test
    fun productionModeToggleHasReadableCheckedAndDistinctDisabledStates() {
        withProductionLayout { root ->
            listOf(R.id.modeUSB, R.id.modeWireless, R.id.modeInternet).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                assertTrue(
                    root.resources.getResourceEntryName(id),
                    button.autoSizeMinTextSize >= sp(root.context, 12),
                )
                val checkedBackground = stateColor(button.backgroundTintList, state_enabled, state_checked)
                val checkedText = stateColor(button.textColors, state_enabled, state_checked)
                val disabledBackground = stateColor(button.backgroundTintList, -state_enabled, state_checked)
                val disabledText = stateColor(button.textColors, -state_enabled)

                assertTrue(ColorUtils.calculateContrast(checkedText, checkedBackground) >= 4.5)
                assertNotEquals(checkedBackground, disabledBackground)
                assertNotEquals(checkedText, disabledText)
            }
        }
    }

    @Test
    fun internetRouteToggleDoesNotAutosizeBelowReadableText() {
        withProductionLayout { root ->
            listOf(R.id.internetPreferDirect, R.id.internetForceRelay).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                assertTrue(
                    root.resources.getResourceEntryName(id),
                    button.autoSizeMinTextSize >= sp(root.context, 12),
                )
            }
        }
    }

    @Test
    fun productionUsbConnectVisuallyDistinguishesEnabledAndDisabledStates() {
        withProductionLayout { root ->
            val button = root.findViewById<MaterialButton>(R.id.connectButton)
            val enabledBackground = stateColor(button.backgroundTintList, state_enabled)
            val disabledBackground = stateColor(button.backgroundTintList, -state_enabled)
            val enabledText = stateColor(button.textColors, state_enabled)
            val disabledText = stateColor(button.textColors, -state_enabled)

            assertNotEquals(enabledBackground, disabledBackground)
            assertNotEquals(enabledText, disabledText)
            assertTrue(ColorUtils.calculateContrast(enabledText, enabledBackground) >= 4.5)
        }
    }

    @Test
    fun productionChecklistReportsEveryTransportLabelAndHighlightsFailures() {
        withProductionLayout { root ->
            val indicator = root.findViewById<View>(R.id.checkDeveloperMode)
            val label = root.findViewById<TextView>(R.id.textDeveloperMode)
            val context = root.context
            val labels =
                listOf(
                    R.string.developer_mode,
                    R.string.usb_debugging,
                    R.string.wireless_debugging,
                    R.string.usb_or_wireless_debugging,
                    R.string.usb_data_link,
                    R.string.wireless_debugging_connection,
                    R.string.usb_data_link_or_wireless_debugging,
                    R.string.mac_server,
                )

            labels.forEach { labelResource ->
                ChecklistStatus.entries.forEach { status ->
                    ChecklistStatusApplier.apply(context, indicator, label, labelResource, status)
                    assertEquals(
                        context.getString(
                            R.string.checklist_item_status,
                            context.getString(labelResource),
                            context.getString(
                                when (status) {
                                    ChecklistStatus.READY -> R.string.checklist_ready
                                    ChecklistStatus.NOT_READY -> R.string.checklist_not_ready
                                    ChecklistStatus.CHECKING -> R.string.checklist_checking
                                },
                            ),
                        ),
                        label.text.toString(),
                    )
                }
            }
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, label.accessibilityLiveRegion)
            assertFalse(indicator.isImportantForAccessibility)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.CHECKING,
            )
            val unchangedText = label.text
            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.CHECKING,
            )
            assertTrue("Unchanged status should not replace the live-region text", unchangedText === label.text)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.NOT_READY,
            )
            assertEquals(ContextCompat.getColor(context, R.color.warning), label.currentTextColor)
            assertEquals(Typeface.BOLD, (label.typeface?.style ?: Typeface.NORMAL) and Typeface.BOLD)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.mac_server,
                ChecklistStatus.READY,
            )
            assertEquals(ContextCompat.getColor(context, R.color.on_surface_muted), label.currentTextColor)
            assertEquals(Typeface.NORMAL, label.typeface?.style ?: Typeface.NORMAL)
        }
    }

    private fun withProductionLayout(
        context: Context = applicationContext(),
        block: (ViewGroup) -> Unit,
    ) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
            block(LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false) as ViewGroup)
        }
    }

    private fun measureAndLayout(
        root: ViewGroup,
        context: Context,
        widthDp: Int,
        heightDp: Int,
    ) {
        val widthPx = dp(context, widthDp)
        val heightPx = dp(context, heightDp)
        root.measure(
            View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(heightPx, View.MeasureSpec.EXACTLY),
        )
        root.layout(0, 0, root.measuredWidth, root.measuredHeight)
    }

    private fun configuredContext(
        widthDp: Int,
        heightDp: Int,
    ): Context {
        val configuration = Configuration(applicationContext().resources.configuration)
        configuration.screenWidthDp = widthDp
        configuration.screenHeightDp = heightDp
        configuration.smallestScreenWidthDp = minOf(widthDp, heightDp)
        configuration.orientation = Configuration.ORIENTATION_PORTRAIT
        return applicationContext().createConfigurationContext(configuration)
    }

    private fun connectionPanelViews(root: ViewGroup): ConnectionPanelLayoutApplier.Views =
        ConnectionPanelLayoutApplier.Views(
            content = root.findViewById(R.id.connectionContent),
            header = root.findViewById(R.id.connectionHeader),
            actions = root.findViewById(R.id.connectionActions),
            subtitle = root.findViewById(R.id.connectionSubtitle),
        )

    private fun assertAccessibilityAction(
        view: View,
        expectedLabel: String,
    ) {
        val actionLabels = view.createAccessibilityNodeInfo().actionList.mapNotNull { it.label?.toString() }
        assertTrue("Expected accessibility action '$expectedLabel' in $actionLabels", expectedLabel in actionLabels)
    }

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(context: Context, value: Int): Int =
        (value * context.resources.displayMetrics.density).roundToInt()

    private fun sp(context: Context, value: Int): Int =
        TypedValue
            .applyDimension(TypedValue.COMPLEX_UNIT_SP, value.toFloat(), context.resources.displayMetrics)
            .roundToInt()

    private fun stateColor(colors: android.content.res.ColorStateList?, vararg states: Int): Int {
        checkNotNull(colors)
        return colors.getColorForState(states, colors.defaultColor)
    }
}
