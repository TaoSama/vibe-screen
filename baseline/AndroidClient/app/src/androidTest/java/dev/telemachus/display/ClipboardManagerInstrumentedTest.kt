package dev.telemachus.display

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ClipboardManagerInstrumentedTest {
    @Test
    fun foregroundActivityCanUseAndroidSystemClipboardLocally() {
        val marker = "vs-clipboard-device-${System.currentTimeMillis()}"
        withForegroundActivity { activity, clipboard ->
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

            clearClipboard(clipboard, activity.getString(R.string.clipboard_plain_text_label))
        }
    }

    @Test
    fun foregroundActivityCanRoundTripUnicodeAndLargePlainTextLocally() {
        val prefix = "vs-clipboard-unicode-${System.currentTimeMillis()}\naccent=\u00e9\ncjk=\u526a\u8d34\u677f\nemoji=\ud83d\ude80\n"
        val marker = prefix + "x".repeat(LARGE_SMOKE_CLIPBOARD_BYTES - prefix.toByteArray(Charsets.UTF_8).size)
        assertEquals(LARGE_SMOKE_CLIPBOARD_BYTES, marker.toByteArray(Charsets.UTF_8).size)

        withForegroundActivity { activity, clipboard ->
            clipboard.setPrimaryClip(
                ClipData.newPlainText(
                    activity.getString(R.string.clipboard_plain_text_label),
                    marker,
                ),
            )

            val primaryClip = clipboard.primaryClip
            assertNotNull("large unicode primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            assertEquals(marker, primaryClip.getItemAt(0).coerceToText(activity).toString())
            Log.i(TAG, "clipboard_manager_unicode_large bytes=${marker.toByteArray(Charsets.UTF_8).size}")

            clearClipboard(clipboard, activity.getString(R.string.clipboard_plain_text_label))
        }
    }

    @Test
    fun foregroundActivityHandlesNonTextClipboardItemSafely() {
        withForegroundActivity { activity, clipboard ->
            val intent = Intent("dev.telemachus.display.CLIPBOARD_NON_TEXT_SMOKE")
            clipboard.setPrimaryClip(ClipData.newIntent("Vibe Screen intent smoke", intent))

            val primaryClip = clipboard.primaryClip
            assertNotNull("non-text primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            val item = primaryClip.getItemAt(0)
            assertNull(item.text)
            assertTrue(item.coerceToText(activity).toString().contains("dev.telemachus.display.CLIPBOARD_NON_TEXT_SMOKE"))
            Log.i(TAG, "clipboard_manager_non_text_safe")

            clearClipboard(clipboard, activity.getString(R.string.clipboard_plain_text_label))
        }
    }

    @Test
    fun setForegroundClipboardFromInstrumentationArgument() {
        val marker =
            InstrumentationRegistry
                .getArguments()
                .getString(ARG_CLIPBOARD_MARKER)
                ?.takeIf { it.isNotBlank() }
                ?: "vs-clipboard-arg-set-${System.currentTimeMillis()}"
        withForegroundActivity { activity, clipboard ->
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
            clearClipboard(clipboard, activity.getString(R.string.clipboard_plain_text_label))
        }
    }

    @Test
    fun assertForegroundClipboardMatchesInstrumentationArgument() {
        val argumentMarker =
            InstrumentationRegistry
                .getArguments()
                .getString(ARG_CLIPBOARD_MARKER)
                ?.takeIf { it.isNotBlank() }
        val expected = argumentMarker ?: "vs-clipboard-arg-assert-${System.currentTimeMillis()}"
        withForegroundActivity { activity, clipboard ->
            if (argumentMarker == null) {
                clipboard.setPrimaryClip(
                    ClipData.newPlainText(
                        activity.getString(R.string.clipboard_plain_text_label),
                        expected,
                    ),
                )
            }
            val primaryClip = clipboard.primaryClip
            assertNotNull("primaryClip should be visible to the foreground app", primaryClip)
            assertEquals(1, primaryClip!!.itemCount)
            val actual = primaryClip.getItemAt(0).coerceToText(activity).toString()
            assertEquals(expected, actual)
            Log.i(TAG, "clipboard_manager_assert marker=$actual")
            if (argumentMarker == null) {
                clearClipboard(clipboard, activity.getString(R.string.clipboard_plain_text_label))
            }
        }
    }

    private fun withForegroundActivity(assertion: (MainActivity, ClipboardManager) -> Unit) {
        val scenario = ActivityScenario.launch(MainActivity::class.java)
        try {
            scenario.moveToState(Lifecycle.State.RESUMED)
            scenario.onActivity { activity ->
                assertion(activity, activity.getSystemService(ClipboardManager::class.java))
            }
        } finally {
            scenario.close()
        }
    }

    private companion object {
        private const val ARG_CLIPBOARD_MARKER = "clipboard_marker"
        private const val LARGE_SMOKE_CLIPBOARD_BYTES = 256 * 1024
        private const val TAG = "ClipboardDeviceTest"

        private fun clearClipboard(clipboard: ClipboardManager, label: String) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                clipboard.clearPrimaryClip()
            } else {
                clipboard.setPrimaryClip(ClipData.newPlainText(label, ""))
            }
        }
    }
}
