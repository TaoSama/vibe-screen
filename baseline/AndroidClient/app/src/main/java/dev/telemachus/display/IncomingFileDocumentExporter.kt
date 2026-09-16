package dev.telemachus.display

import android.content.ContentResolver
import android.net.Uri
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

internal class IncomingFileDocumentExporter(
    private val openInput: (Uri) -> InputStream?,
    private val openOutput: (Uri) -> OutputStream?,
    private val deleteDestination: (Uri) -> Boolean,
) {
    constructor(contentResolver: ContentResolver) : this(
        openInput = contentResolver::openInputStream,
        openOutput = { uri -> contentResolver.openOutputStream(uri, "w") },
        deleteDestination = { uri -> contentResolver.delete(uri, null, null) > 0 },
    )

    fun export(
        source: Uri,
        destination: Uri,
        checkCancelled: () -> Unit = {},
    ) {
        require(source != destination) { "Export source and destination must differ" }
        try {
            openInput(source)?.use { input ->
                openOutput(destination)?.use { output ->
                    val buffer = ByteArray(COPY_BUFFER_BYTES)
                    while (true) {
                        checkCancelled()
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                    }
                    checkCancelled()
                } ?: throw IOException("Unable to open export destination")
            } ?: throw IOException("Unable to open saved incoming file")
        } catch (failure: Throwable) {
            try {
                // ACTION_CREATE_DOCUMENT owns a newly created destination. A
                // failed or cancelled copy must not leave that partial file.
                if (!deleteDestination(destination)) {
                    throw IOException("Unable to delete partial export destination")
                }
            } catch (deleteFailure: Throwable) {
                failure.addSuppressed(deleteFailure)
            }
            throw failure
        }
    }

    private companion object {
        const val COPY_BUFFER_BYTES = 64 * 1024
    }
}
