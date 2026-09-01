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
            val useFuture =
                executor.submit<Any?> {
                    gate.withCurrent { admittedDecoder ->
                        assertSame(decoder, admittedDecoder)
                        useStarted.countDown()
                        assertTrue(releaseUse.await(1, TimeUnit.SECONDS))
                        admittedDecoder
                    }
                }
            assertTrue(useStarted.await(1, TimeUnit.SECONDS))

            val clearFuture =
                executor.submit<Any?> {
                    clearStarted.countDown()
                    gate.clear().also { clearCompleted.set(true) }
                }

            assertTrue(clearStarted.await(1, TimeUnit.SECONDS))
            Thread.sleep(50)
            assertFalse(clearCompleted.get())
            releaseUse.countDown()

            assertSame(decoder, useFuture.get(1, TimeUnit.SECONDS))
            assertSame(decoder, clearFuture.get(1, TimeUnit.SECONDS))
            assertNull(gate.current())
        } finally {
            releaseUse.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(1, TimeUnit.SECONDS))
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
                        assertTrue(releaseCallback.await(5, TimeUnit.SECONDS))
                    }
                }
            assertTrue(callbackEntered.await(1, TimeUnit.SECONDS))

            val installFuture =
                executor.submit<Boolean> {
                    installThread = Thread.currentThread()
                    installEntered.countDown()
                    gate.installIf(replacement) { true }
                }
            assertTrue(installEntered.await(1, TimeUnit.SECONDS))
            waitUntilBlocked(requireNotNull(installThread))
            assertFalse(installFuture.isDone)

            releaseCallback.countDown()
            assertSame(decoder, clearFuture.get(1, TimeUnit.SECONDS))
            assertTrue(installFuture.get(1, TimeUnit.SECONDS))
            assertSame(replacement, gate.current())
        } finally {
            releaseCallback.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(1, TimeUnit.SECONDS))
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
                        assertTrue(releaseCallback.await(5, TimeUnit.SECONDS))
                    }
                }
            assertTrue(callbackEntered.await(1, TimeUnit.SECONDS))

            val installFuture =
                executor.submit<Boolean> {
                    installThread = Thread.currentThread()
                    installEntered.countDown()
                    gate.installIf(replacement) { true }
                }
            assertTrue(installEntered.await(1, TimeUnit.SECONDS))
            waitUntilBlocked(requireNotNull(installThread))
            assertFalse(installFuture.isDone)

            releaseCallback.countDown()
            assertTrue(compareFuture.get(1, TimeUnit.SECONDS))
            assertTrue(installFuture.get(1, TimeUnit.SECONDS))
            assertSame(replacement, gate.current())
        } finally {
            releaseCallback.countDown()
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(1, TimeUnit.SECONDS))
        }
    }

    private fun waitUntilBlocked(thread: Thread) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (System.nanoTime() < deadline) {
            if (thread.state == Thread.State.BLOCKED) return
            Thread.sleep(10)
        }
        throw AssertionError("Expected competing install to wait for the decoder gate")
    }
}
