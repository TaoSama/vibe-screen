package dev.telemachus.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.Executor

class OnceAsyncDispatcherTest {
    @Test
    fun `dispatch returns before cleanup and cleanup never runs on caller`() {
        val recordingExecutor = RecordingExecutor()
        val callerThread = Thread.currentThread()
        var claimed = 0
        var cleanup = 0
        var cleanupThread: Thread? = null
        val dispatcher =
            OnceAsyncDispatcher<String>(
                executor = recordingExecutor,
                onClaim = { claimed++ },
                complete = {
                    Thread.sleep(200)
                    cleanup++
                    cleanupThread = Thread.currentThread()
                },
            )

        val startedAt = System.nanoTime()
        assertTrue(dispatcher.dispatch("outbound_backpressure"))
        val elapsedMs = (System.nanoTime() - startedAt) / 1_000_000.0

        assertTrue("dispatch took ${elapsedMs}ms", elapsedMs < 50.0)
        assertEquals(1, claimed)
        assertEquals(0, cleanup)
        assertEquals(1, recordingExecutor.size)
        assertFalse(dispatcher.dispatch("duplicate"))
        assertEquals(1, recordingExecutor.size)

        val worker = Thread(recordingExecutor.remove(), "termination-test-worker")
        worker.start()
        worker.join(1_000)
        assertFalse(worker.isAlive)
        assertEquals(1, cleanup)
        assertNotEquals(callerThread, cleanupThread)
    }

    @Test
    fun `first terminal path wins for both synchronous and queued completion order`() {
        listOf(true, false).forEach { synchronousFirst ->
            val recordingExecutor = RecordingExecutor()
            val completed = mutableListOf<String>()
            val dispatcher =
                OnceAsyncDispatcher<String>(
                    executor = recordingExecutor,
                    onClaim = {},
                    complete = { completed += it },
                )

            if (synchronousFirst) {
                assertTrue(dispatcher.completeNow("receive_finally"))
                assertFalse(dispatcher.dispatch("explicit_disconnect"))
                assertEquals(listOf("receive_finally"), completed)
                assertEquals(0, recordingExecutor.size)
            } else {
                assertTrue(dispatcher.dispatch("explicit_disconnect"))
                assertFalse(dispatcher.completeNow("receive_finally"))
                assertTrue(completed.isEmpty())
                recordingExecutor.remove().run()
                assertEquals(listOf("explicit_disconnect"), completed)
            }
        }
    }

    private class RecordingExecutor : Executor {
        private val tasks = ArrayDeque<Runnable>()

        val size: Int
            get() = tasks.size

        override fun execute(command: Runnable) {
            tasks.addLast(command)
        }

        fun remove(): Runnable = tasks.removeFirst()
    }
}
