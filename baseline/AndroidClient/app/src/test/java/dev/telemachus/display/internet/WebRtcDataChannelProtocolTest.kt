package dev.telemachus.display.internet

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test

class WebRtcDataChannelProtocolTest {
    @Test
    fun congestionReplacesWholeUnstartedFrameBatch() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1, 2))
        queue.offer(frame(3, 4))

        assertArrayEquals(byteArrayOf(3), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertArrayEquals(byteArrayOf(4), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertNull(queue.nextRecord())
    }

    @Test
    fun startedBatchFinishesBeforeNewestPendingReplacementWithoutMixingFrames() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1, 2, 3))

        val delivered = mutableListOf<Int>()
        delivered += takeAccepted(queue)
        queue.offer(frame(4, 5))
        queue.offer(frame(6, 7))
        while (queue.hasWork()) delivered += takeAccepted(queue)

        assertArrayEquals(intArrayOf(1, 2, 3, 6, 7), delivered.toIntArray())
    }

    @Test
    fun rejectedRecordRetriesInsideSameBatchBeforePendingFrame() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1, 2))

        assertArrayEquals(byteArrayOf(1), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertArrayEquals(byteArrayOf(2), queue.nextRecord())
        queue.offer(frame(3, 4))
        queue.completeRecord(accepted = false)
        assertArrayEquals(byteArrayOf(2), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertArrayEquals(byteArrayOf(3), queue.nextRecord())
    }

    @Test
    fun completingActiveBatchPromotesPendingBeforeNewOfferReplacesIt() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1))
        assertArrayEquals(byteArrayOf(1), queue.nextRecord())
        queue.offer(frame(2))

        queue.completeRecord(accepted = true)
        queue.offer(frame(3))

        assertArrayEquals(byteArrayOf(3), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertNull(queue.nextRecord())
    }

    @Test
    fun replacingFirstRejectedSendClearsOlderPendingBatch() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1))
        assertArrayEquals(byteArrayOf(1), queue.nextRecord())
        queue.offer(frame(2))
        queue.completeRecord(accepted = false)

        queue.offer(frame(3))

        assertArrayEquals(byteArrayOf(3), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertNull(queue.nextRecord())
    }

    @Test
    fun thrownRecordSendClearsInFlightAndPendingBatchesForRecovery() {
        val queue = LatestFrameBatchQueue()
        queue.offer(frame(1))
        queue.offer(frame(2))

        assertThrows(IllegalStateException::class.java) {
            queue.sendNext { throw IllegalStateException("seal failed") }
        }

        assertFalse(queue.hasWork())
        queue.offer(frame(3))
        assertTrue(queue.sendNext { record -> record.contentEquals(byteArrayOf(3)) } == true)
        assertFalse(queue.hasWork())
    }

    @Test
    fun queueOwnsWholeBatchCopy() {
        val first = byteArrayOf(7)
        val second = byteArrayOf(8)
        val queue = LatestFrameBatchQueue()
        queue.offer(OutboundMediaFrame(listOf(first, second)))
        first[0] = 9
        second[0] = 10

        assertArrayEquals(byteArrayOf(7), queue.nextRecord())
        queue.completeRecord(accepted = true)
        assertArrayEquals(byteArrayOf(8), queue.nextRecord())
        assertTrue(queue.hasWork())
    }

    private fun takeAccepted(queue: LatestFrameBatchQueue): Int =
        checkNotNull(queue.nextRecord()).single().toInt().also {
            queue.completeRecord(accepted = true)
        }

    private fun frame(vararg bytes: Int): OutboundMediaFrame =
        OutboundMediaFrame(bytes.map { byteArrayOf(it.toByte()) })
}
