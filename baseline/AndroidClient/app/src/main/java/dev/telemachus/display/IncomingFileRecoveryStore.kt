package dev.telemachus.display

import android.content.Context
import android.content.SharedPreferences
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.SHA256_BYTES
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.Base64
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal enum class IncomingFilePublicationState {
    RECEIVED,
    MEDIASTORE_PENDING,
    APP_SPECIFIC_TARGET,
    PUBLISHED,
}

internal data class RecoveredIncomingFile(
    val recoveryId: String,
    val transferId: ByteString,
    val displayName: String,
    val mimeType: String,
    val byteLength: Long,
    val sha256: ByteString,
    val payloadFile: File,
    val publicationState: IncomingFilePublicationState = IncomingFilePublicationState.RECEIVED,
    val mediaStorePendingUri: String = "",
    val appSpecificTargetName: String = "",
    val appSpecificPartialName: String = "",
    val publishedUri: String = "",
) {
    fun asCompletedIncomingFile(): CompletedIncomingFile =
        CompletedIncomingFile(transferId, displayName, mimeType, payloadFile, sha256)
}

internal interface IncomingFileRecoveryMetadataPersistence {
    fun read(): Map<String, *>

    fun persist(values: Map<String, Any>): Boolean

    fun clear(): Boolean
}

internal interface IncomingFileRecoveryFileOperations {
    fun ensureDirectory(directory: File)

    fun copyAndSync(
        source: File,
        destination: File,
    ): IncomingFileRecoveryCopy

    fun atomicMove(
        source: File,
        destination: File,
    )

    fun delete(file: File): Boolean

    fun exists(file: File): Boolean

    fun listFiles(directory: File): List<File>

    fun isRegularFile(file: File): Boolean

    fun digest(file: File): ByteString
}

internal data class IncomingFileRecoveryCopy(
    val byteLength: Long,
    val sha256: ByteString,
)

internal fun interface IncomingFileDurableOwner {
    @Throws(IOException::class)
    fun adoptBeforeAcknowledgement(completed: CompletedIncomingFile): CompletedIncomingFile

    companion object {
        val PASS_THROUGH = IncomingFileDurableOwner { completed -> completed }
    }
}

private class IncomingFileRecoveryCorruptionException(
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause)

