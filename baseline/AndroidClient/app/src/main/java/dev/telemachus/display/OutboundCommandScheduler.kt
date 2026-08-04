package dev.telemachus.display

import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.locks.ReentrantLock
import java.util.concurrent.locks.LockSupport
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
    private val beforeOverflowPublish: () -> Unit = {},
    private val afterOverflowValuePublished: () -> Unit = {},
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
    private val hasSpace = lock.newCondition()
    private val terminated = lock.newCondition()
    private val ingress = ConcurrentLinkedQueue<IngressCommand<C>>()
    private val overflowKeyframe = AtomicReference(OverflowSlot<C>(accepting = true, command = null))
    private val overflowPing = AtomicReference(OverflowSlot<C>(accepting = true, command = null))
    private val occupiedCount = AtomicInteger()
    private val accepting = AtomicBoolean(true)
    private val workerStarted = AtomicBoolean(false)
    private val touchCommands = ArrayDeque<PendingTouch<C>>()
    private var keyframe: C? = null
    private var ping: C? = null
    private var pendingCount = 0
    @Volatile private var state = State.OPEN
    private var failureCallbackClaimed = false
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
        if (!accepting.get()) return Submission.CLOSED
        val deadlineNs = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis)
        val acquired =
            if (timeoutMillis == 0L) {
                lock.tryLock()
            } else {
                lock.tryLock(timeoutMillis, TimeUnit.MILLISECONDS)
            }
        if (!acquired) return submitThroughIngress(kind, command)
        try {
            drainIngressLocked()
            if (!accepting.get() || state != State.OPEN) return Submission.CLOSED

            replacePending(kind, command)?.let { return it }

            var remainingNanos = (deadlineNs - System.nanoTime()).coerceAtLeast(0L)
            while (!reserveSlot(kind)) {
                if (kind != Kind.MOVE && removeOldestMove()) {
                    pendingCount--
                    occupiedCount.decrementAndGet()
                    if (reserveSlot(kind)) {
                        enqueueReserved(kind, command)
                        return Submission.ACCEPTED_AFTER_COALESCING_MOVE
                    }
                }
                if (remainingNanos <= 0) return Submission.TIMED_OUT
                remainingNanos = hasSpace.awaitNanos(remainingNanos)
                if (state != State.OPEN) return Submission.CLOSED
                drainIngressLocked()
                replacePending(kind, command)?.let { return it }
            }

            enqueueReserved(kind, command)
            return Submission.ACCEPTED
        } finally {
            lock.unlock()
        }
    }

    private fun submitThroughIngress(
        kind: Kind,
        command: C,
    ): Submission {
        if (!accepting.get() || state != State.OPEN) return Submission.CLOSED
        if (!reserveSlot(kind)) return submitCoalescibleOverflow(kind, command)
        val ingressCommand = IngressCommand(kind, command, reservedSlot = true)
        ingress.add(ingressCommand)
        ensureWorkerStarted()
        LockSupport.unpark(worker)
        if (accepting.get() && state == State.OPEN) return Submission.ACCEPTED
        if (ingressCommand.cancel()) {
            occupiedCount.decrementAndGet()
            return Submission.CLOSED
        }
        return if (ingressCommand.wasDrained()) Submission.ACCEPTED else Submission.CLOSED
    }

    private fun submitCoalescibleOverflow(
        kind: Kind,
        command: C,
    ): Submission {
        val overflow = overflowSlot(kind) ?: return Submission.TIMED_OUT
        beforeOverflowPublish()
        while (true) {
            val slot = overflow.get()
            if (!slot.accepting) return Submission.CLOSED
            val replacement = if (slot.command == null) command else coalesce(kind, slot.command, command)
            if (!overflow.compareAndSet(slot, OverflowSlot(accepting = true, command = replacement))) continue
            if (slot.command != null) return Submission.COALESCED
            afterOverflowValuePublished()
            overflow.get().let { published ->
                if (published.command == null) {
                    return if (published.discarded) Submission.CLOSED else Submission.ACCEPTED
                }
            }
            val marker = IngressCommand<C>(kind, command = null, reservedSlot = false)
            ingress.add(marker)
            ensureWorkerStarted()
            LockSupport.unpark(worker)
            return Submission.ACCEPTED
        }
    }

    /** Stops accepting new commands, drains accepted commands, and waits for termination. */
    @Throws(InterruptedException::class)
    fun shutdownGracefully(timeoutMillis: Long): Boolean {
        require(timeoutMillis >= 0) { "timeoutMillis must not be negative" }
        lock.lockInterruptibly()
        try {
            if (state == State.OPEN) {
                accepting.set(false)
                closeOverflowAdmissions(preserveCommands = true)
                drainOverflowSlotsLocked()
                drainIngressLocked()
                if (!workerStarted.get() && pendingCount == 0) {
                    state = State.CLOSED
                    terminated.signalAll()
                } else {
                    state = State.CLOSING
                    LockSupport.unpark(worker)
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
            accepting.set(false)
            closeOverflowAdmissions(preserveCommands = false)
            clearPending()
            state = State.CLOSED
            hasSpace.signalAll()
            terminated.signalAll()
            LockSupport.unpark(worker)
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

    private fun enqueueReserved(
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
        ensureWorkerStarted()
        LockSupport.unpark(worker)
    }

    private fun runWriter() {
        while (true) {
            val command: C? =
                lock.withLock {
                    drainIngressLocked()
                    if (pendingCount == 0 && state != State.OPEN) {
                        if (state == State.CLOSING) state = State.CLOSED
                        terminated.signalAll()
                        return
                    }
                    if (pendingCount == 0) {
                        null
                    } else {
                        takeNext().also {
                            pendingCount--
                            occupiedCount.decrementAndGet()
                            hasSpace.signalAll()
                        }
                    }
                }

            if (command == null) {
                LockSupport.park(this)
                continue
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
                accepting.set(false)
                closeOverflowAdmissions(preserveCommands = false)
                clearPending()
                state = State.FAILED
                hasSpace.signalAll()
                terminated.signalAll()
                if (failureCallbackClaimed) false else true.also { failureCallbackClaimed = true }
            }
        if (shouldDeliver) onWriteFailure(failure)
    }

    private fun clearPending() {
        occupiedCount.addAndGet(-pendingCount)
        touchCommands.clear()
        keyframe = null
        ping = null
        pendingCount = 0
        overflowKeyframe.set(OverflowSlot(accepting = false, command = null, discarded = true))
        overflowPing.set(OverflowSlot(accepting = false, command = null, discarded = true))
        while (true) {
            val command = ingress.poll() ?: break
            if (command.claimForDrain(accepted = false) && command.reservedSlot) {
                occupiedCount.decrementAndGet()
            }
        }
    }

    private fun removeOldestMove(): Boolean {
        val index = touchCommands.indexOfFirst { it.kind == Kind.MOVE }
        if (index < 0) return false
        touchCommands.removeAt(index)
        return true
    }

    private fun reserveSlot(kind: Kind): Boolean {
        val limit = admissionLimit(kind)
        while (true) {
            val occupied = occupiedCount.get()
            if (occupied >= limit) return false
            if (occupiedCount.compareAndSet(occupied, occupied + 1)) return true
        }
    }

    private fun drainIngressLocked() {
        while (true) {
            val ingressCommand = ingress.poll() ?: return
            val acceptsPreviouslyAdmitted = state == State.OPEN || state == State.CLOSING
            if (!ingressCommand.claimForDrain(acceptsPreviouslyAdmitted)) continue
            if (!acceptsPreviouslyAdmitted) {
                if (ingressCommand.reservedSlot) occupiedCount.decrementAndGet()
                continue
            }
            val command = ingressCommand.command ?: takeOverflow(ingressCommand.kind) ?: continue
            val merged = replacePending(ingressCommand.kind, command)
            if (merged != null) {
                if (ingressCommand.reservedSlot) occupiedCount.decrementAndGet()
                hasSpace.signalAll()
            } else {
                val hasReservation = ingressCommand.reservedSlot || reserveSlot(ingressCommand.kind)
                if (hasReservation) {
                    enqueueReserved(ingressCommand.kind, command)
                } else {
                    restoreOverflow(ingressCommand.kind, command)
                    ingress.add(IngressCommand(ingressCommand.kind, command = null, reservedSlot = false))
                    return
                }
            }
        }
    }

    private fun takeOverflow(kind: Kind): C? {
        val overflow = overflowSlot(kind) ?: return null
        while (true) {
            val slot = overflow.get()
            val command = slot.command ?: return null
            if (overflow.compareAndSet(slot, slot.copy(command = null))) return command
        }
    }

    private fun restoreOverflow(
        kind: Kind,
        command: C,
    ) {
        val overflow = checkNotNull(overflowSlot(kind))
        while (true) {
            val slot = overflow.get()
            val replacement = if (slot.command == null) command else coalesce(kind, command, slot.command)
            if (overflow.compareAndSet(slot, slot.copy(command = replacement))) return
        }
    }

    private fun overflowSlot(kind: Kind): AtomicReference<OverflowSlot<C>>? =
        when (kind) {
            Kind.KEYFRAME -> overflowKeyframe
            Kind.PING -> overflowPing
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            -> null
        }

    private fun closeOverflowAdmissions(preserveCommands: Boolean) {
        listOf(overflowKeyframe, overflowPing).forEach { overflow ->
            while (true) {
                val slot = overflow.get()
                val closed =
                    OverflowSlot(
                        accepting = false,
                        command = if (preserveCommands) slot.command else null,
                        discarded = !preserveCommands,
                    )
                if (overflow.compareAndSet(slot, closed)) break
            }
        }
    }

    private fun drainOverflowSlotsLocked() {
        listOf(Kind.KEYFRAME, Kind.PING).forEach { kind ->
            val command = takeOverflow(kind) ?: return@forEach
            val merged = replacePending(kind, command)
            if (merged != null) return@forEach
            if (reserveSlot(kind)) {
                enqueueReserved(kind, command)
            } else {
                restoreOverflow(kind, command)
                ingress.add(IngressCommand(kind, command = null, reservedSlot = false))
                ensureWorkerStarted()
                LockSupport.unpark(worker)
            }
        }
    }

    private fun ensureWorkerStarted() {
        if (workerStarted.compareAndSet(false, true)) worker.start()
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

    private data class OverflowSlot<C : Any>(
        val accepting: Boolean,
        val command: C?,
        val discarded: Boolean = false,
    )

    private class IngressCommand<C : Any>(
        val kind: Kind,
        val command: C?,
        val reservedSlot: Boolean,
    ) {
        private val state = AtomicReference(IngressState.PENDING)

        fun claimForDrain(accepted: Boolean): Boolean =
            state.compareAndSet(
                IngressState.PENDING,
                if (accepted) IngressState.DRAINED else IngressState.DISCARDED,
            )

        fun cancel(): Boolean = state.compareAndSet(IngressState.PENDING, IngressState.CANCELED)

        fun wasDrained(): Boolean = state.get() == IngressState.DRAINED
    }

    private enum class IngressState {
        PENDING,
        DRAINED,
        DISCARDED,
        CANCELED,
    }

    private companion object {
        const val DEFAULT_CLOSE_TIMEOUT_MS = 5_000L
        const val MIN_CAPACITY_WITH_RECOVERY_RESERVE = 4
    }
}

data class OutboundWriteFailure<C : Any>(
    val command: C,
    val cause: Throwable,
)
