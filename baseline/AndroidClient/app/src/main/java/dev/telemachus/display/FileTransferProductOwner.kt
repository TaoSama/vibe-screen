package dev.telemachus.display

import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import dev.telemachus.display.protocol.FileChunk
import dev.telemachus.display.protocol.FileTransferException
import dev.telemachus.display.protocol.FileTransferPolicy
import dev.telemachus.display.protocol.IncomingFileTransferManager
import dev.telemachus.display.protocol.OutgoingFileTransfer
import dev.telemachus.display.protocol.RemoteManagedPolicy
import dev.telemachus.display.protocol.SHA256_BYTES
import dev.vibescreen.protocol.v1.FileAccept
import dev.vibescreen.protocol.v1.FileOffer
import dev.vibescreen.protocol.v1.FileTransferCancel
import dev.vibescreen.protocol.v1.FileTransferComplete
import dev.vibescreen.protocol.v1.FileTransferProgress
import dev.vibescreen.protocol.v1.ManagedPolicyStatus
import java.io.File
import java.io.IOException
import java.util.IdentityHashMap

/** Owns Android file-transfer product state while the wire/session boundary stays outside. */
internal class FileTransferProductOwner(
    val fileTransferPolicy: FileTransferPolicy = FileTransferPolicy(),
    private val stagingDirectory: () -> File,
    private val pendingOfferGate: PendingOfferGate,
    private val incomingManagerFactory: IncomingManagerFactory = IncomingManagerFactory { policy, directory, approve ->
        IncomingFileTransferStore(IncomingFileTransferManager(policy, directory, approve))
    },
    private val outgoingTransferFactory: OutgoingTransferFactory = OutgoingTransferFactory { file, mimeType, policy, remotePolicy ->
        OutgoingFileTransferStore(OutgoingFileTransfer(file, mimeType, policy, remotePolicy))
    },
) {
    private val lock = Any()
    private var incomingFileTransfers: IncomingTransferStore? = null
    private val preparedOutgoingTransfers = LinkedHashSet<OutgoingTransferStore>()
    private val outgoingFileTransfers = LinkedHashMap<ByteString, OutgoingTransferStore>()
    private val terminatedOutgoingTransfers = IdentityHashMap<OutgoingTransferStore, String>()
    private var remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED

    @Volatile var onFileOffer: ((FileOffer) -> Unit)? = null
    @Volatile var onIncomingFileCompleted: ((CompletedIncomingFile) -> Unit)? = null
    @Volatile var onFileTransferResult: ((accepted: Boolean, reason: String) -> Unit)? = null

    fun activateSession() {
        val newIncomingFileTransfers =
            incomingManagerFactory.create(fileTransferPolicy, stagingDirectory()) { true }
        val previousIncoming: IncomingTransferStore?
        val previousOutgoing: OutgoingDrain
        synchronized(lock) {
            previousIncoming = incomingFileTransfers
            incomingFileTransfers = newIncomingFileTransfers
            remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED
            previousOutgoing = drainOutgoingLocked("session_deactivated")
        }
        previousIncoming?.cancelAll()
        previousOutgoing.cancelAll()
        notifyOutgoingTransfers(previousOutgoing)
        pendingOfferGate.clearFileOffers()
    }

    fun clear(reasonCode: String = "connection_cleanup") {
        val previousIncoming: IncomingTransferStore?
        val previousOutgoing: OutgoingDrain
        synchronized(lock) {
            previousIncoming = incomingFileTransfers
            incomingFileTransfers = null
            remoteManagedPolicy = RemoteManagedPolicy.UNMANAGED
            previousOutgoing = drainOutgoingLocked(reasonCode)
        }
        previousIncoming?.cancelAll()
        previousOutgoing.cancelAll()
        notifyOutgoingTransfers(previousOutgoing)
        pendingOfferGate.clearFileOffers()
    }

    fun applyManagedPolicy(status: ManagedPolicyStatus) {
        var clearPendingOffers = false
        var incomingToCancel: IncomingTransferStore? = null
        var outgoingToCancel = OutgoingDrain.EMPTY
        synchronized(lock) {
            remoteManagedPolicy = RemoteManagedPolicy(status)
            if (!fileTransferPolicy.applying(remoteManagedPolicy).allowed) {
                incomingToCancel = incomingFileTransfers
                outgoingToCancel = drainOutgoingLocked("policy_denied")
                clearPendingOffers = true
            }
        }
        incomingToCancel?.cancelAll()
        outgoingToCancel.cancelAll()
        notifyOutgoingTransfers(outgoingToCancel)
        if (clearPendingOffers) pendingOfferGate.clearFileOffers()
    }

    fun receiveFileOffer(
        ownerToken: Any,
        connectionGeneration: Long,
        offer: FileOffer,
        negotiatedPolicy: FileTransferPolicy = fileTransferPolicy,
    ): FileAccept? {
        val callback = synchronized(lock) {
            if (incomingFileTransfers == null) return rejectedFileAccept(offer.transferId, "policy_denied")
            val effectivePolicy = negotiatedPolicy.applying(remoteManagedPolicy)
            val rejectionReason = validateIncomingOffer(offer, effectivePolicy)
            if (rejectionReason != null) {
                return rejectedFileAccept(offer.transferId, rejectionReason)
            }
            onFileOffer ?: return rejectedFileAccept(offer.transferId, "user_denied")
        }
        if (!pendingOfferGate.trackFileOffer(offer.transferId, ownerToken, connectionGeneration)) {
            return rejectedFileAccept(offer.transferId, "file_offer_pending_limit")
        }
        callback.invoke(offer)
        return null
    }

    fun claimFileOfferDecision(offer: FileOffer): PendingOfferOwner? =
        pendingOfferGate.claimFileOffer(offer.transferId)

    fun releaseFileOfferDecision(offer: FileOffer) {
        pendingOfferGate.releaseFileOffer(offer.transferId)
    }

    fun releaseFileOfferDecision(transferId: ByteString) {
        pendingOfferGate.releaseFileOffer(transferId)
    }

    fun isPendingOrActiveIncomingTransfer(transferId: ByteString): Boolean {
        val active = synchronized(lock) { incomingFileTransfers?.contains(transferId) == true }
        return active || pendingOfferGate.hasFileOffer(transferId)
    }

    fun isActiveIncomingTransfer(transferId: ByteString): Boolean =
        synchronized(lock) { incomingFileTransfers?.contains(transferId) == true }

    fun decideFileOffer(
        offer: FileOffer,
        acceptedByUser: Boolean,
        negotiatedPolicy: FileTransferPolicy,
        sessionEpoch: Long,
    ): FileAccept {
        if (!acceptedByUser) return rejectedFileAccept(offer.transferId, "user_denied")
        val manager: IncomingTransferStore?
        val remotePolicy: RemoteManagedPolicy
        synchronized(lock) {
            manager = incomingFileTransfers
            remotePolicy = remoteManagedPolicy
        }
        if (manager == null) return rejectedFileAccept(offer.transferId, "policy_denied")
        return try {
            manager.accept(
                offer,
                remotePolicy = remotePolicy,
                negotiatedPolicy = negotiatedPolicy,
                sessionEpoch = sessionEpoch,
            )
        } catch (failure: FileTransferException) {
            rejectedFileAccept(offer.transferId, failure.reasonCode)
        }
    }

    fun receiveIncomingChunk(
        chunk: FileChunk,
        canTransferFiles: Boolean,
        sessionEpoch: Long,
    ): IncomingChunkResult {
        val (manager, fileTransferAllowed) =
            synchronized(lock) { incomingFileTransfers to fileTransferPolicy.applying(remoteManagedPolicy).allowed }
        if (!canTransferFiles || manager == null || !fileTransferAllowed) {
            return IncomingChunkResult.Rejected(
                transferId = chunk.header.transferId,
                reasonCode = "policy_denied",
            )
        }
        return try {
            val receivedBytes = manager.append(chunk, sessionEpoch)
            if (chunk.header.final) {
                try {
                    IncomingChunkResult.Accepted(
                        transferId = chunk.header.transferId,
                        receivedBytes = receivedBytes,
                        completed = manager.finish(chunk.header.transferId),
                    )
                } catch (failure: FileTransferException) {
                    manager.cancel(chunk.header.transferId)
                    IncomingChunkResult.Rejected(
                        transferId = chunk.header.transferId,
                        reasonCode = failure.reasonCode,
                        receivedBytes = receivedBytes,
                        failure = failure,
                    )
                } catch (failure: IOException) {
                    manager.cancel(chunk.header.transferId)
                    IncomingChunkResult.Rejected(
                        transferId = chunk.header.transferId,
                        reasonCode = "io_failure",
                        receivedBytes = receivedBytes,
                        failure = failure,
                    )
                }
            } else {
                IncomingChunkResult.Accepted(
                    transferId = chunk.header.transferId,
                    receivedBytes = receivedBytes,
                    completed = null,
                )
            }
        } catch (failure: FileTransferException) {
            manager.cancel(chunk.header.transferId)
            IncomingChunkResult.Rejected(
                transferId = chunk.header.transferId,
                reasonCode = failure.reasonCode,
                failure = failure,
            )
        } catch (failure: IOException) {
            manager.cancel(chunk.header.transferId)
            IncomingChunkResult.Rejected(
                transferId = chunk.header.transferId,
                reasonCode = "io_failure",
                failure = failure,
            )
        }
    }

    fun prepareOutgoingFile(
        file: File,
        mimeType: String,
        negotiatedPolicy: FileTransferPolicy,
    ): PrepareOutgoingResult =
        try {
            val remotePolicy = synchronized(lock) { remoteManagedPolicy }
            val transfer = outgoingTransferFactory.create(file, mimeType, negotiatedPolicy, remotePolicy)
            var rejectionReason: String? = null
            synchronized(lock) {
                val effectivePolicy = negotiatedPolicy.applying(remoteManagedPolicy)
                if (incomingFileTransfers == null) {
                    rejectionReason = "policy_denied"
                } else if (!effectivePolicy.allowed) {
                    rejectionReason = "policy_denied"
                } else if (transfer.offer.byteLength > effectivePolicy.maximumFileBytes) {
                    rejectionReason = "file_too_large"
                } else {
                    preparedOutgoingTransfers += transfer
                }
            }
            rejectionReason?.let { reason ->
                transfer.cancel()
                PrepareOutgoingResult.Rejected(reason)
            } ?: PrepareOutgoingResult.Prepared(PreparedOutgoingTransfer(transfer))
        } catch (failure: FileTransferException) {
            PrepareOutgoingResult.Rejected(failure.reasonCode)
        }

    fun startPreparedOutgoing(
        prepared: PreparedOutgoingTransfer,
        canTransferFiles: Boolean,
    ): StartOutgoingResult {
        var transferToCancel: OutgoingTransferStore? = null
        val result = synchronized(lock) {
            val transfer = prepared.transfer
            when {
                !preparedOutgoingTransfers.remove(transfer) ->
                    StartOutgoingResult.Stale(terminatedOutgoingTransfers.remove(transfer))
                !canTransferFiles -> {
                    transferToCancel = transfer
                    StartOutgoingResult.Rejected("policy_denied")
                }
                outgoingFileTransfers.isNotEmpty() -> {
                    transferToCancel = transfer
                    StartOutgoingResult.Rejected("concurrent_limit")
                }
                outgoingFileTransfers.containsKey(transfer.offer.transferId) -> {
                    transferToCancel = transfer
                    StartOutgoingResult.Rejected("concurrent_limit")
                }
                else -> {
                    outgoingFileTransfers[transfer.offer.transferId] = transfer
                    StartOutgoingResult.Started(transfer.offer)
                }
            }
        }
        transferToCancel?.cancel()
        return result
    }

    fun cancelPreparedOutgoing(prepared: PreparedOutgoingTransfer) {
        val transferToCancel: OutgoingTransferStore?
        synchronized(lock) {
            val transferId = prepared.transfer.offer.transferId
            val removedPrepared = preparedOutgoingTransfers.remove(prepared.transfer)
            transferToCancel = prepared.transfer.takeIf {
                removedPrepared && outgoingFileTransfers[transferId] !== prepared.transfer
            }
        }
        transferToCancel?.cancel()
    }

    fun cancelOutgoingTransfer(transferId: ByteString) {
        synchronized(lock) { outgoingFileTransfers.remove(transferId) }?.cancel()
    }

    fun cancelIncomingTransfer(transferId: ByteString): Boolean {
        val manager = synchronized(lock) { incomingFileTransfers }
        return manager?.cancel(transferId) == true
    }

    fun handleBulkSendFailed(transferId: ByteString): OutgoingUpdate {
        val transfer = synchronized(lock) { outgoingFileTransfers.remove(transferId) }
        transfer ?: return OutgoingUpdate()
        transfer.cancel()
        return OutgoingUpdate(
            cancelTransferId = transferId,
            cancelReasonCode = "bulk_send_failed",
            result = TransferResult(accepted = false, reason = "bulk_send_failed"),
        )
    }

    fun rejectOutgoingTransfer(
        transferId: ByteString,
        prepared: PreparedOutgoingTransfer,
        reasonCode: String,
    ): TransferResult? {
        val transferToCancel: OutgoingTransferStore?
        val staleReason: String?
        synchronized(lock) {
            val transfer = outgoingFileTransfers[transferId]
            transferToCancel = if (transfer === prepared.transfer) outgoingFileTransfers.remove(transferId) else null
            staleReason = if (transferToCancel == null) terminatedOutgoingTransfers.remove(prepared.transfer) else null
        }
        if (transferToCancel == null) {
            return staleReason?.let { reason -> TransferResult(accepted = false, reason = reason) }
        }
        transferToCancel.cancel()
        return TransferResult(accepted = false, reason = reasonCode)
    }

    fun isOutgoingTransferActive(
        transferId: ByteString,
        prepared: PreparedOutgoingTransfer,
    ): Boolean = synchronized(lock) { outgoingFileTransfers[transferId] === prepared.transfer }

    fun handleFileAccept(
        response: FileAccept,
        sessionEpoch: Long,
    ): OutgoingUpdate {
        val transfer = synchronized(lock) { outgoingFileTransfers[response.transferId] }
        if (response.accepted) {
            if (transfer == null) return OutgoingUpdate()
            transfer.applyAcceptedMaximumChunkBytes(response.maximumChunkBytes)
            return nextOutgoingChunk(response.transferId, transfer, sessionEpoch)
        }
        val transferToCancel = synchronized(lock) { outgoingFileTransfers.remove(response.transferId) }
            ?: return OutgoingUpdate()
        transferToCancel.cancel()
        return OutgoingUpdate(result = TransferResult(accepted = false, reason = response.rejectionReason))
    }

    fun handleFileProgress(
        progress: FileTransferProgress,
        sessionEpoch: Long,
    ): OutgoingUpdate {
        val transfer = synchronized(lock) { outgoingFileTransfers[progress.transferId] } ?: return OutgoingUpdate()
        val rejectionReason = transfer.acknowledgeOffset(progress.receivedBytes)
        return if (rejectionReason == null) {
            nextOutgoingChunk(progress.transferId, transfer, sessionEpoch)
        } else {
            val transferToCancel = synchronized(lock) {
                if (outgoingFileTransfers[progress.transferId] === transfer) {
                    outgoingFileTransfers.remove(progress.transferId)
                } else {
                    null
                }
            } ?: return OutgoingUpdate()
            transferToCancel.cancel()
            OutgoingUpdate(
                cancelTransferId = progress.transferId,
                cancelReasonCode = rejectionReason,
                result = TransferResult(accepted = false, reason = rejectionReason),
            )
        }
    }

    fun handleFileCancel(cancellation: FileTransferCancel): TransferResult? {
        val manager: IncomingTransferStore?
        val outgoing: OutgoingTransferStore?
        synchronized(lock) {
            manager = incomingFileTransfers
            outgoing = outgoingFileTransfers.remove(cancellation.transferId)
        }
        val cancelledIncoming = manager?.cancel(cancellation.transferId) == true
        outgoing?.cancel()
        return if (cancelledIncoming || outgoing != null) {
            TransferResult(accepted = false, reason = cancellation.reasonCode)
        } else {
            null
        }
    }

    fun handleFileComplete(result: FileTransferComplete): OutgoingUpdate {
        val transfer = synchronized(lock) { outgoingFileTransfers.remove(result.transferId) }
        transfer ?: return OutgoingUpdate()
        transfer.cancel()
        val reason = when {
            !result.accepted -> result.rejectionReason
            !transfer.hasCompletedAcknowledgement() -> "incomplete_file"
            transfer.offer.sha256 != result.sha256 -> "digest_mismatch"
            else -> ""
        }
        val accepted = result.accepted && reason.isEmpty()
        return OutgoingUpdate(
            cancelTransferId = if (result.accepted && reason.isNotEmpty()) result.transferId else null,
            cancelReasonCode = if (result.accepted && reason.isNotEmpty()) reason else null,
            result = TransferResult(accepted = accepted, reason = reason),
        )
    }

    fun notifyIncomingFileCompleted(completed: CompletedIncomingFile) {
        onIncomingFileCompleted?.invoke(completed)
    }

    fun notifyFileTransferResult(result: TransferResult) {
        onFileTransferResult?.invoke(result.accepted, result.reason)
    }

    fun activeIncomingTransferCount(): Int = synchronized(lock) { incomingFileTransfers?.activeTransferCount() ?: 0 }

    fun activeOutgoingTransferCount(): Int = synchronized(lock) { outgoingFileTransfers.size }

    private fun nextOutgoingChunk(
        transferId: ByteString,
        transfer: OutgoingTransferStore,
        sessionEpoch: Long,
    ): OutgoingUpdate {
        synchronized(lock) {
            if (outgoingFileTransfers[transferId] !== transfer) return OutgoingUpdate()
        }
        return try {
            val chunk = transfer.nextChunk(
                maximumBytes = transfer.maximumChunkBytes(defaultBytes = fileTransferPolicy.maximumChunkBytes),
                sessionEpoch = sessionEpoch,
            )
            synchronized(lock) {
                if (outgoingFileTransfers[transferId] !== transfer) return OutgoingUpdate()
            }
            OutgoingUpdate(chunk = chunk)
        } catch (failure: FileTransferException) {
            synchronized(lock) { outgoingFileTransfers.remove(transferId) }?.cancel()
            OutgoingUpdate(
                cancelTransferId = transferId,
                cancelReasonCode = failure.reasonCode,
                result = TransferResult(accepted = false, reason = failure.reasonCode),
            )
        }
    }

    private fun drainOutgoingLocked(reasonCode: String): OutgoingDrain {
        val prepared = preparedOutgoingTransfers.toList()
        val active = outgoingFileTransfers.values.toList()
        preparedOutgoingTransfers.clear()
        outgoingFileTransfers.clear()
        prepared.forEach { terminatedOutgoingTransfers[it] = reasonCode }
        active.forEach { terminatedOutgoingTransfers[it] = reasonCode }
        return OutgoingDrain(prepared = prepared, active = active)
    }

    private data class OutgoingDrain(
        val prepared: List<OutgoingTransferStore>,
        val active: List<OutgoingTransferStore>,
    ) {
        fun cancelAll() {
            val outgoing = LinkedHashSet<OutgoingTransferStore>()
            outgoing += prepared
            outgoing += active
            outgoing.forEach(OutgoingTransferStore::cancel)
        }

        companion object {
            val EMPTY = OutgoingDrain(emptyList(), emptyList())
        }
    }

    private fun notifyOutgoingTransfers(drain: OutgoingDrain) {
        val outgoing = LinkedHashSet<OutgoingTransferStore>()
        outgoing += drain.prepared
        outgoing += drain.active
        val results = synchronized(lock) {
            outgoing.mapNotNull { transfer ->
                terminatedOutgoingTransfers.remove(transfer)?.let { reason ->
                    TransferResult(accepted = false, reason = reason)
                }
            }
        }
        results.forEach(::notifyFileTransferResult)
    }

    private fun rejectedFileAccept(transferId: ByteString, reasonCode: String): FileAccept =
        FileAccept
            .newBuilder()
            .setTransferId(transferId)
            .setAccepted(false)
            .setRejectionReason(reasonCode)
            .build()

    private fun validateIncomingOffer(
        offer: FileOffer,
        effectivePolicy: FileTransferPolicy,
    ): String? =
        when {
            !effectivePolicy.allowed || effectivePolicy.maximumFileBytes <= 0L -> "policy_denied"
            offer.transferId.isEmpty -> "invalid_transfer_id"
            !IncomingFileTransferManager.isSafeFileName(offer.fileName) -> "invalid_file_name"
            offer.sha256.size() != SHA256_BYTES -> "invalid_digest"
            offer.byteLength > effectivePolicy.maximumFileBytes -> "file_too_large"
            else -> null
        }

    fun interface IncomingManagerFactory {
        fun create(
            policy: FileTransferPolicy,
            directory: File,
            approve: (FileOffer) -> Boolean,
        ): IncomingTransferStore
    }

    interface IncomingTransferStore {
        fun accept(
            offer: FileOffer,
            remotePolicy: RemoteManagedPolicy,
            negotiatedPolicy: FileTransferPolicy,
            sessionEpoch: Long,
        ): FileAccept

        fun append(chunk: FileChunk, sessionEpoch: Long): Long

        fun finish(transferId: ByteString): CompletedIncomingFile

        fun cancel(transferId: ByteString): Boolean

        fun contains(transferId: ByteString): Boolean

        fun cancelAll()

        fun activeTransferCount(): Int
    }

    private class IncomingFileTransferStore(
        private val manager: IncomingFileTransferManager,
    ) : IncomingTransferStore {
        override fun accept(
            offer: FileOffer,
            remotePolicy: RemoteManagedPolicy,
            negotiatedPolicy: FileTransferPolicy,
            sessionEpoch: Long,
        ): FileAccept = manager.accept(offer, remotePolicy, negotiatedPolicy, sessionEpoch)

        override fun append(chunk: FileChunk, sessionEpoch: Long): Long = manager.append(chunk, sessionEpoch)

        override fun finish(transferId: ByteString): CompletedIncomingFile = manager.finish(transferId)

        override fun cancel(transferId: ByteString): Boolean = manager.cancel(transferId)

        override fun contains(transferId: ByteString): Boolean = manager.contains(transferId)

        override fun cancelAll() = manager.cancelAll()

        override fun activeTransferCount(): Int = manager.activeTransferCount()
    }

    fun interface OutgoingTransferFactory {
        fun create(
            file: File,
            mimeType: String,
            policy: FileTransferPolicy,
            remotePolicy: RemoteManagedPolicy,
        ): OutgoingTransferStore
    }

    interface OutgoingTransferStore {
        val offer: FileOffer

        fun cancel()

        fun applyAcceptedMaximumChunkBytes(maximumBytes: Int)

        fun maximumChunkBytes(defaultBytes: Int): Int

        fun nextChunk(maximumBytes: Int, sessionEpoch: Long): FileChunk?

        fun acknowledgeOffset(receivedBytes: Long): String?

        fun hasCompletedAcknowledgement(): Boolean
    }

    private class OutgoingFileTransferStore(
        private val transfer: OutgoingFileTransfer,
    ) : OutgoingTransferStore {
        override val offer: FileOffer
            get() = transfer.offer

        override fun cancel() = transfer.cancel()

        override fun applyAcceptedMaximumChunkBytes(maximumBytes: Int) =
            transfer.applyAcceptedMaximumChunkBytes(maximumBytes)

        override fun maximumChunkBytes(defaultBytes: Int): Int =
            transfer.maximumChunkBytes(defaultBytes)

        override fun nextChunk(maximumBytes: Int, sessionEpoch: Long): FileChunk? =
            transfer.nextChunk(maximumBytes, sessionEpoch)

        override fun acknowledgeOffset(receivedBytes: Long): String? =
            transfer.acknowledgeOffset(receivedBytes)

        override fun hasCompletedAcknowledgement(): Boolean =
            transfer.hasCompletedAcknowledgement()
    }

    interface PendingOfferGate {
        fun trackFileOffer(
            transferId: ByteString,
            ownerToken: Any,
            connectionGeneration: Long,
        ): Boolean

        fun claimFileOffer(transferId: ByteString): PendingOfferOwner?

        fun releaseFileOffer(transferId: ByteString)

        fun hasFileOffer(transferId: ByteString): Boolean

        fun clearFileOffers()
    }

    data class PendingOfferOwner(
        val ownerToken: Any,
        val connectionGeneration: Long,
    )

    class PreparedOutgoingTransfer internal constructor(
        internal val transfer: OutgoingTransferStore,
    )

    sealed class PrepareOutgoingResult {
        data class Prepared(val transfer: PreparedOutgoingTransfer) : PrepareOutgoingResult()
        data class Rejected(val reasonCode: String) : PrepareOutgoingResult()
    }

    sealed class StartOutgoingResult {
        data class Started(val offer: FileOffer) : StartOutgoingResult()
        data class Rejected(val reasonCode: String) : StartOutgoingResult()
        data class Stale(val reasonCode: String?) : StartOutgoingResult()
    }

    sealed class IncomingChunkResult {
        abstract val transferId: ByteString

        data class Accepted(
            override val transferId: ByteString,
            val receivedBytes: Long,
            val completed: CompletedIncomingFile?,
        ) : IncomingChunkResult()

        data class Rejected(
            override val transferId: ByteString,
            val reasonCode: String,
            val receivedBytes: Long? = null,
            val failure: IOException? = null,
        ) : IncomingChunkResult()
    }

    data class OutgoingUpdate(
        val chunk: FileChunk? = null,
        val cancelTransferId: ByteString? = null,
        val cancelReasonCode: String? = null,
        val result: TransferResult? = null,
    )

    data class TransferResult(
        val accepted: Boolean,
        val reason: String,
    )

}
