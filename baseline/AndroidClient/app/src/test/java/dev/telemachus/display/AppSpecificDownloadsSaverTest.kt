package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.sha256
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.util.concurrent.Callable
import java.util.concurrent.CyclicBarrier
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class AppSpecificDownloadsSaverTest {
    private companion object {
        const val COLLISION_ATTEMPT_LIMIT = 1_000
    }

    @Test
    fun savePublishesAtomicallyAndAvoidsOverwritingExistingName() {
        val directory = Files.createTempDirectory("vibescreen-downloads").toFile()
        try {
            val existing = File(directory, "report.txt")
            existing.writeText("existing")
            val source = File(directory, "source.tmp")
            source.writeText("new-content")

            val saved = AppSpecificDownloadsSaver.save(source, directory, "report.txt")

            assertEquals("report (1).txt", saved.name)
            assertEquals("existing", existing.readText())
            assertEquals("new-content", saved.readText())
            assertFalse(directory.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun saveRetriesDestinationWhenNameIsClaimedDuringCopy() {
        val directory = Files.createTempDirectory("vibescreen-downloads-race").toFile()
        try {
            val source = File(directory, "source.tmp")
            source.writeText("new-content")

            val saved = AppSpecificDownloadsSaver.save(source, directory, "report.txt") { _, output ->
                File(directory, "report.txt").writeText("racing-content")
                output.write("new-content".toByteArray())
            }

            assertEquals("report (1).txt", saved.name)
            assertEquals("racing-content", File(directory, "report.txt").readText())
            assertEquals("new-content", saved.readText())
            assertFalse(directory.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun concurrentSavesWithSameDisplayNamePublishDistinctFiles() {
        val directory = Files.createTempDirectory("vibescreen-downloads-concurrent").toFile()
        val executor = Executors.newFixedThreadPool(2)
        try {
            val first = File(directory, "source-1.tmp").apply { writeText("first-content") }
            val second = File(directory, "source-2.tmp").apply { writeText("second-content") }
            val copyBarrier = CyclicBarrier(2)
            val tasks =
                listOf(first, second).map { source ->
                    Callable {
                        AppSpecificDownloadsSaver.save(source, directory, "report.txt") { file, output ->
                            copyBarrier.await(5, TimeUnit.SECONDS)
                            output.write(file.readBytes())
                        }
                    }
                }

            val saved = executor.invokeAll(tasks).map { it.get(5, TimeUnit.SECONDS) }

            assertEquals(setOf("report.txt", "report (1).txt"), saved.map { it.name }.toSet())
            assertEquals(setOf("first-content", "second-content"), saved.map { it.readText() }.toSet())
            assertFalse(directory.containsPartialDownload())
        } finally {
            executor.shutdownNow()
            directory.deleteRecursively()
        }
    }

    @Test
    fun saveRemovesPartialAndLeavesTargetMissingWhenCopyFails() {
        val directory = Files.createTempDirectory("vibescreen-downloads-failure").toFile()
        try {
            val source = File(directory, "source.tmp")
            source.writeText("source-content")
            val target = File(directory, "incoming.txt")
            val copyFailure = IOException("copy failed")

            val thrown = assertThrows(IOException::class.java) {
                AppSpecificDownloadsSaver.save(source, directory, "incoming.txt") { _, output ->
                    output.write("partial".toByteArray())
                    throw copyFailure
                }
            }

            assertSame(copyFailure, thrown)
            assertFalse(target.exists())
            assertFalse(directory.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun saveRejectsUnsafeDisplayNamesBeforeCreatingArtifacts() {
        val directory = Files.createTempDirectory("vibescreen-downloads-unsafe").toFile()
        try {
            val source = File(directory, "source.tmp")
            source.writeText("source-content")

            assertThrows(IOException::class.java) {
                AppSpecificDownloadsSaver.save(source, directory, "../escape.txt")
            }

            assertTrue(directory.listFiles().orEmpty().single().name == "source.tmp")
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun saveRemovesPartialWhenDestinationNamesAreExhausted() {
        val directory = Files.createTempDirectory("vibescreen-downloads-exhausted").toFile()
        try {
            val source = File(directory, "source.tmp")
            source.writeText("source-content")
            File(directory, "report.txt").writeText("existing")
            for (attempt in 1..COLLISION_ATTEMPT_LIMIT) {
                File(directory, "report ($attempt).txt").writeText("existing-$attempt")
            }

            assertThrows(IOException::class.java) {
                AppSpecificDownloadsSaver.save(source, directory, "report.txt")
            }

            assertEquals("existing", File(directory, "report.txt").readText())
            assertFalse(directory.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun validateDisplayNameRejectsPathSegmentsForAllSaveBackends() {
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("nested/escape.txt")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("nested\\escape.txt")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("..")
        }
    }

    @Test
    fun validateDisplayNameRejectsControlCharactersAndAmbiguousWhitespace() {
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("foo\nbar.txt")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("foo\rbar.txt")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("foo\tbar.txt")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("   ")
        }
        assertThrows(IOException::class.java) {
            AppSpecificDownloadsSaver.validateDisplayName("  report.txt  ")
        }
    }

    @Test
    fun saveHandlesCollisionForExtensionlessMultidotAndDotfileNames() {
        val directory = Files.createTempDirectory("vibescreen-downloads-collision-edges").toFile()
        try {
            val cases = listOf(
                "report" to "report (1)",
                "archive.tar.gz" to "archive.tar (1).gz",
                ".gitignore" to ".gitignore (1)",
                "foo." to "foo. (1)",
            )
            cases.forEachIndexed { index, (displayName, expectedCollisionName) ->
                File(directory, displayName).writeText("existing-$index")
                val source = File(directory, "source-$index.tmp")
                source.writeText("new-$index")

                val saved = AppSpecificDownloadsSaver.save(source, directory, displayName)

                assertEquals(expectedCollisionName, saved.name)
                assertEquals("new-$index", saved.readText())
                assertEquals("existing-$index", File(directory, displayName).readText())
            }
            assertFalse(directory.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun safeDisplayNameNormalizesUnsafeIncomingNamesBeforeSaving() {
        assertEquals("escape.txt", AppSpecificDownloadsSaver.safeDisplayName("../escape.txt", 120))
        assertEquals("file.txt", AppSpecificDownloadsSaver.safeDisplayName("dir/file.txt", 120))
        assertEquals("bad_name.txt", AppSpecificDownloadsSaver.safeDisplayName("bad\u0000name.txt", 120))
        assertEquals("bad_name.txt", AppSpecificDownloadsSaver.safeDisplayName("bad\nname.txt", 120))
        assertEquals("bad_name.txt", AppSpecificDownloadsSaver.safeDisplayName("bad\tname.txt", 120))
        assertEquals("foo.txt", AppSpecificDownloadsSaver.safeDisplayName("  foo.txt  ", 120))
        assertEquals("download.bin", AppSpecificDownloadsSaver.safeDisplayName(".", 120, fallback = "download.bin"))
        assertEquals("download.bin", AppSpecificDownloadsSaver.safeDisplayName("..", 120, fallback = "download.bin"))
        assertEquals("download.bin", AppSpecificDownloadsSaver.safeDisplayName("   ", 120, fallback = "download.bin"))
        assertEquals("abcdef", AppSpecificDownloadsSaver.safeDisplayName("abcdefgh", 6))
    }

    @Test
    fun saveCompletedIncomingFileUsesSafeBasenameAndRemovesStagingFile() {
        val directory = Files.createTempDirectory("vibescreen-completed-save").toFile()
        val downloads = File(directory, "downloads")
        val staging = File(directory, ".vibescreen-staged.partial")
        try {
            val payload = "saved-content".toByteArray()
            staging.writeBytes(payload)
            val completed = completedIncomingFile(staging, "../report.txt", payload)

            val saved = AppSpecificDownloadsSaver.saveCompletedIncomingFile(
                completed = completed,
                downloads = downloads,
                maxDisplayNameLength = 120,
            )

            assertEquals("report.txt", saved.name)
            assertEquals("saved-content", saved.readText())
            assertFalse(staging.exists())
            assertFalse(downloads.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun saveCompletedIncomingFileRemovesStagingAndPartialWhenCopyFails() {
        val directory = Files.createTempDirectory("vibescreen-completed-failure").toFile()
        val downloads = File(directory, "downloads")
        val staging = File(directory, ".vibescreen-staged.partial")
        try {
            val payload = "source-content".toByteArray()
            staging.writeBytes(payload)
            val completed = completedIncomingFile(staging, "incoming.txt", payload)
            val copyFailure = IOException("simulated full disk")

            val thrown = assertThrows(IOException::class.java) {
                AppSpecificDownloadsSaver.saveCompletedIncomingFile(
                    completed = completed,
                    downloads = downloads,
                    maxDisplayNameLength = 120,
                ) { _, output ->
                    output.write("partial".toByteArray())
                    throw copyFailure
                }
            }

            assertSame(copyFailure, thrown)
            assertFalse(staging.exists())
            assertFalse(File(downloads, "incoming.txt").exists())
            assertFalse(downloads.containsPartialDownload())
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun File.containsPartialDownload(): Boolean =
        listFiles().orEmpty().any { it.name.startsWith(".vibescreen-") && it.name.endsWith(".partial") }

    private fun completedIncomingFile(
        staging: File,
        fileName: String,
        payload: ByteArray,
    ): CompletedIncomingFile =
        CompletedIncomingFile(
            transferId = ByteString.copyFromUtf8("completed-${staging.name}"),
            fileName = fileName,
            mimeType = "text/plain",
            stagingFile = staging,
            sha256 = sha256(payload),
        )
}
