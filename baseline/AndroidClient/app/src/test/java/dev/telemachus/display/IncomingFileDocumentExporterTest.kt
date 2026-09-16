package dev.telemachus.display

import android.net.Uri
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlinx.coroutines.CancellationException
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingFileDocumentExporterTest {
    @Test
    fun exportCopiesExactBytesWithoutDeletingDestination() {
        val source = Uri.parse("content://downloads/source")
        val destination = Uri.parse("content://documents/destination")
        val payload = "verified incoming payload".toByteArray()
        val output = ByteArrayOutputStream()
        val deleted = mutableListOf<Uri>()

        IncomingFileDocumentExporter(
            openInput = { uri -> if (uri == source) ByteArrayInputStream(payload) else null },
            openOutput = { uri -> if (uri == destination) output else null },
            deleteDestination = deleted::add,
        ).export(source, destination)

        assertArrayEquals(payload, output.toByteArray())
        assertEquals(emptyList<Uri>(), deleted)
    }

    @Test
    fun exportDeletesNewDocumentWhenProviderWriteFails() {
        val source = Uri.parse("content://downloads/source")
        val destination = Uri.parse("content://documents/destination")
        val deleted = mutableListOf<Uri>()

        assertThrows(IOException::class.java) {
            IncomingFileDocumentExporter(
                openInput = { ByteArrayInputStream("payload".toByteArray()) },
                openOutput = { throw IOException("provider rejected write") },
                deleteDestination = deleted::add,
            ).export(source, destination)
        }
        assertEquals(listOf(destination), deleted)
    }

    @Test
    fun exportRejectsOverwritingTheSavedSource() {
        val source = Uri.parse("content://downloads/source")
        val deleted = mutableListOf<Uri>()

        assertThrows(IllegalArgumentException::class.java) {
            IncomingFileDocumentExporter(
                openInput = { error("must not read") },
                openOutput = { error("must not write") },
                deleteDestination = deleted::add,
            ).export(source, source)
        }
        assertEquals(emptyList<Uri>(), deleted)
    }

    @Test
    fun exportDeletesNewDocumentAndPropagatesCancellation() {
        val source = Uri.parse("content://downloads/source")
        val destination = Uri.parse("content://documents/destination")
        val deleted = mutableListOf<Uri>()
        var checks = 0

        assertThrows(CancellationException::class.java) {
            IncomingFileDocumentExporter(
                openInput = { ByteArrayInputStream(ByteArray(128 * 1024)) },
                openOutput = { ByteArrayOutputStream() },
                deleteDestination = deleted::add,
            ).export(source, destination) {
                checks += 1
                if (checks > 1) throw CancellationException("Activity destroyed")
            }
        }

        assertEquals(listOf(destination), deleted)
    }

    @Test
    fun exportReportsCleanupFailureWhenProviderCannotDeletePartialDestination() {
        val source = Uri.parse("content://downloads/source")
        val destination = Uri.parse("content://documents/destination")

        val failure =
            assertThrows(IOException::class.java) {
                IncomingFileDocumentExporter(
                    openInput = { ByteArrayInputStream("payload".toByteArray()) },
                    openOutput = { throw IOException("provider rejected write") },
                    deleteDestination = { false },
                ).export(source, destination)
            }

        assertEquals("provider rejected write", failure.message)
        assertEquals(1, failure.suppressed.size)
        assertEquals("Unable to delete partial export destination", failure.suppressed.single().message)
    }
}
