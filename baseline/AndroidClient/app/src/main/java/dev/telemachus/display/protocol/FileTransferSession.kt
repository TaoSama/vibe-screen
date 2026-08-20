package dev.telemachus.display.protocol

import com.google.protobuf.ByteString
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileChunkHeader
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import dev.vibescreen.protocol.v1.ResourceLimits
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID

internal data class FileTransferPolicy(
    val allowed: Boolean = true,
    val maximumFileBytes: Long = DEFAULT_MAXIMUM_FILE_BYTES,
    val maximumChunkBytes: Int = DEFAULT_MAXIMUM_CHUNK_BYTES,
    val maximumConcurrentTransfers: Int = 1,
    val maximumTotalTemporaryBytes: Long = DEFAULT_MAXIMUM_TEMPORARY_BYTES,
) {
    init {
        require(maximumFileBytes >= 0)
        require(maximumChunkBytes > 0)
        require(maximumConcurrentTransfers > 0)
        require(maximumTotalTemporaryBytes >= 0)
    }

    fun toResourceLimits(): ResourceLimits =
        ResourceLimits
            .newBuilder()
            .setMaximumFileBytes(maximumFileBytes)
            .setMaximumFileChunkBytes(maximumChunkBytes)
            .build()

    fun applying(remote: RemoteManagedPolicy): FileTransferPolicy =
        if (!remote.managed) {
            this
        } else {
            copy(
                allowed = allowed && remote.fileTransferAllowed,
                maximumFileBytes = minOf(maximumFileBytes, remote.maximumFileBytes),
            )
        }

    fun negotiated(peer: ResourceLimits): FileTransferPolicy {
        val peerMaximumFileBytes = if (peer.maximumFileBytes == 0L) maximumFileBytes else peer.maximumFileBytes
        val peerMaximumChunkBytes =
            if (peer.maximumFileChunkBytes == 0) maximumChunkBytes else peer.maximumFileChunkBytes
        return copy(
            maximumFileBytes = minOf(maximumFileBytes, peerMaximumFileBytes),
            maximumChunkBytes = maxOf(1, minOf(maximumChunkBytes, peerMaximumChunkBytes)),
        )
    }

    companion object {
        const val DEFAULT_MAXIMUM_FILE_BYTES = 512L * 1024L * 1024L
        const val DEFAULT_MAXIMUM_CHUNK_BYTES = 64 * 1024
        const val DEFAULT_MAXIMUM_TEMPORARY_BYTES = 768L * 1024L * 1024L
    }
}

internal data class RemoteManagedPolicy(
    val managed: Boolean,
    val fileTransferAllowed: Boolean,
    val maximumFileBytes: Long,
) {
    constructor(status: ManagedPolicyStatus) : this(
        managed = status.managed,
        fileTransferAllowed = if (status.managed) status.fileTransferAllowed else true,
        maximumFileBytes = if (status.managed) status.maximumFileBytes else FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
    )

    companion object {
        val UNMANAGED = RemoteManagedPolicy(
            managed = false,
            fileTransferAllowed = true,
            maximumFileBytes = FileTransferPolicy.DEFAULT_MAXIMUM_FILE_BYTES,
        )
    }
}

internal data class CompletedIncomingFile(
    val transferId: ByteString,
    val fileName: String,
    val stagingFile: File,
    val sha256: ByteString,
)

internal class FileTransferException(
    val reasonCode: String,
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause)

internal data class FileChunk(
    val header: FileChunkHeader,
    val payload: ByteArray,
) {
    fun toFrame(): ByteArray = ProtocolV1Framing.encodeFileChunk(header, payload)

    companion object {
        fun fromFrame(frame: ByteArray): FileChunk {
            val decoded = ProtocolV1Framing.decodeFileChunk(frame)
            if (decoded.header.chunkSha256.size() != SHA256_BYTES) {
                throw fileTransferFailure("invalid_digest", "File chunk digest must be SHA-256")
            }
            val digest = sha256(decoded.payload)
            if (digest != decoded.header.chunkSha256) {
                throw fileTransferFailure("chunk_digest_mismatch", "File chunk digest mismatch")
            }
            return FileChunk(decoded.header, decoded.payload)
        }
    }
}

