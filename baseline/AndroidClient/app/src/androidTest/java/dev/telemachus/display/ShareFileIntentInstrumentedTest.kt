package dev.telemachus.display

import android.content.Intent
import android.content.ClipData
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ShareFileIntentInstrumentedTest {
    @Test
    fun noHostShareRemainsPendingWithoutReadingContentUri() {
        ShareFileIntentTestProvider.reset()
        ActivityScenario.launch<MainActivity>(shareIntent()).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            scenario.onActivity { activity ->
                assertPendingShare(activity)
                assertEquals("external share extras must not enable automatic USB", false, automaticUsbConnect(activity))
            }

            scenario.recreate()
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity(::assertPendingShare)
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
            scenario.onActivity(::assertPendingShare)
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
                activity.findViewById<Button>(R.id.pendingSharedFileCancelButton).performClick()
                assertEquals(View.GONE, activity.findViewById<View>(R.id.pendingSharedFileContainer).visibility)
                activity.startActivity(shareIntent().addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP))
            }
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()

            scenario.onActivity(::assertPendingShare)
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

    private fun assertPendingShare(activity: MainActivity) {
        val container = activity.findViewById<View>(R.id.pendingSharedFileContainer)
        val title = activity.findViewById<TextView>(R.id.pendingSharedFileTitle)
        val summary = activity.findViewById<TextView>(R.id.pendingSharedFileSummary)
        val send = activity.findViewById<Button>(R.id.pendingSharedFileSendButton)
        val cancel = activity.findViewById<Button>(R.id.pendingSharedFileCancelButton)

        assertEquals(View.VISIBLE, container.visibility)
        assertEquals(activity.getString(R.string.pending_shared_file_title), title.text.toString())
        assertEquals(activity.getString(R.string.pending_shared_file_waiting), summary.text.toString())
        assertEquals("Review must stay hidden without a capable session", View.GONE, send.visibility)
        assertFalse("Review must remain disabled without a capable session", send.isEnabled)
        assertTrue("A pending share must always be cancellable", cancel.isEnabled)
    }
}
