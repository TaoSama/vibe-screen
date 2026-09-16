package dev.telemachus.display

import android.net.Uri
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
import java.io.ByteArrayInputStream
import java.nio.file.Files

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingFileDownloadsSaverTest {
    @Test
    fun recoveredMediaStoreWriteFailureRetriesTheSamePendingUri() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val store = IncomingFileRecoveryStore(context)
        store.load()?.let(store::discard)
        val payload = "resume-same-uri".toByteArray()
        val staging = File(context.cacheDir, "recovery-write-failure.partial").apply { writeBytes(payload) }
        val mediaStore = FakeMediaStoreDownloadsCollection()
        val recovery = store.adopt(completedIncomingFile(staging, "incoming.txt", "text/plain", payload), "incoming.txt")
        mediaStore.failNextWrite = true
        try {
            assertThrows(IOException::class.java) { recoverySaver(mediaStore).publishRecoveredIncomingFile(recovery, store) }
            val pending = requireNotNull(store.load())
            assertEquals(IncomingFilePublicationState.MEDIASTORE_PENDING, pending.publicationState)
            assertEquals(1, mediaStore.inserted.size)

            val saved = recoverySaver(mediaStore).publishRecoveredIncomingFile(pending, store)

            assertEquals(mediaStore.inserted.single(), saved)
            assertEquals(1, mediaStore.inserted.size)
            assertArrayEquals(payload, mediaStore.bytesFor(saved))
            assertNull(store.load())
        } finally {
            store.load()?.let(store::discard)
            staging.delete()
        }
    }

    @Test
    fun recoveredMediaStoreDetectsAlreadyPublishedRowWithoutRewritingOrReinserting() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val store = IncomingFileRecoveryStore(context)
        store.load()?.let(store::discard)
        val payload = "published-before-marker".toByteArray()
        val staging = File(context.cacheDir, "recovery-published.partial").apply { writeBytes(payload) }
        val mediaStore = FakeMediaStoreDownloadsCollection()
        val recovery = store.adopt(completedIncomingFile(staging, "incoming.txt", "text/plain", payload), "incoming.txt")
        val uri = mediaStore.insertPending("incoming.txt", "text/plain")
        mediaStore.seedPublished(uri, payload)
        val pending = store.markMediaStorePending(recovery, uri.toString())
        try {
            val saved = recoverySaver(mediaStore).publishRecoveredIncomingFile(pending, store)

            assertEquals(uri, saved)
            assertEquals(1, mediaStore.inserted.size)
            assertEquals(0, mediaStore.modeWrites)
            assertTrue(mediaStore.published.isEmpty())
            assertNull(store.load())
        } finally {
            store.load()?.let(store::discard)
            staging.delete()
        }
    }

    @Test
    fun discardPendingMediaStoreRecoveryIsRetryableAfterMetadataClearFailure() {
        val directory = Files.createTempDirectory("vibescreen-discard-retry").toFile()
        val persistence = RetryableClearPersistence()
        val store = IncomingFileRecoveryStore(File(directory, "recovery"), persistence)
        val payload = "discard-pending".toByteArray()
        val staging = File(directory, "staging.partial").apply { writeBytes(payload) }
        val mediaStore = FakeMediaStoreDownloadsCollection()
        val recovery = store.adopt(completedIncomingFile(staging, "incoming.txt", "text/plain", payload), "incoming.txt")
        val uri = mediaStore.insertPending("incoming.txt", "text/plain")
        val pending = store.markMediaStorePending(recovery, uri.toString())
        persistence.failClear = true
        try {
            assertThrows(IOException::class.java) { recoverySaver(mediaStore).discardRecoveredIncomingFile(pending, store) }
            assertEquals(listOf(uri), mediaStore.deleted)
            assertEquals(IncomingFilePublicationState.MEDIASTORE_PENDING, store.load()?.publicationState)

            persistence.failClear = false
            recoverySaver(mediaStore).discardRecoveredIncomingFile(requireNotNull(store.load()), store)

            assertEquals(listOf(uri, uri), mediaStore.deleted)
            assertNull(store.load())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun api26RecoveredPublicationReallocatesTargetClaimedAfterReservation() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val store = IncomingFileRecoveryStore(context)
        store.load()?.let(store::discard)
        val root = Files.createTempDirectory("vibescreen-api26-recovery").toFile()
        val downloads = File(root, "downloads")
        val payload = "new-content".toByteArray()
        val staging = File(root, "staging.partial").apply { writeBytes(payload) }
        val recovery = store.adopt(completedIncomingFile(staging, "report.txt", "text/plain", payload), "report.txt")
        downloads.mkdirs()
        val reserved = store.markAppSpecificTarget(recovery, "report.txt", ".vibescreen-${recovery.recoveryId}.partial")
        File(downloads, "report.txt").writeText("racing-content")
        try {
            val saved =
                IncomingFileDownloadsSaver(
                    sdkInt = Build.VERSION_CODES.O,
                    appSpecificDownloads = { downloads },
                    mediaStoreDownloads = { error("API26 must not use MediaStore") },
                ).publishRecoveredIncomingFile(reserved, store)

            assertEquals(Uri.fromFile(File(downloads, "report (1).txt")), saved)
            assertEquals("racing-content", File(downloads, "report.txt").readText())
            assertArrayEquals(payload, File(downloads, "report (1).txt").readBytes())
            assertNull(store.load())
        } finally {
            store.load()?.let(store::discard)
            root.deleteRecursively()
        }
    }

    @Test
    fun api26DiscardDeletesOnlyACompletedTargetThatMatchesRecovery() {
        val directory = Files.createTempDirectory("vibescreen-api26-discard").toFile()
        val downloads = File(directory, "downloads").apply { mkdirs() }
        val persistence = RetryableClearPersistence()
        val store = IncomingFileRecoveryStore(File(directory, "recovery"), persistence)
        val payload = "completed-before-marker".toByteArray()
        val staging = File(directory, "staging.partial").apply { writeBytes(payload) }
        val recovery = store.adopt(completedIncomingFile(staging, "report.txt", "text/plain", payload), "report.txt")
        val reserved = store.markAppSpecificTarget(recovery, "report.txt", ".vibescreen-${recovery.recoveryId}.partial")
        val target = File(downloads, "report.txt").apply { writeBytes(payload) }
        try {
            IncomingFileDownloadsSaver(
                sdkInt = Build.VERSION_CODES.O,
                appSpecificDownloads = { downloads },
                mediaStoreDownloads = { error("API26 must not use MediaStore") },
            ).discardRecoveredIncomingFile(reserved, store)

            assertFalse(target.exists())
            assertNull(store.load())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun api26DiscardDoesNotDeleteAReservedTargetWithDifferentBytes() {
        val directory = Files.createTempDirectory("vibescreen-api26-discard-collision").toFile()
        val downloads = File(directory, "downloads").apply { mkdirs() }
        val persistence = RetryableClearPersistence()
        val store = IncomingFileRecoveryStore(File(directory, "recovery"), persistence)
        val payload = "expected".toByteArray()
        val staging = File(directory, "staging.partial").apply { writeBytes(payload) }
        val recovery = store.adopt(completedIncomingFile(staging, "report.txt", "text/plain", payload), "report.txt")
        val reserved = store.markAppSpecificTarget(recovery, "report.txt", ".vibescreen-${recovery.recoveryId}.partial")
        val target = File(downloads, "report.txt").apply { writeText("someone-else") }
        try {
            IncomingFileDownloadsSaver(
                sdkInt = Build.VERSION_CODES.O,
                appSpecificDownloads = { downloads },
                mediaStoreDownloads = { error("API26 must not use MediaStore") },
            ).discardRecoveredIncomingFile(reserved, store)

            assertEquals("someone-else", target.readText())
            assertNull(store.load())
        } finally {
            directory.deleteRecursively()
        }
    }

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
    fun api26FallbackLeavesPrivateSourceLifecycleToCaller() {
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
            assertTrue("API26 fallback must retain recovery source for caller cleanup", staging.exists())
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

    private fun recoverySaver(mediaStore: FakeMediaStoreDownloadsCollection): IncomingFileDownloadsSaver =
        IncomingFileDownloadsSaver(
            sdkInt = Build.VERSION_CODES.Q,
            appSpecificDownloads = { error("Q+ recovery must not use app-specific Downloads") },
            mediaStoreDownloads = { mediaStore },
        )

    private class FakeMediaStoreDownloadsCollection : MediaStoreDownloadsCollection {
        val inserted = mutableListOf<Uri>()
        val deleted = mutableListOf<Uri>()
        val published = mutableListOf<Uri>()
        val displayNames = mutableListOf<String>()
        val mimeTypes = mutableListOf<String>()
        private val streams = linkedMapOf<Uri, ByteArrayOutputStream>()
        private val pending = linkedMapOf<Uri, Boolean>()
        var failNextWrite = false
        var modeWrites = 0

        override fun insertPending(
            displayName: String,
            mimeType: String,
        ): Uri {
            val uri = Uri.parse("content://downloads/fake/${inserted.size + 1}")
            inserted += uri
            displayNames += displayName
            mimeTypes += mimeType
            streams[uri] = ByteArrayOutputStream()
            pending[uri] = true
            return uri
        }

        override fun openOutputStream(uri: Uri): OutputStream? = streams[uri]

        override fun openOutputStream(uri: Uri, mode: String): OutputStream? {
            modeWrites += 1
            if (failNextWrite) {
                failNextWrite = false
                throw IOException("injected write failure")
            }
            return ByteArrayOutputStream().also { streams[uri] = it }
        }

        override fun openInputStream(uri: Uri) = ByteArrayInputStream(bytesFor(uri))

        override fun query(uri: Uri): MediaStoreDownloadsEntry? =
            pending[uri]?.let(::MediaStoreDownloadsEntry)

        override fun publish(uri: Uri) {
            published += uri
            pending[uri] = false
        }

        override fun delete(uri: Uri) {
            deleted += uri
            streams.remove(uri)
            pending.remove(uri)
        }

        fun bytesFor(uri: Uri): ByteArray = requireNotNull(streams[uri]).toByteArray()

        fun seedPublished(uri: Uri, payload: ByteArray) {
            streams[uri] = ByteArrayOutputStream().apply { write(payload) }
            pending[uri] = false
        }
    }

    private class RetryableClearPersistence : IncomingFileRecoveryMetadataPersistence {
        private val values = linkedMapOf<String, Any>()
        var failClear = false

        override fun read(): Map<String, *> = values.toMap()

        override fun persist(values: Map<String, Any>): Boolean {
            this.values.clear()
            this.values.putAll(values)
            return true
        }

        override fun clear(): Boolean {
            if (failClear) return false
            values.clear()
            return true
        }
    }
}
