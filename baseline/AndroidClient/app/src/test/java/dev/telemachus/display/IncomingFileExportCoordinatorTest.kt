package dev.telemachus.display

import android.net.Uri
import java.io.IOException
import java.util.concurrent.Executor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class IncomingFileExportCoordinatorTest {
    @Test
    fun inlineExecutorReceivesTheReturnedSubscription() {
        val request = request("inline")
        val coordinator = IncomingFileExportCoordinator(Executor(Runnable::run)) { }
        var callbackSubscription: IncomingFileExportSubscription? = null

        val returned = coordinator.export(request) { subscription, result ->
            callbackSubscription = subscription
            result.export.getOrThrow()
        }

        assertTrue(callbackSubscription === returned)
    }

    @Test
    fun duplicateRequestSharesOneExport() {
        val executor = QueuedExecutor()
        val request = request("shared")
        var exports = 0
        val coordinator = IncomingFileExportCoordinator(executor) { exports += 1 }
        val first = mutableListOf<IncomingFileExportResult>()
        val second = mutableListOf<IncomingFileExportResult>()

        coordinator.export(request) { _, result -> first.add(result) }
        coordinator.export(request) { _, result -> second.add(result) }
        assertEquals(1, executor.pendingCount)

        executor.runNext()

        assertEquals(1, exports)
        first.single().export.getOrThrow()
        second.single().export.getOrThrow()
    }

    @Test
    fun closingActivityObserverDoesNotCancelCopyAndReplacementReceivesResult() {
        val executor = QueuedExecutor()
        val request = request("rotate")
        var exports = 0
        val coordinator = IncomingFileExportCoordinator(executor) { exports += 1 }
        val oldResults = mutableListOf<IncomingFileExportResult>()
        val newResults = mutableListOf<IncomingFileExportResult>()

        coordinator.export(request) { _, result -> oldResults.add(result) }.close()
        assertNotNull(coordinator.observeLatest { _, result -> newResults.add(result) })
        executor.runNext()

        assertTrue(oldResults.isEmpty())
        assertEquals(1, exports)
        newResults.single().export.getOrThrow()
    }

    @Test
    fun failureSurvivesObserverReplacementUntilConsumed() {
        val executor = QueuedExecutor()
        val expected = IOException("provider failed")
        val coordinator = IncomingFileExportCoordinator(executor) { throw expected }
        val subscription = coordinator.export(request("failure")) { _, _ -> }
        subscription.close()
        executor.runNext()
        val resumed = mutableListOf<IncomingFileExportResult>()

        assertNotNull(coordinator.observeLatest { _, result -> resumed.add(result) })
        assertEquals(expected, resumed.single().export.exceptionOrNull())
        assertTrue(subscription.consume())
        assertNull(coordinator.observeLatest { _, _ -> })
    }

    @Test
    fun staleSubscriptionCannotConsumeNewDestinationResult() {
        val executor = QueuedExecutor()
        val coordinator = IncomingFileExportCoordinator(executor) { }
        val oldSubscription = coordinator.export(request("old")) { _, _ -> }
        executor.runNext()
        val newResults = mutableListOf<IncomingFileExportResult>()
        coordinator.export(request("new")) { _, result -> newResults.add(result) }

        assertFalse(oldSubscription.consume())
        executor.runNext()
        newResults.single().export.getOrThrow()
    }

    private fun request(id: String) = IncomingFileExportRequest(
        source = Uri.parse("content://downloads/$id"),
        destination = Uri.parse("content://documents/$id"),
        displayName = "$id.bin",
        mimeType = "application/octet-stream",
    )

    private class QueuedExecutor : Executor {
        private val tasks = ArrayDeque<Runnable>()
        val pendingCount: Int get() = tasks.size

        override fun execute(command: Runnable) {
            tasks.addLast(command)
        }

        fun runNext() {
            tasks.removeFirst().run()
        }
    }
}
