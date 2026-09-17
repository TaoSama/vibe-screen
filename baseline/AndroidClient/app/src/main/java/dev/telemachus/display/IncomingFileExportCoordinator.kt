package dev.telemachus.display

import android.content.Context
import android.net.Uri
import java.util.concurrent.Executor
import java.util.concurrent.Executors

internal data class IncomingFileExportRequest(
    val source: Uri,
    val destination: Uri,
    val displayName: String,
    val mimeType: String,
)

internal data class IncomingFileExportResult(
    val request: IncomingFileExportRequest,
    val export: Result<Unit>,
)

internal typealias IncomingFileExportSubscription = ProcessOperationSubscription

/** Keeps a user-selected document export alive across Activity replacement. */
internal class IncomingFileExportCoordinator(
    private val executor: Executor,
    private val exportDocument: (IncomingFileExportRequest) -> Unit,
) {
    private data class OperationKey(
        val source: Uri,
        val destination: Uri,
    )

    private val operations = ProcessRetainedOperationCoordinator<OperationKey, IncomingFileExportResult>(
        executor = executor,
        shouldPruneCompleted = { true },
        onObserverFailure = { failure -> android.util.Log.e(LOG_TAG, "Incoming export observer failed", failure) },
    )

    fun export(
        request: IncomingFileExportRequest,
        observer: (IncomingFileExportSubscription, IncomingFileExportResult) -> Unit,
    ): IncomingFileExportSubscription = operations.subscribeOrStart(OperationKey(request.source, request.destination), observer) {
        IncomingFileExportResult(request, runCatching { exportDocument(request) })
    }

    fun observe(
        request: IncomingFileExportRequest,
        observer: (IncomingFileExportSubscription, IncomingFileExportResult) -> Unit,
    ): IncomingFileExportSubscription? =
        operations.subscribeExisting(OperationKey(request.source, request.destination), observer)

    companion object {
        private const val LOG_TAG = "VibeScreenFileExport"
        private val PROCESS_LOCK = Any()
        @Volatile private var processInstance: IncomingFileExportCoordinator? = null

        fun processShared(context: Context): IncomingFileExportCoordinator {
            processInstance?.let { return it }
            return synchronized(PROCESS_LOCK) {
                processInstance ?: create(context.applicationContext).also { processInstance = it }
            }
        }

        private fun create(context: Context): IncomingFileExportCoordinator =
            IncomingFileExportCoordinator(
                executor = Executors.newSingleThreadExecutor { task ->
                    Thread(task, "vibescreen-incoming-file-export").apply { isDaemon = true }
                },
                exportDocument = { request ->
                    IncomingFileDocumentExporter(context.contentResolver).export(request.source, request.destination)
                },
            )
    }
}
