package dev.telemachus.display

import com.google.protobuf.ByteString
import java.io.File
import java.util.concurrent.Executor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class IncomingFileDiscardCoordinatorTest {
    @Test
    fun inlineExecutorReceivesTheReturnedSubscription() {
        val recovery = recovery("inline")
        val coordinator = coordinator(Executor(Runnable::run), recovery) { }
        var callbackSubscription: IncomingFileDiscardSubscription? = null

        val returned = coordinator.discard(recovery) { subscription, result ->
            callbackSubscription = subscription
            result.discard.getOrThrow()
        }

        assertTrue(callbackSubscription === returned)
    }

    @Test
    fun concurrentSubscribersShareOneDiscard() {
        val executor = QueuedExecutor()
        val recovery = recovery("shared")
        var discards = 0
        val coordinator = coordinator(executor, recovery) { discards += 1 }
        val first = mutableListOf<IncomingFileDiscardResult>()
        val second = mutableListOf<IncomingFileDiscardResult>()

        coordinator.discard(recovery) { _, result -> first.add(result) }
        coordinator.discard(recovery) { _, result -> second.add(result) }
        assertEquals(1, executor.pendingCount)

        executor.runNext()

        assertEquals(1, discards)
        first.single().discard.getOrThrow()
        second.single().discard.getOrThrow()
    }

    @Test
    fun closingOldSubscriberDoesNotCancelWorkAndReplacementCanTakeOver() {
        val executor = QueuedExecutor()
        val recovery = recovery("rotate")
        var discards = 0
        val coordinator = coordinator(executor, recovery) { discards += 1 }
        val oldResults = mutableListOf<IncomingFileDiscardResult>()
        val newResults = mutableListOf<IncomingFileDiscardResult>()

        coordinator.discard(recovery) { _, result -> oldResults.add(result) }.close()
        assertNotNull(coordinator.observe(recovery) { _, result -> newResults.add(result) })
        executor.runNext()

        assertTrue(oldResults.isEmpty())
        assertEquals(1, discards)
        newResults.single().discard.getOrThrow()
    }

    @Test
    fun completedResultRemainsObservableUntilConsumed() {
        val executor = QueuedExecutor()
        val recovery = recovery("completed")
        val coordinator = coordinator(executor, recovery) { }
        val subscription = coordinator.discard(recovery) { _, _ -> }
        executor.runNext()
        val resumed = mutableListOf<IncomingFileDiscardResult>()

        assertNotNull(coordinator.observeLatest { _, result -> resumed.add(result) })
        resumed.single().discard.getOrThrow()
        assertTrue(subscription.consume())
        assertNull(coordinator.observeLatest { _, _ -> })
        assertFalse(subscription.consume())
    }

    @Test
    fun failureSurvivesObserverReplacementAndCanBeConsumedForRetry() {
        val executor = QueuedExecutor()
        val recovery = recovery("failure")
        val expected = IllegalStateException("discard failed")
        val coordinator = coordinator(executor, recovery) { throw expected }
        val subscription = coordinator.discard(recovery) { _, _ -> }
        subscription.close()
        executor.runNext()
        val resumed = mutableListOf<IncomingFileDiscardResult>()

        assertNotNull(coordinator.observe(recovery) { _, result -> resumed.add(result) })
        assertEquals(expected, resumed.single().discard.exceptionOrNull())
        assertTrue(subscription.consume())
    }

    @Test
    fun ownershipChangeFailsClosedWithoutDiscardingTheReplacement() {
        val executor = QueuedExecutor()
        val requested = recovery("requested")
        val replacement = recovery("replacement")
        var current = requested
        var discarded: RecoveredIncomingFile? = null
        val coordinator = IncomingFileDiscardCoordinator(executor, { current }) { discarded = it }
        val results = mutableListOf<IncomingFileDiscardResult>()

        coordinator.discard(requested) { _, result -> results.add(result) }
        current = replacement
        executor.runNext()

        assertNotNull(results.single().discard.exceptionOrNull())
        assertNull(discarded)
    }

    @Test
    fun staleSubscriptionCannotConsumeANewerOperation() {
        val executor = QueuedExecutor()
        var current = recovery("old")
        val coordinator = IncomingFileDiscardCoordinator(executor, { current }) { }
        val oldSubscription = coordinator.discard(current) { _, _ -> }
        executor.runNext()
        current = recovery("new")
        val newResults = mutableListOf<IncomingFileDiscardResult>()
        coordinator.discard(current) { _, result -> newResults.add(result) }

        assertFalse(oldSubscription.consume())
        executor.runNext()
        newResults.single().discard.getOrThrow()
    }

    private fun coordinator(
        executor: Executor,
        recovery: RecoveredIncomingFile,
        discard: (RecoveredIncomingFile) -> Unit,
    ) = IncomingFileDiscardCoordinator(executor, { recovery }, discard)

    private fun recovery(id: String): RecoveredIncomingFile =
        RecoveredIncomingFile(
            recoveryId = id,
            transferId = ByteString.copyFromUtf8("transfer-$id"),
            displayName = "$id.txt",
            mimeType = "text/plain",
            byteLength = 1L,
            sha256 = ByteString.copyFrom(ByteArray(32) { it.toByte() }),
            payloadFile = File("/tmp/$id.txt"),
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
