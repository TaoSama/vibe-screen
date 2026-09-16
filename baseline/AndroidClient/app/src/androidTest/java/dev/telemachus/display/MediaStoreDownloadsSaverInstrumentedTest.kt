package dev.telemachus.display

import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.security.MessageDigest

@RunWith(AndroidJUnit4::class)
class MediaStoreDownloadsSaverInstrumentedTest {
    @Test
    fun productionDocumentExporterCopiesPublishedIncomingFileExactly() {
        assumeTrue("MediaStore.Downloads export path is Android Q+ only", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)

        val suffix = System.currentTimeMillis().toString()
        val sourceName = "vibescreen-p0110-export-source-" + suffix + ".bin"
        val destinationName = "vibescreen-p0110-export-destination-" + suffix + ".bin"
        val payload = ("p0110-user-selected-export\n" + "fedcba9876543210".repeat(256)).toByteArray()
        withTargetContext { context ->
            val collection = ContentResolverMediaStoreDownloadsCollection(context.contentResolver)
            var source: Uri? = null
            var destination: Uri? = null
            try {
                source = collection.insertPending(sourceName, TEST_MIME_TYPE)
                collection.openOutputStream(source)?.use { it.write(payload) }
                    ?: throw IOException("Unable to seed export source")
                collection.publish(source)

                destination = collection.insertPending(destinationName, TEST_MIME_TYPE)
                IncomingFileDocumentExporter(context.contentResolver).export(source, destination)
                collection.publish(destination)

                val exported = context.contentResolver.openInputStream(destination)?.use { it.readBytes() }
                    ?: throw IOException("Unable to read export destination")
                assertArrayEquals(payload, exported)
                assertArrayEquals(sha256Bytes(payload), sha256Bytes(exported))
                Log.i(TAG, "incoming_document_export source=" + source + " destination=" + destination + " bytes=" + exported.size)
            } finally {
                destination?.let { context.contentResolver.delete(it, null, null) }
                source?.let { context.contentResolver.delete(it, null, null) }
            }
        }
    }

    @Test
    fun productionSaverPublishesIncomingFileToMediaStoreDownloads() {
        assumeTrue("MediaStore.Downloads publish path is Android Q+ only", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)

        val displayName = "vibescreen-p0110-mediastore-${System.currentTimeMillis()}.txt"
        val payload =
            ("p0110-mediastore-downloads-smoke\n" + "0123456789abcdef".repeat(256))
                .toByteArray(Charsets.UTF_8)
        withTargetContext { context ->
            val staging = File(context.cacheDir, ".vibescreen-$displayName.partial").apply { writeBytes(payload) }
            var saved: Uri? = null
            try {
                saved =
                    IncomingFileDownloadsSaver(
                        sdkInt = Build.VERSION.SDK_INT,
                        appSpecificDownloads = { error("Android Q+ smoke must publish through MediaStore") },
                        mediaStoreDownloads = { ContentResolverMediaStoreDownloadsCollection(context.contentResolver) },
                    ).saveCompletedIncomingFile(
                        completed = completedIncomingFile(staging, displayName, TEST_MIME_TYPE, payload),
                        displayName = displayName,
                        maxDisplayNameLength = 180,
                    )

                val row = queryDownloadsRow(context.contentResolver, saved)
                assertEquals(displayName, row.displayName)
                assertEquals(TEST_MIME_TYPE, row.mimeType)
                assertEquals(Environment.DIRECTORY_DOWNLOADS + "/", row.relativePath)
                assertEquals(0, row.isPending)

                val publishedBytes = context.contentResolver.openInputStream(saved)?.use { it.readBytes() }
                    ?: throw IOException("Unable to read published Downloads entry")
                assertArrayEquals(payload, publishedBytes)
                assertArrayEquals(sha256Bytes(payload), sha256Bytes(publishedBytes))
                assertTrue("production Q+ saver leaves staging cleanup to MainActivity", staging.exists())

                Log.i(TAG, "mediastore_downloads_publish uri=$saved bytes=${publishedBytes.size}")
            } finally {
                saved?.let { context.contentResolver.delete(it, null, null) }
                staging.delete()
            }
        }
    }

