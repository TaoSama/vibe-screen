package dev.telemachus.display

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ReliabilityPrimitivesTest {
    @After
    fun resetCodecFallback() {
        CodecFallbackPolicy.resetForTest()
    }

    @Test
    fun latestFrameQueueEvictsOldestAndNeverExceedsCapacity() {
        val queue = LatestFrameQueue<Int>(capacity = 2) { value -> value < 0 }

        assertTrue(queue.offer(-1).accepted)
        assertTrue(queue.offer(1).accepted)
        val rejected = queue.offer(2)
        assertFalse(rejected.accepted)
        assertEquals(listOf(2), rejected.dropped)
        assertEquals(2, queue.size())
        assertEquals(-1, queue.poll())
        assertEquals(1, queue.poll())
        assertNull(queue.poll())
    }

    @Test
    fun latestFrameQueueRejectsCapacityAboveWireContract() {
        assertThrows(IllegalArgumentException::class.java) {
            LatestFrameQueue<Int>(capacity = 3) { false }
        }
    }

    @Test
    fun dependentOverflowClearsBacklogAndWaitsForKeyframe() {
        val queue = LatestFrameQueue<Int>(capacity = 2) { value -> value < 0 }
        assertTrue(queue.offer(-1).accepted)
        assertEquals(-1, queue.poll())
        assertTrue(queue.offer(1).accepted)
        assertTrue(queue.offer(2).accepted)

        val overflow = queue.offer(3)

        assertFalse(overflow.accepted)
        assertEquals(listOf(1, 2, 3), overflow.dropped)
        assertTrue(overflow.requiresKeyframe)
        assertEquals(0, queue.size())
        assertFalse(queue.offer(4).accepted)
        assertTrue(queue.offer(-2).accepted)
        assertEquals(-2, queue.poll())
    }

    @Test
    fun newSessionRejectsPriorEpoch() {
        val gate = SessionEpochGate()
        val first = gate.beginSession()
        val second = gate.beginSession()

        assertFalse(gate.accepts(first))
        assertTrue(gate.accepts(second))
        assertFalse(gate.accepts(0L))
    }

    @Test
    fun heartbeatExpiresAtConfiguredDeadline() {
        val monitor = HeartbeatMonitor(timeoutMs = 3_000L)
        monitor.reset(nowNs = 1_000_000_000L)

        assertFalse(monitor.isExpired(3_999_999_999L))
        assertTrue(monitor.isExpired(4_000_000_000L))
        monitor.recordInbound(5_000_000_000L)
        assertFalse(monitor.isExpired(5_000_000_001L))
    }

    @Test
    fun structuralHevcTargetFailureMakesH264ExplicitNextCandidate() {
        assertEquals(listOf(StreamCodec.HEVC, StreamCodec.H264), CodecFallbackPolicy.candidates(true))
        assertEquals(
            listOf(StreamCodec.HEVC, StreamCodec.H264),
            CodecFallbackPolicy.candidates(hasUsableHevcDecoder = true, hasUsableAv1Decoder = true),
        )

        CodecFallbackPolicy.recordStructuralUnsupported(StreamCodec.HEVC)

        assertTrue(CodecFallbackPolicy.shouldUseH264(hasUsableHevcDecoder = true))
        assertEquals(listOf(StreamCodec.H264), CodecFallbackPolicy.candidates(true))
    }
}
