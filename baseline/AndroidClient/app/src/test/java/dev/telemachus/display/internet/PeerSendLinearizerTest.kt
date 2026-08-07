package dev.telemachus.display.internet

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PeerSendLinearizerTest {
    @Test
    fun mediaPathTransitionCannotInvalidateAcceptedRecordBeforeTransmit() {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val generation = AtomicLong(1)
        val operationEntered = CountDownLatch(1)
        val releaseOperation = CountDownLatch(1)
        val transitionFinished = CountDownLatch(1)
        val transmitted = AtomicBoolean(false)

        Thread {
            linearizer.withCurrentMediaPath(
                snapshot = { PeerMediaSendSnapshot("channel", "cipher", generation.get()) },
                isCurrent = { connected.get() && it.generation == generation.get() },
            ) {
                operationEntered.countDown()
                check(releaseOperation.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
                transmitted.set(true)
            }
        }.start()

        assertTrue(operationEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        Thread {
            linearizer.withGate {
                connected.set(false)
                generation.incrementAndGet()
            }
            transitionFinished.countDown()
        }.start()
        assertFalse(transitionFinished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseOperation.countDown()
        assertTrue(transitionFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(transmitted.get())
    }

    @Test
    fun staleMediaGenerationIsRejectedBeforeOperation() {
        val linearizer = PeerSendLinearizer()
        val generation = AtomicLong(2)
        val operated = AtomicBoolean(false)

        val result =
            linearizer.withCurrentMediaPath(
                snapshot = { PeerMediaSendSnapshot("channel", "cipher", 1) },
                isCurrent = { it.generation == generation.get() },
            ) {
                operated.set(true)
            }

        assertTrue(result == null)
        assertFalse(operated.get())
    }

    @Test
    fun nativeRestartCallHoldsGateUntilItReturns() {
        val linearizer = PeerSendLinearizer()
        val restartEntered = CountDownLatch(1)
        val releaseRestart = CountDownLatch(1)
        val closeFinished = CountDownLatch(1)

        Thread {
            linearizer.withGate {
                restartEntered.countDown()
                check(releaseRestart.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
            }
        }.start()
        assertTrue(restartEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))

        Thread {
            linearizer.withGate { }
            closeFinished.countDown()
        }.start()
        assertFalse(closeFinished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseRestart.countDown()
        assertTrue(closeFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
    }

    @Test
    fun transitionWaitsForAcceptedControlSend() {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val generation = AtomicLong(1)
        val sealEntered = CountDownLatch(1)
        val releaseSeal = CountDownLatch(1)
        val sendFinished = CountDownLatch(1)
        val transitionFinished = CountDownLatch(1)
        val transmitted = AtomicBoolean(false)
        val result = AtomicReference<Boolean>()

        Thread {
            result.set(
                linearizer.sendControl(
                    snapshot = {
                        PeerControlSendSnapshot("channel", "cipher", generation.get())
                            .takeIf { connected.get() }
                    },
                    seal = {
                        sealEntered.countDown()
                        check(releaseSeal.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
                        byteArrayOf(1)
                    },
                    isCurrent = { connected.get() && it.generation == generation.get() },
                    transmit = { _, _ -> transmitted.also { it.set(true) }.get() },
                ),
            )
            sendFinished.countDown()
        }.start()

        assertTrue(sealEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        Thread {
            linearizer.withGate {
                connected.set(false)
                generation.incrementAndGet()
            }
            transitionFinished.countDown()
        }.start()
        assertFalse(transitionFinished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseSeal.countDown()
        assertTrue(sendFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(transitionFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(result.get())
        assertTrue(transmitted.get())
        assertFalse(connected.get())
    }

    @Test
    fun generationChangeDuringSealRejectsBeforeTransmit() {
        val linearizer = PeerSendLinearizer()
        val generation = AtomicLong(1)
        val transmitted = AtomicBoolean(false)

        val accepted =
            linearizer.sendControl(
                snapshot = { PeerControlSendSnapshot("channel", "cipher", generation.get()) },
                seal = {
                    generation.incrementAndGet()
                    byteArrayOf(1)
                },
                isCurrent = { it.generation == generation.get() },
                transmit = { _, _ -> transmitted.also { it.set(true) }.get() },
            )

        assertFalse(accepted)
        assertFalse(transmitted.get())
    }

    @Test
    fun transitionThatWinsTheGateMakesConcurrentControlSendReturnFalse() {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val generation = AtomicLong(1)
        val transitionEntered = CountDownLatch(1)
        val releaseTransition = CountDownLatch(1)
        val transitionFinished = CountDownLatch(1)
        val sendStarted = CountDownLatch(1)
        val sendFinished = CountDownLatch(1)
        val transmitted = AtomicBoolean(false)
        val result = AtomicReference<Boolean>()

        Thread {
            linearizer.withGate {
                connected.set(false)
                generation.incrementAndGet()
                transitionEntered.countDown()
                check(releaseTransition.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
            }
            transitionFinished.countDown()
        }.start()
        assertTrue(transitionEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))

        Thread {
            sendStarted.countDown()
            result.set(
                linearizer.sendControl(
                    snapshot = {
                        PeerControlSendSnapshot("channel", "cipher", generation.get())
                            .takeIf { connected.get() }
                    },
                    seal = { byteArrayOf(1) },
                    isCurrent = { connected.get() && it.generation == generation.get() },
                    transmit = { _, _ -> transmitted.also { it.set(true) }.get() },
                ),
            )
            sendFinished.countDown()
        }.start()
        assertTrue(sendStarted.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertFalse(sendFinished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseTransition.countDown()
        assertTrue(transitionFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(sendFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertFalse(result.get())
        assertFalse(transmitted.get())
    }

    @Test
    fun closeRacesFromSealValidationAndTransmitReturnFalse() {
        val linearizer = PeerSendLinearizer()
        val snapshot = { PeerControlSendSnapshot("channel", "cipher", 1) }

        assertFalse(
            linearizer.sendControl(
                snapshot = snapshot,
                seal = { throw IllegalStateException("cipher closed") },
                isCurrent = { true },
                transmit = { _, _ -> true },
            ),
        )
        assertFalse(
            linearizer.sendControl(
                snapshot = snapshot,
                seal = { byteArrayOf(1) },
                isCurrent = { throw IllegalStateException("channel closed") },
                transmit = { _, _ -> true },
            ),
        )
        assertFalse(
            linearizer.sendControl(
                snapshot = snapshot,
                seal = { byteArrayOf(1) },
                isCurrent = { true },
                transmit = { _, _ -> throw IllegalStateException("channel closed") },
            ),
        )
    }

    @Test
    fun failureTransitionThatWinsGateRejectsLateControlAndMedia() {
        assertTransitionThatWinsGateRejectsLateControlAndMedia { connected, selectedRoute, routeFailed, generation ->
            connected.set(false)
            selectedRoute.set(false)
            routeFailed.set(true)
            generation.incrementAndGet()
        }
    }

    @Test
    fun disconnectedTransitionThatWinsGateRejectsLateControlAndMedia() {
        assertTransitionThatWinsGateRejectsLateControlAndMedia { connected, selectedRoute, routeFailed, generation ->
            connected.set(false)
            selectedRoute.set(false)
            routeFailed.set(false)
            generation.incrementAndGet()
        }
    }

    private fun assertTransitionThatWinsGateRejectsLateControlAndMedia(
        transition: (AtomicBoolean, AtomicBoolean, AtomicBoolean, AtomicLong) -> Unit,
    ) {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val selectedRoute = AtomicBoolean(true)
        val routeFailed = AtomicBoolean(false)
        val generation = AtomicLong(1)
        val transitionEntered = CountDownLatch(1)
        val releaseTransition = CountDownLatch(1)
        val deliveries = AtomicInteger(0)
        val results = listOf(AtomicReference<Boolean>(), AtomicReference<Boolean>())
        val started = CountDownLatch(results.size)
        val finished = CountDownLatch(results.size)

        Thread {
            linearizer.withGate {
                transition(connected, selectedRoute, routeFailed, generation)
                transitionEntered.countDown()
                check(releaseTransition.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
            }
        }.start()
        assertTrue(transitionEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))

        listOf("control", "media").forEachIndexed { index, channel ->
            Thread {
                started.countDown()
                results[index].set(
                    linearizer.receiveInbound(
                        snapshot = {
                            PeerInboundReceiveSnapshot(
                                PeerInboundCallbackSource(channel, generation.get()),
                                "cipher",
                                "target",
                                7,
                            )
                                .takeIf {
                                    connected.get() &&
                                        selectedRoute.get() &&
                                        !routeFailed.get()
                                }
                        },
                        decode = { byteArrayOf(1) },
                        isCurrent = {
                            connected.get() &&
                                selectedRoute.get() &&
                                !routeFailed.get() &&
                                it.generation == generation.get()
                        },
                        onDecodeFailure = { throw AssertionError(it) },
                        deliver = { _, _, _ -> deliveries.incrementAndGet() },
                    ),
                )
                finished.countDown()
            }.start()
        }
        assertTrue(started.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertFalse(finished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseTransition.countDown()
        assertTrue(finished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(results.all { it.get() == false })
        assertEquals(0, deliveries.get())
    }

    @Test
    fun inboundThatWinsGateCompletesBeforeFailureTransition() {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val generation = AtomicLong(1)
        val deliveryEntered = CountDownLatch(1)
        val releaseDelivery = CountDownLatch(1)
        val transitionFinished = CountDownLatch(1)
        val order = mutableListOf<String>()

        Thread {
            linearizer.receiveInbound(
                snapshot = {
                    PeerInboundReceiveSnapshot(
                        PeerInboundCallbackSource("control", generation.get()),
                        "cipher",
                        "target",
                        7,
                    )
                        .takeIf { connected.get() }
                },
                decode = { byteArrayOf(1) },
                isCurrent = { connected.get() && it.generation == generation.get() },
                onDecodeFailure = { throw AssertionError(it) },
            ) { _, _, _ ->
                deliveryEntered.countDown()
                check(releaseDelivery.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
                synchronized(order) { order += "control" }
            }
        }.start()
        assertTrue(deliveryEntered.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))

        Thread {
            linearizer.withGate {
                connected.set(false)
                generation.incrementAndGet()
                synchronized(order) { order += "failure" }
            }
            transitionFinished.countDown()
        }.start()
        assertFalse(transitionFinished.await(BLOCKED_ASSERTION_MILLIS, TimeUnit.MILLISECONDS))

        releaseDelivery.countDown()
        assertTrue(transitionFinished.await(TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertEquals(listOf("control", "failure"), synchronized(order) { order.toList() })
    }

    @Test
    fun restartRejectsOldGenerationCallbacksOnBothChannels() {
        val linearizer = PeerSendLinearizer()
        val currentGeneration = AtomicLong(2)
        val decoded = AtomicInteger(0)
        val delivered = AtomicInteger(0)

        listOf("control", "media").forEach { channel ->
            val callbackGeneration = 1L
            val accepted =
                linearizer.receiveInbound(
                    snapshot = {
                        PeerInboundReceiveSnapshot(
                            PeerInboundCallbackSource(channel, callbackGeneration),
                            "cipher",
                            "target",
                            7,
                        )
                            .takeIf { callbackGeneration == currentGeneration.get() }
                    },
                    decode = {
                        decoded.incrementAndGet()
                        byteArrayOf(1)
                    },
                    isCurrent = { it.generation == currentGeneration.get() },
                    onDecodeFailure = { throw AssertionError(it) },
                    deliver = { _, _, _ -> delivered.incrementAndGet() },
                )

            assertFalse(accepted)
        }
        assertEquals(0, decoded.get())
        assertEquals(0, delivered.get())
    }

    @Test
    fun nativeQueuedCallbacksCannotAdoptCurrentGenerationWithSameChannelCipherAndEpoch() {
        val linearizer = PeerSendLinearizer()
        val channels = mapOf("control" to Any(), "media" to Any())
        val cipher = Any()
        val target = Any()
        val staleDecoded = AtomicInteger(0)
        val staleDelivered = AtomicInteger(0)
        val currentDelivered = AtomicInteger(0)

        repeat(NATIVE_QUEUE_STRESS_ITERATIONS) { iteration ->
            listOf("restart", "failure", "close").forEach { transition ->
                channels.forEach { (_, channel) ->
                    val registeredGeneration = iteration.toLong() * 10 + 1
                    val currentGeneration = registeredGeneration + 1
                    val staleSource = PeerInboundCallbackSource(channel, registeredGeneration)
                    val closed = transition == "close"

                    val staleAccepted =
                        linearizer.receiveInbound(
                            snapshot = {
                                PeerInboundReceiveSnapshot(staleSource, cipher, target, SESSION_EPOCH)
                                    .takeIf {
                                        !closed &&
                                            staleSource.generation == currentGeneration
                                    }
                            },
                            decode = {
                                staleDecoded.incrementAndGet()
                                byteArrayOf(1)
                            },
                            isCurrent = { !closed && it.generation == currentGeneration },
                            onDecodeFailure = { throw AssertionError(it) },
                            deliver = { _, _, _ -> staleDelivered.incrementAndGet() },
                        )
                    assertFalse(staleAccepted)

                    if (!closed) {
                        val currentSource = PeerInboundCallbackSource(channel, currentGeneration)
                        assertTrue(
                            linearizer.receiveInbound(
                                snapshot = {
                                    PeerInboundReceiveSnapshot(currentSource, cipher, target, SESSION_EPOCH)
                                },
                                decode = { byteArrayOf(2) },
                                isCurrent = { it.generation == currentGeneration },
                                onDecodeFailure = { throw AssertionError(it) },
                                deliver = { _, epoch, _ ->
                                    assertEquals(SESSION_EPOCH, epoch)
                                    currentDelivered.incrementAndGet()
                                },
                            ),
                        )
                    }
                }
            }
        }

        assertEquals(0, staleDecoded.get())
        assertEquals(0, staleDelivered.get())
        assertEquals(NATIVE_QUEUE_STRESS_ITERATIONS * channels.size * 2, currentDelivered.get())
    }

    @Test
    fun mediaRetryQueueStaysSinglePendingUnderSustainedBackpressure() {
        val scheduler = ManualRetryScheduler()
        val retryGate = PeerMediaRetryGate<String>(scheduler)
        val executions = AtomicInteger(0)

        repeat(MEDIA_RETRY_STRESS_ITERATIONS) { iteration ->
            assertTrue(retryGate.schedule("generation-$iteration") { executions.incrementAndGet() })
            repeat(MEDIA_RETRY_DUPLICATES_PER_ITERATION) {
                assertFalse(retryGate.schedule("duplicate-$iteration-$it") { executions.incrementAndGet() })
            }
            assertEquals(1, scheduler.activeCount)

            scheduler.runNext()
            assertEquals(iteration + 1, executions.get())
            assertEquals(0, scheduler.activeCount)
        }
    }

    @Test
    fun cancellingMediaRetryDropsStaleGenerationAndAllowsReplacement() {
        val scheduler = ManualRetryScheduler()
        val retryGate = PeerMediaRetryGate<String>(scheduler)
        val executions = mutableListOf<String>()

        assertTrue(retryGate.schedule("old-generation") { executions += it })
        retryGate.cancel()
        assertEquals(0, scheduler.activeCount)

        assertTrue(retryGate.schedule("current-generation") { executions += it })
        assertEquals(1, scheduler.activeCount)
        scheduler.runAll()

        assertEquals(listOf("current-generation"), executions)
        assertEquals(0, scheduler.activeCount)
    }

    @Test
    fun inboundUpperCallbackMayReenterTransitionWithoutDeadlock() {
        val linearizer = PeerSendLinearizer()
        val connected = AtomicBoolean(true)
        val generation = AtomicLong(1)

        val accepted =
            linearizer.receiveInbound(
                snapshot = {
                    PeerInboundReceiveSnapshot(
                        PeerInboundCallbackSource("control", generation.get()),
                        "cipher",
                        "target",
                        7,
                    )
                },
                decode = { byteArrayOf(1) },
                isCurrent = { connected.get() && it.generation == generation.get() },
                onDecodeFailure = { throw AssertionError(it) },
            ) { _, _, _ ->
                linearizer.withGate {
                    connected.set(false)
                    generation.incrementAndGet()
                }
            }

        assertTrue(accepted)
        assertFalse(connected.get())
        assertEquals(2, generation.get())
    }

    private companion object {
        const val TIMEOUT_SECONDS = 2L
        const val BLOCKED_ASSERTION_MILLIS = 100L
        const val SESSION_EPOCH = 7L
        const val NATIVE_QUEUE_STRESS_ITERATIONS = 128
        const val MEDIA_RETRY_STRESS_ITERATIONS = 128
        const val MEDIA_RETRY_DUPLICATES_PER_ITERATION = 256
    }

    private class ManualRetryScheduler : PeerRetryScheduler {
        private val lock = Any()
        private val tasks = ArrayDeque<ScheduledTask>()

        val activeCount: Int
            get() = synchronized(lock) { tasks.count { !it.cancelled } }

        override fun schedule(task: () -> Unit): PeerRetryCancellation {
            val scheduled = ScheduledTask(task)
            synchronized(lock) { tasks.addLast(scheduled) }
            return PeerRetryCancellation { synchronized(lock) { scheduled.cancelled = true } }
        }

        fun runNext() {
            val scheduled = synchronized(lock) { tasks.removeFirst() }
            if (!scheduled.cancelled) scheduled.task()
        }

        fun runAll() {
            while (synchronized(lock) { tasks.isNotEmpty() }) runNext()
        }

        private class ScheduledTask(
            val task: () -> Unit,
            var cancelled: Boolean = false,
        )
    }
}