/** Owns one verified incoming file until Downloads publication succeeds or the user discards it. */
internal class IncomingFileRecoveryStore(
    private val directory: File,
    private val persistence: IncomingFileRecoveryMetadataPersistence,
    private val fileOperations: IncomingFileRecoveryFileOperations = SystemIncomingFileRecoveryFileOperations,
    private val newRecoveryId: () -> String = { UUID.randomUUID().toString() },
) {
    constructor(context: Context) : this(
        directory = File(context.applicationContext.filesDir, RECOVERY_DIRECTORY_NAME),
        persistence =
            SharedPreferencesIncomingFileRecoveryMetadataPersistence(
                context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE),
            ),
    )

    @Synchronized
    @Throws(IOException::class)
    fun adopt(
        completed: CompletedIncomingFile,
        safeDisplayName: String,
    ): RecoveredIncomingFile {
        return synchronized(PROCESS_LOCK) {
            adoptLocked(completed, safeDisplayName)
        }
    }

    @Throws(IOException::class)
    fun adoptBeforeAcknowledgement(
        completed: CompletedIncomingFile,
        maxDisplayNameLength: Int,
        fallbackDisplayName: String,
    ): CompletedIncomingFile =
        synchronized(PROCESS_LOCK) {
            val safeDisplayName =
                AppSpecificDownloadsSaver.safeDisplayName(
                    completed.fileName,
                    maxDisplayNameLength,
                    fallbackDisplayName,
                )
            val existing = loadLocked()
            val recovery =
                if (existing != null && existing.matches(completed)) {
                    existing
                } else {
                    adoptLocked(completed, safeDisplayName, existing)
                }
            if (completed.stagingFile.canonicalFile != recovery.payloadFile.canonicalFile &&
                completed.stagingFile.exists()
            ) {
                completed.stagingFile.delete()
            }
            recovery.asCompletedIncomingFile()
        }

    private fun adoptLocked(
        completed: CompletedIncomingFile,
        safeDisplayName: String,
        existing: RecoveredIncomingFile? = loadLocked(),
    ): RecoveredIncomingFile {
        AppSpecificDownloadsSaver.validateDisplayName(safeDisplayName)
        require(!completed.transferId.isEmpty) { "Incoming recovery transfer ID is required" }
        require(completed.sha256.size() == SHA256_BYTES) { "Incoming recovery digest must be SHA-256" }
        if (existing != null) throw IOException("Another incoming file is pending recovery")
        if (!fileOperations.isRegularFile(completed.stagingFile)) {
            throw IOException("Incoming staging file is unavailable")
        }

        fileOperations.ensureDirectory(directory)
        val recoveryId = newRecoveryId().also(::validateRecoveryId)
        val payloadFile = File(directory, payloadFileName(recoveryId))
        val temporaryFile = File(directory, temporaryFileName(recoveryId))
        checkControlledFile(payloadFile)
        checkControlledFile(temporaryFile)
        if (fileOperations.exists(payloadFile) || fileOperations.exists(temporaryFile)) {
            throw IOException("Incoming recovery identifier already exists")
        }

        var published = false
        var retainPublishedAfterFailure = false
        try {
            val copied = fileOperations.copyAndSync(completed.stagingFile, temporaryFile)
            if (copied.sha256 != completed.sha256) {
                throw IOException("Incoming recovery digest mismatch")
            }
            if (temporaryFile.length() != copied.byteLength) {
                throw IOException("Incoming recovery length mismatch")
            }
            fileOperations.atomicMove(temporaryFile, payloadFile)
            published = true
            if (!fileOperations.isRegularFile(payloadFile) || payloadFile.length() != copied.byteLength) {
                throw IOException("Incoming recovery payload was not published completely")
            }
            if (fileOperations.digest(payloadFile) != completed.sha256) {
                throw IOException("Published incoming recovery digest mismatch")
            }

            val recovery =
                RecoveredIncomingFile(
                    recoveryId = recoveryId,
                    transferId = completed.transferId,
                    displayName = safeDisplayName,
                    mimeType = completed.mimeType,
                    byteLength = copied.byteLength,
                    sha256 = completed.sha256,
                    payloadFile = payloadFile,
                )
            try {
                if (!persistence.persist(recovery.toMetadata())) {
                    throw IOException("Unable to persist incoming file recovery metadata")
                }
            } catch (failure: Exception) {
                val cleared = try {
                    persistence.clear()
                } catch (clearFailure: Exception) {
                    failure.addSuppressed(clearFailure)
                    false
                }
                if (!cleared) {
                    retainPublishedAfterFailure = true
                    failure.addSuppressed(IOException("Unable to roll back incoming file recovery metadata"))
                }
                throw failure
            }
            return recovery
        } catch (failure: Exception) {
            cleanupAfterFailedAdoption(
                temporaryFile,
                if (published && !retainPublishedAfterFailure) payloadFile else null,
                failure,
            )
            throw failure
        }
    }

    @Throws(IOException::class)
    fun load(): RecoveredIncomingFile? = synchronized(PROCESS_LOCK) { loadLocked() }

    @Throws(IOException::class)
    fun beginPublication(record: RecoveredIncomingFile): IncomingFilePublicationLease? =
        synchronized(PROCESS_LOCK) {
            val current = loadLocked() ?: throw IOException("Incoming file recovery is no longer pending")
            if (current.recoveryId != record.recoveryId) throw IOException("Incoming file recovery ownership changed")
            if (!ACTIVE_PUBLICATIONS.add(record.recoveryId)) return@synchronized null
            IncomingFilePublicationLease(record.recoveryId)
        }

    @Throws(IOException::class)
    fun markMediaStorePending(record: RecoveredIncomingFile, uri: String): RecoveredIncomingFile =
        updatePublication(record) { current ->
            if (current.publicationState != IncomingFilePublicationState.RECEIVED) {
                throw IOException("Incoming recovery cannot reserve a MediaStore target")
            }
            if (uri.isBlank()) throw IOException("Pending MediaStore URI is required")
            current.copy(
                publicationState = IncomingFilePublicationState.MEDIASTORE_PENDING,
                mediaStorePendingUri = uri,
            )
        }

    @Throws(IOException::class)
    fun markAppSpecificTarget(
        record: RecoveredIncomingFile,
        targetName: String,
        partialName: String,
    ): RecoveredIncomingFile =
        updatePublication(record) { current ->
            if (current.publicationState != IncomingFilePublicationState.RECEIVED &&
                current.publicationState != IncomingFilePublicationState.APP_SPECIFIC_TARGET
            ) {
                throw IOException("Incoming recovery cannot reserve an app-specific target")
            }
            AppSpecificDownloadsSaver.validateDisplayName(targetName)
            validateAppSpecificPartialName(partialName, current.recoveryId)
            current.copy(
                publicationState = IncomingFilePublicationState.APP_SPECIFIC_TARGET,
                appSpecificTargetName = targetName,
                appSpecificPartialName = partialName,
            )
        }

    @Throws(IOException::class)
    fun markPublished(record: RecoveredIncomingFile, uri: String): RecoveredIncomingFile =
        updatePublication(record) { current ->
            if (current.publicationState == IncomingFilePublicationState.RECEIVED) {
                throw IOException("Incoming recovery target must be reserved before publication")
            }
            if (uri.isBlank()) throw IOException("Published URI is required")
            current.copy(
                publicationState = IncomingFilePublicationState.PUBLISHED,
                publishedUri = uri,
            )
        }

    private fun loadLocked(): RecoveredIncomingFile? {
        fileOperations.ensureDirectory(directory)
        val values = persistence.read()
        if (values.isEmpty()) {
            deleteControlledFiles()
            return null
        }
        return try {
            decodeAndValidate(values)
        } catch (failure: IncomingFileRecoveryCorruptionException) {
            clearCorruptRecovery(failure)
            null
        }
    }

    @Throws(IOException::class)
    fun discard(record: RecoveredIncomingFile) = synchronized(PROCESS_LOCK) { clearPersistedRecovery(record) }

    @Throws(IOException::class)
    fun clearAfterSaved(record: RecoveredIncomingFile) = synchronized(PROCESS_LOCK) { clearPersistedRecovery(record) }

    @Throws(IOException::class)
    fun clearPublished(record: RecoveredIncomingFile) =
        synchronized(PROCESS_LOCK) {
            val current = loadLocked() ?: throw IOException("Incoming file recovery is no longer pending")
            if (current.recoveryId != record.recoveryId) throw IOException("Incoming file recovery ownership changed")
            if (current.publicationState != IncomingFilePublicationState.PUBLISHED) {
                throw IOException("Incoming file recovery has not been published")
            }
            if (fileOperations.exists(current.payloadFile)) deleteOrThrow(current.payloadFile)
            if (!persistence.clear()) throw IOException("Unable to clear published incoming file recovery metadata")
        }

    private fun updatePublication(
        record: RecoveredIncomingFile,
        update: (RecoveredIncomingFile) -> RecoveredIncomingFile,
    ): RecoveredIncomingFile =
        synchronized(PROCESS_LOCK) {
            val current = loadLocked() ?: throw IOException("Incoming file recovery is no longer pending")
            if (current.recoveryId != record.recoveryId) throw IOException("Incoming file recovery ownership changed")
            val updated = update(current)
            if (!persistence.persist(updated.toMetadata())) {
                throw IOException("Unable to persist incoming file publication state")
            }
            updated
        }

    private fun clearPersistedRecovery(record: RecoveredIncomingFile) {
        fileOperations.ensureDirectory(directory)
        val values = persistence.read()
        if (values.isEmpty()) throw IOException("Incoming file recovery is no longer pending")
        val persistedId = values[RECOVERY_ID_KEY] as? String
        if (persistedId != record.recoveryId) throw IOException("Incoming file recovery ownership changed")
        val payload = controlledPayloadFrom(values)
        if (!persistence.clear()) {
            throw IOException("Unable to clear incoming file recovery metadata")
        }
        if (payload != null) deleteOrThrow(payload)
        deleteControlledFiles()
    }

    private fun decodeAndValidate(values: Map<String, *>): RecoveredIncomingFile {
        val version = values.requiredInt(VERSION_KEY)
        if (version != LEGACY_METADATA_VERSION && version != METADATA_VERSION) {
            corruption("Incoming recovery metadata version is unsupported")
        }
        val expectedKeys = if (version == LEGACY_METADATA_VERSION) LEGACY_METADATA_KEYS else METADATA_KEYS
        if (values.keys != expectedKeys) corruption("Incoming recovery metadata keys are invalid")
        val recoveryId = values.requiredString(RECOVERY_ID_KEY).also(::validateRecoveryId)
        val payloadName = values.requiredString(PAYLOAD_FILE_KEY)
        if (payloadName != payloadFileName(recoveryId)) corruption("Incoming recovery payload name is invalid")
        val payload = File(directory, payloadName).also(::checkControlledFile)
        val displayName = values.requiredString(DISPLAY_NAME_KEY)
        try {
            AppSpecificDownloadsSaver.validateDisplayName(displayName)
        } catch (failure: IOException) {
            throw IncomingFileRecoveryCorruptionException("Incoming recovery display name is invalid", failure)
        }
        val byteLength = values.requiredLong(BYTE_LENGTH_KEY)
        if (byteLength < 0L) corruption("Incoming recovery length is invalid")
        val transferId = decodeCanonicalBase64(values.requiredString(TRANSFER_ID_KEY), "transfer ID")
        if (transferId.isEmpty()) corruption("Incoming recovery transfer ID is missing")
        val sha256 = decodeCanonicalBase64(values.requiredString(SHA256_KEY), "digest")
        if (sha256.size != SHA256_BYTES) corruption("Incoming recovery digest is invalid")
        val publicationState =
            if (version == LEGACY_METADATA_VERSION) {
                IncomingFilePublicationState.RECEIVED
            } else {
                try {
                    IncomingFilePublicationState.valueOf(values.requiredString(PUBLICATION_STATE_KEY))
                } catch (failure: IllegalArgumentException) {
                    throw IncomingFileRecoveryCorruptionException("Incoming recovery publication state is invalid", failure)
                }
            }
        val mediaStorePendingUri = if (version == LEGACY_METADATA_VERSION) "" else values.requiredString(MEDIASTORE_PENDING_URI_KEY)
        val appSpecificTargetName = if (version == LEGACY_METADATA_VERSION) "" else values.requiredString(APP_SPECIFIC_TARGET_NAME_KEY)
        val appSpecificPartialName = if (version == LEGACY_METADATA_VERSION) "" else values.requiredString(APP_SPECIFIC_PARTIAL_NAME_KEY)
        val publishedUri = if (version == LEGACY_METADATA_VERSION) "" else values.requiredString(PUBLISHED_URI_KEY)
        validatePublicationMetadata(
            publicationState,
            mediaStorePendingUri,
            appSpecificTargetName,
            appSpecificPartialName,
            publishedUri,
            recoveryId,
        )
        val payloadExists = fileOperations.isRegularFile(payload)
        if (!payloadExists && publicationState != IncomingFilePublicationState.PUBLISHED) {
            corruption("Incoming recovery payload is unavailable")
        }
        if (payloadExists && payload.length() != byteLength) corruption("Incoming recovery payload length changed")
        val expectedDigest = ByteString.copyFrom(sha256)
        if (payloadExists && fileOperations.digest(payload) != expectedDigest) corruption("Incoming recovery payload digest changed")
        return RecoveredIncomingFile(
            recoveryId = recoveryId,
            transferId = ByteString.copyFrom(transferId),
            displayName = displayName,
            mimeType = values.requiredString(MIME_TYPE_KEY),
            byteLength = byteLength,
            sha256 = expectedDigest,
            payloadFile = payload,
            publicationState = publicationState,
            mediaStorePendingUri = mediaStorePendingUri,
            appSpecificTargetName = appSpecificTargetName,
            appSpecificPartialName = appSpecificPartialName,
            publishedUri = publishedUri,
        )
    }

    private fun RecoveredIncomingFile.toMetadata(): Map<String, Any> =
        linkedMapOf(
            VERSION_KEY to METADATA_VERSION,
            RECOVERY_ID_KEY to recoveryId,
            TRANSFER_ID_KEY to Base64.getEncoder().encodeToString(transferId.toByteArray()),
            DISPLAY_NAME_KEY to displayName,
            MIME_TYPE_KEY to mimeType,
            BYTE_LENGTH_KEY to byteLength,
            SHA256_KEY to Base64.getEncoder().encodeToString(sha256.toByteArray()),
            PAYLOAD_FILE_KEY to payloadFile.name,
            PUBLICATION_STATE_KEY to publicationState.name,
            MEDIASTORE_PENDING_URI_KEY to mediaStorePendingUri,
            APP_SPECIFIC_TARGET_NAME_KEY to appSpecificTargetName,
            APP_SPECIFIC_PARTIAL_NAME_KEY to appSpecificPartialName,
            PUBLISHED_URI_KEY to publishedUri,
        )

    private fun validatePublicationMetadata(
        state: IncomingFilePublicationState,
        mediaStoreUri: String,
        targetName: String,
        partialName: String,
        publishedUri: String,
        recoveryId: String,
    ) {
        when (state) {
            IncomingFilePublicationState.RECEIVED -> {
                if (mediaStoreUri.isNotEmpty() || targetName.isNotEmpty() || partialName.isNotEmpty() || publishedUri.isNotEmpty()) {
                    corruption("Received recovery contains unexpected publication metadata")
                }
            }
            IncomingFilePublicationState.MEDIASTORE_PENDING -> {
                if (mediaStoreUri.isBlank() || targetName.isNotEmpty() || partialName.isNotEmpty() || publishedUri.isNotEmpty()) {
                    corruption("Pending MediaStore recovery metadata is invalid")
                }
            }
            IncomingFilePublicationState.APP_SPECIFIC_TARGET -> {
                if (mediaStoreUri.isNotEmpty() || targetName.isEmpty() || publishedUri.isNotEmpty()) {
                    corruption("App-specific recovery metadata is invalid")
                }
                try {
                    AppSpecificDownloadsSaver.validateDisplayName(targetName)
                    validateAppSpecificPartialName(partialName, recoveryId)
                } catch (failure: IOException) {
                    throw IncomingFileRecoveryCorruptionException("App-specific recovery target is invalid", failure)
                }
            }
            IncomingFilePublicationState.PUBLISHED -> {
                if (publishedUri.isBlank()) corruption("Published recovery URI is missing")
            }
        }
    }

    private fun validateAppSpecificPartialName(name: String, recoveryId: String) {
        if (name != ".vibescreen-" + recoveryId + ".partial") {
            throw IOException("Incoming recovery partial name is invalid")
        }
    }

    private fun controlledPayloadFrom(values: Map<String, *>): File? {
        val name = values[PAYLOAD_FILE_KEY] as? String ?: return null
        if (!PAYLOAD_NAME.matches(name)) return null
        return File(directory, name).takeIf { isDirectChild(it) }
    }

    private fun clearCorruptRecovery(primaryFailure: Throwable) {
        if (!persistence.clear()) {
            throw IOException("Unable to clear corrupt incoming recovery metadata", primaryFailure)
        }
        try {
            deleteControlledFiles()
        } catch (cleanupFailure: Exception) {
            primaryFailure.addSuppressed(cleanupFailure)
            throw IOException("Unable to clean corrupt incoming recovery payload", primaryFailure)
        }
    }

    private fun cleanupAfterFailedAdoption(
        temporaryFile: File,
        payloadFile: File?,
        primaryFailure: Exception,
    ) {
        listOfNotNull(temporaryFile, payloadFile).forEach { file ->
            if (fileOperations.exists(file) && !fileOperations.delete(file)) {
                primaryFailure.addSuppressed(IOException("Unable to clean failed incoming recovery file ${file.name}"))
            }
        }
    }

    private fun deleteControlledFiles() {
        fileOperations.listFiles(directory)
            .filter { file -> isDirectChild(file) && CONTROLLED_FILE_NAMES.any { pattern -> pattern.matches(file.name) } }
            .forEach(::deleteOrThrow)
    }

    private fun deleteOrThrow(file: File) {
        if (fileOperations.exists(file) && !fileOperations.delete(file)) {
            throw IOException("Unable to delete incoming recovery file ${file.name}")
        }
    }

    private fun checkControlledFile(file: File) {
        if (!isDirectChild(file) || CONTROLLED_FILE_NAMES.none { pattern -> pattern.matches(file.name) }) {
            corruption("Incoming recovery path escapes its private directory")
        }
    }

    private fun isDirectChild(file: File): Boolean =
        file.parentFile?.canonicalFile == directory.canonicalFile

    private fun validateRecoveryId(value: String) {
        val parsed = runCatching { UUID.fromString(value) }.getOrNull()
        if (parsed == null || parsed.toString() != value) corruption("Incoming recovery identifier is invalid")
    }

    private fun decodeCanonicalBase64(
        value: String,
        label: String,
    ): ByteArray {
        val decoded = try {
            Base64.getDecoder().decode(value)
        } catch (failure: IllegalArgumentException) {
            throw IncomingFileRecoveryCorruptionException("Incoming recovery $label is invalid", failure)
        }
        if (Base64.getEncoder().encodeToString(decoded) != value) {
            corruption("Incoming recovery $label is not canonical")
        }
        return decoded
    }

    private fun corruption(message: String): Nothing =
        throw IncomingFileRecoveryCorruptionException(message)

    companion object {
        private val PROCESS_LOCK = Any()
        private val ACTIVE_PUBLICATIONS = mutableSetOf<String>()
        internal const val VERSION_KEY = "version"
        internal const val RECOVERY_ID_KEY = "recovery_id"
        internal const val TRANSFER_ID_KEY = "transfer_id"
        internal const val DISPLAY_NAME_KEY = "display_name"
        internal const val MIME_TYPE_KEY = "mime_type"
        internal const val BYTE_LENGTH_KEY = "byte_length"
        internal const val SHA256_KEY = "sha256"
        internal const val PAYLOAD_FILE_KEY = "payload_file"
        internal const val PUBLICATION_STATE_KEY = "publication_state"
        internal const val MEDIASTORE_PENDING_URI_KEY = "mediastore_pending_uri"
        internal const val APP_SPECIFIC_TARGET_NAME_KEY = "app_specific_target_name"
        internal const val APP_SPECIFIC_PARTIAL_NAME_KEY = "app_specific_partial_name"
        internal const val PUBLISHED_URI_KEY = "published_uri"
        private const val LEGACY_METADATA_VERSION = 1
        private const val METADATA_VERSION = 2
        private const val RECOVERY_DIRECTORY_NAME = "vibescreen-incoming-recovery"
        private const val PREFERENCES_NAME = "incoming_file_recovery"
        internal const val COPY_BUFFER_BYTES = 64 * 1024
        private val PAYLOAD_NAME = Regex("payload-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.bin")
        private val TEMPORARY_NAME = Regex("\\.payload-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.tmp")
        private val CONTROLLED_FILE_NAMES = listOf(PAYLOAD_NAME, TEMPORARY_NAME)
        private val LEGACY_METADATA_KEYS =
            setOf(
                VERSION_KEY,
                RECOVERY_ID_KEY,
                TRANSFER_ID_KEY,
                DISPLAY_NAME_KEY,
                MIME_TYPE_KEY,
                BYTE_LENGTH_KEY,
                SHA256_KEY,
                PAYLOAD_FILE_KEY,
            )
        private val METADATA_KEYS =
            LEGACY_METADATA_KEYS +
                setOf(
                    PUBLICATION_STATE_KEY,
                    MEDIASTORE_PENDING_URI_KEY,
                    APP_SPECIFIC_TARGET_NAME_KEY,
                    APP_SPECIFIC_PARTIAL_NAME_KEY,
                    PUBLISHED_URI_KEY,
                )

        private fun payloadFileName(recoveryId: String): String = "payload-$recoveryId.bin"

        private fun temporaryFileName(recoveryId: String): String = ".payload-$recoveryId.tmp"

        private fun Map<String, *>.requiredString(key: String): String =
            (this[key] as? String) ?: throw IncomingFileRecoveryCorruptionException("Incoming recovery $key is missing")

        private fun Map<String, *>.requiredInt(key: String): Int =
            (this[key] as? Int) ?: throw IncomingFileRecoveryCorruptionException("Incoming recovery $key is missing")

        private fun Map<String, *>.requiredLong(key: String): Long =
            (this[key] as? Long) ?: throw IncomingFileRecoveryCorruptionException("Incoming recovery $key is missing")
    }

    internal class IncomingFilePublicationLease internal constructor(
        private val recoveryId: String,
    ) : AutoCloseable {
        private val closed = AtomicBoolean(false)

        override fun close() {
            if (!closed.compareAndSet(false, true)) return
            synchronized(PROCESS_LOCK) { ACTIVE_PUBLICATIONS.remove(recoveryId) }
        }
    }
}

