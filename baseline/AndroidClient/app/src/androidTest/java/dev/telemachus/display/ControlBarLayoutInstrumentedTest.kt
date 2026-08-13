package dev.telemachus.display

import android.content.Context
import android.view.ContextThemeWrapper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ControlBarLayoutInstrumentedTest {
    @Test
    fun narrowLayoutPreservesLabelsAndActionTouchTargets() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val themedContext = ContextThemeWrapper(context, R.style.AppTheme)
        val root = LayoutInflater.from(themedContext).inflate(R.layout.activity_main, null, false)
        val fullDisplayName = "Vibe Screen Virtual Extended Display With A Deliberately Long Name"
        val selector = root.findViewById<ViewGroup>(R.id.displayCapsuleGroup)
        val label = root.findViewById<TextView>(R.id.controlDisplaysLabel)

        root.findViewById<View>(R.id.controlBar).visibility = View.VISIBLE
        selector.visibility = View.VISIBLE
        root.findViewById<View>(R.id.controlHostActionsButton).visibility = View.VISIBLE
        selector.contentDescription = fullDisplayName
        label.text = fullDisplayName

        val density = context.resources.displayMetrics.density
        val width = (NARROW_LAYOUT_WIDTH_DP * density).toInt()
        val height = (LAYOUT_HEIGHT_DP * density).toInt()
        root.measure(
            View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY),
        )
        root.layout(0, 0, root.measuredWidth, root.measuredHeight)

        assertEquals(fullDisplayName, selector.contentDescription.toString())
        assertTrue("Long display label was not visually ellipsized", label.layout.getEllipsisCount(0) > 0)

        val minimumTouchTarget = (MINIMUM_TOUCH_TARGET_DP * density).toInt()
        listOf(
            R.id.controlHostActionsButton,
            R.id.controlSettingsButton,
            R.id.controlDisconnectButton,
        ).forEach { id ->
            val control = root.findViewById<View>(id)
            assertTrue("Control $id was narrower than 48dp", control.measuredWidth >= minimumTouchTarget)
            assertTrue("Control $id was shorter than 48dp", control.measuredHeight >= minimumTouchTarget)
        }
    }

    private companion object {
        const val NARROW_LAYOUT_WIDTH_DP = 352
        const val LAYOUT_HEIGHT_DP = 240
        const val MINIMUM_TOUCH_TARGET_DP = 48
    }
}
