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
    fun touchMoveUsesIngressWhenSchedulerLockIsContended() {
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

        val moveSubmission = scheduler.submit(MOVE, "move", timeoutMillis = 0)

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, moveSubmission)
        releaseCoalescer.countDown()
        coalescerThread.join(1_000)
        assertFalse(coalescerThread.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, coalescedSubmission.get())
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "normal+force", "move"), written)
    }

    @Test
    fun touchMoveIngressStillTimesOutWhenItsAdmissionLimitIsFull() {
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
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "fill"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "normal"))
        val coalescerThread =
            Thread {
                coalescedSubmission.set(scheduler.submit(KEYFRAME, "force"))
            }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        val moveSubmission = scheduler.submit(MOVE, "move", timeoutMillis = 0)

        assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, moveSubmission)
        releaseCoalescer.countDown()
        coalescerThread.join(1_000)
        assertFalse(coalescerThread.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, coalescedSubmission.get())
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "normal+force", "fill"), written)
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
        val afterActive = written.drop(1)
        assertEquals(listOf("down", "up"), afterActive.filter { it == "down" || it == "up" })
        val recovery = afterActive.filterNot { it == "down" || it == "up" }
        assertEquals(1, recovery.count { it == "ping" })
        val keyframes = recovery.filterNot { it == "ping" }
        assertTrue(
            "unexpected keyframe writes: $keyframes",
            keyframes == listOf("normal+lock-holder+force-1+force-2") ||
                keyframes == listOf("normal+lock-holder", "force-1+force-2"),
        )
    }

    @Test
    fun gracefulShutdownDrainsQueuedIngressBeforeOverflowFallback() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val boundaryGenerationAllocated = CountDownLatch(1)
        val overflowValuePublished = CountDownLatch(1)
        val releaseOverflowPublisher = CountDownLatch(1)
        val shutdownHasMainLock = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val boundaryResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val moveResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val shutdownResult = AtomicReference<Boolean>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 8,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
                afterOverflowValuePublished = {
                    overflowValuePublished.countDown()
                    releaseOverflowPublisher.await()
                },
                afterControllerBoundaryGenerationAllocated = { boundaryGenerationAllocated.countDown() },
                beforeControllerLifecycleClose = { shutdownHasMainLock.countDown() },
            )

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "keyframe"))
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-latest") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(STRUCTURAL, "ingress-before"),
        )
        val boundarySubmitter =
            Thread { boundaryResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "boundary")) }.apply { start() }
        assertTrue(boundaryGenerationAllocated.await(1, TimeUnit.SECONDS))
        val moveSubmitter =
            Thread { moveResult.set(scheduler.submit(CONTROLLER_MOVE, "move-after")) }.apply { start() }
        assertTrue(overflowValuePublished.await(1, TimeUnit.SECONDS))
        releaseOverflowPublisher.countDown()
        boundarySubmitter.join(1_000)
        moveSubmitter.join(1_000)
        assertFalse(boundarySubmitter.isAlive)
        assertFalse(moveSubmitter.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, boundaryResult.get())
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, moveResult.get())
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(STRUCTURAL, "ingress-after"),
        )

        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        assertFalse(lockHolder.isAlive)
        val shutdown =
            Thread { shutdownResult.set(scheduler.shutdownGracefully(1_000)) }.apply { start() }
        assertTrue(shutdownHasMainLock.await(1, TimeUnit.SECONDS))
        releaseWriter.countDown()
        shutdown.join(2_000)

        assertFalse(shutdown.isAlive)
        assertEquals(true, shutdownResult.get())
        assertEquals(
            listOf("ingress-before", "boundary", "move-after", "ingress-after"),
            written.filter { it.startsWith("ingress-") || it == "boundary" || it == "move-after" },
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
        assertTrue(scheduler.shutdownGracefully(100))
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
    fun structuralTouchCanReuseMoveSlotWhileRecoveryReserveIsOccupied() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "active") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "active"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "down"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "keyframe"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(PING, "ping"))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(STRUCTURAL, "up"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "keyframe", "ping", "down", "up"), written)
    }

    @Test
    fun structuralTouchDoesNotDiscardControllerStateFromAnotherInputDomain() {
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

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "active"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controller-move"),
        )
        assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, scheduler.submit(STRUCTURAL, "up"))
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "controller-move"), written)
    }

    @Test
    fun recoveryCommandsCanTakeTheSlotOfAStaleTouchMove() {
        listOf(KEYFRAME to "keyframe", PING to "ping").forEach { (kind, recovery) ->
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

            assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "active"))
            assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
            assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "move"))
            assertEquals(
                OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
                scheduler.submit(kind, recovery),
            )
            releaseWriter.countDown()

            assertTrue(scheduler.shutdownGracefully(1_000))
            assertEquals(listOf("active", recovery), written)
        }
    }

    @Test
    fun recoveryCommandsDoNotDiscardControllerStateFromAnotherInputDomain() {
        listOf(KEYFRAME to "keyframe", PING to "ping").forEach { (kind, recovery) ->
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

            assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "active"))
            assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
            assertEquals(
                OutboundCommandScheduler.Submission.ACCEPTED,
                scheduler.submit(CONTROLLER_MOVE, "controller-move"),
            )
            assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, scheduler.submit(kind, recovery))
            releaseWriter.countDown()

            assertTrue(scheduler.shutdownGracefully(1_000))
            assertEquals(listOf("active", "controller-move"), written)
        }
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
        assertTrue(scheduler.shutdownGracefully(100))
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

    @Test
    fun controllerStructuralBoundarySupersedesPriorControllerMoves() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "move-1"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_STRUCTURAL, "connect"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "move-2"))
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertFalse(written.contains("move-1"))
        assertEquals(listOf("block", "connect", "move-2"), written)
    }

    @Test
    fun controllerMovesBeforeStructuralBoundaryAreNotCoalescedAcrossIt() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "block")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(CONTROLLER_MOVE, "move-before")
        scheduler.submit(CONTROLLER_STRUCTURAL, "boundary")
        scheduler.submit(CONTROLLER_MOVE, "move-after")
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("block", "boundary", "move-after"), written)
    }

    @Test
    fun controllerStructuralDoesNotBlockOnHasSpaceAndFailsClosedWhenFull() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 2) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        scheduler.submit(STRUCTURAL, "block")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "fill-1"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "fill-2"))
        // No more slots; controller structural must fail closed with TIMED_OUT, not block
        val result = scheduler.submit(CONTROLLER_STRUCTURAL, "structural-full", timeoutMillis = 50)
        assertEquals(OutboundCommandScheduler.Submission.TIMED_OUT, result)
        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
    }

    @Test
    fun controllerStructuralUsesRecoveryReserveDuringTouchSaturation() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "touch-1"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "touch-2"))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-disconnected"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.TIMED_OUT,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-overflow"),
        )

        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(
            listOf("block", "touch-1", "touch-2", "controller-connected", "controller-disconnected"),
            written,
        )
    }

    @Test
    fun controllerStructuralEvictsOldestAnalogDomainWhenCapacityIsFull() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 2) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "touch-move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "controller-move"))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"),
        )

        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("block", "controller-connected"), written)
    }

    @Test
    fun controllerStructuralCanReuseAnalogSlotWhileRecoveryReserveIsOccupied() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "touch-move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "controller-move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "keyframe"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(PING, "ping"))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("block", "keyframe", "ping", "controller-connected"), written)
    }

    @Test
    fun acceptedControllerStructuralIsDrainedDuringGracefulShutdown() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler = scheduler(capacity = 4) { command ->
            if (command == "block") {
                writerEntered.countDown()
                releaseWriter.await()
            }
            written += command
        }

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_STRUCTURAL, "connect"))
        val shutdownResult = AtomicReference<Boolean>()
        val shutdown = Thread { shutdownResult.set(scheduler.shutdownGracefully(1_000)) }.apply { start() }
        releaseWriter.countDown()
        shutdown.join(2_000)

        assertFalse(shutdown.isAlive)
        assertEquals(true, shutdownResult.get())
        assertEquals(listOf("block", "connect"), written)
    }

    @Test
    fun controllerMoveOverflowUsesGenerationAndIsSupersededByStructural() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 5,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
            )

        scheduler.submit(STRUCTURAL, "block")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(STRUCTURAL, "fill")
        scheduler.submit(KEYFRAME, "keyframe")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-latest") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "move-overflow"))
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_STRUCTURAL, "boundary"),
        )

        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertFalse(written.contains("move-overflow"))
        assertTrue(written.contains("boundary"))
    }

    @Test
    fun controllerLifecycleLockDoesNotDeadlockAgainstShutdown() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val shutdownOwnsMainLock = CountDownLatch(1)
        val allowShutdownToTakeLifecycleLock = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 4,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                beforeControllerLifecycleClose = {
                    shutdownOwnsMainLock.countDown()
                    allowShutdownToTakeLifecycleLock.await()
                },
            )

        scheduler.submit(STRUCTURAL, "block")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))

        val shutdownResult = AtomicReference<Boolean>()
        val shutdownThread = Thread {
            shutdownResult.set(scheduler.shutdownGracefully(2_000))
        }
        shutdownThread.start()
        assertTrue(shutdownOwnsMainLock.await(1, TimeUnit.SECONDS))
        val submitResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val submitThread = Thread {
            submitResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "during-shutdown"))
        }
        submitThread.start()
        submitThread.join(1_000)
        assertFalse(submitThread.isAlive)
        allowShutdownToTakeLifecycleLock.countDown()
        releaseWriter.countDown()
        shutdownThread.join(3_000)
        assertTrue(shutdownResult.get() == true)
        // Either accepted and drained, or closed during shutdown
        assertTrue(
            submitResult.get() == OutboundCommandScheduler.Submission.ACCEPTED ||
                submitResult.get() == OutboundCommandScheduler.Submission.CLOSED,
        )
    }
    @Test
    fun contendedIngressStructuralBoundaryKeepsSameGenerationMoveSubmittedAfterIt() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val boundarySubmission = AtomicReference<OutboundCommandScheduler.Submission>()
        val sched =
            OutboundCommandScheduler<String>(
                capacity = 6,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == OutboundCommandScheduler.Kind.KEYFRAME) {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
            )

        // Block the writer so the main lock stays contended and the structural
        // boundary is forced through the lock-free ingress path.
        sched.submit(STRUCTURAL, "block")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        sched.submit(STRUCTURAL, "fill-1")
        sched.submit(STRUCTURAL, "fill-2")
        sched.submit(KEYFRAME, "keyframe")

        // Hold the main lock via the keyframe coalesce callback so the next
        // controller structural submit cannot acquire it and must use ingress.
        val lockHolder = Thread {
            sched.submit(KEYFRAME, "keyframe-latest")
        }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        // Submit the structural boundary through ingress from a separate thread.
        // Waiting for this submission to finish proves the boundary is enqueued
        // before the same-generation move is published behind it.
        val boundarySubmitter = Thread {
            boundarySubmission.set(sched.submit(CONTROLLER_STRUCTURAL, "boundary"))
        }.apply { start() }
        boundarySubmitter.join(1_000)
        assertFalse(boundarySubmitter.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, boundarySubmission.get())
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            sched.submit(CONTROLLER_MOVE, "move-after-boundary"),
        )
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        releaseWriter.countDown()

        assertTrue(sched.shutdownGracefully(1_000))
        val boundaryIdx = written.indexOf("boundary")
        assertTrue(boundaryIdx >= 0)
        // The move submitted after the boundary (same generation) must survive
        // and be written after the boundary, not discarded by it.
        assertTrue(written.subList(boundaryIdx, written.size).contains("move-after-boundary"))
    }

    @Test
    fun deferredRecoveryMarkerCannotReorderControllerStructuralBoundaries() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val mainLockHeld = CountDownLatch(1)
        val releaseMainLock = CountDownLatch(1)
        val firstBoundaryReserved = CountDownLatch(1)
        val releaseFirstBoundary = CountDownLatch(1)
        val boundaryHookCalls = AtomicInteger()
        val firstBoundaryResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 5,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == MOVE && replacement == "hold-main-lock") {
                        mainLockHeld.countDown()
                        releaseMainLock.await()
                    }
                    replacement
                },
                afterControllerBoundaryGenerationAllocated = {
                    if (boundaryHookCalls.incrementAndGet() == 1) {
                        firstBoundaryReserved.countDown()
                        releaseFirstBoundary.await()
                    }
                },
            )

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "touch-boundary"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "touch-move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "controller-move"))

        val lockHolder = Thread { scheduler.submit(MOVE, "hold-main-lock") }.apply { start() }
        assertTrue(mainLockHeld.await(1, TimeUnit.SECONDS))
        val firstBoundarySubmitter =
            Thread {
                firstBoundaryResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "boundary-1"))
            }.apply { start() }
        assertTrue(firstBoundaryReserved.await(1, TimeUnit.SECONDS))

        // The keyframe consumes the last slot while boundary-1 is reserved but
        // not yet enqueued. The ping then publishes an unreserved marker ahead
        // of boundary-1 and cannot be drained until capacity is released.
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "keyframe"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(PING, "deferred-ping"))
        releaseFirstBoundary.countDown()
        firstBoundarySubmitter.join(1_000)
        assertFalse(firstBoundarySubmitter.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, firstBoundaryResult.get())

        releaseMainLock.countDown()
        lockHolder.join(1_000)
        assertFalse(lockHolder.isAlive)
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(CONTROLLER_STRUCTURAL, "boundary-2"),
        )

        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        val firstBoundaryIndex = written.indexOf("boundary-1")
        val secondBoundaryIndex = written.indexOf("boundary-2")
        assertTrue(firstBoundaryIndex >= 0)
        assertTrue(secondBoundaryIndex >= 0)
        assertTrue(firstBoundaryIndex < secondBoundaryIndex)
        assertTrue(written.contains("deferred-ping"))
        assertFalse(written.contains("hold-main-lock"))
    }

    @Test
    fun controllerBoundaryCapacityReleaseRetriesDeferredRecoveryBeforeInput() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val mainLockHeld = CountDownLatch(1)
        val releaseMainLock = CountDownLatch(1)
        val firstBoundaryReserved = CountDownLatch(1)
        val releaseFirstBoundary = CountDownLatch(1)
        val boundaryHookCalls = AtomicInteger()
        val firstBoundaryResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 3,
                writer = { command ->
                    if (command == "block") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == MOVE && replacement == "hold-main-lock") {
                        mainLockHeld.countDown()
                        releaseMainLock.await()
                    }
                    replacement
                },
                afterControllerBoundaryGenerationAllocated = {
                    if (boundaryHookCalls.incrementAndGet() == 1) {
                        firstBoundaryReserved.countDown()
                        releaseFirstBoundary.await()
                    }
                },
            )

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(STRUCTURAL, "block"))
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "touch-move"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "controller-move"))

        val lockHolder = Thread { scheduler.submit(MOVE, "hold-main-lock") }.apply { start() }
        assertTrue(mainLockHeld.await(1, TimeUnit.SECONDS))
        val firstBoundarySubmitter =
            Thread {
                firstBoundaryResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "boundary-1"))
            }.apply { start() }
        assertTrue(firstBoundaryReserved.await(1, TimeUnit.SECONDS))

        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(KEYFRAME, "deferred-keyframe"))
        releaseFirstBoundary.countDown()
        firstBoundarySubmitter.join(1_000)
        assertFalse(firstBoundarySubmitter.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, firstBoundaryResult.get())

        releaseMainLock.countDown()
        lockHolder.join(1_000)
        assertFalse(lockHolder.isAlive)
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(CONTROLLER_STRUCTURAL, "boundary-2"),
        )

        releaseWriter.countDown()
        assertTrue(scheduler.shutdownGracefully(1_000))
        val keyframeIndex = written.indexOf("deferred-keyframe")
        val firstBoundaryIndex = written.indexOf("boundary-1")
        val secondBoundaryIndex = written.indexOf("boundary-2")
        assertTrue(keyframeIndex >= 0)
        assertTrue(firstBoundaryIndex >= 0)
        assertTrue(secondBoundaryIndex >= 0)
        assertTrue(keyframeIndex < firstBoundaryIndex)
        assertTrue(firstBoundaryIndex < secondBoundaryIndex)
        assertFalse(written.contains("hold-main-lock"))
    }

    private companion object {
        val STRUCTURAL = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
        val MOVE = OutboundCommandScheduler.Kind.MOVE
        val KEYFRAME = OutboundCommandScheduler.Kind.KEYFRAME
        val PING = OutboundCommandScheduler.Kind.PING
        val CONTROLLER_STRUCTURAL = OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL
        val CONTROLLER_MOVE = OutboundCommandScheduler.Kind.CONTROLLER_MOVE
    }
}
