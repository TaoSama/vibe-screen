package dev.telemachus.display

import android.net.Uri
import android.os.Build
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.nio.file.Files

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingFileDownloadsSaverTest {
    @Test
    fun androidQAndLaterPublishesThroughMediaStoreAndLeavesStagingLifecycleToCaller() {
        val directory = Files.createTempDirectory("vibescreen-mediastore-save").toFile()
        try {
            val payload = "incoming-media-store".toByteArray()
            val staging = File(directory, ".vibescreen-staged.partial").apply { writeBytes(payload) }
            val mediaStore = FakeMediaStoreDownloadsCollection()

            val saved =
                IncomingFileDownloadsSaver(
                    sdkInt = Build.VERSION_CODES.Q,
                    appSpecificDownloads = { error("Q+ save must not use app-specific Downloads") },
                    mediaStoreDownloads = { mediaStore },
                ).saveCompletedIncomingFile(
                    completed = completedIncomingFile(staging, "incoming.txt", "text/plain", payload),
                    displayName = "incoming.txt",
                    maxDisplayNameLength = 120,
                )

            assertEquals(mediaStore.inserted.single(), saved)
            assertEquals(listOf("incoming.txt"), mediaStore.displayNames)
            assertEquals(listOf("text/plain"), mediaStore.mimeTypes)
            assertEquals(listOf(saved), mediaStore.published)
            assertTrue("Q+ boundary must leave private staging cleanup to MainActivity", staging.exists())
            assertArrayEquals(payload, mediaStore.bytesFor(saved))
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun androidQAndLaterDeletesInsertedEntryWhenCopyFailsAndLeavesStagingLifecycleToCaller() {
        val directory = Files.createTempDirectory("vibescreen-mediastore-copy-failure").toFile()
        try {
            val payload = "incoming-copy-failure".toByteArray()
            val staging = File(directory, ".vibescreen-staged.partial").apply { writeBytes(payload) }
            val mediaStore = FakeMediaStoreDownloadsCollection()
            val copyFailure = IOException("simulated MediaStore write failure")

            val thrown = assertThrows(IOException::class.java) {
                IncomingFileDownloadsSaver(
                    sdkInt = Build.VERSION_CODES.Q,
                    appSpecificDownloads = { error("Q+ save must not use app-specific Downloads") },
                    mediaStoreDownloads = { mediaStore },
                    copy = { _, output ->
                        output.write("partial".toByteArray())
                        throw copyFailure
                    },
                ).saveCompletedIncomingFile(
                    completed = completedIncomingFile(staging, "incoming.txt", "text/plain", payload),
                    displayName = "incoming.txt",
                    maxDisplayNameLength = 120,
                )
            }

            assertSame(copyFailure, thrown)
            val inserted = mediaStore.inserted.single()
            assertEquals(listOf(inserted), mediaStore.deleted)
            assertTrue("failure path must not delete private staging before caller cleanup", staging.exists())
            assertFalse("failed entry should not be published", inserted in mediaStore.published)
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun androidQAndLaterDefaultsBlankMimeTypeBeforeInsert() {
        val directory = Files.createTempDirectory("vibescreen-mediastore-mime").toFile()
        try {
            val payload = byteArrayOf(1, 2, 3)
            val staging = File(directory, ".vibescreen-staged.partial").apply { writeBytes(payload) }
            val mediaStore = FakeMediaStoreDownloadsCollection()

            IncomingFileDownloadsSaver(
                sdkInt = Build.VERSION_CODES.Q,
                appSpecificDownloads = { error("Q+ save must not use app-specific Downloads") },
                mediaStoreDownloads = { mediaStore },
            ).saveCompletedIncomingFile(
                completed = completedIncomingFile(staging, "incoming.bin", "", payload),
                displayName = "incoming.bin",
                maxDisplayNameLength = 120,
            )

            assertEquals(listOf(IncomingFileDownloadsSaver.DEFAULT_MIME_TYPE), mediaStore.mimeTypes)
            assertTrue(staging.exists())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun api26FallbackKeepsAppSpecificDownloadsBehavior() {
        val directory = Files.createTempDirectory("vibescreen-api26-downloads").toFile()
        try {
            val payload = "api26-fallback".toByteArray()
            val downloads = File(directory, "downloads")
            val staging = File(directory, ".vibescreen-staged.partial").apply { writeBytes(payload) }
            val mediaStore = FakeMediaStoreDownloadsCollection()

            val saved =
                IncomingFileDownloadsSaver(
                    sdkInt = Build.VERSION_CODES.O,
                    appSpecificDownloads = { downloads },
                    mediaStoreDownloads = { mediaStore },
                ).saveCompletedIncomingFile(
                    completed = completedIncomingFile(staging, "incoming.txt", "text/plain", payload),
                    displayName = "incoming.txt",
                    maxDisplayNameLength = 120,
                )

            assertEquals(Uri.fromFile(File(downloads, "incoming.txt")), saved)
            assertEquals("api26-fallback", File(downloads, "incoming.txt").readText())
            assertFalse("API26 fallback should retain existing staging cleanup behavior", staging.exists())
            assertTrue(mediaStore.inserted.isEmpty())
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun completedIncomingFile(
        staging: File,
        fileName: String,
        mimeType: String,
        payload: ByteArray,
    ): CompletedIncomingFile =
        CompletedIncomingFile(
            transferId = ByteString.copyFromUtf8("transfer-${staging.name}"),
            fileName = fileName,
            mimeType = mimeType,
            stagingFile = staging,
            sha256 = sha256(payload),
        )

    private class FakeMediaStoreDownloadsCollection : MediaStoreDownloadsCollection {
        val inserted = mutableListOf<Uri>()
        val deleted = mutableListOf<Uri>()
        val published = mutableListOf<Uri>()
        val displayNames = mutableListOf<String>()
        val mimeTypes = mutableListOf<String>()
        private val streams = linkedMapOf<Uri, ByteArrayOutputStream>()

        override fun insertPending(
            displayName: String,
            mimeType: String,
        ): Uri {
            val uri = Uri.parse("content://downloads/fake/${inserted.size + 1}")
            inserted += uri
            displayNames += displayName
            mimeTypes += mimeType
            streams[uri] = ByteArrayOutputStream()
            return uri
        }

        override fun openOutputStream(uri: Uri): OutputStream? = streams[uri]

        override fun publish(uri: Uri) {
            published += uri
        }

        override fun delete(uri: Uri) {
            deleted += uri
            streams.remove(uri)
        }

        fun bytesFor(uri: Uri): ByteArray = requireNotNull(streams[uri]).toByteArray()
    }
}
