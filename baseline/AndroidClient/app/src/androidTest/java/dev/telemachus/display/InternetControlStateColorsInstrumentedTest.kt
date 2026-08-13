package dev.telemachus.display

import android.R.attr.state_checked
import android.R.attr.state_enabled
import android.content.Context
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.core.graphics.ColorUtils
import com.google.android.material.button.MaterialButton
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InternetControlStateColorsInstrumentedTest {
    @Test
    fun productionRouteToggleDistinguishesCheckedAndUncheckedStates() {
        withProductionLayout { root ->
            listOf(R.id.internetPreferDirect, R.id.internetForceRelay).forEach { id ->
                val button = root.findViewById<MaterialButton>(id)
                button.isChecked = true
                button.refreshDrawableState()
                val checkedBackground = stateColor(button.backgroundTintList, state_enabled, state_checked)
                val checkedText = stateColor(button.textColors, state_enabled, state_checked)

                button.isChecked = false
                button.refreshDrawableState()
                val uncheckedBackground = stateColor(button.backgroundTintList, state_enabled, -state_checked)

                assertNotEquals(checkedBackground, uncheckedBackground)
                assertReadable(checkedText, checkedBackground)
            }
        }
    }

    @Test
    fun productionInternetActionsDistinguishEnabledAndDisabledStates() {
        withProductionLayout { root ->
            val connect = root.findViewById<MaterialButton>(R.id.internetConnectButton)
            assertEnabledStateColorsDiffer(connect, includeBackground = true)

            listOf(
                R.id.internetScanProfileButton,
                R.id.internetImportProfileButton,
                R.id.internetRevokeButton,
            ).forEach { id ->
                assertEnabledStateColorsDiffer(root.findViewById(id), includeBackground = false)
            }
        }
    }

    private fun withProductionLayout(block: (View) -> Unit) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
            block(LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false))
        }
    }

    private fun assertEnabledStateColorsDiffer(button: MaterialButton, includeBackground: Boolean) {
        button.isEnabled = true
        button.refreshDrawableState()
        val enabledText = button.currentTextColor
        if (includeBackground) {
            assertReadable(enabledText, stateColor(button.backgroundTintList, state_enabled))
        }

        button.isEnabled = false
        button.refreshDrawableState()
        assertNotEquals(enabledText, button.currentTextColor)
        if (includeBackground) {
            assertNotEquals(
                stateColor(button.backgroundTintList, state_enabled),
                stateColor(button.backgroundTintList, -state_enabled),
            )
        }
    }

    private fun stateColor(colors: android.content.res.ColorStateList?, vararg states: Int): Int {
        assertNotNull(colors)
        return colors!!.getColorForState(states, colors.defaultColor)
    }

    private fun assertReadable(foreground: Int, background: Int) {
        assertTrue(
            "Expected at least 4.5:1 contrast, got ${ColorUtils.calculateContrast(foreground, background)}",
            ColorUtils.calculateContrast(foreground, background) >= 4.5,
        )
    }
}