private fun RecoveredIncomingFile.matches(completed: CompletedIncomingFile): Boolean =
    transferId == completed.transferId &&
        byteLength == completed.stagingFile.length() &&
        sha256 == completed.sha256

private class SharedPreferencesIncomingFileRecoveryMetadataPersistence(
    private val preferences: SharedPreferences,
) : IncomingFileRecoveryMetadataPersistence {
    override fun read(): Map<String, *> = preferences.all.toMap()

    override fun persist(values: Map<String, Any>): Boolean {
        val editor = preferences.edit().clear()
        values.forEach { (key, value) ->
            when (value) {
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is String -> editor.putString(key, value)
                else -> throw IllegalArgumentException("Unsupported incoming recovery metadata value")
            }
        }
        return editor.commit()
    }

    override fun clear(): Boolean = preferences.edit().clear().commit()
}

private object SystemIncomingFileRecoveryFileOperations : IncomingFileRecoveryFileOperations {
    override fun ensureDirectory(directory: File) {
        if (directory.exists()) {
            if (Files.isSymbolicLink(directory.toPath()) || !directory.isDirectory) {
                throw IOException("Incoming recovery path is not a private directory")
            }
            return
        }
        if (!directory.mkdirs()) throw IOException("Unable to create incoming recovery directory")
    }

