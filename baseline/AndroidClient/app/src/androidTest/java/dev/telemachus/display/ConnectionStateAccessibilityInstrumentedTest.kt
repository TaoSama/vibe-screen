package dev.telemachus.display

import android.R.attr.state_checked
import android.R.attr.state_enabled
import android.content.Context
import android.content.res.Configuration
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.graphics.ColorUtils
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.android.material.button.MaterialButton
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
                R.id.statusText,
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
    fun productionModeToggleHasReadableCheckedAndDistinctDisabledStates() {
        withProductionLayout { root ->
            listOf(R.id.modeUSB, R.id.modeWireless, R.id.modeInternet).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
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
    fun productionChecklistReportsEveryTransportLabelAndStatusWithoutColor() {
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

    private fun applicationContext(): Context = ApplicationProvider.getApplicationContext()

    private fun dp(context: Context, value: Int): Int =
        (value * context.resources.displayMetrics.density).roundToInt()

    private fun stateColor(colors: android.content.res.ColorStateList?, vararg states: Int): Int {
        checkNotNull(colors)
        return colors.getColorForState(states, colors.defaultColor)
    }
}
