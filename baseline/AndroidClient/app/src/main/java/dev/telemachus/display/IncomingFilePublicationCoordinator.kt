package dev.telemachus.display

import android.content.Context
import android.net.Uri
import android.os.Environment
import com.google.protobuf.ByteString
import dev.telemachus.display.protocol.CompletedIncomingFile
import java.io.Closeable
import java.io.IOException
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

internal data class IncomingFilePublicationResult(
    val recovery: RecoveredIncomingFile,
    val publication: Result<Uri>,
)

internal interface IncomingFilePublicationSubscription : Closeable {
    fun consume(): Boolean
}

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

    private class Observer(
        val id: Long,
        val active: AtomicBoolean,
        val subscription: IncomingFilePublicationSubscription,
        val callback: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    )

    private class Operation {
        val observers = LinkedHashMap<Long, Observer>()
        var result: Result<IncomingFilePublicationResult>? = null
    }

    private val lock = Any()
    private val nextObserverId = AtomicLong(0L)
    private val operations = LinkedHashMap<OperationKey, Operation>()

    fun publish(
        completed: CompletedIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription = subscribeOrStart(key(completed.transferId, completed.sha256), observer) {
        val recovery = loadMatchingRecovery(completed.transferId, completed.sha256, completed.stagingFile.canonicalFile)
        IncomingFilePublicationResult(recovery, runCatching { publishRecovery(recovery) })
    }

    fun publish(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription = subscribeOrStart(key(recovery.transferId, recovery.sha256), observer) {
        val current = loadMatchingRecovery(recovery.transferId, recovery.sha256, recovery.payloadFile.canonicalFile)
        IncomingFilePublicationResult(current, runCatching { publishRecovery(current) })
    }

    fun observe(
        recovery: RecoveredIncomingFile,
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription? = subscribeExisting(key(recovery.transferId, recovery.sha256), observer)

    fun observeLatest(
        observer: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription? {
        val operationKey = synchronized(lock) { operations.keys.lastOrNull() } ?: return null
        return subscribeExisting(operationKey, observer)
    }

    private fun consume(operationKey: OperationKey): Boolean = synchronized(lock) {
        val operation = operations[operationKey] ?: return@synchronized false
        if (operation.result == null) return@synchronized false
        operations.remove(operationKey)
        operation.observers.values.forEach { it.active.set(false) }
        true
    }

    private fun subscribeOrStart(
        operationKey: OperationKey,
        callback: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
        work: () -> IncomingFilePublicationResult,
    ): IncomingFilePublicationSubscription {
        var start = false
        val observer = observer(operationKey, callback)
        val completed: Result<IncomingFilePublicationResult>?
        synchronized(lock) {
            val completedOldKeys = operations.entries
                .filter { (key, operation) -> key != operationKey && operation.result?.isSuccess == true }
                .map { it.key }
            completedOldKeys.forEach { oldKey ->
                operations.remove(oldKey)?.observers?.values?.forEach { it.active.set(false) }
            }
            val operation = operations.getOrPut(operationKey) {
                start = true
                Operation()
            }
            operation.observers[observer.id] = observer
            completed = operation.result
        }
        if (start) executor.execute { complete(operationKey, runCatching(work)) }
        completed?.let { notify(observer, it) }
        return observer.subscription
    }

    private fun subscribeExisting(
        operationKey: OperationKey,
        callback: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): IncomingFilePublicationSubscription? {
        val observer = observer(operationKey, callback)
        val completed: Result<IncomingFilePublicationResult>?
        synchronized(lock) {
            val operation = operations[operationKey] ?: return null
            operation.observers[observer.id] = observer
            completed = operation.result
        }
        completed?.let { notify(observer, it) }
        return observer.subscription
    }

    private fun complete(
        operationKey: OperationKey,
        result: Result<IncomingFilePublicationResult>,
    ) {
        val observers = synchronized(lock) {
            val operation = operations[operationKey] ?: return
            operation.result = result
            operation.observers.values.toList()
        }
        observers.forEach { notify(it, result) }
    }

    private fun notify(
        observer: Observer,
        result: Result<IncomingFilePublicationResult>,
    ) {
        if (!observer.active.get()) return
        runCatching { observer.callback(observer.subscription, result) }
            .onFailure { android.util.Log.e(LOG_TAG, "Incoming publication observer failed", it) }
    }

    private fun observer(
        operationKey: OperationKey,
        callback: (IncomingFilePublicationSubscription, Result<IncomingFilePublicationResult>) -> Unit,
    ): Observer {
        val observerId = nextObserverId.incrementAndGet()
        val active = AtomicBoolean(true)
        val subscription = subscription(operationKey, observerId, active)
        return Observer(observerId, active, subscription, callback)
    }

    private fun subscription(
        operationKey: OperationKey,
        observerId: Long,
        active: AtomicBoolean,
    ): IncomingFilePublicationSubscription =
        object : IncomingFilePublicationSubscription {
            override fun close() {
                if (!active.compareAndSet(true, false)) return
                synchronized(lock) { operations[operationKey]?.observers?.remove(observerId) }
            }

            override fun consume(): Boolean = consume(operationKey)
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
