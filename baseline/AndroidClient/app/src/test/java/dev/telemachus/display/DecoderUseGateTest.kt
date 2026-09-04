package dev.telemachus.display

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class DecoderUseGateTest {
    @Test
    fun clearWaitsForAdmittedUseBeforeDetachingDecoder() {
        val decoder = Any()
        val gate = DecoderUseGate<Any>()
        assertTrue(gate.installIf(decoder) { true })
        val useStarted = CountDownLatch(1)
        val releaseUse = CountDownLatch(1)
        val clearStarted = CountDownLatch(1)
        val clearCompleted = AtomicBoolean(false)
        val executor = Executors.newFixedThreadPool(2)
        try {
            var clearThread: Thread? = null
            val useFuture =
                executor.submit<Any?> {
                    gate.withCurrent { admittedDecoder ->
                        assertSame(decoder, admittedDecoder)
                        useStarted.countDown()
                        assertTrue(releaseUse.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                        admittedDecoder
                    }
                }
            assertTrue(useStarted.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))

            val clearFuture =
                executor.submit<Any?> {
                    clearThread = Thread.currentThread()
                    clearStarted.countDown()
                    gate.clear().also { clearCompleted.set(true) }
                }

            assertTrue(clearStarted.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = requireNotNull(clearThread),
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing clear",
            )
            assertFalse(clearCompleted.get())
            releaseUse.countDown()

            assertSame(decoder, useFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertSame(decoder, clearFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertNull(gate.current())
        } finally {
            releaseUse.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        }
    }

    @Test
    fun clearCallbackRunsWhileHoldingGateLockSoInstallCannotInterleave() {
        val decoder = Any()
        val replacement = Any()
        val gate = DecoderUseGate<Any>()
        val callbackEntered = CountDownLatch(1)
        val releaseCallback = CountDownLatch(1)
        val installEntered = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(2)

        assertTrue(gate.installIf(decoder) { true })
        try {
            var installThread: Thread? = null
            val clearFuture =
                executor.submit<Any?> {
                    gate.clear {
                        callbackEntered.countDown()
                        assertTrue(releaseCallback.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                    }
                }
            assertTrue(callbackEntered.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))

            val installFuture =
                executor.submit<Boolean> {
                    installThread = Thread.currentThread()
                    installEntered.countDown()
                    gate.installIf(replacement) { true }
                }
            assertTrue(installEntered.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = requireNotNull(installThread),
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing install",
            )
            assertFalse(installFuture.isDone)

            releaseCallback.countDown()
            assertSame(decoder, clearFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertTrue(installFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertSame(replacement, gate.current())
        } finally {
            releaseCallback.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        }
    }

    @Test
    fun clearedDecoderRejectsNewUsesAndCompareAndSetRequiresIdentityMatch() {
        val first = Any()
        val second = Any()
        val gate = DecoderUseGate<Any>()

        assertTrue(gate.installIf(first) { true })
        assertFalse(gate.compareAndSet(second, null))
        assertSame(first, gate.current())
        assertTrue(gate.compareAndSet(first, second))
        assertSame(second, gate.current())

        assertSame(second, gate.clear())
        assertNull(gate.withCurrent { it })
        assertFalse(gate.compareAndSet(second, first))
    }

    @Test
    fun conditionalInstallAndReplacePublishOnlyWhenAdmitted() {
        val first = Any()
        val second = Any()
        val third = Any()
        val gate = DecoderUseGate<Any>()

        assertFalse(gate.installIf(first) { false })
        assertNull(gate.current())
        assertTrue(gate.installIf(first) { true })
        assertSame(first, gate.current())

        assertFalse(gate.replaceIfCurrent(second, third) { true })
        assertSame(first, gate.current())
        assertFalse(gate.replaceIfCurrent(first, second) { false })
        assertSame(first, gate.current())
        assertTrue(gate.replaceIfCurrent(first, second) { true })
        assertSame(second, gate.current())
        assertTrue(gate.replaceIfCurrent(first, second) { true })
        assertSame(second, gate.current())
    }

    @Test
    fun withCurrentIfExecutesOnlyWhenAdmittedAndDecoderPresent() {
        val decoder = Any()
        val gate = DecoderUseGate<Any>()
        var actionCalled = false

        assertNull(gate.withCurrentIf(admit = { true }) { actionCalled = true; it })
        assertFalse(actionCalled)

        assertTrue(gate.installIf(decoder) { true })
        assertNull(gate.withCurrentIf(admit = { false }) { actionCalled = true; it })
        assertFalse(actionCalled)

        assertSame(decoder, gate.withCurrentIf(admit = { true }) { actionCalled = true; it })
        assertTrue(actionCalled)
    }

    @Test
    fun compareAndSetSuccessCallbackRunsWhileHoldingGateLockSoInstallCannotInterleave() {
        val decoder = Any()
        val replacement = Any()
        val gate = DecoderUseGate<Any>()
        val callbackEntered = CountDownLatch(1)
        val releaseCallback = CountDownLatch(1)
        val installEntered = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(2)

        assertTrue(gate.installIf(decoder) { true })
        try {
            var installThread: Thread? = null
            val compareFuture =
                executor.submit<Boolean> {
                    gate.compareAndSet(decoder, null) {
                        callbackEntered.countDown()
                        assertTrue(releaseCallback.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
                    }
                }
            assertTrue(callbackEntered.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))

            val installFuture =
                executor.submit<Boolean> {
                    installThread = Thread.currentThread()
                    installEntered.countDown()
                    gate.installIf(replacement) { true }
                }
            assertTrue(installEntered.await(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            waitUntilBlockedByDecoderGate(
                thread = requireNotNull(installThread),
                timeoutSeconds = WAIT_TIMEOUT_SECONDS,
                operation = "competing install",
            )
            assertFalse(installFuture.isDone)

            releaseCallback.countDown()
            assertTrue(compareFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertTrue(installFuture.get(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertSame(replacement, gate.current())
        } finally {
            releaseCallback.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(WAIT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        }
    }

    private companion object {
        const val WAIT_TIMEOUT_SECONDS = 5L
    }
}