    override fun copyAndSync(
        source: File,
        destination: File,
    ): IncomingFileRecoveryCopy {
        if (!destination.createNewFile() || !isRegularFile(destination)) {
            throw IOException("Unable to create incoming recovery temporary file")
        }
        val digest = MessageDigest.getInstance("SHA-256")
        var byteLength = 0L
        BufferedInputStream(source.inputStream()).use { input ->
            FileOutputStream(destination).use { rawOutput ->
                val output = BufferedOutputStream(rawOutput)
                val buffer = ByteArray(IncomingFileRecoveryStore.COPY_BUFFER_BYTES)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    if (read == 0) continue
                    output.write(buffer, 0, read)
                    digest.update(buffer, 0, read)
                    byteLength += read
                }
                output.flush()
                rawOutput.fd.sync()
            }
        }
        return IncomingFileRecoveryCopy(byteLength, ByteString.copyFrom(digest.digest()))
    }

    override fun atomicMove(
        source: File,
        destination: File,
    ) {
        Files.move(source.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE)
    }

    override fun delete(file: File): Boolean = file.delete()

    override fun exists(file: File): Boolean = Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)

    override fun listFiles(directory: File): List<File> =
        directory.listFiles()?.toList() ?: throw IOException("Unable to list incoming recovery directory")

    override fun isRegularFile(file: File): Boolean =
        !Files.isSymbolicLink(file.toPath()) && Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)

    override fun digest(file: File): ByteString {
        val digest = MessageDigest.getInstance("SHA-256")
        BufferedInputStream(file.inputStream()).use { input ->
            val buffer = ByteArray(IncomingFileRecoveryStore.COPY_BUFFER_BYTES)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) digest.update(buffer, 0, read)
            }
        }
        return ByteString.copyFrom(digest.digest())
    }
}
