package dev.telemachus.display

import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * A bounded, single-writer scheduler for latency-sensitive outbound commands.
 *
 * Recovery commands are written before input commands. Pending moves, pings, and
 * keyframe requests are each represented by at most one entry; submitting a new
 * command of the same coalescing kind replaces the older pending command.
 * Admitted structural touch commands retain FIFO order. Saturation is reported
 * as [Submission.TIMED_OUT], allowing the session owner to fail closed rather
 * than silently lose a boundary or leave remote input pressed.
 */
class OutboundCommandScheduler<C : Any>(
    private val capacity: Int,
    private val writer: (C) -> Unit,
    private val onWriteFailure: (OutboundWriteFailure<C>) -> Unit,
    private val coalesce: (Kind, C, C) -> C = { _, _, replacement -> replacement },
    threadName: String = "OutboundCommandWriter",
) : AutoCloseable {
    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    enum class Kind {
        STRUCTURAL_TOUCH,
        MOVE,
        KEYFRAME,
        PING,
    }

    enum class Submission {
        ACCEPTED,
        COALESCED,
        ACCEPTED_AFTER_COALESCING_MOVE,
        TIMED_OUT,
        CLOSED,
    }

    private enum class State {
        OPEN,
        CLOSING,
        FAILED,
        CLOSED,
    }

    private val lock = ReentrantLock()
    private val hasWork = lock.newCondition()
    private val hasSpace = lock.newCondition()
    private val terminated = lock.newCondition()
    private val touchCommands = ArrayDeque<PendingTouch<C>>()
    private var keyframe: C? = null
    private var ping: C? = null
    private var pendingCount = 0
    private var state = State.OPEN
    private var failureCallbackClaimed = false
    private var workerStarted = false
    private val recoveryReservedSlots = if (capacity >= MIN_CAPACITY_WITH_RECOVERY_RESERVE) 2 else 0

    private val worker =
        Thread(::runWriter, threadName).apply {
            isDaemon = true
        }

    /**
     * Submits a command, waiting up to [timeoutMillis] for bounded queue space.
     * A zero timeout performs a non-blocking submission.
     */
    @Throws(InterruptedException::class)
    fun submit(
        kind: Kind,
        command: C,
        timeoutMillis: Long = 0,
    ): Submission {
        require(timeoutMillis >= 0) { "timeoutMillis must not be negative" }
        val deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        val acquired =
            if (timeoutMillis == 0L) {
                lock.tryLock()
            } else {
                lock.tryLock(timeoutMillis, TimeUnit.MILLISECONDS)
            }
        if (!acquired) return Submission.TIMED_OUT
        try {
            if (state != State.OPEN) return Submission.CLOSED

            replacePending(kind, command)?.let { return it }

            var remainingNanos = (deadlineNs - System.nanoTime()).coerceAtLeast(0L)
            while (pendingCount >= admissionLimit(kind)) {
                if (kind != Kind.MOVE && removeOldestMove()) {
                    pendingCount--
                    enqueue(kind, command)
                    return Submission.ACCEPTED_AFTER_COALESCING_MOVE
                }
                if (remainingNanos <= 0) return Submission.TIMED_OUT
                remainingNanos = hasSpace.awaitNanos(remainingNanos)
                if (state != State.OPEN) return Submission.CLOSED
                replacePending(kind, command)?.let { return it }
            }

            enqueue(kind, command)
            return Submission.ACCEPTED
        } finally {
            lock.unlock()
        }
    }

    /** Stops accepting new commands, drains accepted commands, and waits for termination. */
    @Throws(InterruptedException::class)
    fun shutdownGracefully(timeoutMillis: Long): Boolean {
        require(timeoutMillis >= 0) { "timeoutMillis must not be negative" }
        lock.lockInterruptibly()
        try {
            if (state == State.OPEN) {
                if (!workerStarted && pendingCount == 0) {
                    state = State.CLOSED
                    terminated.signalAll()
                } else {
                    state = State.CLOSING
                    hasWork.signalAll()
                }
            }
            var remainingNanos = TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
            while (state != State.CLOSED && state != State.FAILED) {
                if (remainingNanos <= 0) return false
                remainingNanos = terminated.awaitNanos(remainingNanos)
            }
            return true
        } finally {
            lock.unlock()
        }
    }

    /** Immediately rejects new work and discards commands that have not started writing. */
    fun shutdownNow() {
        lock.withLock {
            if (state == State.CLOSED || state == State.FAILED) return
            clearPending()
            state = State.CLOSED
            hasWork.signalAll()
            hasSpace.signalAll()
            terminated.signalAll()
        }
    }

    override fun close() {
        if (!shutdownGracefully(DEFAULT_CLOSE_TIMEOUT_MS)) shutdownNow()
    }

    private fun replacePending(
        kind: Kind,
        command: C,
    ): Submission? =
        when (kind) {
            Kind.MOVE -> {
                val lastTouch = touchCommands.lastOrNull()
                if (lastTouch?.kind == Kind.MOVE) {
                    touchCommands[touchCommands.lastIndex] =
                        PendingTouch(Kind.MOVE, coalesce(Kind.MOVE, lastTouch.command, command))
                    Submission.COALESCED
                } else {
                    null
                }
            }
            Kind.KEYFRAME ->
                keyframe?.let {
                    keyframe = coalesce(Kind.KEYFRAME, it, command)
                    Submission.COALESCED
                }
            Kind.PING ->
                ping?.let {
                    ping = coalesce(Kind.PING, it, command)
                    Submission.COALESCED
                }
            Kind.STRUCTURAL_TOUCH -> null
        }

    private fun enqueue(
        kind: Kind,
        command: C,
    ) {
        when (kind) {
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            -> touchCommands.addLast(PendingTouch(kind, command))
            Kind.KEYFRAME -> keyframe = command
            Kind.PING -> ping = command
        }
        pendingCount++
        check(pendingCount <= capacity)
        if (!workerStarted) {
            workerStarted = true
            worker.start()
        }
        hasWork.signal()
    }

    private fun runWriter() {
        while (true) {
            val command =
                lock.withLock {
                    while (pendingCount == 0 && state == State.OPEN) hasWork.await()
                    if (pendingCount == 0 && state != State.OPEN) {
                        if (state == State.CLOSING) state = State.CLOSED
                        terminated.signalAll()
                        return
                    }
                    takeNext().also {
                        pendingCount--
                        hasSpace.signalAll()
                    }
                }

            try {
                writer(command)
            } catch (cause: Throwable) {
                fail(command, cause)
                return
            }
        }
    }

    private fun takeNext(): C {
        keyframe?.let {
            keyframe = null
            return it
        }
        ping?.let {
            ping = null
            return it
        }
        return touchCommands.removeFirst().command
    }

    private fun fail(
        command: C,
        cause: Throwable,
    ) {
        val failure = OutboundWriteFailure(command, cause)
        val shouldDeliver =
            lock.withLock {
                if (state == State.CLOSED) return
                clearPending()
                state = State.FAILED
                hasSpace.signalAll()
                terminated.signalAll()
                if (failureCallbackClaimed) false else true.also { failureCallbackClaimed = true }
            }
        if (shouldDeliver) onWriteFailure(failure)
    }

    private fun clearPending() {
        touchCommands.clear()
        keyframe = null
        ping = null
        pendingCount = 0
    }

    private fun removeOldestMove(): Boolean {
        val index = touchCommands.indexOfFirst { it.kind == Kind.MOVE }
        if (index < 0) return false
        touchCommands.removeAt(index)
        return true
    }

    private fun admissionLimit(kind: Kind): Int =
        when (kind) {
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            -> capacity - recoveryReservedSlots

            Kind.KEYFRAME,
            Kind.PING,
            -> capacity
        }

    private data class PendingTouch<C : Any>(
        val kind: Kind,
        val command: C,
    )

    private companion object {
        const val DEFAULT_CLOSE_TIMEOUT_MS = 5_000L
        const val MIN_CAPACITY_WITH_RECOVERY_RESERVE = 4
    }
}

data class OutboundWriteFailure<C : Any>(
    val command: C,
    val cause: Throwable,
)