internal class IncomingFileTransferManager(
    private val policy: FileTransferPolicy,
    private val directory: File,
    private val approve: (FileOffer) -> Boolean,
) {
    private data class State(
        val offer: FileOffer,
        val file: File,
        val handle: RandomAccessFile,
        val sessionEpoch: Long,
        val maximumChunkBytes: Int,
        val digest: MessageDigest = MessageDigest.getInstance("SHA-256"),
        var offset: Long = 0L,
    )

    private val transfers = LinkedHashMap<ByteString, State>()

    init {
        if (!directory.exists() && !directory.mkdirs()) {
            throw fileTransferFailure("io_failure", "Unable to create file transfer staging directory")
        }
    }

    @Synchronized
    fun accept(
        offer: FileOffer,
        remotePolicy: RemoteManagedPolicy,
        negotiatedPolicy: FileTransferPolicy,
        sessionEpoch: Long,
    ): FileAccept {
        val effective = negotiatedPolicy.applying(remotePolicy)
        if (!effective.allowed) throw fileTransferFailure("policy_denied", "File transfer denied by policy")
        validateOffer(offer, effective)
        if (!approve(offer)) throw fileTransferFailure("user_denied", "File transfer denied by user")
        if (transfers.containsKey(offer.transferId)) throw fileTransferFailure("duplicate_transfer", "Duplicate file transfer")
        if (transfers.size >= effective.maximumConcurrentTransfers) {
            throw fileTransferFailure("concurrent_limit", "Too many file transfers")
        }
        val declared = transfers.values.fold(0L) { total, state -> total + state.offer.byteLength }
        if (offer.byteLength > effective.maximumTotalTemporaryBytes ||
            declared > effective.maximumTotalTemporaryBytes - offer.byteLength
        ) {
            throw fileTransferFailure("temporary_space_limit", "Temporary file transfer limit exceeded")
        }
        val staging = File(directory, ".vibescreen-" + UUID.randomUUID() + ".partial")
        val handle =
            try {
                RandomAccessFile(staging, "rw")
            } catch (failure: IOException) {
                throw fileTransferFailure("io_failure", "Unable to create staging file", failure)
            }
        transfers[offer.transferId] = State(offer, staging, handle, sessionEpoch, effective.maximumChunkBytes)
        return FileAccept
            .newBuilder()
            .setTransferId(offer.transferId)
            .setAccepted(true)
            .setMaximumChunkBytes(effective.maximumChunkBytes)
            .build()
    }

    @Synchronized
    fun append(chunk: FileChunk, sessionEpoch: Long): Long {
        val state = transfers[chunk.header.transferId]
            ?: throw fileTransferFailure("unknown_transfer", "Unknown file transfer")
        if (chunk.header.sessionEpoch != sessionEpoch || state.sessionEpoch != sessionEpoch) {
            throw fileTransferFailure("stale_session_epoch", "File chunk belongs to a stale session epoch")
        }
        if (chunk.payload.size > state.maximumChunkBytes) {
            throw fileTransferFailure("chunk_too_large", "File chunk exceeds negotiated limit")
        }
        if (chunk.payload.isEmpty() && !(state.offer.byteLength == 0L && state.offset == 0L && chunk.header.final)) {
            throw fileTransferFailure("empty_chunk", "File chunk must not be empty unless it completes an empty file")
        }
        if (chunk.header.offset != state.offset) {
            throw fileTransferFailure("unexpected_offset", "Unexpected file chunk offset")
        }
        if (chunk.payload.size.toLong() > state.offer.byteLength - state.offset) {
            throw fileTransferFailure("exceeds_declared_length", "File chunk exceeds declared length")
        }
        val willComplete = state.offset + chunk.payload.size == state.offer.byteLength
        if (chunk.header.final != willComplete) {
            throw fileTransferFailure("invalid_final_flag", "File chunk final flag is inconsistent")
        }
        try {
            state.handle.write(chunk.payload)
        } catch (failure: IOException) {
            throw fileTransferFailure("io_failure", "Unable to write staging file", failure)
        }
        state.digest.update(chunk.payload)
        state.offset += chunk.payload.size
        return state.offset
    }

    @Synchronized
    fun finish(transferId: ByteString): CompletedIncomingFile {
        val state = transfers[transferId]
            ?: throw fileTransferFailure("unknown_transfer", "Unknown file transfer")
        if (state.offset != state.offer.byteLength) {
            throw fileTransferFailure("incomplete_file", "File transfer is incomplete")
        }
        val digest = ByteString.copyFrom(state.digest.digest())
        if (digest != state.offer.sha256) {
            cancelLocked(transferId)
            throw fileTransferFailure("digest_mismatch", "Completed file digest mismatch")
        }
        try {
            state.handle.close()
        } catch (failure: IOException) {
            cancelLocked(transferId)
            throw fileTransferFailure("io_failure", "Unable to close staging file", failure)
        }
        transfers.remove(transferId)
        return CompletedIncomingFile(transferId, state.offer.fileName, state.file, digest)
    }

    @Synchronized
    fun cancel(transferId: ByteString) {
        cancelLocked(transferId)
    }

    @Synchronized
    fun cancelAll() {
        transfers.keys.toList().forEach(::cancelLocked)
    }

    @Synchronized
    fun activeTransferCount(): Int = transfers.size

    private fun cancelLocked(transferId: ByteString) {
        val state = transfers.remove(transferId) ?: return
        try {
            state.handle.close()
        } catch (_: IOException) {
        }
        state.file.delete()
    }

    private fun validateOffer(offer: FileOffer, effective: FileTransferPolicy) {
        if (offer.transferId.isEmpty) throw fileTransferFailure("invalid_transfer_id", "File transfer id is missing")
        if (!isSafeFileName(offer.fileName)) throw fileTransferFailure("invalid_file_name", "Unsafe file name")
        if (offer.sha256.size() != SHA256_BYTES) throw fileTransferFailure("invalid_digest", "File digest must be SHA-256")
        if (offer.byteLength > effective.maximumFileBytes) {
            throw fileTransferFailure("file_too_large", "File exceeds negotiated maximum")
        }
    }

    companion object {
        fun isSafeFileName(name: String): Boolean =
            name.isNotEmpty() &&
                name != "." &&
                name != ".." &&
                !name.contains('\u0000') &&
                !name.contains('/') &&
                !name.contains('\\') &&
                File(name).name == name
    }
}

