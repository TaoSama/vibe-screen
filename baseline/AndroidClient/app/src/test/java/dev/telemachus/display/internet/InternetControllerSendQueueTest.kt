package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InternetControllerSendQueueTest {
    @Test
    fun analogBatchesCoalesceWhenTrailing() {
        val queue = InternetControllerSendQueue<String>()
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("a"), InternetControllerSendQueue.Delivery.ANALOG),
        )
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.COALESCED,
            queue.enqueue(listOf("b"), InternetControllerSendQueue.Delivery.ANALOG),
        )

        val pending = queue.pendingBatches()

        assertEquals(1, pending.size)
        assertEquals(listOf("b"), pending.single().second)
    }

    @Test
    fun structuralBatchesAreFifoAndNotCoalesced() {
        val queue = InternetControllerSendQueue<String>()

        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("s2"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )

        val pending = queue.pendingBatches()

        assertEquals(2, pending.size)
        assertEquals(listOf("s1"), pending[0].second)
        assertEquals(listOf("s2"), pending[1].second)
    }

    @Test
    fun structuralSupersedesTrailingAnalog() {
        val queue = InternetControllerSendQueue<String>()

        queue.enqueue(listOf("a"), InternetControllerSendQueue.Delivery.ANALOG)
        queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)

        val pending = queue.pendingBatches()

        assertEquals(1, pending.size)
        assertEquals(InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL, pending.single().first)
    }

    @Test
    fun structuralOverflowRejectsWhenAtCapacity() {
        val queue = InternetControllerSendQueue<String>(maximumStructuralBatches = 2)

        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("s2"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.STRUCTURAL_OVERFLOW,
            queue.enqueue(listOf("s3"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )
    }

    @Test
    fun structuralOverflowDoesNotDiscardTrailingAnalog() {
        val queue = InternetControllerSendQueue<String>(maximumStructuralBatches = 2)
        queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)
        queue.enqueue(listOf("s2"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)
        queue.enqueue(listOf("analog"), InternetControllerSendQueue.Delivery.ANALOG)

        assertEquals(
            InternetControllerSendQueue.EnqueueResult.STRUCTURAL_OVERFLOW,
            queue.enqueue(listOf("s3"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL),
        )
        assertEquals(
            listOf(
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL to listOf("s1"),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL to listOf("s2"),
                InternetControllerSendQueue.Delivery.ANALOG to listOf("analog"),
            ),
            queue.pendingBatches(),
        )
    }

    @Test
    fun drainSendsEventsInOrderUntilBackpressure() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)
        queue.enqueue(listOf("a1"), InternetControllerSendQueue.Delivery.ANALOG)
        val sent = mutableListOf<String>()

        val result = queue.drain { event -> sent += event; true }

        assertEquals(listOf("s1", "a1"), sent)
        assertEquals(2, result.sentEvents)
        assertFalse(result.blocked)
    }

    @Test
    fun drainRetriesBlockedEvent() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)

        val result = queue.drain { false }
        val retry = queue.drain { true }

        assertEquals(0, result.sentEvents)
        assertTrue(result.blocked)
        assertEquals(1, retry.sentEvents)
    }

    @Test
    fun drainSelectableSkipsBlockedHeadWithoutPassingEarlierSameKey() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("a2", "b1", "a3"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)
        val sent = mutableListOf<String>()

        val result =
            queue.drainSelectable(
                canSend = { event -> event != "a2" },
                sharesOrderingKey = { first, second -> first.first() == second.first() },
                send = { event ->
                    sent += event
                    true
                },
            )

        assertEquals(listOf("b1"), sent)
        assertEquals(1, result.sentEvents)
        assertTrue(result.blocked)
        assertEquals(
            listOf(InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL to listOf("a2", "a3")),
            queue.pendingBatches(),
        )
    }

    @Test
    fun analogBackpressureKeepsCurrentRemainderAndOnlyLatestSnapshot() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("old-1", "old-2"), InternetControllerSendQueue.Delivery.ANALOG)

        val firstAttempt = mutableListOf<String>()
        val blocked = queue.drain { event -> firstAttempt += event; event == "old-1" }
        queue.enqueue(listOf("new-1"), InternetControllerSendQueue.Delivery.ANALOG)
        repeat(100) { index ->
            assertEquals(
                InternetControllerSendQueue.EnqueueResult.COALESCED,
                queue.enqueue(listOf("new-${index + 2}"), InternetControllerSendQueue.Delivery.ANALOG),
            )
        }

        val pending = queue.pendingBatches()
        val retried = mutableListOf<String>()
        val drained = queue.drain { event -> retried += event; true }

        assertEquals(listOf("old-1", "old-2"), firstAttempt)
        assertEquals(1, blocked.sentEvents)
        assertTrue(blocked.blocked)
        assertEquals(2, pending.size)
        assertEquals(listOf("old-2"), pending[0].second)
        assertEquals(listOf("new-101"), pending[1].second)
        assertEquals(listOf("old-2", "new-101"), retried)
        assertEquals(2, drained.sentEvents)
        assertFalse(drained.blocked)
        assertTrue(queue.pendingBatches().isEmpty())
    }

    @Test
    fun structuralBackpressureKeepsOnlyTheUnsentRemainder() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(
            listOf("connected", "state-1", "state-2"),
            InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL,
        )

        val firstAttempt = mutableListOf<String>()
        val blocked = queue.drain { event -> firstAttempt += event; event != "state-2" }

        assertEquals(listOf("connected", "state-1", "state-2"), firstAttempt)
        assertEquals(2, blocked.sentEvents)
        assertTrue(blocked.blocked)
        assertEquals(
            listOf(InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL to listOf("state-2")),
            queue.pendingBatches(),
        )
    }

    @Test
    fun structuralDoesNotDiscardPartiallyDrainedTrailingAnalog() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("analog-1", "analog-2"), InternetControllerSendQueue.Delivery.ANALOG)
        queue.drain { event -> event == "analog-1" }

        queue.enqueue(listOf("structural"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)

        assertEquals(
            listOf(
                InternetControllerSendQueue.Delivery.ANALOG to listOf("analog-2"),
                InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL to listOf("structural"),
            ),
            queue.pendingBatches(),
        )
    }

    @Test
    fun clearRemovesAllPendingBatches() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("s1"), InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL)
        queue.enqueue(listOf("a1"), InternetControllerSendQueue.Delivery.ANALOG)

        queue.clear()

        assertTrue(queue.pendingBatches().isEmpty())
    }

    @Test(expected = IllegalArgumentException::class)
    fun enqueueRejectsEmptyEvents() {
        InternetControllerSendQueue<String>().enqueue(emptyList(), InternetControllerSendQueue.Delivery.ANALOG)
    }
}
