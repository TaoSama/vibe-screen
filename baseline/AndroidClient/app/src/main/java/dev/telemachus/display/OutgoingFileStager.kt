package dev.telemachus.display

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.OutgoingFileSnapshot
import kotlinx.coroutines.CancellationException
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal data class StagedOutgoingFile(
    val file: File,
    val stagingDirectory: File,
    val mimeType: String,
    val displayName: String,
    val byteLength: Long,
    val sha256: ByteString,
) {
    fun snapshot(): OutgoingFileSnapshot =
        OutgoingFileSnapshot(
            fileName = file.name,
            byteLength = byteLength,
            sha256 = sha256,
        )

    fun cleanup() {
        if (stagingDirectory.exists() && !stagingDirectory.deleteRecursively()) {
            throw IOException("Unable to delete outgoing file staging directory")
        }
    }

    fun cleanupBestEffort(onFailure: (Throwable) -> Unit = {}) {
        runCatching { cleanup() }.onFailure(onFailure)
    }

    suspend fun <T> transferOwnershipOrCleanup(
        onCleanupFailure: (Throwable) -> Unit = {},
        block: suspend (markOwned: () -> Unit) -> T,
    ): T {
        val ownershipTransferred = AtomicBoolean(false)
        try {
            return block { ownershipTransferred.set(true) }
        } catch (exception: CancellationException) {
            throw exception
        } finally {
            if (!ownershipTransferred.get()) {
                cleanupBestEffort(onCleanupFailure)
            }
        }
    }
}

internal object OutgoingFileStagingOwner {
    fun cleanupToken(
        token: Any?,
        onFailure: (Throwable) -> Unit = {},
    ): Boolean {
        val stagedFile = token as? StagedOutgoingFile ?: return false
        stagedFile.cleanupBestEffort(onFailure)
        return true
    }
}

internal class SelectedFileTooLargeException : IOException("selected_file_exceeds_transfer_limit")

internal class OutgoingFileStager(
    private val contentResolver: ContentResolver,
    private val cacheDirectory: File,
    private val maxDisplayNameLength: Int,
) {
    fun stage(
        uri: Uri,
        maximumFileBytes: Long,
    ): StagedOutgoingFile {
        val mimeType = contentResolver.getType(uri) ?: DEFAULT_MIME_TYPE
        val safeName = safeDisplayName(displayNameForUri(uri) ?: uri.lastPathSegment, maxDisplayNameLength)
        val directory = File(cacheDirectory, STAGING_ROOT + "/" + UUID.randomUUID())
        if (!directory.mkdirs()) throw IOException("Unable to create outgoing file staging directory")
        val staged = File(directory, safeName)
        val digest = MessageDigest.getInstance("SHA-256")
        var total = 0L
        try {
            contentResolver.openInputStream(uri).use { input ->
                if (input == null) throw IOException("Unable to open selected file")
                FileOutputStream(staged).use { output ->
                    val buffer = ByteArray(COPY_BUFFER_BYTES)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read.toLong()
                        if (total > maximumFileBytes) {
                            throw SelectedFileTooLargeException()
                        }
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                    }
                }
            }
            return StagedOutgoingFile(
                file = staged,
                stagingDirectory = directory,
                mimeType = mimeType,
                displayName = safeDisplayName(staged.name, maxDisplayNameLength),
                byteLength = total,
                sha256 = ByteString.copyFrom(digest.digest()),
            )
        } catch (failure: Throwable) {
            directory.deleteRecursively()
            throw failure
        }
    }

    private fun displayNameForUri(uri: Uri): String? =
        runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (index >= 0) cursor.getString(index) else null
                } else {
                    null
                }
            }
        }.getOrNull()

    companion object {
        const val DEFAULT_MIME_TYPE = "application/octet-stream"
        private const val COPY_BUFFER_BYTES = 64 * 1024
        private const val STAGING_ROOT = "vibescreen-outgoing-files"

        fun safeDisplayName(
            displayName: String?,
            maxDisplayNameLength: Int,
        ): String = AppSpecificDownloadsSaver.safeDisplayName(displayName, maxDisplayNameLength)

        fun sha256(bytes: ByteArray): ByteString = dev.telemachus.display.protocol.sha256(bytes)
    }
}
