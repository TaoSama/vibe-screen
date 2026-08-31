package dev.telemachus.display

import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

internal object AppSpecificDownloadsSaver {
    private const val COPY_BUFFER_BYTES = 64 * 1024
    private const val MAX_COLLISION_ATTEMPTS = 1_000
    private const val PARTIAL_PREFIX = ".vibescreen-"
    private const val PARTIAL_SUFFIX = ".partial"
    private const val DEFAULT_DISPLAY_NAME = "transfer.bin"

    fun save(
        source: File,
        downloads: File,
        displayName: String,
        copy: (File, OutputStream) -> Unit = ::copyFileTo,
    ): File {
        validateDisplayName(displayName)
        ensureDirectory(downloads)
        val target = availableDestination(downloads, displayName)
        val partial = newPartialFile(downloads)
        try {
            partial.outputStream().use { output -> copy(source, output) }
            publishPartial(partial, target)
            return target
        } catch (failure: Throwable) {
            partial.delete()
            throw failure
        }
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
            displayName == "." ||
            displayName == ".." ||
            displayName.contains('\u0000') ||
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
                ?.replace('\u0000', '_')
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
            this != "." &&
            this != ".." &&
            !contains('\u0000') &&
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
    ) {
        if (target.exists()) throw IOException("Downloads destination already exists")
        Files.move(partial.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE)
    }

    private fun copyFileTo(
        source: File,
        output: OutputStream,
    ) {
        BufferedInputStream(source.inputStream()).use { input ->
            BufferedOutputStream(output).use { bufferedOutput ->
                val buffer = ByteArray(COPY_BUFFER_BYTES)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    bufferedOutput.write(buffer, 0, read)
                }
            }
        }
    }
}
