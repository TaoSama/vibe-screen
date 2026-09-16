package dev.telemachus.display

import android.annotation.TargetApi
import android.content.ContentResolver
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import dev.telemachus.display.protocol.CompletedIncomingFile
import com.google.protobuf.ByteString
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

internal class IncomingFileDownloadsSaver(
    private val sdkInt: Int = Build.VERSION.SDK_INT,
    private val appSpecificDownloads: () -> File?,
    private val mediaStoreDownloads: () -> MediaStoreDownloadsCollection,
    private val copy: (File, OutputStream) -> Unit = AppSpecificDownloadsSaver::copyFileTo,
) {
    fun publishRecoveredIncomingFile(
        recovery: RecoveredIncomingFile,
        store: IncomingFileRecoveryStore,
    ): Uri {
        val lease = store.beginPublication(recovery) ?: throw IOException("Incoming file publication is already in progress")
        lease.use {
            var current = store.load() ?: throw IOException("Incoming file recovery is no longer pending")
            if (current.recoveryId != recovery.recoveryId) throw IOException("Incoming file recovery ownership changed")
            if (current.publicationState == IncomingFilePublicationState.PUBLISHED) {
                val published = Uri.parse(current.publishedUri)
                store.clearPublished(current)
                return published
            }
            val published =
                if (sdkInt >= Build.VERSION_CODES.Q) {
                    publishRecoveredToMediaStore(current, store)
                } else {
                    publishRecoveredToAppSpecificDownloads(current, store)
                }
            current = store.markPublished(published.first, published.second.toString())
            store.clearPublished(current)
            return published.second
        }
    }

    fun discardRecoveredIncomingFile(
        recovery: RecoveredIncomingFile,
        store: IncomingFileRecoveryStore,
    ) {
        val lease = store.beginPublication(recovery) ?: throw IOException("Incoming file publication is already in progress")
        lease.use {
            val current = store.load() ?: return
            if (current.recoveryId != recovery.recoveryId) throw IOException("Incoming file recovery ownership changed")
            when (current.publicationState) {
                IncomingFilePublicationState.MEDIASTORE_PENDING ->
                    mediaStoreDownloads().delete(Uri.parse(current.mediaStorePendingUri))
                IncomingFilePublicationState.APP_SPECIFIC_TARGET -> {
                    val downloads = appSpecificDownloads() ?: throw IOException("Downloads directory is unavailable")
                    val partial = File(downloads, current.appSpecificPartialName)
                    if (partial.exists() && !partial.delete()) throw IOException("Unable to delete pending downloads file")
                    val target = File(downloads, current.appSpecificTargetName)
                    if (AppSpecificDownloadsSaver.matches(target, current.byteLength, current.sha256) && !target.delete()) {
                        throw IOException("Unable to delete recovered downloads file")
                    }
                }
                IncomingFilePublicationState.PUBLISHED -> {
                    store.clearPublished(current)
                    return
                }
                IncomingFilePublicationState.RECEIVED -> Unit
            }
            store.discard(current)
        }
    }

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

    private fun publishRecoveredToMediaStore(
        recovery: RecoveredIncomingFile,
        store: IncomingFileRecoveryStore,
    ): Pair<RecoveredIncomingFile, Uri> {
        val downloads = mediaStoreDownloads()
        val pending =
            when (recovery.publicationState) {
                IncomingFilePublicationState.RECEIVED -> {
                    val entry = downloads.insertPending(
                        displayName = recovery.displayName,
                        mimeType = recovery.mimeType.ifBlank { DEFAULT_MIME_TYPE },
                    )
                    try {
                        store.markMediaStorePending(recovery, entry.toString())
                    } catch (failure: Throwable) {
                        runCatching { downloads.delete(entry) }.exceptionOrNull()?.let(failure::addSuppressed)
                        throw failure
                    }
                }
                IncomingFilePublicationState.MEDIASTORE_PENDING -> recovery
                else -> throw IOException("Incoming recovery has an incompatible publication target")
            }
        val entry = Uri.parse(pending.mediaStorePendingUri)
        val snapshot = downloads.query(entry) ?: throw IOException("Pending downloads entry is unavailable")
        if (!snapshot.pending) {
            verifyMediaStoreBytes(downloads, entry, pending)
            return pending to entry
        }
        downloads.openOutputStream(entry, "wt")?.use { output ->
            copy(pending.payloadFile, output)
        } ?: throw IOException("Unable to open downloads entry")
        verifyMediaStoreBytes(downloads, entry, pending)
        downloads.publish(entry)
        return pending to entry
    }

    private fun publishRecoveredToAppSpecificDownloads(
        recovery: RecoveredIncomingFile,
        store: IncomingFileRecoveryStore,
    ): Pair<RecoveredIncomingFile, Uri> {
        val downloads = appSpecificDownloads() ?: throw IOException("Downloads directory is unavailable")
        var reserved =
            when (recovery.publicationState) {
                IncomingFilePublicationState.RECEIVED -> {
                    val target = AppSpecificDownloadsSaver.allocateStablePublication(
                        downloads = downloads,
                        recoveryId = recovery.recoveryId,
                        displayName = recovery.displayName,
                    )
                    store.markAppSpecificTarget(recovery, target.target.name, target.partial.name)
                }
                IncomingFilePublicationState.APP_SPECIFIC_TARGET -> recovery
                else -> throw IOException("Incoming recovery has an incompatible publication target")
            }
        val target = File(downloads, reserved.appSpecificTargetName)
        if (AppSpecificDownloadsSaver.matches(target, reserved.byteLength, reserved.sha256)) {
            return reserved to Uri.fromFile(target)
        }
        if (target.exists()) {
            val replacement =
                AppSpecificDownloadsSaver.allocateStablePublication(
                    downloads = downloads,
                    recoveryId = reserved.recoveryId,
                    displayName = reserved.displayName,
                )
            reserved =
                store.markAppSpecificTarget(
                    reserved,
                    replacement.target.name,
                    replacement.partial.name,
                )
        }
        val currentTarget = File(downloads, reserved.appSpecificTargetName)
        val currentPartial = File(downloads, reserved.appSpecificPartialName)
        AppSpecificDownloadsSaver.writeStablePartial(reserved.payloadFile, currentPartial, copy)
        AppSpecificDownloadsSaver.publishStablePartial(currentPartial, currentTarget)
        return reserved to Uri.fromFile(currentTarget)
    }

    private fun verifyMediaStoreBytes(
        downloads: MediaStoreDownloadsCollection,
        uri: Uri,
        recovery: RecoveredIncomingFile,
    ) {
        val digest = MessageDigest.getInstance("SHA-256")
        var length = 0L
        downloads.openInputStream(uri)?.use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) {
                    digest.update(buffer, 0, read)
                    length += read
                }
            }
        } ?: throw IOException("Unable to verify downloads entry")
        if (length != recovery.byteLength || ByteString.copyFrom(digest.digest()) != recovery.sha256) {
            throw IOException("Downloads entry verification failed")
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

    fun openOutputStream(uri: Uri, mode: String): OutputStream? = openOutputStream(uri)

    fun openInputStream(uri: Uri): InputStream? = throw IOException("Downloads entry verification is unavailable")

    fun query(uri: Uri): MediaStoreDownloadsEntry? = throw IOException("Downloads entry query is unavailable")

    fun publish(uri: Uri)

    fun delete(uri: Uri)
}

internal data class MediaStoreDownloadsEntry(val pending: Boolean)

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

    override fun openOutputStream(uri: Uri, mode: String): OutputStream? =
        contentResolver.openOutputStream(uri, mode)

    override fun openInputStream(uri: Uri): InputStream? = contentResolver.openInputStream(uri)

    override fun query(uri: Uri): MediaStoreDownloadsEntry? =
        contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) return@use null
            MediaStoreDownloadsEntry(
                pending = cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.Downloads.IS_PENDING)) != 0,
            )
        }

    override fun publish(uri: Uri) {
        val published =
            ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }.let { values ->
                contentResolver.update(uri, values, null, null)
            }
        if (published <= 0) throw IOException("Unable to publish downloads entry")
    }

    override fun delete(uri: Uri) {
        contentResolver.delete(uri, null, null)
    }
}
