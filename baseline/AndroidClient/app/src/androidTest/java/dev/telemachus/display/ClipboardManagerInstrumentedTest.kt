package dev.telemachus.display

import android.content.ClipData
import android.content.ClipboardManager
import android.os.Build
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
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

    private companion object {
        private const val TAG = "ClipboardDeviceTest"
    }
}
