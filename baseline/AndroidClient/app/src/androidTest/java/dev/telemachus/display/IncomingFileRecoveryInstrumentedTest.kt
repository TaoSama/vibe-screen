package dev.telemachus.display

import android.content.Intent
import android.app.AlertDialog
import android.net.Uri
import android.os.SystemClock
import android.provider.MediaStore
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest

@RunWith(AndroidJUnit4::class)
class IncomingFileRecoveryInstrumentedTest {
    @Test
    fun pendingMediaStorePublicationResumesWithTheSameUriAfterStoreRecreation() {
        assumeTrue("MediaStore recovery journal requires Android Q+", android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = IncomingFileRecoveryStore(context)
        clearRecovery(store)
        val displayName = "vibescreen-pending-resume-${System.currentTimeMillis()}.bin"
        val payload = ("pending-resume\n" + "abcdef0123456789".repeat(128)).toByteArray()
        val staging = File(context.cacheDir, ".$displayName.partial").apply { writeBytes(payload) }
        val collection = ContentResolverMediaStoreDownloadsCollection(context.contentResolver)
        var pendingUri: Uri? = null
        try {
            val recovery = store.adopt(completed(staging, displayName, payload), displayName)
            staging.delete()
            pendingUri = collection.insertPending(displayName, TEST_MIME_TYPE)
            store.markMediaStorePending(recovery, pendingUri.toString())

            val recreatedStore = IncomingFileRecoveryStore(context)
            val saved = recoverySaver(context).publishRecoveredIncomingFile(requireNotNull(recreatedStore.load()), recreatedStore)

            assertEquals("Retry must reuse the journaled pending URI", pendingUri, saved)
            assertEquals(0, queryDownloadsPending(saved))
            assertEquals(1, countDownloadsRows(displayName))
            assertArrayEquals(payload, requireNotNull(context.contentResolver.openInputStream(saved)?.use { it.readBytes() }))
            assertNull(recreatedStore.load())
        } finally {
            pendingUri?.let { context.contentResolver.delete(it, null, null) }
            staging.delete()
            clearRecovery(store)
        }
    }

    @Test
    fun publishedJournalCleanupAfterStoreRecreationDoesNotCreateAnotherDownload() {
        assumeTrue("MediaStore recovery journal requires Android Q+", android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = IncomingFileRecoveryStore(context)
        clearRecovery(store)
        val displayName = "vibescreen-published-resume-${System.currentTimeMillis()}.bin"
        val payload = ("published-resume\n" + "0123456789abcdef".repeat(128)).toByteArray()
        val staging = File(context.cacheDir, ".$displayName.partial").apply { writeBytes(payload) }
        val collection = ContentResolverMediaStoreDownloadsCollection(context.contentResolver)
        var publishedUri: Uri? = null
        try {
            val recovery = store.adopt(completed(staging, displayName, payload), displayName)
            staging.delete()
            publishedUri = collection.insertPending(displayName, TEST_MIME_TYPE)
            collection.openOutputStream(publishedUri, "wt")!!.use { it.write(payload) }
            collection.publish(publishedUri)
            val pending = store.markMediaStorePending(recovery, publishedUri.toString())
            val published = store.markPublished(pending, publishedUri.toString())
            assertTrue(published.payloadFile.delete())

            val recreatedStore = IncomingFileRecoveryStore(context)
            val saved = recoverySaver(context).publishRecoveredIncomingFile(requireNotNull(recreatedStore.load()), recreatedStore)

            assertEquals("Published cleanup retry must return the original URI", publishedUri, saved)
            assertEquals(1, countDownloadsRows(displayName))
            assertArrayEquals(payload, requireNotNull(context.contentResolver.openInputStream(saved)?.use { it.readBytes() }))
            assertNull(recreatedStore.load())
        } finally {
            publishedUri?.let { context.contentResolver.delete(it, null, null) }
            staging.delete()
            clearRecovery(store)
        }
    }

    @Test
    fun coldStartRetryPublishesExactBytesAndClearsRecovery() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = IncomingFileRecoveryStore(context)
        clearRecovery(store)
        val displayName = "vibescreen-recovery-retry-${System.currentTimeMillis()}.bin"
        val payload = ("recovery-retry\n" + "0123456789abcdef".repeat(256)).toByteArray()
        val staging = File(context.cacheDir, ".$displayName.partial").apply { writeBytes(payload) }
        var savedUri: Uri? = null
        try {
            store.adopt(completed(staging, displayName, payload), displayName)
            staging.delete()
            ActivityScenario.launch<MainActivity>(launchIntent()).use { scenario ->
                waitForActivity(scenario) { activity ->
                    activity.findViewById<View>(R.id.recentIncomingFileContainer).visibility == View.VISIBLE &&
                        activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                        activity.getString(R.string.file_transfer_incoming_save_failed_title)
                }
                scenario.recreate()
                waitForActivity(scenario) { activity ->
                    activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                        activity.getString(R.string.file_transfer_incoming_save_failed_title)
                }
                scenario.onActivity { activity ->
                    val retry = activity.findViewById<Button>(R.id.incomingFileStatusPrimaryButton)
                    val discard = activity.findViewById<Button>(R.id.incomingFileStatusSecondaryButton)
                    assertTrue(retry.isEnabled)
                    assertTrue(discard.isEnabled)
                    assertTrue(retry.minimumHeight >= activity.dp(48))
                    assertTrue(discard.minimumHeight >= activity.dp(48))
                    assertTrue(retry.performClick())
                }
                waitForActivity(scenario) { activity ->
                    activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                        activity.getString(R.string.file_transfer_incoming_saved_title)
                }
            }

            savedUri = findDownloadByName(displayName)
            assertNotNull("Retry must publish a visible Downloads row", savedUri)
            assertEquals("Retry must create exactly one Downloads row", 1, countDownloadsRows(displayName))
            val savedBytes = requireNotNull(context.contentResolver.openInputStream(savedUri!!)?.use { it.readBytes() })
            assertArrayEquals(payload, savedBytes)
            assertArrayEquals(MessageDigest.getInstance("SHA-256").digest(payload), MessageDigest.getInstance("SHA-256").digest(savedBytes))
            assertNull(store.load())
        } finally {
            savedUri?.let { context.contentResolver.delete(it, null, null) }
            staging.delete()
            clearRecovery(store)
        }
    }

    @Test
    fun discardRequiresConfirmationAndRemovesRecovery() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = IncomingFileRecoveryStore(context)
        clearRecovery(store)
        val displayName = "vibescreen-recovery-discard-${System.currentTimeMillis()}.bin"
        val payload = "discard-after-confirmation".toByteArray()
        val staging = File(context.cacheDir, ".$displayName.partial").apply { writeBytes(payload) }
        try {
            store.adopt(completed(staging, displayName, payload), displayName)
            staging.delete()
            ActivityScenario.launch<MainActivity>(launchIntent()).use { scenario ->
                waitForActivity(scenario) { activity ->
                    activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                        activity.getString(R.string.file_transfer_incoming_save_failed_title)
                }
                scenario.onActivity { activity ->
                    assertTrue(activity.findViewById<Button>(R.id.incomingFileStatusSecondaryButton).performClick())
                    val dialog = requireNotNull(activity.incomingFileDiscardDialog)
                    assertTrue(dialog.isShowing)
                    assertEquals(
                        activity.getString(R.string.file_transfer_incoming_discard_confirmation_cancel),
                        dialog.getButton(AlertDialog.BUTTON_NEGATIVE).text.toString(),
                    )
                    assertTrue(dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick())
                }
                assertNotNull("Cancelling discard must retain recovery", store.load())
                scenario.recreate()
                waitForActivity(scenario) { activity ->
                    activity.findViewById<TextView>(R.id.incomingFileStatusTitle).text.toString() ==
                        activity.getString(R.string.file_transfer_incoming_save_failed_title)
                }

                scenario.onActivity { activity ->
                    assertTrue(activity.findViewById<Button>(R.id.incomingFileStatusSecondaryButton).performClick())
                    val dialog = requireNotNull(activity.incomingFileDiscardDialog)
                    assertTrue(dialog.isShowing)
                    assertEquals(
                        activity.getString(R.string.file_transfer_incoming_discard_confirmation_confirm),
                        dialog.getButton(AlertDialog.BUTTON_POSITIVE).text.toString(),
                    )
                    assertTrue(dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick())
                }
                waitForActivity(scenario) { activity ->
                    activity.findViewById<View>(R.id.recentIncomingFileContainer).visibility == View.GONE
                }
                assertNull(store.load())
            }
        } finally {
            staging.delete()
            clearRecovery(store)
        }
    }

