package dev.telemachus.display.internet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class InternetControllerSendQueueTest {
    @Test
    fun `analog backlog retains only latest complete multi-controller snapshot`() {
        val queue = InternetControllerSendQueue<String>()

        assertEquals(
            InternetControllerSendQueue.EnqueueResult.ACCEPTED,
            queue.enqueue(listOf("one=0.2", "two=-0.4"), ANALOG),
        )
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.COALESCED,
            queue.enqueue(listOf("one=0.8", "two=0.0"), ANALOG),
        )

        assertEquals(listOf(ANALOG to listOf("one=0.8", "two=0.0")), queue.pendingBatches())
    }

    @Test
    fun `normal analog backpressure keeps session-owned queue retryable`() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("one=0.2", "two=-0.4"), ANALOG)

        val blocked = queue.drain { false }
        assertTrue(blocked.blocked)
        assertEquals(0, blocked.sentEvents)
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.COALESCED,
            queue.enqueue(listOf("one=0.9", "two=0.1"), ANALOG),
        )

        val written = mutableListOf<String>()
        val drained = queue.drain { event -> true.also { written += event } }
        assertFalse(drained.blocked)
        assertEquals(listOf("one=0.9", "two=0.1"), written)
    }

    @Test
    fun `structural boundaries stay fifo and supersede unsent analog state`() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("connected"), STRUCTURAL)
        queue.enqueue(listOf("analog-old-one", "analog-old-two"), ANALOG)
        queue.enqueue(listOf("button-one", "button-two"), STRUCTURAL)
        queue.enqueue(listOf("analog-new-one", "analog-new-two"), ANALOG)
        queue.enqueue(listOf("neutral", "disconnected"), STRUCTURAL)

        val written = mutableListOf<String>()
        queue.drain { event -> true.also { written += event } }

        assertEquals(
            listOf("connected", "button-one", "button-two", "neutral", "disconnected"),
            written,
        )
    }

    @Test
    fun `connect and disconnect supersede analog only with remaining controller snapshots`() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("analog:B=0.4"), ANALOG)
        queue.enqueue(listOf("connected:A", "state:A=0.0", "state:B=0.4"), STRUCTURAL)
        queue.enqueue(listOf("analog:A=0.2", "analog:B=0.8"), ANALOG)
        queue.enqueue(listOf("neutral:A", "disconnected:A", "state:B=0.8"), STRUCTURAL)

        val written = mutableListOf<String>()
        queue.drain { event -> true.also { written += event } }

        assertEquals(
            listOf(
                "connected:A",
                "state:A=0.0",
                "state:B=0.4",
                "neutral:A",
                "disconnected:A",
                "state:B=0.8",
            ),
            written,
        )
    }

    @Test
    fun `partially transmitted full snapshot completes before its replacement`() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("old-one", "old-two"), ANALOG)
        var attempts = 0
        queue.drain {
            attempts++
            attempts == 1
        }

        queue.enqueue(listOf("new-one", "new-two"), ANALOG)
        val written = mutableListOf<String>()
        queue.drain { event -> true.also { written += event } }

        assertEquals(listOf("old-two", "new-one", "new-two"), written)
    }

    @Test
    fun `structural capacity is explicit without evicting boundaries`() {
        val queue = InternetControllerSendQueue<String>(maximumStructuralBatches = 1)
        assertEquals(InternetControllerSendQueue.EnqueueResult.ACCEPTED, queue.enqueue(listOf("connected"), STRUCTURAL))
        assertEquals(
            InternetControllerSendQueue.EnqueueResult.STRUCTURAL_OVERFLOW,
            queue.enqueue(listOf("button"), STRUCTURAL),
        )
        assertEquals(listOf(STRUCTURAL to listOf("connected")), queue.pendingBatches())
    }

    @Test
    fun `send exception clears in-flight ownership and retains event for explicit retry`() {
        val queue = InternetControllerSendQueue<String>()
        queue.enqueue(listOf("state"), ANALOG)

        val failure = IllegalStateException("encoder failed")
        val failed = queue.drain { throw failure }
        assertEquals(failure, failed.failure)
        assertFalse(failed.blocked)
        assertEquals(listOf(ANALOG to listOf("state")), queue.pendingBatches())

        val written = mutableListOf<String>()
        val retried = queue.drain { event -> true.also { written += event } }
        assertEquals(null, retried.failure)
        assertEquals(listOf("state"), written)
    }

    @Test
    fun `control linearizer orders id allocation encoding and send across threads`() {
        val gate = InternetControlSendLinearizer()
        val nextId = AtomicInteger()
        val firstAllocated = CountDownLatch(1)
        val releaseFirstSend = CountDownLatch(1)
        val sent = Collections.synchronizedList(mutableListOf<Int>())

        val first =
            Thread {
                gate.withGate {
                    val id = nextId.incrementAndGet()
                    firstAllocated.countDown()
                    releaseFirstSend.await()
                    sent += id
                }
            }.apply { start() }
        assertTrue(firstAllocated.await(1, TimeUnit.SECONDS))
        val second =
            Thread {
                gate.withGate {
                    val id = nextId.incrementAndGet()
                    sent += id
                }
            }.apply { start() }

        assertTrue(sent.isEmpty())
        releaseFirstSend.countDown()
        first.join(1_000)
        second.join(1_000)

        assertFalse(first.isAlive)
        assertFalse(second.isAlive)
        assertEquals(listOf(1, 2), sent)
    }

    @Test
    fun `control linearizer permits same-thread callback reentry`() {
        val gate = InternetControlSendLinearizer()
        val order = mutableListOf<String>()

        gate.withGate {
            order += "outer-before"
            gate.withGate { order += "callback" }
            order += "outer-after"
        }

        assertEquals(listOf("outer-before", "callback", "outer-after"), order)
    }

    private companion object {
        val ANALOG = InternetControllerSendQueue.Delivery.ANALOG
        val STRUCTURAL = InternetControllerSendQueue.Delivery.FULL_STATE_STRUCTURAL
    }
}
