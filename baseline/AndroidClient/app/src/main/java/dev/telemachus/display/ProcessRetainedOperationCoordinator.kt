package dev.telemachus.display

import java.io.Closeable
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

internal interface ProcessOperationSubscription : Closeable {
    fun consume(): Boolean
}

/** Retains one keyed background operation until a UI observer consumes its completed result. */
internal class ProcessRetainedOperationCoordinator<Key : Any, Result : Any>(
    private val executor: Executor,
    private val shouldPruneCompleted: (Result) -> Boolean,
    private val onObserverFailure: (Throwable) -> Unit,
) {
    private class Observer<Result : Any>(
        val id: Long,
        val active: AtomicBoolean,
        val subscription: ProcessOperationSubscription,
        val callback: (ProcessOperationSubscription, Result) -> Unit,
    )

    private class Operation<Result : Any> {
        val observers = LinkedHashMap<Long, Observer<Result>>()
        var result: Result? = null
    }

    private val lock = Any()
    private val nextObserverId = AtomicLong(0L)
    private val operations = LinkedHashMap<Key, Operation<Result>>()

    fun subscribeOrStart(
        key: Key,
        callback: (ProcessOperationSubscription, Result) -> Unit,
        work: () -> Result,
    ): ProcessOperationSubscription {
        var start = false
        val observer = observer(key, callback)
        val completed: Result?
        synchronized(lock) {
            val completedOldKeys = operations.entries
                .filter { (oldKey, operation) ->
                    oldKey != key && operation.result?.let(shouldPruneCompleted) == true
                }.map { it.key }
            completedOldKeys.forEach { oldKey ->
                operations.remove(oldKey)?.observers?.values?.forEach { it.active.set(false) }
            }
            val operation = operations.getOrPut(key) {
                start = true
                Operation()
            }
            operation.observers[observer.id] = observer
            completed = operation.result
        }
        if (start) executor.execute { complete(key, work()) }
        completed?.let { notify(observer, it) }
        return observer.subscription
    }

    fun subscribeExisting(
        key: Key,
        callback: (ProcessOperationSubscription, Result) -> Unit,
    ): ProcessOperationSubscription? {
        val observer = observer(key, callback)
        val completed: Result?
        synchronized(lock) {
            val operation = operations[key] ?: return null
            operation.observers[observer.id] = observer
            completed = operation.result
        }
        completed?.let { notify(observer, it) }
        return observer.subscription
    }

    fun subscribeLatest(
        callback: (ProcessOperationSubscription, Result) -> Unit,
    ): ProcessOperationSubscription? {
        val key = synchronized(lock) { operations.keys.lastOrNull() } ?: return null
        return subscribeExisting(key, callback)
    }

    private fun complete(key: Key, result: Result) {
        val observers = synchronized(lock) {
            val operation = operations[key] ?: return
            operation.result = result
            operation.observers.values.toList()
        }
        observers.forEach { notify(it, result) }
    }

    private fun consume(key: Key): Boolean = synchronized(lock) {
        val operation = operations[key] ?: return@synchronized false
        if (operation.result == null) return@synchronized false
        operations.remove(key)
        operation.observers.values.forEach { it.active.set(false) }
        true
    }

    private fun notify(observer: Observer<Result>, result: Result) {
        if (!observer.active.get()) return
        runCatching { observer.callback(observer.subscription, result) }.onFailure(onObserverFailure)
    }

    private fun observer(
        key: Key,
        callback: (ProcessOperationSubscription, Result) -> Unit,
    ): Observer<Result> {
        val observerId = nextObserverId.incrementAndGet()
        val active = AtomicBoolean(true)
        val subscription = subscription(key, observerId, active)
        return Observer(observerId, active, subscription, callback)
    }

    private fun subscription(
        key: Key,
        observerId: Long,
        active: AtomicBoolean,
    ): ProcessOperationSubscription =
        object : ProcessOperationSubscription {
            override fun close() {
                if (!active.compareAndSet(true, false)) return
                synchronized(lock) { operations[key]?.observers?.remove(observerId) }
            }

            override fun consume(): Boolean = consume(key)
        }
}
