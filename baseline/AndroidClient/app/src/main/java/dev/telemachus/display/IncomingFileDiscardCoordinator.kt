package dev.telemachus.display

import android.content.Context
import android.os.Environment
import java.io.IOException
import java.util.concurrent.Executor
import java.util.concurrent.Executors

internal data class IncomingFileDiscardResult(
    val recovery: RecoveredIncomingFile,
    val discard: Result<Unit>,
)

internal typealias IncomingFileDiscardSubscription = ProcessOperationSubscription

/** Keeps an explicitly confirmed recovery discard alive across Activity replacement. */
internal class IncomingFileDiscardCoordinator(
    private val executor: Executor,
    private val loadRecovery: () -> RecoveredIncomingFile?,
    private val discardRecovery: (RecoveredIncomingFile) -> Unit,
) {
    private val operations = ProcessRetainedOperationCoordinator<String, IncomingFileDiscardResult>(
        executor = executor,
        shouldPruneCompleted = { true },
        onObserverFailure = { failure -> android.util.Log.e(LOG_TAG, "Incoming discard observer failed", failure) },
    )

    fun discard(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFileDiscardSubscription, IncomingFileDiscardResult) -> Unit,
    ): IncomingFileDiscardSubscription = operations.subscribeOrStart(recovery.recoveryId, observer) {
        IncomingFileDiscardResult(
            recovery = recovery,
            discard = runCatching {
                val current = loadRecovery() ?: throw IOException("Incoming file recovery is no longer pending")
                if (current.recoveryId != recovery.recoveryId) {
                    throw IOException("Incoming file recovery ownership changed")
                }
                discardRecovery(current)
            },
        )
    }

    fun observe(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFileDiscardSubscription, IncomingFileDiscardResult) -> Unit,
    ): IncomingFileDiscardSubscription? = operations.subscribeExisting(recovery.recoveryId, observer)

    fun observeLatest(
        observer: (IncomingFileDiscardSubscription, IncomingFileDiscardResult) -> Unit,
    ): IncomingFileDiscardSubscription? {
        return operations.subscribeLatest(observer)
    }

    companion object {
        private const val LOG_TAG = "VibeScreenFileDiscard"
        private val PROCESS_LOCK = Any()
        @Volatile private var processInstance: IncomingFileDiscardCoordinator? = null

        fun processShared(context: Context): IncomingFileDiscardCoordinator {
            processInstance?.let { return it }
            return synchronized(PROCESS_LOCK) {
                processInstance ?: create(context.applicationContext).also { processInstance = it }
            }
        }

        private fun create(context: Context): IncomingFileDiscardCoordinator {
            val store = IncomingFileRecoveryStore(context)
            val saver = IncomingFileDownloadsSaver(
                appSpecificDownloads = { context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) },
                mediaStoreDownloads = { ContentResolverMediaStoreDownloadsCollection(context.contentResolver) },
            )
            return IncomingFileDiscardCoordinator(
                executor = Executors.newSingleThreadExecutor { task ->
                    Thread(task, "vibescreen-incoming-file-discard").apply { isDaemon = true }
                },
                loadRecovery = store::load,
                discardRecovery = { recovery -> saver.discardRecoveredIncomingFile(recovery, store) },
            )
        }
    }
}
