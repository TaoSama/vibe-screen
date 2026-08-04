package dev.telemachus.display.protocol

import dev.vibescreen.protocol.v1.InputPhase
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

internal data class TouchSample(
    val pointerId: Int,
    val phase: InputPhase,
    val x: Double,
    val y: Double,
) {
    init {
        require(pointerId >= 0) { "pointerId must not be negative" }
        require(phase != InputPhase.INPUT_PHASE_UNSPECIFIED) { "phase must be specified" }
        require(x in 0.0..1.0 && y in 0.0..1.0) { "touch coordinates must be normalized" }
    }
}

internal data class MotionPointer(
    val pointerId: Int,
    val x: Double,
    val y: Double,
)

/** Android-compatible action values without depending on the Android runtime. */
internal object MotionActions {
    const val DOWN = 0
    const val UP = 1
    const val MOVE = 2
    const val CANCEL = 3
    const val POINTER_DOWN = 5
    const val POINTER_UP = 6
}

internal data class MotionSnapshot(
    val actionMasked: Int,
    val actionIndex: Int,
    val pointers: List<MotionPointer>,
)

internal object TouchSampleMapper {
    fun map(snapshot: MotionSnapshot): List<TouchSample> =
        when (snapshot.actionMasked) {
            MotionActions.DOWN,
            MotionActions.POINTER_DOWN,
            -> snapshot.actionPointerOrNull(InputPhase.INPUT_PHASE_BEGAN)?.let(::listOf).orEmpty()

            MotionActions.UP,
            MotionActions.POINTER_UP,
            -> snapshot.actionPointerOrNull(InputPhase.INPUT_PHASE_ENDED)?.let(::listOf).orEmpty()

            MotionActions.MOVE -> snapshot.pointers.map { it.toSample(InputPhase.INPUT_PHASE_CHANGED) }
            MotionActions.CANCEL -> snapshot.pointers.map { it.toSample(InputPhase.INPUT_PHASE_CANCELLED) }
            else -> emptyList()
        }

    private fun MotionSnapshot.actionPointerOrNull(phase: InputPhase): TouchSample? =
        pointers.getOrNull(actionIndex)?.toSample(phase)

    private fun MotionPointer.toSample(phase: InputPhase) = TouchSample(pointerId, phase, x, y)
}

/**
 * Bounded actor mailbox for touch input. Motion samples may be coalesced or evicted, while
 * pointer lifecycle boundaries are never discarded or reordered.
 */
internal class TouchEventBuffer(
    private val capacity: Int = DEFAULT_CAPACITY,
) {
    internal enum class OfferResult {
        ACCEPTED,
        RETRY_REQUIRED,
    }

    private val samples = ArrayList<TouchSample>(capacity)
    private val lock = ReentrantLock()
    private val notEmpty = lock.newCondition()
    private val notFull = lock.newCondition()

    init {
        require(capacity > 0) { "capacity must be positive" }
    }

    fun offer(sample: TouchSample): OfferResult =
        lock.withLock { offerLocked(sample) }

    fun take(): TouchSample =
        lock.withLock {
            while (samples.isEmpty()) {
                notEmpty.await()
            }
            samples.removeAt(0).also { notFull.signalAll() }
        }

    /** Blocks only when the mailbox contains lifecycle boundaries that cannot be discarded. */
    @Throws(InterruptedException::class)
    fun put(sample: TouchSample) {
        lock.withLock {
            while (offerLocked(sample) == OfferResult.RETRY_REQUIRED) {
                notFull.await()
            }
        }
    }

    fun size(): Int = lock.withLock { samples.size }

    /** Do not merge a motion sample across a lifecycle boundary for the same pointer. */
    private fun coalesceChanged(sample: TouchSample): Boolean {
        for (index in samples.indices.reversed()) {
            val queued = samples[index]
            if (queued.pointerId != sample.pointerId) continue
            if (queued.phase != InputPhase.INPUT_PHASE_CHANGED) return false
            samples[index] = sample
            return true
        }
        return false
    }

    private fun offerLocked(sample: TouchSample): OfferResult {
        if (sample.phase == InputPhase.INPUT_PHASE_CHANGED && coalesceChanged(sample)) {
            return OfferResult.ACCEPTED
        }
        if (samples.size == capacity) {
            val droppableIndex =
                samples.indexOfFirst {
                    it.phase == InputPhase.INPUT_PHASE_CHANGED &&
                        (sample.phase == InputPhase.INPUT_PHASE_CHANGED || it.pointerId != sample.pointerId)
                }
            if (droppableIndex < 0) return OfferResult.RETRY_REQUIRED
            samples.removeAt(droppableIndex)
        }
        samples.add(sample)
        notEmpty.signal()
        return OfferResult.ACCEPTED
    }

    private companion object {
        const val DEFAULT_CAPACITY = 64
    }
}
