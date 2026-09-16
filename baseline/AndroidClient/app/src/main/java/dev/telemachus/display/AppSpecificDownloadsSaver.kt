package dev.telemachus.display

import dev.telemachus.display.protocol.CompletedIncomingFile
import com.google.protobuf.ByteString
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.UUID

internal object AppSpecificDownloadsSaver {
    private const val COPY_BUFFER_BYTES = 64 * 1024
    private const val MAX_COLLISION_ATTEMPTS = 1_000
    private const val PARTIAL_PREFIX = ".vibescreen-"
    private const val PARTIAL_SUFFIX = ".partial"
    private const val DEFAULT_DISPLAY_NAME = "transfer.bin"
    private val publishLock = Any()

    internal data class StablePublicationTarget(
        val target: File,
        val partial: File,
    )

    fun save(
        source: File,
        downloads: File,
        displayName: String,
        copy: (File, OutputStream) -> Unit = ::copyFileTo,
    ): File {
        validateDisplayName(displayName)
        ensureDirectory(downloads)
        val partial = newPartialFile(downloads)
        try {
            partial.outputStream().use { output -> copy(source, output) }
            return synchronized(publishLock) {
                publishPartialToAvailableDestination(partial, downloads, displayName)
            }
        } catch (failure: Throwable) {
            partial.delete()
            throw failure
        }
    }

    fun saveCompletedIncomingFile(
        completed: CompletedIncomingFile,
        downloads: File,
        maxDisplayNameLength: Int,
        fallbackDisplayName: String = DEFAULT_DISPLAY_NAME,
        copy: (File, OutputStream) -> Unit = ::copyFileTo,
    ): File {
        val displayName = safeDisplayName(
            completed.fileName,
            maxDisplayNameLength,
            fallback = fallbackDisplayName,
        )
        return save(
            source = completed.stagingFile,
            downloads = downloads,
            displayName = displayName,
            copy = copy,
        )
    }

    fun allocateStablePublication(
        downloads: File,
        recoveryId: String,
        displayName: String,
    ): StablePublicationTarget =
        synchronized(publishLock) {
            validateDisplayName(displayName)
            ensureDirectory(downloads)
            val target = availableDestination(downloads, displayName)
            val partial = File(downloads, PARTIAL_PREFIX + recoveryId + PARTIAL_SUFFIX)
            if (partial.parentFile?.canonicalFile != downloads.canonicalFile) {
                throw IOException("Downloads partial path escapes its directory")
            }
            StablePublicationTarget(target = target, partial = partial)
        }

    fun writeStablePartial(
        source: File,
        partial: File,
        copy: (File, OutputStream) -> Unit = ::copyFileTo,
    ) {
        FileOutputStream(partial, false).use { rawOutput ->
            copy(source, rawOutput)
            rawOutput.fd.sync()
        }
    }

    fun publishStablePartial(partial: File, target: File) {
        synchronized(publishLock) {
            if (!publishPartial(partial, target)) throw IOException("Downloads target already exists")
        }
    }

    fun matches(
        file: File,
        byteLength: Long,
        sha256: ByteString,
    ): Boolean {
        if (!file.isFile || file.length() != byteLength) return false
        val digest = MessageDigest.getInstance("SHA-256")
        BufferedInputStream(file.inputStream()).use { input ->
            val buffer = ByteArray(COPY_BUFFER_BYTES)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                if (read > 0) digest.update(buffer, 0, read)
            }
        }
        return ByteString.copyFrom(digest.digest()) == sha256
    }

    private fun ensureDirectory(directory: File) {
        if (directory.exists()) {
            if (!directory.isDirectory) throw IOException("Downloads path is not a directory")
            return
        }
        if (!directory.mkdirs()) throw IOException("Unable to create downloads directory")
    }

    fun validateDisplayName(displayName: String) {
        if (displayName.isEmpty() ||
            displayName.isBlank() ||
            displayName.trim() != displayName ||
            displayName == "." ||
            displayName == ".." ||
            displayName.any(Char::isISOControl) ||
            displayName.contains('/') ||
            displayName.contains('\\') ||
            File(displayName).name != displayName
        ) {
            throw IOException("Unsafe downloads file name")
        }
    }

    fun safeDisplayName(
        displayName: String?,
        maxLength: Int,
        fallback: String = DEFAULT_DISPLAY_NAME,
    ): String {
        require(maxLength > 0) { "maxLength must be positive" }
        val candidate =
            displayName
                ?.substringAfterLast('/')
                ?.substringAfterLast('\\')
                ?.map { character -> if (character.isISOControl()) '_' else character }
                ?.joinToString(separator = "")
                ?.trim()
                ?.take(maxLength)
                .orEmpty()
        val fallbackCandidate = fallback.take(maxLength)
        return if (candidate.isSafeDisplayName()) {
            candidate
        } else {
            check(fallbackCandidate.isSafeDisplayName()) { "fallback display name must be safe" }
            fallbackCandidate
        }
    }

    private fun String.isSafeDisplayName(): Boolean =
        isNotEmpty() &&
            isNotBlank() &&
            trim() == this &&
            this != "." &&
            this != ".." &&
            !any(Char::isISOControl) &&
            !contains('/') &&
            !contains('\\') &&
            File(this).name == this

    private fun availableDestination(
        directory: File,
        displayName: String,
    ): File {
        val first = File(directory, displayName)
        if (!first.exists()) return first

        val dotIndex = displayName.lastIndexOf('.')
        val hasExtension = dotIndex > 0 && dotIndex < displayName.lastIndex
        val stem = if (hasExtension) displayName.substring(0, dotIndex) else displayName
        val extension = if (hasExtension) displayName.substring(dotIndex) else ""
        for (attempt in 1..MAX_COLLISION_ATTEMPTS) {
            val candidate = File(directory, "$stem ($attempt)$extension")
            if (!candidate.exists()) return candidate
        }
        throw IOException("Unable to allocate downloads file name")
    }

    private fun newPartialFile(directory: File): File {
        repeat(MAX_COLLISION_ATTEMPTS) {
            val candidate = File(directory, PARTIAL_PREFIX + UUID.randomUUID() + PARTIAL_SUFFIX)
            if (candidate.createNewFile()) return candidate
        }
        throw IOException("Unable to allocate downloads staging file")
    }

    private fun publishPartial(
        partial: File,
        target: File,
    ): Boolean {
        if (target.exists()) return false
        try {
            Files.move(partial.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE)
        } catch (_: FileAlreadyExistsException) {
            return false
        }
        return true
    }

    private fun publishPartialToAvailableDestination(
        partial: File,
        directory: File,
        displayName: String,
    ): File {
        repeat(MAX_COLLISION_ATTEMPTS) {
            val target = availableDestination(directory, displayName)
            if (publishPartial(partial, target)) return target
        }
        throw IOException("Unable to allocate downloads file name")
    }

    fun copyFileTo(
        source: File,
        output: OutputStream,
    ) {
        BufferedInputStream(source.inputStream()).use { input ->
            val bufferedOutput = BufferedOutputStream(output)
            val buffer = ByteArray(COPY_BUFFER_BYTES)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                bufferedOutput.write(buffer, 0, read)
            }
            bufferedOutput.flush()
        }
    }
}