    private fun launchIntent(): Intent =
        Intent(InstrumentationRegistry.getInstrumentation().targetContext, MainActivity::class.java)
            .putExtra("auto_connect", false)

    private fun completed(
        staging: File,
        displayName: String,
        payload: ByteArray,
    ): CompletedIncomingFile =
        CompletedIncomingFile(
            transferId = ByteString.copyFromUtf8("recovery-$displayName"),
            fileName = displayName,
            mimeType = TEST_MIME_TYPE,
            stagingFile = staging,
            sha256 = sha256(payload),
        )

    private fun clearRecovery(store: IncomingFileRecoveryStore) {
        store.load()?.let(store::discard)
    }

    private fun findDownloadByName(displayName: String): Uri? {
        val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
        resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Downloads._ID, MediaStore.Downloads.IS_PENDING),
            "${MediaStore.Downloads.DISPLAY_NAME} = ?",
            arrayOf(displayName),
            null,
        )?.use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)) == 0) {
                    val id = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID))
                    return Uri.withAppendedPath(MediaStore.Downloads.EXTERNAL_CONTENT_URI, id.toString())
                }
            }
        }
        return null
    }

    private fun queryDownloadsPending(uri: Uri): Int {
        val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
        resolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use { cursor ->
            assertTrue("Downloads row must remain queryable", cursor.moveToFirst())
            return cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING))
        }
        throw AssertionError("Downloads row is unavailable")
    }

    private fun countDownloadsRows(displayName: String): Int {
        val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver
        return resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Downloads._ID),
            "${MediaStore.Downloads.DISPLAY_NAME} = ?",
            arrayOf(displayName),
            null,
        )?.use { cursor -> cursor.count } ?: 0
    }

    private fun recoverySaver(context: android.content.Context): IncomingFileDownloadsSaver =
        IncomingFileDownloadsSaver(
            sdkInt = android.os.Build.VERSION.SDK_INT,
            appSpecificDownloads = { error("Android Q+ recovery must use MediaStore") },
            mediaStoreDownloads = { ContentResolverMediaStoreDownloadsCollection(context.contentResolver) },
        )

    private fun waitForActivity(
        scenario: ActivityScenario<MainActivity>,
        timeoutMs: Long = 10_000L,
        predicate: (MainActivity) -> Boolean,
    ) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            var satisfied = false
            scenario.onActivity { activity -> satisfied = predicate(activity) }
            if (satisfied) return
            SystemClock.sleep(50L)
        }
        var finalState = false
        scenario.onActivity { activity -> finalState = predicate(activity) }
        assertTrue("Timed out waiting for Activity state", finalState)
    }

    private fun MainActivity.dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val TEST_MIME_TYPE = "application/octet-stream"
    }
}
