package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DecoderTelemetryAccumulatorTest {
    @Test
    fun peekDoesNotResetAndConsumeResetsTelemetry() {
        val accumulator = DecoderTelemetryAccumulator()

        accumulator.recordDecoderLatency(4_000_000L)
        accumulator.recordDecoderLatency(8_000_000L)
        accumulator.recordDroppedFrames(2L)

        val diagnosticSnapshot = accumulator.peek()
        assertEquals(2L, diagnosticSnapshot.droppedFrames)
        assertEquals(6.0, diagnosticSnapshot.decoderLatencyAvgMs ?: -1.0, 0.001)
        assertEquals(8.0, diagnosticSnapshot.decoderLatencyMaxMs ?: -1.0, 0.001)
        assertEquals(2, diagnosticSnapshot.decoderLatencySamples)

        val consumedSnapshot = accumulator.consume()
        assertEquals(diagnosticSnapshot, consumedSnapshot)

        val emptySnapshot = accumulator.consume()
        assertEquals(0L, emptySnapshot.droppedFrames)
        assertNull(emptySnapshot.decoderLatencyAvgMs)
        assertNull(emptySnapshot.decoderLatencyMaxMs)
        assertEquals(0, emptySnapshot.decoderLatencySamples)
    }

    @Test
    fun streamStatsConsumerResetsOnlyTheConsumedPeriod() {
        val accumulator = DecoderTelemetryAccumulator()

        accumulator.recordDecoderLatency(10_000_000L)
        accumulator.recordDroppedFrames()
        accumulator.consume()

        accumulator.recordDecoderLatency(20_000_000L)
        accumulator.recordDecoderLatency(40_000_000L)
        accumulator.recordDroppedFrames(3L)

        val nextPeriod = accumulator.consume()

        assertEquals(3L, nextPeriod.droppedFrames)
        assertEquals(30.0, nextPeriod.decoderLatencyAvgMs ?: -1.0, 0.001)
        assertEquals(40.0, nextPeriod.decoderLatencyMaxMs ?: -1.0, 0.001)
        assertEquals(2, nextPeriod.decoderLatencySamples)
    }

}
