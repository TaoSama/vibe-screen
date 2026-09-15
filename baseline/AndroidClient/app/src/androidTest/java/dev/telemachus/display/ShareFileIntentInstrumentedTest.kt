package dev.telemachus.display

import android.content.Intent
import android.content.ClipData
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ShareFileIntentInstrumentedTest {
    @Test
    fun noHostShareFailsClosedBeforeReadingContentUri() {
        ShareFileIntentTestProvider.reset()
        ActivityScenario.launch<MainActivity>(shareIntent()).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            scenario.onActivity { activity ->
                val dialog = currentAlertDialog(activity)
                val title = dialog?.findViewById<TextView>(androidx.appcompat.R.id.alertTitle)
                val message = dialog?.findViewById<TextView>(android.R.id.message)
                val positive = dialog?.getButton(AlertDialog.BUTTON_POSITIVE)

                assertEquals(activity.getString(R.string.file_transfer_unavailable_title), title?.text?.toString())
                assertEquals(activity.getString(R.string.file_transfer_share_unavailable), message?.text?.toString())
                assertEquals(activity.getString(android.R.string.ok), positive?.text?.toString())
                assertTrue("share unavailable dialog must not offer retry", dialog?.getButton(AlertDialog.BUTTON_NEGATIVE)?.visibility != View.VISIBLE)
                assertEquals("external share extras must not enable automatic USB", false, automaticUsbConnect(activity))
            }
        }

        assertEquals("No-Host share must not query source metadata", 0, ShareFileIntentTestProvider.queryCount.get())
        assertEquals("No-Host share must not open source bytes", 0, ShareFileIntentTestProvider.openFileCount.get())
        assertEquals("No-Host share must not resolve source MIME through ContentResolver", 0, ShareFileIntentTestProvider.getTypeCount.get())
    }

    @Test
    fun clipDataOnlyShareIsAcceptedWithoutReadingSourceWhenNoHostExists() {
        ShareFileIntentTestProvider.reset()
        val intent =
            Intent(Intent.ACTION_SEND)
                .setClassName("dev.telemachus.display", "dev.telemachus.display.MainActivity")
                .setType("application/octet-stream")
                .apply { clipData = ClipData.newRawUri("source.bin", ShareFileIntentTestProvider.uri) }

        ActivityScenario.launch<MainActivity>(intent).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity { activity ->
                val dialog = currentAlertDialog(activity)
                val message = dialog?.findViewById<TextView>(android.R.id.message)
                assertEquals(activity.getString(R.string.file_transfer_share_unavailable), message?.text?.toString())
            }
        }

        assertEquals(0, ShareFileIntentTestProvider.queryCount.get())
        assertEquals(0, ShareFileIntentTestProvider.openFileCount.get())
        assertEquals(0, ShareFileIntentTestProvider.getTypeCount.get())
    }

    @Test
    fun repeatedShareOfSameUriIsHandledAsANewUserAction() {
        ShareFileIntentTestProvider.reset()
        ActivityScenario.launch<MainActivity>(shareIntent()).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            scenario.onActivity { activity ->
                currentAlertDialog(activity)?.getButton(AlertDialog.BUTTON_POSITIVE)?.performClick()
                activity.startActivity(shareIntent().addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))
            }
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            scenario.onActivity { activity ->
                val dialog = currentAlertDialog(activity)
                val message = dialog?.findViewById<TextView>(android.R.id.message)
                assertTrue("a repeated user share must show a fresh result", dialog?.isShowing == true)
                assertEquals(activity.getString(R.string.file_transfer_share_unavailable), message?.text?.toString())
            }
        }

        assertEquals(0, ShareFileIntentTestProvider.queryCount.get())
        assertEquals(0, ShareFileIntentTestProvider.openFileCount.get())
        assertEquals(0, ShareFileIntentTestProvider.getTypeCount.get())
    }

    private fun shareIntent(): Intent =
        Intent(Intent.ACTION_SEND)
            .setClassName("dev.telemachus.display", "dev.telemachus.display.MainActivity")
            .setType("application/octet-stream")
            .putExtra(Intent.EXTRA_STREAM, ShareFileIntentTestProvider.uri)
            .putExtra("auto_connect", true)

    private fun automaticUsbConnect(activity: MainActivity): Boolean {
        val field = MainActivity::class.java.getDeclaredField("automaticUsbConnect")
        field.isAccessible = true
        return field.getBoolean(activity)
    }

    private fun currentAlertDialog(activity: MainActivity): AlertDialog? {
        val field = MainActivity::class.java.getDeclaredField("fileTransferErrorDialog")
        field.isAccessible = true
        return field.get(activity) as? AlertDialog
    }
}