    @Test
    fun failedMediaStorePublishDeletesInsertedEntryAndKeepsStagingForCallerCleanup() {
        assumeTrue("MediaStore.Downloads failure path is Android Q+ only", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)

        val displayName = "vibescreen-p0110-mediastore-failure-${System.currentTimeMillis()}.bin"
        val payload = "p0110-mediastore-failure".toByteArray(Charsets.UTF_8)
        withTargetContext { context ->
            val staging = File(context.cacheDir, ".vibescreen-$displayName.partial").apply { writeBytes(payload) }
            val failingDownloads =
                FailingAfterInsertMediaStoreDownloadsCollection(
                    ContentResolverMediaStoreDownloadsCollection(context.contentResolver),
                )
            try {
                val thrown =
                    runCatching {
                        IncomingFileDownloadsSaver(
                            sdkInt = Build.VERSION.SDK_INT,
                            appSpecificDownloads = { error("Android Q+ smoke must publish through MediaStore") },
                            mediaStoreDownloads = { failingDownloads },
                        ).saveCompletedIncomingFile(
                            completed = completedIncomingFile(staging, displayName, TEST_MIME_TYPE, payload),
                            displayName = displayName,
                            maxDisplayNameLength = 180,
                        )
                    }.exceptionOrNull()

                assertTrue("failure should be reported", thrown is IOException)
                assertTrue("staging remains caller-owned after MediaStore failure", staging.exists())
                assertEquals(listOf(failingDownloads.insertedUri), failingDownloads.deleted)
                failingDownloads.insertedUri?.let { inserted ->
                    assertFalse("failed entry should be deleted from Downloads", downloadsEntryExists(context.contentResolver, inserted))
                }
                Log.i(TAG, "mediastore_downloads_failure_cleanup uri=${failingDownloads.insertedUri}")
            } finally {
                failingDownloads.insertedUri?.let { context.contentResolver.delete(it, null, null) }
                staging.delete()
            }
        }
    }

    private fun withTargetContext(assertion: (android.content.Context) -> Unit) =
        assertion(ApplicationProvider.getApplicationContext())

    private data class DownloadsRow(
        val displayName: String,
        val mimeType: String,
        val relativePath: String,
        val isPending: Int,
    )

    private fun queryDownloadsRow(
        contentResolver: android.content.ContentResolver,
        uri: Uri,
    ): DownloadsRow {
        val projection =
            arrayOf(
                MediaStore.Downloads.DISPLAY_NAME,
                MediaStore.Downloads.MIME_TYPE,
                MediaStore.Downloads.RELATIVE_PATH,
                MediaStore.Downloads.IS_PENDING,
            )
        contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
            assertTrue("published Downloads row should be queryable", cursor.moveToFirst())
            return DownloadsRow(
                displayName = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)),
                mimeType = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.MIME_TYPE)),
                relativePath = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.RELATIVE_PATH)),
                isPending = cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)),
            )
        }
        throw IOException("Published Downloads row is unavailable")
    }

    private fun downloadsEntryExists(
        contentResolver: android.content.ContentResolver,
        uri: Uri,
    ): Boolean =
        contentResolver.query(uri, arrayOf(MediaStore.Downloads._ID), null, null, null)?.use { cursor ->
            cursor.moveToFirst()
        } ?: false

    private fun completedIncomingFile(
        staging: File,
        fileName: String,
        mimeType: String,
        payload: ByteArray,
    ): CompletedIncomingFile =
        CompletedIncomingFile(
            transferId = ByteString.copyFromUtf8("mediastore-${staging.name}"),
            fileName = fileName,
            mimeType = mimeType,
            stagingFile = staging,
            sha256 = sha256(payload),
        )

    private class FailingAfterInsertMediaStoreDownloadsCollection(
        private val delegate: MediaStoreDownloadsCollection,
    ) : MediaStoreDownloadsCollection {
        var insertedUri: Uri? = null
            private set
        val deleted = mutableListOf<Uri>()

        override fun insertPending(
            displayName: String,
            mimeType: String,
        ): Uri =
            delegate.insertPending(displayName, mimeType).also { insertedUri = it }

        override fun openOutputStream(uri: Uri): OutputStream? =
            throw IOException("simulated MediaStore output failure")

        override fun publish(uri: Uri) {
            error("failed output must not publish")
        }

        override fun delete(uri: Uri) {
            deleted += uri
            delegate.delete(uri)
        }
    }

    private companion object {
        private const val TEST_MIME_TYPE = "text/plain"
        private const val TAG = "MediaStoreDownloadsTest"

        private fun sha256Bytes(bytes: ByteArray): ByteArray =
            MessageDigest.getInstance("SHA-256").digest(bytes)
    }
}
