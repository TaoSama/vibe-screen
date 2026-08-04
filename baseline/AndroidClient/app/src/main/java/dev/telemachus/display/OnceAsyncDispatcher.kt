package dev.telemachus.display

import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean

/** Claims one terminal value synchronously and completes it on the selected execution context. */
internal class OnceAsyncDispatcher<T : Any>(
    private val executor: Executor,
    private val onClaim: (T) -> Unit,
    private val complete: (T) -> Unit,
) {
    private val claimed = AtomicBoolean(false)

    fun dispatch(value: T): Boolean {
        if (!claim(value)) return false
        executor.execute { complete(value) }
        return true
    }

    fun completeNow(value: T): Boolean {
        if (!claim(value)) return false
        complete(value)
        return true
    }

    fun isClaimed(): Boolean = claimed.get()

    private fun claim(value: T): Boolean {
        if (!claimed.compareAndSet(false, true)) return false
        onClaim(value)
        return true
    }
}
