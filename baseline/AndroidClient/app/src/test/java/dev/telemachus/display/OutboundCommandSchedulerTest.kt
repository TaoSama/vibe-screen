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
    fun pointerAndControllerMovesUseIndependentCoalescingDomains() {
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

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "pointer-1"))
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controllers:{one=0.2,two=-0.4}"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.COALESCED,
            scheduler.submit(MOVE, "pointer-2"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.COALESCED,
            scheduler.submit(CONTROLLER_MOVE, "controllers:{one=0.0,two=0.0}"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(
            listOf("active", "pointer-2", "controllers:{one=0.0,two=0.0}"),
            written,
        )
    }

    @Test
    fun structuralCommandCanEvictOldestControllerMove() {
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
        scheduler.submit(CONTROLLER_MOVE, "controllers:{one=0.7}")
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(STRUCTURAL, "controller-disconnected"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "controller-disconnected"), written)
    }

    @Test
    fun latestControllerNeutralIsAdmittedWhenInterleavedMoveDomainsFillQueue() {
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
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(MOVE, "pointer-1"))
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(CONTROLLER_MOVE, "controller-1"))
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, scheduler.submit(MOVE, "pointer-2"))
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, scheduler.submit(CONTROLLER_MOVE, "controller-neutral"))
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "pointer-2", "controller-neutral"), written)
    }

    @Test
    fun crossDomainSaturationDoesNotEvictControllerNeutral() {
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
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controller-neutral"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(MOVE, "pointer-latest"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "controller-neutral", "pointer-latest"), written)
    }

    @Test
    fun contendedControllerOverflowAtomicallyKeepsLatestNeutral() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val updateResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 2,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME && replacement == "lock-holder-update") {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(CONTROLLER_MOVE, "controller-pressed")
        scheduler.submit(KEYFRAME, "lock-holder")
        val lockHolder =
            Thread {
                updateResult.set(scheduler.submit(KEYFRAME, "lock-holder-update"))
            }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controller-drift"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.COALESCED,
            scheduler.submit(CONTROLLER_MOVE, "controller-neutral"),
        )
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        releaseWriter.countDown()

        assertFalse(lockHolder.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.COALESCED, updateResult.get())
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "lock-holder-update", "controller-neutral"), written)
    }

    @Test
    fun controllerLifecycleBoundaryDiscardsOlderOverflowState() {
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
        scheduler.submit(MOVE, "pointer-blocker")
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controller-neutral-overflow"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED_AFTER_COALESCING_MOVE,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-disconnected"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "controller-disconnected"), written)
    }

    @Test
    fun rejectedControllerLifecycleBoundaryPreservesOverflowNeutral() {
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
        scheduler.submit(STRUCTURAL, "touch-boundary")
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "controller-neutral"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.TIMED_OUT,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-disconnected"),
        )
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        assertEquals(listOf("active", "touch-boundary", "controller-neutral"), written)
    }

    @Test
    fun controllerOverflowPublisherCannotCrossAcceptedLifecycleGeneration() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val oldPublisherEntered = CountDownLatch(1)
        val releaseOldPublisher = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val oldResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 3,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME && replacement == "keyframe-update") {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
                beforeOverflowPublish = {
                    oldPublisherEntered.countDown()
                    releaseOldPublisher.await()
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(KEYFRAME, "keyframe")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-update") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val oldPublisher =
            Thread {
                oldResult.set(scheduler.submit(CONTROLLER_MOVE, "old-controller-state"))
            }.apply { start() }
        assertTrue(oldPublisherEntered.await(1, TimeUnit.SECONDS))

        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-disconnected"),
        )
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, scheduler.submit(PING, "drain-ingress"))
        releaseOldPublisher.countDown()
        oldPublisher.join(1_000)
        releaseWriter.countDown()

        assertFalse(oldPublisher.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, oldResult.get())
        assertTrue(scheduler.shutdownGracefully(1_000))
        assertFalse(written.contains("old-controller-state"))
        assertTrue(written.contains("controller-disconnected"))
    }

    @Test
    fun contendedLifecycleAdmissionPreservesNewerControllerMove() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 3,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME && replacement == "keyframe-update") {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(KEYFRAME, "keyframe")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-update") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))

        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"),
        )
        assertEquals(
            OutboundCommandScheduler.Submission.ACCEPTED,
            scheduler.submit(CONTROLLER_MOVE, "new-controller-state"),
        )
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        releaseWriter.countDown()

        assertTrue(scheduler.shutdownGracefully(1_000))
        val boundaryIndex = written.indexOf("controller-connected")
        val stateIndex = written.indexOf("new-controller-state")
        assertTrue(boundaryIndex >= 0)
        assertTrue(stateIndex > boundaryIndex)
    }

    @Test
    fun lifecyclePublicationIsVisibleBeforeNewMoveCapturesGeneration() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val boundaryGenerationAllocated = CountDownLatch(1)
        val releaseBoundaryPublication = CountDownLatch(1)
        val moveStarted = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val boundaryResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val moveResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 3,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME && replacement == "keyframe-update") {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
                afterControllerBoundaryGenerationAllocated = {
                    boundaryGenerationAllocated.countDown()
                    releaseBoundaryPublication.await()
                },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(KEYFRAME, "keyframe")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-update") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val boundaryPublisher =
            Thread {
                boundaryResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"))
            }.apply { start() }
        assertTrue(boundaryGenerationAllocated.await(1, TimeUnit.SECONDS))
        val newMove =
            Thread {
                moveStarted.countDown()
                moveResult.set(scheduler.submit(CONTROLLER_MOVE, "new-controller-state"))
            }.apply { start() }
        assertTrue(moveStarted.await(1, TimeUnit.SECONDS))

        releaseBoundaryPublication.countDown()
        boundaryPublisher.join(1_000)
        newMove.join(1_000)
        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        releaseWriter.countDown()

        assertFalse(boundaryPublisher.isAlive)
        assertFalse(newMove.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, boundaryResult.get())
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, moveResult.get())
        assertTrue(scheduler.shutdownGracefully(1_000))
        val boundaryIndex = written.indexOf("controller-connected")
        val stateIndex = written.indexOf("new-controller-state")
        assertTrue(boundaryIndex >= 0)
        assertTrue(stateIndex > boundaryIndex)
    }

    @Test
    fun gracefulShutdownWaitsForAcceptedLifecyclePublication() {
        val writerEntered = CountDownLatch(1)
        val releaseWriter = CountDownLatch(1)
        val coalescerEntered = CountDownLatch(1)
        val releaseCoalescer = CountDownLatch(1)
        val boundaryGenerationAllocated = CountDownLatch(1)
        val releaseBoundaryPublication = CountDownLatch(1)
        val shutdownHasSchedulerLock = CountDownLatch(1)
        val written = Collections.synchronizedList(mutableListOf<String>())
        val boundaryResult = AtomicReference<OutboundCommandScheduler.Submission>()
        val shutdownResult = AtomicReference<Boolean>()
        val scheduler =
            OutboundCommandScheduler<String>(
                capacity = 3,
                writer = { command ->
                    if (command == "active") {
                        writerEntered.countDown()
                        releaseWriter.await()
                    }
                    written += command
                },
                onWriteFailure = { throw AssertionError("Unexpected failure", it.cause) },
                coalesce = { kind, _, replacement ->
                    if (kind == KEYFRAME && replacement == "keyframe-update") {
                        coalescerEntered.countDown()
                        releaseCoalescer.await()
                    }
                    replacement
                },
                afterControllerBoundaryGenerationAllocated = {
                    boundaryGenerationAllocated.countDown()
                    releaseBoundaryPublication.await()
                },
                beforeControllerLifecycleClose = { shutdownHasSchedulerLock.countDown() },
            )

        scheduler.submit(STRUCTURAL, "active")
        assertTrue(writerEntered.await(1, TimeUnit.SECONDS))
        scheduler.submit(KEYFRAME, "keyframe")
        val lockHolder = Thread { scheduler.submit(KEYFRAME, "keyframe-update") }.apply { start() }
        assertTrue(coalescerEntered.await(1, TimeUnit.SECONDS))
        val boundaryPublisher =
            Thread {
                boundaryResult.set(scheduler.submit(CONTROLLER_STRUCTURAL, "controller-connected"))
            }.apply { start() }
        assertTrue(boundaryGenerationAllocated.await(1, TimeUnit.SECONDS))
        val shutdown = Thread { shutdownResult.set(scheduler.shutdownGracefully(1_000)) }.apply { start() }

        releaseCoalescer.countDown()
        lockHolder.join(1_000)
        assertTrue(shutdownHasSchedulerLock.await(1, TimeUnit.SECONDS))
        releaseBoundaryPublication.countDown()
        boundaryPublisher.join(1_000)
        releaseWriter.countDown()
        shutdown.join(1_000)

        assertFalse(boundaryPublisher.isAlive)
        assertFalse(shutdown.isAlive)
        assertEquals(OutboundCommandScheduler.Submission.ACCEPTED, boundaryResult.get())
        assertEquals(true, shutdownResult.get())
        assertTrue(written.contains("controller-connected"))
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

    private companion object {
        val STRUCTURAL = OutboundCommandScheduler.Kind.STRUCTURAL_TOUCH
        val MOVE = OutboundCommandScheduler.Kind.MOVE
        val CONTROLLER_MOVE = OutboundCommandScheduler.Kind.CONTROLLER_MOVE
        val CONTROLLER_STRUCTURAL = OutboundCommandScheduler.Kind.CONTROLLER_STRUCTURAL
        val KEYFRAME = OutboundCommandScheduler.Kind.KEYFRAME
        val PING = OutboundCommandScheduler.Kind.PING
    }
}
