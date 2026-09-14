package dev.telemachus.display

import android.annotation.TargetApi
import android.content.ContentResolver
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import dev.telemachus.display.protocol.CompletedIncomingFile
import java.io.File
import java.io.IOException
import java.io.OutputStream

internal class IncomingFileDownloadsSaver(
    private val sdkInt: Int = Build.VERSION.SDK_INT,
    private val appSpecificDownloads: () -> File?,
    private val mediaStoreDownloads: () -> MediaStoreDownloadsCollection,
    private val copy: (File, OutputStream) -> Unit = AppSpecificDownloadsSaver::copyFileTo,
) {
    fun saveCompletedIncomingFile(
        completed: CompletedIncomingFile,
        displayName: String,
        maxDisplayNameLength: Int,
    ): Uri {
        AppSpecificDownloadsSaver.validateDisplayName(displayName)
        if (sdkInt >= Build.VERSION_CODES.Q) {
            return saveToMediaStore(completed, displayName)
        }

        val downloads = appSpecificDownloads() ?: throw IOException("Downloads directory is unavailable")
        val target =
            AppSpecificDownloadsSaver.saveCompletedIncomingFile(
                completed = completed,
                downloads = downloads,
                maxDisplayNameLength = maxDisplayNameLength,
                fallbackDisplayName = displayName,
                copy = copy,
            )
        return Uri.fromFile(target)
    }

    private fun saveToMediaStore(
        completed: CompletedIncomingFile,
        displayName: String,
    ): Uri {
        val downloads = mediaStoreDownloads()
        val entry = downloads.insertPending(
            displayName = displayName,
            mimeType = completed.mimeType.ifBlank { DEFAULT_MIME_TYPE },
        )
        try {
            downloads.openOutputStream(entry)?.use { output ->
                copy(completed.stagingFile, output)
            } ?: throw IOException("Unable to open downloads entry")
            downloads.publish(entry)
            return entry
        } catch (failure: Throwable) {
            try {
                downloads.delete(entry)
            } catch (deleteFailure: Throwable) {
                failure.addSuppressed(deleteFailure)
            }
            throw failure
        }
    }

    companion object {
        const val DEFAULT_MIME_TYPE = "application/octet-stream"
    }
}

internal interface MediaStoreDownloadsCollection {
    fun insertPending(
        displayName: String,
        mimeType: String,
    ): Uri

    fun openOutputStream(uri: Uri): OutputStream?

    fun publish(uri: Uri)

    fun delete(uri: Uri)
}

@TargetApi(Build.VERSION_CODES.Q)
internal class ContentResolverMediaStoreDownloadsCollection(
    private val contentResolver: ContentResolver,
) : MediaStoreDownloadsCollection {
    override fun insertPending(
        displayName: String,
        mimeType: String,
    ): Uri {
        val values =
            ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, displayName)
                put(MediaStore.Downloads.MIME_TYPE, mimeType)
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
        return contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("Unable to create downloads entry")
    }

    override fun openOutputStream(uri: Uri): OutputStream? =
        contentResolver.openOutputStream(uri)

    override fun publish(uri: Uri) {
        val published =
            ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }.let { values ->
                contentResolver.update(uri, values, null, null)
            }
        if (published <= 0) throw IOException("Unable to publish downloads entry")
    }

    override fun delete(uri: Uri) {
        val deleted = contentResolver.delete(uri, null, null)
        if (deleted <= 0) throw IOException("Unable to delete downloads entry")
    }
}
