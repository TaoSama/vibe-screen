package dev.telemachus.display

import android.content.Intent
import android.content.ClipData
import android.net.Uri
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
    fun actionSendMultipleWithOneContentUriRemainsPendingWithoutReadingSourceWhenNoHostExists() {
        ShareFileIntentTestProvider.reset()

        ActivityScenario.launch<MainActivity>(shareMultipleIntent(listOf(ShareFileIntentTestProvider.uri))).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity(::assertPendingShare)
        }

        assertProviderWasNotRead()
    }

    @Test
    fun actionSendMultipleWithMultipleItemsIsRejectedWithoutReadingSourcesWhenNoHostExists() {
        ShareFileIntentTestProvider.reset()

        ActivityScenario.launch<MainActivity>(
            shareMultipleIntent(
                listOf(
                    ShareFileIntentTestProvider.uri,
                    Uri.parse("content://dev.telemachus.display.sharefiletest/second.bin"),
                ),
            ),
        ).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity { activity ->
                assertEquals(View.GONE, activity.findViewById<View>(R.id.pendingSharedFileContainer).visibility)
            }
        }

        assertProviderWasNotRead()
    }

    @Test
    fun actionSendMultipleWithBareUriExtraIsRejectedWithoutReadingSourceWhenNoHostExists() {
        ShareFileIntentTestProvider.reset()
        val intent =
            Intent(Intent.ACTION_SEND_MULTIPLE)
                .setClassName("dev.telemachus.display", "dev.telemachus.display.MainActivity")
                .setType("application/octet-stream")
                .putExtra(Intent.EXTRA_STREAM, ShareFileIntentTestProvider.uri)

        ActivityScenario.launch<MainActivity>(intent).use { scenario ->
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            scenario.onActivity { activity ->
                assertEquals(View.GONE, activity.findViewById<View>(R.id.pendingSharedFileContainer).visibility)
            }
        }

        assertProviderWasNotRead()
    }

    @Test
    fun manifestResolvesActionSendMultipleFileShareTarget() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val resolverIntent =
            Intent(Intent.ACTION_SEND_MULTIPLE)
                .addCategory(Intent.CATEGORY_DEFAULT)
                .setType("*/*")
                .setPackage(context.packageName)

        val resolvedActivities = context.packageManager.queryIntentActivities(resolverIntent, 0)

        assertTrue(
            "MainActivity must resolve ACTION_SEND_MULTIPLE */* shares",
            resolvedActivities.any { it.activityInfo.name == MainActivity::class.java.name },
        )
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

    private fun shareMultipleIntent(uris: List<Uri>): Intent =
        Intent(Intent.ACTION_SEND_MULTIPLE)
            .setClassName("dev.telemachus.display", "dev.telemachus.display.MainActivity")
            .setType("application/octet-stream")
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
            .apply {
                uris.forEachIndexed { index, uri ->
                    if (index == 0) {
                        clipData = ClipData.newRawUri("source-$index", uri)
                    } else {
                        clipData?.addItem(ClipData.Item(uri))
                    }
                }
            }

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

    private fun assertProviderWasNotRead() {
        assertEquals("No-Host share must not query source metadata", 0, ShareFileIntentTestProvider.queryCount.get())
        assertEquals("No-Host share must not open source bytes", 0, ShareFileIntentTestProvider.openFileCount.get())
        assertEquals("No-Host share must not resolve source MIME through ContentResolver", 0, ShareFileIntentTestProvider.getTypeCount.get())
    }
}
