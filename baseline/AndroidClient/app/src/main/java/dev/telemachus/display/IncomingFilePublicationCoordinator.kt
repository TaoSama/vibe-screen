package dev.telemachus.display

import android.content.Context
import android.net.Uri
import android.os.Environment
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import java.io.IOException
import java.util.concurrent.Executor
import java.util.concurrent.Executors

internal data class IncomingFilePublicationResult(
    val recovery: RecoveredIncomingFile,
    val publication: Result<Uri>,
)

internal typealias IncomingFilePublicationSubscription = ProcessOperationSubscription

/** Keeps incoming Downloads publication alive across Activity replacement. */
internal class IncomingFilePublicationCoordinator(
    private val executor: Executor,
    private val loadRecovery: () -> RecoveredIncomingFile?,
    private val publishRecovery: (RecoveredIncomingFile) -> Uri,
) {
    private data class OperationKey(
        val transferId: ByteString,
        val sha256: ByteString,
    )

    private val operations = ProcessRetainedOperationCoordinator<OperationKey, Result<IncomingFilePublicationResult>>(
        executor = executor,
        shouldPruneCompleted = Result<IncomingFilePublicationResult>::isSuccess,
        onObserverFailure = { failure -> android.util.Log.e(LOG_TAG, "Incoming publication observer failed", failure) },
    )

    fun publish(
        completed: CompletedIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription = operations.subscribeOrStart(key(completed.transferId, completed.sha256), observer) {
        runCatching {
            val recovery = loadMatchingRecovery(completed.transferId, completed.sha256, completed.stagingFile.canonicalFile)
            IncomingFilePublicationResult(recovery, runCatching { publishRecovery(recovery) })
        }
    }

    fun publish(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription = operations.subscribeOrStart(key(recovery.transferId, recovery.sha256), observer) {
        runCatching {
            val current = loadMatchingRecovery(recovery.transferId, recovery.sha256, recovery.payloadFile.canonicalFile)
            IncomingFilePublicationResult(current, runCatching { publishRecovery(current) })
        }
    }

    fun observe(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription? = operations.subscribeExisting(key(recovery.transferId, recovery.sha256), observer)

    fun observeLatest(
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription? {
        return operations.subscribeLatest(observer)
    }

    private fun loadMatchingRecovery(
        transferId: ByteString,
        sha256: ByteString,
        expectedPayload: java.io.File,
    ): RecoveredIncomingFile {
        val recovery = loadRecovery() ?: throw IOException("Durable incoming recovery ownership is unavailable")
        if (recovery.transferId != transferId ||
            recovery.sha256 != sha256 ||
            recovery.payloadFile.canonicalFile != expectedPayload
        ) {
            throw IOException("Durable incoming recovery ownership changed")
        }
        return recovery
    }

    private fun key(transferId: ByteString, sha256: ByteString) = OperationKey(transferId, sha256)

    companion object {
        private const val LOG_TAG = "VibeScreenFilePublish"
        private val PROCESS_LOCK = Any()
        @Volatile private var processInstance: IncomingFilePublicationCoordinator? = null

        fun processShared(context: Context): IncomingFilePublicationCoordinator {
            processInstance?.let { return it }
            return synchronized(PROCESS_LOCK) {
                processInstance ?: create(context.applicationContext).also { processInstance = it }
            }
        }

        private fun create(context: Context): IncomingFilePublicationCoordinator {
            val store = IncomingFileRecoveryStore(context)
            val saver = IncomingFileDownloadsSaver(
                appSpecificDownloads = { context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) },
                mediaStoreDownloads = { ContentResolverMediaStoreDownloadsCollection(context.contentResolver) },
            )
            return IncomingFilePublicationCoordinator(
                executor = Executors.newSingleThreadExecutor { task ->
                    Thread(task, "vibescreen-incoming-file-publication").apply { isDaemon = true }
                },
                loadRecovery = store::load,
                publishRecovery = { recovery -> saver.publishRecoveredIncomingFile(recovery, store) },
            )
        }
    }
}
