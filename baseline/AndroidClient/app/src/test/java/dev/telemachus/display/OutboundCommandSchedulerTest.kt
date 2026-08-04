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
import java.util.concurrent.atomic.AtomicReference

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
    fun lockContentionWithAvailableCapacityDoesNotReportSaturation() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val coalescedSubmission = AtomicReference<OutboundCommandScheduler.Submission>()
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
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                        "$pending+$replacement"
                    } else {
                        replacement
                    }
                },
            )

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "active"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "normal"))
        val coalescerThread =
            Thread {
                coalescedSubmission.set(scheduler.submit(KEYFRAME, "force"))
            }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        val structuralSubmission = scheduler.submit(STRUCTURAL, "up", timeoutMillis = 0)

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, structuralSubmission)
        releaseCoalescer.countDown()
        coalescerThread.join(1_000)
        assertFalse(coalescerThread.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, coalescedSubmission.get())
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "normal+force", "up"), written)
    }

    @Test
    fun fullQueueContentionStillCoalescesPendingKeyframe() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val firstCoalesced = AtomicReference<OutboundCommandScheduler.Submission>()
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
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                        "$pending+$replacement"
                    } else {
                        replacement
                    }
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")
        scheduler.submit(KEYFRAME, "normal")
        scheduler.submit(PING, "ping")
        val coalescerThread =
            Thread {
                firstCoalesced.set(scheduler.submit(KEYFRAME, "force-1"))
            }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        val contendedSubmission = scheduler.submit(KEYFRAME, "force-2", timeoutMillis = 0)

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, contendedSubmission)
        releaseCoalescer.countDown()
        coalescerThread.join(1_000)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, firstCoalesced.get())
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "normal+force-1+force-2", "ping", "down", "up"), written)
    }

    @Test
    fun shutdownNowRejectsOverflowPublishersThatObservedOpenState() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val overflowPublishersEntered = CountDownLatch(2)
        val releaseOverflowPublishers = CountDownLatch(1)
        val firstResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val secondResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 4,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, pending, replacement ->
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                        "$pending+$replacement"
                    } else {
                        replacement
                    }
                },
                beforeOverflowPublish = {
                    overflowPublishersEntered.countDown()
                    releaseOverflowPublishers.await()
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")
        scheduler.submit(KEYFRAME, "normal")
        scheduler.submit(PING, "ping")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "lock-holder") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val first = Thread { firstResult.set(scheduler.submit(KEYFRAME, "force-1")) }.apply { start() }
        val second = Thread { secondResult.set(scheduler.submit(KEYFRAME, "force-2")) }.apply { start() }
        assertTrue(overflowPublishersEntered.await(1, TimeUnit.SECONDS))

        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        scheduler.shutdownNow()
        releaseOverflowPublishers.countDown()
        first.join(1_000)
        second.join(1_000)
        releaseWriter.countDown()

        assertEquals(OutboundCommandScheduler.Submission.CLOSED, firstResult.get())
        assertEquals(OutboundCommandScheduler.Submission.CLOSED, secondResult.get())
        assertEquals(OutboundCommandScheduler.Submission.CLOSED, scheduler.submit(KEYFRAME, "late"))
    }

    @Test
    fun gracefulShutdownDrainsOverflowPublishedBeforeItsMarker() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val overflowPublishersEntered = CountDownLatch(2)
        val overflowValuePublished = CountDownLatch(1)
        val releaseOverflowPublisher = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val firstResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val secondResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val shutdownResult = AtomicReference<Boolean>()
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
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                        "$pending+$replacement"
                    } else {
                        replacement
                    }
                },
                beforeOverflowPublish = { overflowPublishersEntered.countDown() },
                afterOverflowValuePublished = {
                    overflowValuePublished.countDown()
                    releaseOverflowPublisher.await()
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")
        scheduler.submit(KEYFRAME, "normal")
        scheduler.submit(PING, "ping")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "lock-holder") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val first = Thread { firstResult.set(scheduler.submit(KEYFRAME, "force-1")) }.apply { start() }
        assertTrue(overflowValuePublished.await(1, TimeUnit.SECONDS))
        val second = Thread { secondResult.set(scheduler.submit(KEYFRAME, "force-2")) }.apply { start() }
        assertTrue(overflowPublishersEntered.await(1, TimeUnit.SECONDS))

        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        second.join(1_000)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, secondResult.get())
        val shutdown = Thread { shutdownResult.set(scheduler.shutdownGracefully(1_000)) }.apply { start() }
        releaseWriter.countDown()
        shutdown.join(1_000)
        releaseOverflowPublisher.countDown()
        first.join(1_000)

        assertEquals(true, shutdownResult.get())
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, firstResult.get())
        assertEquals("active", written.first())
        assertEquals(listOf("down", "up"), written.takeLast(2))
        val recovery = written.drop(1).dropLast(2)
        assertTrue(recovery.contains("ping"))
        assertEquals(
            "normal+lock-holder+force-1+force-2",
            recovery.filterNot { it == "ping" }.joinToString("+"),
        )
    }

    @Test
    fun shutdownNowMarksPublishedOverflowAsDiscardedBeforeMarker() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val overflowValuePublished = CountDownLatch(1)
        val releaseOverflowPublisher = CountDownLatch(1)
        val result = AtomicReference<OutboundCommandScheduler.Submission>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 4,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, pending, replacement ->
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                        "$pending+$replacement"
                    } else {
                        replacement
                    }
                },
                afterOverflowValuePublished = {
                    overflowValuePublished.countDown()
                    releaseOverflowPublisher.await()
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "down")
        scheduler.submit(STRUCTURAL, "up")
        scheduler.submit(KEYFRAME, "normal")
        scheduler.submit(PING, "ping")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "lock-holder") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val publisher = Thread { result.set(scheduler.submit(KEYFRAME, "force")) }.apply { start() }
        assertTrue(overflowValuePublished.await(1, TimeUnit.SECONDS))

        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        scheduler.shutdownNow()
        releaseOverflowPublisher.countDown()
        publisher.join(1_000)
        releaseWriter.countDown()

        assertEquals(OutboundCommandScheduler.Submission.CLOSED, result.get())
        assertEquals(OutboundCommandScheduler.Submission.CLOSED, scheduler.submit(KEYFRAME, "late"))
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
        val startedAt = System.nanoTime()
        val cancelSubmission = scheduler.submit(STRUCTURAL, "cancel", timeoutMillis = 0)
        val elapsedMs = (System.nanoTime() - startedAt) / 1_000_000.0
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, cancelSubmission)
        assertTrue("zero-timeout submission took ${elapsedMs}ms", elapsedMs < 50.0)
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
