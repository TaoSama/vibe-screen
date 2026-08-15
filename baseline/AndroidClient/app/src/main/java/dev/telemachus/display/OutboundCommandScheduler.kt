package dev.telemachus.display

import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.locks.ReentrantLock
import java.util.concurrent.locks.LockSupport
import kotlin.concurrent.withLock

/**
 * A bounded, single-writer scheduler for latency-sensitive outbound commands.
 *
 * Recovery commands are written before input commands. Pending pointer/stylus
 * moves, controller moves, pings, and keyframe requests use independent
 * coalescing domains; submitting a new command of the same domain replaces the
 * older pending command.
 * Admitted structural touch and controller structural commands retain FIFO
 * order. Controller structural boundaries (connect/disconnect/button/hat)
 * allocate a monotonic generation and supersede any controller move that
 * predates them, so a stale analog state can never be written after the
 * lifecycle boundary that replaces it.
 * Saturation is reported as [Submission.TIMED_OUT], allowing the session owner
 * to fail closed rather than silently lose a boundary or leave remote input
 * pressed.
 */
class OutboundCommandScheduler<C : Any>(
    private val capacity: Int,
    private val writer: (C) -> Unit,
    private val onWriteFailure: (OutboundWriteFailure<C>) -> Unit,
    private val coalesce: (Kind, C, C) -> C = { _, _, replacement -> replacement },
    threadName: String = "OutboundCommandWriter",
    private val beforeOverflowPublish: () -> Unit = {},
    private val afterOverflowValuePublished: () -> Unit = {},
    private val afterControllerBoundaryGenerationAllocated: () -> Unit = {},
    private val beforeControllerLifecycleClose: () -> Unit = {},
) : AutoCloseable {
    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    enum class Kind {
        STRUCTURAL_TOUCH,
        MOVE,
        CONTROLLER_STRUCTURAL,
        CONTROLLER_MOVE,
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
    private val controllerLifecycleLock = ReentrantLock()
    private val hasSpace = lock.newCondition()
    private val terminated = lock.newCondition()
    private val ingress = ConcurrentLinkedQueue<IngressCommand<C>>()
    private val overflowControllerMove = AtomicReference(OverflowSlot<C>(accepting = true, command = null))
    private val overflowKeyframe = AtomicReference(OverflowSlot<C>(accepting = true, command = null))
    private val overflowPing = AtomicReference(OverflowSlot<C>(accepting = true, command = null))
    private val occupiedCount = AtomicInteger()
    private val controllerGeneration = AtomicLong()
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
            return if (kind.isControllerKind()) {
                submitControllerLocked(kind, command)
            } else {
                submitLocked(kind, command, deadlineNs)
            }
        } finally {
            lock.unlock()
        }
    }

    private fun submitLocked(
        kind: Kind,
        command: C,
        deadlineNs: Long,
    ): Submission {
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
    }

    /**
     * Controller submissions never wait on [hasSpace] while holding
     * [controllerLifecycleLock]. Controller moves are coalescible overflow and
     * controller structural boundaries fail closed with [Submission.TIMED_OUT]
     * when no slot and no evictable move are available. This keeps the
     * lifecycle lock out of any condition-wait path so shutdown can never
     * deadlock against a controller submitter.
     */
    private fun submitControllerLocked(
        kind: Kind,
        command: C,
    ): Submission =
        controllerLifecycleLock.withLock {
            // A contended controller structural submit can enter through the
            // lock-free ingress. Drain it while holding both locks before
            // assigning this command's generation, otherwise a later analog
            // command could be placed before an already-admitted boundary.
            drainIngressLocked()
            if (!accepting.get() || state != State.OPEN) return@withLock Submission.CLOSED

            replacePending(kind, command)?.let { return@withLock it }

            while (!reserveSlot(kind)) {
                if (removeOldestMove()) {
                    pendingCount--
                    occupiedCount.decrementAndGet()
                    if (reserveSlot(kind)) {
                        enqueueAdmittedController(kind, command)
                        return@withLock Submission.ACCEPTED_AFTER_COALESCING_MOVE
                    }
                }
                // Controller structural commands never block on the condition
                // variable; saturation fails closed so the session owner can
                // tear down instead of leaving remote input pressed.
                return@withLock Submission.TIMED_OUT
            }

            enqueueAdmittedController(kind, command)
            Submission.ACCEPTED
        }

    private fun submitThroughIngress(
        kind: Kind,
        command: C,
    ): Submission {
        if (!accepting.get() || state != State.OPEN) return Submission.CLOSED
        if (kind.isCoalescibleMove()) return submitCoalescibleOverflow(kind, command)
        if (!reserveSlot(kind)) return submitCoalescibleOverflow(kind, command)
        if (!accepting.get() || state != State.OPEN) {
            occupiedCount.decrementAndGet()
            return Submission.CLOSED
        }
        val ingressCommand =
            if (kind == Kind.CONTROLLER_STRUCTURAL) {
                controllerLifecycleLock.withLock {
                    if (!accepting.get() || state != State.OPEN) {
                        occupiedCount.decrementAndGet()
                        return Submission.CLOSED
                    }
                    val boundaryGeneration = controllerGeneration.incrementAndGet()
                    afterControllerBoundaryGenerationAllocated()
                    IngressCommand(kind, command, reservedSlot = true, boundaryGeneration = boundaryGeneration).also {
                        ingress.add(it)
                        ensureWorkerStarted()
                        LockSupport.unpark(worker)
                    }
                }
            } else {
                IngressCommand(kind, command, reservedSlot = true).also {
                    ingress.add(it)
                    ensureWorkerStarted()
                    LockSupport.unpark(worker)
                }
            }
        if (accepting.get() && state == State.OPEN) return Submission.ACCEPTED
        if (ingressCommand.cancel()) {
            if (ingressCommand.reservedSlot) occupiedCount.decrementAndGet()
            return Submission.CLOSED
        }
        return if (ingressCommand.wasDrained()) Submission.ACCEPTED else Submission.CLOSED
    }

    private fun submitCoalescibleOverflow(
        kind: Kind,
        command: C,
    ): Submission {
        val overflow = overflowSlot(kind) ?: return Submission.TIMED_OUT
        return if (kind == Kind.CONTROLLER_MOVE) {
            controllerLifecycleLock.withLock {
                publishCoalescibleOverflow(kind, command, overflow, controllerGeneration.get())
            }
        } else {
            publishCoalescibleOverflow(kind, command, overflow, 0L)
        }
    }

    private fun publishCoalescibleOverflow(
        kind: Kind,
        command: C,
        overflow: AtomicReference<OverflowSlot<C>>,
        submissionGeneration: Long,
    ): Submission {
        beforeOverflowPublish()
        while (true) {
            val slot = overflow.get()
            if (!slot.accepting) return Submission.CLOSED
            val sameGeneration = kind != Kind.CONTROLLER_MOVE || slot.generation == submissionGeneration
            val replacement =
                if (slot.command == null || !sameGeneration) command else coalesce(kind, slot.command, command)
            val published = OverflowSlot(accepting = true, command = replacement, generation = submissionGeneration)
            if (!overflow.compareAndSet(slot, published)) continue
            if (slot.command != null && sameGeneration) return Submission.COALESCED
            afterOverflowValuePublished()
            overflow.get().let { pub ->
                if (pub.command == null) {
                    return if (pub.discarded) Submission.CLOSED else Submission.ACCEPTED
                }
            }
            val marker =
                IngressCommand<C>(
                    kind,
                    command = null,
                    reservedSlot = false,
                    boundaryGeneration = submissionGeneration,
                )
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
            beforeControllerLifecycleClose()
            controllerLifecycleLock.withLock {
                if (state == State.OPEN) {
                    accepting.set(false)
                    closeOverflowAdmissions(preserveCommands = true)
                    drainIngressLocked()
                    drainOverflowSlotsLocked()
                    if (!workerStarted.get() && pendingCount == 0) {
                        state = State.CLOSED
                        terminated.signalAll()
                    } else {
                        state = State.CLOSING
                        LockSupport.unpark(worker)
                    }
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
            beforeControllerLifecycleClose()
            controllerLifecycleLock.withLock {
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
    }

    override fun close() {
        if (!shutdownGracefully(DEFAULT_CLOSE_TIMEOUT_MS)) shutdownNow()
    }

    private fun replacePending(
        kind: Kind,
        command: C,
        commandGeneration: Long = generationFor(kind),
    ): Submission? =
        when (kind) {
            Kind.MOVE,
            Kind.CONTROLLER_MOVE,
            -> {
                val pendingIndex = pendingMoveIndexAfterLatestStructuralBoundary(kind)
                if (pendingIndex >= 0 && touchCommands[pendingIndex].generation == commandGeneration) {
                    val pending = touchCommands[pendingIndex]
                    touchCommands[pendingIndex] =
                        PendingTouch(kind, coalesce(kind, pending.command, command), commandGeneration)
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
            Kind.STRUCTURAL_TOUCH,
            Kind.CONTROLLER_STRUCTURAL,
            -> null
        }

    /**
     * Returns the index of the latest pending move of [kind] that comes after
     * the most recent structural boundary (STRUCTURAL_TOUCH for MOVE,
     * CONTROLLER_STRUCTURAL for CONTROLLER_MOVE). A structural boundary is a
     * hard separator: moves before it belong to a previous lifecycle phase and
     * must not be coalesced with moves after it. Returns -1 when no such move
     * exists.
     */
    private fun pendingMoveIndexAfterLatestStructuralBoundary(kind: Kind): Int {
        val boundaryKind =
            when (kind) {
                Kind.MOVE -> Kind.STRUCTURAL_TOUCH
                Kind.CONTROLLER_MOVE -> Kind.CONTROLLER_STRUCTURAL
                else -> return -1
            }
        for (index in touchCommands.lastIndex downTo 0) {
            when (touchCommands[index].kind) {
                boundaryKind -> return -1
                kind -> return index
                else -> Unit
            }
        }
        return -1
    }

    private fun enqueueReserved(
        kind: Kind,
        command: C,
        commandGeneration: Long = generationFor(kind),
    ) {
        when (kind) {
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            Kind.CONTROLLER_STRUCTURAL,
            Kind.CONTROLLER_MOVE,
            -> touchCommands.addLast(PendingTouch(kind, command, commandGeneration))
            Kind.KEYFRAME -> keyframe = command
            Kind.PING -> ping = command
        }
        pendingCount++
        check(pendingCount <= capacity)
        ensureWorkerStarted()
        LockSupport.unpark(worker)
    }

    private fun enqueueAdmittedController(
        kind: Kind,
        command: C,
    ) {
        if (kind == Kind.CONTROLLER_STRUCTURAL) {
            // Serialize generation allocation with the ingress path so structural
            // boundaries are numbered in the exact order they are admitted.
            // controllerLifecycleLock is always acquired after `lock`, so this
            // is a consistent lock ordering and cannot deadlock with shutdown.
            controllerLifecycleLock.withLock {
                val boundaryGeneration = controllerGeneration.incrementAndGet()
                afterControllerBoundaryGenerationAllocated()
                supersedeControllerMovesBeforeLocked(boundaryGeneration)
                enqueueReserved(kind, command, boundaryGeneration)
            }
        } else {
            enqueueReserved(kind, command)
        }
    }

    private fun supersedeControllerMovesBeforeLocked(boundaryGeneration: Long) {
        // A structural boundary with generation N supersedes every controller
        // move whose generation is strictly less than N. The boundary allocates
        // its generation via controllerGeneration.incrementAndGet(), so a move
        // that reads controllerGeneration.get() afterwards receives the same
        // generation N and was submitted after the boundary. Such a move must
        // be retained so it is written after the boundary, not discarded.
        val removed = touchCommands.count {
            it.kind == Kind.CONTROLLER_MOVE && it.generation < boundaryGeneration
        }
        if (removed > 0) {
            touchCommands.removeAll {
                it.kind == Kind.CONTROLLER_MOVE && it.generation < boundaryGeneration
            }
            pendingCount -= removed
            occupiedCount.addAndGet(-removed)
            hasSpace.signalAll()
        }
        while (true) {
            val slot = overflowControllerMove.get()
            if (slot.command == null || slot.generation >= boundaryGeneration) break
            if (overflowControllerMove.compareAndSet(slot, slot.copy(command = null))) break
        }
    }

    private fun generationFor(kind: Kind): Long =
        if (kind == Kind.CONTROLLER_MOVE) {
            controllerLifecycleLock.withLock { controllerGeneration.get() }
        } else {
            0L
        }

    private fun Kind.isControllerKind(): Boolean =
        this == Kind.CONTROLLER_MOVE || this == Kind.CONTROLLER_STRUCTURAL

    private fun Kind.isCoalescibleMove(): Boolean = this == Kind.MOVE || this == Kind.CONTROLLER_MOVE

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
                beforeControllerLifecycleClose()
                controllerLifecycleLock.withLock {
                    if (state == State.CLOSED) return
                    accepting.set(false)
                    closeOverflowAdmissions(preserveCommands = false)
                    clearPending()
                    state = State.FAILED
                    hasSpace.signalAll()
                    terminated.signalAll()
                    if (failureCallbackClaimed) false else true.also { failureCallbackClaimed = true }
                }
            }
        if (shouldDeliver) onWriteFailure(failure)
    }

    private fun clearPending() {
        occupiedCount.addAndGet(-pendingCount)
        touchCommands.clear()
        keyframe = null
        ping = null
        pendingCount = 0
        overflowControllerMove.set(OverflowSlot(accepting = false, command = null, discarded = true))
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
        val index = touchCommands.indexOfFirst { it.kind.isCoalescibleMove() }
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
            val overflowCommand =
                if (ingressCommand.command == null) {
                    takeOverflow(ingressCommand.kind, ingressCommand.boundaryGeneration)
                } else {
                    null
                }
            val command = ingressCommand.command ?: overflowCommand?.command ?: continue
            val commandGeneration = overflowCommand?.generation ?: ingressCommand.boundaryGeneration
            val merged = replacePending(ingressCommand.kind, command, commandGeneration)
            if (merged != null) {
                if (ingressCommand.reservedSlot) occupiedCount.decrementAndGet()
                hasSpace.signalAll()
            } else {
                val hasReservation = ingressCommand.reservedSlot || reserveSlot(ingressCommand.kind)
                if (hasReservation) {
                    if (ingressCommand.kind == Kind.CONTROLLER_STRUCTURAL) {
                        supersedeControllerMovesBeforeLocked(commandGeneration)
                    }
                    enqueueReserved(ingressCommand.kind, command, commandGeneration)
                } else {
                    checkNotNull(overflowSlot(ingressCommand.kind)) {
                        "Previously admitted structural command lost its reservation"
                    }
                    restoreOverflow(ingressCommand.kind, command, commandGeneration)
                    ingress.add(
                        IngressCommand<C>(
                            ingressCommand.kind,
                            command = null,
                            reservedSlot = false,
                            boundaryGeneration = commandGeneration,
                        ),
                    )
                    return
                }
            }
        }
    }

    private fun takeOverflow(
        kind: Kind,
        expectedGeneration: Long? = null,
    ): OverflowCommand<C>? {
        val overflow = overflowSlot(kind) ?: return null
        while (true) {
            val slot = overflow.get()
            val command = slot.command ?: return null
            if (kind == Kind.CONTROLLER_MOVE && slot.generation != controllerGeneration.get()) {
                if (overflow.compareAndSet(slot, slot.copy(command = null))) continue
                continue
            }
            if (kind == Kind.CONTROLLER_MOVE && expectedGeneration != null && slot.generation != expectedGeneration) {
                return null
            }
            if (overflow.compareAndSet(slot, slot.copy(command = null))) return OverflowCommand(command, slot.generation)
        }
    }

    private fun restoreOverflow(
        kind: Kind,
        command: C,
        commandGeneration: Long,
    ) {
        val overflow = checkNotNull(overflowSlot(kind))
        while (true) {
            val slot = overflow.get()
            if (kind == Kind.CONTROLLER_MOVE) {
                if (commandGeneration != controllerGeneration.get()) return
                if (slot.command != null && slot.generation > commandGeneration) return
            }
            val sameGeneration = kind != Kind.CONTROLLER_MOVE || slot.generation == commandGeneration
            val replacement =
                if (slot.command == null || !sameGeneration) command else coalesce(kind, command, slot.command)
            val generation = if (kind == Kind.CONTROLLER_MOVE) commandGeneration else slot.generation
            if (overflow.compareAndSet(slot, slot.copy(command = replacement, generation = generation))) return
        }
    }

    private fun overflowSlot(kind: Kind): AtomicReference<OverflowSlot<C>>? =
        when (kind) {
            Kind.CONTROLLER_MOVE -> overflowControllerMove
            Kind.KEYFRAME -> overflowKeyframe
            Kind.PING -> overflowPing
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            Kind.CONTROLLER_STRUCTURAL,
            -> null
        }

    private fun closeOverflowAdmissions(preserveCommands: Boolean) {
        overflowSlots().forEach { overflow ->
            while (true) {
                val slot = overflow.get()
                val closed =
                    OverflowSlot(
                        accepting = false,
                        command = if (preserveCommands) slot.command else null,
                        discarded = !preserveCommands,
                        generation = slot.generation,
                    )
                if (overflow.compareAndSet(slot, closed)) break
            }
        }
    }

    private fun drainOverflowSlotsLocked() {
        listOf(Kind.CONTROLLER_MOVE, Kind.KEYFRAME, Kind.PING).forEach { kind ->
            val overflowCommand = takeOverflow(kind) ?: return@forEach
            val command = overflowCommand.command
            val merged = replacePending(kind, command, overflowCommand.generation)
            if (merged != null) return@forEach
            if (reserveSlot(kind)) {
                enqueueReserved(kind, command, overflowCommand.generation)
            } else {
                restoreOverflow(kind, command, overflowCommand.generation)
                ingress.add(
                    IngressCommand<C>(
                        kind,
                        command = null,
                        reservedSlot = false,
                        boundaryGeneration = overflowCommand.generation,
                    ),
                )
                ensureWorkerStarted()
                LockSupport.unpark(worker)
            }
        }
    }

    private fun overflowSlots(): List<AtomicReference<OverflowSlot<C>>> =
        listOf(overflowControllerMove, overflowKeyframe, overflowPing)

    private fun ensureWorkerStarted() {
        if (workerStarted.compareAndSet(false, true)) worker.start()
    }

    private fun admissionLimit(kind: Kind): Int =
        when (kind) {
            Kind.STRUCTURAL_TOUCH,
            Kind.MOVE,
            Kind.CONTROLLER_STRUCTURAL,
            Kind.CONTROLLER_MOVE,
            -> capacity - recoveryReservedSlots

            Kind.KEYFRAME,
            Kind.PING,
            -> capacity
        }

    private data class PendingTouch<C : Any>(
        val kind: Kind,
        val command: C,
        val generation: Long,
    )

    private data class OverflowCommand<C : Any>(val command: C, val generation: Long)

    private data class OverflowSlot<C : Any>(
        val accepting: Boolean,
        val command: C?,
        val discarded: Boolean = false,
        val generation: Long = 0,
    )

    private class IngressCommand<C : Any>(
        val kind: Kind,
        val command: C?,
        val reservedSlot: Boolean,
        val boundaryGeneration: Long = 0,
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
