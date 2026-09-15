package dev.telemachus.display

import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.IOException
import java.security.MessageDigest

@RunWith(AndroidJUnit4::class)
class OutgoingFileStagerInstrumentedTest {
    @Test
    fun productionStagerReadsContentUriIntoPrivateBytesMetadataAndCleansUp() {
        assumeTrue("MediaStore.Downloads content source is Android Q+ only", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)

        val displayName = "vibescreen-p0110-outgoing-source-${System.currentTimeMillis()}.txt"
        val payload =
            ("p0110-outgoing-content-staging-smoke\n" + "0123456789abcdef".repeat(96))
                .toByteArray(Charsets.UTF_8)
        withTargetContext { context ->
            val source = insertDownloadsSource(context, displayName, TEST_MIME_TYPE, payload)
            var staged: StagedOutgoingFile? = null
            try {
                staged = OutgoingFileStager(
                    contentResolver = context.contentResolver,
                    cacheDirectory = context.cacheDir,
                    maxDisplayNameLength = 180,
                ).stage(source, maximumFileBytes = payload.size.toLong())

                assertEquals(displayName, staged.displayName)
                assertEquals(TEST_MIME_TYPE, staged.mimeType)
                assertEquals(payload.size.toLong(), staged.byteLength)
                assertEquals(testSha256(payload), staged.sha256)
                assertArrayEquals(payload, staged.file.readBytes())
                assertTrue(staged.file.isFile)
                assertTrue(staged.stagingDirectory.absolutePath.startsWith(context.cacheDir.absolutePath))

                Log.i(TAG, "outgoing_staged_content_uri uri=$source bytes=${staged.byteLength}")
            } finally {
                staged?.cleanupBestEffort { failure ->
                    Log.w(TAG, "outgoing staging cleanup failed", failure)
                }
                context.contentResolver.delete(source, null, null)
            }
            assertFalse("private staging directory should be removed after cleanup", staged?.stagingDirectory?.exists() == true)
        }
    }

    @Test
    fun oversizeContentUriStagingFailureRemovesPrivateDirectory() {
        assumeTrue("MediaStore.Downloads content source is Android Q+ only", Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)

        val displayName = "vibescreen-p0110-outgoing-large-${System.currentTimeMillis()}.txt"
        val payload = "0123456789abcdef".repeat(32).toByteArray(Charsets.UTF_8)
        withTargetContext { context ->
            val source = insertDownloadsSource(context, displayName, TEST_MIME_TYPE, payload)
            val stagingRoot = File(context.cacheDir, "vibescreen-outgoing-files")
            try {
                val thrown = runCatching {
                    OutgoingFileStager(
                        contentResolver = context.contentResolver,
                        cacheDirectory = context.cacheDir,
                        maxDisplayNameLength = 180,
                    ).stage(source, maximumFileBytes = 16)
                }.exceptionOrNull()

                assertTrue(thrown is SelectedFileTooLargeException)
                assertFalse("oversize failure should remove private partial staging directories", stagingRoot.containsStagedChildren())
                Log.i(TAG, "outgoing_staging_oversize_cleanup uri=$source")
            } finally {
                context.contentResolver.delete(source, null, null)
                stagingRoot.deleteRecursively()
            }
        }
    }

    private fun withTargetContext(assertion: (Context) -> Unit) =
        assertion(ApplicationProvider.getApplicationContext())

    private fun insertDownloadsSource(
        context: Context,
        displayName: String,
        mimeType: String,
        payload: ByteArray,
    ): Uri {
        val collection = ContentResolverMediaStoreDownloadsCollection(context.contentResolver)
        val uri = collection.insertPending(displayName, mimeType)
        try {
            collection.openOutputStream(uri)?.use { output -> output.write(payload) }
                ?: throw IOException("Unable to open source downloads entry")
            collection.publish(uri)
            val row = queryDownloadsRow(context, uri)
            assertEquals(displayName, row.displayName)
            assertEquals(TEST_MIME_TYPE, row.mimeType)
            assertEquals(Environment.DIRECTORY_DOWNLOADS + "/", row.relativePath)
            assertEquals(0, row.isPending)
            return uri
        } catch (failure: Throwable) {
            collection.delete(uri)
            throw failure
        }
    }

    private data class DownloadsRow(
        val displayName: String,
        val mimeType: String,
        val relativePath: String,
        val isPending: Int,
    )

    private fun queryDownloadsRow(
        context: Context,
        uri: Uri,
    ): DownloadsRow {
        val projection =
            arrayOf(
                MediaStore.Downloads.DISPLAY_NAME,
                MediaStore.Downloads.MIME_TYPE,
                MediaStore.Downloads.RELATIVE_PATH,
                MediaStore.Downloads.IS_PENDING,
            )
        context.contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
            assertTrue("Downloads source row should be queryable", cursor.moveToFirst())
            return DownloadsRow(
                displayName = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)),
                mimeType = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.MIME_TYPE)),
                relativePath = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Downloads.RELATIVE_PATH)),
                isPending = cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)),
            )
        }
        throw IOException("Downloads source row is unavailable")
    }

    private companion object {
        private const val TEST_MIME_TYPE = "text/plain"
        private const val TAG = "OutgoingFileStagerTest"

        fun File.containsStagedChildren(): Boolean = exists() && listFiles().orEmpty().isNotEmpty()

        fun testSha256(bytes: ByteArray) =
            com.google.protobuf.ByteString.copyFrom(MessageDigest.getInstance("SHA-256").digest(bytes))
    }
}
