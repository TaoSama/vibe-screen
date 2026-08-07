package dev.telemachus.display.internet

internal data class PeerControlSendSnapshot<Channel : Any, Cipher : Any>(
    val channel: Channel,
    val cipher: Cipher,
    val generation: Long,
)

internal data class PeerMediaSendSnapshot<Channel : Any, Cipher : Any>(
    val channel: Channel,
    val cipher: Cipher,
    val generation: Long,
)

internal data class PeerInboundCallbackSource<Channel : Any>(
    val channel: Channel,
    val generation: Long,
)

internal data class PeerInboundReceiveSnapshot<Channel : Any, Cipher : Any, Target : Any>(
    val source: PeerInboundCallbackSource<Channel>,
    val cipher: Cipher,
    val target: Target,
    val sessionEpoch: Long,
) {
    val channel: Channel get() = source.channel
    val generation: Long get() = source.generation
}

internal fun interface PeerRetryCancellation {
    fun cancel()
}

internal fun interface PeerRetryScheduler {
    fun schedule(task: () -> Unit): PeerRetryCancellation
}

/** Keeps at most one retry queued and makes cancellation race-safe. */
internal class PeerMediaRetryGate<Key : Any>(
    private val scheduler: PeerRetryScheduler,
) {
    private val lock = Any()
    private var pending: Pending<Key>? = null

    fun schedule(
        key: Key,
        operation: (Key) -> Unit,
    ): Boolean {
        val token =
            synchronized(lock) {
                if (pending != null) return false
                Pending(key).also { pending = it }
            }
        val cancellation =
            try {
                scheduler.schedule { run(token, operation) }
            } catch (failure: Throwable) {
                synchronized(lock) {
                    if (pending === token) pending = null
                }
                throw failure
            }
        val cancelImmediately =
            synchronized(lock) {
                if (pending === token) {
                    token.cancellation = cancellation
                    false
                } else {
                    true
                }
            }
        if (cancelImmediately) cancellation.cancel()
        return true
    }

    fun cancel() {
        val cancellation =
            synchronized(lock) {
                val token = pending ?: return
                pending = null
                token.cancellation
            }
        cancellation?.cancel()
    }

    private fun run(
        token: Pending<Key>,
        operation: (Key) -> Unit,
    ) {
        val key =
            synchronized(lock) {
                if (pending !== token) return
                pending = null
                token.key
            }
        operation(key)
    }

    private class Pending<Key : Any>(
        val key: Key,
        var cancellation: PeerRetryCancellation? = null,
    )
}

/** Serializes data-channel I/O with connection-generation transitions. */
internal class PeerSendLinearizer {
    private val monitor = java.lang.Object()
    private var owner: Thread? = null
    private var depth = 0

    /**
     * The intrinsic monitor is released before [operation] runs. Ownership still excludes other
     * threads, while same-thread callbacks may re-enter without deadlocking.
     */
    fun <T> withGate(operation: () -> T): T {
        enter()
        return try {
            operation()
        } finally {
            exit()
        }
    }

    fun <Channel : Any, Cipher : Any, Result> withCurrentMediaPath(
        snapshot: () -> PeerMediaSendSnapshot<Channel, Cipher>?,
        isCurrent: (PeerMediaSendSnapshot<Channel, Cipher>) -> Boolean,
        operation: (PeerMediaSendSnapshot<Channel, Cipher>) -> Result,
    ): Result? =
        withGate {
            val candidate = snapshot() ?: return@withGate null
            if (!isCurrent(candidate)) return@withGate null
            operation(candidate)
        }

    fun <Channel : Any, Cipher : Any> sendControl(
        snapshot: () -> PeerControlSendSnapshot<Channel, Cipher>?,
        seal: (Cipher) -> ByteArray,
        isCurrent: (PeerControlSendSnapshot<Channel, Cipher>) -> Boolean,
        transmit: (Channel, ByteArray) -> Boolean,
    ): Boolean =
        withGate {
            val candidate =
                try {
                    snapshot()
                } catch (_: IllegalStateException) {
                    null
                } ?: return@withGate false
            val record =
                try {
                    seal(candidate.cipher)
                } catch (_: IllegalStateException) {
                    return@withGate false
                }
            val stillCurrent =
                try {
                    isCurrent(candidate)
                } catch (_: IllegalStateException) {
                    false
                }
            if (!stillCurrent) return@withGate false
            try {
                transmit(candidate.channel, record)
            } catch (_: IllegalStateException) {
                false
            }
        }

    fun <Channel : Any, Cipher : Any, Target : Any> receiveInbound(
        snapshot: () -> PeerInboundReceiveSnapshot<Channel, Cipher, Target>?,
        decode: (Cipher) -> ByteArray?,
        isCurrent: (PeerInboundReceiveSnapshot<Channel, Cipher, Target>) -> Boolean,
        onDecodeFailure: (Exception) -> Unit,
        deliver: (Target, Long, ByteArray) -> Unit,
    ): Boolean =
        withGate {
            val candidate =
                try {
                    snapshot()
                } catch (_: IllegalStateException) {
                    null
                } ?: return@withGate false
            val payload =
                try {
                    decode(candidate.cipher)
                } catch (failure: Exception) {
                    onDecodeFailure(failure)
                    return@withGate false
                } ?: return@withGate false
            val stillCurrent =
                try {
                    isCurrent(candidate)
                } catch (_: IllegalStateException) {
                    false
                }
            if (!stillCurrent) return@withGate false
            deliver(candidate.target, candidate.sessionEpoch, payload)
            true
        }

    private fun enter() {
        val current = Thread.currentThread()
        synchronized(monitor) {
            while (owner != null && owner !== current) monitor.wait()
            owner = current
            depth++
        }
    }

    private fun exit() {
        val current = Thread.currentThread()
        synchronized(monitor) {
            check(owner === current && depth > 0) { "Peer I/O gate ownership is inconsistent" }
            depth--
            if (depth == 0) {
                owner = null
                monitor.notifyAll()
            }
        }
    }
}
