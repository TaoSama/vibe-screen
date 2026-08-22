package dev.telemachus.display

import java.util.concurrent.atomic.AtomicLong

/**
 * A bounded queue that always makes room for the newest item by evicting the
 * oldest one. Callers retain ownership of the returned item and must release
 * any resources it holds.
 */
data class LatestFrameOfferResult<T>(
    val accepted: Boolean,
    val dropped: List<T>,
    val requiresKeyframe: Boolean,
)

class LatestFrameQueue<T>(
    private val capacity: Int,
    private val isKeyframe: (T) -> Boolean,
) {
    private val items = ArrayDeque<T>(capacity)
    private var requiresKeyframe = true

    init {
        require(capacity in 1..MAX_CAPACITY) { "capacity must be between 1 and $MAX_CAPACITY" }
    }

    @Synchronized
    fun offer(item: T): LatestFrameOfferResult<T> {
        if (requiresKeyframe && !isKeyframe(item)) {
            return LatestFrameOfferResult(false, listOf(item), true)
        }
        if (isKeyframe(item)) {
            val dropped = drainLocked()
            items.addLast(item)
            requiresKeyframe = false
            return LatestFrameOfferResult(true, dropped, false)
        }
        if (items.size == capacity) {
            if (items.any(isKeyframe)) {
                return LatestFrameOfferResult(false, listOf(item), false)
            }
            val dropped = drainLocked() + item
            requiresKeyframe = true
            return LatestFrameOfferResult(false, dropped, true)
        }
        items.addLast(item)
        return LatestFrameOfferResult(true, emptyList(), false)
    }

    @Synchronized
    fun poll(): T? = if (items.isEmpty()) null else items.removeFirst()

    @Synchronized
    fun drain(): List<T> = drainLocked().also { requiresKeyframe = true }

    private fun drainLocked(): List<T> = buildList {
        while (items.isNotEmpty()) add(items.removeFirst())
    }

    @Synchronized
    fun size(): Int = items.size

    companion object {
        private const val MAX_CAPACITY = 2
    }
}

/** Rejects work produced by a connection that has been superseded. */
class SessionEpochGate(initialEpoch: Long = 0L) {
    private val current = AtomicLong(initialEpoch)

    fun beginSession(): Long = current.incrementAndGet()

    fun accepts(epoch: Long): Boolean = epoch > 0L && epoch == current.get()

    fun currentEpoch(): Long = current.get()
}

/** Sender-local heartbeat state; monotonic nanoseconds must be supplied. */
class HeartbeatMonitor(
    timeoutMs: Long,
) {
    private val timeoutNs = timeoutMs * NANOS_PER_MILLISECOND

    @Volatile private var lastInboundNs = 0L

    init {
        require(timeoutMs > 0L) { "timeoutMs must be positive" }
        require(timeoutMs <= Long.MAX_VALUE / NANOS_PER_MILLISECOND) { "timeoutMs is too large" }
    }

    fun reset(nowNs: Long) {
        lastInboundNs = nowNs
    }

    fun recordInbound(nowNs: Long) {
        lastInboundNs = nowNs
    }

    fun isExpired(nowNs: Long): Boolean {
        val last = lastInboundNs
        return last > 0L && nowNs - last >= timeoutNs
    }

    companion object {
        private const val NANOS_PER_MILLISECOND = 1_000_000L
    }
}

/** Bounded exponential reconnect delay shared by connection entry points. */
class ReconnectBackoff(
    private val initialDelayMs: Long = INITIAL_DELAY_MS,
    private val maximumDelayMs: Long = MAXIMUM_DELAY_MS,
    private val jitterRatio: Double = 0.20,
) {
    private var nextAttempt = 0

    init {
        require(initialDelayMs > 0L) { "initialDelayMs must be positive" }
        require(maximumDelayMs >= initialDelayMs) { "maximumDelayMs must be at least initialDelayMs" }
        require(jitterRatio in 0.0..1.0) { "jitterRatio must be between 0 and 1" }
    }

    fun delayForAttempt(attempt: Int): Long = baseDelayForAttempt(attempt)

    @Synchronized
    fun nextDelayMs(jitterUnit: Double = Math.random()): Long {
        require(jitterUnit in 0.0..1.0) { "jitterUnit must be between 0 and 1" }
        val baseDelay = baseDelayForAttempt(nextAttempt++)
        val factor = 1.0 + ((jitterUnit * 2.0) - 1.0) * jitterRatio
        return (baseDelay * factor).toLong().coerceIn(1L, maximumDelayMs)
    }

    @Synchronized
    fun reset() {
        nextAttempt = 0
    }

    private fun baseDelayForAttempt(attempt: Int): Long {
        val shift = attempt.coerceIn(0, MAX_SHIFT)
        val multiplier = 1L shl shift
        return if (initialDelayMs > maximumDelayMs / multiplier) {
            maximumDelayMs
        } else {
            initialDelayMs * multiplier
        }
    }

    companion object {
        const val INITIAL_DELAY_MS = 500L
        const val MAXIMUM_DELAY_MS = 3_000L
        private const val MAX_SHIFT = 20
    }
}

enum class StreamCodec {
    HEVC,
    H264,
    AV1,
}

/**
 * Records a process-local structural HEVC target incompatibility. The next
 * connection uses the explicit AVC-only wire offer instead of silently changing
 * codec inside the failing connection.
 */
object CodecFallbackPolicy {
    @Volatile private var hevcFailedAtRuntime = false

    internal fun recordStructuralUnsupported(codec: StreamCodec) {
        if (codec == StreamCodec.HEVC) hevcFailedAtRuntime = true
    }

    fun shouldUseH264(hasUsableHevcDecoder: Boolean): Boolean =
        !hasUsableHevcDecoder || hevcFailedAtRuntime

    fun candidates(
        hasUsableHevcDecoder: Boolean,
        @Suppress("UNUSED_PARAMETER")
        hasUsableAv1Decoder: Boolean = false,
    ): List<StreamCodec> =
        if (shouldUseH264(hasUsableHevcDecoder)) {
            listOf(StreamCodec.H264)
        } else {
            listOf(StreamCodec.HEVC, StreamCodec.H264)
        }

    internal fun resetForTest() {
        hevcFailedAtRuntime = false
    }
}

internal object CodecFallbackCommitGate {
    fun recordCurrentStructuralHevcFailure(
        codec: StreamCodec,
        failure: DecoderFailure,
        isCurrentConfiguration: () -> Boolean,
    ): Boolean {
        if (!isCurrentConfiguration()) return false
        if (codec != StreamCodec.HEVC ||
            failure.kind != DecoderFailureKind.STRUCTURAL_TARGET_UNSUPPORTED
        ) return false
        CodecFallbackPolicy.recordStructuralUnsupported(StreamCodec.HEVC)
        return true
    }
}
