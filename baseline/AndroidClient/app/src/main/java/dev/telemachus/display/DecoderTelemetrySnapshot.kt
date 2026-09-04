package dev.telemachus.display

internal data class DecoderTelemetrySnapshot(
    val droppedFrames: Long,
    val decoderLatencyAvgMs: Double?,
    val decoderLatencyMaxMs: Double?,
    val decoderLatencySamples: Int = 0,
) {
    companion object {
        val empty = DecoderTelemetrySnapshot(0L, null, null)
    }
}

internal class DecoderTelemetryAccumulator {
    private val lock = Any()
    private var droppedFrames = 0L
    private var latencySumNs = 0L
    private var latencySamples = 0
    private var latencyMaxNs = 0L

    fun recordDroppedFrames(count: Long = 1L) {
        if (count <= 0L) return
        synchronized(lock) {
            droppedFrames += count
        }
    }

    fun recordDecoderLatency(latencyNs: Long) {
        synchronized(lock) {
            latencySumNs += latencyNs
            latencySamples++
            if (latencyNs > latencyMaxNs) latencyMaxNs = latencyNs
        }
    }

    fun peek(): DecoderTelemetrySnapshot = capture(reset = false)

    fun consume(): DecoderTelemetrySnapshot = capture(reset = true)

    private fun capture(reset: Boolean): DecoderTelemetrySnapshot =
        synchronized(lock) {
            val snapshot =
                DecoderTelemetrySnapshot(
                    droppedFrames = droppedFrames,
                    decoderLatencyAvgMs = if (latencySamples > 0) latencySumNs / latencySamples / 1_000_000.0 else null,
                    decoderLatencyMaxMs = if (latencySamples > 0) latencyMaxNs / 1_000_000.0 else null,
                    decoderLatencySamples = latencySamples,
                )
            if (reset) {
                droppedFrames = 0L
                latencySumNs = 0L
                latencySamples = 0
                latencyMaxNs = 0L
            }
            snapshot
        }
}

internal fun currentSessionDecoderTelemetrySnapshot(
    isCurrentSession: () -> Boolean,
    currentDecoderSnapshot: () -> DecoderTelemetrySnapshot?,
): DecoderTelemetrySnapshot {
    if (!isCurrentSession()) return DecoderTelemetrySnapshot.empty
    return currentDecoderSnapshot() ?: DecoderTelemetrySnapshot.empty
}
