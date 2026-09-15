package dev.telemachus.display

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import java.io.File
import java.nio.file.Files

@RunWith(RobolectricTestRunner::class)
class OutgoingFileStagerTest {
    @Test
    fun stagesResolverBytesMetadataDigestAndCleansPrivateDirectory() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val source = Files.createTempFile("vibescreen-source-", ".txt").toFile()
        val payload = "outbound staging smoke".toByteArray(Charsets.UTF_8)
        source.writeBytes(payload)
        val cache = Files.createTempDirectory("vibescreen-outgoing-stager-test-").toFile()
        try {
            val staged = OutgoingFileStager(context.contentResolver, cache, maxDisplayNameLength = 120)
                .stage(Uri.fromFile(source), maximumFileBytes = 1024)

            assertEquals(source.name, staged.displayName)
            assertEquals(OutgoingFileStager.DEFAULT_MIME_TYPE, staged.mimeType)
            assertEquals(source.name, staged.file.name)
            assertEquals(payload.size.toLong(), staged.byteLength)
            assertEquals(OutgoingFileStager.sha256(payload), staged.sha256)
            assertArrayEquals(payload, staged.file.readBytes())
            assertTrue(staged.file.parentFile == staged.stagingDirectory)
            assertTrue(staged.stagingDirectory.absolutePath.startsWith(cache.absolutePath))

            staged.cleanup()

            assertFalse(staged.stagingDirectory.exists())
        } finally {
            source.delete()
            cache.deleteRecursively()
        }
    }

    @Test
    fun oversizeFailureDeletesPartiallyStagedDirectory() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val source = Files.createTempFile("vibescreen-large-source-", ".txt").toFile()
        source.writeText("0123456789abcdef")
        val cache = Files.createTempDirectory("vibescreen-outgoing-stager-large-").toFile()
        try {
            val thrown = runCatching {
                OutgoingFileStager(context.contentResolver, cache, maxDisplayNameLength = 120)
                    .stage(Uri.fromFile(source), maximumFileBytes = 4)
            }.exceptionOrNull()

            assertTrue(thrown is SelectedFileTooLargeException)
            assertFalse(cache.resolve("vibescreen-outgoing-files").containsStagedChildren())
        } finally {
            source.delete()
            cache.deleteRecursively()
        }
    }

    @Test
    fun safeDisplayNameKeepsBasenameAndFallbackPolicy() {
        assertEquals("report.txt", OutgoingFileStager.safeDisplayName("nested/report.txt", 120))
        assertEquals("transfer.bin", OutgoingFileStager.safeDisplayName("../", 120))
    }

    @Test
    fun ownershipTransferKeepsStagingUntilExplicitOwnerCleanup() = runBlocking {
        val staged = stagedOutgoingFile("owned.txt", "owned-by-product-session".toByteArray(Charsets.UTF_8))

        staged.transferOwnershipOrCleanup { markOwned ->
            markOwned()
        }

        assertTrue(staged.stagingDirectory.exists())
        assertTrue(OutgoingFileStagingOwner.cleanupToken(staged))
        assertFalse(staged.stagingDirectory.exists())
    }

    @Test
    fun cancellationBeforeOwnershipTransferDeletesStagingAndRethrows() = runBlocking {
        val staged = stagedOutgoingFile("cancel-window.txt", "cancel-before-owner".toByteArray(Charsets.UTF_8))

        val thrown = runCatching {
            staged.transferOwnershipOrCleanup {
                throw CancellationException("main-dispatch-cancelled")
            }
        }.exceptionOrNull()

        assertTrue(thrown is CancellationException)
        assertFalse(staged.stagingDirectory.exists())
    }

    @Test
    fun unownedStagingReturnPathDeletesDirectory() = runBlocking {
        val staged = stagedOutgoingFile("stale-session.txt", "stale-session-bytes".toByteArray(Charsets.UTF_8))

        staged.transferOwnershipOrCleanup { "stale" }

        assertFalse(staged.stagingDirectory.exists())
    }

    private companion object {
        fun File.containsStagedChildren(): Boolean = exists() && listFiles().orEmpty().isNotEmpty()

        fun stagedOutgoingFile(
            displayName: String,
            payload: ByteArray,
        ): StagedOutgoingFile {
            val directory = Files.createTempDirectory("vibescreen-staged-owner-").toFile()
            val file = File(directory, displayName).also { it.writeBytes(payload) }
            return StagedOutgoingFile(
                file = file,
                stagingDirectory = directory,
                mimeType = "text/plain",
                displayName = displayName,
                byteLength = payload.size.toLong(),
                sha256 = OutgoingFileStager.sha256(payload),
            )
        }
    }
}
