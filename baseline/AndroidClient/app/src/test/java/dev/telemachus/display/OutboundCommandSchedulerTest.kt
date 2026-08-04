package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class OutboundCommandSchedulerTest {
    @Test
    fun moveKeepsOnlyLatestPendingValue() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 3) { command ->
            if (command == "down") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "down"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "move-1"))
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, scheduler.submit(MOVE, "move-2"))
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, scheduler.submit(MOVE, "move-3"))
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("down", "move-3"), written)
    }

    @Test
    fun latestMoveRemainsBetweenGestureBoundaries() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 3) { command ->
            if (command == "down") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "down")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(MOVE, "move-1")
        scheduler.submit(MOVE, "move-latest")
        scheduler.submit(STRUCTURAL, "up")
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("down", "move-latest", "up"), written)
    }

    @Test
    fun recoveryCommandsAreCoalescedAndWrittenBeforeTouchQueue() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 5) { command ->
            if (command == "active") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")
        scheduler.submit(PING, "ping-1")
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, scheduler.submit(PING, "ping-2"))
        scheduler.submit(KEYFRAME, "keyframe")
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "keyframe", "ping-2", "down", "up"), written)
    }

    @Test
    fun keyframeCoalescerCanPreserveForcedRecoveryFlag() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 4,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, pending, replacement ->
                    if (kind == KEYFRAME) "$pending+$replacement" else replacement
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(KEYFRAME, "normal")
        scheduler.submit(KEYFRAME, "force")
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "normal+force"), written)
    }

    @Test
    fun structuralSaturationIsExplicitSoCallerCanFailSessionClosed() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 2) { command ->
            if (command == "active") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "down"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "up"))
        val cancelSubmission = scheduler.submit(STRUCTURAL, "cancel", timeoutMillis = 1)
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, cancelSubmission)
        assertEquals(listOf("active", "down", "up"), written)
    }

    @Test
    fun structuralTouchCanTakeTheSlotOfAStaleMove() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 1) { command ->
            if (command == "active") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(MOVE, "move")
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(STRUCTURAL, "up"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "up"), written)
    }

    @Test
    fun gracefulShutdownDrainsAndRejectsNewCommands() {
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 2) { written += it }
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("down", "up"), written)
        assertEquals(OutboundCommandScheduler.Submission.CLOSED, scheduler.submit(STRUCTURAL, "late"))
    }

    @Test
    fun writeFailureIsTypedDeliveredOnceAndClosesScheduler() {
        val callbacks = AtomicInteger()
        val callbackDelivered = CountDownLatch(1)
        val failures = Collections.synchronizedList(mutableListOf<OutboundWriteFailure<String>>())
        val scheduler =
            OutboundCommandScheduler(
                capacity = 3,
                writer = { throw IOException("socket closed") },
                onWriteFailure = {
                    callbacks.incrementAndGet()
                    failures += it
                    callbackDelivered.countDown()
                },
            )

        scheduler.submit(STRUCTURAL, "down")
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertTrue(callbackDelivered.await(1, TimeUnit.SECONDS))
        assertEquals(1, callbacks.get())
        assertEquals("down", failures.single().command)
        assertTrue(failures.single().cause is IOException)
        assertEquals(OutboundCommandScheduler.Submission.CLOSED, scheduler.submit(STRUCTURAL, "up"))
        assertFalse(failures.isEmpty())
    }

    private fun scheduler(
        capacity: Int,
        writer: (String) -> Unit,
    ) =
        OutboundCommandScheduler(
            capacity = capacity,
            writer = writer,
            onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
        )

    private companion object {
        val STRUCTURAL = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
        val MOVE = OutboundCommandScheduler.Kind.MOVE
        val KEYFRAME = OutboundCommandScheduler.Kind.KEYFRAME
        val PING = OutboundCommandScheduler.Kind.PING
    }
}
