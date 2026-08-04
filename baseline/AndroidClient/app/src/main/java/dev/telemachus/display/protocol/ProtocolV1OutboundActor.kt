package dev.telemachus.display.protocol

import dev.vibescreen.protocol.v1.Envelope
import dev.vibescreen.protocol.v1.InputPhase
import java.io.Closeable
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Owns all mutable outbound [ProtocolV1Session] access and wire writes.
 *
 * Builders intentionally run on the actor thread: assigning a message id on a
 * caller thread and only serializing the write can put a larger id on the wire
 * before a smaller one. The bounded queue applies backpressure instead of
 * silently dropping lifecycle/control messages. High-rate move events should
 * first pass through [TouchEventBuffer], which coalesces them by pointer.
 */
internal class ProtocolV1OutboundActor(
    private val session: ProtocolV1Session,
    private val writeEnvelope: (Envelope) -> Unit,
    private val onAction: (ProtocolV1Session.Action) -> Unit = {},
    private val onFailure: (Throwable) -> Unit,
    capacity: Int = DEFAULT_CAPACITY,
    threadName: String = DEFAULT_THREAD_NAME,
) : Closeable {
    private sealed interface Work {
        class Build(val builder: (ProtocolV1Session) -> Envelope) : Work

        class Receive(
            val envelope: Envelope,
            val completion: CompletableFuture<Unit>?,
        ) : Work

        class Barrier(val latch: CountDownLatch) : Work
    }

    private val accepting = AtomicBoolean(true)
    private val queue = ArrayBlockingQueue<Work>(capacity)
    private val worker =
        Thread(::run, threadName).apply {
            isDaemon = true
            start()
        }

    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    /** Blocks under backpressure so a control or touch lifecycle event is never dropped. */
    fun submit(builder: (ProtocolV1Session) -> Envelope): Boolean = enqueue(Work.Build(builder))

    fun clientHello(): Boolean = submit(ProtocolV1Session::clientHello)

    fun ping(sequence: Long): Boolean = submit { it.ping(sequence) }

    fun requestKeyframe(reason: String): Boolean = submit { it.requestKeyframe(reason) }

    fun touch(
        inputId: Long,
        sample: TouchSample,
    ): Boolean =
        submit {
            it.touch(
                inputId = inputId,
                pointerId = sample.pointerId,
                phase = sample.phase,
                x = sample.x,
                y = sample.y,
            )
        }

    fun touch(
        inputId: Long,
        pointerId: Int,
        phase: InputPhase,
        x: Double,
        y: Double,
    ): Boolean = submit { it.touch(inputId, pointerId, phase, x, y) }

    fun protocolError(
        message: String,
        correlationId: Long = 0,
    ): Boolean = submit { it.protocolError(message, correlationId) }

    /**
     * Runs receive on the same actor that owns outbound ids. Any [ProtocolV1Session.Action.Send]
     * is written immediately, before later queued work. Other actions are reported in order.
     */
    fun receive(envelope: Envelope): Boolean = enqueue(Work.Receive(envelope, completion = null))

    /**
     * Waits until receive and all of its ordered actions have completed. The receive loop uses
     * this before consuming a following media frame, so VideoConfigured is visible first.
     */
    fun receiveAndWait(
        envelope: Envelope,
        timeout: Long,
        unit: TimeUnit = TimeUnit.MILLISECONDS,
    ) {
        val completion = CompletableFuture<Unit>()
        check(enqueue(Work.Receive(envelope, completion))) { "Protocol v1 outbound actor is closed" }
        try {
            completion.get(timeout, unit)
        } catch (failure: ExecutionException) {
            throw failure.cause ?: failure
        }
    }

    /** Test/integration synchronization point; it does not stop the actor. */
    fun awaitIdle(
        timeout: Long,
        unit: TimeUnit = TimeUnit.MILLISECONDS,
    ): Boolean {
        if (!accepting.get()) return false
        val latch = CountDownLatch(1)
        if (!enqueue(Work.Barrier(latch))) return false
        return latch.await(timeout, unit)
    }

    override fun close() {
        if (accepting.compareAndSet(true, false)) {
            releaseQueuedWork()
            worker.interrupt()
        }
    }

    val isClosed: Boolean
        get() = !accepting.get()

    private fun enqueue(work: Work): Boolean {
        return try {
            while (accepting.get()) {
                if (queue.offer(work, ENQUEUE_POLL_MS, TimeUnit.MILLISECONDS)) {
                    if (accepting.get()) return true
                    queue.remove(work)
                    return false
                }
            }
            false
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
    }

    private fun run() {
        try {
            while (accepting.get()) {
                when (val work = queue.take()) {
                    is Work.Build -> writeEnvelope(work.builder(session))
                    is Work.Receive -> receive(work)
                    is Work.Barrier -> work.latch.countDown()
                }
            }
        } catch (_: InterruptedException) {
            // close() is the only intentional interruption path.
        } catch (failure: Throwable) {
            accepting.set(false)
            releaseQueuedWork()
            onFailure(failure)
        } finally {
            accepting.set(false)
            releaseQueuedWork()
        }
    }

    private fun dispatch(actions: List<ProtocolV1Session.Action>) {
        actions.forEach { action ->
            if (action is ProtocolV1Session.Action.Send) {
                writeEnvelope(action.envelope)
            } else {
                onAction(action)
            }
        }
    }

    private fun receive(work: Work.Receive) {
        try {
            dispatch(session.receive(work.envelope))
            work.completion?.complete(Unit)
        } catch (failure: Throwable) {
            accepting.set(false)
            work.completion?.completeExceptionally(failure)
            throw failure
        }
    }

    private fun releaseQueuedWork() {
        queue.forEach { work ->
            if (work is Work.Barrier) work.latch.countDown()
            if (work is Work.Receive) work.completion?.completeExceptionally(IllegalStateException("Actor closed"))
        }
        queue.clear()
    }

    companion object {
        private const val DEFAULT_CAPACITY = 128
        private const val DEFAULT_THREAD_NAME = "protocol-v1-outbound"
        private const val ENQUEUE_POLL_MS = 50L
    }
}
