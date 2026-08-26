package dev.telemachus.display

import android.content.ClipData
import android.content.ClipboardManager
import android.os.Build
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ClipboardManagerInstrumentedTest {
    @Test
    fun foregroundActivityCanUseAndroidSystemClipboardLocally() {
        val marker = "vs-clipboard-device-${System.currentTimeMillis()}"
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            val clipboard = activity.getSystemService(ClipboardManager::class.java)
            clipboard.setPrimaryClip(
                ClipData.newPlainText(
                    activity.getString(R.string.clipboard_plain_text_label),
                    marker,
                ),
            )

            val primaryClip = clipboard.primaryClip
            assertNotNull("primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            assertEquals(marker, primaryClip.getItemAt(0).coerceToText(activity).toString())
            Log.i(TAG, "clipboard_manager_roundtrip marker=$marker")

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                clipboard.clearPrimaryClip()
            } else {
                clipboard.setPrimaryClip(
                    ClipData.newPlainText(
                        activity.getString(R.string.clipboard_plain_text_label),
                        "",
                    ),
                )
            }
            activity.finish()
        }
    }

    @Test
    fun setForegroundClipboardFromInstrumentationArgument() {
        val marker =
            InstrumentationRegistry
                .getArguments()
                .getString(ARG_CLIPBOARD_MARKER)
                ?.takeIf { it.isNotBlank() }
                ?: return
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            val clipboard = activity.getSystemService(ClipboardManager::class.java)
            clipboard.setPrimaryClip(
                ClipData.newPlainText(
                    activity.getString(R.string.clipboard_plain_text_label),
                    marker,
                ),
            )

            val primaryClip = clipboard.primaryClip
            assertNotNull("primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            assertEquals(marker, primaryClip.getItemAt(0).coerceToText(activity).toString())
            Log.i(TAG, "clipboard_manager_set marker=$marker")
            activity.finish()
        }
    }

    @Test
    fun assertForegroundClipboardMatchesInstrumentationArgument() {
        val expected =
            InstrumentationRegistry
                .getArguments()
                .getString(ARG_CLIPBOARD_MARKER)
                ?: return
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        scenario.onActivity { activity ->
            val clipboard = activity.getSystemService(ClipboardManager::class.java)
            val primaryClip = clipboard.primaryClip
            assertNotNull("primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            val actual = primaryClip.getItemAt(0).coerceToText(activity).toString()
            assertEquals(expected, actual)
            Log.i(TAG, "clipboard_manager_assert marker=$actual")
            activity.finish()
        }
    }

    private companion object {
        private const val ARG_CLIPBOARD_MARKER = "clipboard_marker"
        private const val TAG = "ClipboardDeviceTest"
    }
}
