package dev.telemachus.display

import android.content.Intent
import android.net.Uri
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class IncomingFileSavedPanelInstrumentedTest {
    @Test
    fun latestCompletedFileSurvivesRecreationAndCanBeDismissed() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val launchIntent =
            Intent(context, MainActivity::class.java)
                .putExtra(AUTO_CONNECT_EXTRA, false)

        ActivityScenario.launch<MainActivity>(launchIntent).use { scenario ->
            scenario.onActivity { activity ->
                activity.showIncomingFileSavedAction("first.bin")
                activity.showIncomingFileSavedAction("latest.bin")
                activity.assertRecentFilePanel("latest.bin")
            }

            scenario.recreate()
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity { activity ->
                activity.assertRecentFilePanel("latest.bin")
                assertTrue(activity.findViewById<Button>(R.id.recentIncomingFileDismissButton).performClick())
                assertEquals(View.GONE, activity.findViewById<View>(R.id.recentIncomingFileContainer).visibility)
            }
        }
    }

    private fun MainActivity.showIncomingFileSavedAction(displayName: String) {
        MainActivity::class.java
            .getDeclaredMethod(
                "showIncomingFileSavedAction",
                Uri::class.java,
                String::class.java,
                String::class.java,
            ).apply { isAccessible = true }
            .invoke(
                this,
                Uri.parse("content://dev.telemachus.display.test/downloads/$displayName"),
                displayName,
                "application/octet-stream",
            )
    }

    private fun MainActivity.assertRecentFilePanel(displayName: String) {
        val container = findViewById<View>(R.id.recentIncomingFileContainer)
        val summary = findViewById<TextView>(R.id.recentIncomingFileSummary)
        val saveCopy = findViewById<Button>(R.id.recentIncomingFileSaveCopyButton)
        val dismiss = findViewById<Button>(R.id.recentIncomingFileDismissButton)

        assertEquals(View.VISIBLE, container.visibility)
        assertTrue(summary.text.toString().contains(displayName))
        assertTrue(saveCopy.isEnabled)
        assertTrue(dismiss.isEnabled)
        assertTrue(saveCopy.minimumHeight >= dp(48))
        assertTrue(dismiss.minimumHeight >= dp(48))
    }

    private fun MainActivity.dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val AUTO_CONNECT_EXTRA = "auto_connect"
    }
}
