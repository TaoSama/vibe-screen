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
