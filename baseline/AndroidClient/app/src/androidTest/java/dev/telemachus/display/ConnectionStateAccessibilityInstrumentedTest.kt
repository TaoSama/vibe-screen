package dev.telemachus.display

import android.R.attr.state_checked
import android.R.attr.state_enabled
import android.content.Context
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
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

@RunWith(AndroidJUnit4::class)
class ConnectionStateAccessibilityInstrumentedTest {
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
    fun productionChecklistReportsReadyAndNotReadyWithoutColor() {
        withProductionLayout { root ->
            val indicator = root.findViewById<View>(R.id.checkDeveloperMode)
            val label = root.findViewById<TextView>(R.id.textDeveloperMode)
            val context = root.context

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.developer_mode,
                ChecklistStatus.NOT_READY,
            )
            assertEquals(
                context.getString(
                    R.string.checklist_item_status,
                    context.getString(R.string.developer_mode),
                    context.getString(R.string.checklist_not_ready),
                ),
                label.text.toString(),
            )
            assertEquals(View.ACCESSIBILITY_LIVE_REGION_POLITE, label.accessibilityLiveRegion)
            assertFalse(indicator.isImportantForAccessibility)

            val unchangedText = label.text
            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.developer_mode,
                ChecklistStatus.NOT_READY,
            )
            assertTrue("Unchanged status should not replace the live-region text", unchangedText === label.text)

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.developer_mode,
                ChecklistStatus.READY,
            )
            assertEquals(
                context.getString(
                    R.string.checklist_item_status,
                    context.getString(R.string.developer_mode),
                    context.getString(R.string.checklist_ready),
                ),
                label.text.toString(),
            )

            ChecklistStatusApplier.apply(
                context,
                indicator,
                label,
                R.string.developer_mode,
                ChecklistStatus.CHECKING,
            )
            assertEquals(
                context.getString(
                    R.string.checklist_item_status,
                    context.getString(R.string.developer_mode),
                    context.getString(R.string.checklist_checking),
                ),
                label.text.toString(),
            )
        }
    }

    private fun withProductionLayout(block: (View) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
            block(LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false))
        }
    }

    private fun stateColor(colors: android.content.res.ColorStateList?, vararg states: Int): Int {
        checkNotNull(colors)
        return colors.getColorForState(states, colors.defaultColor)
    }
}
