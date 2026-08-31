package dev.telemachus.display

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
    fun safeDisplayNameNormalizesUnsafeIncomingNamesBeforeSaving() {
        assertEquals("escape.txt", AppSpecificDownloadsSaver.safeDisplayName("../escape.txt", 120))
        assertEquals("file.txt", AppSpecificDownloadsSaver.safeDisplayName("dir/file.txt", 120))
        assertEquals("bad_name.txt", AppSpecificDownloadsSaver.safeDisplayName("bad\u0000name.txt", 120))
        assertEquals("foo.txt", AppSpecificDownloadsSaver.safeDisplayName("  foo.txt  ", 120))
        assertEquals("download.bin", AppSpecificDownloadsSaver.safeDisplayName(".", 120, fallback = "download.bin"))
        assertEquals("download.bin", AppSpecificDownloadsSaver.safeDisplayName("..", 120, fallback = "download.bin"))
        assertEquals("abcdef", AppSpecificDownloadsSaver.safeDisplayName("abcdefgh", 6))
    }

    private fun File.containsPartialDownload(): Boolean =
        listFiles().orEmpty().any { it.name.startsWith(".vibescreen-") && it.name.endsWith(".partial") }
}