internal class OutgoingFileTransfer(
    file: File,
    mimeType: String,
    policy: FileTransferPolicy,
    remotePolicy: RemoteManagedPolicy = RemoteManagedPolicy.UNMANAGED,
) {
    private val effectivePolicy = policy.applying(remotePolicy)
    private val handle: RandomAccessFile
    private var offset = 0L
    private var cancelled = false
    private var emittedEmptyFileChunk = false
    private var acceptedMaximumChunkBytes: Int? = null

    val offer: FileOffer

    init {
        if (!effectivePolicy.allowed) throw fileTransferFailure("policy_denied", "File transfer denied by policy")
        if (!file.isFile) throw fileTransferFailure("invalid_file_name", "Outgoing file must be a regular file")
        val byteLength = file.length()
        if (byteLength < 0 || byteLength > effectivePolicy.maximumFileBytes) {
            throw fileTransferFailure("file_too_large", "File exceeds negotiated maximum")
        }
        if (!IncomingFileTransferManager.isSafeFileName(file.name)) {
            throw fileTransferFailure("invalid_file_name", "Unsafe file name")
        }
        val digest = digest(file, effectivePolicy.maximumChunkBytes)
        offer =
            FileOffer
                .newBuilder()
                .setTransferId(ByteString.copyFrom(UUID.randomUUID().toBytes()))
                .setFileName(file.name)
                .setMimeType(mimeType)
                .setByteLength(byteLength)
                .setSha256(digest)
                .build()
        handle =
            try {
                RandomAccessFile(file, "r")
            } catch (failure: IOException) {
                throw fileTransferFailure("io_failure", "Unable to open outgoing file", failure)
            }
    }

    @Synchronized
    fun nextChunk(maximumBytes: Int, sessionEpoch: Long): FileChunk? {
        if (cancelled) throw fileTransferFailure("unknown_transfer", "File transfer was cancelled")
        if (offer.byteLength == 0L) {
            if (emittedEmptyFileChunk) return null
            emittedEmptyFileChunk = true
            val payload = ByteArray(0)
            val header =
                FileChunkHeader
                    .newBuilder()
                    .setTransferId(offer.transferId)
                    .setOffset(0)
                    .setPayloadLength(0)
                    .setSessionEpoch(sessionEpoch)
                    .setChunkSha256(sha256(payload))
                    .setFinal(true)
                    .build()
            return FileChunk(header, payload)
        }
        if (offset >= offer.byteLength) return null
        val requested = minOf(maxOf(1, minOf(effectivePolicy.maximumChunkBytes, maximumBytes)), (offer.byteLength - offset).toInt())
        val payload = ByteArray(requested)
        val read =
            try {
                handle.read(payload)
            } catch (failure: IOException) {
                throw fileTransferFailure("io_failure", "Unable to read outgoing file", failure)
            }
        if (read <= 0) throw fileTransferFailure("incomplete_file", "Outgoing file ended early")
        val exactPayload = if (read == payload.size) payload else payload.copyOf(read)
        val header =
            FileChunkHeader
                .newBuilder()
                .setTransferId(offer.transferId)
                .setOffset(offset)
                .setPayloadLength(exactPayload.size)
                .setSessionEpoch(sessionEpoch)
                .setChunkSha256(sha256(exactPayload))
                .setFinal(offset + exactPayload.size == offer.byteLength)
                .build()
        offset += exactPayload.size
        return FileChunk(header, exactPayload)
    }

    @Synchronized
    fun cancel() {
        cancelled = true
        try {
            handle.close()
        } catch (_: IOException) {
        }
    }

    @Synchronized
    fun applyAcceptedMaximumChunkBytes(maximumBytes: Int) {
        acceptedMaximumChunkBytes = maximumBytes.takeIf { it > 0 }
    }

    @Synchronized
    fun maximumChunkBytes(defaultBytes: Int): Int = acceptedMaximumChunkBytes ?: defaultBytes

    companion object {
        private fun digest(file: File, chunkBytes: Int): ByteString {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(chunkBytes)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    if (read > 0) digest.update(buffer, 0, read)
                }
            }
            return ByteString.copyFrom(digest.digest())
        }
    }
}

internal fun sha256(data: ByteArray): ByteString =
    ByteString.copyFrom(MessageDigest.getInstance("SHA-256").digest(data))

internal fun fileTransferFailure(
    reasonCode: String,
    message: String,
    cause: Throwable? = null,
): FileTransferException = FileTransferException(reasonCode, message, cause)

private const val SHA256_BYTES = 32

private fun UUID.toBytes(): ByteArray {
    val buffer = java.nio.ByteBuffer.allocate(16)
    buffer.putLong(mostSignificantBits)
    buffer.putLong(leastSignificantBits)
    return buffer.array()
}
